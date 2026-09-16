# =================== AIPass ====================
# Name: entry_limits.py
# Description: Entry limits config reader, validator, and diff helper for memory files
# Version: 1.11.0
# Created: 2026-06-13
# Modified: 2026-09-15
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

JUDGED BY WHAT IT AUTHORS, NOT BY WHAT IT CARRIES (2026-08-30)
-------------------------------------------------------------
An entry byte-identical to one already on disk was not written by this write,
and a write cannot be refused for text it did not author.

That clause was narrowed to ``todos`` on 2026-08-27 on the reasoning that the
trinity push had cured drift fleet-wide, so "unchanged and over cap passes"
now hid new drift rather than protecting old.  Three hours of identical
rollover errors proved both halves wrong about the world:

  * Drift RECURS.  @ai_mail carried three over-cap key_learnings the same
    evening the deadlock was reported; @seedgo carried one 343-char summary.
  * This gate is structurally BLIND to how drift arrives.  @hooks' edit_gate
    says so in its own refusal text: caps are measured on the Edit/Write lane
    only.  A write made from the shell reaches their handler (the project
    fence runs there) but never reaches the cap check, and @baud drifted to
    2529/300 for a week through that gap.  An entry the gate never MEASURED
    cannot be caught by refusing the NEXT write.

So the narrowing put the detection job on the one component that cannot see
the drift arrive, and charged rollover for it: the extractor removed a tail,
wrote the document back, and was refused whole for an entry in the head it is
not allowed to touch.  The archiver loses that deadlock every time — the file
cannot get smaller because it is too big.

Detection belongs to the lane that READS DISK: ``drone @memory lint`` scans
every branch's entries on demand, read-only, and owes nothing to write order.

What the narrowing was RIGHT about is the silence.  The old clause skipped a
carried over-cap entry without a word.  It is now reported instead: the same
diff yields two labels, and each consumer sets its own policy from one
measurement.

  ``classify_entries()`` → both halves from ONE traversal:
      ``["authored"]`` — what this write wrote.   Refuse these.
      ``["carried"]``  — what it carries from disk. Report these.
      ``["near"]``     — authored and CLOSE to the cap. Report these too.

THE NEAR-CAP LINE (1.7.0, 2026-08-31), asked for by @ai_mail with the best
argument available: they wrote over the cap FOUR HOURS after being burned by it,
knowing the number, with it in front of them.  Their words, and the reason this
is not a knowledge problem: "nothing in the act of writing shows you the limit —
the only instrument is downstream."  A refusal teaches you at the moment it is
too late to matter; a near-cap line arrives while there is still room to act.

Only AUTHORED entries are reported near.  A carried near-cap entry is not this
write's doing, and warning about it on every write is how a channel becomes
noise nobody reads — the same discriminator that decides refusals, applied to
the softer signal for the same reason.

  ``changed_entries()`` is the authored half alone, kept because @hooks'
  edit_gate calls it by that name — the published contract, unchanged in
  shape.

The labels PARTITION the over-cap set; no entry wears both.  Touch an entry
and you own it — the exemption covers byte-identical text only, so editing a
fat entry into a slightly less fat one is authorship and is refused.

THE CLOSED SHAPE (1.11.0, FPLAN-0593 / DPLAN-0347)
--------------------------------------------------
One field capped per entry type is what let @devpulse carry a 917-char
``status`` past every gate while the fleet median is 9.  A cap on ONE field
does not bound an entry; it bounds a field, and the entry grows through the
fields nobody measured — S464 again, on the branch that had already taken the
diet.  Measured 2026-09-15 across 22 branches, 803 entries: ``status`` max 917
/ p95 12, ``key`` max 83 / p95 65, ``tags`` max 9 items and 100 joined chars,
``priority`` max 6, ``date`` max 10 everywhere.

So ``entry_types.<type>.fields`` in memory.config.json is now the CLOSED
shape: every field an entry may carry, its type, whether it is required, and
its cap.  Nothing else may appear.  The boardroom refused a per-entry TOTAL
for the same reason (thread 16): a total lets one field eat the entry.

