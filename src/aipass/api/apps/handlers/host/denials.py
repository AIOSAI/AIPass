# =================== AIPass ====================
# Name: denials.py
# Description: Host API Denials — the fixed sentence a client gets, the words the log keeps
# Version: 1.0.1
# Created: 2026-10-10
# Modified: 2026-10-13
# =============================================

"""
Host API Denials

How the host API says no when a caught exception is the reason. The exception's
words belong to the operator: they can carry a host path, another program's
stderr, another branch's JSON, an OSError's text. Copied into a response they go
to whoever sent the request (CodeQL py/stack-trace-exposure, PR #774; seedgo
exception_text_in_response). So the words go to this host's log with the
traceback, the client gets one fixed sentence per error code, and a short `ref`
on both sides joins the two: the handset shows it, the operator greps for it.

The code is still the contract. A client branches on `code` (and on `reason`
where a route carries one), never on prose, so the prose can be fixed without
taking anything a client can act on.

Split out of server.py, which sits at its 1500-line cap; the stand-in exception
class came with it, being the other half of "what an error looks like here".

Classes:
    UnavailableHTTPException - Stand-in for FastAPI's HTTPException without the [host] extra

Functions:
    logged()  - Log a caught exception's words under a fresh ref, and return the ref
"""

import uuid
from typing import Any

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

#: The one sentence each error code hands a client when an exception is the reason.
#: Every one ends by saying where the words went, so nobody reads it as the whole story.
SENTENCES = {
    "face_unavailable": "The phone face could not be served; the reason is in this host's log",
    "feed_unavailable": "The notification feed could not be read; the reason is in this host's log",
    "fleet_unavailable": "@baud could not answer this read; the reason is in this host's log",
    "lock_door_failed": "@skills' lock_state() could not answer; the reason is in this host's log",
    "machine_refused": "@skills refused the machine read; its code is in `reason`, its words in this host's log",
    "memory_config_refused": "@memory refused this config request; the reason is in this host's log",
    "memory_config_unavailable": "@memory could not answer this config request; the reason is in this host's log",
    "pairing_unavailable": "The pairing could not be completed; the reason is in this host's log",
    "read_refused": "This read was refused; the reason is in this host's log",
    "read_unavailable": "This read could not be answered; the reason is in this host's log",
    "roots_unavailable": "The branch roots could not be listed; the reason is in this host's log",
    "roster_misuse": "This server asked @baud for the roster in a way it refuses; the reason is in this host's log",
    "settings_refused": "This settings request was refused; the reason is in this host's log",
    "settings_unavailable": "The settings could not be read or written; the reason is in this host's log",
    "upload_unavailable": "The upload could not be stored; the reason is in this host's log",
    "verb_unavailable": "This action could not be carried out; the reason is in this host's log",
}

#: The socket lanes close with one of these: a close reason is a response too.
SOCKET_CENSUS_FAILED = "@baud could not resolve this room; the reason is in this host's log"
SOCKET_UNAVAILABLE = "This room could not be opened; the reason is in this host's log"


class UnavailableHTTPException(Exception):
    """
    Stand-in for FastAPI's HTTPException when the [host] extra is absent.

    It mirrors the real signature because the name is both raised and handed to
    @app.exception_handler(), which wants a class. Learning banked on d7330b00:
    an import fallback that lands in a type position cannot be None.
    """

    def __init__(self, status_code: int = 500, detail: Any = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def logged(error: BaseException, status: int, code: str) -> str:
    """
    Keep a caught exception's words in this host's log, under a fresh ref.

    Args:
        error: The exception that is the reason for the refusal.
        status: The HTTP status the client is about to get.
        code: The error code the client is about to get.

    Returns:
        The ref: short enough to read off a handset, unique enough to grep.
    """
    ref = uuid.uuid4().hex[:12]
    logger.warning("[host_api] %s %s refused (ref %s): %s", status, code, ref, error, exc_info=error)
    json_handler.log_operation("host_api_denied", {"status": status, "code": code, "ref": ref})
    return ref
