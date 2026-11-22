# =================== AIPass ====================
# Name: error_registry.py
# Description: Structured error tracking and registry for Medic v2
# Version: 2.12.0
# Created: 2026-02-13
# Modified: 2026-11-22
# =============================================

"""
Error Registry Handler - Structured error tracking for Medic v2
"""

import hashlib
import json
import re
import time
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Iterator, Optional, Tuple


from aipass.prax import logger
from aipass.trigger.apps.config import TRIGGER_JSON_DIR, atomic_write_json, json_file_lock
from aipass.trigger.apps.handlers.json import json_handler

REGISTRY_FILE = TRIGGER_JSON_DIR / "error_registry.json"
CB_STATE_FILE = TRIGGER_JSON_DIR / "trigger_cb_state.json"

VALID_STATUSES = ("new", "investigating", "suppressed", "resolved")
VALID_SEVERITIES = ("low", "medium", "high", "critical")
VALID_FIX_STATUSES = ("none", "pending_fix", "fix_requested", "fix_confirmed")

# A line's own identity: fault[KEY], KEY holding no whitespace and no closing bracket. Hooks pins this text.
FAULT_MARKER: re.Pattern = re.compile(r"fault\[([^\s\]]+)\]")

# Breaker policy: counts would-be mails, never log lines.
RECIPIENT_CAP = 5
RECIPIENT_WINDOW_SECONDS = 600


@dataclass
class ErrorEvent:
    """Structured error entry for the registry."""

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
    """Circuit breaker state tracking: closed, open, or half_open (one probe dispatch)."""

    state: str = "closed"
    opened_at: float = 0.0
    cooldown_seconds: int = 300
    base_cooldown: int = 300
    max_cooldown: int = 3600
    recent_sends: list = field(default_factory=list)
    trip_threshold: int = 10
    trip_window_seconds: int = 60
    summary_sent: bool = False
    half_open_allow: bool = True
    probe_at: float = 0.0
    held: dict = field(default_factory=dict)


def _save_circuit_breaker_state(breaker: CircuitBreakerState, per_fingerprint: dict) -> None:
    """Write breaker + per-fingerprint state to trigger_cb_state.json; the caller holds the lock."""
    state_data = {
        "circuit_breaker": {
            "state": breaker.state,
            "opened_at": breaker.opened_at,
            "cooldown_seconds": breaker.cooldown_seconds,
            "recent_sends": breaker.recent_sends,
            "summary_sent": breaker.summary_sent,
            "half_open_allow": breaker.half_open_allow,
            "probe_at": breaker.probe_at,
            "held": breaker.held,
        },
        "per_fingerprint": per_fingerprint,
    }
    try:
        atomic_write_json(CB_STATE_FILE, state_data)
    except Exception as exc:
        raise RuntimeError(f"circuit breaker state unsaved ({CB_STATE_FILE.name}): {exc}") from exc


def _load_circuit_breaker_state() -> Tuple[CircuitBreakerState, dict]:
    """Load the breaker and per-fingerprint {fp: {last_dispatch, count}} from trigger_cb_state.json."""
    breaker = CircuitBreakerState()
    per_fingerprint: dict = {}
    try:
        if not CB_STATE_FILE.exists():
            return breaker, per_fingerprint
        raw = CB_STATE_FILE.read_text(encoding="utf-8").strip()
        if not raw:
            return breaker, per_fingerprint
        data = json.loads(raw)
        if isinstance(data.get("per_fingerprint"), dict):
            per_fingerprint = data["per_fingerprint"]
        cb_data = data.get("circuit_breaker")
        if not isinstance(cb_data, dict) or cb_data.get("state") not in ("closed", "open", "half_open"):
            return breaker, per_fingerprint
        breaker.state = cb_data["state"]
        breaker.opened_at = float(cb_data.get("opened_at", 0.0))
        breaker.cooldown_seconds = int(cb_data.get("cooldown_seconds", breaker.base_cooldown))
        # A pre-2.9 file's recent_errors are line times, not sends: they are not carried over.
        sends = cb_data.get("recent_sends", [])
        breaker.recent_sends = [[float(t), str(r), str(fp), str(note)] for t, r, fp, note in sends]
        breaker.held = dict(cb_data.get("held", {}))
        breaker.probe_at = float(cb_data.get("probe_at", 0.0))
        breaker.summary_sent = bool(cb_data.get("summary_sent", False))
        breaker.half_open_allow = bool(cb_data.get("half_open_allow", True))
    except Exception as exc:
        raise RuntimeError(f"circuit breaker state unreadable ({CB_STATE_FILE.name}): {exc}") from exc
    return breaker, per_fingerprint


