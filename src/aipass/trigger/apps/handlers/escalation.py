# =================== AIPass ====================
# Name: escalation.py
# Description: Repeat-signature escalation digest — repeat warns/errors email the operator
# Version: 1.6.1
# Created: 2026-08-08
# Modified: 2026-10-24
# =============================================

"""
Escalation Digest Lane (DPLAN-0283 WS-A)

Counts repeats per normalized signature and mails the operator when repetition
means nothing got fixed. A mute stops dispatch, never the counting or a digest;
a suppression stays silent unless escalate_suppressed. A WARNING still repeating
past warning_age_hours gets a registry row and goes to the branch that LOGGED it
(never a name parsed from the text); the manager gets one roll-up instead.
Mail upserts per thread (level, branch, module), not per signature.

The state file name avoids `<module>_<config|data|log>.json`: json_handler
regenerates a blank template over any trio name in trigger_json/.
"""

import hashlib
import json
import re
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from aipass.trigger.apps.config import (
    TRIGGER_JSON_DIR,
    TRIGGER_ROOT,
    atomic_write_json,
    json_file_lock,
    trail_logger,
)
from aipass.trigger.apps.handlers.repo_root import find_repo_root
from aipass.trigger.apps.handlers.json import config_loader
from aipass.trigger.apps.handlers.json import json_handler

STATE_FILE = TRIGGER_JSON_DIR / "escalation_state.json"

# .jsonl, not .log: the branch watcher reads *.log, so this cannot feed the lane.
ESCALATION_LOG = TRIGGER_ROOT / "logs" / "escalation.jsonl"

MAX_MESSAGE_CHARS = 400
MAX_SAMPLE_CHARS = 500

MAX_ROSTER_LINES = 15
MAX_ROSTER_MESSAGE_CHARS = 160

MAX_ROLLUP_LINES = 30

ROLLUP_UPSERT_KEY = "escalation:rollup"

# Set by the module layer: handlers never import modules.
_send_email: Optional[Callable[..., bool]] = None

CONFIG_TTL_SECONDS = 30.0
_config_cache: tuple = (0.0, None)


# Not prax: a prax line here is watched, fired back as an error event and recorded again.
logger = trail_logger(ESCALATION_LOG)


def set_send_email_callback(callback: Callable[..., bool]) -> None:
    """Set the callback used to send digest emails."""
    global _send_email
    _send_email = callback


def get_config() -> Dict[str, Any]:
    """Return the operator's escalation settings, merged over defaults.

    TTL-cached: record() runs per watched log line, so no file read per line.
    """
    global _config_cache
    checked_at, cached = _config_cache
    now = time.time()
    if cached is not None and now - checked_at < CONFIG_TTL_SECONDS:
        return cached
    cfg = config_loader.section("escalation")
    _config_cache = (now, cfg)
    return cfg


BRANCH_REGISTRY_FILE = find_repo_root(TRIGGER_ROOT, caller="escalation") / "AIPASS_REGISTRY.json"

# TTL, not an mtime check: two registry writes in one clock tick share an mtime,
# so an mtime check could pin a stale name list indefinitely.
_branch_names_cache: Tuple[float, Optional[re.Pattern]] = (0.0, None)

# Any @handle, so an unregistered name cannot fragment a signature.
HANDLE_PATTERN = re.compile(r"@\w+")

# The unit suffix matters: "1237ms" has no \b between digits and letters.
# The token must stay <id>, the registry's own, or "99" and "101" sign apart.
NUMBER_PATTERN = re.compile(r"\b\d+[a-zA-Z]{0,3}\b")


