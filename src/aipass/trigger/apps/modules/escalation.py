# =================== AIPass ====================
# Name: escalation.py
# Description: Escalation digest CLI — inspect repeat warning/error signatures
# Version: 1.0.0
# Created: 2026-08-08
# Modified: 2026-08-08
# =============================================

"""
Escalation Digest Module — inspect the repeat-signature lane

Medic dispatches an error's owner once and then goes quiet. This lane counts
what keeps happening anyway — repeat WARNING and ERROR signatures — and emails
the operator when a signature crosses its threshold inside the window.

Commands: status, list, config

Architecture: module renders, handlers/escalation.py owns counting and sending
"""

import os
import sys

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.trigger.apps.handlers import escalation
from aipass.trigger.apps.handlers.json import json_handler

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

_SUBCOMMANDS = ["status", "list", "config"]


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        logger.info("CLI console not available, using rich fallback")
        from rich.console import Console

        console = Console()

    console.print()
    console.print("[bold cyan]escalation Module[/bold cyan]")
    console.print("[dim]Repeat warning/error signatures — digest email to the operator[/dim]")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print("    [cyan]•[/cyan] escalation.py [dim](get_stats — lane settings and tracked totals)[/dim]")
    console.print("    [cyan]•[/cyan] escalation.py [dim](get_signatures — tracked repeat signatures)[/dim]")
    console.print("    [cyan]•[/cyan] escalation.py [dim](record_warning / record_error — counting)[/dim]")
    console.print("  [cyan]handlers/json/[/cyan]")
    console.print("    [cyan]•[/cyan] config_loader.py [dim](section — operator thresholds and window)[/dim]")
    console.print()


def print_help() -> None:
    """Display escalation command help."""
    from aipass.cli.apps.modules import console

    console.print()
    console.print("[bold cyan]drone @trigger escalation[/bold cyan] — repeat-signature digest lane")
    console.print()
    console.print("[yellow]Commands:[/yellow]")
    console.print("  [cyan]status[/cyan]            Lane settings, tracked signatures, digests sent")
    # \[level] is escaped: rich reads a bare [level] as a markup tag and eats it.
    console.print("  [cyan]list \\[level][/cyan]      Tracked signatures (level: warning | error)")
    console.print("  [cyan]config[/cyan]            Show the operator config file path and values")
    console.print()
    console.print("[yellow]What it does:[/yellow]")
    console.print("  Counts repeat WARNING and ERROR signatures. When one crosses its")
    console.print("  threshold inside the window, ONE digest email goes to the operator —")
    console.print("  email, never a dispatch. Per-signature cooldown stops mailbox spam.")
    console.print()
    console.print("  [dim]A mute stops medic re-dispatching. It never stops the counting here.[/dim]")
    console.print("  [dim]A suppressed fingerprint stays silent (compass #219) unless[/dim]")
    console.print("  [dim]escalate_suppressed is turned on.[/dim]")
    console.print()
    console.print("[yellow]Settings[/yellow] [dim](edit the JSON, not the code):[/dim]")
    console.print(f"  [dim]{escalation.config_loader.CONFIG_PATH}[/dim]")
    console.print()


def _handle_status(console) -> None:
    """Render lane status."""
    stats = escalation.get_stats()
    state = "[green]ENABLED[/green]" if stats["enabled"] else "[red]DISABLED[/red]"

    console.print()
    console.print(f"[bold cyan]Escalation Digest[/bold cyan] — {state}")
    console.print()
    console.print(f"  Recipient        : [cyan]{stats['digest_recipient']}[/cyan] [dim](email, never a wake)[/dim]")
    console.print(
        f"  Thresholds       : {stats['warning_threshold']} warning / "
        f"{stats['error_threshold']} error in {stats['window_minutes']} min"
    )
    console.print(f"  Cooldown         : {stats['cooldown_minutes']} min per signature")
    console.print(f"  Branch warnings  : {'watched' if stats['watch_branch_log_warnings'] else 'not watched'}")
    console.print(f"  Suppressed errors: {'escalated' if stats['escalate_suppressed'] else 'stay silent'}")
    if stats["ignore_branches"]:
        console.print(f"  Ignored branches : {', '.join(stats['ignore_branches'])}")
    console.print()
    console.print(
        f"  Tracked          : {stats['tracked_signatures']} signatures "
        f"[dim]({stats['tracked_warnings']} warning / {stats['tracked_errors']} error)[/dim]"
    )
    console.print(f"  Digests sent     : {stats['digests_sent']} [dim]across {stats['signatures_digested']}[/dim]")
    if not stats["email_wired"]:
        console.print("  [dim]Email callback not wired in this process (wired when events fire).[/dim]")
    console.print()
    console.print(f"  [dim]state : {stats['state_file']}[/dim]")
    console.print(f"  [dim]config: {stats['config_file']}[/dim]")
    console.print()


