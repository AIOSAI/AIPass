# =================== AIPass ====================
# Name: test_host_attach.py
# Description: Tests for the host API attach lane — the pump's shape and the socket's records
# Version: 1.1.0
# Created: 2026-08-14
# Modified: 2026-10-08
# =============================================

"""Tests for the attach socket's records in apps/handlers/host/server.py and the pump's shape in pump.py."""

# Tests for the Attach Lane
#
# DPLAN-0300 Round 18b/18c. `WS /v1/room/attach` runs a PTY hosting a tmux CLIENT
# into a branch's persistent room — the desktop's window over a different wire.
#
# THE THREE THINGS THIS LANE COULD GET WRONG, and none of them is "does it work":
#
#   1. **Killing a room it was only supposed to leave.** Detach is a SIGHUP to the
#      client; the session survives. If this ever became a kill, closing a sheet on
#      a phone would end an agent mid-task. Pinned by behaviour AND by reading the
#      module source for kill-session, because the failure is one word long.
#
#   2. **Leaking the token into a log.** A WebSocket cannot carry an Authorization
#      header, and the easy answer — a query parameter — writes the credential into
#      every access log, proxy log and browser history entry. The bearer rides the
#      subprotocol, and the ACCEPTED protocol is the sentinel rather than the token.
#
#   3. **Spawning a PTY for an unauthenticated caller.** The scope check happens
#      BEFORE accept, so a refused socket never reaches a shell.
#
# WHERE EACH LIVES since the oversize split (api, 2026-10-08): the first in
# test_host_attach_pump.py, the second and third in test_host_attach_route.py.
# This file keeps the pump's shape read at the source and the records the
# socket leaves behind; the helpers the three share are support_host_attach.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered) — issue_token() and the token store's own locking, tests/test_host_token_store.py

import json
import re
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

from aipass.api.apps.handlers.host import attach as host_attach
from aipass.api.apps.handlers.host import pump as host_pump
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens
from aipass.api.tests.support_host_attach import (
    StubSession,
    detach_and_wait,
    fastapi_required,
    source_of,
    wait_for_log,
)

# The patch targets stay this file's own constants rather than the support
# module's: seedgo's discarded_patch rule reads a target imported from this
# branch's package as one it judges, and these silence loggers on purpose.
PATCH_SERVER_JSON = "aipass.api.apps.handlers.host.server.json_handler"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"
# The pump carries its own logger since the 2026-08-21 split: attach and
# detach are logged by the route, control frames by the pump.
PATCH_PUMP_LOGGER = "aipass.api.apps.handlers.host.pump.logger"
PATCH_PUMP_JSON = "aipass.api.apps.handlers.host.pump.json_handler"


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


def test_the_control_frame_is_json_and_the_verbs_are_resize_and_ping() -> None:
    """
    Text frames are CONTROL, binary frames are KEYSTROKES.

    That split is what lets a resize travel on the same socket without a resize
    message ever being mistaken for something the operator typed — and it is why
    an unparseable control frame is ignored rather than written to the room.

    TWO verbs now (@baud's FPLAN-0446 r5): `ping` joined `resize` so the browser
    has a round-trip of its own. The split it rides on is unchanged, and the
    `session.write` assertion is the one that keeps it that way — a control verb
    reaching the write path types its own JSON into the operator's shell.
    """
    handler = source_of("_handle_control")

    assert 'verb == "ping"' in handler
    assert 'verb != "resize"' in handler
    assert "session.write" not in handler
    # The pong answers on the channel it arrived on. On the binary one it would
    # be indistinguishable from room output, and would paint itself across the
    # terminal the operator is reading.
    assert "send_text(" in handler
    assert "send_bytes" not in handler
    assert json.loads(host_pump.PONG_FRAME) == {"type": "pong"}


def test_a_blocking_read_never_runs_on_the_event_loop() -> None:
    """
    The PTY read blocks. On a single-worker uvicorn, a blocking read on the loop
    freezes every other request this server is serving — which is the whole
    phone, including the fleet card the operator is looking at.

    WHICH executor it runs on is deliberately not asserted here: it moved from
    asyncio's default pool to the attach lane's own one (DPLAN-0305 Audit 2 —
    the default sized itself to 8 threads on this host, and the 9th socket
    silently never pumped). The property that matters is that the read is
    handed to SOME executor, never called on the loop.
    """
    pump = source_of("run_pump")

    assert "run_in_executor(" in pump
    assert "session.read" in pump
    assert "await loop.run_in_executor(None" not in pump


