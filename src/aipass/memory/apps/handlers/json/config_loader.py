# =================== AIPass ====================
# Name: config_loader.py
# Description: Unified config loader for memory.config.json
# Version: 1.8.0
# Created: 2026-06-13
# Modified: 2026-10-23
# =============================================

"""
Unified Config Loader

DEFAULT_CONFIG is the regeneration seed for a MISSING file, not a rival source: keep the two
in lockstep. A file that exists but will not parse is never written over; defaults serve in memory.
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
        # true = regenerate what the fleet operates; a reborn warn-only file would silently drop enforcement.
        "enforce": True,
        # Percent of each cap an agent drafts to; @seedgo's meta line reads it, never mirrors it.
        "draft_percent": 80,
        # The gate refuses past cap * (100 + this) // 100: a writer estimates length, it cannot count it.
        "tolerance_percent": 10,
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
        # Read, never copied: seedgo's startup_budget and the keep-count check read these.
        # passport.json is SIZE only: @spawn owns its schema.
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
        # Records a todo backlog keeps before the OLDEST move to the archive file. A backlog is
        # the only copy of a rolled todo and is never vectorised, so nothing here may delete one.
        "backlog": {"max_records": 100},
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


# Entry type -> (file key, leaf key). The FILE key is the unit the engine resolves per branch.
ENTRY_TYPE_KEYS: dict[str, tuple[str, str]] = {
    "sessions": ("local", "sessions"),
    "key_learnings": ("local", "key_learnings"),
    "observations": ("observations", "observations"),
    "todos": ("local", "todos"),
}

SETTABLE_ENTRY_TYPES: tuple[str, ...] = ("sessions", "key_learnings", "observations")

# COUNT ONLY: todos resolve a count here, but the vector lane never reads it; only
# rollover/todo_roll.py acts on it, one branch at a time.
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
    """Write *config* to _CONFIG_PATH atomically (watcher, rollover and CLI read it concurrently).

    ``ensure_ascii=False`` matches every other writer here; True rewrites every em-dash as a whole-file diff.
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
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            logger.warning(f"[config_loader] Could not clean up temp file {tmp_path}")


