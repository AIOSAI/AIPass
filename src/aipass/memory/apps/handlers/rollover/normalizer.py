# =================== AIPass ====================
# Name: normalizer.py
# Description: Frame-only re-render for a branch rollover just touched — heals the machine frame, never the entries
# Version: 1.0.0
# Created: 2026-08-27
# Modified: 2026-08-27
# =============================================

"""Rollover Normalizer

A branch that rolls heals its own machine frame.

Rollover already rewrites a branch's memory file — it removes the oldest
entries and writes the file back.  At that moment the file is open, the branch
is named, and the write is already happening, so re-rendering the machine
frame costs one more pass over a dict.  This is what "self-healing is
trigger-driven" means in this lane: nothing watches, nothing polls, and idle
means zero processes.  A branch that never rolls is never touched.

WHAT THIS DOES, AND THE HALF IT REFUSES
---------------------------------------
It re-renders exactly what the trinity push's step 1 re-renders:
``document_metadata`` as the standard's CLOSED set, ``managed_by`` in exact
branch-directory casing, ``_usage`` and ``guidelines`` verbatim from the gold
templates, and every ``*_meta`` line re-composed from config.  It shares
``trinity_push.build_frame`` rather than reimplementing it — a second renderer
would drift from the first within a release, and the whole standard exists
because two copies of a structure disagree.

It does NOT prune.  Every entry carries over exactly as found, canonical or
not.  Pruning is the push's mandate and the push earns it with a report, a
verified vector round-trip, a receipt and an in-file note; a rollover that
quietly archived entries on the side would be the push's dangerous half
running with none of its gates, from a lane nobody is watching.

SCOPED, ALWAYS
--------------
``normalize_branch`` takes ONE branch and touches ONE branch.  There is no
fleet entry point here on purpose.  On 2026-08-25 an unscoped
``refresh_all_tabs()`` on the tail of a single overdue rollover rewrote all 38
memory files in the fleet, shipping a renderer change to every citizen from a
PreCompact hook nobody was watching.  A per-branch verb with a fleet-wide tail
is the shape that did it, and it is not built twice.
"""

from pathlib import Path
from typing import Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader
from aipass.memory.apps.handlers.json.memory_files import read_memory_file_data, write_memory_file_simple
from aipass.memory.apps.handlers.templates import trinity_push


def _normalize_file(branch_name: str, trinity: Path, file_key: str, config: dict) -> dict:
    """Re-render one file's frame around its existing entries.

    Args:
        branch_name: Branch DIRECTORY name — what ``managed_by`` must equal.
        trinity: The branch's ``.trinity/`` directory.
        file_key: ``local`` or ``observations``.
        config: The parsed memory.config.json.

    Returns:
        ``{"written": bool, "error": str | None, "changes": [str]}``.
    """
    path = trinity / trinity_push._FILE_NAMES[file_key]
    if not path.is_file():
        return {"written": False, "error": f"{path.name}: not found", "changes": []}

    before = read_memory_file_data(path)
    if not isinstance(before, dict):
        # Never treated as empty: rebuilding a frame around no entries would
        # delete a branch's whole memory to fix its formatting.
        return {"written": False, "error": f"{path.name}: unreadable or not a JSON object", "changes": []}

    entries: dict[str, list] = {}
    for section in trinity_push._SECTIONS[file_key]:
        raw = before.get(section)
        if raw is None:
            entries[section] = []
            continue
        if not isinstance(raw, list):
            return {
                "written": False,
                "error": f"{path.name}: '{section}' must be a list, found {type(raw).__name__}",
                "changes": [],
            }
        entries[section] = list(raw)

    after = trinity_push.build_frame(before, file_key, branch_name, entries, config)
    changes = trinity_push._frame_changes(before, after, file_key)
    if not write_memory_file_simple(path, after):
        return {"written": False, "error": f"{path.name}: write failed", "changes": changes}
    return {"written": True, "error": None, "changes": changes}


def normalize_branch(branch_name: str, branch_path: Path, config: dict | None = None) -> dict[str, Any]:
    """Re-render ONE branch's machine frame in place. Entries are untouched.

    Args:
        branch_name: Branch DIRECTORY name, exact casing.
        branch_path: Branch root (the directory holding ``.trinity/``).
        config: Parsed memory.config.json; loaded here when omitted.

    Returns:
        ``{"success": bool, "branch": str, "written": int, "changes": {...},
        "error": str | None}``. ``success`` is False when nothing could be
        written — never an exception, because this runs on the tail of a
        rollover that already succeeded and must not undo its own report.
    """
    trinity = Path(branch_path) / trinity_push.TRINITY_DIR
    result: dict[str, Any] = {
        "success": False,
        "branch": branch_name,
        "written": 0,
        "changes": {},
        "error": None,
    }

    if not trinity.is_dir():
        result["error"] = f"{branch_name}: no .trinity/ directory at {trinity}"
        logger.warning(f"[normalizer] {result['error']}")
        return result

    if config is None:
        config = config_loader.load()

    errors = []
    for file_key in ("local", "observations"):
        outcome = _normalize_file(branch_name, trinity, file_key, config)
        result["changes"][file_key] = outcome["changes"]
        if outcome["written"]:
            result["written"] += 1
        if outcome["error"]:
            errors.append(outcome["error"])

    result["success"] = result["written"] > 0
    if errors:
        result["error"] = f"{branch_name}: " + "; ".join(errors)
        logger.warning(f"[normalizer] {result['error']}")

    json_handler.log_operation(
        "normalize_branch",
        {"branch": branch_name, "written": result["written"], "errors": len(errors)},
        module_name="normalizer",
    )
    return result
