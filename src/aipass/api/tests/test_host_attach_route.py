# =================== AIPass ====================
# Name: test_host_attach_route.py
# Description: Tests for the attach route and its seats — opening, socket auth, watches, outside rooms, the ping
# Version: 1.0.3
# Created: 2026-10-08
# Modified: 2026-10-19
# =============================================

"""Tests for the WS /v1/room/attach route in apps/handlers/host/server.py and open_attach/open_monitor in attach.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered) — issue_token() and the token store's own locking, tests/test_host_token_store.py
# seedgo: no-test-needed(generated) — the tmux client that attach_command() builds; these tests spawn cat, never tmux

import ast
import errno
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.host import attach as host_attach
from aipass.api.apps.handlers.host import denials as host_denials
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens
from aipass.api.apps.handlers.host import verbs as host_verbs
from aipass.api.tests.support_host_attach import (
    TMUX_STANDIN,
    StubSession,
    _forced_tmux_which,
    detach_and_wait,
    fastapi_required,
    pty_required,
    wait_for_log,
)

# Own constants, not the support module's: discarded_patch judges a target imported from this package.
PATCH_ATTACH_JSON = "aipass.api.apps.handlers.host.attach.json_handler"
PATCH_ATTACH_LOGGER = "aipass.api.apps.handlers.host.attach.logger"
PATCH_SERVER_JSON = "aipass.api.apps.handlers.host.server.json_handler"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"
PATCH_PUMP_LOGGER = "aipass.api.apps.handlers.host.pump.logger"


# Portable: Linux symlinks /dev/fd to /proc/self/fd, macOS mounts fdescfs there; /proc is Linux-only.
FD_DIR = "/dev/fd"


def _open_descriptors(listdir: Any = None) -> int:
    """Count the descriptors this process holds open."""
    lister = listdir if listdir is not None else os.listdir
    return len(lister(FD_DIR))


fd_census_required = pytest.mark.skipif(
    not os.path.isdir(FD_DIR),
    reason="this host exposes no /dev/fd, so open descriptors cannot be counted",
)


@pty_required
class TestOpeningAnAttach:
    """What has to be true before a PTY exists at all."""

    def test_a_branch_is_required(self, quiet: Any) -> None:
        """No default room — the same rule every room-targeting lane holds."""
        with pytest.raises(host_attach.AttachRefused):
            host_attach.open_attach("")

    def test_a_room_override_needs_no_branch(self, quiet: Any, tmux_preflight: Any, tmp_path: Path) -> None:
        """The shell door: a named room IS the subject, so the branch-required
        rule steps aside, and the label falls back to the room name."""
        attached_to = []
        with patch.object(host_attach, "client_command", lambda room: attached_to.append(room) or ["cat"]):
            session = host_attach.open_attach("", cwd=tmp_path, room="baud-shell-aipass")

        try:
            assert attached_to == ["baud-shell-aipass"]
            assert session.branch == "baud-shell-aipass"
            assert session.room == attached_to[0]
        finally:
            session.hangup()

    def test_a_watch_is_read_only_at_the_layer_that_counts(self, quiet: Any, tmp_path: Path) -> None:
        """The desktop holds the no-keyboard line twice — xterm's `disableStdin`
        up top and `pty_write`'s refusal underneath; the SESSION refusing is what makes tier-0 a contract."""
        with patch.object(host_attach, "monitor_command", lambda target: ["cat"]):
            session = host_attach.open_monitor("seedgo", cwd=tmp_path)

        try:
            assert session.read_only
            assert session.room == "watch-seedgo"
            with pytest.raises(host_attach.AttachRefused):
                session.write(b"echo hijacked\n")
        finally:
            session.hangup()

    def test_a_watch_target_is_fenced_before_anything_spawns(self, quiet: Any) -> None:
        """A refused target never reaches a PTY, let alone a process."""
        with patch.object(host_attach.subprocess, "Popen") as spawn:
            with pytest.raises(host_attach.AttachRefused):
                host_attach.open_monitor("seedgo; rm -rf /")

        spawn.assert_not_called()

    @pytest.mark.parametrize("room", [";", "-t", "a;b", "a b", "a.b", "a:b", "a\nb"])
    def test_a_room_name_outside_the_charset_is_refused_before_any_spawn(
        self, quiet: Any, tmux_preflight: Any, room: str
    ) -> None:
        """A lone ';' is tmux's command separator and '-' opens an option: refused before argv reaches a process."""
        for attach_only in (False, True):
            with patch.object(host_attach, "_spawn_pty", side_effect=AssertionError("spawned")) as spawn:
                with pytest.raises(host_attach.AttachRefused):
                    host_attach.open_attach("memory", room=room, attach_only=attach_only)

            spawn.assert_not_called()

    def test_a_room_override_wins_over_the_naming_rule(self, quiet: Any, tmux_preflight: Any, tmp_path: Path) -> None:
        """A branch AND a room: the room decides the name, the branch the label."""
        with patch.object(host_attach.subprocess, "Popen") as spawn:
            spawn.return_value = MagicMock(pid=1234)
            session = host_attach.open_attach("devpulse", cwd=tmp_path, room="baud-shell-aipass-devpulse")

        command = spawn.call_args.args[0]
        assert command[: command.index(";")] == ["tmux", "new-session", "-A", "-s", "baud-shell-aipass-devpulse"]
        assert session.room == "baud-shell-aipass-devpulse"
        assert session.branch == "devpulse"

    def test_a_missing_tmux_is_named_rather_than_shrugged_at(self, quiet: Any) -> None:
        """'Attach failed' with no subject is a support ticket."""
        with patch.object(host_attach, "TMUX_BINARY", "aipass-no-such-tmux"):
            with pytest.raises(host_attach.AttachUnavailable) as caught:
                host_attach.open_attach("api")

        assert str(caught.value).startswith("aipass-no-such-tmux is not installed on this host")
        assert "tmux client" in str(caught.value)

    def test_a_pty_case_opens_on_a_host_that_has_no_tmux(self, quiet: Any, monkeypatch: Any) -> None:
        """The other half of the case above, and the whole macOS red in one line."""
        # `which` answers None for EVERY binary, a tmux-less runner; the forced rule must still open the session.
        empty_host = MagicMock(return_value=None)
        monkeypatch.setattr(host_attach.shutil, "which", _forced_tmux_which(empty_host))

        with patch.object(host_attach, "attach_command", lambda branch, scope="": ["cat"]):
            session = host_attach.open_attach("api")

        try:
            assert session.room == "baud-api"
            assert session.process.pid > 0, "no child on a host the preflight was supposed to let through"
            assert not empty_host.called, "tmux must be answered by the rule, never looked up on this host"
        finally:
            session.hangup()

    def test_the_forced_preflight_answers_for_tmux_and_nothing_else(self, tmux_preflight: Any) -> None:
        """A fixture that answered a path for every binary would be a lie with
        reach: the monitor lane runs its own `shutil.which` preflight on drone."""
        assert host_attach.shutil.which(host_attach.TMUX_BINARY) == TMUX_STANDIN
        assert host_attach.shutil.which("aipass-binary-that-exists-on-no-host") is None

    @fd_census_required
    def test_a_failed_spawn_leaks_no_descriptors(self, quiet: Any, tmux_preflight: Any) -> None:
        """The error path is where descriptors leak, because nobody exercises it."""
        before = _open_descriptors()

        with patch.object(host_attach.subprocess, "Popen", side_effect=OSError("no exec")):
            for _ in range(5):
                with pytest.raises(host_attach.AttachUnavailable):
                    host_attach.open_attach("api")

        assert _open_descriptors() <= before + 1

    @fd_census_required
    def test_the_descriptor_census_counts_this_process_without_proc(self) -> None:
        """The instrument above, measured on a host that has no /proc."""
        # It must also SEE a descriptor: a census answering a constant passes the leak test while leaking.
        real_listdir = os.listdir

        def no_proc(path: Any, *args: Any, **kwargs: Any) -> Any:
            if str(path).startswith("/proc"):
                raise FileNotFoundError(errno.ENOENT, "No such file or directory", str(path))
            return real_listdir(path, *args, **kwargs)

        before = _open_descriptors(no_proc)
        holder = open(os.devnull, "rb")
        try:
            assert _open_descriptors(no_proc) == before + 1, "the census does not see this process's own descriptors"
        finally:
            holder.close()

    def test_the_room_is_created_in_the_branch_directory(self, quiet: Any, tmux_preflight: Any, tmp_path: Path) -> None:
        """Attach-or-create lands somewhere that makes sense."""
        with patch.object(host_attach, "attach_command", lambda branch, scope="": ["pwd"]):
            with patch.object(host_attach.subprocess, "Popen") as spawn:
                spawn.return_value = MagicMock(pid=1234)
                host_attach.open_attach("api", cwd=tmp_path)

        assert spawn.call_args.kwargs["cwd"] == str(tmp_path)

    def test_the_child_gets_a_usable_term(self, quiet: Any, tmux_preflight: Any, tmp_path: Path) -> None:
        """A client inheriting a bare TERM renders in the wrong capability set,
        which looks like an application bug rather than an environment one."""
        with patch.object(host_attach, "attach_command", lambda branch, scope="": ["pwd"]):
            with patch.object(host_attach.subprocess, "Popen") as spawn:
                spawn.return_value = MagicMock(pid=1234)
                host_attach.open_attach("api")

        assert spawn.call_args.kwargs["env"]["TERM"] == "xterm-256color"


