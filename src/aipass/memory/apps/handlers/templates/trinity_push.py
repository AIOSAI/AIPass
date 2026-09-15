# =================== AIPass ====================
# Name: trinity_push.py
# Description: The trinity push — frame rebuild, vectorize-verify-prune, todos to the backlog file
# Version: 1.2.1
# Created: 2026-08-27
# Modified: 2026-09-15
# =============================================

"""Trinity Push Handler

The one lane that brings a branch's ``.trinity/`` memory files to the trinity
standard.  A full push does three things per branch, in this order:

1. **Re-render the machine frame.** ``document_metadata`` is rebuilt as a
   CLOSED set — any key the standard does not name is pruned, ``status`` with
   them — ``managed_by`` takes the exact branch directory name, ``_usage`` and
   the ``guidelines`` block come verbatim from the gold-source templates, and
   all four ``*_meta`` lines are re-composed from config + template prose.
2. **Prune every non-canonical entry.**  Pruning is a safety feature, not a
   deletion: the entry is vectorized VERBATIM to this branch's store first,
   the ingestion is VERIFIED by reading it back, and only then is it removed
   from the live file.  Nothing is ever transformed or summarized — a machine
   that cannot faithfully transform must not transform.  Canonical entries
   carry over untouched.  A todo never goes to vectors: see below.
3. **Write one canonical session note** in the branch's own ``sessions[]``
   saying where its entries and todos went and how to get them back.

TODOS GO TO A FILE, NEVER TO VECTORS (DPLAN-0345)
-------------------------------------------------
A todo is a sticky note on a pad: canonical shape ``{number, date, task,
priority?}`` with ``task`` inside its entry_limits cap, and at most
``rollover.defaults.local.todos.count`` of them.  A todo that is not canonical
(``status`` present, a required field missing, the task over its cap, a wrong
type, any key outside the shape) leaves the pad for
``.backup/todo/<branch_dir>/backlog.json`` with reason ``non-canonical``.
After that, when the canonical todos left exceed the count, the oldest by
number follow with reason ``overflow``.

The todo lands in the backlog json-equal: never reshaped, never shortened,
never vectorized (a restored then re-rolled vector copy is the CPLAN-0002
duplicate).  ``todo_roll.append_to_backlog`` appends, replaces atomically and
reads back BEFORE the pad is written; a failed or mismatched append refuses
the branch whole and leaves its local.json untouched.

There is no migration code.  Without ``status`` in the shape every legacy todo
is non-canonical, so the first push empties those pads into their backlogs and
every later push finds nothing to move.

THE ONE LAW, wearing a new hat
------------------------------
``vectorize -> verify -> prune`` is an ORDER, and the verify step is the
whole point of it.  A store call that answers "success" is the writer's
opinion; reading the vector back by ID and comparing it byte-for-byte to what
was sent is evidence.  When verification fails for any entry, NOTHING is
pruned from that branch — the file is left exactly as found and the branch is
reported as refused.  This is the same law that
``chroma_subprocess.vectorize_and_store`` was built for after @ai_mail deleted
four months of mail on the strength of an unread success flag.

Scope
-----
``--branch`` pushes a single branch.  Fleet mode covers the DPLAN scope: every
active citizen in ``AIPASS_REGISTRY.json`` plus the four named resident
projects.  The resident list is a NAMED CONSTANT, never a glob over
``projects/`` — a glob would silently sweep in on-hold projects nobody put in
scope (``marketstand`` is marked ``active`` inside a directory named
``(on _hold)``; it is out of scope and stays out until someone says otherwise).

A branch whose files cannot be read is REFUSED BY NAME, never skipped
silently: a push that quietly passes over the files it could not open reports
a clean fleet it never touched.
"""

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from aipass.memory.apps.handlers import repo_root
from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader
from aipass.memory.apps.handlers.json import entry_limits
from aipass.memory.apps.handlers.monitor import registry_scope
from aipass.memory.apps.handlers.json.memory_files import read_memory_file_data, write_memory_file_simple
from aipass.memory.apps.handlers.templates import receipt
from aipass.memory.apps.handlers.rollover import todo_roll
from aipass.memory.apps.handlers.tracking import tab_renderer
from aipass.memory.apps.handlers.repo_root import module_file

# =============================================================================
# PATHS
# =============================================================================

_MEMORY_ROOT = module_file(__file__).parents[3]
_TEMPLATES_DIR = _MEMORY_ROOT / "templates"


def _find_repo_root() -> Path:
    """Repo root for this lane — resolved by ``handlers/repo_root.py``.

    Kept as a local name because callers and tests patch it here. The body is a
    delegation on purpose: this function used to be one of ten byte-identical
    copies, so the first cure landed on one file and CI went red on the next.

    Returns:
        The directory holding AIPASS_REGISTRY.json, or the source tree. Never
        the process working directory.
    """
    return repo_root.find_repo_root(caller="trinity_push")


_REPO_ROOT = _find_repo_root()

# The fleet is defined ONCE, in registry_scope — the push resolved its own
# scope from a private constant while rollover/lint/health walked the registry
# lane and reached three branches fewer. Re-exported here because this module's
# readers look for it here, but there is only one list.
#
# There is no resident LIST to re-export any more. registry_scope discovers
# candidates under projects/ and classifies them on the passport's declared
# residency, so this lane asks it a question instead of copying an answer.
CORE_REGISTRY = registry_scope.CORE_REGISTRY

# =============================================================================
# THE CANONICAL SHAPE (mirrors seedgo/apps/handlers/aipass_standards/trinity.md)
# =============================================================================

TRINITY_DIR = ".trinity"

_FILE_NAMES = {"local": "local.json", "observations": "observations.json"}

_TEMPLATE_FILES = {"local": "LOCAL.template.json", "observations": "OBSERVATIONS.template.json"}

_DOC_NAME_SUFFIX = {"local": ".LOCAL", "observations": ".OBSERVATIONS"}

