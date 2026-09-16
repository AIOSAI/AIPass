# =================== AIPass ====================
# Name: trinity_groups.py
# Description: Trinity standard - the eight group checkers and their shared helpers
# Version: 1.3.0
# Created: 2026-08-27
# Modified: 2026-09-16
# =============================================

"""
Trinity standard -- the eight group checkers.

Split out of ``trinity_check.py`` on 2026-08-27, when that file crossed the
1500-line architecture cap.  This is a RELOCATION: no rule, threshold or
message changed in the move.  ``trinity_check`` keeps the module contract and
the orchestration; everything that decides whether a specific rule is met
lives here.

Each ``_group_*`` function takes the context dict built by
``trinity_check._build_context`` and returns one check dict
``{"name", "passed", "score", "message"}``.  They are pure: they read the
context, and never touch the disk themselves.

The one law holds in every group
--------------------------------
A field the checker cannot measure is a VIOLATION, never a silent pass.  A
missing, unreadable or invalid file fails every group that depends on it, by
name; a field of the wrong type is reported with the type actually found and
is never coerced or ``len()``-ed.  The guard that makes this true is in
``_records_check``: violation records decide WHETHER a group passes, and the
entry denominator only decides how bad the score is.  A group holding any
record can never score 100, even when the denominator is empty.

Contents, in file order: shared type/path/config helpers, message formatting,
the three check builders, section access, then the eight groups -- file set,
top-level keys, entry shapes, ordering & numbering, char caps, meta lines &
_usage, freshness, receipt.

Todos v2 (DPLAN-0345, 2026-09-15): a todo is ``{number, date, task,
priority?}`` with no ``status``, and the todos tab names the pad size, the
backlog file and the next number.  Group 8, Todos hygiene, is RETIRED: it
flagged a todo kept as ``status: done``, and with no ``status`` field that
trophy can only be spelled as a key outside the closed shape, which Entry
shapes already flags by name.  Its weight moved with the defect.

The shape is READ, not remembered (FPLAN-0593 Phase 2, 2026-09-15)
------------------------------------------------------------------
``_ENTRY_RULES`` used to sit at the top of this file: a hand-kept copy of the
four entry shapes, correct on the day it was written and one @memory config
edit away from wrong on any day after.  It is gone.  :func:`entry_shapes`
derives the required/optional split from
``entry_limits.entry_types.<type>.fields`` in memory.config.json -- the same
closed map @memory's ``trinity_push`` derives its own rules from, so the
checker and the push cannot disagree about what a canonical entry is.

Fail CLOSED, on the Char caps group's contract: the shape is never assumed any
more than the cap numbers are.  An unreadable config refuses Entry shapes
whole; a config that publishes no ``fields`` for a section raises an error row
naming that key, and a group holding any record can never score 100.

The read is by CONFIG KEY, not by import.  memory.config.json is a file this
checker already reads and already declares in ``external_inputs()``, so the
shape arrives with no new coupling and nothing new for the audit cache to
watch.  @memory now publishes ``apps/modules/limits.py`` as the door to the
same accessors, which is the right reach for a caller that holds no config;
this module holds the config dict it is auditing, and a live import would
answer from @memory's own file instead of that dict.

The draft percent made the move too (2026-09-16).  ``_DRAFT_PERCENT = 80`` sat
here for as long as @memory published the number as a module constant with no
key to read.  memory.config.json now carries ``entry_limits.draft_percent``,
so the percent arrives out of the same dict as the caps and the shape, and no
number in this file is a copy of a number in that one.
"""

import re
from datetime import date
from functools import partial
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

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
# the same words the contract uses -- and the same three words @memory's
# config spells them with, which is what lets a config `type` be compared
# against a value here without a translation table in between.
_TYPE_INT = "int"
_TYPE_STR = "str"
_TYPE_STR_LIST = "list[str]"

# Where the closed field shape lives on an entry type definition, spelled as
# @memory spells it (entry_limits.FIELDS_KEY). The KEY is carried here; the
# MAP never is -- see entry_shapes().
_FIELDS_KEY = "fields"

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

