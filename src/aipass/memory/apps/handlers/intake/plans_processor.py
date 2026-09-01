# =================== AIPass ====================
# Name: plans_processor.py
# Description: Plan Archival Vectorization Handler
# Version: 1.0.0
# Created: 2026-03-12
# Modified: 2026-03-12
# =============================================

"""
Plan Archival Vectorization Handler

Reads closed plan files from flow/processed_plans/, chunks them,
generates embeddings via subprocess, and stores vectors in ChromaDB.

Called by memory_watcher._check_plans() during watch mode
and can be invoked directly for manual processing.

Uses subprocess pattern for ML operations (memory venv isolation).
"""

import hashlib
import json
import re
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

from aipass.memory.apps.handlers import repo_root
from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader
from aipass.memory.apps.handlers.repo_root import module_file

# Subprocess scripts
_HANDLERS_DIR = module_file(__file__).parent.parent
EMBED_SUBPROCESS_SCRIPT = _HANDLERS_DIR / "vector" / "embed_subprocess.py"
CHROMA_SUBPROCESS_SCRIPT = _HANDLERS_DIR / "storage" / "chroma_subprocess.py"

# Memory venv python
_MEMORY_ROOT = module_file(__file__).parents[3]
_MEMORY_VENV_PYTHON = _MEMORY_ROOT / ".venv" / "bin" / "python"


def _find_repo_root() -> Path:
    """Repo root for this lane — resolved by ``handlers/repo_root.py``.

    Kept as a local name because callers and tests patch it here. The body is a
    delegation on purpose: this function used to be one of ten byte-identical
    copies, so the first cure landed on one file and CI went red on the next.

    Returns:
        The directory holding AIPASS_REGISTRY.json, or the source tree. Never
        the process working directory.
    """
    return repo_root.find_repo_root(caller="plans_processor")


def _get_memory_python() -> str:
    env_override = os.environ.get("AIPASS_MEMORY_PYTHON")
    if env_override:
        return env_override
    if _MEMORY_VENV_PYTHON.exists():
        return str(_MEMORY_VENV_PYTHON)
    return sys.executable


MEMORY_PYTHON = _get_memory_python()

# Track which files have been processed
_PROCESSED_MANIFEST = _MEMORY_ROOT / "memory_json" / ".plans_processed.json"

# Chunk settings
MAX_CHUNK_CHARS = 1500  # ~375 tokens, fits well with all-MiniLM-L6-v2


# =============================================================================
# CHUNKING
# =============================================================================


# A line that is nothing but a bracketed prompt: "[What do you want to achieve?]"
# or "<describe the approach>". Anchored at both ends, so a markdown link like
# "[the audit](./audit.md)" -- which opens with a bracket and is real content --
# does not match.
_PLACEHOLDER_LINE = re.compile(r"^\s*[\[<][^\n]*[\]>]\s*$")

# A markdown horizontal rule. Structure, not content: the two most-repeated
# unfilled sections in the live collection both end in one, and treating it as
# content would have made this filter reach 2% instead of 5.4%.
_HORIZONTAL_RULE = re.compile(r"^\s*([-*_])\1{2,}\s*$")


def _is_placeholder_only(chunk_text: str) -> bool:
    """True when a section's body is ONLY the template prompt nobody filled in.

    Vectorizing an unfilled section stores a question the TEMPLATE asked,
    attributed to a plan that never answered it — 452 of 8,433 vectors in
    flow_plans (5.4%), measured 2026-08-30 on @flow's proposal.

    Deliberately narrow. @flow's plan-level version of this idea
    (``is_template_content``) was retired after it false-positived on
    real-but-minimal FPLANs and destroyed the file, the registry row and the
    archive together. Here the unit is a chunk, so the worst case is a dropped
    empty section rather than a lost plan — and the rule fires only when EVERY
    content line is bracketed. One line of real prose keeps the whole section.

    A body with no content lines at all is NOT a placeholder: that is absence,
    which the length gate already handles, and saying otherwise would make this
    function's own name wrong about what it found.
    """
    lines = chunk_text.split("\n")
    body = lines[1:] if lines and lines[0].lstrip().startswith("#") else lines
    content = [line for line in body if line.strip() and not _HORIZONTAL_RULE.match(line)]
    return bool(content) and all(_PLACEHOLDER_LINE.match(line) for line in content)


