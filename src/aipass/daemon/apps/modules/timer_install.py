# =================== AIPass ====================
# Name: timer_install.py
# Description: Idempotent systemd user timer installer for daemon scheduler
# Version: 1.0.0
# Created: 2026-06-25
# Modified: 2026-06-25
# =============================================

"""
Timer installer — idempotent install/uninstall of daemon-tick systemd user units.

Handles 'drone @daemon install-timer' and 'drone @daemon uninstall-timer'.
Copies daemon-tick.service + daemon-tick.timer to ~/.config/systemd/user/,
reloads systemd, and enables/starts the timer.
"""

import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from aipass.daemon.apps.handlers.json import json_handler

_DAEMON_ROOT = Path(__file__).resolve().parents[2]
_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"

# The shared AIPass state directory. A MODULE CONSTANT rather than a
# Path.home() call inside _install(), because a path computed at call time
# has no seam: the test could patch _DAEMON_ROOT and _UNIT_DIR and still
# watch the suite mkdir the real ~/.aipass, which holds admin_grant.key and
# commons.db. Found by the audit-tests lane, red-first before this line moved.
_STATE_DIR = Path.home() / ".aipass"
_SERVICE_NAME = "daemon-tick.service"
_TIMER_NAME = "daemon-tick.timer"

HANDLED_COMMANDS = {"install-timer", "uninstall-timer"}


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]timer_install Module[/bold cyan]")
    console.print()
    console.print("[dim]Idempotent systemd user timer installer for daemon scheduler[/dim]")
    console.print()
    console.print("[yellow]Unit files:[/yellow]")
    console.print(f"  [cyan]*[/cyan] {_DAEMON_ROOT / _SERVICE_NAME}")
    console.print(f"  [cyan]*[/cyan] {_DAEMON_ROOT / _TIMER_NAME}")
    console.print(f"  [cyan]*[/cyan] Installs to: {_UNIT_DIR}/")
    console.print()


def print_help():
    """Display usage information."""
    console.print("\n[bold cyan]install-timer / uninstall-timer — Daemon Scheduler Timer[/bold cyan]")
    console.print("\n[yellow]USAGE:[/yellow]")
    console.print("  drone @daemon install-timer     Install + enable daemon-tick timer")
    console.print("  drone @daemon uninstall-timer   Stop + remove daemon-tick timer")
    console.print("  drone @daemon install-timer --help")
    console.print("\n[yellow]DESCRIPTION:[/yellow]")
    console.print("  Copies daemon-tick.service and daemon-tick.timer to")
    console.print("  ~/.config/systemd/user/")
    console.print("  Then reloads systemd and enables+starts the timer.")
    console.print("  Idempotent — safe to run multiple times.")
    console.print()


def _run_systemctl(*args: str) -> bool:
    """Run a systemctl --user command. Returns True on success."""
    cmd = ["systemctl", "--user", *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            logger.warning("[timer_install] systemctl --user %s failed: %s", " ".join(args), result.stderr.strip())
            error(f"FAIL: systemctl --user {' '.join(args)}")
            if result.stderr.strip():
                console.print(f"  [dim]{result.stderr.strip()}[/dim]")
            return False
        return True
    except FileNotFoundError:
        logger.error("[timer_install] systemctl not found — systemd not available")
        error("systemctl not found — systemd not available")
        return False
    except subprocess.TimeoutExpired:
        logger.error("[timer_install] systemctl --user %s timed out", " ".join(args))
        error("systemctl timed out")
        return False


def _install() -> int:
    """Install and enable the daemon-tick timer."""
    service_src = _DAEMON_ROOT / _SERVICE_NAME
    timer_src = _DAEMON_ROOT / _TIMER_NAME

    for src in (service_src, timer_src):
        if not src.exists():
            logger.error("[timer_install] Missing unit file: %s", src)
            return 1

    _UNIT_DIR.mkdir(parents=True, exist_ok=True)

    json_handler.log_operation("install_timer", {"target": str(_UNIT_DIR)})

    console.print("[bold cyan]Installing daemon-tick units...[/bold cyan]")
    console.print()

    for src in (service_src, timer_src):
        dst = _UNIT_DIR / src.name
        shutil.copy2(src, dst)
        console.print(f"  [green]Copied:[/green] {src.name} -> {dst}")

    console.print()

    console.print("  Reloading systemd user daemon...")
    if not _run_systemctl("daemon-reload"):
        return 1

    console.print("  Enabling daemon-tick.timer...")
    if not _run_systemctl("enable", _TIMER_NAME):
        return 1

    console.print("  Starting daemon-tick.timer...")
    if not _run_systemctl("start", _TIMER_NAME):
        return 1

    console.print()
    console.print("[bold green]daemon-tick.timer installed and active.[/bold green]")
    console.print("[dim]Verify: systemctl --user list-timers | grep daemon[/dim]")
    console.print()

    _STATE_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("[timer_install] daemon-tick timer installed and started")
    return 0


def _uninstall() -> int:
    """Stop, disable, and remove the daemon-tick timer."""
    console.print("[bold cyan]Uninstalling daemon-tick units...[/bold cyan]")
    console.print()

    _run_systemctl("stop", _TIMER_NAME)
    _run_systemctl("disable", _TIMER_NAME)

    for name in (_SERVICE_NAME, _TIMER_NAME):
        dst = _UNIT_DIR / name
        if dst.exists():
            dst.unlink()
            try:
                from aipass.trigger.apps.modules.core import trigger

                trigger.fire("file_deleted", path=str(dst), source="timer_install")
            except ImportError:
                logger.info("[timer_install] Trigger module not available, skipping event fire")
            except Exception as e:
                logger.warning("[timer_install] Trigger fire failed (non-critical): %s", e)
            console.print(f"  [yellow]Removed:[/yellow] {dst}")
        else:
            console.print(f"  [dim]Not found:[/dim] {dst}")

    _run_systemctl("daemon-reload")

    console.print()
    console.print("[bold green]daemon-tick units removed.[/bold green]")
    console.print()

    logger.info("[timer_install] daemon-tick timer uninstalled")
    return 0


def handle_command(command: str, args: List[str]) -> bool:
    """Handle install-timer / uninstall-timer commands."""
    if command not in HANDLED_COMMANDS:
        return False

    if args and args[0] in ("--help", "-h"):
        print_help()
        return True

    if command == "install-timer":
        exit_code = _install()
    else:
        exit_code = _uninstall()

    if exit_code != 0:
        sys.exit(exit_code)
    return True
