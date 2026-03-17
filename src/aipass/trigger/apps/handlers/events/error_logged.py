# =================== AIPass ====================
# Name: error_logged.py
# Description: Legacy error logged event handler with medic gating (deprecated)
# Version: 2.0.0
# Created: 2026-01-31
# Modified: 2026-02-25
# =============================================

"""
Error Logged Event Handler (DEPRECATED)

Legacy handler for error_logged events. The primary error dispatch pipeline
is now error_detected.py (Medic v2) which provides circuit breaker, per-fingerprint
backoff, and registry-based deduplication.

This handler remains for backward compatibility with code that fires error_logged
events directly. It now includes full medic gating (medic_enabled, branch_muted,
rate limiting, devpulse protection) to prevent bypass.

Event data expected:
    - branch: Branch where error occurred (e.g., FLOW)
    - message: Error message text
    - error_hash: Unique hash for deduplication
    - timestamp: When the error occurred
    - log_file: Path to log file
    - source_module: Module that logged the error
    - level: Log level (always 'error' for this handler)
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from aipass.trigger.apps.config import TRIGGER_ROOT
from aipass.trigger.apps.handlers.json import json_handler

def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()

_REPO_ROOT = _find_repo_root()

TRIGGER_CONFIG_FILE = TRIGGER_ROOT / "trigger_json" / "trigger_config.json"
BRANCH_REGISTRY_FILE = _REPO_ROOT / "BRANCH_REGISTRY.json"
SUPPRESSED_LOG = TRIGGER_ROOT / "logs" / "medic_suppressed.log"

# Legacy rate limiting
_dispatch_timestamps: Dict[str, List[float]] = {}
MAX_DISPATCHES_PER_WINDOW = 3
RATE_LIMIT_WINDOW_SECONDS = 600  # 10 minutes


def _is_medic_enabled() -> bool:
    """Check if medic dispatch is enabled globally.

    Reads medic_enabled from trigger_config.json.
    Defaults to True if config is missing or unreadable.

    Returns:
        True if medic dispatch is enabled
    """
    try:
        if TRIGGER_CONFIG_FILE.exists():
            data = json.loads(TRIGGER_CONFIG_FILE.read_text(encoding='utf-8'))
            return bool(data.get('config', {}).get('medic_enabled', True))
    except Exception:
        return True
    return True


def _is_branch_muted(branch_name: str) -> bool:
    """Check if a specific branch is muted for medic dispatch.

    Reads muted_branches list from trigger_config.json.

    Args:
        branch_name: Branch name (case-insensitive)

    Returns:
        True if branch is in the muted list
    """
    try:
        if TRIGGER_CONFIG_FILE.exists():
            data = json.loads(TRIGGER_CONFIG_FILE.read_text(encoding='utf-8'))
            muted = data.get('config', {}).get('muted_branches', [])
            return branch_name.lower() in [b.lower() for b in muted]
    except Exception:
        return False
    return False


def _get_registered_emails() -> set:
    """Read registered branch emails from BRANCH_REGISTRY.json.

    Returns:
        Set of registered email addresses (e.g., {'@flow', '@drone'})
    """
    try:
        if BRANCH_REGISTRY_FILE.exists():
            data = json.loads(BRANCH_REGISTRY_FILE.read_text(encoding='utf-8'))
            return {b["email"] for b in data.get("branches", [])}
    except Exception:
        return set()
    return set()


def _is_rate_limited(branch_email: str) -> bool:
    """Check if a branch has exceeded the dispatch rate limit.

    Args:
        branch_email: Target branch email (e.g., '@flow')

    Returns:
        True if branch has hit the limit (3 dispatches in 10 minutes)
    """
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS

    if branch_email not in _dispatch_timestamps:
        _dispatch_timestamps[branch_email] = []

    _dispatch_timestamps[branch_email] = [
        ts for ts in _dispatch_timestamps[branch_email] if ts > cutoff
    ]

    return len(_dispatch_timestamps[branch_email]) >= MAX_DISPATCHES_PER_WINDOW


def _record_dispatch(branch_email: str) -> None:
    """Record a dispatch timestamp for rate limiting.

    Args:
        branch_email: Target branch email (e.g., '@flow')
    """
    if branch_email not in _dispatch_timestamps:
        _dispatch_timestamps[branch_email] = []
    _dispatch_timestamps[branch_email].append(time.time())


def _log_suppression(reason: str, branch: str, source_module: str, message: str) -> None:
    """Log a suppressed dispatch to medic_suppressed.log.

    Args:
        reason: Why dispatch was suppressed
        branch: Target branch name
        source_module: Module that logged the error
        message: Error message (truncated to 100 chars)
    """
    try:
        SUPPRESSED_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(SUPPRESSED_LOG, 'a') as f:
            f.write(
                f"{datetime.now().isoformat()} | "
                f"{reason} - suppressed dispatch for {branch}: "
                f"{source_module} - {message[:100]}\n"
            )
    except Exception:
        return


def _build_notification_message(
    error_hash: str,
    source_module: str,
    message: str,
    timestamp: str,
    log_file: str
) -> str:
    """Build error notification message with investigation instructions.

    Args:
        error_hash: Unique error identifier
        source_module: Module that logged the error
        message: Error message text
        timestamp: When error occurred
        log_file: Path to source log file

    Returns:
        Formatted message string
    """
    return f"""Error detected - investigate and respond.

