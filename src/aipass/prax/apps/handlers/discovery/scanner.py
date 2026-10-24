# =================== AIPass ====================
# Name: scanner.py
# Description: Directory Scanning
# Version: 1.2.0
# Created: 2025-11-10
# Modified: 2026-10-24
# =============================================

"""
PRAX Discovery Scanner
"""

import logging

from pathlib import Path

from datetime import datetime, timezone
from typing import Dict, Any, Optional, Set

from aipass.prax.apps.handlers.config.load import ECOSYSTEM_ROOT, get_system_logs_dir, get_module_logs_dir

from aipass.prax.apps.handlers.discovery import filtering
from aipass.prax.apps.handlers.json import json_handler

logger = logging.getLogger(__name__)


def scan_directory_safely(directory: Path, modules: Dict, max_depth: int = 10, patterns: Optional[Set[str]] = None):
    """Safely scan directory with depth limit"""
    # Sandboxes are never entered: an archived copy would take a live module's stem-keyed entry.
    if max_depth <= 0:
        return
    if patterns is None:
        patterns = filtering.load_ignore_patterns_from_config()

    try:
        items = list(directory.iterdir())
    except OSError as e:
        logger.warning(f"[scanner] Error scanning directory {directory}: {e}")
        return

    # Per item: one file vanishing mid-walk must not drop the rest of the directory from the registry.
    for item in items:
        try:
            if filtering.should_ignore_path(item, ECOSYSTEM_ROOT, patterns) or filtering.in_sandbox(item, directory):
                continue

            if item.is_file() and item.suffix == ".py":
                module_name = item.stem
                stat = item.stat()
                modules[module_name] = {
                    "file_path": str(item),
                    "relative_path": str(item.relative_to(ECOSYSTEM_ROOT)),
                    "system_log_file": str(get_system_logs_dir() / f"prax_{module_name}.log"),
                    "log_file": str(get_module_logs_dir("prax") / f"{module_name}.log"),
                    "discovered_time": datetime.now(timezone.utc).isoformat(),
                    "size": stat.st_size,
                    "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "enabled": True,
                }

            elif item.is_dir():
                scan_directory_safely(item, modules, max_depth - 1, patterns)

        except (OSError, ValueError) as e:
            logger.warning(f"[scanner] Error scanning {item}: {e}")


def discover_python_modules() -> Dict[str, Dict[str, Any]]:
    """Discover all Python modules in the ecosystem"""
    modules = {}

    scan_directory_safely(ECOSYSTEM_ROOT, modules)

    json_handler.log_operation("modules_scanned", {"modules_found": len(modules)})

    return modules
