# =================== AIPass ====================
# Name: command_job.py
# Description: Command jobs - a scheduled drone command run as a subprocess, no wake
# Version: 1.1.0
# Created: 2026-09-11
# Modified: 2026-10-25
# =============================================

"""Command jobs (DPLAN-0338): a schedule job that runs a drone command instead of waking an agent.

Reference: docs/command_jobs.md
Every subprocess here (command and notify mail) goes through LAUNCHER; tests/conftest.py seals it.
"""

import os
import shlex
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import List, Optional

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler

COMMAND_EXECUTABLE = "drone"

#: The job's own first token is replaced by this, never run as written.
LAUNCHER = (COMMAND_EXECUTABLE,)

#: Matches drone's own executor default, so a command job is never cut shorter than drone would cut it.
DEFAULT_TIMEOUT_SECONDS = 600

MAIL_TIMEOUT_SECONDS = 60

#: The cap sits under runstate's 500-char last_error slice, so the whole detail fits in the row.
TAIL_LINES = 5
TAIL_MAX_CHARS = 400

#: Between SIGTERM to the group and SIGKILL to whatever ignored it.
_STOP_GRACE_SECONDS = 2.0
_STOP_POLL_SECONDS = 0.05

_POSIX = os.name == "posix"


@dataclass
class CommandResult:
    """How one subprocess ended. ``exit_code`` is None when it never finished on its own."""

    exit_code: Optional[int]
    duration: float
    tail: str
    timed_out: bool = False
    error: str = ""
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ok_exit_codes: tuple = ()

    @property
    def ok(self) -> bool:
        """Exit 0 or one the job lists, inside the timeout, started at all. Anything else is a failure."""
        passed = self.exit_code == 0 or self.exit_code in self.ok_exit_codes
        return passed and not self.timed_out and not self.error


def command_argv(command) -> List[str]:
    """Split a job's command the way it will run, or raise ValueError naming why it cannot.

    Shared by discovery's validation and the fire path, so an accepted command is exactly the argv run.
    """
    if not isinstance(command, str) or not command.strip():
        raise ValueError(f"command must be a non-empty string, got {command!r}")
    try:
        argv = shlex.split(command)
    except ValueError as e:
        raise ValueError(f"command does not parse ({e}): {command!r}") from e
    if argv[0] != COMMAND_EXECUTABLE:
        raise ValueError(f"the first token must be '{COMMAND_EXECUTABLE}', got '{argv[0]}'")
    return argv


def timeout_for(job: dict):
    """The job's timeout in seconds: its own ``timeout_seconds``, else the default."""
    return job.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)


def ok_exit_codes_for(job: dict) -> tuple:
    """The non-zero exit codes the job's owner counts as a pass, from ``ok_exit_codes``."""
    return tuple(job.get("ok_exit_codes", ()))


def notify_email(job: dict) -> str:
    """The citizen address ``notify.email`` names, or '' when the job asks for no mail."""
    notify = job.get("notify")
    if isinstance(notify, dict):
        return notify.get("email") or ""
    return ""


def command_job_problem(job: dict) -> str:
    """'' when a command job is well-formed, else the reason discovery must refuse it."""
    try:
        command_argv(job.get("command"))
    except ValueError as e:
        return str(e)

    if job.get("schedule", {}).get("type") == "rotation":
        return "a rotation job wakes tonight's citizen on the roster; a command wakes nobody, so the two cannot mix"

    timeout = timeout_for(job)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        return f"timeout_seconds must be a positive whole number of seconds, got {timeout!r}"

    codes = job.get("ok_exit_codes", [])
    if not isinstance(codes, list) or not all(
        isinstance(code, int) and not isinstance(code, bool) and 1 <= code <= 255 for code in codes
    ):
        return f"ok_exit_codes must be a list of exit codes from 1 to 255, got {codes!r}"

    notify = job.get("notify")
    if notify is not None and not isinstance(notify, (bool, dict)):
        return f'notify must be true, false or a block like {{"email": "@devpulse"}}, got {notify!r}'
    if isinstance(notify, dict) and "email" in notify:
        email = notify["email"]
        if not isinstance(email, str) or not email.startswith("@") or len(email) < 2:
            return f"notify.email must be a citizen address like '@devpulse', got {email!r}"
    return ""


def output_tail(text: str, lines: int = TAIL_LINES, max_chars: int = TAIL_MAX_CHARS) -> str:
    """The last few non-blank lines of some output, capped from the FRONT so the ending survives."""
    kept = [line.rstrip() for line in text.splitlines() if line.strip()][-lines:]
    tail = "\n".join(kept)
    if len(tail) > max_chars:
        tail = "..." + tail[-(max_chars - 3) :]
    return tail


def signal_group(pid: int, sig) -> None:
    """Signal a whole process group. A group that is already gone is the answer we wanted."""
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        logger.info("[command_job] process group %s already gone before signal %s", pid, sig)
    except PermissionError as e:
        logger.warning("[command_job] could not signal process group %s: %s", pid, e)


def _leader_exited(pid: int) -> bool:
    """True once the group leader has exited, WITHOUT reaping it. Raises ChildProcessError once reaped."""
    if hasattr(os, "waitid"):
        return os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    return False


def _await_leader_unreaped(pid: int) -> None:
    """Give the leader the grace to exit on SIGTERM, polling so it stays an unreaped zombie."""
    deadline = time.monotonic() + _STOP_GRACE_SECONDS
    while not _leader_exited(pid):
        if time.monotonic() >= deadline:
            logger.info("[command_job] pid %s ignored SIGTERM, killing its group", pid)
            return
        time.sleep(_STOP_POLL_SECONDS)


