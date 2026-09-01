# =================== AIPass ====================
# Name: runaway_handler.py
# Description: Runaway log event handler with per-file cooldown gating
# Version: 1.3.0
# Created: 2026-07-14
# Modified: 2026-08-09
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

Severity doctrine — WARNING observes, CRITICAL wakes:
    - WARNING (100 lines/min sustained 12 intervals) is OBSERVE-ONLY. It writes
      the alert and the decision entry with full fidelity and records the
      per-file cooldown, but it sends no email and wakes nobody. The 100/min
      threshold predates routine multi-agent fleets: it fires overwhelmingly on
      healthy chatty logs under normal load, and agents were being woken out of
      sleep for a system behaving exactly as designed.
    - CRITICAL (600 lines/min sustained 6 intervals) is unchanged. Email plus
      wake_branch, bypassing a volume mute if one is set.

    Accepted trade-off, ruled deliberately and not an oversight: a sustained
    moderate leak — say ~150 lines/min for days — never climbs to CRITICAL, so
    under observe-only nobody is ever woken for it. It lands in alerts.json and
    in the decision log, plainly visible to anyone who looks, but nobody is
    told. We chose a quiet record over a fleet that stops trusting the wake.

Gating:
    - Per-file cooldown (30min default) — independent of medic circuit breaker
    - VOLUME mute check (volume_muted_branches in medic_state.json)
    - UNKNOWN/missing branch → dispatch to @prax as fallback

Mute classes are deliberately separate. Medic CONTENT mutes (muted_branches)
never gate runaway alerts: every dispatch checklist tells agents to medic-mute
before build/edit work, which is exactly when log floods happen, so gating on
the content mute made this channel structurally dead in its own peak window.
A volume mute must be set deliberately, and CRITICAL runaways bypass even that
— a machine-eating flood is never something you asked to silence.

Every gating decision is appended to logs/runaway_suppressed.jsonl with an
`outcome` field ("suppressed", "delivered" or "observed") so suppressed-by-design,
delivered-by-bypass and recorded-but-untold are distinguishable in the trail.
"observed" is the observe-only WARNING outcome: we did record it, so it is not a
suppression, and nobody was told, so it is not a delivery — it needed its own
word. Entries written before the `outcome` field existed are all suppressions.

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

# Volume mutes are a separate class from medic's content mutes (muted_branches).
VOLUME_MUTE_KEY = "volume_muted_branches"


# Deliberately NOT prax: this handler runs on the event path the log watchers
# read, so a line through prax would be detected and fired straight back at it.
# The sidecar is `.jsonl`, which the watchers skip — they read only `*.log`.
logger = trail_logger(TRIGGER_ROOT / "logs" / "runaway_handler.jsonl")


_REPO_ROOT = find_repo_root(caller="runaway_handler")
ALERTS_FILE = _REPO_ROOT / ".aipass" / "alerts.json"
# Live medic state — see medic_state.py for why it is not on the trio path.
MEDIC_STATE_FILE = TRIGGER_JSON_DIR / "medic_state.json"
LEGACY_MEDIC_STATE_FILE = TRIGGER_JSON_DIR / "trigger_config.json"

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


def _is_branch_volume_muted(branch_name: str) -> bool:
    """Check if a branch is VOLUME-muted for runaway dispatch.

    Reads volume_muted_branches from medic_state.json — deliberately NOT
    muted_branches, which is the medic content-mute list. Supports both
    plain-string entries (permanent) and dict entries with TTL.

    Args:
        branch_name: Branch name (case-insensitive)

    Returns:
        True if branch is actively volume-muted
    """
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
        return False


def _write_decision_log(outcome: str, reason: str, file_path: str, branch: str) -> None:
    """Write a gating decision to the runaway decision trail.

    Args:
        outcome: "suppressed" (alert dropped), "delivered" (alert sent anyway)
            or "observed" (recorded, nobody woken — observe-only WARNING)
        reason: Machine-readable cause, e.g. "cooldown", "volume_muted"
        file_path: Path to the runaway log file
        branch: Responsible branch name
    """
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
    """Handle runaway_log_detected event — observe WARNING, dispatch CRITICAL.

    Volume-based detection, independent of medic error_detected pipeline.
    Uses per-file cooldown (30min) instead of the medic circuit breaker.

    WARNING is observe-only: alert, decision entry and cooldown are recorded,
    but no email is sent and no branch is woken. CRITICAL keeps the full
    dispatch path — email, wake_branch, alert, cooldown.

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
            _write_decision_log("suppressed", "cooldown", file_path, branch or "UNKNOWN")
            return

        is_unknown = not branch or branch.upper() == "UNKNOWN"
        target_branch = branch or "UNKNOWN"
        is_critical = severity.lower() == "critical"

        if not is_unknown and _is_branch_volume_muted(target_branch):
            if not is_critical:
                _write_decision_log("suppressed", "volume_muted", file_path, target_branch)
                return
            # A machine-eating flood is never something you asked to silence.
            _write_decision_log("delivered", "bypass_critical", file_path, target_branch)

        if not is_critical:
            # Observe-only: record with full fidelity, wake nobody. The cooldown
            # is recorded too — without it every detection interval would append
            # another alert and the record would become its own flood.
            _write_alert(
                file_path, severity, target_branch, rate_lines_per_min, sustained_duration_sec, forever=forever
            )
            _write_decision_log("observed", "observe_only", file_path, target_branch)
            _record_file_dispatch(file_path)
            json_handler.log_operation("runaway_observed", {"branch": target_branch, "file": file_path})
            return

        if _send_email is None:
            logger.warning("No email callback — cannot dispatch runaway alert")
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
            return

        try:
            from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

            wake_branch(recipient, fresh=False, sender="@trigger")
        except Exception as exc:
            # Not fatal — the email is already delivered and waits in the inbox.
            # But a wake that never lands means nobody reads it until they next
            # wake anyway, so the miss is recorded rather than swallowed.
            logger.warning(f"wake failed for {recipient} ({file_path}): {exc}")

        _write_alert(file_path, severity, target_branch, rate_lines_per_min, sustained_duration_sec, forever=forever)
        _record_file_dispatch(file_path)
        json_handler.log_operation("runaway_dispatch_sent", {"recipient": recipient, "file": file_path})

    except Exception as exc:
        logger.warning(f"handle_runaway_log_detected failed: {exc}")