@fastapi_required
class TestTheBearerRidesTheSubprotocolAndNeverTheUrl:
    """A WebSocket cannot carry an Authorization header. The query string is
    disqualified because URLs are written to access logs, proxy logs and browser history."""

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
        """Without the sentinel there is nothing to echo back, and a handshake that
        cannot echo a protocol fails in the browser anyway."""
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
        """Protocol order is the client's to choose, and a 401 that depends on it
        would be unexplainable from the phone end."""
        record, raw = host_tokens.issue_token("pixel-8", scope="operate")

        assert host_server.socket_bearer(self._socket(f"{raw}, aipass.bearer"))["id"] == record["id"]

    def test_an_unknown_token_is_refused(self, store: Any) -> None:
        """Same wall as the HTTP lane, same store, same compare."""
        with pytest.raises(PermissionError):
            host_server.socket_bearer(self._socket("aipass.bearer, not-a-real-token"))

    def test_a_revoked_token_is_refused_on_the_next_connection(self, store: Any) -> None:
        """Revocation works here for free, because the store is re-read per
        connection exactly as it is per request."""
        record, raw = host_tokens.issue_token("pixel-8", scope="operate")
        host_tokens.revoke_token(record["id"])

        with pytest.raises(PermissionError):
            host_server.socket_bearer(self._socket(f"aipass.bearer, {raw}"))

    def test_a_read_token_cannot_attach(self, store: Any) -> None:
        """An attached room is a shell prompt. There is no reading half of that, so
        there is no read-scope attach."""
        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        with pytest.raises(PermissionError):
            host_server.socket_bearer(self._socket(f"aipass.bearer, {raw}"))

    def test_the_accepted_protocol_is_the_sentinel_never_the_token(self) -> None:
        """The accepted subprotocol appears in the handshake RESPONSE."""
        source = Path(host_server.__file__).read_text(encoding="utf-8")

        assert "await websocket.accept(subprotocol=host_attach.BEARER_SUBPROTOCOL)" in source

    def test_the_route_takes_no_token_query_parameter(self) -> None:
        """The disqualified design, pinned so it cannot come back as a convenience."""
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
        """A GET that 200s here would be a second, unauthenticated way in."""
        app = host_server.create_app()
        http = [
            route.path
            for route in app.routes
            if getattr(route, "path", "") == "/v1/room/attach" and hasattr(route, "methods")
        ]

        assert http == []


