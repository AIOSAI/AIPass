# =================== AIPass ====================
# Name: prune.py
# Description: Prune handler — finds and removes stored copies whose project path the ignore spec now matches
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-17
# =============================================

"""Prune handler — stored copies of paths the ignore spec now matches.

Reference: docs/store_cleanup.md
"""

import hashlib
import os
import shutil
import stat
from pathlib import Path

import pathspec

from aipass.prax import logger

from ..audit import trail
from ..ignore.patterns import is_ignored, load_spec
from ..ignore.whitelist import is_whitelisted, load_whitelist
from ..path.builder import build_snapshot_path, build_versioned_store

#: The top-level group a root-level file is listed under.
ROOT_GROUP = "(root files)"
_LONG_NAME = 50


def _raise_walk_error(err: OSError) -> None:
    """Raise on a store directory the walk cannot list: an unlisted subtree would read as clean."""
    raise err


def _folder_name(name: str) -> str:
    """The file-folder name the versioned store gives a file called ``name``; mirrors path/builder.py."""
    if len(name) > _LONG_NAME:
        return name[:30] + "_" + hashlib.md5(name.encode()).hexdigest()[:8]
    return name


def _top_group(rel_path: str) -> str:
    """The top-level directory a project-relative path is listed under."""
    head, sep, _rest = rel_path.partition("/")
    return head if sep else ROOT_GROUP


def _matched(rel_path: str, spec: pathspec.PathSpec, whitelist: list[str]) -> bool:
    """True when the backup's own filter would now leave this path out."""
    return is_ignored(rel_path, spec) and not is_whitelisted(rel_path, whitelist)


def _snapshot_candidates(store: Path, spec: pathspec.PathSpec, whitelist: list[str]) -> list[dict]:
    """Every file under the snapshot store whose project-relative path is now matched."""
    found: list[dict] = []
    if not store.exists():
        return found
    for dirpath, _dirnames, filenames in os.walk(store, onerror=_raise_walk_error, followlinks=False):
        for filename in filenames:
            path = Path(dirpath) / filename
            rel_path = path.relative_to(store).as_posix()
            if _matched(rel_path, spec, whitelist):
                found.append({"rel_path": rel_path, "path": path, "bytes": path.lstat().st_size})
    return found


def _current_name(folder: Path, filenames: list[str]) -> str | None:
    """The current copy's name when ``folder`` is a versioned file-folder, else None."""
    for filename in filenames:
        if _folder_name(filename) == folder.name:
            return filename
    return None


def _folder_bytes(folder: Path, name: str, filenames: list[str]) -> int:
    """Bytes held by one file-folder: its own files and its ``<name>_diffs/``."""
    total = sum((folder / filename).lstat().st_size for filename in filenames)
    diffs = folder / f"{name}_diffs"
    if diffs.is_dir():
        for dirpath, _dirnames, diff_files in os.walk(diffs, onerror=_raise_walk_error, followlinks=False):
            total += sum((Path(dirpath) / f).lstat().st_size for f in diff_files)
    return total


def _versioned_candidates(store: Path, spec: pathspec.PathSpec, whitelist: list[str]) -> list[dict]:
    """Every file-folder under the versioned store whose project-relative path is now matched."""
    found: list[dict] = []
    if not store.exists():
        return found
    for dirpath, dirnames, filenames in os.walk(store, onerror=_raise_walk_error, followlinks=False):
        folder = Path(dirpath)
        name = _current_name(folder, filenames) if folder != store else None
        if name is None:
            continue
        # A file-folder's own diffs are part of it, never a folder of their own.
        dirnames[:] = [d for d in dirnames if d != f"{name}_diffs"]
        parent = folder.parent.relative_to(store).as_posix()
        rel_path = name if parent == "root" else f"{parent}/{name}"
        if _matched(rel_path, spec, whitelist):
            found.append(
                {"rel_path": rel_path, "path": folder, "bytes": _folder_bytes(folder, name, filenames), "name": name}
            )
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
    """List the stored copies the ignore spec now matches, in both stores; OSError on an unlistable store."""
    spec = load_spec(project_root)
    whitelist = load_whitelist(project_root)
    snapshots = _snapshot_candidates(build_snapshot_path(project_root), spec, whitelist)
    versioned = _versioned_candidates(build_versioned_store(project_root), spec, whitelist)
    everything = snapshots + versioned
    found = {
        "snapshots": snapshots,
        "versioned": versioned,
        "groups": {"snapshots": _group(snapshots), "versioned": _group(versioned)},
        "count": len(everything),
        "bytes": sum(item["bytes"] for item in everything),
    }
    trail.log_operation(
        "prune_listed",
        {"project_root": project_root, "count": found["count"], "bytes": found["bytes"]},
    )
    return found


def _make_writable(path: Path) -> None:
    """Best-effort chmod so a read-only stored copy can be removed."""
    try:
        path.chmod(stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
    except OSError as e:
        logger.info(f"[prune] Could not chmod {path}: {e}")


def _remove(lane: str, item: dict) -> None:
    """Remove one candidate: a snapshot file, or a versioned file-folder's files and diffs.

    A file-folder itself goes only once empty: a subdirectory other than its
    diffs belongs to a later project directory of the same name, and stays.
    """
    if lane == "snapshots":
        _make_writable(item["path"])
        item["path"].unlink()
        return
    folder: Path = item["path"]
    for entry in folder.iterdir():
        if entry.is_file() or entry.is_symlink():
            _make_writable(entry)
            entry.unlink()
    diffs = folder / f"{item['name']}_diffs"
    if diffs.is_dir():
        shutil.rmtree(diffs)
    if not any(folder.iterdir()):
        folder.rmdir()


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
    for lane in ("snapshots", "versioned"):
        done: list[Path] = []
        for item in found[lane]:
            try:
                _remove(lane, item)
            except OSError as e:
                logger.warning(f"[prune] Could not remove {item['path']}: {e}")
                errors.append(f"{lane}/{item['rel_path']}: {e}")
                continue
            removed += 1
            freed += item["bytes"]
            done.append(item["path"])
            trail.log_operation(
                "prune_removed",
                {"project_root": project_root, "lane": lane, "rel_path": item["rel_path"], "bytes": item["bytes"]},
            )
        store = build_snapshot_path(project_root) if lane == "snapshots" else build_versioned_store(project_root)
        try:
            _remove_empty_parents(done, store)
        except OSError as e:
            logger.warning(f"[prune] Could not remove an emptied directory under {store}: {e}")
            errors.append(f"{lane}: emptied directory not removed: {e}")
    trail.log_operation(
        "prune_applied",
        {"project_root": project_root, "removed": removed, "bytes": freed, "errors": len(errors)},
    )
    logger.info(f"[prune] Removed {removed} stored paths ({freed} bytes) for {project_root}")
    return {"removed": removed, "bytes": freed, "errors": errors}
