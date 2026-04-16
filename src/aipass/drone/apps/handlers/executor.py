# =================== AIPass ====================
# Name: executor.py
# Description: Safe subprocess execution for branch command routing
# Version: 1.0.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""
Safe subprocess execution for branch command routing.

Wraps subprocess.run with safety guards: timeout enforcement, no shell injection,
captured output, and consistent error wrapping via CommandExecutionError.
"""

import subprocess
from dataclasses import dataclass
from typing import List

from .exceptions import CommandExecutionError
from aipass.drone.apps.handlers.json import json_handler


@dataclass
class CommandResult:
    """Result of a routed command execution."""

    stdout: str
    stderr: str
    exit_code: int
    branch: str
    command: str


def execute_command(
    executable: str,
    args: List[str],
    cwd: str,
    timeout: int = 30,
    env: dict | None = None,
    interactive: bool = False,
) -> CommandResult:
    """Execute a command via subprocess with safety guards.

    Never uses shell=True to prevent shell injection attacks.

    Args:
        interactive: If True, inherit stdio (no capture, no timeout).
                     Used for long-running commands like prax monitor.
    """
    import os

    full_cmd = [executable] + list(args)

    # Merge custom env vars with current environment
    run_env = None
    if env:
        run_env = os.environ.copy()
        run_env.update(env)

    try:
        if interactive:
            # Inherit stdin/stdout/stderr for live interaction
            result = subprocess.run(
                full_cmd,
                cwd=cwd,
                shell=False,
                env=run_env,
            )
        else:
            result = subprocess.run(
                full_cmd,
                cwd=cwd,
                capture_output=True,
                timeout=timeout,
                shell=False,
                env=run_env,
            )
    except KeyboardInterrupt:
        # Clean exit on Ctrl+C — no traceback
        if interactive:
            return CommandResult(stdout="", stderr="", exit_code=130, branch="", command="")
        raise
    except subprocess.TimeoutExpired as e:
        raise CommandExecutionError(f"Command timed out after {timeout}s: {' '.join(full_cmd)}") from e
    except FileNotFoundError as e:
        raise CommandExecutionError(f"Executable not found: {executable!r}") from e
    except OSError as e:
        raise CommandExecutionError(f"OS error executing command: {e}") from e

    if interactive:
        return CommandResult(
            stdout="",
            stderr="",
            exit_code=result.returncode,
            branch="",
            command="",
        )

    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")

    json_handler.log_operation("execute_command", {"command": str(full_cmd), "exit_code": result.returncode})

    return CommandResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=result.returncode,
        branch="",
        command="",
    )
