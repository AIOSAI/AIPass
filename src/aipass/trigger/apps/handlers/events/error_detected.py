# =================== AIPass ====================
# Name: error_detected.py
# Description: Error detected event handler with Medic v2 dispatch gating
# Version: 2.15.0
# Created: 2026-02-10
# Modified: 2026-11-16
# =============================================

"""
Error Detected Event Consumer
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from aipass.prax import append_jsonl, logger
from aipass.trigger.apps.config import TRIGGER_ROOT
from aipass.trigger.apps.handlers.repo_root import find_repo_root
from aipass.trigger.apps.handlers.json import json_handler
from aipass.trigger.apps.handlers import escalation, medic_state
from aipass.memory.apps.modules.door_registry_scope import fleet_branches


_REPO_ROOT = find_repo_root(caller="error_detected")

BRANCH_REGISTRY_FILE = _REPO_ROOT / "AIPASS_REGISTRY.json"

# Set by the module layer, so this handler never imports from modules.
_send_email: Optional[Callable[..., bool]] = None

from aipass.trigger.apps.handlers.error_registry import (
    RECIPIENT_CAP,
    RECIPIENT_WINDOW_SECONDS,
    circuit_breaker_delivered,
    circuit_breaker_held,
    circuit_breaker_send_failed,
    circuit_breaker_summary,
    circuit_breaker_summary_sent,
    dispatch_gate,
    should_dispatch as registry_should_dispatch,
    record_dispatch as registry_record_dispatch,
    is_suppressed as registry_is_suppressed,
)


# Per-branch rate limiting, used only for an error with no fingerprint.
_dispatch_timestamps: Dict[str, List[float]] = {}
MAX_DISPATCHES_PER_WINDOW = 3
RATE_LIMIT_WINDOW_SECONDS = 600  # 10 minutes


def _is_medic_enabled() -> bool:
    """Check if medic (auto-healing dispatch) is enabled."""
    # Unreadable state raises, never answers enabled: it may hold a person's 'medic off'.
    try:
        return medic_state.is_enabled()
    except Exception as exc:
        raise RuntimeError(f"medic state unreadable ({medic_state.MEDIC_STATE_FILE.name}): {exc}") from exc


def _is_branch_muted(branch_name: str) -> bool:
    """Check if a specific branch is muted for medic dispatch."""
    # Unreadable raises, never answers unmuted: it may hold a person's mute.
    try:
        muted = medic_state.get_muted_branches()
    except Exception as exc:
        raise RuntimeError(f"mute list unreadable ({medic_state.MEDIC_STATE_FILE.name}): {exc}") from exc
    return branch_name.lstrip("@").lower() in muted


def set_send_email_callback(callback: Callable[..., bool]) -> None:
    """Set the callback function for sending emails."""
    global _send_email
    _send_email = callback


# TTL-bound: the door logs each refused row at ERROR into a log this lane watches, so a per-event read loops.
REGISTERED_TTL_SECONDS = 60.0
_registered_cache: tuple = (0.0, None)
# spawn issues every passport and keeps the registry; an unreadable one is spawn's to fix.
REGISTRY_OWNER = "@spawn"
_census_alerted: Optional[str] = None  # the failure already told to REGISTRY_OWNER


def _get_registered_emails() -> set:
    """Emails of every declared citizen (core, resident, external), read through memory's door."""
    # Unreadable or absent raises, never answers empty: an empty set reads every branch as unregistered.
    global _registered_cache
    checked_at, cached = _registered_cache
    now = time.monotonic()
    if cached is not None and now - checked_at < REGISTERED_TTL_SECONDS:
        return cached
    if not BRANCH_REGISTRY_FILE.exists():
        raise RuntimeError(f"branch registry unreadable ({BRANCH_REGISTRY_FILE.name}): file absent")
    try:
        rows = fleet_branches(repo_root=BRANCH_REGISTRY_FILE.parent, name_from="registry", strict=True)
    except Exception as exc:
        raise RuntimeError(f"branch registry unreadable ({BRANCH_REGISTRY_FILE.name}): {exc}") from exc
    emails = {row["email"] for row in rows if row.get("email")}
    _registered_cache = (now, emails)
    return emails


