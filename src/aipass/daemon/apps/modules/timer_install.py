# =================== AIPass ====================
# Name: timer_install.py
# Description: Idempotent systemd user timer installer for daemon scheduler
# Version: 1.2.0
# Created: 2026-06-25
# Modified: 2026-10-17
# =============================================

"""
Timer installer — idempotent install/uninstall of daemon-tick systemd user units.

Handles 'drone @daemon install-timer' and 'drone @daemon uninstall-timer'.
"""

import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.cli.arg_gate import gate
from aipass.daemon.apps.handlers.module_root import module_file

_DAEMON_ROOT = module_file(__file__).parents[2]
_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"

# A module constant, not a Path.home() call in _install(): a call-time path has no test seam,
# and the suite would mkdir the real ~/.aipass (admin_grant.key, commons.db).
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


# systemctl's exit for a unit it does not know (a stop of a name that is not loaded).
_EXIT_NOT_LOADED = 5


def _run_systemctl(*args: str, not_loaded_ok: bool = False, not_found_ok: bool = False) -> Optional[bool]:
    """Run a systemctl --user command. Returns True on success.

    Every failure (non-zero exit, missing systemctl, timeout) answers False after printing error(); True is
    a zero exit, or exit 5 (unit not loaded) when the caller passes not_loaded_ok.

    None, only when the caller passes not_found_ok: systemctl is not found on this host (logged, not
    printed), so the caller can tell not found from every other failure. A timeout is never not found.
    """
    cmd = ["systemctl", "--user", *args]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if not_loaded_ok and result.returncode == _EXIT_NOT_LOADED:
            logger.info("[timer_install] systemctl --user %s: not loaded, nothing to do", " ".join(args))
            return True
        if result.returncode != 0:
            logger.warning("[timer_install] systemctl --user %s failed: %s", " ".join(args), result.stderr.strip())
            error(f"FAIL: systemctl --user {' '.join(args)}")
            if result.stderr.strip():
                console.print(f"  [dim]{result.stderr.strip()}[/dim]")
            return False
        return True
    except FileNotFoundError:
        if not_found_ok:
            logger.info("[timer_install] systemctl not found — systemd not available, answered as not found")
            return None
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


def _uninstall_step_failed(*args: str) -> int:
    """Name the systemctl step an uninstall stopped at, with error(), and answer exit code 1."""
    step = " ".join(args)
    logger.warning("[timer_install] uninstall stopped: systemctl --user %s failed", step)
    error(
        f"uninstall-timer: systemctl --user {step} failed",
        suggestion="systemctl --user status daemon-tick.timer",
    )
    return 1


def _uninstall() -> int:
    """Stop, disable, and remove the daemon-tick timer.

    Installed means a unit file in _UNIT_DIR or a unit systemd knows, so the stop is always asked.
    Each step must answer True: the first failure is named with error(), the answer is 1, and the files stay.

    Where systemctl is not found: no unit file standing means nothing installed (exit 0); a standing
    unit file makes the stop the failed step (exit 1, files stay). A stop timeout is a failure.
    """
    console.print("[bold cyan]Uninstalling daemon-tick units...[/bold cyan]")
    console.print()

    installed = [_UNIT_DIR / name for name in (_SERVICE_NAME, _TIMER_NAME) if (_UNIT_DIR / name).exists()]

    stopped = _run_systemctl("stop", _TIMER_NAME, not_loaded_ok=True, not_found_ok=True)
    if stopped is None and not installed:
        console.print(f"  [dim]Not installed:[/dim] no systemctl on this host and no daemon-tick unit in {_UNIT_DIR}")
        console.print()
        logger.info("[timer_install] uninstall: no systemctl and no unit file, nothing installed")
        return 0
    if not stopped:
        return _uninstall_step_failed("stop", _TIMER_NAME)
    if (_UNIT_DIR / _TIMER_NAME).exists() and not _run_systemctl("disable", _TIMER_NAME):
        return _uninstall_step_failed("disable", _TIMER_NAME)

    if not installed:
        console.print(f"  [dim]Not installed:[/dim] no daemon-tick unit in {_UNIT_DIR}, nothing to remove")
        logger.info("[timer_install] uninstall: no daemon-tick unit file, nothing to remove")

    for dst in installed:
        dst.unlink()
        try:
            from aipass.trigger.apps.modules.core import trigger

            trigger.fire("file_deleted", path=str(dst), source="timer_install")
        except ImportError:
            logger.info("[timer_install] Trigger module not available, skipping event fire")
        except Exception as e:
            logger.warning("[timer_install] Trigger fire failed (non-critical): %s", e)
        console.print(f"  [yellow]Removed:[/yellow] {dst}")

    if not _run_systemctl("daemon-reload"):
        return _uninstall_step_failed("daemon-reload")

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

    gate(command, args, usage=f"drone @daemon {command}")

    if command == "install-timer":
        exit_code = _install()
    else:
        exit_code = _uninstall()

    if exit_code != 0:
        sys.exit(exit_code)
    return True