def _branch_name_pattern() -> Optional[re.Pattern]:
    """Compile an alternation of registered citizen names, or None if unreadable."""
    global _branch_names_cache
    checked_at, cached = _branch_names_cache
    now = time.time()
    # `checked_at`, not `cached`: a missing registry (None) is a valid cached answer.
    if checked_at and now - checked_at < CONFIG_TTL_SECONDS:
        return cached

    pattern: Optional[re.Pattern] = None
    try:
        data = json.loads(BRANCH_REGISTRY_FILE.read_text(encoding="utf-8"))
        names = {str(b["name"]).upper() for b in data.get("branches", []) if b.get("name")}
        if names:
            # Longest first so AI_MAIL is matched before AI.
            ordered = sorted(names, key=len, reverse=True)
            pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in ordered) + r")\b", re.IGNORECASE)
    except Exception as exc:
        logger.warning(f"branch registry unreadable, names will not collapse: {exc}")

    _branch_names_cache = (now, pattern)
    return pattern


def _collapse_repeat_variables(text: str) -> str:
    """Collapse the values that vary between repeats of one condition."""
    text = NUMBER_PATTERN.sub("<id>", text)
    names = _branch_name_pattern()
    if names is not None:
        text = names.sub("<branch>", text)
    return HANDLE_PATTERN.sub("<branch>", text)


def _normalize(message: str) -> str:
    """Strip variable data from a message so repeats share one signature.

    The repeat-only collapse stays local: registry fingerprints keep their grain.
    """
    try:
        from aipass.trigger.apps.handlers.error_registry import normalize_message

        return _collapse_repeat_variables(normalize_message(message))
    except Exception as exc:
        logger.warning(f"normalizer unavailable, signing on raw text: {exc}")
        return message


def compute_signature(level: str, branch: str, module: str, message: str) -> str:
    """Compute the repeat signature for a log line."""
    raw = f"{level.upper()}|{branch.upper()}|{module}|{_normalize(message)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _registry_report(**kwargs: Any) -> Dict[str, Any]:
    """Open or increment a registry row. The seam tests replace."""
    try:
        from aipass.trigger.apps.handlers.error_registry import report

        return report(**kwargs)
    except Exception as exc:
        logger.warning(f"registry row not opened: {exc}")
        return {}


def _age_hours(entry: Dict[str, Any], now: float) -> Optional[float]:
    """Return how many hours ago this signature was FIRST seen.

    None when unreadable: a bad stamp must never age a signal out of the manager's lane.
    """
    try:
        return (now - datetime.fromisoformat(entry.get("first_seen", "")).timestamp()) / 3600.0
    except ValueError:
        logger.warning(f"unreadable first_seen, staying on the manager digest: {entry.get('first_seen')!r}")
        return None


def _aged_owner(level: str, entry: Dict[str, Any], cfg: Dict[str, Any], now: float) -> Optional[Tuple[str, float]]:
    """Decide whether this repeat belongs to its own branch now, and whose it is."""
    limit = float(cfg.get("warning_age_hours", 24) or 0)
    if level != "WARNING" or limit <= 0:
        return None

    age = _age_hours(entry, now)
    if age is None or age < limit:
        return None

    branch = str(entry.get("branch", ""))
    if not branch or not _has_registered_owner(branch):
        return None

    return f"@{branch.lower()}", age


def thread_key(level: str, branch: str, module: str) -> str:
    """Return the digest thread a signature's mail lands in."""
    return f"escalation:{level.upper()}:{branch.lower()}:{module}"


def _thread_siblings(
    signatures: Dict[str, Any], signature: str, entry: Dict[str, Any]
) -> List[Tuple[str, Dict[str, Any]]]:
    """Return the other signatures sharing *entry*'s thread, newest first."""
    key = thread_key(entry.get("level", ""), entry.get("branch", ""), entry.get("module", ""))
    siblings = [
        (sig, other)
        for sig, other in signatures.items()
        if sig != signature
        and thread_key(other.get("level", ""), other.get("branch", ""), other.get("module", "")) == key
    ]
    siblings.sort(key=lambda kv: _seen_order(kv[1]), reverse=True)
    return siblings


def _empty_state() -> Dict[str, Any]:
    """Return a fresh, empty state document."""
    return {
        "_meta": {
            "purpose": "Repeat-signature counts for the escalation digest lane",
            "managed_by": "handlers/escalation.py",
        },
        "signatures": {},
        "write_seq": 0,
    }