def _tell_registry_owner(reason: str, send: Callable[..., bool]) -> None:
    """Dispatch the registry's owner once per failure; a readable census re-arms it."""
    global _census_alerted
    if _census_alerted == reason:
        return
    body = (
        f"Medic cannot read the branch registry, so every error dispatch is held until it can: {reason}\n\n"
        f"Path: {BRANCH_REGISTRY_FILE}\nEach held dispatch is recorded in trigger/logs/medic_suppressed.jsonl."
    )
    sent = send(
        to_branch=REGISTRY_OWNER,
        subject="[MEDIC] branch registry unreadable",
        message=body,
        auto_execute=True,
        reply_to="@devpulse",
        from_branch="@trigger",
    )
    if not sent:
        raise RuntimeError(f"could not tell {REGISTRY_OWNER} that {reason}")
    _census_alerted = reason
    _wake(REGISTRY_OWNER, "registry unreadable")


def _wake(recipient: str, about: str) -> None:
    """Wake the branch a delivered mail is for; a failure raises, since the mail then sits unread."""
    # Through ai_mail's published door, never its handlers.
    from aipass.ai_mail import wake_branch

    try:
        wake_branch(recipient, fresh=False, sender="@trigger")
    except Exception as exc:
        raise RuntimeError(f"mail delivered to {recipient} but wake failed ({about}): {exc}") from exc


def _is_rate_limited(branch_email: str) -> bool:
    """Check if a branch has exceeded the dispatch rate limit."""
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS

    if branch_email not in _dispatch_timestamps:
        _dispatch_timestamps[branch_email] = []

    _dispatch_timestamps[branch_email] = [ts for ts in _dispatch_timestamps[branch_email] if ts > cutoff]

    return len(_dispatch_timestamps[branch_email]) >= MAX_DISPATCHES_PER_WINDOW


def _record_dispatch(branch_email: str) -> None:
    """Record a dispatch timestamp for rate limiting."""
    if branch_email not in _dispatch_timestamps:
        _dispatch_timestamps[branch_email] = []
    _dispatch_timestamps[branch_email].append(time.time())


def _read_log_context(log_path: str, error_message: str, context_lines: int = 2) -> str:
    """Read context lines around an error in the log file; an unreadable file raises."""
    path = Path(log_path)
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    target_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        if error_message in lines[i]:
            target_idx = i
            break
    if target_idx < 0:
        return ""
    start = max(0, target_idx - context_lines)
    end = min(len(lines), target_idx + context_lines + 1)
    return "\n".join(lines[start:end])


def _build_notification_message(
    error_hash: str,
    module: str,
    message: str,
    timestamp: str,
    log_path: str,
    occurrences: int = 1,
    first_seen: str = "",
    last_seen: str = "",
    log_context: str = "",
    fingerprint: str = "",
    registry_id: str = "",
) -> str:
    """Build error notification message with investigation instructions."""
    context_block = ""
    if log_context:
        context_block = f"""
Log context (surrounding lines):
{log_context}
"""

    registry_block = ""
    if fingerprint:
        registry_block = f"""
Registry tracking:
  Fingerprint: {fingerprint[:12]}
"""

    # The ID shown must be the one the registry verbs accept, and the closing verbs must be
    # named: an entry nobody resolves stays new and re-dispatches.
    if registry_id:
        identity_line = f"Error ID: {registry_id}"
        closing_block = f"""CLOSE IT - a dispatch nobody closes comes back:
  drone @trigger errors resolve {registry_id}            once the fix is verified
  drone @trigger errors suppress {registry_id} "reason"  when it is known and not worth fixing
"""
    else:
        identity_line = f"Reference: {error_hash} (not tracked in the registry - errors detail cannot find it)"
        closing_block = """CLOSE IT: this occurrence has no registry entry, so there is nothing to resolve.
Say so to @devpulse - a dispatch with no row is a defect in the lane that fired it.
"""
    report_ref = registry_id or error_hash

    return f"""Error detected - investigate and respond.

{identity_line}
Module: {module}
Timestamp: {timestamp}
Log file: {log_path}
Occurrences: {occurrences}
First seen: {first_seen or timestamp}
Last seen: {last_seen or timestamp}
{registry_block}
Error message:
{message}
{context_block}
---
INVESTIGATION STEPS:
1. Check the log file for context around this error
2. Identify root cause

DECISION TREE:
- SIMPLE FIX (typo, missing import, config issue):
  -> Fix it yourself, then report what you did to @devpulse
- COMPLEX/UNCLEAR (needs research, affects multiple files):
  -> Report findings only to @devpulse, recommend action, don't fix
- CRITICAL (data loss risk, security, system stability):
  -> STOP immediately, escalate to @devpulse with full context

SENTRY STANDARDS REMINDER:
- Any code changes made during this investigation MUST follow Sentry standards
- After fixing, run: drone @sentry checklist <modified_file>
- Fixes scoring below 80% on Sentry audit should NOT be shipped - clean up first

{closing_block}
REPORT TO @devpulse:
  ai_mail email @devpulse "ERROR {report_ref} - [STATUS]" "Findings..."

  Include: Error ID, severity (low/medium/high/critical), what you found, action taken or recommended.
"""


