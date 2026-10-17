# =================== AIPass ====================
# Name: heal_registry.py
# Description: Registry Doctrine Self-Heal Handler
# Version: 1.5.0
# Created: 2026-07-29
# Modified: 2026-10-17
# =============================================

"""
Registry Doctrine Self-Heal Handler

Heals the plan-registry corruption classes so none needs a manual JSON edit:
1. Number collision: a row's file is gone and an unregistered file holds its number.
2. Unregistered file: a plan file on disk with no row in its type's registry.
3. Wrong-prefix row: a row in another type's registry (TDPLAN file in fplan_registry).
4. Missing-file orphan: an open row whose file is gone; closed on every scan, not only on create.
5. Orphan location: a row recorded at a ghost path or a project root instead of its seat.
   Stale paths are expected debris, so the class is healed; unattributable rows are quarantined.
6. Not a plan: an open row whose file is_plan_file calls False; closed in the registry only.

On-disk .md files are never renamed, moved or deleted here; only registry rows change,
always through save_registry. Nothing is guessed.
"""

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from aipass.prax import logger

from aipass.flow.apps.handlers.json import json_handler
from aipass.flow.apps.handlers.plan.auto_cleanup import auto_close_orphaned_plans
from aipass.flow.apps.handlers.plan.close_helpers import _self_heal_unregistered_plan
from aipass.flow.apps.handlers.plan.registry_routing import _load_template_registry
from aipass.flow.apps.handlers.registry.load_registry import load_registry
from aipass.flow.apps.handlers.registry.monitor_ops import IGNORE_FOLDERS, PLAN_PATTERN, is_plan_file
from aipass.flow.apps.handlers.registry.save_registry import save_registry
from aipass.flow.apps.handlers.repo_root import exists_exactly, find_repo_root

MODULE_NAME = "heal_registry"

FILENAME_PREFIX_PATTERN = re.compile(r"^([A-Z]+PLAN)-")


def _heal_not_a_plan_rows(
    prefix: str,
    registry_file: str,
    load_registry_fn: Callable[..., Dict[str, Any]],
    save_registry_fn: Callable[..., bool],
) -> List[Dict[str, Any]]:
    """Close, registry only, open rows whose present file is not a plan.

    close would archive the file, so these rows are retired here and the file is never touched.
    Only a False from is_plan_file closes a row: unreadable (None) and absent files are left alone.
    """
    registry = load_registry_fn(registry_file=registry_file)
    registry.setdefault("plans", {})

    actions: List[Dict[str, Any]] = []
    for number, entry in sorted(registry["plans"].items()):
        file_path = entry.get("file_path", "") or ""
        if entry.get("status") != "open" or not file_path or not Path(file_path).is_file():
            continue
        if is_plan_file(Path(file_path)) is not False:
            continue
        entry["status"] = "closed"
        entry["closed"] = datetime.now(timezone.utc).isoformat()
        entry["closed_reason"] = "not_a_plan"
        actions.append(
            {
                "action": "closed_not_a_plan",
                "prefix": prefix,
                "registry_file": registry_file,
                "number": number,
                "file": file_path,
            }
        )
        logger.warning(f"[{MODULE_NAME}] Closed {prefix}-{number}, registry only: its file is not a plan: {file_path}")

    # save_registry answers False instead of raising; raising here makes the caller log a failed
    # sweep rather than report rows never written. Same at every save in this file.
    if actions and not save_registry_fn(registry, registry_file=registry_file):
        raise OSError(f"could not save {registry_file}: no row was closed")
    return actions


def _build_plan_file_index(ecosystem_root: Path) -> Dict[Tuple[str, str], Path]:
    """Index every plan file on disk by (prefix, number).

    Keyed by the pair: DPLAN-0011 and TDPLAN-0011 are different plans, and a number-only
    index would cross-heal the wrong registry. Sorted walk, so the index is deterministic;
    on an on-disk duplicate the first path wins.
    """

    def handle_walk_error(error):
        """Handle permission errors during os.walk"""
        if not isinstance(error, PermissionError):
            logger.warning(f"[{MODULE_NAME}] Error during scan: {error}")

    index: Dict[Tuple[str, str], Path] = {}

    for root, dirs, files in os.walk(str(ecosystem_root), topdown=True, onerror=handle_walk_error):
        # Exact-name pruning: substring matching skips whole trees.
        dirs[:] = sorted(d for d in dirs if d not in IGNORE_FOLDERS)

        for filename in sorted(files):
            match = PLAN_PATTERN.match(filename)
            if not match:
                continue
            key = (match.group(1), match.group(2))
            file_path = Path(root) / filename
            if not is_plan_file(file_path):
                continue
            if key in index:
                logger.warning(f"[{MODULE_NAME}] On-disk duplicate for {key[0]}-{key[1]}: {file_path} (keeping first)")
                continue
            index[key] = file_path

    logger.info(f"[{MODULE_NAME}] Indexed {len(index)} plan file(s) under {ecosystem_root}")
    return index