def _regenerate(reason: str) -> dict[str, Any]:
    """Rebuild the config file from DEFAULT_CONFIG and return the defaults; fires on a MISSING file only."""
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

    MISSING regenerates in full. EXISTS but unreadable for ANY reason (syntax, bytes, permissions,
    shape) is never written over and never raises: log ERROR, serve defaults in memory.
    """
    if not _CONFIG_PATH.exists():
        logger.info(f"[config_loader] No config at {_CONFIG_PATH}, regenerating from defaults")
        return _regenerate("missing")

    try:
        raw = _CONFIG_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
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
        logger.error(f"[config_loader] Malformed JSON in {_CONFIG_PATH}: {exc}")
        json_handler.log_operation(
            "config_load_malformed",
            {"path": str(_CONFIG_PATH), "error": str(exc)},
            module_name="config_loader",
        )
        return copy.deepcopy(DEFAULT_CONFIG)

    if not isinstance(file_config, dict):
        # Valid JSON, wrong shape: deep_merge would raise on it.
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
    """Repo root for this lane — resolved by ``handlers/repo_root.py``, never the process CWD.

    Imported inside the function: a module-level import is a cycle via ``handlers/json/__init__``.
    """
    from aipass.memory.apps.handlers import repo_root

    return repo_root.find_repo_root(caller="config_loader")


class RegistryUnreadable(ValueError):
    """AIPASS_REGISTRY.json exists and cannot be read; raised rather than answered with ``{}`` (no active branch)."""


def materialize_per_branch() -> dict[str, Any]:
    """Build per_branch from AIPASS_REGISTRY.json, seeded from rollover.defaults; raises RegistryUnreadable."""
    repo_root = _find_repo_root()
    registry_path = repo_root / "AIPASS_REGISTRY.json"
    from aipass.memory.apps.handlers import repo_root

    # exists_exactly, not exists(): see handlers/repo_root.py. Local import: same cycle as _find_repo_root.
    if not repo_root.exists_exactly(registry_path):
        logger.warning("[config_loader] AIPASS_REGISTRY.json not found")
        return {}

    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        raise RegistryUnreadable(f"Unreadable registry {registry_path}: {e}") from e

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
    """Overwrite every per_branch entry with defaults (full replacement, not merge)."""
    try:
        per_branch = materialize_per_branch()
    except RegistryUnreadable as exc:
        logger.error(f"[config_loader] Refusing push: {exc}")
        return {"success": False, "error": str(exc)}
    if not per_branch:
        return {"success": False, "error": "No branches found in registry"}

    current: dict = {}
    if _CONFIG_PATH.exists():
        loaded: Any = None
        try:
            loaded = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            # Unknowable content must not be written over.
            logger.error(f"[config_loader] Cannot push onto unreadable config: {type(exc).__name__}: {exc}")
        if isinstance(loaded, dict):
            current = loaded
        else:
            # Same rule as load(): refuse, never rebuild over a broken operator file.
            logger.error(f"[config_loader] Refusing push onto unreadable {_CONFIG_PATH}")
            return {
                "success": False,
                "error": f"Config at {_CONFIG_PATH} is unreadable — fix or move it aside, then push again",
            }

    current.setdefault("rollover", {})["per_branch"] = per_branch
    if not _write_config_file(current):
        return {"success": False, "error": f"Failed to write {_CONFIG_PATH}"}

    return {"success": True, "branches": len(per_branch), "per_branch": per_branch}


def _as_dict(value: Any) -> dict[str, Any]:
    """Return *value* when it is a dict, else an empty dict (every node is hand-editable)."""
    return value if isinstance(value, dict) else {}


def _co_tenant_text(file_key: str, counts: dict[str, Any], entry_types: dict[str, Any], entry_type: str) -> str:
    """Render the co-tenant counts a ceiling was computed against, or ``"no co-tenants"``."""
    others = budget.co_tenants(file_key, counts, entry_types, exclude=entry_type)
    return ", ".join(f"{name} {count}" for name, count in others.items()) if others else "no co-tenants"


def _clamp_to_budget(resolved: dict[str, Any], entry_cfg: dict[str, Any], branch: str) -> None:
    """Lower any resolved count whose worst-case file would bust its budget; mutates *resolved*.

    Lowered to the ceiling, never dropped (no limit means unbounded growth); the raw value stays as ``requested_count``.
    """
    entry_types = _as_dict(entry_cfg.get("entry_types"))
    budgets = _as_dict(entry_cfg.get("file_budgets"))
    if not entry_types or not budgets:
        return

    # Snapshot BEFORE any clamp: clamping one type must not buy room for the next in iteration order.
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
        row["is_override"] = _is_override(row)


def _is_override(row: dict[str, Any]) -> bool:
    """The one rule: the count in force came from per_branch AND differs from the default."""
    return row["source"] == "per_branch" and row["count"] != row["default_count"]


def _resolve_limits(
    rollover_cfg: dict[str, Any],
    branch: str,
    entry_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the limits the rollover engine will REALLY apply to *branch*.

    Mirrors detector ``_should_rollover``: lookup is per FILE KEY, so a per_branch ``local`` with only
    ``sessions`` leaves ``key_learnings`` with NO limit. A deep merge would report an unenforced limit.
    *entry_cfg* is passed, never fetched: no I/O here (load() logs a write); without it, no budget clamp.
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
            # A per_branch `local` block without a todos count must not stop that branch's roll.
            count = default_count
            source = "defaults"

        resolved[entry_type] = {
            "count": count,
            "requested_count": count,
            "default_count": default_count,
            "auto_compact_cap": leaf.get("auto_compact_cap"),
            "source": source,
        }
        resolved[entry_type]["is_override"] = _is_override(resolved[entry_type])

    if isinstance(entry_cfg, dict):
        _clamp_to_budget(resolved, entry_cfg, branch)

    return resolved


def resolve_limits(
    rollover_cfg: dict[str, Any],
    branch: str,
    entry_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Public, no-I/O resolver — the ONE implementation of "what does the engine enforce"."""
    return _resolve_limits(rollover_cfg, branch, entry_cfg)


def get_default_limits() -> dict[str, Any]:
    """Return the global default limit for each entry type."""
    defaults = _as_dict(section("rollover").get("defaults"))

    limits: dict[str, Any] = {}
    for entry_type, (file_key, leaf_key) in ENTRY_TYPE_KEYS.items():
        leaf = _as_dict(_as_dict(defaults.get(file_key)).get(leaf_key))
        limits[entry_type] = {"count": leaf.get("count"), "auto_compact_cap": leaf.get("auto_compact_cap")}

    return limits


def get_effective_limits(branch: str) -> dict[str, Any]:
    """Return the limits the rollover engine applies to *branch*, clamped to the file budgets."""
    config = load()
    return _resolve_limits(_as_dict(config.get("rollover")), branch, _as_dict(config.get("entry_limits")))


