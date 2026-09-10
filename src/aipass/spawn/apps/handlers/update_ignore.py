# =================== AIPass ====================
# Name: update_ignore.py
# Description: .updateignore parser — the branch owner's decision about what update skips
# Version: 1.0.0
# Created: 2026-09-09
# Modified: 2026-09-09
# =============================================

"""Owner-protected files: the ``.updateignore`` contract at a BRANCH root.

Patrick's ruling (2026-09-09 00:41): *"maybe a .spawnignore just like
.backupignore and .gitignore, same fashion? project owners decide what update
skips."* It shipped under the name ``.updateignore`` because **two doors honour
one file**: ``aipass init update`` at project roots (DPLAN-0335, landed
6ecd5acb) and ``drone @spawn update`` at branch roots (this module). An owner
learns the syntax once.

THIS IS A SECOND PARSER AND THAT IS DELIBERATE. ``aipass`` ships the same
contract in ``apps/handlers/init/scaffold_manifest.py``. Branches never import
each other's handlers — the guard in ``handlers/__init__.py`` exists to say so —
so the choice was to copy the twenty lines or to break the fence. The contract
is small, frozen (no negation in v1), and pinned on both sides; a shared
implementation would cost the boundary that keeps a branch's handlers its own.
If the contract ever grows, it grows in the DPLAN first and both doors follow.

The case this exists for is @vera's todo 25: ``drone @spawn update @vera``
proposed merging template boilerplate into her passport, and she did not apply,
because the tool could not tell her passport from a template. With
``.trinity/passport.json`` in her ``.updateignore``, her passport is hers — and
the rest of the update can proceed instead of being refused wholesale.

SPAWN NEVER CREATES OR MODIFIES THIS FILE. It is the owner's, read-only from
here, and its absence means exactly nothing is protected.
"""

import fnmatch
from pathlib import Path

from aipass.prax import logger

#: The one name, shared with ``aipass init update`` at project roots.
IGNORE_NAME: str = ".updateignore"


def read_ignore(branch_dir) -> list:
    """Patterns from *branch_dir*'s ``.updateignore``, or [] when it is absent.

    Same fashion as ``.gitignore`` and ``.backupignore``: one pattern per line,
    ``#`` comments, blank lines ignored. Negation (``!``) is deliberately not in
    v1 — an ignore file whose meaning depends on line order is a support burden,
    and nobody has asked for it.

    An UNREADABLE file protects nothing and says so in the log rather than
    raising: a branch whose ignore file has bad bytes still gets its update, and
    an owner who cannot see the log still sees every protected path missing from
    the preview's skipped list.

    Args:
        branch_dir: The branch root — the directory holding ``.trinity/``.

    Returns:
        Pattern strings in file order. Empty when the file is absent or unreadable.
    """
    path = Path(branch_dir) / IGNORE_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        logger.info("[update] %s unreadable, protecting nothing: %s", path, exc)
        return []

    patterns = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            patterns.append(stripped)
    return patterns


def is_ignored(rel: str, patterns: list) -> bool:
    """True when *rel* is owner-protected and must not be written, merged or backed up.

    A trailing slash means a directory and everything under it. A pattern with no
    slash also matches a bare filename at any depth, which is what an owner
    writing ``passport.json`` means — requiring the full ``.trinity/`` prefix for
    the common case would make the file a trap.

    Args:
        rel: A posix path relative to the branch root, e.g. ``.trinity/passport.json``.
        patterns: The result of :func:`read_ignore`.

    Returns:
        True if any pattern claims this path.
    """
    name = rel.rsplit("/", 1)[-1]
    for pattern in patterns:
        if pattern.endswith("/"):
            prefix = pattern.rstrip("/")
            if rel == prefix or rel.startswith(prefix + "/") or fnmatch.fnmatch(rel, prefix + "/*"):
                return True
            continue
        if fnmatch.fnmatch(rel, pattern):
            return True
        if "/" not in pattern and fnmatch.fnmatch(name, pattern):
            return True
    return False
