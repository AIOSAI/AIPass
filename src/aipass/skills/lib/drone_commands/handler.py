# =================== AIPass ====================
# Name: handler.py
# Description: Drone Commands skill handler, delegates to apps/modules/command_runner
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-10-24
# =============================================

"""
Drone Commands skill handler.

Called by: drone @skills run drone_commands <action> [args]
"""

from aipass.skills.lib.drone_commands.apps.modules import command_runner


def run(action, args=None, config=None):
    """Execute a drone commands action; returns {"success", "output", "error"}."""
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
                "error": "Missing 'command' argument. Usage: drone @skills run drone_commands run 'command=@module action'",
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
                "error": "Missing 'module' argument. Usage: drone @skills run drone_commands help module=<name>",
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
