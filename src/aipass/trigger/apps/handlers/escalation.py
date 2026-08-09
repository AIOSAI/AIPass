# =================== AIPass ====================
# Name: escalation.py
# Description: Repeat-signature escalation digest — repeat warns/errors email the operator
# Version: 1.0.0
# Created: 2026-08-08
# Modified: 2026-08-08
# =============================================

"""
Escalation Digest Lane (DPLAN-0283 WS-A)

Medic answers an error ONCE: it dispatches the owning branch and then goes
quiet — backoff, a mute, or a suppression keeps it quiet. That is correct for
agents and blind for humans. An error that keeps firing AFTER its owner was
told, or while a branch is muted, is invisible to Patrick forever. Warnings
are worse: they have never had an escalation path at all.

This lane counts repetition and mails the operator when repetition means
nothing got fixed:

    same signature, >= threshold occurrences inside the window
      -> ONE email to the digest recipient (a manager: email, never a wake)
      -> per-signature cooldown so the same noise cannot spam the mailbox

RULES (Patrick, S193 / DPLAN-0283):
    - A mute stops re-DISPATCHING. It must NEVER stop the COUNTING, and it
      must never stop a digest — a mute is how a branch says "I am building",
      not how the system goes dark for the human.
    - A suppression IS a human saying "this is benign" (compass #219), so it
      stays silent here too unless escalate_suppressed is turned on.
    - Counting is unconditional; only the SENDING is gated. A signature that
      never escalates is still fully auditable in the state file.

Thresholds, window, cooldown and recipient are operator settings and live in
trigger_json/custom_config/trigger.config.json — not in code. See
handlers/json/config_loader.py for the doctrine.

State lives at trigger_json/escalation_state.json. That name is deliberately
NOT `<module>_<config|data|log>.json`: json_handler owns every trio name in
that directory and regenerates a blank template over anything parked there.
"""

import hashlib
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from aipass.trigger.apps.config import TRIGGER_JSON_DIR, TRIGGER_ROOT, atomic_write_json, json_file_lock
from aipass.trigger.apps.handlers.json import config_loader
from aipass.trigger.apps.handlers.json import json_handler

try:
    from aipass.prax import append_jsonl as _append_jsonl
except Exception:
    _append_jsonl = None

# Live state — off the trio path (see module docstring).
STATE_FILE = TRIGGER_JSON_DIR / "escalation_state.json"

# Decision trail. .jsonl, not .log: the branch watcher only reads *.log, so
# writing here cannot feed the lane its own output.
ESCALATION_LOG = TRIGGER_ROOT / "logs" / "escalation.jsonl"

# How much of a message is kept for the digest body / state file.
MAX_MESSAGE_CHARS = 400
MAX_SAMPLE_CHARS = 500

# Email send callback (set by the module layer — handlers never import modules).
_send_email: Optional[Callable[..., bool]] = None

# Config cache — see get_config(). (checked_at, config or None)
CONFIG_TTL_SECONDS = 30.0
_config_cache: tuple = (0.0, None)


def _log(level: str, message: str, **fields: Any) -> None:
    """Append a line to the escalation trail (recursion-safe path).

    Deliberately NOT prax: this runs on the error path the log watchers read.
    A prax line here would be detected, fired back as an error_detected event,
    and land in record() again — the lane feeding itself forever.
    """
    if _append_jsonl is None:
        return
    try:
        entry = {"ts": datetime.now().isoformat(), "level": level, "msg": message}
        entry.update(fields)
        _append_jsonl(ESCALATION_LOG, entry)
    except Exception:
        pass  # seedgo:bypass meta-logging


def _log_warning(message: str, **fields: Any) -> None:
    """Record a warning on the escalation trail."""
    _log("WARNING", message, **fields)


def set_send_email_callback(callback: Callable[..., bool]) -> None:
    """Set the callback used to send digest emails.

    Args:
        callback: Callable accepting (to_branch, subject, message, ...) -> bool
    """
    global _send_email
    _send_email = callback


def get_config() -> Dict[str, Any]:
    """Return the operator's escalation settings, merged over defaults.

    Cached for a short TTL: record() runs once per watched WARNING/ERROR line,
    and a config file read per log line would put file IO on the hot path. An
    operator edit still takes effect within the TTL without a restart.

    Returns:
        The escalation config section
    """
    global _config_cache
    checked_at, cached = _config_cache
    now = time.time()
    if cached is not None and now - checked_at < CONFIG_TTL_SECONDS:
        return cached
    cfg = config_loader.section("escalation")
    _config_cache = (now, cfg)
    return cfg


