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

Commands: on, off, status, mute, unmute
Architecture: Module orchestrates, medic_state handler manages persistence
"""

import subprocess
import sys
from pathlib import Path


from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.trigger.apps.handlers.json import json_handler

from aipass.trigger.apps.handlers.medic_state import (
    is_enabled,
    set_enabled,
    get_muted_branches,
    mute_branch,
    unmute_branch,
    get_suppression_stats,
    get_rate_limit_stats,
)

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
    console.print("medic Module")
    console.print("Medic toggle — control auto-healing error dispatch on/off/mute/unmute")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/")
    console.print("    - medic_state.py (is_enabled — check if medic is enabled)")
    console.print("    - medic_state.py (set_enabled — toggle medic on/off)")
    console.print("    - medic_state.py (get_muted_branches — list muted branches)")
    console.print("    - medic_state.py (mute_branch — suppress dispatch for a branch)")
    console.print("    - medic_state.py (unmute_branch — resume dispatch for a branch)")
    console.print("    - medic_state.py (get_suppression_stats — suppression statistics)")
    console.print("    - medic_state.py (get_rate_limit_stats — rate limit statistics)")
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
    console.print("  [bold]off[/bold]                Disable error dispatch globally (errors still logged)")
    console.print("  [bold]status[/bold]             Show current state, muted branches, and statistics")
    console.print("  [bold]mute[/bold] @branch       Suppress dispatch for a specific branch")
    console.print("  [bold]unmute[/bold] @branch     Resume dispatch for a muted branch")
    console.print("  [bold]help[/bold]               Show this help")
    console.print()
    console.rule("OFF vs MUTE")
    console.print()
    console.print("  [yellow]off[/yellow]    Global kill switch. ALL error dispatch stops. No branch")
    console.print("         receives auto-healing emails. Errors still logged to")
    console.print("         medic_suppressed.log for review.")
    console.print()
    console.print("  [yellow]mute[/yellow]   Per-branch suppress. Only the muted branch stops receiving")
    console.print("         dispatch. All other branches continue normally. Muted errors")
    console.print("         logged to medic_suppressed.log.")
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
    console.print("  Suppressed errors: trigger/logs/medic_suppressed.log")
    console.print()


def _handle_mute(console, args: list) -> None:
    """Handle 'medic mute @branch'."""
    if not args:
        console.print("[red]Missing branch name[/red] - usage: medic mute @branch")
        return
    branch_name = _extract_branch_name(args[0])
    if not branch_name:
        console.print("[red]Missing branch name[/red] - usage: medic mute @branch")
        return
    if mute_branch(branch_name):
        logger.info(f"[MEDIC] Muted branch: {branch_name}")
        console.print(f"  [yellow]Muted[/yellow] @{branch_name} — errors logged but not dispatched")
    else:
        console.print(f"  [red]Failed to mute[/red] @{branch_name} — check trigger_config.json")


def _handle_unmute(console, args: list) -> None:
    """Handle 'medic unmute @branch'."""
    if not args:
        console.print("[red]Missing branch name[/red] - usage: medic unmute @branch")
        return
    branch_name = _extract_branch_name(args[0])
    if not branch_name:
        console.print("[red]Missing branch name[/red] - usage: medic unmute @branch")
        return
    if unmute_branch(branch_name):
        logger.info(f"[MEDIC] Unmuted branch: {branch_name}")
        console.print(f"  [green]Unmuted[/green] @{branch_name} — dispatch resumed")
    else:
        console.print(f"  [red]Failed to unmute[/red] @{branch_name} — check trigger_config.json")


def _handle_status(console) -> None:
    """Handle 'medic status' — display current medic state."""
    enabled = is_enabled()
    watcher_active = _is_service_active()

    suppression = get_suppression_stats()
    rate_limits = get_rate_limit_stats()
    muted = get_muted_branches()

    state_color = "green" if enabled else "yellow"
    state_text = "ENABLED" if enabled else "DISABLED"
    if watcher_active:
        watcher_text = "[green]running[/green] (systemd)"
    elif enabled:
        watcher_text = "[yellow]stopped[/yellow] — run [bold]medic on[/bold] to start"
    else:
        watcher_text = "stopped"
    muted_text = ", ".join(f"@{b}" for b in muted) if muted else "none"

    console.print("Medic Status")
    console.print(f"  State:           [{state_color}]{state_text}[/{state_color}]")
    console.print(f"  Log watcher:     {watcher_text}")
    console.print(f"  Muted branches:  {muted_text}")
    console.print(f"  Suppressed:      {suppression['suppressed_count']}")
    console.print(f"  Last suppressed: {suppression['last_suppressed']}")
    console.print(f"  Rate limited:    {rate_limits['rate_limited_count']}")
    console.print(f"  Last rate limit: {rate_limits['last_rate_limited']}")
    console.print()
    if not enabled:
        console.print("  [dim]All error dispatch suppressed. Errors logged to medic_suppressed.log[/dim]")


def _handle_on(console) -> None:
    """Handle 'medic on' — enable dispatch and start watcher."""
    from rich.panel import Panel

    if not set_enabled(True):
        console.print("[red]Failed to enable Medic[/red] - check trigger_config.json")
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


def _handle_off(console) -> None:
    """Handle 'medic off' — disable dispatch and stop watcher."""
    from rich.panel import Panel

    if not set_enabled(False):
        console.print("[red]Failed to disable Medic[/red] - check trigger_config.json")
        return

    logger.info("[MEDIC] Medic DISABLED - error dispatch suppressed")
    if _is_service_active():
        _systemctl("stop")
        logger.info("[MEDIC] Log watcher service stopped")

    console.print(
        Panel(
            "[bold yellow]Medic DISABLED[/bold yellow]\n\n"
            "Error dispatch is [yellow]suppressed[/yellow]. Errors are still detected\n"
            "and logged to [dim]medic_suppressed.log[/dim] for review.\n"
            "Log watcher: [yellow]stopped[/yellow]",
            title="Medic",
            border_style="yellow",
        )
    )


def _route_medic_module(args: list) -> bool:
    """Route 'drone @trigger medic <subcmd>' to handle_command."""
    if not args:
        print_introspection()
        return True
    if args[0] in ["--help", "-h", "help"]:
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

    if command not in ["on", "off", "status", "mute", "unmute"]:
        return False

    if args and args[0] in ["--help", "-h", "help"]:
        print_help()
        return True

    handlers = {
        "mute": lambda: _handle_mute(console, args),
        "unmute": lambda: _handle_unmute(console, args),
        "on": lambda: _handle_on(console),
        "off": lambda: _handle_off(console),
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
