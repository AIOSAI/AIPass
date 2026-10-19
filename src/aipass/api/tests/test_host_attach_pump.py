# =================== AIPass ====================
# Name: test_host_attach_pump.py
# Description: Tests for the attach lane's room and pump — the tmux command, a real PTY, resize and hangup
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/host/attach.py's room and PTY, and apps/handlers/host/pump.py's control frames."""

# REAL PTYs running `cat`/`echo`, never tmux: EOF on close, SIGHUP and TIOCSWINSZ order live where a mock invents.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered) — issue_token() and the token store's own locking, tests/test_host_token_store.py
# seedgo: no-test-needed(generated) — the tmux client that attach_command() builds; these tests spawn cat, never tmux

import ast
import asyncio
import errno
import os
import signal
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aipass.api.apps.handlers.host import attach as host_attach
from aipass.api.apps.handlers.host import pump as host_pump
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens
from aipass.api.tests.support_host_attach import (
    StubSession,
    detach_and_wait,
    fastapi_required,
    pty_required,
    source_of,
    wait_for_log,
)

# Own constants, not the support module's: discarded_patch judges a target imported from this package.
PATCH_SERVER_JSON = "aipass.api.apps.handlers.host.server.json_handler"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"
PATCH_PUMP_LOGGER = "aipass.api.apps.handlers.host.pump.logger"


@pytest.fixture
def handed_hook(quiet: Any, tmux_preflight: Any, monkeypatch: Any) -> Iterator[Any]:
    """The preexec_fn open_attach hands Popen, read off a recorder."""
    # _spawn_pty closes the slave end itself; the master belongs to the session and is closed here.
    master, slave = os.pipe()
    handed: dict = {}
    monkeypatch.setattr(host_attach, "pty", SimpleNamespace(openpty=lambda: (master, slave)))
    monkeypatch.setattr(host_attach, "set_winsize", lambda *a: None)
    monkeypatch.setattr(host_attach.subprocess, "Popen", lambda *a, **k: handed.update(k) or MagicMock(pid=1))
    session = host_attach.open_attach("", room="baud-hook")
    yield handed["preexec_fn"]
    os.close(session.descriptor)


@pytest.fixture
def cat_session(quiet: Any, tmux_preflight: Any):
    """A real PTY running `cat` — an echo chamber that proves the pump."""
    with patch.object(host_attach, "attach_command", lambda branch, scope="": ["cat"]):
        session = host_attach.open_attach("api", cwd=None)
        try:
            yield session
        finally:
            session.hangup()


def _chained(command: list) -> list:
    """Split a tmux argv into the commands that follow the first `;`."""
    groups: list = []
    for piece in command:
        if piece == ";":
            groups.append([])
        elif groups:
            groups[-1].append(piece)
    return groups


class TestTheCommandIsTheDesktopsCommand:
    """`pty.rs` spawns `tmux new-session -A -t <room>`. This spawns the same thing,
    or a phone and a desktop end up in two rooms with one agent's name on them."""

    def test_the_room_name_uses_bauds_prefix(self) -> None:
        """Mirrored, not invented — their desktop names rooms this way."""
        assert host_attach.room_name("memory") == "baud-memory"

    def test_an_address_form_resolves_to_the_same_room(self) -> None:
        """'@memory' and 'memory' are one room, never two."""
        assert host_attach.room_name("@memory") == host_attach.room_name("memory")

    def test_external_rooms_carry_the_project_scope(self) -> None:
        """THE DESKTOP'S OWN TEST VECTORS, copied from `room_names_are_tmux_safe`
        and `external_rooms_carry_the_project_scope` in @baud's lib.rs."""
        assert host_attach.room_name("vera", "vera-studio") == "baud-vera-studio-vera"
        assert host_attach.room_name("chess", "chess") == "baud-chess-chess"
        assert host_attach.room_name("x", "a.b:c") == "baud-a-b-c-x"
        assert host_attach.room_name("AIPASS.admin") == "baud-AIPASS-admin"
        assert host_attach.room_name("a:b c") == "baud-a-b-c"

    def test_a_scoped_command_targets_the_scoped_room_everywhere(self) -> None:
        """Every `-t` in the chained argv must carry the SCOPED name — a chain
        that set mouse on `baud-baud` instead would configure a stranger's room."""
        command = host_attach.attach_command("baud", "baud")

        assert command[: command.index(";")] == ["tmux", "new-session", "-A", "-s", "baud-baud-baud"]
        for chained in _chained(command):
            if "-t" in chained:
                assert chained[chained.index("-t") + 1] == "baud-baud-baud"

    def test_shell_rooms_live_in_their_own_namespace(self) -> None:
        """`baud-shell-` is a namespace the fleet scan can never mistake for an
        agent; the project is always in the name, since two projects can each have a devpulse."""
        assert host_attach.shell_room_name("AIPass") == "baud-shell-aipass"
        assert host_attach.shell_room_name("aipass", "devpulse") == "baud-shell-aipass-devpulse"
        assert host_attach.shell_room_name("TESTING", "testing") == "baud-shell-testing-testing"
        assert host_attach.shell_room_name("a.b:c", "@x") == "baud-shell-a-b-c-x"

    def test_monitor_targets_are_branch_lists_or_commons(self) -> None:
        """THE DESKTOP'S OWN FENCE VECTORS, copied from
        `monitor_targets_are_branch_lists_or_commons` and `monitor_target_fence_refuses_command_shapes` in pty.rs."""
        # "" stays refused: open_monitor asks about absence itself, and folding it in would break the mirror.
        assert host_attach.valid_monitor_target("commons")
        assert host_attach.valid_monitor_target("seedgo")
        assert host_attach.valid_monitor_target("seedgo,cli")
        assert host_attach.valid_monitor_target("ai_mail")
        assert not host_attach.valid_monitor_target("")
        assert not host_attach.valid_monitor_target("seedgo; rm -rf /")
        assert not host_attach.valid_monitor_target("SEEDGO")
        assert not host_attach.valid_monitor_target("a b")
        assert not host_attach.valid_monitor_target("../etc")

    def test_the_argv_builders_refuse_a_name_they_cannot_pass_safely(self) -> None:
        """The builders hold the fence themselves, so no caller can hand Popen an unfenced name."""
        for build in (host_attach.client_command, host_attach.attach_only_command):
            with pytest.raises(host_attach.AttachRefused):
                build(";")
        with pytest.raises(host_attach.AttachRefused):
            host_attach.monitor_command("seedgo; rm -rf /")

        assert host_attach.client_command("0")[4] == "0"
        assert host_attach.monitor_command("seedgo,cli")[-1] == "seedgo,cli"

    def test_the_watch_command_is_the_desktops_command(self) -> None:
        """`drone @prax monitor run <target>` — pty.rs `monitor_create`'s exact
        command, minus its login shell: drone resolves from this server's PATH and no shell sees the target."""
        assert host_attach.monitor_command("seedgo") == ["drone", "@prax", "monitor", "run", "seedgo"]

    def test_a_shell_command_targets_the_shell_room_everywhere(self) -> None:
        """The shell lane reuses the agent lane's argv builder, so the mouse and
        window-size lessons hold there too."""
        command = host_attach.client_command("baud-shell-aipass")

        assert command[: command.index(";")] == ["tmux", "new-session", "-A", "-s", "baud-shell-aipass"]
        for chained in _chained(command):
            assert "-t" in chained, f"chained command with no target: {chained}"
            assert chained[chained.index("-t") + 1] == "baud-shell-aipass"

    def test_the_command_is_attach_or_create(self) -> None:
        """`new-session -A` is the whole lifecycle promise in one flag."""
        command = host_attach.attach_command("memory")

        assert command[: command.index(";")] == ["tmux", "new-session", "-A", "-s", "baud-memory"]

    def test_the_room_gets_mouse_and_smallest_sizing(self) -> None:
        """A room born through this door must match one born at the desk."""
        # `smallest` is @baud's measurement: it holds the phone through a desk resize and self-heals on detach.
        command = host_attach.attach_command("memory")

        assert _chained(command) == [
            ["set-option", "-t", "baud-memory", "mouse", "on"],
            ["set-option", "-w", "-t", "baud-memory", "window-size", "smallest"],
        ]

    def test_every_chained_command_carries_its_own_target(self) -> None:
        """The guard @devpulse asked for by name, and the one that would have
        caught the bug @baud found in their own `pty.rs`."""
        # A chained `set-option` with no `-t` hits whatever tmux calls the current session, and still exits 0.
        room = "baud-memory"
        chained = _chained(host_attach.attach_command("memory"))

        assert chained, "the whole point is that there ARE chained commands"
        for command in chained:
            assert "-t" in command, f"chained command with no target: {command}"
            assert command[command.index("-t") + 1] == room

    def test_the_separator_is_its_own_argument(self) -> None:
        """`;` as a separate argv element is how tmux separates commands with no
        shell involved; glued to a neighbour, the second command becomes an argument of the first."""
        command = host_attach.attach_command("memory")

        assert ";" in command
        assert not any(piece != ";" and piece.endswith(";") for piece in command)

    def test_the_command_is_a_list_so_it_never_reaches_a_shell(self) -> None:
        """A list argv cannot be word-split, so a branch name cannot become one."""
        command = host_attach.attach_command("memory; rm -rf /")

        assert isinstance(command, list)
        assert command[command.index("-s") + 1] == "baud-memory--rm--rf--"
        for chained in _chained(command):
            assert chained[chained.index("-t") + 1] == "baud-memory--rm--rf--"