def _next_write_seq(state: Dict[str, Any]) -> int:
    """Return the next write-ordering number for this state document.

    Breaks last_seen ties (Windows clock ticks ~15.6ms); persisted, not monotonic(),
    because a monotonic value is meaningless across a restart.
    """
    seq = int(state.get("write_seq", 0)) + 1
    state["write_seq"] = seq
    return seq


def _seen_order(entry: Dict[str, Any]) -> tuple:
    """Return the sort key for "how recently was this signature touched"."""
    return (entry.get("last_seen", ""), int(entry.get("last_seen_seq", 0)))


def _load_state() -> Dict[str, Any]:
    """Read the state file, tolerating absence and corruption."""
    if not STATE_FILE.exists():
        return _empty_state()
    try:
        import json

        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"unreadable escalation state, starting empty: {exc}")
        return _empty_state()
    if not isinstance(data, dict) or not isinstance(data.get("signatures"), dict):
        logger.warning("escalation state has wrong shape, starting empty")
        return _empty_state()
    return data


def _prune(signatures: Dict[str, Any], max_signatures: int) -> None:
    """Drop least-recently-seen signatures so the state file stays bounded."""
    if max_signatures <= 0 or len(signatures) <= max_signatures:
        return
    ordered = sorted(signatures.items(), key=lambda kv: _seen_order(kv[1]))
    for sig, _entry in ordered[: len(signatures) - max_signatures]:
        signatures.pop(sig, None)


def _is_error_eligible(branch: str, fingerprint: str, cfg: Dict[str, Any]) -> tuple:
    """Decide whether a repeating ERROR is one the human needs to hear about.

    Eligible means medic is not waking the owner about it right now.
    """
    if fingerprint:
        try:
            from aipass.trigger.apps.handlers.error_registry import get_dispatch_count, is_suppressed

            if is_suppressed(fingerprint) and not cfg.get("escalate_suppressed", False):
                return False, "suppressed by operator"
            if get_dispatch_count(fingerprint) >= 1:
                return True, "owner already dispatched, still recurring"
        except Exception as exc:
            logger.warning(f"registry state unavailable for {fingerprint[:12]}: {exc}")

    try:
        from aipass.trigger.apps.handlers import medic_state

        if not medic_state.is_enabled():
            return True, "medic off — no dispatch happening"
        if branch.lower() in [b.lower() for b in medic_state.get_muted_branches()]:
            return True, "branch muted — dispatch suppressed, counting continues"
    except Exception as exc:
        logger.warning(f"medic state unavailable for {branch}: {exc}")

    if not _has_registered_owner(branch):
        return True, "no registered owner — medic cannot dispatch this anywhere"

    return False, "owner dispatch still pending"


def _has_registered_owner(branch: str) -> bool:
    """Check whether *branch* is a citizen medic could dispatch to.

    True when the check fails: an unverifiable registry must not manufacture digests.
    """
    try:
        from aipass.trigger.apps.handlers.events.error_detected import _get_registered_emails

        return f"@{branch.lower()}" in _get_registered_emails()
    except Exception as exc:
        logger.warning(f"registry lookup failed for {branch}: {exc}")
        return True


def record_warning(
    branch: str, module: str, message: str, log_file: str = "", raw_line: str = ""
) -> Optional[Dict[str, Any]]:
    """Record a WARNING occurrence and escalate if it keeps repeating."""
    return _record("WARNING", branch, module, message, log_file, raw_line, fingerprint="")


