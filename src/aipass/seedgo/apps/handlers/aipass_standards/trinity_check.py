# =================== AIPass ====================
# Name: trinity_check.py
# Description: Trinity Memory File Standards Checker
# Version: 1.0.0
# Created: 2026-08-25
# Modified: 2026-08-25
# =============================================

"""
Trinity Memory File Standards Checker

Enforces the trinity standard (devpulse dropbox/trinity_pattern.md) on the
three in-scope files of every citizen's ``.trinity/``: ``local.json``,
``observations.json`` and ``.template_version.json``.  ``passport.json``
matters here for EXISTENCE only -- passports and compass are separate systems
with their own rules, so nothing inside a passport is read or judged.

The one law
-----------
A field the checker cannot measure is a VIOLATION, never a silent pass.  This
standard exists because the old gate measured unparseable shapes as zero chars
and passed them.  So: a missing, unreadable or invalid file fails every group
that depends on it, loudly and by name; a field of the wrong type is reported
with the type actually found and is never coerced or ``len()``-ed; an
unreadable ``memory.config.json`` fails the Char caps group instead of falling
back to remembered numbers; unreadable gold templates fail the Meta lines
group instead of falling back to a copied-out prose string.  There is no code
path where something unreadable produces a passing check.

The nine groups and their weights (GROUP_WEIGHTS, sums to 100)
--------------------------------------------------------------
Shape and type weigh heaviest -- they break the machinery that caps, rolls and
archives these files; freshness weighs lightest.  Each group reports its own
0-100 subscore; the standard's score is the weighted mean, rounded.

Per-group subscore rule (proportional where a natural denominator exists,
binary 0/100 otherwise):

* Entry shapes (25) -- proportional over every entry in the four containers.
  A container that is missing, is not a list, or lives in an unreadable file
  counts as one failed unit rather than being skipped.
* Top-level keys (15) -- proportional over 17 fixed sub-rules: eight per file
  (file parses, key set, key order, duplicate keys, document_metadata fields,
  no ``status`` block, document_name, managed_by) plus one cross-file
  managed_by agreement check.  An unreadable file fails all eight of its own.
* Ordering & numbering (12) -- proportional over every entry.
* Char caps (12) -- proportional over every entry; binary 0 when
  memory.config.json cannot be read, because caps are never assumed.
* File set (10) -- proportional over the five canonical names plus one unit
  per stray file or directory found in ``.trinity/``.
* Meta lines & _usage (10) -- proportional over six byte-match units: four
  ``*_meta`` lines and two ``_usage`` strings.  Binary 0 when config or the
  gold templates cannot be read.
* Receipt (8) -- proportional over six units: file parses, template_versions
  shape, template_versions values, and the three timestamp/actor strings.
* Todos hygiene (5) -- proportional over every todo entry.
* Freshness (3) -- proportional over two units, one per file.

Expected fleet state (not a bug)
--------------------------------
Two groups are RED on every branch today, by design of the migration rather
than by defect of the checker:

* Meta lines & _usage -- every live ``*_meta`` line on disk carries the
  machine tab ONLY, with no template prose, and every ``_usage`` carries the
  string @memory's renderer used to hard-code.  @memory's tab_renderer 1.1.0
  now composes tab + template prose (compose_meta) and reads ``_usage`` from
  the gold template (template_usage) -- expected_meta_line() below is verified
  byte-identical to it -- but the fleet's files only change on the next
  refresh pass.  Until that pass runs, every branch fails this group; that is
  the standard measuring reality, not a false positive.
* Receipt -- no branch carries ``.trinity/.template_version.json`` yet; the
  push/spawn/reset machinery that writes it is still to come.

Known contract items deliberately NOT scored here
-------------------------------------------------
* ``observations.json``'s ``guidelines`` block "carries the template text
  verbatim" (contract, Canonical Shape -- observations.json).  Its PRESENCE is
  scored under Top-level keys; its CONTENT is not, because the pinned checker
  contract defines the Meta lines group as the four ``*_meta`` lines plus the
  two ``_usage`` strings and nothing else.  Flagged here so the gap is loud
  rather than silent -- it needs a ruling before it can be scored.
* Extra keys inside ``document_metadata`` other than ``status`` are not
  flagged; the contract names the required fields and deletes ``status``, but
  does not declare the block closed.

Bypass
------
None, deliberately -- see check_branch().
"""

import json
import re
from datetime import date
from functools import partial
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "branch_level"

GROUP_WEIGHTS: dict[str, int] = {
    "Entry shapes": 25,
    "Top-level keys": 15,
    "Ordering & numbering": 12,
    "Char caps": 12,
    "File set": 10,
    "Meta lines & _usage": 10,
    "Receipt": 8,
    "Todos hygiene": 5,
    "Freshness": 3,
}

# -- Names on disk -----------------------------------------------------------

_TRINITY_DIR = ".trinity"
_LOCAL_NAME = "local.json"
_OBSERVATIONS_NAME = "observations.json"
_RECEIPT_NAME = ".template_version.json"

_CANONICAL_FILES = (
    "passport.json",
    _LOCAL_NAME,
    _OBSERVATIONS_NAME,
    "README.md",
    _RECEIPT_NAME,
)

_FILE_NAMES = {"local": _LOCAL_NAME, "observations": _OBSERVATIONS_NAME}

# A versioned backup is a LEGAL resident of .trinity/ (Patrick's File set ruling):
# the house convention renames the current file as a version and leaves it in
# place while the new file is written. The rule is a SHAPE, not a list of the two
# suffixes minted so far -- the next migration mints its own and must pass without
# a code change here. Anchored on ``pre`` because that is what the convention
# means (what the file was BEFORE the migration) and it is what both live
# generations use; the version token itself is free.
#
# Deliberately tight on the token: no dots, so ``local.json.pre_v3_backup.tmp``
# stays a stray. A rule loose enough to admit ``local.json.tmp`` would make
# torn-write staging files invisible inside the fleet's own memory directory.
_VERSION_SUFFIX_RE = re.compile(r"^pre[-_][A-Za-z0-9][A-Za-z0-9_-]*$")

# -- Canonical structure -----------------------------------------------------

_LOCAL_KEY_ORDER = [
    "document_metadata",
    "todos_meta",
    "todos",
    "key_learnings_meta",
    "key_learnings",
    "sessions_meta",
    "sessions",
]

_OBSERVATIONS_KEY_ORDER = [
    "document_metadata",
    "guidelines",
    "observations_meta",
    "observations",
]

