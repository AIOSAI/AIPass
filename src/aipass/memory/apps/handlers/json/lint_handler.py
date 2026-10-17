# =================== AIPass ====================
# Name: lint_handler.py
# Description: Read-only lint handler for .trinity entry limit violations
# Version: 1.3.0
# Created: 2026-06-13
# Modified: 2026-10-17
# =============================================

"""
Lint Handler — Entry Limit Violation Scanner

Read-only. ``run_lint`` judges the canonical field; ``run_lint_fields`` inventories every
other field, so the two never report the same defect twice.
"""

import json
import math
from pathlib import Path
from typing import Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json.entry_limits import (
    check_entry,
    check_fields,
    check_file_budget,
    fields_for,
    load_entry_limits,
    load_file_budgets,
)

# The passport is measured as a WHOLE FILE, never against a field shape:
# @spawn owns its schema, so this handler asks only how big it is.
PASSPORT_FILE = "passport.json"

# The summary percentile. High enough that one fat outlier cannot move it,
# low enough to say what the type actually costs on a normal branch.
P95 = 0.95

# Units a measurement can be in, named once because the summary joins on them.
UNITS_CHARS = "chars"
UNITS_ITEMS = "items"


def _measure_dict_container(
    data: dict[str, Any],
    field: str,
) -> list[tuple[str, Any, bool]]:
    """Extract (key, payload, field_present) triples from a dict-style container.

    The payload stays untyped and missing fields are kept: ``check_entry`` must see what the write gate refuses.
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

    Untyped on purpose: ``len()`` on a list of dicts measured 3 and passed a 300-char cap.
    """
    pairs: list[tuple[str, Any, bool]] = []
    for idx, item in enumerate(data):
        if isinstance(item, dict):
            pairs.append((f"[{idx}]", item.get(field), field in item))
        else:
            pairs.append((f"[{idx}]", item, True))
    return pairs


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
    """Build one violation record; ``missing_field`` names a key to rename, ``unmeasurable`` a wrong type."""
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
    """Lint a single branch and return a list of violation dicts."""
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


def run_lint(
    branches: list[dict[str, Any]],
    branch_filter: str | None = None,
) -> dict[str, Any]:
    """Scan branches for entry-limit violations (read-only), worst-first."""
    all_violations: list[dict[str, Any]] = []
    branches_scanned = 0
    branches_skipped = 0

    for branch in branches:
        name = branch.get("name", "unknown")
        path = branch.get("path", "")

        if branch_filter and name.lower() != branch_filter.lower():
            continue

        limits = load_entry_limits(name)

        if not limits.get("enabled", True):
            branches_skipped += 1
            continue

        branch_violations = _lint_branch(name, path, limits)
        all_violations.extend(branch_violations)
        branches_scanned += 1

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


def _percentile(values: list[int], fraction: float) -> int:
    """Return the nearest-rank *fraction* percentile of *values* (0 when empty).

    Nearest-rank, not interpolated: every number printed is a length some entry really has.
    """
    if not values:
        return 0
    ordered = sorted(values)
    rank = int(math.ceil(fraction * len(ordered)))
    return ordered[min(max(rank, 1), len(ordered)) - 1]


def _cap_of(spec: Any, key: str) -> int:
    """Read one integer cap off a field spec, 0 when it publishes none (``check_entry``'s convention)."""
    if not isinstance(spec, dict):
        return 0
    cap = spec.get(key)
    return cap if isinstance(cap, int) and not isinstance(cap, bool) else 0


def _entry_pairs(container_data: Any, kind: str) -> list[tuple[str, Any]]:
    """Return (key-label, WHOLE entry) pairs; the _measure_* helpers extract only the canonical text."""
    if kind == "dict" and isinstance(container_data, dict):
        return [(str(key), value) for key, value in container_data.items()]
    if kind == "list" and isinstance(container_data, list):
        return [(f"[{idx}]", item) for idx, item in enumerate(container_data)]
    return []


