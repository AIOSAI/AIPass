# =================== AIPass ====================
# Name: agent_route.py
# Description: Host API Agent Route — an agent's feed and usage; typing, keys and model switches in its room
# Version: 1.1.0
# Created: 2026-11-04
# Modified: 2026-11-05
# =============================================
# pyright: reportMissingImports=false, reportInvalidTypeForm=false, reportOptionalCall=false
# The suppressions cover the optional-dependency placeholders, as in server.py:
# without the [host] extra these names are None, and register() is only ever
# called from create_app(), which refuses first when the extra is missing.

"""
Host API Agent Route
GET /v1/agent/{project}/{name}/feed and .../usage; POST .../send, .../interrupt, .../allow, .../deny, .../model.
Reference: docs/host_agent_chat.md"""

import json
from typing import Any, Callable, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import agent_chat
from aipass.api.apps.handlers.host import agent_models
from aipass.api.apps.handlers.host import agent_usage
from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.handlers.host.attach import ROOM_NAME

try:
    from fastapi import Depends, Request
except ImportError as e:
    logger.debug("[host_api] agent route libraries not available: %s", e)
    Depends = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]

SINCE_PARAM = "since"
MODEL_FIELDS = ("provider", "model", "effort")

TRANSCRIPT_SENTENCES = {
    "not_written": "{name}'s Codex rollout is not on disk yet",
    "unsupported_provider": "{name} runs on a provider whose transcript is not read here; only Claude and Codex are",
    "missing": "{name}'s transcript is not on disk",
}


def json_body(deny: Callable[..., Any]) -> Callable[..., Any]:
    """A dependency reading the body as JSON, or a 400 agent_body_refused: FastAPI's own parse would answer 422."""

    async def _json_body(request: Request) -> Any:
        """The body as JSON; an empty body is {}."""
        raw = await request.body()
        try:
            return json.loads(raw) if raw.strip() else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise deny(400, "agent_body_refused", "The body must be a JSON object.") from None

    return _json_body


