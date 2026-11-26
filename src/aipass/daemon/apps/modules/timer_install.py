# =================== AIPass ====================
# Name: timer_install.py
# Description: Idempotent systemd user timer installer for daemon scheduler
# Version: 1.4.2
# Created: 2026-06-25
# Modified: 2026-11-26
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
from aipass.ai_mail import resolve_verified_caller
from aipass.cli import console, error
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.cli.arg_gate import gate

_DAEMON_ROOT = Path(__file__).resolve().parents[2]
_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"

# A module constant, not a Path.home() call in _install(): a call-time path has no test seam,
# and the suite would mkdir the real ~/.aipass (admin_grant.key, commons.db).
_STATE_DIR = Path.home() / ".aipass"
_SERVICE_NAME = "daemon-tick.service"
_TIMER_NAME = "daemon-tick.timer"

HANDLED_COMMANDS = {"install-timer", "uninstall-timer"}

#: The seat that may start or stop the fleet's scheduler; the owner runs it from that seat too.
ADMIN_SEAT = "@devpulse"


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
    console.print("Run [green]drone @daemon install-timer --help[/green] for usage information")
    console.print()


def print_help():
    """Display usage information."""
    console.print("\n[bold cyan]install-timer / uninstall-timer — daemon Scheduler Timer[/bold cyan]")
    console.print("\n[yellow]USAGE:[/yellow]")
    console.print("  drone @daemon install-timer     Install + enable daemon-tick timer")
    console.print("  drone @daemon uninstall-timer   Stop + remove daemon-tick timer")
    console.print("  drone @daemon install-timer --help")
    console.print("\n[yellow]DESCRIPTION:[/yellow]")
    console.print("  Copies daemon-tick.service and daemon-tick.timer to")
    console.print("  ~/.config/systemd/user/")
    console.print("  Then reloads systemd and enables+starts the timer.")
    console.print("  Idempotent — safe to run multiple times.")
    console.print("  An install that cannot enable the timer puts the unit folder back as it was.")
    console.print(f"  The admin seat ({ADMIN_SEAT}) only, run from its folder: the timer wakes the whole fleet.")
    console.print("\n[yellow]EXAMPLES:[/yellow]")
    console.print("  drone @daemon install-timer")
    console.print("  drone @daemon uninstall-timer")
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


def _seat_refusal(command: str) -> str:
    """'' when the admin seat runs *command*, else the refusal naming what to do.

    The seat is the rule, not the admin grant: a fresh install's lane is dark and cannot be lit.
    A rail that raises propagates, so a check that cannot run never reads as granted.
    """
    caller = resolve_verified_caller()
    if caller == ADMIN_SEAT:
        return ""
    logger.warning("[timer_install] %s refused for %s: not the admin seat", command, caller or "no seat")
    reason = (
        f"the daemon-tick timer wakes the whole fleet, so only the admin seat ({ADMIN_SEAT}) installs or removes it."
    )
    if not caller:
        seat_dir = _DAEMON_ROOT.parent / ADMIN_SEAT.lstrip("@")
        return f"{command} refused: no AIPass seat ran it: {reason} Run it from that seat: cd {seat_dir} && drone @daemon {command}"
    return (
        f"{command} refused for {caller}: {reason} "
        f'Ask: drone @ai_mail email {ADMIN_SEAT} "{command}" "why the timer should change"'
    )


def _restore(previous: dict) -> None:
    """Put each unit path back as it was before the copy: its old bytes, or absent."""
    from aipass.trigger import trigger

    for dst, old in previous.items():
        if old is None:
            dst.unlink(missing_ok=True)
            try:
                trigger.fire("file_deleted", path=str(dst), source="timer_install")
            except Exception as e:
                logger.warning("[timer_install] Trigger fire failed (non-critical): %s", e)
            console.print(f"  [yellow]Removed:[/yellow] {dst} (install did not finish)")
        else:
            dst.write_bytes(old)
            console.print(f"  [yellow]Restored:[/yellow] {dst} (install did not finish)")
    logger.warning("[timer_install] install did not finish: unit folder put back as it was")


def _install() -> int:
    """Install and enable the daemon-tick timer. A failed systemctl step puts the unit folder back as it was."""
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

    previous = {}
    for src in (service_src, timer_src):
        dst = _UNIT_DIR / src.name
        previous[dst] = dst.read_bytes() if dst.exists() else None
        shutil.copy2(src, dst)
        console.print(f"  [green]Copied:[/green] {src.name} -> {dst}")

    console.print()

    for label, step in (
        ("Reloading systemd user daemon...", ("daemon-reload",)),
        ("Enabling daemon-tick.timer...", ("enable", _TIMER_NAME)),
        ("Starting daemon-tick.timer...", ("start", _TIMER_NAME)),
    ):
        console.print(f"  {label}")
        if not _run_systemctl(*step):
            _restore(previous)
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

    Where systemctl is not found, no systemd runs the units, so there is nothing to stop: standing unit
    files are removed (exit 0). A stop timeout or failure where systemctl exists stops the uninstall.
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
    if stopped is False:
        return _uninstall_step_failed("stop", _TIMER_NAME)
    if stopped and (_UNIT_DIR / _TIMER_NAME).exists() and not _run_systemctl("disable", _TIMER_NAME):
        return _uninstall_step_failed("disable", _TIMER_NAME)

    if not installed:
        console.print(f"  [dim]Not installed:[/dim] no daemon-tick unit in {_UNIT_DIR}, nothing to remove")
        logger.info("[timer_install] uninstall: no daemon-tick unit file, nothing to remove")

    from aipass.trigger import trigger

    for dst in installed:
        dst.unlink()
        try:
            trigger.fire("file_deleted", path=str(dst), source="timer_install")
        except Exception as e:
            logger.warning("[timer_install] Trigger fire failed (non-critical): %s", e)
        console.print(f"  [yellow]Removed:[/yellow] {dst}")

    if stopped is None:
        console.print("  [dim]No systemctl on this host: nothing was running the units, nothing to reload[/dim]")
        logger.info("[timer_install] uninstall: no systemctl, unit files removed without a reload")
    elif not _run_systemctl("daemon-reload"):
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

    refusal = _seat_refusal(command)
    if refusal:
        error(refusal)
        sys.exit(1)

    if command == "install-timer":
        exit_code = _install()
    else:
        exit_code = _uninstall()

    if exit_code != 0:
        sys.exit(exit_code)
    return True
