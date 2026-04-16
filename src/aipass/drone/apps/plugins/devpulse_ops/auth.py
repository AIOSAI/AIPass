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

ALLOWED_CALLERS: list[str] = ["devpulse"]


def verify_caller() -> str:
    """Verify the calling branch is authorized for devpulse operations.

    Walks up from CWD looking for ``.trinity/passport.json``, reads the
    branch name, and checks it against :data:`ALLOWED_CALLERS`.

    Returns:
        The caller's branch name if authorized.

    Raises:
        PermissionError: If the caller is not in the allowed list or no
            passport can be found.
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
                if name not in ALLOWED_CALLERS:
                    msg = f"Branch '{name}' is not authorized for system-pr. Allowed callers: {ALLOWED_CALLERS}"
                    logger.error(msg)
                    raise PermissionError(msg)
                json_handler.log_operation(
                    "devpulse_auth_verify",
                    {"caller": name, "passport": str(passport_path)},
                )
                logger.info("Caller '%s' authorized for devpulse operations", name)
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
