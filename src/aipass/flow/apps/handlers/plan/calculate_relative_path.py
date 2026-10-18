# =================== AIPass ====================
# Name: calculate_relative_path.py
# Description: Relative Path Calculator
# Version: 0.1.0
# Created: 2025-11-15
# Modified: 2026-10-17
# =============================================

"""Relative Path Calculator"""

from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.flow.apps.handlers.json import json_handler


def calculate_relative_location(target_dir: Path, ecosystem_root: Path) -> str:
    """Calculate relative location from ecosystem root

    Returns "root" for the root itself, and target_dir unchanged when it lies outside the root.
    """
    try:
        relative_location = str(target_dir.relative_to(ecosystem_root))

        if relative_location == ".":
            relative_location = "root"

        json_handler.log_operation("relative_path_calculated", {"target": str(target_dir), "result": relative_location})
        return relative_location

    except ValueError:
        logger.warning(
            f"[calculate_relative_path] Target '{target_dir}' is outside ecosystem root"
            f" '{ecosystem_root}', using absolute path"
        )
        return str(target_dir)
