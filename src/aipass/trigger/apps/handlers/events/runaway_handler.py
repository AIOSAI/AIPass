# =================== AIPass ====================
# Name: runaway_handler.py
# Description: Runaway log event handler with per-file cooldown gating
# Version: 1.5.1
# Created: 2026-07-14
# Modified: 2026-10-17
# =============================================

"""
Runaway Log Detected Event Handler

WARNING observes (alert, trail, cooldown; no mail, no wake); CRITICAL mails, wakes and bypasses a volume mute.
Medic content mutes never gate runaways; an unreadable medic_state.json is not a mute.
Trail outcomes in logs/runaway_suppressed.jsonl: suppressed, observed, delivered, failed (older lines: suppressed).
"""

import json
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from aipass.trigger.apps.config import (
    TRIGGER_JSON_DIR,
    TRIGGER_ROOT,
    append_trail,
    atomic_write_json,
    json_file_lock,
    migrate_json_file,
    trail_logger,
)
from aipass.trigger.apps.handlers.repo_root import find_repo_root
from aipass.trigger.apps.handlers.json import json_handler

DECISION_LOG = TRIGGER_ROOT / "logs" / "runaway_suppressed.jsonl"

VOLUME_MUTE_KEY = "volume_muted_branches"


# Not prax: the watchers would read its line and fire it back; they skip `.jsonl`.
logger = trail_logger(TRIGGER_ROOT / "logs" / "runaway_handler.jsonl")


_REPO_ROOT = find_repo_root(caller="runaway_handler")
ALERTS_FILE = _REPO_ROOT / ".aipass" / "alerts.json"
MEDIC_STATE_FILE = TRIGGER_JSON_DIR / "medic_state.json"
LEGACY_MEDIC_STATE_FILE = TRIGGER_JSON_DIR / "trigger_config.json"

_send_email: Optional[Callable[..., bool]] = None

_file_cooldowns: dict[str, float] = {}
COOLDOWN_SECONDS = 1800
DEFAULT_ALERT_TTL_SECONDS = 86400  # 24 hours — matches medic_state.py DEFAULT_MUTE_SECONDS


def set_send_email_callback(callback: Callable[..., bool]) -> None:
    """Set the callback function for sending emails; the registry layer sets it before events fire."""
    global _send_email
    _send_email = callback


def _is_file_on_cooldown(file_path: str) -> bool:
    """Check if a file is still within its dispatch cooldown window."""
    last = _file_cooldowns.get(file_path, 0.0)
    return (time.time() - last) < COOLDOWN_SECONDS


def _record_file_dispatch(file_path: str) -> None:
    """Record a dispatch timestamp for per-file cooldown."""
    _file_cooldowns[file_path] = time.time()


def _mute_entry_matches(entry, branch_lower: str, now: datetime) -> bool:
    """Check if a single mute entry matches the branch and is still active."""
    if isinstance(entry, str):
        return entry.lower() == branch_lower
    if not isinstance(entry, dict):
        return False
    if entry.get("name", "").lower() != branch_lower:
        return False
    expires_at = entry.get("expires_at")
    if expires_at is None:
        return True
    return datetime.fromisoformat(expires_at) > now


def _is_branch_volume_muted(branch_name: str) -> Optional[bool]:
    """Check if a branch is VOLUME-muted for runaway dispatch; None means unreadable, never "not muted"."""
    try:
        migrate_json_file(LEGACY_MEDIC_STATE_FILE, MEDIC_STATE_FILE)
        if not MEDIC_STATE_FILE.exists():
            return False
        data = json.loads(MEDIC_STATE_FILE.read_text(encoding="utf-8"))
        muted = data.get("config", {}).get(VOLUME_MUTE_KEY, [])
        branch_lower = branch_name.lower()
        now = datetime.now()
        return any(_mute_entry_matches(e, branch_lower, now) for e in muted)
    except Exception as exc:
        logger.warning(f"_is_branch_volume_muted config read failed: {exc}")
        return None


def _write_decision_log(outcome: str, reason: str, file_path: str, branch: str) -> None:
    """Write a gating decision to the runaway decision trail."""
    entry = {
        "ts": datetime.now().isoformat(),
        "outcome": outcome,
        "reason": reason,
        "file": file_path,
        "branch": branch,
    }
    if not append_trail(DECISION_LOG, entry):
        logger.warning(f"decision log write failed ({outcome}/{reason})")


