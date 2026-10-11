# ===================AIPASS====================
# META DATA HEADER
# Name: handler.py - Drone Commands skill handler
# Date: 2026-03-07
# Version: 1.0.0
# Category: skills/lib/drone_commands
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-07): Initial implementation
#
# CODE STANDARDS:
#   - Top-level handler: delegates to apps/modules/
#   - Returns dicts, NEVER prints
#   - stdlib only (no external deps)
#   - Graceful error handling
# =============================================

"""
Drone Commands skill handler.

Top-level entry point that delegates to the command_runner module
in the 3-layer apps/ structure.

Called by: drone @skills run drone_commands <action> [args]
"""

import os
import sys

# Set up import path for this skill's apps package
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_APPS_DIR = os.path.join(_THIS_DIR, "apps")
_MODULES_DIR = os.path.join(_APPS_DIR, "modules")

if _MODULES_DIR not in sys.path:
    sys.path.insert(0, _MODULES_DIR)
if _APPS_DIR not in sys.path:
    sys.path.insert(0, _APPS_DIR)

from modules import command_runner


def run(action, args=None, config=None):
    """Execute a drone commands action.

    Args:
        action: One of: run, list, help
        args: Dict of action arguments:
            - run: {"command": "drone @module action"}
            - list: {} (no args needed)
            - help: {"module": "module_name"}
        config: Dict of resolved config values (unused)

    Returns:
        {"success": bool, "output": str, "error": str|None}
    """
    args = args or {}
    config = config or {}

    timeout = args.get("timeout")
    if timeout is not None:
        try:
            timeout = int(timeout)
        except (ValueError, TypeError):
            timeout = None

    if action == "run":
        command = args.get("command", "")
        if not command:
            return {
                "success": False,
                "output": "",
                "error": "Missing 'command' argument. Usage: --args '{\"command\": \"drone @module action\"}'",
            }
        return command_runner.run_command(command, timeout=timeout)

    elif action == "list":
        return command_runner.list_modules(timeout=timeout)

    elif action == "help":
        module_name = args.get("module", "")
        if not module_name:
            return {
                "success": False,
                "output": "",
                "error": "Missing 'module' argument. Usage: --args '{\"module\": \"module_name\"}'",
            }
        return command_runner.module_help(module_name, timeout=timeout)

    else:
        available = ", ".join(get_actions())
        return {
            "success": False,
            "output": "",
            "error": f"Unknown action: {action}. Available: {available}",
        }


def get_actions():
    """List available actions for this skill."""
    return ["run", "list", "help"]