def _evaluated_strings(module: Any) -> list:
    """Every string a module actually EVALUATES, docstrings excluded."""
    # A text grep would forbid the prose explaining the design while permitting the argument that breaks it.
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            if isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))

    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
    ]


def _identifiers(module: Any) -> set:
    """Every name and attribute the module references."""
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
    return names


class TestNoSessionIsEverKilledHere:
    """The property this whole module is built around: detach is not kill."""

    def test_no_string_this_module_evaluates_contains_a_kill(self) -> None:
        """kill-session, kill-server, kill-pane — a tmux kill is a literal, and
        this module constructs none."""
        offenders = [text for text in _evaluated_strings(host_attach) if "kill" in text.lower()]

        assert offenders == []

    def test_the_module_never_reaches_for_sigkill(self) -> None:
        """SIGHUP is a detaching terminal. SIGKILL is an execution."""
        names = _identifiers(host_attach)

        assert "SIGKILL" not in names
        assert "SIGTERM" not in names
        assert "SIGHUP" in names


@pty_required
class TestThePumpMovesRealBytes:
    """A PTY that cannot carry bytes is a PTY that carries nothing."""

    def test_what_is_written_comes_back(self, cat_session: Any) -> None:
        """The round trip, through a real terminal, in both directions."""
        cat_session.write(b"hello room\n")

        received = b""
        deadline = time.monotonic() + 5
        while b"hello room" not in received and time.monotonic() < deadline:
            received += cat_session.read()

        assert b"hello room" in received

    def test_control_bytes_travel_unchanged(self, cat_session: Any) -> None:
        """The key bar writes real control bytes — \\x1b[A for Up, and so on."""
        cat_session.write(b"\x1b[A\x1b[B\r")

        received = b""
        deadline = time.monotonic() + 5
        while b"\x1b[A" not in received and time.monotonic() < deadline:
            received += cat_session.read()

        assert b"\x1b[A" in received

    def test_read_returns_bytes_never_text(self, cat_session: Any) -> None:
        """Decoding here would corrupt partial UTF-8 across a chunk boundary and
        mangle escape sequences."""
        cat_session.write(b"x\n")

        deadline = time.monotonic() + 5
        data = b""
        while not data and time.monotonic() < deadline:
            data = cat_session.read()

        # isinstance alone holds for b"" too; the loop waited for data, so an empty read is a real failure.
        assert isinstance(data, bytes), f"the pump decoded to text: {type(data).__name__}"
        assert data.startswith(b"x"), f"the pump did not hand back what cat echoed: {data!r}"

    def test_a_closed_pty_reads_empty_rather_than_raising(self, quiet: Any, tmux_preflight: Any) -> None:
        """EOF is how a PTY reports end-of-life, and the pump reads it as 'stop'."""
        with patch.object(host_attach, "attach_command", lambda branch, scope="": ["echo", "done"]):
            session = host_attach.open_attach("api")

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if session.read() == b"":
                break

        assert session.read() == b""
        session.hangup()


