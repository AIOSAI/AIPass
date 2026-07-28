# =================== AIPass ====================
# Name: skip_dirs.py
# Description: Shared source-skip directories for branch-tree-scanning checkers
# Version: 1.0.0
# Created: 2026-06-10
# Modified: 2026-06-10
# =============================================

"""Shared skip-directory set for checkers that rglob branch trees.

Single source of truth so per-checker lists cannot drift.
Output dirs (artifacts, dropbox, docs.local, system_logs) are runtime
products, not committed source — scanning them causes local-vs-CI
audit divergence (FPLAN-0261).
"""

import sys
import tempfile
from pathlib import Path

from aipass.prax import logger

DISABLED_FILE_MARKER = "(disabled)"

_PROTOTYPE_MARKER = "# seedgo: prototype"


def is_disabled_file(name: str) -> bool:
    """Return True if filename contains the (disabled) convention marker."""
    return DISABLED_FILE_MARKER in name


def _get_temp_roots() -> list[Path]:
    """Return resolved system temp directory roots (cross-platform)."""
    roots: list[Path] = []
    try:
        roots.append(Path(tempfile.gettempdir()).resolve())
    except Exception as exc:
        logger.info("[skip_dirs] tempfile.gettempdir() failed: %s", exc)
    if sys.platform != "win32":
        tmp = Path("/" + "tmp")
        if tmp.exists():
            resolved_tmp = tmp.resolve()
            if resolved_tmp not in roots:
                roots.append(resolved_tmp)
    return roots


def is_throwaway_path(path_str: str) -> bool:
    """Return True if path is under a system temp dir or scratchpad."""
    resolved = Path(path_str).resolve()
    if any(resolved.is_relative_to(temp_root) for temp_root in _get_temp_roots()):
        return True
    if "scratchpad" in str(resolved).lower():
        return True
    return False


def is_prototype_file(path_str: str) -> bool:
    """Return True if the file has a '# seedgo: prototype' marker in its first 5 lines."""
    try:
        with open(path_str, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 5:
                    break
                if _PROTOTYPE_MARKER in line:
                    return True
    except (OSError, UnicodeDecodeError) as exc:
        logger.info("[skip_dirs] Cannot read %s for prototype check: %s", path_str, exc)
    return False


SOURCE_SKIP_DIRS: frozenset[str] = frozenset(
    {
        # Build / cache
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        # Environment
        ".venv",
        "venv",
        "node_modules",
        ".git",
        "site-packages",
        # Archive / staging
        ".archive",
        ".sorting_unprocessed",
        # Project infrastructure (not auditable source)
        ".trinity",
        ".aipass",
        ".ai_mail.local",
        ".spawn",
        # Output / runtime (gitignored — causes local-vs-CI divergence)
        "artifacts",
        "dropbox",
        "docs.local",
        "system_logs",
        # Data / non-source
        "logs",
        "tools",
        "backups",
        "reports",
        "docs",
    }
)
