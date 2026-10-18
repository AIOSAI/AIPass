# =================== AIPass ====================
# Name: error_detected.py
# Description: Error detected event handler with Medic v2 dispatch gating
# Version: 2.9.1
# Created: 2026-02-10
# Modified: 2026-10-17
# =============================================

"""
Error Detected Event Consumer
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from aipass.trigger.apps.config import (
    TRIGGER_JSON_DIR,
    TRIGGER_ROOT,
    append_trail,
    migrate_json_file,
    trail_logger,
)
from aipass.trigger.apps.handlers.repo_root import find_repo_root
from aipass.trigger.apps.handlers.json import json_handler
from aipass.trigger.apps.handlers import escalation

# Not prax: this runs on the watched event path, so a prax line would fire straight back at it.
logger = trail_logger(TRIGGER_ROOT / "logs" / "error_detected_handler.jsonl")


_REPO_ROOT = find_repo_root(caller="error_detected")

BRANCH_REGISTRY_FILE = _REPO_ROOT / "AIPASS_REGISTRY.json"

# Live medic state — see medic_state.py for why it is not on the trio path.
MEDIC_STATE_FILE = TRIGGER_JSON_DIR / "medic_state.json"
LEGACY_MEDIC_STATE_FILE = TRIGGER_JSON_DIR / "trigger_config.json"

# Set by the module layer, so this handler never imports from modules.
_send_email: Optional[Callable[..., bool]] = None

try:
    from aipass.trigger.apps.handlers.error_registry import (
        circuit_breaker_allows,
        circuit_breaker_record_error,
        circuit_breaker_probe_succeeded,
        should_dispatch as registry_should_dispatch,
        record_dispatch as registry_record_dispatch,
        is_suppressed as registry_is_suppressed,
    )

    _REGISTRY_DISPATCH_AVAILABLE = True
except ImportError:
    _REGISTRY_DISPATCH_AVAILABLE = False

    def circuit_breaker_allows() -> bool:
        """Fallback circuit breaker check that always allows dispatch."""
        return True

    def circuit_breaker_record_error() -> None:
        """Fallback no-op error recording when error_registry is unavailable."""
        pass

    def circuit_breaker_probe_succeeded() -> None:
        """Fallback no-op when error_registry is unavailable."""
        pass

    def registry_should_dispatch(fingerprint: str) -> bool:
        """Fallback dispatch check that always allows dispatch for any fingerprint."""
        return True

    def registry_record_dispatch(fingerprint: str) -> None:
        """Fallback no-op dispatch recording when error_registry is unavailable."""
        pass

    def registry_is_suppressed(fingerprint: str) -> bool:
        """Fallback suppression check — nothing is suppressed without the registry."""
        return False


# Per-branch rate limiting, used only when error_registry is unavailable.
_dispatch_timestamps: Dict[str, List[float]] = {}
MAX_DISPATCHES_PER_WINDOW = 3
RATE_LIMIT_WINDOW_SECONDS = 600  # 10 minutes


def _read_medic_state() -> Dict[str, Any]:
    """Read medic_state.json, migrating off the legacy path on first read."""
    migrate_json_file(LEGACY_MEDIC_STATE_FILE, MEDIC_STATE_FILE)
    if not MEDIC_STATE_FILE.exists():
        return {}
    return json.loads(MEDIC_STATE_FILE.read_text(encoding="utf-8"))


def _is_medic_enabled() -> bool:
    """Check if medic (auto-healing dispatch) is enabled."""
    # Unreadable state raises, never answers enabled: it may hold a person's 'medic off'.
    try:
        config = _read_medic_state().get("config", {})
        enabled = bool(config.get("medic_enabled", True))
        if enabled:
            return True
        disabled_until = config.get("medic_disabled_until")
        if disabled_until and datetime.fromisoformat(disabled_until) <= datetime.now():
            return True
        return False
    except Exception as exc:
        raise RuntimeError(f"medic state unreadable ({MEDIC_STATE_FILE.name}): {exc}") from exc


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
    """Check if a specific branch is muted for medic dispatch."""
    try:
        muted = _read_medic_state().get("config", {}).get("muted_branches", [])
        branch_lower = branch_name.lower()
        now = datetime.now()
        return any(_mute_entry_matches(e, branch_lower, now) for e in muted)
    except Exception as exc:
        logger.warning(f"_is_branch_muted config read failed: {exc}")
        return False


def set_send_email_callback(callback: Callable[..., bool]) -> None:
    """Set the callback function for sending emails."""
    global _send_email
    _send_email = callback


def _get_registered_emails() -> set:
    """Read registered branch emails from AIPASS_REGISTRY.json."""
    # Unreadable raises, never answers empty: an empty set reads every branch as unregistered.
    if not BRANCH_REGISTRY_FILE.exists():
        return set()
    try:
        data = json.loads(BRANCH_REGISTRY_FILE.read_text(encoding="utf-8"))
        return {b["email"] for b in data.get("branches", [])}
    except Exception as exc:
        raise RuntimeError(f"branch registry unreadable ({BRANCH_REGISTRY_FILE.name}): {exc}") from exc


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
    """Read context lines around an error in the log file."""
    try:
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
        context = lines[start:end]
        return "\n".join(context)
    except Exception as exc:
        logger.warning(f"_read_log_context failed for {log_path}: {exc}")
        return ""


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

SEEDGO STANDARDS REMINDER:
- Any code changes made during this investigation MUST follow Seedgo standards
- After fixing, run: drone @seedgo checklist <modified_file>
- Fixes scoring below 80% on Seedgo audit should NOT be shipped - clean up first

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
    if not append_trail(TRIGGER_ROOT / "logs" / "medic_suppressed.jsonl", entry):
        logger.warning(f"suppression log write failed ({reason})")


def _write_rate_log(reason: str, detail: str) -> None:
    """Write a line to the rate-limited log."""
    entry = {"ts": datetime.now().isoformat(), "reason": reason, "detail": detail}
    if not append_trail(TRIGGER_ROOT / "logs" / "rate_limited.jsonl", entry):
        logger.warning(f"rate log write failed ({reason})")


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
    # Silent by contract: never raises, never prints, never logs through prax.
    try:
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

        # The breaker counts at detection time, not dispatch time.
        if _REGISTRY_DISPATCH_AVAILABLE:
            circuit_breaker_record_error()

        if _send_email is None:
            return

        recipient = f"@{branch.lower()}"

        # devpulse is protected from auto-triggering.
        if recipient == "@devpulse":
            return

        registered_emails = _get_registered_emails()
        if recipient not in registered_emails:
            _write_suppression_log(f"Unknown branch skipped: {recipient}", branch, module, message)
            return

        if _REGISTRY_DISPATCH_AVAILABLE and fingerprint:
            if not circuit_breaker_allows():
                _write_suppression_log("Circuit breaker OPEN - suppressed dispatch for", branch, module, message)
                return

            if not registry_should_dispatch(fingerprint):
                # Keep a permanent suppression from reading as a timing wait on the trail.
                if registry_is_suppressed(fingerprint):
                    _write_suppression_log(
                        f"Suppressed fingerprint {fingerprint[:12]} - no dispatch for", branch, module, message
                    )
                else:
                    _write_rate_log(
                        "Backoff active", f"fingerprint {fingerprint[:12]}: {recipient} - {module}, skipping"
                    )
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

        error_log_context = _read_log_context(effective_log_path, message)

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
            logger.warning(f"Email delivery failed for {recipient} (fingerprint={fingerprint})")
            return

        try:
            # Through ai_mail's published door, never its handlers.
            from aipass.ai_mail.apps.modules.door_wake import wake_branch

            wake_branch(recipient, fresh=False, sender="@trigger")
        except Exception as exc:
            # Not fatal: the email waits in the inbox. Recorded so the missed wake is visible.
            logger.warning(f"wake failed for {recipient} (fingerprint={fingerprint}): {exc}")

        json_handler.log_operation("dispatch_sent", {"recipient": recipient})

        if _REGISTRY_DISPATCH_AVAILABLE and fingerprint:
            registry_record_dispatch(fingerprint)
            circuit_breaker_probe_succeeded()
        else:
            _record_dispatch(recipient)

    except Exception as exc:
        logger.warning(f"handle_error_detected failed: {exc}")
        return  # Silent failure - handler must not raise