_DOC_META_FIELDS = (
    "document_type",
    "document_name",
    "version",
    "schema_version",
    "created",
    "last_updated",
    "managed_by",
    "tags",
    "_usage",
)

_DOC_NAME_SUFFIX = {"local": ".LOCAL", "observations": ".OBSERVATIONS"}

_ALL_SECTIONS = ("todos", "key_learnings", "sessions", "observations")
_LOCAL_SECTIONS = ("todos", "key_learnings", "sessions")
_SECTION_FILE = {
    "todos": "local",
    "key_learnings": "local",
    "sessions": "local",
    "observations": "observations",
}

# Type specs are strings so a violation message can name the expectation in
# the same words the contract uses.
_TYPE_INT = "int"
_TYPE_STR = "str"
_TYPE_STR_LIST = "list[str]"

_ENTRY_RULES: dict[str, dict[str, dict[str, str]]] = {
    "sessions": {
        "required": {
            "number": _TYPE_INT,
            "date": _TYPE_STR,
            "summary": _TYPE_STR,
            "status": _TYPE_STR,
        },
        "optional": {"tags": _TYPE_STR_LIST},
    },
    "key_learnings": {
        "required": {
            "number": _TYPE_INT,
            "date": _TYPE_STR,
            "key": _TYPE_STR,
            "value": _TYPE_STR,
        },
        "optional": {},
    },
    "todos": {
        "required": {
            "number": _TYPE_INT,
            "date": _TYPE_STR,
            "task": _TYPE_STR,
            "priority": _TYPE_STR,
            "status": _TYPE_STR,
        },
        "optional": {},
    },
    "observations": {
        "required": {
            "number": _TYPE_INT,
            "date": _TYPE_STR,
            "note": _TYPE_STR,
            "tags": _TYPE_STR_LIST,
        },
        "optional": {},
    },
}

# -- Rendering (mirrors memory/apps/handlers/tracking/tab_renderer.py) -------

# Which rollover FILE key and leaf key each section resolves through. The
# lookup is per file key, exactly as @memory's config_loader._resolve_limits
# does it: a per_branch entry that carries "local" at all means defaults are
# never consulted for that file. A deep merge here would compose an expected
# meta line the renderer would never write.
_ROLLOVER_KEYS = {
    "sessions": ("local", "sessions"),
    "key_learnings": ("local", "key_learnings"),
    "observations": ("observations", "observations"),
}

# The renderer's OWN fallbacks, reproduced so expected_meta_line() stays a
# total function when a section is absent from config. These are never used
# as caps: the Char caps group refuses to measure without config, and the
# Meta lines group fails the item loud before it reaches this path.
_RENDERER_FALLBACK_MAX_CHARS = 300
_RENDERER_FALLBACK_FIELD = "value"

_PLACEHOLDER_RE = re.compile(r"^\{\{[A-Z0-9_]+\}\} (?P<prose>.+)$", re.DOTALL)
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

_META_SOURCE = {
    "todos": ("local", "todos_meta"),
    "key_learnings": ("local", "key_learnings_meta"),
    "sessions": ("local", "sessions_meta"),
    "observations": ("observations", "observations_meta"),
}

_TEMPLATE_FILES = (
    ("local", "LOCAL.template.json"),
    ("observations", "OBSERVATIONS.template.json"),
)

_RECEIPT_STRING_FIELDS = ("stamped", "stamped_by", "config_rendered")

_MAX_SAMPLE_NUMBERS = 3
_MAX_MESSAGE_GROUPS = 4
_EXPECTED_PREVIEW_CHARS = 90


# =============================================================================
# SMALL TYPE HELPERS
# =============================================================================


def _as_dict(value: object) -> dict:
    """Return *value* when it is a dict, otherwise an empty dict."""
    return value if isinstance(value, dict) else {}


def _is_int(value: object) -> bool:
    """Return True for a real int (bools are not integers here)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _type_ok(value: object, spec: str) -> bool:
    """Return True when *value* satisfies the type *spec*."""
    if spec == _TYPE_INT:
        return _is_int(value)
    if spec == _TYPE_STR:
        return isinstance(value, str)
    if spec == _TYPE_STR_LIST:
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    return False


def _found(container: dict, field: str) -> str:
    """Name the type actually present at *field*, or 'absent'."""
    if field not in container:
        return "absent"
    return type(container[field]).__name__


def _lookup_case_insensitive(mapping: object, key: str) -> object:
    """Return mapping[key] matched case-insensitively, or None."""
    wanted = key.lower()
    for name, value in _as_dict(mapping).items():
        if isinstance(name, str) and name.lower() == wanted:
            return value
    return None


# =============================================================================
# PATHS AND FILE READING
# =============================================================================


def _repo_root() -> Path | None:
    """Walk up from this file to the repo root -- the dir holding src/aipass."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "src" / "aipass").is_dir():
            return parent
    logger.warning("trinity_check: cannot locate repo root from %s", __file__)
    return None


def _memory_dir() -> Path | None:
    """Return the @memory branch directory, or None outside a repo."""
    root = _repo_root()
    if root is None:
        return None
    return root / "src" / "aipass" / "memory"


def _pairs_hook(duplicates: list[str]):
    """Build an object_pairs_hook that records every repeated key it sees."""

    def hook(pairs: list) -> dict:
        """Build the object from *pairs*, appending each repeated key seen."""
        seen: set[str] = set()
        for key, _value in pairs:
            if key in seen:
                duplicates.append(key)
            seen.add(key)
        return dict(pairs)

    return hook


def _fail_read(reason: str) -> dict:
    """Build the failed shape of a _read_json_file result."""
    return {"data": None, "duplicates": [], "error": reason}


def _read_json_file(path: Path) -> dict:
    """Read one JSON object, recording duplicate keys.

    Returns a dict with ``data`` (the parsed object or None), ``duplicates``
    (every key seen more than once at any depth -- json.load keeps only the
    last value, so the raw pairs are the only place a duplicate is visible)
    and ``error`` (a reason string, or None on success).  The reason never
    repeats the file name; callers prefix it themselves.
    """
    if not path.is_file():
        return _fail_read("not found")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("trinity_check: cannot read %s: %s", path, exc)
        return _fail_read(f"unreadable ({exc})")

    duplicates: list[str] = []
    try:
        data = json.loads(raw, object_pairs_hook=_pairs_hook(duplicates))
    except ValueError as exc:
        logger.warning("trinity_check: %s is not valid JSON: %s", path, exc)
        return _fail_read(f"not valid JSON ({exc})")

    if not isinstance(data, dict):
        return _fail_read(f"top level must be an object, found {type(data).__name__}")
    return {"data": data, "duplicates": duplicates, "error": None}


