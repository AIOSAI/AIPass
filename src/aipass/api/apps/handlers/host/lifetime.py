# =================== AIPass ====================
# Name: lifetime.py
# Description: Host API Lifetime Handler — a serve that outlives the shell that started it
# Version: 1.0.0
# Created: 2026-08-19
# Modified: 2026-08-19
# =============================================

"""
Host API Lifetime Handler

Starting, finding and stopping a long-running server without a wrapper holding
it by the throat.

WHY THIS EXISTS
---------------
`host-api serve` is a process that should run for weeks. Every route into it
runs it as a CHILD of something with an opinion about how long a command may
take. drone applies an exec timeout to everything it routes, so the server was
launched with `--drone-timeout 43200` — and on 2026-08-19 @baud read the pane
and found what that buys: fourteen cycles of

    drone: Command timed out after 43200s: apps/api.py host-api serve
    [host-api] serve exited - restarting in 2s

The server answered fine between deaths. What did not survive was the ACCESS
HISTORY. uvicorn writes its access log to stdout, stdout was a tmux pane, and a
pane holds a bounded scrollback — so the restart churn pushed an entire day out
of it. That log was the instrument for the morning's deploy archaeology; by
evening @baud could not answer which bundle a phone had pulled, and the reason
was not that nobody looked. There was nowhere for it to be.

Those are the same defect. A server whose output has no home but a terminal has
no history, and a server that must be held open by a caller cannot outlive that
caller's patience. Detaching fixes both at once: the child gets its own session
and a FILE for its output, and the launcher — which is what drone is actually
timing — exits in under a second.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It does not restart anything. The shell loop that produced those fourteen lines
lives in whoever's pane typed it, not in this tree, and replacing it with a
supervisor of my own would be inventing a second one. A detached server that
dies stays dead and says so through `status` — which looks like a worse failure
and is a much more honest one than a process quietly reincarnating every twelve
hours with a fresh, empty log.

Nor does it make detaching the default. `serve` in the foreground is still the
right thing under a real supervisor, and is what every existing caller gets.

THE REAL SUPERVISOR ARRIVED ON 2026-08-27, and that refusal is why it is
systemd rather than something here. @baud's face went dark after a reboot took
the detached server with it; the answer is a user unit (see autostart.py), not a
loop in this file. What CHANGED here is only knowledge: two commands used to
assume that a server they did not start does not exist.

    running() asked a record file that a unit-managed server never writes, so a
    perfectly healthy server read as absent.

    stop() signalled a pid directly, which under a restart policy is a stop the
    supervisor is entitled to undo — a command that works and then reverses
    itself is worse than one that refuses.

Both now ask who owns the process first. `serve` in the foreground is still what
the unit itself runs, so the supervised path goes through the same code every
other caller does.

Functions:
    serve_argv()      - The one spelling of how this server is started
    write_unit()      - Render the supervisor unit into this branch
    autostart_report() - Render the unit and gather everything an install needs
    server_state()    - The status lane's answer, including "cannot tell"
    serve_detached()  - Start the server in its own session, return its facts
    running()         - The live server's record, or None
    stop()            - Stop the running server, through its owner
    log_path()        - Where a detached server's output goes
    record_path()     - Where its facts are kept
    unit_path()       - Where the rendered unit is written
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import autostart

# logs/ is gitignored and is already where this branch's runtime output lives,
# so a detached server's stdout and its pid record sit beside the prax logs
# rather than inventing a second runtime directory nobody looks in.
RUNTIME_DIRNAME = "logs"
LOG_NAME = "host_api_serve.log"
RECORD_NAME = "host_api_serve.json"

# The rendered unit lands beside them, and is GITIGNORED along with the rest of
# logs/ on purpose: it necessarily carries this machine's absolute paths and
# this machine's bind address, and a file like that in a public tree is either a
# hardcoded path or somebody else's broken install.
UNIT_FILE_NAME = "aipass-host-api.service"

# Who is holding the server. Reported rather than inferred at the point of use,
# because both commands that care have to make a different decision on it.
OWNER_SUPERVISOR = "systemd"
OWNER_DETACHED = "detached"

# How long to wait for a stopped server to actually go. Long enough for uvicorn
# to finish its graceful shutdown, short enough that a caller is not left
# wondering whether the command hung.
STOP_TIMEOUT_SECONDS = 10.0
STOP_POLL_SECONDS = 0.2

# Long enough for an immediate failure — a missing extra, a port already taken —
# to have happened and reached the log. A launcher that reports success for a
# process that died on startup is worse than no launcher.
SETTLE_SECONDS = 0.6


class LifetimeError(Exception):
    """A detached server could not be started, found or stopped."""


def _detach_kwargs() -> Dict[str, Any]:
    """
    However this platform says "you are not my child any more".

    Returns:
        The Popen keywords that actually detach here.

    Note:
        start_new_session IS THE POSIX SPELLING AND ONLY THAT. Popen accepts it
        on Windows and silently does nothing with it, which is the worst
        possible failure for this particular flag: `--detach` would report
        success, the server would look detached, and it would still die with
        whatever timed out its parent. Caught by seedgo's Windows check on
        2026-08-19, not by a test — nothing here runs on Windows.

        DETACHED_PROCESS severs the console; CREATE_NEW_PROCESS_GROUP means a
        Ctrl-C in the launching terminal is not delivered to the server. Both
        are needed: either alone leaves one of the two ways a terminal can
        reach in.
    """
    if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
        detached_process = 0x00000008
        create_new_process_group = 0x00000200
        return {"creationflags": detached_process | create_new_process_group}

    return {"start_new_session": True}


def _branch_root() -> Path:
    """
    This branch's own directory.

    Returns:
        The directory holding apps/, resolved from this file rather than from a
        caller's cwd — a detached server is started from wherever the operator
        happened to be standing.
    """
    return Path(__file__).resolve().parents[3]


def _runtime_dir() -> Path:
    """
    The directory holding a detached server's output and record.

    Returns:
        The runtime directory, created if absent.
    """
    directory = _branch_root() / RUNTIME_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def log_path() -> Path:
    """
    Where a detached server's stdout and stderr go.

    Returns:
        The log file path. APPENDED to, never truncated — the whole point is
        that history survives a restart.
    """
    return _runtime_dir() / LOG_NAME


def record_path() -> Path:
    """
    Where a detached server's facts are kept.

    Returns:
        The record path — pid, bind address, and when it started.
    """
    return _runtime_dir() / RECORD_NAME


def unit_path() -> Path:
    """
    Where the rendered supervisor unit is written.

    Returns:
        The unit file's path inside this branch. Installing it is a separate,
        host-side step — nothing in this tree writes under ~/.config.
    """
    return _runtime_dir() / UNIT_FILE_NAME


def serve_argv(host: str, port: int) -> list:
    """
    The one spelling of how this server is started.

    Args:
        host: The bind address.
        port: The bind port.

    Returns:
        The argv, absolute in both the interpreter and the entry point.

    Note:
        SHARED BY THE DETACHED PATH AND THE UNIT ON PURPOSE. Two ways to start
        one server is how a fix lands in one of them and the other keeps the
        bug — and the unit's copy is the one nobody re-reads, because it lives
        in a file under somebody's home directory that this tree cannot see.
    """
    entry = _branch_root() / "apps" / "api.py"
    return [sys.executable, str(entry), "host-api", "serve", "--host", str(host), "--port", str(port)]


def write_unit(host: Optional[str] = None, port: Optional[int] = None) -> Path:
    """
    Render the supervisor unit into this branch.

    Args:
        host: Bind address override. Defaults to the stored config.
        port: Bind port override. Defaults to the stored config.

    Returns:
        The path the unit was written to.

    Raises:
        BindRefused: The address was refused. NOTHING is written.
        AutostartUnsupported: There is no user-level systemd here.

    Note:
        THE BIND GATE RUNS HERE TOO, and for the same reason it runs before a
        detached spawn: a unit is a spawn that happens at every boot from now
        on, with nobody watching. An address refused at the CLI and then baked
        into a unit would be D1 holding everywhere except the one place it
        repeats forever.
    """
    from aipass.api.apps.handlers.host import config as host_config

    if not autostart.is_supported():
        raise autostart.AutostartUnsupported(
            "Autostart needs a user-level systemd, which this platform does not have. "
            "The server still runs with: drone @api host-api serve --detach"
        )

    config = host_config.load_config()
    bind_host = host if host is not None else config["host"]
    bind_port = int(port if port is not None else config["port"])

    host_config.validate_bind(bind_host, bind_port)

    target = unit_path()
    target.write_text(
        autostart.unit_text(serve_argv(bind_host, bind_port), _branch_root(), log_path()),
        encoding="utf-8",
    )

    logger.info("[host_api] supervisor unit rendered: %s (%s:%s)", target, bind_host, bind_port)
    json_handler.log_operation(
        "host_api_autostart_unit_written",
        {"unit": str(target), "host": bind_host, "port": bind_port},
    )

    return target


def _alive(pid: int) -> bool:
    """
    Whether a process id is currently running.

    Args:
        pid: The process to ask about.

    Returns:
        True if it exists.

    Note:
        os.kill(pid, 0) is the POSIX idiom and is NOT portable — on Windows,
        os.kill ignores the signal and terminates the process outright, so
        asking "are you alive" there would kill the thing it asked about. The
        Windows branch opens a read-only handle instead.

        THE ZOMBIE, found by running this for real on 2026-08-19. A process
        that has exited but not been reaped still has a pid entry, so
        os.kill(pid, 0) says yes to a corpse. The first live start/stop proved
        it: the server logged "Finished server process", and stop() waited the
        full ten seconds and then reported that it would not go.

        It only bites when the caller is the server's own PARENT — in a
        separate `drone @api host-api stop`, init has already reaped it — which
        is exactly the shape that is hardest to notice and easiest to ship. The
        non-blocking reap costs nothing and answers correctly either way:
        ChildProcessError means not ours and nothing to reap.
    """
    if pid <= 0:
        return False

    if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
        import ctypes

        query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(query_limited_information, False, pid)

        if not handle:
            return False

        ctypes.windll.kernel32.CloseHandle(handle)
        return True

    try:
        # Reap it if it is ours and already gone, so the check below sees an
        # absence rather than a zombie.
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError) as e:
        # Not ours to reap, or already reaped. Neither is a problem — the kill
        # check below is what actually answers — but a reap that fails for a
        # THIRD reason would otherwise be invisible.
        logger.debug("[host_api] nothing to reap for pid %s: %s", pid, e)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        logger.debug("[host_api] pid %s is gone", pid)
        return False
    except PermissionError:
        # It exists and belongs to somebody else. Alive is still the answer —
        # and worth saying, because a server this process cannot signal is a
        # server `stop` is about to fail on.
        logger.warning("[host_api] pid %s is running but not ours to signal", pid)
        return True

    return True


def running() -> Optional[Dict[str, Any]]:
    """
    The live server's record, whoever started it.

    Returns:
        The record with an `owner` naming who holds it, or None when there is
        no server — including when a record exists but names a process that has
        gone. A stale record is treated as no server rather than as an error,
        because a machine that rebooted leaves one behind and that is not a
        fault anybody needs to clear.

    Raises:
        SupervisorUnreachable: There is a systemctl here and it did not answer,
            so whether a unit holds the server is UNKNOWN. Propagated rather
            than flattened to None: on the tailnet host the unit writes no
            record file, so returning None would send every caller down the
            record path and report "no server is running" about a server that
            is answering requests. Each of the three callers wants to refuse
            here — status must say it cannot tell, stop must not signal into the
            dark, and serve must not start a second listener on a port it
            cannot see.

    Note:
        THE SUPERVISOR IS ASKED FIRST, because when a unit is running it IS the
        server and the record file is at best a leftover from before the reboot.
        Reading the file first would answer with a dead pid while a healthy
        server listened on the same port.

        This is the whole of requirement four. Before today a unit-managed
        server reported as "no detached server is running" — the command an
        operator runs at exactly the moment they need it to be true, telling
        them the opposite of the truth.
    """
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
        logger.warning("[host_api] the serve record could not be read (%s): %s", record_file, e)
        return None

    if not isinstance(record, dict) or not _alive(int(record.get("pid") or 0)):
        return None

    record["owner"] = OWNER_DETACHED
    return record


def serve_detached(host: Optional[str] = None, port: Optional[int] = None) -> Dict[str, Any]:
    """
    Start the server in its own session, with its output in a file.

    Args:
        host: Bind address override. Defaults to the stored config.
        port: Port override. Defaults to the stored config.

    Returns:
        The record — pid, bind address, log path, started time.

    Raises:
        BindRefused: The address was refused. NOTHING is spawned.
        LifetimeError: A server is already running, or the child died on start.
        SupervisorUnreachable: Whether a unit holds the server is unknown, so
            nothing is spawned — a second listener started blind is how you get
            two servers fighting over one port and a log that cannot say which
            one wrote a line.

    Note:
        THE BIND IS VALIDATED IN THIS PROCESS, BEFORE ANY SPAWN. D1 says a
        refused address must never reach a listener, and a refusal that happens
        inside a detached child is a refusal the operator reads about later in a
        log file, if at all. Validating here means the command that was told no
        is the command that says no.
    """
    from aipass.api.apps.handlers.host import config as host_config

    existing = running()

    if existing is not None:
        # Naming the OWNER, because the two cases need different commands from
        # the operator and "already running" alone sends them to the wrong one:
        # a supervised server signalled by hand comes straight back.
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

    host_config.validate_bind(bind_host, bind_port)

    command = serve_argv(bind_host, bind_port)

    # Append, never truncate: a new server joining the same file is exactly the
    # continuity the restart churn destroyed.
    with open(log_path(), "a", encoding="utf-8") as stream:
        child = subprocess.Popen(
            command,
            stdout=stream,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=str(_branch_root()),
            # The whole mechanism: the child leaves the process group drone is
            # timing and loses the terminal, so neither a timeout nor a closed
            # pane reaches it. Spelled differently per platform — see above.
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
    """
    Stop the running server, through whoever owns it.

    Returns:
        The record of the server that was stopped, or None if none was running.

    Raises:
        LifetimeError: The server was asked to stop and was still there when the
            wait ran out. Said rather than escalated — SIGKILL would cut short a
            graceful shutdown, and this handler does not get to decide that a
            server taking its time is a server that has hung.

    Note:
        A SUPERVISED SERVER IS STOPPED THROUGH ITS SUPERVISOR, never by pid.
        Requirement five, and it is not a formality: signalling the process
        directly leaves the restart policy free to start it again, so `stop`
        would print success and the server would be back before the operator
        finished reading it. `systemctl stop` outranks Restart= by definition —
        the unit stays down until somebody starts it.
    """
    record = running()

    if record is None:
        # A record naming a dead process is not an error to report; clear it so
        # the next serve is not refused by a ghost.
        record_path().unlink(missing_ok=True)
        return None

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

    raise LifetimeError(
        f"The server (pid {pid}) did not exit within {STOP_TIMEOUT_SECONDS}s. "
        f"It may still be shutting down — check again, or end it yourself."
    )


def _stop_supervised(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ask the supervisor to bring its unit down, and confirm that it did.

    Args:
        record: The running server's record, owned by the supervisor.

    Returns:
        The same record, once the process is actually gone.

    Raises:
        LifetimeError: The supervisor refused the stop, or the process was
            still there afterwards.

    Note:
        THE PID IS RE-CHECKED AFTER systemctl RETURNS rather than trusted. A
        supervisor that accepted the request and a process that has exited are
        two facts, and this branch has already been caught once believing the
        first implies the second — os.kill(pid, 0) answering yes to an unreaped
        corpse, found by running the thing for real.
    """
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

    # The SUPERVISOR'S budget, not this module's ten seconds. systemd gives the
    # server TimeoutStopSec to shut down gracefully; waiting less than that here
    # would report a failure while the supervisor was still doing exactly what
    # it was told to, and the operator would go looking for a hang that is a
    # graceful shutdown halfway through.
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
    """
    Render the unit and gather everything an install needs to be safe.

    Args:
        host: Bind address override. Defaults to the stored config.
        port: Bind port override. Defaults to the stored config.

    Returns:
        The supervisor's own report plus `conflict` — the hand-started server
        currently holding the port, or None.

    Raises:
        BindRefused: The address was refused. NOTHING is written.
        AutostartUnsupported: There is no user-level systemd here.

    Note:
        The conflict check is a COURTESY and cannot retract a unit that was
        already written, so an unreachable supervisor is caught here rather than
        propagated: by this line the file exists, and failing the command after
        a successful write would leave the operator with a rendered unit and an
        error telling them it did not happen.
    """
    unit = write_unit(host, port)
    report = autostart.installation_report(unit)

    try:
        current = running()
    except autostart.SupervisorUnreachable as e:
        logger.warning("[host_api] the port-conflict check could not reach the supervisor: %s", e)
        current = None

    report["conflict"] = current if (current or {}).get("owner") == OWNER_DETACHED else None
    return report


def server_state() -> Dict[str, Any]:
    """
    The status lane's answer, including the one running() cannot return.

    Returns:
        A dict with `state` — "running", "none" or "unknown" — and `record` for
        the running case.

    Note:
        running() RAISES when the supervisor cannot be asked, which is right for
        stop and serve: both must refuse rather than act blind. Status is the
        one caller whose whole job is to report a state, and "I cannot tell" IS
        a state — so it is data here rather than an exception, and the module
        above renders three cases without branching on an exception type.
    """
    try:
        record = running()
    except autostart.SupervisorUnreachable as e:
        logger.warning("[host_api] status could not reach the supervisor: %s", e)
        return {"state": "unknown", "record": None, "reason": str(e)}

    if record is None:
        return {"state": "none", "record": None, "reason": ""}

    return {"state": "running", "record": record, "reason": ""}
