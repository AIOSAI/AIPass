#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_host_attach.py
# Description: Tests for the host API attach lane — a real PTY running a tmux client
# Version: 1.0.0
# Created: 2026-08-14
# =============================================

"""
Tests for the Attach Lane

DPLAN-0300 Round 18b/18c. `WS /v1/room/attach` runs a PTY hosting a tmux CLIENT
into a branch's persistent room — the desktop's window over a different wire.

THE THREE THINGS THIS LANE COULD GET WRONG, and none of them is "does it work":

  1. **Killing a room it was only supposed to leave.** Detach is a SIGHUP to the
     client; the session survives. If this ever became a kill, closing a sheet on
     a phone would end an agent mid-task. Pinned by behaviour AND by reading the
     module source for kill-session, because the failure is one word long.

  2. **Leaking the token into a log.** A WebSocket cannot carry an Authorization
     header, and the easy answer — a query parameter — writes the credential into
     every access log, proxy log and browser history entry. The bearer rides the
     subprotocol, and the ACCEPTED protocol is the sentinel rather than the token.

  3. **Spawning a PTY for an unauthenticated caller.** The scope check happens
     BEFORE accept, so a refused socket never reaches a shell.

REAL PTYs, DELIBERATELY. These tests spawn actual processes — `cat` and `echo`,
never tmux and never a room. A mocked PTY would prove the mock's behaviour, and
the interesting failures here (EOF on close, SIGHUP not killing a session,
TIOCSWINSZ argument order) live precisely in the parts a mock invents.
"""

import ast
import errno
import json
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.host import attach as host_attach
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens

PATCH_SECRETS_BASE = "aipass.api.apps.handlers.auth.secrets.SECRETS_BASE"
PATCH_SECRETS_JSON = "aipass.api.apps.handlers.auth.secrets.json_handler"
PATCH_SECRETS_LOGGER = "aipass.api.apps.handlers.auth.secrets.logger"
PATCH_TOKENS_JSON = "aipass.api.apps.handlers.host.tokens.json_handler"
PATCH_TOKENS_LOGGER = "aipass.api.apps.handlers.host.tokens.logger"
PATCH_ATTACH_JSON = "aipass.api.apps.handlers.host.attach.json_handler"
PATCH_ATTACH_LOGGER = "aipass.api.apps.handlers.host.attach.logger"
PATCH_SERVER_JSON = "aipass.api.apps.handlers.host.server.json_handler"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"

pty_required = pytest.mark.skipif(
    not host_attach.is_available(),
    reason="a PTY is a POSIX object and this platform has none",
)

fastapi_required = pytest.mark.skipif(
    not host_server.is_available(),
    reason="the [host] extra is not installed",
)


@pytest.fixture
def quiet():
    """Silence the attach lane's own logging."""
    with patch(PATCH_ATTACH_JSON), patch(PATCH_ATTACH_LOGGER):
        yield


@pytest.fixture
def store(tmp_path: Path):
    """Redirect the token store to a temp dir — no real token is ever touched."""
    with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
        with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER):
            yield tmp_path


@pytest.fixture
def cat_session(quiet: Any):
    """
    A real PTY running `cat` — an echo chamber that proves the pump.

    `cat` is the honest stand-in for a room: it is a real process on a real PTY
    whose behaviour under read, write and hangup is identical to tmux's, and it
    cannot touch anybody's session if a test goes wrong.
    """
    with patch.object(host_attach, "attach_command", lambda branch: ["cat"]):
        session = host_attach.open_attach("api", cwd=None)
        try:
            yield session
        finally:
            session.hangup()


# ==============================================
# THE COMMAND — mirrored from the desktop
# ==============================================


def _chained(command: list) -> list:
    """
    Split a tmux argv into the commands that follow the first `;`.

    Args:
        command: The full argv.

    Returns:
        A list of chained commands, each a list of arguments.
    """
    groups: list = []
    for piece in command:
        if piece == ";":
            groups.append([])
        elif groups:
            groups[-1].append(piece)
    return groups