# =============================================================================
# CONFIG AND GOLD TEMPLATES
# =============================================================================


def load_memory_config() -> dict | None:
    """Load @memory's memory.config.json.

    Returns:
        The parsed config dict, or None when the repo root, the file, or its
        JSON cannot be resolved.  None is a hard failure for the Char caps and
        Meta lines groups -- there is no fallback set of numbers.
    """
    memory_dir = _memory_dir()
    if memory_dir is None:
        return None
    path = memory_dir / "memory_json" / "custom_config" / "memory.config.json"
    result = _read_json_file(path)
    if result["error"] is not None:
        logger.warning("trinity_check: memory.config.json %s", result["error"])
        return None
    return result["data"]


def _load_templates() -> dict | None:
    """Load both gold templates keyed 'local' / 'observations', or None."""
    memory_dir = _memory_dir()
    if memory_dir is None:
        return None
    base = memory_dir / "templates"
    loaded: dict[str, dict] = {}
    for key, filename in _TEMPLATE_FILES:
        result = _read_json_file(base / filename)
        if result["error"] is not None:
            logger.warning("trinity_check: gold template %s %s", filename, result["error"])
            return None
        loaded[key] = result["data"]
    return loaded


def _prose_after_placeholder(text: object) -> str | None:
    """Return the prose that follows a ``{{PLACEHOLDER}} `` token, or None."""
    if not isinstance(text, str):
        return None
    match = _PLACEHOLDER_RE.match(text)
    if match is None:
        return None
    return match.group("prose")


def _prose_from_templates(templates: dict | None) -> dict | None:
    """Extract the four sections' template prose, or None if any is malformed."""
    if templates is None:
        return None
    prose: dict[str, str] = {}
    for section, (file_key, meta_key) in _META_SOURCE.items():
        parsed = _prose_after_placeholder(_as_dict(templates.get(file_key)).get(meta_key))
        if parsed is None:
            logger.warning("trinity_check: template %s is not '{{PLACEHOLDER}} <prose>'", meta_key)
            return None
        prose[section] = parsed
    return prose


def _usage_from_templates(templates: dict | None) -> dict | None:
    """Extract each template's document_metadata._usage text, or None."""
    if templates is None:
        return None
    usage: dict[str, str] = {}
    for file_key in _FILE_NAMES:
        text = _as_dict(_as_dict(templates.get(file_key)).get("document_metadata")).get("_usage")
        if not isinstance(text, str):
            logger.warning("trinity_check: %s template has no string _usage", file_key)
            return None
        usage[file_key] = text
    return usage


def _gold_versions_from_templates(templates: dict | None) -> dict | None:
    """Return the gold template_versions values, or None when unreadable.

    GOLD SOURCE, INFERRED -- needs confirming with @memory. The contract's
    example receipt shows {"local": "3.0.0", "observations": "3.0.0"}: two
    equal values. In the templates themselves document_metadata.version
    DIFFERS (LOCAL 2.0.0, OBSERVATIONS 1.0.0) while schema_version is 3.0.0
    in both, so schema_version is the only field that reproduces the
    contract's example. This checker therefore compares against
    schema_version. If @memory rules that the receipt tracks the per-file
    version instead, change this one function.
    """
    if templates is None:
        return None
    versions: dict[str, str] = {}
    for file_key in _FILE_NAMES:
        value = _as_dict(_as_dict(templates.get(file_key)).get("document_metadata")).get("schema_version")
        if not isinstance(value, str):
            logger.warning("trinity_check: %s template has no string schema_version", file_key)
            return None
        versions[file_key] = value
    return versions


def load_template_prose(templates: dict | None = None) -> dict | None:
    """Load the per-section prose that the gold templates own.

    Each ``*_meta`` value in a template is ``"{{PLACEHOLDER}} <prose>"``; the
    prose is everything after the placeholder token and its single following
    space.  The prose text is never carried in this module -- an unreadable
    template returns None and fails the Meta lines group loud.

    Args:
        templates: Already-loaded gold templates, so a caller that also needs
            the receipt's gold versions reads the two files once instead of
            twice.  Omit to load them here.

    Returns:
        ``{"todos": ..., "key_learnings": ..., "sessions": ...,
        "observations": ...}`` or None.
    """
    if templates is None:
        templates = _load_templates()
    return _prose_from_templates(templates)


# =============================================================================
# CONFIG RESOLUTION (caps and keep-counts)
# =============================================================================


def _resolve_entry_limits(config: dict, branch_name: str) -> dict:
    """Merge entry_limits.per_branch[branch] over entry_limits.entry_types."""
    section = _as_dict(config).get("entry_limits")
    base = _as_dict(_as_dict(section).get("entry_types"))
    merged = {name: dict(spec) for name, spec in base.items() if isinstance(spec, dict)}
    overrides = _lookup_case_insensitive(_as_dict(section).get("per_branch"), branch_name)
    for name, spec in _as_dict(overrides).items():
        if isinstance(spec, dict):
            merged[name] = {**merged.get(name, {}), **spec}
    return merged


def _resolve_rollover_count(config: dict, section: str, branch_name: str) -> int | None:
    """Resolve the keep-count the rollover engine really applies, or None."""
    keys = _ROLLOVER_KEYS.get(section)
    if keys is None:
        return None
    file_key, leaf_key = keys
    rollover = _as_dict(_as_dict(config).get("rollover"))
    branch_cfg = _as_dict(_lookup_case_insensitive(rollover.get("per_branch"), branch_name))
    file_limits = _as_dict(branch_cfg.get(file_key))
    if not file_limits:
        file_limits = _as_dict(_as_dict(rollover.get("defaults")).get(file_key))
    count = _as_dict(file_limits.get(leaf_key)).get("count")
    return count if _is_int(count) else None


