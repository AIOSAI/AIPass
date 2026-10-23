# =================== AIPass ====================
# Name: ci_red.py
# Description: ci_red event handler - wakes the owner of a red CI run through medic's dispatch gates
# Version: 1.1.0
# Created: 2026-10-22
# Modified: 2026-10-23
# =============================================

"""
CI Red Event Consumer

Payload: run_id (required), workflow, step, owner, lines, url. With no owner and no lines the
handler triages the run itself, so a hand fire of a bare run id walks the whole lane.
"""

from typing import Any, Dict, List

from aipass.trigger.apps.config import TRIGGER_ROOT, trail_logger
from aipass.trigger.apps.handlers import error_registry, escalation
from aipass.trigger.apps.handlers.ci import git_door, ledger, outbound, replies, triage
from aipass.trigger.apps.handlers.events import error_detected as medic
from aipass.trigger.apps.handlers.json import json_handler

# Not prax: this runs on the watched event path, so a prax line would fire straight back at it.
logger = trail_logger(TRIGGER_ROOT / "logs" / "ci_lane.jsonl")

PAYLOAD_KEYS = ("run_id", "workflow", "step", "owner", "lines", "url", "fingerprint")
# Cures still waiting on a gate or the cap: every poll fires them again until one dispatches.
RETRIED_STATES = ("queued", "gated")


def run_url(run_id: str) -> str:
    """The run's page on GitHub, from origin's slug; empty when origin cannot be read."""
    try:
        slug = git_door.repo_slug()
    except Exception as exc:
        logger.warning(f"run URL not resolved for {run_id}: {exc}")
        return ""
    return f"https://github.com/{slug}/actions/runs/{run_id}" if slug else ""


def _as_lines(lines: Any) -> List[str]:
    """Lines from the bus: a list from the poll, one string from a hand fire."""
    if isinstance(lines, str):
        return [line for line in lines.split("\n") if line.strip()]
    return [str(line) for line in (lines or [])]


def _fingerprint(owner: str, workflow: str, step: str) -> str:
    """Register the red in the error registry so suppression, backoff and the digest apply to it."""
    entry = error_registry.report(
        error_type="ci_red", message=f"CI red: {workflow} / {step}", component=owner, severity="high"
    )
    return str(entry.get("fingerprint", ""))


def _gate_reason(owner: str, fingerprint: str, fresh: bool = True) -> str:
    """The first of medic's gates that refuses this owner, in medic's order; empty when all are open.

    A retry is not a new error, so only a fresh red feeds the breaker."""
    if not medic._is_medic_enabled():
        return "Medic OFF - suppressed dispatch for"
    if medic._is_branch_muted(owner):
        return "Branch muted - suppressed dispatch for"
    if f"@{owner}" not in medic._get_registered_emails():
        return f"Unknown branch skipped: @{owner}"
    if fresh:
        medic.circuit_breaker_record_error()
    if not medic.circuit_breaker_allows():
        return "Circuit breaker OPEN - suppressed dispatch for"
    if fingerprint and not medic.registry_should_dispatch(fingerprint):
        return f"Suppressed or backing off {fingerprint[:12]} - no dispatch for"
    return ""


def _gate(payload: Dict[str, Any], fresh: bool) -> str:
    """Run the gates and write a refusal to medic's suppression log, where medic status counts it."""
    reason = _gate_reason(payload["owner"], payload["fingerprint"], fresh)
    if reason:
        message = f"CI red run {payload['run_id']}: {payload['workflow']} / {payload['step']}"
        medic._write_suppression_log(reason, payload["owner"], "ci", message)
    return reason


def _record_run(payload: Dict[str, Any], verdict: str) -> None:
    """A hand-fired run gets its ledger row too, so `ci status` and the poll know it."""
    with ledger.update() as data:
        run = data["runs"].setdefault(str(payload["run_id"]), {"workflow": payload.get("workflow", "")})
        run.update(verdict=verdict, step=payload.get("step", ""), url=payload.get("url", ""), triaged=True)