def _chunk_plan_text(text: str, filename: str) -> List[Dict[str, str]]:
    """
    Chunk plan text into sections for vectorization.

    Splits on markdown headers (## / ###), with fallback to paragraph splitting.
    Each chunk gets metadata about its source.

    Args:
        text: Full plan text
        filename: Source filename for metadata

    Returns:
        List of dicts with 'text' and 'section' keys
    """
    chunks = []

    # Split by markdown headers
    lines = text.split("\n")
    current_section = filename
    current_lines = []

    for line in lines:
        if line.startswith("## ") or line.startswith("### "):
            # Flush previous section
            if current_lines:
                section_text = "\n".join(current_lines).strip()
                if section_text and len(section_text) > 30:
                    chunks.append({"text": section_text, "section": current_section})
            current_section = line.lstrip("#").strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    # Flush last section
    if current_lines:
        section_text = "\n".join(current_lines).strip()
        if section_text and len(section_text) > 30:
            chunks.append({"text": section_text, "section": current_section})

    # If no headers found, chunk by size
    if not chunks:
        full_text = text.strip()
        if len(full_text) > MAX_CHUNK_CHARS:
            for i in range(0, len(full_text), MAX_CHUNK_CHARS):
                chunk_text = full_text[i : i + MAX_CHUNK_CHARS].strip()
                if chunk_text and len(chunk_text) > 30:
                    chunks.append({"text": chunk_text, "section": f"{filename}_part{i // MAX_CHUNK_CHARS}"})
        elif len(full_text) > 30:
            chunks.append({"text": full_text, "section": filename})

    # Split oversized chunks
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

    # Filtered HERE, at the one exit, rather than at each of the four places a
    # chunk is appended above -- a rule applied at three of four sites is the
    # failure this branch spent the day fixing elsewhere.
    kept = [c for c in final_chunks if not _is_placeholder_only(c["text"])]
    dropped = len(final_chunks) - len(kept)
    if dropped:
        logger.info(f"[plans] {filename}: skipped {dropped} unfilled template section(s)")
    return kept


# =============================================================================
# PROCESSED MANIFEST
# =============================================================================


