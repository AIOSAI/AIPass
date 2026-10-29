# =================== AIPass ====================
# Name: schedule.py
# Description: Watchdog Schedule Handler — wall-clock + relative wake, optional command
# Version: 1.0.2
# Created: 2026-04-14
# Modified: 2026-10-28
# =============================================

# Naive local datetimes throughout: "02:00" means what a human means by it.

"""
Watchdog Schedule Handler — wake at a wall-clock time or after a relative delay.
"""

import re
import shlex
import subprocess
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.devpulse.apps.handlers.watchdog import registry as _registry
from aipass.devpulse.apps.handlers.watchdog.timer import parse_duration
from aipass.devpulse.apps.handlers.json import json_handler


# Chunked so a long sleep stays interruptible and an injected clock returns at once.
_SLEEP_CHUNK_SECONDS = 5.0

# A hung command must not hold the wake's report forever; its output is the wake.
_COMMAND_TIMEOUT_SECONDS = 600.0

_WALL_CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_RELATIVE_PREFIX = "+"


def parse_schedule(time_str: str, now: datetime | None = None) -> datetime:
    """Parse ``HH:MM[:SS]`` (rolls to tomorrow if past) or ``+<duration>`` into a target ``datetime``."""
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
    """Render the wait between ``now`` and ``target``: ``"in 2h 15m"``, ``"overdue by 3m"``."""
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


def _run_command(argv: list[str]) -> dict:
    """Execute ``argv``, no shell; an exec failure or a timeout answers exit -1."""
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
        return {
            "command_exit_code": completed.returncode,
            "command_stdout": completed.stdout,
            "command_stderr": completed.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        logger.warning("[watchdog.schedule] command timed out after %ss %r", _COMMAND_TIMEOUT_SECONDS, argv)
        return {
            "command_exit_code": -1,
            "command_stdout": "",
            "command_stderr": f"timed out after {int(_COMMAND_TIMEOUT_SECONDS)}s: {exc}",
        }
    except OSError as exc:
        logger.warning("[watchdog.schedule] command exec failed %r: %s", argv, exc)
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
    """Block until ``time_str`` elapses, optionally run ``command`` on wake."""
    json_handler.log_operation("wake_at", {"time_str": time_str, "command": command})
    clock = now_fn if now_fn is not None else datetime.now
    start = clock()
    target = parse_schedule(time_str, now=start)
    # Before the sleep: an unclosed quote must fail now, not after the whole wait.
    argv = shlex.split(command) if command else None
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
        if argv:
            command_result = _run_command(argv)

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