def get_todos_count(branch: str, rollover_cfg: dict[str, Any] | None = None) -> int | None:
    """The todo pad size for *branch*, through the one resolver; None unless a whole number >= 1.

    A supplied *rollover_cfg* keeps the call I/O-free and therefore unclamped.
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


def get_backlog_ceiling() -> int | None:
    """How many records a todo backlog keeps before the oldest are archived.

    None means NO TRIM, never a trim to zero: a lost key must leave every record where it is.
    """
    raw = _as_dict(_as_dict(section("rollover")).get("backlog")).get("max_records")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        if raw is not None:
            logger.warning(f"[config_loader] rollover.backlog.max_records is not a record count ({raw!r}) — no trim")
        return None
    return raw


def get_branches_with_overrides() -> dict[str, Any]:
    """Return only the configured branches whose limits deviate from defaults (one config load)."""
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


def get_file_budgets() -> dict[str, Any]:
    """Return a private copy of the whole-file ceilings; ``entry_limits`` delegates here (one reader per key)."""
    budgets = _as_dict(section("entry_limits").get("file_budgets"))
    if not budgets:
        logger.warning("[config_loader] No 'file_budgets' in config — serving the regeneration seed")
        budgets = DEFAULT_CONFIG["entry_limits"]["file_budgets"]
    return copy.deepcopy(budgets)


def get_draft_percent() -> int:
    """Return the percent of a cap an agent should draft to; the seed's 80 when unusable, never removed."""
    raw = section("entry_limits").get("draft_percent")
    if isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= 100:
        if raw is not None:
            logger.warning(f"[config_loader] entry_limits.draft_percent is not 1-100 ({raw!r}) — serving the seed")
        return int(DEFAULT_CONFIG["entry_limits"]["draft_percent"])
    return raw


def get_count_ceilings(branch: str | None = None) -> dict[str, Any]:
    """The largest keep-count each entry type may take, and what bounds it.

    Per file: co-tenants share a budget, so raising one type lowers the others' ceilings.
    ``fixed_chars + n * entry_chars`` is the worst case at keep-count *n*; empty when unmeasurable.
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
    """Judge one proposed keep-count against its file budget; None when it fits or is unmeasurable.

    The sentence lives here, not at the verb, so the numbers it quotes have one reader.
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


def _read_config_for_write() -> tuple[dict[str, Any] | None, str | None]:
    """Read the config for a read-modify-write, or refuse to touch it (same no-clobber contract as load())."""
    if not _CONFIG_PATH.exists():
        load()

    loaded: Any = None
    try:
        loaded = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        # Unknowable content must not be written over.
        logger.error(f"[config_loader] Cannot write onto unreadable config: {type(exc).__name__}: {exc}")

    if isinstance(loaded, dict):
        return loaded, None

    logger.error(f"[config_loader] Refusing write onto unreadable {_CONFIG_PATH}")
    return None, f"Config at {_CONFIG_PATH} is unreadable — fix or move it aside, then try again"


def _apply_limit(tree: dict[str, Any], file_key: str, leaf_key: str, count: int) -> None:
    """Set ``tree[file_key][leaf_key]["count"] = count`` in place; siblings like auto_compact_cap survive."""
    file_section = _as_dict(tree.get(file_key))
    leaf_section = _as_dict(file_section.get(leaf_key))
    leaf_section["count"] = count
    file_section[leaf_key] = leaf_section
    tree[file_key] = file_section


def _seed_branch_entry(defaults: dict[str, Any], branch: str) -> dict[str, Any]:
    """Build a fresh per_branch entry in the shape materialize_per_branch() makes."""
    entry = {key: copy.deepcopy(val) for key, val in defaults.items() if key != "_note"}
    entry["_note"] = f"Limits for @{branch}. Manual edits persist until next push."
    return entry


def _materialize_todos(entry: dict[str, Any], defaults: dict[str, Any]) -> None:
    """Carry the todos count into a per_branch ``local`` block that lacks one, in place.

    Readers resolving per FILE key (hooks' advisory) would otherwise see no todo count.
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
    """Write one per-branch rollover limit override; never prints, never raises.

    ``pushed`` is always False: this writes ONE branch, never the fleet-wide push.
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
    """Write one global default rollover limit; ``per_branch`` is left alone.

    ``pushed`` is always False: the new default reaches NO branch until ``rollover push``.
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
