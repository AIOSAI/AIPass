# =================== AIPass ====================
# Name: user.py
# Description: User Info Handler
# Version: 2.3.0
# Created: 2025-11-30
# Modified: 2026-10-17
# =============================================

"""
User Info Handler

Fails hard if sender detection fails; fallbacks hide bugs.
"""

import os
from pathlib import Path
from typing import Dict, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler

from .branch_detection import detect_branch_from_pwd, find_branch_root


def _detection_failure_reason() -> str:
    """Explain WHY sender detection failed, naming the path actually walked.

    Sender identity comes from drone's AIPASS_CALLER_* env vars, never this process's cwd (always the target branch).
    """
    caller_branch = os.environ.get("AIPASS_CALLER_BRANCH")
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD")

    # Checked before the CALLER_BRANCH claim: a caller outside any branch is the real reason, not an unset CWD.
    if caller_cwd and not find_branch_root(Path(caller_cwd)):
        return (
            f"AIPASS_CALLER_CWD={caller_cwd} is not inside a branch — no "
            ".trinity/passport.json at or above it. The caller invoked drone from "
            "outside any branch directory (e.g. the repo root); re-run from within "
            "the sending branch."
        )

    if caller_branch:
        return (
            f"AIPASS_CALLER_BRANCH={caller_branch!r} is not a known sender: no matching "
            "contact, no entry in the AIPass or caller registry, and AIPASS_CALLER_CWD "
            "is unset so no external identity could be synthesized."
        )
    if caller_cwd:
        # Here the cwd does sit in a branch; only the registry claim is missing.
        return (
            f"AIPASS_CALLER_CWD={caller_cwd} sits inside a branch, but no registry "
            "entry matches that path — the branch is not registered under this "
            "project's AIPASS_REGISTRY.json or the caller project's *_REGISTRY.json."
        )
    return (
        "No AIPASS_CALLER_BRANCH or AIPASS_CALLER_CWD was set, and no "
        ".trinity/passport.json was found at or above the working directory."
    )


def get_current_user() -> Dict:
    """Get current user's information from branch detection (AIPASS_REGISTRY.json)"""
    json_handler.log_operation("get_current_user", {"cwd": str(Path.cwd())})

    # Detect branch from PWD
    branch_info = detect_branch_from_pwd()

    if not branch_info:
        raise RuntimeError(
            "BRANCH DETECTION FAILED: Could not resolve the sending branch.\n"
            f"{_detection_failure_reason()}\n"
            f"(This process's working directory is {Path.cwd()} — informational only, "
            "sender identity is NOT resolved from it.)\n"
            "No fallback configured - this is intentional to catch bugs."
        )

    from .branch_detection import BRANCH_REGISTRY_PATH

    _repo_root = BRANCH_REGISTRY_PATH.parent

    branch_name = branch_info.get("name")
    path_str = branch_info.get("path")
    branch_path = Path(path_str) if path_str else None
    if branch_path and not branch_path.is_absolute():
        branch_path = (_repo_root / branch_path).resolve()
    email = branch_info.get("email")

    if not all([branch_name, branch_path, email]):
        raise RuntimeError(
            f"INVALID BRANCH INFO: Branch registry entry incomplete.\n"
            f"Branch: {branch_name}\n"
            f"Path: {branch_path}\n"
            f"Email: {email}\n"
            "Check AIPASS_REGISTRY.json for missing fields."
        )

    assert branch_path is not None
    mailbox_path = branch_path / ".ai_mail.local"

    return {
        "email_address": email,
        "display_name": branch_name,
        "mailbox_path": str(mailbox_path),
        "timestamp_format": "%Y-%m-%d %H:%M:%S",
    }


def get_user_by_email(email: str) -> Optional[Dict]:
    """Get user information by email address from AIPASS_REGISTRY.json

    None when unknown or no registry exists; raises RegistryUnreadable when the registry exists but cannot be read.
    """
    from .branch_detection import BRANCH_REGISTRY_PATH, _get_branches_list

    registry_path = BRANCH_REGISTRY_PATH
    if not registry_path.exists():
        return None

    try:
        import json

        _repo_root = registry_path.parent

        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)

        for branch in _get_branches_list(registry):
            if branch.get("email") == email:
                branch_path = Path(branch.get("path", ""))
                if branch_path and not branch_path.is_absolute():
                    branch_path = (_repo_root / branch_path).resolve()
                return {
                    "email_address": branch.get("email"),
                    "display_name": branch.get("name"),
                    "mailbox_path": str(branch_path / ".ai_mail.local"),
                    "timestamp_format": "%Y-%m-%d %H:%M:%S",
                }
        return None
    except (OSError, ValueError) as e:
        logger.error("[identity] get_user_by_email(%s) could not read %s: %s", email, registry_path, e)
        from aipass.ai_mail.apps.handlers.registry.read import RegistryUnreadable

        raise RegistryUnreadable(f"{registry_path} could not be read: {e}") from e


def get_all_users() -> Dict[str, Dict]:
    """Get all users from AIPASS_REGISTRY.json"""
    from .branch_detection import BRANCH_REGISTRY_PATH, _get_branches_list

    registry_path = BRANCH_REGISTRY_PATH
    if not registry_path.exists():
        return {}

    try:
        import json

        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)

        _repo_root = registry_path.parent
        users = {}
        for branch in _get_branches_list(registry):
            email = branch.get("email", "")
            if email:
                branch_path = Path(branch.get("path", ""))
                if branch_path and not branch_path.is_absolute():
                    branch_path = (_repo_root / branch_path).resolve()
                users[email] = {
                    "email_address": email,
                    "display_name": branch.get("name"),
                    "mailbox_path": str(branch_path / ".ai_mail.local"),
                    "timestamp_format": "%Y-%m-%d %H:%M:%S",
                }
        return users
    except Exception as e:
        logger.warning("[identity] get_all_users() failed: %s", e)
        from aipass.ai_mail.apps.handlers.registry.read import RegistryUnreadable

        raise RegistryUnreadable(f"{registry_path} could not be read: {e}") from e
