# =================== AIPass ====================
# Name: budget.py
# Description: Worst-case size arithmetic for the .trinity file budgets
# Version: 1.0.1
# Created: 2026-09-15
# Modified: 2026-10-23
# =============================================

"""File budget arithmetic. Imports no config_loader or entry_limits: config_loader calls this while resolving."""

import json
from typing import Any

_INDENT = 2
_ENTRY_DEPTH = 2
_ENTRY_INDENT = " " * (_INDENT * _ENTRY_DEPTH)

# Counts a comma for the last entry too: over by one char, the safe direction.
_SEPARATOR_CHARS = len(",\n")

_INT_DIGITS = 3
_WORST_INT = 10**_INT_DIGITS - 1

_TYPE_INT = "int"
_TYPE_STR_LIST = "list[str]"

# Set above the measured fleet max: the rendered *_meta prose grows when a tab gains a field.
FILE_STRUCTURE_ALLOWANCE: dict[str, int] = {"local.json": 3500, "observations.json": 2500}

# Mirrors rollover.defaults.local.sessions.auto_compact_cap: sessions on disk past the keep-count.
AUTO_COMPACT_EXTRA: dict[str, int] = {"sessions": 3}

# Far above rollover's _MAX_COUNT, so an unconfigured budget never refuses anything.
UNBOUNDED_CEILING = 10_000


def _worst_field_value(spec: Any) -> Any:
    """Largest legal field value; a list's JOINED text is max_chars, as _check_list_field measures."""
    if not isinstance(spec, dict):
        return ""

    kind = spec.get("type")
    if kind == _TYPE_INT:
        return _WORST_INT

    # shortcut: the plain cap, not the tolerance band (local.json worst case 23,973 -> 25,374 of 25,000 with it); upgrade on a budget ruling.
    max_chars = spec.get("max_chars")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 0:
        max_chars = 0

    if kind == _TYPE_STR_LIST:
        max_items = spec.get("max_items")
        if not isinstance(max_items, int) or isinstance(max_items, bool) or max_items < 1:
            max_items = 1
        # Item count drives the punctuation, total text drives the rest, so
        # how the chars are spread across the items cannot change the size.
        base, remainder = divmod(max_chars, max_items)
        return ["x" * (base + (1 if index < remainder else 0)) for index in range(max_items)]

    return "x" * max_chars


def worst_entry_chars(fields: dict) -> int:
    """The largest an entry of this shape can legally be, measured as written to disk."""
    if not isinstance(fields, dict) or not fields:
        return 0

    entry = {name: _worst_field_value(spec) for name, spec in fields.items()}
    block = json.dumps(entry, indent=_INDENT, ensure_ascii=False)
    indented = "\n".join(_ENTRY_INDENT + line for line in block.splitlines())
    return len(indented) + _SEPARATOR_CHARS


def _usable_count(value: Any) -> int:
    """A keep-count as arithmetic can use it — anything unusable is zero entries."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def worst_file_chars(file_key: str, counts: dict[str, int], entry_types: dict) -> int:
    """The largest *file_key* can legally get at these keep-counts."""
    total = FILE_STRUCTURE_ALLOWANCE.get(file_key, 0)
    if not isinstance(entry_types, dict):
        return total

    for type_name, type_def in entry_types.items():
        if not isinstance(type_def, dict) or type_def.get("file") != file_key:
            continue
        shape = type_def.get("fields")
        per_entry = worst_entry_chars(shape if isinstance(shape, dict) else {})
        count = _usable_count(counts.get(type_name)) + AUTO_COMPACT_EXTRA.get(type_name, 0)
        total += count * per_entry

    return total


def co_tenants(file_key: str, counts: dict[str, Any], entry_types: dict, exclude: str = "") -> dict[str, Any]:
    """The other entry types sharing *file_key*: every surface reporting a ceiling reports these."""
    if not isinstance(entry_types, dict):
        return {}
    return {
        name: counts.get(name)
        for name, type_def in entry_types.items()
        if isinstance(type_def, dict) and type_def.get("file") == file_key and name != exclude
    }


def count_ceiling(entry_type: str, counts: dict[str, int], entry_types: dict, budgets: dict) -> int:
    """The largest keep-count *entry_type* may take without busting its file; never 0."""
    type_def = entry_types.get(entry_type) if isinstance(entry_types, dict) else None
    if not isinstance(type_def, dict):
        return UNBOUNDED_CEILING

    shape = type_def.get("fields")
    per_entry = worst_entry_chars(shape if isinstance(shape, dict) else {})
    if per_entry <= 0:
        return UNBOUNDED_CEILING

    file_key = type_def.get("file")
    if not isinstance(file_key, str):
        return UNBOUNDED_CEILING

    spec = budgets.get(file_key) if isinstance(budgets, dict) else None
    budget = spec.get("max_chars") if isinstance(spec, dict) else None
    if not isinstance(budget, int) or isinstance(budget, bool):
        return UNBOUNDED_CEILING

    fixed = worst_file_chars(file_key, co_tenants(file_key, counts, entry_types, exclude=entry_type), entry_types)
    return max(1, (budget - fixed) // per_entry)