class TestTheCommandIsTheDesktopsCommand:
    """
    `pty.rs` spawns `tmux new-session -A -t <room>`. This spawns the same thing,
    because a phone and a desktop that build the room name differently end up in
    two rooms with one agent's name on them.
    """

    def test_the_room_name_uses_bauds_prefix(self) -> None:
        """Mirrored, not invented — their desktop names rooms this way."""
        assert host_attach.room_name("memory") == "baud-memory"

    def test_an_address_form_resolves_to_the_same_room(self) -> None:
        """'@memory' and 'memory' are one room, never two."""
        assert host_attach.room_name("@memory") == host_attach.room_name("memory")

    def test_the_command_is_attach_or_create(self) -> None:
        """
        `new-session -A` is the whole lifecycle promise in one flag.

        Without -A a second attach would create a SECOND session; with it, the
        phone joins the room the desktop is already in.
        """
        command = host_attach.attach_command("memory")

        assert command[: command.index(";")] == ["tmux", "new-session", "-A", "-s", "baud-memory"]

    def test_the_room_gets_mouse_and_smallest_sizing(self) -> None:
        """
        A room born through this door must match one born at the desk.

        Without these two, a phone-created room comes up with no scroll lane and
        the `latest` sizing policy — so the phone-only path would get the worst
        geometry of the two doors. `smallest` is @baud's measurement against two
        real clients: it holds the phone through a desk resize and self-heals on
        detach.
        """
        command = host_attach.attach_command("memory")

        assert _chained(command) == [
            ["set-option", "-t", "baud-memory", "mouse", "on"],
            ["set-option", "-w", "-t", "baud-memory", "window-size", "smallest"],
        ]

    def test_every_chained_command_carries_its_own_target(self) -> None:
        """
        The guard @devpulse asked for by name, and the one that would have
        caught the bug @baud found in their own `pty.rs`.

        A chained `set-option` with no `-t` resolves against whatever tmux calls
        the current session. It parses, it exits 0, and whether it reaches the
        room being opened depends on state this code cannot see. Targeting
        explicitly removes the question — and a test that reads the argv is the
        only thing that stops a future edit from dropping one `-t` and leaving a
        command that still looks correct.
        """
        room = "baud-memory"
        chained = _chained(host_attach.attach_command("memory"))

        assert chained, "the whole point is that there ARE chained commands"
        for command in chained:
            assert "-t" in command, f"chained command with no target: {command}"
            assert command[command.index("-t") + 1] == room

    def test_the_separator_is_its_own_argument(self) -> None:
        """
        `;` as a separate argv element is how tmux separates commands with no
        shell involved. Glued to a neighbour it becomes part of a word, and the
        second command silently turns into an argument of the first.
        """
        command = host_attach.attach_command("memory")

        assert ";" in command
        assert not any(piece != ";" and piece.endswith(";") for piece in command)

    def test_the_command_is_a_list_so_it_never_reaches_a_shell(self) -> None:
        """
        A list argv cannot be word-split, so a branch name cannot become one.

        The registry already refuses non-citizens, but defence that costs
        nothing is defence worth keeping.
        """
        command = host_attach.attach_command("memory; rm -rf /")

        assert isinstance(command, list)
        # The whole hostile name survives as ONE element rather than being split
        # into a session name and a second command — including where it is
        # re-used as the -t target of every chained option.
        assert command[command.index("-s") + 1] == "baud-memory; rm -rf /"
        for chained in _chained(command):
            assert chained[chained.index("-t") + 1] == "baud-memory; rm -rf /"


def _evaluated_strings(module: Any) -> list:
    """
    Every string a module actually EVALUATES, docstrings excluded.

    A plain `"kill-session" not in source` reads the prose too, so it forbids the
    comment that explains the design while permitting the argument that breaks
    it. Parsing instead means the guard fires on the tmux subcommand and stays
    quiet about the paragraph promising never to send one.
    """
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
    """
    The property this whole module is built around: detach is not kill.

    Closing a sheet on a phone must never end an agent mid-task, so this lane
    has no way to say so. Both guards read the PARSED module rather than its
    text, because the failure they catch is one word long — and a text grep here
    would forbid the comment explaining the design while permitting the argument
    that breaks it.
    """

    def test_no_string_this_module_evaluates_contains_a_kill(self) -> None:
        """
        kill-session, kill-server, kill-pane — a tmux kill is a literal, and
        this module constructs none.
        """
        offenders = [text for text in _evaluated_strings(host_attach) if "kill" in text.lower()]

        assert offenders == []

    def test_the_module_never_reaches_for_sigkill(self) -> None:
        """
        SIGHUP is a detaching terminal. SIGKILL is an execution.

        A client that will not detach is not a reason to escalate — it is a
        reason to close the descriptor and let tmux notice.
        """
        names = _identifiers(host_attach)

        assert "SIGKILL" not in names
        assert "SIGTERM" not in names
        assert "SIGHUP" in names


# ==============================================
# THE PTY — real processes, real descriptors
# ==============================================


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
        """
        The key bar writes real control bytes — \\x1b[A for Up, and so on.

        Nothing in this lane interprets them, which is why the allowlist the
        capture design needed evaporated with it: a keyboard does not ask
        permission to send an escape sequence.
        """
        cat_session.write(b"\x1b[A\x1b[B\r")

        received = b""
        deadline = time.monotonic() + 5
        while b"\x1b[A" not in received and time.monotonic() < deadline:
            received += cat_session.read()

        assert b"\x1b[A" in received

    def test_read_returns_bytes_never_text(self, cat_session: Any) -> None:
        """
        Decoding here would corrupt partial UTF-8 across a chunk boundary and
        mangle escape sequences. The socket carries binary frames for the same
        reason.
        """
        cat_session.write(b"x\n")

        deadline = time.monotonic() + 5
        data = b""
        while not data and time.monotonic() < deadline:
            data = cat_session.read()

        assert isinstance(data, bytes)

    def test_a_closed_pty_reads_empty_rather_than_raising(self, quiet: Any) -> None:
        """
        EOF is how a PTY reports end-of-life, and the pump reads it as 'stop'.

        Raising instead would turn an ordinary exit into an error the socket
        handler has to special-case.
        """
        with patch.object(host_attach, "attach_command", lambda branch: ["echo", "done"]):
            session = host_attach.open_attach("api")

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if session.read() == b"":
                break

        assert session.read() == b""
        session.hangup()


