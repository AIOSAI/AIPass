# =================== AIPass ====================
# Name: auth.py
# Description: Passport-based authorization for devpulse operations
# Version: 1.0.0
# Created: 2026-03-30
# Modified: 2026-03-30
# =============================================

"""Passport-based authorization for devpulse operations.

Verifies the calling branch identity by walking up from CWD to locate
``.trinity/passport.json`` and checking the branch name against the
allowed-callers list.
"""

from __future__ import annotations

import json
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.seedgo.apps.modules.permissions import TRUSTED_CROSS_WRITERS

ALLOWED_CALLERS: list[str] = list(TRUSTED_CROSS_WRITERS)

GIT_ACCESS_TIERS: dict[str, dict] = {
    "global": {
        "commands": ["status", "diff", "log", "lock", "issue", "run", "workflow", "branches"],
        "description": "Read-only — available to all branches",
    },
    "owner": {
        "commands": [
            "commit",
            "checkout",
            "sync",
            "unlock",
            "merge",
            "smart-sync",
            "fix",
            "dev-pr",
            "pr",
            "delete-branch",
        ],
        "allowed_callers": ["devpulse"],
        "description": "Write operations — project owner only",
    },
}


def _find_caller() -> str:
    """Walk up from CWD to find passport.json and return branch name.

    Returns the branch name, or raises PermissionError if no passport found.
    """
    current = Path.cwd().resolve()
    for _ in range(10):
        passport_path = current / ".trinity" / "passport.json"
        if passport_path.exists():
            try:
                with open(passport_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                name = data.get("branch_info", {}).get("branch_name")
                if not name:
                    name = data.get("identity", {}).get("name")
                if not name:
                    msg = f"Passport at {passport_path} has no branch_name"
                    logger.error(msg)
                    raise PermissionError(msg)
                return name
            except PermissionError:
                raise
            except Exception as exc:
                logger.error("Failed to read passport at %s: %s", passport_path, exc)
                raise PermissionError(f"Failed to read passport at {passport_path}: {exc}") from exc
        parent = current.parent
        if parent == current:
            break
        current = parent

    msg = "No .trinity/passport.json found in directory hierarchy — cannot verify caller"
    logger.error(msg)
    raise PermissionError(msg)


def verify_git_access(command: str) -> str:
    """Check if the calling branch is authorized for this git command.

    Uses GIT_ACCESS_TIERS to determine access level. Global-tier commands
    are available to all branches; owner-tier commands require the caller
    to be in the allowed_callers list.

    Returns:
        The caller's branch name if authorized.

    Raises:
        PermissionError: If the caller is not authorized for this command.
    """
    global_cmds = GIT_ACCESS_TIERS["global"]["commands"]
    owner_tier = GIT_ACCESS_TIERS["owner"]

    if command in global_cmds:
        caller = _find_caller()
        json_handler.log_operation(
            "git_access_verify",
            {"caller": caller, "command": command, "tier": "global"},
        )
        return caller

    if command in owner_tier["commands"]:
        caller = _find_caller()
        allowed = owner_tier["allowed_callers"]
        if caller not in allowed:
            msg = f"Branch '{caller}' is not authorized for '{command}'. Only {allowed} can use owner-tier commands."
            logger.error(msg)
            raise PermissionError(msg)
        json_handler.log_operation(
            "git_access_verify",
            {"caller": caller, "command": command, "tier": "owner"},
        )
        return caller

    raise PermissionError(f"Unknown git command: '{command}'")
