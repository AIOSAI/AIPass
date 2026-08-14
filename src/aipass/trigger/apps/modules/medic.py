# =================== AIPass ====================
# Name: medic.py
# Description: Medic toggle module for auto-healing error dispatch control
# Version: 1.4.0
# Created: 2026-02-12
# Modified: 2026-03-01
# =============================================

"""
Medic Toggle Module - Control auto-healing error dispatch

Provides on/off/status/mute/unmute commands for the Medic system
(error detection + auto-dispatch chain). When Medic is off, errors
are still detected and logged but NOT dispatched to branches.
Per-branch muting suppresses dispatch for specific branches only.

Two mute classes, deliberately independent:
    mute / unmute                CONTENT — gates error_detected dispatch
    volume-mute / volume-unmute  VOLUME  — gates runaway_log_detected alerts

Commands: on, off, status, mute, unmute, volume-mute, volume-unmute
Architecture: Module orchestrates, medic_state handler manages persistence
"""

import os
import subprocess
import sys
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.trigger.apps.handlers.cli.help_flags import wants_help
from aipass.trigger.apps.handlers.json import json_handler

from aipass.trigger.apps.handlers.medic_state import (
    is_enabled,
    set_enabled,
    get_muted_branches_detail,
    get_volume_muted_branches_detail,
    get_disabled_until,
    mute_branch,
    unmute_branch,
    mute_branch_volume,
    unmute_branch_volume,
    get_suppression_stats,
    get_rate_limit_stats,
    parse_duration,
    DEFAULT_MUTE_SECONDS,
    DEFAULT_OFF_SECONDS,
)

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

SERVICE_NAME = "trigger-log-watcher.service"
_SERVICE_UNIT_PATH = Path.home() / ".config" / "systemd" / "user" / SERVICE_NAME
_TEMPLATE_PATH = Path(__file__).resolve().parent.parent.parent / "templates" / f"{SERVICE_NAME}.template"


def _get_aipass_home() -> Path:
    """Resolve AIPASS_HOME from env var or git repo root."""
    import os

    env = os.environ.get("AIPASS_HOME")
    if env:
        return Path(env)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception as exc:
        logger.warning("[MEDIC] git repo root detection failed: %s", exc)
    return Path(__file__).resolve().parent.parent.parent.parent.parent


