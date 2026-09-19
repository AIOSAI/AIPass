# =================== AIPass ====================
# Name: budget.py
# Description: Worst-case size arithmetic for the .trinity file budgets
# Version: 1.0.0
# Created: 2026-09-15
# Modified: 2026-09-15
# =============================================

"""
File Budget Arithmetic

Answers ONE question: how large may a keep-count be before the file it
lives in cannot fit inside its budget?

WHY A CEILING IS PER FILE AND NEEDS ITS CO-TENANTS
--------------------------------------------------
The caps in ``entry_limits`` bound a single ENTRY.  The budgets in
``file_budgets`` bound a whole FILE.  Nothing in between bounded the
number of entries, so a keep-count was free to multiply a legal entry
until the file it sits in was illegal — every entry inside its cap, the
document over budget, and no surface able to say which number was wrong.

The missing arithmetic is per file because that is the unit a budget
names, and it needs co-tenants because a .trinity file is shared:

    local.json        sessions + key_learnings + todos   →  25,000 chars
    observations.json observations                       →  15,000 chars

"The sessions ceiling" is therefore not a property of sessions.  It is
what is LEFT of local.json's 25,000 once key_learnings and todos have
taken their configured share and the document's own structure has taken
its allowance.  Raise key_learnings and the sessions ceiling drops —
which is why :func:`count_ceiling` takes the whole count map and not
just the type being asked about.

PURE ON PURPOSE — IMPORTS NOTHING FROM config_loader OR entry_limits
--------------------------------------------------------------------
``config_loader`` clamps on load and must call this module while it is
resolving; an import edge back the other way would be a cycle that only
shows up in whichever import order CI happens to take.  So every map
this module works on is HANDED to it — field shapes, entry types,
budgets, counts — and it reads no config and touches no disk.

MEASURED, NOT HAND-SUMMED
-------------------------
The worst case is built as a real entry and serialized exactly the way
memory files are written (``indent=2, ensure_ascii=False``), then
measured.  Hand-summing the punctuation of a JSON object — braces,
quotes, colons, commas, the indentation each line carries — is how a
ceiling ends up wrong by a few percent in the direction nobody checks.
"""

import json
from typing import Any

# The .trinity files are written with a two-space indent, and an entry sits
# inside a top-level container list: the document is depth 0, the list value
# is depth 1, and the entry object itself is depth 2. So every line of an
# entry's own serialization carries four leading spaces beyond what
# json.dumps() of that entry alone produces.
_INDENT = 2
_ENTRY_DEPTH = 2
_ENTRY_INDENT = " " * (_INDENT * _ENTRY_DEPTH)

# The newline that opens an entry's block plus the comma that closes it. The
# LAST entry in a list carries no comma, so counting one for every entry
# over-states a file by one char per container — the safe direction for a
# ceiling, and cheaper than teaching the arithmetic about list position.
_SEPARATOR_CHARS = len(",\n")

# Entry `number` fields are unbounded ints in the shape, so a worst case has
# to assume a width. Three digits is the fleet's ceiling today: the highest
# number on any branch is a session count in the low hundreds, and a branch
# that reached four digits would have rolled over ~900 times. Widening this
# to 4 costs one char per entry, so the assumption is cheap to revisit.
_INT_DIGITS = 3
_WORST_INT = 10**_INT_DIGITS - 1

_TYPE_INT = "int"
_TYPE_STR_LIST = "list[str]"

# Everything in a .trinity file that is NOT an entry: document_metadata with
# its tags and _usage prose, the three *_meta tab lines, the container keys
# and the JSON scaffolding around them.
#
# Measured 2026-09-15 across 22 branches: local.json non-entry structure max
# 3,254 (HOOKS) / median 2,739; observations.json max 2,068 (devpulse) /
# median 1,581. Re-measured the same day across the 18 branches carrying a
# live .trinity in this checkout, the same structure reads 1,629 max / 1,620
# median for local.json and 1,306 max / 1,300 median for observations.json —
# roughly half. The allowance is set ABOVE the larger of the two readings
# because the *_meta lines are rendered prose that grows when a tab gains a
# field, and a ceiling that has to be re-derived every time a banner grows a
# clause is a ceiling nobody will trust.
FILE_STRUCTURE_ALLOWANCE: dict[str, int] = {"local.json": 3500, "observations.json": 2500}

# Extra entries a file must budget for BEYOND its keep-count. The auto-compact
# pass may leave up to `auto_compact_cap` additional sessions on disk before
# rollover reclaims them, and they are as real as the 15 below them: a ceiling
# that ignores them under-counts local.json by three worst-case sessions.
# Mirrors rollover.defaults.local.sessions.auto_compact_cap (3) — a constant
# and not a config read because this module holds no config door.
AUTO_COMPACT_EXTRA: dict[str, int] = {"sessions": 3}

