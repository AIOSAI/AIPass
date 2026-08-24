# =================== AIPass ====================
# Name: pump.py
# Description: Host API Pump Handler — the bidirectional room socket and its control frames
# Version: 1.0.0
# Created: 2026-08-21
# Modified: 2026-08-21
# =============================================

"""
Host API Pump Handler

What happens between an accepted `/v1/room/attach` socket and the PTY behind it,
for as long as both are alive. The route decides WHICH room; this decides what
crosses the wire once one is open.

THE SPLIT, TEXT VS BINARY. Binary frames are KEYSTROKES and text frames are
CONTROL. That is what lets a resize — or a liveness probe — ride the same socket
as the operator's typing without either being mistaken for the other, and it is
why bytes are forwarded undecoded in both directions: the room emits escape
sequences and partial UTF-8 across chunk boundaries, and decoding either end
corrupts both.

TWO CONTROL VERBS:
    resize  - refused rather than clamped, and never fatal. A bad geometry must
              not drop a room somebody is working in.
    ping    - answered `pong`, and nothing else. It exists because the browser
              WebSocket API exposes no protocol-level ping to JS, so a phone
              whose peer vanished without a FIN reads its socket as OPEN forever
              and renders a corpse frame the operator believes is live.

Functions:
    run_pump()  - Run both directions until either side goes away
"""

import asyncio
import json
from typing import Any, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import attach as host_attach


# The whole answer to a ping. A constant rather than a dump per frame: the
# phone sends one every few seconds per open room, and this is the one shape
# the client feature-detects on.
PONG_FRAME = json.dumps({"type": "pong"})


# THE PUMP AND ITS CONTROL FRAMES were nested inside the app factory in the
# first cut, then lifted to module level in server.py, and now live here. Both
# moves had the same reason under them: these two take everything they touch as
# ARGUMENTS, so nothing ever held them where they were except indentation. The
# second move was forced by a line cap — server.py crossed 1500 when the ping
# lane landed — and a cap is only a good reason to move code that was already
# separable. This was.
async def run_pump(websocket: Any, session: Any) -> Optional[int]:
    """
    Run the bidirectional pump until either side goes away.

    The PTY read is blocking, so it lives on a thread executor rather than
    the event loop — a blocking read on the loop would freeze every other
    request this server is serving, which on a single-worker uvicorn means
    the whole phone.

    Args:
        websocket: The accepted connection.
        session: The live AttachSession.

    Returns:
        The close code the socket ended on, or None when the ROOM ended first
        and the client never sent one. Returned rather than logged here so the
        detach line sits beside the attach line it closes, at the same level.
    """
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    close_code: Optional[int] = None

    async def room_to_socket() -> None:
        """PTY output → client. Binary frames: the room emits escape
        sequences and partial UTF-8 across chunk boundaries, and decoding
        here would corrupt both."""
        while not stop.is_set():
            data = await loop.run_in_executor(host_attach.pump_executor(), session.read)
            if not data:
                break
            await websocket.send_bytes(data)
        stop.set()

    async def socket_to_room() -> None:
        """Client input → PTY. Bytes forwarded UNCHANGED — the key bar
        sends real control bytes, exactly as a keyboard would, so there is
        nothing here to interpret."""
        nonlocal close_code

        while not stop.is_set():
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                close_code = message.get("code")
                break

            if message.get("bytes") is not None:
                try:
                    session.write(message["bytes"])
                except host_attach.AttachRefused as e:
                    # A read-only watch was typed into. The session's own
                    # refusal (the layer that counts) ends the attach with
                    # the sentence — a client that types into a watch has
                    # broken the contract, and pretending the bytes landed
                    # would be the silent fallback this house refuses.
                    logger.warning("[host_api] input refused on %s: %s", session.room, e)
                    # The ONE socket refusal on this surface that left no
                    # structured trace. Every other one goes through the
                    # route's _audit_socket_refusal; this one happens after
                    # the socket is live, so it never passed that gate — and
                    # a client typing into a read-only watch is exactly the
                    # event an audit trail exists for. Found by the standards
                    # checker asking the new module why it logged no
                    # operations, which was a fair question.
                    json_handler.log_operation(
                        "host_api_input_refused",
                        {"room": session.room, "reason": str(e), "route": "/v1/room/attach"},
                    )
                    close_code = 1008
                    await websocket.close(code=1008, reason=str(e))
                    break
                continue

            text = message.get("text")
            if text:
                await _handle_control(websocket, session, text)
        stop.set()

    tasks = [asyncio.ensure_future(room_to_socket()), asyncio.ensure_future(socket_to_room())]

    try:
        # FIRST_COMPLETED, not gather. Waiting for BOTH deadlocks on a quiet
        # room: the phone closes the sheet, socket_to_room ends, and
        # room_to_socket is still parked in a blocking os.read that will not
        # return until the room happens to print something. The detach — and
        # the SIGHUP with it — would wait on output that may never come, and
        # the executor thread would stay parked with it.
        #
        # Either direction ending means the attach is over, so the first one
        # to finish is the signal.
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # Always, and FIRST: hangup closes the descriptor, which is what
        # breaks the blocked reader out of os.read. Cancelling the task
        # alone would not — a thread sitting in a syscall does not notice
        # an asyncio cancellation.
        session.hangup()

        for task in tasks:
            task.cancel()

        # Let the unblocked reader finish rather than leaving it to be
        # collected mid-flight, which logs a 'task was destroyed but it is
        # pending' at whoever reads the server log next.
        await asyncio.gather(*tasks, return_exceptions=True)

    return close_code


async def _handle_control(websocket: Any, session: Any, text: str) -> None:
    """
    Handle a control frame from the client.

    Text frames are CONTROL, binary frames are KEYSTROKES. That split is
    what lets a resize travel on the same socket without a resize message
    ever being mistaken for something the operator typed.

    Two verbs: `resize`, and `ping` — which exists because a BROWSER cannot
    send a protocol-level ping. The JS WebSocket API exposes no ping, so a
    phone whose peer vanished without a FIN reads its socket as OPEN forever
    and renders a corpse frame the operator believes is live (@baud's
    FPLAN-0446 r5). uvicorn pings from this side, so the SERVER always notices
    a dead phone; this is the same round-trip pointed the other way, and the
    client is the half that had none.

    Args:
        websocket: The accepted connection, for answering a ping.
        session: The live AttachSession.
        text: The JSON control message.
    """
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("[host_api] ignoring an unparseable control frame on %s", session.room)
        return

    verb = message.get("type") if isinstance(message, dict) else None

    if verb == "ping":
        # Text, like every other control frame — a pong on the BINARY channel
        # would land in the room's output stream and paint JSON across the
        # operator's terminal. Answered inline and not recorded: a liveness
        # probe every few seconds is not an event, and logging it would bury
        # the attach and detach lines that are.
        await websocket.send_text(PONG_FRAME)
        return

    if verb != "resize":
        logger.warning("[host_api] ignoring an unknown control frame on %s", session.room)
        return

    try:
        session.resize(message.get("cols"), message.get("rows"))
    except (host_attach.AttachRefused, host_attach.AttachUnavailable, OSError) as e:
        # Never fatal: a bad resize should not drop a live session the
        # operator is working in.
        logger.warning("[host_api] resize refused on %s: %s", session.room, e)
