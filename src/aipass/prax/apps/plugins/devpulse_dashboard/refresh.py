# =================== AIPass ====================
# Name: refresh.py
# Description: Orchestrates all devpulse custom dashboard sections
# Version: 1.0.0
# Created: 2026-05-16
# Modified: 2026-10-17
# =============================================

"""Refresh orchestrator for devpulse dashboard plugin."""

from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax.apps.modules.logger import system_logger as logger


# No .resolve(): on Windows ntpath.realpath reads the cwd, and the parents here are structural.
_AIPASS_SRC = Path(__file__).parents[4]  # .../src/aipass/
DEVPULSE_PATH = _AIPASS_SRC / "devpulse"


def refresh(branch_path: Optional[Path] = None) -> Dict:
    """Refresh all devpulse custom dashboard sections; one failing section does not block the others."""
    target = branch_path or DEVPULSE_PATH
    results: Dict[str, Dict] = {}

    builders: List[tuple] = [
        ("git", _refresh_git),
        ("dispatch", _refresh_dispatch),
    ]

    for name, builder_fn in builders:
        try:
            builder_fn(target)
            results[name] = {"success": True, "error": None}
        except Exception as e:
            logger.error("Failed to refresh section '%s': %s", name, e)
            results[name] = {"success": False, "error": str(e)}

    return results


def _refresh_git(branch_path: Path) -> None:
    from .git_section import build_git_section

    build_git_section(branch_path)


def _refresh_dispatch(branch_path: Path) -> None:
    from .dispatch_section import build_dispatch_section

    build_dispatch_section(branch_path)
