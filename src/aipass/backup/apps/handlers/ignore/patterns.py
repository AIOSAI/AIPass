# =================== AIPass ====================
# Name: patterns.py
# Description: Ignore pattern loader — pathspec/gitwildmatch matcher
# Version: 2.0.0
# Created: 2026-04-17
# Modified: 2026-06-12
# =============================================

"""Ignore patterns handler.

Loads .backupignore from the project root and matches paths using
pathspec (gitwildmatch) — true gitignore semantics.
"""

import pathspec

from ..audit import trail
from ..path import builder


def load_spec(project_root: str) -> pathspec.PathSpec:
    """Load a PathSpec from .backupignore at the project root.

    This is the runtime source of truth — the seed template is not consulted here.
    Reads raw lines — pathspec handles #comments, blanks, !negation,
    anchoring, dir-only trailing /, and last-match-wins natively.

    Args:
        project_root: Absolute path to the project root.

    Returns:
        A compiled PathSpec using gitwildmatch semantics.
    """
    ignore_path = builder.build_ignore_path(project_root)
    lines: list[str] = []

    if ignore_path.exists():
        with open(ignore_path, encoding="utf-8") as f:
            lines = f.readlines()

    spec = pathspec.PathSpec.from_lines("gitignore", lines)
    trail.log_operation(
        "load_spec",
        {"project_root": project_root, "pattern_count": len(spec.patterns)},
    )
    return spec


def is_ignored(rel_path: str, spec: pathspec.PathSpec) -> bool:
    """Check whether a relative path is ignored by the spec.

    Args:
        rel_path: Path relative to the project root (forward slashes).
        spec: Compiled PathSpec from load_spec().

    Returns:
        True when the path should be ignored.
    """
    return spec.match_file(rel_path.replace("\\", "/"))


# =============================================
