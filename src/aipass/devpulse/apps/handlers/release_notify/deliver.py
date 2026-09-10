# =================== AIPass ====================
# Name: deliver.py
# Description: Delivery — one drone call per manager, one commons thread, one stamp
# Version: 1.0.0
# Created: 2026-09-09
# Modified: 2026-09-09
# =============================================

"""Delivery and the per-version stamp (DPLAN-0335 leg 1).

Every send is ``subprocess.run`` with a LIST of arguments and no shell, from
the devpulse branch directory — drone resolves the caller's identity from the
cwd's passport, so the cwd is the sender. A list means the subject and body
are arguments, not a command line: nothing in a CHANGELOG line can become a
shell token.

One recipient's failure is that recipient's failure. The loop keeps going and
the caller is handed both lists, because a mail lane that stops at the first
refusal tells five managers nothing and reports one problem.
"""

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from aipass.prax import logger
from aipass.devpulse.apps.handlers.json import json_handler
from aipass.devpulse.apps.handlers.release_notify.managers import devpulse_root

MODULE_NAME = "release_notify"

# Branch-local runtime state, beside .watchdog/ and .feedback.local/ — the
# branch's other module state directories. Named in DPLAN-0335 leg 1.
STATE_DIRNAME = ".devpulse"
STATE_FILENAME = "release_notify.json"

# r/announcements exists for exactly this ("System-wide announcements and
# updates"); general is the discussion room.
COMMONS_ROOM = "announcements"
COMMONS_TYPE = "announcement"

SEND_TIMEOUT_SECONDS = 120


def state_path() -> Path:
    """Where the per-version stamp lives.

    Returns:
        Path to .devpulse/release_notify.json inside this branch.
    """
    return devpulse_root() / STATE_DIRNAME / STATE_FILENAME


def load_state() -> dict:
    """Read the stamp file.

    An unreadable file is reported and treated as empty rather than taken as
    "already sent": the safe direction for a corrupt stamp is a duplicate
    mail, never a release nobody hears about. The ``unreadable`` flag lets the
    caller say so out loud.

    Returns:
        dict with ``versions`` and, when the file could not be parsed, ``unreadable``.
    """
    path = state_path()
    if not path.exists():
        return {"versions": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.error(f"[{MODULE_NAME}] stamp file unreadable at {path}: {exc!r} — treating as empty")
        return {"versions": {}, "unreadable": True}
    if not isinstance(data, dict) or not isinstance(data.get("versions"), dict):
        logger.error(f"[{MODULE_NAME}] stamp file at {path} has the wrong shape — treating as empty")
        return {"versions": {}, "unreadable": True}
    return data


def already_notified(state: dict, version: str) -> dict | None:
    """The record of an earlier run for this version, if there is one.

    Args:
        state: The loaded stamp file.
        version: The bare version being announced.

    Returns:
        The stored record, or None when this version has not been sent.
    """
    record = state.get("versions", {}).get(version)
    return record if isinstance(record, dict) else None


def record_notified(version: str, recipients: list[str], failed: list[str], commons: str) -> Path:
    """Stamp this version as sent.

    Args:
        version: The bare version announced.
        recipients: Addresses that accepted the mail.
        failed: Addresses whose send failed.
        commons: Outcome of the commons post ("posted" or the failure reason).

    Returns:
        The stamp file's path.
    """
    state = load_state()
    state.pop("unreadable", None)
    versions = state.setdefault("versions", {})
    versions[version] = {
        "sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "recipients": recipients,
        "failed": failed,
        "commons": commons,
    }

    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    json_handler.log_operation(
        "release_notify_stamped",
        {"version": version, "recipients": len(recipients), "failed": len(failed)},
        module_name=MODULE_NAME,
    )
    return path


def _run_drone(args: list[str]) -> tuple[bool, str]:
    """Run one drone command from the devpulse branch directory.

    Args:
        args: The drone arguments, already split — never a command string.

    Returns:
        tuple: (succeeded, detail). Detail is "" on success, else the reason.
    """
    binary = shutil.which("drone")
    if binary is None:
        logger.error(f"[{MODULE_NAME}] drone is not on PATH — nothing can be sent")
        return False, "drone is not on PATH"

    try:
        completed = subprocess.run(
            [binary, *args],
            cwd=str(devpulse_root()),
            capture_output=True,
            text=True,
            timeout=SEND_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.error(f"[{MODULE_NAME}] drone {' '.join(args[:2])} timed out after {SEND_TIMEOUT_SECONDS}s")
        return False, f"timed out after {SEND_TIMEOUT_SECONDS}s"
    except OSError as exc:
        logger.error(f"[{MODULE_NAME}] drone {' '.join(args[:2])} could not run: {exc!r}")
        return False, f"{type(exc).__name__}: {exc}"

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        reason = detail[-1] if detail else f"exit {completed.returncode}"
        logger.error(f"[{MODULE_NAME}] drone {' '.join(args[:2])} exit {completed.returncode}: {reason}")
        return False, f"exit {completed.returncode}: {reason}"
    return True, ""


def send_email(address: str, subject: str, body: str) -> tuple[bool, str]:
    """Send one release mail through ai_mail.

    Deliberately ``email`` and not ``dispatch``: this is news, not a task, and
    the manager reads it on their next wake (DPLAN-0335, leg 1).

    Args:
        address: The manager's @address.
        subject: The release subject line.
        body: The composed body.

    Returns:
        tuple: (sent, reason when it failed).
    """
    json_handler.log_operation("release_notify_email", {"to": address}, module_name=MODULE_NAME)
    return _run_drone(["@ai_mail", "email", address, subject, body])


def post_commons(subject: str, body: str) -> tuple[bool, str]:
    """Post the one commons thread for this release.

    Args:
        subject: The release subject line, used as the thread title.
        body: The composed body.

    Returns:
        tuple: (posted, reason when it failed).
    """
    json_handler.log_operation("release_notify_commons", {"room": COMMONS_ROOM}, module_name=MODULE_NAME)
    return _run_drone(["@commons", "post", COMMONS_ROOM, subject, body, "--type", COMMONS_TYPE])
