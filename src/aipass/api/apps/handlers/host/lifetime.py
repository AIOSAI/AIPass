# =================== AIPass ====================
# Name: lifetime.py
# Description: Host API Lifetime Handler — a serve that outlives the shell that started it
# Version: 1.3.0
# Created: 2026-08-19
# Modified: 2026-10-17
# =============================================

"""
Host API Lifetime Handler

Detached so drone's exec timeout cannot kill it and its output lands in a file,
not a pane's bounded scrollback. It restarts nothing: the supervisor is systemd.
Reference: docs/host_autostart.md
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

from aipass.drone.apps.modules.config import resolve_aipass_home
from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import autostart

# logs/ is gitignored, which the unit needs: it carries this machine's absolute paths.
RUNTIME_DIRNAME = "logs"
LOG_NAME = "host_api_serve.log"
RECORD_NAME = "host_api_serve.json"

UNIT_FILE_NAME = "aipass-host-api.service"

OWNER_SUPERVISOR = "systemd"
OWNER_DETACHED = "detached"

STOP_TIMEOUT_SECONDS = 10.0
STOP_POLL_SECONDS = 0.2

# Long enough for a startup failure (missing extra, port taken) to happen and be seen.
SETTLE_SECONDS = 0.6

_ANNOUNCED_HOMES: Set[Path] = set()


class LifetimeError(Exception):
    """A detached server could not be started, found or stopped."""


def _detach_kwargs() -> Dict[str, Any]:
    """However this platform says "you are not my child any more"."""
    # start_new_session is POSIX only: Windows accepts it and silently does nothing.
    # Both Windows flags are needed: one severs the console, the other blocks Ctrl-C.
    if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
        detached_process = 0x00000008
        create_new_process_group = 0x00000200
        return {"creationflags": detached_process | create_new_process_group}

    return {"start_new_session": True}


def _branch_root() -> Path:
    """This branch's own directory."""
    return Path(__file__).resolve().parents[3]


def _runtime_dir() -> Path:
    """The directory holding a detached server's output and record."""
    # The home's branch (server_home), not this copy: every later drone command reads the home's record.
    directory = server_home()[1] / RUNTIME_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def log_path() -> Path:
    """Where a detached server's stdout and stderr go."""
    return _runtime_dir() / LOG_NAME


def record_path() -> Path:
    """Where a detached server's facts are kept."""
    return _runtime_dir() / RECORD_NAME


def unit_path() -> Path:
    """Where the rendered supervisor unit is written."""
    return _runtime_dir() / UNIT_FILE_NAME


def server_home() -> Tuple[str, Path]:
    """Which interpreter runs the server, and from which api branch."""
    root = _branch_root()
    home = resolve_aipass_home().path
    if home is None or root.is_relative_to(home.resolve()):
        return sys.executable, root

    branch = home / "src" / "aipass" / "api"
    windows = sys.platform == "win32"
    # Used as found, never resolved: a venv's python is a symlink, and following it loses the venv.
    python = home / ".venv" / ("Scripts" if windows else "bin") / ("python.exe" if windows else "python")
    for needed in (python, branch / "apps" / "api.py"):
        if not needed.is_file():
            raise LifetimeError(
                f"The AIPass home {home} has no {needed}, so its server cannot be started "
                f"(setup.sh makes it; this home is half-installed)"
            )

    if home not in _ANNOUNCED_HOMES:
        _ANNOUNCED_HOMES.add(home)
        logger.info(
            "[host_api] the server runs from the AIPass home %s on %s; this process's copy at %s "
            "belongs to another install",
            home,
            python,
            root,
        )
    return str(python), branch


def serve_argv(host: str, port: int) -> list:
    """The one spelling of how this server is started."""
    # Shared by the detached path and the unit, so a fix cannot land in only one.
    python, branch = server_home()
    entry = branch / "apps" / "api.py"
    return [python, str(entry), "host-api", "serve", "--host", str(host), "--port", str(port)]


def write_unit(host: Optional[str] = None, port: Optional[int] = None) -> Path:
    """Render the supervisor unit into this branch."""
    from aipass.api.apps.handlers.host import config as host_config

    if not autostart.is_supported():
        raise autostart.AutostartUnsupported(
            "Autostart needs a user-level systemd, which this platform does not have. "
            "The server still runs with: drone @api host-api serve --detach"
        )

    config = host_config.load_config()
    bind_host = host if host is not None else config["host"]
    bind_port = int(port if port is not None else config["port"])

    # The bind gate runs here too: a unit is a spawn at every boot, with nobody watching.
    host_config.validate_bind(bind_host, bind_port)

    target = unit_path()
    target.write_text(
        autostart.unit_text(serve_argv(bind_host, bind_port), server_home()[1], log_path()),
        encoding="utf-8",
    )

    logger.info("[host_api] supervisor unit rendered: %s (%s:%s)", target, bind_host, bind_port)
    json_handler.log_operation(
        "host_api_autostart_unit_written",
        {"unit": str(target), "host": bind_host, "port": bind_port},
    )

    return target