The canonical text field keeps its own top-level ``field`` / ``max_chars``
keys untouched — @seedgo's ``trinity_groups`` and the state-tab renderer read
them, and that mirror only retires in Phase 2.  ``load_entry_limits``
reconciles the two so they can never disagree at runtime: the top-level
``max_chars`` wins, because it is the number the agent is shown in its own
``*_meta`` line.

Two new reasons, in the SAME shape as today's over-cap violation so @hooks'
``%d`` formatting keeps working:

  ``unknown_field``  — a field outside the closed shape.  ``field`` names it.
  ``field_over_cap`` — a non-canonical field over its cap.  ``field`` names
                       it, ``units`` is ``"chars"`` or ``"items"``.

A missing REQUIRED field and a wrongly-typed one reuse the existing
``missing_field`` / ``unmeasurable`` reasons rather than minting more: the
consumer already renders them, and the agent's action is identical.

The canonical field is checked ONLY by the original path and the non-canonical
fields ONLY by the new one, so no entry is reported twice for one defect.

CARRIED, AT FIELD RESOLUTION.  The authored-not-carried rule holds, but its
identity had to sharpen: the canonical path calls an entry carried when its
TEXT matches disk, and a write that edits only ``status`` leaves the summary
byte-identical.  Judging the new fields by that test would wave through
exactly the edit this shape exists to catch.  For field violations an entry is
carried only when the WHOLE entry dict is present verbatim in *before*.

Usage:
    from aipass.memory.apps.handlers.json.entry_limits import (
        load_entry_limits, check_entry, changed_entries, classify_entries,
        fields_for, load_file_budgets, check_file_budget,
    )

    limits = load_entry_limits("devpulse")
    verdict = check_entry("key_learnings", some_text, limits)
    # => {"ok": True/False, "length": int, "cap": int, "over_by": int, "entry_type": str}

    violations = changed_entries(before_dict, after_dict, limits)
    # => [{"entry_type", "container", "key", "length", "cap", "over_by"}, ...]

    split = classify_entries(before_dict, after_dict, limits)
    # => {"authored": [...], "carried": [...]} — same six-key shape in both