# What :func:`count_ceiling` answers when there is nothing to measure against
# — no budget configured for the file, or no field shape for the entry type.
# Far above rollover's own _MAX_COUNT of 100, so the caller's other bound
# governs and an unconfigured budget never refuses anything.
UNBOUNDED_CEILING = 10_000


def _worst_field_value(spec: Any) -> Any:
    """Build the largest legal value for one field of the closed shape.

    Args:
        spec: One field's entry in the shape — ``{"type", "required",
            "max_chars"?, "max_items"?}``. A non-dict spec is treated as an
            unbounded string, which contributes nothing but its quotes.

    Returns:
        A value of the field's declared type at its declared cap: ints at
        ``_INT_DIGITS`` width, strings at ``max_chars``, and ``list[str]`` at
        ``max_items`` items whose JOINED text is exactly ``max_chars`` —
        the way ``entry_limits._check_list_field`` measures a list, so the
        worst case here is the largest list that validator would pass.
    """
    if not isinstance(spec, dict):
        return ""

    kind = spec.get("type")
    if kind == _TYPE_INT:
        return _WORST_INT

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
    """The largest an entry of this shape can legally be, as written to disk.

    Builds a synthetic entry with every field at its cap and MEASURES the
    serialization rather than hand-summing it. Optional fields are included:
    an entry that carries them is legal, so the worst case carries them.

    Args:
        fields: The closed field shape for one entry type —
            ``{field_name: {"type", "required", "max_chars"?, "max_items"?}}``.

    Returns:
        Chars this entry costs its container: its own ``indent=2`` block,
        re-indented to the depth an entry sits at inside a .trinity container
        list, plus the newline and comma that separate it from its neighbour.
        ``0`` when the shape is empty or not a dict — an entry type the config
        publishes no shape for is not measurable, and must not be guessed at.
    """
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
    """The largest *file_key* can legally get at these keep-counts.

    Every entry type whose ``file`` is *file_key* contributes its count of
    worst-case entries, plus any :data:`AUTO_COMPACT_EXTRA` it carries, plus
    the file's :data:`FILE_STRUCTURE_ALLOWANCE`.

    Args:
        file_key: ``"local.json"`` or ``"observations.json"``.
        counts: ``{entry_type: keep_count}``. A missing, negative or
            non-integer count is read as zero entries of that type.
        entry_types: The ``entry_limits.entry_types`` map — each value
            carrying its ``file`` and its ``fields`` shape.

    Returns:
        Worst-case chars for the whole file. A file with no configured
        structure allowance gets none, so it reports only its entries.
    """
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
    """The other entry types sharing *file_key*, with the counts they hold.

    The company a ceiling is computed in.  Named once here because every
    surface that reports a ceiling has to report the co-tenants with it — a
    bare "sessions may keep at most 16" is unanswerable without them.

    Args:
        file_key: ``"local.json"`` or ``"observations.json"``.
        counts: ``{entry_type: keep_count}``.
        entry_types: The ``entry_limits.entry_types`` map.
        exclude: An entry type to leave out — normally the one being measured.

    Returns:
        ``{entry_type: count}`` in the config's own order, co-tenants only.
        Empty when the type has the file to itself.
    """
    if not isinstance(entry_types, dict):
        return {}
    return {
        name: counts.get(name)
        for name, type_def in entry_types.items()
        if isinstance(type_def, dict) and type_def.get("file") == file_key and name != exclude
    }


def count_ceiling(entry_type: str, counts: dict[str, int], entry_types: dict, budgets: dict) -> int:
    """The largest keep-count *entry_type* may take without busting its file.

    Every OTHER entry type in the same file holds its configured count while
    this one grows: the ceiling is what is left of the budget after the file's
    structure allowance, its co-tenants and any auto-compact extras have been
    subtracted, divided by one worst-case entry of *entry_type*.

    Args:
        entry_type: The type being asked about, e.g. ``"sessions"``.
        counts: ``{entry_type: keep_count}`` for every type in the file. The
            entry under test is ignored here — that is the number being solved
            for — but its auto-compact extras are not.
        entry_types: The ``entry_limits.entry_types`` map.
        budgets: The ``entry_limits.file_budgets`` map.

    Returns:
        A whole number >= 1. :data:`UNBOUNDED_CEILING` when nothing can be
        measured — an unknown entry type, a type with no published field
        shape, or a file with no configured budget. Never 0: a budget so
        small that not one entry fits is a config to fix, not a reason to
        report a limit that would roll every entry away on sight.
    """
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
