# =================== AIPass ====================
# Name: read.py
# Description: Registry Read Handler
# Version: 1.0.0
# Created: 2025-11-15
# Modified: 2025-11-15
# =============================================

"""
Registry Read Handler

Handles reading branch registry data including:
- Reading all branches from AIPASS_REGISTRY.json
- Deriving email addresses from branch names
- Mapping email addresses to branch paths

Handler Independence:
- No module imports from ai_mail
- Only uses Prax logger and standard library
- Fully transportable and self-contained
"""

import json
from pathlib import Path
from typing import List, Dict, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root


# Constants
MODULE_NAME = "registry.read"

BRANCH_REGISTRY_PATH = find_repo_root() / "AIPASS_REGISTRY.json"


def get_all_branches() -> List[Dict]:
    """
    Get list of all branches for email routing and selection.
    Reads from AIPass branch registry (AIPASS_REGISTRY.json at repo root).

    Handles both list and dict formats for branches in the registry.
    Uses explicit email field from registry when present, falls back
    to derivation from branch name.

    Returns:
        List of dicts with branch info:
        [{"name": "AIPASS.admin", "path": "/", "email": "@admin"}, ...]

    Note:
        Returns empty list if registry not found or on error.
    """
    json_handler.log_operation("get_all_branches", {"registry_path": str(BRANCH_REGISTRY_PATH)})

    branches = []

    if not BRANCH_REGISTRY_PATH.exists():
        return []

    try:
        with open(BRANCH_REGISTRY_PATH, "r", encoding="utf-8") as f:
            registry_data = json.load(f)

        # Handle both formats: list of dicts or dict keyed by name
        raw_branches = registry_data.get("branches", [])
        if isinstance(raw_branches, dict):
            raw_branches = list(raw_branches.values())

        for branch in raw_branches:
            branch_name = branch.get("name", "")
            path = branch.get("path", "")

            if not branch_name or not path:
                continue

            # Use explicit email from registry if present (preferred)
            # Fall back to derivation only if email field is missing
            explicit_email = branch.get("email", "")
            if explicit_email:
                email = explicit_email
            else:
                email = _derive_email_from_branch_name(branch_name)

            branches.append({"name": branch_name, "path": path, "email": email})

        return branches

    except Exception as e:
        logger.warning("[registry] get_all_branches failed: %s", e)
        return []


def _derive_email_from_branch_name(branch_name: str) -> str:
    """
    Derive email address from branch name.

    Rules:
    - AIPASS.admin -> @admin (take part after dot)
    - AIPASS Workshop -> @aipass (take first word)
    - AIPASS-HELP -> @help (take second part to avoid collision)
    - BACKUP -> @backup (take whole name)
    - DRONE -> @drone (take whole name)

    Args:
        branch_name: Branch name from registry

    Returns:
        Email address in format "@email"
    """
    if "." in branch_name:
        # Special case: AIPASS.admin -> admin
        email_part = branch_name.split(".")[-1].lower()
    elif " " in branch_name:
        # Handle spaces: take first word
        email_part = branch_name.split()[0].lower()
    elif "-" in branch_name and branch_name.split("-")[0] == "AIPASS":
        # AIPASS-prefixed branches: use second part to avoid collision
        email_part = branch_name.split("-", 1)[1].lower()
    else:
        # Take first word before hyphen or whole name
        email_part = branch_name.split("-")[0].lower()

    return f"@{email_part}"


def get_branch_by_email(email: str) -> Optional[Dict]:
    """
    Get branch information by email address.

    Args:
        email: Email address (e.g., "@admin")

    Returns:
        Branch dict with name, path, email or None if not found
    """
    branches = get_all_branches()

    for branch in branches:
        if branch["email"] == email:
            return branch

    return None


def get_caller_project_branches(caller_cwd: str) -> Dict[str, str]:
    """Load branch email→path mappings from the caller's project registry.

    Walks up from caller_cwd to find a *_REGISTRY.json file (e.g.
    VERA_REGISTRY.json), then extracts branch email→path mappings.
    Used for cross-project dispatch when the target branch is not in
    the AIPass registry.

    Args:
        caller_cwd: Working directory of the calling project (typically
                    from AIPASS_CALLER_CWD env var).

    Returns:
        Dict mapping email address to absolute path string.
        Empty dict if no registry found or on error.
    """
    current = Path(caller_cwd).resolve()
    for _ in range(10):
        for reg_file in current.glob("*_REGISTRY.json"):
            try:
                with open(reg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                result: Dict[str, str] = {}
                branches = data.get("branches", [])
                if isinstance(branches, list):
                    for b in branches:
                        email = b.get("email", f"@{b.get('name', '').lower()}")
                        path = b.get("path", "")
                        if path and not Path(path).is_absolute():
                            path = str((reg_file.parent / path).resolve())
                        if email and path:
                            result[email] = path
                elif isinstance(branches, dict):
                    for name, info in branches.items():
                        email = info.get("email", f"@{name}")
                        path = info.get("path", "")
                        if path and not Path(path).is_absolute():
                            path = str((reg_file.parent / path).resolve())
                        if email and path:
                            result[email] = path
                if result:
                    return result
            except Exception as exc:
                logger.warning("[registry] get_caller_project_branches: failed reading %s: %s", reg_file, exc)
        parent = current.parent
        if parent == current:
            break
        current = parent
    return {}


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    console.print("\n" + "=" * 70)
    console.print("AI_MAIL HANDLER: registry/read.py")
    console.print("=" * 70)
    console.print("\nRegistry Read Handler")
    console.print()
    console.print("FUNCTIONS PROVIDED:")
    console.print("  - get_all_branches() -> List[Dict]")
    console.print("  - get_branch_by_email(email) -> Optional[Dict]")
    console.print()
    console.print("TESTING:")

    branches = get_all_branches()
    console.print(f"\nLoaded {len(branches)} branches:")
    for branch in branches[:5]:  # Show first 5
        console.print(f"  {branch['email']:15} -> {branch['name']}")

    if len(branches) > 5:
        console.print(f"  ... and {len(branches) - 5} more")

    console.print("\n" + "=" * 70 + "\n")
