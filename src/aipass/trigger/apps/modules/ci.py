# =================== AIPass ====================
# Name: ci.py
# Description: CI red lane - poll dev's runs, wake the owner, gate the cure through @seedgo, push it through drone
# Version: 1.0.0
# Created: 2026-10-22
# Modified: 2026-10-22
# =============================================

"""
CI red lane - poll dev's runs, wake the owner of a red, gate its cure through @seedgo, push it
"""

import os
import sys
from typing import Any, Dict, List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.trigger.apps.handlers.ci import git_door, ledger, outbound, replies, triage
from aipass.trigger.apps.handlers.cli.help_flags import wants_help
from aipass.trigger.apps.handlers.events.ci_red import PAYLOAD_KEYS, run_url
from aipass.trigger.apps.handlers.json import json_handler
from aipass.trigger.apps.handlers.repo_root import find_repo_root
from aipass.trigger.apps.modules.core import trigger

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

_SUBCOMMANDS = ["poll", "status", "reply", "verdict"]
CHANGELOG_NAME = "CHANGELOG.md"


def print_introspection():
    """Display module introspection info."""
    from aipass.cli.apps.modules import console

    console.print()
    console.print("[bold cyan]ci Module[/bold cyan]")
    console.print("[dim]CI red lane — detect a red run on dev, wake its owner, review and push the cure[/dim]")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/ci/[/cyan]")
    console.print("    [cyan]•[/cyan] git_door.py [dim](run list, run view, diff, remote, the ci-cure door)[/dim]")
    console.print("    [cyan]•[/cyan] triage.py [dim](newest run per workflow, infra steps, owner mapping)[/dim]")
    console.print("    [cyan]•[/cyan] ledger.py [dim](trigger_json/ci_ledger.json — runs and cures)[/dim]")
    console.print("    [cyan]•[/cyan] replies.py [dim](owner and seedgo reply parsers, briefs, CHANGELOG insert)[/dim]")
    console.print("    [cyan]•[/cyan] outbound.py [dim](mail, dispatch, feed, the two-awake cap)[/dim]")
    console.print("  [cyan]handlers/events/[/cyan]")
    console.print("    [cyan]•[/cyan] ci_red.py [dim](handle_ci_red — medic's gates, then the owner's wake)[/dim]")
    console.print()


def print_help() -> None:
    """Display ci command help."""
    from aipass.cli.apps.modules import console

    console.print()
    console.print("[bold cyan]drone @trigger ci[/bold cyan] — the CI red lane")
    console.print()
    console.print("[yellow]Commands:[/yellow]")
    console.print("  [cyan]poll[/cyan]                            Read dev's runs, dispatch new reds, drain the queue")
    console.print("  [cyan]status[/cyan]                          The ledger: recent runs and every open cure")
    console.print("  [cyan]reply <run_id> @owner <text>[/cyan]    Take the owner's reply, dispatch @seedgo's review")
    console.print("  [cyan]verdict <run_id> @owner <text>[/cyan]  Seedgo's VERDICT: OK pushes, HELD mails @devpulse")
    console.print()
    console.print("[yellow]On a wake-back:[/yellow]")
    console.print('  A reply to [CI RED] run N @x     ->  drone @trigger ci reply N @x "<the reply body>"')
    console.print('  A reply to [CI REVIEW] run N @x  ->  drone @trigger ci verdict N @x "<the reply body>"')
    console.print()
    console.print("  [dim]The poll runs from .daemon/schedule.json. A hand fire walks the lane too:[/dim]")
    console.print("  [dim]drone @trigger fire ci_red run_id=<a red run id from drone @git run list>[/dim]")
    console.print()


def _wire_mail() -> None:
    """First use of the bus runs setup_handlers, which wires the mail adapter the lane sends through."""
    trigger.status()


def _observe(data: Dict[str, Any], row: Dict[str, str], newest_id: str) -> bool:
    """Record one dev run; True when it is a red seen for the first time as its workflow's newest."""
    run = data["runs"].setdefault(row["run_id"], {"verdict": "running"})
    run.update({k: row[k] for k in ("workflow", "event", "title", "created", "status", "conclusion")})
    if run.get("triaged") or row["status"] != "completed":
        return False
    if row["conclusion"] == "success":
        run.update(verdict="green", triaged=True)
        return False
    if row["run_id"] != newest_id:
        run.update(verdict="superseded", triaged=True)
        return False
    return True


