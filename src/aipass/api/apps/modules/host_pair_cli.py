# =================== AIPass ====================
# Name: host_pair_cli.py
# Description: Host API Pair Module — a one-use pairing QR in the terminal, for the phone's camera
# Version: 1.0.1
# Created: 2026-10-13
# Modified: 2026-10-16
# =============================================

"""
Host API Pair Module

`host-api pair <label> [--scope read|operate] [--ttl SECONDS]` (DPLAN-0406). The
owner's ruling, 2026-10-13: hold the phone up to the terminal and it connects.
This prints a QR of the face's URL with a one-use, five-minute code in the
fragment; the phone redeems it at POST /v1/pair and holds the only copy of the
bearer it gets back. No token value is printed and no receipt is written.

A sub-router like host_config_cli.py: host_api.py offers it every host-api call
and owns everything it declines.

Functions:
    handle_command()      - Claim pair, decline everything else
    print_introspection() - This module's live self-map
    _cmd_pair()           - Mint a code and print its QR, URL and expiry
"""

import sys
from datetime import datetime
from typing import List

from aipass.cli.apps.modules import console, error
from aipass.api.apps.handlers.json import json_handler
from aipass.prax import logger
from aipass.api.apps.handlers.host import pairings as host_pairings
from aipass.api.apps.modules import host_serve

SUBCOMMANDS = ("pair",)
USAGE = "drone @api host-api pair <label> [--scope read|operate] [--ttl SECONDS]"


def _life(seconds: int) -> str:
    """'5 minutes', '1 minute' or '90 seconds': the code's life as the expiry line says it."""
    if seconds % 60:
        return f"{seconds} seconds"
    minutes = seconds // 60
    return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"


def _cmd_pair(args: List[str]) -> None:
    """Mint a pairing code; print its QR, a blank line, its URL and its expiry. Refusals exit 1."""
    scope = host_serve.flag_value(args, "--scope") or "read"
    ttl_text = host_serve.flag_value(args, "--ttl")
    flag_values = {scope, ttl_text}
    labels = [arg for arg in args if not arg.startswith("-") and arg not in flag_values]

    if not labels:
        error("A pairing needs a label", suggestion=USAGE)
        sys.exit(1)

    try:
        ttl = int(ttl_text) if ttl_text is not None else host_pairings.DEFAULT_TTL_SECONDS
    except ValueError as e:
        logger.warning("[host_api] pair refused a ttl that is not whole seconds: %s", e)
        error(f"--ttl must be whole seconds, got {ttl_text!r}", suggestion=USAGE)
        sys.exit(1)

    try:
        # Before the mint: a loopback bind would print a code no phone can open.
        host_pairings.bind_address(allow_loopback=False)
        minted = host_pairings.mint_pairing(labels[0], scope, ttl)
        qr = host_pairings.render_qr(minted["url"])
    except host_pairings.PairingError as e:
        logger.warning("[host_api] pair refused: %s", e)
        error(str(e))
        sys.exit(1)

    expires = datetime.fromisoformat(minted["expires_at"]).astimezone().strftime("%H:%M")
    console.print(qr, markup=False, highlight=False, soft_wrap=True)
    console.print()
    console.print(minted["url"], markup=False, highlight=False, soft_wrap=True)
    console.print(
        f"Expires {expires} ({_life(ttl)}), one use. Open your phone's camera and point it at the code.",
        markup=False,
        highlight=False,
        soft_wrap=True,
    )
    json_handler.log_operation("host_api_pair_printed", {"id": minted["id"], "scope": minted["scope"], "ttl": ttl})


def handle_command(command: str, args: List[str]) -> bool:
    """
    Claim the pair subcommand of `host-api`.

    Args:
        command: The routed command name.
        args: Everything after it, subcommand first.

    Returns:
        True if this module handled it. False means "not mine".
    """
    # Both spellings, matching host_api.py and its other sub-routers.
    if command not in ("host-api", "host_api"):
        return False

    # NO-ARGS GATE and HELP GATE (seedgo standard), as in host_config_cli.py.
    # The help gate claims only pair: `host-api --help` is host_api.py's,
    # whatever order the router discovered the modules in.
    if not args:
        print_introspection()
        return True

    if args[0] not in SUBCOMMANDS:
        return False

    if any(arg in ("--help", "-h", "help") for arg in args):
        print_introspection()
        return True

    _cmd_pair(args[1:])
    return True


def print_introspection() -> None:
    """Show what this module answers for."""
    console.print()
    console.print("[bold cyan]host_pair_cli — a phone signs in by its camera[/bold cyan]")
    console.print()
    console.print("  [cyan]host-api pair <label>[/cyan]  [dim]A one-use QR, five minutes; the phone redeems it[/dim]")
    console.print()
