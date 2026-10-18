# =================== AIPass ====================
# Name: patterns.py
# Description: Ignore pattern loader — pathspec/gitwildmatch matcher
# Version: 2.1.0
# Created: 2026-04-17
# Modified: 2026-10-17
# =============================================

"""Ignore patterns handler."""

import pathspec

from ..audit import trail
from ..path import builder

# Ahead of every project's own .backupignore, so a project can still re-include with "!*.tmp".
# *.tmp: the json service's staging temps a killed writer leaves; never anyone's work.
BUILTIN_IGNORE_PATTERNS: tuple[str, ...] = ("*.tmp",)


def load_spec(project_root: str) -> pathspec.PathSpec:
    """Load a PathSpec from .backupignore at the project root."""
    ignore_path = builder.build_ignore_path(project_root)
    lines: list[str] = list(BUILTIN_IGNORE_PATTERNS)

    if ignore_path.exists():
        with open(ignore_path, encoding="utf-8") as f:
            lines.extend(f.readlines())

    spec = pathspec.PathSpec.from_lines("gitignore", lines)
    trail.log_operation(
        "load_spec",
        {"project_root": project_root, "pattern_count": len(spec.patterns)},
    )
    return spec


def is_ignored(rel_path: str, spec: pathspec.PathSpec) -> bool:
    """Check whether a relative path is ignored by the spec."""
    return spec.match_file(rel_path.replace("\\", "/"))
