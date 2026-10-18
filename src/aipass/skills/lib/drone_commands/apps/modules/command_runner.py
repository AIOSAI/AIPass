# ===================AIPASS====================
# META DATA HEADER
# Name: command_runner.py - Orchestrates drone command execution
# Date: 2026-03-07
# Version: 1.0.0
# Category: skills/lib/drone_commands/apps/modules
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-07): Initial implementation
#
# CODE STANDARDS:
#   - Modules layer: orchestration
#   - Delegates to handlers for execution and parsing
#   - Returns dicts for skill handler contract
#   - stdlib only (no external deps)
# =============================================

"""
Command runner module for drone_commands skill.
"""

import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_APPS_DIR = os.path.dirname(_THIS_DIR)
_HANDLERS_DIR = os.path.join(_APPS_DIR, "handlers")

if _HANDLERS_DIR not in sys.path:
    sys.path.insert(0, _HANDLERS_DIR)
if _APPS_DIR not in sys.path:
    sys.path.insert(0, _APPS_DIR)

from handlers import executor, parser


AIPASS_ROOT = os.environ.get("AIPASS_ROOT", os.path.expanduser("~"))
DRONE_BIN = os.path.join(AIPASS_ROOT, "drone")


def run_command(command_string, timeout=None):
    """Run an arbitrary drone command; returns {"success", "output", "error"}."""
    if not command_string or not command_string.strip():
        return {
            "success": False,
            "output": "",
            "error": "No command provided",
        }

    cmd = command_string.strip()
    if not cmd.startswith("drone"):
        cmd = f"drone {cmd}"

    result = executor.execute(cmd, cwd=AIPASS_ROOT, timeout=timeout)

    stdout_clean = parser.parse_output(result.get("stdout", ""))
    stderr_clean = parser.parse_output(result.get("stderr", ""))

    if result["success"]:
        return {
            "success": True,
            "output": stdout_clean,
            "error": None,
        }

    error_parts = []
    if stderr_clean:
        error_parts.append(stderr_clean)
    error_msg = "\n".join(error_parts) if error_parts else f"Command failed with exit code {result['returncode']}"

    output = stdout_clean if stdout_clean else ""

    return {
        "success": False,
        "output": output,
        "error": error_msg,
    }


def list_modules(timeout=None):
    """List all available drone modules via `drone systems`."""
    result = executor.execute("drone systems", cwd=AIPASS_ROOT, timeout=timeout)

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

    return {
        "success": True,
        "output": output,
        "error": None,
    }


def module_help(module_name, timeout=None):
    """Get help for a specific drone module."""
    if not module_name or not module_name.strip():
        return {
            "success": False,
            "output": "",
            "error": "No module name provided",
        }

    module_name = module_name.strip().lstrip("@")
    cmd = f"drone @{module_name} --help"

    result = executor.execute(cmd, cwd=AIPASS_ROOT, timeout=timeout)

    stdout_clean = parser.parse_output(result.get("stdout", ""))
    stderr_clean = parser.parse_output(result.get("stderr", ""))

    if result["success"]:
        output = stdout_clean if stdout_clean else f"No help output for module '{module_name}'"
        return {
            "success": True,
            "output": output,
            "error": None,
        }

    # Some modules output help to stderr
    if stderr_clean and ("usage" in stderr_clean.lower() or "help" in stderr_clean.lower()):
        return {
            "success": True,
            "output": stderr_clean,
            "error": None,
        }

    error_msg = stderr_clean or f"Failed to get help for module '{module_name}'"
    return {
        "success": False,
        "output": stdout_clean,
        "error": error_msg,
    }
