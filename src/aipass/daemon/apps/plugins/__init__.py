
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

Plugins are auto-discovered Python files in this directory.
Each plugin defines WHAT to run and WHEN via PLUGIN_CONFIG.
The scheduler runner handles HOW (calling wake script).

Plugin Contract:
    1. Expose PLUGIN_CONFIG dict (required)
    2. Expose run() -> dict function (optional, for custom logic)

PLUGIN_CONFIG Schema:
    {
        "name": str,              # Unique plugin identifier
        "schedule": str,          # "daily" | "hourly" | "interval"
        "time": str | None,       # For daily: "HH:MM" (24h). For hourly: minute "MM"
        "interval_minutes": int | None,  # For interval: minutes between runs
        "enabled": bool,          # Plugin active/inactive toggle
        "branch": str,            # Target branch email (e.g., "@seedgo")
        "fresh": bool,            # True = fresh session, False = resume
        "max_turns": int,         # Max agent turns (safety limit)
        "prompt": str,            # What the spawned agent should do
    }

Schedule Types:
    - "daily": Runs once per day at PLUGIN_CONFIG["time"] (HH:MM)
    - "hourly": Runs once per hour at minute PLUGIN_CONFIG["time"] (MM)
    - "interval": Runs every PLUGIN_CONFIG["interval_minutes"] minutes

Naming Convention:
    - Name plugins by WHAT they do, not WHO/WHEN
    - Good: daily_audit.py, heartbeat.py, backup.py
    - Bad: seed_daily_audit.py, vera_heartbeat.py
    - The PLUGIN_CONFIG holds branch/schedule metadata
"""

# Plugin discovery helper
import importlib
from pathlib import Path

from aipass.prax import logger


def discover_plugins() -> list:
    """
    Discover all valid plugins in this directory.

    Returns list of dicts: [{"module": module, "config": PLUGIN_CONFIG}, ...]
    """
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

            # Validate required fields
            required = {"name", "schedule", "enabled", "branch", "fresh", "max_turns", "prompt"}
            missing = required - set(config.keys())
            if missing:
                continue

            plugins.append({
                "module": module,
                "config": config,
                "file": str(file_path),
            })
        except Exception as e:
            logger.warning("Failed to load plugin %s: %s", module_name, e)
            continue

    return plugins
