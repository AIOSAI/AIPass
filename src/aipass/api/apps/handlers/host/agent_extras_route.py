# =================== AIPass ====================
# Name: agent_extras_route.py
# Description: Host API Agent Extras Route — the chat panel's model catalog and its read-aloud voice
# Version: 1.0.0
# Created: 2026-11-05
# Modified: 2026-11-05
# =============================================
# pyright: reportMissingImports=false, reportInvalidTypeForm=false, reportOptionalCall=false
# The suppressions cover the optional-dependency placeholders, as in server.py:
# without the [host] extra these names are None, and register() is only ever
# called from create_app(), which refuses first when the extra is missing.

"""Host API Agent Extras Route: GET /v1/models, POST /v1/speak. Reference: docs/host_agent_chat.md"""

from typing import Any, Callable

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import agent_chat
from aipass.api.apps.handlers.host import agent_models
from aipass.api.apps.handlers.host import speech
from aipass.api.apps.handlers.host.agent_route import json_body

try:
    from fastapi import Depends
    from fastapi.responses import StreamingResponse
except ImportError as e:
    logger.debug("[host_api] agent extras route libraries not available: %s", e)
    Depends = None  # type: ignore[assignment, misc]
    StreamingResponse = None  # type: ignore[assignment, misc]

PCM_MEDIA_TYPE = "audio/L16"
RATE_HEADER = "X-Sample-Rate"


def register(
    app: Any,
    deny: Callable[..., Any],
    logged_denial: Callable[..., Any],
    require_scope: Callable[[str], Any],
) -> None:
    """Add GET /v1/models and POST /v1/speak to *app*."""
    _json_body = json_body(deny)

    @app.get("/v1/models")
    def models(record: dict = Depends(require_scope("read"))) -> dict:
        """Every provider's models and the switch table; a def, as the OpenCode listing execs `opencode models`."""
        return agent_models.listing()

    # read scope: it types into no agent and only makes local audio. def: Piper is a child process.
    @app.post("/v1/speak")
    def speak(record: dict = Depends(require_scope("read")), body: Any = Depends(_json_body)) -> Any:
        """Stream Piper's raw 16-bit mono PCM for {text} as it is made, the rate in X-Sample-Rate."""
        text = body.get("text") if isinstance(body, dict) else None
        cleaned = agent_chat.clean_text(text) if isinstance(text, str) else ""
        if not cleaned:
            raise deny(400, "speak_text_refused", "The body needs a non-empty text field.")
        try:
            rate = speech.sample_rate()
        except speech.SpeechUnavailable as e:
            raise logged_denial(e, 503, "speech_unavailable") from e
        return StreamingResponse(speech.stream(cleaned), media_type=PCM_MEDIA_TYPE, headers={RATE_HEADER: str(rate)})

    json_handler.log_operation("host_api_agent_extras_route_registered", {"routes": ["/v1/models", "/v1/speak"]})