def register(
    app: Any,
    deny: Callable[..., Any],
    logged_denial: Callable[..., Any],
    require_scope: Callable[[str], Any],
) -> None:
    """Add the agent chat routes to *app*."""

    def _fenced(project: str, name: str) -> None:
        """Refuse a project or name that is not a plain identifier, before any lookup."""
        if not (ROOM_NAME.fullmatch(project) and ROOM_NAME.fullmatch(name)):
            raise deny(400, "agent_refused", "An agent is <project>/<name>: letters, digits, '_' and '-' only.")

    def _unknown(project: str, name: str) -> Any:
        """The 404 for an agent the roster does not list."""
        return deny(404, "agent_not_live", f"{name} in {project} is not live: @baud's roster does not list it.")

    def _no_room(name: str) -> Any:
        """The 409 for an agent with no room of its own to type into."""
        return deny(409, "agent_no_room", f"{name} has no live BAUD room to type into.")

    _json_body = json_body(deny)

    def _keystrokes(project: str, name: str, act: Callable[[], None]) -> dict:
        """Run one keystroke action, mapping its refusals onto the lane's status codes."""
        _fenced(project, name)
        try:
            act()
        except agent_chat.AgentUnknown:
            raise _unknown(project, name) from None
        except agent_chat.AgentNoRoom:
            raise _no_room(name) from None
        except agent_chat.SendFailed as e:
            raise logged_denial(e, 503, "agent_send_failed") from e
        except host_fleet.FleetUnavailable as e:
            raise logged_denial(e, 503, "fleet_unavailable") from e
        except host_fleet.FleetMisuse as e:
            raise logged_denial(e, 500, "roster_misuse") from e
        return {"ok": True}

    # def, not async: the roster execs @baud and the feed reads up to 4 MB of transcript.
    @app.get("/v1/agent/{project}/{name}/feed")
    def agent_feed(project: str, name: str, request: Request, record: dict = Depends(require_scope("read"))) -> dict:
        """The agent's transcript as {n, role, text, time, model?} lines, with busy and waiting."""
        _fenced(project, name)
        others = sorted(key for key in request.query_params.keys() if key != SINCE_PARAM)
        if others:
            raise deny(400, "agent_feed_refused", f"The feed takes only since — received: {', '.join(others)}.")
        raw = request.query_params.get(SINCE_PARAM)
        since: Optional[int] = None
        if raw is not None:
            try:
                since = int(raw)
            except ValueError:
                raise deny(400, "agent_feed_refused", "since must be a whole number, a line's n.") from None
        try:
            return agent_chat.feed(project, name, since)
        except agent_chat.AgentUnknown:
            raise _unknown(project, name) from None
        except agent_chat.TranscriptUnavailable as e:
            sentence = TRANSCRIPT_SENTENCES[e.code].format(name=name)
            raise deny(404, "transcript_unavailable", sentence) from None
        except host_fleet.FleetUnavailable as e:
            raise logged_denial(e, 503, "fleet_unavailable") from e
        except host_fleet.FleetMisuse as e:
            raise logged_denial(e, 500, "roster_misuse") from e

    @app.post("/v1/agent/{project}/{name}/send")
    def agent_send(
        project: str, name: str, record: dict = Depends(require_scope("operate")), body: Any = Depends(_json_body)
    ) -> dict:
        """Type {text} into the agent's room, then Enter."""
        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str) or not agent_chat.clean_text(text):
            raise deny(400, "agent_text_refused", "The body needs a non-empty text field.")
        return _keystrokes(project, name, lambda: agent_chat.send(project, name, text))

    def _looked_up(project: str, name: str, read: Callable[[], Any]) -> Any:
        """Run one roster read, mapping its refusals onto the lane's status codes."""
        _fenced(project, name)
        try:
            return read()
        except agent_chat.AgentUnknown:
            raise _unknown(project, name) from None
        except host_fleet.FleetUnavailable as e:
            raise logged_denial(e, 503, "fleet_unavailable") from e
        except host_fleet.FleetMisuse as e:
            raise logged_denial(e, 500, "roster_misuse") from e

    @app.get("/v1/agent/{project}/{name}/usage")
    def agent_usage_read(project: str, name: str, record: dict = Depends(require_scope("read"))) -> dict:
        """The agent's context window and its provider's plan limits; the sign-in token never leaves the process."""
        return _looked_up(project, name, lambda: agent_usage.read(project, name))

    @app.post("/v1/agent/{project}/{name}/model")
    def agent_model(
        project: str, name: str, record: dict = Depends(require_scope("operate")), body: Any = Depends(_json_body)
    ) -> dict:
        """Type the agent's /model line, or its switch command to another provider, then the slash menu's Enter."""
        fields = body if isinstance(body, dict) else {}
        picked = [fields.get(key) for key in MODEL_FIELDS]
        if not (fields.get("model") or fields.get("provider")) or not all(
            v is None or isinstance(v, str) for v in picked
        ):
            raise deny(400, "agent_model_refused", "The body is {provider?, model?, effort?}: a model or a provider.")
        provider, model, effort = picked
        row = _looked_up(project, name, lambda: agent_chat.find_agent(project, name))
        line, why = agent_models.switch_line(row, provider, model, effort)
        if line is None:
            raise deny(400, "agent_model_refused", why or "That switch is refused.")
        state = agent_models.busy_state(row)
        if state:
            raise deny(409, "agent_busy", f"{name} is {state}; switch its model when it is idle.")
        _keystrokes(project, name, lambda: agent_models.type_line(project, name, line))
        return {"ok": True, "typed": line}

    def _key_route(action: str) -> None:
        """Hang one key action's route on the app."""

        def agent_key(project: str, name: str, record: dict = Depends(require_scope("operate"))) -> dict:
            """Press the action's key in the agent's room; the body, {} by contract, is not read."""
            return _keystrokes(project, name, lambda: agent_chat.press(project, name, action))

        agent_key.__name__ = f"agent_{action}"
        app.post(f"/v1/agent/{{project}}/{{name}}/{action}")(agent_key)

    for action in agent_chat.KEYS:
        _key_route(action)

    json_handler.log_operation("host_api_agent_route_registered", {"keys": sorted(agent_chat.KEYS)})
