# =================== AIPass ====================
# Name: ignore_handler.py
# Description: Ignore Pattern Configuration Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Ignore Pattern Configuration Handler

Provides ignore patterns for audit file filtering, template baseline checking,
and deprecated pattern tracking. Pure configuration with helper functions.

Also provides the .seedgoignore engine — a gitignore-style dotfile droppable
into any directory (per-directory scope, same nesting semantics as .gitignore)
plus a global default so agents' tools/ dirs are ignored fleet-wide with zero
per-branch setup. See DEFAULT_IGNORE_PATTERNS / is_seedgo_ignored().
"""

# =============================================
# IMPORTS
# =============================================

from pathlib import Path
from typing import List, Optional, Tuple

import pathspec

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

# =============================================
# TEMPLATE IGNORE PATTERNS
# =============================================

# Template files that exist in spawn template but aren't required in branches
# Used by architecture_check.py when checking template baseline
TEMPLATE_IGNORE_PATTERNS = [
    ".gitkeep",  # Git placeholder files - not actual requirements
    "notepad.md",  # Optional scratch file
    ".gitignore",  # Optional - branches inherit from root
    "test_scaffold.py",  # Scaffold example — branches have their own tests
]

# =============================================
# AUDIT IGNORE PATTERNS
# =============================================

# Patterns for files/directories to skip during audit
# Used by standards_audit.py
AUDIT_IGNORE_PATTERNS = [
    "__pycache__",
    "/.archive/",  # Temp archive directories
    "/.backup/",  # Temp backup directories
    "/backups/",  # Actual backup storage (backup/backups/)
    "/artifacts/",  # Build artifacts
    "/integrations/",  # Private integrations (gitignored content)
    ".temp",  # Temp files
    ".old",  # Old files
    "/deprecated/",  # Deprecated code
    "/test/",  # Test directories
]

# =============================================
# DEPRECATED PATTERNS
# =============================================

# Patterns that have been removed from the system
# Used by standards_verify.py to detect leftover usage
# Note: --full was reinstated by DPLAN-0275 (force a full re-scan, bypassing
# the incremental audit cache) — no longer deprecated.
DEPRECATED_PATTERNS = {"--verbose": "removed from audit (v0.4.0)"}

# =============================================
# HELPER FUNCTIONS
# =============================================


def get_template_ignore_patterns() -> List[str]:
    """Return list of template files to skip in architecture baseline check

    Returns:
        Copy of template ignore patterns list

    Example:
        patterns = get_template_ignore_patterns()
        if template_name in patterns:
            # Skip this template file
    """
    json_handler.log_operation("config_accessed", {"config": "template_ignore_patterns"})
    return TEMPLATE_IGNORE_PATTERNS.copy()


def get_audit_ignore_patterns() -> List[str]:
    """Return list of patterns for files/directories to skip during audit

    Returns:
        Copy of audit ignore patterns list

    Example:
        patterns = get_audit_ignore_patterns()
        if any(pattern in file_path for pattern in patterns):
            # Skip this file
    """
    json_handler.log_operation("config_accessed", {"config": "audit_ignore_patterns"})
    return AUDIT_IGNORE_PATTERNS.copy()


def get_deprecated_patterns() -> dict:
    """Return dict of deprecated patterns and their removal reasons

    Returns:
        Copy of deprecated patterns dict

    Example:
        patterns = get_deprecated_patterns()
        for pattern, reason in patterns.items():
            # Check if pattern exists in codebase
    """
    json_handler.log_operation("config_accessed", {"config": "deprecated_patterns"})
    return DEPRECATED_PATTERNS.copy()


# =============================================
# SEEDGO_IGNORE — gitignore-style, per-directory
# =============================================

# Dotfile name — droppable into any directory in a branch, gitignore-style
# patterns (via pathspec), scoped to that directory's subtree exactly like a
# real .gitignore.
IGNORE_FILENAME = ".seedgoignore"

# Global default — applied to every branch with zero per-branch setup.
# Agents' tools/ dirs are deliberate throwaway prototyping space (quick
# scripts for fast answers) — not standards-compliant by design, and that's
# fine and wanted (Patrick ruling).
DEFAULT_IGNORE_PATTERNS: List[str] = [
    "tools/",
]


def _iter_seedgo_ignore_files(branch_root: Path) -> List[Path]:
    """Return every .seedgoignore file under branch_root, shallowest first."""
    return sorted(branch_root.rglob(IGNORE_FILENAME), key=lambda p: len(p.parts))


def load_ignore_entries(branch_root: Path) -> List[Tuple[str, "pathspec.PathSpec"]]:
    """Build the ordered (scope, PathSpec) list for a branch.

    scope "" is the global default and applies branch-wide. Each discovered
    .seedgoignore file adds a scope equal to its own directory (relative to
    branch_root) — its patterns are relative to that directory and only
    match within its subtree, same nesting semantics as a real .gitignore.

    Args:
        branch_root: Absolute path to the branch root.

    Returns:
        Ordered list of (scope, PathSpec) pairs, global default first.
    """
    root = Path(branch_root).resolve()
    entries: List[Tuple[str, "pathspec.PathSpec"]] = [
        ("", pathspec.PathSpec.from_lines("gitignore", DEFAULT_IGNORE_PATTERNS))
    ]

    for ignore_file in _iter_seedgo_ignore_files(root):
        scope = ignore_file.parent.relative_to(root).as_posix()
        if scope == ".":
            scope = ""
        try:
            lines = ignore_file.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.info("[ignore_handler] Cannot read %s: %s", ignore_file, exc)
            continue
        entries.append((scope, pathspec.PathSpec.from_lines("gitignore", lines)))

    json_handler.log_operation("seedgo_ignore_loaded", {"branch_root": str(root), "files": len(entries) - 1})
    return entries


def is_seedgo_ignored(
    file_path: str, branch_root: Path, entries: Optional[List[Tuple[str, "pathspec.PathSpec"]]] = None
) -> bool:
    """Check whether file_path is ignored via .seedgoignore or the global default.

    Args:
        file_path: Absolute path to the candidate file.
        branch_root: Absolute path to the branch root.
        entries: Pre-loaded result of load_ignore_entries(); loaded fresh if omitted.

    Returns:
        True when scans/audits/checklists/checker-style enforcement should skip this path.
    """
    root = Path(branch_root).resolve()
    try:
        rel = Path(file_path).resolve().relative_to(root).as_posix()
    except ValueError as exc:
        logger.info("[ignore_handler] %s not under branch root %s: %s", file_path, root, exc)
        return False

    if entries is None:
        entries = load_ignore_entries(root)

    for scope, spec in entries:
        if scope and rel != scope and not rel.startswith(scope + "/"):
            continue
        sub_rel = rel[len(scope) + 1 :] if scope else rel
        if spec.match_file(sub_rel):
            return True
    return False


# =============================================
# MODULE INITIALIZATION
# =============================================

# No initialization needed - pure configuration