def _alive(pid: int) -> bool:
    """Whether a process id is currently running."""
    if pid <= 0:
        return False

    # Never os.kill on Windows: it terminates outright, killing what it asked about.
    if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
        import ctypes

        query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(query_limited_information, False, pid)

        if not handle:
            return False

        ctypes.windll.kernel32.CloseHandle(handle)
        return True

    try:
        # Reap our own exited child first: os.kill(pid, 0) says yes to a zombie.
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError) as e:
        logger.debug("[host_api] nothing to reap for pid %s: %s", pid, e)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        logger.debug("[host_api] pid %s is gone", pid)
        return False
    except PermissionError:
        logger.warning("[host_api] pid %s is running but not ours to signal", pid)
        return True

    return True


def running() -> Optional[Dict[str, Any]]:
    """The live server's record, whoever started it."""
    # Supervisor first: a running unit IS the server, and writes no record file.
    # SupervisorUnreachable propagates, since None would call a live unit absent.
    supervised = autostart.supervised_pid()

    if supervised and _alive(supervised):
        unit_host, unit_port = autostart.supervised_bind()
        return {
            "pid": supervised,
            "host": unit_host,
            "port": unit_port,
            "log": str(log_path()),
            "started": None,
            "owner": OWNER_SUPERVISOR,
            "unit": autostart.unit_name(),
        }

    record_file = record_path()

    if not record_file.is_file():
        return None

    try:
        record = json.loads(record_file.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        # Unreadable is not absent: stop would clear the file naming a live server's pid.
        logger.warning("[host_api] the serve record could not be read (%s): %s", record_file, e)
        raise LifetimeError(f"The serve record at {record_file} could not be read: {e}") from e

    if not isinstance(record, dict):
        raise LifetimeError(f"The serve record at {record_file} is not a record: {type(record).__name__}")

    # A stale record (a reboot leaves one) is no server, not a fault.
    if not _alive(int(record.get("pid") or 0)):
        return None

    record["owner"] = OWNER_DETACHED
    return record


def serve_detached(host: Optional[str] = None, port: Optional[int] = None) -> Dict[str, Any]:
    """Start the server in its own session, with its output in a file."""
    from aipass.api.apps.handlers.host import config as host_config

    existing = running()

    if existing is not None:
        # Name the owner: a supervised server signalled by hand comes straight back.
        if existing.get("owner") == OWNER_SUPERVISOR:
            raise LifetimeError(
                f"The supervisor is already running this server (unit {existing.get('unit')}, "
                f"pid {existing.get('pid')}). Stop it first: drone @api host-api stop"
            )

        raise LifetimeError(
            f"A host-api server is already running (pid {existing.get('pid')}, "
            f"{existing.get('host')}:{existing.get('port')}). Stop it first: drone @api host-api stop"
        )

    config = host_config.load_config()
    bind_host = host if host is not None else config["host"]
    bind_port = int(port if port is not None else config["port"])

    # Before any spawn: a refusal inside the detached child would surface only in a log.
    host_config.validate_bind(bind_host, bind_port)

    command = serve_argv(bind_host, bind_port)

    # Append, never truncate: history surviving a restart is the point.
    with open(log_path(), "a", encoding="utf-8") as stream:
        child = subprocess.Popen(
            command,
            stdout=stream,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=str(server_home()[1]),
            **_detach_kwargs(),
        )

    time.sleep(SETTLE_SECONDS)

    if child.poll() is not None:
        raise LifetimeError(f"The server exited immediately (code {child.returncode}). Its output is in {log_path()}")

    record = {
        "pid": child.pid,
        "host": bind_host,
        "port": bind_port,
        "log": str(log_path()),
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    record_path().write_text(json.dumps(record, indent=2), encoding="utf-8")

    logger.info("[host_api] detached server started: pid=%s %s:%s", child.pid, bind_host, bind_port)
    json_handler.log_operation("host_api_serve_detached", record)

    return record


def stop() -> Optional[Dict[str, Any]]:
    """Stop the running server, through whoever owns it."""
    record = running()

    if record is None:
        # Clear a dead process's record so the next serve is not refused by a ghost.
        record_path().unlink(missing_ok=True)
        return None

    # Never by pid when supervised: Restart= would undo the signal; systemctl stop outranks it.
    if record.get("owner") == OWNER_SUPERVISOR:
        return _stop_supervised(record)

    pid = int(record["pid"])

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        raise LifetimeError(f"Could not signal the server (pid {pid}): {e}") from e

    deadline = time.monotonic() + STOP_TIMEOUT_SECONDS

    while time.monotonic() < deadline:
        if not _alive(pid):
            record_path().unlink(missing_ok=True)
            logger.info("[host_api] detached server stopped: pid=%s", pid)
            json_handler.log_operation("host_api_serve_stopped", {"pid": pid})
            return record

        time.sleep(STOP_POLL_SECONDS)

    # Said, not escalated: SIGKILL would cut short a graceful shutdown that is merely slow.
    raise LifetimeError(
        f"The server (pid {pid}) did not exit within {STOP_TIMEOUT_SECONDS}s. "
        f"It may still be shutting down — check again, or end it yourself."
    )


def _stop_supervised(record: Dict[str, Any]) -> Dict[str, Any]:
    """Ask the supervisor to bring its unit down, and confirm that it did."""
    pid = int(record.get("pid") or 0)

    try:
        accepted = autostart.stop_unit()
    except autostart.AutostartUnsupported as e:
        raise LifetimeError(str(e)) from e

    if not accepted:
        raise LifetimeError(
            f"The supervisor would not stop {record.get('unit')}. "
            f"Ask it directly: systemctl --user status {record.get('unit')}"
        )

    # systemd's TimeoutStopSec budget, not ours: less would call a graceful shutdown a hang.
    # The pid is re-checked: the supervisor accepting a stop is not the process being gone.
    deadline = time.monotonic() + autostart.STOP_TIMEOUT_SECONDS

    while time.monotonic() < deadline:
        if not _alive(pid):
            # No record file to clear: a supervised server never wrote one.
            logger.info("[host_api] the supervisor stopped the server: pid=%s", pid)
            json_handler.log_operation(
                "host_api_serve_stopped",
                {"pid": pid, "owner": OWNER_SUPERVISOR, "unit": record.get("unit")},
            )
            return record

        time.sleep(STOP_POLL_SECONDS)

    raise LifetimeError(
        f"The supervisor accepted the stop but the server (pid {pid}) is still running "
        f"after {autostart.STOP_TIMEOUT_SECONDS}s. Check it: systemctl --user status {record.get('unit')}"
    )


def autostart_report(host: Optional[str] = None, port: Optional[int] = None) -> Dict[str, Any]:
    """Render the unit and gather everything an install needs to be safe."""
    unit = write_unit(host, port)
    report = autostart.installation_report(unit)

    # The conflict check is a courtesy: the unit is written by now, so failing would deny a done write.
    try:
        current = running()
    except autostart.SupervisorUnreachable as e:
        logger.warning("[host_api] the port-conflict check could not reach the supervisor: %s", e)
        current = None
    except LifetimeError as e:
        logger.warning("[host_api] the port-conflict check could not read the serve record: %s", e)
        current = None

    report["conflict"] = current if (current or {}).get("owner") == OWNER_DETACHED else None
    return report


def ensure_autostart(host: Optional[str] = None, port: Optional[int] = None) -> Dict[str, Any]:
    """autostart_report, safe to call twice: a unit the supervisor runs is not re-rendered."""
    pid = autostart.supervised_pid()
    # A live unit keeps the bind it started with; host and port are not applied to it.
    if pid:
        report = autostart.installation_report(unit_path())
        report.update(conflict=None, rendered=False, running=pid)
        return report

    report = autostart_report(host, port)
    report.update(rendered=True, running=0)
    return report


def enable_autostart(dry_run: bool = False) -> Dict[str, Any]:
    """Enable and start the installed unit, unless a hand-started server holds the port."""
    # Refused, not warned: enable --now would retry an unbindable unit into failed, unread.
    current = running() or {}
    if current.get("owner") == OWNER_DETACHED:
        pid = current.get("pid")
        refused = f"A hand-started server holds the port (pid {pid}); stop it first: drone @api host-api stop"
        logger.warning("[host_api] autostart enable refused: %s", refused)
        return {"dry_run": dry_run, "ok": False, "steps": [], "refused": refused}

    return autostart.enable_unit(dry_run)


def server_state() -> Dict[str, Any]:
    """The status lane's answer, including the one running() cannot return."""
    # running() raises for stop and serve, which must refuse; for status "cannot tell" is data.
    try:
        record = running()
    except autostart.SupervisorUnreachable as e:
        logger.warning("[host_api] status could not reach the supervisor: %s", e)
        return {"state": "unknown", "record": None, "reason": str(e)}
    except LifetimeError as e:
        logger.warning("[host_api] status could not read the serve record: %s", e)
        return {"state": "unknown", "record": None, "reason": str(e)}

    if record is None:
        return {"state": "none", "record": None, "reason": ""}

    return {"state": "running", "record": record, "reason": ""}
