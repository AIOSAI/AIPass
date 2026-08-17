# =================== AIPass ====================
# Name: config_loader.py
# Description: Unified config loader for memory.config.json
# Version: 1.3.0
# Created: 2026-06-13
# Modified: 2026-08-08
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

from aipass.memory.apps.handlers.json import json_handler
from aipass.prax import logger

_MEMORY_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _MEMORY_ROOT / "memory_json" / "custom_config" / "memory.config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "_meta": {
        "memory_pool": {
            "consumers": ["intake/pool_processor.py", "intake/auto_process.py", "monitor/memory_watcher.py"],
            "purpose": "Vectorize files dropped in memory_pool/, archive beyond keep_recent",
        },
        "entry_limits": {
            "consumers": ["json/entry_limits.py", "modules/lint.py"],
            "purpose": "Per-entry char caps on .trinity writes (enforced)",
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
            },
            "sessions": {
                "file": "local.json",
                "container": "sessions",
                "kind": "list",
                "field": "summary",
                "max_chars": 300,
            },
            "todos": {
                "file": "local.json",
                "container": "todos",
                "kind": "list",
                "field": "task",
                "max_chars": 150,
            },
            "observations": {
                "file": "observations.json",
                "container": "observations",
                "kind": "list",
                "field": "note",
                "max_chars": 300,
            },
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


# Entry type -> (file key, leaf key) inside the rollover limits tree. These
# three are the ONLY settable rollover limits. The FILE key is the unit the
# rollover engine resolves per branch (see _resolve_limits); the leaf key is
# the entry family inside it.
ENTRY_TYPE_KEYS: dict[str, tuple[str, str]] = {
    "sessions": ("local", "sessions"),
    "key_learnings": ("local", "key_learnings"),
    "observations": ("observations", "observations"),
}


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
    """Walk up from this file to find repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


def materialize_per_branch() -> dict[str, Any]:
    """Build per_branch from AIPASS_REGISTRY.json, seeded from rollover.defaults."""
    repo_root = _find_repo_root()
    registry_path = repo_root / "AIPASS_REGISTRY.json"
    if not registry_path.exists():
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


def _resolve_limits(rollover_cfg: dict[str, Any], branch: str) -> dict[str, Any]:
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

    Args:
        rollover_cfg: The ``rollover`` section (already loaded — no I/O here).
        branch: Branch name, matched case-insensitively.

    Returns:
        ``{entry_type: {"count", "default_count", "auto_compact_cap",
        "source", "is_override"}}`` for each of the three entry types.
        ``count`` is None when neither per_branch nor defaults set one.
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

        resolved[entry_type] = {
            "count": count,
            "default_count": default_count,
            "auto_compact_cap": leaf.get("auto_compact_cap"),
            "source": source,
            "is_override": count != default_count,
        }

    return resolved


def resolve_limits(rollover_cfg: dict[str, Any], branch: str) -> dict[str, Any]:
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

    Returns:
        See ``_resolve_limits``.
    """
    return _resolve_limits(rollover_cfg, branch)


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
        See ``_resolve_limits`` — one entry per settable entry type.
    """
    return _resolve_limits(section("rollover"), branch)


def get_branches_with_overrides() -> dict[str, Any]:
    """Return only the configured branches whose limits deviate from defaults.

    Loads the config once, not once per branch: 17 loads would mean 17 reads
    and 17 operation-log lines for a single display.

    Returns:
        ``{branch: effective_limits}``, branch-sorted, deviating branches only.
    """
    rollover_cfg = section("rollover")
    per_branch = _as_dict(rollover_cfg.get("per_branch"))

    deviating: dict[str, Any] = {}
    for branch in sorted(per_branch):
        limits = _resolve_limits(rollover_cfg, branch)
        if any(row["is_override"] for row in limits.values()):
            deviating[branch] = limits

    return deviating


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


def set_branch_limit(branch: str, entry_type: str, count: int) -> dict[str, Any]:
    """Write one per-branch rollover limit override.

    Never prints and never raises: the module layer owns the refusal wording.

    Args:
        branch: Branch name — the lowercase form is always what gets written.
        entry_type: One of ``ENTRY_TYPE_KEYS``.
        count: The new limit (bounds are the module layer's contract).

    Returns:
        ``{"success": True, "branch", "entry_type", "count", "pushed"}`` or
        ``{"success": False, "error": <sentence>}``.  ``pushed`` is always
        False: this writes ONE branch's entry, it never runs the fleet-wide
        push.  It is reported rather than assumed so the machine surface
        states the delivery semantics in data instead of in prose.
    """
    if entry_type not in ENTRY_TYPE_KEYS:
        return {"success": False, "error": f"Unknown entry type: '{entry_type}'"}

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
        entry_type: One of ``ENTRY_TYPE_KEYS``.
        count: The new default limit.

    Returns:
        ``{"success": True, "entry_type", "count", "pushed"}`` or
        ``{"success": False, "error": <sentence>}``.  ``pushed`` is always
        False and says the load-bearing thing about this verb: the new
        default reached NO branch.  ``rollover push`` is what delivers it.
    """
    if entry_type not in ENTRY_TYPE_KEYS:
        return {"success": False, "error": f"Unknown entry type: '{entry_type}'"}

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