def reset_config_cache() -> None:
    """Drop the cached config so the next read hits the file."""
    global _config_cache
    _config_cache = (0.0, None)


def _normalize(message: str) -> str:
    """Strip variable data from a message so repeats share one signature.

    Reuses the error registry's normalizer (paths, timestamps, hashes, IDs)
    so an escalation signature lines up with the fingerprint an operator
    already sees in `errors list`.

    Args:
        message: Raw message text

    Returns:
        Normalized message, or the raw message if the normalizer is missing
    """
    try:
        from aipass.trigger.apps.handlers.error_registry import normalize_message

        return normalize_message(message)
    except Exception as exc:
        _log_warning(f"normalizer unavailable, signing on raw text: {exc}")
        return message


def compute_signature(level: str, branch: str, module: str, message: str) -> str:
    """Compute the repeat signature for a log line.

    Args:
        level: Log level (WARNING / ERROR / CRITICAL)
        branch: Owning branch name
        module: Module that logged the line
        message: Raw message text

    Returns:
        12-char hex signature
    """
    raw = f"{level.upper()}|{branch.upper()}|{module}|{_normalize(message)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _empty_state() -> Dict[str, Any]:
    """Return a fresh, empty state document."""
    return {
        "_meta": {
            "purpose": "Repeat-signature counts for the escalation digest lane",
            "managed_by": "handlers/escalation.py",
        },
        "signatures": {},
    }


def _load_state() -> Dict[str, Any]:
    """Read the state file, tolerating absence and corruption.

    Returns:
        State dict — always usable, empty when the file is unreadable
    """
    if not STATE_FILE.exists():
        return _empty_state()
    try:
        import json

        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        _log_warning(f"unreadable escalation state, starting empty: {exc}")
        return _empty_state()
    if not isinstance(data, dict) or not isinstance(data.get("signatures"), dict):
        _log_warning("escalation state has wrong shape, starting empty")
        return _empty_state()
    return data


def _prune(signatures: Dict[str, Any], max_signatures: int) -> None:
    """Drop least-recently-seen signatures so the state file stays bounded.

    Args:
        signatures: Signature map, mutated in place
        max_signatures: Maximum entries to keep
    """
    if max_signatures <= 0 or len(signatures) <= max_signatures:
        return
    ordered = sorted(signatures.items(), key=lambda kv: kv[1].get("last_seen", ""))
    for sig, _entry in ordered[: len(signatures) - max_signatures]:
        signatures.pop(sig, None)


def _is_error_eligible(branch: str, fingerprint: str, cfg: Dict[str, Any]) -> tuple:
    """Decide whether a repeating ERROR is one the human needs to hear about.

    Eligible means medic will NOT be waking the owner about this right now:
    it already dispatched them, or the branch is muted, or medic is off, or
    the error has no registered owner to dispatch to at all.

    A deliberately SUPPRESSED fingerprint stays silent (compass #219) unless
    escalate_suppressed is set.

    Args:
        branch: Branch the error was attributed to
        fingerprint: Registry fingerprint (may be empty)
        cfg: Escalation config section

    Returns:
        (eligible, reason) — reason is a short human-readable state string
    """
    if fingerprint:
        try:
            from aipass.trigger.apps.handlers.error_registry import get_dispatch_count, is_suppressed

            if is_suppressed(fingerprint) and not cfg.get("escalate_suppressed", False):
                return False, "suppressed by operator"
            if get_dispatch_count(fingerprint) >= 1:
                return True, "owner already dispatched, still recurring"
        except Exception as exc:
            _log_warning(f"registry state unavailable for {fingerprint[:12]}: {exc}")

    try:
        from aipass.trigger.apps.handlers import medic_state

        if not medic_state.is_enabled():
            return True, "medic off — no dispatch happening"
        if branch.lower() in [b.lower() for b in medic_state.get_muted_branches()]:
            return True, "branch muted — dispatch suppressed, counting continues"
    except Exception as exc:
        _log_warning(f"medic state unavailable for {branch}: {exc}")

    if not _has_registered_owner(branch):
        return True, "no registered owner — medic cannot dispatch this anywhere"

    return False, "owner dispatch still pending"


