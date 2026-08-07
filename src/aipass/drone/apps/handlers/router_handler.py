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
from typing import List, Optional

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
        raise CommandExecutionError(f"Entry point not found for branch '{branch_name}': {entry_point}")
    return entry_point


_REGISTRY_SUFFIX = "_REGISTRY.json"


def _project_name_from_registry(reg_file: Path) -> str | None:
    """Derive a project name from a registry file, or None if it cannot be read.

    Prefers a declared ``metadata.project_name``/``name``, then falls back to the
    filename: AIPASS_REGISTRY.json → 'aipass', VERA-STUDIO_REGISTRY.json →
    'vera-studio'. The filename is the one thing every registry provably has —
    AIPass's own metadata carries only version/last_updated/total_branches/id, so
    requiring a declared name made the framework repo the one place this fallback
    could never fire.
    """
    try:
        with open(reg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("Caller detection: registry %s found but unreadable: %s", reg_file, exc)
        return None

    meta = data.get("metadata", {}) if isinstance(data, dict) else {}
    declared = meta.get("project_name") or meta.get("name")
    if declared:
        return str(declared).lower().replace(" ", "-")

    derived = reg_file.name[: -len(_REGISTRY_SUFFIX)].lower().replace(" ", "-")
    if not derived:
        # A file named exactly '_REGISTRY.json' leaves nothing to derive from.
        logger.warning("Caller detection: registry %s yields no usable project name", reg_file)
        return None

    logger.info(
        "Caller detection: registry %s declares no metadata.name — using filename-derived '%s'",
        reg_file.name,
        derived,
    )
    return derived


def detect_caller_branch_name(cwd: Path) -> str | None:
    """Walk up from cwd to find .trinity/passport.json and extract branch name.

    Falls back to the project name from the registry when no passport is found —
    a caller standing at a project root rather than in a branch. That resolves to
    the PROJECT, never to a citizen, and deliberately so: CWD is identity, and a
    registry file proves which project you are in, not who you are. Nothing here
    grants authority; git's owner-tier reads passports directly and a name
    derived here can never satisfy it.
    """
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
                if name:
                    return name
                logger.warning("Passport at %s names no branch — trying registry fallback", passport)
            except Exception as exc:
                logger.warning("Failed to read passport at %s: %s — trying registry fallback", passport, exc)
            # A passport was found but is unusable. Stop the walk-up rather than
            # continue: a parent branch's passport would misattribute identity.
            # Fall through to the registry fallback, which the docstring promises
            # and the old `return None` here silently skipped.
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Fallback: detect project name from registry file (callers at a project root)
    current = cwd.resolve()
    for _ in range(10):
        # sorted() so a directory holding two registries resolves the same way
        # every time, matching registry_handler._first_registry_in.
        for reg_file in sorted(current.glob(f"*{_REGISTRY_SUFFIX}")):
            project_name = _project_name_from_registry(reg_file)
            if project_name:
                return project_name
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Single log site for a lost caller identity — every caller of this function
    # gets the breadcrumb without any of them re-logging it. WARNING, not ERROR:
    # the branch that actually refuses the work owns the page (see auth.py).
    # Without the cwd this failure is invisible — the downstream error names the
    # TARGET's directory, which sends investigation to the wrong branch entirely.
    logger.warning("Caller branch detection failed — no passport or registry found from cwd %s", cwd)
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
    caller_env = {
        "AIPASS_CALLER_CWD": str(Path.cwd()),
        "AIPASS_BRANCH_NAME": branch_name,
    }

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

    caller_tag = f" [CALLER:{caller_branch.upper()}]" if caller_branch else ""
    logger.info("Executed @%s%s %s → exit %d", branch_name, caller_tag, command or "(introspection)", result.exit_code)
    json_handler.log_operation(
        "execute_branch_command", {"branch": branch_name, "command": command or "", "exit_code": result.exit_code}
    )

    return CommandResult(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        branch=branch_name,
        command=command or "",
    )
