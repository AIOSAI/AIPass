# =================== AIPass ====================
# Name: entry_limits.py
# Description: Entry limits config reader, validator, and diff helper for memory files
# Version: 1.12.0
# Created: 2026-06-13
# Modified: 2026-10-23
# =============================================

"""
Entry Limits Validator & Diff Helper

Only what a write AUTHORS may be refused; an entry byte-identical to disk is CARRIED and reported,
or rollover deadlocks (it cannot shrink a file it is refused for carrying).
Reference: docs/trinity_standard.md
"""

import copy
import json
from typing import Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader
from aipass.memory.apps.handlers.repo_root import module_file

_MEMORY_ROOT = module_file(__file__).parents[3]


# How close to the cap earns a line: a ratio so it scales across caps an order of magnitude apart.
# The fleet sweep has no knee (0.9 fires on ~57% of entries); retuning is fleet policy, not this constant.
NEAR_CAP_RATIO = 0.9


# The draft target is derived from the cap, never stored beside it (draft_percent() reads the config).


# @hooks matches on these strings: a typo in a refusal reason is a refusal nobody renders.
FIELDS_KEY = "fields"
TOLERANCE_KEY = "tolerance_percent"
REASON_UNKNOWN_FIELD = "unknown_field"
REASON_FIELD_OVER_CAP = "field_over_cap"
REASON_FILE_OVER_BUDGET = "file_over_budget"

# Type names as the config spells them, matching trinity_push's contract.
_TYPE_INT = "int"
_TYPE_STR = "str"
_TYPE_STR_LIST = "list[str]"


def draft_percent() -> int:
    """Return the percent of a cap an agent should draft to — a delegation to config_loader, not a second reader."""
    return config_loader.get_draft_percent()


def draft_target(max_chars: int) -> int:
    """Return the length to draft an entry to for a cap of *max_chars*; floored, below a positive cap."""
    return max_chars * draft_percent() // 100


def tolerance_percent(section: dict[str, Any]) -> int:
    """Return the section's tolerance band in percent; the seed when the key is missing or unusable."""
    raw = section.get(TOLERANCE_KEY)
    if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= 100:
        if raw is not None:
            logger.warning(f"[entry_limits] {TOLERANCE_KEY} is not 0-100 ({raw!r}) — serving the seed")
        return int(config_loader.DEFAULT_CONFIG["entry_limits"][TOLERANCE_KEY])
    return raw


def allowed_chars(cap: int, percent: int) -> int:
    """The longest text the gate accepts for *cap*: the band rounded down to whole characters."""
    return cap * (100 + percent) // 100


