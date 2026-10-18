# =================== AIPass ====================
# Name: ignore_handler.py
# Description: Ignore Pattern Configuration Handler
# Version: 1.1.0
# Created: 2026-03-05
# Modified: 2026-10-17
# =============================================

"""Ignore Pattern Configuration Handler"""

from pathlib import Path
from typing import List, Optional, Tuple

import pathspec

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

# Spawn-template files a branch need not carry (architecture_check's baseline).
TEMPLATE_IGNORE_PATTERNS = [
    ".gitkeep",  # Git placeholder files - not actual requirements
    "notepad.md",  # Optional scratch file
    ".gitignore",  # Optional - branches inherit from root
    "test_scaffold.py",  # Scaffold example — branches have their own tests
]

# Gitignore-style, matched against the BRANCH-RELATIVE path ("/" anchors to the branch root);
# ignored_tracked_source() convicts any entry that removes a file git tracks.
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

# standards_verify.py flags leftover usage; --full is live (forces a full re-scan), not deprecated.
DEPRECATED_PATTERNS = {"--verbose": "removed from audit (v0.4.0)"}


def get_template_ignore_patterns() -> List[str]:
    """Return list of template files to skip in architecture baseline check"""
    json_handler.log_operation("config_accessed", {"config": "template_ignore_patterns"})
    return TEMPLATE_IGNORE_PATTERNS.copy()


def get_audit_ignore_patterns() -> List[str]:
    """Return list of patterns for files/directories to skip during audit"""
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

    The deepest .gitignore with an opinion wins and negations are honoured; no subprocess, agents have no git.
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

    Outside a git repository every removed file is returned unverified, never acquitted.
    """
    repo_root = find_repo_root(branch_path)
    if repo_root is None:
        return list(ignored_rel_paths)
    return [rel for rel in ignored_rel_paths if not gitignored(branch_path / rel, repo_root)]


def get_deprecated_patterns() -> dict:
    """Return dict of deprecated patterns and their removal reasons"""
    json_handler.log_operation("config_accessed", {"config": "deprecated_patterns"})
    return DEPRECATED_PATTERNS.copy()


# Scoped to its own directory's subtree, exactly like a real .gitignore.
IGNORE_FILENAME = ".seedgoignore"

# Applied to every branch: agents' tools/ dirs are throwaway prototyping space, not held to standards.
DEFAULT_IGNORE_PATTERNS: List[str] = [
    "tools/",
]


def _iter_seedgo_ignore_files(branch_root: Path) -> List[Path]:
    """Return every .seedgoignore file under branch_root, shallowest first."""
    return sorted(branch_root.rglob(IGNORE_FILENAME), key=lambda p: len(p.parts))


def load_ignore_entries(branch_root: Path) -> List[Tuple[str, "pathspec.PathSpec"]]:
    """Build the ordered (scope, PathSpec) list for a branch, global default (scope "") first."""
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
    """Check whether file_path is ignored via .seedgoignore or the global default."""
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