@pty_required
class TestTheRoomCanActuallyHearAResize:
    """The bug that made every resize a no-op, and the two halves of its fix."""

    # TIOCSWINSZ signals the foreground group of the CONTROLLING terminal; a child without one never hears a resize.

    def test_the_pty_opens_at_the_size_the_docstring_promises(self, quiet: Any, tmux_preflight: Any) -> None:
        """openpty hands back 0x0, and a tmux client reads that, calls it invalid
        and falls back to its OWN 80x24 — two defaults agreeing is not a contract."""
        import struct

        with patch.object(host_attach, "attach_command", lambda branch, scope="": ["cat"]):
            session = host_attach.open_attach("api")

        try:
            packed = host_attach.fcntl.ioctl(session.descriptor, host_attach.termios.TIOCGWINSZ, b"\0" * 8)
            rows, cols, _, _ = struct.unpack("HHHH", packed)
            host_attach.set_winsize(session.descriptor, 132, 50)
            restamped = host_attach.fcntl.ioctl(session.descriptor, host_attach.termios.TIOCGWINSZ, b"\0" * 8)
        finally:
            session.hangup()

        assert struct.unpack("HHHH", restamped)[:2] == (50, 132)
        assert (cols, rows) == (host_attach.DEFAULT_COLS, host_attach.DEFAULT_ROWS)
        assert (cols, rows) != (0, 0)

    def test_the_size_is_stamped_before_the_child_exists(self, quiet: Any, tmux_preflight: Any) -> None:
        """Order matters: a client started against a 0x0 terminal has ALREADY
        chosen its fallback by the time a later ioctl arrives."""
        calls = []

        with patch.object(host_attach, "attach_command", lambda branch, scope="": ["cat"]):
            with patch.object(host_attach, "set_winsize", side_effect=lambda *a: calls.append("winsize")):
                with patch.object(host_attach.subprocess, "Popen") as spawn:
                    spawn.side_effect = lambda *a, **k: calls.append("popen") or MagicMock(pid=1)
                    host_attach.open_attach("api")

        assert calls == ["winsize", "popen"]

    def test_the_child_takes_a_controlling_terminal(self, quiet: Any, tmux_preflight: Any) -> None:
        """The half that makes SIGWINCH have a destination."""
        # `start_new_session=True` leaves a leader with no controlling tty; the preexec_fn does the setsid itself.
        with patch.object(host_attach, "attach_command", lambda branch, scope="": ["cat"]):
            with patch.object(host_attach.subprocess, "Popen") as spawn:
                spawn.return_value = MagicMock(pid=1)
                host_attach.open_attach("api")

        kwargs = spawn.call_args.kwargs
        assert kwargs["preexec_fn"] is host_attach._acquire_controlling_tty
        assert "start_new_session" not in kwargs

    def test_the_child_is_still_isolated_from_our_signals(self, quiet: Any, tmux_preflight: Any) -> None:
        """The property `start_new_session` was there for, kept."""
        with patch.object(host_attach, "attach_command", lambda branch, scope="": ["cat"]):
            session = host_attach.open_attach("api")

        try:
            if hasattr(os, "getpgid"):
                assert os.getpgid(session.process.pid) != os.getpgid(os.getpid())
            else:
                pytest.fail("this platform opens a PTY and has no os.getpgid to read the child's group by")
        finally:
            session.hangup()

    def test_the_preexec_hook_does_no_lookups_in_the_forked_child(self, handed_hook: Any) -> None:
        """It runs after fork in a process that HAS threads, where only
        async-signal-safe work is really allowed."""
        # The shape, not the effect: the effect only shows up as a rare deadlock under load.
        import inspect

        signature = inspect.signature(handed_hook)

        assert signature.parameters, "nothing is bound — the child would look it all up"
        for parameter in signature.parameters.values():
            assert parameter.default is not inspect.Parameter.empty

    def test_the_pre_3_11_fallback_does_setsid_then_tiocsctty(self, handed_hook: Any) -> None:
        """The branch that never runs on this interpreter, and would ship untested."""
        # Mocked: a real `os.setsid()` would detach the runner. Order matters: TIOCSCTTY only serves a session leader.
        order = []
        setsid = MagicMock(side_effect=lambda: order.append("setsid"))
        ioctl = MagicMock(side_effect=lambda *a: order.append("ioctl"))

        handed_hook(
            _setsid=setsid,
            _login_tty=None,
            _ioctl=ioctl,
            _tiocsctty=1234,
        )

        assert order == ["setsid", "ioctl"]
        ioctl.assert_called_once_with(0, 1234, 0)

    def test_the_hook_claims_the_descriptor_subprocess_actually_hands_it(self, handed_hook: Any) -> None:
        """fd 0, and it has to be 0."""
        # subprocess dups the slave onto 0, 1 and 2 BEFORE preexec_fn, so the terminal to claim is stdin.
        ioctl = MagicMock()

        handed_hook(
            _setsid=MagicMock(),
            _login_tty=None,
            _ioctl=ioctl,
            _tiocsctty=1234,
        )

        assert ioctl.call_args.args[0] == 0

    def test_the_login_tty_path_claims_the_same_descriptor(self, handed_hook: Any) -> None:
        """The 3.11+ path targets fd 0 too — one behaviour, two implementations."""
        login_tty = MagicMock()

        handed_hook(_login_tty=login_tty)

        login_tty.assert_called_once_with(0)

    def test_a_real_child_ends_up_owning_the_terminal(self, quiet: Any, tmux_preflight: Any) -> None:
        """The property itself, on a real process rather than a mock."""
        # Both reads happen while the child lives: macOS answers ESRCH for a reaped pid where Linux keeps a zombie's
        # pgid, so the stand-in refuses after hangup and moving a read below it goes red here too.
        with patch.object(host_attach, "attach_command", lambda branch, scope="": ["cat"]):
            session = host_attach.open_attach("api")

        def macos_getpgid(pid: int) -> int:
            if session.closed:
                raise ProcessLookupError(errno.ESRCH, "No such process")
            if hasattr(os, "getpgid"):
                return os.getpgid(pid)
            pytest.fail("this platform opens a PTY and has no os.getpgid to read the child's group by")

        try:
            child_group = macos_getpgid(session.process.pid)
            # Until the child's exec claims the terminal, the foreground is still ours.
            deadline = time.monotonic() + 5
            foreground = os.tcgetpgrp(session.descriptor)
            while foreground != child_group and time.monotonic() < deadline:
                foreground = os.tcgetpgrp(session.descriptor)
        finally:
            session.hangup()

        assert foreground > 0
        assert foreground == child_group