def _heal_missing_file_plans(
    prefix: str,
    registry_file: str,
    load_registry_fn: Callable[..., Dict[str, Any]],
    save_registry_fn: Callable[..., bool],
) -> List[Dict[str, Any]]:
    """Close open registry rows whose file_path no longer exists on disk.

    Raises whatever the loader raises: an unreadable registry is a failed sweep, not an empty one.
    """
    registry = load_registry_fn(registry_file=registry_file)

    registry.setdefault("plans", {})
    open_before = {num for num, entry in registry["plans"].items() if entry.get("status") == "open"}

    registry, closed_count = auto_close_orphaned_plans(registry)
    if closed_count == 0:
        return []

    if not save_registry_fn(registry, registry_file=registry_file):
        raise OSError(f"could not save {registry_file}: no missing-file row was closed")

    actions: List[Dict[str, Any]] = []
    for number in sorted(open_before):
        entry = registry["plans"].get(number, {})
        if entry.get("closed_reason") != "auto_closed_missing_file":
            continue
        actions.append(
            {
                "action": "auto_closed_missing_file",
                "prefix": prefix,
                "registry_file": registry_file,
                "number": number,
                "file": entry.get("file_path", ""),
            }
        )
        logger.info(f"[{MODULE_NAME}] Auto-closed missing-file orphan {prefix}-{number}: {entry.get('file_path', '')}")

    return actions


