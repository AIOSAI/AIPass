# =================== AIPass ====================
# Name: phone_ready.py
# Description: Read what the phone needs after the face lands: the tailnet address, @api's bind, a live server
# Version: 1.0.0
# Created: 2026-10-12
# Modified: 2026-10-12
# =============================================

"""
What stands between an installed phone face and a phone that can open it (FPLAN-0642 slice B).

After the face and baud-cli land, ``aipass install`` ends on one print: the URL,
the token command, the guide. This handler gathers the facts that print states:

    - the tailnet address, read from ``tailscale ip -4``;
    - @api's configured bind, read through the module door the caller hands in
      as ``host_config`` (the same edge point.py uses; this file never imports @api);
    - whether a server answers on that bind: one GET to ``/``, the face entry,
      which @api serves without a token.

It changes nothing. Setting the bind and installing the boot unit are @api's,
and its module door publishes neither yet (HELD to @api, 2026-10-12): until it
does, the print carries the exact command the user runs instead.
"""

from __future__ import annotations

import ipaddress
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from aipass.aipass.apps.handlers.json import json_handler
from aipass.prax import logger

# Tailscale hands out addresses from the CGNAT block; nothing else on a host sits there.
TAILNET = ipaddress.ip_network("100.64.0.0/10")
_TAILSCALE_TIMEOUT = 5
_PROBE_TIMEOUT = 3
# A wildcard bind listens everywhere, loopback included, so the probe asks loopback.
_WILDCARDS = ("0.0.0.0", "::", "")

# tailscale states
TAILSCALE_ABSENT = "absent"  # no tailscale on PATH
TAILSCALE_DOWN = "down"  # it answered, with no tailnet address
TAILSCALE_UNREADABLE = "unreadable"  # it did not answer (timed out, or could not run)

# server states
SERVER_SERVING = "serving"  # / answered 2xx: the face is served
SERVER_ANSWERING = "answering"  # / answered an error status: up, but not serving the face
SERVER_SILENT = "silent"  # nothing answered on the bind
SERVER_UNPROBED = "unprobed"  # a dry run, or no @api


@dataclass
class PhoneReady:
    """The facts the install's last print states. ``api`` False: @api is not importable here.

    ``tailnet`` is this host's tailnet IPv4, or one of the TAILSCALE_* words;
    ``server`` is one of the SERVER_* words.
    """

    api: bool
    host: str
    port: int
    tailnet: str
    server: str


def is_tailnet(host: str) -> bool:
    """True when ``host`` is an address in Tailscale's block."""
    try:
        return ipaddress.ip_address(host) in TAILNET
    except ValueError:
        return False


def tailnet_ipv4() -> str:
    """This host's tailnet IPv4 from ``tailscale ip -4``.

    Returns:
        The address; else TAILSCALE_ABSENT (no binary), TAILSCALE_DOWN (no tailnet
        address in its answer) or TAILSCALE_UNREADABLE (it timed out or could not run).
    """
    tailscale = shutil.which("tailscale")
    if tailscale is None:
        return TAILSCALE_ABSENT
    try:
        proc = subprocess.run(
            [tailscale, "ip", "-4"], capture_output=True, text=True, timeout=_TAILSCALE_TIMEOUT, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("[baud] tailscale ip -4 did not answer: %s", exc)
        return TAILSCALE_UNREADABLE
    lines = proc.stdout.split() if proc.returncode == 0 else []
    address = lines[0] if lines else ""
    if not is_tailnet(address):
        logger.info("[baud] tailscale ip -4 gave no tailnet address (exit %s)", proc.returncode)
        return TAILSCALE_DOWN
    return address


def server_answers(host: str, port: int) -> str:
    """One GET to ``/`` on the bind: SERVER_SERVING, SERVER_ANSWERING (an error status) or SERVER_SILENT."""
    probe_host = "127.0.0.1" if host in _WILDCARDS else host
    if ":" in probe_host:
        probe_host = f"[{probe_host}]"
    try:
        with urllib.request.urlopen(f"http://{probe_host}:{port}/", timeout=_PROBE_TIMEOUT):
            return SERVER_SERVING
    except urllib.error.HTTPError as exc:
        logger.info("[baud] the server on %s:%s answered %s", host, port, exc.code)
        return SERVER_ANSWERING
    except (urllib.error.URLError, OSError) as exc:
        logger.info("[baud] no server answered on %s:%s: %s", host, port, exc)
        return SERVER_SILENT


def readiness(host_config: Any, dry_run: bool) -> PhoneReady:
    """Gather the facts. A dry run reads @api's config and nothing else: no tailscale, no probe.

    ``api`` False: @api is not importable here, or its host config could not be read.
    """
    load_config = getattr(host_config, "load_config", None)
    if load_config is None:
        return PhoneReady(api=False, host="", port=0, tailnet=TAILSCALE_ABSENT, server=SERVER_UNPROBED)
    try:
        config = load_config()
        host, port = str(config["host"]), int(config["port"])
    except (OSError, KeyError, TypeError, ValueError) as exc:
        logger.warning("[baud] @api's host config could not be read: %s", exc)
        return PhoneReady(api=False, host="", port=0, tailnet=TAILSCALE_ABSENT, server=SERVER_UNPROBED)
    if dry_run:
        return PhoneReady(api=True, host=host, port=port, tailnet=TAILSCALE_ABSENT, server=SERVER_UNPROBED)
    ready = PhoneReady(api=True, host=host, port=port, tailnet=tailnet_ipv4(), server=server_answers(host, port))
    facts = {"bind": f"{host}:{port}", "tailnet": ready.tailnet, "server": ready.server}
    json_handler.log_operation("baud_phone_ready", facts, module_name="baud")
    return ready
