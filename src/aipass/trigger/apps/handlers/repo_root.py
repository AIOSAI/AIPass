# =================== AIPass ====================
# Name: repo_root.py
# Description: One guarded answer to "where is my file" and "where is the repo root" — never the process cwd
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""Module-file and repo-root resolution, defined once for trigger.

WHY THIS FILE EXISTS
--------------------
Two defects, one line apart, found the same week.

THE CRASH. ``ntpath.realpath`` reads ``os.getcwd()`` UNCONDITIONALLY — not only
for relative paths, the way ``posixpath`` does — and ``Path.resolve()`` routes
through it. So on Windows every ``Path(__file__).resolve()`` REACHED AT IMPORT
is an import-time working-directory dependency: a process whose cwd was deleted
cannot import the module at all. Measured on the Windows CI gate 2026-08-31
(@memory's finding); @prax's own import chain died inside trigger's handler
guard and took every prax consumer with it.

THE QUIET ONE, which would have outlived the crash. Four byte-identical copies
of ``_find_repo_root`` in this tree ended in ``return Path.cwd()``. The
directory a process happened to start in says nothing about where this source
file lives, so on a registry-less tree (``AIPASS_REGISTRY.json`` is gitignored
and machine-local, so every clean clone and CI runner is one) each caller
resolved against whatever the shell was pointing at — silently, and differently
per caller. A ``try``/``except`` would have fixed the traceback and kept the
wrong answer.

FOUR COPIES IS THE DEFECT, NOT FOUR BUGS
----------------------------------------
The copies lived in ``escalation.py``, ``events/error_detected.py``,
``events/runaway_handler.py`` and ``events/plan_file.py``, all four evaluated at
MODULE level.  (The fourth was retired outright the same day, on separate
evidence — see ``events/.archive/plan_file.py``.) A cure landing on some of N identical paths is the species this
branch spent the week naming in other people's trees; one implementation is the
only version of it that cannot recur.

A FILENAME IS NOT AN ``exists()``
---------------------------------
Windows and macOS-default filesystems fold case, so
``(parent / "AIPASS_REGISTRY.json").exists()`` returns True for a file actually
named ``aipass_registry.json``. That is worse than the glob form swept fleet-wide
in ebb8075d because there is no pattern in the line to warn a reader. The walk
below decides which installation this branch belongs to and several callers
build WRITE paths from the answer, so a folded bait file would be accepted as
THE repo root. ``exists_exactly`` is @memory's cure, adopted here rather than
re-invented.

WHERE THE TWO HALVES LIVE, AND WHY
----------------------------------
``module_file`` — the guarded ``__file__`` resolve — lives in ``apps/config.py``,
not here. config.py is where this branch's package paths are defined, its own
``TRIGGER_ROOT`` is the first caller, and config.py must not import a handler.
This module is the WALK, which is handler-layer work; it imports the resolve
from config like every other handler does.

NO PRAX. Every caller here sits on the event path the log watchers read, so a
line through prax would be detected and fired straight back at this branch —
and config.py, which this module imports, cannot import the prax logger at all
(circular). The fallback is reported through the ``.jsonl`` trail sidecar the
callers already use; the watchers read only ``*.log``. That write is itself
guarded, because four callers reach it at IMPORT time and a diagnostic line must
never become the import crash this module exists to prevent.
"""

import os
from pathlib import Path

from aipass.trigger.apps.config import TRIGGER_ROOT, module_file, trail_logger

MODULE_NAME = "repo_root"

# Infrastructure — redirect to temp dir during tests, the same door
# json_handler already uses. Measured, not assumed: the first version of this
# module wrote 38 lines into the live tree while its own pins ran.
_test_log_dir = os.environ.get("AIPASS_TEST_LOG_DIR")
if _test_log_dir:
    _LOG_FILE = Path(_test_log_dir) / "trigger" / "repo_root.jsonl"
else:
    _LOG_FILE = TRIGGER_ROOT / "logs" / "repo_root.jsonl"

logger = trail_logger(_LOG_FILE)

# Observable state for the one guard that has nothing left to call. See
# _record_fallback: it is the arm that fires when the LOGGER itself failed.
RECORD_FAILURES: list[str] = []

# The marker that defines a repo root: the core registry file.
CORE_REGISTRY = "AIPASS_REGISTRY.json"


_THIS_FILE = module_file(__file__)

# The repo root implied by THIS FILE's location, derived from the package layout
# and nothing else. ``src/`` is the marker because it is the one directory the
# layout guarantees. The last-resort value is the filesystem root: defined,
# never raises, and absurd enough to fail loudly downstream instead of quietly
# resolving against somebody's home directory.
SOURCE_ROOT = next(
    (parent.parent for parent in _THIS_FILE.parents if parent.name == "src"),
    _THIS_FILE.parents[-1],
)


def exists_exactly(path: Path) -> bool:
    """True when *path* exists AND is spelled on disk exactly as asked.

    ``Path.exists()`` asks the filesystem, and Windows and macOS-default
    filesystems answer about a case-folded name. The only reliable way to learn
    the real spelling is to LIST the parent — ``resolve()`` would work on Windows
    but follows symlinks, so a legitimately symlinked registry would come back
    under its target's name and be refused.

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
    except OSError:
        return True


def _record_fallback(caller: str, marker: str, current: Path) -> None:
    """Record the fallback without ever raising.

    Runs at module import time on all four callers, so every failure mode here
    is swallowed: an operations record is worth having, and it is never worth
    turning a diagnostic write into the import crash this module prevents.

    Args:
        caller: Lane that took the fallback.
        marker: Filename that was searched for.
        current: Directory the walk started from.
    """
    try:
        logger.warning(
            f"[{caller}] No {marker} above {current} — "
            f"resolving to the source tree at {SOURCE_ROOT}, never the process directory"
        )
        # The operations record, in @memory's ratified shape. Function-local
        # because json_handler imports config and config is imported above —
        # a module-level edge would close the loop, and it would only show up
        # in whichever import order CI happened to take.
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation(
            "repo_root_fallback",
            {"caller": caller, "marker": marker, "searched_from": str(current), "resolved": str(SOURCE_ROOT)},
            module_name=MODULE_NAME,
        )
    except Exception as exc:  # noqa: BLE001 - an audit line must never take an import down
        # The record of the failed record. Not a swallow: the reason is kept
        # where a reader can find it, because the alternative — raising from a
        # diagnostic line reached at import — is the crash this module prevents.
        RECORD_FAILURES.append(f"{caller}/{marker}: {type(exc).__name__}: {exc}")


def find_repo_root(start: Path | None = None, *, marker: str = CORE_REGISTRY, caller: str = MODULE_NAME) -> Path:
    """Walk up from *start* to the directory holding *marker*.

    Falls back to the root implied by THIS FILE's location — never to the process
    working directory. See the module docstring for the two defects that fallback
    carried.

    Args:
        start: Directory to walk up from. Defaults to this file's directory,
            which is what every caller in this tree wants: they all live under
            the same ``src/aipass/trigger`` package, so it is the same walk
            whichever of them asks.
        marker: Filename that marks a repo root.
        caller: Name used in the log line, so a fallback names the lane that took
            it rather than reporting anonymously.

    Returns:
        The directory holding *marker*, or ``SOURCE_ROOT`` when no *marker*
        exists anywhere above *start*. Never reads the process cwd.
    """
    # module_file, not resolve(): every caller reaches this line at IMPORT time,
    # and on Windows resolve() reads the working directory. The discriminator
    # that matters is REACHED AT IMPORT, not written at module scope.
    current = Path(start) if start is not None else _THIS_FILE.parent
    for parent in [current] + list(current.parents):
        if exists_exactly(parent / marker):
            return parent
    _record_fallback(caller, marker, current)
    return SOURCE_ROOT
