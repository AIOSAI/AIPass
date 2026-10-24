# =================== AIPass ====================
# Name: command_runner.py
# Description: Orchestrates drone command execution for the drone_commands skill
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-10-24
# =============================================

"""
Command runner module for drone_commands skill.
"""

import shlex

from aipass.skills.lib.drone_commands.apps.handlers import executor, parser


def _drone_argv(command_string):
    """Split a command into a drone argv; the program is always drone, whatever the string says."""
    argv = shlex.split(command_string)
    if argv and argv[0] == "drone":
        argv = argv[1:]
    return ["drone", *argv]


def run_command(command_string, timeout=None):
    """Run one drone command; returns {"success", "output", "error"}.

    No shell: ';', '&&' and '|' reach drone as plain arguments, never a second command."""
    if not command_string or not command_string.strip():
        return {"success": False, "output": "", "error": "No command provided"}

    try:
        argv = _drone_argv(command_string)
    except ValueError as exc:
        return {"success": False, "output": "", "error": f"Cannot parse command: {exc}"}

    result = executor.execute(argv, timeout=timeout)

    stdout_clean = parser.parse_output(result.get("stdout", ""))
    stderr_clean = parser.parse_output(result.get("stderr", ""))

    if result["success"]:
        return {"success": True, "output": stdout_clean, "error": None}

    error_msg = stderr_clean or f"Command failed with exit code {result['returncode']}"
    return {"success": False, "output": stdout_clean, "error": error_msg}


def list_modules(timeout=None):
    """List all available drone modules via `drone systems`."""
    result = executor.execute(["drone", "systems"], timeout=timeout)

    if not result["success"]:
        stderr_clean = parser.parse_output(result.get("stderr", ""))
        return {
            "success": False,
            "output": "",
            "error": stderr_clean or f"'drone systems' failed with exit code {result['returncode']}",
        }

    stdout_clean = parser.parse_output(result.get("stdout", ""))
    modules = parser.extract_modules(result.get("stdout", ""))

    if modules:
        module_list = "\n".join(f"  - {m}" for m in modules)
        output = f"Registered modules ({len(modules)}):\n{module_list}"
    else:
        output = stdout_clean if stdout_clean else "No modules found"

    return {"success": True, "output": output, "error": None}


def module_help(module_name, timeout=None):
    """Get help for a specific drone module."""
    if not module_name or not module_name.strip():
        return {"success": False, "output": "", "error": "No module name provided"}

    module_name = module_name.strip().lstrip("@")
    result = executor.execute(["drone", f"@{module_name}", "--help"], timeout=timeout)

    stdout_clean = parser.parse_output(result.get("stdout", ""))
    stderr_clean = parser.parse_output(result.get("stderr", ""))

    if result["success"]:
        output = stdout_clean if stdout_clean else f"No help output for module '{module_name}'"
        return {"success": True, "output": output, "error": None}

    # Some modules output help to stderr
    if stderr_clean and ("usage" in stderr_clean.lower() or "help" in stderr_clean.lower()):
        return {"success": True, "output": stderr_clean, "error": None}

    error_msg = stderr_clean or f"Failed to get help for module '{module_name}'"
    return {"success": False, "output": stdout_clean, "error": error_msg}