@pty_required
class TestTheRoomCanActuallyHearAResize:
    """
    The bug that made every resize a no-op, and the two halves of its fix.

    @devpulse traced it on the live server while Patrick's phone painted 80
    columns into a 46-column screen. The evidence chain was: `stty` on the
    client tty read `0 0` at startup; a resize frame DID land in the kernel
    (`stty` then read the new size); and `tmux list-clients` stayed at 80x24
    forever. The resize path worked perfectly and reached nobody.

    TIOCSWINSZ delivers SIGWINCH to the foreground process group of the pty's
    CONTROLLING terminal. `start_new_session=True` made the child a session
    leader with NO controlling terminal — inheriting an already-open descriptor
    never acquires one — so the signal had no destination. The room was deaf.

    Both halves are pinned here, because either one alone still leaves a phone
    rendering against a geometry the room does not have.
    """

    def test_the_pty_opens_at_the_size_the_docstring_promises(self, quiet: Any) -> None:
        """
        openpty hands back 0x0, and a tmux client reads that, calls it invalid
        and falls back to its OWN 80x24. This lane has always DOCUMENTED 80x24
        and until the fix it was true only by that accident — two independent
        defaults agreeing, which is not the same as a contract.
        """
        import fcntl
        import struct
        import termios

        with patch.object(host_attach, "attach_command", lambda branch: ["cat"]):
            session = host_attach.open_attach("api")

        try:
            packed = fcntl.ioctl(session.descriptor, termios.TIOCGWINSZ, b"\0" * 8)
            rows, cols, _, _ = struct.unpack("HHHH", packed)
        finally:
            session.hangup()

        assert (cols, rows) == (host_attach.DEFAULT_COLS, host_attach.DEFAULT_ROWS)
        assert (cols, rows) != (0, 0)

    def test_the_size_is_stamped_before_the_child_exists(self, quiet: Any) -> None:
        """
        Order matters: a client started against a 0x0 terminal has ALREADY
        chosen its fallback by the time a later ioctl arrives. Setting the size
        after Popen would leave startup wrong and only the first resize would
        correct it — which is exactly the symptom, one frame later.
        """
        calls = []

        with patch.object(host_attach, "attach_command", lambda branch: ["cat"]):
            with patch.object(host_attach, "set_winsize", side_effect=lambda *a: calls.append("winsize")):
                with patch.object(host_attach.subprocess, "Popen") as spawn:
                    spawn.side_effect = lambda *a, **k: calls.append("popen") or MagicMock(pid=1)
                    host_attach.open_attach("api")

        assert calls == ["winsize", "popen"]

    def test_the_child_takes_a_controlling_terminal(self, quiet: Any) -> None:
        """
        The half that makes SIGWINCH have a destination.

        `start_new_session=True` is the shape that broke it: a session leader
        with no controlling tty. The preexec_fn does the setsid ITSELF, so the
        signal isolation is kept and the terminal is gained.
        """
        with patch.object(host_attach, "attach_command", lambda branch: ["cat"]):
            with patch.object(host_attach.subprocess, "Popen") as spawn:
                spawn.return_value = MagicMock(pid=1)
                host_attach.open_attach("api")

        kwargs = spawn.call_args.kwargs
        assert kwargs["preexec_fn"] is host_attach._acquire_controlling_tty
        assert "start_new_session" not in kwargs

    def test_the_child_is_still_isolated_from_our_signals(self, quiet: Any) -> None:
        """
        The property `start_new_session` was there for, kept.

        Restarting the host API must never take the operator's room down with
        it, so the child still has to be in its own session — the fix moves that
        into the preexec_fn rather than dropping it.
        """
        with patch.object(host_attach, "attach_command", lambda branch: ["cat"]):
            session = host_attach.open_attach("api")

        try:
            assert os.getpgid(session.process.pid) != os.getpgid(os.getpid())
        finally:
            session.hangup()

    def test_the_preexec_hook_does_no_lookups_in_the_forked_child(self) -> None:
        """
        It runs after fork in a process that HAS threads, where only
        async-signal-safe work is really allowed.

        Everything it needs is bound as a default argument, so the child does no
        attribute lookup, no import and no allocation before exec. This asserts
        the shape rather than the effect, because the effect only shows up as a
        rare deadlock under load — the kind of bug no test catches after the
        fact.
        """
        import inspect

        signature = inspect.signature(host_attach._acquire_controlling_tty)

        assert signature.parameters, "nothing is bound — the child would look it all up"
        for parameter in signature.parameters.values():
            assert parameter.default is not inspect.Parameter.empty

    def test_the_pre_3_11_fallback_does_setsid_then_TIOCSCTTY(self) -> None:
        """
        The branch that never runs on this interpreter, and would ship untested.

        `os.login_tty` is 3.11+; this project supports 3.10, so on those the
        fallback is the ONLY path that claims the terminal — and a mutation
        proved nothing was watching it. Both calls are mocked deliberately: a
        real `os.setsid()` here would detach the test runner from its own
        session, and the default-argument shape that makes the hook fork-safe is
        what makes injecting them possible.

        Order is asserted, not just presence. TIOCSCTTY only grants the terminal
        to a session LEADER, so an ioctl before the setsid fails with EPERM and
        leaves the room exactly as deaf as before.
        """
        order = []
        setsid = MagicMock(side_effect=lambda: order.append("setsid"))
        ioctl = MagicMock(side_effect=lambda *a: order.append("ioctl"))

        host_attach._acquire_controlling_tty(
            _setsid=setsid,
            _login_tty=None,
            _ioctl=ioctl,
            _tiocsctty=1234,
        )

        assert order == ["setsid", "ioctl"]
        ioctl.assert_called_once_with(0, 1234, 0)

    def test_the_hook_claims_the_descriptor_subprocess_actually_hands_it(self) -> None:
        """
        fd 0, and it has to be 0.

        subprocess dup's the slave onto 0, 1 and 2 BEFORE calling preexec_fn, so
        by the time this runs the terminal to claim is stdin. Reaching for the
        original slave descriptor number instead would claim a descriptor that
        may no longer mean anything in the child.
        """
        ioctl = MagicMock()

        host_attach._acquire_controlling_tty(
            _setsid=MagicMock(),
            _login_tty=None,
            _ioctl=ioctl,
            _tiocsctty=1234,
        )

        assert ioctl.call_args.args[0] == 0

    def test_the_login_tty_path_claims_the_same_descriptor(self) -> None:
        """The 3.11+ path targets fd 0 too — one behaviour, two implementations."""
        login_tty = MagicMock()

        host_attach._acquire_controlling_tty(_login_tty=login_tty)

        login_tty.assert_called_once_with(0)

    def test_a_real_child_ends_up_owning_the_terminal(self, quiet: Any) -> None:
        """
        The property itself, on a real process rather than a mock.

        tcgetpgrp on the master answers with the foreground process group of the
        terminal's session — and it only HAS one if something claimed the
        terminal. Before the fix this raised ENOTTY, which is the kernel saying
        'nobody is listening', and is precisely why SIGWINCH went nowhere.
        """
        with patch.object(host_attach, "attach_command", lambda branch: ["cat"]):
            session = host_attach.open_attach("api")

        try:
            time.sleep(0.3)
            foreground = os.tcgetpgrp(session.descriptor)
        finally:
            session.hangup()

        assert foreground > 0
        assert foreground == os.getpgid(session.process.pid)


