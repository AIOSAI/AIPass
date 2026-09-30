# =================== AIPass ====================
# Name: bypass.py
# Description: Bypass Module — prune the bypass rules that can never match
# Version: 1.1.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""Bypass Module

``bypass prune @branch`` removes the rules in a branch's ``.seedgo/bypass.json``
that the audit convicts as dead: the file matches nothing on disk, the standard
is not a checker, or every named line lies past the end of the file. A dead rule
matches nothing, so removing it moves no score. It is debris that reads as a live
exception to anyone who opens the file.

Only convicted rules are removed, and a live rule is never touched. A rule with
a blank ``file`` or ``standard`` is dead as well (a rule needs both to be active,
owner 2026-09-25 18:55) but is left and named: its reason is the owner's intent,
and only the owner can rewrite it as named rules. ``--dry-run`` writes nothing.

Run: seedgo bypass prune @flow --dry-run
"""

import json
import sys
from pathlib import Path
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
from aipass.cli.apps.modules import error as display_error, success, warning

# Handlers (implementation)
from aipass.seedgo.apps.handlers.audit.branch_audit import discover_checkers
from aipass.seedgo.apps.handlers.audit.discovery import discover_branches
from aipass.seedgo.apps.handlers.bypass import dead_rules
from aipass.seedgo.apps.handlers.cli.help_flags import wants_help
from aipass.seedgo.apps.handlers.module_root import module_file
from aipass.seedgo.apps.modules import CommandRefused

#: An argument nobody recognised (handlers/audit_tests/refusal.py's vocabulary).
EXIT_UNKNOWN_ARGUMENT = 7
#: A target with nothing to act on: no such branch.
EXIT_NO_TARGET = 3
#: The lane could not run: the bypass.json is unreadable or is not JSON.
EXIT_LANE_FAILED = 2

_SUBCOMMANDS = {
    "prune": "prune @branch [--dry-run] — remove the rules the audit convicts as dead",
}
_FLAGS = ("--dry-run",)


# =============================================================================
# COMMAND HANDLER
# =============================================================================


def print_introspection() -> None:
    """Display module info and connected handlers."""
    console.print()
    console.print("[bold cyan]bypass Module[/bold cyan]")
    console.print("Prune the bypass rules that can never match — never a live or blank-field rule")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/bypass/[/cyan]")
    console.print("    [dim]- dead_rules.py (dead_rules, bypass_markers, prune)[/dim]")
    console.print("  [cyan]handlers/audit/[/cyan]")
    console.print("    [dim]- discovery.py (discover_branches), branch_audit.py (discover_checkers)[/dim]")
    console.print()
    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @seedgo bypass prune @flow --dry-run[/green]   [dim]# What would go[/dim]")
    console.print("  [green]drone @seedgo bypass --help[/green]                  [dim]# Full usage guide[/dim]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle 'bypass' command.

    Args:
        command: Command name
        args: Additional arguments

    Returns:
        True if handled, False if not this module's command

    Raises:
        CommandRefused: exit 7 for an unknown subcommand or flag, 3 for an unknown
            branch, 2 when the branch's bypass.json cannot be read or written.
    """
    if command != "bypass":
        return False

    if not args:
        print_introspection()
        return True

    # A help flag ANYWHERE wins — asking about a verb must never run it.
    if wants_help(None, args):
        print_help()
        return True

    if args[0] != "prune":
        _refuse(args[0], EXIT_UNKNOWN_ARGUMENT)
    _handle_prune(args[1:])
    return True


def _refuse(token: str, code: int) -> None:
    """Name the refused token back and exit non-zero (owner's 2026-09-07 ruling)."""
    console.print()
    display_error(f"Refused: '{token}'")
    console.print("[yellow]Usage:[/yellow] " + "; ".join(_SUBCOMMANDS.values()))
    console.print(f"[dim]Module: {module_file(__file__)}[/dim]")
    console.print()
    raise CommandRefused(code, token)


# =============================================================================
# SUBCOMMAND ORCHESTRATION
# =============================================================================


