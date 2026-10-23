# =================== AIPass ====================
# Name: trinity_push.py
# Description: The trinity push — frame rebuild, vectorize-verify-prune, todos to the backlog file
# Version: 1.7.0
# Created: 2026-08-27
# Modified: 2026-10-23
# =============================================

"""Trinity Push Handler

Order is the law: vectorize -> VERIFY by read-back -> prune; unverified, nothing is pruned.
Reference: docs/trinity_push.md
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


_MEMORY_ROOT = module_file(__file__).parents[3]
_TEMPLATES_DIR = _MEMORY_ROOT / "templates"


def _find_repo_root() -> Path:
    """Repo root for this lane — a local name because callers and tests patch it here."""
    return repo_root.find_repo_root(caller="trinity_push")


_REPO_ROOT = _find_repo_root()

# The fleet is defined ONCE, in registry_scope; re-exported for readers who look here.
CORE_REGISTRY = registry_scope.CORE_REGISTRY


TRINITY_DIR = ".trinity"

_FILE_NAMES = {"local": "local.json", "observations": "observations.json"}

_TEMPLATE_FILES = {"local": "LOCAL.template.json", "observations": "OBSERVATIONS.template.json"}

_DOC_NAME_SUFFIX = {"local": ".LOCAL", "observations": ".OBSERVATIONS"}

# A CLOSED set mirroring seedgo's trinity.md: anything not named is pruned, `status` included.
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

# The entry shape has ONE home, entry_limits.entry_types.<type>.fields in memory.config.json; never copy it here.
# Only the global fallback is cached: the push hands its resolved cap_spec in, so per_branch overrides bypass it.
_RULES_CACHE: dict[str, dict[str, dict[str, str]]] = {}


def _rules_from_fields(fields: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Split a closed field map into ``{"required": {name: type}, "optional": {name: type}}``."""
    required: dict[str, str] = {}
    optional: dict[str, str] = {}
    for name, spec in fields.items():
        if not isinstance(spec, dict):
            continue
        target = required if spec.get("required") else optional
        target[name] = str(spec.get("type", _TYPE_STR))
    return {"required": required, "optional": optional}


def entry_rules(section: str, cap_spec: Any = None) -> dict[str, dict[str, str]] | None:
    """Return the canonical shape for *section*, read from the config; *cap_spec*'s ``fields`` win.

    None when the config publishes no shape: an unknown section stays unknown, never an open one.
    """
    if isinstance(cap_spec, dict):
        fields = cap_spec.get("fields")
        if isinstance(fields, dict) and fields:
            return _rules_from_fields(fields)

    if section in _RULES_CACHE:
        return _RULES_CACHE[section]

    types = entry_limits.load_entry_limits("").get("entry_types", {})
    for name, type_def in types.items():
        fields = type_def.get("fields") if isinstance(type_def, dict) else None
        if isinstance(fields, dict) and fields:
            _RULES_CACHE[name] = _rules_from_fields(fields)
    return _RULES_CACHE.get(section)


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
    """Whether *entry*'s canonical text field busts its configured cap; over-cap is non-canonical."""
    if not isinstance(cap_spec, dict):
        return None
    field = cap_spec.get("field")
    max_chars = cap_spec.get("max_chars")
    if not isinstance(field, str) or not isinstance(max_chars, int) or isinstance(max_chars, bool):
        return None
    value = entry.get(field)
    allowed = entry_limits.allowed_chars(max_chars, cap_spec.get("tolerance_percent", 0))
    if not isinstance(value, str) or len(value) <= allowed:
        return None
    return f"'{field}' is {len(value)} chars, over its {max_chars}-char cap"


def entry_problems(section: str, entry: Any, cap_spec: Any = None) -> list[str]:
    """Name every way *entry* departs from its section's canonical shape; empty when canonical.

    The messages are read by the agent whose file it is, so they name fields, not rules.
    """
    rules = entry_rules(section, cap_spec)
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
    """The first reason, in :data:`DEFECT_ORDER`, that *entry* is not a canonical todo; None when canonical."""
    if not isinstance(entry, dict):
        return DEFECT_NOT_OBJECT
    rules = entry_rules(TODO_SECTION, cap_spec)
    if rules is None:
        # Unreachable while the config publishes a todos shape; an unjudgeable todo is moved, never carried.
        logger.warning("[trinity_push] No todos field shape in config — every todo reads as non-canonical")
        return DEFECT_UNKNOWN
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

    Non-canonical todos move first, then the oldest by number past *count*; a None *count* rolls nothing.
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
    """How big the moving todos are: ``len(json.dumps(<entries as one list>, ensure_ascii=False))``."""
    if not moves:
        return 0
    return len(json.dumps([move["entry"] for move in moves], ensure_ascii=False))