def _proving(data: Dict[str, Any], rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Link each pushed cure to the first run of its workflow after the push; answers the notes owed."""
    notes = []
    for cure in data["cures"].values():
        if cure["state"] != "pushed":
            continue
        after = [
            r
            for r in rows
            if r["branch"] == "dev"
            and r["created"] >= cure.get("pushed_at", "")
            and r["workflow"] == (cure.get("workflow") or r["workflow"])
        ]
        if not after:
            continue
        proof = min(after, key=lambda r: (r["created"], int(r["run_id"])))
        if not cure.get("proving_run"):
            cure["proving_run"] = proof["run_id"]
            notes.append({"kind": "pushed", "cure": dict(cure)})
        if proof["status"] == "completed":
            cure["state"] = "cured" if proof["conclusion"] == "success" else "unproven"
            cure["updated"] = ledger.utc_now()
            if cure["state"] == "cured":
                notes.append({"kind": "green", "cure": dict(cure)})
    return notes


def _send_note(note: Dict[str, Any]) -> None:
    """The pushed note (with the proving run) and the one green note after a cure."""
    cure = note["cure"]
    run_id, owner, proof = cure["run_id"], cure["owner"], cure.get("proving_run", "")
    if note["kind"] == "pushed":
        body = (
            f"Cure for run {run_id} pushed by ci-cure as {cure.get('sha', '')}; run {proof} is proving it.\n\n"
            f"Owner: @{owner}\nFiles:\n" + "\n".join(f"  {p}" for p in cure.get("files", [])) + "\n\n"
            f"CHANGELOG: {cure.get('changelog', '') or '(none)'}\n\nOwner's note:\n{cure.get('note', '')}\n\n"
            f"Seedgo's lesson:\n{cure.get('lesson', '') or '(none)'}\n"
        )
        outbound.mail(outbound.MANAGER, f"[CI PUSHED] run {run_id} @{owner} - run {proof} proving it", body)
        return
    outbound.mail(
        outbound.MANAGER,
        f"[CI GREEN] run {proof} proves the cure of run {run_id} @{owner}",
        f"Run {proof} ({cure.get('workflow', '')}) is green: the cure of run {run_id} by @{owner} holds.\n",
    )
    title = f"CI green: {cure.get('workflow', '')} run {proof}, @{owner}'s cure holds"
    outbound.feed("green", title, f"proves run {run_id}", **{**cure, "run_id": proof})


def _triage_reds(reds: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Read each new red's failed log; infra reds get a feed event and their ledger mark, the rest a payload."""
    payloads, verdicts = [], {}
    for row in reds:
        run_id = row["run_id"]
        try:
            facts = triage.triage_log(git_door.run_view_failed(run_id)) if row["conclusion"] == "failure" else {}
        except git_door.DroneCallFailed as exc:
            logger.warning(f"[ci] run {run_id} log unread, retried next poll: {exc}")
            continue
        base = {"run_id": run_id, "workflow": row["workflow"], "url": run_url(run_id)}
        base.update(step=facts.get("step", ""), lines=facts.get("lines", []))
        if triage.is_infra(row["conclusion"], base["step"]):
            verdicts[run_id] = "infra"
            title = f"CI red (infra, no dispatch): {row['workflow']} run {run_id}"
            outbound.feed("red", title, f"{row['conclusion']} at {base['step'] or 'no step'}", **base)
            continue
        verdicts[run_id] = "red"
        owners = facts.get("owners") or [""]
        payloads.extend({**base, "owner": owner} for owner in owners)
    with ledger.update() as data:
        for run_id, verdict in verdicts.items():
            data["runs"][run_id].update(verdict=verdict, triaged=True)
    return payloads


def _drain(data: Dict[str, Any]) -> tuple:
    """Cures waiting on the cap: owner wakes to re-fire, seedgo reviews to re-request."""
    owners = [c for c in data["cures"].values() if c["state"] == "queued"]
    reviews = [key for key, c in data["cures"].items() if c["state"] == "review_queued"]
    return owners, reviews


def poll() -> Dict[str, Any]:
    """One pass of the lane: observe dev's runs, supersede, dispatch new reds, drain the queue, send notes."""
    _wire_mail()
    rows = triage.parse_run_list(git_door.run_list())
    newest = triage.newest_per_workflow(rows)
    with ledger.update() as data:
        reds = [r for r in rows if r["branch"] == "dev" and _observe(data, r, newest[r["workflow"]]["run_id"])]
        superseded = ledger.supersede(data, newest)
        notes = _proving(data, rows)
        queued, reviews = _drain(data)
    payloads = _triage_reds(reds)
    for payload in payloads + [{k: c.get(k) for k in PAYLOAD_KEYS} for c in queued]:
        trigger.fire("ci_red", **payload)
    for key in reviews:
        request_review(key)
    for note in notes:
        _send_note(note)
    summary = {"runs": len(rows), "new_reds": len(reds), "superseded": len(superseded), "drained": len(queued)}
    summary.update(reviews=len(reviews), notes=len(notes))
    json_handler.log_operation("ci_poll", summary)
    return summary


def _cure(key: str) -> Dict[str, Any]:
    """The cure under *key*; a missing one raises, naming the key."""
    cure = ledger.load()["cures"].get(key)
    if cure is None:
        raise KeyError(f"no cure {key} in the ledger")
    return cure


def _set(key: str, state: str, **fields: Any) -> Dict[str, Any]:
    """Move a cure under the ledger lock."""
    with ledger.update() as data:
        cure = data["cures"][key]
        return ledger.set_cure(data, cure["run_id"], cure["owner"], state, **fields)


def hold(key: str, reason: str) -> Dict[str, Any]:
    """Stop a cure: @devpulse gets the diff and the reason, nothing is pushed."""
    cure = _set(key, "held", reason=reason)
    run_id, owner = cure["run_id"], cure["owner"]
    body = (
        f"The cure of run {run_id} by @{owner} is held; nothing was pushed.\n\nReason:\n{reason}\n\n"
        f"Files:\n" + "\n".join(f"  {p}" for p in cure.get("files") or []) + "\n\n"
        f"CHANGELOG: {cure.get('changelog', '') or '(none)'}\n\nOwner's note:\n{cure.get('note', '') or '(none)'}\n\n"
        f"Diff:\n{cure.get('diff', '') or '(none)'}\n"
    )
    outbound.mail(outbound.MANAGER, f"[CI HELD] run {run_id} @{owner}", body)
    outbound.feed("held", f"CI cure held: run {run_id}, @{owner}", reason[:300], **cure)
    return cure


def request_review(key: str) -> str:
    """Dispatch @seedgo once with the cure's diff, or queue it while two citizens are awake."""
    cure = _cure(key)
    if not outbound.cap_allows():
        _set(key, "review_queued", reason="two citizens awake")
        return "review_queued"
    subject = f"[CI REVIEW] run {cure['run_id']} @{cure['owner']} - {cure.get('workflow', '')}"
    if not outbound.dispatch(outbound.REVIEWER, subject, replies.seedgo_brief(cure)):
        _set(key, "review_queued", reason="mail not delivered")
        return "review_queued"
    _set(key, "reviewing", reason="")
    outbound.feed("dispatched", f"CI cure to @seedgo for review: run {cure['run_id']}", subject, **cure)
    return "reviewing"


def take_reply(run_id: str, owner: str, text: str) -> str:
    """The owner's wake-back: parse the reply, take the diff, then hold or send to review."""
    key = ledger.cure_key(run_id, owner)
    cure = _cure(key)
    if cure["state"] not in ("dispatched", "emailed"):
        raise ValueError(f"cure {key} is {cure['state']}, not waiting on its owner")
    reply = replies.parse_owner_reply(text)
    _set(key, "replied", files=reply["files"], changelog=reply["changelog"], note=reply["note"])
    if reply["files"] is None:
        return hold(key, "The owner's reply has no FILES: block.")["state"]
    if not reply["files"]:
        return hold(key, "The owner's FILES: block names no file.")["state"]
    refused = replies.outside_owner_tree(reply["files"], cure["owner"])
    if refused:
        return hold(key, "Outside the owner's tree, the cure door refuses: " + ", ".join(refused))["state"]
    try:
        diff = git_door.diff(reply["files"])
    except git_door.DroneCallFailed as exc:
        return hold(key, f"The diff could not be read: {exc}")["state"]
    _set(key, "replied", diff=diff)
    return request_review(key)


def push(key: str) -> str:
    """Seedgo said OK: append the bullet, call the ci-cure door; any refusal restores CHANGELOG and holds."""
    cure = _cure(key)
    paths = list(cure.get("files") or [])
    original = None
    changelog = find_repo_root(caller="ci") / CHANGELOG_NAME
    # Stamped before the door: the proving run is the first one created after this instant.
    started = ledger.utc_now()
    try:
        if cure.get("changelog"):
            original = replies.append_changelog(changelog, cure["changelog"])
            paths += [] if CHANGELOG_NAME in paths else [CHANGELOG_NAME]
        message = replies.commit_message(cure["owner"], cure["run_id"], cure.get("changelog", ""), cure.get("note", ""))
        pushed, sha, output = git_door.ci_cure(cure["run_id"], cure["owner"], message, paths)
    except (OSError, ValueError, git_door.DroneCallFailed) as exc:
        pushed, sha, output = False, "", str(exc)
    if not pushed and sha:
        # The door commits before it pushes: the bullet is in that commit, so the tree keeps it.
        _set(key, "held", sha=sha)
        return hold(key, f"ci-cure committed {sha} on dev but the push failed:\n{output.strip()[-1500:]}")["state"]
    if not pushed:
        if original is not None:
            replies.restore_changelog(changelog, original)
        return hold(key, f"The ci-cure door did not push:\n{output.strip()[-1500:]}")["state"]
    cure = _set(key, "pushed", sha=sha, pushed_at=started)
    outbound.feed("pushed", f"CI cure pushed: run {cure['run_id']}, @{cure['owner']} as {sha[:10]}", sha, **cure)
    return "pushed"


def take_verdict(run_id: str, owner: str, text: str) -> str:
    """Seedgo's wake-back: OK pushes, HELD mails @devpulse; a reply in neither shape changes nothing."""
    key = ledger.cure_key(run_id, owner)
    cure = _cure(key)
    if cure["state"] != "reviewing":
        raise ValueError(f"cure {key} is {cure['state']}, not under review")
    verdict = replies.parse_verdict(text)
    if verdict is None:
        raise ValueError("seedgo's reply must start with VERDICT: OK or VERDICT: HELD")
    _set(key, "reviewing", verdict=verdict["verdict"], lesson=verdict["body"])
    if verdict["verdict"] == "HELD":
        return hold(key, f"@seedgo: VERDICT: HELD\n{verdict['body']}")["state"]
    return push(key)


def _print_status() -> None:
    """Render the ledger: the newest runs, then every cure still in the lane."""
    from aipass.cli.apps.modules import console

    data = ledger.load()
    runs = sorted(data["runs"].items(), key=lambda item: item[1].get("created", ""), reverse=True)[:12]
    console.print()
    console.print(f"[bold cyan]CI ledger[/bold cyan] [dim]{ledger.LEDGER_FILE}[/dim]")
    for run_id, run in runs:
        verdict, workflow = run.get("verdict", "?"), run.get("workflow", "")
        console.print(f"  {run_id}  {verdict:<11} {workflow} [dim]{run.get('created', '')}[/dim]")
    console.print()
    open_cures = [c for c in data["cures"].values() if c["state"] not in ("cured", "superseded")]
    console.print(f"[bold cyan]Cures[/bold cyan] [dim]({len(open_cures)} not cured)[/dim]")
    for cure in open_cures:
        reason = f" [dim]{cure.get('reason', '')[:60]}[/dim]" if cure.get("reason") else ""
        console.print(f"  run {cure['run_id']} @{cure['owner']:<10} {cure['state']}{reason}")
    console.print()


def _run_subcommand(subcommand: str, args: List[str]) -> bool:
    """Run one ci subcommand; a refusal goes out through error() so the exit code says so."""
    from aipass.cli.apps.modules import console, error, success

    if subcommand == "status":
        _print_status()
        return True
    if subcommand == "poll":
        summary = poll()
        success(f"CI poll: {summary['runs']} runs, {summary['new_reds']} new red, {summary['drained']} drained")
        console.print(f"  [dim]{summary}[/dim]")
        return True
    if len(args) < 3 or not args[0].isdigit() or not args[1].startswith("@"):
        error(f"Usage: drone @trigger ci {subcommand} <run_id> @owner <reply text>")
        return True
    take = take_reply if subcommand == "reply" else take_verdict
    state = take(args[0], args[1].lstrip("@").lower(), " ".join(args[2:]))
    success(f"run {args[0]} {args[1]}: {state}")
    return True


def handle_command(command: str, args: list) -> bool:
    """Handle `ci` and its verbs; claims the module name only."""
    from aipass.cli.apps.modules import error

    if command != "ci":
        return False
    if not args:
        print_introspection()
        return True
    if wants_help(args):
        print_help()
        return True
    if args[0] not in _SUBCOMMANDS:
        return False
    try:
        handled = _run_subcommand(args[0], args[1:])
    except (KeyError, ValueError, RuntimeError, OSError) as exc:
        logger.warning(f"[ci] {args[0]} refused: {exc}")
        error(f"ci {args[0]}: {exc}")
        handled = True
    json_handler.log_operation("ci_command", {"command": args[0]})
    return handled


if __name__ == "__main__":
    if len(sys.argv) == 1 or sys.argv[1] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    handle_command("ci", sys.argv[1:])
