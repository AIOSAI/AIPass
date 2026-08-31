# =================== AIPass ====================
# Name: repo_root.py
# Description: The one answer to "which repo root does this source tree sit in" — never the process cwd
# Version: 1.0.0
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

from pathlib import Path

from aipass.memory.apps.handlers.json import json_handler
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
SOURCE_ROOT = next(
    (parent.parent for parent in Path(__file__).resolve().parents if parent.name == "src"),
    Path(__file__).resolve().parents[-1],
)


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
    current = Path(start) if start is not None else Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / marker).exists():
            return parent
    _record_fallback(caller, marker, current)
    return SOURCE_ROOT