def record_error(
    branch: str, module: str, message: str, log_file: str = "", fingerprint: str = "", raw_line: str = ""
) -> Optional[Dict[str, Any]]:
    """Record an ERROR occurrence and escalate if it recurs past medic.

    Call before medic's dispatch gates: a mute or open breaker must not stop the count.
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
    """Count one occurrence and decide whether a digest fires. Never raises."""
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
                    "last_seen_seq": 0,
                    "occurrences": [],
                    "total_count": 0,
                    "digests_sent": 0,
                    "last_digest": "",
                    "samples": [],
                }
                signatures[signature] = entry

            # Bookkeeping first, unconditionally: a mute must never stop this.
            entry["last_seen"] = datetime.now().isoformat()
            entry["last_seen_seq"] = _next_write_seq(state)
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
                siblings = _thread_siblings(signatures, signature, entry)
                outcome = _evaluate_digest(signature, entry, cfg, window_count, window_seconds, now, siblings)
                if outcome == "aged_owner_mail":
                    _maybe_send_rollup(state, cfg, now)

            _prune(signatures, int(cfg.get("max_signatures", 500)))
            atomic_write_json(STATE_FILE, state)

        return {"signature": signature, "count": window_count, "outcome": outcome}

    except Exception as exc:
        logger.warning(f"escalation record failed for {branch}/{module}: {exc}")
        return {"signature": "", "count": 0, "outcome": "record_failed"}


def _evaluate_digest(
    signature: str,
    entry: Dict[str, Any],
    cfg: Dict[str, Any],
    window_count: int,
    window_seconds: int,
    now: float,
    siblings: Optional[List[Tuple[str, Dict[str, Any]]]] = None,
) -> str:
    """Apply cooldown + eligibility to an over-threshold signature, then send."""
    level = entry.get("level", "ERROR")
    branch = entry.get("branch", "UNKNOWN")

    cooldown_seconds = max(0, int(cfg.get("cooldown_minutes", 360))) * 60
    last_digest = entry.get("last_digest", "")
    if last_digest and cooldown_seconds:
        try:
            elapsed = now - datetime.fromisoformat(last_digest).timestamp()
            if elapsed < cooldown_seconds:
                logger.info(
                    "digest held by cooldown",
                    signature=signature,
                    branch=branch,
                    count=window_count,
                    outcome="cooldown",
                )
                return "cooldown"
        except ValueError:
            # Unparseable stamp: no cooldown rather than going silent.
            logger.warning(f"bad last_digest stamp on {signature}: {last_digest!r}")

    if level == "ERROR":
        eligible, reason = _is_error_eligible(branch, entry.get("fingerprint", ""), cfg)
    else:
        eligible, reason = True, "warnings have no dispatch path — repetition is the only signal"

    if not eligible:
        logger.info(
            "digest withheld",
            signature=signature,
            branch=branch,
            count=window_count,
            reason=reason,
            outcome="not_eligible",
        )
        return "not_eligible"

    aged = _aged_owner(level, entry, cfg, now)
    if aged is not None:
        return _send_aged_notice(signature, entry, cfg, window_count, window_seconds, siblings, aged)

    recipient = str(cfg.get("digest_recipient", "@devpulse"))
    subject, body = build_digest(signature, entry, window_count, window_seconds, reason, recipient, siblings)

    if _send_email is None:
        logger.warning(
            "digest not sent — no email callback wired",
            signature=signature,
            branch=branch,
            count=window_count,
            outcome="send_failed",
        )
        return "send_failed"

    # Keyed on the thread: the rendered subject changes with the count, and a
    # per-signature key splits one module's mail across many messages.
    upsert_key = thread_key(level, branch, entry.get("module", ""))
    upsert_result: Dict[str, Any] = {}

    try:
        # auto_execute=False: an email, never a dispatch; managers cannot be woken.
        sent = _send_email(
            to_branch=recipient,
            subject=subject,
            message=body,
            auto_execute=False,
            reply_to="@trigger",
            from_branch="@trigger",
            upsert_key=upsert_key,
            upsert_result=upsert_result,
        )
    except Exception as exc:
        logger.warning(f"digest send raised for {signature}: {exc}", outcome="send_failed")
        return "send_failed"

    if not sent:
        # No cooldown on a failed send: the next occurrence retries.
        logger.warning(
            "digest delivery failed",
            signature=signature,
            branch=branch,
            count=window_count,
            outcome="send_failed",
        )
        return "send_failed"

    entry["last_digest"] = datetime.now().isoformat()
    entry["digests_sent"] = int(entry.get("digests_sent", 0)) + 1
    entry["occurrences"] = []
    # None: the callback did not report created/updated (older adapter).
    upsert_action = upsert_result.get("upsert_action")
    logger.info(
        "digest sent",
        signature=signature,
        branch=branch,
        signature_level=level,
        count=window_count,
        recipient=recipient,
        reason=reason,
        upsert_key=upsert_key,
        upsert_action=upsert_action,
        outcome="sent",
    )
    # json_handler writes JSON, never a watched .log, so this cannot feed the lane.
    json_handler.log_operation(
        "escalation_digest_sent",
        {
            "signature": signature,
            "level": level,
            "branch": branch,
            "count": window_count,
            "recipient": recipient,
            "upsert_key": upsert_key,
            "upsert_action": upsert_action,
        },
    )
    return "sent"


def _send_aged_notice(
    signature: str,
    entry: Dict[str, Any],
    cfg: Dict[str, Any],
    window_count: int,
    window_seconds: int,
    siblings: Optional[List[Tuple[str, Dict[str, Any]]]],
    aged: Tuple[str, float],
) -> str:
    """Open a registry row and mail the branch that logged this repeat."""
    recipient, age = aged
    branch = str(entry.get("branch", ""))

    row = _registry_report(
        error_type="WARNING",
        message=str(entry.get("message", "")),
        component=branch.upper(),
        log_path=str(entry.get("log_file", "")),
        severity="low",
    )
    fingerprint = str(row.get("fingerprint", ""))
    if row.get("status") == "suppressed" and not cfg.get("escalate_suppressed", False):
        logger.info("aged notice withheld", signature=signature, branch=branch, outcome="not_eligible")
        return "not_eligible"

    subject, body = build_aged_notice(
        signature, entry, window_count, window_seconds, recipient, siblings, age, fingerprint
    )

    if _send_email is None:
        logger.warning(
            "aged notice not sent — no email callback wired",
            signature=signature,
            branch=branch,
            outcome="send_failed",
        )
        return "send_failed"

    upsert_result: Dict[str, Any] = {}
    try:
        # auto_execute=False: mail the owner reads, never a wake.
        sent = _send_email(
            to_branch=recipient,
            subject=subject,
            message=body,
            auto_execute=False,
            reply_to="@trigger",
            from_branch="@trigger",
            upsert_key=thread_key("WARNING", branch, str(entry.get("module", ""))),
            upsert_result=upsert_result,
        )
    except Exception as exc:
        logger.warning(f"aged notice raised for {signature}: {exc}", outcome="send_failed")
        return "send_failed"

    if not sent:
        # No cooldown stamp on a failed send: the next occurrence retries.
        logger.warning(
            "aged notice delivery failed",
            signature=signature,
            branch=branch,
            outcome="send_failed",
        )
        return "send_failed"

    entry["last_digest"] = datetime.now().isoformat()
    entry["digests_sent"] = int(entry.get("digests_sent", 0)) + 1
    entry["occurrences"] = []
    entry.setdefault("aged_since", datetime.now().isoformat())
    entry["aged_notices"] = int(entry.get("aged_notices", 0)) + 1
    if fingerprint:
        entry["registry_fingerprint"] = fingerprint

    logger.info(
        "aged warning mailed to its owner",
        signature=signature,
        branch=branch,
        count=window_count,
        recipient=recipient,
        age_hours=round(age, 1),
        registry_fingerprint=fingerprint[:12],
        upsert_action=upsert_result.get("upsert_action"),
        outcome="aged_owner_mail",
    )
    json_handler.log_operation(
        "escalation_aged_notice_sent",
        {
            "signature": signature,
            "branch": branch,
            "recipient": recipient,
            "age_hours": round(age, 1),
            "registry_fingerprint": fingerprint,
        },
    )
    return "aged_owner_mail"


def _rollup_is_due(state: Dict[str, Any], current: List[str], hours: float, now: float) -> bool:
    """Decide whether the manager's roll-up should be written again.

    Cadence paces only an unchanged list; a changed list is news and sends now.
    """
    if current != state.get("rollup_rows"):
        return True

    last_sent = str(state.get("rollup_last_sent", ""))
    if not last_sent:
        return True

    try:
        return now - datetime.fromisoformat(last_sent).timestamp() >= hours * 3600
    except ValueError:
        # An unreadable stamp must not mute the manager forever.
        logger.warning(f"bad rollup stamp, sending anyway: {last_sent!r}")
        return True


def _maybe_send_rollup(state: Dict[str, Any], cfg: Dict[str, Any], now: float) -> None:
    """Mail the manager one roll-up of every open aged row, at most per window. Never raises."""
    try:
        hours = float(cfg.get("rollup_hours", 24) or 0)
        if hours <= 0 or _send_email is None:
            return

        rows = [(sig, entry) for sig, entry in state.get("signatures", {}).items() if entry.get("aged_since")]
        if not rows:
            return
        rows.sort(key=lambda kv: _seen_order(kv[1]), reverse=True)

        current = sorted(sig for sig, _entry in rows)
        if not _rollup_is_due(state, current, hours, now):
            return

        recipient = str(cfg.get("digest_recipient", "@devpulse"))
        subject, body = build_rollup(rows, recipient, hours)
        if _send_email(
            to_branch=recipient,
            subject=subject,
            message=body,
            auto_execute=False,
            reply_to="@trigger",
            from_branch="@trigger",
            upsert_key=ROLLUP_UPSERT_KEY,
            upsert_result={},
        ):
            state["rollup_last_sent"] = datetime.now().isoformat()
            state["rollup_rows"] = current
            logger.info("aged roll-up sent", rows=len(rows), recipient=recipient, outcome="rollup_sent")
    except Exception as exc:
        logger.warning(f"roll-up failed: {exc}", outcome="rollup_failed")


def build_rollup(rows: List[Tuple[str, Dict[str, Any]]], recipient: str, hours: float) -> tuple:
    """Build the manager's roll-up of open aged rows."""
    lines = [
        f"  {sig}  @{entry.get('branch', '?').lower()}/{entry.get('module', '?')}  "
        f"x{entry.get('total_count', 0)} lifetime  aged since {entry.get('aged_since', 'unknown')}  "
        f"registry {str(entry.get('registry_fingerprint', ''))[:12] or 'none'}"
        for sig, entry in rows[:MAX_ROLLUP_LINES]
    ]
    if len(rows) > MAX_ROLLUP_LINES:
        lines.append(f"  ... and {len(rows) - MAX_ROLLUP_LINES} more")
    row_block = "\n".join(lines)

    subject = f"[ROLL-UP] {len(rows)} warning(s) repeating past their age limit"
    body = f"""Warnings that outlived their age limit — each one now belongs to the branch
that logged it, not to this inbox. One line per open row, every {hours:.0f}h.

{row_block}

Each row is mailed to its own branch on its own thread and carries a registry
row: drone @trigger errors list, then suppress (benign, silent) or resolve
(fixed — a recurrence is signal again).

---
This is an EMAIL, not a dispatch — nothing was woken. The repeat digests for
these signatures have stopped; this line replaces them.
Sent to {recipient} by @trigger."""

    return subject, body