def _stop_tree(proc: "subprocess.Popen[bytes]") -> None:
    """Stop an overrunning command and everything it started, then reap it."""
    if _POSIX:
        signal_group(proc.pid, signal.SIGTERM)
        # The pgid is ours only while the leader is unreaped: a reaped pid can be reissued to a stranger.
        try:
            _await_leader_unreaped(proc.pid)
        except ChildProcessError:
            logger.warning("[command_job] pid %s was reaped before SIGKILL; its pgid is not ours to signal", proc.pid)
        else:
            # Unconditional: a grandchild may have ignored TERM, and the group outlives its leader.
            signal_group(proc.pid, signal.SIGKILL)
    else:
        proc.kill()
    try:
        proc.wait(timeout=_STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        logger.warning("[command_job] pid %s not reaped after kill; it may remain a zombie", proc.pid)


def _execute(argv: List[str], cwd, timeout_seconds) -> CommandResult:
    """Run one argv to completion or timeout. Never raises; every failure is named in the result."""
    start = time.monotonic()
    with tempfile.TemporaryFile() as out:
        try:
            proc = subprocess.Popen(
                argv,
                cwd=str(cwd),
                shell=False,
                stdin=subprocess.DEVNULL,  # a scheduled command has no human to answer a prompt
                stdout=out,
                stderr=subprocess.STDOUT,  # one stream, so the tail reads in the order it was written
                start_new_session=_POSIX,
            )
        except OSError as e:
            logger.warning("[command_job] could not start %s in %s: %s", argv[:3], cwd, e)
            elapsed = time.monotonic() - start
            return CommandResult(None, elapsed, "", error=f"could not start: {e}", timeout_seconds=timeout_seconds)

        timed_out = False
        try:
            exit_code: Optional[int] = proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            logger.warning("[command_job] pid %s overran %ss, stopping its process tree", proc.pid, timeout_seconds)
            _stop_tree(proc)
            exit_code, timed_out = None, True

        out.seek(0)
        text = out.read().decode("utf-8", errors="replace")

    elapsed = time.monotonic() - start
    return CommandResult(exit_code, elapsed, output_tail(text), timed_out=timed_out, timeout_seconds=timeout_seconds)


def run_command(command: str, cwd, timeout_seconds=DEFAULT_TIMEOUT_SECONDS, ok_exit_codes=()) -> CommandResult:
    """Run a command job's drone command in ``cwd`` and say how it ended. Never raises.

    ``cwd`` is required: falling back to the tick's own cwd would sign the work as the project.
    """
    try:
        argv = command_argv(command)
    except ValueError as e:
        return CommandResult(None, 0.0, "", error=f"refused: {e}", timeout_seconds=timeout_seconds)
    if not cwd:
        return CommandResult(
            None, 0.0, "", error="refused: no branch directory for the owner", timeout_seconds=timeout_seconds
        )

    result = _execute(list(LAUNCHER) + argv[1:], cwd, timeout_seconds)
    result.ok_exit_codes = tuple(ok_exit_codes)
    json_handler.log_operation("command_job_run", {"exit_code": result.exit_code, "timed_out": result.timed_out})
    return result


def verdict_text(result: CommandResult) -> str:
    """How it ended and how long it took, e.g. ``exit 0, 0.4s``."""
    if result.error:
        head = result.error
    elif result.timed_out:
        head = f"timed out after {result.timeout_seconds}s, process tree stopped"
    else:
        head = f"exit {result.exit_code}"
    return f"{head}, {result.duration:.1f}s"


def done_text(result: CommandResult) -> str:
    """One line for the DONE log line and the runstate detail: the verdict, then the output tail."""
    tail = result.tail.replace("\n", " | ")
    return f"{verdict_text(result)} — {tail or 'no output'}"


def start_mail(job: dict) -> tuple:
    """(subject, body) for the mail sent as a command job starts."""
    subject = f"Command job started: {job['owner']}/{job['id']}"
    body = (
        f"Command job started by the daemon scheduler.\n"
        f"Owner: {job['owner']}\nJob: {job['id']}\nCommand: {job['command']}\n"
        f"Timeout: {timeout_for(job)}s\n"
        f"It runs as a subprocess in the owner's branch. No agent is woken."
    )
    return subject, body


def finish_mail(job: dict, result: CommandResult) -> tuple:
    """(subject, body) for the mail sent as a command job finishes, pass or fail."""
    verdict = "passed" if result.ok else "FAILED"
    subject = f"Command job {verdict}: {job['owner']}/{job['id']} ({verdict_text(result)})"
    exit_code = "none" if result.exit_code is None else result.exit_code
    body = (
        f"Command job {verdict}: {verdict_text(result)}.\n"
        f"Owner: {job['owner']}\nJob: {job['id']}\nCommand: {job['command']}\n"
        f"Exit code: {exit_code}\n"
        f"Duration: {result.duration:.1f}s\n"
        f"Output tail:\n{result.tail or '(no output)'}"
    )
    return subject, body


def send_mail(to: str, subject: str, body: str, sender_dir) -> str:
    """Send one ai_mail email (never a wake) through drone, signed by ``sender_dir``'s citizen.

    Returns '' when it went, else the reason; fail-soft so the mail never changes the fire's answer.
    """
    argv = list(LAUNCHER) + ["@ai_mail", "email", to, subject, body]
    result = _execute(argv, sender_dir, MAIL_TIMEOUT_SECONDS)
    json_handler.log_operation("command_job_mail", {"to": to, "sent": result.ok})
    if result.ok:
        return ""
    return done_text(result)
