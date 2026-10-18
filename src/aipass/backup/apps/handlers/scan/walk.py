# =================== AIPass ====================
# Name: walk.py
# Description: Project tree walker yielding file paths
# Version: 1.0.1
# Created: 2026-04-16
# Modified: 2026-10-17
# =============================================

"""Project tree walker."""

import os
from collections.abc import Iterator

from ..audit import trail


def walk_project(root: str) -> Iterator[tuple[str, str]]:
    """Walk the project tree rooted at ``root``."""
    trail.log_operation("walk_project", {"root": root})
    root_path = os.path.realpath(root)

    def _refuse_unlisted(err: OSError) -> None:
        """Raise on a directory the walk cannot list; only a root that is not there walks to nothing."""
        if isinstance(err, FileNotFoundError) and err.filename == root_path:
            return
        raise err

    for dirpath, _dirnames, filenames in os.walk(root_path, onerror=_refuse_unlisted, followlinks=False):
        for filename in filenames:
            abs_path = os.path.join(dirpath, filename)
            if os.path.islink(abs_path):
                continue
            rel_path = os.path.relpath(abs_path, root_path)
            yield abs_path, rel_path
