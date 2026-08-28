# =================== AIPass ====================
# Name: lint_handler.py
# Description: Read-only lint handler for .trinity entry limit violations
# Version: 1.2.0
# Created: 2026-06-13
# Modified: 2026-06-13
# =============================================

"""
Lint Handler — Entry Limit Violation Scanner

Scans .trinity memory files across branches and reports entries that
exceed their configured character caps.  Strictly **read-only** — never
writes, modifies, truncates, or deletes any file.

Called by the ``lint`` module (thin CLI layer).
"""

import json
from pathlib import Path
from typing import Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json.entry_limits import (
    check_entry,
    load_entry_limits,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _measure_dict_container(
    data: dict[str, Any],
    field: str,
) -> list[tuple[str, Any, bool]]:
    """Extract (key, payload, field_present) triples from a dict-style container.

    Each value may be:
      - a plain string (the entry itself), or
      - a dict containing *field* (the entry is ``value[field]``).

    The payload is returned **as it sits in the file**, whatever its type.
    Judging it is ``check_entry``'s job, and it refuses anything it cannot
    measure — filtering non-strings out here would restore the silence this
    scanner exists to break.

    ``field_present`` distinguishes the two refusal species: a value the
    scanner cannot READ from a field it cannot FIND. An entry that lacks the
    canonical key used to be dropped here, so lint answered "compliant" for a
    shape the write gate refuses.
    """
    pairs: list[tuple[str, Any, bool]] = []
    for key, value in data.items():
        if isinstance(value, dict):
            pairs.append((key, value.get(field), field in value))
        else:
            pairs.append((key, value, True))
    return pairs


def _measure_list_container(
    data: list[Any],
    field: str,
) -> list[tuple[str, Any, bool]]:
    """Extract (index-label, payload, field_present) triples from a list container.

    Each item is expected to be a dict containing *field*; a bare string item
    carries its own text, matching ``_extract_text``.

    The payload is returned untyped, on purpose. This function used to hand
    ``item[field]`` straight to ``len()``: a ``note`` holding three dicts
    measured as **3** and sailed under a 300-char cap. That was the second
    independent silent pass over the same corruption (the first being the
    edit-time gate), and two blind measurements agreeing is what made the
    drift look verified.

    Items lacking the canonical field used to be skipped here, on the reading
    that a missing field is a shape question for the trinity checker. That
    boundary cost more than it bought: the write gate refuses those entries,
    so a branch could be told it was compliant and then be blocked on its next
    write for a shape lint had already seen and said nothing about.
    """
    pairs: list[tuple[str, Any, bool]] = []
    for idx, item in enumerate(data):
        if isinstance(item, dict):
            pairs.append((f"[{idx}]", item.get(field), field in item))
        else:
            pairs.append((f"[{idx}]", item, True))
    return pairs


# ---------------------------------------------------------------------------
# Core lint logic
# ---------------------------------------------------------------------------


def _violation_record(
    branch_name: str,
    file_name: str,
    container: str,
    key: str,
    type_name: str,
    verdict: dict[str, Any],
    text: Any,
    field: str,
    present: bool,
) -> dict[str, Any]:
    """Build one violation record and log the cause it names.

    Two refusal species share the eight base keys and differ in what the agent
    must DO about them: ``missing_field`` names the key to rename,
    ``unmeasurable`` names the type that arrived where a string belongs.
    """
    violation: dict[str, Any] = {
        "branch": branch_name,
        "file": file_name,
        "container": container,
        "key": key,
        "length": verdict["length"],
        "cap": verdict["cap"],
        "over_by": verdict["over_by"],
        "entry_type": type_name,
    }
    if not verdict.get("reason"):
        return violation

    if not present:
        violation["reason"] = "missing_field"
        violation["found_type"] = "missing"
        violation["field"] = field
        logger.warning(
            f"[lint] {branch_name}/{file_name} {container}{key}: "
            f"{type_name} has no '{field}' field — cannot be measured"
        )
        return violation

    violation["reason"] = verdict["reason"]
    violation["found_type"] = type(text).__name__
    logger.warning(
        f"[lint] {branch_name}/{file_name} {container}{key}: "
        f"{type_name} is {type(text).__name__}, not str — cannot be measured"
    )
    return violation


def _lint_branch(
    branch_name: str,
    branch_path: str,
    limits: dict[str, Any],
) -> list[dict[str, Any]]:
    """Lint a single branch and return a list of violation dicts.

    Each violation dict has keys:
        branch, file, container, key, length, cap, over_by, entry_type
    An unmeasurable payload adds ``reason`` and ``found_type``; a missing
    canonical field adds ``field`` beside them.
    """
    violations: list[dict[str, Any]] = []
    trinity_dir = Path(branch_path) / ".trinity"

    if not trinity_dir.is_dir():
        logger.info(f"[lint] Branch '{branch_name}' has no .trinity directory, skipping")
        return violations

    entry_types = limits.get("entry_types", {})

    for type_name, type_def in entry_types.items():
        file_name = type_def.get("file", "")
        container = type_def.get("container", "")
        kind = type_def.get("kind", "")
        field = type_def.get("field", "")

        file_path = trinity_dir / file_name
        if not file_path.is_file():
            logger.info(f"[lint] {branch_name}: missing {file_name}, skipping {type_name}")
            continue

        try:
            raw = file_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"[lint] {branch_name}: failed to read {file_name}: {exc}")
            continue

        container_data = data.get(container)
        if container_data is None:
            continue

        # Build (key, text) pairs depending on kind
        if kind == "dict" and isinstance(container_data, dict):
            pairs = _measure_dict_container(container_data, field)
        elif kind == "list" and isinstance(container_data, list):
            pairs = _measure_list_container(container_data, field)
        else:
            continue

        for key, text, present in pairs:
            verdict = check_entry(type_name, text, limits)
            if not verdict["ok"]:
                violations.append(
                    _violation_record(branch_name, file_name, container, key, type_name, verdict, text, field, present)
                )

    return violations


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_lint(
    branches: list[dict[str, Any]],
    branch_filter: str | None = None,
) -> dict[str, Any]:
    """Scan branches for entry-limit violations.

    This function is **read-only** — it never writes, modifies, truncates,
    or deletes any file.

    Args:
        branches: List of branch dicts (``{"name": ..., "path": ...}``),
            typically from ``_read_registry()`` in the module layer.
        branch_filter: If provided, only lint this branch (case-insensitive).

    Returns:
        Result dict::

            {
                "success": True,
                "violations": [...],      # sorted worst-first (highest over_by)
                "total_violations": int,
                "branches_scanned": int,
                "branches_skipped": int,
            }
    """
    all_violations: list[dict[str, Any]] = []
    branches_scanned = 0
    branches_skipped = 0

    for branch in branches:
        name = branch.get("name", "unknown")
        path = branch.get("path", "")

        # Apply branch filter (case-insensitive)
        if branch_filter and name.lower() != branch_filter.lower():
            continue

        limits = load_entry_limits(name)

        if not limits.get("enabled", True):
            branches_skipped += 1
            continue

        branch_violations = _lint_branch(name, path, limits)
        all_violations.extend(branch_violations)
        branches_scanned += 1

    # Sort worst-first (highest over_by)
    all_violations.sort(key=lambda v: v["over_by"], reverse=True)

    json_handler.log_operation(
        "lint",
        {
            "total_violations": len(all_violations),
            "branches_scanned": branches_scanned,
            "branch_filter": branch_filter,
        },
        module_name="lint",
    )

    return {
        "success": True,
        "violations": all_violations,
        "total_violations": len(all_violations),
        "branches_scanned": branches_scanned,
        "branches_skipped": branches_skipped,
    }
