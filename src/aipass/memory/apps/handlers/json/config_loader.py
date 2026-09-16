# =================== AIPass ====================
# Name: config_loader.py
# Description: Unified config loader for memory.config.json
# Version: 1.5.0
# Created: 2026-06-13
# Modified: 2026-09-15
# =============================================

"""
Unified Config Loader

Single entry point for reading memory.config.json.  Replaces the 9
ad-hoc readers that previously loaded the file independently, each
with subtly different defaults and error handling.

Provides a canonical DEFAULT_CONFIG, a non-mutating deep_merge, and a
load() that guarantees callers always receive a usable dict.

Doctrine (Patrick, S193): configs live inside JSONs, not inside code.
memory.config.json on disk is the RUNTIME AUTHORITY the operator edits.
DEFAULT_CONFIG exists so that file can be REGENERATED when it goes
missing — it is the regeneration seed, not a rival source of truth.
Keep the two in lockstep: what ships as default here is what an operator
finds in the file after a regen.  A file that exists but will not parse
is never written over (DPLAN-0206): defaults are served in memory only.

Usage:
    from aipass.memory.apps.handlers.json.config_loader import load, section

    cfg = load()
    rollover = section("rollover")
"""

import copy
import json
import os
from pathlib import Path
from typing import Any

from aipass.memory.apps.handlers.json import budget
from aipass.memory.apps.handlers.json import json_handler
from aipass.prax import logger
from aipass.memory.apps.handlers.repo_root import module_file

_MEMORY_ROOT = module_file(__file__).parents[3]
_CONFIG_PATH = _MEMORY_ROOT / "memory_json" / "custom_config" / "memory.config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "_meta": {
        "memory_pool": {
            "consumers": ["intake/pool_processor.py", "intake/auto_process.py", "monitor/memory_watcher.py"],
            "purpose": "Vectorize files dropped in memory_pool/, archive beyond keep_recent",
        },
        "entry_limits": {
            "consumers": [
                "json/entry_limits.py",
                "json/budget.py",
                "modules/lint.py",
                "templates/trinity_push.py",
            ],
            "purpose": "The closed entry shape: entry_types.<type>.fields is every field an entry may carry,"
            " its type and its cap (FPLAN-0593). file_budgets is the whole-file ceiling seedgo and the"
            " keep-count check read.",
        },
        "plans": {
            "consumers": ["intake/plans_processor.py", "monitor/memory_watcher.py"],
            "purpose": "Vectorize closed plan .md files into ChromaDB",
        },
        "rollover": {
            "consumers": [
                "monitor/detector.py",
                "monitor/memory_watcher.py",
                "rollover/extractor.py",
                "rollover/todo_roll.py",
                "templates/pusher.py",
            ],
            "purpose": "Entry-count thresholds that trigger .trinity rollover",
        },
    },
    "memory_pool": {
        "enabled": True,
        "process_on_startup": False,
        "keep_recent": 0,
        "supported_extensions": [".md", ".txt"],
        "collection_name": "memory_pool_docs",
        "chunk_size": 1000,
        "chunk_overlap": 100,
        "archive_path": "memory_pool_archive",
    },
    "entry_limits": {
        "enabled": True,
        # true = regenerate what we actually operate (Patrick, S193). The June
        # fail-safe lean (false) was written when enforcement was still rolling
        # out; the fleet has run true for months, so a reborn file that came
        # back warn-only would silently drop enforcement, not protect anyone.
        "enforce": True,
        "entry_types": {
            "key_learnings": {
                "file": "local.json",
                "container": "key_learnings",
                "kind": "list",
                "field": "value",
                "max_chars": 200,
                "fields": {
                    "number": {"type": "int", "required": True},
                    "date": {"type": "str", "required": True, "max_chars": 10},
                    "key": {"type": "str", "required": True, "max_chars": 80},
                    "value": {"type": "str", "required": True, "max_chars": 200},
                },
            },
            "sessions": {
                "file": "local.json",
                "container": "sessions",
                "kind": "list",
                "field": "summary",
                "max_chars": 300,
                "fields": {
                    "number": {"type": "int", "required": True},
                    "date": {"type": "str", "required": True, "max_chars": 10},
                    "summary": {"type": "str", "required": True, "max_chars": 300},
                    "status": {"type": "str", "required": True, "max_chars": 40},
                    "tags": {"type": "list[str]", "required": False, "max_items": 10, "max_chars": 120},
                },
            },
            "todos": {
                "file": "local.json",
                "container": "todos",
                "kind": "list",
                "field": "task",
                "max_chars": 100,
                "fields": {
                    "number": {"type": "int", "required": True},
                    "date": {"type": "str", "required": True, "max_chars": 10},
                    "task": {"type": "str", "required": True, "max_chars": 100},
                    "priority": {"type": "str", "required": False, "max_chars": 10},
                },
            },
            "observations": {
                "file": "observations.json",
                "container": "observations",
                "kind": "list",
                "field": "note",
                "max_chars": 300,
                "fields": {
                    "number": {"type": "int", "required": True},
                    "date": {"type": "str", "required": True, "max_chars": 10},
                    "note": {"type": "str", "required": True, "max_chars": 300},
                    "tags": {"type": "list[str]", "required": True, "max_items": 10, "max_chars": 120},
                },
            },
        },
        # The whole-file ceilings. Read, never copied: @seedgo's startup_budget
        # pack and the keep-count check both come here for these three numbers.
        # passport.json is SIZE only — @spawn owns its schema, so there is no
        # closed field shape for it, just a file budget and a per-string cap.
        "file_budgets": {
            "local.json": {"max_chars": 25000},
            "observations.json": {"max_chars": 15000},
            "passport.json": {"max_chars": 6000, "max_string_chars": 600},
        },
        "per_branch": {},
    },
    "plans": {
        "enabled": True,
        "path": ".backup/processed_plans",
        "collection_name": "plans",
        "supported_extensions": [".md"],
    },
    "rollover": {
        "defaults": {
            "local": {
                "sessions": {"count": 15, "auto_compact_cap": 3},
                "key_learnings": {"count": 15},
                "todos": {"count": 10},
            },
            "observations": {
                "observations": {"count": 15},
            },
            "_note": "DEFAULTS — edit then `drone @memory rollover push` to apply system-wide."
            " Char caps live in entry_limits.",
        },
        "per_branch": {},
    },
}


