# =================== AIPass ====================
# Name: config.py
# Description: Host API Config Handler — server config, bind-address and face-dir validation
# Version: 1.1.0
# Created: 2026-08-14
# Modified: 2026-09-13
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

THE LOOPBACK GATE IS OPEN: LOOPBACK_ONLY has been False since 2026-08-14, Patrick's
ruling on the security review (FPLAN-0411 Phase 5). An address this machine holds
is accepted, the tailnet one included; every other refusal above still stands.
Read the flag's own comment before assuming more than that.

THE FACE DIR (FPLAN-0587): where the phone face is served from, stored beside the
bind under the key face_dir. The bind rule's doctrine applies: validated before it
is stored, refused otherwise, nothing half-written. Unset means the checkout
build. face.py makes that call; this file only stores the choice.

Functions:
    load_config()   - Effective config, defaults merged under any stored values
    save_config()   - Persist config to the store
    face_dir()      - The configured phone-face directory, or None
    set_face_dir()  - Validate and store it, or clear it; raises FaceDirRefused
    validate_bind() - Enforce the bind rule; raises BindRefused
    pin_registry()  - Take drone's registry fast path once, at boot
"""

import ipaddress
import socket
from pathlib import Path
from typing import Any, Dict, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.auth import secrets as secrets_store

CONFIG_PROVIDER = "host_api"
CONFIG_SLUG = "config"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

# The phone face's directory, when one is configured. Deliberately absent from
# DEFAULT_CONFIG: unset means the checkout build, and that is never stored.
FACE_DIR_KEY = "face_dir"

# @baud's entry document. Named here rather than in face.py because
# set_face_dir() checks for it, and face.py imports this module, not the reverse.
FACE_ENTRY = "phone.html"

# OPENED 2026-08-14 by Patrick's ruling on the Phase 5 security review (C1 audit
# shipped, C2 blast radius accepted in his words, C3 admission list verified by
# devpulse: exactly two enrolled devices, both his).
#
# READ THIS BEFORE ASSUMING THE GATE IS GONE. This flag governs ONE refusal — the
# non-loopback one. Everything else in validate_bind() is independent of it and
# still refuses: wildcards (is_unspecified), hostnames, addresses this machine
# does not hold, and out-of-range ports. Setting it False widens the server from
# "loopback only" to "one real address this machine actually holds". It does NOT
# make 0.0.0.0 bindable, and the ratified NO-GO says nothing beyond the tailnet.
LOOPBACK_ONLY = False

DEFAULT_CONFIG: Dict[str, Any] = {
    "host": DEFAULT_HOST,
    "port": DEFAULT_PORT,
}


class BindRefused(Exception):
    """The configured bind address was refused. The server must not start."""


class FaceDirRefused(ValueError):
    """The face directory was refused. Nothing was stored."""


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
# FACE DIR
# ==============================================


def face_dir() -> Optional[Path]:
    """
    The configured phone-face directory.

    Read as stored, never re-validated here: a directory that was valid when it
    was stored and has emptied since is face.py's to report, naming the
    configured source. Answering None for it would quietly hand the phone the
    checkout build instead.

    Returns:
        The stored directory, or None when no face_dir is configured.
    """
    stored = load_config().get(FACE_DIR_KEY)
    return None if stored is None else Path(str(stored))


def set_face_dir(path: Optional[Path]) -> Optional[Path]:
    """
    Store the phone-face directory, or clear it.

    Validated BEFORE anything is written, the bind rule's doctrine: a directory
    that would not serve is refused while whoever named it is still there, not
    at the first navigation after a restart. Either way a running server keeps
    the directory it started with (face.py, KNOWN LIMIT).

    "~" is not expanded here. A caller holding a shell-style path expands it
    first; this layer only ever stores an absolute path.

    Args:
        path: An absolute directory holding phone.html, or None to clear.

    Returns:
        The stored directory, or None when cleared. Clearing when nothing is
        configured writes nothing.

    Raises:
        FaceDirRefused: Not absolute, not a directory, or no phone.html in it.
            Nothing is stored.
    """
    if path is None:
        config = load_config()
        if FACE_DIR_KEY in config:
            del config[FACE_DIR_KEY]
            save_config(config)
            json_handler.log_operation("host_api_face_dir_cleared", {})
            logger.info("[host_api] face dir cleared: the checkout build serves after a restart")
        return None

    candidate = Path(path)
    if not candidate.is_absolute():
        raise FaceDirRefused(f"The face dir must be an absolute path, got: {str(path)!r}")
    if not candidate.is_dir():
        raise FaceDirRefused(f"The face dir is not a directory: {candidate}")
    if not (candidate / FACE_ENTRY).is_file():
        raise FaceDirRefused(f"The face dir has no {FACE_ENTRY}: {candidate} (point it at a built phone bundle)")

    config = load_config()
    config[FACE_DIR_KEY] = str(candidate)
    save_config(config)

    logger.info("[host_api] face dir set to %s: served after a restart", candidate)
    json_handler.log_operation("host_api_face_dir_set", {"face_dir": str(candidate)})
    return candidate


# ==============================================
# LAUNCH ENVIRONMENT
# ==============================================


def pin_registry() -> Any:
    """
    Pin the citizen registry for the life of this process.

    drone resolves the registry per lookup: walk up from CWD, glob each parent
    for *_REGISTRY.json, and read the nearest passport to credential-check every
    candidate. That is filesystem work on EVERY branch resolution, and this
    server resolves branches on most of its read routes. drone already carries
    the fast path — set_registry_path() takes priority over the AIPASS_REGISTRY
    env var, which takes priority over the walk — so a long-lived server should
    take it once at boot instead of paying the walk per request.

    Pinning, not exporting: set_registry_path is drone's own public door and
    covers every launch method (module, console script, uvicorn reload child),
    while an env var only reaches processes this one spawns.

    Returns:
        The pinned path, or None when no registry was found (nothing pinned —
        drone keeps its own resolution, which is what it does today).

    Note:
        Called from serve(), never from create_app(): the test suite builds
        apps constantly and must not have its drone module mutated underneath it.
        The measured saving is 0.73ms per lookup. The OTHER 10ms of a
        get_branch_info lives in drone's own tree — an audit-log write and a
        full re-read plus per-branch path resolve on every call — and is
        reported, not reached into from here.
    """
    import aipass.drone as drone

    found = Path(drone.get_registry_path())
    if not found.is_file():
        logger.warning("[host_api] no registry to pin at %s — drone keeps resolving per lookup", found)
        return None

    drone.set_registry_path(found)
    logger.info("[host_api] registry pinned for this process: %s", found)
    return found


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