@contextmanager
def _cb_state() -> Iterator[Tuple[CircuitBreakerState, dict]]:
    """Load, let the caller change, and save the breaker file under its lock.

    The file is the truth: the daemon, a CLI reset and a ci poll each see the others' writes.
    """
    stack = ExitStack()
    try:
        stack.enter_context(json_file_lock(CB_STATE_FILE))
        locked = True
    except Exception as exc:
        # Unlocked, the state is still read but never written: a blind write could drop another's change.
        logger.warning("Failed to lock circuit breaker state: %s", exc)
        locked = False
    with stack:
        breaker, per_fingerprint = _load_circuit_breaker_state()
        before = (asdict(breaker), json.dumps(per_fingerprint, sort_keys=True))
        yield breaker, per_fingerprint
        if locked and before != (asdict(breaker), json.dumps(per_fingerprint, sort_keys=True)):
            _save_circuit_breaker_state(breaker, per_fingerprint)


def _close(breaker: CircuitBreakerState) -> None:
    """Return the breaker to closed with the base cooldown; held mail stays with its recipient."""
    breaker.state = "closed"
    breaker.opened_at = 0.0
    breaker.cooldown_seconds = breaker.base_cooldown
    breaker.recent_sends = []
    breaker.summary_sent = False
    breaker.half_open_allow = True


def _hold(breaker: CircuitBreakerState, recipient: str, fingerprint: str, note: str, now: float) -> None:
    """Keep a refused mail on its recipient's list, so it rides in that branch's next mail."""
    row = breaker.held.setdefault(recipient, {}).setdefault(fingerprint, {"note": note, "count": 0, "first_held": now})
    row["count"] += 1
    row["note"] = note


def dispatch_gate(recipient: str, fingerprint: str, note: str, now: Optional[float] = None) -> str:
    """The one breaker gate for every fingerprinted mail; call it only where a mail would go.

    Answers send, probe, held_cap, held_open or tripped (held, and the @devpulse summary is owed).
    Only this gate moves open to half_open; a status read never does. `now` is a test seam.
    """
    now = time.time() if now is None else now
    with _cb_state() as (breaker, _):
        breaker.recent_sends = [s for s in breaker.recent_sends if s[0] >= now - RECIPIENT_WINDOW_SECONDS]
        if breaker.state == "open" and now - breaker.opened_at >= breaker.cooldown_seconds:
            breaker.state = "half_open"
            breaker.half_open_allow = True
        # A probe whose send never reported back (a raise, a queue) is replaced, or half_open holds forever.
        lost = breaker.state == "half_open" and not breaker.half_open_allow
        if lost and now - breaker.probe_at >= breaker.base_cooldown:
            breaker.half_open_allow = True
        if breaker.state == "open" or (breaker.state == "half_open" and not breaker.half_open_allow):
            _hold(breaker, recipient, fingerprint, note, now)
            return "held_open" if breaker.summary_sent else "tripped"
        mine = {s[2] for s in breaker.recent_sends if s[1] == recipient}
        if fingerprint not in mine and len(mine) >= RECIPIENT_CAP:
            _hold(breaker, recipient, fingerprint, note, now)
            return "held_cap"
        if breaker.state == "half_open":
            breaker.half_open_allow = False
            breaker.probe_at = now
            breaker.recent_sends.append([now, recipient, fingerprint, note])
            return "probe"
        fleet = {(s[1], s[2]) for s in breaker.recent_sends if s[0] >= now - breaker.trip_window_seconds}
        if len(fleet | {(recipient, fingerprint)}) >= breaker.trip_threshold:
            logger.info("Circuit breaker tripped: threshold_exceeded")
            breaker.state = "open"
            breaker.opened_at = now
            breaker.summary_sent = False
            _hold(breaker, recipient, fingerprint, note, now)
            return "tripped"
        breaker.recent_sends.append([now, recipient, fingerprint, note])
        return "send"


def circuit_breaker_held(recipient: str) -> Dict[str, dict]:
    """The mails held for this recipient, {fingerprint: {note, count, first_held}}."""
    return dict(_load_circuit_breaker_state()[0].held.get(recipient, {}))


def circuit_breaker_delivered(recipient: str, fingerprints: list) -> None:
    """A mail went: drop what rode in it from the held list, and a spent probe closes the breaker."""
    with _cb_state() as (breaker, _):
        held = breaker.held.get(recipient, {})
        for fingerprint in fingerprints:
            held.pop(fingerprint, None)
        if not held:
            breaker.held.pop(recipient, None)
        if breaker.state == "half_open" and not breaker.half_open_allow:
            _close(breaker)