def _load_manifest() -> Dict[str, Any]:
    """Load processed files manifest.

    Values are either the content-keyed row this module writes now, or the bare
    ISO string written before 2026-08-30 -- see :func:`_recorded`.
    """
    if _PROCESSED_MANIFEST.exists():
        try:
            return json.loads(_PROCESSED_MANIFEST.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[plans_processor] Failed to load processed manifest: {e}")
            return {}
    return {}


def _save_manifest(manifest: Dict[str, Any]) -> None:
    """Save processed files manifest."""
    _PROCESSED_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    _PROCESSED_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _content_hash(text: str) -> str:
    """The plan's content, as one comparable value."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _manifest_entry(text: str) -> Dict[str, str]:
    """A row that records WHAT was processed, not merely that something was."""
    return {"processed_at": datetime.now().isoformat(), "content_sha256": _content_hash(text)}


def _recorded(entry: Any) -> tuple[str | None, str | None]:
    """``(processed_at, content_sha256)`` from either manifest shape.

    Rows written before 2026-08-30 are a bare ISO string — processed, content
    unrecorded. Both shapes are read here so the file needs no migration pass
    and no version field; a legacy row upgrades itself the next time it is seen.
    """
    if isinstance(entry, dict):
        stamp = entry.get("processed_at")
        digest = entry.get("content_sha256")
        return (stamp if isinstance(stamp, str) else None, digest if isinstance(digest, str) else None)
    if isinstance(entry, str):
        return entry, None
    return None, None


def _is_stale(plan_file: Path, entry: Any, text: str) -> bool:
    """Does this file need processing, given what the manifest remembers?

    Keyed on CONTENT, not on the name alone. @flow found the failure the name
    key caused: `restore` puts a plan file back but nothing removes its manifest
    row, so when that plan is genuinely closed later its final content is never
    vectorized and the store keeps only its pre-restore text. Three live cases.
    Content keying is self-healing and needs nothing from the restoring lane —
    it also covers a plan simply edited after close, which a restore callback
    would still have missed.
    """
    stamp, digest = _recorded(entry)
    if digest is not None:
        return digest != _content_hash(text)

    # Legacy row: no hash, so "unchanged" is a belief rather than a fact. The
    # file's own mtime is the only evidence available, and it answers the case
    # that matters -- a restore WRITES the file, long after the row was recorded.
    # Measured 2026-08-30 before choosing this: 491 rows, 488 files present, ZERO
    # of them modified after processing. So the backfill below cannot silently
    # skip a change that already happened; this guard covers one arriving later.
    if stamp:
        try:
            if datetime.fromtimestamp(plan_file.stat().st_mtime) > datetime.fromisoformat(stamp):
                logger.info(f"[plans] {plan_file.name} is newer than its manifest row — re-processing")
                return True
        except (ValueError, OSError) as exc:
            logger.warning(f"[plans] Cannot compare {plan_file.name} to its manifest row ({exc}) — re-processing")
            return True
    return False


# =============================================================================
# SUBPROCESS WRAPPERS
# =============================================================================


def _embed_texts(texts: List[str], timeout: int = 120) -> dict:
    """Encode texts via subprocess."""
    input_data = json.dumps({"texts": texts})
    try:
        result = subprocess.run(
            [str(MEMORY_PYTHON), str(EMBED_SUBPROCESS_SCRIPT)],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return {"success": False, "error": result.stderr or "Embedding failed"}
        return json.loads(result.stdout)
    except Exception as e:
        logger.warning(f"[plans_processor] Embedding subprocess failed: {e}")
        return {"success": False, "error": str(e)}


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
    try:
        result = subprocess.run(
            [str(MEMORY_PYTHON), str(CHROMA_SUBPROCESS_SCRIPT)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return {"success": False, "error": result.stderr or "Storage failed"}
        return json.loads(result.stdout)
    except Exception as e:
        logger.warning(f"[plans_processor] Vector storage subprocess failed: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# PUBLIC API
# =============================================================================


def process_plans() -> Dict[str, Any]:
    """
    Process plan files from flow/processed_plans/ into vector storage.

    Processes each file independently so partial failure makes partial
    progress — manifest is saved after every successful file.

    Returns:
        Dict with success, files_processed, total_chunks
    """
    plans_config = config_loader.section("plans")

    if not plans_config.get("enabled", False):
        return {"success": True, "skipped": True, "reason": "plans disabled"}

    plans_dir = plans_config.get("path", ".backup/processed_plans")
    repo_root = _find_repo_root()
    plans_path = Path(plans_dir) if Path(plans_dir).is_absolute() else repo_root / plans_dir
    extensions = plans_config.get("supported_extensions", [".md"])
    collection_name = plans_config.get("collection_name", "plans")

    if not plans_path.exists():
        return {"success": True, "files_processed": 0, "total_chunks": 0, "reason": "plans dir not found"}

    files = []
    for ext in extensions:
        files.extend(plans_path.glob(f"*{ext}"))

    if not files:
        return {"success": True, "files_processed": 0, "total_chunks": 0}

    manifest = _load_manifest()

    # Read each file ONCE here: the same text decides staleness and, for a file
    # that turns out to be current, backfills the hash its legacy row never had.
    unprocessed = []
    backfilled = 0
    for plan_file in files:
        if plan_file.name not in manifest:
            unprocessed.append(plan_file)
            continue
        try:
            text = plan_file.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning(f"[plans] Cannot read {plan_file.name} to check freshness ({exc}) — re-processing")
            unprocessed.append(plan_file)
            continue
        if _is_stale(plan_file, manifest[plan_file.name], text):
            unprocessed.append(plan_file)
        elif _recorded(manifest[plan_file.name])[1] is None:
            # Current content, legacy row. Record what it was always missing
            # rather than paying to embed 488 plans nothing suggests are stale.
            manifest[plan_file.name] = {
                "processed_at": _recorded(manifest[plan_file.name])[0] or datetime.now().isoformat(),
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

    for plan_file in unprocessed:
        try:
            text = plan_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"[plans] Failed to read {plan_file.name}: {e}")
            errors.append(f"{plan_file.name}: read error: {e}")
            continue

        chunks = _chunk_plan_text(text, plan_file.name)
        if not chunks:
            manifest[plan_file.name] = _manifest_entry(text)
            _save_manifest(manifest)
            continue

        texts = [c["text"] for c in chunks]
        metadatas = [
            {
                "source_file": plan_file.name,
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

        manifest[plan_file.name] = _manifest_entry(text)
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
