# =================== AIPass ====================
# Name: calculate_relative_path.py
# Description: Relative Path Calculator
# Version: 0.1.0
# Created: 2025-11-15
# Modified: 2025-11-15
# =============================================

"""
Relative Path Calculator

Calculates relative paths from ecosystem root for plan location display.
"""

from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.flow.apps.handlers.json import json_handler


def calculate_relative_location(target_dir: Path, ecosystem_root: Path) -> str:
    """
    Calculate relative location from ecosystem root

    Returns a string representation of target_dir relative to ecosystem_root.
    Special cases:
    - If target_dir == ecosystem_root, returns "root"
    - If target_dir outside ecosystem_root, returns absolute path string

    Args:
        target_dir: Absolute path to target directory
        ecosystem_root: Root directory for relative calculation

    Returns:
        Relative path string, "root" if same as ecosystem_root,
        or absolute path string if outside ecosystem_root

    Examples:
        >>> calculate_relative_location(
        ...     Path("/repo/src/aipass/flow"),
        ...     Path("/repo/src/aipass")
        ... )
        "flow"

        >>> calculate_relative_location(
        ...     Path("/repo/src/aipass"),
        ...     Path("/repo/src/aipass")
        ... )
        "root"

        >>> calculate_relative_location(
        ...     Path("/tmp/somewhere"),
        ...     Path("/repo/src/aipass")
        ... )
        "/tmp/somewhere"
    """
    try:
        relative_location = str(target_dir.relative_to(ecosystem_root))

        # Special case: "." becomes "root" for clarity
        if relative_location == ".":
            relative_location = "root"

        json_handler.log_operation("relative_path_calculated", {"target": str(target_dir), "result": relative_location})
        return relative_location

    except ValueError:
        # target_dir is outside ecosystem_root
        logger.warning(
            f"[calculate_relative_path] Target '{target_dir}' is outside ecosystem root '{ecosystem_root}', using absolute path"
        )
        return str(target_dir)
