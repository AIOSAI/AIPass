# =================== AIPass ====================
# Name: protected_paths.py
# Version: 2.1.0
# Description: The files that switch the gates themselves — written by the admin seat alone (git_gate)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-09-30
# Modified: 2026-10-01
# =============================================

"""Which files decide whether the gates run, and so must never be an agent's to write (DPLAN-0356 item 1).

Measured before this module: any branch could write ``src/aipass/<self>/.aipass/hooks.json``
(its own directory, so ownership allowed it) and its sessions ran with no gates;
``~/.aipass/trusted_projects.json`` was writable by every branch and named by no
gate. The loader now ignores a branch-level config, and these files are the
admin seat's to write, through the tool lane and the Bash lane alike
(handlers/security/git_gate.py consumes this):

  - any ``.aipass/hooks.json`` under AIPASS_HOME, the root one included;
  - ``~/.aipass/trusted_projects.json``;
  - any ``.claude/settings*.json`` (the provider wiring), ``.claude/hooks/`` and ``.git/hooks/``;
  - this branch's promoted copies (``.live-*``): only ``drone @hooks promote`` writes them;
  - since 2.1.0 (phase 4, P2): everything under AIPASS_HOME's ``.git/``, and every
    sealed ``*_REGISTRY.json`` under AIPASS_HOME (registry_gate's set).

Since 2.1.0 the Bash lane is default-deny for this set: off the admin seat a
command naming one as an operand is refused unless the program only reads
(modules/shell_programs.READ_ONLY_PROGRAMS).

An external project's own ``.aipass/hooks.json`` is not listed: trust decides
whether it runs, and changing it breaks its trust hash.

Since 2.0.0 (DPLAN-0356 phase 3, the red team's R1) a file is matched by WHAT
it is as well as by its name. A hard link is a second name for the same file:
``ln ~/.aipass/trusted_projects.json mine.json`` and a write to ``mine.json``
lands in the trust registry. So an existing file with more than one link is
compared by (device, inode) against every protected file on disk; one name of
a protected file is protected under every name. :func:`protected_within` names a
directory that holds a protected file, for the lanes that delete or move a
directory whole (R2).
"""

import os
import re
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.handlers.config.loader import aipass_home
from aipass.hooks.apps.handlers.module_root import module_file
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

_HOOKS_BRANCH = module_file(__file__).parent.parent.parent

# Matched on the path spelled with "/" and case-insensitively: Windows and default
# macOS filesystems open .Claude\Settings.json as the same file.
_ANYWHERE = (
    (re.compile(r"/\.claude/settings[^/]*\.json$", re.IGNORECASE), "the provider hook wiring (.claude/settings*.json)"),
    (re.compile(r"/\.claude/hooks/", re.IGNORECASE), "the provider hook scripts (.claude/hooks/)"),
    (re.compile(r"/\.git/hooks/", re.IGNORECASE), "git's own hooks (.git/hooks/)"),
)
_CONFIG_TAIL = re.compile(r"/\.aipass/hooks\.json$", re.IGNORECASE)
# registry_gate's sealed set: any *_REGISTRY.json (phase 4, P2 — under AIPASS_HOME).
_REGISTRY_TAIL = re.compile(r"/\w+_REGISTRY\.json$", re.IGNORECASE)

TRUST = "the trust registry (~/.aipass/trusted_projects.json)"
CONFIG = "the AIPass hook config (.aipass/hooks.json)"
LIVE = "the promoted hook code (.live-*; drone @hooks promote writes it)"
GIT_DATA = "the repository's git data (.git/; drone @git is the interface)"
REGISTRY = "a sealed registry (*_REGISTRY.json; its owner's drone verbs write it)"

# Inside a directory, what marks it as holding a protected file (protected_within).
_HELD_INSIDE = (
    (".claude", "the provider hook wiring and scripts (.claude/)"),
    (".git/hooks", "git's own hooks (.git/hooks/)"),
)


def _spelled(path: Path) -> str:
    try:
        path = path.resolve()
    except (OSError, RuntimeError) as exc:  # resolve reads the cwd on Windows; the spelling still names the file
        logger.info("[HOOKS] protected_paths: cannot resolve %s: %s", path, exc)
    return str(path).replace("\\", "/")


def _under(spelled: str, root: Path) -> bool:
    base = _spelled(root).rstrip("/").casefold()
    return spelled.casefold() == base or spelled.casefold().startswith(base + "/")


def _absolute(path: str | Path, cwd: str) -> Path:
    target = Path(path).expanduser()
    if not target.is_absolute() and cwd:
        target = Path(cwd) / target
    return target