def circuit_breaker_send_failed(now: Optional[float] = None) -> None:
    """A failed probe reopens with doubled cooldown; any other failed send leaves the state alone."""
    with _cb_state() as (breaker, _):
        if breaker.state == "half_open" and not breaker.half_open_allow:
            breaker.state = "open"
            breaker.opened_at = time.time() if now is None else now
            breaker.cooldown_seconds = min(breaker.cooldown_seconds * 2, breaker.max_cooldown)


def circuit_breaker_summary() -> str:
    """The open breaker's account for @devpulse: the sends that tripped it and every mail it holds."""
    breaker = _load_circuit_breaker_state()[0]
    sent = [f"  {s[1]} {s[2][:12]} {s[3]}" for s in breaker.recent_sends]
    held = [
        f"  {recipient} {fp[:12]} x{row['count']} {row['note']}"
        for recipient, rows in breaker.held.items()
        for fp, row in rows.items()
    ]
    return (
        f"Medic's circuit breaker opened: {breaker.trip_threshold} distinct mails in "
        f"{breaker.trip_window_seconds}s. Mail is held for {breaker.cooldown_seconds}s, then one probe.\n\n"
        "Recent sends:\n" + ("\n".join(sent) or "  (none)") + "\n\nHeld:\n" + ("\n".join(held) or "  (none)") + "\n"
    )


def circuit_breaker_summary_sent() -> None:
    """Mark this opening's summary delivered: one per opening."""
    with _cb_state() as (breaker, _):
        breaker.summary_sent = True


def circuit_breaker_reset() -> None:
    """Reset circuit breaker to closed state; per-fingerprint backoff is kept."""
    with _cb_state() as (breaker, _):
        _close(breaker)


def get_circuit_breaker_status(now: Optional[float] = None) -> dict:
    """Get current circuit breaker state as a dictionary."""
    if now is None:
        now = time.time()
    # A read, never a transition: only dispatch_gate moves open to half_open.
    breaker = _load_circuit_breaker_state()[0]
    remaining = 0
    if breaker.state == "open":
        remaining = max(0, int(breaker.cooldown_seconds - (now - breaker.opened_at)))
    return {
        "state": breaker.state,
        "opened_at": breaker.opened_at,
        "cooldown_seconds": breaker.cooldown_seconds,
        "recent_send_count": len(breaker.recent_sends),
        "held_count": sum(len(rows) for rows in breaker.held.values()),
        "summary_sent": breaker.summary_sent,
        "remaining_seconds": remaining,
    }


def get_backoff_seconds(dispatch_count: int) -> int:
    """Calculate backoff duration based on dispatch count."""
    if dispatch_count <= 0:
        return 0
    if dispatch_count == 1:
        return 300
    if dispatch_count == 2:
        return 900
    if dispatch_count == 3:
        return 2700
    return 7200


def get_dispatch_count(fingerprint: str) -> int:
    """Return how many times this fingerprint has been dispatched.

    The escalation digest reads it to tell "owner told, still happening" from "not told yet".
    """
    return int(_load_circuit_breaker_state()[1].get(fingerprint, {}).get("count", 0))


def is_suppressed(fingerprint: str) -> bool:
    """Check whether a fingerprint is currently marked suppressed in the registry.

    'resolved' deliberately does not silence: a recurring resolved error means the fix did not hold.
    """
    # Unreadable raises: an answer either way is a guess, and the guess may silence or flood.
    entry = _find_entry(_load_registry(), fingerprint)
    return bool(entry) and entry.get("status") == "suppressed"


def should_dispatch(fingerprint: str, now: Optional[float] = None) -> bool:
    """Check if this fingerprint should be dispatched.

    Gates: suppressed status first, then exponential backoff. Suppressed errors are still
    counted, so a wrong suppress stays auditable. `now` is a test seam.
    """
    if is_suppressed(fingerprint):
        return False

    info = _load_circuit_breaker_state()[1].get(fingerprint, {})
    count = int(info.get("count", 0))
    last_dispatch = float(info.get("last_dispatch", 0.0))
    if count == 0 or last_dispatch <= 0:
        return True

    elapsed = (time.time() if now is None else now) - last_dispatch
    return elapsed >= get_backoff_seconds(count)