def _write_suppression_log(reason: str, branch: str, module: str, message: str) -> None:
    """Write a line to the medic suppression log."""
    entry = {
        "ts": datetime.now().isoformat(),
        "reason": reason,
        "branch": branch,
        "module": module,
        "msg": message[:100],
    }
    append_jsonl(TRIGGER_ROOT / "logs" / "medic_suppressed.jsonl", entry)


def _write_rate_log(reason: str, detail: str) -> None:
    """Write a line to the rate-limited log."""
    entry = {"ts": datetime.now().isoformat(), "reason": reason, "detail": detail}
    append_jsonl(TRIGGER_ROOT / "logs" / "rate_limited.jsonl", entry)


def breaker_gate(recipient: str, fingerprint: str, note: str) -> str:
    """The breaker gate medic and ci_red share: empty to send, else the hold reason for the trail.

    Call it only past suppression, backoff and the recipient checks. An owed summary goes to @devpulse
    as plain mail, never a wake.
    """
    verdict = dispatch_gate(recipient, fingerprint, note)
    if verdict in ("send", "probe"):
        return ""
    if verdict == "held_cap":
        return f"Held, {recipient} had {RECIPIENT_CAP} faults mailed in {RECIPIENT_WINDOW_SECONDS // 60} min - held for"
    if verdict == "tripped":
        if _send_email is None:
            raise RuntimeError("no ai_mail adapter wired: the breaker summary cannot reach @devpulse")
        sent = _send_email(
            to_branch="@devpulse",
            subject="[MEDIC] circuit breaker open: mail held",
            message=circuit_breaker_summary(),
            auto_execute=False,
            reply_to="@trigger",
            from_branch="@trigger",
        )
        if not sent:
            raise RuntimeError("breaker summary to @devpulse not delivered; the next hold retries it")
        circuit_breaker_summary_sent()
    return "Circuit breaker OPEN - held for"