def test_the_pump_always_hangs_up() -> None:
    """
    A pump that raises must still detach.

    Otherwise the room keeps a client attached to a socket nobody is holding,
    and the operator's next attach lands in a session with a ghost in it.
    """
    pump = source_of("run_pump")

    assert "finally:" in pump
    assert "session.hangup()" in pump


# ==============================================
# LIVENESS AND LIFETIME
# ==============================================


class SilentRoom(StubSession):
    """A room that ENDS rather than blocking — EOF on the first read."""

    def read(self, size: int = 0) -> bytes:
        """The room is gone: EOF straight away, which ends the pump's reader."""
        return b""


@fastapi_required
class TestTheDetachIsWrittenDownToo:
    """
    @baud's second r5 finding: ATTACH was logged and DETACH was not.

    Tonight's flap put 13 attaches on one room in three minutes (server.log
    21:42:26-21:45:28) and the log could say the phone kept ARRIVING without
    being able to say it kept leaving, how long it stayed, or why it went. Two
    facts separate a reconnect loop from an operator opening sheets: how long
    the socket lived, and the code it closed on.
    """

    def test_the_detach_line_names_the_room_the_duration_and_the_close_code(self, store: Any, seated: Any) -> None:
        """
        All three facts, in the line that actually gets written.

        1001 rather than 1000 on purpose: a hardcoded normal-closure would pass
        a test that closed normally, and 1001 (going away — a locked screen, a
        backgrounded tab) is the code the flap is most likely to be made of.
        """
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        session = StubSession()

        with patch(PATCH_SERVER_LOGGER) as log, patch(PATCH_SERVER_JSON):
            with patch.object(host_attach, "open_attach", return_value=session):
                client = TestClient(host_server.create_app())
                with client.websocket_connect(
                    "/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]
                ) as socket:
                    wait_for_log(log, "socket attached to")

                    socket.close(code=1001)
                    line = wait_for_log(log, "socket detached from")

        assert "baud-api" in line
        assert "close 1001" in line
        assert re.search(r"after \d+\.\d+s", line), line

    def test_the_duration_is_the_socket_s_own_lifetime_not_a_constant(self, store: Any, seated: Any) -> None:
        """
        A duration that is always 0.0s measures the logging, not the socket.

        Half a second is enough to separate a real clock from a stamp taken
        twice in the same breath, and short enough that the suite does not pay
        for the proof.
        """
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        session = StubSession()

        with patch(PATCH_SERVER_LOGGER) as log, patch(PATCH_SERVER_JSON):
            with patch.object(host_attach, "open_attach", return_value=session):
                client = TestClient(host_server.create_app())
                with client.websocket_connect(
                    "/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]
                ) as socket:
                    wait_for_log(log, "socket attached to")
                    time.sleep(0.5)

                    socket.close(code=1000)
                    line = wait_for_log(log, "socket detached from")

        assert re.sub(r"after \d+\.\d+s", "after Ns", line) == (
            "[host_api] socket detached from baud-api after Ns (close 1000)"
        )
        (held,) = re.findall(r"after (\d+\.\d+)s", line)

        assert float(held) >= 0.5, line

    def test_a_room_that_ends_first_says_so_instead_of_printing_none(self, store: Any, seated: Any) -> None:
        """
        The detach nobody's client caused.

        When the ROOM goes (tmux killed, the agent exited), the pump ends from
        the other direction and there is no close code, because the client never
        sent one. A bare `None` in that field reads as a logging bug — the line
        has to say which kind of detach this was.
        """
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        session = SilentRoom()

        with patch(PATCH_SERVER_LOGGER) as log, patch(PATCH_SERVER_JSON):
            with patch.object(host_attach, "open_attach", return_value=session):
                client = TestClient(host_server.create_app())
                with client.websocket_connect("/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]):
                    line = wait_for_log(log, "socket detached from")

        assert "close room ended" in line
        assert "None" not in line

    def test_every_attach_is_paired_with_a_detach(self, store: Any, seated: Any) -> None:
        """
        The property the flap investigation actually needed.

        Counting alone is what made 13 attaches unreadable: without the other
        half, an arrival count cannot distinguish 13 sockets that came and went
        from 13 that came and stayed. Three sockets in, three lines each way.
        """
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")

        with patch(PATCH_SERVER_LOGGER) as log, patch(PATCH_SERVER_JSON):
            client = TestClient(host_server.create_app())
            for _ in range(3):
                session = StubSession()
                with patch.object(host_attach, "open_attach", return_value=session):
                    with client.websocket_connect(
                        "/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]
                    ) as socket:
                        detach_and_wait(socket, session)
                wait_for_log(log, "socket detached from")

        rendered = [call.args[0] % call.args[1:] for call in log.info.call_args_list if len(call.args) > 1]

        assert len([line for line in rendered if "socket attached to" in line]) == 3
        assert len([line for line in rendered if "socket detached from" in line]) == 3


class RefusingSession(StubSession):
    """A read-only watch, refusing at the layer that counts — like open_monitor's."""

    def write(self, data: bytes) -> None:
        """Refuse for real: the session, not the route, is what says no."""
        raise host_attach.AttachRefused("This session is read-only — a watch takes no input")


@fastapi_required
class TestTypingIntoAWatchLeavesARecord:
    """
    The one socket refusal on this surface that used to leave no structured trace.

    Every refusal BEFORE the socket goes live runs through the route's
    _audit_socket_refusal — wrong scope, unknown branch, no tmux. This one
    happens after: the socket is open, authenticated and pumping when a client
    types into a read-only watch, so it never passes that gate. It logged a
    warning and closed 1008, and the audit trail said nothing at all.

    Found by the standards checker asking the new pump module why it recorded no
    operations. The checker was right, and the honest way to satisfy it was to
    close the gap rather than to log something cheap.
    """

    def test_the_refusal_is_recorded_with_the_room_and_the_reason(self, store: Any, seated: Any) -> None:
        """
        A client breaking the contract is exactly what an audit trail is for.

        The room names WHICH watch was typed into and the reason carries the
        session's own sentence — the two things somebody reading the record
        afterwards cannot reconstruct from a close code.
        """
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        session = RefusingSession()

        with (
            patch(PATCH_SERVER_LOGGER),
            patch(PATCH_PUMP_LOGGER),
            patch(PATCH_SERVER_JSON),
            patch(PATCH_PUMP_JSON) as audit,
            patch.object(host_attach, "open_attach", return_value=session),
        ):
            client = TestClient(host_server.create_app())
            with client.websocket_connect("/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]) as socket:
                socket.send_bytes(b"rm -rf /")
                session.wait_until(lambda: session.hangups > 0)

        recorded = [call for call in audit.log_operation.call_args_list if call.args[0] == "host_api_input_refused"]

        assert len(recorded) == 1, audit.log_operation.call_args_list
        assert recorded[0].args[1]["room"] == "baud-api"
        assert "read-only" in recorded[0].args[1]["reason"]
        assert session.hangups == 1

    def test_the_detach_line_carries_the_code_the_server_chose(self, store: Any, seated: Any) -> None:
        """
        A server-initiated close is a detach too, and it has a code.

        1008 is the policy close the pump sends when a watch is typed into. If
        only CLIENT codes reached the detach line, every refusal would read as
        'room ended' and the log would lose which side ended the socket.
        """
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")
        session = RefusingSession()

        with patch(PATCH_SERVER_LOGGER) as log, patch(PATCH_PUMP_LOGGER), patch(PATCH_SERVER_JSON):
            with patch(PATCH_PUMP_JSON):
                with patch.object(host_attach, "open_attach", return_value=session):
                    client = TestClient(host_server.create_app())
                    with client.websocket_connect(
                        "/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]
                    ) as socket:
                        socket.send_bytes(b"rm -rf /")
                        line = wait_for_log(log, "socket detached from")

        assert "close 1008" in line