@fastapi_required
class TestTheSocketRefusesBeforeItSpawns:
    """A PTY for an unauthenticated caller is a shell for an unauthenticated
    caller. The scope check happens before accept, so it never gets that far."""

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

    def test_an_authenticated_caller_gets_a_readable_refusal(self, store: Any, seated: Any) -> None:
        """A refusal the operator can ACT on has to reach the screen."""
        # A browser shows a close reason only on an ESTABLISHED socket, so only auth refuses before accept.
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

    def test_a_server_side_failure_closes_on_its_own_code(self, store: Any, seated: Any) -> None:
        """1011 is 'ours', 1008 is 'yours' — the same split the HTTP lanes make
        between 503 and 400."""
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
        # The close reason is a response too: the fixed sentence, never the exception's words.
        assert closed["reason"] == host_denials.SOCKET_UNAVAILABLE
        assert "tmux" not in closed["reason"]

    def test_the_accepted_socket_carries_only_the_sentinel(self, store: Any) -> None:
        """The handshake response, read back off a real connection."""
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


class TestGlobalMissionControlIsReachable:
    """The watch lane must be able to express `drone @prax monitor run` — bare."""

    def test_no_target_drops_the_argument_entirely(self) -> None:
        """The desktop's argv, character for character — nothing trailing."""
        assert host_attach.monitor_command("") == ["drone", "@prax", "monitor", "run"]

    def test_the_synonym_is_deliberately_not_used(self) -> None:
        """@prax documents `run all` for the same thing. This lane mirrors the
        DESKTOP's argv, so if the two ever diverge the phone diverges with the desk."""
        assert "all" not in host_attach.monitor_command("")

    @pty_required
    def test_the_global_watch_actually_opens(self, quiet: Any, tmp_path: Path) -> None:
        """End to end through open_monitor, with no target at all."""
        with patch.object(host_attach, "monitor_command", lambda target="": ["cat"]):
            session = host_attach.open_monitor(cwd=tmp_path)

        try:
            assert session.read_only
            assert session.room == host_attach.GLOBAL_WATCH_LABEL
        finally:
            session.hangup()

    @pty_required
    def test_a_targetless_watch_is_named_not_blank(self, quiet: Any, tmp_path: Path) -> None:
        """'watch-' with nothing after it reads as a truncated name. A watch over
        everything has a name of its own so a log line says what it was."""
        with patch.object(host_attach, "monitor_command", lambda target="": ["cat"]):
            session = host_attach.open_monitor("", cwd=tmp_path)

        try:
            assert session.room == "watch-all"
            assert session.branch == "watch-all"
        finally:
            session.hangup()

    @pytest.mark.parametrize(
        "garbage",
        ["seedgo; rm -rf /", "SEEDGO", "a b", "../etc", "seedgo && curl evil", "$(whoami)", "run all", "--relay", "-x"],
    )
    def test_garbage_is_still_refused_before_anything_spawns(self, quiet: Any, garbage: str, monkeypatch) -> None:
        """Making absence reachable must not make anything ELSE reachable."""
        # PTY_AVAILABLE forced so the FENCE answers on every platform; the platform gate stands in front of it.
        monkeypatch.setattr(host_attach, "PTY_AVAILABLE", True)
        # No drone on PATH: the fence must answer before the PATH check, not lean on the argv builder behind it.
        which = MagicMock(return_value=None)
        monkeypatch.setattr(host_attach.shutil, "which", which)
        with patch.object(host_attach.subprocess, "Popen") as spawn:
            with pytest.raises(host_attach.AttachRefused):
                host_attach.open_monitor(garbage)

        which.assert_not_called()
        spawn.assert_not_called()

    def test_a_pty_less_platform_is_refused_in_words_before_the_fence(self, quiet: Any) -> None:
        """The Windows contract, pinned from every platform: no PTY means the
        honest sentence, raised before the fence or any spawn is consulted."""
        with patch.object(host_attach, "PTY_AVAILABLE", False):
            with patch.object(host_attach.subprocess, "Popen") as spawn:
                with pytest.raises(host_attach.AttachUnavailable) as refusal:
                    host_attach.open_monitor("seedgo")

        assert "PTY is a POSIX object" in str(refusal.value)
        spawn.assert_not_called()

    @pty_required
    def test_whitespace_is_absence_not_a_target(self, quiet: Any, tmp_path: Path) -> None:
        """A target of spaces is nobody named, which is the global form."""
        with patch.object(host_attach, "monitor_command", lambda target="": ["cat"]):
            session = host_attach.open_monitor("   ", cwd=tmp_path)

        try:
            assert session.room == host_attach.GLOBAL_WATCH_LABEL
        finally:
            session.hangup()