def _unowned(payload: Dict[str, Any]) -> None:
    """No branch named in the log: @devpulse gets the excerpt, the ledger marks the run unowned."""
    run_id = payload["run_id"]
    if ledger.load()["runs"].get(run_id, {}).get("verdict") == "unowned":
        return
    _record_run(payload, "unowned")
    excerpt = "\n".join(payload["lines"]) or "(no failing lines captured)"
    outbound.mail(
        outbound.MANAGER,
        f"[CI UNOWNED] run {run_id} - {payload['workflow']}: {payload['step']}",
        f"A red run names no branch, so nobody was woken.\n\nRun: {run_id}\nWorkflow: {payload['workflow']}\n"
        f"Step: {payload['step']}\nURL: {payload['url'] or '(not resolved)'}\n\nFailing lines:\n{excerpt}\n",
    )
    outbound.feed("unowned", f"CI red, no owner: {payload['workflow']} run {run_id}", excerpt[:300], **payload)


def _dispatch_owner(payload: Dict[str, Any]) -> str:
    """Gate, then wake the owner with its brief; answers the cure's new state."""
    owner = payload["owner"] = payload["owner"].lstrip("@").lower()
    key = ledger.cure_key(payload["run_id"], owner)
    existing = ledger.load()["cures"].get(key)
    if existing and existing["state"] not in RETRIED_STATES:
        return existing["state"]
    if not payload.get("fingerprint"):
        payload["fingerprint"] = _fingerprint(owner, payload["workflow"], payload["step"])
    message = f"CI red: {payload['workflow']} / {payload['step']}"
    if existing is None:
        # Count before every gate, as medic does: a mute stops the wake, never the count.
        escalation.record_error(branch=owner, module="ci", message=message, fingerprint=payload["fingerprint"])
        _record_run(payload, "red")
        outbound.feed("red", f"CI red: {payload['workflow']} on dev, @{owner}", message, **payload)
    stored = {k: payload.get(k) for k in PAYLOAD_KEYS}
    reason = _gate(payload, fresh=existing is None)
    recipient = f"@{owner}"
    if reason:
        state = "gated"
    elif recipient != outbound.MANAGER and not outbound.cap_allows():
        state, reason = "queued", "two citizens awake"
    else:
        subject = f"[CI RED] run {payload['run_id']} @{owner} - {payload['workflow']}: {payload['step']}"
        sent = outbound.dispatch(recipient, subject, replies.owner_brief(payload))
        state = ("emailed" if recipient == outbound.MANAGER else "dispatched") if sent else "queued"
        reason = "" if sent else "mail not delivered"
        if sent:
            medic.registry_record_dispatch(payload["fingerprint"])
            medic.circuit_breaker_probe_succeeded()
            outbound.feed("dispatched", f"CI red sent to @{owner}: run {payload['run_id']}", subject, **payload)
    with ledger.update() as data:
        ledger.set_cure(data, payload["run_id"], owner, state, reason=reason, **stored)
    json_handler.log_operation("ci_red_handled", {"owner": owner, "state": state})
    return state


def _triaged(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fill a bare run id from drone: workflow from the run list, step, lines and owners from the log."""
    run_id = payload["run_id"]
    if not payload["workflow"]:
        rows = triage.parse_run_list(git_door.run_list())
        payload["workflow"] = next((r["workflow"] for r in rows if r["run_id"] == run_id), "")
    facts = triage.triage_log(git_door.run_view_failed(run_id))
    payload.update(step=payload["step"] or facts["step"], lines=facts["lines"])
    payload["url"] = payload["url"] or run_url(run_id)
    return [{**payload, "owner": owner} for owner in facts["owners"]] or [{**payload, "owner": ""}]


def handle_ci_red(
    run_id: Any = None,
    workflow: str = "",
    step: str = "",
    owner: str = "",
    lines: Any = None,
    url: str = "",
    fingerprint: str = "",
    **kwargs: Any,
) -> None:
    """Handle ci_red - dispatch the run's owner, or mail @devpulse when it has none."""
    # Silent by contract: never raises, never prints, never logs through prax.
    try:
        if not run_id:
            return
        payload: Dict[str, Any] = {
            "run_id": str(run_id),
            "workflow": str(workflow or ""),
            "step": str(step or ""),
            "owner": str(owner or ""),
            "lines": _as_lines(lines),
            "url": str(url or ""),
            "fingerprint": str(fingerprint or ""),
        }
        targets = _triaged(payload) if not payload["owner"] and not payload["lines"] else [payload]
        for target in targets:
            if target["owner"]:
                _dispatch_owner(target)
            else:
                _unowned(target)
    except Exception as exc:
        logger.warning(f"handle_ci_red failed for run {run_id}: {exc}")