def _pad_as_found(plan: dict) -> list:
    """The todos list of the plan's local file as read, so its numbers reach the backlog's ``high_water``."""
    for file_plan in plan.get("files", []):
        before = file_plan.get("before")
        if file_plan.get("file_key") == "local" and isinstance(before, dict):
            pad = before.get(TODO_SECTION)
            return pad if isinstance(pad, list) else []
    return []


def move_todos(plan: dict) -> dict:
    """Append a plan's todo moves to its backlog: one verified append per reason, in plan order.

    Any ``error`` in the result means the pad must not be written.
    """
    outcome: dict[str, Any] = {"moved": 0, "error": None}
    moves = plan.get("todo_moves", [])
    pad = _pad_as_found(plan)
    for reason in (todo_roll.REASON_NON_CANONICAL, todo_roll.REASON_OVERFLOW):
        group = [move["entry"] for move in moves if move["reason"] == reason]
        if not group:
            continue
        appended = todo_roll.append_to_backlog(plan["backlog"], plan["branch"], group, reason, pad=pad)
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


def resolve_scope(branch: str | None = None) -> dict:
    """Resolve which branches this run covers; an unknown *branch* is an error, never an empty run."""
    # This lane WRITES, so its scope stops at the repo edge (no external tier). Strict, because it
    # matches by NAME: with the core registry unreadable, a same-named resident would be the match.
    try:
        fleet = registry_scope.fleet_branches(_REPO_ROOT, name_from="path", strict=True)
    except registry_scope.RegistryUnreadable as exc:
        logger.error(f"[trinity_push] REFUSED: {exc}")
        return {"branches": [], "error": f"REFUSED: {exc}"}
    branches = [item for item in fleet if item.get("residency") != registry_scope.RESIDENCY_EXTERNAL]

    if branch is None:
        return {"branches": branches, "error": None}

    wanted = branch.lstrip("@").lower()
    matches = [item for item in branches if item["name"].lower() == wanted]
    if not matches:
        known = ", ".join(sorted(item["name"] for item in branches))
        return {"branches": [], "error": f"Unknown branch: @{branch.lstrip('@')} — in scope: {known}"}
    return {"branches": matches, "error": None}


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

    Only ``created`` survives from the file: history no template can supply.
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
    """Assemble the canonical file: machine frame around the surviving entries, keys in canonical order."""
    rollover_cfg = config.get("rollover", {})
    entry_limits_cfg = config.get("entry_limits", {})

    meta = build_doc_metadata(before.get("document_metadata"), file_key, branch_name)
    data: dict[str, Any] = {"document_metadata": meta}

    if file_key == "observations":
        data["guidelines"] = copy.deepcopy(_load_template("observations").get("guidelines", {}))
    elif todo_ctx is None:
        pad = before.get(TODO_SECTION)
        todo_ctx = tab_renderer.todo_context(
            branch_name, [] if pad is None else pad, todos_meta=before.get("todos_meta")
        )

    for section in _SECTIONS[file_key]:
        data[f"{section}_meta"] = tab_renderer.compose_meta(
            section, rollover_cfg, entry_limits_cfg, branch_name, todo_ctx if section == TODO_SECTION else None
        )
        data[section] = entries.get(section, [])

    return {key: data[key] for key in _KEY_ORDER[file_key] if key in data}


def resolve_caps(config: dict, branch_name: str) -> dict:
    """The char caps this branch is held to, from the ONE resolver the write gate and tab renderer share."""
    return entry_limits.resolve_entry_types(config.get("entry_limits", {}), branch_name)


def _plan_file(branch_name: str, trinity: Path, file_key: str, config: dict, backlog: dict | None = None) -> dict:
    """Plan one file: what gets pruned, what moves to the backlog, what carries over, what the frame changes.

    An unreadable file is an ``error``, never empty: a frame around no entries would delete a branch's memory.
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
            # Only the count SEEN tells an empty pad from one that was emptied.
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
        todo_ctx = tab_renderer.todo_context(
            branch_name, [] if pad is None else pad, backlog, todos_meta=before.get("todos_meta")
        )
    after = build_frame(before, file_key, branch_name, survivors, config, todo_ctx=todo_ctx)
    plan["before"] = before
    plan["after"] = after
    plan["frame_changes"] = _frame_changes(before, after, file_key)
    return plan


def _backlog_display(path: Path) -> str:
    """The backlog path relative to the repo root when it sits inside it, else in full - posix separators either way."""
    try:
        return Path(path).relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        logger.debug(f"[trinity_push] {path} sits outside the repo root - shown in full")
        return Path(path).as_posix()


def plan_branch(branch_name: str, branch_path: Path, config: dict, backlog_path: Path | None = None) -> dict:
    """Plan a whole branch — pure and read-only, the dry-run's only source."""
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

