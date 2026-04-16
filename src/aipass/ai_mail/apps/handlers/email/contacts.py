# =================== AIPass ====================
# Name: contacts.py
# Description: Contacts address book — maps branch names to inbox paths
# Version: 1.0.0
# Created: 2026-04-11
# Modified: 2026-04-11
# =============================================

"""
Contacts Address Book Handler

Maps branch names to their inbox paths for fast sender/recipient resolution.
Solves the BRANCH DETECTION FAILED problem when external projects call drone
— contacts lookup works even when CWD-walking cannot identify the caller.
"""

from datetime import datetime
from typing import Dict, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root

CONTACTS_FILE = find_repo_root() / "src/aipass/ai_mail/.ai_mail.local/contacts.json"


# =============================================
# INTERNAL HELPERS
# =============================================


def _load_contacts() -> Dict:
    """Load contacts.json from disk with fallback to empty structure.

    Returns:
        Dict with 'contacts' key mapping branch names to contact info.
    """
    if not CONTACTS_FILE.exists():
        return {"contacts": {}}
    try:
        import json

        with open(CONTACTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "contacts" not in data:
            return {"contacts": {}}
        return data
    except Exception as e:
        logger.warning("[contacts] _load_contacts() failed: %s", e)
        return {"contacts": {}}


def _save_contacts(data: Dict) -> bool:
    """Save contacts dict to contacts.json.

    Args:
        data: Full contacts data dict to save.

    Returns:
        True on success, False on error.
    """
    try:
        import json

        CONTACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.warning("[contacts] _save_contacts() failed: %s", e)
        return False


# =============================================
# PUBLIC API
# =============================================


def get_contact(branch_name: str) -> Optional[Dict]:
    """Look up a contact by branch name.

    Args:
        branch_name: Branch name or email (e.g., 'devpulse' or '@devpulse').

    Returns:
        Contact dict with 'project', 'inbox', 'last_seen' keys, or None if not found.
    """
    json_handler.log_operation("contacts_get", {"branch": branch_name})
    name_key = branch_name.lstrip("@").lower()
    data = _load_contacts()
    return data["contacts"].get(name_key)


def register_contact(branch_name: str, project: str, inbox_path: str) -> bool:
    """Add or update a contact in the contacts address book.

    Args:
        branch_name: Branch name or email (leading @ stripped, lowercased).
        project: Project name (e.g., 'AIPass', 'VeraStudio').
        inbox_path: Absolute path to the branch's inbox.json file.

    Returns:
        True on success, False on error.
    """
    json_handler.log_operation("contacts_register", {"branch": branch_name, "inbox": inbox_path})
    name_key = branch_name.lstrip("@").lower()
    data = _load_contacts()
    data["contacts"][name_key] = {
        "project": project,
        "inbox": inbox_path,
        "last_seen": datetime.now().isoformat(),
    }
    return _save_contacts(data)


def all_contacts() -> Dict:
    """Return all contacts as a dict keyed by branch name.

    Returns:
        Dict mapping branch names to contact info dicts.
    """
    json_handler.log_operation("contacts_list")
    data = _load_contacts()
    return data["contacts"]


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    console.print("\n" + "=" * 70)
    console.print("CONTACTS ADDRESS BOOK HANDLER")
    console.print("=" * 70)
    console.print(f"\nContacts file: {CONTACTS_FILE}")
    contacts = all_contacts()
    if contacts:
        console.print(f"\n{len(contacts)} registered contact(s):")
        for name, info in sorted(contacts.items()):
            console.print(f"  @{name} -> {info.get('inbox', '?')} ({info.get('project', '')})")
    else:
        console.print("\nNo contacts registered yet.")
    console.print("\nFunctions provided:")
    console.print("  - get_contact(branch_name) -> Optional[Dict]")
    console.print("  - register_contact(branch_name, project, inbox_path) -> bool")
    console.print("  - all_contacts() -> Dict")
    console.print()