def _write_alert(
    file_path: str, severity: str, branch: str, rate: float, duration: float, forever: bool = False
) -> None:
    """Write an alert entry to .aipass/alerts.json."""
    try:
        expires_at = None if forever else (datetime.now() + timedelta(seconds=DEFAULT_ALERT_TTL_SECONDS)).isoformat()
        alert = {
            "id": str(uuid.uuid4()),
            "source": "prax",
            "severity": severity,
            "title": f"Runaway log: {Path(file_path).name}",
            "body": (
                f"Log file {file_path} producing {rate:.0f} lines/min sustained {duration:.0f}s. Branch: {branch}."
            ),
            "created_at": datetime.now().isoformat(),
            "expires_at": expires_at,
        }
        ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with json_file_lock(ALERTS_FILE):
            existing = {"alerts": []}
            if ALERTS_FILE.exists():
                raw = ALERTS_FILE.read_text(encoding="utf-8").strip()
                if raw:
                    existing = json.loads(raw)
            existing.setdefault("alerts", []).append(alert)
            atomic_write_json(ALERTS_FILE, existing)
    except Exception as exc:
        logger.warning(f"_write_alert failed: {exc}")


def handle_runaway_log_detected(
    file_path: str | None = None,
    rate_lines_per_min: float = 0,
    sustained_duration_sec: float = 0,
    severity: str = "warning",
    branch: str | None = None,
    forever: bool = False,
    **kwargs: Any,
) -> None:
    """Handle runaway_log_detected event — observe WARNING, dispatch CRITICAL."""
    try:
        if not file_path:
            return

        if _is_file_on_cooldown(file_path):
            _write_decision_log("suppressed", "cooldown", file_path, branch or "UNKNOWN")
            return

        is_unknown = not branch or branch.upper() == "UNKNOWN"
        target_branch = branch or "UNKNOWN"
        is_critical = severity.lower() == "critical"

        # One trail line per event, written where the outcome is known: never "delivered" before the send.
        gate_reason: Optional[str] = None
        muted = False if is_unknown else _is_branch_volume_muted(target_branch)
        if muted is None:
            # Unread is not muted: a runaway must reach someone.
            gate_reason = "mute_unreadable"
        elif muted:
            if not is_critical:
                _write_decision_log("suppressed", "volume_muted", file_path, target_branch)
                return
            gate_reason = "bypass_critical"

        if not is_critical:
            # The cooldown is recorded too, or every interval appends another alert.
            _write_alert(
                file_path, severity, target_branch, rate_lines_per_min, sustained_duration_sec, forever=forever
            )
            _write_decision_log("observed", gate_reason or "observe_only", file_path, target_branch)
            _record_file_dispatch(file_path)
            json_handler.log_operation("runaway_observed", {"branch": target_branch, "file": file_path})
            return

        if _send_email is None:
            logger.warning("No email callback — cannot dispatch runaway alert")
            _write_decision_log("failed", "no_callback", file_path, target_branch)
            return

        recipient = "@prax" if is_unknown else f"@{target_branch.lower()}"

        subject = f"[RUNAWAY] {Path(file_path).name} — {severity.upper()}"
        message = (
            f"Runaway log detected.\n\n"
            f"File: {file_path}\n"
            f"Rate: {rate_lines_per_min:.0f} lines/min\n"
            f"Sustained: {sustained_duration_sec:.0f}s\n"
            f"Severity: {severity}\n"
            f"Branch: {target_branch}\n\n"
            f"---\n"
            f"INVESTIGATION STEPS:\n"
            f"1. Identify the process writing to this log\n"
            f"2. Check for spin loops, retry storms, or misconfigured log levels\n"
            f"3. Fix the root cause or kill the offending process\n"
            f"4. Report to @devpulse\n"
        )

        sent = _send_email(
            to_branch=recipient,
            subject=subject,
            message=message,
            auto_execute=True,
            reply_to="@devpulse",
            from_branch="@trigger",
        )

        if not sent:
            logger.warning(f"Email delivery failed for {recipient} ({file_path})")
            _write_decision_log("failed", "send_refused", file_path, target_branch)
            return
        _write_decision_log("delivered", gate_reason or "critical", file_path, target_branch)

        try:
            # Through ai_mail's published door, never its handlers.
            from aipass.ai_mail.apps.modules.door_wake import wake_branch

            wake_branch(recipient, fresh=False, sender="@trigger")
        except Exception as exc:
            logger.warning(f"wake failed for {recipient} ({file_path}): {exc}")

        _write_alert(file_path, severity, target_branch, rate_lines_per_min, sustained_duration_sec, forever=forever)
        _record_file_dispatch(file_path)
        json_handler.log_operation("runaway_dispatch_sent", {"recipient": recipient, "file": file_path})

    except Exception as exc:
        logger.warning(f"handle_runaway_log_detected failed: {exc}")