# Entry type -> (file key, leaf key) inside the rollover limits tree. The FILE
# key is the unit the rollover engine resolves per branch (see _resolve_limits);
# the leaf key is the entry family inside it.
ENTRY_TYPE_KEYS: dict[str, tuple[str, str]] = {
    "sessions": ("local", "sessions"),
    "key_learnings": ("local", "key_learnings"),
    "observations": ("observations", "observations"),
    "todos": ("local", "todos"),
}

# The three the vector rollover engine enforces, and the only ones `config set` writes.
SETTABLE_ENTRY_TYPES: tuple[str, ...] = ("sessions", "key_learnings", "observations")

# COUNT ONLY (DPLAN-0345). todos resolve a count here so every surface reads one
# number, but nothing on the vector lane acts on it: detector._should_rollover,
# the extractor and the orchestrator name their three families explicitly and
# never read this key. The one consumer that acts is rollover/todo_roll.py, for
# ONE branch at a time. Display-only in v1, like auto_compact_cap.
COUNT_ONLY_ENTRY_TYPES: tuple[str, ...] = ("todos",)


def deep_merge(base: dict, overrides: dict) -> dict:
    """Recursively merge *overrides* into *base* without mutating either."""
    result = copy.deepcopy(base)
    for key, val in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = copy.deepcopy(val)
    return result


def _write_config_file(config: dict[str, Any]) -> bool:
    """Write *config* to _CONFIG_PATH atomically.

    Atomic because the watcher, rollover subprocesses and the CLI all read
    this file concurrently — a half-written file would be read as corrupt,
    turning a routine write into a fleet-wide fall back to defaults.

    ``ensure_ascii=False`` matches every other JSON writer on this branch
    (memory_files, central_writer, detector, normalize, both pushers) and is
    what the operator's file already holds.  With the default True, setting a
    single limit rewrote every em-dash in the file as ``\\u2014`` — a whole-file
    diff carrying no change, on the file BAUD puts in front of the operator.

    Returns:
        True if the file was written, False if the write failed (logged).
    """
    tmp_path = _CONFIG_PATH.parent / f"{_CONFIG_PATH.name}.tmp-{os.getpid()}"
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp_path, _CONFIG_PATH)
        return True
    except OSError as exc:
        logger.error(f"[config_loader] Failed to write {_CONFIG_PATH}: {exc}")
        return False
    finally:
        # Never leave a half-written temp behind for the next reader to find
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            logger.warning(f"[config_loader] Could not clean up temp file {tmp_path}")


def _regenerate(reason: str) -> dict[str, Any]:
    """Rebuild the config file from DEFAULT_CONFIG and return the defaults.

    Fires on a genuinely-missing file ONLY.  A file that exists but cannot be
    read is never regenerated over — see load().

    Args:
        reason: Why regeneration fired — logged.

    Returns:
        A fresh copy of DEFAULT_CONFIG, whether or not the write succeeded.
        A failed write is logged as an error, never silently swallowed, and
        the caller still gets a usable config.
    """
    written = _write_config_file(DEFAULT_CONFIG)
    if written:
        logger.info(f"[config_loader] Regenerated {_CONFIG_PATH} from defaults ({reason})")
    json_handler.log_operation(
        f"config_regenerate_{reason}",
        {"path": str(_CONFIG_PATH), "written": written},
        module_name="config_loader",
    )
    return copy.deepcopy(DEFAULT_CONFIG)


