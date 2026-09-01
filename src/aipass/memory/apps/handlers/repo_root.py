# =================== AIPass ====================
# Name: repo_root.py
# Description: The one answer to "which repo root is this" — never the process cwd, never a folded filename
# Version: 1.2.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""Repo root discovery, defined once.

WHY THIS FILE EXISTS
--------------------
On 2026-08-31 @drone reported that ``registry_scope`` crashed on import in a
process whose working directory had been deleted: a module-level walk-up whose
last resort was ``Path.cwd()``.  It was cured within the hour.  The SAME HOUR,
CI went red again on ``detector.py`` — the identical function, one file over,
found by the very subprocess pin written for the first fix.

That second red is the real defect.  ``_find_repo_root`` existed as TEN
byte-identical copies across this tree, so the cure landed on one of them and
nine kept the disease.  A fix that lands on some of N identical paths is this
week's lesson arriving twice in one night, and the only version of it that
cannot recur is one implementation.  This is that implementation.

WHAT THE FALLBACK MUST NEVER BE
-------------------------------
``Path.cwd()`` carried two defects in one line.

THE LOUD ONE: the walk is evaluated at MODULE level in four of the callers, and
a clean checkout has no registry (``AIPASS_REGISTRY.json`` is gitignored and
machine-local), so a bare CI runner takes the fallback on every import.  When
the process's working directory has been deleted, ``Path.cwd()`` raises
``FileNotFoundError`` while merely IMPORTING the module — no call required.

THE QUIET ONE, which would have outlived the crash: cwd is a GUESS.  The
directory a process happened to start in says nothing about where this source
file lives, so on a registry-less tree every lane resolves against whatever the
caller's shell was pointing at — silently, and DIFFERENTLY PER CALLER.  Several
of the callers here are WRITERS.  A writer with a guessed root writes into a
tree nobody chose.  A ``try``/``except`` would have fixed the traceback and kept
the wrong answer.

The source-derived answer is not a guess: on a registry-less checkout it IS the
checkout, which is the true answer there.  And the absence is said out loud,
because a fallback nobody can see is how the next one survives.

A FILENAME IS NOT A GLOB AND NOT AN ``exists()`` (1.1.0, 2026-08-31)
-------------------------------------------------------------------
Windows and macOS-default filesystems fold case.  ``*_REGISTRY.json`` matches
``flow_json_registry.json`` there, and ``(parent / "AIPASS_REGISTRY.json").exists()``
returns True for a file actually named ``aipass_registry.json``.  @drone found
the first form on the Windows CI leg; @seedgo's fleet discriminator published
the second as its own blind spot, and it is the worse of the two because there
is no glob in the line to warn a reader.

Both belong here rather than at each walk.  ``find_repo_root`` IS a cased
literal check, run at module level in four callers, so a folded bait file would
be accepted as THE REPO ROOT and every writer built on it would write into a
tree nobody chose — the quiet defect this module exists to prevent, arriving
through a different door.

IMPORTING THIS MODULE MUST NEVER RAISE
--------------------------------------
Four callers resolve their root at module level, so anything this file does at
import time happens during THEIR import.  That is why the audit line on the
fallback path is written defensively: an operations record is worth having, and
it is never worth turning a diagnostic write into the very import crash this
module exists to prevent.

