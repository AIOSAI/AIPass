# =================== AIPass ====================
# Name: user.py
# Description: User Info Handler
# Version: 2.0.0
# Created: 2025-11-30
# Modified: 2025-11-30
# =============================================

"""
User Info Handler

Handles user information retrieval and management for AI_Mail system.
Uses branch detection to identify sender - NO FALLBACKS.

PHILOSOPHY: Fail hard if detection fails. Fallbacks hide bugs.
"""

# =============================================
# IMPORTS
# =============================================
from pathlib import Path
from typing import Dict

from aipass.prax.apps.modules.logger import system_logger as logger

# Import branch detection functions
from .branch_detection import detect_branch_from_pwd

# =============================================
# USER INFO FUNCTIONS
# =============================================

def get_current_user() -> Dict:
    """
    Get current user's information from branch detection (BRANCH_REGISTRY.json)

    Uses PWD/CWD to detect which branch is calling, then looks up info
    in BRANCH_REGISTRY.json. NO FALLBACKS - fails hard if detection fails.

    Returns:
        Dict containing user information:
        {
            "email_address": "@branch",
            "display_name": "BRANCH_NAME",
            "mailbox_path": "/path/to/branch/.ai_mail.local",
            "timestamp_format": "%Y-%m-%d %H:%M:%S"
        }

    Raises:
        RuntimeError: If branch detection fails (not called from a branch directory)
    """
    # Detect branch from PWD
    branch_info = detect_branch_from_pwd()

    if not branch_info:
        raise RuntimeError(
            "BRANCH DETECTION FAILED: Could not detect branch from current directory.\n"
            "AI_MAIL must be called from within a branch directory (with .trinity/passport.json).\n"
            f"Current directory: {Path.cwd()}\n"
            "No fallback configured - this is intentional to catch bugs."
        )

    # Extract info from branch_info (from BRANCH_REGISTRY.json)
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
            "Check BRANCH_REGISTRY.json for missing fields."
        )

    # Construct mailbox path (branch_path guaranteed non-None by check above)
    assert branch_path is not None
    mailbox_path = branch_path / ".ai_mail.local"

    # Return user info in expected format
    return {
        "email_address": email,
        "display_name": branch_name,
        "mailbox_path": str(mailbox_path),
        "timestamp_format": "%Y-%m-%d %H:%M:%S"
    }


def get_user_by_email(email: str) -> Dict | None:
    """
    Get user information by email address from BRANCH_REGISTRY.json

    Args:
        email: Email address (e.g., "@seed")

    Returns:
        Dict containing user info, or None if not found
    """
    from .branch_detection import BRANCH_REGISTRY_PATH, _get_branches_list

    # Use registry lookup
    registry_path = BRANCH_REGISTRY_PATH
    if not registry_path.exists():
        return None

    try:
        import json
        with open(registry_path, 'r', encoding='utf-8') as f:
            registry = json.load(f)

        for branch in _get_branches_list(registry):
            if branch.get("email") == email:
                branch_path = Path(branch.get("path", ""))
                return {
                    "email_address": branch.get("email"),
                    "display_name": branch.get("name"),
                    "mailbox_path": str(branch_path / ".ai_mail.local"),
                    "timestamp_format": "%Y-%m-%d %H:%M:%S"
                }
        return None
    except Exception as e:
        logger.warning("[identity] get_user_by_email(%s) failed: %s", email, e)
        return None


def get_all_users() -> Dict[str, Dict]:
    """
    Get all users from BRANCH_REGISTRY.json

    Returns:
        Dict mapping branch emails to user info dicts
    """
    from .branch_detection import BRANCH_REGISTRY_PATH, _get_branches_list
    registry_path = BRANCH_REGISTRY_PATH
    if not registry_path.exists():
        return {}

    try:
        import json
        with open(registry_path, 'r', encoding='utf-8') as f:
            registry = json.load(f)

        users = {}
        for branch in _get_branches_list(registry):
            email = branch.get("email", "")
            if email:
                branch_path = Path(branch.get("path", ""))
                users[email] = {
                    "email_address": email,
                    "display_name": branch.get("name"),
                    "mailbox_path": str(branch_path / ".ai_mail.local"),
                    "timestamp_format": "%Y-%m-%d %H:%M:%S"
                }
        return users
    except Exception as e:
        logger.warning("[identity] get_all_users() failed: %s", e)
        return {}
