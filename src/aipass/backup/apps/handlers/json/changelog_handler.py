# =================== AIPass ====================
# Name: changelog_handler.py
# Description: Backup changelog management
# Version: 1.0.0
# Created: 2025-11-16
# Modified: 2026-03-09
# =============================================

"""
Backup Changelog Handler

Manages persistent changelog of backup operations with notes/comments.
Tracks all backup operations with timestamps and user notes for history tracking.

Functions:
    load_changelog: Load changelog from JSON file
    save_changelog_entry: Add timestamped entry to changelog
    display_previous_comments: Display recent entries to user
"""

# =============================================
# IMPORTS
# =============================================

import datetime
import json
import os
import tempfile
from pathlib import Path
from typing import Dict

from aipass.prax import logger


def _atomic_write(file_path: Path, data: dict) -> None:
    """Write JSON atomically via temp file + rename."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(suffix='.tmp', dir=str(file_path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(file_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError as cleanup_err:
            logger.warning(f"[changelog_handler] Failed to clean temp file: {cleanup_err}")
        raise


# =============================================
# CHANGELOG OPERATIONS
# =============================================

def load_changelog(changelog_file: Path) -> Dict:
    """Load persistent changelog of backup comments.

    Args:
        changelog_file: Path to changelog JSON file

    Returns:
        Dictionary with 'entries' list (empty dict if file missing)
    """
    if changelog_file.exists():
        try:
            with open(changelog_file, 'r', encoding='utf-8', errors='replace') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading changelog: {e}")
    return {"entries": []}


def save_changelog_entry(changelog_file: Path, note: str, mode: str,
                        backup_path: Path) -> bool:
    """Add new entry to persistent changelog.

    Args:
        changelog_file: Path to changelog JSON file
        note: User note describing the backup
        mode: Backup mode ('snapshot' or 'versioned')
        backup_path: Path to backup destination

    Returns:
        True if save succeeded, False otherwise
    """
    try:
        changelog = load_changelog(changelog_file)
        new_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "note": note,
            "mode": mode,
            "backup_path": str(backup_path)
        }
        changelog["entries"].append(new_entry)

        _atomic_write(changelog_file, changelog)
        logger.info(f"[changelog_handler] Saved changelog entry: {note[:50]}")
        return True
    except Exception as e:
        logger.error(f"[changelog_handler] Error saving changelog: {e}")
        return False


def display_previous_comments(changelog_file: Path, mode_name: str):
    """Display previous backup comments with mode identification.

    Args:
        changelog_file: Path to changelog JSON file
        mode_name: Display name of backup mode ('System Snapshot', etc.)
    """
    try:
        changelog = load_changelog(changelog_file)
        entries = changelog.get("entries", [])

        if not entries:
            logger.warning(f"No previous {mode_name} backup comments found.")
            return

        logger.info(f"PREVIOUS {mode_name.upper()} BACKUP COMMENTS")

        # Show last 10 entries (most recent first)
        recent_entries = entries[-10:]
        for i, entry in enumerate(reversed(recent_entries), 1):
            try:
                timestamp = datetime.datetime.fromisoformat(entry["timestamp"])
                formatted_time = timestamp.strftime("%Y-%m-%d %H:%M")
                mode_info = entry.get('mode', 'unknown')
                # Handle encoding issues in notes
                note = str(entry['note']).encode('ascii', errors='replace').decode('ascii')
                logger.info(f"{i:2d}. [{formatted_time}] [{mode_info}] {note}")
            except Exception as e:
                logger.error(f"{i:2d}. [ERROR] Failed to display entry: {e}")

        if len(entries) > 10:
            logger.info(f"... and {len(entries) - 10} older entries")
    except FileNotFoundError:
        logger.warning(f"No previous {mode_name} backup comments found.")
    except PermissionError as e:
        logger.warning(f"Cannot read backup history - permission denied: {e}")
        logger.warning("Continuing with backup...")
    except Exception as e:
        logger.warning(f"Error displaying comments: {e}")
        logger.warning("Continuing with backup...")


# =============================================
# MODULE INITIALIZATION
# =============================================

# No module-level initialization needed
