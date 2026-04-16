# =================== AIPass ====================
# Name: error_detected.py
# Description: Error detected event handler with Medic v2 dispatch gating
# Version: 2.1.0
# Created: 2026-02-10
# Modified: 2026-02-14
# =============================================

"""
Error Detected Event Consumer

Handles error_detected events fired by Trigger's log_watcher.
Delivers notifications to affected branches via AI_MAIL.

Event data from log_watcher.py (Medic v2):
    - branch: Target branch name (e.g., 'FLOW')
    - module: Module that logged the error
    - message: Error message text
    - log_path: Path to log file
    - error_hash: Short ID from registry (or legacy 8-char MD5)
    - timestamp: When error occurred
    - fingerprint: SHA1 fingerprint from error_registry (Medic v2)
    - registry_id: Short UUID from error_registry (Medic v2)
    - first_seen: ISO timestamp of first occurrence (Medic v2)
    - last_seen: ISO timestamp of most recent occurrence (Medic v2)

Architecture (Medic v2):
    1. Trigger's log_watcher detects ERROR in branch logs
    2. log_watcher reports to error_registry, fires error_detected if new
    3. This handler checks circuit_breaker_allows() (global gate)
    4. This handler checks should_dispatch(fingerprint) (per-error backoff)
    5. If allowed, delivers email to affected branch (auto_execute=True)
    6. Records dispatch via record_dispatch() and circuit_breaker_record_error()
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from aipass.trigger.apps.config import TRIGGER_ROOT
from aipass.trigger.apps.handlers.json import json_handler

_HANDLER_LOG = TRIGGER_ROOT / "logs" / "error_detected_handler.log"


def _log_warning(message: str) -> None:
    """Log warning to file (event handlers cannot import Prax logger - causes recursion)."""
    try:
        _HANDLER_LOG.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with open(_HANDLER_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts} | WARNING | {message}\n")
    except Exception:
        pass


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


_REPO_ROOT = _find_repo_root()

BRANCH_REGISTRY_FILE = _REPO_ROOT / "AIPASS_REGISTRY.json"
TRIGGER_CONFIG_FILE = TRIGGER_ROOT / "trigger_json" / "trigger_config.json"

# Email send callback (set by module layer, avoids handler importing from modules)
_send_email: Optional[Callable[..., bool]] = None

# Try to import error_registry for Medic v2 circuit breaker + per-fingerprint backoff
try:
    from aipass.trigger.apps.handlers.error_registry import (
        circuit_breaker_allows,
        circuit_breaker_record_error,
        should_dispatch as registry_should_dispatch,
        record_dispatch as registry_record_dispatch,
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

    def registry_should_dispatch(fingerprint: str) -> bool:
        """Fallback dispatch check that always allows dispatch for any fingerprint."""
        return True

    def registry_record_dispatch(fingerprint: str) -> None:
        """Fallback no-op dispatch recording when error_registry is unavailable."""
        pass


# Legacy rate limiting (kept for backward compat when registry unavailable)
_dispatch_timestamps: Dict[str, List[float]] = {}
MAX_DISPATCHES_PER_WINDOW = 3
RATE_LIMIT_WINDOW_SECONDS = 600  # 10 minutes


def _is_medic_enabled() -> bool:
    """
    Check if medic (auto-healing dispatch) is enabled.

    Reads medic_enabled from trigger_config.json.
    Defaults to True if config is missing or unreadable.

    Returns:
        True if medic dispatch is enabled
    """
    try:
        if TRIGGER_CONFIG_FILE.exists():
            data = json.loads(TRIGGER_CONFIG_FILE.read_text(encoding="utf-8"))
            return bool(data.get("config", {}).get("medic_enabled", True))
    except Exception as exc:
        _log_warning(f"_is_medic_enabled config read failed: {exc}")
        return True  # Default to enabled on read failure
    return True


def _is_branch_muted(branch_name: str) -> bool:
    """
    Check if a specific branch is muted for medic dispatch.

    Reads muted_branches list from trigger_config.json.
    Muted branches have errors detected but NOT dispatched.

    Args:
        branch_name: Branch name (case-insensitive)

    Returns:
        True if branch is in the muted list
    """
    try:
        if TRIGGER_CONFIG_FILE.exists():
            data = json.loads(TRIGGER_CONFIG_FILE.read_text(encoding="utf-8"))
            muted = data.get("config", {}).get("muted_branches", [])
            return branch_name.lower() in [b.lower() for b in muted]
    except Exception as exc:
        _log_warning(f"_is_branch_muted config read failed: {exc}")
        return False
    return False


def set_send_email_callback(callback: Callable[..., bool]) -> None:
    """
    Set the callback function for sending emails.

    Must be called by the module/registry layer before events fire.
    This avoids handler importing from modules (maintains independence).

    Args:
        callback: Function matching send_email_direct signature
    """
    global _send_email
    _send_email = callback


def _get_registered_emails() -> set:
    """
    Read registered branch emails from AIPASS_REGISTRY.json.

    Returns:
        Set of registered email addresses (e.g., {'@flow', '@drone'})
    """
    try:
        if BRANCH_REGISTRY_FILE.exists():
            data = json.loads(BRANCH_REGISTRY_FILE.read_text(encoding="utf-8"))
            return {b["email"] for b in data.get("branches", [])}
    except Exception as exc:
        _log_warning(f"_get_registered_emails registry read failed: {exc}")
        return set()
    return set()


def _is_rate_limited(branch_email: str) -> bool:
    """
    Check if a branch has exceeded the dispatch rate limit.

    BACKWARD COMPAT: Legacy Medic v1 per-branch rate limiting.
    Primary dispatch gating is now circuit_breaker_allows() +
    should_dispatch(fingerprint) from error_registry (Medic v2).

    Args:
        branch_email: Target branch email (e.g., '@flow')

    Returns:
        True if branch has hit the limit (3 dispatches in 10 minutes)
    """
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS

    if branch_email not in _dispatch_timestamps:
        _dispatch_timestamps[branch_email] = []

    # Prune old timestamps
    _dispatch_timestamps[branch_email] = [ts for ts in _dispatch_timestamps[branch_email] if ts > cutoff]

    return len(_dispatch_timestamps[branch_email]) >= MAX_DISPATCHES_PER_WINDOW


def _record_dispatch(branch_email: str) -> None:
    """
    Record a dispatch timestamp for rate limiting.

    BACKWARD COMPAT: Legacy Medic v1 per-branch dispatch tracking.
    Primary tracking is now record_dispatch(fingerprint) from error_registry (Medic v2).

    Args:
        branch_email: Target branch email (e.g., '@flow')
    """
    if branch_email not in _dispatch_timestamps:
        _dispatch_timestamps[branch_email] = []
    _dispatch_timestamps[branch_email].append(time.time())


def _read_log_context(log_path: str, error_message: str, context_lines: int = 2) -> str:
    """
    Read context lines around an error in the log file.

    Args:
        log_path: Path to the log file
        error_message: Error message to find in the log
        context_lines: Number of lines before and after to include

    Returns:
        Formatted context string, or empty string if unavailable
    """
    try:
        path = Path(log_path)
        if not path.exists():
            return ""
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        # Find last occurrence of the error message
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
        _log_warning(f"_read_log_context failed for {log_path}: {exc}")
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
    """
    Build error notification message with investigation instructions.

    Args:
        error_hash: Unique error identifier (8-char legacy or registry ID)
        module: Module that logged the error
        message: Error message text
        timestamp: When error occurred
        log_path: Path to source log file
        occurrences: Number of times this error was seen
        first_seen: Timestamp of first occurrence
        last_seen: Timestamp of most recent occurrence
        log_context: Lines surrounding the error from the log file
        fingerprint: SHA1 fingerprint from error_registry (Medic v2)
        registry_id: Short UUID from error_registry (Medic v2)

    Returns:
        Formatted message string with investigation instructions
    """
    context_block = ""
    if log_context:
        context_block = f"""