@pty_required
class TestResizeIsAnIoctlAndItsArgumentsAreOrdered:
    """struct winsize is (rows, cols, xpixel, ypixel) — ROWS FIRST."""

    def test_a_resize_reaches_the_terminal(self, cat_session: Any) -> None:
        """Read the size back off the descriptor rather than trusting the call."""
        import struct

        cat_session.resize(100, 30)

        packed = host_attach.fcntl.ioctl(cat_session.descriptor, host_attach.termios.TIOCGWINSZ, b"\0" * 8)
        rows, cols, _, _ = struct.unpack("HHHH", packed)

        assert (cols, rows) == (100, 30)

    def test_a_zero_dimension_is_refused(self, cat_session: Any) -> None:
        """A terminal with no columns renders nothing and reports no error."""
        with pytest.raises(host_attach.AttachRefused):
            cat_session.resize(0, 30)

    def test_a_negative_dimension_is_refused(self, cat_session: Any) -> None:
        """Nonsense in, refusal out."""
        with pytest.raises(host_attach.AttachRefused):
            cat_session.resize(100, -1)

    def test_an_absurd_dimension_is_refused_not_clamped(self, cat_session: Any) -> None:
        """A geometry silently changed is one the client renders against wrongly."""
        with pytest.raises(host_attach.AttachRefused):
            cat_session.resize(99999, 30)

    def test_a_non_numeric_dimension_is_refused(self, cat_session: Any) -> None:
        """The caller's mistake, named as theirs rather than crashed on."""
        with pytest.raises(host_attach.AttachRefused):
            cat_session.resize("wide", 30)