@fastapi_required
class TestAWatchIsNotAnchorTooling:
    """The parked external-watch refusal, ruled against and measured out."""

    # @prax's output is identical from any cwd and it already says on screen what it cannot show.

    @pty_required
    def test_a_tenant_project_watch_is_not_refused(self, quiet: Any, tmp_path: Path) -> None:
        """BAUD lives in projects/ and @prax scopes to it. Measured, not assumed."""
        with patch.object(host_attach, "monitor_command", lambda target="": ["cat"]):
            session = host_attach.open_monitor("baud", cwd=tmp_path)

        try:
            assert session.room == "watch-baud"
        finally:
            session.hangup()

    def test_the_refusal_sentence_is_gone_from_the_socket_lane(self) -> None:
        """Grep-shaped because this fence lived in exactly one branch of one route
        and the reasoning that justified it was measured false."""
        source = Path(host_server.__file__).read_text(encoding="utf-8")

        assert "@prax monitors the seat, not" not in source

    def test_an_external_project_watch_opens_instead_of_refusing(self, store: Any, seated: Any, tmp_path: Path) -> None:
        """The parked refusal, through the real socket."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="read")

        # Only the existence gate is stubbed: the fleet census is a live machine fact, absent on a fresh runner.
        with patch(PATCH_SERVER_LOGGER), patch(PATCH_SERVER_JSON):
            with patch.object(host_verbs.host_reads, "resolve_branch_root", return_value=tmp_path / "vera") as gate:
                with patch.object(host_attach, "open_monitor") as spawn:
                    spawn.side_effect = host_attach.AttachUnavailable("stop here, the fence is what is under test")
                    client = TestClient(host_server.create_app())

                    with client.websocket_connect(
                        "/v1/room/attach?kind=watch&branch=vera&project=VERA-STUDIO",
                        subprotocols=["aipass.bearer", raw],
                    ) as socket:
                        closed = socket.receive()

        assert spawn.call_count == 1
        assert spawn.call_args.args[0] == "vera"
        gate.assert_called_once_with("vera", "VERA-STUDIO")
        assert "anchor tooling" not in closed["reason"]

    def test_no_allowlist_of_watchable_projects_is_built_here(self) -> None:
        """@prax keeps the ruling on what it can monitor."""
        source = Path(host_attach.__file__).read_text(encoding="utf-8")

        assert "resolve_branch" not in source


@fastapi_required
class TestOneRoomHonoursAnOutsideSeat:
    """The phone attaches to where the agent
    ACTUALLY IS, not to a room rebuilt from its name."""

    def _row(self, has_room: bool, outside: Any) -> dict:
        return {"name": "demo", "path": "/x/demo", "has_room": has_room, "outside_room": outside}

    def _attach(self, census: dict, kind: str = "") -> tuple:
        """Drive the real socket route for branch 'demo' and record the room decision."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        query = "/v1/room/attach?branch=demo" + (f"&kind={kind}" if kind else "")

        with patch(PATCH_SERVER_LOGGER) as log, patch(PATCH_SERVER_JSON):
            with patch.object(host_server.host_fleet, "resolve_branch", **census) as resolved:
                with patch.object(host_attach, "open_attach", return_value=StubSession()) as opened:
                    client = TestClient(host_server.create_app())
                    with client.websocket_connect(query, subprotocols=["aipass.bearer", raw]) as socket:
                        line = wait_for_log(log, "socket attached to")
                        socket.close(code=1000)
                        wait_for_log(log, "socket detached from")

        return opened.call_args.kwargs, line, resolved

    @pytest.fixture(autouse=True)
    def _seated_branch_exists(self, tmp_path: Path):
        """Stand 'demo' up as a seated branch."""
        # Only the registry is stubbed: the real citizen_address runs on top.
        with patch.object(host_server.host_reads, "resolve_branch_root", return_value=tmp_path):
            yield

    def test_an_outside_room_is_attached_and_never_created(self, store: Any, seated: Any) -> None:
        """The whole cure in one assertion: the argv attaches, and carries nothing
        that could bring a session into being."""
        opened, line, _ = self._attach({"return_value": self._row(False, "aipass-42")})

        assert opened["room"] == "aipass-42", "the snapshot's own name must be used verbatim"
        assert opened["attach_only"] is True
        assert line == "[host_api] socket attached to baud-api for @demo", "the citizen address the real gate composed"

    def test_the_attach_only_flag_actually_reaches_the_spawned_argv(self, monkeypatch) -> None:
        """The WIRING, not just the resolution — and this pin exists because a
        mutation proved the wiring was unprotected."""
        # Preflights FORCED, never skipped: argv composition is string work, and a skip leaves it unmeasured on Windows.
        monkeypatch.setattr(host_attach, "PTY_AVAILABLE", True)
        monkeypatch.setattr(host_attach.shutil, "which", lambda _binary: "/usr/bin/tmux")
        with patch.object(host_attach, "_spawn_pty") as spawn:
            spawn.return_value = (MagicMock(pid=4242), 7)
            with patch(PATCH_ATTACH_LOGGER), patch(PATCH_ATTACH_JSON):
                host_attach.open_attach("demo", cwd=None, room="aipass-42", attach_only=True)

        argv = spawn.call_args[0][0]
        assert "attach-session" in argv
        assert "new-session" not in argv, "this lane must not be able to create a room"
        assert "-A" not in argv, "attach-or-create is exactly what put a blank terminal on the phone"

    def test_without_the_flag_a_named_room_is_still_attach_or_create(self, monkeypatch) -> None:
        """The regression guard for the pin above. The shell lane names its own
        room and MUST still be able to create it."""
        monkeypatch.setattr(host_attach, "PTY_AVAILABLE", True)
        monkeypatch.setattr(host_attach.shutil, "which", lambda _binary: "/usr/bin/tmux")
        with patch.object(host_attach, "_spawn_pty") as spawn:
            spawn.return_value = (MagicMock(pid=4242), 7)
            with patch(PATCH_ATTACH_LOGGER), patch(PATCH_ATTACH_JSON):
                host_attach.open_attach("demo", cwd=None, room="shell-demo")

        argv = spawn.call_args[0][0]
        assert "new-session" in argv
        assert "-A" in argv

    def test_an_own_room_still_wins_and_the_snapshot_does_not_override_it(self, store: Any, seated: Any) -> None:
        """has_room true keeps today's behaviour EXACTLY. This lane may only ever
        rescue a branch that has no room of its own."""
        opened, _, _ = self._attach({"return_value": self._row(True, "aipass-42")})

        assert opened["room"] == "", "an empty room name is what lets the agent naming rule decide"
        assert opened["attach_only"] is False

    def test_no_outside_room_falls_through_to_the_naming_rule(self, store: Any, seated: Any) -> None:
        """A branch with neither a room nor an outside seat is unchanged."""
        opened, _, _ = self._attach({"return_value": self._row(False, None)})

        assert opened["room"] == ""
        assert opened["attach_only"] is False

    def test_a_census_that_cannot_answer_does_not_refuse_the_attach(self, store: Any, seated: Any) -> None:
        """A read failure leaves the caller on the behaviour that shipped for
        months, rather than refusing because an IMPROVEMENT could not be computed."""
        opened, _, _ = self._attach({"side_effect": host_server.host_fleet.FleetUnavailable("census down")})

        assert opened["room"] == ""
        assert opened["attach_only"] is False

    def test_a_shell_is_never_diverted_to_an_outside_room(self, store: Any, seated: Any) -> None:
        """A shell asks for its OWN room by name. `outside_room` is where an agent
        sits, and dropping an operator's shell into the agent's session is the
        opposite of what they typed."""
        opened, _, census = self._attach({"return_value": self._row(False, "aipass-42")}, kind="shell")

        assert opened["room"] != "aipass-42"
        assert opened["attach_only"] is False
        census.assert_not_called()


