# =================== AIPass ====================
# Name: autostart.py
# Description: Host API Autostart Handler — the supervisor seam, so the server survives a reboot
# Version: 1.1.0
# Created: 2026-08-27
# Modified: 2026-10-17
# =============================================

"""
Host API Autostart Handler

Supervises nothing: renders a systemd user unit, answers whether systemd holds
the server, and asks it to stop. Reference: docs/host_autostart.md
"""

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

# Spelled once: the printed install commands and the "are you holding it?" probe must mean one unit.
UNIT_NAME = "aipass-host-api.service"

USER_UNIT_DIR = "~/.config/systemd/user"

# enable --now starts the server, so it waits for a start, not a probe.
ENABLE_TIMEOUT_SECONDS = 30.0

# A hung probe would hang `status`, the command run precisely when things are strange.
PROBE_TIMEOUT_SECONDS = 5.0

# Above TIMEOUT_STOP_SECONDS: systemd runs the graceful shutdown and its bookkeeping.
STOP_TIMEOUT_SECONDS = 20.0

# Generous enough to outlast tailscaled assigning the bind address at boot, still finite.
RESTART_SECONDS = 5
START_LIMIT_INTERVAL_SECONDS = 600
START_LIMIT_BURST = 60

# Above lifetime's ten seconds, so the supervisor never cuts a shutdown short.
TIMEOUT_STOP_SECONDS = 15


class AutostartUnsupported(Exception):
    """This platform has no user-level systemd to hand the server to."""


class SupervisorUnreachable(Exception):
    """There IS a supervisor here and it did not answer."""


def is_supported() -> bool:
    """Whether the supervisor lane can work on this platform at all."""
    if not sys.platform.startswith("linux"):
        return False

    return shutil.which("systemctl") is not None


def unit_name() -> str:
    """The unit this branch installs and asks about."""
    return UNIT_NAME


def unit_text(argv: List[str], workdir: Path, log: Path) -> str:
    """Render the unit file."""
    # append:, never file: (truncates each start). StartLimit* belong under [Unit]:
    # since v230 systemd silently IGNORES them under [Service].
    command = " ".join(argv)

    return f"""[Unit]
Description=AIPass host API — the tailnet server behind BAUD's phone face
Documentation=file://{workdir}/README.md
StartLimitIntervalSec={START_LIMIT_INTERVAL_SECONDS}
StartLimitBurst={START_LIMIT_BURST}

[Service]
Type=simple
WorkingDirectory={workdir}
ExecStart={command}
StandardOutput=append:{log}
StandardError=append:{log}
Restart=on-failure
RestartSec={RESTART_SECONDS}
KillSignal=SIGTERM
TimeoutStopSec={TIMEOUT_STOP_SECONDS}

[Install]
WantedBy=default.target
"""