def build_aged_notice(
    signature: str,
    entry: Dict[str, Any],
    window_count: int,
    window_seconds: int,
    recipient: str,
    siblings: Optional[List[Tuple[str, Dict[str, Any]]]],
    age: float,
    fingerprint: str,
) -> tuple:
    """Build the mail the logging branch gets once a warning has aged."""
    subject, body = build_digest(
        signature,
        entry,
        window_count,
        window_seconds,
        f"repeating for {age:.0f}h — this is yours now, not the manager's",
        recipient,
        siblings,
    )
    subject = subject.replace("[REPEAT]", f"[REPEAT {age:.0f}h]", 1)

    header = f"""This warning has been repeating for {age:.0f} hours, so it stops going to the
manager and comes to you — you are the branch that LOGGED it. If the line names
another branch as the one who can cure it, routing it is your call, not mine.

Registry row : {fingerprint or "not opened — the registry was unreachable"}
  fixed it      -> drone @trigger errors resolve {fingerprint[:12] or "<id>"}
  it is benign  -> drone @trigger errors suppress {fingerprint[:12] or "<id>"} "why"
Nothing was dispatched: this lane never wakes anyone, and medic does not
dispatch warnings at all.

"""
    return subject, header + body


def build_digest(
    signature: str,
    entry: Dict[str, Any],
    window_count: int,
    window_seconds: int,
    reason: str,
    recipient: str,
    siblings: Optional[List[Tuple[str, Dict[str, Any]]]] = None,
) -> tuple:
    """Build the digest subject and body; investigation must start from the mail alone."""
    level = entry.get("level", "ERROR")
    branch = entry.get("branch", "UNKNOWN")
    module = entry.get("module", "unknown")
    message = entry.get("message", "")
    window_minutes = max(1, window_seconds // 60)
    samples = entry.get("samples", [])
    sample_block = "\n".join(f"  {line}" for line in samples) if samples else "  (no samples captured)"

    siblings = siblings or []
    subject = f"[REPEAT] {level} x{window_count} @{branch.lower()} / {module}"
    if siblings:
        subject += f" ({len(siblings) + 1} signatures)"

    roster_block = ""
    if siblings:
        roster = [
            f"  {sig}  x{other.get('total_count', 0)}  last {other.get('last_seen', 'unknown')}  "
            f"{str(other.get('message', ''))[:MAX_ROSTER_MESSAGE_CHARS]}"
            for sig, other in siblings[:MAX_ROSTER_LINES]
        ]
        if len(siblings) > MAX_ROSTER_LINES:
            roster.append(f"  ... and {len(siblings) - MAX_ROSTER_LINES} more — drone @trigger escalation list")
        roster_lines = "\n".join(roster)
        roster_block = f"""
Other signatures in this thread ({len(siblings)}), newest first
{roster_lines}
"""

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
{roster_block}
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
    """Return tracked signatures, most recently seen first."""
    state = _load_state()
    rows = []
    for sig, entry in state.get("signatures", {}).items():
        if level and entry.get("level", "").upper() != level.upper():
            continue
        row = dict(entry)
        row["signature"] = sig
        row["window_count"] = len(entry.get("occurrences", []))
        rows.append(row)
    rows.sort(key=_seen_order, reverse=True)
    return rows[:limit]


def get_stats() -> Dict[str, Any]:
    """Return escalation lane statistics for the CLI."""
    cfg = get_config()
    state = _load_state()
    signatures = state.get("signatures", {})
    warnings = sum(1 for e in signatures.values() if e.get("level") == "WARNING")
    errors = sum(1 for e in signatures.values() if e.get("level") != "WARNING")
    digests = sum(int(e.get("digests_sent", 0)) for e in signatures.values())
    in_cooldown = sum(1 for e in signatures.values() if e.get("last_digest"))
    aged = sum(1 for e in signatures.values() if e.get("aged_since"))
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "digest_recipient": cfg.get("digest_recipient", "@devpulse"),
        "warning_threshold": cfg.get("warning_threshold", 10),
        "error_threshold": cfg.get("error_threshold", 5),
        "window_minutes": cfg.get("window_minutes", 60),
        "cooldown_minutes": cfg.get("cooldown_minutes", 360),
        "warning_age_hours": cfg.get("warning_age_hours", 24),
        "rollup_hours": cfg.get("rollup_hours", 24),
        "escalate_suppressed": bool(cfg.get("escalate_suppressed", False)),
        "watch_branch_log_warnings": bool(cfg.get("watch_branch_log_warnings", True)),
        "ignore_branches": cfg.get("ignore_branches", []),
        "tracked_signatures": len(signatures),
        "tracked_warnings": warnings,
        "tracked_errors": errors,
        "digests_sent": digests,
        "signatures_digested": in_cooldown,
        "aged_signatures": aged,
        "state_file": str(STATE_FILE),
        "config_file": str(config_loader.CONFIG_PATH),
        "email_wired": _send_email is not None,
        # The trail cannot log its own write failures, so they are counted here.
        "trail_writes_dropped": logger.dropped,
    }