# Backups from two named migrations (@spawn's migrate-passports, memory's v3 rollover): not strays.
_KNOWN_MIGRATION_BACKUPS = (".pre_v2_backup", ".pre_v3_backup")


def _trinity_strays(trinity: Path) -> list[str]:
    """Unexplained names in ``.trinity/`` — reported, never removed: deleting them is the owner's call."""
    try:
        return sorted(
            item.name + ("/" if item.is_dir() else "")
            for item in trinity.iterdir()
            if item.name not in _CANONICAL_TRINITY_FILES and not item.name.endswith(_KNOWN_MIGRATION_BACKUPS)
        )
    except OSError as exc:
        logger.warning(f"[trinity_push] Cannot list {trinity}: {exc}")
        return []


def archive_text(prune: dict) -> str:
    """Serialize a pruned entry VERBATIM for the vector store — never a summary: recovery rests on it."""
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
    """Read the stored vectors back and compare them byte-for-byte; the store's success flag is not evidence."""
    if len(ids) != len(texts):
        # The store dedupes byte-identical documents into one ID, so a shorter id list is legitimate.
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
    """Vectorize every pruned entry and prove it landed in EVERY destination; unverified, prune nothing."""
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
    """How one moved todo is named in the note: its ``number``, else its pad position (legacy todos may lack one)."""
    number = record.get("number")
    if isinstance(number, int) and not isinstance(number, bool):
        return f"#{number}"
    return f"[{record.get('index')}]"


def _fitting(candidates: list, max_chars: Any) -> str:
    """The first candidate summary that fits the cap; the shortest if none do — told the count beats told nothing."""
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
    """Compose the canonical session entry recording what was archived and which todos moved where."""
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
    """Execute a branch plan: archive, verify, prune, note, stamp — the order is the contract.

    Verification failure short-circuits BEFORE any file is touched.
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
        # Refused whole: half-pushing leaves one file canonical and one not, with no record of which.
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

    # The pad is written only after the backlog took its todos and read back json-equal.
    moved = move_todos(plan)
    if moved["error"]:
        result["refused"] = True
        result["errors"].append(f"{plan['branch']}: NOTHING WRITTEN — {moved['error']}")
        logger.error(f"[trinity_push] {result['errors'][-1]}")
        return result
    result["todos_moved"] = moved["moved"]

    note = None
    # Minted only when something LEFT the files, so notes never stack and the push stays idempotent.
    if plan["prunes"] or plan.get("todo_moves"):
        local_plan = next((item for item in plan["files"] if item["file_key"] == "local"), None)
        sessions = local_plan["after"].get("sessions", []) if local_plan and not local_plan["error"] else []
        note_cap = resolve_caps(plan["config"], plan["branch"]).get("sessions")
        cap_chars = note_cap.get("max_chars") if isinstance(note_cap, dict) else None
        note = build_note(len(plan["prunes"]), sessions, plan.get("todo_moves"), cap_chars, plan.get("backlog_display"))
        # The note meets the same gate it pruned against: a non-canonical note is refused, not written.
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


def push(branch: str | None = None, dry_run: bool = True, store_client=None, backup_root: Path | None = None) -> dict:
    """Run the trinity push over one branch or the whole scope; *dry_run* writes nothing anywhere."""
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
        destinations, local_store = _destinations(item["name"])
        applied = apply_plan(plan, store_client, destinations)
        applied["local_store"] = local_store
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


def _destinations(branch_name: str) -> tuple[list, str | None]:
    """The two stores a pruned entry must reach: the branch's own, and global.

    No local ``.chroma`` means global only, never a store invented; reason says why the local one is absent.
    """
    from aipass.memory.apps.handlers.rollover.orchestrator import local_store_lookup

    destinations: list = []
    local_path, reason = local_store_lookup(branch_name)
    if local_path:
        destinations.append(("local", local_path))
    destinations.append(("global", None))
    return destinations, reason


def todo_summary(plan: dict) -> dict:
    """The todo half of a branch's report entry, shared by the dry run and the real push."""
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