``handlers/json/__init__`` imports ``config_loader``, so ``config_loader``
reaches this module through a function-local import.  A module-level edge back
would be a cycle, and the cycle would only appear in whichever import order CI
happened to take.
"""

import os
from pathlib import Path

from aipass.prax.apps.modules.logger import get_system_logger

logger = get_system_logger()

MODULE_NAME = "repo_root"

# The marker that defines a repo root: the core registry file.
CORE_REGISTRY = "AIPASS_REGISTRY.json"


# The repo root this FILE sits in, derived from the layout and nothing else.
# ``src/`` is the marker because it is the one directory the package layout
# guarantees.  The last-resort value is the filesystem root: defined, never
# raises, and absurd enough to fail loudly downstream instead of quietly
# resolving against somebody's home directory.
def module_file(file: str) -> Path:
    """A module's own path, absolute, resolved when the filesystem allows.

    ``Path(__file__).resolve()`` at module level is a cwd read on Windows.
    ``ntpath.realpath`` computes ``os.getcwd()`` UNCONDITIONALLY — not only for
    a relative path, the way POSIX does — so in a process whose working
    directory is gone, importing the module raises ``FileNotFoundError`` from a
    line that only wanted to know where its own file is. Found on the Windows CI
    leg 2026-08-31, one frame at a time: the guard in ``handlers/__init__``
    crashed first, and behind it sat thirty-two more module-level copies of the
    same idiom.

    ``.resolve()`` is still attempted, because normalising symlinks is why the
    call is there and it succeeds on every healthy machine. The fallback is only
    reached in the world where the alternative is a dead import, and it is
    sound: ``__file__`` has been absolute since Python 3.9, so what is returned
    is the right file either way — just spelled through the symlink rather than
    past it.

    Args:
        file: A module's ``__file__``.

    Returns:
        The module's path, resolved if the filesystem could be asked.
    """
    path = Path(file)
    try:
        return path.resolve()
    except OSError as exc:
        # debug, not warning: in the world that reaches this line EVERY module
        # import takes it, and thirty-two identical warnings describe one
        # condition. The condition itself is reported once, loudly, by whatever
        # lane actually fails on it.
        logger.debug(f"[repo_root] Cannot resolve {path} ({type(exc).__name__}) — using its absolute spelling")
        return path


_THIS_FILE = module_file(__file__)
SOURCE_ROOT = next(
    (parent.parent for parent in _THIS_FILE.parents if parent.name == "src"),
    _THIS_FILE.parents[-1],
)


def exists_exactly(path: Path) -> bool:
    """True when *path* exists AND is spelled on disk exactly as asked.

    ``Path.exists()`` asks the filesystem, and Windows and macOS-default
    filesystems answer about a case-folded name. So a directory holding
    ``aipass_registry.json`` reports True for ``AIPASS_REGISTRY.json``, and a
    caller that meant the one blessed filename silently gets a different file.

    The only reliable way to learn the real spelling is to LIST the parent —
    ``resolve()`` would work on Windows but follows symlinks, so a legitimately
    symlinked registry would come back under its target's name and be refused.
    The listing is cheap where it matters: it only runs when ``exists()``
    already said yes, which in a walk is at most once.

    An unlistable parent returns True rather than False. This is a READ anchor,
    and today's behaviour is ``exists()`` alone; refusing a file that is
    demonstrably there because its directory could not be enumerated would be a
    new failure invented by the guard.

    Args:
        path: The exact filename being asserted.

    Returns:
        True when a directory entry with that exact name exists.
    """
    candidate = Path(path)
    if not candidate.exists():
        return False
    try:
        with os.scandir(candidate.parent) as entries:
            return any(entry.name == candidate.name for entry in entries)
    except OSError as exc:
        logger.debug(
            f"[repo_root] Cannot enumerate {candidate.parent} ({exc}) — trusting exists() for {candidate.name}"
        )
        return True


def exactly_named(candidates: list[Path], suffix: str) -> list[Path]:
    """Keep only the candidates whose filename ends with *suffix* in EXACT case.

    The post-filter for every ``*_REGISTRY.json`` glob in this tree. A glob is
    a pattern the OS interprets; the rule it spells is about names, and on a
    folding filesystem those are not the same set.

    The narrowing only ever removes, and it never reorders — callers sort
    before filtering and the order is the answer in at least one of them.

    Args:
        candidates: Paths returned by a glob.
        suffix: The exact-case filename ending required.

    Returns:
        The candidates whose ``name`` genuinely ends with *suffix*.
    """
    return [path for path in candidates if path.name.endswith(suffix)]


def _record_fallback(caller: str, marker: str, current: Path) -> None:
    """Log the fallback loudly, and record it without ever raising.

    Called only from the fallback branch, which on four of the callers runs at
    module import time. ``log_operation`` writes a file, and a write that fails
    in a bare world must not become the import crash this module prevents.

    Args:
        caller: Lane that took the fallback.
        marker: Filename that was searched for.
        current: Directory the walk started from.
    """
    logger.warning(
        f"[{caller}] No {marker} above {current} — "
        f"resolving to the source tree at {SOURCE_ROOT}, never the process directory"
    )
    try:
        from aipass.memory.apps.handlers.json import json_handler

        json_handler.log_operation(
            "repo_root_fallback",
            {"caller": caller, "marker": marker, "searched_from": str(current), "resolved": str(SOURCE_ROOT)},
            module_name=MODULE_NAME,
        )
    except Exception as exc:  # noqa: BLE001 - an audit line must never take an import down
        logger.debug(f"[{caller}] repo_root fallback not recorded: {type(exc).__name__}: {exc}")


def find_repo_root(start: Path | None = None, *, marker: str = CORE_REGISTRY, caller: str = MODULE_NAME) -> Path:
    """Walk up from *start* to the directory holding *marker*.

    Falls back to the root implied by THIS FILE's location — never to the
    process working directory. See the module docstring for the two defects
    that fallback carried.

    Args:
        start: Directory to walk up from. Defaults to this file's directory,
            which is what every caller in this tree wants: they all live under
            the same ``src/aipass/memory`` package, so it is the same walk
            whichever of them asks.
        marker: Filename that marks a repo root.
        caller: Name used in the log line, so a fallback names the lane that
            took it rather than reporting anonymously.

    Returns:
        The directory holding *marker*, or ``SOURCE_ROOT`` when no *marker*
        exists anywhere above *start*. Never reads the process cwd.
    """
    # module_file, not resolve(): four callers reach this line at IMPORT time,
    # and on Windows resolve() reads the working directory. The first sweep of
    # this species keyed on "module level" and skipped this line for sitting
    # inside a function — the discriminator that matters is REACHED AT IMPORT,
    # not written at module scope, and this was the last crash standing.
    current = Path(start) if start is not None else module_file(__file__).parent
    for parent in [current] + list(current.parents):
        if exists_exactly(parent / marker):
            return parent
    _record_fallback(caller, marker, current)
    return SOURCE_ROOT