@pty_required
class TestResizeIsAnIoctlAndItsArgumentsAreOrdered:
    """
    struct winsize is (rows, cols, xpixel, ypixel) — ROWS FIRST.

    Getting that pair backwards produces a room drawing at a plausible but wrong
    shape, which reads as a rendering bug in somebody else's code.
    """

    def test_a_resize_reaches_the_terminal(self, cat_session: Any) -> None:
        """Read the size back off the descriptor rather than trusting the call."""
        import fcntl
        import struct
        import termios

        cat_session.resize(100, 30)

        packed = fcntl.ioctl(cat_session.descriptor, termios.TIOCGWINSZ, b"\0" * 8)
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
        """
        A geometry silently changed is one the client renders against wrongly.

        Same rule as every other cap on this server: refuse, never trim.
        """
        with pytest.raises(host_attach.AttachRefused):
            cat_session.resize(99999, 30)

    def test_a_non_numeric_dimension_is_refused(self, cat_session: Any) -> None:
        """The caller's mistake, named as theirs rather than crashed on."""
        with pytest.raises(host_attach.AttachRefused):
            cat_session.resize("wide", 30)


@pty_required
class TestHangupDetachesAndNeverKillsTheRoom:
    """
    The lifecycle promise, tested against a real process.

    A room outlives its client. That is what makes closing a phone sheet free,
    and it is the single behaviour a bug here would destroy silently.
    """

    def test_hangup_sends_sighup_and_not_a_kill(self, quiet: Any) -> None:
        """The signal itself, captured — a detaching terminal sends SIGHUP."""
        with patch.object(host_attach, "attach_command", lambda branch: ["cat"]):
            session = host_attach.open_attach("api")

        session.process = MagicMock()
        session.hangup()

        session.process.send_signal.assert_called_once_with(signal.SIGHUP)

    def test_hangup_closes_the_descriptor(self, quiet: Any) -> None:
        """A leaked master descriptor per attach is a file handle leak per glance."""
        with patch.object(host_attach, "attach_command", lambda branch: ["cat"]):
            session = host_attach.open_attach("api")

        descriptor = session.descriptor
        session.hangup()

        with pytest.raises(OSError) as caught:
            os.fstat(descriptor)

        assert caught.value.errno == errno.EBADF

    def test_a_second_hangup_touches_nothing(self, quiet: Any) -> None:
        """
        A socket that errors and then closes calls this twice, and the second
        call must be a no-op at the SYSCALL level — not merely quiet.

        Asserting 'it does not raise' would have passed with the guard removed:
        the second close raises EBADF and the handler swallows it. The real
        hazard is worse and silent. Descriptor numbers are REUSED, so by the
        time a stale hangup fires, that integer may belong to another operator's
        attach — and closing it would SUCCEED, killing a session nobody touched.
        That is why the guard is a flag checked first, not a try/except wrapped
        around the close.
        """
        with patch.object(host_attach, "attach_command", lambda branch: ["cat"]):
            session = host_attach.open_attach("api")

        session.hangup()
        session.process = MagicMock()

        with patch.object(host_attach.os, "close") as closer:
            session.hangup()

        assert not closer.called
        assert not session.process.send_signal.called
        assert session.closed is True

    def test_the_child_is_in_its_own_session(self, quiet: Any) -> None:
        """
        start_new_session, so a signal aimed at this server's process group
        cannot take the operator's room down with it.

        Restarting the host API must never end somebody's attached session.
        """
        with patch.object(host_attach, "attach_command", lambda branch: ["cat"]):
            session = host_attach.open_attach("api")

        try:
            assert os.getpgid(session.process.pid) != os.getpgid(os.getpid())
        finally:
            session.hangup()


