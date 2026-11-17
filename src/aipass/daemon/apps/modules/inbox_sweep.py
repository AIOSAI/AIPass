# =================== AIPass ====================
# Name: inbox_sweep.py
# Description: Fleet inbox sweep — wake branches sitting on mail unread past 24h
# Version: 1.5.0
# Created: 2026-08-11
# Modified: 2026-11-15
# =============================================

"""
Inbox sweep — the fleet's unread-mail backstop (drone @daemon inbox-sweep).

Replies never wake their recipient, so the sweep wakes the owner of any inbox holding NEW mail older than 24h.
Hand tool only: nothing scheduled calls it (the nightly rotation takes each inbox to zero); --dry-run is the cheap look.

Rules: one wake per branch per sweep; managers are never woken (reported as skipped);
MAX_WAKES caps a pass and deferred branches are named.

Scope is the whole fleet (framework branches, projects/*/ residents, externals), because
find_stale_inboxes() walks discovery's branch map, not AIPASS_REGISTRY.json.
"""

import time
from typing import List

from aipass.prax import logger
from aipass.cli import console, error
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.cli.arg_gate import gate
from aipass.daemon.apps.handlers.monitoring.inbox_scanner import (
    DEFAULT_STALE_HOURS,
    find_stale_inboxes,
)

HANDLED_COMMANDS = {"inbox-sweep", "inbox_sweep"}

# Skip reason owned here — the blocklist is wake policy, not mailbox state.
SKIP_BLOCKLIST = "wake-blocklist"

# Wakes spawn Claude sessions; entries are oldest-first, so the cap defers the freshest stale mailboxes.
MAX_WAKES = 5

# Seconds between wakes — staggers process spawns, same guard as the run tick.
WAKE_STAGGER_SECONDS = 2.0

# Light model: the woken agent reads its inbox and acts, it does not build.
WAKE_MODEL = "sonnet"


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]inbox-sweep Module[/bold cyan]")
    console.print()
    console.print("[dim]Wakes branches sitting on mail unread past 24h[/dim]")
    console.print()
    console.print("[yellow]Reads:[/yellow]")
    console.print("  [cyan]*[/cyan] <citizen>/.ai_mail.local/inbox.json [dim](per-branch mailboxes)[/dim]")
    console.print("  [cyan]*[/cyan] the fleet definition [dim](@memory's fleet gateway — every registry)[/dim]")
    console.print()
    console.print("[yellow]Wakes via:[/yellow]")
    console.print("  [cyan]*[/cyan] wake_branch() [dim](ai_mail dispatch — direct import)[/dim]")
    console.print()


def print_help():
    """Display usage information."""
    console.print("\n[bold cyan]inbox-sweep — Fleet Unread-Mail Backstop[/bold cyan]")
    console.print("\n[yellow]USAGE:[/yellow]")
    console.print("  drone @daemon inbox-sweep              Wake owners of stale unread mail")
    console.print("  drone @daemon inbox-sweep --dry-run    Show who WOULD wake, wake nobody")
    console.print("  drone @daemon inbox-sweep --hours N    Staleness threshold (default 24)")
    console.print("  drone @daemon inbox-sweep --limit N    Max branches to wake (default 5)")
    console.print("  drone @daemon inbox-sweep --help       Show this help message")
    console.print("\n[yellow]DESCRIPTION:[/yellow]")
    console.print("  Replies never wake their recipient, so unread mail sits invisible in")
    console.print("  sleeping branches. This sweep reads every active branch's inbox.json")
    console.print("  and wakes the owner of any mailbox holding NEW mail past the threshold.")
    console.print("\n[yellow]RULES:[/yellow]")
    console.print("  [cyan]*[/cyan] One wake per branch per sweep")
    console.print("  [cyan]*[/cyan] Managers are never woken — their mail lands live")
    console.print(f"  [cyan]*[/cyan] At most {MAX_WAKES} wakes per pass, oldest mailbox first")
    console.print("\n[yellow]SCHEDULE:[/yellow]")
    console.print("  None — hand tool only since 2026-09-10. The nightly rounds")
    console.print("  (drone @daemon rotation) take each citizen's inbox to zero.")
    console.print()


def _event(message: str) -> None:
    """One sweep event: the prax line is the record, the console line the hand run's report."""
    logger.info("[inbox_sweep] %s", message)
    console.print(message)


def _apply_wake_policy(entries: List[dict]) -> None:
    """Stamp ai_mail's wake blocklist onto scanner entries, in place.

    The scanner reports mailbox state; eligibility to be woken is decided here,
    against the same blocklist wake_branch itself enforces.
    """
    from aipass.ai_mail.apps.modules.door_wake import is_wake_blocked

    for entry in entries:
        if entry["skip_reason"] is None and is_wake_blocked(entry["owner"]):
            entry["skip_reason"] = SKIP_BLOCKLIST


def _wake_message(entry: dict) -> str:
    """Build the custom wake prompt for a branch with stale mail."""
    count = entry["stale_count"]
    plural = "s" if count != 1 else ""
    return (
        f"You have {count} unread email{plural} sitting in your inbox — the oldest is "
        f"{entry['oldest_age_hours']:.0f}h old, from {entry['oldest_from']}: "
        f'"{entry["oldest_subject"]}". Check inbox, process the mail, reply where a '
        f"reply is owed, and update your memories when done."
    )


