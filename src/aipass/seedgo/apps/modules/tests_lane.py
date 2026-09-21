# =================== AIPass ====================
# Name: tests_lane.py
# Description: Tests Lane Module — the retire lane and the test-template distribution
# Version: 1.0.0
# Created: 2026-09-21
# Modified: 2026-09-21
# =============================================

"""Tests Lane Module

Two lanes over a branch's ``tests/`` directory, neither of which reads or
writes a test's body.

The RETIRE lane: a test file leaves by a logged move to
``<repo>/.backup/tests/<branch>/`` and can come back. ``tests retired`` lists
what is there with its log line; ``tests restore NAME`` moves one back.

The TEMPLATE lane: seedgo is the gold source of the fleet's test template
(owner 2026-09-20 22:50, DPLAN-0354), on @memory's trinity pattern.
``tests template-status`` reads every branch's receipt against gold;
``tests template bump`` reports, and with ``--confirm`` writes.

Run: seedgo tests retired
"""

import json
import sys
from typing import List

# =============================================================================
# INFRASTRUCTURE SETUP
# =============================================================================

# IMPORTS
# =============================================================================

# Prax logger (system-wide, always first)
from aipass.prax import logger

# JSON handler for tracking
from aipass.seedgo.apps.handlers.json import json_handler

# CLI services (display/output formatting)
from aipass.cli import console, header
from aipass.cli.apps.modules import error as display_error, warning

# Handlers (implementation)
from aipass.seedgo.apps.handlers.cli.help_flags import wants_help
from aipass.seedgo.apps.handlers.module_root import module_file
from aipass.seedgo.apps.handlers.tests_lane import retire_ops, template_ops
from aipass.seedgo.apps.modules import CommandRefused

#: An argument nobody recognised. The vocabulary is
#: handlers/audit_tests/refusal.py's, so one code never means two things.
EXIT_UNKNOWN_ARGUMENT = 7

#: This branch. The retire lane is per-branch and seedgo only ever operates its
#: own: another branch's retirement is that branch's move to make.
BRANCH = "seedgo"

_SUBCOMMANDS = {
    "retired": "What is in the retire lane, with the line that put it there",
    "restore": "Move one retired test file back into tests/",
    "template-status": "Every branch's template receipt against gold",
    "template": "template bump [@branch] [--confirm] — report, or write the receipts",
}


# =============================================================================
# COMMAND HANDLER
# =============================================================================