def _by_name(spelled: str) -> str | None:
    for pattern, what in _ANYWHERE:
        if pattern.search(spelled):
            return what
    if spelled.casefold() == _spelled(Path.home() / ".aipass" / "trusted_projects.json").casefold():
        return TRUST
    home = aipass_home()
    if home is not None and _CONFIG_TAIL.search(spelled) and _under(spelled, home):
        return CONFIG
    if home is not None and _under(spelled, home / ".git"):
        return GIT_DATA
    if home is not None and _REGISTRY_TAIL.search(spelled) and _under(spelled, home):
        return REGISTRY
    if _under(spelled, _HOOKS_BRANCH) and spelled[len(_spelled(_HOOKS_BRANCH)) :].lstrip("/").startswith(".live-"):
        return LIVE
    return None


def _files(root: Path, pattern: str) -> list[Path]:
    try:
        return [found for found in root.glob(pattern) if found.is_file()]
    except OSError as exc:  # an unreadable tree names no anchor in it; the name lane still holds
        logger.info("[HOOKS] protected_paths: cannot list %s/%s: %s", root, pattern, exc)
        return []


def anchors() -> list[Path]:
    """Every protected file on disk now: the files a second name could reach.

    Returns:
        The existing protected files, each spelled once.
    """
    user = Path.home()
    found = [user / ".aipass" / "trusted_projects.json", *_files(user / ".claude", "settings*.json")]
    found.extend(_files(user / ".claude" / "hooks", "**/*"))
    home = aipass_home()
    if home is not None:
        for pattern in (
            ".aipass/hooks.json",
            "src/aipass/*/.aipass/hooks.json",
            "projects/*/.aipass/hooks.json",
            ".claude/settings*.json",
            ".claude/hooks/**/*",
            ".git/*",
            "*_REGISTRY.json",
            "src/aipass/*/*_REGISTRY.json",
            "projects/*/*_REGISTRY.json",
            ".git/hooks/**/*",
        ):
            found.extend(_files(home, pattern))
    found.extend(_files(_HOOKS_BRANCH, ".live-*/**/*"))
    return [path for path in dict.fromkeys(found) if path.is_file()]


def _by_identity(target: Path) -> str | None:
    """What *target* is when it is another name for a protected file (R1a)."""
    info = None
    try:
        info = os.stat(target)
    except OSError as exc:  # a file that does not exist yet has one name: the one being written
        logger.debug("[HOOKS] protected_paths: no file at %s: %s", target, exc)
    if info is None or info.st_nlink < 2:
        return None
    mine = (info.st_dev, info.st_ino)
    for anchor in anchors():
        try:
            theirs = os.stat(anchor)
        except OSError as exc:  # gone since it was listed: no second name to share
            logger.debug("[HOOKS] protected_paths: anchor gone %s: %s", anchor, exc)
            continue
        if (theirs.st_dev, theirs.st_ino) == mine:
            return _by_name(_spelled(anchor)) or TRUST
    return None


def protected(path: str | Path, cwd: str = "") -> str | None:
    """What *path* governs when it is a protected file, by name or by file identity, else None.

    Args:
        path: The file a write lands on; a relative path is read from *cwd*.
        cwd: The session directory.

    Returns:
        A short phrase naming what the file switches, or None.
    """
    target = _absolute(path, cwd)
    return _by_name(_spelled(target)) or _by_identity(target)


def protected_within(path: str | Path, cwd: str = "") -> str | None:
    """What a protected file inside directory *path* governs, else None (R2: a directory deleted or moved whole).

    Args:
        path: A directory a delete or move takes whole; a relative path is read from *cwd*.
        cwd: The session directory.

    Returns:
        A short phrase naming what the held file switches, or None.
    """
    target = _absolute(path, cwd)
    spelled = _spelled(target)
    for anchor in anchors():
        anchor_spelled = _spelled(anchor)
        if anchor_spelled.casefold().startswith(spelled.rstrip("/").casefold() + "/"):
            return _by_name(anchor_spelled) or TRUST
    for inside, what in _HELD_INSIDE:
        if (target / inside).is_dir():
            return what
    return None


def print_introspection() -> None:
    """Print module structure for drone routing: the protected files found now, never a live verdict."""
    CONSOLE.print("[bold cyan]protected_paths[/bold cyan] — files that switch the gates, the admin seat's to write")
    CONSOLE.print("[dim]Consumed by git_gate (tool lane and Bash lane), matched by name and by inode.[/dim]")
    found = anchors()
    for anchor in found[:20]:
        CONSOLE.print(f"  {anchor}")
    if len(found) > 20:
        CONSOLE.print(f"  [dim]… and {len(found) - 20} more[/dim]")
