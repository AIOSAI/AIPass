# =================== AIPass ====================
# Name: protocol.py
# Description: Typed protocol for broker IPC
# Version: 1.0.1
# Created: 2026-06-09
# Modified: 2026-10-23
# =============================================

"""Typed protocol for broker IPC.

JSON-line messages over a unix socket. Extensible — only ``delete`` is
implemented now, but the envelope supports future operation types.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Literal

from aipass.drone.apps.handlers.json import json_handler


@dataclass
class BrokerRequest:
    """A request from sandboxed drone to the broker."""

    op: Literal["delete", "identify"]
    path: str = ""
    request_id: str = ""
    extra: dict[str, str] = field(default_factory=dict)
    branch: str = ""
    hmac: str = ""

    def to_bytes(self) -> bytes:
        """Serialize to a newline-terminated JSON bytes line."""
        return json.dumps(asdict(self), separators=(",", ":")).encode() + b"\n"

    @classmethod
    def from_bytes(cls, data: bytes) -> BrokerRequest:
        """Deserialize from JSON bytes; ValueError/KeyError/TypeError/AttributeError on a malformed line."""
        d = json.loads(data)
        json_handler.log_operation("broker_request_parse", {"op": d.get("op", "")})
        req = cls(
            op=d["op"],
            path=d.get("path", ""),
            request_id=d.get("request_id", ""),
            extra=d.get("extra", {}),
            branch=d.get("branch", ""),
            hmac=d.get("hmac", ""),
        )
        for name in ("op", "path", "request_id", "branch", "hmac"):
            if not isinstance(getattr(req, name), str):
                raise TypeError(f"{name} must be a string")
        return req


@dataclass
class BrokerResponse:
    """The broker's reply."""

    ok: bool
    message: str
    request_id: str = ""
    error_code: str = ""

    def to_bytes(self) -> bytes:
        """Serialize to a newline-terminated JSON bytes line."""
        return json.dumps(asdict(self), separators=(",", ":")).encode() + b"\n"

    @classmethod
    def from_bytes(cls, data: bytes) -> BrokerResponse:
        """Deserialize from JSON bytes."""
        d = json.loads(data)
        return cls(
            ok=d["ok"],
            message=d["message"],
            request_id=d.get("request_id", ""),
            error_code=d.get("error_code", ""),
        )