def load() -> dict[str, Any]:
    """Load memory.config.json, deep-merged over DEFAULT_CONFIG.

    The file on disk is the runtime authority.  A genuinely-MISSING file is
    regenerated in full from DEFAULT_CONFIG, so the operator always has a
    real file to edit — that is the whole reason code carries defaults.

    A file that EXISTS but cannot be read is a different case and is never
    written over (DPLAN-0206 red flag, seedgo-consulted): it may be one stray
    comma away from correct and carry hand-tuned per_branch limits.  Log an
    ERROR, serve defaults in memory, and leave the operator's file for the
    operator to fix.

    "Cannot be read" means for ANY reason (json_structure v3.0.0) — bad bytes
    and bad permissions are as unreadable as bad syntax, and none of them may
    escape as a raw exception into a caller that only wanted a config.

    Returns:
        The effective config dict (always safe to use).
    """
    if not _CONFIG_PATH.exists():
        logger.info(f"[config_loader] No config at {_CONFIG_PATH}, regenerating from defaults")
        return _regenerate("missing")

    try:
        raw = _CONFIG_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # Unopenable or undecodable — same no-clobber contract as malformed.
        logger.error(f"[config_loader] Cannot read {_CONFIG_PATH}: {type(exc).__name__}: {exc}")
        json_handler.log_operation(
            "config_load_unreadable",
            {"path": str(_CONFIG_PATH), "error": f"{type(exc).__name__}: {exc}"},
            module_name="config_loader",
        )
        return copy.deepcopy(DEFAULT_CONFIG)

    try:
        file_config = json.loads(raw)
    except json.JSONDecodeError as exc:
        # Fail loud, do NOT overwrite — the operator must fix their file.
        logger.error(f"[config_loader] Malformed JSON in {_CONFIG_PATH}: {exc}")
        json_handler.log_operation(
            "config_load_malformed",
            {"path": str(_CONFIG_PATH), "error": str(exc)},
            module_name="config_loader",
        )
        return copy.deepcopy(DEFAULT_CONFIG)

    if not isinstance(file_config, dict):
        # Valid JSON, wrong shape (a list, a bare string). deep_merge would
        # raise on it, so it takes the same no-clobber path as malformed.
        logger.error(f"[config_loader] Config at {_CONFIG_PATH} is {type(file_config).__name__}, expected object")
        json_handler.log_operation(
            "config_load_wrong_shape",
            {"path": str(_CONFIG_PATH), "found_type": type(file_config).__name__},
            module_name="config_loader",
        )
        return copy.deepcopy(DEFAULT_CONFIG)

    merged = deep_merge(DEFAULT_CONFIG, file_config)
    json_handler.log_operation(
        "config_load",
        {"path": str(_CONFIG_PATH)},
        module_name="config_loader",
    )
    return merged


def section(name: str) -> dict[str, Any]:
    """Return a single top-level section from the config, or empty dict."""
    return load().get(name, {})


def _find_repo_root() -> Path:
    """Repo root for this lane — resolved by ``handlers/repo_root.py``.

    IMPORTED INSIDE THE FUNCTION, not at module level. ``handlers/json/__init__``
    imports this module, and ``repo_root`` imports ``handlers.json`` for its
    audit line, so a module-level edge here would be a cycle that only appears
    in whichever import order CI happens to take.

    Returns:
        The directory holding AIPASS_REGISTRY.json, or the source tree. Never
        the process working directory.
    """
    from aipass.memory.apps.handlers import repo_root

    return repo_root.find_repo_root(caller="config_loader")


def materialize_per_branch() -> dict[str, Any]:
    """Build per_branch from AIPASS_REGISTRY.json, seeded from rollover.defaults."""
    repo_root = _find_repo_root()
    registry_path = repo_root / "AIPASS_REGISTRY.json"
    from aipass.memory.apps.handlers import repo_root

    # exists_exactly, not exists(): see handlers/repo_root.py. Function-local
    # import for the same cycle reason _find_repo_root uses one.
    if not repo_root.exists_exactly(registry_path):
        logger.warning("[config_loader] AIPASS_REGISTRY.json not found")
        return {}

    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"[config_loader] Failed to load registry: {e}")
        return {}

    cfg = load()
    defaults = cfg.get("rollover", {}).get("defaults", {})
    limits_only = {k: v for k, v in defaults.items() if k != "_note"}

    branches = registry.get("branches", [])
    active = [b for b in branches if b.get("status") == "active"]

    per_branch: dict[str, Any] = {}
    for branch in active:
        name = branch.get("name", "").lower()
        if not name:
            continue
        entry = copy.deepcopy(limits_only)
        _materialize_todos(entry, defaults)
        entry["_note"] = f"Limits for @{name}. Manual edits persist until next push."
        per_branch[name] = entry

    return per_branch


