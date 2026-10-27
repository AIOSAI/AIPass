# =================== AIPass ====================
# Name: update_ignore.py
# Description: .updateignore parser — the branch owner's decision about what update skips
# Version: 1.2.0
# Created: 2026-09-09
# Modified: 2026-10-26
# =============================================

"""Owner-protected files: the ``.updateignore`` contract at a branch root and at its project root.

Deliberate twin of aipass's ``scaffold_manifest.py`` parser (no cross-branch imports): change both."""

import fnmatch
from pathlib import Path

from aipass.prax import logger

IGNORE_NAME: str = ".updateignore"


class UpdateIgnoreUnreadable(Exception):
    """A branch's ``.updateignore`` is there but cannot be read (not the same as absent)."""


def read_ignore(branch_dir) -> list:
    """Patterns from *branch_dir*'s ``.updateignore``, or [] when it is absent.

    Raises UpdateIgnoreUnreadable when unreadable, so update refuses before any write."""
    path = Path(branch_dir) / IGNORE_NAME
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("[update] %s is there but cannot be read: %s", path, exc)
        raise UpdateIgnoreUnreadable(f"{path} is there but cannot be read ({exc}); fix or remove it") from exc

    patterns = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            patterns.append(stripped)
    return patterns


def is_ignored(rel: str, patterns: list) -> bool:
    """True when *rel* is owner-protected and must not be written, merged or backed up.

    A slashless pattern also matches a bare filename at any depth."""
    name = rel.rsplit("/", 1)[-1]
    for pattern in patterns:
        if pattern.endswith("/"):
            prefix = pattern.rstrip("/")
            # fnmatch(rel, prefix) is the bare directory row of a wildcard prefix, which == never matches.
            literal = rel == prefix or rel.startswith(prefix + "/")
            if literal or fnmatch.fnmatch(rel, prefix) or fnmatch.fnmatch(rel, prefix + "/*"):
                return True
            continue
        if fnmatch.fnmatch(rel, pattern):
            return True
        if "/" not in pattern and fnmatch.fnmatch(name, pattern):
            return True
    return False