def _heal_type_registry(
    prefix: str,
    registry_file: str,
    plan_file_index: Dict[Tuple[str, str], Path],
    load_registry_fn: Callable[..., Dict[str, Any]],
    save_registry_fn: Callable[..., bool],
) -> List[Dict[str, Any]]:
    """Heal unregistered files (case 2) and number collisions (case 1).

    A collision registers the on-disk file at a fresh number and leaves the original row untouched.
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

    # A squatter keeps its old number in its filename forever, but a prior heal registered it
    # under a fresh one. Keying only on (prefix, number) would mint a duplicate row every scan.
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
            # Nothing to compare against: refuse to guess.
            logger.warning(f"[{MODULE_NAME}] Row {prefix}-{number} has no file_path — leaving alone")
            continue

        if Path(registered_path) == path:
            continue

        if Path(registered_path).exists():
            continue

        # The row's file may have archived legitimately; `path` is still a different live file on
        # the same number, so this is a collision whatever the stale row's status.
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


def _heal_wrong_prefix_rows(
    registered_types: Dict[str, Dict[str, Any]],
    load_registry_fn: Callable[..., Dict[str, Any]],
    save_registry_fn: Callable[..., bool],
) -> List[Dict[str, Any]]:
    """Relocate or drop registry rows that live in the wrong type registry."""
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
            if not save_registry_fn(host_registry, registry_file=host_registry_file):
                raise OSError(f"could not save {host_registry_file}: row '{number}' is still there")

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


def _find_repo_root() -> Path:
    """Walk up to the repo root (the directory holding AIPASS_REGISTRY.json)."""
    return find_repo_root(caller="heal_registry")


def _is_citizen_seat(path: Path) -> bool:
    """A seat is a directory carrying a passport. Nothing else is a citizen."""
    return (path / ".trinity" / "passport.json").is_file()


def _project_root(path: Path) -> Path | None:
    """Nearest ancestor holding a .git directory, or None."""
    for parent in [path] + list(path.parents):
        if (parent / ".git").exists():
            return parent
    return None


def _citizen_seat_index() -> Dict[str, List[Path]]:
    """Index live citizen seats by directory name.

    Sources: the ecosystem registry, plus locations in the plan registries (the only way citizens
    in other repos are known). A path counts only if it carries a passport.
    """
    repo_root = _find_repo_root()
    candidates: set[Path] = set()

    # exists_exactly: on a case-folding filesystem is_file() accepts a lowercase lookalike,
    # which matters when find_repo_root fell back to SOURCE_ROOT.
    registry_file = repo_root / "AIPASS_REGISTRY.json"
    if exists_exactly(registry_file) and registry_file.is_file():
        try:
            import json

            data = json.loads(registry_file.read_text(encoding="utf-8"))
            for branch in data.get("branches", []):
                rel = branch.get("path", "")
                if rel:
                    candidates.add((repo_root / rel).resolve())
        except Exception as exc:
            logger.warning(f"[{MODULE_NAME}] Could not read ecosystem registry for seat index: {exc}")

    types = _load_template_registry().get("types", {})
    for config in types.values():
        prefix = config.get("prefix", "")
        if not prefix:
            continue
        try:
            registry = load_registry(f"{prefix.lower()}_registry.json")
        except Exception as exc:
            # A smaller seat index only under-attributes (quarantines, never mis-heals); say so.
            logger.warning(
                f"[{MODULE_NAME}] Could not read '{prefix.lower()}_registry.json' for the seat index; "
                f"citizens known only from it may be quarantined this run: {exc}"
            )
            continue
        for row in registry.get("plans", {}).values():
            location = row.get("location", "")
            if location:
                candidates.add(Path(location))

    index: Dict[str, List[Path]] = {}
    for path in candidates:
        if _is_citizen_seat(path):
            index.setdefault(path.name, []).append(path)
    return index


def _seats_beneath(location: Path, seats: Dict[str, List[Path]]) -> List[Path]:
    """Live citizen seats living strictly below a directory."""
    return [seat for group in seats.values() for seat in group if location in seat.parents]


def _is_orphan_location(location: Path, seats: Dict[str, List[Path]]) -> bool:
    """Decide whether a recorded location is orphaned.

    Orphaned means gone from disk, or a non-seat holding exactly one seat beneath it. Not
    "anything that is not a seat": repo-root and subdirectory filings are normal, and a
    directory holding several seats is a container.
    """
    if not location.exists():
        return True
    if _is_citizen_seat(location):
        return False
    return len(_seats_beneath(location, seats)) == 1


def _attribute_orphan(location: Path, seats: Dict[str, List[Path]]) -> Tuple[Path | None, str]:
    """Decide which live citizen an orphaned location belongs to.

    Containment of exactly one seat wins; otherwise exactly one same-named seat whose repository
    holds the orphan. A bare name match across repos is refused. Returns (seat, "") or (None, reason).
    """
    enclosed = _seats_beneath(location, seats)
    if len(enclosed) == 1:
        return enclosed[0], ""

    matches = seats.get(location.name, [])
    if not matches:
        return None, f"no live citizen named '{location.name}'"
    if len(matches) > 1:
        return None, f"{len(matches)} live citizens named '{location.name}' — ambiguous"

    seat = matches[0]
    root = _project_root(seat)
    if root is None:
        return None, f"cannot establish the repository of seat '{seat}'"
    if root not in location.parents and location != root:
        return None, f"orphan lies outside the repository of citizen '{location.name}'"
    return seat, ""


def _heal_orphan_locations(
    types: Dict[str, Any],
    load_registry_fn: Callable[..., Dict[str, Any]],
    save_registry_fn: Callable[..., bool],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Re-attribute plan rows whose location is not a live citizen seat.

    Rows are never deleted and locations never guessed: unattributable rows are returned as
    quarantined and left as they are. Returns (heal actions, quarantined rows).
    """
    seats = _citizen_seat_index()
    actions: List[Dict[str, Any]] = []
    quarantined: List[Dict[str, Any]] = []

    for _type_key, config in sorted(types.items()):
        prefix = config.get("prefix", "")
        if not prefix:
            continue
        registry_file = f"{prefix.lower()}_registry.json"
        registry = load_registry_fn(registry_file)
        plans = registry.get("plans", {})
        dirty = False

        for number, row in plans.items():
            plan_id = f"{prefix}-{str(number).zfill(4)}"
            raw_location = row.get("location", "")
            if not raw_location:
                quarantined.append(
                    {"plan_id": plan_id, "registry": registry_file, "location": "", "reason": "no location recorded"}
                )
                continue

            location = Path(raw_location)
            if not _is_orphan_location(location, seats):
                continue

            seat, reason = _attribute_orphan(location, seats)
            if seat is None:
                quarantined.append(
                    {"plan_id": plan_id, "registry": registry_file, "location": raw_location, "reason": reason}
                )
                continue

            row["location"] = str(seat)
            # A half-moved record is worse than an un-moved one.
            for key in ("file_path", "relative_path"):
                value = row.get(key, "")
                if value and str(value).startswith(raw_location):
                    row[key] = str(value).replace(raw_location, str(seat), 1)
            dirty = True
            actions.append(
                {
                    "action": "orphan_location_reattributed",
                    "plan_id": plan_id,
                    "prefix": prefix,
                    "number": str(number).zfill(4),
                    "registry": registry_file,
                    "from": raw_location,
                    "to": str(seat),
                }
            )
            logger.info(f"[{MODULE_NAME}] {plan_id}: location re-attributed {raw_location} -> {seat}")

        if dirty and not save_registry_fn(registry, registry_file):
            raise OSError(f"could not save {registry_file}: no location was re-attributed")

    if quarantined:
        logger.warning(
            f"[{MODULE_NAME}] {len(quarantined)} plan row(s) quarantined — location not attributable to any "
            f"live citizen. Surfaced by 'drone @flow registry status'; nothing was written for these."
        )

    return actions, quarantined