def expected_meta_line(section: str, branch_name: str, config: dict, template_prose: str) -> str:
    """Compose the ``*_meta`` line the renderer would produce for *section*.

    The result is ``<rendered machine tab> + " " + <template prose>``: the tab
    carries the live numbers from ``memory.config.json``, the sentence after
    it carries the section's meaning from the gold template.  Glyphs are
    byte-identical to @memory's tab_renderer.

    Args:
        section: One of todos, key_learnings, sessions, observations.
        branch_name: Branch directory name; per-branch overrides match it
            case-insensitively.
        config: The parsed memory.config.json.
        template_prose: The prose this section's template owns.

    Returns:
        The expected meta line as one string.
    """
    limits = _resolve_entry_limits(_as_dict(config), branch_name)
    spec = _as_dict(limits.get(section))
    max_chars = spec.get("max_chars", _RENDERER_FALLBACK_MAX_CHARS)
    field = spec.get("field", _RENDERER_FALLBACK_FIELD)

    if section == "todos":
        tab = f"⟦ rollover OFF — operational, never trimmed · cap ~10 entries · task ≤{max_chars} chars ⟧"
        return f"{tab} {template_prose}"

    count = _resolve_rollover_count(_as_dict(config), section, branch_name)
    if count is None:
        tab = f"⟦ rollover ON → no entry limit configured · {field} ≤{max_chars} chars ⟧"
    else:
        tab = f"⟦ rollover ON → oldest archived to @memory · keep {count} · {field} ≤{max_chars} chars ⟧"
    return f"{tab} {template_prose}"


# =============================================================================
# ENTRY SHAPE VALIDATION
# =============================================================================


def _required_field_problems(required: dict, entry: dict) -> list[str]:
    """Report every required field that is absent or of the wrong type."""
    problems: list[str] = []
    for field, spec in required.items():
        if field not in entry:
            problems.append(f"missing required field '{field}'")
        elif not _type_ok(entry[field], spec):
            problems.append(f"{field} must be {spec}, found {type(entry[field]).__name__}")
    return problems


def _optional_field_problems(optional: dict, entry: dict) -> list[str]:
    """Report every optional field that is present but of the wrong type."""
    problems: list[str] = []
    for field, spec in optional.items():
        if field in entry and not _type_ok(entry[field], spec):
            problems.append(f"{field} must be {spec}, found {type(entry[field]).__name__}")
    return problems


def validate_entry_shape(section: str, entry: object) -> list[str]:
    """Validate one entry against its section's canonical shape.

    Required fields must be present WITH their required types, optional
    fields must type-check when present, and any other key is a violation
    named by the key found -- that is how a renamed field (``learning`` for
    key/value, ``session``/``category``/``type`` for ``tags``) becomes
    visible instead of silently measuring as nothing.

    Args:
        section: One of sessions, key_learnings, todos, observations.
        entry: The candidate entry, of any type.

    Returns:
        A list of human-readable violation strings; empty means clean.
    """
    rules = _ENTRY_RULES.get(section)
    if rules is None:
        return [f"unknown section '{section}' -- no canonical shape to measure against"]
    if not isinstance(entry, dict):
        return [f"entry must be an object, found {type(entry).__name__}"]

    required = rules["required"]
    optional = rules["optional"]
    problems = _required_field_problems(required, entry)
    problems.extend(_optional_field_problems(optional, entry))
    allowed = set(required) | set(optional)
    problems.extend(
        f"unexpected field '{key}' (found {type(entry[key]).__name__})" for key in entry if key not in allowed
    )
    return problems


# =============================================================================
# MESSAGE FORMATTING
# =============================================================================


def _entry_label(entry: object, index: int) -> str:
    """Name an entry by its number, falling back to its position."""
    if isinstance(entry, dict) and _is_int(entry.get("number")):
        return str(entry["number"])
    return f"#{index + 1}"


def _format_entry_numbers(labels: list) -> str:
    """Render 'entries 41, 39, 37; +6 more' from a list of entry labels."""
    named = [label for label in labels if label is not None]
    if not named:
        return ""
    shown = ", ".join(str(label) for label in named[:_MAX_SAMPLE_NUMBERS])
    noun = "entry" if len(named) == 1 else "entries"
    extra = len(named) - _MAX_SAMPLE_NUMBERS
    if extra > 0:
        return f"{noun} {shown}; +{extra} more"
    return f"{noun} {shown}"


def _format_records(records: list) -> str:
    """Render (file, rule, entry-label) records as one failure message."""
    grouped: dict[tuple, list] = {}
    for file_label, rule, entry_label in records:
        grouped.setdefault((file_label, rule), []).append(entry_label)

    parts: list[str] = []
    for (file_label, rule), labels in list(grouped.items())[:_MAX_MESSAGE_GROUPS]:
        suffix = _format_entry_numbers(labels)
        parts.append(f"{file_label}: {rule} ({suffix})" if suffix else f"{file_label}: {rule}")
    overflow = len(grouped) - _MAX_MESSAGE_GROUPS
    if overflow > 0:
        parts.append(f"+{overflow} more rule(s)")
    return "; ".join(parts)


def _join_messages(messages: list, failed: int, total: int) -> str:
    """Join item messages, or state the count when none were attached."""
    named = [text for text in messages if text]
    if not named:
        return f"{failed}/{total} checks failed"
    head = "; ".join(named[:_MAX_MESSAGE_GROUPS])
    overflow = len(named) - _MAX_MESSAGE_GROUPS
    if overflow > 0:
        return f"{head}; +{overflow} more"
    return head


# =============================================================================
# CHECK BUILDERS
# =============================================================================


def _score_of(ok: int, total: int) -> int:
    """Proportional subscore that never rounds a failure up to 100."""
    if total <= 0:
        return 100
    if ok >= total:
        return 100
    return min(99, int(ok / total * 100))


def _binary_check(name: str, ok: bool, message: str) -> dict:
    """Build a 0/100 group result."""
    return {"name": name, "passed": ok, "message": message, "score": 100 if ok else 0}


def _items_check(name: str, items: list, clean_message: str) -> dict:
    """Build a proportional group result from (ok, message) item tuples."""
    ok = sum(1 for flag, _message in items if flag)
    total = len(items)
    score = _score_of(ok, total)
    if score == 100:
        return {"name": name, "passed": True, "message": clean_message, "score": 100}
    messages = [message for flag, message in items if not flag]
    return {
        "name": name,
        "passed": False,
        "message": _join_messages(messages, total - ok, total),
        "score": score,
    }


def _records_check(name: str, ok: int, total: int, records: list, clean_message: str) -> dict:
    """Build a proportional group result from per-entry violation records.

    THE ONE LAW applies to the scoring itself: a group holding any violation
    record never scores 100, whatever the entry denominator says. A record
    raised with no measurable entries behind it -- an unreadable section, a
    config carrying no spec for that section -- divides by a zero denominator,
    and scoring that clean would be the exact silent pass this standard exists
    to end. The denominator decides how bad; the records decide whether.
    """
    if not records:
        score = _score_of(ok, total)
        return {"name": name, "passed": score == 100, "message": clean_message, "score": score}
    return {
        "name": name,
        "passed": False,
        "message": _format_records(records),
        "score": min(_score_of(ok, total), 99),
    }


