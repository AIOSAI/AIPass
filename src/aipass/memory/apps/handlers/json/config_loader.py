# =================== AIPass ====================
# Name: config_loader.py
# Description: Unified config loader for memory.config.json
# Version: 1.2.0
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

    Returns:
        True if the file was written, False if the write failed (logged).
    """
    tmp_path = _CONFIG_PATH.parent / f"{_CONFIG_PATH.name}.tmp-{os.getpid()}"
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
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

    Returns:
        The effective config dict (always safe to use).
    """
    if not _CONFIG_PATH.exists():
        logger.info(f"[config_loader] No config at {_CONFIG_PATH}, regenerating from defaults")
        return _regenerate("missing")

    raw = _CONFIG_PATH.read_text(encoding="utf-8")
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
        except json.JSONDecodeError as exc:
            logger.error(f"[config_loader] Cannot push onto unreadable config: {exc}")
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
