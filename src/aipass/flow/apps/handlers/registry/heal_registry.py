# =================== AIPass ====================
# Name: heal_registry.py
# Description: Registry Doctrine Self-Heal Handler
# Version: 1.0.0
# Created: 2026-07-29
# Modified: 2026-07-29
# =============================================

"""
Registry Doctrine Self-Heal Handler

Extends the S155 "drift bugs auto-heal" doctrine to the per-type plan
registries. A registry audit found three classes of corruption that must
never again require a manual JSON edit:

1. Number collision — a registry entry points at a file path that no
   longer exists, while a *different*, unregistered plan file occupies the
   same type+number on disk.
2. Unregistered file — a well-formed plan file exists on disk with no
   registry key at all for its number, in its own type's registry.
3. Wrong-prefix row — a registry row lives in the wrong type's registry
   entirely (e.g. a row keyed "0011" in fplan_registry.json whose
   file_path actually names a TDPLAN file).

Guarantees:
- On-disk .md files are NEVER renamed, moved or deleted here. Only
  registry JSON rows are edited/removed. Content always survives.
- Deterministic — the registry record wins for history, the on-disk file
  gets a fresh slot. Nothing is guessed.
- Every heal is logged via prax + json_handler.
- Registry writes always go through save_registry (atomic + locked).

Usage:
    from aipass.flow.apps.handlers.registry.heal_registry import (
        heal_registry_doctrine_impl,
    )

    result = heal_registry_doctrine_impl(ecosystem_root=REPO_ROOT)
    # result -> {"healed": [...], "healed_count": 3}
"""

import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from aipass.prax import logger

from aipass.flow.apps.handlers.json import json_handler
from aipass.flow.apps.handlers.plan.close_helpers import _self_heal_unregistered_plan
from aipass.flow.apps.handlers.plan.registry_routing import _load_template_registry
from aipass.flow.apps.handlers.registry.load_registry import load_registry
from aipass.flow.apps.handlers.registry.monitor_ops import IGNORE_FOLDERS, PLAN_PATTERN
from aipass.flow.apps.handlers.registry.save_registry import save_registry

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "heal_registry"

# Matches the plan-type prefix at the start of a plan filename.
FILENAME_PREFIX_PATTERN = re.compile(r"^([A-Z]+PLAN)-")


# =============================================
# FILESYSTEM INDEX
# =============================================


def _build_plan_file_index(ecosystem_root: Path) -> Dict[Tuple[str, str], Path]:
    """Index every plan file on disk by (prefix, number).

    Keyed by the *pair* deliberately: DPLAN-0011, TDPLAN-0011 and
    PPLAN-0011 are three legitimately different plans, so a number-only
    index would collapse them into one and cross-heal the wrong registry.

    Walk skeleton mirrors ``monitor_ops.scan_plan_files_impl`` (same
    IGNORE_FOLDERS pruning, same permission-error tolerance). Directory and
    file lists are sorted so the index is deterministic run to run.

    Args:
        ecosystem_root: Root directory to scan from

    Returns:
        Dict of (prefix, number) -> Path, e.g. ``("DPLAN", "0165")``.
        On a genuine on-disk duplicate of the same prefix+number the first
        path wins and a warning is logged (renumbering is out of scope).
    """

    def handle_walk_error(error):
        """Handle permission errors during os.walk"""
        if not isinstance(error, PermissionError):
            logger.warning(f"[{MODULE_NAME}] Error during scan: {error}")

    index: Dict[Tuple[str, str], Path] = {}

    for root, dirs, files in os.walk(str(ecosystem_root), topdown=True, onerror=handle_walk_error):
        # Exact-name pruning (substring matching silently skipped whole trees)
        dirs[:] = sorted(d for d in dirs if d not in IGNORE_FOLDERS)

        for filename in sorted(files):
            match = PLAN_PATTERN.match(filename)
            if not match:
                continue
            key = (match.group(1), match.group(2))
            file_path = Path(root) / filename
            if key in index:
                logger.warning(f"[{MODULE_NAME}] On-disk duplicate for {key[0]}-{key[1]}: {file_path} (keeping first)")
                continue
            index[key] = file_path

    logger.info(f"[{MODULE_NAME}] Indexed {len(index)} plan file(s) under {ecosystem_root}")
    return index


# =============================================
# CASE 1 + 2 — PER-TYPE HEAL
# =============================================


