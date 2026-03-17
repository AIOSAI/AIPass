# =================== AIPass ====================
# Name: error_registry.py
# Description: Structured error tracking and registry for Medic v2
# Version: 2.3.0
# Created: 2026-02-13
# Modified: 2026-02-27
# =============================================

"""
Error Registry Handler - Structured error tracking for Medic v2

Replaces the simple MD5 hash dedup from Medic v1 with a structured
error registry. Errors become first-class objects with fingerprinting,
deduplication, status tracking, and metadata.

Phase 2 adds:
    - Circuit breaker: Pauses all dispatch when error rate exceeds threshold.
      Three states (closed/open/half_open) with exponential cooldown backoff.
    - Per-fingerprint rate limiting: Exponential backoff per error fingerprint
      to prevent repeated dispatch of the same known error.

Architecture:
    Module (medic.py) orchestrates, this handler manages error records.
    Errors are normalized, fingerprinted (SHA1), and stored as structured
    entries in error_registry.json. Circuit breaker and rate limiting state
    is held in-memory (resets on process restart).

Storage:
    trigger/trigger_json/error_registry.json
    Format: {
        "errors": {fingerprint: ErrorEvent_as_dict, ...},
        "metadata": {"version": "2.0.0", "last_updated": "..."}
    }
"""

import hashlib
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


from aipass.prax.apps.modules.logger import get_direct_logger
from aipass.trigger.apps.config import TRIGGER_ROOT
from aipass.trigger.apps.handlers.json import json_handler

logger = get_direct_logger()
REGISTRY_FILE = TRIGGER_ROOT / "trigger_json" / "error_registry.json"
TRIGGER_CONFIG_FILE = TRIGGER_ROOT / "trigger_json" / "trigger_config.json"

VALID_STATUSES = ('new', 'investigating', 'suppressed', 'resolved')
VALID_SEVERITIES = ('low', 'medium', 'high', 'critical')
VALID_FIX_STATUSES = ('none', 'pending_fix', 'fix_requested', 'fix_confirmed')

# Patterns that indicate user errors (bad commands, wrong args) rather
# than system failures.  Matched case-insensitively against the raw message.
_USER_ERROR_PATTERNS: re.Pattern = re.compile(
    r'unknown command|invalid argument|unrecognized|'
    r'missing required argument|usage:|no such command|'
    r'not a valid command|unrecognized option|'
    r'unknown option|too few arguments|too many arguments',
    re.IGNORECASE,
)


