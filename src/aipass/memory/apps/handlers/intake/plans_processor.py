# =================== AIPass ====================
# Name: plans_processor.py
# Description: Plan Archival Vectorization Handler
# Version: 1.3.0
# Created: 2026-03-12
# Modified: 2026-10-26
# =============================================

"""
Plan Archival Vectorization Handler

ML runs in a subprocess on the memory venv's python (venv isolation).
"""

import hashlib
import json
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

from aipass.memory.apps.handlers import repo_root
from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader
from aipass.memory.apps.handlers.monitor import registry_scope
from aipass.memory.apps.handlers.repo_root import module_file
from aipass.memory.apps.handlers.storage.lane import CHROMA_SUBPROCESS_SCRIPT, EMBED_SUBPROCESS_SCRIPT, run_json


def _find_repo_root() -> Path:
    """Repo root for this lane — resolved by ``handlers/repo_root.py``.

    Kept as a local name because callers and tests patch it here.
    """
    return repo_root.find_repo_root(caller="plans_processor")


_MEMORY_ROOT = module_file(__file__).parents[3]
_PROCESSED_MANIFEST = _MEMORY_ROOT / "memory_json" / ".plans_processed.json"

MAX_CHUNK_CHARS = 1500  # ~375 tokens, fits well with all-MiniLM-L6-v2


# Anchored at both ends so a markdown link line "[the audit](./audit.md)" does not match.
_PLACEHOLDER_LINE = re.compile(r"^\s*[\[<][^\n]*[\]>]\s*$")

# Structure, not content: unfilled sections often end in one.
_HORIZONTAL_RULE = re.compile(r"^\s*([-*_])\1{2,}\s*$")


def _is_placeholder_only(chunk_text: str) -> bool:
    """True when a section's body is ONLY the template prompt nobody filled in.

    Deliberately narrow: fires only when EVERY content line is bracketed. An empty
    body is absence, not a placeholder; the length gate handles it.
    """
    lines = chunk_text.split("\n")
    body = lines[1:] if lines and lines[0].lstrip().startswith("#") else lines
    content = [line for line in body if line.strip() and not _HORIZONTAL_RULE.match(line)]
    return bool(content) and all(_PLACEHOLDER_LINE.match(line) for line in content)


def _chunk_plan_text(text: str, filename: str) -> List[Dict[str, str]]:
    """Chunk plan text into sections on ## / ### headers, falling back to size."""
    chunks = []

    lines = text.split("\n")
    current_section = filename
    current_lines = []

    for line in lines:
        if line.startswith("## ") or line.startswith("### "):
            if current_lines:
                section_text = "\n".join(current_lines).strip()
                if section_text and len(section_text) > 30:
                    chunks.append({"text": section_text, "section": current_section})
            current_section = line.lstrip("#").strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        section_text = "\n".join(current_lines).strip()
        if section_text and len(section_text) > 30:
            chunks.append({"text": section_text, "section": current_section})

    if not chunks:
        full_text = text.strip()
        if len(full_text) > MAX_CHUNK_CHARS:
            for i in range(0, len(full_text), MAX_CHUNK_CHARS):
                chunk_text = full_text[i : i + MAX_CHUNK_CHARS].strip()
                if chunk_text and len(chunk_text) > 30:
                    chunks.append({"text": chunk_text, "section": f"{filename}_part{i // MAX_CHUNK_CHARS}"})
        elif len(full_text) > 30:
            chunks.append({"text": full_text, "section": filename})

    final_chunks = []
    for chunk in chunks:
        if len(chunk["text"]) > MAX_CHUNK_CHARS * 2:
            text_content = chunk["text"]
            for i in range(0, len(text_content), MAX_CHUNK_CHARS):
                part = text_content[i : i + MAX_CHUNK_CHARS].strip()
                if part and len(part) > 30:
                    final_chunks.append({"text": part, "section": f"{chunk['section']}_part{i // MAX_CHUNK_CHARS}"})
        else:
            final_chunks.append(chunk)

    # Filtered at the one exit, not at each of the four append sites above.
    kept = [c for c in final_chunks if not _is_placeholder_only(c["text"])]
    dropped = len(final_chunks) - len(kept)
    if dropped:
        logger.info(f"[plans] {filename}: skipped {dropped} unfilled template section(s)")
    return kept