def print_introspection() -> None:
    """Display module info and connected handlers."""
    console.print()
    console.print("[bold cyan]tests_lane Module[/bold cyan]")
    console.print("The retire lane and the test-template distribution — never a test's body")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/tests_lane/[/cyan]")
    console.print("    [dim]- retire_ops.py (retire_root, list_retired, restore)[/dim]")
    console.print("    [dim]- template_ops.py (gold_versions, receipt_status, bump)[/dim]")
    console.print()
    console.print("  [cyan]handlers/audit/[/cyan]")
    console.print("    [dim]- discovery.py (discover_branches — who gets a receipt)[/dim]")
    console.print()

    console.print("[yellow]External Dependencies:[/yellow]")
    console.print("  [dim]- aipass.prax (logger)[/dim]")
    console.print("  [dim]- aipass.cli (console, header)[/dim]")
    console.print("  [dim]- aipass.trigger (bump announcements, best effort)[/dim]")
    console.print()

    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @seedgo tests retired[/green]              [dim]# The retire lane[/dim]")
    console.print("  [green]drone @seedgo tests template-status[/green]      [dim]# Who is on which version[/dim]")
    console.print("  [green]drone @seedgo tests --help[/green]               [dim]# Full usage guide[/dim]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle 'tests' command.

    Args:
        command: Command name
        args: Additional arguments

    Returns:
        True if handled, False if not this module's command

    Raises:
        CommandRefused: An unknown subcommand, carrying exit code 7.
    """
    if command not in ("tests", "tests_lane"):
        return False

    if not args:
        print_introspection()
        return True

    # A help flag ANYWHERE wins — asking about a verb must never run it.
    if wants_help(None, args):
        print_help()
        return True

    subcommand = args[0]
    remaining = args[1:]

    if subcommand == "retired":
        _handle_retired()
    elif subcommand == "restore":
        _handle_restore(remaining)
    elif subcommand == "template-status":
        _handle_template_status()
    elif subcommand == "template":
        _handle_template(remaining)
    else:
        _refuse(subcommand)

    return True


def _refuse(subcommand: str) -> None:
    """Name the unknown subcommand back and exit non-zero (owner's 2026-09-07 ruling)."""
    console.print()
    display_error(f"Unknown subcommand: '{subcommand}'")
    console.print("[yellow]Valid subcommands:[/yellow] " + ", ".join(_SUBCOMMANDS))
    console.print()
    console.print(f"[dim]Module: {module_file(__file__)}[/dim]")
    console.print()
    raise CommandRefused(EXIT_UNKNOWN_ARGUMENT, subcommand)


# =============================================================================
# SUBCOMMAND ORCHESTRATION — RETIRE LANE
# =============================================================================


def _handle_retired() -> None:
    """List what the retire lane holds."""
    rows = retire_ops.list_retired(BRANCH)
    folder = retire_ops.retire_root(BRANCH)

    console.print()
    console.print(f"[bold cyan]Retired tests: {BRANCH}[/bold cyan]")
    console.print(f"[dim]{folder}[/dim]")
    console.print()

    if not rows:
        console.print("  [dim]nothing retired[/dim]")
        console.print()
        return

    for row in rows:
        mark = "[green]>[/green]" if row["present"] else "[yellow]![/yellow]"
        console.print(f"  {mark} {row['what']}")
        if row.get("why"):
            console.print(f"      [dim]{row['when']} by {row['by']} — {row['why']}[/dim]")
            console.print(f"      [dim]from {row['from']}[/dim]")
        else:
            console.print("      [dim]no log line — the file is here but nothing recorded it[/dim]")
        if not row["present"]:
            warning("the file is gone; this line cannot be restored")
    console.print()
    console.print(f"[dim]Restore one: drone @seedgo tests restore {rows[0]['what']}[/dim]")
    console.print()


def _handle_restore(args: List[str]) -> None:
    """Move one retired file back into tests/."""
    if not args:
        warning("Usage: drone @seedgo tests restore <name>")
        console.print("[dim]See what is there: drone @seedgo tests retired[/dim]")
        return

    landed, message = retire_ops.restore(args[0], BRANCH)
    if landed:
        console.print(f"  [green]Restored[/green] {message}")
    else:
        display_error(f"Cannot restore: {message}")


# =============================================================================
# SUBCOMMAND ORCHESTRATION — TEMPLATE LANE
# =============================================================================


def _handle_template_status() -> None:
    """Report who carries which template version."""
    console.print()
    console.print("[bold cyan]Test Template — Version Status[/bold cyan]")
    console.print()

    status = template_ops.receipt_status()
    gold = status["gold"]
    if not gold:
        display_error(f"No gold versions: {template_ops.manifest_path()} is missing or unreadable")
        return

    console.print("[bold]Gold source:[/bold] " + " · ".join(f"{k} {v}" for k, v in sorted(gold.items())))
    console.print(f"[dim]{template_ops.GOLD_DIR}[/dim]")
    console.print()

    stale = [row for row in status["branches"] if not row["current"]]
    current = len(status["branches"]) - len(stale)
    console.print(f"[bold]Branches:[/bold] {current}/{len(status['branches'])} carry the current version")
    console.print()
    for row in stale:
        carries = row["carries"]
        detail = "NO RECEIPT" if carries is None else ", ".join(f"{k} {v}" for k, v in sorted(carries.items()))
        console.print(f"  [yellow]![/yellow] {row['branch']}: {detail}")
    if not stale:
        console.print("  [green]>[/green] every branch is current")
    console.print()
    console.print("[dim]Stamp: drone @seedgo tests template bump (dry run; add --confirm to write)[/dim]")
    console.print()


def _handle_template(args: List[str]) -> None:
    """Route the template verbs that sit under 'template'."""
    if not args or args[0] != "bump":
        _refuse("template " + (args[0] if args else ""))
        return

    rest = args[1:]
    confirm = "--confirm" in rest
    targets = [a for a in rest if not a.startswith("--")]
    if len(targets) > 1:
        _refuse(" ".join(targets))
        return
    _run_bump(confirm, targets[0] if targets else None)


def _run_bump(confirm: bool, only: str | None) -> None:
    """The bump site: report what would change, or write it and announce."""
    console.print()
    mode = "EXECUTE" if confirm else "DRY RUN"
    scope = only if only else "fleet"
    console.print(f"[bold cyan]Test Template Bump · {mode} · {scope}[/bold cyan]")
    console.print()

    outcome = template_ops.bump(confirm=confirm, only=only)
    if outcome.get("error"):
        display_error(outcome["error"])
        return

    console.print("[bold]Gold:[/bold] " + " · ".join(f"{k} {v}" for k, v in sorted(outcome["gold"].items())))
    console.print()

    styles = {
        "stamped": "green",
        "would-stamp": "yellow",
        "current": "dim",
        "no-tests-dir": "dim",
        "skipped": "dim",
    }
    for row in outcome["branches"]:
        style = styles.get(row["action"], "red")
        console.print(f"  [{style}]{row['action']:<13}[/{style}] {row['branch']}")
    console.print()

    if not confirm:
        console.print("[dim]Nothing was written. Add --confirm to stamp.[/dim]")
        console.print()

    _announce_bump(outcome)


def _announce_bump(outcome: dict) -> None:
    """Announce a bump on @trigger's bus. Best effort — the bus never gates a stamp.

    Lives in the module layer, not beside the domain logic: reaching the bus
    means importing @trigger's module layer, and a handler doing that is
    orchestration in a handler's clothing. The handler owns the event's NAME
    (``template_ops.BUMP_EVENT``); this owns the sending.

    The two failures are logged differently on purpose. An ImportError means
    @trigger is not installed here — an environment fact, nothing to repair.
    Anything else raised on this path is OUR bug, and a broad "bus unavailable"
    line would make it read as a missing dependency.
    """
    try:
        from aipass.trigger.apps.modules.core import trigger
    except ImportError as exc:
        logger.info("Event bus unavailable, template bump not announced: %s", exc)
        return

    stamped = [row["branch"] for row in outcome["branches"] if row["action"] == "stamped"]
    try:
        trigger.fire(
            template_ops.BUMP_EVENT,
            dry_run=outcome.get("dry_run", True),
            stamped=len(stamped),
            branches=",".join(stamped),
            versions=json.dumps(outcome.get("gold") or {}, sort_keys=True),
        )
    except Exception as exc:
        logger.error(f"Template bump announcement FAILED ({type(exc).__name__}): {exc}", exc_info=True)


# =============================================================================
# HELP
# =============================================================================


def print_help() -> None:
    """Print help information"""
    console.print()
    header("Tests Lane")
    console.print()
    console.print("[yellow]COMMANDS:[/yellow]")
    console.print("  [green]drone @seedgo tests retired[/green]                     [dim]The retire lane[/dim]")
    console.print("  [green]drone @seedgo tests restore <name>[/green]              [dim]Bring one back[/dim]")
    console.print("  [green]drone @seedgo tests template-status[/green]             [dim]Receipts vs gold[/dim]")
    console.print("  [green]drone @seedgo tests template bump[/green]               [dim]Dry run[/dim]")
    console.print("  [green]drone @seedgo tests template bump --confirm[/green]     [dim]Write the receipts[/dim]")
    console.print("  [green]drone @seedgo tests template bump @flow --confirm[/green] [dim]One branch[/dim]")
    console.print()
    console.print("[yellow]THE RETIRE LANE:[/yellow]")
    console.print("  A retired test is MOVED to .backup/tests/<branch>/, never deleted,")
    console.print("  and retired.json beside it records what, when, why, from and by.")
    console.print()
    console.print("[yellow]THE TEMPLATE LANE:[/yellow]")
    console.print("  Gold is seedgo/templates/. Each branch holds tests/.template_version.json.")
    console.print("  A bump writes that receipt and the page; a test's BODY is never distributed.")
    console.print("  A bump announces test_template_bumped on @trigger's bus — never polled.")
    console.print()
    console.print("[dim]Commands: tests, tests_lane, --help[/dim]")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    if len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    logger.info("Prax logger connected to tests_lane")
    json_handler.log_operation("tests_lane_run", {"command": "standalone", "args": sys.argv[1:]})

    handle_command("tests", sys.argv[1:])
