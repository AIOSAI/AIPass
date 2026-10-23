# =================== AIPass ====================
# Name: config.py
# Description: Host API Config Handler — server config, bind-address and face-dir validation
# Version: 1.2.1
# Created: 2026-08-14
# Modified: 2026-10-22
# =============================================

"""
Host API Config Handler

Reference: docs/host_api.md (the bind rule), docs/host_surfaces.md (face_dir, baud_bin).
Lives in the secrets store's keyring (not a secret): one machine root, no repo discovery, never ships.
"""

import ipaddress
import os
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

# Deliberately absent from DEFAULT_CONFIG: unset means the checkout build, never stored.
FACE_DIR_KEY = "face_dir"

# Lives here, not in face.py: set_face_dir() checks it and face.py imports this module.
FACE_ENTRY = "phone.html"

BAUD_BIN_KEY = "baud_bin"

# Governs ONE refusal, the non-loopback one. Wildcards, hostnames, unheld addresses
# and bad ports refuse regardless; False never makes 0.0.0.0 bindable.
LOOPBACK_ONLY = False

DEFAULT_CONFIG: Dict[str, Any] = {
    "host": DEFAULT_HOST,
    "port": DEFAULT_PORT,
}


class BindRefused(Exception):
    """The configured bind address was refused. The server must not start."""


class FaceDirRefused(ValueError):
    """The face directory was refused. Nothing was stored."""


class BaudBinRefused(ValueError):
    """The baud binary path was refused. Nothing was stored."""


def load_config() -> Dict[str, Any]:
    """Read the effective server config."""
    config = dict(DEFAULT_CONFIG)

    stored = secrets_store.get_secret(CONFIG_PROVIDER, CONFIG_SLUG, as_json=True)
    if isinstance(stored, dict):
        config.update(stored)
    elif stored is not None:
        logger.warning("[host_api] config store is not a JSON object — using defaults")

    return config


def save_config(config: Dict[str, Any]) -> str:
    """Persist server config to the keyring entry host_api/config; returns the entry's name."""
    entry = secrets_store.set_secret(CONFIG_PROVIDER, CONFIG_SLUG, config, as_json=True)
    # Named in words: CodeQL flags the secret-named call's result in a log as clear-text secret.
    logger.info("[host_api] config saved to the host_api config in the secrets store")
    return entry


def set_bind(host: str, port: int) -> Dict[str, Any]:
    """Validate and store the bind address: set-config --host --port as a function."""
    validate_bind(host, port)

    config = load_config()
    previous = {"host": config["host"], "port": config["port"]}
    bind = {"host": str(host).strip(), "port": port}

    if previous == bind:
        return {**bind, "changed": False, "previous": previous}

    config.update(bind)
    save_config(config)
    json_handler.log_operation("host_api_config_saved", bind)
    return {**bind, "changed": True, "previous": previous}


def face_dir() -> Optional[Path]:
    """The configured phone-face directory."""
    # Never re-validated: None for a since-emptied dir would quietly serve the checkout build.
    stored = load_config().get(FACE_DIR_KEY)
    return None if stored is None else Path(str(stored))


def set_face_dir(path: Optional[Path]) -> Optional[Path]:
    """Store the phone-face directory, or clear it."""
    if path is None:
        if _write_setting(FACE_DIR_KEY, None):
            json_handler.log_operation("host_api_face_dir_cleared", {})
            logger.info("[host_api] face dir cleared: the checkout build serves after a restart")
        return None

    candidate = validate_face_dir(path)
    _write_setting(FACE_DIR_KEY, candidate)

    logger.info("[host_api] face dir set to %s: served after a restart", candidate)
    json_handler.log_operation("host_api_face_dir_set", {"face_dir": str(candidate)})
    return candidate


def validate_face_dir(path: Path) -> Path:
    """Check a face dir the way set_face_dir() will, storing nothing."""
    candidate = Path(path)
    if not candidate.is_absolute():
        raise FaceDirRefused(f"The face dir must be an absolute path, got: {str(path)!r}")
    if not candidate.is_dir():
        raise FaceDirRefused(f"The face dir is not a directory: {candidate}")
    if not (candidate / FACE_ENTRY).is_file():
        raise FaceDirRefused(f"The face dir has no {FACE_ENTRY}: {candidate} (point it at a built phone bundle)")
    return candidate


def baud_bin() -> Optional[Path]:
    """The configured baud binary."""
    # Never re-validated: None for a vanished binary would quietly hand the lanes the automatic lookup.
    stored = load_config().get(BAUD_BIN_KEY)
    return None if stored is None else Path(str(stored))


def set_baud_bin(path: Optional[Path]) -> Optional[Path]:
    """Store the baud binary the host lanes exec, or clear it back to automatic."""
    if path is None:
        if _write_setting(BAUD_BIN_KEY, None):
            json_handler.log_operation("host_api_baud_bin_cleared", {})
            logger.info("[host_api] baud binary cleared: the automatic lookup answers the next request")
        return None

    candidate = validate_baud_bin(path)
    _write_setting(BAUD_BIN_KEY, candidate)

    logger.info("[host_api] baud binary set to %s: used from the next request", candidate)
    json_handler.log_operation("host_api_baud_bin_set", {"baud_bin": str(candidate)})
    return candidate


def validate_baud_bin(path: Path) -> Path:
    """Check a baud binary path the way set_baud_bin() will, storing nothing."""
    candidate = Path(path)
    if not candidate.is_absolute():
        raise BaudBinRefused(f"The baud binary must be an absolute path, got: {str(path)!r}")
    if not candidate.exists():
        raise BaudBinRefused(f"The baud binary does not exist: {candidate}")
    if not candidate.is_file():
        raise BaudBinRefused(f"The baud binary is not a regular file: {candidate}")
    if not os.access(candidate, os.X_OK):
        raise BaudBinRefused(f"The baud binary is not executable: {candidate} (chmod +x it, or name another)")
    return candidate


def _write_setting(key: str, value: Optional[Path]) -> bool:
    """Store one path setting, or remove it, keeping every other key in the store."""
    config = load_config()
    if value is None:
        if key not in config:
            return False
        del config[key]
    else:
        config[key] = str(value)
    save_config(config)
    return True


def pin_registry() -> Any:
    """Pin the citizen registry for the life of this process."""
    # Call from serve(), never create_app(): the suite must not have drone mutated under it.
    # Pinned, not exported: an env var only reaches child processes.
    import aipass.drone as drone

    found = Path(drone.get_registry_path())
    if not found.is_file():
        logger.warning("[host_api] no registry to pin at %s — drone keeps resolving per lookup", found)
        return None

    drone.set_registry_path(found)
    logger.info("[host_api] registry pinned for this process: %s", found)
    return found


def validate_bind(host: str, port: int) -> None:
    """Enforce the bind rule. Returns None if the address may be bound."""
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

    # A wildcard binds fine everywhere; that is the danger: it answers on every interface.
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
    json_handler.log_operation(
        "host_api_bind_validated",
        {"host": host, "port": port, "loopback": address.is_loopback},
    )


def _probe_bind(host: str, address: Any) -> None:
    """Confirm the machine actually holds *host* by binding it on an ephemeral port."""
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET

    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.bind((host, 0))
    except OSError as e:
        raise BindRefused(
            f"Address {host!r} is not available on this machine ({e}). "
            "Refusing to start rather than falling back to another address."
        ) from e
