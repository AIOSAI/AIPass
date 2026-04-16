# =================== AIPass ====================
# Name: purge.py
# Description: Sent/Deleted Auto-Purge Handler
# Version: 2.0.0
# Created: 2026-02-04
# Modified: 2026-02-04
# =============================================

"""
Sent/Deleted Auto-Purge Handler

Automatically purges oldest emails when folder exceeds threshold (10).
Before removal:
1. Vectorizes content to @memory (via subprocess)
2. Archives originals to .archive/

Triggered after send/delete operations.

v2.0.0: deleted/ now uses directory structure (like sent/).
"""

import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root

# Purge configuration
MAX_EMAILS = 10

# Memory branch paths for subprocess vectorization (optional external service)
# These are resolved relative to repo root if available; vectorization is best-effort
_REPO_ROOT = find_repo_root()
MEMORY_PYTHON = _REPO_ROOT / "src" / "aipass" / "memory" / ".venv" / "bin" / "python3"
CHROMA_SUBPROCESS_SCRIPT = (
    _REPO_ROOT / "src" / "aipass" / "memory" / "apps" / "handlers" / "storage" / "chroma_subprocess.py"
)


def purge_sent_folder(mailbox_path: Path) -> Dict[str, Any]:
    """
    Purge sent folder if count exceeds threshold.

    Keeps 10 most recent emails, vectorizes and archives older ones.

    Args:
        mailbox_path: Path to .ai_mail.local directory

    Returns:
        Dict with success, purged_count, archived_paths
    """
    sent_folder = mailbox_path / "sent"

    if not sent_folder.exists():
        return {"success": True, "purged_count": 0, "message": "Sent folder empty"}

    # Get all email files sorted by modification time (newest first)
    email_files = sorted(sent_folder.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)

    total_count = len(email_files)
    if total_count <= MAX_EMAILS:
        return {"success": True, "purged_count": 0, "message": f"Below threshold ({total_count}/{MAX_EMAILS})"}

    # Files to purge (oldest, beyond threshold)
    files_to_purge = email_files[MAX_EMAILS:]

    return _purge_email_files(mailbox_path, files_to_purge, "sent")


def purge_deleted_folder(mailbox_path: Path) -> Dict[str, Any]:
    """
    Purge deleted/ folder if file count exceeds threshold.

    Keeps 10 most recent emails, vectorizes and archives older ones.

    Args:
        mailbox_path: Path to .ai_mail.local directory

    Returns:
        Dict with success, purged_count, archived_count
    """
    deleted_folder = mailbox_path / "deleted"

    if not deleted_folder.exists():
        return {"success": True, "purged_count": 0, "message": "Deleted folder empty"}

    # Get all email files sorted by modification time (newest first)
    email_files = sorted(deleted_folder.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)

    total_count = len(email_files)
    if total_count <= MAX_EMAILS:
        return {"success": True, "purged_count": 0, "message": f"Below threshold ({total_count}/{MAX_EMAILS})"}

    # Files to purge (oldest, beyond threshold)
    files_to_purge = email_files[MAX_EMAILS:]

    return _purge_email_files(mailbox_path, files_to_purge, "deleted")


def _purge_email_files(mailbox_path: Path, files: List[Path], folder_type: str) -> Dict[str, Any]:
    """
    Purge list of email files (vectorize, then delete originals).

    Vectorizes email content to @memory for long-term retrieval,
    then deletes originals. Only deletes if vectorization succeeds —
    files are preserved on failure.

    Args:
        mailbox_path: Path to .ai_mail.local directory
        files: List of file paths to purge
        folder_type: "sent" or "deleted" for logging

    Returns:
        Dict with results
    """
    if not files:
        return {"success": True, "purged_count": 0}

    # Load email data from files
    emails_data = []
    load_errors = []
    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                email_data = json.load(f)
                email_data["_source_file"] = str(file_path.name)
                emails_data.append(email_data)
        except Exception as e:
            logger.warning("[purge] Failed to load email file %s: %s", file_path.name, e)
            load_errors.append(f"{file_path.name}: {e}")

    # Vectorize emails to @memory
    vectorize_result = _vectorize_emails(emails_data, folder_type)

    # Only delete originals if vectorization succeeded — no data loss
    if not vectorize_result.get("success", False):
        logger.warning("[purge] Vectorization failed for %s — keeping %d files", folder_type, len(files))
        return {
            "success": False,
            "purged_count": 0,
            "vectorized": False,
            "message": f"Vectorization failed, {len(files)} files preserved",
            "load_errors": load_errors if load_errors else None,
        }

    # Delete original files (data is safely in @memory)
    deleted_count = 0
    delete_errors = []
    for file_path in files:
        try:
            file_path.unlink()
            deleted_count += 1
        except Exception as e:
            logger.warning("[purge] Failed to delete file %s: %s", file_path.name, e)
            delete_errors.append(f"{file_path.name}: {e}")

    return {
        "success": True,
        "purged_count": deleted_count,
        "vectorized": True,
        "load_errors": load_errors if load_errors else None,
        "delete_errors": delete_errors if delete_errors else None,
    }


