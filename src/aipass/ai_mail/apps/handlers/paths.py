# =================== AIPass ====================
# Name: paths.py
# Description: Shared path utilities for ai_mail handlers
# Version: 1.1.0
# Created: 2026-03-29
# Modified: 2026-08-31
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

# The suffix a registry file must END with, case exactly as written.
#
# SUFFIX, never the stem. External projects name their registry after
# themselves — Vera-Studio_REGISTRY.json, vera_studio_REGISTRY.json — so a check
# keyed on the stem would delete real citizens in order to fix this bug.
REGISTRY_SUFFIX = "_REGISTRY.json"
REGISTRY_GLOB = f"*{REGISTRY_SUFFIX}"


def registries_in(directory: Path, pattern: str = REGISTRY_GLOB) -> list:
    """Registry files under *directory*, with the NAME re-checked case-sensitively.

    The one filtered reader every registry walk in this branch goes through.
    ``pathlib`` delegates matching to the filesystem, so on Windows and default
    macOS ``*_REGISTRY.json`` also matches ``*_registry.json`` — and this repo is
    full of bait: ``drone_command_registry.json`` sits beside drone's tree, every
    branch carries ``.spawn/.template_registry.json`` (pathlib ``*`` matches
    dotfiles, unlike the ``glob`` module), and @flow keeps ten
    ``flow_json/*_registry.json`` plan counters. Measured on CI, ``find_registry``
    returned a command table as the trust-anchor candidate (@drone, ef029782).

    The glob still does the walking — only the filesystem knows where the files
    are. What it cannot be trusted with is the ANSWER, so the name is compared
    again here in Python, where case means what it says.

    Why this matters in ai_mail specifically: these walks are identity-bearing.
    They answer "which project is this" for the cross-project delivery fence and
    "which registry names the caller" for branch detection. A counter file
    accepted as a registry is the directory-name-as-identity species arriving
    through a different door.

    Args:
        directory: Where to look.
        pattern: Glob pattern, defaulting to one level. Callers pass a deeper
            pattern (``*/*_REGISTRY.json``) for tree discovery; the SUFFIX check
            below is applied whatever the depth, which is the whole point of
            routing every depth through one function.

    Returns:
        Sorted list of matching paths. Sorted for a deterministic pick when a
        directory holds several — callers that only want existence read the
        list's truthiness.
    """
    try:
        found = list(directory.glob(pattern))
    except OSError as exc:
        logger.warning("[paths] registries_in: glob failed at %s: %s", directory, exc)
        return []

    kept = []
    for candidate in found:
        if candidate.name.endswith(REGISTRY_SUFFIX):
            kept.append(candidate)
        else:
            # Named, never silent. On Linux this branch is unreachable and the
            # log stays empty; on Windows it is the only record that the
            # filesystem handed back something the pattern did not ask for.
            logger.info(
                "[paths] registries_in: %s refused — name does not end with %s (case-insensitive filesystem)",
                candidate.name,
                REGISTRY_SUFFIX,
            )
    return sorted(kept)


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

    Reads through :func:`registries_in`, so a lowercase counter file cannot be
    mistaken for a registry on a case-insensitive filesystem. This answer feeds
    the cross-project delivery fence (``delivery.py``), where a wrong root makes
    the fence compare two different questions and refuse ordinary same-project
    mail.

    One behaviour change came with that: an unreadable directory used to abort
    the whole walk and return None. It now skips that level and keeps climbing —
    a registry found higher up is still a real registry, and for the fence the
    new direction fails CLOSED (a found root can refuse; None always allows).

    Returns the directory containing the registry, or None if not found.
    Stops at filesystem root.
    """
    current = start.resolve()
    for candidate in [current] + list(current.parents):
        if registries_in(candidate):
            return candidate
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