def _heal_type_registry(
    prefix: str,
    registry_file: str,
    plan_file_index: Dict[Tuple[str, str], Path],
    load_registry_fn: Callable[..., Dict[str, Any]],
    save_registry_fn: Callable[..., bool],
) -> List[Dict[str, Any]]:
    """Heal unregistered files (case 2) and number collisions (case 1).

    For each on-disk file of this prefix:
    - No registry row for its number -> register it (case 2).
    - Row exists and its file_path is this exact file -> already correct.
    - Row exists, its file_path is missing from disk, and the path is not
      merely relocated (open or closed -- status alone proves nothing) ->
      collision (case 1): register the on-disk file at a fresh number and
      leave the original row untouched.
    - Row exists and its file_path still exists on disk -> not one of the
      three doctrine cases, left strictly alone.

    Args:
        prefix: Plan-type prefix (e.g. "DPLAN")
        registry_file: Registry filename for this type
        plan_file_index: Output of :func:`_build_plan_file_index`
        load_registry_fn: Registry loader (injected)
        save_registry_fn: Registry saver (injected)

    Returns:
        List of heal-action dicts performed for this type.
    """
    actions: List[Dict[str, Any]] = []

    on_disk = sorted(((num, path) for (pfx, num), path in plan_file_index.items() if pfx == prefix))
    if not on_disk:
        return actions

    try:
        registry = load_registry_fn(registry_file=registry_file)
    except Exception as e:
        logger.warning(f"[{MODULE_NAME}] Could not load '{registry_file}' — skipping {prefix} heal: {e}")
        return actions

    registry.setdefault("plans", {})

    # Path-level idempotency: a squatter file keeps its OLD number in its own
    # filename forever (files are never renamed), so re-scanning always finds
    # it under the same (prefix, number) key -- but a prior heal may already
    # have registered it under a *different*, fresh number, and that row
    # (open or closed) is never removed. Keying only on (prefix, number)
    # can't see that, so it mints a brand new duplicate row every scan. This
    # index lets both registration sites below check by file_path first.
    registered_by_path: Dict[Path, str] = {}
    for existing_number, existing_entry in registry["plans"].items():
        existing_path = existing_entry.get("file_path", "")
        if existing_path:
            registered_by_path.setdefault(Path(existing_path), existing_number)

    for number, path in on_disk:
        entry = registry["plans"].get(number)

        if entry is None:
            already_registered_as = registered_by_path.get(path)
            if already_registered_as is not None:
                logger.info(
                    f"[{MODULE_NAME}] {prefix}-{number} file already registered as "
                    f"{prefix}-{already_registered_as} — skipping duplicate registration"
                )
                continue
            actual_key, registry = _self_heal_unregistered_plan(
                prefix, number, path, registry, registry_file, save_registry_fn, load_registry_fn, []
            )
            registered_by_path[path] = actual_key
            actions.append(
                {
                    "action": "registered_unregistered_file",
                    "prefix": prefix,
                    "registry_file": registry_file,
                    "number": actual_key,
                    "file": str(path),
                }
            )
            logger.info(f"[{MODULE_NAME}] Registered unregistered file {prefix}-{actual_key}: {path}")
            continue

        registered_path = entry.get("file_path", "")
        if not registered_path:
            # Nothing to compare against — refuse to guess (doctrine: deterministic only).
            logger.warning(f"[{MODULE_NAME}] Row {prefix}-{number} has no file_path — leaving alone")
            continue

        if Path(registered_path) == path:
            continue

        if Path(registered_path).exists():
            # Both the row's file and this file are real — not a doctrine case.
            continue

        # Row's own file is gone -- whether or not it archived legitimately
        # (e.g. a closed plan's routine move to .backup/processed_plans),
        # that's a fact about the OLD file, not about `path`. `path` is a
        # different, real, live file squatting on the same number: a
        # genuine collision regardless of the stale row's status or where
        # its history went.
        already_registered_as = registered_by_path.get(path)
        if already_registered_as is not None:
            logger.info(
                f"[{MODULE_NAME}] {prefix}-{number} squatter already resolved as "
                f"{prefix}-{already_registered_as} — skipping duplicate collision heal"
            )
            continue

        actual_key, registry = _self_heal_unregistered_plan(
            prefix, number, path, registry, registry_file, save_registry_fn, load_registry_fn, []
        )
        registered_by_path[path] = actual_key
        actions.append(
            {
                "action": "resolved_collision",
                "prefix": prefix,
                "registry_file": registry_file,
                "number": actual_key,
                "file": str(path),
            }
        )
        logger.info(
            f"[{MODULE_NAME}] Resolved number collision on {prefix}-{number} — "
            f"registered on-disk file as {prefix}-{actual_key} ({path}), original row untouched"
        )

    return actions


# =============================================
# CASE 3 — WRONG-PREFIX ROWS
# =============================================


