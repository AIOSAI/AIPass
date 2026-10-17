# =================== AIPass ====================
# Name: contacts.py
# Description: Contacts address book — maps branch names to inbox paths
# Version: 1.1.0
# Created: 2026-04-11
# Modified: 2026-10-17
# =============================================

"""
Contacts Address Book Handler

Resolves callers from external projects where CWD-walking cannot identify them.
"""

import os
import sys
from datetime import datetime
from typing import Dict, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

CONTACTS_FILE = find_repo_root() / "src/aipass/ai_mail/.ai_mail.local/contacts.json"


def _load_contacts() -> Dict:
    """Load contacts.json from disk.

    Only a missing file reads as empty; an unreadable book raises RuntimeError, since
    read as empty it lets the identity chain synthesize a citizen where a fault stands.
    """
    import json

    try:
        with open(CONTACTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.debug("[contacts] no book at %s: no contacts", CONTACTS_FILE)
        return {"contacts": {}}
    except (OSError, ValueError) as e:
        logger.error("[contacts] _load_contacts() could not read %s: %s", CONTACTS_FILE, e)
        raise RuntimeError(f"{CONTACTS_FILE} could not be read: {e}") from e
    if not isinstance(data, dict) or "contacts" not in data:
        return {"contacts": {}}
    return data


def _save_contacts(data: Dict) -> bool:
    """Save contacts dict to contacts.json."""
    try:
        import json

        CONTACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.warning("[contacts] _save_contacts() failed: %s", e)
        return False


def get_contact(branch_name: str) -> Optional[Dict]:
    """Look up a contact by branch name."""
    json_handler.log_operation("contacts_get", {"branch": branch_name})
    name_key = branch_name.lstrip("@").lower()
    data = _load_contacts()
    return data["contacts"].get(name_key)


def register_contact(branch_name: str, project: str, inbox_path: str) -> bool:
    """Add or update a contact in the contacts address book.

    An unreadable book returns False untouched: a write over it would replace every row.
    """
    json_handler.log_operation("contacts_register", {"branch": branch_name, "inbox": inbox_path})
    name_key = branch_name.lstrip("@").lower()
    try:
        data = _load_contacts()
    except RuntimeError as e:
        logger.error("[contacts] register_contact(%s) refused, book left as found: %s", name_key, e)
        return False
    data["contacts"][name_key] = {
        "project": project,
        "inbox": inbox_path,
        "last_seen": datetime.now().isoformat(),
    }
    return _save_contacts(data)


def all_contacts() -> Dict:
    """Return all contacts as a dict keyed by branch name."""
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