def push_defaults_to_per_branch() -> dict[str, Any]:
    """Overwrite every per_branch entry with defaults (full replacement, not merge).

    Returns:
        Dict with branch count and the new per_branch data.
    """
    per_branch = materialize_per_branch()
    if not per_branch:
        return {"success": False, "error": "No branches found in registry"}

    current: dict = {}
    if _CONFIG_PATH.exists():
        loaded: Any = None
        try:
            loaded = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            # Bad syntax, bad bytes and bad permissions all mean the same thing
            # here: we cannot know what is in the file, so we must not write it.
            logger.error(f"[config_loader] Cannot push onto unreadable config: {type(exc).__name__}: {exc}")
        if isinstance(loaded, dict):
            current = loaded
        else:
            # Same rule as load(): never write over a broken operator file.
            # Refusing is the honest outcome — the old behaviour rebuilt from
            # scratch and silently discarded everything they had.
            logger.error(f"[config_loader] Refusing push onto unreadable {_CONFIG_PATH}")
            return {
                "success": False,
                "error": f"Config at {_CONFIG_PATH} is unreadable — fix or move it aside, then push again",
            }

    current.setdefault("rollover", {})["per_branch"] = per_branch
    if not _write_config_file(current):
        return {"success": False, "error": f"Failed to write {_CONFIG_PATH}"}

    return {"success": True, "branches": len(per_branch), "per_branch": per_branch}


# =============================================================================
# ROLLOVER LIMITS — READ
# =============================================================================


def _as_dict(value: Any) -> dict[str, Any]:
    """Return *value* when it is a dict, else an empty dict.

    Every node in this tree is hand-editable, so a string or a list can turn
    up anywhere.  Coercing to {} keeps a malformed corner from raising into a
    caller that only asked what a limit is.
    """
    return value if isinstance(value, dict) else {}


def _co_tenant_text(file_key: str, counts: dict[str, Any], entry_types: dict[str, Any], entry_type: str) -> str:
    """Render the co-tenant counts a ceiling was computed against.

    Args:
        file_key: ``"local.json"`` or ``"observations.json"``.
        counts: ``{entry_type: count}`` as resolved.
        entry_types: The ``entry_limits.entry_types`` map.
        entry_type: The type being measured — left out of its own company.

    Returns:
        ``"key_learnings 15, todos 10"``, or ``"no co-tenants"`` when the type
        has the file to itself.
    """
    others = budget.co_tenants(file_key, counts, entry_types, exclude=entry_type)
    return ", ".join(f"{name} {count}" for name, count in others.items()) if others else "no co-tenants"


def _clamp_to_budget(resolved: dict[str, Any], entry_cfg: dict[str, Any], branch: str) -> None:
    """Lower any resolved count whose worst-case file would bust its budget.

    A keep-count multiplies an entry that is individually legal until the FILE
    it lives in is not.  Nothing measured that until now, so a hand-edit of
    memory.config.json could put a branch permanently over budget with every
    single entry inside its cap — and the number was reported, and obeyed, as
    if it were enforceable.  It is not: the budget is the harder bound.

    The count is lowered to the ceiling rather than dropped, because a branch
    with no limit rolls nothing and grows without end.  The raw value stays on
    the row as ``requested_count`` so ``config get`` can still show what the
    operator wrote next to what the engine will do.

    Mutates *resolved* in place.

    Args:
        resolved: The rows built by :func:`_resolve_limits`.
        entry_cfg: The ``entry_limits`` section — its ``entry_types`` shapes
            and ``file_budgets``.  Anything else is no ceiling data and the
            rows are left exactly as resolved.
        branch: Branch name, for the warning.
    """
    entry_types = _as_dict(entry_cfg.get("entry_types"))
    budgets = _as_dict(entry_cfg.get("file_budgets"))
    if not entry_types or not budgets:
        return

    # The snapshot is taken BEFORE any clamp so every ceiling is measured
    # against the same co-tenants; clamping one type must not silently buy
    # room for the next one in iteration order.
    counts = {name: row["count"] for name, row in resolved.items()}

    for entry_type, row in resolved.items():
        count = row["count"]
        if isinstance(count, bool) or not isinstance(count, int):
            continue
        ceiling = budget.count_ceiling(entry_type, counts, entry_types, budgets)
        if count <= ceiling:
            continue

        file_key = _as_dict(entry_types.get(entry_type)).get("file", "")
        max_chars = _as_dict(budgets.get(file_key)).get("max_chars")
        worst = budget.worst_file_chars(str(file_key), counts, entry_types)
        logger.warning(
            f"[config_loader] {branch}: {entry_type} count {count} exceeds the ceiling of {ceiling} for "
            f"{file_key} — worst case {worst:,} chars against its {max_chars:,} budget "
            f"(with {_co_tenant_text(str(file_key), counts, entry_types, entry_type)}). Enforcing {ceiling}."
        )
        row["count"] = ceiling
        row["is_override"] = ceiling != row["default_count"]