# The draft target every tab carries beside its cap (DPLAN-0342, the user's
# ruling 2026-09-13): integer percent, floored, derived from the SAME resolved
# cap (per_branch included) - 300/200/150 -> 240/160/120, 77 -> 61, never
# rounded.
#
# THE MIRROR RETIRED (2026-09-16). It was `_DRAFT_PERCENT = 80` here, guarded
# by a pin on @memory's live draft_target(), for as long as @memory published
# the percent as a module constant with no key to read. It publishes
# entry_limits.draft_percent now, so the number is READ from the config dict
# this module is handed -- the same dict the caps and the entry shape come
# out of, from a file external_inputs() already declares.
#
# NEVER ASSUMED. A config that publishes no usable percent (absent, not an
# int, outside 1-100) does not get a guessed one: _draft_percent returns None,
# the tab renders the marker below rather than a number, and the Meta lines
# group refuses the whole group loud, naming the key and its owner. @memory's
# own loader narrows to its regeneration seed instead, which is its call to
# make about what it writes -- but a checker that quietly agreed with a seed
# would be scoring files against a number nobody published.
_DRAFT_PERCENT_KEY = "draft_percent"
_DRAFT_PERCENT_BOUNDS = (1, 100)
_UNPUBLISHED_DRAFT = "<entry_limits.draft_percent unpublished>"

# The todos pad tab (DPLAN-0345), mirroring @memory's tab_renderer._todos_tab
# and todo_roll's BACKUP_DIR / TODO_DIR / BACKLOG_FILE. A caller without branch
# context renders the honest unknowns, never a guessed directory or number.
_TODO_BACKLOG_PARTS = (".backup", "todo")
_TODO_BACKLOG_FILE = "backlog.json"
_UNKNOWN_BRANCH_DIR = "<branch>"
_UNKNOWN_NEXT = "?"

# How str() writes an int: the only thing a rendered `next #N` can hold besides
# the unknown. N is derived at RENDER time and adding a todo does not re-render
# (contract section 3), so the checker reads the slot's shape, never its value.
_RENDERED_INT_RE = re.compile(r"0|-?[1-9][0-9]*")

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


def _guidelines_from_templates(templates: dict | None) -> dict | None:
    """The gold observations ``guidelines`` block, or None if unreadable.

    None means REFUSE, never score zero: an unreadable gold source makes the
    field unmeasurable, and the standard's one law is that an unmeasurable
    field is refused rather than assumed.

    Args:
        templates: Loaded gold templates, or None.

    Returns:
        The template's guidelines dict, or None when it cannot be read.
    """
    if templates is None:
        return None
    block = _as_dict(templates.get("observations")).get("guidelines")
    return block if isinstance(block, dict) else None


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


# =============================================================================
# CONFIG RESOLUTION (caps and keep-counts)
# =============================================================================


def _draft_percent(config: object) -> int | None:
    """Return the draft percent @memory publishes in *config*, or None when it publishes none usable.

    Args:
        config: The memory.config.json mapping, as read.

    Returns:
        The percent as an int when ``entry_limits.draft_percent`` is an int
        inside :data:`_DRAFT_PERCENT_BOUNDS`; None otherwise, so no caller can
        receive a number this file invented.
    """
    raw = _as_dict(_as_dict(config).get("entry_limits")).get(_DRAFT_PERCENT_KEY)
    low, high = _DRAFT_PERCENT_BOUNDS
    if not _is_int(raw) or not low <= int(raw) <= high:  # pyright: ignore[reportArgumentType]
        return None
    return int(raw)  # pyright: ignore[reportArgumentType]


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


def _resolve_todos_count(config: dict, branch_name: str) -> int | None:
    """Resolve the todo pad size the way @memory's config_loader.get_todos_count does, or None.

    Per file key like the other sections, with one exception @memory makes for
    todos alone: a per_branch ``local`` block that carries no todos count falls
    back to the default todos count instead of leaving the pad unsized.  A
    bool, a non-int, zero or a negative number is not a pad size.
    """
    rollover = _as_dict(_as_dict(config).get("rollover"))
    defaults_local = _as_dict(_as_dict(rollover.get("defaults")).get("local"))
    branch_cfg = _as_dict(_lookup_case_insensitive(rollover.get("per_branch"), branch_name))
    file_limits = _as_dict(branch_cfg.get("local")) or defaults_local
    count = _as_dict(file_limits.get("todos")).get("count")
    if count is None:
        count = _as_dict(defaults_local.get("todos")).get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        return None
    return count


