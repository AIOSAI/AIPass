# ===================AIPASS====================
# META DATA HEADER
# Name: __init__.py - Daemon Scheduler Plugin Interface
# Date: 2026-02-20
# Version: 1.0.0
# Category: daemon/apps/plugins
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-02-20): Initial plugin interface definition
#
# CODE STANDARDS:
#   - Plugin interface specification only
#   - No business logic
# =============================================

"""
Daemon Scheduler Plugin Interface

A plugin is a non-underscore .py here exposing PLUGIN_CONFIG with every key discover_plugins requires.
"""

import importlib
from pathlib import Path

from aipass.prax import logger


def discover_plugins() -> list:
    """Discover all valid plugins in this directory."""
    plugins_dir = Path(__file__).parent
    plugins = []

    for file_path in sorted(plugins_dir.glob("*.py")):
        if file_path.name.startswith("_"):
            continue

        module_name = file_path.stem
        try:
            module = importlib.import_module(f".{module_name}", package=__package__)

            if not hasattr(module, "PLUGIN_CONFIG"):
                continue

            config = module.PLUGIN_CONFIG

            required = {"name", "schedule", "enabled", "branch", "fresh", "max_turns", "prompt"}
            missing = required - set(config.keys())
            if missing:
                continue

            plugins.append(
                {
                    "module": module,
                    "config": config,
                    "file": str(file_path),
                }
            )
        except Exception as e:
            logger.warning("Failed to load plugin %s: %s", module_name, e)
            continue

    return plugins
