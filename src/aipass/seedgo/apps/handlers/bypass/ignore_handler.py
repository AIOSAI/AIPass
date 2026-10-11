# =================== AIPass ====================
# Name: ignore_handler.py
# Description: Ignore Pattern Configuration Handler
# Version: 1.1.0
# Created: 2026-03-05
# Modified: 2026-09-25
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

# What the audit removes from a branch's corpus, as gitignore-style patterns
# matched against the BRANCH-RELATIVE path (a leading "/" anchors to the branch
# root; a bare "name/" matches that directory anywhere). Until 2026-09-25 these
# were substrings of the whole lowercased path, and "/integrations/" and
# "/artifacts/" silently removed 5 tracked source files (1,399 lines) in api and
# commons (survey row #14, owner "Ok go."). Every entry carries its reason;
# ignored_tracked_source() convicts any entry that removes a file git tracks.
# Dropped that day: ".temp" and ".old" (the corpus is *.py, so they could only
# ever hit a mid-name dot in real source) and "/test/" (tests live in tests/,
# which joined the corpus 2026-09-21; a test/ directory under apps/ is product).
AUDIT_IGNORE_RULES: Tuple[Tuple[str, str], ...] = (
    ("__pycache__/", "bytecode caches: never source"),
    (".archive/", "retired copies, same as applicability.RETIRED_DIRS"),
    (".backup/", "rollover and snapshot storage, never source"),
    ("deprecated/", "retired code, same as applicability.RETIRED_DIRS"),
    ("/backups/", "@backup's storage at the branch root, gitignored (.gitignore backups/)"),
    ("/artifacts/", "a branch's published artifacts/ at its root, gitignored (.gitignore artifacts/)"),
    ("/apps/integrations/", "the private driver layer, gitignored (.gitignore src/aipass/*/apps/integrations/**)"),
)
AUDIT_IGNORE_PATTERNS = [pattern for pattern, _reason in AUDIT_IGNORE_RULES]

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


def audit_ignore_match(rel_path: str) -> Optional[str]:
    """The AUDIT_IGNORE_PATTERNS entry that removes a branch-relative path from the audit, or None."""
    posix = Path(rel_path).as_posix()
    return next(
        (p for p in AUDIT_IGNORE_PATTERNS if pathspec.GitIgnoreSpec.from_lines([p]).match_file(posix)),
        None,
    )


def find_repo_root(path: Path) -> Optional[Path]:
    """The nearest ancestor holding a .git entry: the root git reads .gitignore files from."""
    resolved = path.resolve()
    return next((parent for parent in (resolved, *resolved.parents) if (parent / ".git").exists()), None)


def _gitignore_spec(gitignore: Path) -> pathspec.GitIgnoreSpec:
    """One .gitignore file compiled the way git reads it; an unreadable one raises, never reads as empty."""
    return pathspec.GitIgnoreSpec.from_lines(gitignore.read_text(encoding="utf-8").splitlines())


def gitignored(file_path: Path, repo_root: Path) -> bool:
    """Whether the repository's .gitignore files ignore file_path, read without git.

    Every .gitignore from the repository root down to the file's directory is
    consulted in order and the deepest one that has an opinion wins, the way git
    layers them. Negations (``!path``) are honoured, so commons' re-included
    ``apps/handlers/artifacts/*.py`` reads as tracked. No subprocess: agents have
    no git.
    """
    target = file_path.resolve()
    root = repo_root.resolve()
    rel = target.relative_to(root)
    verdict = False
    directory = root
    for part in ("", *rel.parts[:-1]):
        directory = directory / part if part else directory
        gitignore = directory / ".gitignore"
        if gitignore.is_file():
            include = _gitignore_spec(gitignore).check_file(target.relative_to(directory).as_posix()).include
            if include is not None:
                verdict = include
    return verdict


def ignored_tracked_source(branch_path: Path, ignored_rel_paths: List[str]) -> List[str]:
    """The files the audit ignore list removed that git does NOT ignore: tracked source dropped by a pattern.

    Outside a git repository nothing is tracked, so the answer is every
    removed file unverified -- returned as is, never as an acquittal.
    """
    repo_root = find_repo_root(branch_path)
    if repo_root is None:
        return list(ignored_rel_paths)
    return [rel for rel in ignored_rel_paths if not gitignored(branch_path / rel, repo_root)]


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
# fine and wanted (the owner ruling).
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
