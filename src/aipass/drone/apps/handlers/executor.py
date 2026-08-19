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


# Raised 30 -> 60 on 2026-08-13 (Patrick's ruling). Two known runners finish
# around 31s and were tripping the old default. The evening before showed
# fleet-wide what a quiet default costs: a 30s UserPromptSubmit timeout
# discarded a hooks context for weeks because the real work legitimately took
# longer (DPLAN-0285). A default that kills work at N when work takes N+1 fails
# silently, which is the expensive way to fail.
DEFAULT_TIMEOUT = 60

TIMEOUT_OVERRIDES: dict[str, dict[str, int]] = {
    "memory": {"process-plans": 120, "rollover": 100},
    "flow": {"close": 90},
}


def resolve_timeout(branch: str, command: str | None, explicit: int | None = None) -> int:
    """Resolve subprocess timeout for a branch command.

    Priority: explicit flag > per-command policy > DEFAULT_TIMEOUT.
    """
    if explicit is not None:
        return explicit
    branch_key = branch.lstrip("@").lower()
    if command and branch_key in TIMEOUT_OVERRIDES:
        cmd_timeout = TIMEOUT_OVERRIDES[branch_key].get(command)
        if cmd_timeout is not None:
            return cmd_timeout
    return DEFAULT_TIMEOUT


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
    timeout: int = DEFAULT_TIMEOUT,
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
        raise CommandExecutionError(
            f"Command timed out after {timeout}s: {' '.join(full_cmd)}\n"
            f"  Override with: drone @<target> <command> --drone-timeout <seconds>"
        ) from e
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