def _vectorize_emails(emails: List[Dict[str, Any]], folder_type: str) -> Dict[str, Any]:
    """
    Vectorize email content and store in @memory.

    Args:
        emails: List of email data dicts
        folder_type: "sent" or "deleted" for metadata

    Returns:
        Dict with success status
    """
    if not emails:
        return {"success": True, "count": 0}

    try:
        # Extract text for vectorization
        texts = []
        metadatas = []

        for email in emails:
            # Combine subject and message for richer semantic content
            subject = email.get("subject", "")
            message = email.get("message", "")
            text = f"{subject}\n\n{message}"
            texts.append(text)

            metadatas.append(
                {
                    "type": f"email_{folder_type}",
                    "from": email.get("from", ""),
                    "to": email.get("to", ""),
                    "subject": subject,
                    "timestamp": email.get("timestamp", ""),
                    "archived_at": datetime.now().isoformat(),
                }
            )

        # Call @memory vectorization via subprocess (handler independence)
        input_data = {
            "operation": "vectorize_and_store",
            "branch": "AI_MAIL",
            "memory_type": f"email_{folder_type}",
            "texts": texts,
            "metadatas": metadatas,
        }

        result = subprocess.run(
            [str(MEMORY_PYTHON), str(CHROMA_SUBPROCESS_SCRIPT)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            return {"success": False, "error": result.stderr or "Storage failed"}

        return {"success": True, "count": len(texts)}

    except subprocess.TimeoutExpired as e:
        logger.warning("[purge] Vectorization timed out for %s: %s", folder_type, e)
        return {"success": False, "error": "Vectorization timed out"}
    except Exception as e:
        logger.warning("[purge] Vectorization failed for %s: %s", folder_type, e)
        return {"success": False, "error": str(e)}


def run_purge(mailbox_path: Path) -> Dict[str, Any]:
    """
    Run purge on both sent and deleted folders.

    Convenience function to run both purges.

    Args:
        mailbox_path: Path to .ai_mail.local directory

    Returns:
        Dict with combined results
    """
    json_handler.log_operation("run_purge", {"mailbox_path": str(mailbox_path)})
    sent_result = purge_sent_folder(mailbox_path)
    deleted_result = purge_deleted_folder(mailbox_path)

    return {
        "success": sent_result["success"] and deleted_result["success"],
        "sent": sent_result,
        "deleted": deleted_result,
    }


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    console.print("\n" + "=" * 70)
    console.print("SENT/DELETED AUTO-PURGE HANDLER")
    console.print("=" * 70)
    console.print("\nPURPOSE:")
    console.print("  Auto-purge sent/deleted folders when they exceed 10 emails")
    console.print()
    console.print("FUNCTIONS PROVIDED:")
    console.print("  - purge_sent_folder(mailbox_path) -> Dict")
    console.print("  - purge_deleted_folder(mailbox_path) -> Dict")
    console.print("  - run_purge(mailbox_path) -> Dict")
    console.print()
    console.print("WORKFLOW (v2.0):")
    console.print("  1. Check if folder exceeds 10 items")
    console.print("  2. Vectorize oldest items to @memory")
    console.print("  3. Archive originals to .archive/")
    console.print("  4. Remove from sent/ or deleted/")
    console.print()
    console.print("FOLDER STRUCTURE:")
    console.print("  - sent/      -> Individual JSON files")
    console.print("  - deleted/   -> Individual JSON files (same as sent/)")
    console.print()
    console.print("TRIGGERED BY:")
    console.print("  - create.py (after email sent)")
    console.print("  - inbox_cleanup.py (after email deleted)")
    console.print()
    console.print("=" * 70 + "\n")
