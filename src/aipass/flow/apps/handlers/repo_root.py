# =================== AIPass ====================
# Name: repo_root.py
# Description: The one guarded answer to "where is my file" and "which repo root is this"
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""Location discovery for flow, defined once and guarded.

WHY THIS FILE EXISTS
--------------------
Measured on the Windows CI gate 2026-08-31 (@memory's finding, relayed by
@devpulse): ``ntpath.realpath`` calls ``os.getcwd()`` UNCONDITIONALLY — on its
first lines, before it even asks whether the path is absolute, where
``posixpath`` only reads the cwd for a relative one — and ``Path.resolve()``
routes through ``os.path.realpath``. So on Windows every module-level
``Path(__file__).resolve()`` is an import-time working-directory dependency: a
process whose cwd has been deleted cannot import the module at all. Guarding
inside that module's functions changes nothing; the import died before any of
them existed.

Flow carried the idiom **29 times**, in every module and nearly every handler,
always spelled ``_PKG_ROOT = Path(__file__).resolve().parents[N]``. Measured
red-first in a subprocess before any cure: 61 of 61 flow modules died on
import, all of them masked at ``handlers/__init__.py`` — the guard crashes
first, so the count only becomes true as cures land (61 dead → 43 after the
guard → 0 after this file).

WHAT THE REPO-ROOT FALLBACK MUST NEVER BE
-----------------------------------------
``_find_repo_root`` existed as **seven** near-identical private copies in this
tree, each ending ``return Path.cwd()``, and **six of them are called at MODULE
level**. That one line carried two defects.

THE LOUD ONE: ``AIPASS_REGISTRY.json`` is gitignored and machine-local, so a
clean checkout or a bare CI runner has no marker anywhere above the file and
takes the fallback on EVERY import. With the working directory deleted,
``Path.cwd()`` raises ``FileNotFoundError`` while merely importing — no call
required.

THE QUIET ONE, which would have outlived the crash: cwd is a GUESS. The
directory a process happened to start in says nothing about where this source
file lives. Four of the seven callers are WRITERS —
``push_central``/``aggregate_central`` build ``.ai_central/PLANS.central.json``,
``close_helpers`` and ``restore_ops`` build the ``.backup/processed_plans``
archive path — and a writer with a guessed root writes into a tree nobody
chose. A ``try``/``except`` would have fixed the traceback and kept the wrong
answer.

The source-derived answer is not a guess: on a registry-less checkout it IS the
checkout, which is the true answer there. And the absence is said out loud,
because a fallback nobody can see is how the next one survives.

A FILENAME IS NOT AN ``exists()`` ON A FOLDING FILESYSTEM
---------------------------------------------------------
Windows and macOS-default filesystems fold case, so
``(parent / "AIPASS_REGISTRY.json").exists()`` returns True for a file actually
named ``aipass_registry.json``. That is the worse half of the round-3 species
(@drone found the glob form; @seedgo published this literal form as its own
blind spot) because there is no glob in the line to warn a reader. Since
``find_repo_root`` runs at module level in six callers, a folded bait file
would be accepted as THE REPO ROOT and every writer built on it would write
into a tree nobody chose — the quiet defect above, arriving through a different
door. ``exists_exactly`` guards it.

IMPORTING THIS MODULE MUST NEVER RAISE
--------------------------------------
Every flow module reaches this file at import time, so anything done here
happens during THEIR import. That is why the audit line on the fallback path is
written defensively: an operations record is worth having, and it is never
worth turning a diagnostic write into the very import crash this module exists
to prevent. The ``json_handler`` import is function-local for the same reason —
``json_handler`` imports THIS module at its own module level, and a module-level
edge back would be a cycle that only appears in whichever import order CI
happened to take.
"""

import os
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

MODULE_NAME = "repo_root"

# The marker that defines a repo root: the core registry file.
CORE_REGISTRY = "AIPASS_REGISTRY.json"


def module_file(file: str) -> Path:
    """A module's own path, absolute, resolved when the filesystem allows.

    ``.resolve()`` is still attempted, because normalising symlinks is why the
    call is there and it succeeds on every healthy machine. The fallback is
    only reached in the world where the alternative is a dead import, and it is
    sound: ``__file__`` has been absolute since Python 3.9, so the return is the
    right file either way — just spelled through the symlink rather than past
    it.

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
        # import takes it, and twenty-nine identical warnings describe one
        # condition. The condition itself is reported once, loudly, by whatever
        # lane actually fails on it.
        logger.debug(f"[{MODULE_NAME}] Cannot resolve {path} ({type(exc).__name__}) — using its absolute spelling")
        return path


# The repo root this FILE sits in, derived from the layout and nothing else.
# ``src/`` is the marker because it is the one directory the package layout
# guarantees. The last-resort value is the filesystem root: defined, never
# raises, and absurd enough to fail loudly downstream instead of quietly
# resolving against somebody's home directory.
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
            f"[{MODULE_NAME}] Cannot enumerate {candidate.parent} ({exc}) — trusting exists() for {candidate.name}"
        )
        return True


def exactly_named(candidates: list[Path], suffix: str) -> list[Path]:
    """Keep only the candidates whose filename ends with *suffix* in EXACT case.

    The post-filter for a ``*_REGISTRY.json`` glob. A glob is a pattern the OS
    interprets; the rule it spells is about NAMES, and on a folding filesystem
    those are not the same set — ``pathlib``'s glob is case-insensitive on
    Windows and default macOS, so ``*_REGISTRY.json`` also serves flow's own
    eight lowercase ``flow_json/*_registry.json`` plan registries.

    The narrowing only ever removes, and it never reorders — callers sort before
    filtering and the order decides which candidate is read first.

    Args:
        candidates: Paths returned by a glob.
        suffix: The exact-case filename ending required.

    Returns:
        The candidates whose ``name`` genuinely ends with *suffix*.
    """
    return [path for path in candidates if path.name.endswith(suffix)]


def _record_fallback(caller: str, marker: str, current: Path) -> None:
    """Log the fallback loudly, and record it without ever raising.

    Called only from the fallback branch, which on six of the callers runs at
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
        from aipass.flow.apps.handlers.json import json_handler

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
            the same ``src/aipass/flow`` package, so it is the same walk
            whichever of them asks.
        marker: Filename that marks a repo root.
        caller: Name used in the log line, so a fallback names the lane that
            took it rather than reporting anonymously.

    Returns:
        The directory holding *marker*, or ``SOURCE_ROOT`` when no *marker*
        exists anywhere above *start*. Never reads the process cwd.
    """
    # module_file, not resolve(): six callers reach this line at IMPORT time,
    # and on Windows resolve() reads the working directory.
    current = Path(start) if start is not None else module_file(__file__).parent
    for parent in [current] + list(current.parents):
        if exists_exactly(parent / marker):
            return parent
    _record_fallback(caller, marker, current)
    return SOURCE_ROOT
