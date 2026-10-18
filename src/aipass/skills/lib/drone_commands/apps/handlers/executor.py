# ===================AIPASS====================
# META DATA HEADER
# Name: executor.py - Runs drone commands via subprocess
# Date: 2026-03-07
# Version: 1.0.0
# Category: skills/lib/drone_commands/apps/handlers
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-07): Initial implementation
#
# CODE STANDARDS:
#   - Handlers layer: returns dicts, NEVER prints
#   - stdlib only (no external deps)
#   - Graceful error handling
# =============================================

"""
Executor handler for drone commands.
"""

import os
import subprocess
from pathlib import Path

AIPASS_ROOT = Path(os.environ.get("AIPASS_ROOT", str(Path.home())))
DEFAULT_TIMEOUT = 30


def execute(command, cwd=None, timeout=None):
    """Run a command via subprocess; returns {"success", "stdout", "stderr", "returncode"}."""
    if cwd is None:
        cwd = str(AIPASS_ROOT)
    if timeout is None:
        timeout = DEFAULT_TIMEOUT

    if not command or not command.strip():
        return {
            "success": False,
            "stdout": "",
            "stderr": "Empty command",
            "returncode": -1,
        }

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s: {command}",
            "returncode": -1,
        }
    except FileNotFoundError as exc:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"File not found (bad cwd or shell?): {exc}",
            "returncode": -1,
        }
    except OSError as exc:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"OS error running command: {exc}",
            "returncode": -1,
        }
    except Exception as exc:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Unexpected error: {exc}",
            "returncode": -1,
        }