"""

import copy
import json
from typing import Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader
from aipass.memory.apps.handlers.repo_root import module_file

# Resolve paths relative to handler location (same pattern as memory_files.py)
_MEMORY_ROOT = module_file(__file__).parents[3]


# How close to the cap earns a line. 0.9 puts a 200-char cap's warning at 180,
# which is roughly one more sentence of headroom. A ratio rather than a fixed
# margin so it scales with caps that differ by an order of magnitude across
# entry types.
#
# "NOT SO EARLY THAT MOST WRITES TRIP IT" IS WHAT I FIRST WROTE HERE, AND IT IS
# FALSE — measured 2026-08-31 across all 18 branches' .trinity files, 735
# entries, at @ai_mail's request rather than on my own initiative. They saw it
# fire on 13 of their own 15 key_learnings and asked for the fleet number
# before accepting the threshold, which is the right order.
#
#   entry_type      n    fires    median length/cap
#   sessions       294   65.0%          0.94
#   key_learnings  258   60.5%          0.92
#   todos           74   48.6%          0.90
#   observations   109   35.8%          0.87
#   TOTAL          735   57.4%
#
# And @ai_mail is not the outlier they assumed: at 46.4% they sit BELOW the
# fleet's 57.4%, twelfth of eighteen. The band is everyone's.
#
# THE THRESHOLD SWEEP HAS NO KNEE, which is the finding rather than the number:
#
#   0.90 -> 57.7% of entries   (19 chars of headroom at a 200 cap)
#   0.95 -> 35.7%              (10 chars)
#   0.97 -> 24.2%              ( 6 chars)
#   0.99 -> 11.6%              ( 2 chars)
#
# Every threshold quiet enough to read as signal leaves too little room to act
# on, which is the one thing this line exists to give. So the distribution is
# not telling us the warning is mistuned — it is telling us the CAP is tight,
# and people write to the target they are given. That is a fleet-policy
# question (whose caps these are is not mine to answer), and it is routed with
# these numbers rather than settled by quietly retuning a constant here.
#
# 0.9 STAYS in the meantime, on measured value rather than taste: it has caught
# @ai_mail three times and this branch four times in the two days it has
# existed, and it is one line per authored entry, not per write.
NEAR_CAP_RATIO = 0.9


# Derived from the cap, never stored beside it: a second number per entry type
# would go stale the first time a per_branch override moved only the cap.
# Integer percent so the floor is exact (300/200/150 -> 240/160/120).
DRAFT_PERCENT = 80


# The closed shape's home on an entry type definition, and the two reasons it
# publishes. Named constants because @hooks matches on the strings: a typo in a
# refusal reason is a refusal nobody renders.
FIELDS_KEY = "fields"
REASON_UNKNOWN_FIELD = "unknown_field"
REASON_FIELD_OVER_CAP = "field_over_cap"
REASON_FILE_OVER_BUDGET = "file_over_budget"

# Type names as the config spells them, matching trinity_push's contract.
_TYPE_INT = "int"
_TYPE_STR = "str"
_TYPE_STR_LIST = "list[str]"


def draft_target(max_chars: int) -> int:
    """Return the length to draft an entry to, for a cap of *max_chars*.

    Args:
        max_chars: The enforced character cap for the entry type.

    Returns:
        ``DRAFT_PERCENT`` of the cap, floored. Always below a positive cap.
    """
    return max_chars * DRAFT_PERCENT // 100


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
        resolved = _deep_merge_entry_types(base_types, branch_overrides)
    else:
        resolved = copy.deepcopy(base_types)
    for type_name, type_def in resolved.items():
        _reconcile_canonical_cap(type_name, type_def)
    return resolved


def _reconcile_canonical_cap(type_name: str, type_def: dict[str, Any]) -> None:
    """Make the canonical field's cap one number, whichever copy was edited.

    ``max_chars`` sits twice for the canonical field: at the top of the type
    definition, where @seedgo and the tab renderer read it, and inside
    ``fields``, where the closed shape lists it beside every other field.  The
    duplicate is transitional (Phase 2 retires the top-level mirror), and until
    then the two must not be able to disagree — a per_branch override that
    moved only one of them would measure against one number and print the
    other into the agent's memory file as an instruction.

    The top-level key wins because it is the number the agent is SHOWN.

    Mutates *type_def* in place; it is already a deep copy.
    """
    fields = type_def.get(FIELDS_KEY)
    field = type_def.get("field")
    cap = type_def.get("max_chars")
    if not isinstance(fields, dict) or not isinstance(field, str):
        return
    spec = fields.get(field)
    if not isinstance(spec, dict) or not isinstance(cap, int) or isinstance(cap, bool):
        return
    if spec.get("max_chars") != cap:
        logger.warning(
            f"[entry_limits] {type_name}: fields['{field}'].max_chars is {spec.get('max_chars')!r} "
            f"but max_chars is {cap} — using {cap}, the number the meta line prints"
        )
        spec["max_chars"] = cap


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

    # The near-cap threshold is published as a CHARACTER COUNT rather than left
    # for the caller to recompute from a ratio, for the same reason `over_by` is:
    # a second implementation of the same arithmetic is a second chance for the
    # warning and the refusal to disagree about one entry.
    #
    # `near_cap_ratio` on the type definition wins over the module default when
    # it is present. @ai_mail's argument, and it is the right shape: one ratio
    # across four containers whose median fill differs by seven points is one
    # number doing four jobs. The knob now lives where `max_chars` lives, so
    # whoever owns the caps owns this too — which is not me.
    ratio = type_def.get("near_cap_ratio", NEAR_CAP_RATIO)
    if not isinstance(ratio, int | float) or not 0 < ratio <= 1:
        logger.warning(
            f"[entry_limits] Ignoring near_cap_ratio {ratio!r} for '{entry_type}' — "
            f"expected a number in (0, 1]; using {NEAR_CAP_RATIO}"
        )
        ratio = NEAR_CAP_RATIO

    return {
        "ok": length <= cap,
        "length": length,
        "cap": cap,
        "over_by": over_by,
        "entry_type": entry_type,
        "near_at": cap * ratio,
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


def is_near_cap(verdict: dict[str, Any]) -> bool:
    """True when a PASSING verdict is close enough to its cap to be worth a word.

    Deliberately not a second measurement: it reads the numbers
    :func:`check_entry` already produced, so the warning and the refusal can
    never disagree about a length.

    A cap of 0 means "no cap known for this type", and there is nothing to be
    near. Returning True there would put a line on every entry of every type
    nobody has configured.

    Args:
        verdict: A verdict dict from :func:`check_entry`.

    Returns:
        True when the entry is within cap but at or above the ``near_at``
        threshold :func:`check_entry` published for it — which is
        :data:`NEAR_CAP_RATIO` of the cap unless the entry type overrides it
        with its own ``near_cap_ratio``.
    """
    cap = verdict.get("cap", 0)
    if not verdict.get("ok") or cap <= 0:
        return False
    # A verdict from before `near_at` existed still answers correctly rather
    # than reading a missing key as "never near".
    near_at = verdict.get("near_at", cap * NEAR_CAP_RATIO)
    return verdict["length"] >= near_at


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


# ---------------------------------------------------------------------------
# The closed field shape (FPLAN-0593)
# ---------------------------------------------------------------------------


def fields_for(entry_type: str, limits: dict[str, Any]) -> dict[str, Any]:
    """Return the closed field shape for *entry_type*.

    THE ACCESSOR @hooks CALLS.  ``load_entry_limits`` already carries the map
    inside each entry type; this names it once so no consumer has to know that
    ``fields`` is the key.

    Args:
        entry_type: Name of the entry type (e.g. ``"sessions"``).
        limits: The dict returned by :func:`load_entry_limits`.

    Returns:
        ``{field_name: {"type", "required", "max_chars"?, "max_items"?}}``.
        An EMPTY dict when the config publishes no shape for this type — the
        field checks then do nothing, which is the fail-open an unconfigured
        entry type deserves.  The character cap on the canonical field is
        unaffected either way.
    """
    type_def = limits.get("entry_types", {}).get(entry_type)
    if not isinstance(type_def, dict):
        return {}
    fields = type_def.get(FIELDS_KEY)
    return fields if isinstance(fields, dict) else {}


def _type_matches(value: Any, spec: Any) -> bool:
    """Whether *value* matches the config's type name for a field.

    An unrecognised type name answers True: the shape is data an operator
    edits, and refusing every entry because a type name was misspelt turns a
    config typo into a fleet-wide write freeze.  The misspelling is logged by
    the caller instead.
    """
    if spec == _TYPE_INT:
        return isinstance(value, int) and not isinstance(value, bool)
    if spec == _TYPE_STR:
        return isinstance(value, str)
    if spec == _TYPE_STR_LIST:
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    return True


def _field_violation(
    type_name: str,
    container: str,
    key: str,
    field: str,
    reason: str,
    length: int,
    cap: int,
    units: str = "chars",
) -> dict[str, Any]:
    """Build one field-level violation in the published six-key shape.

    ``length``/``cap``/``over_by`` stay ints on every path — @hooks formats
    them with ``%d``, so a reason that carried None there would crash the
    renderer rather than refuse the write.
    """
    return {
        "entry_type": type_name,
        "container": container,
        "key": key,
        "length": length,
        "cap": cap,
        "over_by": max(0, length - cap) if cap else 0,
        "reason": reason,
        "field": field,
        "units": units,
    }


def _check_list_field(
    type_name: str,
    container: str,
    key: str,
    field: str,
    value: list[Any],
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    """Measure a ``list[str]`` field both ways: how many items, how much text.

    Two caps because they fail differently. ``max_items`` is what stops a tag
    list becoming a log; ``max_chars`` on the JOINED text is what stops ten
    tags each carrying a sentence. A list can bust either alone.
    """
    hits: list[dict[str, Any]] = []
    max_items = spec.get("max_items")
    if isinstance(max_items, int) and not isinstance(max_items, bool) and len(value) > max_items:
        hits.append(
            _field_violation(
                type_name, container, key, field, REASON_FIELD_OVER_CAP, len(value), max_items, units="items"
            )
        )
    max_chars = spec.get("max_chars")
    joined = len("".join(value))
    if isinstance(max_chars, int) and not isinstance(max_chars, bool) and joined > max_chars:
        hits.append(_field_violation(type_name, container, key, field, REASON_FIELD_OVER_CAP, joined, max_chars))
    return hits


def check_fields(
    type_name: str,
    container: str,
    key: str,
    entry: Any,
    limits: dict[str, Any],
) -> list[dict[str, Any]]:
    """Measure every NON-canonical field of *entry* against the closed shape.

    The canonical text field is deliberately skipped — :func:`check_entry` owns
    it, including its cap, its missing-field case and its unmeasurable case.
    Checking it here too would report one defect twice in one refusal.

    Args:
        type_name: Entry type name (e.g. ``"sessions"``).
        container: Container key in the file dict.
        key: Dict key or list index, as a string.
        entry: The entry as it sits in the file.
        limits: The dict returned by :func:`load_entry_limits`.

    Returns:
        Violation dicts, empty when the entry matches the shape or the type
        publishes no shape.  A non-dict entry returns nothing: the canonical
        path already refuses it, and "not an object" is one defect.
    """
    fields = fields_for(type_name, limits)
    if not fields or not isinstance(entry, dict):
        return []

    canonical = limits.get("entry_types", {}).get(type_name, {}).get("field")
    hits: list[dict[str, Any]] = []

    for field, spec in fields.items():
        if field == canonical or not isinstance(spec, dict):
            continue
        if field not in entry:
            if spec.get("required"):
                hits.append(_field_violation(type_name, container, key, field, "missing_field", 0, 0))
                hits[-1]["found_type"] = "missing"
            continue
        value = entry[field]
        if not _type_matches(value, spec.get("type")):
            hit = _field_violation(type_name, container, key, field, "unmeasurable", 0, 0)
            hit["found_type"] = type(value).__name__
            hits.append(hit)
            continue
        if isinstance(value, str):
            cap = spec.get("max_chars")
            if isinstance(cap, int) and not isinstance(cap, bool) and len(value) > cap:
                hits.append(_field_violation(type_name, container, key, field, REASON_FIELD_OVER_CAP, len(value), cap))
        elif isinstance(value, list):
            hits.extend(_check_list_field(type_name, container, key, field, value, spec))

    for field in entry:
        if field not in fields:
            length = len(entry[field]) if isinstance(entry[field], str) else 0
            hits.append(_field_violation(type_name, container, key, field, REASON_UNKNOWN_FIELD, length, 0))

    return hits


def _check_dict_container(
    type_name: str,
    container: str,
    field: str,
    before_container: Any,
    after_container: Any,
    limits: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a dict-shaped container's over-cap entries into authored / carried.

    Args:
        type_name: Entry type name (e.g. ``"key_learnings"``).
        container: Container key in the file dict.
        field: Field to extract text from dict-valued entries.
        before_container: The container value from the on-disk file.
        after_container: The container value from the proposed file.
        limits: The dict returned by :func:`load_entry_limits`.

    Returns:
        ``(authored, carried, near)``. An entry byte-identical to the one under
        the same key on disk is CARRIED — this write did not write it.
        Everything else over cap is AUTHORED. ``near`` holds the authored
        entries that PASS but sit close to the cap.
    """
    if not isinstance(after_container, dict):
        return [], [], []
    before_dict = before_container if isinstance(before_container, dict) else {}
    authored: list[dict[str, Any]] = []
    carried: list[dict[str, Any]] = []
    near: list[dict[str, Any]] = []

    for key, after_value in after_container.items():
        after_text = _extract_text(after_value, field)
        verdict = check_entry(type_name, after_text, limits)
        on_disk = _is_unchanged(after_text, after_value, key in before_dict, before_dict.get(key), field)
        # Field identity is the WHOLE entry, never the canonical text alone —
        # see the module docstring: editing only `status` leaves the summary
        # byte-identical, and that is the write this shape exists to catch.
        exact_on_disk = key in before_dict and before_dict[key] == after_value
        field_hits = check_fields(type_name, container, str(key), after_value, limits)
        (carried if exact_on_disk else authored).extend(field_hits)
        if verdict["ok"]:
            if is_near_cap(verdict) and not on_disk:
                near.append(_violation(type_name, container, str(key), verdict))
            continue
        hit = _violation(type_name, container, str(key), verdict, _found_type(after_value, field), field)
        (carried if on_disk else authored).append(hit)
    return authored, carried, near


