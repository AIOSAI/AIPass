# =================== AIPass ====================
# Name: support_host_attach.py
# Description: Shared helpers for the attach lane's test files (test_host_attach*.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Helpers shared by test_host_attach.py, test_host_attach_pump.py and test_host_attach_route.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import ast
import threading
from pathlib import Path
from typing import Any

import pytest

from aipass.api.apps.handlers.host import attach as host_attach
from aipass.api.apps.handlers.host import pump as host_pump
from aipass.api.apps.handlers.host import server as host_server

pty_required = pytest.mark.skipif(
    not host_attach.is_available(),
    reason="a PTY is a POSIX object and this platform has none",
)

fastapi_required = pytest.mark.skipif(
    not host_server.is_available(),
    reason="the [host] extra is not installed",
)


# Exists on no host: `tmux_preflight` cases replace the argv before any spawn,
# so an exec of this fails by name instead of running the runner's own tmux.
TMUX_STANDIN = "/nonexistent/bin/tmux"


def _forced_tmux_which(host_which: Any) -> Any:
    """The preflight rule: tmux is answered for, every other binary is the host's."""

    def _which(binary: str) -> Any:
        return TMUX_STANDIN if binary == host_attach.TMUX_BINARY else host_which(binary)

    return _which


def source_of(name: str, module: Any = host_pump) -> str:
    """The source of ONE function, cut on structure not on neighbours."""
    # A slice between two literal names swallows unrelated code once functions move, and can pass on borrowed luck.
    source = Path(module.__file__).read_text(encoding="utf-8")

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            segment = ast.get_source_segment(source, node)
            if segment is not None:
                return segment

    raise AssertionError(f"{Path(module.__file__).name} has no function named {name!r}")


def detach_and_wait(socket: Any, session: Any, timeout: float = 10.0) -> None:
    """Close the sheet, then wait for the SERVER to finish detaching."""
    # Not the context manager's close: its teardown cancels the app task, so a slow detach reads as CancelledError.
    socket.close()
    session.wait_until(lambda: session.hangups > 0, timeout)


class StubSession:
    """A session that records instead of running, but REFUSES for real."""

    def __init__(self) -> None:
        self.room = "baud-api"
        self.writes: list = []
        self.resizes: list = []
        self.hangups = 0
        self._release = threading.Event()
        self._recorded = threading.Condition()

    def wait_until(self, done: Any, timeout: float = 10.0) -> None:
        """Block until `done()` holds or `timeout` passes; the caller asserts on what it then sees."""
        with self._recorded:
            self._recorded.wait_for(done, timeout)

    def read(self, size: int = 0) -> bytes:
        """Block like a quiet room, until the pump is torn down."""
        self._release.wait(timeout=10)
        return b""

    def write(self, data: bytes) -> None:
        """Record what was typed into the room."""
        with self._recorded:
            self.writes.append(data)
            self._recorded.notify_all()

    def resize(self, cols: object, rows: object) -> None:
        """Validate for real, then record."""
        # The product's own `_require_dimension`, so a bad frame hits production validation, not a copy that drifts.
        size = (host_attach._require_dimension(cols, "cols"), host_attach._require_dimension(rows, "rows"))
        with self._recorded:
            self.resizes.append(size)
            self._recorded.notify_all()

    def hangup(self) -> None:
        """Release the blocked reader so the pump can finish."""
        with self._recorded:
            self.hangups += 1
            self._recorded.notify_all()
        self._release.set()


def wait_for_log(log: Any, needle: str, timeout: float = 10.0) -> str:
    """Wait for a rendered info line containing `needle`, and return it."""
    # RENDERED: applying the `%` here makes a format/arg mismatch fail as a TypeError, not a mangled server.log line.
    # The mock records a call before its side effect, which needs the lock `wait_for` holds, so no line slips between.
    logged = threading.Condition()

    def rendered_line() -> str | None:
        for call in list(log.info.call_args_list):
            rendered = call.args[0] % call.args[1:] if len(call.args) > 1 else call.args[0]
            if needle in rendered:
                return rendered
        return None

    def announce(*args: Any, **kwargs: Any) -> None:
        with logged:
            logged.notify_all()

    log.info.side_effect = announce
    with logged:
        line = logged.wait_for(rendered_line, timeout)

    if line is None:
        raise AssertionError(f"no info line containing {needle!r}: {log.info.call_args_list}")
    return line