# =============================================================================
# SECTION ACCESS
# =============================================================================


def _section_file(section: str) -> str:
    """Return the file name that owns *section*."""
    return _FILE_NAMES[_SECTION_FILE[section]]


def _section_entries(ctx: dict, section: str):
    """Return (entries, error) for *section*; entries is None on any failure."""
    fileref = ctx[_SECTION_FILE[section]]
    if fileref["error"] is not None:
        return None, f"{fileref['error']} -- '{section}' unmeasurable"
    data = fileref["data"]
    if section not in data:
        return None, f"'{section}' section missing"
    value = data[section]
    if not isinstance(value, list):
        return None, f"'{section}' must be a list, found {type(value).__name__}"
    return value, None


def _entry_scan(ctx: dict, sections: tuple, probe) -> tuple[int, int, list]:
    """Run *probe* over every entry of *sections*; return (ok, total, records).

    A section that cannot be reached at all counts as one failed unit so an
    unreadable file can never shrink the denominator to a passing zero.
    """
    ok = 0
    total = 0
    records: list = []
    for section in sections:
        entries, error = _section_entries(ctx, section)
        if entries is None:
            total += 1
            records.append((_section_file(section), error, None))
            continue
        section_ok, section_records = probe(section, entries)
        ok += section_ok
        total += len(entries)
        records.extend(section_records)
    return ok, total, records


def _run_probe(section: str, entries: list, problem_of) -> tuple[int, list]:
    """Apply a per-entry problem function; return (ok_count, records)."""
    label = _section_file(section)
    ok = 0
    records: list = []
    for index, entry in enumerate(entries):
        problem = problem_of(entry)
        if problem is None:
            ok += 1
        else:
            records.append((label, problem, _entry_label(entry, index)))
    return ok, records


# =============================================================================
# GROUP 1 -- FILE SET
# =============================================================================


def is_versioned_backup(name: str) -> bool:
    """Whether a filename is a legal versioned backup of a canonical file.

    The shape is ``<canonical filename>.pre<sep><token>`` -- for example
    ``local.json.pre_v3_backup`` or ``observations.json.pre-aipl``. Versioning
    a non-canonical name does not launder it into a resident.

    Pure name predicate, no I/O: the caller decides what to do about
    directories, which are never versioned backups whatever they are called.

    Args:
        name: A bare filename, no path separators.

    Returns:
        True when the name is a versioned backup of a canonical file.
    """
    base, _, suffix = name.rpartition(".")
    return base in _CANONICAL_FILES and bool(_VERSION_SUFFIX_RE.match(suffix))