# document_metadata is a CLOSED set — Patrick's ruling. Anything not named
# here is pruned from the block, `status` included (health is computed at run
# time; a stored copy of a derivable fact is a second source of truth).
DOC_META_FIELDS = (
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

_KEY_ORDER = {
    "local": [
        "document_metadata",
        "todos_meta",
        "todos",
        "key_learnings_meta",
        "key_learnings",
        "sessions_meta",
        "sessions",
    ],
    "observations": [
        "document_metadata",
        "guidelines",
        "observations_meta",
        "observations",
    ],
}

_SECTIONS = {"local": ("todos", "key_learnings", "sessions"), "observations": ("observations",)}

TODO_SECTION = "todos"

_TYPE_INT = "int"
_TYPE_STR = "str"
_TYPE_STR_LIST = "list[str]"

ENTRY_RULES: dict[str, dict[str, dict[str, str]]] = {
    "sessions": {
        "required": {"number": _TYPE_INT, "date": _TYPE_STR, "summary": _TYPE_STR, "status": _TYPE_STR},
        "optional": {"tags": _TYPE_STR_LIST},
    },
    "key_learnings": {
        "required": {"number": _TYPE_INT, "date": _TYPE_STR, "key": _TYPE_STR, "value": _TYPE_STR},
        "optional": {},
    },
    # DPLAN-0345: no `status`. What is on the pad IS the status; done = deleted.
    "todos": {
        "required": {"number": _TYPE_INT, "date": _TYPE_STR, "task": _TYPE_STR},
        "optional": {"priority": _TYPE_STR},
    },
    "observations": {
        "required": {"number": _TYPE_INT, "date": _TYPE_STR, "note": _TYPE_STR, "tags": _TYPE_STR_LIST},
        "optional": {},
    },
}


def _type_ok(value: Any, spec: str) -> bool:
    """Whether *value* matches the contract's type name for a field."""
    if spec == _TYPE_INT:
        return isinstance(value, int) and not isinstance(value, bool)
    if spec == _TYPE_STR:
        return isinstance(value, str)
    if spec == _TYPE_STR_LIST:
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    return False


def _cap_problem(entry: dict, cap_spec: Any) -> str | None:
    """Whether *entry*'s canonical text field busts its configured cap.

    Shape and size are two different scan groups in the standard, and an entry
    can pass one while failing the other: a perfectly shaped 315-char session
    summary under a 300 cap is canonical to look at and still leaves its
    branch short of 100. It is also exactly the entry @hooks' edit_gate
    grandfathers today — the clause only becomes moot post-push if the push
    actually takes these out, so an over-cap entry is pruned like any other
    non-canonical one, and its full text survives in the vector store.
    """
    if not isinstance(cap_spec, dict):
        return None
    field = cap_spec.get("field")
    max_chars = cap_spec.get("max_chars")
    if not isinstance(field, str) or not isinstance(max_chars, int) or isinstance(max_chars, bool):
        return None
    value = entry.get(field)
    if not isinstance(value, str) or len(value) <= max_chars:
        return None
    return f"'{field}' is {len(value)} chars, over its {max_chars}-char cap"


def entry_problems(section: str, entry: Any, cap_spec: Any = None) -> list[str]:
    """Name every way *entry* departs from its section's canonical shape.

    Returns an empty list for a canonical entry. The messages are written to
    be read by the agent whose file it is, so they name fields, not rules.

    Args:
        section: One of todos, key_learnings, sessions, observations.
        entry: The entry as it sits in the file.
        cap_spec: This section's resolved ``{field, max_chars}``, or None to
            check shape only. When given, an over-cap entry is non-canonical.

    Returns:
        Human-readable problem strings, empty when the entry is canonical.
    """
    rules = ENTRY_RULES.get(section)
    if rules is None:
        return [f"unknown section '{section}'"]
    if not isinstance(entry, dict):
        return [f"entry must be an object, found {type(entry).__name__}"]

    problems = []
    for field, spec in rules["required"].items():
        if field not in entry:
            problems.append(f"missing '{field}'")
        elif not _type_ok(entry[field], spec):
            problems.append(f"'{field}' must be {spec}, found {type(entry[field]).__name__}")
    for field, spec in rules["optional"].items():
        if field in entry and not _type_ok(entry[field], spec):
            problems.append(f"'{field}' must be {spec}, found {type(entry[field]).__name__}")

    allowed = set(rules["required"]) | set(rules["optional"])
    extra = [key for key in entry if key not in allowed]
    if extra:
        problems.append("extra field(s) " + ", ".join(sorted(extra)) + " — the entry shape is closed")

    over_cap = _cap_problem(entry, cap_spec)
    if over_cap:
        problems.append(over_cap)
    return problems


def is_canonical(section: str, entry: Any, cap_spec: Any = None) -> bool:
    """True when *entry* may carry over into the pushed file untouched."""
    return not entry_problems(section, entry, cap_spec)


# =============================================================================
# THE PAD RULE (todos, DPLAN-0345)
# =============================================================================

DEFECT_STATUS = "status present"
DEFECT_OVER_CAP = "task over cap"
DEFECT_MISSING = "missing field"
DEFECT_UNKNOWN = "unknown field"
DEFECT_TYPE = "wrong type"
DEFECT_NOT_OBJECT = "not an object"
DEFECT_OVERFLOW = "overflow"

# A todo with several defects is counted ONCE, under its first match here.
# This is the order todo_defect checks in; the report prints it as stated.
DEFECT_ORDER = (
    DEFECT_NOT_OBJECT,
    DEFECT_STATUS,
    DEFECT_OVER_CAP,
    DEFECT_MISSING,
    DEFECT_UNKNOWN,
    DEFECT_TYPE,
    DEFECT_OVERFLOW,
)


def todo_defect(entry: Any, cap_spec: Any = None) -> str | None:
    """The first reason, in :data:`DEFECT_ORDER`, that *entry* is not a canonical todo.

    Args:
        entry: The todo as it sits on the pad.
        cap_spec: The branch's resolved todos ``{field, max_chars}``.

    Returns:
        One ``DEFECT_*`` label, or None when the todo is canonical.
    """
    if not isinstance(entry, dict):
        return DEFECT_NOT_OBJECT
    rules = ENTRY_RULES[TODO_SECTION]
    allowed = set(rules["required"]) | set(rules["optional"])
    if "status" in entry:
        return DEFECT_STATUS
    if _cap_problem(entry, cap_spec):
        return DEFECT_OVER_CAP
    if any(field not in entry for field in rules["required"]):
        return DEFECT_MISSING
    if any(key not in allowed for key in entry):
        return DEFECT_UNKNOWN
    if entry_problems(TODO_SECTION, entry, cap_spec):
        return DEFECT_TYPE
    return None


def _defect_label(defect: str, cap_spec: Any) -> str:
    """A defect as the report prints it: the over-cap label names the configured cap."""
    max_chars = cap_spec.get("max_chars") if isinstance(cap_spec, dict) else None
    if defect == DEFECT_OVER_CAP and isinstance(max_chars, int) and not isinstance(max_chars, bool):
        return f"task over {max_chars}"
    return defect


def _todo_move(index: int, entry: Any, reason: str, defect: str) -> dict:
    """One todo leaving the pad: where it sat, why, and the entry itself (never copied into a new shape)."""
    return {
        "index": index,
        "number": entry.get("number") if isinstance(entry, dict) else None,
        "reason": reason,
        "defect": defect,
        "entry": entry,
    }


def plan_todos(raw: list, cap_spec: Any, count: int | None) -> dict:
    """Split one pad into what stays and what moves to the backlog. Pure, no I/O.

    Non-canonical todos move first (reason ``non-canonical``, file order). Then,
    when the canonical todos left exceed *count*, the oldest by number move
    (reason ``overflow``, oldest first). A None *count* rolls nothing.

    Args:
        raw: The todos list from local.json.
        cap_spec: The branch's resolved todos ``{field, max_chars}``.
        count: The pad size from ``config_loader.get_todos_count``.

    Returns:
        ``{"kept": [...], "moves": [...], "reasons": {label: count}}`` with the
        reasons in :data:`DEFECT_ORDER`.
    """
    kept: list[int] = []
    moves: list[dict] = []
    for index, entry in enumerate(raw):
        defect = todo_defect(entry, cap_spec)
        if defect is None:
            kept.append(index)
        else:
            moves.append(_todo_move(index, entry, todo_roll.REASON_NON_CANONICAL, defect))

    if count is not None and len(kept) > count:
        oldest = sorted(kept, key=lambda index: (raw[index]["number"], index))[: len(kept) - count]
        moves.extend(_todo_move(index, raw[index], todo_roll.REASON_OVERFLOW, DEFECT_OVERFLOW) for index in oldest)
        kept = [index for index in kept if index not in set(oldest)]

    tally = {defect: sum(1 for move in moves if move["defect"] == defect) for defect in DEFECT_ORDER}
    reasons = {_defect_label(defect, cap_spec): number for defect, number in tally.items() if number}
    return {"kept": [raw[index] for index in kept], "moves": moves, "reasons": reasons}


def todos_chars(moves: list[dict]) -> int:
    """How big the moving todos are: ``len(json.dumps(<entries as one list>, ensure_ascii=False))``.

    The measure behind DPLAN-0345's "Todo JSON is 106,408 chars".
    """
    if not moves:
        return 0
    return len(json.dumps([move["entry"] for move in moves], ensure_ascii=False))


def move_todos(plan: dict) -> dict:
    """Append a plan's todo moves to its backlog: one verified append per reason, in plan order.

    Args:
        plan: A plan from :func:`plan_branch`.

    Returns:
        ``{"moved": int, "error": str | None}``. Any error means the pad must
        not be written.
    """
    outcome: dict[str, Any] = {"moved": 0, "error": None}
    moves = plan.get("todo_moves", [])
    for reason in (todo_roll.REASON_NON_CANONICAL, todo_roll.REASON_OVERFLOW):
        group = [move["entry"] for move in moves if move["reason"] == reason]
        if not group:
            continue
        appended = todo_roll.append_to_backlog(plan["backlog"], plan["branch"], group, reason)
        if not appended["success"]:
            both = outcome["moved"]
            doubled = f"; the {both} appended before it sit in the backlog AND on the pad" if both else ""
            outcome["error"] = (
                f"backlog append of {len(group)} {reason} todo(s) not verified ({appended['error']}){doubled}"
                " — local.json untouched"
            )
            return outcome
        outcome["moved"] += appended["appended"]
    return outcome


# =============================================================================
# SCOPE
# =============================================================================


def resolve_scope(branch: str | None = None) -> dict:
    """Resolve which branches this run covers.

    Args:
        branch: A single branch directory name, or None for the whole fleet.

    Returns:
        ``{"branches": [{"name", "path", "registry"}], "error": str | None}``.
        An unknown ``branch`` is an error, never an empty run: silence would
        read as "nothing to do" for a name that was simply mistyped.
    """
    # Converged on registry_scope 2026-08-28 (DPLAN-0319). This lane used to
    # walk a named resident tuple itself, which meant the "one definition of the
    # fleet" had two implementations that only agreed by coincidence — and this
    # copy did no residency classification at all, so the push would have kept
    # sweeping projects by the retired rules while every other lane read the
    # passport. Same list, same order, one place.
    # ...and narrowed again 2026-08-30 (FPLAN-0460 phase 4). registry_scope
    # 3.0.0 added the external tier, so `fleet_branches` now answers with
    # citizens living in OTHER repositories. Every other consumer of that list
    # reads; this lane WRITES template files into each branch it resolves. The
    # external tier build never writes outside this repo and the push does not
    # get to be the exception, so the scope stops at the repo edge here — at the
    # one consumer that acts on the list, not in the reader that serves them all.
    branches = [
        item
        for item in registry_scope.fleet_branches(_REPO_ROOT, name_from="path")
        if item.get("residency") != registry_scope.RESIDENCY_EXTERNAL
    ]

    if branch is None:
        return {"branches": branches, "error": None}

    wanted = branch.lstrip("@").lower()
    matches = [item for item in branches if item["name"].lower() == wanted]
    if not matches:
        known = ", ".join(sorted(item["name"] for item in branches))
        return {"branches": [], "error": f"Unknown branch: @{branch.lstrip('@')} — in scope: {known}"}
    return {"branches": matches, "error": None}


# =============================================================================
# THE FRAME
# =============================================================================


def _load_template(file_key: str) -> dict:
    """Read a gold-source template. Raises rather than inventing structure."""
    return json.loads((_TEMPLATES_DIR / _TEMPLATE_FILES[file_key]).read_text(encoding="utf-8"))


def _today() -> str:
    """Today as YYYY-MM-DD — the date shape every entry and stamp uses."""
    return datetime.now().strftime("%Y-%m-%d")


def _template_tags(template: dict, branch_name: str) -> list[str]:
    """The template's tag list with ``{{BRANCH}}`` resolved."""
    tags = template.get("document_metadata", {}).get("tags", [])
    return [tag.replace("{{BRANCH}}", branch_name) for tag in tags if isinstance(tag, str)]


def build_doc_metadata(current: Any, file_key: str, branch_name: str) -> dict:
    """Rebuild ``document_metadata`` as the standard's CLOSED set.

    Only ``created`` survives from the branch's own file — it is history no
    template can supply, and inventing it would date every citizen to today.
    Everything else is machine-owned and comes from the template or from this
    push: a key the standard does not name is dropped, ``status`` included.

    Args:
        current: The file's existing ``document_metadata`` (may be anything).
        file_key: ``local`` or ``observations``.
        branch_name: The branch DIRECTORY name — exact casing, per the ruling.

    Returns:
        A fresh dict carrying exactly ``DOC_META_FIELDS``, in standard order.
    """
    existing = current if isinstance(current, dict) else {}
    template = _load_template(file_key)
    tmpl_meta = template.get("document_metadata", {})

    created = existing.get("created")
    if not isinstance(created, str) or not created:
        created = _today()

    return {
        "document_type": tmpl_meta.get("document_type", ""),
        "document_name": f"{branch_name}{_DOC_NAME_SUFFIX[file_key]}",
        "version": tmpl_meta.get("version", ""),
        "schema_version": tmpl_meta.get("schema_version", ""),
        "created": created,
        "last_updated": _today(),
        "managed_by": branch_name,
        "tags": _template_tags(template, branch_name),
        "_usage": tab_renderer.template_usage(file_key),
    }


def _frame_changes(before: dict, after: dict, file_key: str) -> list[str]:
    """Describe what the frame rebuild changes, for the dry-run report."""
    changes: list[str] = []
    raw_meta = before.get("document_metadata")
    old_meta: dict = raw_meta if isinstance(raw_meta, dict) else {}
    new_meta = after["document_metadata"]

    dropped = [key for key in old_meta if key not in DOC_META_FIELDS]
    if dropped:
        changes.append(f"document_metadata: prune non-standard key(s) {', '.join(sorted(dropped))}")
    for field in DOC_META_FIELDS:
        if field == "last_updated":
            continue
        if old_meta.get(field) != new_meta[field]:
            changes.append(f"document_metadata.{field}: rewritten from the standard")

    for section in _SECTIONS[file_key]:
        key = f"{section}_meta"
        if before.get(key) != after[key]:
            changes.append(f"{key}: re-composed from config + template prose")

    if file_key == "observations" and before.get("guidelines") != after["guidelines"]:
        changes.append("guidelines: overwritten with the template text verbatim")

    stray = [key for key in before if key not in _KEY_ORDER[file_key]]
    if stray:
        changes.append(f"top level: prune stray section(s) {', '.join(sorted(stray))}")
    return changes


def build_frame(
    before: dict, file_key: str, branch_name: str, entries: dict, config: dict, todo_ctx: dict | None = None
) -> dict:
    """Assemble the canonical file: machine frame around the surviving entries.

    Args:
        before: The file as read from disk.
        file_key: ``local`` or ``observations``.
        branch_name: The branch directory name.
        entries: ``{section: [surviving entries]}``.
        config: The parsed memory.config.json.
        todo_ctx: ``tab_renderer.todo_context`` for the todos tab. When None
            for a local file it is derived here from the pad as found and the
            branch's backlog at its default path.

    Returns:
        A new dict with exactly the canonical top-level keys, in order.
    """
    rollover_cfg = config.get("rollover", {})
    entry_limits_cfg = config.get("entry_limits", {})

    meta = build_doc_metadata(before.get("document_metadata"), file_key, branch_name)
    data: dict[str, Any] = {"document_metadata": meta}

    if file_key == "observations":
        data["guidelines"] = copy.deepcopy(_load_template("observations").get("guidelines", {}))
    elif todo_ctx is None:
        pad = before.get(TODO_SECTION)
        todo_ctx = tab_renderer.todo_context(branch_name, [] if pad is None else pad)

    for section in _SECTIONS[file_key]:
        data[f"{section}_meta"] = tab_renderer.compose_meta(
            section, rollover_cfg, entry_limits_cfg, branch_name, todo_ctx if section == TODO_SECTION else None
        )
        data[section] = entries.get(section, [])

    return {key: data[key] for key in _KEY_ORDER[file_key] if key in data}


# =============================================================================
# PLANNING (read-only)
# =============================================================================


def resolve_caps(config: dict, branch_name: str) -> dict:
    """The char caps this branch is actually held to, from the ONE resolver.

    Shares ``entry_limits.resolve_entry_types`` with the write gate and the
    tab renderer, so the size the push prunes on is the same number the gate
    refuses on and the same number the branch's own meta line advertises.
    """
    return entry_limits.resolve_entry_types(config.get("entry_limits", {}), branch_name)


def _plan_file(branch_name: str, trinity: Path, file_key: str, config: dict, backlog: dict | None = None) -> dict:
    """Plan one file: what gets pruned, what moves to the backlog, what carries over, what the frame changes.

    Returns a plan dict, or one carrying ``error`` when the file cannot be
    read. A file that cannot be read is never treated as empty — rebuilding a
    frame around no entries would delete a branch's whole memory.

    *backlog* is the branch's ``todo_roll.read_backlog`` state, used to derive
    the todos tab's ``next #N`` from the pad as found plus the backlog as found
    (the same number set the pad and backlog hold after the move).
    """
    path = trinity / _FILE_NAMES[file_key]
    plan: dict[str, Any] = {
        "file_key": file_key,
        "path": path,
        "error": None,
        "prunes": [],
        "todo_moves": [],
        "todo_reasons": {},
        "todos_count": None,
        "carried": 0,
        "todos_seen": 0,
        "frame_changes": [],
        "before": None,
        "after": None,
    }

    if not path.is_file():
        plan["error"] = f"{_FILE_NAMES[file_key]}: not found"
        return plan

    before = read_memory_file_data(path)
    if not isinstance(before, dict):
        plan["error"] = f"{_FILE_NAMES[file_key]}: unreadable or not a JSON object"
        return plan

    caps = resolve_caps(config, branch_name)
    survivors: dict[str, list] = {}
    for section in _SECTIONS[file_key]:
        raw = before.get(section)
        if raw is None:
            survivors[section] = []
            continue
        if not isinstance(raw, list):
            plan["error"] = f"{_FILE_NAMES[file_key]}: '{section}' must be a list, found {type(raw).__name__}"
            return plan
        if section == TODO_SECTION:
            # Counted whether or not any of them move. A branch that owes
            # nothing and a branch whose pad was emptied both keep zero; only
            # the count SEEN tells those two apart (@ai_mail, 2026-08-27).
            count = config_loader.get_todos_count(branch_name, config.get("rollover", {}))
            split = plan_todos(raw, caps.get(section), count)
            plan.update(todos_count=count, todo_moves=split["moves"], todo_reasons=split["reasons"])
            plan["todos_seen"] += len(raw)
            plan["carried"] += len(split["kept"])
            survivors[section] = split["kept"]
            continue
        kept = []
        for index, entry in enumerate(raw):
            problems = entry_problems(section, entry, caps.get(section))
            if not problems:
                kept.append(entry)
                plan["carried"] += 1
                continue
            record = {
                "file_key": file_key,
                "container": section,
                "index": index,
                "number": entry.get("number") if isinstance(entry, dict) else None,
                "reason": "; ".join(problems),
                "entry": entry,
            }
            plan["prunes"].append(record)
        survivors[section] = kept

    todo_ctx = None
    if file_key == "local":
        pad = before.get(TODO_SECTION)
        todo_ctx = tab_renderer.todo_context(branch_name, [] if pad is None else pad, backlog)
    after = build_frame(before, file_key, branch_name, survivors, config, todo_ctx=todo_ctx)
    plan["before"] = before
    plan["after"] = after
    plan["frame_changes"] = _frame_changes(before, after, file_key)
    return plan


def _backlog_display(path: Path) -> str:
    """The backlog path relative to the repo root when it sits inside it, else in full."""
    try:
        return Path(path).relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        logger.debug(f"[trinity_push] {path} sits outside the repo root - shown in full")
        return str(path)


def plan_branch(branch_name: str, branch_path: Path, config: dict, backlog_path: Path | None = None) -> dict:
    """Plan a whole branch — pure and read-only, the dry-run's only source.

    Args:
        branch_name: Branch directory name.
        branch_path: Branch root (the directory holding ``.trinity/``).
        config: The parsed memory.config.json.
        backlog_path: This branch's todo backlog file; defaults to
            ``todo_roll.backlog_path_for(branch_name)``.

    Returns:
        ``{"branch", "path", "files": [file plans], "errors": [...],
        "prunes": [...], "todo_moves": [...], "todo_reasons": {...},
        "todos_count", "backlog", "backlog_display", "backlog_exists",
        "carried": int, "strays": [...]}``. ``todo_moves`` are the todos that
        leave the pad for the backlog.
    """
    trinity = Path(branch_path) / TRINITY_DIR
    backlog = Path(backlog_path) if backlog_path is not None else todo_roll.backlog_path_for(branch_name)
    plan: dict[str, Any] = {
        "branch": branch_name,
        "config": config,
        "path": Path(branch_path),
        "trinity": trinity,
        "files": [],
        "errors": [],
        "prunes": [],
        "todo_moves": [],
        "todo_reasons": {},
        "todos_count": None,
        "backlog": backlog,
        "backlog_display": _backlog_display(backlog),
        "backlog_exists": False,
        "carried": 0,
        "todos_seen": 0,
        "strays": [],
    }

    if not trinity.is_dir():
        plan["errors"].append(f"{branch_name}: no .trinity/ directory at {trinity}")
        return plan

    plan["strays"] = _trinity_strays(trinity)
    state = todo_roll.read_backlog(backlog)
    plan["backlog_exists"] = state["exists"]

    for file_key in ("local", "observations"):
        file_plan = _plan_file(branch_name, trinity, file_key, config, state)
        plan["files"].append(file_plan)
        if file_plan["error"]:
            plan["errors"].append(f"{branch_name}: {file_plan['error']}")
            continue
        plan["prunes"].extend(file_plan["prunes"])
        plan["carried"] += file_plan["carried"]
        plan["todos_seen"] += file_plan["todos_seen"]
        if file_key == "local":
            plan.update(
                todo_moves=file_plan["todo_moves"],
                todo_reasons=file_plan["todo_reasons"],
                todos_count=file_plan["todos_count"],
            )

    if plan["todo_moves"] and state["error"]:
        # The pad may only shrink into a backlog that can be appended to.
        plan["errors"].append(f"{branch_name}: {len(plan['todo_moves'])} todo(s) cannot move — {state['error']}")
    return plan


_CANONICAL_TRINITY_FILES = (
    "passport.json",
    "local.json",
    "observations.json",
    "README.md",
    ".template_version.json",
)

# Backups written by two NAMED migrations, not unexplained files: `.pre_v2_backup`
# by @spawn's `migrate-passports --confirm` (DPLAN-0319) and `.pre_v3_backup` by
# this branch's own v3 rollover. 54 of them across 22 branches made every branch
# report "NOT push scope" on every run forever — a permanent line that says
# nothing, since the push neither needs them gone nor may delete them. An
# accounted-for artifact of a migration someone can name is not a stray. Genuinely
# unexplained files in a `.trinity/` still are, and are still reported (FPLAN-0492
# wave 6; measured by @spawn 2026-09-07, ruled by @devpulse).
_KNOWN_MIGRATION_BACKUPS = (".pre_v2_backup", ".pre_v3_backup")


def _trinity_strays(trinity: Path) -> list[str]:
    """Unexplained names in ``.trinity/`` — not canonical, not a known backup.

    Reported, never removed. Deleting another branch's backup or status file
    is a destructive act outside this lane's three-part mandate; the dry-run
    surfaces them so the call stays Patrick's.
    """
    try:
        return sorted(
            item.name + ("/" if item.is_dir() else "")
            for item in trinity.iterdir()
            if item.name not in _CANONICAL_TRINITY_FILES and not item.name.endswith(_KNOWN_MIGRATION_BACKUPS)
        )
    except OSError as exc:
        logger.warning(f"[trinity_push] Cannot list {trinity}: {exc}")
        return []


# =============================================================================
# THE ARCHIVE — vectorize, then VERIFY, and only then may anything be pruned
# =============================================================================


def archive_text(prune: dict) -> str:
    """Serialize a pruned entry VERBATIM for the vector store.

    The stored document is the entry itself as JSON — not a summary, not a
    rendering. A machine that cannot faithfully transform must not transform,
    and the whole promise of the push ("your entries are recoverable") rests
    on the archived copy being the entry rather than a description of it.
    """
    return json.dumps(prune["entry"], ensure_ascii=False, indent=2)


def _archive_metadata(branch_name: str, prune: dict, stamped: str) -> dict:
    """Vector metadata for one pruned entry — scalars only, ChromaDB's rule."""
    meta = {
        "branch": branch_name,
        "type": prune["file_key"],
        "array_field": prune["container"],
        "extracted_at": stamped,
        "source_file": _FILE_NAMES[prune["file_key"]],
        "archived_by": "trinity_push",
        "prune_reason": prune["reason"],
    }
    number = prune["number"]
    if isinstance(number, int) and not isinstance(number, bool):
        meta["entry_number"] = number
    entry = prune["entry"]
    if isinstance(entry, dict) and isinstance(entry.get("date"), str) and entry["date"]:
        meta["entry_date"] = entry["date"]
    return meta


def _verify_ingestion(store_client, collection: str, texts: list[str], ids: list[str], db_path) -> dict:
    """Read the stored vectors back and compare them byte-for-byte.

    The store call's own success flag is the writer's opinion; this is the
    evidence. Anything short of "every text is present and identical" is a
    failure, and a failure means nothing gets pruned.

    Args:
        store_client: Module exposing ``get_by_ids_subprocess``.
        collection: Collection the vectors were written to.
        texts: The exact documents that were sent.
        ids: The IDs the store reported writing.
        db_path: Chroma database path, or None for global.

    Returns:
        ``{"verified": bool, "error": str | None, "checked": int}``.
    """
    if len(ids) != len(texts):
        # The store dedupes byte-identical documents from the same file into
        # one ID, so a shorter id list is legitimate — but it must still be a
        # SUBSET relationship, never fewer unique documents than we can match.
        logger.info(f"[trinity_push] {collection}: {len(texts)} texts stored under {len(ids)} ids (dedupe)")

    wanted = dict(zip(ids, texts))
    reply = store_client.get_by_ids_subprocess(collection, sorted(set(ids)), db_path=db_path)
    if not reply.get("success"):
        return {"verified": False, "error": f"read-back failed: {reply.get('error')}", "checked": 0}

    found = reply.get("documents", {})
    missing = [vid for vid in wanted if vid not in found]
    if missing:
        return {
            "verified": False,
            "error": f"{len(missing)} of {len(set(ids))} vectors absent on read-back",
            "checked": len(found),
        }

    mismatched = [vid for vid, text in wanted.items() if found.get(vid) != text]
    if mismatched:
        return {
            "verified": False,
            "error": f"{len(mismatched)} vector(s) read back with different content",
            "checked": len(found),
        }
    return {"verified": True, "error": None, "checked": len(found)}


def archive_prunes(store_client, branch_name: str, prunes: list[dict], destinations: list) -> dict:
    """Vectorize every pruned entry and prove it landed in EVERY destination.

    Args:
        store_client: Module exposing ``vectorize_and_store_subprocess`` and
            ``get_by_ids_subprocess``.
        branch_name: Owning branch.
        prunes: The entries about to be removed.
        destinations: ``[(label, db_path)]`` — local store and global store.

    Returns:
        ``{"verified": bool, "error": str | None, "stored": int,
        "destinations": [{"label", "collection", "checked"}]}``.
        ``verified`` False means the caller MUST NOT prune anything.
    """
    if not prunes:
        return {"verified": True, "error": None, "stored": 0, "destinations": []}

    stamped = datetime.now().isoformat()
    by_type: dict[str, list[dict]] = {}
    for prune in prunes:
        by_type.setdefault(prune["file_key"], []).append(prune)

    report: list[dict] = []
    for label, db_path in destinations:
        for memory_type, group in by_type.items():
            texts = [archive_text(prune) for prune in group]
            metadatas = [_archive_metadata(branch_name, prune, stamped) for prune in group]
            stored = store_client.vectorize_and_store_subprocess(
                branch=branch_name, memory_type=memory_type, texts=texts, metadatas=metadatas, db_path=db_path
            )
            if not stored.get("success"):
                return {
                    "verified": False,
                    "error": f"{label}/{memory_type}: store refused — {stored.get('error')}",
                    "stored": 0,
                    "destinations": report,
                }

            collection = stored.get("collection", f"{branch_name.lower()}_{memory_type.lower()}")
            checked = _verify_ingestion(store_client, collection, texts, stored.get("ids", []), db_path)
            if not checked["verified"]:
                return {
                    "verified": False,
                    "error": f"{label}/{memory_type}: {checked['error']}",
                    "stored": 0,
                    "destinations": report,
                }
            report.append({"label": label, "collection": collection, "checked": checked["checked"]})

    return {"verified": True, "error": None, "stored": len(prunes), "destinations": report}


# =============================================================================
# THE NOTE
# =============================================================================

NOTE_STATUS = "completed"
NOTE_TAGS = ["system_push"]

NOTE_ARCHIVED = (
    "{count} non-canonical entries were safely vectorized to @memory in a system-wide "
    "trinity push, then pruned from these files — recall any of them anytime with "
    "drone @memory search."
)
NOTE_TODOS_NAMED = (
    "{count} todo(s) {labels} moved to {backlog} — nothing reshaped; pull back what you still need by hand."
)
NOTE_TODOS_COUNTED = "{count} todo(s) moved to {backlog} — nothing reshaped; pull back what you still need by hand."
NOTE_BACKLOG_FALLBACK = "this branch's todo backlog"


def _move_label(record: dict) -> str:
    """How one todo that moved to the backlog is named in the note.

    Its entry ``number`` when it has one, otherwise its position on the pad —
    a legacy todo can lack ``number`` entirely, and "the third one down" is
    still an address.
    """
    number = record.get("number")
    if isinstance(number, int) and not isinstance(number, bool):
        return f"#{number}"
    return f"[{record.get('index')}]"


def _fitting(candidates: list, max_chars: Any) -> str:
    """The first candidate summary that fits the cap; the shortest if none do.

    The note is measured by the same gate everything else was pruned against,
    so it degrades on purpose rather than being refused whole: naming forty
    todos will not fit 300 chars, and a branch told nothing is worse off than
    a branch told the count.
    """
    usable = [text for text in candidates if text]
    if not usable:
        return ""
    if not isinstance(max_chars, int) or isinstance(max_chars, bool):
        return usable[0]
    for text in usable:
        if len(text) <= max_chars:
            return text
    return min(usable, key=len)


def build_note(
    prune_count: int,
    sessions: list,
    moved: list | None = None,
    max_chars: Any = None,
    backlog: str | None = None,
) -> dict:
    """Compose the canonical session entry recording what the push did.

    The note is written in the branch's OWN sessions[] because that is where
    its agent will look. It is a canonical entry like any other — same four
    fields, same cap — so the note announcing the standard cannot itself
    violate it.

    It carries two independent facts. What was ARCHIVED (and how to get it
    back), and what MOVED — the todos that left the pad for the backlog file,
    named so their owner knows which lines went and where.

    Args:
        prune_count: How many entries were vectorized and removed.
        sessions: The surviving sessions, used only to continue the numbering.
        moved: The todo moves written to the backlog, if any.
        max_chars: This branch's session-summary cap, so the enumeration can
            step down to a count instead of busting the cap it announces.
        backlog: The backlog path as displayed (repo-relative).

    Returns:
        A canonical session entry.
    """
    numbers = [
        entry["number"] for entry in sessions if isinstance(entry, dict) and _type_ok(entry.get("number"), _TYPE_INT)
    ]
    archived = NOTE_ARCHIVED.format(count=prune_count) if prune_count else ""

    left = list(moved or [])
    if left:
        where = backlog or NOTE_BACKLOG_FALLBACK
        labels = ", ".join(_move_label(record) for record in left)
        named = NOTE_TODOS_NAMED.format(count=len(left), labels=labels, backlog=where)
        counted = NOTE_TODOS_COUNTED.format(count=len(left), backlog=where)
        candidates = [
            " ".join(part for part in (archived, named) if part),
            " ".join(part for part in (archived, counted) if part),
            archived,
        ]
    else:
        candidates = [archived]

    return {
        "number": (max(numbers) + 1) if numbers else 1,
        "date": _today(),
        "summary": _fitting(candidates, max_chars),
        "status": NOTE_STATUS,
        "tags": list(NOTE_TAGS),
    }


# =============================================================================
# APPLY
# =============================================================================


def _write_files(plan: dict, note: dict | None) -> tuple[int, list[str]]:
    """Write every planned file, adding *note* to local.json's sessions."""
    written = 0
    errors: list[str] = []
    for file_plan in plan["files"]:
        if file_plan["error"]:
            continue
        data = file_plan["after"]
        if note is not None and file_plan["file_key"] == "local":
            data = copy.deepcopy(data)
            data["sessions"] = [note] + data.get("sessions", [])
        if write_memory_file_simple(file_plan["path"], data):
            written += 1
        else:
            errors.append(f"{plan['branch']}: failed to write {file_plan['path'].name}")
    return written, errors


def apply_plan(plan: dict, store_client, destinations: list) -> dict:
    """Execute a branch plan: archive, verify, prune, note, stamp.

    The order is the contract. Verification failure short-circuits BEFORE any
    file is touched, so a branch whose archive could not be proven is left
    byte-identical to how it was found.

    Args:
        plan: A plan from :func:`plan_branch`.
        store_client: Module exposing the two subprocess calls.
        destinations: ``[(label, db_path)]`` for the archive.

    Returns:
        ``{"branch", "pruned", "carried", <todo summary keys>, "todos_moved",
        "written", "noted", "receipt", "errors", "refused"}``.
    """
    result = {
        "branch": plan["branch"],
        "pruned": 0,
        "carried": plan["carried"],
        **todo_summary(plan),
        "todos_moved": 0,
        "written": 0,
        "noted": False,
        "receipt": False,
        "errors": list(plan["errors"]),
        "refused": False,
    }

    if plan["errors"]:
        # A branch with an unreadable file is refused whole. Half-pushing it
        # would leave one file canonical and one not, with no record of which.
        result["refused"] = True
        return result

    archived = archive_prunes(store_client, plan["branch"], plan["prunes"], destinations)
    if not archived["verified"]:
        result["refused"] = True
        result["errors"].append(
            f"{plan['branch']}: NOTHING PRUNED — archive could not be verified ({archived['error']})"
        )
        logger.error(f"[trinity_push] {result['errors'][-1]}")
        return result

    # The pad is written only after the backlog took its todos and read back
    # json-equal. Archived vectors, if any, are already verified above; a push
    # re-run dedupes those, while a backlog append is never retried blind.
    moved = move_todos(plan)
    if moved["error"]:
        result["refused"] = True
        result["errors"].append(f"{plan['branch']}: NOTHING WRITTEN — {moved['error']}")
        logger.error(f"[trinity_push] {result['errors'][-1]}")
        return result
    result["todos_moved"] = moved["moved"]

    note = None
    # The note is minted only when something actually LEFT the files: entries
    # archived to vectors, or todos moved to the backlog. A second push finds
    # neither, so notes never stack and the push stays idempotent.
    if plan["prunes"] or plan.get("todo_moves"):
        local_plan = next((item for item in plan["files"] if item["file_key"] == "local"), None)
        sessions = local_plan["after"].get("sessions", []) if local_plan and not local_plan["error"] else []
        note_cap = resolve_caps(plan["config"], plan["branch"]).get("sessions")
        cap_chars = note_cap.get("max_chars") if isinstance(note_cap, dict) else None
        note = build_note(len(plan["prunes"]), sessions, plan.get("todo_moves"), cap_chars, plan.get("backlog_display"))
        # The note is measured by the same gate everything else was pruned
        # against. A push that leaves behind a note the standard would refuse
        # has re-introduced, in its own hand, the exact violation it came to
        # remove — and the branch would fail the checker on the one entry the
        # push authored. Refusing to write it beats writing it and lying.
        if not is_canonical("sessions", note, note_cap):
            reasons = "; ".join(entry_problems("sessions", note, note_cap))
            result["errors"].append(f"{plan['branch']}: note NOT written — it is not canonical ({reasons})")
            logger.error(f"[trinity_push] {result['errors'][-1]}")
            note = None

    written, errors = _write_files(plan, note)
    result["written"] = written
    result["errors"].extend(errors)
    result["pruned"] = len(plan["prunes"])
    result["noted"] = note is not None

    if written:
        stamp = receipt.write_receipt(plan["trinity"], receipt.STAMPED_BY_PUSH)
        result["receipt"] = bool(stamp["success"])
        if not stamp["success"]:
            result["errors"].append(f"{plan['branch']}: receipt not stamped — {stamp['error']}")

    return result


# =============================================================================
# THE LANE
# =============================================================================


def push(branch: str | None = None, dry_run: bool = True, store_client=None, backup_root: Path | None = None) -> dict:
    """Run the trinity push over one branch or the whole DPLAN scope.

    Args:
        branch: A single branch directory name, or None for fleet mode.
        dry_run: When True nothing is written anywhere — not the memory
            files, not the vector store, not the receipts, not a backlog.
        store_client: Injected vector-store client; defaults to
            ``push_store``. Tests pass a double.
        backup_root: The ``.backup`` directory the todo backlogs live under;
            defaults to ``<repo_root>/.backup``. Tests pass a scratch one.

    Returns:
        ``{"success", "dry_run", "scope", "branches": [...], "errors": [...]}``
        where each branch entry carries its own plan summary or outcome.
    """
    if store_client is None:
        from aipass.memory.apps.handlers.templates import push_store

        store_client = push_store

    scope = resolve_scope(branch)
    if scope["error"]:
        return {"success": False, "dry_run": dry_run, "scope": 0, "branches": [], "errors": [scope["error"]]}

    config = config_loader.load()

    out: dict[str, Any] = {
        "success": True,
        "dry_run": dry_run,
        "scope": len(scope["branches"]),
        "branches": [],
        "errors": [],
    }

    # The backlog is keyed by directory name, so a name shared anywhere in scope
    # would merge two branches' backlogs: resolved against the WHOLE scope.
    fleet = scope["branches"] if branch is None else resolve_scope()["branches"]
    for item in scope["branches"]:
        target = todo_roll.resolve_target(item["name"], fleet=fleet, backup_root=backup_root)
        plan = plan_branch(item["name"], item["path"], config, backlog_path=target["backlog"])
        if target["error"]:
            plan["errors"].append(f"{item['name']}: todos not movable — {target['error']}")
        if dry_run:
            out["branches"].append(_dry_entry(plan))
            out["errors"].extend(plan["errors"])
            continue
        applied = apply_plan(plan, store_client, _destinations(item["name"]))
        applied["strays"] = plan["strays"]
        out["branches"].append(applied)
        out["errors"].extend(applied["errors"])

    if out["errors"]:
        out["success"] = False

    json_handler.log_operation(
        "trinity_push",
        {
            "dry_run": dry_run,
            "scope": out["scope"],
            "branch": branch or "fleet",
            "pruned": sum(entry.get("pruned", 0) for entry in out["branches"]),
            "todos_to_backlog": sum(
                entry.get("todos_to_backlog" if dry_run else "todos_moved", 0) for entry in out["branches"]
            ),
            "errors": len(out["errors"]),
        },
        module_name="trinity_push",
    )
    return out


def _destinations(branch_name: str) -> list:
    """The two stores a pruned entry must reach: the branch's own, and global.

    A branch with no local ``.chroma`` gets the global store only — reported,
    not invented. Creating a store for a branch that has never had one is a
    side effect the push has no mandate for.
    """
    from aipass.memory.apps.handlers.rollover.orchestrator import get_branch_local_chroma_path

    destinations: list = []
    local_path = get_branch_local_chroma_path(branch_name)
    if local_path:
        destinations.append(("local", local_path))
    destinations.append(("global", None))
    return destinations


def todo_summary(plan: dict) -> dict:
    """The todo half of a branch's report entry, shared by the dry run and the real push.

    Args:
        plan: A plan from :func:`plan_branch`.

    Returns:
        ``{"todos_seen", "todos_count", "todos_to_backlog", "todos_chars",
        "todo_reasons", "todo_moves", "backlog_display", "backlog_exists"}``.
    """
    moves = list(plan.get("todo_moves", []))
    return {
        "todos_seen": plan.get("todos_seen", 0),
        "todos_count": plan.get("todos_count"),
        "todos_to_backlog": len(moves),
        "todos_chars": todos_chars(moves),
        "todo_reasons": dict(plan.get("todo_reasons", {})),
        "todo_moves": moves,
        "backlog_display": plan.get("backlog_display"),
        "backlog_exists": bool(plan.get("backlog_exists")),
    }


def _dry_entry(plan: dict) -> dict:
    """Shape one branch's dry-run report entry."""
    return {
        "branch": plan["branch"],
        "pruned": len(plan["prunes"]),
        "carried": plan["carried"],
        **todo_summary(plan),
        "prunes": plan["prunes"],
        "frame_changes": {item["file_key"]: item["frame_changes"] for item in plan["files"] if not item["error"]},
        "strays": plan["strays"],
        "errors": plan["errors"],
        "refused": bool(plan["errors"]),
    }