def _todos_tab(config: dict, branch_name: str, max_chars: object, draft: object, todo_ctx: dict | None) -> str:
    """The todos pad tab: pad size, backlog file, caps, next number -- @memory's _todos_tab, glyph for glyph."""
    context = todo_ctx if isinstance(todo_ctx, dict) else {}
    branch_dir = context.get("branch_dir") or _UNKNOWN_BRANCH_DIR
    number = context.get("next_number")
    next_label = number if _is_int(number) else _UNKNOWN_NEXT
    tail = f"task ≤{max_chars} chars · draft to {draft} · next #{next_label}"
    count = _resolve_todos_count(config, branch_name)
    if count is None:
        return f"⟦ no pad size configured — nothing rolls · {tail} ⟧"
    backlog = "/".join((*_TODO_BACKLOG_PARTS, str(branch_dir), _TODO_BACKLOG_FILE))
    return f"⟦ pad of {count} · oldest roll to {backlog} · {tail} ⟧"


def expected_meta_line(
    section: str,
    branch_name: str,
    config: dict,
    template_prose: str,
    todo_ctx: dict | None = None,
) -> str:
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
        todo_ctx: ``{"branch_dir", "next_number"}`` for the todos tab, the
            shape of @memory's ``tab_renderer.todo_context``; None renders
            ``<branch>`` and ``next #?`` exactly as @memory does without it.
            Ignored for every other section.

    Returns:
        The expected meta line as one string.
    """
    limits = _resolve_entry_limits(_as_dict(config), branch_name)
    spec = _as_dict(limits.get(section))
    max_chars = spec.get("max_chars", _RENDERER_FALLBACK_MAX_CHARS)
    field = spec.get("field", _RENDERER_FALLBACK_FIELD)
    # A non-integer cap is a config error the Char caps group reports; echo it
    # rather than raise, so this function stays total. An unpublished percent
    # renders its marker for the same reason: loud in the diff, never a guess.
    percent = _draft_percent(config)
    if percent is None:
        draft = _UNPUBLISHED_DRAFT
    else:
        draft = max_chars * percent // 100 if _is_int(max_chars) else max_chars

    if section == "todos":
        return f"{_todos_tab(_as_dict(config), branch_name, max_chars, draft, todo_ctx)} {template_prose}"

    count = _resolve_rollover_count(_as_dict(config), section, branch_name)
    if count is None:
        tab = f"⟦ rollover ON → no entry limit configured · {field} ≤{max_chars} chars · draft to {draft} ⟧"
    else:
        tab = (
            f"⟦ rollover ON → oldest archived to @memory · keep {count} · {field} ≤{max_chars} chars"
            f" · draft to {draft} ⟧"
        )
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


def _rules_from_fields(fields: dict) -> dict | None:
    """Split one closed field map into the required/optional shape this module checks.

    The derivation @memory's ``trinity_push._rules_from_fields`` runs on the
    same map, reproduced as LOGIC rather than as data: a field is required
    when the config says so and optional otherwise, and ``type`` is one of the
    three names both sides already spell identically.

    Args:
        fields: ``entry_types.<type>.fields`` --
            ``{name: {"type", "required", ...}}`` as the config publishes it.

    Returns:
        ``{"required": {name: type}, "optional": {name: type}}``, or None when
        a field spec is not an object or carries no ``type`` string.  None is
        the fail-closed answer: a shape that cannot be read is not a shape
        every entry happens to satisfy, and the caller turns it into an error
        row naming the key rather than measuring against a remembered rule.
    """
    required: dict[str, str] = {}
    optional: dict[str, str] = {}
    for name, spec in fields.items():
        if not isinstance(spec, dict):
            return None
        field_type = spec.get("type")
        if not isinstance(field_type, str):
            return None
        target = required if spec.get("required") else optional
        target[name] = field_type
    return {"required": required, "optional": optional}


def entry_shapes(config: object, branch_name: str) -> dict:
    """Return the canonical entry shape per section, read from @memory's config.

    THE SHAPE HAS ONE HOME AND IT IS NOT HERE (FPLAN-0593 Phase 2).  This
    module carried its own literal copy of the four entry shapes until
    2026-09-15, @memory's ``trinity_push`` carried a second, and the write
    gate measured against a third.  Three copies of one contract is three
    chances for a push to prune an entry the gate would have accepted.  Phase
    1 moved the shape into ``entry_limits.entry_types.<type>.fields`` in
    memory.config.json; this reads it from there, through the same per_branch
    resolution the caps already use, so a branch cannot be held to one shape
    and told another.

    Read from the CONFIG KEY, not through a gateway, and deliberately:
    @memory publishes ``entry_limits.fields_for()`` from
    ``apps/handlers/json/entry_limits.py``, and a cross-branch ``handlers``
    import is a violation of seedgo's own encapsulation standard (it scores
    every branch, including this one).  ``apps/modules/`` carries no gateway
    for it -- those modules are CLI command handlers, not an importable
    surface.  memory.config.json is the file this checker already opens
    (:func:`trinity_check.load_memory_config`) and already declares in
    ``external_inputs()``, so reading one more key out of it adds no new
    coupling and nothing new for the audit cache to watch.

    Args:
        config: The parsed memory.config.json, or anything unusable.
        branch_name: Branch directory name; per-branch overrides match it
            case-insensitively.

    Returns:
        ``{section: {"required": {...}, "optional": {...}}}`` holding only the
        sections the config publishes a usable shape for.  A section missing
        from the result is the fail-closed signal -- the caller raises an
        error row naming the key, never a pass.
    """
    shapes: dict[str, dict] = {}
    for section, spec in _resolve_entry_limits(_as_dict(config), branch_name).items():
        fields = _as_dict(spec).get(_FIELDS_KEY)
        if not isinstance(fields, dict) or not fields:
            continue
        rules = _rules_from_fields(fields)
        if rules is not None:
            shapes[section] = rules
    return shapes


def validate_entry_shape(section: str, entry: object, shapes: dict) -> list[str]:
    """Validate one entry against its section's canonical shape.

    Required fields must be present WITH their required types, optional
    fields must type-check when present, and any other key is a violation
    named by the key found -- that is how a renamed field (``learning`` for
    key/value, ``session``/``category``/``type`` for ``tags``) becomes
    visible instead of silently measuring as nothing.

    Args:
        section: One of sessions, key_learnings, todos, observations.
        entry: The candidate entry, of any type.
        shapes: The map from :func:`entry_shapes` -- @memory's published
            shape, resolved for this branch.  Required rather than defaulted:
            a shape this module could supply on its own is the mirror Phase 2
            exists to delete.

    Returns:
        A list of human-readable violation strings; empty means clean.
    """
    rules = _as_dict(shapes).get(section)
    if not isinstance(rules, dict):
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
        _extra_meta_fields_item(name, meta),
    ]


def _extra_meta_fields_item(name: str, meta: dict) -> tuple:
    """Item: document_metadata carries no field outside the closed set.

    ``status`` is excluded here because it already has its own item, which
    says WHY it is deleted (health is computed, never stored). Folding it into
    a generic "unexpected field" line would lose that instruction.
    """
    extra = [key for key in meta if key not in _DOC_META_FIELDS and key != "status"]
    if not extra:
        return (True, None)
    return (False, f"{name}: document_metadata has unexpected field(s) {', '.join(sorted(extra))} -- the set is closed")


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


def _shape_probe(section: str, entries: list, shapes: dict) -> tuple[int, list]:
    """Validate every entry of *section* against the published shape; return (ok_count, records)."""
    label = _section_file(section)
    if section not in shapes:
        reason = f"cannot measure shapes for '{section}': config has no usable entry_types.{section}.fields"
        return 0, [(label, reason, None)]
    ok = 0
    records: list = []
    for index, entry in enumerate(entries):
        problems = validate_entry_shape(section, entry, shapes)
        if not problems:
            ok += 1
            continue
        entry_label = _entry_label(entry, index)
        records.extend((label, problem, entry_label) for problem in problems)
    return ok, records


def _group_entry_shapes(ctx: dict) -> dict:
    """Group 3: required fields with required types, no extras -- the shape from the config.

    Fails CLOSED, on the Char caps group's contract: the shape is never
    assumed any more than the cap numbers are.  An unreadable config refuses
    the whole group; a config that publishes no ``fields`` map for a section
    raises an error row naming that key, and a group holding any record can
    never score 100 (see ``_records_check``).
    """
    config = ctx["config"]
    if config is None:
        message = "cannot measure shapes: memory.config.json unreadable -- the entry shape is never assumed"
        return _binary_check("Entry shapes", False, message)
    shapes = entry_shapes(config, ctx["branch"])
    ok, total, records = _entry_scan(ctx, _ALL_SECTIONS, partial(_shape_probe, shapes=shapes))
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


def _todos_meta_matches(actual: str, ctx: dict) -> bool:
    """True when *actual* is a todos line @memory's renderer can write for this branch.

    A byte-match everywhere but the ``next #N`` slot.  N is derived when the
    tab is RENDERED, and adding or deleting a todo does not re-render, so a
    correctly rendered file disagrees with an N recomputed from today's pad
    until the next render (the shape contract, section 3).  With the branch
    directory in the tab the slot may hold any rendered int or ``?``; the
    no-context rendering (``<branch>`` and ``#?``, what spawn birth writes)
    matches whole.
    """
    branch, config, prose = ctx["branch"], ctx["config"], ctx["prose"]["todos"]
    known = expected_meta_line("todos", branch, config, prose, {"branch_dir": branch, "next_number": None})
    if actual in (known, expected_meta_line("todos", branch, config, prose)):
        return True
    head, slot, tail = known.partition(f"next #{_UNKNOWN_NEXT} ⟧")
    prefix, suffix = f"{head}next #", f" ⟧{tail}"
    if not slot or len(actual) <= len(prefix) + len(suffix):
        return False
    if not (actual.startswith(prefix) and actual.endswith(suffix)):
        return False
    return _RENDERED_INT_RE.fullmatch(actual[len(prefix) : len(actual) - len(suffix)]) is not None


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

    actual = fileref["data"].get(meta_key)
    if not isinstance(actual, str):
        return (False, f"{name}: {meta_key} must be str, found {_found(fileref['data'], meta_key)}")
    if section == "todos":
        todo_ctx = {"branch_dir": ctx["branch"], "next_number": None}
        expected = expected_meta_line(section, ctx["branch"], ctx["config"], ctx["prose"][section], todo_ctx)
        matched = _todos_meta_matches(actual, ctx)
    else:
        expected = expected_meta_line(section, ctx["branch"], ctx["config"], ctx["prose"][section])
        matched = actual == expected
    if not matched:
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


def _guidelines_item(ctx: dict) -> tuple:
    """Item: observations.json's guidelines block matches the gold template.

    Ruling 3 landed template-verbatim, so the block's CONTENT is scored and
    not only its presence -- the pre-push fleet carried the right two keys
    with different text, which presence-only scoring could never see.
    """
    name = _OBSERVATIONS_NAME
    fileref = ctx["observations"]
    if fileref["error"] is not None:
        return (False, f"{name}: {fileref['error']} -- guidelines unmeasurable")
    block = fileref["data"].get("guidelines")
    if not isinstance(block, dict):
        return (False, f"{name}: guidelines must be an object, found {_found(fileref['data'], 'guidelines')}")
    if block != ctx["guidelines"]:
        return (False, f"{name}: guidelines does not match the gold template text")
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

    if ctx["guidelines"] is None:
        message = "cannot read the gold guidelines block: memory/templates/*.template.json unreadable -- never assumed"
        return _binary_check("Meta lines & _usage", False, message)

    if _draft_percent(ctx["config"]) is None:
        message = (
            "cannot compose expected meta lines: memory.config.json publishes no usable "
            f"entry_limits.{_DRAFT_PERCENT_KEY} (int 1-100, owner @memory) -- the draft target is never assumed"
        )
        return _binary_check("Meta lines & _usage", False, message)

    items = [_meta_item(ctx, section) for section in _ALL_SECTIONS]
    items.extend(_usage_item(ctx, file_key) for file_key in _FILE_NAMES)
    items.append(_guidelines_item(ctx))
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
# GROUP 8 -- RECEIPT
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
    """Group 8: the machine-written template version receipt."""
    fileref = ctx["receipt"]
    if fileref["error"] is not None:
        message = f"{_RECEIPT_NAME}: {fileref['error']} -- no receipt means no lookup for who carries the standard"
        return {"name": "Receipt", "passed": False, "message": message, "score": 0}

    data = fileref["data"]
    items = [(True, None), _receipt_versions_shape(data), _receipt_versions_match(ctx, data)]
    items.extend(_receipt_string_items(data))
    return _items_check("Receipt", items, f"{_RECEIPT_NAME} is machine-shaped and carries the gold versions")


# =============================================================================
# THE PUBLIC ENTRY POINT
# =============================================================================


def all_groups(ctx: dict) -> list:
    """Run the eight group checkers against one branch context.

    The order is the reporting order the audit renders, and it is fixed here
    rather than at the call site so the engine cannot silently drop a group by
    forgetting one in its list -- the failure mode a many-name import invites.

    Args:
        ctx: The context dict from trinity_check._build_context.

    Returns:
        Eight check dicts, each ``{"name", "passed", "score", "message"}``.
    """
    checks = [
        _group_entry_shapes(ctx),
        _group_top_level(ctx),
        _group_ordering(ctx),
        _group_char_caps(ctx),
        _group_file_set(ctx),
        _group_meta_lines(ctx),
        _group_receipt(ctx),
        _group_freshness(ctx),
    ]
    json_handler.log_operation(
        "trinity_groups_scored",
        {"branch": ctx.get("branch"), "failed": [c["name"] for c in checks if not c["passed"]]},
    )
    return checks
