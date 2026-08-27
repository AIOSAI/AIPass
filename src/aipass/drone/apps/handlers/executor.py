# =================== AIPass ====================
# Name: executor.py
# Description: Safe subprocess execution for branch command routing
# Version: 1.1.0
# Created: 2026-03-09
# Modified: 2026-08-27
# =============================================

"""
Safe subprocess execution for branch command routing.

Wraps subprocess with safety guards: a hang guard sized for the worst
legitimate case, no shell injection, captured output that survives a kill, and
consistent error wrapping via CommandExecutionError.
"""

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import IO, List

from .exceptions import CommandExecutionError
from aipass.drone.apps.handlers.json import json_handler
from aipass.prax import logger


# Raised 30 -> 60 on 2026-08-13 (Patrick's ruling). Two known runners finish
# around 31s and were tripping the old default. The evening before showed
# fleet-wide what a quiet default costs: a 30s UserPromptSubmit timeout
# discarded a hooks context for weeks because the real work legitimately took
# longer (DPLAN-0285). A default that kills work at N when work takes N+1 fails
# silently, which is the expensive way to fail.
#
# Raised 60 -> 600 on 2026-08-27 (Patrick's ruling: "it is configured wrong —
# it should not be timing out before it completes; processing time is fine,
# increase the allowed timeout so things can actually complete"). Two live
# kills in one morning made the same point twice:
#   1. the fleet-wide trinity push died at 60s mid-alphabet; re-fired with
#      --drone-timeout 900 it completed in about five minutes;
#   2. an @all mail broadcast to 18 recipients was killed at 60s AFTER every
#      message had already been delivered — and the caller was told only
#      "Command timed out", because the child's captured output was discarded
#      with the exception.
#
# THE DESIGN POSITION, so the next raise argues with the right thing: this is a
# HANG GUARD sized for the worst legitimate case, NOT a per-verb performance
# budget. Per-verb integers were considered and rejected — they cannot tell
# `email @seedgo` from `email @all`, which is one command with two very
# different worst cases. Legitimate work completes; hung work still dies.
DEFAULT_TIMEOUT = 600

# The extension quantum, and the window that counts as "recent output". A child
# still talking when its deadline arrives buys another IDLE_GRACE, repeatedly,
# up to MAX_TIMEOUT. Silence never SHORTENS anything: a long SILENT computation
# still gets its full base, so this adds no false-kill mode that a flat base
# did not already have.
IDLE_GRACE = 120

# The hard ceiling. Extension can never pass it — a process that chatters
# forever is exactly what the guard exists to kill.
MAX_TIMEOUT = 1800

# Kept as a MECHANISM, deliberately empty as DATA.
#
# It held three entries — memory process-plans 120, memory rollover 100, flow
# close 90 — every one of them written to RAISE above the old 60s default.
# Against a 600s base the same numbers invert into CAPS: the three commands we
# know are slow would get the LEAST time in the fleet, which is the failure
# this ruling exists to end. The rule that put them here ("a policy value is a
# decision, not a floor" — it wins even when lower than the default) is still
# the rule, and resolve_timeout still honours it. Only the now-harmful data is
# gone.
TIMEOUT_OVERRIDES: dict[str, dict[str, int]] = {}

# How often the wait loop checks for exit. Small enough that a fast command is
# not held at the door, large enough not to spin a core.
_POLL_INTERVAL = 0.1

# Between terminate() and kill(), and again before we stop waiting to reap.
_TERMINATE_GRACE = 1.0

# Reader threads are joined so buffered output is not lost. Longer on a clean
# exit (there is at most a pipe buffer left to drain); short on the kill path,
# where the point is to report what we have, not to wait on a dying child.
_READER_JOIN_ON_EXIT = 5.0
_READER_JOIN_ON_KILL = 2.0

_READ_CHUNK = 65536

# Partial output is replayed tail-first: the newest lines say where the work
# got to. Truncation is ALWAYS announced — a silent trim is the same species
# of lie as a silent kill.
_PARTIAL_REPLAY_CHARS = 4000


def resolve_timeout(branch: str, command: str | None, explicit: int | None = None) -> int:
    """Resolve subprocess timeout for a branch command.

    Priority: explicit flag > per-command policy > DEFAULT_TIMEOUT.

    Order, not magnitude: a policy value wins even when it is LOWER than the
    default. There is deliberately no max() here.
    """
    if explicit is not None:
        return explicit
    branch_key = branch.lstrip("@").lower()
    if command and branch_key in TIMEOUT_OVERRIDES:
        cmd_timeout = TIMEOUT_OVERRIDES[branch_key].get(command)
        if cmd_timeout is not None:
            return cmd_timeout
    return DEFAULT_TIMEOUT


@dataclass
class CommandResult:
    """Result of a routed command execution."""

    stdout: str
    stderr: str
    exit_code: int
    branch: str
    command: str


