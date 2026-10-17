# =================== AIPass ====================
# Name: pump.py
# Description: Host API Pump Handler — the bidirectional room socket and its control frames
# Version: 1.1.0
# Created: 2026-08-21
# Modified: 2026-10-17
# =============================================

"""Host API Pump Handler"""

import asyncio
import json
from typing import Any, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import attach as host_attach


PONG_FRAME = json.dumps({"type": "pong"})

ROOM_ENDED_CODE = 4000
ROOM_ENDED_REASON = "room ended"


async def run_pump(websocket: Any, session: Any) -> Optional[int]:
    """Run the bidirectional pump until either side goes away."""
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
                try:
                    await websocket.close(code=ROOM_ENDED_CODE, reason=ROOM_ENDED_REASON)
                except RuntimeError as e:
                    logger.info("[host_api] room %s ended after its socket closed: %s", session.room, e)
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
                    logger.warning("[host_api] input refused on %s: %s", session.room, e)
                    # Recorded here: this refusal comes after the socket is live, past the route's audit gate.
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
        # FIRST_COMPLETED, not gather: waiting for both deadlocks on a quiet room parked in os.read.
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # First: closing the descriptor breaks the reader out of os.read; a cancel never reaches a syscall.
        session.hangup()

        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)

    return close_code


async def _handle_control(websocket: Any, session: Any, text: str) -> None:
    """Handle a control frame from the client."""
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("[host_api] ignoring an unparseable control frame on %s", session.room)
        return

    verb = message.get("type") if isinstance(message, dict) else None

    if verb == "ping":
        # Text, never binary: a binary pong paints JSON across the terminal. Not logged: it is no event.
        await websocket.send_text(PONG_FRAME)
        return

    if verb != "resize":
        logger.warning("[host_api] ignoring an unknown control frame on %s", session.room)
        return

    try:
        session.resize(message.get("cols"), message.get("rows"))
    except (host_attach.AttachRefused, host_attach.AttachUnavailable, OSError) as e:
        logger.warning("[host_api] resize refused on %s: %s", session.room, e)