@pty_required
class TestHangupDetachesAndNeverKillsTheRoom:
    """The lifecycle promise, tested against a real process."""

    def test_hangup_sends_sighup_and_not_a_kill(self, quiet: Any, tmux_preflight: Any) -> None:
        """The signal itself, captured — a detaching terminal sends SIGHUP."""
        with patch.object(host_attach, "attach_command", lambda branch, scope="": ["cat"]):
            session = host_attach.open_attach("api")

        session.process = MagicMock()
        session.hangup()

        session.process.send_signal.assert_called_once_with(signal.SIGHUP)

    def test_hangup_closes_the_descriptor(self, quiet: Any, tmux_preflight: Any) -> None:
        """A leaked master descriptor per attach is a file handle leak per glance."""
        with patch.object(host_attach, "attach_command", lambda branch, scope="": ["cat"]):
            session = host_attach.open_attach("api")

        descriptor = session.descriptor
        session.hangup()

        with pytest.raises(OSError) as caught:
            os.fstat(descriptor)

        assert caught.value.errno == errno.EBADF

    def test_a_second_hangup_touches_nothing(self, quiet: Any, tmux_preflight: Any) -> None:
        """A socket that errors and then closes calls this twice, and the second
        call must be a no-op at the SYSCALL level — not merely quiet."""
        # Descriptor numbers are REUSED: a stale close could SUCCEED on another operator's attach.
        with patch.object(host_attach, "attach_command", lambda branch, scope="": ["cat"]):
            session = host_attach.open_attach("api")

        session.hangup()
        session.process = MagicMock()

        with patch.object(host_attach.os, "close") as closer:
            session.hangup()

        assert not closer.called
        assert not session.process.send_signal.called
        assert session.closed is True

    def test_the_child_is_in_its_own_session(self, quiet: Any, tmux_preflight: Any) -> None:
        """The child LEADS its own session, which is more than another process group."""
        # Leading a session also keeps this server's terminal hangup away, so a restart never ends a room.
        with patch.object(host_attach, "attach_command", lambda branch, scope="": ["cat"]):
            session = host_attach.open_attach("api")

        try:
            if hasattr(os, "getsid"):
                assert os.getsid(session.process.pid) == session.process.pid
            else:
                pytest.fail("this platform opens a PTY and has no os.getsid to read the child's session by")
        finally:
            session.hangup()