def find_quarantined_locations(
    load_registry_fn: Callable[..., Dict[str, Any]] = load_registry,
) -> List[Dict[str, Any]]:
    """List plan rows whose location cannot be attributed to a live citizen.

    Read-only: status output must never write.
    """
    seats = _citizen_seat_index()
    types = _load_template_registry().get("types", {})
    quarantined: List[Dict[str, Any]] = []

    for _type_key, config in sorted(types.items()):
        prefix = config.get("prefix", "")
        if not prefix:
            continue
        registry_file = f"{prefix.lower()}_registry.json"
        try:
            registry = load_registry_fn(registry_file)
        except Exception as exc:
            logger.warning(f"[{MODULE_NAME}] Could not read '{registry_file}' for quarantine list: {exc}")
            continue

        for number, row in registry.get("plans", {}).items():
            plan_id = f"{prefix}-{str(number).zfill(4)}"
            raw_location = row.get("location", "")
            if not raw_location:
                quarantined.append(
                    {"plan_id": plan_id, "registry": registry_file, "location": "", "reason": "no location recorded"}
                )
                continue
            location = Path(raw_location)
            if not _is_orphan_location(location, seats):
                continue
            seat, reason = _attribute_orphan(location, seats)
            if seat is None:
                quarantined.append(
                    {"plan_id": plan_id, "registry": registry_file, "location": raw_location, "reason": reason}
                )

    return quarantined


def heal_registry_doctrine_impl(
    ecosystem_root: Path,
    load_registry_fn: Callable[..., Dict[str, Any]] = load_registry,
    save_registry_fn: Callable[..., bool] = save_registry,
) -> Dict[str, Any]:
    """Run the full registry doctrine heal across every registered plan type.

    Per-type heals run before the wrong-prefix sweep, so real files are already registered
    under their correct type and most wrong-prefix work is ghost-row cleanup.
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
            actions.extend(_heal_missing_file_plans(prefix, registry_file, load_registry_fn, save_registry_fn))
        except Exception as e:
            logger.error(f"[{MODULE_NAME}] Missing-file sweep failed for type {prefix}: {e}")
        try:
            actions.extend(_heal_not_a_plan_rows(prefix, registry_file, load_registry_fn, save_registry_fn))
        except Exception as e:
            logger.error(f"[{MODULE_NAME}] Not-a-plan sweep failed for type {prefix}: {e}")
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

    quarantined: List[Dict[str, Any]] = []
    try:
        orphan_actions, quarantined = _heal_orphan_locations(types, load_registry_fn, save_registry_fn)
        actions.extend(orphan_actions)
    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Orphan-location sweep failed: {e}")

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
            "quarantined": len(quarantined),
            "success": True,
        },
    )

    return {
        "healed": actions,
        "healed_count": len(actions),
        "quarantined": quarantined,
        "quarantined_count": len(quarantined),
    }
