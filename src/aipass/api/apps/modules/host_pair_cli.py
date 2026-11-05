# =================== AIPass ====================
# Name: host_pair_cli.py
# Description: Host API Pair Module — a one-use pairing QR for the phone's camera, or a code for the extension
# Version: 1.1.0
# Created: 2026-10-13
# Modified: 2026-11-05
# =============================================

"""
Host API Pair Module

No token value is printed and no receipt is written: the phone holds the only copy of the bearer.
Reference: docs/host_api.md
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
USAGE = "drone @api host-api pair <label>|extension [--scope read|operate] [--ttl SECONDS]"
EXTENSION_MODE = "extension"
PAIR_FRAGMENT = "/#pair="


def _life(seconds: int) -> str:
    """'5 minutes', '1 minute' or '90 seconds': the code's life as the expiry line says it."""
    if seconds % 60:
        return f"{seconds} seconds"
    minutes = seconds // 60
    return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"


def _cmd_pair(args: List[str]) -> None:
    """Mint a pairing code; print its QR, a blank line, its URL and its expiry. Refusals exit 1.
    `extension` mode: operate by default, loopback allowed (same machine), the code and base URL as text, no QR."""
    extension = bool(args) and args[0] == EXTENSION_MODE
    scope = host_serve.flag_value(args, "--scope") or ("operate" if extension else "read")
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
        host_pairings.bind_address(allow_loopback=extension)
        minted = host_pairings.mint_pairing(labels[0], scope, ttl)
        qr = "" if extension else host_pairings.render_qr(minted["url"])
    except host_pairings.PairingError as e:
        logger.warning("[host_api] pair refused: %s", e)
        error(str(e))
        sys.exit(1)

    expires = datetime.fromisoformat(minted["expires_at"]).astimezone().strftime("%H:%M")
    if extension:
        lines = [
            f"Pairing code: {minted['code']}",
            f"Host: {minted['url'].partition(PAIR_FRAGMENT)[0]}",
            f"Expires {expires} ({_life(ttl)}), one use. Paste both into the extension's options page.",
        ]
    else:
        console.print(qr, markup=False, highlight=False, soft_wrap=True)
        console.print()
        lines = [
            minted["url"],
            f"Expires {expires} ({_life(ttl)}), one use. Open your phone's camera and point it at the code.",
        ]
    for line in lines:
        console.print(line, markup=False, highlight=False, soft_wrap=True)
    json_handler.log_operation(
        "host_api_pair_printed", {"id": minted["id"], "scope": minted["scope"], "ttl": ttl, "extension": extension}
    )


def handle_command(command: str, args: List[str]) -> bool:
    """Claim the pair subcommand of `host-api`."""
    if command not in ("host-api", "host_api"):
        return False

    # The help gate claims only pair: `host-api --help` is host_api.py's, whatever the discovery order.
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
    console.print(
        "  [cyan]host-api pair extension[/cyan]  [dim]A one-use code and the host URL as text, operate scope, "
        "loopback allowed; paste both into the browser extension's options page[/dim]"
    )
    console.print()