BAD_CONTROL_FRAMES = [
    '{"type": "resize", "cols": 0, "rows": 24}',
    '{"type": "resize", "cols": -5, "rows": 24}',
    '{"type": "resize", "cols": 99999, "rows": 24}',
    '{"type": "resize", "cols": "wide", "rows": 24}',
    '{"type": "resize", "cols": null, "rows": null}',
    '{"type": "resize", "rows": 24}',
    '{"type": "resize"}',
    '{"type": "detonate"}',
    '{"not even a type": 1}',
    "not json at all",
    "[]",
    "null",
    "",
]


@fastapi_required
class TestABadResizeIsDroppedAndTheSessionLivesOn:
    """The branch @baud could not test from their end, handed back on purpose."""

    # An exception escaping the control handler kills the pump and detaches an operator over a typo.

    def test_every_bad_frame_is_dropped_and_the_room_survives_all_of_them(self, store: Any, seated: Any) -> None:
        """Thirteen malformed frames down one socket, then a good one."""
        # A control frame falling through to `write` types JSON into the operator's shell.
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        session = StubSession()

        with patch(PATCH_SERVER_LOGGER) as log, patch(PATCH_PUMP_LOGGER), patch(PATCH_SERVER_JSON):
            with patch.object(host_attach, "open_attach", return_value=session):
                client = TestClient(host_server.create_app())
                with client.websocket_connect(
                    "/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]
                ) as socket:
                    for frame in BAD_CONTROL_FRAMES:
                        socket.send_text(frame)

                    socket.send_text('{"type": "resize", "cols": 72, "rows": 44}')
                    session.wait_until(lambda: bool(session.resizes))

                    # The hangup precedes the route's detach line; leaving before that line cancels a live server.
                    detach_and_wait(socket, session)
                    wait_for_log(log, "socket detached from")

        assert session.resizes == [(72, 44)]
        assert session.writes == []
        assert session.hangups == 1

    def test_a_bad_frame_does_not_stop_the_keystrokes_that_follow_it(self, store: Any, seated: Any) -> None:
        """Recovery on the OTHER channel."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        session = StubSession()

        with patch(PATCH_SERVER_LOGGER) as log, patch(PATCH_SERVER_JSON):
            with patch.object(host_attach, "open_attach", return_value=session):
                client = TestClient(host_server.create_app())
                with client.websocket_connect(
                    "/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]
                ) as socket:
                    socket.send_text('{"type": "resize", "cols": 0, "rows": 0}')
                    socket.send_bytes(b"echo still-listening")
                    socket.send_bytes(b"\r")
                    session.wait_until(lambda: len(session.writes) >= 2)

                    detach_and_wait(socket, session)
                    wait_for_log(log, "socket detached from")

        assert session.writes == [b"echo still-listening", b"\r"]

    def test_a_disconnect_on_a_silent_room_still_detaches_promptly(self, store: Any, seated: Any) -> None:
        """The bug this file found, pinned so it cannot come back."""
        # Waiting on BOTH directions parks the detach on a silent room's os.read; the stub reads nothing for 10s.
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        session = StubSession()

        with patch(PATCH_SERVER_LOGGER) as log, patch(PATCH_SERVER_JSON):
            with patch.object(host_attach, "open_attach", return_value=session):
                client = TestClient(host_server.create_app())
                started = time.monotonic()
                with client.websocket_connect(
                    "/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]
                ) as socket:
                    detach_and_wait(socket, session)
                    wait_for_log(log, "socket detached from")
                elapsed = time.monotonic() - started

        assert session.hangups == 1
        assert elapsed < 5

    def test_the_pump_waits_for_the_first_direction_not_both(self) -> None:
        """The fix, named at the source."""
        # Tidying FIRST_COMPLETED back into a `gather` would reintroduce the deadlock.
        pump = source_of("run_pump")

        assert "return_when=asyncio.FIRST_COMPLETED" in pump
        # hangup first: closing the descriptor breaks the reader out of os.read; a cancel never reaches a syscall.
        assert pump.index("session.hangup()") < pump.index("task.cancel()")

    def test_the_handler_swallows_a_refusal_rather_than_killing_the_pump(self) -> None:
        """The wiring, read at the source as well as driven."""
        handler = source_of("_handle_control")

        assert "except (host_attach.AttachRefused, host_attach.AttachUnavailable, OSError)" in handler
        assert "raise" not in handler


class TestARoomThatEndsClosesItsSocketWith4000:
    """The phone tells "room ended" from "server hung up" by the close code alone."""

    def test_an_empty_read_closes_the_socket_with_4000_room_ended(self) -> None:
        """The room's PTY reads empty: the socket is closed 4000 "room ended", the session hung up once."""
        session = SimpleNamespace(room="aipass-api", read=lambda: b"", hangups=0)
        session.hangup = lambda: setattr(session, "hangups", session.hangups + 1)

        async def silent_client() -> dict:
            await asyncio.Event().wait()
            return {}

        websocket = MagicMock()
        websocket.close = AsyncMock()
        websocket.receive = silent_client

        close_code = asyncio.run(host_pump.run_pump(websocket, session))

        websocket.close.assert_awaited_once_with(code=4000, reason="room ended")
        assert close_code is None, "the room ended first; the client sent no code"
        assert session.hangups == 1
