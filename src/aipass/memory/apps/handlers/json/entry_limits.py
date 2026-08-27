# =================== AIPass ====================
# Name: entry_limits.py
# Description: Entry limits config reader, validator, and diff helper for memory files
# Version: 1.5.0
# Created: 2026-06-13
# Modified: 2026-06-13
# =============================================

"""
Entry Limits Validator & Diff Helper

Delegates config reading to ``config_loader`` and returns the effective
limits for a given branch, with per_branch overrides deep-merged over
the default entry_types.

Provides ``check_entry()`` — a pure validator that checks whether a
single entry text exceeds its character cap.

Provides ``changed_entries()`` — a pure diff helper that compares
before/after file dicts and returns only NEW or CHANGED entries that
exceed their character cap.

THE GRANDFATHER CLAUSE, NARROWED 2026-08-27
-------------------------------------------
"Unchanged and over cap passes untouched" was written for a fleet full of
legacy drift: without it a maintenance write — a rollover, a frame
re-render — would be refused whole because of an entry it was not touching,
and the branch's memories would stop rolling.  The trinity push has since
cured that drift fleet-wide, so for the three ARCHIVABLE containers the
clause now protects nothing real and hides everything new: a fresh over-cap
session written straight to disk reads as "already there" on the next write
and never surfaces.

``todos`` keep the exemption, and only todos.  A non-canonical todo can sit
in a branch indefinitely BY DESIGN — the push is forbidden to archive open
work (1.1.0), so nothing but that branch's own agent can ever cure it.
Refusing every write to such a file would brick its rollover, which is
slow-motion data loss: the debt would be preserved by destroying the lane
that preserves everything else.  The gate and the push share ONE
``RESHAPE_ONLY_SECTIONS`` rather than each restating it, because two lists of
"the containers we may not prune" would disagree within a release.

The exemption covers what is ALREADY ON DISK.  A newly written over-cap todo
is refused like anything else.

The constant lives HERE rather than beside the push's prune lane only because
``trinity_push`` already imports this module: defining it there and importing
it back would close a cycle (entry_limits -> trinity_push -> memory_files ->
entry_limits). The push re-exports it, so both lanes still read one list.

Usage:
    from aipass.memory.apps.handlers.json.entry_limits import (
        load_entry_limits, check_entry, changed_entries,
    )

    limits = load_entry_limits("devpulse")
    verdict = check_entry("key_learnings", some_text, limits)
    # => {"ok": True/False, "length": int, "cap": int, "over_by": int, "entry_type": str}

    violations = changed_entries(before_dict, after_dict, limits)
    # => [{"entry_type", "container", "key", "length", "cap", "over_by"}, ...]
"""

import copy
from pathlib import Path
from typing import Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader

# Resolve paths relative to handler location (same pattern as memory_files.py)
_MEMORY_ROOT = Path(__file__).resolve().parents[3]

# Containers where a non-canonical entry may legitimately persist, because no
# machine is allowed to remove it. Today: todos — open work is never archived,
# so only the branch's own agent can cure a drifted one. See the module
# docstring; ``trinity_push`` re-exports this as its prune-lane exemption.
RESHAPE_ONLY_SECTIONS = ("todos",)