def _stop_process(proc: "subprocess.Popen[bytes]") -> None:
    """Ask the child to stop, insist if it does not, and reap it either way.

    terminate() first so a child with a signal handler can flush; kill() only
    when it will not go. The final wait() is the reaping — an unreaped child is
    a zombie held by this process for as long as it lives.
    """
    try:
        proc.terminate()
    except OSError as exc:
        # Already gone (it exited in the race between the poll and here), or
        # never ours to signal. Either way there is nothing left to stop.
        logger.debug("Hang guard: terminate on pid %s failed, treating as already exited: %s", proc.pid, exc)
        return
    try:
        proc.wait(timeout=_TERMINATE_GRACE)
        return
    except subprocess.TimeoutExpired:
        logger.debug("Hang guard: pid %s ignored SIGTERM within %.1fs, escalating to kill", proc.pid, _TERMINATE_GRACE)
    try:
        proc.kill()
    except OSError as exc:
        logger.debug("Hang guard: kill on pid %s failed, treating as already exited: %s", proc.pid, exc)
    try:
        proc.wait(timeout=_TERMINATE_GRACE)
    except subprocess.TimeoutExpired:
        # WARNING, not debug: this is the one branch that leaves something
        # behind. A child that has not been reaped after SIGKILL is a zombie
        # held for the lifetime of this process, and it is invisible unless
        # said here.
        logger.warning("Hang guard: pid %s not reaped after kill — it may remain a zombie", proc.pid)


def _format_partial(label: str, raw: bytes) -> str:
    """Render one captured stream for replay in a timeout error."""
    text = raw.decode("utf-8", errors="replace")
    if not text:
        return f"--- partial {label} ({len(raw)} bytes) --- (nothing was produced)"
    if len(text) > _PARTIAL_REPLAY_CHARS:
        header = (
            f"--- partial {label} ({len(raw)} bytes, TRUNCATED — "
            f"showing the last {_PARTIAL_REPLAY_CHARS} characters) ---"
        )
        body = text[-_PARTIAL_REPLAY_CHARS:]
    else:
        header = f"--- partial {label} ({len(raw)} bytes) ---"
        body = text
    return f"{header}\n{body}"


def _capture_with_hang_guard(
    proc: "subprocess.Popen[bytes]",
    full_cmd: List[str],
    timeout: int,
    extend_on_output: bool,
) -> tuple[bytes, bytes]:
    """Drain both pipes concurrently and enforce the hang guard.

    Each pipe is drained in its own daemon thread. Reading one to EOF while the
    other fills is the classic Popen deadlock: the child blocks writing to a
    full pipe, we block reading the pipe it has stopped writing to, and neither
    side ever moves again.

    Returns the captured (stdout, stderr) bytes. Raises CommandExecutionError
    if the child outlives its deadline, chaining a TimeoutExpired that CARRIES
    the partial output rather than discarding it.
    """
    start = time.monotonic()
    lock = threading.Lock()
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []

    # Initialised to the start, not to 0: nothing has been measured yet, and a
    # fabricated epoch of silence is still a fabrication.
    #
    # `saw_output` is what actually makes "no output, no extension" true. A
    # timestamp alone cannot: with a base SHORTER than IDLE_GRACE (every test
    # here, and any tight --drone-timeout), silence-since-start is itself
    # inside the recent-output window, so a child that never said a word would
    # buy an extension on the strength of never having spoken. Output extends
    # life; the absence of output is not output.
    last_output_at = start
    saw_output = False

    def drain(stream: IO[bytes], sink: list[bytes]) -> None:
        """Read one pipe to EOF into *sink*, stamping the arrival of each chunk.

        Runs in its own thread. The stamp is what output-extends-life reads;
        nothing here decides the deadline.
        """
        nonlocal last_output_at, saw_output
        try:
            while True:
                chunk = stream.read(_READ_CHUNK)
                if not chunk:
                    break
                with lock:
                    sink.append(chunk)
                    last_output_at = time.monotonic()
                    saw_output = True
        except (OSError, ValueError) as exc:
            # The pipe was closed under us on the kill path. What was already
            # collected is still evidence and is still reported.
            logger.debug("Hang guard: reader stopped early, reporting what was captured: %s", exc)
        finally:
            try:
                stream.close()
            except OSError as exc:
                logger.debug("Hang guard: closing a drained pipe failed: %s", exc)

    readers: list[threading.Thread] = []
    for stream, sink in ((proc.stdout, stdout_chunks), (proc.stderr, stderr_chunks)):
        if stream is None:
            continue
        reader = threading.Thread(target=drain, args=(stream, sink), daemon=True)
        reader.start()
        readers.append(reader)

    deadline = start + timeout
    # Two guards were tried here and both proved to be the same rule written
    # twice — mutations of each survived, which is what an equivalent mutant
    # means. Neither `if extend_on_output` (the flag already gates the only
    # read, below) nor `max(MAX_TIMEOUT, timeout)` (a base ABOVE the ceiling is
    # already honoured in full: `deadline` starts at start+timeout and only
    # ever moves outward, so the comparison below is false from the first
    # check and nothing is ever cut short) changes any outcome.
    hard_deadline = start + MAX_TIMEOUT
    timed_out = False

    try:
        while True:
            if proc.poll() is not None:
                break
            now = time.monotonic()
            if now < deadline:
                time.sleep(min(_POLL_INTERVAL, deadline - now))
                continue
            with lock:
                quiet_for = now - last_output_at
                spoke = saw_output
            if extend_on_output and spoke and quiet_for < IDLE_GRACE and deadline < hard_deadline:
                # Still talking at the deadline: this is work, not a hang.
                deadline = min(deadline + IDLE_GRACE, hard_deadline)
                continue
            timed_out = True
            break
    except KeyboardInterrupt:
        # Ctrl+C belongs to the operator, but the child is ours — leaving it
        # running would orphan it to nobody's terminal.
        _stop_process(proc)
        for reader in readers:
            reader.join(timeout=_READER_JOIN_ON_KILL)
        raise

    if timed_out:
        elapsed = time.monotonic() - start
        effective_limit = deadline - start
        _stop_process(proc)
        for reader in readers:
            reader.join(timeout=_READER_JOIN_ON_KILL)
        with lock:
            partial_out = b"".join(stdout_chunks)
            partial_err = b"".join(stderr_chunks)
        message = (
            f"Command timed out after {elapsed:.1f}s (limit {effective_limit:.0f}s): {' '.join(full_cmd)}\n"
            f"  Override with: drone @<target> <command> --drone-timeout <seconds>\n"
            f"{_format_partial('stdout', partial_out)}\n"
            f"{_format_partial('stderr', partial_err)}"
        )
        raise CommandExecutionError(message) from subprocess.TimeoutExpired(
            cmd=full_cmd,
            timeout=effective_limit,
            output=partial_out,
            stderr=partial_err,
        )

    for reader in readers:
        reader.join(timeout=_READER_JOIN_ON_EXIT)
    with lock:
        return b"".join(stdout_chunks), b"".join(stderr_chunks)


