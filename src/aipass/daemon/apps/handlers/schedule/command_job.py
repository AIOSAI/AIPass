# =================== AIPass ====================
# Name: command_job.py
# Description: Command jobs - a scheduled drone command run as a subprocess, no wake
# Version: 1.0.0
# Created: 2026-09-11
# Modified: 2026-09-11
# =============================================

"""Command jobs (DPLAN-0338): a schedule job that runs a drone command instead of waking an agent.

A job carries ``command`` where a wake job carries ``prompt``. The tick runs it as a
subprocess in the owner's branch directory and records the answer exactly like a
wake: no seat, no session, no tokens. Patrick, 2026-09-11: "if it runs there's a
log, if it passed or failed there's a log."

THE RULES, and why each one exists:

- **drone is the first token, always.** The schedule file is per-branch and
  editable by its owner, so whatever it names runs with the tick's authority.
  Holding it to drone verbs keeps drone's own gates (rm's fence, git's refusal,
  the argument gates) as the whole story of what a scheduled command may do.
- **No shell.** ``shlex.split`` then an argv list: no globs, no pipes, no ``;``,
  no expansion — nothing in a JSON string can become a second command.
- **cwd is the owner's branch.** Drone reads cwd as identity, so the command is
  logged as the citizen whose schedule asked for it. Run from the tick's own cwd
  (the repo root) it would be logged as the project, so a job with no branch
  directory is refused rather than run from there.

TWO MEASURED CHOICES the plain ``subprocess.run(capture_output=True)`` form gets
wrong, which is why this runs ``Popen`` itself:

- **Output goes to an anonymous temp file, not a pipe.** A pipe reaches EOF only
  when every holder of its write end closes it. A drone verb that starts anything
  in the background hands that process the pipe, and the read then waits on it —
  a command that exited 0 in a second would be reported as a 600s timeout.
  ``TemporaryFile`` is unlinked at creation, so it leaves no litter either.
- **A timeout stops the whole process tree.** Drone runs every ``@branch`` verb in
  a child of its own (``drone/apps/handlers/executor.py``), so killing drone alone
  orphans exactly the work that overran. On POSIX the command runs in its own
  session and the timeout signals the group. Windows has no group to signal: the
  direct child is killed and a grandchild may outlive it — the known residual.

Every subprocess this module starts — the command AND the notify mail — goes
through :data:`LAUNCHER`, so one seam covers both. The test suite seals it
session-wide (``tests/conftest.py``): no test can reach the real drone.
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

#: The only executable a command job may name.
COMMAND_EXECUTABLE = "drone"

#: The argv prefix that stands for ``drone``. The job's own first token is
#: replaced by this, never run as written. Patched by the test suite's seal.
LAUNCHER = (COMMAND_EXECUTABLE,)

#: Seconds a command may run before its tree is stopped. Matches drone's own
#: executor default, so a command job is never cut shorter than drone would cut it.
DEFAULT_TIMEOUT_SECONDS = 600

#: Seconds the notify mail may take. A mail is one drone call; a minute is generous.
MAIL_TIMEOUT_SECONDS = 60

#: How much of the output survives into the log line, the mail and the runstate
#: row. The end is kept, because that is where a command says how it ended. The
#: character cap sits under runstate's 500-char last_error slice, so the whole
#: detail fits in the row.
TAIL_LINES = 5
TAIL_MAX_CHARS = 400

#: Between SIGTERM to the group and SIGKILL to whatever ignored it.
_STOP_GRACE_SECONDS = 2.0

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

    @property
    def ok(self) -> bool:
        """Exit 0, inside the timeout, started at all. Anything else is a failure."""
        return self.exit_code == 0 and not self.timed_out and not self.error


def command_argv(command) -> List[str]:
    """Split a job's command the way it will run, or raise ValueError naming why it cannot.

    One definition for discovery's validation and the fire path, so a command
    the validator accepted is exactly the argv the tick runs.
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


def _killpg(pid: int, sig) -> None:
    """Signal a whole process group. A group that is already gone is the answer we wanted."""
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        logger.info("[command_job] process group %s already gone before signal %s", pid, sig)
    except PermissionError as e:
        logger.warning("[command_job] could not signal process group %s: %s", pid, e)


def _stop_tree(proc: "subprocess.Popen[bytes]") -> None:
    """Stop an overrunning command and everything it started, then reap it."""
    if _POSIX:
        _killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=_STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            logger.info("[command_job] pid %s ignored SIGTERM, killing its group", proc.pid)
        # Unconditional: the leader exiting on TERM says nothing about a
        # grandchild that ignored it, and the group outlives its leader.
        _killpg(proc.pid, signal.SIGKILL)
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
            # No drone on PATH, a branch directory that is gone: the command never started.
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


def run_command(command: str, cwd, timeout_seconds=DEFAULT_TIMEOUT_SECONDS) -> CommandResult:
    """Run a command job's drone command in ``cwd`` and say how it ended. Never raises.

    ``cwd`` is required: the owner's branch directory is the command's identity,
    and falling back to the tick's own cwd would sign the work as the project.
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

    Returns '' when it went, else the reason it did not. Fail-soft on purpose:
    the mail reports a fire and must never change the fire's answer.
    """
    argv = list(LAUNCHER) + ["@ai_mail", "email", to, subject, body]
    result = _execute(argv, sender_dir, MAIL_TIMEOUT_SECONDS)
    json_handler.log_operation("command_job_mail", {"to": to, "sent": result.ok})
    if result.ok:
        return ""
    return done_text(result)
