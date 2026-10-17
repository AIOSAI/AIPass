# =================== AIPass ====================
# Name: retire_ops.py
# Description: The retire lane — a test file leaves by a logged move and can come back
# Version: 1.0.0
# Created: 2026-09-21
# Modified: 2026-10-17
# =============================================

"""Retire lane operations.

A retired file is moved to ``<repo_root>/.backup/tests/<branch>/``, never deleted:
the moved file is the only copy. The repo root is the registry's directory, never
cwd: drone runs a branch from the branch's own directory.
"""

import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers import registry_scan
from aipass.seedgo.apps.handlers.json import json_handler


BACKUP_DIR = ".backup"
TESTS_DIR = "tests"
LOG_FILE = "retired.json"

#: The document a caller gets when a branch has never retired anything. Written
#: only when the first entry lands, so an untouched branch has no empty file.
EMPTY_LOG: Dict = {
    "document_metadata": {
        "document_type": "retired_tests_log",
        "schema_version": "1.0.0",
        "managed_by": "seedgo",
    },
    "entries": [],
}


def repo_root() -> Path:
    """The directory holding AIPASS_REGISTRY.json — the repo, never the cwd."""
    return registry_scan.find_registry().parent


def retire_root(branch: str, root: Optional[Path] = None) -> Path:
    """The retire folder for one branch: ``<repo>/.backup/tests/<branch>/``."""
    base = Path(root) if root is not None else repo_root()
    return base / BACKUP_DIR / TESTS_DIR / branch


def log_path(branch: str, root: Optional[Path] = None) -> Path:
    """The retired.json that sits beside the moved files."""
    return retire_root(branch, root) / LOG_FILE


def read_log(branch: str, root: Optional[Path] = None) -> Dict:
    """Read a branch's retire log, or the empty document if it has none."""
    path = log_path(branch, root)
    if not path.exists():
        return {"document_metadata": dict(EMPTY_LOG["document_metadata"]), "entries": []}
    try:
        document = json_handler.read_json(path)
    except Exception as exc:
        logger.info("Cannot read retire log at %s: %s", path, exc)
        return {"document_metadata": dict(EMPTY_LOG["document_metadata"]), "entries": []}
    if not isinstance(document, dict) or "entries" not in document:
        logger.info("Retire log at %s is not a retire log", path)
        return {"document_metadata": dict(EMPTY_LOG["document_metadata"]), "entries": []}
    return document


def list_retired(branch: str, root: Optional[Path] = None) -> List[Dict]:
    """Every retired file for a branch, newest first, each marked present or not.

    ``present`` is measured off the disk, not trusted from the log.
    """
    folder = retire_root(branch, root)
    document = read_log(branch, root)

    rows: List[Dict] = []
    logged: set = set()
    for entry in document.get("entries", []):
        name = str(entry.get("what", ""))
        logged.add(name)
        rows.append({**entry, "present": bool(name) and (folder / name).exists()})

    if folder.exists():
        for found in sorted(folder.glob("*.py")):
            if found.name not in logged:
                rows.append({"what": found.name, "when": "", "why": "", "from": "", "by": "", "present": True})
    return rows


def restore(name: str, branch: str, root: Optional[Path] = None) -> Tuple[bool, str]:
    """Move one retired file back to the path its log line says it came from.

    The destination is read, never guessed: a file with no recorded origin refuses.
    A refusal never moves anything and never edits the log.
    """
    filename = name if name.endswith(".py") else f"{name}.py"
    source = retire_root(branch, root) / filename
    if not source.exists():
        return False, f"nothing retired under that name: {filename}"

    origin = _recorded_origin(filename, branch, root)
    if origin is None:
        return False, f"{filename} has no log line, so nothing records where it came from"

    base = Path(root) if root is not None else repo_root()
    target = base / origin
    if target.exists():
        return False, f"{filename} already exists at {target.parent} — move it aside first"

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(source), str(target))
    except OSError as exc:
        logger.info("Cannot restore %s to %s: %s", source, target, exc)
        return False, f"could not move {filename}: {exc}"

    _drop_entry(filename, branch, root)
    json_handler.log_operation("test_restored", {"file": filename, "branch": branch})
    return True, f"{filename} restored to {target}"


def _recorded_origin(filename: str, branch: str, root: Optional[Path]) -> Optional[str]:
    """The repo-relative path the log says this file came from, or None."""
    for entry in read_log(branch, root).get("entries", []):
        if entry.get("what") == filename:
            origin = str(entry.get("from", "")).strip()
            return origin or None
    return None


def _drop_entry(filename: str, branch: str, root: Optional[Path]) -> None:
    """Remove a restored file's line from the log; the file is no longer retired."""
    path = log_path(branch, root)
    if not path.exists():
        return
    document = read_log(branch, root)
    document["entries"] = [e for e in document.get("entries", []) if e.get("what") != filename]
    document.setdefault("document_metadata", {})["last_restored"] = datetime.now().isoformat(timespec="seconds")
    try:
        json_handler.write_json(path, document)
    except Exception as exc:
        logger.error("Restored %s but could not update %s: %s", filename, path, exc)
