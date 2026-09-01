# =================== AIPass ====================
# Name: inbox_sweep.py
# Description: Fleet inbox sweep — wake branches sitting on mail unread past 24h
# Version: 1.1.0
# Created: 2026-08-11
# Modified: 2026-08-31
# =============================================

"""
Inbox sweep — the fleet's unread-mail backstop (drone @daemon inbox-sweep).

Replies never wake their recipient, so a reply landing in a sleeping branch's
inbox stays invisible indefinitely. This sweep looks at every branch mailbox
and wakes the owner of any inbox holding NEW mail older than 24h.

Rules:
  - at most one wake per branch per sweep
  - managers are never woken (they read mail live) — reported as skipped
  - MAX_WAKES caps a single pass; deferred branches are named, not dropped
"""

import time
from typing import List

from aipass.prax import logger
from aipass.cli.apps.modules import console
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.monitoring.inbox_scanner import (
    DEFAULT_STALE_HOURS,
    find_stale_inboxes,
)

HANDLED_COMMANDS = {"inbox-sweep", "inbox_sweep"}

# Skip reason owned here — the blocklist is wake policy, not mailbox state.
SKIP_BLOCKLIST = "wake-blocklist"

# Wakes spawn Claude sessions — capping one pass keeps a fleet-wide backlog from
# starting a dozen at once. Entries are oldest-first, so the cap defers the
# freshest stale mailboxes to tomorrow's sweep (and says so).
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
    console.print("  [cyan]*[/cyan] src/aipass/*/.ai_mail.local/inbox.json [dim](per-branch mailboxes)[/dim]")
    console.print("  [cyan]*[/cyan] AIPASS_REGISTRY.json [dim](active branches)[/dim]")
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
    console.print("  Runs daily from .daemon/schedule.json (job id: inbox-sweep)")
    console.print()


def _log(message: str) -> None:
    """Print timestamped log line."""
    from datetime import datetime

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    console.print(f"[{timestamp}] {message}")


def _apply_wake_policy(entries: List[dict]) -> None:
    """Stamp ai_mail's wake blocklist onto scanner entries, in place.

    The scanner reports mailbox state; eligibility to be woken is decided here,
    against the same blocklist wake_branch itself enforces.
    """
    try:
        from aipass.ai_mail.apps.handlers.dispatch.wake import is_wake_blocked
    # OSError, not only ImportError: MEASURED 2026-08-31 - this import raises
    # FileNotFoundError under a dead working directory, and the sweep must degrade
    # rather than crash on an optional consult.
    except (ImportError, OSError) as e:
        logger.warning("[inbox_sweep] Wake blocklist unavailable, skipping policy check: %s", e)
        return

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
    # Cross-branch handler import authorized by DPLAN-0204 §2.8 (same path as run.py)
    from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

    owner = entry["owner"]
    _log(f"WAKE: {owner} — {entry['stale_count']} unread, oldest {entry['oldest_age_hours']:.0f}h")

    try:
        status, ok = wake_branch(
            owner,
            custom_message=_wake_message(entry),
            fresh=True,
            auto=True,
            sender="@daemon",
            model=WAKE_MODEL,
        )
    except Exception as e:
        logger.error("[inbox_sweep] Exception waking %s: %s", owner, e)
        _log(f"ERROR: {owner} — {e}")
        return False, str(e)

    if ok:
        logger.info("[inbox_sweep] Woke %s (%d unread)", owner, entry["stale_count"])
        _log(f"OK: {owner} — {status.summary}")
        return True, status.summary

    logger.warning("[inbox_sweep] Wake failed for %s: %s", owner, status.summary)
    _log(f"FAIL: {owner} — {status.summary}")
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

    _log(f"Scanning branch inboxes for mail unread past {stale_hours}h...")
    entries = find_stale_inboxes(stale_hours=stale_hours)
    results["stale_branches"] = len(entries)

    if not entries:
        _log("No branch is sitting on stale unread mail.")
        return results

    _apply_wake_policy(entries)

    skipped = [e for e in entries if e["skip_reason"]]
    wakeable = [e for e in entries if not e["skip_reason"]]
    results["wakeable"] = len(wakeable)
    results["skipped"] = len(skipped)
    results["skipped_targets"] = [f"{e['owner']} ({e['skip_reason']})" for e in skipped]

    _report_candidates(wakeable, skipped)

    for entry in skipped:
        _log(f"SKIP: {entry['owner']} — {entry['skip_reason']}, mail lands live")

    targets = wakeable[:limit]
    deferred = wakeable[limit:]
    results["wake_targets"] = [e["owner"] for e in targets]
    results["deferred"] = len(deferred)
    results["deferred_targets"] = [e["owner"] for e in deferred]

    if deferred:
        names = ", ".join(e["owner"] for e in deferred)
        _log(f"DEFERRED (limit {limit}): {names} — will be picked up by the next sweep")

    if dry_run:
        names = ", ".join(e["owner"] for e in targets) or "nobody"
        _log(f"DRY RUN — would wake: {names}")
        return results

    for index, entry in enumerate(targets):
        ok, _detail = _wake_owner(entry)
        if ok:
            results["woken"] += 1
        else:
            results["failed"] += 1
        if index < len(targets) - 1:
            time.sleep(WAKE_STAGGER_SECONDS)

    _log(
        f"Sweep complete: {results['woken']} woken, {results['failed']} failed, "
        f"{results['skipped']} skipped, {results['deferred']} deferred"
    )
    return results


def _parse_int_flag(args: List[str], flag: str, default: int) -> int:
    """Read an integer value following `flag`. Falls back to default."""
    if flag not in args:
        return default
    position = args.index(flag)
    if position + 1 >= len(args):
        logger.info("[inbox_sweep] %s given without a value, using %d", flag, default)
        return default
    try:
        return int(args[position + 1])
    except ValueError:
        logger.info("[inbox_sweep] %s value %r is not an integer, using %d", flag, args[position + 1], default)
        return default


def handle_command(command: str, args: List[str]) -> bool:
    """Handle 'inbox-sweep' command from daemon CLI router."""
    if command not in HANDLED_COMMANDS:
        return False

    if args and args[0] in ("--help", "-h"):
        print_help()
        return True

    dry_run = "--dry-run" in args
    stale_hours = _parse_int_flag(args, "--hours", DEFAULT_STALE_HOURS)
    limit = _parse_int_flag(args, "--limit", MAX_WAKES)

    _log("=" * 60)
    _log("Fleet inbox sweep")

    run_sweep(dry_run=dry_run, stale_hours=stale_hours, limit=limit)

    _log("=" * 60)
    return True
