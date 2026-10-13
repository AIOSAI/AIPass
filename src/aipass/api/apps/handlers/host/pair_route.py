# =================== AIPass ====================
# Name: pair_route.py
# Description: Host API Pair Route — POST /v1/pair, the one route without a bearer
# Version: 1.0.0
# Created: 2026-10-13
# Modified: 2026-10-13
# =============================================
# pyright: reportMissingImports=false, reportInvalidTypeForm=false, reportOptionalCall=false
# The suppressions cover the optional-dependency placeholders, as in server.py:
# without the [host] extra these names are None, and register() is only ever
# called from create_app(), which refuses first when the extra is missing.

"""
Host API Pair Route

POST /v1/pair (DPLAN-0406). A phone that scanned a pairing QR posts the code from
the URL's fragment and receives a bearer. The answer is pairings.answer_pair();
this file is the glue that hangs it on the app. Here and not in server.py, which
sits at its 1500-line cap.

The one route without a bearer dependency: the code IS the credential, for one
use and five minutes. A wrong code is throttled per client address, ten a
minute, by an attempt window that lives as long as the app.

Functions:
    register() - Add POST /v1/pair to an app
"""

from typing import Any, Callable

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import denials as host_denials
from aipass.api.apps.handlers.host import pairings as host_pairings

try:
    from fastapi import Body, Request
except ImportError as e:
    # server.py warns about the missing extra; register() is never reached.
    logger.debug("[host_api] pair route libraries not available: %s", e)
    Body = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]


def register(app: Any, deny: Callable[..., Any], peer: Callable[[Any], str]) -> None:
    """
    Add POST /v1/pair to *app*.

    Args:
        app: The FastAPI app.
        deny: server._deny, so every refusal leaves through the one envelope.
        peer: server._peer, the caller's address as the audit names it.
    """
    window = host_pairings.AttemptWindow()

    # def, not async: a redeem takes a file lock and writes two stores (DPLAN-0305).
    @app.post("/v1/pair")
    def pair(request: Request, payload: Any = Body(default=None)) -> dict:
        """Trade a one-use pairing code for a bearer. 200, or 401/429/400 through the envelope."""
        try:
            status, body = host_pairings.answer_pair(payload, peer(request), window)
        except host_pairings.PairingError as e:
            # The words go to the log under a ref; the phone gets the fixed sentence.
            ref = host_denials.logged(e, 503, "pairing_unavailable")
            status, body = 503, {"code": "pairing_unavailable", "ref": ref}
            body["message"] = host_denials.SENTENCES["pairing_unavailable"]
        if status != 200:
            raise deny(status, body.pop("code"), body.pop("message"), **body)
        return body

    json_handler.log_operation("host_api_pair_route_registered", {"limit": window.limit, "seconds": window.seconds})