def record_dispatch(fingerprint: str) -> None:
    """Record that a dispatch was sent for this fingerprint."""
    with _cb_state() as (_, per_fingerprint):
        info = per_fingerprint.get(fingerprint, {})
        per_fingerprint[fingerprint] = {"last_dispatch": time.time(), "count": int(info.get("count", 0)) + 1}


def normalize_message(message: str) -> str:
    """Normalize an error message by stripping variable data; a marked line is its marker alone."""
    marker = FAULT_MARKER.search(message)
    if marker:
        return marker.group(0)
    normalized = message

    normalized = re.sub(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:[+-]\d{2}:?\d{2}|Z)?", "<timestamp>", normalized
    )

    normalized = re.sub(r"\d{4}-\d{2}-\d{2}", "<date>", normalized)

    normalized = re.sub(r"/[\w./-]+", "<path>", normalized)

    normalized = re.sub(r"\bline \d+\b", "line N", normalized, flags=re.IGNORECASE)

    normalized = re.sub(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "<uuid>", normalized
    )

    normalized = re.sub(r"\b[0-9a-fA-F]{8,}\b", "<hash>", normalized)

    normalized = re.sub(r":\d{2,5}\b", ":<port>", normalized)

    normalized = re.sub(r"\b\d{3,}\b", "<id>", normalized)

    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized


def compute_fingerprint(error_type: str, normalized_msg: str, component: str) -> str:
    """Compute a SHA1 fingerprint for error deduplication; the component's case never splits a fingerprint."""
    # Folded to the case the registry was minted in, so stored rows and their suppressions keep their identity.
    content = f"{error_type}:{normalized_msg}:{component.upper()}"
    return hashlib.sha1(content.encode("utf-8")).hexdigest()


def _load_registry() -> dict:
    """Load the error registry from disk; absent or empty is a new one, unreadable raises.

    Callers write what this returns, so a blank answer for an unreadable file would erase the registry.
    """
    raw = REGISTRY_FILE.read_text(encoding="utf-8").strip() if REGISTRY_FILE.exists() else ""
    if not raw:
        return {"errors": {}, "metadata": {"version": "1.0.0", "last_updated": datetime.now().isoformat()}}
    data = json.loads(raw)
    if not isinstance(data, dict) or "errors" not in data:
        raise ValueError(f"{REGISTRY_FILE.name} has no errors map: not a registry")
    return data


def _save_registry(data: dict) -> bool:
    """Save the error registry to disk."""
    try:
        data["metadata"]["last_updated"] = datetime.now().isoformat()
        atomic_write_json(REGISTRY_FILE, data)
        return True
    except Exception as exc:
        logger.warning("Failed to save error registry to %s: %s", REGISTRY_FILE, exc)
        return False


def report(error_type: str, message: str, component: str, log_path: str = "", severity: str = "medium") -> dict:
    """Report an error to the registry; the returned entry carries an 'is_new' flag. Unreadable raises."""
    if severity not in VALID_SEVERITIES:
        severity = "medium"

    normalized = normalize_message(message)
    fingerprint = compute_fingerprint(error_type, normalized, component)

    # No guessing intent from words: a rejected command logs at INFO, so every line here is a fault.
    with json_file_lock(REGISTRY_FILE):
        registry = _load_registry()
        now = datetime.now().isoformat()

        if fingerprint in registry["errors"]:
            entry = registry["errors"][fingerprint]
            entry["count"] = entry.get("count", 1) + 1
            entry["last_seen"] = now
            if log_path:
                entry["log_path"] = log_path
            # The retired phrase filter's guess, never an operator's call; kept suppressed until now so purge spares it.
            if entry.get("status") == "suppressed" and entry.get("suppress_reason") == "user_error":
                entry["status"] = "new"
            _save_registry(registry)
            result = dict(entry)
            result["is_new"] = False
            json_handler.log_operation("error_registered", {"fingerprint": fingerprint[:12], "count": entry["count"]})
            return result
        else:
            event = ErrorEvent(
                fingerprint=fingerprint,
                error_type=error_type,
                message=message,
                normalized_message=normalized,
                component=component,
                severity=severity,
                count=1,
                status="new",
                first_seen=now,
                last_seen=now,
                log_path=log_path,
                source_fix_status="none",
            )
            entry_dict = asdict(event)
            registry["errors"][fingerprint] = entry_dict
            _save_registry(registry)
            result = dict(entry_dict)
            result["is_new"] = True
            json_handler.log_operation("error_registered", {"fingerprint": fingerprint[:12], "count": 1})
            return result


