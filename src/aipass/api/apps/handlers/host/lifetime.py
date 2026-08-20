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

Functions:
    serve_detached()  - Start the server in its own session, return its facts
    running()         - The live server's record, or None
    stop()            - Ask the recorded server to exit
    log_path()        - Where a detached server's output goes
    record_path()     - Where its facts are kept
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

# logs/ is gitignored and is already where this branch's runtime output lives,
# so a detached server's stdout and its pid record sit beside the prax logs
# rather than inventing a second runtime directory nobody looks in.
RUNTIME_DIRNAME = "logs"
LOG_NAME = "host_api_serve.log"
RECORD_NAME = "host_api_serve.json"

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
    The detached server's record, if one is actually running.

    Returns:
        The record, or None when there is no server — including when a record
        exists but names a process that has gone. A stale record is treated as
        no server rather than as an error, because a machine that rebooted
        leaves one behind and that is not a fault anybody needs to clear.
    """
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
        raise LifetimeError(
            f"A host-api server is already running (pid {existing.get('pid')}, "
            f"{existing.get('host')}:{existing.get('port')}). Stop it first: drone @api host-api stop"
        )

    config = host_config.load_config()
    bind_host = host if host is not None else config["host"]
    bind_port = int(port if port is not None else config["port"])

    host_config.validate_bind(bind_host, bind_port)

    entry = _branch_root() / "apps" / "api.py"
    command = [sys.executable, str(entry), "host-api", "serve", "--host", bind_host, "--port", str(bind_port)]

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
    Ask the recorded server to exit.

    Returns:
        The record of the server that was stopped, or None if none was running.

    Raises:
        LifetimeError: The server was asked to stop and was still there when the
            wait ran out. Said rather than escalated — SIGKILL would cut short a
            graceful shutdown, and this handler does not get to decide that a
            server taking its time is a server that has hung.
    """
    record = running()

    if record is None:
        # A record naming a dead process is not an error to report; clear it so
        # the next serve is not refused by a ghost.
        record_path().unlink(missing_ok=True)
        return None

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