@dataclass
class ErrorEvent:
    """Structured error entry for the registry.

    Attributes:
        id: Short UUID4 identifier (first 8 chars)
        fingerprint: SHA1 of normalized error_type + message + component
        error_type: Error class name (e.g., 'ImportError', 'ConnectionError')
        message: Original error message text
        normalized_message: Message stripped of variable data
        component: Branch/module that generated the error
        severity: Error severity level (low, medium, high, critical)
        count: Number of times this fingerprint was seen
        status: Current tracking status (new, investigating, suppressed, resolved)
        first_seen: ISO timestamp of first occurrence
        last_seen: ISO timestamp of most recent occurrence
        log_path: Source log file path
        suppress_reason: Why this error was suppressed (optional)
        source_fix_status: Fix tracking (none, pending_fix, fix_requested, fix_confirmed)
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    fingerprint: str = ""
    error_type: str = ""
    message: str = ""
    normalized_message: str = ""
    component: str = ""
    severity: str = "medium"
    count: int = 1
    status: str = "new"
    first_seen: str = field(default_factory=lambda: datetime.now().isoformat())
    last_seen: str = field(default_factory=lambda: datetime.now().isoformat())
    log_path: str = ""
    suppress_reason: str = ""
    source_fix_status: str = "none"


@dataclass
class CircuitBreakerState:
    """Circuit breaker state tracking.

    Three states control dispatch flow:
    - closed: Normal operation, all dispatches allowed
    - open: Paused, no dispatches until cooldown expires
    - half_open: Testing, allows one dispatch to probe recovery
    """
    state: str = "closed"  # closed, open, half_open
    opened_at: float = 0.0  # time.time() when breaker opened
    cooldown_seconds: int = 300  # Current cooldown (5 min default)
    base_cooldown: int = 300  # Base cooldown for reset
    max_cooldown: int = 3600  # Max cooldown (1 hour)
    recent_errors: list = field(default_factory=list)  # timestamps of recent new errors
    trip_threshold: int = 10  # Errors per window to trip
    trip_window_seconds: int = 60  # Window to count errors in
    summary_sent: bool = False  # Whether summary notification sent for current open state
    half_open_allow: bool = True  # Whether the half_open probe dispatch is still available


# ---------------------------------------------------------------------------
# Circuit Breaker Persistence
# ---------------------------------------------------------------------------

def _save_circuit_breaker_state() -> None:
    """Persist circuit breaker state to trigger_config.json.

    Saves the current breaker state, opened_at timestamp, and cooldown
    under the 'circuit_breaker' key so the state survives process restarts.
    """
    try:
        data: Dict[str, Any] = {}
        if TRIGGER_CONFIG_FILE.exists():
            data = json.loads(TRIGGER_CONFIG_FILE.read_text(encoding='utf-8'))
        data['circuit_breaker'] = {
            'state': _circuit_breaker.state,
            'opened_at': _circuit_breaker.opened_at,
            'cooldown_seconds': _circuit_breaker.cooldown_seconds,
        }
        TRIGGER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        TRIGGER_CONFIG_FILE.write_text(
            json.dumps(data, indent=2), encoding='utf-8'
        )
    except Exception as exc:
        logger.warning("Failed to save circuit breaker state: %s", exc)


def _load_circuit_breaker_state() -> CircuitBreakerState:
    """Load persisted circuit breaker state from trigger_config.json.

    If a valid persisted state exists, restores it into a new
    CircuitBreakerState. Otherwise returns a fresh default instance.

    Returns:
        CircuitBreakerState populated from disk or defaults.
    """
    try:
        if TRIGGER_CONFIG_FILE.exists():
            data = json.loads(TRIGGER_CONFIG_FILE.read_text(encoding='utf-8'))
            cb_data = data.get('circuit_breaker')
            if isinstance(cb_data, dict) and cb_data.get('state') in ('closed', 'open', 'half_open'):
                breaker = CircuitBreakerState()
                breaker.state = cb_data['state']
                breaker.opened_at = float(cb_data.get('opened_at', 0.0))
                breaker.cooldown_seconds = int(cb_data.get('cooldown_seconds', breaker.base_cooldown))
                return breaker
    except Exception as exc:
        logger.warning("Failed to load circuit breaker state: %s", exc)
    return CircuitBreakerState()


def _clear_circuit_breaker_state() -> None:
    """Remove persisted circuit breaker state from trigger_config.json.

    Deletes the 'circuit_breaker' key so restarts start with a clean slate.
    """
    try:
        if TRIGGER_CONFIG_FILE.exists():
            data = json.loads(TRIGGER_CONFIG_FILE.read_text(encoding='utf-8'))
            if 'circuit_breaker' in data:
                del data['circuit_breaker']
                TRIGGER_CONFIG_FILE.write_text(
                    json.dumps(data, indent=2), encoding='utf-8'
                )
    except Exception as exc:
        logger.warning("Failed to clear circuit breaker state: %s", exc)


# Module-level circuit breaker state (restored from disk if available)
_circuit_breaker = _load_circuit_breaker_state()

# Module-level dicts for per-fingerprint dispatch tracking
_fingerprint_dispatch_times: Dict[str, List[float]] = {}  # fingerprint -> [dispatch_timestamps]
_fingerprint_dispatch_count: Dict[str, int] = {}  # fingerprint -> total dispatch count


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

def circuit_breaker_allows() -> bool:
    """Check if the circuit breaker allows dispatch.

    Three states:
    - Closed (normal): All dispatches allowed. Records are checked against
      trip_threshold to determine if breaker should open.
    - Open (paused): No dispatches. Transitions to half_open after cooldown
      period expires.
    - Half-Open (testing): Allow ONE dispatch to test recovery. If it
      resolves, caller should reset to Closed. If another error comes,
      circuit_breaker_record_error() will re-open with doubled cooldown.

    Returns:
        True if dispatch is allowed, False if breaker is blocking
    """
    global _circuit_breaker
    now = time.time()

    if _circuit_breaker.state == "closed":
        return True

    if _circuit_breaker.state == "open":
        elapsed = now - _circuit_breaker.opened_at
        if elapsed >= _circuit_breaker.cooldown_seconds:
            # Cooldown expired - transition to half_open
            # This call IS the probe dispatch, so mark probe as used
            _circuit_breaker.state = "half_open"
            _circuit_breaker.half_open_allow = False
            _circuit_breaker.summary_sent = False
            return True
        return False

    if _circuit_breaker.state == "half_open":
        if _circuit_breaker.half_open_allow:
            _circuit_breaker.half_open_allow = False
            return True
        return False

    return False


def circuit_breaker_record_error() -> None:
    """Record a new error occurrence for circuit breaker tracking.

    Adds the current timestamp to recent_errors. Prunes errors outside
    the trip_window_seconds window. If the count of recent errors exceeds
    trip_threshold, trips the breaker to open state.

    In half_open state, any error re-opens the breaker with doubled
    cooldown (up to max_cooldown).
    """
    global _circuit_breaker
    now = time.time()

    if _circuit_breaker.state == "half_open":
        # Error during probe - re-open with doubled cooldown
        new_cooldown = min(
            _circuit_breaker.cooldown_seconds * 2,
            _circuit_breaker.max_cooldown
        )
        _circuit_breaker.state = "open"
        _circuit_breaker.opened_at = now
        _circuit_breaker.cooldown_seconds = new_cooldown
        _circuit_breaker.summary_sent = False
        _circuit_breaker.recent_errors = [now]
        _save_circuit_breaker_state()
        return

    # Add timestamp and prune old entries
    _circuit_breaker.recent_errors.append(now)
    cutoff = now - _circuit_breaker.trip_window_seconds
    _circuit_breaker.recent_errors = [
        t for t in _circuit_breaker.recent_errors if t >= cutoff
    ]

    # Check if threshold exceeded -> trip
    if len(_circuit_breaker.recent_errors) >= _circuit_breaker.trip_threshold:
        circuit_breaker_trip(reason="threshold_exceeded")


def circuit_breaker_trip(reason: str = "") -> None:
    """Manually trip the circuit breaker to open state.

    Sets state to open with the current cooldown_seconds. Resets
    summary_sent flag so a new summary can be generated.
    Persists state to trigger_config.json for restart survival.

    Args:
        reason: Optional reason string for logging/diagnostics
    """
    global _circuit_breaker
    _circuit_breaker.state = "open"
    _circuit_breaker.opened_at = time.time()
    _circuit_breaker.summary_sent = False
    _save_circuit_breaker_state()


def circuit_breaker_reset() -> None:
    """Reset circuit breaker to closed state.

    Restores all state to defaults: closed state, base cooldown,
    empty recent_errors list, and cleared flags.
    Clears persisted state from trigger_config.json.
    """
    global _circuit_breaker
    _circuit_breaker.state = "closed"
    _circuit_breaker.opened_at = 0.0
    _circuit_breaker.cooldown_seconds = _circuit_breaker.base_cooldown
    _circuit_breaker.recent_errors = []
    _circuit_breaker.summary_sent = False
    _circuit_breaker.half_open_allow = True
    _clear_circuit_breaker_state()


def get_circuit_breaker_status() -> dict:
    """Get current circuit breaker state as a dictionary.

    Returns:
        Dict with keys: state, opened_at, cooldown_seconds,
        recent_error_count, summary_sent
    """
    return {
        "state": _circuit_breaker.state,
        "opened_at": _circuit_breaker.opened_at,
        "cooldown_seconds": _circuit_breaker.cooldown_seconds,
        "recent_error_count": len(_circuit_breaker.recent_errors),
        "summary_sent": _circuit_breaker.summary_sent,
    }


# ---------------------------------------------------------------------------
# Per-Fingerprint Rate Limiting (Exponential Backoff)
# ---------------------------------------------------------------------------

def get_backoff_seconds(dispatch_count: int) -> int:
    """Calculate backoff duration based on dispatch count.

    Backoff schedule:
    - 0 previous dispatches: 0 seconds (dispatch immediately)
    - 1 previous dispatch: 300 seconds (5 minutes)
    - 2 previous dispatches: 900 seconds (15 minutes)
    - 3 previous dispatches: 2700 seconds (45 minutes)
    - 4+ previous dispatches: 7200 seconds (2 hours)

    Args:
        dispatch_count: How many times this fingerprint has been dispatched

    Returns:
        Seconds to wait before next dispatch
    """
    if dispatch_count <= 0:
        return 0
    if dispatch_count == 1:
        return 300
    if dispatch_count == 2:
        return 900
    if dispatch_count == 3:
        return 2700
    return 7200


def should_dispatch(fingerprint: str) -> bool:
    """Check if this fingerprint should be dispatched based on exponential backoff.

    Uses the dispatch history for this fingerprint to determine if enough
    time has elapsed since the last dispatch according to the backoff
    schedule.

    Args:
        fingerprint: Error fingerprint to check

    Returns:
        True if enough time has passed since last dispatch for this fingerprint
    """
    count = _fingerprint_dispatch_count.get(fingerprint, 0)
    if count == 0:
        return True

    times = _fingerprint_dispatch_times.get(fingerprint, [])
    if not times:
        return True

    last_dispatch = max(times)
    backoff = get_backoff_seconds(count)
    elapsed = time.time() - last_dispatch

    return elapsed >= backoff


def record_dispatch(fingerprint: str) -> None:
    """Record that a dispatch was sent for this fingerprint.

    Appends the current timestamp to the dispatch history and increments
    the total dispatch count for this fingerprint.

    Args:
        fingerprint: Error fingerprint that was dispatched
    """
    now = time.time()
    if fingerprint not in _fingerprint_dispatch_times:
        _fingerprint_dispatch_times[fingerprint] = []
    _fingerprint_dispatch_times[fingerprint].append(now)
    _fingerprint_dispatch_count[fingerprint] = \
        _fingerprint_dispatch_count.get(fingerprint, 0) + 1


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------

def normalize_message(message: str) -> str:
    """Normalize an error message by stripping variable data.

    Strips line numbers, timestamps, absolute paths, UUIDs, hex hashes,
    port numbers, and numeric IDs to produce a stable message for
    fingerprinting.

    Args:
        message: Raw error message text

    Returns:
        Normalized message with variable data replaced by placeholders
    """
    normalized = message

    # Strip ISO timestamps (2026-02-13T10:30:45.123456, 2026-02-13 10:30:45)
    normalized = re.sub(
        r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:[+-]\d{2}:?\d{2}|Z)?',
        '<timestamp>',
        normalized
    )

    # Strip date-only patterns (2026-02-13)
    normalized = re.sub(r'\d{4}-\d{2}-\d{2}', '<date>', normalized)

    # Strip absolute paths (any /path/to/something)
    normalized = re.sub(r'/[\w./-]+', '<path>', normalized)

    # Strip line numbers ("line 42" -> "line N")
    normalized = re.sub(r'\bline \d+\b', 'line N', normalized, flags=re.IGNORECASE)

    # Strip UUIDs (8-4-4-4-12 hex format)
    normalized = re.sub(
        r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
        '<uuid>',
        normalized
    )

    # Strip hex hashes (8+ hex chars that look like hashes)
    normalized = re.sub(r'\b[0-9a-fA-F]{8,}\b', '<hash>', normalized)

    # Strip port numbers (:8080, :3000, :443)
    normalized = re.sub(r':\d{2,5}\b', ':<port>', normalized)

    # Strip standalone numeric IDs (pure numbers 3+ digits)
    normalized = re.sub(r'\b\d{3,}\b', '<id>', normalized)

    # Collapse multiple spaces
    normalized = re.sub(r'\s+', ' ', normalized).strip()

    return normalized


def compute_fingerprint(error_type: str, normalized_msg: str, component: str) -> str:
    """Compute a SHA1 fingerprint for error deduplication.

    Creates a deterministic hash from the combination of error type,
    normalized message, and component. This allows the same logical
    error from the same component to be recognized across occurrences.

    Args:
        error_type: Error class name (e.g., 'ImportError')
        normalized_msg: Message after normalize_message() processing
        component: Branch/module identifier (e.g., 'FLOW')

    Returns:
        Full SHA1 hex digest (40 chars). Use [:12] for display.
    """
    content = f"{error_type}:{normalized_msg}:{component}"
    return hashlib.sha1(content.encode('utf-8')).hexdigest()


# ---------------------------------------------------------------------------
# Registry I/O
# ---------------------------------------------------------------------------

def _load_registry() -> dict:
    """Load the error registry from disk.

    Returns:
        Registry dict with 'errors' and 'metadata' keys.
        Returns empty registry structure on read failure.
    """
    try:
        if REGISTRY_FILE.exists():
            data = json.loads(REGISTRY_FILE.read_text(encoding='utf-8'))
            if isinstance(data, dict) and 'errors' in data:
                return data
    except Exception:
        pass
    return {
        "errors": {},
        "metadata": {
            "version": "1.0.0",
            "last_updated": datetime.now().isoformat()
        }
    }


def _save_registry(data: dict) -> bool:
    """Save the error registry to disk.

    Args:
        data: Full registry dict to persist

    Returns:
        True on success, False on failure
    """
    try:
        data["metadata"]["last_updated"] = datetime.now().isoformat()
        REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        REGISTRY_FILE.write_text(
            json.dumps(data, indent=2), encoding='utf-8'
        )
        return True
    except Exception as exc:
        logger.warning("Failed to save error registry to %s: %s", REGISTRY_FILE, exc)
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def report(
    error_type: str,
    message: str,
    component: str,
    log_path: str = "",
    severity: str = "medium"
) -> dict:
    """Report an error to the registry.

    Normalizes the message, computes a fingerprint, and either creates
    a new entry or increments the count on an existing one.

    Args:
        error_type: Error class name (e.g., 'ImportError', 'ConnectionError')
        message: Original error message text
        component: Branch/module that generated the error (e.g., 'FLOW')
        log_path: Path to source log file (optional)
        severity: Error severity - low, medium, high, critical (default: medium)

    Returns:
        Dict of the error entry with an additional 'is_new' bool flag.
        Returns minimal error dict on failure.
    """
    try:
        # Validate severity
        if severity not in VALID_SEVERITIES:
            severity = "medium"

        normalized = normalize_message(message)
        fingerprint = compute_fingerprint(error_type, normalized, component)

        # User-error rejection: errors that look like bad commands or
        # invalid arguments are auto-suppressed to avoid noisy dispatch.
        is_user_error = bool(_USER_ERROR_PATTERNS.search(message))

        registry = _load_registry()
        now = datetime.now().isoformat()

        if fingerprint in registry["errors"]:
            # Existing error - increment count and update last_seen
            entry = registry["errors"][fingerprint]
            entry["count"] = entry.get("count", 1) + 1
            entry["last_seen"] = now
            # Update log_path if provided (might be from a different log file)
            if log_path:
                entry["log_path"] = log_path
            # Auto-suppress user errors that were previously unsuppressed
            if is_user_error and entry.get("status") != "suppressed":
                entry["status"] = "suppressed"
                entry["suppress_reason"] = "user_error"
            _save_registry(registry)
            result = dict(entry)
            result["is_new"] = False
            json_handler.log_operation("error_registered", {"fingerprint": fingerprint[:12], "count": entry["count"]})
            return result
        else:
            # New error - create entry
            initial_status = "suppressed" if is_user_error else "new"
            initial_suppress_reason = "user_error" if is_user_error else ""

            event = ErrorEvent(
                fingerprint=fingerprint,
                error_type=error_type,
                message=message,
                normalized_message=normalized,
                component=component,
                severity=severity,
                count=1,
                status=initial_status,
                first_seen=now,
                last_seen=now,
                log_path=log_path,
                suppress_reason=initial_suppress_reason,
                source_fix_status="none"
            )
            entry_dict = asdict(event)
            registry["errors"][fingerprint] = entry_dict
            _save_registry(registry)
            result = dict(entry_dict)
            result["is_new"] = True
            json_handler.log_operation("error_registered", {"fingerprint": fingerprint[:12], "count": 1})
            return result

    except Exception:
        return {
            "error_type": error_type,
            "message": message,
            "component": component,
            "is_new": True,
            "status": "new",
            "count": 1
        }


def query(
    status: Optional[str] = None,
    component: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50
) -> list:
    """Query the error registry with optional filters.

    Filters errors by any combination of status, component, and severity.
    Results are sorted by last_seen descending (most recent first).

    Args:
        status: Filter by status (new, investigating, suppressed, resolved)
        component: Filter by component/branch name
        severity: Filter by severity (low, medium, high, critical)
        limit: Maximum number of results to return (default: 50)

    Returns:
        List of matching error entry dicts, sorted by last_seen descending
    """
    try:
        registry = _load_registry()
        entries = list(registry["errors"].values())

        # Apply filters
        if status is not None:
            entries = [e for e in entries if e.get("status") == status]
        if component is not None:
            entries = [e for e in entries
                       if e.get("component", "").upper() == component.upper()]
        if severity is not None:
            entries = [e for e in entries if e.get("severity") == severity]

        # Sort by last_seen descending
        entries.sort(key=lambda e: e.get("last_seen", ""), reverse=True)

        return entries[:limit]

    except Exception:
        return []


def update_status(fingerprint: str, new_status: str, reason: str = "") -> bool:
    """Update the status of an error entry.

    Supports the lifecycle: new -> investigating -> resolved/suppressed.
    If suppressing, stores the reason in suppress_reason.

    Args:
        fingerprint: Full or prefix fingerprint to match
        new_status: Target status (new, investigating, suppressed, resolved)
        reason: Reason for status change (stored in suppress_reason if suppressing)

    Returns:
        True on success, False if fingerprint not found or invalid status
    """
    try:
        if new_status not in VALID_STATUSES:
            return False

        registry = _load_registry()
        entry = _find_entry(registry, fingerprint)

        if entry is None:
            return False

        entry["status"] = new_status
        if new_status == "suppressed" and reason:
            entry["suppress_reason"] = reason
        elif reason:
            entry["suppress_reason"] = reason

        return _save_registry(registry)

    except Exception:
        return False


def get_entry(fingerprint: str) -> Optional[dict]:
    """Get a single error entry by fingerprint or prefix.

    Supports prefix matching - if the provided string is shorter than
    40 chars, matches against the beginning of stored fingerprints.

    Args:
        fingerprint: Full fingerprint (40 chars) or prefix to match

    Returns:
        Error entry dict, or None if not found
    """
    try:
        registry = _load_registry()
        return _find_entry(registry, fingerprint)
    except Exception:
        return None


def clear_resolved(days: int = 7) -> int:
    """Remove resolved entries older than N days.

    Cleans up the registry by removing entries with status='resolved'
    whose last_seen timestamp is older than the specified number of days.

    Args:
        days: Age threshold in days (default: 7)

    Returns:
        Count of removed entries
    """
    try:
        registry = _load_registry()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        removed = 0

        fingerprints_to_remove = []
        for fp, entry in registry["errors"].items():
            if entry.get("status") == "resolved":
                last_seen = entry.get("last_seen", "")
                if last_seen and last_seen < cutoff:
                    fingerprints_to_remove.append(fp)

        for fp in fingerprints_to_remove:
            del registry["errors"][fp]
            removed += 1

        if removed > 0:
            _save_registry(registry)

        return removed

    except Exception:
        return 0


def get_stats() -> dict:
    """Get summary statistics from the error registry.

    Returns:
        Dict with:
            - total: Total number of tracked errors
            - by_status: Count per status (new, investigating, etc.)
            - by_component: Count per component/branch
            - by_severity: Count per severity level
    """
    try:
        registry = _load_registry()
        entries = list(registry["errors"].values())

        by_status: Dict[str, int] = {}
        by_component: Dict[str, int] = {}
        by_severity: Dict[str, int] = {}

        for entry in entries:
            status = entry.get("status", "unknown")
            by_status[status] = by_status.get(status, 0) + 1

            component = entry.get("component", "unknown")
            by_component[component] = by_component.get(component, 0) + 1

            severity = entry.get("severity", "unknown")
            by_severity[severity] = by_severity.get(severity, 0) + 1

        return {
            "total": len(entries),
            "by_status": by_status,
            "by_component": by_component,
            "by_severity": by_severity
        }

    except Exception:
        return {
            "total": 0,
            "by_status": {},
            "by_component": {},
            "by_severity": {}
        }


def update_source_fix_status(fingerprint: str, fix_status: str) -> bool:
    """Update the source fix status of an error entry.

    Tracks whether the source branch has been notified and fixed
    the underlying issue.

    Args:
        fingerprint: Full or prefix fingerprint to match
        fix_status: One of: none, pending_fix, fix_requested, fix_confirmed

    Returns:
        True on success
    """
    if fix_status not in VALID_FIX_STATUSES:
        return False
    try:
        registry = _load_registry()
        entry = _find_entry(registry, fingerprint)
        if entry is None:
            return False
        entry["source_fix_status"] = fix_status
        return _save_registry(registry)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _find_entry(registry: dict, fingerprint: str) -> Optional[dict]:
    """Find an entry by exact fingerprint or prefix match.

    Args:
        registry: Loaded registry dict
        fingerprint: Full fingerprint or prefix

    Returns:
        Reference to the entry dict within the registry, or None
    """
    # Exact match first
    if fingerprint in registry["errors"]:
        return registry["errors"][fingerprint]

    # Prefix match (for short fingerprint lookups like [:12])
    if len(fingerprint) < 40:
        for fp, entry in registry["errors"].items():
            if fp.startswith(fingerprint):
                return entry

    return None