def _has_registered_owner(branch: str) -> bool:
    """Check whether *branch* is a citizen medic could dispatch to.

    Args:
        branch: Branch name (e.g. 'MEMORY', 'UNKNOWN')

    Returns:
        True if the branch resolves to a registered email, or if the check
        itself failed — an unverifiable registry must not manufacture digests
    """
    try:
        from aipass.trigger.apps.handlers.events.error_detected import _get_registered_emails

        return f"@{branch.lower()}" in _get_registered_emails()
    except Exception as exc:
        _log_warning(f"registry lookup failed for {branch}: {exc}")
        return True


def record_warning(
    branch: str, module: str, message: str, log_file: str = "", raw_line: str = ""
) -> Optional[Dict[str, Any]]:
    """Record a WARNING occurrence and escalate if it keeps repeating.

    Warnings have no dispatch path anywhere in medic, so there is nothing to
    gate on — repetition alone is the signal.

    Args:
        branch: Branch the warning came from
        module: Module that logged it
        message: Warning message text
        log_file: Source log path
        raw_line: Full log line, kept as a digest sample

    Returns:
        Decision dict, or None when the lane is off or the input is unusable
    """
    return _record("WARNING", branch, module, message, log_file, raw_line, fingerprint="")


def record_error(
    branch: str, module: str, message: str, log_file: str = "", fingerprint: str = "", raw_line: str = ""
) -> Optional[Dict[str, Any]]:
    """Record an ERROR occurrence and escalate if it recurs past medic.

    MUST be called before medic's dispatch gates, not after: a muted branch
    or an open circuit breaker stops the dispatch, and neither may stop the
    count.

    Args:
        branch: Branch the error was attributed to
        module: Module that logged it
        message: Error message text
        log_file: Source log path
        fingerprint: Registry fingerprint, used for dispatch/suppression state
        raw_line: Full log line, kept as a digest sample

    Returns:
        Decision dict, or None when the lane is off or the input is unusable
    """
    return _record("ERROR", branch, module, message, log_file, raw_line, fingerprint=fingerprint)


def _record(
    level: str,
    branch: str,
    module: str,
    message: str,
    log_file: str,
    raw_line: str,
    fingerprint: str,
) -> Optional[Dict[str, Any]]:
    """Count one occurrence and decide whether a digest fires.

    Silent-failure contract: this runs inside event handlers, so it never
    raises and never returns a value the caller must handle.

    Args:
        level: WARNING or ERROR
        branch: Owning branch
        module: Logging module
        message: Message text
        log_file: Source log path
        raw_line: Full log line for the sample block
        fingerprint: Registry fingerprint (errors only)

    Returns:
        Decision dict {signature, count, outcome} or None
    """
    try:
        if not branch or not module or not message:
            return None

        cfg = get_config()
        if not cfg.get("enabled", True):
            return None
        if branch.lower() in [b.lower() for b in cfg.get("ignore_branches", []) or []]:
            return None

        signature = compute_signature(level, branch, module, message)
        window_seconds = max(1, int(cfg.get("window_minutes", 60))) * 60
        threshold = int(cfg.get("error_threshold", 5) if level == "ERROR" else cfg.get("warning_threshold", 10))
        sample_lines = max(0, int(cfg.get("sample_lines", 3)))
        now = time.time()

        with json_file_lock(STATE_FILE):
            state = _load_state()
            signatures = state.setdefault("signatures", {})
            entry = signatures.get(signature)
            if entry is None:
                entry = {
                    "level": level,
                    "branch": branch,
                    "module": module,
                    "message": message[:MAX_MESSAGE_CHARS],
                    "log_file": log_file,
                    "fingerprint": fingerprint,
                    "first_seen": datetime.now().isoformat(),
                    "occurrences": [],
                    "total_count": 0,
                    "digests_sent": 0,
                    "last_digest": "",
                    "samples": [],
                }
                signatures[signature] = entry

            # Bookkeeping first, unconditionally — a mute must never stop this.
            entry["last_seen"] = datetime.now().isoformat()
            entry["total_count"] = int(entry.get("total_count", 0)) + 1
            if log_file:
                entry["log_file"] = log_file
            if fingerprint:
                entry["fingerprint"] = fingerprint
            occurrences = [ts for ts in entry.get("occurrences", []) if now - ts <= window_seconds]
            occurrences.append(now)
            entry["occurrences"] = occurrences
            if sample_lines and raw_line:
                samples = entry.get("samples", [])
                samples.append(raw_line.strip()[:MAX_SAMPLE_CHARS])
                entry["samples"] = samples[-sample_lines:]

            window_count = len(occurrences)
            outcome = "counted"

            if window_count >= threshold:
                outcome = _evaluate_digest(signature, entry, cfg, window_count, window_seconds, now)

            _prune(signatures, int(cfg.get("max_signatures", 500)))
            atomic_write_json(STATE_FILE, state)

        return {"signature": signature, "count": window_count, "outcome": outcome}

    except Exception as exc:
        _log_warning(f"escalation record failed for {branch}/{module}: {exc}")
        return None


