# =================== AIPass ====================
# Name: test_host_attach.py
# Description: Tests for the host API attach lane — the pump's shape and the socket's records
# Version: 1.1.1
# Created: 2026-08-14
# Modified: 2026-10-17
# =============================================

"""Tests for the attach socket's records in apps/handlers/host/server.py and the pump's shape in pump.py."""

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

# Own constants, not the support module's: discarded_patch judges a target imported from this package.
PATCH_SERVER_JSON = "aipass.api.apps.handlers.host.server.json_handler"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"
PATCH_PUMP_LOGGER = "aipass.api.apps.handlers.host.pump.logger"
PATCH_PUMP_JSON = "aipass.api.apps.handlers.host.pump.json_handler"


def test_the_session_is_created_once_per_socket_not_per_poll() -> None:
    """@baud's bug, checked for its SHAPE on this side rather than assumed absent."""
    # A session keyed off a polled value re-types the launch line into the room on every poll.
    source = Path(host_server.__file__).read_text(encoding="utf-8")

    assert source.count("host_attach.open_attach(") == 1

    route = source[source.index('@app.websocket("/v1/room/attach")') : source.index("def _audit_socket_refusal(")]
    assert "while" not in route


def test_the_control_frame_is_json_and_the_verbs_are_resize_and_ping() -> None:
    """Text frames are CONTROL, binary frames are KEYSTROKES."""
    # A control verb reaching the write path types its own JSON into the operator's shell.
    handler = source_of("_handle_control")

    assert 'verb == "ping"' in handler
    assert 'verb != "resize"' in handler
    assert "session.write" not in handler
    # A pong on the binary channel would paint itself across the operator's terminal as room output.
    assert "send_text(" in handler
    assert "send_bytes" not in handler
    assert json.loads(host_pump.PONG_FRAME) == {"type": "pong"}


def test_a_blocking_read_never_runs_on_the_event_loop() -> None:
    """
    The PTY read blocks. On a single-worker uvicorn, a blocking read on the loop
    freezes every other request this server is serving.
    """
    pump = source_of("run_pump")

    assert "run_in_executor(" in pump
    assert "session.read" in pump
    assert "await loop.run_in_executor(None" not in pump


def test_the_pump_always_hangs_up() -> None:
    """A pump that raises must still detach."""
    pump = source_of("run_pump")

    assert "finally:" in pump
    assert "session.hangup()" in pump


class SilentRoom(StubSession):
    """A room that ENDS rather than blocking — EOF on the first read."""

    def read(self, size: int = 0) -> bytes:
        """The room is gone: EOF straight away, which ends the pump's reader."""
        return b""


@fastapi_required
class TestTheDetachIsWrittenDownToo:
    """@baud's second r5 finding: ATTACH was logged and DETACH was not."""

    def test_the_detach_line_names_the_room_the_duration_and_the_close_code(self, store: Any, seated: Any) -> None:
        """All three facts, in the line that actually gets written."""
        # 1001, not 1000: a hardcoded normal-closure would pass a test that closed normally.
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
        """A duration that is always 0.0s measures the logging, not the socket."""
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
        """The detach nobody's client caused."""
        # A room that ends has no close code; a bare `None` in that field reads as a logging bug.
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
        """The property the flap investigation actually needed."""
        from fastapi.testclient import TestClient

        _, raw = host_tokens.issue_token("pixel-8", scope="operate")

        with patch(PATCH_SERVER_LOGGER) as log, patch(PATCH_SERVER_JSON):
            client = TestClient(host_server.create_app())
            for n in range(3):
                session = StubSession()
                session.room = f"baud-api-{n}"
                with patch.object(host_attach, "open_attach", return_value=session):
                    with client.websocket_connect(
                        "/v1/room/attach?branch=api", subprotocols=["aipass.bearer", raw]
                    ) as socket:
                        # Inside the context, or the exit cancels a server still unwinding.
                        detach_and_wait(socket, session)
                        wait_for_log(log, f"socket detached from baud-api-{n} ")

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
    """The one socket refusal on this surface that used to leave no structured trace."""

    # It happens after the socket is live, so it never passes the route's _audit_socket_refusal.

    def test_the_refusal_is_recorded_with_the_room_and_the_reason(self, store: Any, seated: Any) -> None:
        """A client breaking the contract is exactly what an audit trail is for."""
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
        """A server-initiated close is a detach too, and it has a code."""
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