def _deep_merge_entry_types(
    base: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """Deep-merge per_branch overrides into entry_types.

    For each key in *overrides*:
      - If the key exists in *base*, shallow-merge the override dict
        into a copy of the base dict (override wins per field).
      - If the key is new, add it verbatim (new entry type for branch).

    Args:
        base: Default entry_types dict.
        overrides: per_branch[branch] dict (same shape as entry_types).

    Returns:
        Merged entry_types dict. The originals are not mutated.
    """
    merged = copy.deepcopy(base)
    for type_name, type_overrides in overrides.items():
        if type_name in merged:
            merged[type_name].update(type_overrides)
        else:
            merged[type_name] = copy.deepcopy(type_overrides)
    return merged


def resolve_entry_types(section: dict[str, Any], branch: str) -> dict[str, Any]:
    """Return the entry_types a branch is actually held to — the ONE resolver.

    Pure: takes the ``entry_limits`` section already in hand, does no I/O, and
    deep-merges ``per_branch[branch]`` over the defaults.

    It exists because two callers must never disagree. The write gate measures
    against ``load_entry_limits``; the state-tab renderer prints a cap INTO the
    agent's memory file as an instruction. @seedgo's trinity checker found them
    resolving differently — the renderer read ``entry_types`` straight off the
    config and ignored ``per_branch`` — so the first branch to take a char-cap
    override would have been told one number, measured against another, and
    failed the Meta-lines rule forever while the renderer rewrote the line the
    checker kept rejecting. Latent only because that map is empty today.

    Args:
        section: The ``entry_limits`` section from memory.config.json.
        branch: Branch name, any casing.

    Returns:
        A deep copy of the effective ``entry_types`` map.
    """
    base_types = section.get("entry_types", {})
    branch_overrides = section.get("per_branch", {}).get(branch.lower(), {})
    if branch_overrides:
        return _deep_merge_entry_types(base_types, branch_overrides)
    return copy.deepcopy(base_types)


def load_entry_limits(branch: str) -> dict[str, Any]:
    """Load effective entry limits for *branch*.

    Delegates config reading to ``config_loader``, pulls the
    ``entry_limits`` section, then deep-merges any
    ``per_branch[branch]`` overrides on top of the default
    ``entry_types``.

    Args:
        branch: Branch name (e.g. "devpulse", "memory").

    Returns:
        Dict with keys: enabled, enforce, entry_types.
    """
    branch_key = branch.lower()

    cfg = config_loader.load()
    section = cfg.get("entry_limits")
    if not isinstance(section, dict):
        logger.warning("[entry_limits] No valid 'entry_limits' section in config, returning safe defaults")
        json_handler.log_operation(
            "load_entry_limits",
            {"branch": branch_key, "fallback": "missing_section"},
            module_name="entry_limits",
        )
        section = config_loader.DEFAULT_CONFIG["entry_limits"]

    enabled = section.get("enabled", True)
    enforce = section.get("enforce", False)

    effective_types = resolve_entry_types(section, branch_key)

    result: dict[str, Any] = {
        "enabled": enabled,
        "enforce": enforce,
        "entry_types": effective_types,
    }

    json_handler.log_operation(
        "load_entry_limits",
        {"branch": branch_key, "types_count": len(effective_types)},
        module_name="entry_limits",
    )

    return result


# ---------------------------------------------------------------------------
# Phase 2: pure entry validator
# ---------------------------------------------------------------------------


def check_entry(entry_type: str, text: Any, limits: dict[str, Any]) -> dict[str, Any]:
    """Check whether *text* exceeds the character cap for *entry_type*.

    This is a **pure function** — no I/O, no file reads, no side effects
    (except a log line when the payload is unknown or unmeasurable).

    Args:
        entry_type: Name of the entry type (e.g. ``"key_learnings"``).
        text: The entry payload to measure. Typed ``Any`` on purpose — callers
            hand it whatever sits in the file, and deciding that a list or a
            ``None`` cannot be measured is precisely this function's job. A
            ``str``-only signature would push the type check back out to every
            caller, which is how two of them came to skip it.
        limits: The dict returned by :func:`load_entry_limits`.

    Returns:
        Verdict dict::

            {
                "ok": bool,        # True when within cap (length <= cap)
                "length": int,     # len(text) — characters, not bytes
                "cap": int,        # max_chars for this type (0 if unknown)
                "over_by": int,    # max(0, length - cap)
                "entry_type": str, # echo back the entry_type
            }
    """
    entry_types = limits.get("entry_types", {})
    type_def = entry_types.get(entry_type)

    if not isinstance(text, str):
        # A field the gate cannot measure is a VIOLATION, never a pass. The old
        # code called len() on whatever arrived: a list of five fat dicts
        # measured as 5 and cleared a 300-char cap without a word. Silence is
        # what let that drift read as compliance for months.
        cap = type_def.get("max_chars", 0) if isinstance(type_def, dict) else 0
        logger.warning(f"[entry_limits] UNMEASURABLE {entry_type}: expected str, got {type(text).__name__} — refusing")
        return {
            "ok": False,
            "length": 0,
            "cap": cap,
            "over_by": 0,
            "entry_type": entry_type,
            "reason": "unmeasurable",
            "found_type": type(text).__name__,
        }

    length = len(text)

    if type_def is None:
        logger.info(f"[entry_limits] Unknown entry_type '{entry_type}' — no cap applied")
        return {
            "ok": True,
            "length": length,
            "cap": 0,
            "over_by": 0,
            "entry_type": entry_type,
        }

    cap = type_def.get("max_chars", 0)
    over_by = max(0, length - cap)

    return {
        "ok": length <= cap,
        "length": length,
        "cap": cap,
        "over_by": over_by,
        "entry_type": entry_type,
    }


# ---------------------------------------------------------------------------
# Phase 3: changed-entries diff helper (rollover-safe)
# ---------------------------------------------------------------------------


def _extract_text(value: Any, field: str) -> str | None:
    """Extract the text payload from a container entry.

    For dict containers the value may be a plain string or a dict
    with a *field* key (e.g. ``{"value": "some text", ...}``).
    For list containers the entry is always a dict with a *field* key.

    Args:
        value: The entry value (string or dict).
        field: The field name to extract from a dict value.

    Returns:
        The text string, or ``None`` when the payload cannot be measured.

    Note:
        ``None`` and ``""`` are different answers and must stay different.
        ``""`` means *there is no text* — compliant. ``None`` means *the text
        cannot be read* — a violation. Collapsing the second into the first is
        the defect: a ``note`` holding a list of dicts came back as ``""``,
        measured as zero characters, and passed every cap it should have failed.

        A MISSING field is the same species and was fixed a version late.
        1.3.0 refused the wrong-type case and still answered ``""`` when the
        canonical key was simply absent — so a ``key_learning`` carrying its
        text under ``learning`` where the config says ``value`` measured as
        zero characters and cleared a 200-char cap while three branches ran
        2.7x over it. A renamed field is not an absent text; it is a text the
        reader cannot find. Only a field that is present and empty says ``""``.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text = value.get(field)
        return text if isinstance(text, str) else None
    return None


def _is_unchanged(after_text: str | None, after_value: Any, key_known: bool, before_value: Any, field: str) -> bool:
    """True when this entry is byte-for-byte what is already on disk.

    Unchanged entries are skipped even when over cap, so rollover and other
    maintenance writes are never blocked by legacy fat entries. For an
    UNMEASURABLE entry the comparison has to be on the raw value: two
    different malformed notes both extract to ``None`` and would otherwise
    look identical to each other.
    """
    if not key_known:
        return False
    if after_text is None:
        return after_value == before_value
    return after_text == _extract_text(before_value, field)


def _found_type(value: Any, field: str) -> str:
    """Name the type that could not be measured, as it sits in the file.

    Reported from the RAW entry, not from the sentinel: ``check_entry`` is
    handed ``None`` for an unmeasurable payload, so asking it what it found
    answers "NoneType" — true of the sentinel and useless about the file. The
    agent reading the refusal needs to know its note is a *list*.
    """
    if isinstance(value, dict):
        return type(value.get(field)).__name__ if field in value else "missing"
    return type(value).__name__


def _violation(
    type_name: str,
    container: str,
    key: str,
    verdict: dict[str, Any],
    found_type: str = "",
    field: str = "",
) -> dict[str, Any]:
    """Build a violation record from a refusal verdict.

    The six keys are the published contract — @hooks' edit_gate formats
    ``length``/``cap``/``over_by`` with ``%d`` — so an unmeasurable refusal
    still carries ints there and adds its explanation in ``reason`` /
    ``found_type`` beside them rather than in place of them.

    Two refusal species, two reasons, because the consumer renders them
    differently and the agent can only act on one of them: ``missing_field``
    names the key to rename, ``unmeasurable`` names the type that arrived.
    "expected a string, found missing" would be true and useless.
    """
    hit = {
        "entry_type": type_name,
        "container": container,
        "key": key,
        "length": verdict["length"],
        "cap": verdict["cap"],
        "over_by": verdict["over_by"],
    }
    if verdict.get("reason"):
        if found_type == "missing":
            hit["reason"] = "missing_field"
            hit["field"] = field
        else:
            hit["reason"] = verdict["reason"]
        hit["found_type"] = found_type
    return hit


def _check_dict_container(
    type_name: str,
    container: str,
    field: str,
    before_container: Any,
    after_container: Any,
    limits: dict[str, Any],
) -> list[dict[str, Any]]:
    """Check dict-shaped container for new/changed over-limit entries.

    Args:
        type_name: Entry type name (e.g. ``"key_learnings"``).
        container: Container key in the file dict.
        field: Field to extract text from dict-valued entries.
        before_container: The container value from the on-disk file.
        after_container: The container value from the proposed file.
        limits: The dict returned by :func:`load_entry_limits`.

    Returns:
        List of violation dicts for over-cap entries. In a RESHAPE_ONLY
        container, entries already on disk are skipped; everywhere else an
        over-cap entry is a violation whether or not this write created it.
    """
    if not isinstance(after_container, dict):
        return []
    before_dict = before_container if isinstance(before_container, dict) else {}
    hits: list[dict[str, Any]] = []

    exempt = container in RESHAPE_ONLY_SECTIONS
    for key, after_value in after_container.items():
        after_text = _extract_text(after_value, field)
        if exempt and _is_unchanged(after_text, after_value, key in before_dict, before_dict.get(key), field):
            continue  # Already on disk in a container nothing may prune
        verdict = check_entry(type_name, after_text, limits)
        if not verdict["ok"]:
            hits.append(_violation(type_name, container, str(key), verdict, _found_type(after_value, field), field))
    return hits


def _check_list_container(
    type_name: str,
    container: str,
    field: str,
    before_container: Any,
    after_container: Any,
    limits: dict[str, Any],
) -> list[dict[str, Any]]:
    """Check list-shaped container for new/changed over-limit entries.

    Args:
        type_name: Entry type name (e.g. ``"sessions"``).
        container: Container key in the file dict.
        field: Field to extract text from list-item dicts.
        before_container: The container value from the on-disk file.
        after_container: The container value from the proposed file.
        limits: The dict returned by :func:`load_entry_limits`.

    Returns:
        List of violation dicts for over-cap entries. In a RESHAPE_ONLY
        container, entries already on disk are skipped; everywhere else an
        over-cap entry is a violation whether or not this write created it.
    """
    if not isinstance(after_container, list):
        return []
    before_list = before_container if isinstance(before_container, list) else []
    before_texts = {t for t in (_extract_text(item, field) for item in before_list) if t is not None}
    # Unmeasurable entries are identified by their RAW value, never by the
    # sentinel. Were they all to collapse to one None, a branch carrying a
    # single legacy list-note could add ten more and every one would read as
    # "already on disk" — the fix would open the hole it came to close.
    before_unmeasurable = [item for item in before_list if _extract_text(item, field) is None]
    hits: list[dict[str, Any]] = []

    exempt = container in RESHAPE_ONLY_SECTIONS
    for idx, after_item in enumerate(after_container):
        after_text = _extract_text(after_item, field)
        if exempt:
            if after_text is None:
                if after_item in before_unmeasurable:
                    continue  # Already on disk, and nothing may prune it
            elif after_text in before_texts:
                continue  # Already on disk, and nothing may prune it
        verdict = check_entry(type_name, after_text, limits)
        if not verdict["ok"]:
            hits.append(_violation(type_name, container, str(idx), verdict, _found_type(after_item, field), field))
    return hits


def changed_entries(
    before: dict[str, Any],
    after: dict[str, Any],
    limits: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return over-limit entries that are NEW or CHANGED between *before* and *after*.

    This is a **pure function** — no I/O, no file reads, no side effects.

    In a ``RESHAPE_ONLY_SECTIONS`` container (todos) an entry already on disk
    is skipped even when over cap, so a maintenance write is never blocked by
    a debt no machine is allowed to prune. Everywhere else an over-cap entry
    is reported whether or not this write created it — the fleet is canonical,
    so "unchanged" no longer means "legacy", it means "written and not yet
    caught".

    Args:
        before: Parsed .trinity file dict (current on-disk content).
        after:  Parsed .trinity file dict (proposed new content).
        limits: The dict returned by :func:`load_entry_limits`.

    Returns:
        List of violation dicts, each containing::

            {
                "entry_type": str,   # e.g. "key_learnings"
                "container": str,    # e.g. "key_learnings"
                "key": str,          # dict key or list index (as str)
                "length": int,       # len(text)
                "cap": int,          # max_chars
                "over_by": int,      # length - cap
            }

        Empty list when everything is within limits or unchanged.
    """
    entry_types = limits.get("entry_types", {})
    violations: list[dict[str, Any]] = []

    for type_name, type_def in entry_types.items():
        container = type_def.get("container", "")
        kind = type_def.get("kind", "dict")
        field = type_def.get("field", "value")

        after_container = after.get(container)
        if after_container is None:
            continue

        before_container = before.get(container)

        if kind == "dict":
            violations.extend(
                _check_dict_container(type_name, container, field, before_container, after_container, limits)
            )
        elif kind == "list":
            violations.extend(
                _check_list_container(type_name, container, field, before_container, after_container, limits)
            )

    return violations
