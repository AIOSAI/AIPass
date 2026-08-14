# =================== AIPass ====================
# Name: handoff.py
# Description: CLI handoff orchestration — aipass handoff command
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-20
# =============================================

"""
aipass handoff — pass the user to their chosen CLI in a new session

Thin coordinator. Delegates platform dispatch to handlers/handoff_platform/
which handles tmux (Linux/Mac), wt.exe (Windows), or prints fallback command.

Usage:
    aipass handoff                    # show status / introspection
    aipass handoff launch             # launch with stored profile settings
    aipass handoff launch --cli claude --cwd src/my-agent
    aipass handoff --help
"""

from __future__ import annotations

from aipass.cli.apps.modules import console, success, warning
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler

COMMAND = "handoff"

INIT_PROMPT = "I just completed aipass init and am ready to start. What should I do first?"

CLI_CHOICES = ["claude", "codex"]
FLAG_CHOICES = ["default", "skip-permissions"]


def _get_stored_profile() -> dict:
    """Read cli and agent_path from profile/progress if available."""
    try:
        from aipass.aipass.apps.modules import profile as profile_mod

        p = profile_mod.get_user_profile()
        return {"cli": p.get("preferred_cli") or "claude"}
    except Exception as exc:
        logger.warning("[handoff] could not read profile: %s", exc)
        return {"cli": "claude"}


def do_handoff(
    cli: str = "claude",
    prompt: str = INIT_PROMPT,
    cwd: str = ".",
    flag_variant: str = "default",
) -> bool:
    """
    Perform the platform-dispatched handoff.

    Returns True when a new session was started, False when fallback was used.
    In either case the user sees what to do next.
    """
    from aipass.aipass.apps.handlers.handoff_platform import launch_handoff

    launched, manual_cmd = launch_handoff(cli, prompt, cwd, flag_variant)

    if launched:
        console.print()
        success(f"Session started via tmux/wt — CLI: {cli}")
        console.print(f"[dim]Session name: aipass-handoff | cwd: {cwd}[/dim]")
        console.print()
    else:
        console.print()
        warning("Auto-launch unavailable. Run this command manually:")
        console.print(f"  [cyan]{manual_cmd}[/cyan]")
        console.print()

    json_handler.log_operation("handoff", {"cli": cli, "cwd": cwd, "launched": launched})
    return launched


def print_introspection() -> None:
    """Show handoff module status and stored settings."""
    profile = _get_stored_profile()
    console.print()
    console.print("[bold cyan]handoff Module[/bold cyan]")
    console.print("Platform-dispatched CLI session launch")
    console.print()
    console.print(f"  stored CLI:    [cyan]{profile.get('cli', 'claude')}[/cyan]")
    console.print("  platforms:     tmux (Linux/Mac), wt.exe (Windows), fallback")
    console.print()
    console.print("[dim]Use 'aipass handoff launch' to start a session.[/dim]")
    console.print()


def print_help() -> None:
    """Print usage help for the handoff command."""
    console.print()
    console.print("[bold cyan]aipass handoff[/bold cyan] — launch CLI in a new session")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass handoff[/green]                      [dim]# Show status[/dim]")
    console.print("  [green]aipass handoff launch[/green]               [dim]# Launch with profile defaults[/dim]")
    console.print("  [green]aipass handoff launch --cli claude[/green]  [dim]# Specify CLI[/dim]")
    console.print()
    console.print("[yellow]CLI OPTIONS:[/yellow] " + ", ".join(CLI_CHOICES))
    console.print("[yellow]FLAG OPTIONS:[/yellow] " + ", ".join(FLAG_CHOICES))
    console.print()


def _parse_launch_args(args: list[str]) -> tuple[str, str, str]:
    """Parse --cli, --cwd, --flag from launch subcommand args."""
    cli, cwd, flag_variant = "claude", ".", "default"
    i = 0
    while i < len(args):
        if args[i] == "--cli" and i + 1 < len(args):
            cli = args[i + 1]
            i += 2
        elif args[i] == "--cwd" and i + 1 < len(args):
            cwd = args[i + 1]
            i += 2
        elif args[i] == "--flag" and i + 1 < len(args):
            flag_variant = args[i + 1]
            i += 2
        else:
            i += 1
    return cli, cwd, flag_variant


def handle_command(command: str, args: list[str]) -> bool:
    """Route handoff subcommands: show, launch, help.

    Returns True if handled, False if command does not match.
    """
    if command != COMMAND:
        return False

    if not args:
        print_help()
        return True

    if wants_help(args):
        print_help()
        return True

    if args[0] == "--info":
        print_introspection()
        return True

    if args[0] == "launch":
        cli, cwd, flag_variant = _parse_launch_args(args[1:])
        if cli not in CLI_CHOICES:
            warning(f"Unknown CLI '{cli}'. Valid options: {', '.join(CLI_CHOICES)}")
            return True
        do_handoff(cli=cli, cwd=cwd, flag_variant=flag_variant)
        return True

    print_help()
    return True