def _stray_names(trinity: Path) -> list[str]:
    """Names in .trinity/ that are neither canonical nor a versioned backup."""
    try:
        found = sorted(trinity.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        logger.warning("trinity_check: cannot list %s: %s", trinity, exc)
        return []
    return [
        item.name + ("/" if item.is_dir() else "")
        for item in found
        if item.name not in _CANONICAL_FILES and not (is_versioned_backup(item.name) and not item.is_dir())
    ]


def _group_file_set(ctx: dict) -> dict:
    """Group 1: the five canonical files, plus versioned backups, no strays."""
    trinity = ctx["trinity"]
    if not trinity.is_dir():
        return _binary_check("File set", False, ".trinity/ directory not found -- nothing to measure")

    present = {item.name for item in trinity.iterdir()}
    missing = [name for name in _CANONICAL_FILES if name not in present]
    strays = _stray_names(trinity)

    items = [(name not in missing, f".trinity/: missing {name}") for name in _CANONICAL_FILES]
    items.extend((False, f".trinity/: stray {name} -- not one of the five canonical files") for name in strays)
    return _items_check("File set", items, f".trinity/ holds exactly the {len(_CANONICAL_FILES)} canonical files")


def check_branch_info(branch_path: str) -> list[str]:
    """Non-scored info lines: one per stray file or directory in .trinity/.

    The strays are also scored under the File set group; this channel exists
    so the names stay visible in the audit output even when the renderer
    truncates the group's failure message.

    Args:
        branch_path: Branch root to inspect.

    Returns:
        One line per stray, empty when .trinity/ is clean or absent.
    """
    trinity = Path(branch_path) / _TRINITY_DIR
    if not trinity.is_dir():
        return []
    return [f"trinity: stray .trinity/{name}" for name in _stray_names(trinity)]


# =============================================================================
# GROUP 2 -- TOP-LEVEL KEYS
# =============================================================================


def _key_set_item(name: str, data: dict, order: list) -> tuple:
    """Item: the exact top-level key set, missing and stray named."""
    missing = [key for key in order if key not in data]
    stray = [key for key in data if key not in order]
    parts = []
    if missing:
        parts.append("missing " + ", ".join(missing))
    if stray:
        parts.append("stray top-level section(s) " + ", ".join(stray))
    if parts:
        return (False, f"{name}: " + "; ".join(parts))
    return (True, None)


def _key_order_item(name: str, data: dict, order: list) -> tuple:
    """Item: canonical keys appear in canonical order."""
    present = [key for key in data if key in order]
    expected = [key for key in order if key in data]
    if present != expected:
        return (False, f"{name}: top-level key order is {', '.join(present)} -- expected {', '.join(expected)}")
    return (True, None)


def _duplicate_item(name: str, duplicates: list) -> tuple:
    """Item: no key appears twice in the raw JSON text."""
    if duplicates:
        repeated = ", ".join(sorted(set(duplicates)))
        return (False, f"{name}: duplicate JSON key(s) {repeated} -- the later value silently wins")
    return (True, None)


def _document_name_item(name: str, meta: dict, branch: str, suffix: str) -> tuple:
    """Item: document_name is <BRANCH> plus the exact file suffix."""
    value = meta.get("document_name")
    if not isinstance(value, str):
        return (False, f"{name}: document_name must be str, found {_found(meta, 'document_name')}")
    if not value.endswith(suffix):
        return (False, f"{name}: document_name {value} must end with {suffix}")
    if value[: -len(suffix)].lower() != branch.lower():
        return (False, f"{name}: document_name {value} does not name branch {branch}")
    return (True, None)


def _managed_by_item(name: str, meta: dict, branch: str) -> tuple:
    """Item: managed_by equals the branch directory name exactly."""
    value = meta.get("managed_by")
    if not isinstance(value, str):
        return (False, f"{name}: managed_by must be str, found {_found(meta, 'managed_by')}")
    if value != branch:
        return (False, f"{name}: managed_by {value} != branch directory name {branch}")
    return (True, None)


def _doc_meta_items(ctx: dict, file_key: str, data: dict) -> list:
    """The four document_metadata items for one file."""
    name = _FILE_NAMES[file_key]
    meta = data.get("document_metadata")
    if not isinstance(meta, dict):
        found = _found(data, "document_metadata")
        head = (False, f"{name}: document_metadata must be an object, found {found} -- its fields are unmeasurable")
        return [head, (False, None), (False, None), (False, None)]

    missing = [field for field in _DOC_META_FIELDS if field not in meta]
    fields_item = (not missing, f"{name}: document_metadata missing {', '.join(missing)}" if missing else None)
    status_item = (
        "status" not in meta,
        f"{name}: document_metadata.status is deleted by the standard -- health is computed at run time, never stored",
    )
    return [
        fields_item,
        status_item if "status" in meta else (True, None),
        _document_name_item(name, meta, ctx["branch"], _DOC_NAME_SUFFIX[file_key]),
        _managed_by_item(name, meta, ctx["branch"]),
    ]


def _top_level_items(ctx: dict, file_key: str, order: list) -> list:
    """The eight top-level items for one file."""
    name = _FILE_NAMES[file_key]
    fileref = ctx[file_key]
    if fileref["error"] is not None:
        head = (False, f"{name}: {fileref['error']} -- top-level structure unmeasurable")
        return [head] + [(False, None)] * 7

    data = fileref["data"]
    return [
        (True, None),
        _key_set_item(name, data, order),
        _key_order_item(name, data, order),
        _duplicate_item(name, fileref["duplicates"]),
        *_doc_meta_items(ctx, file_key, data),
    ]


def _managed_by_agreement(ctx: dict) -> tuple:
    """Item: both of a branch's own files carry the same managed_by casing."""
    values = []
    for file_key in _FILE_NAMES:
        fileref = ctx[file_key]
        data = fileref["data"] if fileref["error"] is None else None
        values.append(_as_dict(_as_dict(data).get("document_metadata")).get("managed_by"))
    if any(value is None for value in values):
        return (False, "managed_by agreement unmeasurable -- one of the two files yielded no managed_by")
    if values[0] != values[1]:
        return (False, f"managed_by disagrees across the branch's own files: {values[0]} vs {values[1]}")
    return (True, None)


def _group_top_level(ctx: dict) -> dict:
    """Group 2: top-level key set, order, duplicates and document_metadata."""
    items = _top_level_items(ctx, "local", _LOCAL_KEY_ORDER)
    items.extend(_top_level_items(ctx, "observations", _OBSERVATIONS_KEY_ORDER))
    items.append(_managed_by_agreement(ctx))
    return _items_check("Top-level keys", items, "Both files carry the canonical top-level keys, in order")


# =============================================================================
# GROUP 3 -- ENTRY SHAPES
# =============================================================================


def _shape_probe(section: str, entries: list) -> tuple[int, list]:
    """Validate every entry of *section*; return (ok_count, records)."""
    label = _section_file(section)
    ok = 0
    records: list = []
    for index, entry in enumerate(entries):
        problems = validate_entry_shape(section, entry)
        if not problems:
            ok += 1
            continue
        entry_label = _entry_label(entry, index)
        records.extend((label, problem, entry_label) for problem in problems)
    return ok, records


def _group_entry_shapes(ctx: dict) -> dict:
    """Group 3: required fields with required types, no extras."""
    ok, total, records = _entry_scan(ctx, _ALL_SECTIONS, _shape_probe)
    return _records_check("Entry shapes", ok, total, records, f"All {total} entries carry the canonical shape")


# =============================================================================
# GROUP 4 -- ORDERING AND NUMBERING
# =============================================================================


def _ordering_problem(entry: object, previous: int | None, seen: set) -> str | None:
    """Return why *entry* breaks newest-first numbering, or None."""
    if not isinstance(entry, dict):
        return f"entry must be an object, found {type(entry).__name__} -- no usable number"
    number = entry.get("number")
    if not isinstance(number, int) or isinstance(number, bool):
        return f"no usable 'number' -- must be int, found {_found(entry, 'number')}"
    if number in seen:
        return f"number {number} reused"
    if previous is not None and number >= previous:
        return f"number {number} is not below the entry above it ({previous}) -- lists are newest-first"
    return None


def _ordering_probe(section: str, entries: list) -> tuple[int, list]:
    """Walk *entries* top-down checking strictly descending numbers."""
    label = _section_file(section)
    ok = 0
    records: list = []
    previous: int | None = None
    seen: set = set()
    for index, entry in enumerate(entries):
        problem = _ordering_problem(entry, previous, seen)
        if problem is None:
            ok += 1
        else:
            records.append((label, problem, _entry_label(entry, index)))
        number = entry.get("number") if isinstance(entry, dict) else None
        if _is_int(number):
            seen.add(number)
            previous = number
    return ok, records


def _group_ordering(ctx: dict) -> dict:
    """Group 4: newest-first, numbers strictly descending, never reused."""
    ok, total, records = _entry_scan(ctx, _ALL_SECTIONS, _ordering_probe)
    clean = f"All {total} entries are newest-first with strictly descending numbers"
    return _records_check("Ordering & numbering", ok, total, records, clean)


# =============================================================================
# GROUP 5 -- CHAR CAPS
# =============================================================================


def _cap_problem(entry: object, field: str, max_chars: int) -> str | None:
    """Return why *entry* fails its cap, or None."""
    if not isinstance(entry, dict):
        return f"entry must be an object, found {type(entry).__name__} -- '{field}' unmeasurable"
    value = entry.get(field)
    if not isinstance(value, str):
        return f"'{field}' unmeasurable: must be str, found {_found(entry, field)}"
    if len(value) > max_chars:
        return f"'{field}' is {len(value)} chars, cap {max_chars}"
    return None


def _cap_probe(section: str, entries: list, limits: dict) -> tuple[int, list]:
    """Measure every entry of *section* against its configured cap."""
    spec = _as_dict(limits.get(section))
    field = spec.get("field")
    max_chars = spec.get("max_chars")
    if isinstance(field, str) and isinstance(max_chars, int) and not isinstance(max_chars, bool):
        return _run_probe(section, entries, partial(_cap_problem, field=field, max_chars=max_chars))
    reason = f"cannot measure caps for '{section}': config has no usable entry_types.{section} field/max_chars"
    return 0, [(_section_file(section), reason, None)]


def _group_char_caps(ctx: dict) -> dict:
    """Group 5: char caps measured against the config, never the meta line."""
    config = ctx["config"]
    if config is None:
        message = "cannot measure caps: memory.config.json unreadable -- cap numbers are never assumed"
        return _binary_check("Char caps", False, message)
    limits = _resolve_entry_limits(config, ctx["branch"])
    ok, total, records = _entry_scan(ctx, _ALL_SECTIONS, partial(_cap_probe, limits=limits))
    return _records_check("Char caps", ok, total, records, f"All {total} entries are within their configured caps")


# =============================================================================
# GROUP 6 -- META LINES AND _usage
# =============================================================================


def _preview(text: str) -> str:
    """Shorten a long expected string for a failure message."""
    if len(text) <= _EXPECTED_PREVIEW_CHARS:
        return text
    return text[:_EXPECTED_PREVIEW_CHARS] + "..."


def _meta_item(ctx: dict, section: str) -> tuple:
    """Item: one ``*_meta`` line byte-matches config plus template prose."""
    file_key, meta_key = _META_SOURCE[section]
    name = _FILE_NAMES[file_key]
    fileref = ctx[file_key]
    if fileref["error"] is not None:
        return (False, f"{name}: {fileref['error']} -- {meta_key} unmeasurable")

    spec = _as_dict(_resolve_entry_limits(ctx["config"], ctx["branch"]).get(section))
    if not isinstance(spec.get("field"), str) or not _is_int(spec.get("max_chars")):
        return (False, f"{name}: cannot compose {meta_key} -- config has no entry_types.{section}")

    expected = expected_meta_line(section, ctx["branch"], ctx["config"], ctx["prose"][section])
    actual = fileref["data"].get(meta_key)
    if not isinstance(actual, str):
        return (False, f"{name}: {meta_key} must be str, found {_found(fileref['data'], meta_key)}")
    if actual != expected:
        return (
            False,
            f"{name}: {meta_key} does not byte-match the rendered tab + template prose: {_preview(expected)}",
        )
    return (True, None)


def _usage_item(ctx: dict, file_key: str) -> tuple:
    """Item: document_metadata._usage byte-matches the gold template text."""
    name = _FILE_NAMES[file_key]
    fileref = ctx[file_key]
    if fileref["error"] is not None:
        return (False, f"{name}: {fileref['error']} -- _usage unmeasurable")
    meta = _as_dict(fileref["data"].get("document_metadata"))
    actual = meta.get("_usage")
    if not isinstance(actual, str):
        return (False, f"{name}: document_metadata._usage must be str, found {_found(meta, '_usage')}")
    if actual != ctx["usage"][file_key]:
        return (False, f"{name}: document_metadata._usage does not byte-match the gold template text")
    return (True, None)


def _group_meta_lines(ctx: dict) -> dict:
    """Group 6: meta lines and _usage byte-match config plus gold templates."""
    if ctx["config"] is None:
        message = "cannot compose expected meta lines: memory.config.json unreadable -- numbers are never assumed"
        return _binary_check("Meta lines & _usage", False, message)
    if ctx["prose"] is None or ctx["usage"] is None:
        message = (
            "cannot compose expected meta lines: memory/templates/*.template.json unreadable -- prose is never assumed"
        )
        return _binary_check("Meta lines & _usage", False, message)

    items = [_meta_item(ctx, section) for section in _ALL_SECTIONS]
    items.extend(_usage_item(ctx, file_key) for file_key in _FILE_NAMES)
    return _items_check("Meta lines & _usage", items, "All meta lines and _usage strings byte-match the gold source")


# =============================================================================
# GROUP 7 -- FRESHNESS
# =============================================================================


def _parse_date(value: object) -> date | None:
    """Parse the YYYY-MM-DD part of a date or datetime string, or None."""
    if not isinstance(value, str):
        return None
    match = _DATE_RE.match(value.strip())
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(0))
    except ValueError:
        # Right shape, impossible day (2026-13-45). Logged rather than
        # swallowed: the caller turns None into a loud violation, and the
        # value that produced it belongs in the record.
        logger.warning("trinity_check: %s has the date shape but is not a real date", value)
        return None