def execute_command(
    executable: str,
    args: List[str],
    cwd: str,
    timeout: int = DEFAULT_TIMEOUT,
    env: dict | None = None,
    interactive: bool = False,
    extend_on_output: bool = True,
) -> CommandResult:
    """Execute a command via subprocess with safety guards.

    Never uses shell=True to prevent shell injection attacks.

    Args:
        interactive: If True, inherit stdio (no capture, no timeout).
                     Used for long-running commands like prax monitor.
        extend_on_output: If True (the default), a child still producing output
                     when its deadline arrives is granted another IDLE_GRACE,
                     up to MAX_TIMEOUT. Passed False when an operator named an
                     explicit timeout — their number is their number.
    """
    full_cmd = [executable] + list(args)

    # Merge custom env vars with current environment
    run_env = None
    if env:
        run_env = os.environ.copy()
        run_env.update(env)

    if interactive:
        try:
            # Inherit stdin/stdout/stderr for live interaction
            result = subprocess.run(
                full_cmd,
                cwd=cwd,
                shell=False,
                env=run_env,
            )
        except KeyboardInterrupt:
            # Clean exit on Ctrl+C — no traceback. An interactive child shares
            # this terminal and got the same SIGINT; there is nothing to kill
            # and nothing has failed, so 130 is reported, not raised.
            logger.info("Interactive command interrupted by operator (exit 130): %s", " ".join(full_cmd))
            return CommandResult(stdout="", stderr="", exit_code=130, branch="", command="")
        except FileNotFoundError as e:
            raise CommandExecutionError(f"Executable not found: {executable!r}") from e
        except OSError as e:
            raise CommandExecutionError(f"OS error executing command: {e}") from e
        return CommandResult(
            stdout="",
            stderr="",
            exit_code=result.returncode,
            branch="",
            command="",
        )

    try:
        # bufsize=0 so each read returns whatever is available NOW: the ARRIVAL
        # TIME of output is what buys an extension, and a buffered reader would
        # hold a trickling child's output back until a block filled.
        proc = subprocess.Popen(
            full_cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            shell=False,
            env=run_env,
        )
    except FileNotFoundError as e:
        raise CommandExecutionError(f"Executable not found: {executable!r}") from e
    except OSError as e:
        raise CommandExecutionError(f"OS error executing command: {e}") from e

    stdout_bytes, stderr_bytes = _capture_with_hang_guard(proc, full_cmd, timeout, extend_on_output)

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    exit_code = proc.returncode if proc.returncode is not None else -1

    json_handler.log_operation("execute_command", {"command": str(full_cmd), "exit_code": exit_code})

    return CommandResult(
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        branch="",
        command="",
    )
