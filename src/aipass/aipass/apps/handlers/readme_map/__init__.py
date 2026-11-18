# =================== AIPass ====================
# Name: readme_map/__init__.py
# Description: Branch-name to README-path lookup and live README reads
# Version: 1.4.0
# Created: 2026-04-16
# Modified: 2026-11-17
# =============================================

"""readme_map — branch-name → README-path lookup for `aipass read`; the map is cached, content never."""

from __future__ import annotations

import os
from pathlib import Path

from aipass.aipass.shared.project_home import _detect_aipass_home
from aipass.prax import logger

_AIPASS_ROOT: Path | None = None


def _detect_aipass_root() -> Path:
    """The AIPass project root (parent of src/aipass/); raises, never an empty map, when there is none."""
    env_home = os.environ.get("AIPASS_HOME")
    if env_home:
        return Path(env_home)

    for parent in Path(__file__).resolve().parents:
        if (parent / "src" / "aipass").is_dir():
            return parent

    if not (home := _detect_aipass_home()):
        raise RuntimeError("No AIPass home found, so no branch README can be read: set AIPASS_HOME=/path/to/AIPass")
    return Path(home)


_README_MAP: dict[str, Path] | None = None


def _build_readme_map() -> dict[str, Path]:
    """Build the branch → README.md path map. Called once, result cached.

    No hardcoded roster: any src/aipass/<dir>/README.md counts, so a new branch is findable.
    A dot-dir is tooling, never a branch: pytest's .pytest_cache ships a README.md."""
    global _AIPASS_ROOT
    if _AIPASS_ROOT is None:
        _AIPASS_ROOT = _detect_aipass_root()

    src_aipass = _AIPASS_ROOT / "src" / "aipass"
    result: dict[str, Path] = {}
    if not src_aipass.is_dir():
        return result
    for readme in sorted(src_aipass.glob("*/README.md")):
        if not readme.parent.name.startswith("."):
            result[readme.parent.name] = readme
    return result


def _get_map() -> dict[str, Path]:
    """Return the cached README map, building it on first call."""
    global _README_MAP
    if _README_MAP is None:
        _README_MAP = _build_readme_map()
    return _README_MAP


def get_readme_path(branch: str) -> Path | None:
    """Return Path to src/aipass/{branch}/README.md if it exists, else None."""
    return _get_map().get(branch)


def list_branches() -> list[str]:
    """Return list of branches that have a README.md.

    Reflects the filesystem as it was when the cached map was first built."""
    return list(_get_map().keys())


def read_readme_at(readme_path: Path) -> str | None:
    """Live-read a README at a known path. Returns the whole document, or None on error.

    For callers that already resolved a path: they read through here, not the filesystem."""
    try:
        with open(readme_path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        logger.error("[readme_map] Could not read %s: %s", readme_path, exc)
        return None
