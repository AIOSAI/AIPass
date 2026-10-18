# =================== AIPass ====================
# Name: pair_route.py
# Description: Host API Pair Route — POST /v1/pair, the one route without a bearer
# Version: 1.0.0
# Created: 2026-10-13
# Modified: 2026-10-17
# =============================================
# pyright: reportMissingImports=false, reportInvalidTypeForm=false, reportOptionalCall=false
# The suppressions cover the optional-dependency placeholders, as in server.py:
# without the [host] extra these names are None, and register() is only ever
# called from create_app(), which refuses first when the extra is missing.

"""
Host API Pair Route
Here and not in server.py, which sits at its 1500-line cap. Reference: docs/host_api.md"""

from typing import Any, Callable

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import denials as host_denials
from aipass.api.apps.handlers.host import pairings as host_pairings

try:
    from fastapi import Body, Request
except ImportError as e:
    logger.debug("[host_api] pair route libraries not available: %s", e)
    Body = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]


def register(app: Any, deny: Callable[..., Any], peer: Callable[[Any], str]) -> None:
    """Add POST /v1/pair to *app*."""
    window = host_pairings.AttemptWindow()

    # def, not async: a redeem takes a file lock and writes two stores.
    @app.post("/v1/pair")
    def pair(request: Request, payload: Any = Body(default=None)) -> dict:
        """Trade a one-use pairing code for a bearer. 200, or 401/429/400 through the envelope."""
        try:
            status, body = host_pairings.answer_pair(payload, peer(request), window)
        except host_pairings.PairingError as e:
            ref = host_denials.logged(e, 503, "pairing_unavailable")
            status, body = 503, {"code": "pairing_unavailable", "ref": ref}
            body["message"] = host_denials.SENTENCES["pairing_unavailable"]
        if status != 200:
            raise deny(status, body.pop("code"), body.pop("message"), **body)
        return body

    json_handler.log_operation("host_api_pair_route_registered", {"limit": window.limit, "seconds": window.seconds})