class TestTheOneSeatHostsAnyProjectsRoom:
    """Attach under the one-terminal ruling: any census-known project, tenant or
    external. Regression pins: the ruling made this behaviour load-bearing."""

    def test_an_external_projects_room_reaches_the_spawn(self, store: Any, tmp_path: Path) -> None:
        """The census resolves it; the seat never gets a vote."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        vera_root = tmp_path / "projects" / "vera" / "src" / "vera"

        with patch(PATCH_SERVER_LOGGER), patch(PATCH_SERVER_JSON):
            with patch.object(host_server.host_fleet, "resolve_branch") as census:
                census.return_value = {"name": "vera", "path": str(vera_root)}
                with patch.object(host_attach, "open_attach") as spawn:
                    spawn.side_effect = host_attach.AttachUnavailable("stop here, resolution is what is under test")
                    client = TestClient(host_server.create_app())

                    with client.websocket_connect(
                        "/v1/room/attach?branch=vera&project=VERA-STUDIO",
                        subprotocols=["aipass.bearer", raw],
                    ) as socket:
                        socket.receive()

        census.assert_called_once_with("VERA-STUDIO", "vera")
        assert spawn.call_args.kwargs["cwd"] == vera_root

    def test_the_room_carries_the_projects_scope(self, store: Any) -> None:
        """@baud's rule, their learning 22: an external room is namespaced by its
        project, so a phone attach and a desktop attach land in one room."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")

        with patch(PATCH_SERVER_LOGGER), patch(PATCH_SERVER_JSON):
            with patch.object(host_server.host_fleet, "resolve_branch") as census:
                census.return_value = {"name": "vera", "path": "/projects/vera/src/vera"}
                with patch.object(host_attach, "open_attach") as spawn:
                    spawn.side_effect = host_attach.AttachUnavailable("stop here")
                    client = TestClient(host_server.create_app())

                    with client.websocket_connect(
                        "/v1/room/attach?branch=vera&project=VERA-STUDIO",
                        subprotocols=["aipass.bearer", raw],
                    ) as socket:
                        socket.receive()

        assert spawn.call_args.kwargs["scope"] == "vera-studio"

    def test_an_unknown_branch_in_a_known_project_still_refuses(self, store: Any) -> None:
        """Widening which projects are reachable is not widening to nobody."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")

        with patch(PATCH_SERVER_LOGGER), patch(PATCH_SERVER_JSON):
            with patch.object(host_server.host_fleet, "resolve_branch", return_value=None):
                with patch.object(host_attach, "open_attach") as spawn:
                    client = TestClient(host_server.create_app())

                    with client.websocket_connect(
                        "/v1/room/attach?branch=nope&project=VERA-STUDIO",
                        subprotocols=["aipass.bearer", raw],
                    ) as socket:
                        closed = socket.receive()

        spawn.assert_not_called()
        assert closed["code"] == 1008
        assert "no branch named" in closed["reason"]


class TestThisModuleImportsWhereItCannotRun:
    """The Windows lane's 22 collection errors, and the one line that caused them."""

    # A DEFAULT ARGUMENT IS EVALUATED AT IMPORT: a bare `os.setsid` default breaks importing every host module there.

    def test_no_posix_only_default_is_reached_for_directly(self) -> None:
        """The structural pin, so the NEXT one is caught rather than shipped."""
        tree = ast.parse(Path(host_attach.__file__).read_text(encoding="utf-8"))
        hook = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_acquire_controlling_tty"
        )

        assert hook.args.defaults, "nothing is bound — the child would look it all up"
        for default in hook.args.defaults:
            reached_for = isinstance(default, ast.Attribute) and isinstance(default.value, ast.Name)
            assert not reached_for, f"{ast.unparse(default)} is evaluated at import; use getattr with a default"

    def test_a_platform_with_no_way_to_claim_a_tty_refuses(self) -> None:
        """What the getattr defaults become off POSIX, and what happens then."""
        # No caller reaches this (all sit behind PTY_AVAILABLE); without the refusal it is `None()` in a forked child.
        with pytest.raises(host_attach.AttachUnavailable) as refusal:
            host_attach._acquire_controlling_tty(
                _setsid=None,
                _login_tty=None,
                _ioctl=None,
                _tiocsctty=None,
            )

        assert "controlling tty" in str(refusal.value)


