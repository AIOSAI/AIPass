# =================== AIPass ====================
# Name: create.py
# Description: Email File Creation Handler
# Version: 1.4.0
# Created: 2025-11-15
# Modified: 2026-10-17
# =============================================

"""
Email File Creation Handler
"""

import json
import os
import sys
import uuid
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

_append_footer = None


def _get_append_footer():
    """Lazy import append_footer."""
    global _append_footer
    if _append_footer is None:
        from aipass.ai_mail.apps.handlers.email.footer import append_footer

        _append_footer = append_footer
    return _append_footer


from aipass.ai_mail.apps.handlers.dispatch.report import stamp_dispatch_id


def create_email_file(
    to_branch: str,
    subject: str,
    message: str,
    user_info: Dict,
    reply_to: str | None = None,
    dispatched_to: str | None = None,
) -> Path:
    """Create email file and save to sent folder."""
    json_handler.log_operation("create_email_file", {"to": to_branch, "subject": subject})
    timestamp = datetime.now()
    timestamp_str = timestamp.strftime(user_info.get("timestamp_format", "%Y-%m-%d %H:%M:%S"))

    message_with_footer = _get_append_footer()(message)

    # `id` names the SENT record so it can be cited; each delivery mints its own
    # inbox id, since one sent record fans out to many recipients on a broadcast.
    email_data = {
        "id": str(uuid.uuid4())[:8],
        "from": user_info["email_address"],
        "from_name": user_info["display_name"],
        "to": to_branch,
        "subject": subject,
        "message": message_with_footer,
        "timestamp": timestamp_str,
        "status": "sent",
    }

    if reply_to:
        email_data["reply_to"] = reply_to

    if dispatched_to:
        email_data["dispatched_to"] = dispatched_to

    # The dispatch stamp makes the completion report's email list a record, not an mtime guess.
    stamp_dispatch_id(email_data)

    safe_subject = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in subject)
    safe_subject = safe_subject[:50].strip()  # Limit length
    filename = f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{safe_subject}.json"

    mailbox_path = Path(user_info["mailbox_path"])
    sent_folder = mailbox_path / "sent"
    sent_folder.mkdir(parents=True, exist_ok=True)

    email_file = sent_folder / filename
    with open(email_file, "w", encoding="utf-8") as f:
        json.dump(email_data, f, indent=2)

    _trigger_sent_purge(mailbox_path)

    return email_file


def mark_sent_record_refused(email_file: Path, reason: str) -> bool:
    """Restamp a sent record as ``refused`` after delivery was rejected.

    The record is written before delivery, so without this a refused send reads ``status: sent``.
    Restamp, never delete: the attempt is evidence the sender needs to cite.
    """
    try:
        with open(email_file, "r", encoding="utf-8") as f:
            email_data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("[create] mark_sent_record_refused(%s) could not read record: %s", email_file, e)
        return False

    email_data["status"] = "refused"
    email_data["refused_reason"] = reason
    email_data["refused_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with open(email_file, "w", encoding="utf-8") as f:
            json.dump(email_data, f, indent=2)
    except OSError as e:
        logger.warning("[create] mark_sent_record_refused(%s) could not write record: %s", email_file, e)
        return False

    logger.info("[create] sent record %s marked refused: %s", email_file.name, reason)
    return True


def _trigger_sent_purge(mailbox_path: Path) -> None:
    """Trigger auto-purge of sent folder if threshold exceeded."""
    try:
        from aipass.ai_mail.apps.handlers.email.purge import purge_sent_folder

        purge_sent_folder(mailbox_path)
    except Exception as e:
        logger.warning("[create] _trigger_sent_purge() failed: %s", e)


def load_email_file(email_file: Path) -> Optional[Dict]:
    """Load email data from file.

    Returns None if the file cannot be read.
    """
    if not email_file.exists():
        return None

    try:
        with open(email_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("[create] load_email_file(%s) failed: %s", email_file, e)
        return None


if __name__ == "__main__":
    from rich.console import Console

    c = Console()
    c.print("\n" + "=" * 70)
    c.print("EMAIL FILE CREATION HANDLER")
    c.print("=" * 70)
    c.print("\nPURPOSE:")
    c.print("  Creates and stores email files in sent folders")
    c.print()
    c.print("FUNCTIONS PROVIDED:")
    c.print("  - create_email_file(to_branch, subject, message, user_info) -> Path")
    c.print("  - load_email_file(email_file) -> Optional[Dict]")
    c.print("  - mark_sent_record_refused(email_file, reason) -> bool")
    c.print()
    c.print("HANDLER CHARACTERISTICS:")
    c.print("  ✓ Independent - no module dependencies")
    c.print("  ✓ Pure business logic")
    c.print("  ✗ CANNOT import parent modules")
    c.print()
    c.print("USAGE FROM MODULES:")
    c.print("  from ai_mail.apps.handlers.email.create import create_email_file")
    c.print("  from ai_mail.apps.handlers.email.create import load_email_file")
    c.print()
    c.print("=" * 70 + "\n")