def _handle_prune(args: List[str]) -> None:
    """Resolve the one branch named, prune its dead rules, and print each one with its reason."""
    unknown = [a for a in args if a.startswith("-") and a not in _FLAGS]
    targets = [a for a in args if not a.startswith("-")]
    if unknown:
        _refuse(unknown[0], EXIT_UNKNOWN_ARGUMENT)
    if len(targets) != 1:
        _refuse(" ".join(targets) or "prune (no branch)", EXIT_UNKNOWN_ARGUMENT)
    dry_run = "--dry-run" in args
    wanted = targets[0].lstrip("@").lower()
    branch = next((b for b in discover_branches(include_private=True) if b["name"].lower() == wanted), None)
    if branch is None:
        _refuse(targets[0], EXIT_NO_TARGET)
        return

    known = set(discover_checkers()) | {"diagnostics"}
    try:
        outcome = dead_rules.prune(Path(branch["path"]), known, dry_run=dry_run)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("[bypass] prune @%s could not run: %s", wanted, exc)
        _refuse(f"@{wanted}: {exc}", EXIT_LANE_FAILED)
        return

    json_handler.log_operation(
        "bypass_prune",
        {"branch": wanted, "dry_run": dry_run, "dead": len(outcome["dead"]), "written": outcome["written"]},
    )
    _print_outcome(wanted, dry_run, outcome)


def _print_outcome(branch: str, dry_run: bool, outcome: dict) -> None:
    """Every dead rule with why it is dead and the reason its author gave, then the verdict."""
    console.print()
    console.print(f"[bold cyan]Bypass prune · {'DRY RUN' if dry_run else 'EXECUTE'} · @{branch}[/bold cyan]")
    console.print(f"[dim]{outcome['file']}[/dim]")
    console.print()
    verb = "would remove" if dry_run or not outcome["written"] else "removed"
    for dead in outcome["dead"]:
        console.print(f"  {verb} [{dead['index']}] {dead['file']} / {dead['standard']}: {dead['why']}")
        console.print(f"      [dim]reason: {dead['reason'] or '(none given)'}[/dim]")
    for left in outcome["left"]:
        console.print(f"  left for the owner [{left['index']}] {left['file']} / {left['standard']}: {left['why']}")
        console.print(f"      [dim]reason: {left['reason'] or '(none given)'} — rewrite it as named rules[/dim]")
    console.print()
    console.print(f"  {len(outcome['dead'])} dead, {outcome['kept']} kept ({len(outcome['left'])} blank-field, left)")
    if outcome["refused"]:
        warning(f"Nothing written: {outcome['refused']}")
    elif outcome["written"]:
        success(f"Removed {len(outcome['dead'])} dead rules from @{branch}")
    elif dry_run and outcome["dead"]:
        console.print("  [dim]Nothing was written. Run without --dry-run to remove them.[/dim]")
    console.print()


# =============================================================================
# HELP
# =============================================================================


def print_help() -> None:
    """Print help information"""
    console.print()
    header("Bypass")
    console.print()
    console.print("[yellow]COMMANDS:[/yellow]")
    console.print(
        "  [green]drone @seedgo bypass prune @flow --dry-run[/green]   [dim]What would go, nothing written[/dim]"
    )
    console.print("  [green]drone @seedgo bypass prune @flow[/green]             [dim]Remove the dead rules[/dim]")
    console.print()
    console.print("[yellow]A DEAD RULE:[/yellow]")
    console.print("  its file is a substring of no file on disk (the matcher's own semantics),")
    console.print("  its standard is not a checker, or every line it names is past the file's end.")
    console.print("  It matches nothing, so pruning it moves no score. The audit names each one.")
    console.print()
    console.print("[yellow]NEVER REMOVED:[/yellow]")
    console.print("  a live rule. A rule with a blank file or standard is dead too (a rule needs")
    console.print("  both to be active, owner 2026-09-25) but is LEFT, named, for its owner to rewrite.")
    console.print()
    console.print("[dim]Commands: bypass, --help[/dim]")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    if len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    logger.info("Prax logger connected to bypass")
    json_handler.log_operation("bypass_run", {"command": "standalone", "args": sys.argv[1:]})

    handle_command("bypass", sys.argv[1:])
