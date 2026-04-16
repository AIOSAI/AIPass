# =================== AIPass ====================
# Name: schedule.py
# Description: Watchdog Schedule Handler — wall-clock + relative wake, optional command
# Version: 1.0.0
# Created: 2026-04-14
# Modified: 2026-04-14
# =============================================

# Time handling: naive local datetimes throughout (matches Python stdlib
# default and the way humans think about "02:00"). Timer handler's
# parse_duration is reused for relative input so "+1h30m" parsing stays
# consistent across watchdog. Sleep is chunked so tests can inject a
# fake clock and jump forward without waiting, and so Phase 4 can
# interrupt an in-flight wake cleanly.

"""
Watchdog Schedule Handler — wake at a wall-clock time or after a relative delay.

Public surface:
  parse_schedule(time_str, now=None)     Parse "02:00" / "14:30:15" / "+30m" / "+1h30m"
  format_wait(target, now)               Render "in 2h 15m" / "overdue by 3m"
  wake_at(time_str, command=None, ...)   Block until target, optionally run command
"""

import re
import subprocess
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.devpulse.apps.handlers.watchdog import registry as _registry
from aipass.devpulse.apps.handlers.watchdog.timer import parse_duration


# Chunk size keeps long sleeps interruptible and makes tests with injected
# clocks fast — each iteration re-checks the clock rather than committing
# to one multi-hour time.sleep call.
_SLEEP_CHUNK_SECONDS = 5.0

_WALL_CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_RELATIVE_PREFIX = "+"


def parse_schedule(time_str: str, now: datetime | None = None) -> datetime:
    """Parse a schedule string into a concrete target ``datetime``.

    Accepts:
      - ``"HH:MM"`` or ``"HH:MM:SS"`` — wall-clock today (rolls to tomorrow
        if the time is already in the past vs ``now``).
      - ``"+<duration>"`` — relative offset parsed via
        :func:`timer.parse_duration` (e.g. ``"+30m"``, ``"+1h30m"``,
        ``"+45s"``).

    Returns a naive local ``datetime``. ``now`` may be injected for
    deterministic tests; defaults to :func:`datetime.now`.

    Raises:
        ValueError: on empty, non-string, or unparseable input.
    """
    if time_str is None or not isinstance(time_str, str):
        raise ValueError(f"schedule must be a string, got {type(time_str).__name__}")
    text = time_str.strip()
    if not text:
        raise ValueError("schedule is empty")

    current = now if now is not None else datetime.now()

    if text.startswith(_RELATIVE_PREFIX):
        rel_body = text[1:].strip()
        if not rel_body:
            raise ValueError(f"relative schedule missing duration: {time_str!r}")
        # parse_duration owns the token grammar and rejects negatives.
        seconds = parse_duration(rel_body)
        return current + timedelta(seconds=seconds)

    match = _WALL_CLOCK_RE.match(text)
    if not match:
        raise ValueError(f"invalid schedule: {time_str!r}")

    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3)) if match.group(3) is not None else 0

    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError(f"invalid wall-clock time: {time_str!r}")

    target = current.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if target <= current:
        target = target + timedelta(days=1)
    return target


def format_wait(target: datetime, now: datetime) -> str:
    """Render the wait between ``now`` and ``target`` as a human string.

    Examples: ``"in 2h 15m"``, ``"in 45s"``, ``"overdue by 3m"``, ``"in 0s"``.
    """
    delta_seconds = int((target - now).total_seconds())
    if delta_seconds == 0:
        return "in 0s"
    overdue = delta_seconds < 0
    total = abs(delta_seconds)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        body = f"{hours}h {minutes}m"
    elif minutes:
        body = f"{minutes}m"
    else:
        body = f"{seconds}s"

    return f"overdue by {body}" if overdue else f"in {body}"


def _run_command(command: str) -> dict:
    """Execute ``command`` via the shell, capturing stdout/stderr/exit code.

    Never raises on non-zero exit — the caller wants the exit code, not an
    exception. FileNotFoundError / OSError are caught and mapped to a
    non-zero synthetic exit code so callers always get a stable shape.
    """
    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "command_exit_code": completed.returncode,
            "command_stdout": completed.stdout,
            "command_stderr": completed.stderr,
        }
    except OSError as exc:
        logger.warning("[watchdog.schedule] command exec failed %r: %s", command, exc)
        return {
            "command_exit_code": -1,
            "command_stdout": "",
            "command_stderr": str(exc),
        }


def wake_at(
    time_str: str,
    command: str | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> dict:
    """Block until ``time_str`` elapses, optionally run ``command`` on wake.

    ``now_fn`` injects a clock for tests — default is :func:`datetime.now`.
    Sleep is chunked (``_SLEEP_CHUNK_SECONDS`` at a time) so tests with
    a fast-forwarding ``now_fn`` return immediately and so Phase 4 can
    cancel an in-flight wake cleanly.

    Returns:
        dict with keys ``woke``, ``reason``, ``elapsed``, ``scheduled_for``,
        ``state``, ``command``, ``command_exit_code``, ``command_stdout``,
        ``command_stderr``. Command fields are ``None`` when no command
        was requested.
    """
    clock = now_fn if now_fn is not None else datetime.now
    start = clock()
    target = parse_schedule(time_str, now=start)
    logger.info(
        "[watchdog.schedule] wake_at time=%s target=%s command=%s",
        time_str,
        target.isoformat(),
        command,
    )

    handle = _registry.register(
        "schedule",
        metadata={
            "scheduled_for": target.isoformat(),
            "command": command,
            "time_str": time_str,
        },
    )

    try:
        while True:
            current = clock()
            remaining = (target - current).total_seconds()
            if remaining <= 0:
                break
            chunk = min(_SLEEP_CHUNK_SECONDS, remaining)
            time.sleep(chunk)

        end = clock()
        elapsed = max(0, int((end - start).total_seconds()))

        command_result: dict = {
            "command_exit_code": None,
            "command_stdout": None,
            "command_stderr": None,
        }
        if command:
            command_result = _run_command(command)

        return {
            "woke": True,
            "reason": "schedule fired",
            "elapsed": elapsed,
            "scheduled_for": target.isoformat(),
            "state": "woke",
            "command": command,
            "command_exit_code": command_result["command_exit_code"],
            "command_stdout": command_result["command_stdout"],
            "command_stderr": command_result["command_stderr"],
            "handle": handle,
        }
    finally:
        _registry.deregister(handle)