Log context (surrounding lines):
{log_context}
"""

    # Registry tracking info (Medic v2)
    registry_block = ""
    if fingerprint or registry_id:
        display_fp = fingerprint[:12] if fingerprint else "n/a"
        display_id = registry_id if registry_id else "n/a"
        registry_block = f"""
Registry tracking:
  Fingerprint: {display_fp}
  Registry ID: {display_id}
"""

    return f"""Error detected - investigate and respond.

Error ID: {error_hash}
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

REPORT TO @devpulse:
  ai_mail email @devpulse "ERROR {error_hash} - [STATUS]" "Findings..."

  Include: Error ID, severity (low/medium/high/critical), what you found, action taken or recommended.
"""


def _write_suppression_log(reason: str, branch: str, module: str, message: str) -> None:
    """Write a line to the medic suppression log."""
    try:
        suppressed_log = TRIGGER_ROOT / "logs" / "medic_suppressed.log"
        suppressed_log.parent.mkdir(parents=True, exist_ok=True)
        with open(suppressed_log, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} | {reason} - {branch}: {module} - {message[:100]}\n")
    except Exception as exc:
        _log_warning(f"suppression log write failed ({reason}): {exc}")


def _write_rate_log(reason: str, detail: str) -> None:
    """Write a line to the rate-limited log."""
    try:
        rate_log = TRIGGER_ROOT / "logs" / "rate_limited.log"
        rate_log.parent.mkdir(parents=True, exist_ok=True)
        with open(rate_log, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} | {reason}: {detail}\n")
    except Exception as exc:
        _log_warning(f"rate log write failed ({reason}): {exc}")


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
    """
    Handle error_detected event - deliver notification to affected branch.

    Called by Trigger when log_watcher detects an ERROR in branch logs.
    Sends email to affected branch with auto_execute=True so an
    investigation agent spawns automatically.

    Dispatch threshold: count >= 2 required before dispatching. First
    occurrence (count == 1) is registered but NOT dispatched - could be
    transient. Second occurrence (count >= 2) confirms a pattern and
    triggers investigation dispatch.

    Medic v2 dispatch gating (when error_registry available):
        1. count >= 2 threshold (skip first occurrence)
        2. circuit_breaker_allows() - global gate, pauses all dispatch on error storm
        3. should_dispatch(fingerprint) - per-error exponential backoff
    Fallback: legacy per-branch rate limiting (3 per 10 min) if registry unavailable.

    Args:
        branch: Target branch name (e.g., 'FLOW') - REQUIRED
        module: Module that logged the error - REQUIRED
        message: Error message text - REQUIRED
        log_path: Path to source log file
        error_hash: Short ID from registry or legacy 8-char hash - REQUIRED
        timestamp: When error occurred (defaults to now)
        fingerprint: SHA1 fingerprint from error_registry (Medic v2)
        registry_id: Short UUID from error_registry (Medic v2)
        first_seen: ISO timestamp of first occurrence (Medic v2)
        last_seen: ISO timestamp of most recent occurrence (Medic v2)
        count: Registry occurrence count (default: 1). Dispatch requires >= 2.
        **kwargs: Additional event data (ignored)

    Returns:
        None - handlers must not return values

    Note:
        Handler follows silent failure pattern - all exceptions caught.
        NO logger imports (causes infinite recursion with trigger events).
        NO console.print() (handlers must be silent).
    """
    try:
        # Validate required fields
        if not branch or not module or not message or not error_hash:
            return

        # Medic toggle - if disabled, log but do NOT dispatch
        if not _is_medic_enabled():
            _write_suppression_log("Medic OFF - suppressed dispatch for", branch, module, message)
            return

        # Per-branch mute check - muted branches have errors logged but NOT dispatched
        if _is_branch_muted(branch):
            _write_suppression_log("Branch muted - suppressed dispatch for", branch, module, message)
            return

        # Dispatch threshold: count >= 2 required. First occurrence could
        # be transient - only dispatch when the error recurs.
        if count < 2:
            _write_suppression_log(f"First occurrence (count={count}) - waiting for pattern", branch, module, message)
            return

        # Record error for circuit breaker at detection time (not dispatch time)
        if _REGISTRY_DISPATCH_AVAILABLE:
            circuit_breaker_record_error()

        # Callback must be set by module layer before events fire
        if _send_email is None:
            return

        # Convert branch name to email format (FLOW -> @flow)
        recipient = f"@{branch.lower()}"

        # devpulse is protected from auto-triggering
        if recipient == "@devpulse":
            return

        # Validate target branch exists in registry before attempting delivery
        registered_emails = _get_registered_emails()
        if recipient not in registered_emails:
            _write_suppression_log(f"Unknown branch skipped: {recipient}", branch, module, message)
            return

        # --- Dispatch gating ---
        if _REGISTRY_DISPATCH_AVAILABLE and fingerprint:
            # Medic v2: Circuit breaker (global) + per-fingerprint backoff
            if not circuit_breaker_allows():
                _write_suppression_log("Circuit breaker OPEN - suppressed dispatch for", branch, module, message)
                return

            if not registry_should_dispatch(fingerprint):
                _write_rate_log("Backoff active", f"fingerprint {fingerprint[:12]}: {recipient} - {module}, skipping")
                return
        else:
            # Legacy fallback: per-branch rate limiting (Medic v1)
            recent_count = len(
                [ts for ts in _dispatch_timestamps.get(recipient, []) if ts > time.time() - RATE_LIMIT_WINDOW_SECONDS]
            )
            if _is_rate_limited(recipient):
                _write_rate_log("Rate limited", f"{recipient} has {recent_count} recent dispatches, skipping")
                return

        # Default timestamp to now if not provided
        if not timestamp:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Default log_path if not provided
        effective_log_path = log_path if log_path else "unknown"

        # Read log context (2 lines before and after)
        error_log_context = _read_log_context(effective_log_path, message)

        # Build subject line
        email_subject = f"[ERROR] {module} - detected in logs"

        # Build notification message with structured context
        notification_message = _build_notification_message(
            error_hash=error_hash,
            module=module,
            message=message,
            timestamp=timestamp,
            log_path=effective_log_path,
            occurrences=1,
            first_seen=first_seen or timestamp,
            last_seen=last_seen or timestamp,
            log_context=error_log_context,
            fingerprint=fingerprint,
            registry_id=registry_id,
        )

        # Send via callback (set by module layer, trigger isn't a branch so PWD detection fails)
        _send_email(
            to_branch=recipient,
            subject=email_subject,
            message=notification_message,
            auto_execute=True,
            reply_to="@devpulse",
            from_branch="@trigger",
        )

        # Wake the target branch so the email is processed immediately
        try:
            from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

            wake_branch(recipient, fresh=False, sender="@trigger")
        except Exception:
            pass  # Silent — email in inbox as fallback

        json_handler.log_operation("dispatch_sent", {"recipient": recipient})

        # Record dispatch for tracking
        if _REGISTRY_DISPATCH_AVAILABLE and fingerprint:
            # Medic v2: per-fingerprint dispatch tracking
            registry_record_dispatch(fingerprint)
        else:
            # Legacy: per-branch rate limiting
            _record_dispatch(recipient)

    except Exception as exc:
        _log_warning(f"handle_error_detected failed: {exc}")
        return  # Silent failure - handler must not raise