@fastapi_required
class TestThePhoneCanMeasureItsOwnSocket:
    """A ping is answered with a pong, so the phone can tell a dead socket from an open one."""

    # The JS WebSocket API exposes no ping, so a peer gone without a FIN reads as OPEN forever on the phone.

    def test_a_ping_is_answered_with_a_pong(self, store: Any, seated: Any) -> None:
        """The round trip, end to end. This is the whole feature."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        session = StubSession()

        with patch(PATCH_SERVER_LOGGER) as log, patch(PATCH_SERVER_JSON):
            with patch.object(host_attach, "open_attach", return_value=session):
                client = TestClient(host_server.create_app())
                with client.websocket_connect(
                    "/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]
                ) as socket:
                    socket.send_text('{"type": "ping"}')
                    answer = socket.receive_text()

                    # Wait for the route's last line: leaving while the pump unwinds cancels a live server.
                    detach_and_wait(socket, session)
                    wait_for_log(log, "socket detached from")

        assert json.loads(answer) == {"type": "pong"}

    def test_every_ping_is_answered_so_a_client_can_keep_measuring(self, store: Any, seated: Any) -> None:
        """Not once — a heartbeat is only a heartbeat if it keeps beating."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        session = StubSession()

        with patch(PATCH_SERVER_LOGGER) as log, patch(PATCH_SERVER_JSON):
            with patch.object(host_attach, "open_attach", return_value=session):
                client = TestClient(host_server.create_app())
                with client.websocket_connect(
                    "/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]
                ) as socket:
                    answers = []
                    for _ in range(5):
                        socket.send_text('{"type": "ping"}')
                        answers.append(socket.receive_text())

                    detach_and_wait(socket, session)
                    wait_for_log(log, "socket detached from")

        assert answers == [json.dumps({"type": "pong"})] * 5

    def test_a_ping_never_reaches_the_room(self, store: Any, seated: Any) -> None:
        """The hazard the control/keystroke split exists to prevent, at a new verb."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        session = StubSession()

        with patch(PATCH_SERVER_LOGGER) as log, patch(PATCH_SERVER_JSON):
            with patch.object(host_attach, "open_attach", return_value=session):
                client = TestClient(host_server.create_app())
                with client.websocket_connect(
                    "/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]
                ) as socket:
                    socket.send_text('{"type": "ping"}')
                    socket.receive_text()

                    socket.send_bytes(b"echo alive")
                    session.wait_until(lambda: bool(session.writes))

                    detach_and_wait(socket, session)
                    wait_for_log(log, "socket detached from")

        assert session.writes == [b"echo alive"]
        assert session.resizes == []

    def test_a_pong_from_the_client_is_an_unknown_frame_not_a_loop(self, store: Any, seated: Any) -> None:
        """The server pongs; it does not ping. So an inbound pong is unknown."""
        # Answering a pong would set two sockets shouting at each other on the keystroke wire.
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        session = StubSession()

        with patch(PATCH_PUMP_LOGGER) as log, patch(PATCH_SERVER_LOGGER) as server_log, patch(PATCH_SERVER_JSON):
            with patch.object(host_attach, "open_attach", return_value=session):
                client = TestClient(host_server.create_app())
                with client.websocket_connect(
                    "/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]
                ) as socket:
                    socket.send_text('{"type": "pong"}')

                    # The ping's answer cannot beat one to the pong, so one frame back means one was answered.
                    socket.send_text('{"type": "ping"}')
                    answer = socket.receive_text()

                    detach_and_wait(socket, session)
                    wait_for_log(server_log, "socket detached from")

        assert json.loads(answer) == {"type": "pong"}
        assert any("unknown control frame" in str(call) for call in log.warning.call_args_list)