@pty_required
class TestOpeningAnAttach:
    """What has to be true before a PTY exists at all."""

    def test_a_branch_is_required(self, quiet: Any) -> None:
        """No default room — the same rule every room-targeting lane holds."""
        with pytest.raises(host_attach.AttachRefused):
            host_attach.open_attach("")

    def test_a_missing_tmux_is_named_rather_than_shrugged_at(self, quiet: Any) -> None:
        """'Attach failed' with no subject is a support ticket."""
        with patch.object(host_attach.shutil, "which", return_value=None):
            with pytest.raises(host_attach.AttachUnavailable) as caught:
                host_attach.open_attach("api")

        assert "tmux" in str(caught.value)

    def test_a_failed_spawn_leaks_no_descriptors(self, quiet: Any) -> None:
        """
        The error path is where descriptors leak, because nobody exercises it.

        Counted before and after: a spawn that raises must give both ends back.
        """
        before = len(os.listdir("/proc/self/fd"))

        with patch.object(host_attach.subprocess, "Popen", side_effect=OSError("no exec")):
            for _ in range(5):
                with pytest.raises(host_attach.AttachUnavailable):
                    host_attach.open_attach("api")

        assert len(os.listdir("/proc/self/fd")) <= before + 1

    def test_the_room_is_created_in_the_branch_directory(self, quiet: Any, tmp_path: Path) -> None:
        """
        Attach-or-create lands somewhere that makes sense.

        A room created wherever the server happened to start is a shell in the
        wrong directory, which is worse than no shell — it looks right.
        """
        with patch.object(host_attach, "attach_command", lambda branch: ["pwd"]):
            with patch.object(host_attach.subprocess, "Popen") as spawn:
                spawn.return_value = MagicMock(pid=1234)
                host_attach.open_attach("api", cwd=tmp_path)

        assert spawn.call_args.kwargs["cwd"] == str(tmp_path)

    def test_the_child_gets_a_usable_term(self, quiet: Any, tmp_path: Path) -> None:
        """
        A client inheriting a bare TERM renders in the wrong capability set,
        which looks like an application bug rather than an environment one.
        """
        with patch.object(host_attach, "attach_command", lambda branch: ["pwd"]):
            with patch.object(host_attach.subprocess, "Popen") as spawn:
                spawn.return_value = MagicMock(pid=1234)
                host_attach.open_attach("api")

        assert spawn.call_args.kwargs["env"]["TERM"] == "xterm-256color"


# ==============================================
# SOCKET AUTH — the token never lands in a log
# ==============================================