def _measure_fields(entry: Any, shape: dict[str, Any], canonical: str) -> list[dict[str, Any]]:
    """Measure every string-bearing field of ONE entry.

    An inventory: an unshaped field is reported with ``cap`` 0, not dropped. A ``list[str]`` field
    yields an items row and a chars row, since the shape caps it both ways.
    """
    if isinstance(entry, str):
        # The legacy dict-container shape: the value IS the canonical text.
        return [
            {
                "field": canonical,
                "units": UNITS_CHARS,
                "length": len(entry),
                "cap": _cap_of(shape.get(canonical), "max_chars"),
                "canonical": True,
            }
        ]
    if not isinstance(entry, dict):
        return []

    rows: list[dict[str, Any]] = []
    for field, value in entry.items():
        spec = shape.get(field)
        if isinstance(value, str):
            rows.append(
                {
                    "field": field,
                    "units": UNITS_CHARS,
                    "length": len(value),
                    "cap": _cap_of(spec, "max_chars"),
                    "canonical": field == canonical,
                }
            )
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            rows.append(
                {
                    "field": field,
                    "units": UNITS_ITEMS,
                    "length": len(value),
                    "cap": _cap_of(spec, "max_items"),
                    "canonical": False,
                }
            )
            rows.append(
                {
                    "field": field,
                    "units": UNITS_CHARS,
                    "length": len("".join(value)),
                    "cap": _cap_of(spec, "max_chars"),
                    "canonical": False,
                }
            )
    return rows


def _read_trinity_file(branch_name: str, path: Path) -> tuple[str, Any]:
    """Read and parse one .trinity file, returning ``("", None)`` on any failure (the fields mode's only I/O)."""
    try:
        raw = path.read_text(encoding="utf-8")
        return raw, json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"[lint] {branch_name}: failed to read {path.name}: {exc}")
        return "", None


