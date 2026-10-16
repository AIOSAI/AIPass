# =================== AIPass ====================
# Name: stop_flag.py
# Description: The lane side of a stop — a SIGTERM handler that raises a flag, the stopped state, the stopped line
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================

"""The lane side of ``stop`` (DPLAN-0412).

A lane runs inside :func:`catch_sigterm`. SIGTERM then raises a flag instead of
killing the process; the copy loops and the upload batch read
:func:`stop_requested` between files. A lane that honours the flag calls
:func:`mark_stopped`, and the entry point turns that into exit
:data:`STOPPED_EXIT` (130).

``signal.signal`` only works in the main thread. A lane run from another thread
logs that it cannot catch SIGTERM and runs without the handler: a stop then
ends that process the default way, with no tracker save and no stopped line.
"""

import signal
from contextlib import contextmanager
from typing import Iterator

from aipass.prax import logger

from ..audit import trail
from ..report.formatter import _human_bytes

#: The exit code of a run stopped by request: 128 + SIGINT's 2, the shell's
#: "interrupted", which drone already reports for an interrupted command.
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
    """Turn SIGTERM into the stop flag for the duration of a run, then restore the previous handler.

    Nests: all installs it around its sub-lanes, each of which installs it
    again; the outermost entry starts with the flag down.
    """
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
    """The last stdout line of a stopped run: ``stopped by request: 1,204 of 15,414 files, 310 MB``.

    Bytes go through the branch's one humaniser; a whole number of units drops
    its ``.0``, as the contract writes it.
    """
    size = _human_bytes(nbytes)
    number, unit = size.split(" ")
    if number.endswith(".0"):
        number = number[:-2]
    return f"stopped by request: {done:,} of {total:,} files, {number} {unit}"


# =============================================
