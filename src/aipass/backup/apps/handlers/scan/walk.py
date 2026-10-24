# =================== AIPass ====================
# Name: walk.py
# Description: Project tree walker yielding file paths
# Version: 1.0.3
# Created: 2026-04-16
# Modified: 2026-10-24
# =============================================

"""Project tree walker."""

import os
from collections.abc import Iterator

import pathspec

from ..audit import trail
from ..ignore.patterns import is_ignored


def _prunable(spec: pathspec.PathSpec | None, whitelist: list[str]) -> bool:
    """True when a matched directory can hold nothing the filter keeps: no "!" pattern, no whitelist entry."""
    return spec is not None and not whitelist and all(p.include is not False for p in spec.patterns)


def walk_project(
    root: str,
    spec: pathspec.PathSpec | None = None,
    whitelist: list[str] | None = None,
) -> Iterator[tuple[str, str]]:
    """Walk the project tree rooted at ``root``; with a spec, never enter a directory it ignores."""
    trail.log_operation("walk_project", {"root": root})
    root_path = os.path.realpath(root)
    prune_spec = spec if _prunable(spec, whitelist or []) else None

    def _refuse_unlisted(err: OSError) -> None:
        """Raise on a directory the walk cannot list; only a root that is not there walks to nothing."""
        if isinstance(err, FileNotFoundError) and err.filename == root_path:
            return
        raise err

    for dirpath, dirnames, filenames in os.walk(root_path, onerror=_refuse_unlisted, followlinks=False):
        if prune_spec is not None:
            rel_dir = os.path.relpath(dirpath, root_path)
            prefix = "" if rel_dir == "." else rel_dir + "/"
            dirnames[:] = [d for d in dirnames if not is_ignored(f"{prefix}{d}/", prune_spec)]
        for filename in filenames:
            abs_path = os.path.join(dirpath, filename)
            if os.path.islink(abs_path):
                continue
            rel_path = os.path.relpath(abs_path, root_path)
            yield abs_path, rel_path