def _handle_list(console, args: list) -> None:
    """Render tracked signatures."""
    level = None
    if args and args[0].lower() in ("warning", "warn", "error"):
        level = "WARNING" if args[0].lower().startswith("warn") else "ERROR"

    rows = escalation.get_signatures(level=level)
    console.print()
    label = f"{level.title()} signatures" if level else "Tracked signatures"
    console.print(f"[bold cyan]{label}[/bold cyan] [dim](most recent first)[/dim]")
    console.print()

    if not rows:
        console.print("  [dim]No signatures tracked yet.[/dim]")
        console.print()
        return

    for row in rows:
        colour = "yellow" if row.get("level") == "WARNING" else "red"
        digests = row.get("digests_sent", 0)
        sent = f" [green]{digests} digest(s)[/green]" if digests else ""
        console.print(
            f"  [{colour}]{row.get('level', '?'):<8}[/{colour}] [dim]{row['signature']}[/dim] "
            f"@{row.get('branch', '?').lower()}/{row.get('module', '?')}"
        )
        console.print(
            f"    window {row.get('window_count', 0)} · lifetime {row.get('total_count', 0)}{sent} "
            f"[dim]· last {row.get('last_seen', '?')}[/dim]"
        )
        console.print(f"    [dim]{row.get('message', '')[:100]}[/dim]")
    console.print()


def _handle_config(console) -> None:
    """Render the operator config file and its effective values."""
    cfg = escalation.get_config()
    path = escalation.config_loader.CONFIG_PATH

    console.print()
    console.print("[bold cyan]Escalation config[/bold cyan]")
    console.print(f"  [dim]{path}[/dim]")
    console.print(f"  [dim]{'file present' if path.exists() else 'file missing — regenerates on next load'}[/dim]")
    console.print()
    for key in sorted(cfg):
        console.print(f"  [cyan]{key}[/cyan] = {cfg[key]}")
    console.print()
    console.print("  [dim]Edit the file, not the code. Code defaults are the regeneration seed.[/dim]")
    console.print()


def _run_subcommand(subcommand: str, args: list) -> bool:
    """Run an escalation subcommand.

    Args:
        subcommand: status, list or config
        args: Remaining arguments

    Returns:
        True if the subcommand ran
    """
    from aipass.cli.apps.modules import console

    if subcommand in ["--help", "-h", "help"] or subcommand not in _SUBCOMMANDS:
        print_help()
        return True

    if args and args[0] in ["--help", "-h", "help"]:
        print_help()
        return True

    if subcommand == "status":
        _handle_status(console)
    elif subcommand == "list":
        _handle_list(console, args)
    elif subcommand == "config":
        _handle_config(console)

    json_handler.log_operation("escalation_command", {"command": subcommand})
    return True


def handle_command(command: str, args: list) -> bool:
    """
    Handle escalation commands.

    Claims the module name ONLY. Bare 'status', 'list' and 'config' belong to
    core.py — the router hands a command to whichever module claims it first
    and glob discovery order is not stable, so claiming them here would
    randomly hijack `drone @trigger status`.

    Args:
        command: Command name — handled only when it is 'escalation'
        args: Additional arguments (first is the subcommand)

    Returns:
        True if command was handled, False otherwise
    """
    if command != "escalation":
        return False

    if not args:
        print_introspection()
        return True

    # Intercept help at the entry point, before any subcommand dispatch.
    if args[0] in ["--help", "-h", "help"]:
        print_help()
        return True

    return _run_subcommand(args[0], args[1:])


if __name__ == "__main__":
    if len(sys.argv) == 1 or sys.argv[1] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    handle_command("escalation", sys.argv[1:])
