# =================== AIPass ====================
# Name: scanner.py
# Description: Directory Scanning
# Version: 1.1.0
# Created: 2025-11-10
# Modified: 2026-03-09
# =============================================

"""
PRAX Discovery Scanner

Safe directory scanning for Python module discovery.
"""

import logging

from pathlib import Path

from datetime import datetime, timezone
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Import from prax config
from aipass.prax.apps.handlers.config.load import ECOSYSTEM_ROOT, get_system_logs_dir, get_module_logs_dir

# Import filtering
from aipass.prax.apps.handlers.discovery.filtering import should_ignore_path
from aipass.prax.apps.handlers.json import json_handler


def scan_directory_safely(directory: Path, modules: Dict, max_depth: int = 10):
    """Safely scan directory with depth limit

    Recursively scans directory for Python files, respecting ignore patterns
    and depth limits to prevent infinite loops.

    Args:
        directory: Directory to scan
        modules: Dict to populate with discovered modules
        max_depth: Maximum recursion depth (default 10)
    """
    if max_depth <= 0:
        return

    try:
        for item in directory.iterdir():
            if should_ignore_path(item):
                continue

            if item.is_file() and item.suffix == ".py":
                module_name = item.stem
                relative_path = item.relative_to(ECOSYSTEM_ROOT)

                modules[module_name] = {
                    "file_path": str(item),
                    "relative_path": str(relative_path),
                    "system_log_file": str(get_system_logs_dir() / f"prax_{module_name}.log"),
                    "log_file": str(get_module_logs_dir("prax") / f"{module_name}.log"),
                    "discovered_time": datetime.now(timezone.utc).isoformat(),
                    "size": item.stat().st_size,
                    "modified_time": datetime.fromtimestamp(item.stat().st_mtime).isoformat(),
                    "enabled": True,
                }

            elif item.is_dir():
                scan_directory_safely(item, modules, max_depth - 1)

    except PermissionError as e:
        logger.warning(f"[scanner] Permission denied scanning directory {directory}: {e}")
    except Exception as e:
        logger.warning(f"[scanner] Error scanning directory {directory}: {e}")


def discover_python_modules() -> Dict[str, Dict[str, Any]]:
    """Discover all Python modules in the ecosystem

    Returns:
        Dict mapping module names to their metadata
    """
    modules = {}

    # Scan entire ecosystem recursively
    scan_directory_safely(ECOSYSTEM_ROOT, modules)

    json_handler.log_operation("modules_scanned", {"modules_found": len(modules)})

    return modules