@fastapi_required
class TestTheBearerRidesTheSubprotocolAndNeverTheUrl:
    """
    A WebSocket cannot carry an Authorization header. The query string is
    disqualified because URLs are written to access logs, proxy logs and browser
    history — three permanent copies of a credential nobody chose to make.
    """

    def _socket(self, protocols: str) -> Any:
        """A stand-in connection carrying the offered subprotocols."""
        socket = MagicMock()
        socket.headers = {"sec-websocket-protocol": protocols}
        return socket

    def test_a_valid_bearer_authenticates(self, store: Any) -> None:
        """The happy path, so the refusals below mean something."""
        record, raw = host_tokens.issue_token("pixel-8", scope="operate")

        authenticated = host_server.socket_bearer(self._socket(f"aipass.bearer, {raw}"))

        assert authenticated["id"] == record["id"]

    def test_the_token_alone_is_not_enough(self, store: Any) -> None:
        """
        Without the sentinel there is nothing to echo back, and a handshake that
        cannot echo a protocol fails in the browser anyway.
        """
        _, raw = host_tokens.issue_token("pixel-8", scope="operate")

        with pytest.raises(PermissionError):
            host_server.socket_bearer(self._socket(raw))

    def test_the_sentinel_alone_is_not_enough(self, store: Any) -> None:
        """An offer with no credential in it is an anonymous caller."""
        with pytest.raises(PermissionError):
            host_server.socket_bearer(self._socket("aipass.bearer"))

    def test_no_header_at_all_is_refused(self, store: Any) -> None:
        """Anonymous is not a scope."""
        with pytest.raises(PermissionError):
            host_server.socket_bearer(self._socket(""))

    def test_a_reordered_offer_still_works(self, store: Any) -> None:
        """
        Protocol order is the client's to choose, and a 401 that depends on it
        would be unexplainable from the phone end.
        """
        _, raw = host_tokens.issue_token("pixel-8", scope="operate")

        assert host_server.socket_bearer(self._socket(f"{raw}, aipass.bearer")) is not None

    def test_an_unknown_token_is_refused(self, store: Any) -> None:
        """Same wall as the HTTP lane, same store, same compare."""
        with pytest.raises(PermissionError):
            host_server.socket_bearer(self._socket("aipass.bearer, not-a-real-token"))

    def test_a_revoked_token_is_refused_on_the_next_connection(self, store: Any) -> None:
        """
        Revocation works here for free, because the store is re-read per
        connection exactly as it is per request.
        """
        record, raw = host_tokens.issue_token("pixel-8", scope="operate")
        host_tokens.revoke_token(record["id"])

        with pytest.raises(PermissionError):
            host_server.socket_bearer(self._socket(f"aipass.bearer, {raw}"))

    def test_a_read_token_cannot_attach(self, store: Any) -> None:
        """
        An attached room is a shell prompt. There is no reading half of that, so
        there is no read-scope attach.
        """
        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        with pytest.raises(PermissionError):
            host_server.socket_bearer(self._socket(f"aipass.bearer, {raw}"))

    def test_the_accepted_protocol_is_the_sentinel_never_the_token(self) -> None:
        """
        The accepted subprotocol appears in the handshake RESPONSE.

        Echoing the token back would undo the entire reason it is not in the
        query string — it would simply move the leak from the request line to
        the response header.
        """
        source = Path(host_server.__file__).read_text(encoding="utf-8")

        assert "await websocket.accept(subprotocol=host_attach.BEARER_SUBPROTOCOL)" in source

    def test_the_route_takes_no_token_query_parameter(self) -> None:
        """
        The disqualified design, pinned so it cannot come back as a convenience.

        A token in a URL is a credential in every access log on the path.
        """
        source = Path(host_server.__file__).read_text(encoding="utf-8")
        route = source[source.index('@app.websocket("/v1/room/attach")') :]
        signature = route[: route.index(") -> None:")]

        assert "token" not in signature
        assert "bearer" not in signature.lower()


@fastapi_required
class TestTheAttachRouteIsRegisteredAsASocket:
    """The route table read back — a socket is not an HTTP route."""

    def test_the_socket_route_exists(self) -> None:
        """One attach endpoint, and it is a WebSocket."""
        app = host_server.create_app()
        sockets = [
            route.path
            for route in app.routes
            if getattr(route, "path", "") == "/v1/room/attach" and not hasattr(route, "methods")
        ]

        assert sockets == ["/v1/room/attach"]

    def test_no_http_verb_answers_the_attach_path(self) -> None:
        """
        A GET that 200s here would be a second, unauthenticated way in.

        FastAPI keeps sockets and routes separate, and this asserts nobody has
        added an HTTP twin beside it.
        """
        app = host_server.create_app()
        http = [
            route.path
            for route in app.routes
            if getattr(route, "path", "") == "/v1/room/attach" and hasattr(route, "methods")
        ]

        assert http == []


@fastapi_required
class TestTheSocketRefusesBeforeItSpawns:
    """
    A PTY for an unauthenticated caller is a shell for an unauthenticated
    caller. The scope check happens before accept, so it never gets that far.
    """

    def test_an_unauthenticated_socket_never_opens_a_pty(self, store: Any) -> None:
        """The wall stops the mechanism, not just the response."""
        from fastapi.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        with patch(PATCH_SERVER_LOGGER), patch(PATCH_SERVER_JSON):
            with patch.object(host_attach, "open_attach") as spawn:
                client = TestClient(host_server.create_app())

                with pytest.raises(WebSocketDisconnect):
                    with client.websocket_connect("/v1/room/attach?branch=api"):
                        pass

                assert not spawn.called

    def test_an_authenticated_caller_gets_a_readable_refusal(self, store: Any) -> None:
        """
        A refusal the operator can ACT on has to reach the screen.

        A browser only surfaces a close code and reason on an ESTABLISHED
        socket; refusing an unknown branch pre-accept would put a fixable
        sentence where the phone cannot render it — a blank error screen holding
        the answer. So auth refuses before accept and everything after it
        refuses on an open socket.
        """
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")

        with patch(PATCH_SERVER_LOGGER), patch(PATCH_SERVER_JSON):
            with patch.object(host_attach, "open_attach") as spawn:
                spawn.side_effect = host_attach.AttachRefused("Unknown branch: @nope")
                client = TestClient(host_server.create_app())

                with client.websocket_connect(
                    "/v1/room/attach?branch=nope", subprotocols=["aipass.bearer", raw]
                ) as socket:
                    closed = socket.receive()

        assert closed["type"] == "websocket.close"
        assert closed["code"] == 1008
        assert "Unknown branch" in closed["reason"]

    def test_a_server_side_failure_closes_on_its_own_code(self, store: Any) -> None:
        """
        1011 is 'ours', 1008 is 'yours' — the same split the HTTP lanes make
        between 503 and 400, so the phone can tell the operator whether to fix
        something or wait for someone else to.
        """
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")

        with patch(PATCH_SERVER_LOGGER), patch(PATCH_SERVER_JSON):
            with patch.object(host_attach, "open_attach") as spawn:
                spawn.side_effect = host_attach.AttachUnavailable("tmux is not installed on this host")
                client = TestClient(host_server.create_app())

                with client.websocket_connect(
                    "/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]
                ) as socket:
                    closed = socket.receive()

        assert closed["code"] == 1011
        assert "tmux" in closed["reason"]

    def test_the_accepted_socket_carries_only_the_sentinel(self, store: Any) -> None:
        """
        The handshake response, read back off a real connection.

        The token must not appear in it — echoing it would move the leak from
        the request line to the response header and change nothing else.
        """
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")

        with patch(PATCH_SERVER_LOGGER), patch(PATCH_SERVER_JSON):
            with patch.object(host_attach, "open_attach") as spawn:
                spawn.side_effect = host_attach.AttachRefused("stop here")
                client = TestClient(host_server.create_app())

                with client.websocket_connect(
                    "/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]
                ) as socket:
                    accepted = socket.accepted_subprotocol

        assert accepted == host_attach.BEARER_SUBPROTOCOL
        assert accepted != raw