def handle_error_detected(
    branch: str | None = None,
    module: str | None = None,
    message: str | None = None,
    log_path: str | None = None,
    error_hash: str | None = None,
    timestamp: str | None = None,
    fingerprint: str = "",
    registry_id: str = "",
    first_seen: str = "",
    last_seen: str = "",
    count: int = 1,
    **kwargs: Any,
) -> None:
    """Handle error_detected event - deliver notification to affected branch."""
    global _census_alerted
    # Never prints; a failure raises to the bus, which reports it at a bounded rate.
    if not branch or not module or not message or not error_hash:
        return

    # Count BEFORE every gate: a mute, toggle or open breaker stops the dispatch, never the count.
    escalation.record_error(
        branch=branch,
        module=module,
        message=message,
        log_file=log_path or "",
        fingerprint=fingerprint,
        raw_line=kwargs.get("raw_line", "") or "",
    )

    if not _is_medic_enabled():
        _write_suppression_log("Medic OFF - suppressed dispatch for", branch, module, message)
        return

    if _is_branch_muted(branch):
        _write_suppression_log("Branch muted - suppressed dispatch for", branch, module, message)
        return

    # A first occurrence may be transient; dispatch only on recurrence.
    if count < 2:
        _write_suppression_log(f"First occurrence (count={count}) - waiting for pattern", branch, module, message)
        return

    if _send_email is None:
        raise RuntimeError("no ai_mail adapter wired: medic cannot mail anyone")

    recipient = f"@{branch.lower()}"

    # devpulse is protected from auto-triggering.
    if recipient == "@devpulse":
        return

    try:
        registered_emails = _get_registered_emails()
    except RuntimeError as exc:
        _write_suppression_log(f"Held, {exc} - no dispatch for", branch, module, message)
        _tell_registry_owner(str(exc), _send_email)
        return
    _census_alerted = None
    if recipient not in registered_emails:
        _write_suppression_log(f"Unknown branch skipped: {recipient}", branch, module, message)
        return

    if fingerprint:
        # Backoff first: a half-open breaker's one probe must go to a fingerprint that would be sent.
        if not registry_should_dispatch(fingerprint):
            # Keep a permanent suppression from reading as a timing wait on the trail.
            if registry_is_suppressed(fingerprint):
                _write_suppression_log(
                    f"Suppressed fingerprint {fingerprint[:12]} - no dispatch for", branch, module, message
                )
            else:
                _write_rate_log("Backoff active", f"fingerprint {fingerprint[:12]}: {recipient} - {module}, skipping")
            return

        hold = breaker_gate(recipient, fingerprint, f"{module}: {message[:160]}")
        if hold:
            _write_suppression_log(hold, branch, module, message)
            return
    else:
        recent_count = len(
            [ts for ts in _dispatch_timestamps.get(recipient, []) if ts > time.time() - RATE_LIMIT_WINDOW_SECONDS]
        )
        if _is_rate_limited(recipient):
            _write_rate_log("Rate limited", f"{recipient} has {recent_count} recent dispatches, skipping")
            return

    if not timestamp:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    effective_log_path = log_path if log_path else "unknown"

    try:
        error_log_context = _read_log_context(effective_log_path, message)
    except OSError as exc:
        # Carried into the mail, so the recipient learns why the context is missing; the dispatch still goes.
        logger.warning(f"log context unreadable for {effective_log_path}: {exc}")
        error_log_context = f"(context unavailable: {exc})"

    email_subject = f"[ERROR] {module} - detected in logs"

    notification_message = _build_notification_message(
        error_hash=error_hash,
        module=module,
        message=message,
        timestamp=timestamp,
        log_path=effective_log_path,
        occurrences=count,
        first_seen=first_seen or timestamp,
        last_seen=last_seen or timestamp,
        log_context=error_log_context,
        fingerprint=fingerprint,
        registry_id=registry_id,
    )

    held = circuit_breaker_held(recipient) if fingerprint else {}
    held.pop(fingerprint, None)
    if held:
        notification_message += "\n\nHeld for you while medic's cap or breaker was shut:\n" + "\n".join(
            f"  {fp[:12]} x{row['count']} {row['note']}" for fp, row in held.items()
        )

    # Via the callback: trigger is not a branch, so ai_mail's PWD sender detection fails.
    sent = _send_email(
        to_branch=recipient,
        subject=email_subject,
        message=notification_message,
        auto_execute=True,
        reply_to="@devpulse",
        from_branch="@trigger",
    )

    if not sent:
        if fingerprint:
            circuit_breaker_send_failed()
        raise RuntimeError(f"Email delivery failed for {recipient} (fingerprint={fingerprint})")

    json_handler.log_operation("dispatch_sent", {"recipient": recipient})

    if fingerprint:
        registry_record_dispatch(fingerprint)
        circuit_breaker_delivered(recipient, [fingerprint, *held])
    else:
        _record_dispatch(recipient)

    # Last: the delivered mail is recorded before a wake failure raises to the bus.
    _wake(recipient, f"fingerprint={fingerprint}")