def _ensure_service_installed() -> bool:
    """Install systemd unit from template if missing. Returns True if ready."""
    if _SERVICE_UNIT_PATH.exists():
        return True

    if not _TEMPLATE_PATH.exists():
        logger.warning("[MEDIC] Service template not found: %s", _TEMPLATE_PATH)
        return False

    aipass_home = _get_aipass_home()
    from aipass.trigger.apps.config import read_text_file, write_text_file

    template = read_text_file(_TEMPLATE_PATH)
    rendered = template.replace("{{AIPASS_HOME}}", str(aipass_home))

    write_text_file(_SERVICE_UNIT_PATH, rendered)
    logger.info("[MEDIC] Installed systemd unit to %s", _SERVICE_UNIT_PATH)

    _systemctl("daemon-reload")
    subprocess.run(
        ["systemctl", "--user", "enable", SERVICE_NAME],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return True


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        logger.info("CLI console not available, using rich fallback")
        from rich.console import Console

        console = Console()

    console.print()
    console.print("[bold cyan]medic Module[/bold cyan]")
    console.print("[dim]Medic toggle — control auto-healing error dispatch on/off/mute/unmute[/dim]")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print("    [cyan]•[/cyan] medic_state.py [dim](is_enabled — check if medic is enabled)[/dim]")
    console.print("    [cyan]•[/cyan] medic_state.py [dim](set_enabled — toggle medic on/off)[/dim]")
    console.print("    [cyan]•[/cyan] medic_state.py [dim](get_muted_branches — list muted branches)[/dim]")
    console.print("    [cyan]•[/cyan] medic_state.py [dim](mute_branch — suppress dispatch for a branch)[/dim]")
    console.print("    [cyan]•[/cyan] medic_state.py [dim](unmute_branch — resume dispatch for a branch)[/dim]")
    console.print("    [cyan]•[/cyan] medic_state.py [dim](mute_branch_volume — suppress runaway alerts)[/dim]")
    console.print("    [cyan]•[/cyan] medic_state.py [dim](unmute_branch_volume — resume runaway alerts)[/dim]")
    console.print("    [cyan]•[/cyan] medic_state.py [dim](get_suppression_stats — suppression statistics)[/dim]")
    console.print("    [cyan]•[/cyan] medic_state.py [dim](get_rate_limit_stats — rate limit statistics)[/dim]")
    console.print()


def _systemctl(action: str) -> bool:
    """Run systemctl --user action on the log watcher service.

    Args:
        action: systemctl action (start, stop, restart, is-active)

    Returns:
        True if command succeeded (exit code 0)
    """
    try:
        result = subprocess.run(
            ["systemctl", "--user", action, SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception as exc:
        logger.warning(f"[MEDIC] systemctl {action} failed: {exc}")
        return False


def _is_service_active() -> bool:
    """Check if the log watcher systemd service is running."""
    return _systemctl("is-active")


def _extract_branch_name(raw: str) -> str:
    """
    Extract branch name from raw argument.

    Handles both direct names (@speakeasy, speakeasy) and
    drone-resolved paths (e.g., src/aipass/speakeasy).

    Args:
        raw: Raw argument from command line

    Returns:
        Lowercase branch name (e.g., 'speakeasy')
    """
    cleaned = raw.lstrip("@")
    # If it looks like a path, take the last directory component
    if "/" in cleaned:
        cleaned = Path(cleaned).name
    return cleaned.lower()


def print_help() -> None:
    """Print module help."""
    from aipass.cli.apps.modules import console
    from rich.panel import Panel

    console.print(Panel("Medic - Auto-Healing Error Dispatch", style="bold"))
    console.print()
    console.print("Auto-healing error dispatch system. Watches branch logs for errors")
    console.print("and dispatches fix-it emails to affected branches automatically.")
    console.print()
    console.rule("USAGE")
    console.print()
    console.print("  drone @trigger medic <command>")
    console.print()
    console.rule("COMMANDS")
    console.print()
    console.print("  [bold]on[/bold]                 Enable error dispatch (starts log watcher if needed)")
    console.print("  [bold]off[/bold]                Disable dispatch for 24h (detection continues)")
    console.print("  [bold]off --forever[/bold]      Disable dispatch permanently (stops log watcher)")
    console.print("  [bold]status[/bold]             Show current state, muted branches, and statistics")
    console.print("  [bold]mute[/bold] @branch       Suppress dispatch for 24h (default)")
    console.print("  [bold]mute[/bold] @branch --for 48h  Custom TTL (e.g. 48h, 7d)")
    console.print("  [bold]mute[/bold] @branch --forever  Permanent mute")
    console.print("  [bold]unmute[/bold] @branch     Resume dispatch for a muted branch")
    console.print("  [bold]volume-mute[/bold] @branch    Suppress runaway alerts for 24h (same flags)")
    console.print("  [bold]volume-unmute[/bold] @branch  Resume runaway alerts for a branch")
    console.print("  [bold]help[/bold]               Show this help")
    console.print()
    console.rule("OFF vs MUTE")
    console.print()
    console.print("  [yellow]off[/yellow]       24h dispatch suppression (detection continues).")
    console.print("            Auto-resumes after 24 hours. Use --forever for")
    console.print("            permanent disable (stops log watcher too).")
    console.print()
    console.print("  [yellow]mute[/yellow]      Per-branch suppress for 24h (default).")
    console.print("            --for 48h or --for 7d for custom duration.")
    console.print("            --forever for permanent. Auto-expires — no need to unmute.")
    console.print()
    console.rule("CONTENT MUTE vs VOLUME MUTE")
    console.print()
    console.print("  [yellow]mute[/yellow]          CONTENT — gates error_detected. The 'expect error")
    console.print("                lines from me while I build' switch. Never gates runaways.")
    console.print("  [yellow]volume-mute[/yellow]   VOLUME — gates runaway_log_detected for a branch")
    console.print("                knowingly logging heavy. CRITICAL bypasses it.")
    console.print()
    console.print("  [dim]Separate on purpose: a content mute says nothing about log volume,[/dim]")
    console.print("  [dim]and build windows are exactly when floods happen.[/dim]")
    console.print()
    console.rule("EXAMPLES")
    console.print()
    console.print("  [dim]# Enable Medic (starts watching logs for errors)[/dim]")
    console.print("  drone @trigger medic on")
    console.print()
    console.print("  [dim]# Disable all error dispatch globally[/dim]")
    console.print("  drone @trigger medic off")
    console.print()
    console.print("  [dim]# Mute a noisy branch while debugging[/dim]")
    console.print("  drone @trigger medic mute @speakeasy")
    console.print()
    console.print("  [dim]# Resume dispatch for that branch[/dim]")
    console.print("  drone @trigger medic unmute @speakeasy")
    console.print()
    console.print("  [dim]# Check what's happening[/dim]")
    console.print("  drone @trigger medic status")
    console.print()
    console.rule("HOW IT WORKS")
    console.print()
    console.print("  Trigger watches branch logs  ->  fires error_detected event")
    console.print("  ->  handler checks medic_enabled  ->  checks branch mute list")
    console.print("  ->  dispatches fix-it email to affected branch (or suppresses)")
    console.print()
    console.print("  Prax rate tracker  ->  fires runaway_log_detected event")
    console.print("  ->  handler checks per-file cooldown  ->  checks VOLUME mute list")
    console.print("  ->  dispatches runaway alert (CRITICAL bypasses the mute)")
    console.print()
    console.print("  Suppressed errors:   trigger/logs/medic_suppressed.jsonl")
    console.print("  Runaway decisions:   trigger/logs/runaway_suppressed.jsonl")
    console.print()


def _parse_duration_args(args: list) -> tuple:
    """Extract --for <dur> and --forever from args.

    Returns:
        (duration_seconds_or_None, is_forever, remaining_args)
        Default (no flags): duration=DEFAULT_MUTE_SECONDS, is_forever=False
    """
    remaining = []
    duration = None
    is_forever = False
    i = 0
    while i < len(args):
        if args[i] == "--forever":
            is_forever = True
            i += 1
        elif args[i] == "--for" and i + 1 < len(args):
            parsed = parse_duration(args[i + 1])
            if parsed is not None:
                duration = parsed
            i += 2
        else:
            remaining.append(args[i])
            i += 1
    if is_forever:
        return None, True, remaining
    if duration is not None:
        return duration, False, remaining
    return float(DEFAULT_MUTE_SECONDS), False, remaining


def _fmt_remaining(iso_expiry: str) -> str:
    """Format time remaining from an ISO expiry timestamp."""
    from datetime import datetime

    try:
        expires = datetime.fromisoformat(iso_expiry)
        remaining = expires - datetime.now()
        total_secs = max(0, int(remaining.total_seconds()))
        if total_secs <= 0:
            return "expired"
        hours, rem = divmod(total_secs, 3600)
        minutes = rem // 60
        if hours >= 24:
            days = hours // 24
            hours = hours % 24
            return f"{days}d {hours}h"
        return f"{hours}h {minutes}m"
    except Exception as exc:
        logger.warning("[MEDIC] _fmt_remaining parse failed: %s", exc)
        return "unknown"


def _handle_mute(console, args: list) -> None:
    """Handle 'medic mute @branch [--for <dur>] [--forever]'."""
    from aipass.cli.apps.modules import error

    duration_secs, is_forever, rest = _parse_duration_args(args)

    if not rest:
        error("Missing branch name", suggestion="Usage: medic mute @branch [--for 48h] [--forever]")
        return
    branch_name = _extract_branch_name(rest[0])
    if not branch_name:
        error("Missing branch name", suggestion="Usage: medic mute @branch [--for 48h] [--forever]")
        return
    if mute_branch(branch_name, duration_seconds=duration_secs):
        logger.info(f"[MEDIC] Muted branch: {branch_name}")
        if is_forever or duration_secs is None:
            console.print(f"  [yellow]Muted[/yellow] @{branch_name} — permanent (use unmute to restore)")
        else:
            hours = int(duration_secs) // 3600
            console.print(f"  [yellow]Muted[/yellow] @{branch_name} — auto-expires in {hours}h")
    else:
        error(f"Failed to mute @{branch_name}", suggestion="Check medic_state.json")


def _handle_unmute(console, args: list) -> None:
    """Handle 'medic unmute @branch'."""
    from aipass.cli.apps.modules import error

    if not args:
        error("Missing branch name", suggestion="Usage: medic unmute @branch")
        return
    branch_name = _extract_branch_name(args[0])
    if not branch_name:
        error("Missing branch name", suggestion="Usage: medic unmute @branch")
        return
    if unmute_branch(branch_name):
        logger.info(f"[MEDIC] Unmuted branch: {branch_name}")
        console.print(f"  [green]Unmuted[/green] @{branch_name} — dispatch resumed")
    else:
        error(f"Failed to unmute @{branch_name}", suggestion="Check medic_state.json")


def _handle_volume_mute(console, args: list) -> None:
    """Handle 'medic volume-mute @branch [--for <dur>] [--forever]'."""
    from aipass.cli.apps.modules import error

    duration_secs, is_forever, rest = _parse_duration_args(args)

    usage = "Usage: medic volume-mute @branch [--for 48h] [--forever]"
    if not rest:
        error("Missing branch name", suggestion=usage)
        return
    branch_name = _extract_branch_name(rest[0])
    if not branch_name:
        error("Missing branch name", suggestion=usage)
        return
    if mute_branch_volume(branch_name, duration_seconds=duration_secs):
        logger.info(f"[MEDIC] Volume-muted branch: {branch_name}")
        if is_forever or duration_secs is None:
            console.print(f"  [yellow]Volume-muted[/yellow] @{branch_name} — permanent (use volume-unmute to restore)")
        else:
            hours = int(duration_secs) // 3600
            console.print(f"  [yellow]Volume-muted[/yellow] @{branch_name} — auto-expires in {hours}h")
        console.print("  [dim]Runaway alerts suppressed. CRITICAL runaways still deliver.[/dim]")
    else:
        error(f"Failed to volume-mute @{branch_name}", suggestion="Check medic_state.json")


def _handle_volume_unmute(console, args: list) -> None:
    """Handle 'medic volume-unmute @branch'."""
    from aipass.cli.apps.modules import error

    usage = "Usage: medic volume-unmute @branch"
    if not args:
        error("Missing branch name", suggestion=usage)
        return
    branch_name = _extract_branch_name(args[0])
    if not branch_name:
        error("Missing branch name", suggestion=usage)
        return
    if unmute_branch_volume(branch_name):
        logger.info(f"[MEDIC] Volume-unmuted branch: {branch_name}")
        console.print(f"  [green]Volume-unmuted[/green] @{branch_name} — runaway alerts resumed")
    else:
        error(f"Failed to volume-unmute @{branch_name}", suggestion="Check medic_state.json")


def _fmt_mute_list(detail: list) -> str:
    """Render a mute detail list as a display string."""
    if not detail:
        return "none"
    parts = []
    for m in detail:
        if m["expires_at"] is None:
            parts.append(f"@{m['name']} [dim](permanent)[/dim]")
        else:
            parts.append(f"@{m['name']} [dim]({_fmt_remaining(m['expires_at'])} left)[/dim]")
    return ", ".join(parts)


def _handle_status(console) -> None:
    """Handle 'medic status' — display current medic state."""
    enabled = is_enabled()
    watcher_active = _is_service_active()

    suppression = get_suppression_stats()
    rate_limits = get_rate_limit_stats()
    muted_detail = get_muted_branches_detail()
    volume_muted_detail = get_volume_muted_branches_detail()

    state_color = "green" if enabled else "yellow"
    state_text = "ENABLED" if enabled else "DISABLED"

    disabled_until = get_disabled_until()
    if not enabled and disabled_until:
        remaining = _fmt_remaining(disabled_until)
        state_text = f"DISABLED (auto-resumes in {remaining})"

    if watcher_active:
        watcher_text = "[green]running[/green] (systemd)"
    elif enabled:
        watcher_text = "[yellow]stopped[/yellow] — run [bold]medic on[/bold] to start"
    else:
        watcher_text = "stopped"

    muted_text = _fmt_mute_list(muted_detail)
    volume_muted_text = _fmt_mute_list(volume_muted_detail)

    console.print("Medic Status")
    console.print(f"  State:           [{state_color}]{state_text}[/{state_color}]")
    console.print(f"  Log watcher:     {watcher_text}")
    console.print(f"  Muted branches:  {muted_text} [dim](content errors)[/dim]")
    console.print(f"  Volume-muted:    {volume_muted_text} [dim](runaway alerts)[/dim]")
    console.print(f"  Suppressed:      {suppression['suppressed_count']}")
    console.print(f"  Last suppressed: {suppression['last_suppressed']}")
    console.print(f"  Rate limited:    {rate_limits['rate_limited_count']}")
    console.print(f"  Last rate limit: {rate_limits['last_rate_limited']}")
    console.print()
    if not enabled:
        console.print("  [dim]All error dispatch suppressed. Errors logged to medic_suppressed.jsonl[/dim]")


def _handle_on(console) -> None:
    """Handle 'medic on' — enable dispatch and start watcher."""
    from rich.panel import Panel
    from aipass.cli.apps.modules import error

    if not set_enabled(True):
        error("Failed to enable Medic", suggestion="Check medic_state.json")
        return

    logger.info("[MEDIC] Medic ENABLED - error dispatch active")
    if not _is_service_active():
        _ensure_service_installed()
        started = _systemctl("start")
        if started:
            logger.info("[MEDIC] Log watcher service started")
        else:
            logger.warning("[MEDIC] Could not start log watcher service")

    watcher_status = "running" if _is_service_active() else "failed to start"
    console.print(
        Panel(
            "[bold green]Medic ENABLED[/bold green]\n\n"
            "Error dispatch is [green]active[/green]. Errors detected in branch logs\n"
            "will be dispatched to affected branches automatically.\n"
            f"Log watcher: [green]{watcher_status}[/green]",
            title="Medic",
            border_style="green",
        )
    )


def _handle_off(console, args: list | None = None) -> None:
    """Handle 'medic off [--forever]' — disable dispatch with 24h TTL or permanently."""
    from rich.panel import Panel
    from aipass.cli.apps.modules import error

    args = args or []
    is_forever = "--forever" in args

    if is_forever:
        if not set_enabled(False):
            error("Failed to disable Medic", suggestion="Check medic_state.json")
            return
        logger.info("[MEDIC] Medic DISABLED permanently")
        if _is_service_active():
            _systemctl("stop")
            logger.info("[MEDIC] Log watcher service stopped")
        console.print(
            Panel(
                "[bold yellow]Medic DISABLED (permanent)[/bold yellow]\n\n"
                "Error dispatch is [yellow]suppressed[/yellow]. Log watcher stopped.\n"
                "Use [bold]medic on[/bold] to re-enable.",
                title="Medic",
                border_style="yellow",
            )
        )
    else:
        hours = DEFAULT_OFF_SECONDS // 3600
        if not set_enabled(False, duration_seconds=float(DEFAULT_OFF_SECONDS)):
            error("Failed to disable Medic", suggestion="Check medic_state.json")
            return
        logger.info("[MEDIC] Medic DISABLED for %dh", hours)
        console.print(
            Panel(
                f"[bold yellow]Medic DISABLED ({hours}h)[/bold yellow]\n\n"
                f"Error dispatch suppressed for {hours} hours, then auto-resumes.\n"
                "Detection continues (log watcher stays running).\n"
                "Use [bold]medic off --forever[/bold] for permanent disable.",
                title="Medic",
                border_style="yellow",
            )
        )


def _route_medic_module(args: list) -> bool:
    """Route 'drone @trigger medic <subcmd>' to handle_command."""
    if not args:
        print_introspection()
        return True
    if wants_help(args):
        print_help()
        return True
    return handle_command(args[0], args[1:])


def handle_command(command: str, args: list) -> bool:
    """
    Handle medic commands - orchestrate toggle operations.

    Routes on/off/status to handler functions and coordinates
    with branch_log_events module for watcher lifecycle.

    Args:
        command: Module name or subcommand (medic, on, off, status)
        args: Additional arguments

    Returns:
        True if command was handled, False otherwise
    """
    from aipass.cli.apps.modules import console

    # Module-name routing (drone @trigger medic <subcmd>)
    if command == "medic":
        if not args:
            print_introspection()
            return True
        return _route_medic_module(args)

    if command not in ["on", "off", "status", "mute", "unmute", "volume-mute", "volume-unmute"]:
        return False

    if wants_help(args):
        print_help()
        return True

    handlers = {
        "mute": lambda: _handle_mute(console, args),
        "unmute": lambda: _handle_unmute(console, args),
        "volume-mute": lambda: _handle_volume_mute(console, args),
        "volume-unmute": lambda: _handle_volume_unmute(console, args),
        "on": lambda: _handle_on(console),
        "off": lambda: _handle_off(console, args),
        "status": lambda: _handle_status(console),
    }
    handler = handlers.get(command)
    if handler:
        handler()

    json_handler.log_operation("medic_toggled", {"command": command})
    return True


if __name__ == "__main__":
    if len(sys.argv) == 1 or sys.argv[1] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    handle_command(sys.argv[1], sys.argv[2:])