def _resolve_limits(
    rollover_cfg: dict[str, Any],
    branch: str,
    entry_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the limits the rollover engine will REALLY apply to *branch*.

    Mirrors ``monitor/detector.py`` ``_should_rollover`` exactly: the lookup is
    per FILE KEY, not per leaf key.  If ``per_branch[branch]["local"]`` exists
    at all then ``defaults["local"]`` is never consulted for that branch — so a
    per-branch entry carrying only ``sessions`` leaves ``key_learnings`` with
    NO limit, not the default one.  A deep merge here would report a limit the
    engine does not enforce, which is the one thing this function must not do.

    "Override" is decided BY VALUE, not by where the number came from: all 17
    branches carry a materialized per_branch entry, and calling every one of
    them an override would be pure noise.  A value is an override when it
    differs from the corresponding default.

    THE COUNT IS ALSO CLAMPED TO THE FILE BUDGET (1.5.0, FPLAN-0593).  A
    keep-count is a multiplier on an entry cap, and nothing measured the
    product: 40 sessions of 706 legal chars is a 25,000-char budget missed by
    a third, with every entry inside its cap.  When *entry_cfg* is supplied,
    any count above :func:`budget.count_ceiling` is lowered to the ceiling and
    the raw value is kept on the row as ``requested_count``.

    *entry_cfg* is a PARAMETER and not a read because this function promises
    no I/O and means it: ``config_loader.load()`` writes an operation-log line
    through a read-modify-write of a 1,000-entry JSON file, and the fleet tab
    renderer resolves limits four times per branch.  Fetching budgets here
    would have turned one dashboard refresh into ~70 of those.  Every caller
    that has already loaded the config passes the section along and gets the
    clamp; a caller holding only the rollover section gets the pre-1.5.0
    behaviour, unclamped, which is why the accessors below all pass it.

    Args:
        rollover_cfg: The ``rollover`` section (already loaded — no I/O here).
        branch: Branch name, matched case-insensitively.
        entry_cfg: The ``entry_limits`` section, when the caller has it. No
            ceiling data means no clamp.

    Returns:
        ``{entry_type: {"count", "requested_count", "default_count",
        "auto_compact_cap", "source", "is_override"}}`` for each of
        ``ENTRY_TYPE_KEYS``.  ``count`` is None when neither per_branch nor
        defaults set one, and is the ceiling when the configured value was
        above it; ``requested_count`` is always what the config actually says.
    """
    per_branch = _as_dict(rollover_cfg.get("per_branch"))
    defaults = _as_dict(rollover_cfg.get("defaults"))
    branch_cfg = _as_dict(per_branch.get(branch.lower()))

    resolved: dict[str, Any] = {}
    for entry_type, (file_key, leaf_key) in ENTRY_TYPE_KEYS.items():
        file_limits = _as_dict(branch_cfg.get(file_key))
        source = "per_branch"
        if not file_limits:
            file_limits = _as_dict(defaults.get(file_key))
            source = "defaults"

        leaf = _as_dict(file_limits.get(leaf_key))
        default_leaf = _as_dict(_as_dict(defaults.get(file_key)).get(leaf_key))
        count = leaf.get("count")
        default_count = default_leaf.get("count")
        if count is None and entry_type in COUNT_ONLY_ENTRY_TYPES:
            # A per_branch `local` block written without a todos count must not
            # silently stop that branch's roll. The per-file-key rule above
            # stays exact for the three vector families.
            count = default_count
            source = "defaults"

        resolved[entry_type] = {
            "count": count,
            "requested_count": count,
            "default_count": default_count,
            "auto_compact_cap": leaf.get("auto_compact_cap"),
            "source": source,
            "is_override": count != default_count,
        }

    if isinstance(entry_cfg, dict):
        _clamp_to_budget(resolved, entry_cfg, branch)

    return resolved


def resolve_limits(
    rollover_cfg: dict[str, Any],
    branch: str,
    entry_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Public, no-I/O resolver — the ONE implementation of "what does the engine enforce".

    Takes an already-loaded ``rollover`` section so a caller rendering every
    branch reads the config once, not once per branch.

    Every surface that answers "what limit applies to this branch" must come
    through here.  ``config get`` and ``tab_renderer`` both used to carry their
    own lookup; the tab's copy resolved per-branch-dict instead of per-file-key
    and hard-defaulted a missing count to 15, so it could print a banner
    claiming a limit the engine does not enforce — into the agent's own memory
    file, where it reads as an instruction.  Two writers, one truth: this is
    the writer.

    Args:
        rollover_cfg: The ``rollover`` section, already loaded.
        branch: Branch name, matched case-insensitively.
        entry_cfg: The ``entry_limits`` section, when the caller has it.
            Without it there is no budget to clamp against — see
            ``_resolve_limits`` for why this is passed and never fetched.

    Returns:
        See ``_resolve_limits``.
    """
    return _resolve_limits(rollover_cfg, branch, entry_cfg)


def get_default_limits() -> dict[str, Any]:
    """Return the global default limit for each entry type.

    Returns:
        ``{entry_type: {"count": int | None, "auto_compact_cap": int | None}}``.
    """
    defaults = _as_dict(section("rollover").get("defaults"))

    limits: dict[str, Any] = {}
    for entry_type, (file_key, leaf_key) in ENTRY_TYPE_KEYS.items():
        leaf = _as_dict(_as_dict(defaults.get(file_key)).get(leaf_key))
        limits[entry_type] = {"count": leaf.get("count"), "auto_compact_cap": leaf.get("auto_compact_cap")}

    return limits


def get_effective_limits(branch: str) -> dict[str, Any]:
    """Return the limits the rollover engine applies to *branch*.

    Args:
        branch: Branch name, matched case-insensitively.

    Returns:
        See ``_resolve_limits`` — one entry per settable entry type, clamped
        to the file budgets.
    """
    config = load()
    return _resolve_limits(_as_dict(config.get("rollover")), branch, _as_dict(config.get("entry_limits")))


def get_todos_count(branch: str, rollover_cfg: dict[str, Any] | None = None) -> int | None:
    """The todo pad size for *branch*, through the one resolver.

    Args:
        branch: Branch directory name, matched case-insensitively.
        rollover_cfg: An already-loaded ``rollover`` section; loaded when None.
            Supplying it keeps this call free of I/O, and therefore free of
            the budget clamp — the same trade ``_resolve_limits`` documents.

    Returns:
        A whole number >= 1, or None when no usable count is configured (a
        bool, a string, zero or a negative number is not a pad size).
    """
    if rollover_cfg is not None:
        cfg, entry_cfg = rollover_cfg, None
    else:
        config = load()
        cfg, entry_cfg = _as_dict(config.get("rollover")), _as_dict(config.get("entry_limits"))
    count = _resolve_limits(cfg, branch, entry_cfg)["todos"]["count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        return None
    return count


def get_branches_with_overrides() -> dict[str, Any]:
    """Return only the configured branches whose limits deviate from defaults.

    Loads the config once, not once per branch: 17 loads would mean 17 reads
    and 17 operation-log lines for a single display.

    Returns:
        ``{branch: effective_limits}``, branch-sorted, deviating branches only.
    """
    config = load()
    rollover_cfg = _as_dict(config.get("rollover"))
    entry_cfg = _as_dict(config.get("entry_limits"))
    per_branch = _as_dict(rollover_cfg.get("per_branch"))

    deviating: dict[str, Any] = {}
    for branch in sorted(per_branch):
        limits = _resolve_limits(rollover_cfg, branch, entry_cfg)
        if any(row["is_override"] for row in limits.values()):
            deviating[branch] = limits

    return deviating


# =============================================================================
# ENTRY LIMITS — READ
# =============================================================================


def get_file_budgets() -> dict[str, Any]:
    """Return the whole-file ceilings for the .trinity files.

    config_loader owns config reads, so the keep-count ceiling comes here for
    the budgets rather than opening the file itself.  ``entry_limits``
    publishes the same three numbers under its own name for callers already
    holding its module, and that name DELEGATES here — two readers of one key
    is exactly the drift ``load()`` was written to end.

    Returns:
        ``{file_name: {"max_chars": int, "max_string_chars": int?}}`` — a
        private copy, so a caller cannot edit the fleet's budgets by mutating
        what it was handed.  The regeneration seed's budgets when the config
        publishes none.
    """
    budgets = _as_dict(section("entry_limits").get("file_budgets"))
    if not budgets:
        logger.warning("[config_loader] No 'file_budgets' in config — serving the regeneration seed")
        budgets = DEFAULT_CONFIG["entry_limits"]["file_budgets"]
    return copy.deepcopy(budgets)


def get_count_ceilings(branch: str | None = None) -> dict[str, Any]:
    """The largest keep-count each entry type may take, and what bounds it.

    One config read for the whole table.  The ceiling is per type and per
    file: local.json's budget is shared by sessions, key_learnings and todos,
    so each type's ceiling is what is left once the other two hold their
    counts — raise one and the others' ceilings drop.

    Args:
        branch: Whose counts are the co-tenants.  None asks about the fleet
            defaults, which is the company a ``set-default`` lands in.

    Returns:
        ``{entry_type: {"ceiling", "count", "file_key", "budget_chars",
        "co_tenants", "fixed_chars", "entry_chars"}}``, empty when the config
        publishes no entry shapes or no budgets — nothing measurable is
        nothing to enforce.  ``fixed_chars + n * entry_chars`` is the file's
        worst case at any keep-count *n*, which is what a refusal quotes.
    """
    config = load()
    entry_cfg = _as_dict(config.get("entry_limits"))
    entry_types = _as_dict(entry_cfg.get("entry_types"))
    budgets = _as_dict(entry_cfg.get("file_budgets"))
    if not entry_types or not budgets:
        return {}

    rollover_cfg = _as_dict(config.get("rollover"))
    counts: dict[str, Any]
    if branch:
        counts = {name: row.get("count") for name, row in _resolve_limits(rollover_cfg, branch, entry_cfg).items()}
    else:
        defaults = _as_dict(rollover_cfg.get("defaults"))
        counts = {
            name: _as_dict(_as_dict(defaults.get(file_key)).get(leaf_key)).get("count")
            for name, (file_key, leaf_key) in ENTRY_TYPE_KEYS.items()
        }

    table: dict[str, Any] = {}
    for entry_type in ENTRY_TYPE_KEYS:
        file_key = _as_dict(entry_types.get(entry_type)).get("file")
        if not isinstance(file_key, str):
            continue
        company = budget.co_tenants(file_key, counts, entry_types, exclude=entry_type)
        table[entry_type] = {
            "ceiling": budget.count_ceiling(entry_type, counts, entry_types, budgets),
            "count": counts.get(entry_type),
            "file_key": file_key,
            "budget_chars": _as_dict(budgets.get(file_key)).get("max_chars"),
            "co_tenants": company,
            "fixed_chars": budget.worst_file_chars(file_key, company, entry_types),
            "entry_chars": budget.worst_entry_chars(_as_dict(_as_dict(entry_types.get(entry_type)).get("fields"))),
        }
    return table


def ceiling_refusal(entry_type: str, count: int, branch: str | None = None) -> dict[str, Any] | None:
    """Judge one proposed keep-count against its file budget.

    THE SENTENCE LIVES HERE, not at the verb, for the same reason
    ``set_branch_limit``'s refusals do: config_loader owns config reads, and a
    refusal that quoted numbers the verb had fetched itself would be a second
    reader free to drift from this one.

    Args:
        entry_type: The type the count is for.
        count: The proposed keep-count.
        branch: The branch being written, or None for the fleet defaults.

    Returns:
        ``{"error", "suggestion", "ceiling", "file_key", "budget_chars"}``
        when the count busts the budget, else None — an unmeasurable or
        unconfigured ceiling refuses nothing.
    """
    row = get_count_ceilings(branch).get(entry_type)
    if row is None or count <= row["ceiling"]:
        return None

    company = row["co_tenants"]
    with_clause = (
        "with " + ", ".join(f"{name} {value}" for name, value in company.items())
        if company
        else f"{entry_type} is {row['file_key']}'s only tenant"
    )
    worst = row["fixed_chars"] + count * row["entry_chars"]
    return {
        "error": (
            f"{entry_type} may keep at most {row['ceiling']} — {row['file_key']}'s worst case at {count} "
            f"would be {worst:,} chars against its {row['budget_chars']:,} budget ({with_clause})"
        ),
        "suggestion": (
            f"{row['budget_chars']:,} is {row['file_key']}'s budget, in memory.config.json "
            "entry_limits.file_budgets — the ceiling moves only when that number or the entry caps do"
        ),
        "ceiling": row["ceiling"],
        "file_key": row["file_key"],
        "budget_chars": row["budget_chars"],
    }


# =============================================================================
# ROLLOVER LIMITS — WRITE
# =============================================================================


def _read_config_for_write() -> tuple[dict[str, Any] | None, str | None]:
    """Read the config for a read-modify-write, or refuse to touch it.

    Same no-clobber contract as ``load()`` and ``push_defaults_to_per_branch()``:
    a file that EXISTS but cannot be read is never written over — it may be one
    stray comma from correct and carry hand-tuned per-branch limits.  A
    genuinely-MISSING file is regenerated first (load()'s documented contract),
    so an operator's edit lands in a complete file rather than a stub.

    Returns:
        ``(config, None)`` when the file is usable, else ``(None, refusal)``.
    """
    if not _CONFIG_PATH.exists():
        load()

    loaded: Any = None
    try:
        loaded = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        # Bad syntax, bad bytes and bad permissions all mean the same thing
        # here: we cannot know what is in the file, so we must not write it.
        logger.error(f"[config_loader] Cannot write onto unreadable config: {type(exc).__name__}: {exc}")

    if isinstance(loaded, dict):
        return loaded, None

    logger.error(f"[config_loader] Refusing write onto unreadable {_CONFIG_PATH}")
    return None, f"Config at {_CONFIG_PATH} is unreadable — fix or move it aside, then try again"


def _apply_limit(tree: dict[str, Any], file_key: str, leaf_key: str, count: int) -> None:
    """Set ``tree[file_key][leaf_key]["count"] = count`` in place.

    Only the count is touched.  ``auto_compact_cap`` — and anything else an
    operator parked beside it — survives, because v1 sets one number rather
    than rewriting the leaf.
    """
    file_section = _as_dict(tree.get(file_key))
    leaf_section = _as_dict(file_section.get(leaf_key))
    leaf_section["count"] = count
    file_section[leaf_key] = leaf_section
    tree[file_key] = file_section


def _seed_branch_entry(defaults: dict[str, Any], branch: str) -> dict[str, Any]:
    """Build a fresh per_branch entry in the shape materialize_per_branch() makes.

    Args:
        defaults: The ``rollover.defaults`` tree to seed from.
        branch: Lowercase branch key.

    Returns:
        Limits copied from defaults plus the same ``_note`` line a push writes.
    """
    entry = {key: copy.deepcopy(val) for key, val in defaults.items() if key != "_note"}
    entry["_note"] = f"Limits for @{branch}. Manual edits persist until next push."
    return entry


def _materialize_todos(entry: dict[str, Any], defaults: dict[str, Any]) -> None:
    """Carry the todos count into a per_branch ``local`` block that lacks one, in place.

    Limits resolve per FILE key as a whole block, so a ``local`` block written
    by ``config set @b sessions 12`` without ``todos`` reads as "no todo count"
    to any reader following that rule (hooks' count advisory does). The
    resolver falls back anyway; this keeps the file saying the same thing.

    Args:
        entry: One per_branch entry, edited in place.
        defaults: The ``rollover.defaults`` tree to take the count from.
    """
    local = entry.get("local")
    if not isinstance(local, dict):
        return
    todos = _as_dict(local.get("todos"))
    if todos.get("count") is not None:
        return
    default_count = _as_dict(_as_dict(defaults.get("local")).get("todos")).get("count")
    if default_count is None:
        default_count = DEFAULT_CONFIG["rollover"]["defaults"]["local"]["todos"]["count"]
    todos["count"] = default_count
    local["todos"] = todos


def _refuse_unsettable(entry_type: str) -> dict[str, Any] | None:
    """The refusal for a type ``config set`` may not write, or None when it may."""
    if entry_type in COUNT_ONLY_ENTRY_TYPES:
        return {"success": False, "error": f"'{entry_type}' count is display-only in v1 - not settable"}
    if entry_type not in SETTABLE_ENTRY_TYPES:
        return {"success": False, "error": f"Unknown entry type: '{entry_type}'"}
    return None


def set_branch_limit(branch: str, entry_type: str, count: int) -> dict[str, Any]:
    """Write one per-branch rollover limit override.

    Never prints and never raises: the module layer owns the refusal wording.

    Args:
        branch: Branch name — the lowercase form is always what gets written.
        entry_type: One of ``SETTABLE_ENTRY_TYPES``.
        count: The new limit (bounds are the module layer's contract).

    Returns:
        ``{"success": True, "branch", "entry_type", "count", "pushed"}`` or
        ``{"success": False, "error": <sentence>}``.  ``pushed`` is always
        False: this writes ONE branch's entry, it never runs the fleet-wide
        push.  It is reported rather than assumed so the machine surface
        states the delivery semantics in data instead of in prose.
    """
    refused = _refuse_unsettable(entry_type)
    if refused:
        return refused

    current, refusal = _read_config_for_write()
    if current is None:
        return {"success": False, "error": refusal}

    file_key, leaf_key = ENTRY_TYPE_KEYS[entry_type]
    key = branch.lower()

    rollover_cfg = _as_dict(current.get("rollover"))
    defaults = _as_dict(rollover_cfg.get("defaults")) or copy.deepcopy(DEFAULT_CONFIG["rollover"]["defaults"])
    per_branch = _as_dict(rollover_cfg.get("per_branch"))

    entry = _as_dict(per_branch.get(key)) or _seed_branch_entry(defaults, key)
    _apply_limit(entry, file_key, leaf_key, count)
    _materialize_todos(entry, defaults)

    per_branch[key] = entry
    rollover_cfg["per_branch"] = per_branch
    current["rollover"] = rollover_cfg

    if not _write_config_file(current):
        return {"success": False, "error": f"Failed to write {_CONFIG_PATH}"}

    json_handler.log_operation(
        "config_set_branch_limit",
        {"branch": key, "entry_type": entry_type, "count": count},
        module_name="config_loader",
    )
    return {"success": True, "branch": key, "entry_type": entry_type, "count": count, "pushed": False}


def set_default_limit(entry_type: str, count: int) -> dict[str, Any]:
    """Write one global default rollover limit.

    ``per_branch`` is deliberately left alone — ``rollover push`` stays the one
    explicit fleet-wide reset, so raising a default never silently rewrites
    seventeen branches an operator may have tuned by hand.

    Args:
        entry_type: One of ``SETTABLE_ENTRY_TYPES``.
        count: The new default limit.

    Returns:
        ``{"success": True, "entry_type", "count", "pushed"}`` or
        ``{"success": False, "error": <sentence>}``.  ``pushed`` is always
        False and says the load-bearing thing about this verb: the new
        default reached NO branch.  ``rollover push`` is what delivers it.
    """
    refused = _refuse_unsettable(entry_type)
    if refused:
        return refused

    current, refusal = _read_config_for_write()
    if current is None:
        return {"success": False, "error": refusal}

    file_key, leaf_key = ENTRY_TYPE_KEYS[entry_type]

    rollover_cfg = _as_dict(current.get("rollover"))
    defaults = _as_dict(rollover_cfg.get("defaults")) or copy.deepcopy(DEFAULT_CONFIG["rollover"]["defaults"])
    _apply_limit(defaults, file_key, leaf_key, count)

    rollover_cfg["defaults"] = defaults
    current["rollover"] = rollover_cfg

    if not _write_config_file(current):
        return {"success": False, "error": f"Failed to write {_CONFIG_PATH}"}

    json_handler.log_operation(
        "config_set_default_limit",
        {"entry_type": entry_type, "count": count},
        module_name="config_loader",
    )
    return {"success": True, "entry_type": entry_type, "count": count, "pushed": False}
