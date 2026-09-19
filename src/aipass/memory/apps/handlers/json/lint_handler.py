# =================== AIPass ====================
# Name: lint_handler.py
# Description: Read-only lint handler for .trinity entry limit violations
# Version: 1.3.0
# Created: 2026-06-13
# Modified: 2026-09-15
# =============================================

"""
Lint Handler — Entry Limit Violation Scanner

Scans .trinity memory files across branches and reports entries that
exceed their configured character caps.  Strictly **read-only** — never
writes, modifies, truncates, or deletes any file.

Called by the ``lint`` module (thin CLI layer).

TWO MODES, ONE TRAVERSAL SHAPE (FPLAN-0593 / DPLAN-0347)
-------------------------------------------------------
``run_lint`` measures the CANONICAL text field against its cap — the scan
this handler has always done, unchanged.

``run_lint_fields`` measures EVERY OTHER field against the closed shape
``entry_limits`` publishes, because one capped field per entry type is what
let @devpulse carry a 917-char ``status`` past every gate while the fleet
median is 9.  It is an INVENTORY first and a violation report second: every
string field is listed by characters whether or not it is in breach, since
the number nobody could see is the reason the drift survived.

The two modes never report the same defect twice.  ``check_fields`` skips
the canonical field by contract and ``run_lint_fields`` never re-derives a
cap — the canonical field appears in the fields-mode inventory so the
picture is complete, and its violation stays with ``run_lint``.
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


# ---------------------------------------------------------------------------
# Fields mode — the closed-shape inventory (FPLAN-0593)
# ---------------------------------------------------------------------------


def _percentile(values: list[int], fraction: float) -> int:
    """Return the nearest-rank *fraction* percentile of *values*.

    Nearest-rank rather than interpolated: every number this prints is a
    length some entry actually has, so an agent can go and find it. An
    interpolated 271.4 belongs to no entry and cannot be acted on.

    Args:
        values: Measured lengths, in any order.
        fraction: Percentile as a fraction, e.g. ``0.95``.

    Returns:
        The value at that rank, or 0 when there is nothing to measure.
    """
    if not values:
        return 0
    ordered = sorted(values)
    rank = int(math.ceil(fraction * len(ordered)))
    return ordered[min(max(rank, 1), len(ordered)) - 1]


def _cap_of(spec: Any, key: str) -> int:
    """Read one integer cap off a field spec, 0 when it publishes none.

    0 means "no cap known for this field" everywhere in this module — the
    same convention ``check_entry`` already uses for an unknown entry type.
    """
    if not isinstance(spec, dict):
        return 0
    cap = spec.get(key)
    return cap if isinstance(cap, int) and not isinstance(cap, bool) else 0


def _entry_pairs(container_data: Any, kind: str) -> list[tuple[str, Any]]:
    """Return (key-label, WHOLE entry) pairs for a container.

    Deliberately not ``_measure_dict_container``: those two extract the
    canonical TEXT, which is the one field this mode does not judge. The
    fields mode needs the entry itself, every key of it.
    """
    if kind == "dict" and isinstance(container_data, dict):
        return [(str(key), value) for key, value in container_data.items()]
    if kind == "list" and isinstance(container_data, list):
        return [(f"[{idx}]", item) for idx, item in enumerate(container_data)]
    return []


def _measure_fields(entry: Any, shape: dict[str, Any], canonical: str) -> list[dict[str, Any]]:
    """Measure every string-bearing field of ONE entry.

    An inventory, not a judgement: a field outside the shape is measured and
    reported with ``cap`` 0 rather than dropped, because "how many characters
    is this thing nobody configured" is the question the mode exists to
    answer. ``check_fields`` decides separately whether it is in breach.

    A ``list[str]`` field yields TWO rows — items and joined characters —
    because the shape caps it both ways and a list can bust either alone.

    Args:
        entry: The entry as it sits in the file.
        shape: The closed field shape for this entry type (may be empty).
        canonical: Name of the canonical text field.

    Returns:
        Partial records: ``field``, ``units``, ``length``, ``cap``,
        ``canonical``. The caller stamps branch/file/type on them.
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
    """Read and parse one .trinity file, returning ``("", None)`` on any failure.

    Read-only by construction: this is the only filesystem call the fields
    mode makes, and it opens for reading.
    """
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
    """Inventory every string field of one branch, and flag what is outside the shape.

    Same traversal as :func:`_lint_branch` — the entry types name their own
    file, container and kind, so the two modes can never disagree about which
    files belong to a branch.

    Args:
        branch_name: Branch name, for the records and the log.
        branch_path: Absolute path to the branch root.
        limits: The dict returned by ``load_entry_limits``.

    Returns:
        ``(records, violations)``. Records are the inventory, one per
        measured field per entry; violations come from ``check_fields``
        with ``branch`` and ``file`` stamped on.
    """
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
    """Measure one branch's passport.json against its whole-file budget.

    The passport has no closed field shape — @spawn owns its schema — so it
    is measured by size only: the whole file against 6,000 characters and
    every single string in it against 600.

    Args:
        branch_name: Branch name, for the records.
        branch_path: Absolute path to the branch root.
        budgets: The map returned by ``load_file_budgets``.

    Returns:
        ``(row, violations)``. The row is None when the branch has no
        passport; violations carry ``branch`` and ``file``.
    """
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
    """Roll the per-entry inventory up to one row per branch/type/field/units.

    803 entries across 22 branches is not something anyone reads entry by
    entry; ``max`` and ``p95`` beside the cap are what showed the 917-char
    ``status`` against a fleet median of 9 in the first place.

    Pure — no I/O.

    Args:
        records: Inventory records from :func:`_lint_branch_fields`.
        violations: The flags for the same scan, so each row can say how
            many of its measurements are in breach.

    Returns:
        Rows with ``branch``, ``file``, ``entry_type``, ``field``, ``units``,
        ``count``, ``max``, ``p95``, ``cap``, ``canonical``, ``flagged`` and
        ``worst_over``. Grouped by branch, entry types in config order,
        fields worst-first within a type.
    """
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

    # A field ranks by its WORST unit, so a list's items row and chars row stay
    # side by side. Ranking each row on its own split `tags` across the block
    # and made one field look like two.
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
    """Inventory every .trinity string field across branches, flagging the closed shape.

    This function is **read-only** — it never writes, modifies, truncates,
    or deletes any file.

    Args:
        branches: List of branch dicts (``{"name": ..., "path": ...}``),
            typically from ``_read_registry()`` in the module layer.
        branch_filter: If provided, only scan this branch (case-insensitive).

    Returns:
        Result dict::

            {
                "success": True,
                "fields": [...],       # per-entry inventory records
                "summary": [...],      # one row per branch/type/field/units
                "violations": [...],   # sorted worst-first (highest over_by)
                "passport": [...],     # one whole-file row per branch
                "total_fields": int,
                "total_violations": int,
                "branches_scanned": int,
                "branches_skipped": int,
            }
    """
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

    # Worst-first, exactly as the canonical mode sorts.
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