class StubSession:
    """
    A session that records instead of running, but REFUSES for real.

    `resize` delegates to the module's own `_require_dimension`, so a bad frame
    driven through the live socket hits the same validation a real PTY would.
    Only the syscall is absent; the decision is the production one.
    """

    def __init__(self) -> None:
        self.room = "baud-api"
        self.writes: list = []
        self.resizes: list = []
        self.hangups = 0
        self._release = threading.Event()

    def read(self, size: int = 0) -> bytes:
        """Block like a quiet room, until the pump is torn down."""
        self._release.wait(timeout=10)
        return b""

    def write(self, data: bytes) -> None:
        """Record what was typed into the room."""
        self.writes.append(data)

    def resize(self, cols: object, rows: object) -> None:
        """Validate for real, then record."""
        self.resizes.append(
            (host_attach._require_dimension(cols, "cols"), host_attach._require_dimension(rows, "rows"))
        )

    def hangup(self) -> None:
        """Release the blocked reader so the pump can finish."""
        self.hangups += 1
        self._release.set()


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
    """
    The branch @baud could not test from their end, handed back on purpose.

    Their client's cols/rows come from FitAddon and are guarded > 0, so it has
    no path that produces a bad resize — which means my contract's "refused,
    dropped, never fatal" was untested in both directions. Their words: yours to
    keep honest.

    The hazard is specific and quiet: an exception escaping the control handler
    kills the pump, which hangs up the session, which detaches an operator
    mid-task because a frame had a typo in it. Driven through a REAL socket
    against the REAL handler — re-implementing the parse here would only prove
    the test could parse JSON.
    """

    def test_every_bad_frame_is_dropped_and_the_room_survives_all_of_them(self, store: Any) -> None:
        """
        Thirteen malformed frames down one socket, then a good one.

        Three assertions, and the middle one is the sharp one: not a single bad
        frame reached `write`. A control frame falling through to the write path
        would type JSON into the operator's shell, and on a room sitting at a
        prompt that is a command.
        """
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        session = StubSession()

        with patch(PATCH_SERVER_LOGGER), patch(PATCH_SERVER_JSON):
            with patch.object(host_attach, "open_attach", return_value=session):
                client = TestClient(host_server.create_app())
                with client.websocket_connect(
                    "/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]
                ) as socket:
                    for frame in BAD_CONTROL_FRAMES:
                        socket.send_text(frame)

                    # A good one last: the socket has to still be carrying
                    # traffic after all of that, not merely still be open.
                    socket.send_text('{"type": "resize", "cols": 72, "rows": 44}')

                    deadline = time.monotonic() + 10
                    while not session.resizes and time.monotonic() < deadline:
                        time.sleep(0.01)

        assert session.resizes == [(72, 44)]
        assert session.writes == []
        assert session.hangups == 1

    def test_a_bad_frame_does_not_stop_the_keystrokes_that_follow_it(self, store: Any) -> None:
        """
        Recovery on the OTHER channel.

        A session that survives a bad control frame but stops forwarding
        keystrokes is broken in the way that matters — the operator is looking
        at a live room that has quietly stopped listening.
        """
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        session = StubSession()

        with patch(PATCH_SERVER_LOGGER), patch(PATCH_SERVER_JSON):
            with patch.object(host_attach, "open_attach", return_value=session):
                client = TestClient(host_server.create_app())
                with client.websocket_connect(
                    "/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]
                ) as socket:
                    socket.send_text('{"type": "resize", "cols": 0, "rows": 0}')
                    socket.send_bytes(b"echo still-listening")
                    socket.send_bytes(b"\r")

                    deadline = time.monotonic() + 10
                    while len(session.writes) < 2 and time.monotonic() < deadline:
                        time.sleep(0.01)

        assert session.writes == [b"echo still-listening", b"\r"]

    def test_a_disconnect_on_a_SILENT_room_still_detaches_promptly(self, store: Any) -> None:
        """
        The bug this file found, pinned so it cannot come back.

        The pump used to `gather` both directions, which waits for BOTH. On a
        quiet room that deadlocks: the phone closes the sheet, `socket_to_room`
        ends, and `room_to_socket` is still parked in a blocking `os.read` that
        will not return until the room happens to print something. The detach —
        and the SIGHUP with it — waited on output that might never come, and the
        executor thread stayed parked alongside it. One leaked thread and one
        undetached tmux client per closed sheet, on the most ordinary path there
        is: closing a sheet on an idle agent.

        The stub's read blocks for ten seconds and produces NOTHING, which is
        exactly a silent room. If the hangup waited on it, this test would take
        ten seconds; the timing assertion is the whole point.
        """
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        session = StubSession()

        with patch(PATCH_SERVER_LOGGER), patch(PATCH_SERVER_JSON):
            with patch.object(host_attach, "open_attach", return_value=session):
                client = TestClient(host_server.create_app())
                started = time.monotonic()
                with client.websocket_connect("/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]):
                    pass
                elapsed = time.monotonic() - started

        assert session.hangups == 1
        assert elapsed < 5

    def test_the_pump_waits_for_the_first_direction_not_both(self) -> None:
        """
        The fix, named at the source.

        `gather` is the shape that deadlocked. A future tidy-up that reads
        `asyncio.wait(..., FIRST_COMPLETED)` as a needlessly complicated gather
        would reintroduce the hang, and the timing test above would only catch
        it as a mysterious slow test.
        """
        source = Path(host_server.__file__).read_text(encoding="utf-8")
        pump = source[source.index("async def _pump(") : source.index("def _handle_control(")]

        assert "return_when=asyncio.FIRST_COMPLETED" in pump
        # hangup comes FIRST in the finally: closing the descriptor is what
        # breaks the blocked reader out of os.read. Cancelling alone would not —
        # a thread sitting in a syscall does not notice an asyncio cancellation.
        assert pump.index("session.hangup()") < pump.index("task.cancel()")

    def test_the_handler_swallows_a_refusal_rather_than_killing_the_pump(self) -> None:
        """
        The wiring, read at the source as well as driven.

        An AttachRefused escaping `_handle_control` would propagate out of the
        socket reader, end the gather, and hang up a live session over a typo in
        a resize frame. This names the except clause standing between a bad
        frame and a detached operator, so removing it fails here loudly rather
        than only through a timing-dependent socket test.
        """
        source = Path(host_server.__file__).read_text(encoding="utf-8")
        handler = source[source.index("def _handle_control(") : source.index('@app.get("/", include_in_schema=False)')]

        assert "except (host_attach.AttachRefused, host_attach.AttachUnavailable, OSError)" in handler
        assert "raise" not in handler


def test_the_session_is_created_once_per_socket_not_per_poll() -> None:
    """
    @baud's bug, checked for its SHAPE on this side rather than assumed absent.

    Theirs: the attach effect depended on the branch CARD object, and the fleet
    re-polls every ten seconds handing down a fresh object — so the effect
    re-ran per poll, opening a new socket and a new pty and RE-TYPING the launch
    line into the room every ten seconds. Invisible in the UI, obvious in a byte
    log. They asked me to check whether anything here keys a session off a value
    a poll refreshes.

    It does not, and this is what makes that structural: open_attach is called
    exactly once in this module, inside the socket handler, so a session's
    lifetime is a connection's lifetime. There is no polling loop on this side
    to re-fire it.
    """
    source = Path(host_server.__file__).read_text(encoding="utf-8")

    assert source.count("host_attach.open_attach(") == 1

    route = source[source.index('@app.websocket("/v1/room/attach")') : source.index("def _audit_socket_refusal(")]
    assert "while" not in route


def test_the_control_frame_is_json_and_resize_is_the_only_verb() -> None:
    """
    Text frames are CONTROL, binary frames are KEYSTROKES.

    That split is what lets a resize travel on the same socket without a resize
    message ever being mistaken for something the operator typed — and it is why
    an unparseable control frame is ignored rather than written to the room.
    """
    source = Path(host_server.__file__).read_text(encoding="utf-8")
    handler = source[source.index("def _handle_control(") : source.index('@app.get("/", include_in_schema=False)')]

    assert 'message.get("type") != "resize"' in handler
    assert "session.write" not in handler
    assert json.loads('{"type": "resize", "cols": 80, "rows": 24}')["type"] == "resize"


def test_a_blocking_read_never_runs_on_the_event_loop() -> None:
    """
    The PTY read blocks. On a single-worker uvicorn, a blocking read on the loop
    freezes every other request this server is serving — which is the whole
    phone, including the fleet card the operator is looking at.
    """
    source = Path(host_server.__file__).read_text(encoding="utf-8")

    assert "run_in_executor(None, session.read)" in source


def test_the_pump_always_hangs_up() -> None:
    """
    A pump that raises must still detach.

    Otherwise the room keeps a client attached to a socket nobody is holding,
    and the operator's next attach lands in a session with a ghost in it.
    """
    source = Path(host_server.__file__).read_text(encoding="utf-8")
    pump = source[source.index("async def _pump(") : source.index("def _handle_control(")]

    assert "finally:" in pump
    assert "session.hangup()" in pump