def _deep_merge_entry_types(
    base: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """Deep-merge per_branch overrides into entry_types (override wins per field); originals untouched."""
    merged = copy.deepcopy(base)
    for type_name, type_overrides in overrides.items():
        if type_name in merged:
            merged[type_name].update(type_overrides)
        else:
            merged[type_name] = copy.deepcopy(type_overrides)
    return merged


def resolve_entry_types(section: dict[str, Any], branch: str) -> dict[str, Any]:
    """Return the entry_types a branch is actually held to — the ONE resolver.

    Pure. The write gate and the state-tab renderer both resolve here, so the cap measured is the cap printed.
    """
    base_types = section.get("entry_types", {})
    branch_overrides = section.get("per_branch", {}).get(branch.lower(), {})
    if branch_overrides:
        resolved = _deep_merge_entry_types(base_types, branch_overrides)
    else:
        resolved = copy.deepcopy(base_types)
    percent = tolerance_percent(section)
    for type_name, type_def in resolved.items():
        _reconcile_canonical_cap(type_name, type_def)
        type_def[TOLERANCE_KEY] = percent
    return resolved


def _reconcile_canonical_cap(type_name: str, type_def: dict[str, Any]) -> None:
    """Make the canonical field's cap one number, whichever copy was edited.

    The top-level ``max_chars`` wins: it is the number the agent is SHOWN. Mutates *type_def* in place.
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
    """Load effective entry limits for *branch*: ``{enabled, enforce, entry_types}``."""
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


def check_entry(entry_type: str, text: Any, limits: dict[str, Any]) -> dict[str, Any]:
    """Check whether *text* exceeds the character cap for *entry_type*.

    Pure but for a log line. Verdict keys: ok, length, cap, over_by, entry_type, plus near_at or reason.
    """
    entry_types = limits.get("entry_types", {})
    type_def = entry_types.get(entry_type)

    if not isinstance(text, str):
        # A field the gate cannot measure is a VIOLATION, never a pass: len() of a list is its item count.
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

    # near_at is published in chars so the warning and the refusal share one arithmetic.
    ratio = type_def.get("near_cap_ratio", NEAR_CAP_RATIO)
    if not isinstance(ratio, int | float) or not 0 < ratio <= 1:
        logger.warning(
            f"[entry_limits] Ignoring near_cap_ratio {ratio!r} for '{entry_type}' — "
            f"expected a number in (0, 1]; using {NEAR_CAP_RATIO}"
        )
        ratio = NEAR_CAP_RATIO

    return {
        "ok": length <= allowed_chars(cap, type_def.get(TOLERANCE_KEY, 0)),
        "length": length,
        "cap": cap,
        "over_by": over_by,
        "entry_type": entry_type,
        "near_at": cap * ratio,
    }


def _extract_text(value: Any, field: str) -> str | None:
    """Extract the text payload from a container entry, or ``None`` when it cannot be measured.

    ``None`` (wrong type or MISSING field) is a violation; ``""`` (present and empty) is compliant.
    Collapsing the two lets an unreadable entry measure as zero characters.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text = value.get(field)
        return text if isinstance(text, str) else None
    return None


def _is_unchanged(after_text: str | None, after_value: Any, key_known: bool, before_value: Any, field: str) -> bool:
    """True when this entry is byte-for-byte what is already on disk.

    Unmeasurable entries compare raw values: two different malformed notes both extract to ``None``.
    """
    if not key_known:
        return False
    if after_text is None:
        return after_value == before_value
    return after_text == _extract_text(before_value, field)


def _found_type(value: Any, field: str) -> str:
    """Name the unmeasurable type from the RAW entry (the ``None`` sentinel would answer "NoneType")."""
    if isinstance(value, dict):
        return type(value.get(field)).__name__ if field in value else "missing"
    return type(value).__name__


def is_near_cap(verdict: dict[str, Any]) -> bool:
    """True when a PASSING verdict is close enough to its cap to be worth a word.

    Reads :func:`check_entry`'s numbers, never re-measures; a cap of 0 (none known) is never near.
    """
    cap = verdict.get("cap", 0)
    if not verdict.get("ok") or cap <= 0:
        return False
    # A verdict without `near_at` must not read as "never near".
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

    The six keys are the published contract (@hooks formats length/cap/over_by with ``%d``).
    ``missing_field`` names the key to rename; ``unmeasurable`` names the type that arrived.
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


def fields_for(entry_type: str, limits: dict[str, Any]) -> dict[str, Any]:
    """The closed field shape for *entry_type* (the @hooks accessor); empty, so fail-open, when unpublished."""
    type_def = limits.get("entry_types", {}).get(entry_type)
    if not isinstance(type_def, dict):
        return {}
    fields = type_def.get(FIELDS_KEY)
    return fields if isinstance(fields, dict) else {}


def _type_matches(value: Any, spec: Any) -> bool:
    """Whether *value* matches the config's type name for a field.

    An unrecognised type name answers True: a config typo must not become a fleet-wide write freeze.
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
    """One field-level violation; ``length``/``cap``/``over_by`` stay ints because @hooks formats ``%d``."""
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
    percent: int = 0,
) -> list[dict[str, Any]]:
    """Measure a ``list[str]`` field both ways: how many items, how much text.

    ``max_items`` stops a tag list becoming a log; ``max_chars`` on the JOINED text stops long tags.
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
    if isinstance(max_chars, int) and not isinstance(max_chars, bool) and joined > allowed_chars(max_chars, percent):
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

    The canonical field is skipped: :func:`check_entry` owns it, so one defect is never reported twice.
    """
    fields = fields_for(type_name, limits)
    if not fields or not isinstance(entry, dict):
        return []

    type_def = limits.get("entry_types", {}).get(type_name, {})
    canonical = type_def.get("field")
    percent = type_def.get(TOLERANCE_KEY, 0)
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
            if isinstance(cap, int) and not isinstance(cap, bool) and len(value) > allowed_chars(cap, percent):
                hits.append(_field_violation(type_name, container, key, field, REASON_FIELD_OVER_CAP, len(value), cap))
        elif isinstance(value, list):
            hits.extend(_check_list_field(type_name, container, key, field, value, spec, percent))

    for field in entry:
        if field not in fields:
            length = len(entry[field]) if isinstance(entry[field], str) else 0
            hits.append(_field_violation(type_name, container, key, field, REASON_UNKNOWN_FIELD, length, 0))

    return hits


def check_entry_shape(
    type_name: str,
    container: str,
    key: str,
    entry: Any,
    limits: dict[str, Any],
) -> list[dict[str, Any]]:
    """Every violation in ONE entry: the canonical field and the closed shape together.

    For a caller with a whole entry and no diff (the restore lane). Reports only; never repairs.
    """
    type_def = limits.get("entry_types", {}).get(type_name)
    if not isinstance(type_def, dict):
        return []
    if not isinstance(entry, dict):
        hit = _field_violation(type_name, container, key, "", "unmeasurable", 0, 0)
        hit["found_type"] = type(entry).__name__
        return [hit]

    hits = list(check_fields(type_name, container, key, entry, limits))

    canonical = type_def.get("field")
    if not isinstance(canonical, str) or not canonical:
        return hits

    if canonical not in entry:
        missing = _field_violation(type_name, container, key, canonical, "missing_field", 0, 0)
        missing["found_type"] = "missing"
        hits.append(missing)
        return hits

    verdict = check_entry(type_name, entry[canonical], limits)
    if verdict.get("ok"):
        return hits
    if verdict.get("reason") == "unmeasurable":
        hit = _field_violation(type_name, container, key, canonical, "unmeasurable", 0, 0)
        hit["found_type"] = verdict.get("found_type", "unknown")
        hits.append(hit)
        return hits
    # A NAMED field: a caller with no diff is being told which field to cut.
    hits.append(
        _field_violation(
            type_name,
            container,
            key,
            canonical,
            REASON_FIELD_OVER_CAP,
            int(verdict.get("length", 0)),
            int(verdict.get("cap", 0)),
        )
    )
    return hits


def _check_dict_container(
    type_name: str,
    container: str,
    field: str,
    before_container: Any,
    after_container: Any,
    limits: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a dict-shaped container's over-cap entries into ``(authored, carried, near)``.

    An entry byte-identical to the one under the same key on disk is CARRIED.
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
        # Field identity is the WHOLE entry: an edit to only `status` leaves the canonical text identical.
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
    """Split a list-shaped container's over-cap entries into ``(authored, carried, near)``.

    Identity is the TEXT, never the index: rollover removes the tail and every survivor shifts.
    """
    if not isinstance(after_container, list):
        return [], [], []
    before_list = before_container if isinstance(before_container, list) else []
    before_texts = {t for t in (_extract_text(item, field) for item in before_list) if t is not None}
    # Unmeasurable entries match by RAW value: collapsed to one None, a legacy note would carry any new ones.
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

    The ONE traversal, pure: the selectors read it, so no entry wears both labels.
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

    The authored half: the only thing a write may be refused for. @hooks' edit_gate calls it by this name.
    """
    return classify_entries(before, after, limits)["authored"]


def load_file_budgets() -> dict[str, Any]:
    """Return the whole-file ceilings for the .trinity files — a delegation to config_loader."""
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

    @spawn owns passport.json's schema, so no field shape is judged. Empty when the file has no budget.
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
        # Not silently compliant: the raw size check above already ran.
        logger.warning(f"[entry_limits] {file_name}: cannot parse for per-string budget: {exc}")
        return hits

    for path, value in _walk_strings(data):
        if len(value) > string_cap:
            hits.append(
                _field_violation(file_name, file_name, path, path, REASON_FIELD_OVER_CAP, len(value), string_cap)
            )
    return hits
