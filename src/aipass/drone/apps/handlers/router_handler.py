# =================== AIPass ====================
# Name: router_handler.py
# Description: Handler for command routing implementation
# Version: 1.0.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""
Handler for command routing implementation.

Handles entry point resolution, caller detection, environment building,
and subprocess execution for branch command routing.
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax import logger
from aipass.prax.apps.modules.logger import system_logger
from .exceptions import CommandExecutionError
from .executor import CommandResult, execute_command
from aipass.drone.apps.handlers.json import json_handler

logger = system_logger


def find_entry_point(branch_path: str, branch_name: str) -> Path:
    """Locate the apps/{branch_name}.py entry point for a branch.

    Raises:
        CommandExecutionError: If entry point does not exist
    """
    entry_point = Path(branch_path) / "apps" / f"{branch_name}.py"
    if not entry_point.exists():
        raise CommandExecutionError(
            f"Entry point not found for branch '{branch_name}': {entry_point}"
        )
    return entry_point


def detect_caller_branch_name(cwd: Path) -> str | None:
    """Walk up from cwd to find .trinity/passport.json and extract branch name."""
    current = cwd.resolve()
    for _ in range(10):
        passport = current / ".trinity" / "passport.json"
        if passport.exists():
            try:
                with open(passport, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Handle both passport formats:
                # v1: branch_info.branch_name (local/full passport)
                # v2: identity.name (Docker/minimal passport)
                name = data.get("branch_info", {}).get("branch_name")
                if not name:
                    name = data.get("identity", {}).get("name")
                return name
            except Exception:
                return None
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def execute_branch_command(
    branch_path: str,
    branch_name: str,
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    timeout: int = 30,
    interactive: bool = False,
) -> CommandResult:
    """Execute a command against a branch's entry point via subprocess.

    Resolves the entry point, builds caller environment, and delegates
    to the subprocess executor.

    When command is None, runs the branch with no args (introspection).

    Returns:
        CommandResult with stdout, stderr, exit_code, branch, and command
    """
    entry_point = find_entry_point(branch_path, branch_name)

    relative_entry = str(entry_point.relative_to(branch_path))
    cmd_args = [relative_entry]
    if command:
        cmd_args += [command] + list(args or [])

    # Pass caller's CWD so target branches can detect who invoked them
    caller_env = {"AIPASS_CALLER_CWD": str(Path.cwd())}

    # Detect caller branch name from passport.json, fall back to env var
    # (dispatched agents set AIPASS_BRANCH_NAME which survives cd)
    caller_branch = detect_caller_branch_name(Path.cwd())
    if not caller_branch:
        caller_branch = os.environ.get("AIPASS_BRANCH_NAME")
    if caller_branch:
        caller_env["AIPASS_CALLER_BRANCH"] = caller_branch

    result = execute_command(
        executable=sys.executable,
        args=cmd_args,
        cwd=branch_path,
        timeout=timeout,
        env=caller_env,
        interactive=interactive,
    )

    logger.info("Executed @%s %s → exit %d", branch_name, command or "(introspection)", result.exit_code)
    json_handler.log_operation("execute_branch_command", {"branch": branch_name, "command": command or "", "exit_code": result.exit_code})

    return CommandResult(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        branch=branch_name,
        command=command or "",
    )
