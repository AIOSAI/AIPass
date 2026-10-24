# =================== AIPass ====================
# Name: client.py
# Description: Broker client — sends delete requests over inherited fd
# Version: 2.0.2
# Created: 2026-06-09
# Modified: 2026-10-23
# =============================================

"""Broker client — sends delete requests over an inherited socket fd.

Reference: docs/broker.md
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import os
import socket
import threading
import uuid
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.broker.protocol import BrokerRequest, BrokerResponse

try:
    import fcntl
except ImportError:
    fcntl = None
    logger.info("broker client: fcntl unavailable (Windows), and no broker either")

BROKER_FD_ENV = "AIPASS_BROKER_FD"

# A POSIX lock excludes other processes on the shared fd but not this one's threads.
_FD_THREAD_LOCK = threading.Lock()


def is_sandboxed() -> bool:
    """Return True if running inside a sandbox with a broker fd available."""
    return BROKER_FD_ENV in os.environ


def _get_broker_fd() -> int | None:
    """Return the inherited broker socket fd, or None if not set.

    Raises ValueError for a set-but-invalid value, so it is never reported as unset.
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

    Launcher contract: the caller passes this socket's fd to the sandboxed child via AIPASS_BROKER_FD.
    """
    secret = Path(secret_path).read_bytes()
    mac = hmac_mod.new(secret, branch.encode(), hashlib.sha256).hexdigest()

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(str(socket_path))

        req = BrokerRequest(op="identify", branch=branch, hmac=mac)
        sock.sendall(req.to_bytes())

        data = b""
        while b"\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError("Broker closed connection during identify")
            data += chunk

        resp = BrokerResponse.from_bytes(data)
        if not resp.ok:
            raise RuntimeError(f"Broker identify failed: {resp.message}")
    except BaseException:
        sock.close()
        raise

    logger.info("broker client: identified as %s", branch)
    json_handler.log_operation("broker_identify", {"branch": branch})
    return sock


def _exchange(sock: socket.socket, fd: int, req: BrokerRequest) -> bytes:
    """Send one request and read one reply line, holding the fd's lock so no sharer reads it."""
    # lockf, not flock: flock belongs to the open file description every sharing process holds.
    with _FD_THREAD_LOCK:
        if fcntl is not None:
            fcntl.lockf(fd, fcntl.LOCK_EX)
        try:
            sock.sendall(req.to_bytes())
            data = b""
            while b"\n" not in data:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            return data
        finally:
            if fcntl is not None:
                fcntl.lockf(fd, fcntl.LOCK_UN)


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
            data = _exchange(sock, fd, req)
            if not data.strip():
                logger.error("broker client: empty response from broker")
                return False, "Broker returned empty response"

            try:
                resp = BrokerResponse.from_bytes(data)
            except (ValueError, KeyError) as exc:
                logger.error("broker client: malformed reply for %s: %s", path, exc)
                return False, f"Broker returned a malformed reply: {exc}"
            if resp.request_id != request_id:
                logger.error("broker client: reply %r answers another request than %r", resp.request_id, request_id)
                return False, f"Broker reply was for request {resp.request_id!r}, not {request_id!r}"
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
