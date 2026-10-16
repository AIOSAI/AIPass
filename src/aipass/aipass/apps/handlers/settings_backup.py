# =================== AIPass ====================
# Name: settings_backup.py
# Description: Back up the provider settings file and leave a receipt before every write
# Version: 1.0.0
# Created: 2026-10-15
# Modified: 2026-10-15
# =============================================

"""settings_backup — a backup and a receipt before every write to ~/.claude/settings.json.

The owner's ruling, 2026-10-15 (FPLAN-0645): his personal Claude settings file never
changes without a copy of what it was and a record of who changed it. Every Python
door that writes it calls ``backup_before_write`` first and ``write_receipt`` after.

The folder is ``<settings dir>/.backup/settings/`` and its shape is a contract shared
with @hooks, whose tool-door handler writes the same folder without importing this
module: one history, whichever door fired.

 - Backup name ``<filename>.<YYYY-MM-DDTHH-MM-SS>.<door>``, local time; a second
   backup in the same second gets ``-2``, ``-3``, … An existing backup is never
   overwritten, and nothing here prunes: they stack.
 - ``receipts.jsonl`` beside them, append-only, one JSON object per write.
 - The gate: a backup or a receipt that fails raises ``SettingsBackupError``.
   ``backup_before_write`` also opens the receipt file for append before it returns,
   so a receipt that cannot be written stops the door BEFORE the settings write.

This module hashes the settings file's bytes and copies it; it never parses it and
never writes it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from aipass.prax import logger
from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.shared.registry_discovery import find_registry

DOOR_DOCTOR_FIX = "doctor-fix"
DOOR_INSTALL = "install"
DOOR_SETUP_SH = "setup-sh"
DOOR_RECONCILE_STALE_DENY = "reconcile-stale-deny"

RECEIPTS_NAME = "receipts.jsonl"

_DIR_MODE = 0o700
_FILE_MODE = 0o600
_STAMP_FORMAT = "%Y-%m-%dT%H-%M-%S"


class SettingsBackupError(Exception):
    """A backup or receipt could not be written; the settings write must not happen."""


@dataclass(frozen=True)
class BackupRecord:
    """What ``backup_before_write`` took, handed on to ``write_receipt``."""

    file: Path
    door: str
    actor: str
    pid: int
    backup: Optional[Path]  # None when no settings file existed yet
    before_sha256: Optional[str]
    time: str  # local ISO-8601 with offset, seconds


def backup_dir(settings_path: Path) -> Path:
    """The backup folder for a settings file: ``<its dir>/.backup/settings``."""
    return settings_path.parent / ".backup" / "settings"


def sha256_of(path: Path) -> str:
    """The sha256 hex digest of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seat_actor(cwd: Path) -> str:
    """The AIPass branch of *cwd* when it sits under an AIPass home, else the cwd path.

    The home is the directory holding the registry ``find_registry`` reaches from
    *cwd*; the branch is the nearest ``.trinity/passport.json`` between *cwd* and that
    home. A cwd at the home itself, or outside any home, is named by its path.
    """
    registry = find_registry(cwd)
    if registry is None:
        return str(cwd)
    home = registry.resolve().parent
    current = cwd.resolve()
    if current != home and home not in current.parents:
        return str(cwd)
    while current != home:
        passport_path = current / ".trinity" / "passport.json"
        if passport_path.is_file():
            passport = json_handler.read_json(passport_path) or {}
            name = passport.get("branch_info", {}).get("branch_name")
            if name:
                return str(name)
        current = current.parent
    return str(cwd)


def _ensure_folder(folder: Path) -> None:
    """Create the backup folder 0700 on first use; leave an existing one as it is."""
    if folder.is_dir():
        return
    folder.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        folder.chmod(_DIR_MODE)


def _reserve_backup_name(folder: Path, base: str) -> Path:
    """Claim the first free ``base``, ``base-2``, ``base-3``… with an exclusive create.

    O_EXCL makes the claim atomic, so two doors firing in the same second can never
    pick the same name and overwrite each other.
    """
    suffix = 1
    while True:
        candidate = folder / (base if suffix == 1 else f"{base}-{suffix}")
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
        except FileExistsError:
            logger.info("[settings_backup] %s taken this second — trying the next suffix", candidate.name)
            suffix += 1
            continue
        os.close(fd)
        return candidate


def backup_before_write(settings_path: Path, door: str, actor: Optional[str] = None) -> BackupRecord:
    """Copy *settings_path* into the backup folder before a door writes it.

    Call it immediately before the write. No file yet (a first install) takes no
    copy; the record says so and the receipt carries ``"backup": null``. The receipt
    file is opened for append here too, so an unwritable receipt fails now, while the
    settings file is still untouched.

    Args:
        settings_path: The settings file about to be written.
        door: Which door is writing (``DOOR_*``).
        actor: Who is writing; default the AIPass branch of the cwd, else the cwd path.

    Raises:
        SettingsBackupError: naming the path and the OS error; the caller must not write.
    """
    now = datetime.now().astimezone()
    folder = backup_dir(settings_path)
    backup: Optional[Path] = None
    before_sha256: Optional[str] = None
    target = folder
    try:
        _ensure_folder(folder)
        target = folder / RECEIPTS_NAME
        with target.open("a", encoding="utf-8"):
            pass
        if settings_path.exists():
            target = folder / f"{settings_path.name}.{now.strftime(_STAMP_FORMAT)}.{door}"
            backup = _reserve_backup_name(folder, target.name)
            target = backup
            shutil.copy2(settings_path, backup)
            if os.name != "nt":
                backup.chmod(_FILE_MODE)
            before_sha256 = sha256_of(backup)
    except OSError as exc:
        logger.error("[settings_backup] backup failed at %s: %s", target, exc)
        raise SettingsBackupError(f"settings backup failed at {target}: {exc}") from exc

    record = BackupRecord(
        file=settings_path,
        door=door,
        actor=actor if actor is not None else _seat_actor(Path.cwd()),
        pid=os.getpid(),
        backup=backup,
        before_sha256=before_sha256,
        time=now.isoformat(timespec="seconds"),
    )
    json_handler.log_operation(
        "settings_backup", {"door": door, "backup": backup.name if backup else None, "actor": record.actor}
    )
    return record


def write_receipt(record: BackupRecord, after_sha256: Optional[str], summary: List[str]) -> Path:
    """Append one receipt line for a write the record's door has just made.

    Returns the receipt file's path. Raises ``SettingsBackupError`` naming the path
    and the OS error when the line cannot be appended.
    """
    entry = {
        "time": record.time,
        "door": record.door,
        "file": record.file.name,
        "actor": record.actor,
        "pid": record.pid,
        "backup": record.backup.name if record.backup else None,
        "before_sha256": record.before_sha256,
        "after_sha256": after_sha256,
        "summary": list(summary),
    }
    if record.backup is None:
        entry["note"] = "no file existed"
    receipts = backup_dir(record.file) / RECEIPTS_NAME
    try:
        with receipts.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.error("[settings_backup] receipt failed at %s: %s", receipts, exc)
        raise SettingsBackupError(f"settings receipt failed at {receipts}: {exc}") from exc
    json_handler.log_operation("settings_receipt", {"door": record.door, "receipt": str(receipts)})
    return receipts
