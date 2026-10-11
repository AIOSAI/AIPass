# =================== AIPass ====================
# Name: client.py
# Description: Broker client — sends delete requests over inherited fd
# Version: 2.0.1
# Created: 2026-06-09
# Modified: 2026-09-27
# =============================================

"""Broker client — sends delete requests over an inherited socket fd.

When ``AIPASS_BROKER_FD`` is set, ``drone rm`` uses this client to send
delete requests to the out-of-sandbox broker daemon instead of calling
``Path.unlink`` directly. The fd was pre-opened by the launch wrapper
before the sandbox locked.

Launcher contract (Phase 6a):
    ``create_identified_connection()`` connects to the broker socket,
    reads the per-start secret, computes the HMAC, sends the identify
    preamble, and returns the authenticated socket.  The caller passes
    the socket's fd to the sandboxed child via AIPASS_BROKER_FD.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import os
import socket
import uuid
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.broker.protocol import BrokerRequest, BrokerResponse

BROKER_FD_ENV = "AIPASS_BROKER_FD"


def is_sandboxed() -> bool:
    """Return True if running inside a sandbox with a broker fd available."""
    return BROKER_FD_ENV in os.environ


def _get_broker_fd() -> int | None:
    """Return the inherited broker socket fd, or None if not set.

    Raises ValueError when the variable is set but is not a non-negative
    integer, so an invalid fd is never reported as an unset one.
    """
    raw = os.environ.get(BROKER_FD_ENV)
    if raw is None:
        return None
    try:
        fd = int(raw)
    except ValueError as exc:
        logger.warning("broker client: non-integer AIPASS_BROKER_FD=%s", raw)
        raise ValueError(f"non-integer {BROKER_FD_ENV}={raw!r}") from exc
    if fd < 0:
        logger.warning("broker client: invalid fd %d", fd)
        raise ValueError(f"negative {BROKER_FD_ENV}={fd}")
    return fd


def create_identified_connection(
    socket_path: str | Path,
    secret_path: str | Path,
    branch: str,
) -> socket.socket:
    """Connect to the broker, authenticate via HMAC, return the identified socket.

    This is the launcher contract for dispatch_monitor.  The returned
    socket fd should be passed to the sandboxed child via AIPASS_BROKER_FD.

    Args:
        socket_path: Path to the broker's unix socket.
        secret_path: Path to the broker's per-start secret file (mode 0600).
        branch: Branch name to identify as.

    Returns:
        A connected, identified ``socket.socket``.

    Raises:
        RuntimeError: If identification fails (bad HMAC, broker error).
        OSError: If the socket or secret file cannot be accessed.
    """
    secret = Path(secret_path).read_bytes()
    mac = hmac_mod.new(secret, branch.encode(), hashlib.sha256).hexdigest()

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(socket_path))

    req = BrokerRequest(op="identify", branch=branch, hmac=mac)
    sock.sendall(req.to_bytes())

    data = b""
    while b"\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            sock.close()
            raise RuntimeError("Broker closed connection during identify")
        data += chunk

    resp = BrokerResponse.from_bytes(data)
    if not resp.ok:
        sock.close()
        raise RuntimeError(f"Broker identify failed: {resp.message}")

    logger.info("broker client: identified as %s", branch)
    json_handler.log_operation("broker_identify", {"branch": branch})
    return sock


def broker_delete(path: str) -> tuple[bool, str]:
    """Send a delete request to the broker over the inherited fd.

    Returns ``(success, message)`` matching the pattern in ``rm_handler.safe_delete``.
    """
    try:
        fd = _get_broker_fd()
    except ValueError as exc:
        return False, f"Broker fd invalid: {exc}"
    if fd is None:
        return False, "Broker fd not available (AIPASS_BROKER_FD not set)"

    request_id = uuid.uuid4().hex[:8]
    req = BrokerRequest(op="delete", path=path, request_id=request_id)
    json_handler.log_operation(
        "broker_delete_request",
        {"path": path, "fd": fd, "request_id": request_id},
    )

    try:
        sock = socket.socket(fileno=fd)
        sock.setblocking(True)
        try:
            sock.sendall(req.to_bytes())

            data = b""
            while b"\n" not in data:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk

            if not data.strip():
                logger.error("broker client: empty response from broker")
                return False, "Broker returned empty response"

            resp = BrokerResponse.from_bytes(data)
            logger.info(
                "broker client: %s for %s: %s",
                "ok" if resp.ok else "refused",
                path,
                resp.message,
            )
            return resp.ok, resp.message
        finally:
            sock.detach()
    except OSError as exc:
        logger.error("broker client: socket error for %s: %s", path, exc)
        return False, f"Broker communication failed: {exc}"
