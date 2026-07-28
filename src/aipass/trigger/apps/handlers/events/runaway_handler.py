# =================== AIPass ====================
# Name: runaway_handler.py
# Description: Runaway log event handler with per-file cooldown gating
# Version: 1.0.0
# Created: 2026-07-14
# Modified: 2026-07-21
# =============================================

"""
Runaway Log Detected Event Handler

Handles runaway_log_detected events fired by prax's rate tracker.
Volume-based detection (rate of log output), orthogonal to error_detected
(content-based ERROR line matching).

Event payload from prax:
    - file_path: Path to the runaway log file
    - rate_lines_per_min: Current log rate
    - sustained_duration_sec: How long the rate has been sustained
    - severity: "warning" or "critical"
    - branch: Responsible branch name

Gating:
    - Per-file cooldown (30min default) — independent of medic circuit breaker
    - Branch mute check (reuses TTL mute infrastructure from trigger_config.json)
    - UNKNOWN/missing branch → dispatch to @prax as fallback

Alerts written to .aipass/alerts.json expire after 24h by default (same TTL
convention as medic_state.py's DEFAULT_MUTE_SECONDS) — pass forever=True to
skip expiry.
"""

import json
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from aipass.trigger.apps.config import TRIGGER_ROOT, atomic_write_json, json_file_lock
from aipass.trigger.apps.handlers.json import json_handler

try:
    from aipass.prax import append_jsonl as _append_jsonl
except Exception:
    _append_jsonl = None

_HANDLER_LOG = TRIGGER_ROOT / "logs" / "runaway_handler.jsonl"


def _log_warning(message: str) -> None:
    """Log warning to file (recursion-safe prax path)."""
    if _append_jsonl is None:
        return
    try:
        _append_jsonl(_HANDLER_LOG, {"level": "WARNING", "msg": message})
    except Exception:
        pass  # seedgo:bypass meta-logging


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


_REPO_ROOT = _find_repo_root()
ALERTS_FILE = _REPO_ROOT / ".aipass" / "alerts.json"
TRIGGER_CONFIG_FILE = TRIGGER_ROOT / "trigger_json" / "trigger_config.json"

_send_email: Optional[Callable[..., bool]] = None

_file_cooldowns: dict[str, float] = {}
COOLDOWN_SECONDS = 1800
DEFAULT_ALERT_TTL_SECONDS = 86400  # 24 hours — matches medic_state.py DEFAULT_MUTE_SECONDS


def set_send_email_callback(callback: Callable[..., bool]) -> None:
    """Set the callback function for sending emails.

    Must be called by the registry layer before events fire.

    Args:
        callback: Function matching deliver_email_to_branch adapter signature
    """
    global _send_email
    _send_email = callback


def _is_file_on_cooldown(file_path: str) -> bool:
    """Check if a file is still within its dispatch cooldown window.

    Args:
        file_path: Path to the log file

    Returns:
        True if cooldown has not expired
    """
    last = _file_cooldowns.get(file_path, 0.0)
    return (time.time() - last) < COOLDOWN_SECONDS


def _record_file_dispatch(file_path: str) -> None:
    """Record a dispatch timestamp for per-file cooldown.

    Args:
        file_path: Path to the log file that was dispatched
    """
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


def _is_branch_muted(branch_name: str) -> bool:
    """Check if a branch is muted for dispatch.

    Reads muted_branches from trigger_config.json. Supports both
    plain-string entries (permanent) and dict entries with TTL.

    Args:
        branch_name: Branch name (case-insensitive)

    Returns:
        True if branch is actively muted
    """
    try:
        if not TRIGGER_CONFIG_FILE.exists():
            return False
        data = json.loads(TRIGGER_CONFIG_FILE.read_text(encoding="utf-8"))
        muted = data.get("config", {}).get("muted_branches", [])
        branch_lower = branch_name.lower()
        now = datetime.now()
        return any(_mute_entry_matches(e, branch_lower, now) for e in muted)
    except Exception as exc:
        _log_warning(f"_is_branch_muted config read failed: {exc}")
        return False


def _write_suppression_log(reason: str, file_path: str, branch: str) -> None:
    """Write a line to the runaway suppression log."""
    if _append_jsonl is None:
        return
    try:
        suppressed_log = TRIGGER_ROOT / "logs" / "runaway_suppressed.jsonl"
        entry = {
            "ts": datetime.now().isoformat(),
            "reason": reason,
            "file": file_path,
            "branch": branch,
        }
        _append_jsonl(suppressed_log, entry)
    except Exception as exc:
        _log_warning(f"suppression log write failed ({reason}): {exc}")


def _write_alert(
    file_path: str, severity: str, branch: str, rate: float, duration: float, forever: bool = False
) -> None:
    """Write an alert entry to .aipass/alerts.json.

    Args:
        file_path: Path to the runaway log file
        severity: "warning" or "critical"
        branch: Responsible branch name
        rate: Lines per minute
        duration: Sustained duration in seconds
        forever: If True, alert never auto-expires (default: 24h TTL)
    """
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
        _log_warning(f"_write_alert failed: {exc}")


def handle_runaway_log_detected(
    file_path: str | None = None,
    rate_lines_per_min: float = 0,
    sustained_duration_sec: float = 0,
    severity: str = "warning",
    branch: str | None = None,
    forever: bool = False,
    **kwargs: Any,
) -> None:
    """Handle runaway_log_detected event — dispatch to responsible branch.

    Volume-based detection, independent of medic error_detected pipeline.
    Uses per-file cooldown (30min) instead of the medic circuit breaker.

    Args:
        file_path: Path to the runaway log file — REQUIRED
        rate_lines_per_min: Current log rate
        sustained_duration_sec: How long the rate has been sustained
        severity: "warning" or "critical"
        branch: Responsible branch name (None/UNKNOWN → dispatch to @prax)
        forever: If True, the resulting alert never auto-expires (default: 24h TTL)
        **kwargs: Additional event data (ignored)
    """
    try:
        if not file_path:
            return

        if _is_file_on_cooldown(file_path):
            _write_suppression_log("cooldown", file_path, branch or "UNKNOWN")
            return

        is_unknown = not branch or branch.upper() == "UNKNOWN"
        target_branch = branch or "UNKNOWN"

        if not is_unknown and _is_branch_muted(target_branch):
            _write_suppression_log("branch_muted", file_path, target_branch)
            return

        if _send_email is None:
            _log_warning("No email callback — cannot dispatch runaway alert")
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
            _log_warning(f"Email delivery failed for {recipient} ({file_path})")
            return

        try:
            from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

            wake_branch(recipient, fresh=False, sender="@trigger")
        except Exception:
            pass  # Email in inbox as fallback

        _write_alert(file_path, severity, target_branch, rate_lines_per_min, sustained_duration_sec, forever=forever)
        _record_file_dispatch(file_path)
        json_handler.log_operation("runaway_dispatch_sent", {"recipient": recipient, "file": file_path})

    except Exception as exc:
        _log_warning(f"handle_runaway_log_detected failed: {exc}")