def _scan_section_dates(entries: list, newest: date | None) -> tuple:
    """Fold *entries* into (newest date, labels of unparseable dates)."""
    bad: list[str] = []
    for index, entry in enumerate(entries):
        parsed = _parse_date(entry.get("date")) if isinstance(entry, dict) else None
        if parsed is None:
            bad.append(_entry_label(entry, index))
        elif newest is None or parsed > newest:
            newest = parsed
    return newest, bad


def _newest_entry_date(ctx: dict, sections: tuple) -> tuple:
    """Return (newest entry date, reasons freshness is unmeasurable)."""
    newest: date | None = None
    bad: list[str] = []
    for section in sections:
        entries, error = _section_entries(ctx, section)
        if entries is None:
            bad.append(f"{section} {error}")
            continue
        newest, section_bad = _scan_section_dates(entries, newest)
        bad.extend(f"{section} {label}" for label in section_bad)
    return newest, bad


def _freshness_item(ctx: dict, file_key: str, sections: tuple) -> tuple:
    """Item: last_updated is at least as new as the newest entry date."""
    name = _FILE_NAMES[file_key]
    fileref = ctx[file_key]
    if fileref["error"] is not None:
        return (False, f"{name}: {fileref['error']} -- freshness unmeasurable")

    meta = _as_dict(_as_dict(fileref["data"]).get("document_metadata"))
    stamped = _parse_date(meta.get("last_updated"))
    if stamped is None:
        return (
            False,
            f"{name}: document_metadata.last_updated is not a YYYY-MM-DD date, found {_found(meta, 'last_updated')}",
        )

    newest, bad = _newest_entry_date(ctx, sections)
    if bad:
        return (False, f"{name}: {len(bad)} entry date(s) unmeasurable ({', '.join(bad[:_MAX_SAMPLE_NUMBERS])})")
    if newest is not None and stamped < newest:
        return (False, f"{name}: last_updated {stamped.isoformat()} predates newest entry date {newest.isoformat()}")
    return (True, None)