def _evaluate_digest(
    signature: str,
    entry: Dict[str, Any],
    cfg: Dict[str, Any],
    window_count: int,
    window_seconds: int,
    now: float,
) -> str:
    """Apply cooldown + eligibility to an over-threshold signature, then send.

    Args:
        signature: Repeat signature
        entry: Mutable state entry for this signature
        cfg: Escalation config section
        window_count: Occurrences inside the window
        window_seconds: Window length in seconds
        now: Current epoch time

    Returns:
        Outcome string: sent / send_failed / cooldown / not_eligible
    """
    level = entry.get("level", "ERROR")
    branch = entry.get("branch", "UNKNOWN")

    cooldown_seconds = max(0, int(cfg.get("cooldown_minutes", 360))) * 60
    last_digest = entry.get("last_digest", "")
    if last_digest and cooldown_seconds:
        try:
            elapsed = now - datetime.fromisoformat(last_digest).timestamp()
            if elapsed < cooldown_seconds:
                _log(
                    "INFO",
                    "digest held by cooldown",
                    signature=signature,
                    branch=branch,
                    count=window_count,
                    outcome="cooldown",
                )
                return "cooldown"
        except ValueError:
            # Unparseable stamp — treat as no cooldown rather than going silent.
            _log_warning(f"bad last_digest stamp on {signature}: {last_digest!r}")

    if level == "ERROR":
        eligible, reason = _is_error_eligible(branch, entry.get("fingerprint", ""), cfg)
    else:
        eligible, reason = True, "warnings have no dispatch path — repetition is the only signal"

    if not eligible:
        _log(
            "INFO",
            "digest withheld",
            signature=signature,
            branch=branch,
            count=window_count,
            reason=reason,
            outcome="not_eligible",
        )
        return "not_eligible"

    recipient = str(cfg.get("digest_recipient", "@devpulse"))
    subject, body = build_digest(signature, entry, window_count, window_seconds, reason, recipient)

    if _send_email is None:
        _log_warning(
            "digest not sent — no email callback wired",
            signature=signature,
            branch=branch,
            count=window_count,
            outcome="send_failed",
        )
        return "send_failed"

    try:
        # auto_execute=False: this is an EMAIL, never a dispatch. Managers
        # cannot be woken, and a digest is for reading, not for spawning.
        sent = _send_email(
            to_branch=recipient,
            subject=subject,
            message=body,
            auto_execute=False,
            reply_to="@trigger",
            from_branch="@trigger",
        )
    except Exception as exc:
        _log_warning(f"digest send raised for {signature}: {exc}", outcome="send_failed")
        return "send_failed"

    if not sent:
        # Cooldown is NOT set on a failed send — the next occurrence retries.
        _log_warning(
            "digest delivery failed",
            signature=signature,
            branch=branch,
            count=window_count,
            outcome="send_failed",
        )
        return "send_failed"

    entry["last_digest"] = datetime.now().isoformat()
    entry["digests_sent"] = int(entry.get("digests_sent", 0)) + 1
    # Reset the window so the next digest reports occurrences since this one.
    entry["occurrences"] = []
    _log(
        "INFO",
        "digest sent",
        signature=signature,
        branch=branch,
        signature_level=level,
        count=window_count,
        recipient=recipient,
        reason=reason,
        outcome="sent",
    )
    # Operational record: a digest leaving the branch is an outbound action,
    # not just a trail entry. json_handler writes JSON, never a watched .log,
    # so recording it here cannot feed the lane back into itself.
    json_handler.log_operation(
        "escalation_digest_sent",
        {
            "signature": signature,
            "level": level,
            "branch": branch,
            "count": window_count,
            "recipient": recipient,
        },
    )
    return "sent"


