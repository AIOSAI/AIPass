# =================== AIPass ====================
# Name: support_host_attach.py
# Description: Shared helpers for the attach lane's test files (test_host_attach*.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Helpers shared by test_host_attach.py, test_host_attach_pump.py and test_host_attach_route.py.

No test_ prefix and no Test class, so pytest never collects it. Moved here
whole from test_host_attach.py when the file split along the unit under test
(api, the oversize split leg, 2026-10-08): the platform marks, the tmux
preflight rule, the source reader, the stub session and the two waits, each
used by two or more of the three files. The patch-target strings stay each
file's own constants: seedgo's discarded_patch rule judges a target imported
from this branch's package, and those patches silence loggers on purpose.
"""

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


# A path that exists on no host. Every case holding `tmux_preflight` replaces
# the argv before anything spawns, so this value is only ever read for its
# truthiness — if one of them ever tries to EXEC it, the failure says so by
# name rather than quietly running whatever tmux the runner happened to have.
TMUX_STANDIN = "/nonexistent/bin/tmux"


def _forced_tmux_which(host_which: Any) -> Any:
    """
    The preflight rule: tmux is answered for, every other binary is the host's.

    Shared by the `tmux_preflight` fixture and the case that manufactures a
    runner with nothing installed, so the rule under test and the rule the
    file runs on are one object rather than two that agree today.

    Args:
        host_which: The `shutil.which` this rule stands in front of.

    Returns:
        A `which` answering TMUX_STANDIN for tmux and delegating the rest.
    """

    def _which(binary: str) -> Any:
        return TMUX_STANDIN if binary == host_attach.TMUX_BINARY else host_which(binary)

    return _which


def source_of(name: str, module: Any = host_pump) -> str:
    """
    The source of ONE function, cut on structure not on neighbours.

    Several tests here read the source, because the properties they pin are
    about shape rather than behaviour — an except clause that must exist, a call
    that must come before another. They used to slice between two literal names,
    and that broke the moment the pump moved out to module level: the end anchor
    was still findable, hundreds of lines further down, so the slice swallowed
    code the test was never about and failed for the wrong reason. Three of the
    four went on passing on borrowed luck, which is the worse half of it.

    Same lesson this branch keeps relearning on the other side of the wire: cut
    on structure, never on the prose that happens to sit next to it.

    WHICH MODULE is a parameter for the same reason. The pump moved AGAIN on
    2026-08-21, out of server.py into pump.py under a line cap, and a helper
    that named its file in its own body would have had to be rewritten rather
    than pointed. The default is where the pump lives; callers that read a
    route pass server.py explicitly.

    Args:
        name: The function's name.
        module: The module to read it from — the pump by default.

    Returns:
        Exactly that function's source.
    """
    source = Path(module.__file__).read_text(encoding="utf-8")

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            segment = ast.get_source_segment(source, node)
            if segment is not None:
                return segment

    raise AssertionError(f"{Path(module.__file__).name} has no function named {name!r}")


def detach_and_wait(socket: Any, session: Any, timeout: float = 10.0) -> None:
    """
    Close the sheet, then wait for the SERVER to finish detaching.

    NOT the same as letting the context manager close it. The test client's
    teardown cancels the app task and then reads that task's result, so a
    server still finishing when teardown runs comes back as a CancelledError
    instead of as whatever it was actually doing. On an idle machine the server
    always wins that race; under load it does not — reproduced 3 runs in 4 at
    -n 8 on a 4-core box, and a CI runner is exactly that kind of machine. The
    two tests that flaked were the two that asserted on teardown.

    The hangup is also the honest thing to wait on: it IS the detach these
    tests are about, so waiting for it makes the timing assertion measure the
    server's real teardown rather than the moment the client stopped caring.
    """
    socket.close()
    session.wait_until(lambda: session.hangups > 0, timeout)


class StubSession:
    """
    A session that records instead of running, but REFUSES for real.

    `resize` delegates to the module's own `_require_dimension`, so a bad frame
    driven through the live socket hits the same validation a real PTY would.
    Only the syscall is absent; the decision is the production one.

    Every record is taken under one Condition and announced on it, so a test
    waits on the record it needs (`wait_until`) instead of sleeping in a loop
    and looking again (api, fleet green leg 8).
    """

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
    """
    Wait for a rendered info line containing `needle`, and return it.

    RENDERED, not matched on the format string: `logger.info(fmt, *args)` is
    lazy, so a format string and its arguments can disagree for as long as
    nobody formats them — and the place that finally does is production, at the
    moment somebody is reading the log to diagnose something else. Applying the
    `%` here means a mismatched arg count fails as a TypeError in this test
    instead of as a mangled line in server.log.

    Args:
        log: The patched server logger.
        needle: Text the rendered line must contain.
        timeout: Seconds to keep looking.

    Returns:
        The rendered line.

    Raises:
        AssertionError: No such line arrived in time.

    Woken by each info call rather than polled on a sleep (api, fleet green leg
    8). The mock records a call before it runs the side effect, and the side
    effect needs the lock `wait_for` holds while it looks, so no line lands
    between a look and the wait that follows it.
    """
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
