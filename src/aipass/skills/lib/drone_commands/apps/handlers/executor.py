# =================== AIPass ====================
# Name: executor.py
# Description: Runs one drone argv via subprocess, never through a shell
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-10-24
# =============================================

"""
Executor handler for drone commands.
"""

import subprocess

from aipass.prax import logger

DEFAULT_TIMEOUT = 30


def execute(argv, timeout=None):
    """Run an argv list in the caller's cwd, no shell; returns {"success", "stdout", "stderr", "returncode"}."""
    # The caller's cwd stays: drone reads it as the caller's identity.
    if timeout is None:
        timeout = DEFAULT_TIMEOUT

    if not argv:
        return {"success": False, "stdout": "", "stderr": "Empty command", "returncode": -1}

    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning("drone_commands: %s timed out after %ss", argv[:2], timeout)
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s: {' '.join(argv)}",
            "returncode": -1,
        }
    except OSError as exc:
        logger.warning("drone_commands: could not run %s: %s", argv[0], exc)
        return {"success": False, "stdout": "", "stderr": f"Could not run {argv[0]}: {exc}", "returncode": -1}

    return {
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }
