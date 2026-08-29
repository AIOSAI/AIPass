# =================== AIPass ====================
# Name: discover.py - pytest target discovery
# Description: finds test files under a target; the refusal when there are none
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""Find the pytest files in a target directory.

The lane works on *any* directory containing pytest targets, so discovery is by
filename convention rather than by branch layout.  A target with no test files
is refused loudly: silently scoring an empty suite 100 is the exact shape of
lie Law S1 exists to prevent.
"""

from __future__ import annotations

from pathlib import Path

from .logsetup import logger

SKIP_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    "templates",
    ".backup",
    ".archive",
}


class NoTestsError(RuntimeError):
    """The target holds nothing pytest would collect."""


def find_test_files(root: Path) -> list[Path]:
    """Every ``test_*.py`` / ``*_test.py`` under ``root``, sorted."""
    found: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except OSError as exc:
            logger.debug("unreadable directory skipped: %s", current, exc_info=exc)
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name not in SKIP_DIRS:
                    stack.append(entry)
            elif entry.suffix == ".py" and (entry.name.startswith("test_") or entry.name.endswith("_test.py")):
                found.append(entry)
    return sorted(found)


def require_tests(root: Path) -> list[Path]:
    """Discovery, or a refusal naming the directory that came up empty."""
    if not root.is_dir():
        raise NoTestsError(f"{root} is not a directory")
    files = find_test_files(root)
    if not files:
        raise NoTestsError(
            f"no pytest test files under {root} "
            "(looked for test_*.py and *_test.py). audit-tests refuses to score "
            "a target it cannot measure."
        )
    return files
