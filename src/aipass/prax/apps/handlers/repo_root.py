# =================== AIPass ====================
# Name: repo_root.py
# Description: Repo-Root Resolution That Never Reads The Process CWD
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""
Repo-Root Resolution Handler

One answer to "where is the repo root", derived from the FILE and never from the
process working directory.

WHY THIS EXISTS. Eight copies of the same ``_find_repo_root()`` lived in prax,
each walking up from ``__file__`` for ``AIPASS_REGISTRY.json`` and each ending
``return Path.cwd()``. @memory reported the consequence with a full traceback on
2026-08-31, and it is fleet-wide rather than a prax inconvenience: nearly every
handler in AIPass does ``logger = get_system_logger()`` at MODULE level, so that
walk runs while modules are being IMPORTED. Two failure modes followed:

1. THE CRASH. ``Path.cwd()`` raises FileNotFoundError when the process working
   directory has been deleted — while a module is merely being imported, not
   called. Reproduced against a registry-less copy of this tree.

2. THE QUIET ONE, which outlives the crash. ``AIPASS_REGISTRY.json`` is
   gitignored and machine-local, so on EVERY clean CI checkout the walk falls
   through and ``system_logs/`` resolves against wherever the caller's shell
   happened to stand — silently, and differently per caller.

THE RULE. Derive the fallback from ``__file__``, never from the process. On a
registry-less checkout the source-derived answer IS the checkout, so it is not a
guess there either. The last resort is the filesystem root: defined, incapable of
raising, and absurd enough to fail loudly downstream instead of quietly resolving
into somebody's home directory.

@drone and @memory landed this same shape independently in their own trees.

IMPORT-TIME SAFETY. This module is reached from inside the logger construction
chain, so it imports nothing from prax and uses stdlib ``logging`` only. A
diagnostic must never become the crash it was diagnosing.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

REGISTRY_MARKER = "AIPASS_REGISTRY.json"
SOURCE_DIR_NAME = "src"

_THIS_FILE = Path(__file__).resolve()

# The fallback is announced once per process, not once per caller. Every module
# in the branch reaches this during import; a per-call warning would bury CI
# output on exactly the registry-less checkout the warning is about, and a
# fallback nobody can see is how the next one survives. A set rather than a
# rebindable flag, so nothing here needs ``global``.
_ANNOUNCED: set = set()


# =============================================================================
# RESOLUTION
# =============================================================================


def source_root(start: Optional[Path] = None) -> Path:
    """Derive the checkout root from a file path, reading no process state.

    Walks up for a directory named ``src`` and returns its parent — the layout
    every AIPass branch lives in (``<checkout>/src/aipass/<branch>/...``).

    Args:
        start: A path inside the checkout. Defaults to this file. A RELATIVE
            path is rejected in favour of this file, because resolving one would
            read the working directory this function exists to avoid.

    Returns:
        The directory containing ``src``, or the filesystem root when no ``src``
        component exists. Never the process working directory.
    """
    anchor = start if (start is not None and start.is_absolute()) else _THIS_FILE
    for parent in anchor.parents:
        if parent.name == SOURCE_DIR_NAME:
            return parent.parent
    # Deliberately absurd: a defined answer that fails loudly downstream rather
    # than a plausible one that quietly writes into somebody's home directory.
    return anchor.parents[-1]


def find_repo_root(start: Optional[Path] = None) -> Path:
    """Find the repo root by marker, falling back to the source root — never cwd.

    Args:
        start: A path inside the tree to walk up from; callers pass their own
            ``Path(__file__)``. Defaults to this file. A relative path is
            replaced by this file rather than resolved, since resolving reads
            the working directory.

    Returns:
        The directory containing ``AIPASS_REGISTRY.json`` if one is found above
        ``start``, else :func:`source_root`.
    """
    anchor = start if (start is not None and start.is_absolute()) else _THIS_FILE
    for parent in [anchor] + list(anchor.parents):
        try:
            if (parent / REGISTRY_MARKER).exists():
                return parent
        except OSError as exc:
            # An unreadable directory is not an answer — keep walking rather
            # than let a permissions problem masquerade as "no repo here".
            logger.info("[repo_root] %s is unreadable, continuing the walk: %s", parent, exc)
            continue

    fallback = source_root(anchor)
    _announce_fallback(anchor, fallback)
    return fallback


def _announce_fallback(anchor: Path, fallback: Path) -> None:
    """Say once, out loud, that the marker was never found.

    Uses stdlib logging on purpose — this runs inside the construction of prax's
    own logger, and a warning that needs the logger it is being emitted from is
    a second crash wearing a diagnostic's clothes. That is @memory's caveat and
    it is satisfied by the CHOICE of logger, not by wrapping the call: stdlib
    logging already isolates handler failures (``Handler.handleError``), so a
    broken handler installed by a host application cannot propagate out of here.

    An outer ``except Exception: pass`` was written here first and then removed.
    It only ever caught a condition a test had to invent — replacing this
    module's ``logger`` attribute — and guarding what the platform already
    guarantees is the same "two guards where one decides" that misled a reader
    in introspection.py. The property that matters is pinned structurally
    instead: this module imports nothing from prax.
    """
    if _ANNOUNCED:
        return
    _ANNOUNCED.add(REGISTRY_MARKER)
    logger.warning(
        "[repo_root] %s not found above %s — falling back to the source root %s. "
        "Paths derived from the repo root are resolved against the checkout, "
        "not the working directory.",
        REGISTRY_MARKER,
        anchor,
        fallback,
    )
