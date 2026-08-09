# =================== AIPass ====================
# Name: readme_map/__init__.py
# Description: Branch-name to README-path lookup and live README reads
# Version: 1.2.0
# Created: 2026-04-16
# Modified: 2026-08-08
# =============================================

"""readme_map — branch-name → README-path lookup for help_chat live reads.

Principle: map is cached (path lookup only). Content is NEVER cached.
Every question live-reads the current file. Nothing hardcoded.

AIPASS_ROOT detection:
  1. Try os.environ["AIPASS_HOME"] — if set, use it
  2. Fall back: walk up from this file to find directory containing src/aipass/
  3. AIPASS_ROOT = the parent of src/aipass/ (i.e., the Projects/AIPass directory)
"""

from __future__ import annotations

import os
from pathlib import Path

from aipass.prax import logger

# =============================================================================
# AIPASS ROOT DETECTION
# =============================================================================

_AIPASS_ROOT: Path | None = None


def _detect_aipass_root() -> Path:
    """Detect the AIPass project root (parent of src/aipass/)."""
    # Strategy 1: environment variable
    env_home = os.environ.get("AIPASS_HOME")
    if env_home:
        return Path(env_home)

    # Strategy 2: walk up from this file to find src/aipass/
    # This file lives at: src/aipass/aipass/apps/handlers/readme_map/__init__.py
    # parents: [0]=readme_map/, [1]=handlers/, [2]=apps/, [3]=aipass/,
    #          [4]=src/aipass/, [5]=Projects/AIPass/ (AIPASS_ROOT)
    current = Path(__file__).resolve()
    for parent in current.parents:
        src_aipass = parent / "src" / "aipass"
        if src_aipass.is_dir():
            return parent

    # Fallback: use the inferred path directly (5 levels up from this file)
    return Path(__file__).resolve().parents[5]


# =============================================================================
# BRANCH DISCOVERY
# =============================================================================

# Module-level cache: branch_name → readme_path
# This is the ONLY thing cached. Content is always live-read.
_README_MAP: dict[str, Path] | None = None


def _build_readme_map() -> dict[str, Path]:
    """Build the branch → README.md path map. Called once, result cached.

    Branches are discovered live — any src/aipass/<dir>/README.md counts.
    No hardcoded roster: a branch spawned yesterday is findable today.
    """
    global _AIPASS_ROOT
    if _AIPASS_ROOT is None:
        _AIPASS_ROOT = _detect_aipass_root()

    src_aipass = _AIPASS_ROOT / "src" / "aipass"
    result: dict[str, Path] = {}
    if not src_aipass.is_dir():
        return result
    for readme in sorted(src_aipass.glob("*/README.md")):
        result[readme.parent.name] = readme
    return result


def _get_map() -> dict[str, Path]:
    """Return the cached README map, building it on first call."""
    global _README_MAP
    if _README_MAP is None:
        _README_MAP = _build_readme_map()
    return _README_MAP


# =============================================================================
# PUBLIC API
# =============================================================================


def get_readme_path(branch: str) -> Path | None:
    """Return Path to src/aipass/{branch}/README.md if it exists, else None.

    NEVER reads the file — just returns the path.
    """
    return _get_map().get(branch)


def list_branches() -> list[str]:
    """Return list of branches that have a README.md.

    Checked against the cached path map (built on first call).
    Reflects the filesystem state at the time the map was first built.
    """
    return list(_get_map().keys())


def read_readme_lines(branch: str) -> list[str] | None:
    """Live-read README.md for a branch. Returns list of lines, or None on error.

    Content is NEVER cached — every call reads the current file.
    """
    readme_path = get_readme_path(branch)
    if readme_path is None:
        return None
    try:
        with open(readme_path, encoding="utf-8") as fh:
            return fh.readlines()
    except OSError as exc:
        logger.error("[readme_map] Could not read %s: %s", readme_path, exc)
        return None


def read_readme_at(readme_path: Path) -> str | None:
    """Live-read a README at a known path. Returns the whole document, or None on error.

    The path-based counterpart to read_readme_lines: callers that already
    resolved a path (and reported their own not-found message) read through
    here rather than touching the filesystem themselves. Content is NEVER
    cached — every call reads the current file.
    """
    try:
        with open(readme_path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        logger.error("[readme_map] Could not read %s: %s", readme_path, exc)
        return None