Error ID: {error_hash}
Module: {source_module}
Timestamp: {timestamp}
Log file: {log_file}

Error message:
{message}

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

REPORT TO @devpulse:
  ai_mail send @devpulse "ERROR {error_hash[:8]} - [STATUS]" "Findings..."
"""


def handle_error_logged(
    branch: str | None = None,
    message: str | None = None,
    error_hash: str | None = None,
    timestamp: str | None = None,
    log_file: str | None = None,
    source_module: str | None = None,
    module_name: str | None = None,
    level: str | None = None,  # noqa: ARG001
    **kwargs: Any  # noqa: ARG001
) -> None:
    """Handle error_logged event with full medic gating.

    DEPRECATED: This is the legacy error notification handler. The primary
    pipeline is error_detected.py (Medic v2). This handler remains for
    backward compatibility with code that fires error_logged events.

    Gating (matches error_detected.py):
        1. medic_enabled check (global toggle)
        2. branch_muted check (per-branch suppression)
        3. devpulse protection (never auto-trigger)
        4. Branch validation (unknown branches logged + skipped)
        5. Rate limiting (3 per 10 minutes per branch)

    Args:
        branch: Branch where error occurred - REQUIRED
        message: Error message text - REQUIRED
        error_hash: Unique error identifier - REQUIRED
        timestamp: When error occurred (defaults to now)
        log_file: Path to source log file
        source_module: Module that logged the error
        module_name: Deprecated alias for source_module
        level: Log level (for reference, unused)
        **kwargs: Additional event data (ignored)
    """
    try:
        if not branch or not message or not error_hash:
            return

        # Resolve source_module from either parameter name
        effective_module = source_module or module_name or "unknown"

        # --- Medic gating (FPLAN-0371 Phase 1) ---

        # Gate 1: Global medic toggle
        if not _is_medic_enabled():
            _log_suppression("Medic OFF", branch, effective_module, message)
            return

        # Gate 2: Per-branch mute
        if _is_branch_muted(branch):
            _log_suppression("Branch muted", branch, effective_module, message)
            return

        # Gate 3: Convert branch name to email format
        recipient = f"@{branch.lower()}"

        # devpulse is protected from auto-triggering
        if recipient == '@devpulse':
            return

        # Gate 4: Validate target branch exists in registry
        registered_emails = _get_registered_emails()
        if recipient not in registered_emails:
            _log_suppression("Unknown branch skipped", branch, effective_module, message)
            return

        # Gate 5: Rate limiting (3 dispatches per 10 minutes per branch)
        if _is_rate_limited(recipient):
            _log_suppression("Rate limited", branch, effective_module, message)
            return

        # --- Dispatch ---

        try:
            from aipass.ai_mail.apps.modules.email import deliver_email_to_branch
        except ImportError:
            return

        effective_timestamp = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        effective_log_file = log_file or "unknown"

        email_subject = f"[ERROR] {effective_module} - investigation needed"

        notification_message = _build_notification_message(
            error_hash=error_hash,
            source_module=effective_module,
            message=message,
            timestamp=effective_timestamp,
            log_file=effective_log_file
        )

        email_data = {
            "from": "@trigger",
            "from_name": "TRIGGER",
            "to": recipient,
            "subject": email_subject,
            "message": f"⚡ DISPATCH TASK - READ THIS FIRST ⚡\n\n{notification_message}",
            "timestamp": effective_timestamp,
        }
        deliver_email_to_branch(recipient, email_data)

        # Record dispatch for rate limiting
        _record_dispatch(recipient)

        json_handler.log_operation("error_logged_event", {"success": True})

    except Exception:
        return
