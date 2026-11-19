# =================== AIPass ====================
# Name: prune.py
# Description: Prune handler — finds and removes stored copies whose project path the ignore spec now matches
# Version: 1.1.0
# Created: 2026-10-16
# Modified: 2026-11-15
# =============================================

"""Prune handler — stored copies of paths the ignore spec now matches.

Reference: docs/store_cleanup.md
"""

import os
from pathlib import Path

import pathspec

from aipass.prax import logger

from ..audit import trail
from ..ignore.patterns import load_spec
from ..ignore.whitelist import load_whitelist
from ..scan.filter import is_excluded
from ..path.builder import build_snapshot_path

#: The top-level group a root-level file is listed under.
ROOT_GROUP = "(root files)"
#: The one store prune reads: the snapshot store. Nothing else under .backup/ is touched.
LANE = "snapshots"


def _raise_walk_error(err: OSError) -> None:
    """Raise on a store directory the walk cannot list: an unlisted subtree would read as clean."""
    raise err


def _top_group(rel_path: str) -> str:
    """The top-level directory a project-relative path is listed under."""
    head, sep, _rest = rel_path.partition("/")
    return head if sep else ROOT_GROUP


def _snapshot_candidates(store: Path, spec: pathspec.PathSpec, whitelist: list[str]) -> list[dict]:
    """Every file under the snapshot store whose project-relative path is now matched."""
    found: list[dict] = []
    if not store.exists():
        return found
    for dirpath, _dirnames, filenames in os.walk(store, onerror=_raise_walk_error, followlinks=False):
        for filename in filenames:
            path = Path(dirpath) / filename
            rel_path = path.relative_to(store).as_posix()
            if is_excluded(rel_path, spec, whitelist):
                found.append({"rel_path": rel_path, "path": path, "bytes": path.lstat().st_size})
    return found


def _group(candidates: list[dict]) -> dict[str, dict]:
    """Per top-level directory: how many candidates and how many bytes, sorted by name."""
    groups: dict[str, dict] = {}
    for item in candidates:
        group = groups.setdefault(_top_group(item["rel_path"]), {"count": 0, "bytes": 0})
        group["count"] += 1
        group["bytes"] += item["bytes"]
    return dict(sorted(groups.items()))


def find_prunable(project_root: str) -> dict:
    """List the snapshot copies the ignore spec now matches; OSError on an unlistable store."""
    spec = load_spec(project_root)
    whitelist = load_whitelist(project_root)
    snapshots = _snapshot_candidates(build_snapshot_path(project_root), spec, whitelist)
    found = {
        LANE: snapshots,
        "groups": {LANE: _group(snapshots)},
        "count": len(snapshots),
        "bytes": sum(item["bytes"] for item in snapshots),
    }
    trail.log_operation(
        "prune_listed",
        {"project_root": project_root, "count": found["count"], "bytes": found["bytes"]},
    )
    return found


def _remove_empty_parents(paths: list[Path], store: Path) -> None:
    """Remove directories left empty under ``store`` by the removals, deepest first."""
    parents = {parent for path in paths for parent in path.parents if store in parent.parents}
    for directory in sorted(parents, key=lambda p: len(p.parts), reverse=True):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()


def apply_prune(project_root: str, found: dict) -> dict:
    """Delete what ``find_prunable`` listed, one trail row per removed path; a failure is never counted removed."""
    removed = 0
    freed = 0
    errors: list[str] = []
    done: list[Path] = []
    for item in found[LANE]:
        try:
            item["path"].unlink()
        except OSError as e:
            logger.warning(f"[prune] Could not remove {item['path']}: {e}")
            errors.append(f"{LANE}/{item['rel_path']}: {e}")
            continue
        removed += 1
        freed += item["bytes"]
        done.append(item["path"])
        trail.log_operation(
            "prune_removed",
            {"project_root": project_root, "lane": LANE, "rel_path": item["rel_path"], "bytes": item["bytes"]},
        )
    store = build_snapshot_path(project_root)
    try:
        _remove_empty_parents(done, store)
    except OSError as e:
        logger.warning(f"[prune] Could not remove an emptied directory under {store}: {e}")
        errors.append(f"{LANE}: emptied directory not removed: {e}")
    trail.log_operation(
        "prune_applied",
        {"project_root": project_root, "removed": removed, "bytes": freed, "errors": len(errors)},
    )
    logger.info(f"[prune] Removed {removed} stored paths ({freed} bytes) for {project_root}")
    return {"removed": removed, "bytes": freed, "errors": errors}
