# =================== AIPass ====================
# Name: paths.py
# Description: Shared path utilities for ai_mail handlers
# Version: 1.0.0
# Created: 2026-03-29
# Modified: 2026-03-29
# =============================================

"""
Shared path utilities for ai_mail handlers.

Provides repo root discovery used across all handler files.
Consolidated from 8 identical copies per DPLAN-0036 audit.
"""

import os
import sys
from pathlib import Path
from typing import Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")


_CWD_FALLBACK_WARNED = False

# Markers that identify the repo root, in order of authority.
#
# AIPASS_REGISTRY.json is the live answer and wins whenever it exists. But it is
# UNTRACKED RUNTIME STATE, so on a fresh checkout it exists NOWHERE — which is
# how the cwd fallback stopped being a rare last resort and became the ordinary
# path on every CI run. pyproject.toml is tracked, sits only at the repo root,
# and is on the ancestor chain from this package, so the right answer was always
# available on a fresh checkout; it was simply never asked for.
REPO_ROOT_MARKERS = ("AIPASS_REGISTRY.json", "pyproject.toml")


def find_repo_root() -> Path:
    """Walk up from this file to the repo root, by the first marker that answers.

    THE FRESH CHECKOUT NOW FINDS ITS OWN ROOT. @devpulse put this in my court
    (2026-08-23) with the framing that made the fix findable: the danger is not
    the register being MISSING — they refuse on that, and a missing register
    legitimately means nobody has dispatched here yet — it is the register being
    FOUND IN THE WRONG PLACE, which no refusal they can write will ever catch. A
    watchdog that arms cleanly against an empty file in an unrelated directory
    reports perfect health and covers nothing.

    That is exactly what the old single-marker walk produced. Only
    AIPASS_REGISTRY.json was consulted, it is untracked, so a fresh checkout
    fell through to "wherever this process happens to be standing" and rooted
    the feed, the dispatch register and every completion report there.

    THE CWD FALLBACK SURVIVES, LOUD, AND IT STILL RETURNS RATHER THAN RAISING.
    Refusing would break the fresh checkout it exists to serve: a tree with
    neither marker is broken, but making that fatal turns an unreadable path
    into an import-time failure for every caller, including the ones that never
    needed a repo root. The doctrine asks that a substitution be VISIBLE, not
    that it be fatal — so it is named, once, and the caller carries on.

    Warned once per process because this is called on nearly every path
    construction; a line per call is the runaway-log problem, and a warning
    nobody can read is another kind of silence.
    """
    global _CWD_FALLBACK_WARNED

    current = Path(__file__).resolve().parent
    ancestors = [current] + list(current.parents)

    # Marker-major, not directory-major: a real registry ANYWHERE up the chain
    # outranks a pyproject.toml nearer to hand. The nested case is a package
    # inside a checkout, where the registry is the deeper and more specific
    # answer — losing to a shallower pyproject.toml would re-root everything at
    # the outer tree.
    for marker in REPO_ROOT_MARKERS:
        for parent in ancestors:
            if (parent / marker).exists():
                return parent

    cwd = Path.cwd()
    if not _CWD_FALLBACK_WARNED:
        _CWD_FALLBACK_WARNED = True
        logger.warning(
            "[paths] none of %s found above %s — falling back to the current directory (%s) "
            "as the repo root. Paths derived from this (feed, dispatch register, reports) will be "
            "rooted there. This is no longer expected on a fresh checkout, which pyproject.toml "
            "resolves; reaching here means the tree is not a recognisable AIPass checkout.",
            ", ".join(REPO_ROOT_MARKERS),
            current,
            cwd,
        )
    return cwd


def find_project_root(start: Path) -> Optional[Path]:
    """Walk up from *start* to find the first *_REGISTRY.json (project root).

    Returns the directory containing the registry, or None if not found.
    Stops at filesystem root.
    """
    current = start.resolve()
    for candidate in [current] + list(current.parents):
        try:
            if any(candidate.glob("*_REGISTRY.json")):
                return candidate
        except OSError as exc:
            logger.warning("[paths] find_project_root: glob failed at %s: %s", candidate, exc)
            break
    return None


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    json_handler.log_operation("paths_introspection")
    console.print("\n" + "=" * 70)
    console.print("PATHS UTILITY")
    console.print("=" * 70)
    console.print(f"\nRepo root: {find_repo_root()}")
    console.print("\nFunctions provided:")
    console.print("  - find_repo_root() -> Path")
    console.print()