def _check_list_container(
    type_name: str,
    container: str,
    field: str,
    before_container: Any,
    after_container: Any,
    limits: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a list-shaped container's over-cap entries into authored / carried.

    Identity is the TEXT, never the index. Rollover removes the tail and every
    surviving entry shifts position — matching on index would call the whole
    file newly authored on exactly the write that authored nothing.

    Args:
        type_name: Entry type name (e.g. ``"sessions"``).
        container: Container key in the file dict.
        field: Field to extract text from list-item dicts.
        before_container: The container value from the on-disk file.
        after_container: The container value from the proposed file.
        limits: The dict returned by :func:`load_entry_limits`.

    Returns:
        ``(authored, carried, near)``. See :func:`_check_dict_container`.
    """
    if not isinstance(after_container, list):
        return [], [], []
    before_list = before_container if isinstance(before_container, list) else []
    before_texts = {t for t in (_extract_text(item, field) for item in before_list) if t is not None}
    # Unmeasurable entries are identified by their RAW value, never by the
    # sentinel. Were they all to collapse to one None, a branch carrying a
    # single legacy list-note could add ten more and every one would read as
    # "already on disk" — the fix would open the hole it came to close.
    before_unmeasurable = [item for item in before_list if _extract_text(item, field) is None]
    authored: list[dict[str, Any]] = []
    carried: list[dict[str, Any]] = []
    near: list[dict[str, Any]] = []

    for idx, after_item in enumerate(after_container):
        after_text = _extract_text(after_item, field)
        verdict = check_entry(type_name, after_text, limits)
        if after_text is None:
            on_disk = after_item in before_unmeasurable
        else:
            on_disk = after_text in before_texts
        # See _check_dict_container: the whole entry, not just its text.
        exact_on_disk = after_item in before_list
        field_hits = check_fields(type_name, container, str(idx), after_item, limits)
        (carried if exact_on_disk else authored).extend(field_hits)
        if verdict["ok"]:
            if is_near_cap(verdict) and not on_disk:
                near.append(_violation(type_name, container, str(idx), verdict))
            continue
        hit = _violation(type_name, container, str(idx), verdict, _found_type(after_item, field), field)
        (carried if on_disk else authored).append(hit)
    return authored, carried, near


def classify_entries(
    before: dict[str, Any],
    after: dict[str, Any],
    limits: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Split every over-cap entry in *after* into what this write authored and what it carries.

    The ONE traversal. :func:`changed_entries` and :func:`carried_entries` are
    selectors over this result, so the two labels cannot drift apart and no
    entry can wear both — a caller wanting both (the write gate does: refuse
    one, report the other) should call this once rather than measure twice.

    This is a **pure function** — no I/O, no file reads, no side effects.

    Args:
        before: Parsed .trinity file dict (current on-disk content).
        after:  Parsed .trinity file dict (proposed new content).
        limits: The dict returned by :func:`load_entry_limits`.

    Returns:
        ``{"authored": [...], "carried": [...], "near": [...]}`` — dicts in the
        published six-key shape.
    """
    entry_types = limits.get("entry_types", {})
    authored: list[dict[str, Any]] = []
    carried: list[dict[str, Any]] = []
    near: list[dict[str, Any]] = []

    for type_name, type_def in entry_types.items():
        container = type_def.get("container", "")
        kind = type_def.get("kind", "dict")
        field = type_def.get("field", "value")

        after_container = after.get(container)
        if after_container is None:
            continue

        before_container = before.get(container)

        if kind == "dict":
            checker = _check_dict_container
        elif kind == "list":
            checker = _check_list_container
        else:
            continue

        type_authored, type_carried, type_near = checker(
            type_name, container, field, before_container, after_container, limits
        )
        authored.extend(type_authored)
        carried.extend(type_carried)
        near.extend(type_near)

    return {"authored": authored, "carried": carried, "near": near}


def changed_entries(
    before: dict[str, Any],
    after: dict[str, Any],
    limits: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return over-limit entries that are NEW or CHANGED between *before* and *after*.

    This is what the write AUTHORED, and the only thing a write may be refused
    for. An entry byte-identical to one already on disk is not reported here —
    it is ``classify_entries(...)["carried"]`` — because refusing a write for text
    it did not write deadlocks the archiver: rollover's whole job is handing
    back a SMALLER document, and it may not shrink an entry it is only moving
    past. See the module docstring for the three hours of identical errors that
    settled it.

    This is a **pure function** — no I/O, no file reads, no side effects.

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

        Empty list when everything is within limits or already on disk.
    """
    return classify_entries(before, after, limits)["authored"]


# ---------------------------------------------------------------------------
# Phase 4: whole-file budgets (FPLAN-0593 — the passport row)
# ---------------------------------------------------------------------------


def load_file_budgets() -> dict[str, Any]:
    """Return the whole-file ceilings for the .trinity files.

    A DELEGATION, not a second reader.  config_loader owns config reads and
    publishes the same three numbers through ``get_file_budgets()``; this name
    exists because the gate and @seedgo reach for budgets where they already
    reach for caps.  Two readers of one key is the drift ``load()`` was written
    to end, so there is only one.

    Returns:
        ``{file_name: {"max_chars": int, "max_string_chars": int?}}`` —
        ``local.json`` 25,000, ``observations.json`` 15,000, ``passport.json``
        6,000 file / 600 per string.
    """
    return config_loader.get_file_budgets()


def _walk_strings(value: Any, path: str = "") -> list[tuple[str, str]]:
    """Every string in a parsed JSON document, with its dotted path."""
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(_walk_strings(child, f"{path}.{key}" if path else str(key)))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            found.extend(_walk_strings(child, f"{path}[{idx}]"))
    elif isinstance(value, str):
        found.append((path, value))
    return found


def check_file_budget(
    file_name: str,
    text: str,
    budgets: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Measure a whole .trinity file against its budget — SIZE ONLY.

    This is the passport row.  @spawn owns passport.json's schema, so there is
    no closed field shape for it and this function never judges one: it asks
    only how big the file is and whether any single string in it is oversized.
    The two carried today are ``aipass`` ``identity.purpose`` at 869 chars and
    ``devpulse`` ``identity.class_extension`` at 674, against a 600 cap and a
    fleet median passport of 1,797 chars.

    Pure but for the config read when *budgets* is omitted.

    Args:
        file_name: The file's name, e.g. ``"passport.json"``.
        text: The proposed file content, as it would be written.
        budgets: An already-loaded budget map; loaded when None.

    Returns:
        Violation dicts in the published six-key shape.  ``file_over_budget``
        names the whole file; ``field_over_cap`` names one string by its dotted
        path.  Empty list when the file has no configured budget.
    """
    table = budgets if budgets is not None else load_file_budgets()
    spec = table.get(file_name)
    if not isinstance(spec, dict):
        return []

    hits: list[dict[str, Any]] = []
    cap = spec.get("max_chars")
    if isinstance(cap, int) and not isinstance(cap, bool) and len(text) > cap:
        hits.append(_field_violation(file_name, file_name, file_name, "", REASON_FILE_OVER_BUDGET, len(text), cap))

    string_cap = spec.get("max_string_chars")
    if not isinstance(string_cap, int) or isinstance(string_cap, bool):
        return hits

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        # A file that will not parse is not silently compliant. The size check
        # above already ran on the raw text, which is the honest half.
        logger.warning(f"[entry_limits] {file_name}: cannot parse for per-string budget: {exc}")
        return hits

    for path, value in _walk_strings(data):
        if len(value) > string_cap:
            hits.append(
                _field_violation(file_name, file_name, path, path, REASON_FIELD_OVER_CAP, len(value), string_cap)
            )
    return hits
