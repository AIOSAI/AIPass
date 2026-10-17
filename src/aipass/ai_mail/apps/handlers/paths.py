# =================== AIPass ====================
# Name: paths.py
# Description: Shared path utilities for ai_mail handlers
# Version: 1.1.0
# Created: 2026-03-29
# Modified: 2026-10-17
# =============================================

"""
Shared path utilities for ai_mail handlers.
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

REPO_ROOT_MARKERS = ("AIPASS_REGISTRY.json", "pyproject.toml")

# Match the SUFFIX, never the stem: external projects name registries after themselves.
REGISTRY_SUFFIX = "_REGISTRY.json"
REGISTRY_GLOB = f"*{REGISTRY_SUFFIX}"


def registries_in(directory: Path, pattern: str = REGISTRY_GLOB) -> list:
    """Registry files under *directory*, with the NAME re-checked case-sensitively.

    pathlib glob folds case on Windows, so ``*_registry.json`` counters would pass as identity-bearing registries.
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
            logger.info(
                "[paths] registries_in: %s refused — name does not end with %s (case-insensitive filesystem)",
                candidate.name,
                REGISTRY_SUFFIX,
            )
    return sorted(kept)


def find_repo_root() -> Path:
    """Walk up from this file to the repo root, by the first marker that answers."""
    global _CWD_FALLBACK_WARNED

    current = Path(__file__).resolve().parent
    ancestors = [current] + list(current.parents)

    # Marker-major: a registry anywhere up the chain outranks a nearer pyproject.toml (nested checkout).
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

    An unreadable level is skipped, not fatal: for the delivery fence a found root fails closed, None allows.
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