def build_digest(
    signature: str,
    entry: Dict[str, Any],
    window_count: int,
    window_seconds: int,
    reason: str,
    recipient: str,
) -> tuple:
    """Build the digest subject and body.

    Investigation must be able to start from the mail alone: signature, count,
    window, branch, log path and the last sample lines all travel with it.

    Args:
        signature: Repeat signature
        entry: State entry for this signature
        window_count: Occurrences inside the window
        window_seconds: Window length in seconds
        reason: Why this repeat is escalation-worthy
        recipient: Digest recipient address

    Returns:
        (subject, body)
    """
    level = entry.get("level", "ERROR")
    branch = entry.get("branch", "UNKNOWN")
    module = entry.get("module", "unknown")
    message = entry.get("message", "")
    window_minutes = max(1, window_seconds // 60)
    samples = entry.get("samples", [])
    sample_block = "\n".join(f"  {line}" for line in samples) if samples else "  (no samples captured)"

    subject = f"[REPEAT] {level} x{window_count} @{branch.lower()} / {module}"

    body = f"""Repeat signature escalation — nothing here has been fixed.

Signature   : {signature}
Level       : {level}
Branch      : @{branch.lower()}
Module      : {module}
Occurrences : {window_count} in the last {window_minutes} min (lifetime {entry.get("total_count", window_count)})
First seen  : {entry.get("first_seen", "unknown")}
Last seen   : {entry.get("last_seen", "unknown")}
Log file    : {entry.get("log_file") or "unknown"}
Why escalated: {reason}
Digests sent: {entry.get("digests_sent", 0)} before this one

Message
{message}

Last {len(samples)} sample line(s)
{sample_block}

---
This is an EMAIL, not a dispatch — nothing was woken, nothing is waiting on a
reply. Medic still handles owner dispatch; this lane only reports repetition
that outlived it.

Tune or silence: trigger_json/custom_config/trigger.config.json -> escalation
  warning_threshold / error_threshold / window_minutes / cooldown_minutes
  ignore_branches (deliberate silence for a known-noisy branch)
Inspect: drone @trigger escalation status | drone @trigger escalation list
Sent to {recipient} by @trigger."""

    return subject, body


def get_signatures(level: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """Return tracked signatures, most recently seen first.

    Args:
        level: Optional level filter (WARNING / ERROR)
        limit: Maximum entries returned

    Returns:
        List of signature dicts with the signature key included
    """
    state = _load_state()
    rows = []
    for sig, entry in state.get("signatures", {}).items():
        if level and entry.get("level", "").upper() != level.upper():
            continue
        row = dict(entry)
        row["signature"] = sig
        row["window_count"] = len(entry.get("occurrences", []))
        rows.append(row)
    rows.sort(key=lambda r: r.get("last_seen", ""), reverse=True)
    return rows[:limit]


def get_stats() -> Dict[str, Any]:
    """Return escalation lane statistics for the CLI.

    Returns:
        Dict with config knobs, tracked counts and digest totals
    """
    cfg = get_config()
    state = _load_state()
    signatures = state.get("signatures", {})
    warnings = sum(1 for e in signatures.values() if e.get("level") == "WARNING")
    errors = sum(1 for e in signatures.values() if e.get("level") != "WARNING")
    digests = sum(int(e.get("digests_sent", 0)) for e in signatures.values())
    in_cooldown = sum(1 for e in signatures.values() if e.get("last_digest"))
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "digest_recipient": cfg.get("digest_recipient", "@devpulse"),
        "warning_threshold": cfg.get("warning_threshold", 10),
        "error_threshold": cfg.get("error_threshold", 5),
        "window_minutes": cfg.get("window_minutes", 60),
        "cooldown_minutes": cfg.get("cooldown_minutes", 360),
        "escalate_suppressed": bool(cfg.get("escalate_suppressed", False)),
        "watch_branch_log_warnings": bool(cfg.get("watch_branch_log_warnings", True)),
        "ignore_branches": cfg.get("ignore_branches", []),
        "tracked_signatures": len(signatures),
        "tracked_warnings": warnings,
        "tracked_errors": errors,
        "digests_sent": digests,
        "signatures_digested": in_cooldown,
        "state_file": str(STATE_FILE),
        "config_file": str(config_loader.CONFIG_PATH),
        "email_wired": _send_email is not None,
    }


def clear_state() -> bool:
    """Archive the escalation state file and start fresh.

    Never deletes — the old counts move to trigger_json/.archive/.

    Returns:
        True if state was cleared
    """
    try:
        if not STATE_FILE.exists():
            return True
        from aipass.trigger.apps.config import _archive_legacy_file

        with json_file_lock(STATE_FILE):
            return _archive_legacy_file(Path(STATE_FILE))
    except Exception as exc:
        _log_warning(f"clear_state failed: {exc}")
        return False