def _wake_owner(entry: dict) -> tuple:
    """Wake one branch owner. Returns (ok: bool, detail: str)."""
    from aipass.ai_mail.apps.modules.door_wake import wake_branch

    owner = entry["owner"]
    _event(f"WAKE: {owner} — {entry['stale_count']} unread, oldest {entry['oldest_age_hours']:.0f}h")

    try:
        status, ok = wake_branch(
            owner,
            custom_message=_wake_message(entry),
            fresh=True,
            auto=True,
            sender="@daemon",
            model=WAKE_MODEL,
            # A nudge, not a dispatch: the woken branch owes @daemon no reply.
            wake_back=False,
        )
    except Exception as e:
        logger.error("[inbox_sweep] Exception waking %s: %s", owner, e)
        error(f"{owner} — {e}")
        return False, str(e)

    if ok:
        logger.info("[inbox_sweep] Woke %s (%d unread)", owner, entry["stale_count"])
        console.print(f"OK: {owner} — {status.summary}")
        return True, status.summary

    logger.warning("[inbox_sweep] Wake failed for %s: %s", owner, status.summary)
    console.print(f"FAIL: {owner} — {status.summary}")
    return False, status.summary


def _report_candidates(stale: List[dict], skipped: List[dict]) -> None:
    """Print the scan result before any wake happens."""
    console.print()
    console.print("[bold cyan]Stale Unread Mail[/bold cyan]")
    console.print()
    console.print(f"  {'BRANCH':<13} {'UNREAD':<7} {'OLDEST':<7} {'FROM':<13} SUBJECT")
    console.print("  " + "-" * 74)
    for entry in stale + skipped:
        subject = entry["oldest_subject"]
        subject = subject[:29] + "..." if len(subject) > 29 else subject
        # Pad before wrapping in markup — Rich tags count toward f-string width.
        row = (
            f"{entry['owner']:<13} {entry['stale_count']:<7} "
            f"{entry['oldest_age_hours']:.0f}h{'':<4} {entry['oldest_from']:<13} {subject}"
        )
        console.print(f"  [dim]{row}[/dim]" if entry["skip_reason"] else f"  {row}")
    console.print()


def run_sweep(dry_run: bool = False, stale_hours: int = DEFAULT_STALE_HOURS, limit: int = MAX_WAKES) -> dict:
    """
    Execute one inbox sweep — scan every branch, wake stale-mail owners.

    Returns a summary dict with counts and the branches involved.
    """
    results = {
        "stale_branches": 0,
        "wakeable": 0,
        "woken": 0,
        "failed": 0,
        "skipped": 0,
        "deferred": 0,
        "wake_targets": [],
        "skipped_targets": [],
        "deferred_targets": [],
    }

    json_handler.log_operation("inbox_sweep", {"dry_run": dry_run, "stale_hours": stale_hours})

    console.print(f"Scanning branch inboxes for mail unread past {stale_hours}h...")
    entries = find_stale_inboxes(stale_hours=stale_hours)
    results["stale_branches"] = len(entries)

    if not entries:
        console.print("No branch is sitting on stale unread mail.")
        return results

    _apply_wake_policy(entries)

    skipped = [e for e in entries if e["skip_reason"]]
    wakeable = [e for e in entries if not e["skip_reason"]]
    results["wakeable"] = len(wakeable)
    results["skipped"] = len(skipped)
    results["skipped_targets"] = [f"{e['owner']} ({e['skip_reason']})" for e in skipped]

    _report_candidates(wakeable, skipped)

    for entry in skipped:
        _event(f"SKIP: {entry['owner']} — {entry['skip_reason']}, mail lands live")

    targets = wakeable[:limit]
    deferred = wakeable[limit:]
    results["wake_targets"] = [e["owner"] for e in targets]
    results["deferred"] = len(deferred)
    results["deferred_targets"] = [e["owner"] for e in deferred]

    if deferred:
        names = ", ".join(e["owner"] for e in deferred)
        _event(f"DEFERRED (limit {limit}): {names} — will be picked up by the next sweep")

    if dry_run:
        names = ", ".join(e["owner"] for e in targets) or "nobody"
        console.print(f"DRY RUN — would wake: {names}")
        return results

    for index, entry in enumerate(targets):
        ok, _detail = _wake_owner(entry)
        if ok:
            results["woken"] += 1
        else:
            results["failed"] += 1
        if index < len(targets) - 1:
            time.sleep(WAKE_STAGGER_SECONDS)

    _event(
        f"Sweep complete: {results['woken']} woken, {results['failed']} failed, "
        f"{results['skipped']} skipped, {results['deferred']} deferred"
    )
    return results


def _parse_int_flag(args: List[str], flag: str, default: int) -> int:
    """Read a positive integer following `flag`, or default when absent; below 1 a slice would bypass the cap."""
    if flag not in args:
        return default
    position = args.index(flag)
    raw = args[position + 1] if position + 1 < len(args) else ""
    if not raw.isdecimal() or int(raw) < 1:
        raise ValueError(f"{flag} needs a whole number of 1 or more, got {raw!r}")
    return int(raw)


def handle_command(command: str, args: List[str]) -> bool:
    """Handle 'inbox-sweep' command from daemon CLI router."""
    if command not in HANDLED_COMMANDS:
        return False

    if args and args[0] in ("--help", "-h"):
        print_help()
        return True

    gate(
        "inbox-sweep",
        args,
        flags=("--dry-run",),
        value_flags=("--hours", "--limit"),
        usage="drone @daemon inbox-sweep [--dry-run] [--hours N] [--limit N]",
    )

    dry_run = "--dry-run" in args
    stale_hours = _parse_int_flag(args, "--hours", DEFAULT_STALE_HOURS)
    limit = _parse_int_flag(args, "--limit", MAX_WAKES)

    console.print("=" * 60)
    console.print("Fleet inbox sweep")

    run_sweep(dry_run=dry_run, stale_hours=stale_hours, limit=limit)

    console.print("=" * 60)
    return True
