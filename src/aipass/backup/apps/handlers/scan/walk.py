# =================== AIPass ====================
# Name: walk.py
# Description: Project tree walker yielding file paths
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-23
# =============================================

"""Project tree walker.

Recursively enumerates files beneath a project root and yields
(absolute_path, relative_path) tuples for downstream filtering and copying.
"""

import os
from collections.abc import Iterator

from ..audit import trail


def walk_project(root: str) -> Iterator[tuple[str, str]]:
    """Walk the project tree rooted at ``root``.

    Args:
        root: Absolute path to the project root directory.

    Yields:
        Tuples of (absolute_path, relative_path) for every file beneath root.
        Skips symlinks.
    """
    trail.log_operation("walk_project", {"root": root})
    root_path = os.path.realpath(root)

    for dirpath, _dirnames, filenames in os.walk(root_path, followlinks=False):
        for filename in filenames:
            abs_path = os.path.join(dirpath, filename)
            if os.path.islink(abs_path):
                continue
            rel_path = os.path.relpath(abs_path, root_path)
            yield abs_path, rel_path


# =============================================
