# =================== AIPass ====================
# Name: executor.py
# Description: Safe subprocess execution for branch command routing
# Version: 1.1.2
# Created: 2026-03-09
# Modified: 2026-10-17
# =============================================

"""
Safe subprocess execution for branch command routing.
"""

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import IO, Any, List, cast

from .exceptions import CommandExecutionError
from aipass.drone.apps.handlers.json import json_handler
from aipass.prax import logger


# A HANG GUARD sized for the worst legitimate case, not a per-verb budget: one
# verb (`email @seedgo` vs `email @all`) has very different worst cases.
DEFAULT_TIMEOUT = 600

# A child still talking at its deadline buys another IDLE_GRACE, up to MAX_TIMEOUT.
IDLE_GRACE = 120

# Hard ceiling: a process that chatters forever is what the guard exists to kill.
MAX_TIMEOUT = 1800

# Kept empty on purpose: a policy value wins even when LOWER than the default,
# so a "raise" entry against a 600s base becomes a cap on a slow command.
TIMEOUT_OVERRIDES: dict[str, dict[str, int]] = {}

_POLL_INTERVAL = 0.1

_TERMINATE_GRACE = 1.0

# Short on the kill path: report what we have, do not wait on a dying child.
_READER_JOIN_ON_EXIT = 5.0
_READER_JOIN_ON_KILL = 2.0

_READ_CHUNK = 65536

# Replayed tail-first; truncation is always announced, never silent.
_PARTIAL_REPLAY_CHARS = 4000


def resolve_timeout(branch: str, command: str | None, explicit: int | None = None) -> int:
    """Resolve subprocess timeout for a branch command.

    Order, not magnitude: a policy value wins even when LOWER than the default; no max() here.
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


def _poll_pause(seconds: float) -> None:
    """The hang guard's pause between polls: the one place the wait loop yields."""
    time.sleep(seconds)


def _spawn(full_cmd: List[str], **kwargs: Any) -> "subprocess.Popen[bytes]":
    """Start the captured child: subprocess.Popen with the caller's arguments, nothing else.

    A test seam: patching subprocess.Popen instead replaces it for the whole process.
    """
    # cast: no text/encoding flag is passed, so the pipes are bytes.
    return cast("subprocess.Popen[bytes]", subprocess.Popen(full_cmd, **kwargs))


def _run_interactive(full_cmd: List[str], **kwargs: Any) -> "subprocess.CompletedProcess[bytes]":
    """Run the interactive child: subprocess.run with the caller's arguments, nothing else."""
    return subprocess.run(full_cmd, **kwargs)


def _stop_process(proc: "subprocess.Popen[bytes]") -> None:
    """Ask the child to stop, insist if it does not, and reap it either way."""
    try:
        proc.terminate()
    except OSError as exc:
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
        # WARNING, not debug: an unreaped child is a zombie, invisible unless said here.
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

    One thread per pipe (else the classic Popen deadlock); a timeout's TimeoutExpired carries the partial output.
    """
    start = time.monotonic()
    lock = threading.Lock()
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []

    # saw_output, not the timestamp alone: with a base shorter than IDLE_GRACE a
    # silent child would otherwise look "recent" and buy an extension.
    last_output_at = start
    saw_output = False

    def drain(stream: IO[bytes], sink: list[bytes]) -> None:
        """Read one pipe to EOF into *sink*, stamping the arrival of each chunk."""
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
    # No max(MAX_TIMEOUT, timeout): a base above the ceiling is honoured, `deadline` only grows.
    hard_deadline = start + MAX_TIMEOUT
    timed_out = False

    try:
        while True:
            if proc.poll() is not None:
                break
            now = time.monotonic()
            if now < deadline:
                _poll_pause(min(_POLL_INTERVAL, deadline - now))
                continue
            with lock:
                quiet_for = now - last_output_at
                spoke = saw_output
            if extend_on_output and spoke and quiet_for < IDLE_GRACE and deadline < hard_deadline:
                deadline = min(deadline + IDLE_GRACE, hard_deadline)
                continue
            timed_out = True
            break
    except KeyboardInterrupt:
        # The child is ours: leaving it running would orphan it.
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

    *interactive* inherits stdio (no capture, no timeout); *extend_on_output* is False for an explicit timeout.
    """
    full_cmd = [executable] + list(args)

    run_env = None
    if env:
        run_env = os.environ.copy()
        run_env.update(env)

    if interactive:
        try:
            result = _run_interactive(
                full_cmd,
                cwd=cwd,
                shell=False,
                env=run_env,
            )
        except KeyboardInterrupt:
            # The child shares this terminal and got the same SIGINT: report 130, do not raise.
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
        # bufsize=0: output ARRIVAL time buys an extension; buffering would hide a trickle.
        proc = _spawn(
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
