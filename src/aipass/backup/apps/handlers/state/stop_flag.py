# =================== AIPass ====================
# Name: stop_flag.py
# Description: The lane side of a stop — a SIGTERM handler that raises a flag, the stopped state, the stopped line
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-17
# =============================================

"""The lane side of ``stop``.

Off the main thread signal.signal fails: SIGTERM then kills the run with no tracker save, no stopped line.
"""

import signal
from contextlib import contextmanager
from typing import Iterator

from aipass.prax import logger

from ..audit import trail
from ..report.formatter import _human_bytes

#: 128 + SIGINT: the shell's "interrupted", which drone already reports.
STOPPED_EXIT = 130

_STATE = {"requested": False, "stopped": False, "depth": 0}


def _on_sigterm(signum: int, frame: object) -> None:
    """The installed handler: raise the flag, nothing else (it runs between bytecodes)."""
    _STATE["requested"] = True


def stop_requested() -> bool:
    """True once SIGTERM arrived during the current run."""
    return _STATE["requested"]


def mark_stopped() -> None:
    """Record that a lane honoured the flag; the entry point exits STOPPED_EXIT."""
    _STATE["stopped"] = True


def run_was_stopped() -> bool:
    """True when a lane in this process stopped by request since the last reset."""
    return _STATE["stopped"]


def reset_stop_state() -> None:
    """Clear the flag and the stopped mark; the entry point calls it per command."""
    _STATE["requested"] = False
    _STATE["stopped"] = False


@contextmanager
def catch_sigterm() -> Iterator[None]:
    """Turn SIGTERM into the stop flag for a run, then restore the previous handler; nests, outermost resets."""
    if _STATE["depth"] == 0:
        reset_stop_state()
    _STATE["depth"] += 1
    previous = None
    installed = False
    try:
        previous = signal.signal(signal.SIGTERM, _on_sigterm)
        installed = True
    except ValueError as exc:
        logger.warning(f"[backup] SIGTERM not caught (not the main thread); a stop ends this run outright: {exc}")
        trail.log_operation("sigterm_not_caught", {"reason": str(exc)})
    try:
        yield
    finally:
        _STATE["depth"] -= 1
        if installed:
            signal.signal(signal.SIGTERM, previous if previous is not None else signal.SIG_DFL)


def stopped_line(done: int, total: int, nbytes: int) -> str:
    """The last stdout line of a stopped run: ``stopped by request: 1,204 of 15,414 files, 310 MB``."""
    size = _human_bytes(nbytes)
    number, unit = size.split(" ")
    if number.endswith(".0"):
        number = number[:-2]
    return f"stopped by request: {done:,} of {total:,} files, {number} {unit}"
