# =================== AIPass ====================
# Name: config.py
# Description: Host API Config Handler — server config and bind-address validation
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""
Host API Config Handler

Server configuration and the bind-address gate (FPLAN-0411 design call D1).

Config lives at ~/.secrets/aipass/host_api/config.json — the same 0o700 root the
rest of this branch's credentials use. It is not itself a secret; it lives there
so the server has ONE machine-level root, needs no repo-root discovery (which
breaks for an installed package), and never ships in the public repo.

THE BIND RULE — the security property this whole file exists for:

    The server binds the address it was configured for, or it refuses to start.
    There is no fallback. A silent widen means a server that intended to be
    private is answering the whole network.

So a wildcard address is refused outright (0.0.0.0 and :: BIND FINE — that is
exactly what makes them dangerous), a hostname is refused as ambiguous, and an
address the machine does not actually hold is refused rather than quietly
becoming something else.

PHASE 1 RESERVATION: LOOPBACK_ONLY is True. Non-loopback binds — the tailnet
100.x address Stage 0 is aimed at — are refused until the security review gate
(FPLAN-0411 Phase 5) clears the first network-listening service in AIPass.
Flipping this constant is the whole change; the machinery below already handles
any address.

Functions:
    load_config()   - Effective config, defaults merged under any stored values
    save_config()   - Persist config to the store
    validate_bind() - Enforce the bind rule; raises BindRefused
"""

import ipaddress
import socket
from typing import Any, Dict

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.auth import secrets as secrets_store

CONFIG_PROVIDER = "host_api"
CONFIG_SLUG = "config"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

# Phase 1 gate. See the module docstring — this is a reservation, not a limit of
# the code below. Phase 5's security review is what flips it.
LOOPBACK_ONLY = True

DEFAULT_CONFIG: Dict[str, Any] = {
    "host": DEFAULT_HOST,
    "port": DEFAULT_PORT,
}


class BindRefused(Exception):
    """The configured bind address was refused. The server must not start."""


# ==============================================
# CONFIG
# ==============================================


def load_config() -> Dict[str, Any]:
    """
    Read the effective server config.

    Stored values are merged over the defaults, so a config file carrying only a
    port still gets the loopback host. A missing or unreadable store yields the
    defaults — the defaults are safe (loopback), so this is not a silent widen.

    Returns:
        Config dict with at least 'host' and 'port'.
    """
    config = dict(DEFAULT_CONFIG)

    stored = secrets_store.get_secret(CONFIG_PROVIDER, CONFIG_SLUG, as_json=True)
    if isinstance(stored, dict):
        config.update(stored)
    elif stored is not None:
        logger.warning("[host_api] config store is not a JSON object — using defaults")

    return config


def save_config(config: Dict[str, Any]) -> str:
    """
    Persist server config to the store.

    Args:
        config: Config dict to write.

    Returns:
        Path to the written file, as a string.
    """
    path = secrets_store.set_secret(CONFIG_PROVIDER, CONFIG_SLUG, config, as_json=True)
    logger.info("[host_api] config saved to %s", path)
    return str(path)


# ==============================================
# BIND VALIDATION
# ==============================================


def validate_bind(host: str, port: int) -> None:
    """
    Enforce the bind rule. Returns None if the address may be bound.

    Args:
        host: Literal IP address to bind. Hostnames are refused.
        port: TCP port, 1-65535.

    Raises:
        BindRefused: Wildcard address, hostname, out-of-range port, an address
            this machine does not hold, or (while LOOPBACK_ONLY) any
            non-loopback address.
    """
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise BindRefused(f"Port must be an integer in 1-65535, got: {port!r}")

    if not host or not str(host).strip():
        raise BindRefused("No bind address configured — refusing to start")

    host = str(host).strip()

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise BindRefused(
            f"Bind address must be a literal IP, got hostname: {host!r} "
            "(use 127.0.0.1 rather than 'localhost' — a name is ambiguous, and "
            "an ambiguous bind is how a private server ends up public)"
        ) from None

    # A wildcard binds successfully on every machine. That is the danger, not a
    # reason to allow it: it means "answer on every interface I have".
    if address.is_unspecified:
        raise BindRefused(
            f"Refusing the wildcard bind address {host!r} — it listens on every "
            "interface. Name the exact address this server should answer on."
        )

    if LOOPBACK_ONLY and not address.is_loopback:
        raise BindRefused(
            f"Refusing non-loopback bind {host!r}: Phase 1 is loopback-only. "
            "A wider bind is gated on the security review (FPLAN-0411 Phase 5) — "
            "this would be the first network-listening service in AIPass."
        )

    _probe_bind(host, address)

    logger.info("[host_api] bind address validated: %s:%s", host, port)
    # An audit line for every address this server was ever allowed to bind.
    json_handler.log_operation(
        "host_api_bind_validated",
        {"host": host, "port": port, "loopback": address.is_loopback},
    )


def _probe_bind(host: str, address: Any) -> None:
    """
    Confirm the machine actually holds *host* by binding it on an ephemeral port.

    Asking the OS beats maintaining an interface-enumeration of our own, and it
    is the same question the real bind will ask a moment later.

    Args:
        host: Literal IP address.
        address: The parsed ipaddress object, for family selection.

    Raises:
        BindRefused: The address is not available on this machine.
    """
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET

    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.bind((host, 0))
    except OSError as e:
        raise BindRefused(
            f"Address {host!r} is not available on this machine ({e}). "
            "Refusing to start rather than falling back to another address."
        ) from e