def _systemctl(arguments: List[str], timeout: float) -> Optional[subprocess.CompletedProcess]:
    """
    Run a `systemctl --user` command.

    None means this platform has no systemctl, never that it failed to answer.
    """
    if not is_supported():
        return None

    try:
        return subprocess.run(
            ["systemctl", "--user", *arguments],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("[host_api] the supervisor could not be reached: %s", e)
        raise SupervisorUnreachable(f"systemctl is here but did not answer: {e}") from e


def supervised_pid() -> int:
    """The unit's live main process id."""
    # show, not is-active: is-active exits non-zero for an inactive unit, so "no"
    # and "could not ask" would look alike; show exits non-zero only on failure.
    result = _systemctl(["show", UNIT_NAME, "-p", "MainPID", "--value"], PROBE_TIMEOUT_SECONDS)

    if result is None or result.returncode != 0:
        return 0

    raw = (result.stdout or "").strip()

    try:
        pid = int(raw)
    except ValueError as e:
        # No measurement, so it refuses: zero would claim no unit holds the server.
        raise SupervisorUnreachable(f"the supervisor reported an unreadable MainPID: {raw!r}") from e

    return pid if pid > 0 else 0


def supervised_bind() -> Tuple[Optional[str], Optional[int]]:
    """The address the supervised server was actually started on."""
    # From the unit, not the stored config: set-config changes the next install, not this process.
    try:
        result = _systemctl(["show", UNIT_NAME, "-p", "ExecStart", "--value"], PROBE_TIMEOUT_SECONDS)
    except SupervisorUnreachable as e:
        # Swallowed here only: the pid probe already gave the verdict; this costs just the address.
        logger.warning("[host_api] the unit's bind could not be read: %s", e)
        return (None, None)

    if result is None or result.returncode != 0:
        return (None, None)

    line = (result.stdout or "").strip()

    if not line:
        return (None, None)

    words = line.replace(";", " ").split()

    return (_flag_in(words, "--host"), _port_in(words))


def _flag_in(words: Sequence[str], flag: str) -> Optional[str]:
    """The value following *flag* in a systemd argv line."""
    for name, value in zip(words, words[1:]):
        if name == flag:
            return value

    return None


def _port_in(words: Sequence[str]) -> Optional[int]:
    """The port the unit was started on."""
    raw = _flag_in(words, "--port")

    if raw is None:
        return None

    try:
        return int(raw)
    except ValueError:
        logger.warning("[host_api] the unit names an unreadable port: %r", raw)
        return None


def stop_unit() -> bool:
    """Ask the supervisor to stop the unit."""
    if not is_supported():
        raise AutostartUnsupported("There is no user-level systemd on this platform")

    result = _systemctl(["stop", UNIT_NAME], STOP_TIMEOUT_SECONDS)

    if result is None:
        return False

    if result.returncode != 0:
        logger.warning("[host_api] the supervisor refused the stop: %s", (result.stderr or "").strip())
        return False

    logger.info("[host_api] the supervisor stopped %s", UNIT_NAME)
    json_handler.log_operation("host_api_supervisor_stopped", {"unit": UNIT_NAME})
    return True


def linger_enabled() -> Optional[bool]:
    """
    Whether this account's user units run without a login session.

    None means the question could not be asked: a third answer, not a no.
    """
    if not sys.platform.startswith("linux") or shutil.which("loginctl") is None:
        return None

    try:
        result = subprocess.run(
            ["loginctl", "show-user", str(Path.home().name), "-p", "Linger", "--value"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("[host_api] lingering could not be read: %s", e)
        return None

    if result.returncode != 0:
        return None

    return (result.stdout or "").strip().lower() == "yes"


def install_commands(unit_file: Path) -> List[str]:
    """The exact host-side steps, in the order they must run."""
    # Positional contract: install_unit takes [:3], enable_unit takes [3:].
    # enable --now, so enabled-but-not-running cannot be the state left behind.
    return [
        f"mkdir -p {USER_UNIT_DIR}",
        f"cp {unit_file} {USER_UNIT_DIR}/{UNIT_NAME}",
        "systemctl --user daemon-reload",
        f"systemctl --user enable --now {UNIT_NAME}",
        "loginctl enable-linger $USER",
    ]


def installation_report(unit_file: Path) -> dict:
    """Everything the autostart command has to show, gathered in one place."""
    return {
        "unit": unit_file,
        "steps": install_commands(unit_file),
        "linger": linger_enabled(),
    }


class _StepFailed(Exception):
    """One install step did not complete; its text is the reason."""


def _run_steps(steps: List[Tuple[str, Callable[[], str]]], dry_run: bool) -> Dict[str, Any]:
    """Run named steps in order, stopping at the first that fails."""
    if dry_run:
        return {"dry_run": True, "ok": True, "steps": [{"step": name, "ok": None, "detail": ""} for name, _ in steps]}

    done: List[Dict[str, Any]] = []
    for name, action in steps:
        try:
            detail = action()
        except _StepFailed as e:
            logger.warning("[host_api] autostart step failed: %s: %s", name, e)
            done.append({"step": name, "ok": False, "detail": str(e)})
            return {"dry_run": False, "ok": False, "steps": done}
        done.append({"step": name, "ok": True, "detail": detail})

    json_handler.log_operation("host_api_autostart_steps_ran", {"steps": [entry["step"] for entry in done]})
    return {"dry_run": False, "ok": True, "steps": done}


def _systemctl_step(arguments: List[str], timeout: float) -> str:
    """One systemctl --user call as a step: its stdout, or _StepFailed with why."""
    try:
        result = _systemctl(arguments, timeout)
    except SupervisorUnreachable as e:
        raise _StepFailed(str(e)) from e

    if result is None:
        raise _StepFailed("systemctl could not be run on this platform")
    if result.returncode != 0:
        raise _StepFailed((result.stderr or result.stdout or f"exit {result.returncode}").strip())
    return (result.stdout or "").strip()


def _user_unit_dir() -> Path:
    """The user unit directory, under this account's home."""
    return Path.home() / ".config" / "systemd" / "user"


def install_unit(unit_file: Path, dry_run: bool = False) -> Dict[str, Any]:
    """Copy the rendered unit into the user unit directory and reload systemd."""
    if not is_supported():
        raise AutostartUnsupported("Autostart needs a user-level systemd, which this platform does not have")

    target_dir = _user_unit_dir()
    target = target_dir / UNIT_NAME

    def make_dir() -> str:
        """Create the user unit directory."""
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise _StepFailed(str(e)) from e
        return ""

    def copy_unit() -> str:
        """Copy the rendered unit over any installed one."""
        try:
            shutil.copyfile(unit_file, target)
        except OSError as e:
            raise _StepFailed(str(e)) from e
        return ""

    mkdir_step, copy_step, reload_step = install_commands(unit_file)[:3]
    return _run_steps(
        [
            (mkdir_step, make_dir),
            (copy_step, copy_unit),
            (reload_step, lambda: _systemctl_step(["daemon-reload"], PROBE_TIMEOUT_SECONDS)),
        ],
        dry_run,
    )


def enable_unit(dry_run: bool = False) -> Dict[str, Any]:
    """Enable and start the installed unit, and turn lingering on if it is off."""
    if not is_supported():
        raise AutostartUnsupported("Autostart needs a user-level systemd, which this platform does not have")

    enable_step, linger_step = install_commands(Path(UNIT_NAME))[3:]
    steps: List[Tuple[str, Callable[[], str]]] = [
        (enable_step, lambda: _systemctl_step(["enable", "--now", UNIT_NAME], ENABLE_TIMEOUT_SECONDS)),
    ]
    # Unreadable lingering (None) still runs the step: enable-linger is idempotent.
    if linger_enabled() is not True:
        steps.append((linger_step, _enable_linger))
    return _run_steps(steps, dry_run)


def _enable_linger() -> str:
    """loginctl enable-linger for this account, as a step. No user named: loginctl means the caller."""
    try:
        result = subprocess.run(
            ["loginctl", "enable-linger"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise _StepFailed(str(e)) from e

    if result.returncode != 0:
        raise _StepFailed((result.stderr or f"exit {result.returncode}").strip())
    return ""
