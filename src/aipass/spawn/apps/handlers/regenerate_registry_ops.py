# =================== AIPass ====================
# Name: regenerate_registry_ops.py
# Description: Regenerate .template_registry.json for spawn template directories
# Version: 1.0.4
# Created: 2026-03-25
# Modified: 2026-10-24
# =============================================

"""Regenerate template registry — walk template directory, hash files, build registry."""

import json
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.file_ops import SKIP_NAMES
from aipass.spawn.apps.handlers.meta_ops import compute_file_hash, load_template_registry

_SPAWN_DIR = ".spawn"
_TEMPLATE_REGISTRY_FILE = ".template_registry.json"

_SKIP_SPAWN_FILES = {".template_registry.json", ".branch_meta.json"}

_BRANCH_PLACEHOLDERS = ("{{BRANCH}}", "{{BRANCHNAME}}")


def _registry_date() -> str:
    """Today's date as the registry stamps it (YYYY-MM-DD) — the clock seam.

    Tests patch this rather than the stdlib datetime process-wide.
    """
    return datetime.now().strftime("%Y-%m-%d")


def _existing_newline(registry_path: Path) -> str:
    """The line ending the manifest on disk already uses: CRLF if it has one, else LF (also when absent)."""
    try:
        return "\r\n" if b"\r\n" in registry_path.read_bytes() else "\n"
    except FileNotFoundError:
        return "\n"