def _group_freshness(ctx: dict) -> dict:
    """Group 7: last_updated >= the newest entry date in the same file."""
    items = [
        _freshness_item(ctx, "local", _LOCAL_SECTIONS),
        _freshness_item(ctx, "observations", ("observations",)),
    ]
    return _items_check("Freshness", items, "last_updated is at least as new as the newest entry in both files")


# =============================================================================
# GROUP 8 -- TODOS HYGIENE
# =============================================================================


def _todo_problem(entry: object) -> str | None:
    """Return why a todo breaks hygiene, or None."""
    if not isinstance(entry, dict):
        return f"entry must be an object, found {type(entry).__name__} -- status unmeasurable"
    status = entry.get("status")
    if not isinstance(status, str):
        return f"'status' unmeasurable: must be str, found {_found(entry, 'status')}"
    if status.strip().lower() == "done":
        return "todo kept with status done -- delete it, do not keep it"
    return None


def _todo_probe(section: str, entries: list) -> tuple[int, list]:
    """Check every todo for the done-trophy pattern."""
    return _run_probe(section, entries, _todo_problem)


def _group_todos_hygiene(ctx: dict) -> dict:
    """Group 8: no todo survives as status done."""
    ok, total, records = _entry_scan(ctx, ("todos",), _todo_probe)
    return _records_check("Todos hygiene", ok, total, records, f"All {total} todos are open -- none kept as done")


# =============================================================================
# GROUP 9 -- RECEIPT
# =============================================================================


def _receipt_versions_shape(data: dict) -> tuple:
    """Item: template_versions is a dict of two string versions."""
    versions = data.get("template_versions")
    if not isinstance(versions, dict):
        return (
            False,
            f"{_RECEIPT_NAME}: template_versions must be an object, found {_found(data, 'template_versions')}",
        )
    wrong = [f"{key} {_found(versions, key)}" for key in _FILE_NAMES if not isinstance(versions.get(key), str)]
    if wrong:
        return (False, f"{_RECEIPT_NAME}: template_versions needs str local and observations -- {', '.join(wrong)}")
    return (True, None)


def _receipt_versions_match(ctx: dict, data: dict) -> tuple:
    """Item: template_versions values equal the gold source versions."""
    gold = ctx["gold_versions"]
    if gold is None:
        return (False, f"{_RECEIPT_NAME}: cannot verify template_versions -- gold templates unreadable")
    versions = _as_dict(data.get("template_versions"))
    wrong = [f"{key} {versions.get(key)} != gold {gold[key]}" for key in _FILE_NAMES if versions.get(key) != gold[key]]
    if wrong:
        return (False, f"{_RECEIPT_NAME}: template_versions {', '.join(wrong)}")
    return (True, None)


def _receipt_string_items(data: dict) -> list:
    """Items: stamped, stamped_by and config_rendered are strings."""
    items = []
    for field in _RECEIPT_STRING_FIELDS:
        ok = isinstance(data.get(field), str)
        items.append((ok, None if ok else f"{_RECEIPT_NAME}: {field} must be str, found {_found(data, field)}"))
    return items


def _group_receipt(ctx: dict) -> dict:
    """Group 9: the machine-written template version receipt."""
    fileref = ctx["receipt"]
    if fileref["error"] is not None:
        message = f"{_RECEIPT_NAME}: {fileref['error']} -- no receipt means no lookup for who carries the standard"
        return {"name": "Receipt", "passed": False, "message": message, "score": 0}

    data = fileref["data"]
    items = [(True, None), _receipt_versions_shape(data), _receipt_versions_match(ctx, data)]
    items.extend(_receipt_string_items(data))
    return _items_check("Receipt", items, f"{_RECEIPT_NAME} is machine-shaped and carries the gold versions")


# =============================================================================
# PUBLIC ENTRY POINT
# =============================================================================


def _build_context(branch_path: Path) -> dict:
    """Read every input once: the three files, the config, the gold templates."""
    trinity = branch_path / _TRINITY_DIR
    templates = _load_templates()
    return {
        "branch": branch_path.name,
        "trinity": trinity,
        "local": _read_json_file(trinity / _LOCAL_NAME),
        "observations": _read_json_file(trinity / _OBSERVATIONS_NAME),
        "receipt": _read_json_file(trinity / _RECEIPT_NAME),
        "config": load_memory_config(),
        "prose": load_template_prose(templates),
        "usage": _usage_from_templates(templates),
        "gold_versions": _gold_versions_from_templates(templates),
    }


def _weighted_score(checks: list) -> int:
    """Weighted mean of the nine group subscores, never rounded up to a pass."""
    total = sum(check["score"] * GROUP_WEIGHTS[check["name"]] / 100 for check in checks)
    score = round(total)
    if score >= 100 and any(check["score"] < 100 for check in checks):
        return 99
    return score


def check_branch(branch_path: str, bypass_rules: list | None = None) -> dict:
    """Check one branch's .trinity/ memory files against the trinity standard.

    Nine groups are measured -- file set, top-level keys, entry shapes,
    ordering and numbering, char caps, meta lines and _usage, freshness, todos
    hygiene, and the template version receipt.  Every group reports its own
    0-100 subscore and the standard's score is their weighted mean.

    Nothing here is skipped for being unreadable: a missing file, a broken
    parse, a wrong type or an unreadable config each fail the groups that
    depend on them, by name.

    Args:
        branch_path: Branch root (the directory holding .trinity/).
        bypass_rules: Accepted for interface compatibility ONLY and never
            consulted. The trinity contract's Bypass section reads: "None for
            shape rules, by design -- a bypassable memory standard recreates
            the drift it exists to end. A branch that genuinely needs
            different numbers gets a per-branch entry in @memory's config (the
            one source), not a bypass file." Do not add is_bypassed() here.

    Returns:
        ``{"standard": "TRINITY", "score": int, "passed": bool,
        "checks": [nine group dicts]}``.
    """
    ctx = _build_context(Path(branch_path))
    checks = [
        _group_entry_shapes(ctx),
        _group_top_level(ctx),
        _group_ordering(ctx),
        _group_char_caps(ctx),
        _group_file_set(ctx),
        _group_meta_lines(ctx),
        _group_receipt(ctx),
        _group_todos_hygiene(ctx),
        _group_freshness(ctx),
    ]
    score = _weighted_score(checks)

    result = {
        "standard": "TRINITY",
        "score": score,
        "passed": score == 100,
        "checks": checks,
    }
    json_handler.log_operation(
        "check_completed",
        {"branch": branch_path, "score": score, "standard": "trinity"},
    )
    return result