def _heal_wrong_prefix_rows(
    registered_types: Dict[str, Dict[str, Any]],
    load_registry_fn: Callable[..., Dict[str, Any]],
    save_registry_fn: Callable[..., bool],
) -> List[Dict[str, Any]]:
    """Relocate or drop registry rows that live in the wrong type registry.

    A row whose ``file_path`` names e.g. ``TDPLAN-0011_....md`` has no
    business sitting in ``fplan_registry.json``. Three outcomes:

    - Already correctly registered under its real type (same file_path)
      -> the wrong-registry row is a pure ghost duplicate: removed.
    - File is real on disk but not properly registered -> re-homed into
      its real type's registry, then removed from the wrong one.
    - File does not exist and is registered nowhere correct -> orphaned
      metadata with nothing behind it: removed.

    Args:
        registered_types: ``_load_template_registry()["types"]``
        load_registry_fn: Registry loader (injected)
        save_registry_fn: Registry saver (injected)

    Returns:
        List of heal-action dicts performed.
    """
    actions: List[Dict[str, Any]] = []

    prefix_map: Dict[str, str] = {}
    for _type_key, config in registered_types.items():
        type_prefix = config.get("prefix", "")
        if type_prefix:
            prefix_map[type_prefix] = f"{type_prefix.lower()}_registry.json"

    for host_prefix, host_registry_file in sorted(prefix_map.items()):
        try:
            host_registry = load_registry_fn(registry_file=host_registry_file)
        except Exception as e:
            logger.warning(f"[{MODULE_NAME}] Could not load '{host_registry_file}' for prefix audit: {e}")
            continue

        host_registry.setdefault("plans", {})

        for number, entry in sorted(host_registry["plans"].items()):
            file_path = entry.get("file_path", "") or ""
            match = FILENAME_PREFIX_PATTERN.match(Path(file_path).name)
            if not match:
                continue

            actual_prefix = match.group(1)
            if actual_prefix == host_prefix:
                continue

            actual_registry_file = prefix_map.get(actual_prefix)
            if not actual_registry_file:
                logger.warning(
                    f"[{MODULE_NAME}] Row {host_prefix} '{number}' names unknown prefix "
                    f"'{actual_prefix}' ({file_path}) — leaving alone"
                )
                continue

            try:
                actual_registry = load_registry_fn(registry_file=actual_registry_file)
            except Exception as e:
                logger.warning(f"[{MODULE_NAME}] Could not load '{actual_registry_file}' to re-home row: {e}")
                continue

            actual_registry.setdefault("plans", {})
            correct_entry = actual_registry["plans"].get(number)

            if correct_entry is not None and correct_entry.get("file_path", "") == file_path:
                action = "removed_ghost_row"
            elif file_path and Path(file_path).exists():
                _self_heal_unregistered_plan(
                    actual_prefix,
                    number,
                    Path(file_path),
                    actual_registry,
                    actual_registry_file,
                    save_registry_fn,
                    load_registry_fn,
                    [],
                )
                action = "rehomed_wrong_prefix_row"
            else:
                action = "removed_orphaned_wrong_prefix_row"

            del host_registry["plans"][number]
            save_registry_fn(host_registry, registry_file=host_registry_file)

            actions.append(
                {
                    "action": action,
                    "prefix": host_prefix,
                    "wrong_registry_file": host_registry_file,
                    "prefix_found": actual_prefix,
                    "number": number,
                    "file": file_path,
                }
            )
            logger.info(
                f"[{MODULE_NAME}] {action}: '{number}' in {host_registry_file} "
                f"actually belongs to {actual_prefix} ({file_path})"
            )

    return actions


# =============================================
# ORCHESTRATOR
# =============================================


def heal_registry_doctrine_impl(
    ecosystem_root: Path,
    load_registry_fn: Callable[..., Dict[str, Any]] = load_registry,
    save_registry_fn: Callable[..., bool] = save_registry,
) -> Dict[str, Any]:
    """Run the full registry doctrine heal across every registered plan type.

    Order matters: all per-type heals (cases 1 and 2) run before the
    wrong-prefix sweep (case 3), so real files are already registered under
    their correct type by the time case 3 runs — which reduces most
    wrong-prefix work to pure ghost-row cleanup.

    Args:
        ecosystem_root: Root directory to scan for plan files
        load_registry_fn: Registry loader (injected, defaults to real one)
        save_registry_fn: Registry saver (injected, defaults to real one)

    Returns:
        Dict containing:
        - healed: List of heal-action dicts
        - healed_count: Number of heals performed
    """
    template_reg = _load_template_registry()
    types = template_reg.get("types", {})

    plan_file_index = _build_plan_file_index(ecosystem_root)

    actions: List[Dict[str, Any]] = []

    for _type_key, config in sorted(types.items()):
        prefix = config.get("prefix", "")
        if not prefix:
            continue
        registry_file = f"{prefix.lower()}_registry.json"
        try:
            actions.extend(
                _heal_type_registry(prefix, registry_file, plan_file_index, load_registry_fn, save_registry_fn)
            )
        except Exception as e:
            logger.error(f"[{MODULE_NAME}] Heal failed for type {prefix}: {e}")

    try:
        actions.extend(_heal_wrong_prefix_rows(types, load_registry_fn, save_registry_fn))
    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Wrong-prefix sweep failed: {e}")

    by_action: Dict[str, int] = {}
    for entry in actions:
        name = entry.get("action", "unknown")
        by_action[name] = by_action.get(name, 0) + 1

    if actions:
        logger.info(f"[{MODULE_NAME}] Doctrine heal applied {len(actions)} change(s): {by_action}")

    json_handler.log_operation(
        "registry_doctrine_heal",
        {
            "total_heals": len(actions),
            "by_action": by_action,
            "success": True,
        },
    )

    return {"healed": actions, "healed_count": len(actions)}
