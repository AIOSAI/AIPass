# =================== AIPass ====================
# Name: entry_limits.py
# Description: Entry limits config reader, validator, and diff helper for memory files
# Version: 1.8.0
# Created: 2026-06-13
# Modified: 2026-08-31
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

Usage:
    from aipass.memory.apps.handlers.json.entry_limits import (
        load_entry_limits, check_entry, changed_entries, classify_entries,
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
from typing import Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader
from aipass.memory.apps.handlers.repo_root import module_file

# Resolve paths relative to handler location (same pattern as memory_files.py)
_MEMORY_ROOT = module_file(__file__).parents[3]

# Containers no machine may PRUNE. Today: todos — open work is never archived,
# so only the branch's own agent can cure a drifted one.
#
# This is no longer the cap-exemption discriminator. From 2026-08-30 every
# container is exempt from being refused for text it did not author, so a list
# of "containers we may not prune" answers a question the cap gate stopped
# asking.
#
# ONE consumer remains: ``trinity_push`` re-exports it for its prune lane.
# @hooks read it at call time until 2026-08-30, then deleted their seam the
# same evening — with the rule universal it suppressed nothing on their side,
# and their own reasoning is worth keeping: a rule that has stopped
# suppressing anything is indistinguishable from a load-bearing one. Should
# this fall to zero consumers it should go too, by that same argument.
#
# It lives HERE rather than beside the push only because ``trinity_push``
# already imports this module: defining it there and importing it back would
# close a cycle (entry_limits -> trinity_push -> memory_files -> entry_limits).
RESHAPE_ONLY_SECTIONS = ("todos",)


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
