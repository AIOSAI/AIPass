# =================== AIPass ====================
# Name: identity.py
# Description: Per-branch self-declaration identity files
# Version: 1.0.0
# Created: 2026-04-11
# Modified: 2026-04-11
# =============================================

"""
Per-Branch Identity Handler

Manages identity.json files in each branch's .ai_mail.local/ directory.
These files allow branches to self-declare their name, project, and inbox
path — enabling fast sender resolution without CWD-walking.
"""

import json
from pathlib import Path
from typing import Dict, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler


# =============================================
# PUBLIC API
# =============================================


def create_identity(branch_path: Path, branch_name: str, project: str) -> bool:
    """Write identity.json to branch_path/.ai_mail.local/.

    Args:
        branch_path: Root directory of the branch.
        branch_name: Branch name (e.g., 'devpulse').
        project: Project name (e.g., 'AIPass').

    Returns:
        True on success, False on error.
    """
    json_handler.log_operation("identity_create", {"branch": branch_name, "project": project})
    try:
        mail_dir = branch_path / ".ai_mail.local"
        mail_dir.mkdir(parents=True, exist_ok=True)
        inbox_path = mail_dir / "inbox.json"
        identity_data = {
            "branch": branch_name.lower(),
            "project": project,
            "inbox": str(inbox_path),
        }
        identity_file = mail_dir / "identity.json"
        with open(identity_file, "w", encoding="utf-8") as f:
            json.dump(identity_data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.warning("[identity] create_identity(%s) failed: %s", branch_name, e)
        return False


def read_identity(branch_path: Path) -> Optional[Dict]:
    """Read identity.json from branch_path/.ai_mail.local/.

    Args:
        branch_path: Root directory of the branch.

    Returns:
        Identity dict with 'branch', 'project', 'inbox' keys,
        or None if not found or on error.
    """
    json_handler.log_operation("identity_read", {"path": str(branch_path)})
    identity_file = branch_path / ".ai_mail.local" / "identity.json"
    if not identity_file.exists():
        return None
    try:
        with open(identity_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("[identity] read_identity(%s) failed: %s", branch_path, e)
        return None


def bootstrap_aipass_identities() -> int:
    """Create identity.json for all branches registered in the AIPass registry.

    Uses lazy imports to avoid circular dependencies.

    Returns:
        Number of identity.json files successfully created.
    """
    json_handler.log_operation("identity_bootstrap")
    from aipass.ai_mail.apps.handlers.registry.read import get_all_branches
    from aipass.ai_mail.apps.handlers.paths import find_repo_root

    repo_root = find_repo_root()
    branches = get_all_branches()
    count = 0
    for branch in branches:
        path_str = branch.get("path", "")
        if not path_str:
            continue
        branch_path = Path(path_str)
        if not branch_path.is_absolute():
            branch_path = (repo_root / branch_path).resolve()
        name = branch.get("email", "").lstrip("@") or branch.get("name", "").lower()
        if not name:
            continue
        if create_identity(branch_path, name, "AIPass"):
            count += 1
    return count


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    console.print("\n" + "=" * 70)
    console.print("PER-BRANCH IDENTITY HANDLER")
    console.print("=" * 70)
    console.print("\nFunctions provided:")
    console.print("  - create_identity(branch_path, branch_name, project) -> bool")
    console.print("  - read_identity(branch_path) -> Optional[Dict]")
    console.print("  - bootstrap_aipass_identities() -> int")
    console.print()