def _lint_branch_fields(
    branch_name: str,
    branch_path: str,
    limits: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Inventory every string field of one branch and flag what is outside the shape (same walk as _lint_branch)."""
    records: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    trinity_dir = Path(branch_path) / ".trinity"

    if not trinity_dir.is_dir():
        logger.info(f"[lint] Branch '{branch_name}' has no .trinity directory, skipping")
        return records, violations

    for type_name, type_def in limits.get("entry_types", {}).items():
        file_name = type_def.get("file", "")
        container = type_def.get("container", "")
        canonical = type_def.get("field", "")

        file_path = trinity_dir / file_name
        if not file_path.is_file():
            logger.info(f"[lint] {branch_name}: missing {file_name}, skipping {type_name}")
            continue

        _raw, data = _read_trinity_file(branch_name, file_path)
        if not isinstance(data, dict):
            continue

        shape = fields_for(type_name, limits)
        stamp = {"branch": branch_name, "file": file_name, "entry_type": type_name, "container": container}

        for key, entry in _entry_pairs(data.get(container), type_def.get("kind", "")):
            for row in _measure_fields(entry, shape, canonical):
                records.append({**stamp, "key": key, **row})
            for hit in check_fields(type_name, container, key, entry, limits):
                violations.append({"branch": branch_name, "file": file_name, **hit})

    return records, violations


def _lint_branch_passport(
    branch_name: str,
    branch_path: str,
    budgets: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Measure one branch's passport.json against its whole-file budget; row is None with no passport."""
    file_path = Path(branch_path) / ".trinity" / PASSPORT_FILE
    if not file_path.is_file():
        logger.info(f"[lint] {branch_name}: no {PASSPORT_FILE}, skipping the passport row")
        return None, []

    raw, _data = _read_trinity_file(branch_name, file_path)
    if not raw:
        return None, []

    spec = budgets.get(PASSPORT_FILE, {})
    hits = [
        {"branch": branch_name, "file": PASSPORT_FILE, **hit} for hit in check_file_budget(PASSPORT_FILE, raw, budgets)
    ]
    row = {
        "branch": branch_name,
        "file": PASSPORT_FILE,
        "length": len(raw),
        "cap": _cap_of(spec, "max_chars"),
        "string_cap": _cap_of(spec, "max_string_chars"),
        "oversized_strings": sum(1 for hit in hits if hit.get("reason") != "file_over_budget"),
    }
    return row, hits


def summarize_fields(
    records: list[dict[str, Any]],
    violations: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Roll the per-entry inventory up to one row per branch/type/field/units (pure)."""
    flags: dict[tuple[str, ...], dict[str, int]] = {}
    for hit in violations or []:
        key = (hit.get("branch", ""), hit.get("entry_type", ""), hit.get("field", ""), hit.get("units", UNITS_CHARS))
        slot = flags.setdefault(key, {"flagged": 0, "worst_over": 0})
        slot["flagged"] += 1
        slot["worst_over"] = max(slot["worst_over"], hit.get("over_by", 0))

    buckets: dict[tuple[str, ...], dict[str, Any]] = {}
    type_order: dict[tuple[str, str], int] = {}
    for rec in records:
        type_order.setdefault((rec["branch"], rec["entry_type"]), len(type_order))
        key = (rec["branch"], rec["entry_type"], rec["field"], rec["units"])
        slot = buckets.setdefault(
            key,
            {
                "branch": rec["branch"],
                "file": rec["file"],
                "entry_type": rec["entry_type"],
                "field": rec["field"],
                "units": rec["units"],
                "cap": rec["cap"],
                "canonical": rec["canonical"],
                "lengths": [],
            },
        )
        slot["lengths"].append(rec["length"])

    rows: list[dict[str, Any]] = []
    for key, slot in buckets.items():
        lengths = slot.pop("lengths")
        flag = flags.get(key, {"flagged": 0, "worst_over": 0})
        rows.append(
            {
                **slot,
                "count": len(lengths),
                "max": max(lengths),
                "p95": _percentile(lengths, P95),
                "flagged": flag["flagged"],
                "worst_over": flag["worst_over"],
            }
        )

    # A field ranks by its WORST unit so a list's items and chars rows stay adjacent.
    rank: dict[tuple[str, str, str], tuple[int, int]] = {}
    for row in rows:
        key = (row["branch"], row["entry_type"], row["field"])
        worst = (-row["worst_over"], -row["max"])
        rank[key] = min(rank.get(key, worst), worst)

    rows.sort(
        key=lambda r: (
            r["branch"],
            type_order.get((r["branch"], r["entry_type"]), 0),
            rank[(r["branch"], r["entry_type"], r["field"])],
            r["field"],
            r["units"],
        )
    )
    return rows


def run_lint_fields(
    branches: list[dict[str, Any]],
    branch_filter: str | None = None,
) -> dict[str, Any]:
    """Inventory every .trinity string field across branches, flagging the closed shape (read-only)."""
    budgets = load_file_budgets()
    records: list[dict[str, Any]] = []
    all_violations: list[dict[str, Any]] = []
    passports: list[dict[str, Any]] = []
    branches_scanned = 0
    branches_skipped = 0

    for branch in branches:
        name = branch.get("name", "unknown")
        path = branch.get("path", "")

        if branch_filter and name.lower() != branch_filter.lower():
            continue

        limits = load_entry_limits(name)
        if not limits.get("enabled", True):
            branches_skipped += 1
            continue

        branch_records, branch_violations = _lint_branch_fields(name, path, limits)
        passport_row, passport_violations = _lint_branch_passport(name, path, budgets)

        records.extend(branch_records)
        all_violations.extend(branch_violations)
        all_violations.extend(passport_violations)
        if passport_row is not None:
            passports.append(passport_row)
        branches_scanned += 1

    all_violations.sort(key=lambda v: v.get("over_by", 0), reverse=True)

    json_handler.log_operation(
        "lint_fields",
        {
            "total_fields": len(records),
            "total_violations": len(all_violations),
            "branches_scanned": branches_scanned,
            "branch_filter": branch_filter,
        },
        module_name="lint",
    )

    return {
        "success": True,
        "fields": records,
        "summary": summarize_fields(records, all_violations),
        "violations": all_violations,
        "passport": passports,
        "total_fields": len(records),
        "total_violations": len(all_violations),
        "branches_scanned": branches_scanned,
        "branches_skipped": branches_skipped,
    }