def query(
    status: Optional[str] = None, component: Optional[str] = None, severity: Optional[str] = None, limit: int = 50
) -> list:
    """Query the error registry with optional filters, most recent first."""
    try:
        registry = _load_registry()
        entries = list(registry["errors"].values())

        if status is not None:
            entries = [e for e in entries if e.get("status") == status]
        if component is not None:
            entries = [e for e in entries if e.get("component", "").upper() == component.upper()]
        if severity is not None:
            entries = [e for e in entries if e.get("severity") == severity]

        entries.sort(key=lambda e: e.get("last_seen", ""), reverse=True)

        return entries[:limit]

    except Exception as exc:
        logger.warning("Failed to query error registry: %s", exc)
        return []


def update_status(fingerprint: str, new_status: str, reason: str = "") -> bool:
    """Update the status of an error entry."""
    try:
        if new_status not in VALID_STATUSES:
            return False

        with json_file_lock(REGISTRY_FILE):
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

    except Exception as exc:
        logger.warning("Failed to update status for fingerprint '%s': %s", fingerprint, exc)
        return False


def get_entry(fingerprint: str) -> Optional[dict]:
    """Get a single error entry by fingerprint or prefix."""
    try:
        registry = _load_registry()
        return _find_entry(registry, fingerprint)
    except Exception as exc:
        logger.warning("Failed to get entry for fingerprint '%s': %s", fingerprint, exc)
        return None


def clear_resolved(days: int = 7) -> int:
    """Remove resolved entries older than N days; -1 means the registry could not be walked."""
    try:
        with json_file_lock(REGISTRY_FILE):
            registry = _load_registry()
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            removed = 0

            fingerprints_to_remove = []
            for fp, entry in registry["errors"].items():
                last_seen = entry.get("last_seen", "")
                if entry.get("status") == "resolved" and last_seen and last_seen < cutoff:
                    fingerprints_to_remove.append(fp)

            for fp in fingerprints_to_remove:
                del registry["errors"][fp]
                removed += 1

            if removed > 0:
                _save_registry(registry)

        return removed

    except Exception as exc:
        logger.warning("Failed to clear resolved entries: %s", exc)
        return -1


def purge_stale(days: int = 30, keep_suppressed: bool = False) -> int:
    """Remove entries whose last_seen is older than N days, of any status unless keep_suppressed.

    A dropped suppressed row would dispatch again on its next recurrence. Returns -1 when the
    registry could not be walked.
    """
    try:
        with json_file_lock(REGISTRY_FILE):
            registry = _load_registry()
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            removed = 0

            fingerprints_to_remove = []
            for fp, entry in registry["errors"].items():
                last_seen = entry.get("last_seen", "")
                if last_seen and last_seen < cutoff and not (keep_suppressed and entry.get("status") == "suppressed"):
                    fingerprints_to_remove.append(fp)

            for fp in fingerprints_to_remove:
                del registry["errors"][fp]
                removed += 1

            if removed > 0:
                _save_registry(registry)

        return removed

    except Exception as exc:
        logger.warning("Failed to purge stale entries: %s", exc)
        return -1


def get_stats() -> dict:
    """Get summary statistics from the error registry."""
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

        return {"total": len(entries), "by_status": by_status, "by_component": by_component, "by_severity": by_severity}

    except Exception as exc:
        logger.warning("Failed to get error registry stats: %s", exc)
        return {"total": 0, "by_status": {}, "by_component": {}, "by_severity": {}}


def update_source_fix_status(fingerprint: str, fix_status: str) -> bool:
    """Update the source fix status of an error entry."""
    if fix_status not in VALID_FIX_STATUSES:
        return False
    try:
        with json_file_lock(REGISTRY_FILE):
            registry = _load_registry()
            entry = _find_entry(registry, fingerprint)
            if entry is None:
                return False
            entry["source_fix_status"] = fix_status
            return _save_registry(registry)
    except Exception as exc:
        logger.warning("Failed to update source fix status for '%s': %s", fingerprint, exc)
        return False


def _find_entry(registry: dict, fingerprint: str) -> Optional[dict]:
    """Find an entry by exact fingerprint or a unique prefix; returns the live dict.

    A prefix matching more than one row returns None, so a short prefix never acts on the wrong error.
    """
    if fingerprint in registry["errors"]:
        return registry["errors"][fingerprint]

    if fingerprint and len(fingerprint) < 40:
        matches = [entry for fp, entry in registry["errors"].items() if fp.startswith(fingerprint)]
        if len(matches) == 1:
            return matches[0]

    return None