def regenerate_template_registry(template_dir: Path) -> dict:
    """Walk a template directory, hash files, and build a fresh registry.

    The stats key is not written to JSON. On a refusal, returns only {"error": ...}: the directory is
    missing, the existing manifest is unreadable (nothing written), or the write failed.
    """
    template_dir = Path(template_dir)

    if not template_dir.is_dir():
        logger.error(f"Template directory does not exist: {template_dir}")
        return {"error": f"Template directory does not exist: {template_dir}"}

    # A manifest that exists but cannot be read is refused, not read as absent: fresh ids written
    # over it are a wrong identity.
    registry_path = template_dir / _SPAWN_DIR / _TEMPLATE_REGISTRY_FILE
    existing_registry = load_template_registry(template_dir)
    if existing_registry is None and registry_path.exists():
        msg = f"Template registry {registry_path} is there but cannot be read; fix or remove it (nothing regenerated)"
        logger.error(f"[regenerate-registry] {msg}")
        return {"error": msg}

    files, directories = _scan_template_directory(template_dir, existing_registry)

    # last_updated tracks the TEMPLATE, not the calendar: a no-change run keeps the date, so it is a
    # byte-identical no-op and a real rewrite never hides in daily churn.
    existing_metadata = (existing_registry or {}).get("metadata", {})
    unchanged = (
        bool(existing_registry)
        and files == (existing_registry.get("files") or {})
        and directories == (existing_registry.get("directories") or {})
    )
    if unchanged and existing_metadata.get("last_updated"):
        last_updated = existing_metadata["last_updated"]
    else:
        last_updated = _registry_date()

    registry = {
        "metadata": {
            "version": "1.0.0",
            "last_updated": last_updated,
            "description": "Template file tracking registry for ID-based updates",
        },
        "files": files,
        "directories": directories,
    }

    spawn_dir = template_dir / _SPAWN_DIR
    spawn_dir.mkdir(parents=True, exist_ok=True)

    try:
        # The manifest keeps its line endings: a CRLF checkout rewritten as LF changes every line on a no-op.
        # json.dumps escapes newlines inside strings, so every "\n" is a line end.
        text = json.dumps(registry, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        atomic_write_text(registry_path, text.replace("\n", _existing_newline(registry_path)))
    except (IOError, OSError) as exc:
        logger.error(f"Failed to write template registry: {exc}")
        return {"error": f"Failed to write registry: {exc}"}

    existing_file_count = len(existing_registry.get("files", {})) if existing_registry else 0
    existing_dir_count = len(existing_registry.get("directories", {})) if existing_registry else 0

    stats = {
        "files_tracked": len(files),
        "directories_tracked": len(directories),
        "previous_files": existing_file_count,
        "previous_directories": existing_dir_count,
        "registry_path": str(registry_path),
        "template_dir": str(template_dir),
        "template_name": template_dir.name,
    }

    logger.info(
        f"Regenerated template registry for {template_dir.name}: {len(files)} files, {len(directories)} directories"
    )

    return {**registry, "stats": stats}


def _scan_template_directory(
    template_dir: Path,
    existing_registry: dict | None,
) -> tuple[dict, dict]:
    """Walk template directory and build files and directories dicts.

    Files keep an ID by path, then content hash, else get a new one; directories by path, then name.
    """
    existing_files = existing_registry.get("files", {}) if existing_registry else {}
    existing_dirs = existing_registry.get("directories", {}) if existing_registry else {}

    # Index the 12-char prefix too: old registries stored 16-char hashes.
    hash_to_id: dict[str, str] = {}
    path_to_file_id: dict[str, str] = {}
    for fid, finfo in existing_files.items():
        path_to_file_id[finfo.get("path", "")] = fid
        content_hash = finfo.get("content_hash", "")
        if content_hash and content_hash != "placeholder":
            hash_to_id[content_hash] = fid
            if len(content_hash) > 12:
                hash_to_id[content_hash[:12]] = fid

    path_to_dir_id: dict[str, str] = {}
    name_to_dir_id: dict[str, str] = {}
    for did, dinfo in existing_dirs.items():
        path_to_dir_id[dinfo.get("path", "")] = did
        name_to_dir_id[dinfo.get("name", "")] = did

    claimed_file_ids: set[str] = set()
    claimed_dir_ids: set[str] = set()

    raw_files: list[dict] = []
    raw_dirs: list[dict] = []

    for item in sorted(template_dir.rglob("*")):
        rel = item.relative_to(template_dir)
        rel_str = rel.as_posix()

        if SKIP_NAMES.intersection(rel.parts):
            continue

        if ".spawn" in rel.parts and item.is_file() and item.name in _SKIP_SPAWN_FILES:
            continue

        if item.is_dir():
            has_placeholder = any(p in item.name for p in _BRANCH_PLACEHOLDERS)
            raw_dirs.append(
                {
                    "path": rel_str,
                    "name": item.name,
                    "has_branch_placeholder": has_placeholder,
                }
            )

        elif item.is_file():
            content_hash = compute_file_hash(item)
            has_placeholder = any(p in item.name for p in _BRANCH_PLACEHOLDERS)
            raw_files.append(
                {
                    "path": rel_str,
                    "name": item.name,
                    "content_hash": content_hash,
                    "has_branch_placeholder": has_placeholder,
                }
            )

    files: dict[str, dict] = {}
    unmatched_files: list[dict] = []

    for entry in raw_files:
        path = entry.get("path", "")
        if path and path in path_to_file_id:
            candidate = path_to_file_id[path]
            if candidate not in claimed_file_ids:
                claimed_file_ids.add(candidate)
                files[candidate] = entry
                continue
        unmatched_files.append(entry)

    still_unmatched: list[dict] = []
    for entry in unmatched_files:
        content_hash = entry.get("content_hash", "")
        if content_hash and content_hash in hash_to_id:
            candidate = hash_to_id[content_hash]
            if candidate not in claimed_file_ids:
                claimed_file_ids.add(candidate)
                files[candidate] = entry
                continue
        still_unmatched.append(entry)

    for entry in still_unmatched:
        fid = _next_id("f", claimed_file_ids)
        claimed_file_ids.add(fid)
        files[fid] = entry

    directories: dict[str, dict] = {}
    unmatched_dirs: list[dict] = []

    for entry in raw_dirs:
        path = entry.get("path", "")
        if path and path in path_to_dir_id:
            candidate = path_to_dir_id[path]
            if candidate not in claimed_dir_ids:
                claimed_dir_ids.add(candidate)
                directories[candidate] = entry
                continue
        unmatched_dirs.append(entry)

    still_unmatched_dirs: list[dict] = []
    for entry in unmatched_dirs:
        name = entry.get("name", "")
        if name and name in name_to_dir_id:
            candidate = name_to_dir_id[name]
            if candidate not in claimed_dir_ids:
                claimed_dir_ids.add(candidate)
                directories[candidate] = entry
                continue
        still_unmatched_dirs.append(entry)

    for entry in still_unmatched_dirs:
        did = _next_id("d", claimed_dir_ids)
        claimed_dir_ids.add(did)
        directories[did] = entry

    return files, directories


def _next_id(prefix: str, claimed: set[str]) -> str:
    """Generate the next sequential ID with the given prefix (f001..f999, d001..d999)."""
    for i in range(1, 1000):
        candidate = f"{prefix}{i:03d}"
        if candidate not in claimed:
            return candidate
    logger.warning(f"ID space exhausted for prefix '{prefix}'")
    return f"{prefix}999"