class ManifestUnreadable(ValueError):
    """The processed-plans manifest exists and cannot be read."""


def _load_manifest() -> Dict[str, Any]:
    """Load processed files manifest.

    Raises ManifestUnreadable rather than load {}: that re-embeds every plan and overwrites the file.
    """
    if _PROCESSED_MANIFEST.exists():
        try:
            data = json.loads(_PROCESSED_MANIFEST.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            raise ManifestUnreadable(f"Unreadable processed manifest {_PROCESSED_MANIFEST}: {e}") from e
        if not isinstance(data, dict):
            raise ManifestUnreadable(f"Unreadable processed manifest {_PROCESSED_MANIFEST}: root is not an object")
        return data
    return {}


def _save_manifest(manifest: Dict[str, Any]) -> None:
    """Save processed files manifest."""
    _PROCESSED_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PROCESSED_MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp, _PROCESSED_MANIFEST)


def _content_hash(text: str) -> str:
    """The plan's content, as one comparable value."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _manifest_entry(text: str) -> Dict[str, str]:
    """A row that records WHAT was processed, not merely that something was."""
    return {"processed_at": datetime.now().isoformat(), "content_sha256": _content_hash(text)}


def _recorded(entry: Any) -> tuple[str | None, str | None]:
    """``(processed_at, content_sha256)`` from either manifest shape; a legacy row is a bare ISO string."""
    if isinstance(entry, dict):
        stamp = entry.get("processed_at")
        digest = entry.get("content_sha256")
        return (stamp if isinstance(stamp, str) else None, digest if isinstance(digest, str) else None)
    if isinstance(entry, str):
        return entry, None
    return None, None


def _is_stale(plan_file: Path, entry: Any, text: str) -> bool:
    """Does this file need processing, given what the manifest remembers?

    Keyed on CONTENT: a restored plan keeps its manifest row, so a name key misses its final close.
    """
    stamp, digest = _recorded(entry)
    if digest is not None:
        return digest != _content_hash(text)

    # Legacy row, no hash: mtime is the only evidence, and a restore writes the file.
    if stamp:
        try:
            if datetime.fromtimestamp(plan_file.stat().st_mtime) > datetime.fromisoformat(stamp):
                logger.info(f"[plans] {plan_file.name} is newer than its manifest row — re-processing")
                return True
        except (ValueError, OSError) as exc:
            logger.warning(f"[plans] Cannot compare {plan_file.name} to its manifest row ({exc}) — re-processing")
            return True
    return False


def _archives(plans_dir: str, root: Path) -> List[tuple[str, Path]]:
    """``(project, archive dir)`` for the host, each resident project and each declared root; absent dirs skipped.

    An absolute ``plans.path`` names one archive, the host's.
    """
    if Path(plans_dir).is_absolute():
        return [(root.name, Path(plans_dir))]
    projects = [root] + [reg.parent for reg in registry_scope.resident_registry_paths(root)]
    projects += registry_scope.declared_roots(root)
    return [(project.name, project / plans_dir) for project in projects if (project / plans_dir).is_dir()]


def _manifest_key(project: str, plan_file: Path, host: str) -> str:
    """Host rows keep their bare filename so the existing manifest stays valid; other projects are prefixed."""
    return plan_file.name if project == host else f"{project}/{plan_file.name}"


def _embed_texts(texts: List[str], timeout: int = 120) -> dict:
    """Encode texts via subprocess."""
    return run_json(EMBED_SUBPROCESS_SCRIPT, {"texts": texts}, timeout=timeout, label="Embedding")


def _store_vectors(embeddings, documents, metadatas, collection_name="flow_plans") -> dict:
    """Store vectors via subprocess."""
    input_data = {
        "operation": "store_vectors",
        "branch": "FLOW",
        "memory_type": collection_name,
        "embeddings": embeddings,
        "documents": documents,
        "metadatas": metadatas,
        "db_path": None,  # global
    }
    return run_json(CHROMA_SUBPROCESS_SCRIPT, input_data, timeout=60, label="Storage")


def process_plans() -> Dict[str, Any]:
    """
    Process every visible project's archived plans into vector storage, each chunk tagged with its project.

    The manifest is saved after every successful file, so partial failure makes partial progress.
    """
    plans_config = config_loader.section("plans")

    if not plans_config.get("enabled", False):
        return {"success": True, "skipped": True, "reason": "plans disabled"}

    plans_dir = plans_config.get("path", ".backup/processed_plans")
    repo_root = _find_repo_root()
    extensions = plans_config.get("supported_extensions", [".md"])
    collection_name = plans_config.get("collection_name", "plans")

    archives = _archives(plans_dir, repo_root)
    if not archives:
        return {"success": True, "files_processed": 0, "total_chunks": 0, "reason": "plans dir not found"}

    host = repo_root.name
    files = [
        (project, plan_file, _manifest_key(project, plan_file, host))
        for project, plans_path in archives
        for ext in extensions
        for plan_file in plans_path.glob(f"*{ext}")
    ]

    if not files:
        return {"success": True, "files_processed": 0, "total_chunks": 0}

    try:
        manifest = _load_manifest()
    except ManifestUnreadable as e:
        logger.error(f"[plans_processor] {e} — no plan processed, the manifest is left as it is")
        return {"success": False, "error": str(e)}

    unprocessed = []
    backfilled = 0
    for project, plan_file, key in files:
        if key not in manifest:
            unprocessed.append((project, plan_file, key))
            continue
        try:
            text = plan_file.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(f"[plans] Cannot read {plan_file.name} to check freshness ({exc}) — re-processing")
            unprocessed.append((project, plan_file, key))
            continue
        if _is_stale(plan_file, manifest[key], text):
            unprocessed.append((project, plan_file, key))
        elif _recorded(manifest[key])[1] is None:
            # Current content, legacy row: backfill the hash rather than re-embed.
            manifest[key] = {
                "processed_at": _recorded(manifest[key])[0] or datetime.now().isoformat(),
                "content_sha256": _content_hash(text),
            }
            backfilled += 1
    if backfilled:
        _save_manifest(manifest)
        logger.info(f"[plans] Recorded a content hash for {backfilled} legacy manifest row(s)")

    if not unprocessed:
        return {"success": True, "files_processed": 0, "total_chunks": 0, "reason": "all files already processed"}

    logger.info(f"[plans] Found {len(unprocessed)} unprocessed plan files")

    errors: List[str] = []
    files_processed = 0
    total_chunks = 0

    for project, plan_file, key in unprocessed:
        try:
            text = plan_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"[plans] Failed to read {plan_file.name}: {e}")
            errors.append(f"{plan_file.name}: read error: {e}")
            continue

        chunks = _chunk_plan_text(text, plan_file.name)
        if not chunks:
            manifest[key] = _manifest_entry(text)
            _save_manifest(manifest)
            continue

        texts = [c["text"] for c in chunks]
        metadatas = [
            {
                "source_file": plan_file.name,
                "project": project,
                "section": c["section"],
                "processed_at": datetime.now().isoformat(),
                "type": "plan",
            }
            for c in chunks
        ]

        timeout = max(30, len(texts) * 3)
        embed_result = _embed_texts(texts, timeout=timeout)
        if not embed_result.get("success"):
            logger.warning(f"[plans] Embed failed for {plan_file.name}: {embed_result.get('error')}")
            errors.append(f"{plan_file.name}: embed error: {embed_result.get('error')}")
            continue

        embeddings = embed_result.get("embeddings", [])
        if not embeddings:
            errors.append(f"{plan_file.name}: embed returned no embeddings")
            continue

        store_result = _store_vectors(embeddings, texts, metadatas, collection_name)
        if not store_result.get("success"):
            logger.warning(f"[plans] Store failed for {plan_file.name}: {store_result.get('error')}")
            errors.append(f"{plan_file.name}: store error: {store_result.get('error')}")
            continue

        manifest[key] = _manifest_entry(text)
        _save_manifest(manifest)
        files_processed += 1
        total_chunks += len(texts)
        logger.info(f"[plans] {plan_file.name}: {len(texts)} chunks vectorized")

    if files_processed > 0:
        logger.info(f"[plans] Complete: {files_processed} files, {total_chunks} chunks vectorized")

    result: Dict[str, Any] = {
        "success": files_processed > 0 or not errors,
        "files_processed": files_processed,
        "total_chunks": total_chunks,
    }
    if errors:
        result["errors"] = errors

    json_handler.log_operation(
        "process_plans",
        {"files_processed": files_processed, "total_chunks": total_chunks, "success": result["success"]},
    )

    return result
