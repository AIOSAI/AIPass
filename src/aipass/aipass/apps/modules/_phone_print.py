# =================== AIPass ====================
# Name: _phone_print.py
# Description: aipass install's last print: the phone's bind, boot unit, server, guide and pairing QR
# Version: 1.0.0
# Created: 2026-10-13
# Modified: 2026-10-13
# =============================================

"""
The phone print that ends aipass install, split out of baud.py (DPLAN-0406 slice C).

baud.finish_phone acts through @api's doors and hands what happened here:
``print_phone_ready`` states each door's outcome and the command that does it by
hand. A minted pairing ends the print on its QR block; anything else ends on the
guide with the pair command above it. Nothing here calls a door or prints a token.
"""

from __future__ import annotations

from aipass.aipass.apps.handlers.baud.phone_ready import SERVER_ANSWERING, SERVER_SERVING, PhoneReady, is_tailnet
from aipass.aipass.apps.handlers.baud.phone_setup import (
    BIND_KEPT,
    BIND_MOVED,
    BIND_NO_DOOR,
    BIND_REFUSED,
    BOOT_DONE,
    BOOT_FAILED,
    BOOT_LIVE,
    BOOT_NO_DOOR,
    BOOT_PLANNED,
    BOOT_REFUSED,
    BOOT_UNREACHABLE,
    BOOT_UNSUPPORTED,
    PAIR_LABEL,
    PAIR_MINTED,
    PAIR_REFUSED,
    PAIR_SCOPE,
    PAIR_SKIPPED,
    BindMove,
    BootSetup,
    Pairing,
)
from aipass.aipass.apps.handlers.json import json_handler
from aipass.cli.apps.modules import console, warning
from aipass.prax import logger

# aipass install's last print (FPLAN-0642 slice B). The pair command is @api's
# (drone @api host-api --help); the guide is @baud's.
PHONE_GUIDE_URL = "https://github.com/AIOSAI/baud/blob/main/docs/phone-setup-android.md"
# The pairing door replaced the token hop (DPLAN-0406 slice C): no token on any screen.
PAIR_COMMAND = f"drone @api host-api pair {PAIR_LABEL} --scope {PAIR_SCOPE}"
PAIR_PLAN = (
    f"would mint a pairing code for the phone (label {PAIR_LABEL}, scope {PAIR_SCOPE}, 5 minutes) and show its QR"
)
PAIR_HEADING = "Pair your phone"
PAIR_CAMERA = "Open your phone's camera and point it at this code."
TAILSCALE_INSTALL = "curl -fsSL https://tailscale.com/install.sh | sh"
SERVE_COMMAND = "drone @api host-api serve --detach"
AUTOSTART_COMMAND = "drone @api host-api autostart"
STOP_COMMAND = "drone @api host-api stop"
_DRY = "[yellow]\\[dry-run][/yellow]"
_PAD = " " * 14


def _steps(boot: BootSetup, dry_run: bool) -> None:
    """One line per step the doors ran or would run: the step, and ok or the failure's detail."""
    for report in boot.reports:
        for step in report.get("steps", []):
            if dry_run:
                console.print(f"{_DRY} would run: {step.get('step', '')}")
            elif step.get("ok"):
                console.print(f"{_PAD}ok      {step.get('step', '')}")
            else:
                console.print(f"{_PAD}failed  {step.get('step', '')}: {step.get('detail', '')}")


def _print_dry_run_phone(ready: PhoneReady, bind: BindMove | None, boot: BootSetup | None) -> None:
    """The dry run's phone lines: what each door would do, nothing done."""
    now = f"now {ready.host}:{ready.port}" if ready.api else "@api's config unreadable here"
    console.print(f"{_DRY} would read this host's tailnet address: tailscale ip -4")
    if bind is not None and bind.state == BIND_KEPT:
        console.print(f"{_DRY} would keep @api's bind ({now}), already a tailnet address")
    else:
        console.print(f"{_DRY} would move @api's bind ({now}) to the tailnet address, when tailscale is up")
    if boot is not None and boot.state != BOOT_NO_DOOR:
        console.print(f"{_DRY} would render the boot unit (autostart), unless systemd already runs it")
        _steps(boot, dry_run=True)
    if boot is None or boot.state == BOOT_NO_DOOR:
        console.print(f"{_DRY} would name the boot unit's commands: {SERVE_COMMAND}; {AUTOSTART_COMMAND}")
    elif boot.state == BOOT_REFUSED:
        console.print(f"{_DRY} would not enable it: {boot.detail}")
    elif boot.state != BOOT_PLANNED:
        console.print(f"{_DRY} no boot unit here: {boot.detail}; would name {SERVE_COMMAND}")
    console.print(f"{_DRY} would ask the server on that bind whether it answers (GET /, no token)")
    console.print(f"{_DRY} {PAIR_PLAN}")


def _print_bind(ready: PhoneReady, bind: BindMove) -> None:
    """The Bind line: kept, moved, refused in @api's own words, or the command that moves it."""
    here = bind.previous or f"{ready.host}:{ready.port}"
    move = f"drone @api host-api set-config --host {ready.tailnet} --port {ready.port}"
    if bind.state == BIND_KEPT:
        console.print(f"  Bind:       kept {bind.host}:{bind.port}, already a tailnet address")
    elif bind.state == BIND_MOVED:
        console.print(f"  Bind:       moved to {bind.host}:{bind.port} (was {here})")
    elif bind.state == BIND_REFUSED:
        console.print(f"  Bind:       {here}; @api refused {ready.tailnet}: {bind.detail}")
        console.print(f"{_PAD}Move it by hand: [cyan]{move}[/cyan]")
    elif bind.state == BIND_NO_DOOR and is_tailnet(ready.tailnet):
        console.print(f"  Bind:       {here}; the phone needs {ready.tailnet}. Move it:")
        console.print(f"{_PAD}[cyan]{move}[/cyan]")
    else:
        console.print(f"  Bind:       {here}")


def _print_boot(boot: BootSetup, bind: BindMove) -> None:
    """The Boot unit lines: left alone, the steps run, or why not and the commands that do it by hand."""
    start = f"{_PAD}Start it: [cyan]{SERVE_COMMAND}[/cyan]"
    at_boot = f"{_PAD}at every boot: [cyan]{AUTOSTART_COMMAND}[/cyan]"
    keeps = bind.state == BIND_MOVED
    lines = {
        BOOT_LIVE: [f"  Boot unit:  left alone, systemd already runs it (pid {boot.running})"]
        + ([f"{_PAD}it keeps the bind it started with until it restarts"] if keeps else []),
        BOOT_DONE: ["  Boot unit:  installed and enabled"],
        BOOT_FAILED: ["  Boot unit:  not finished"],
        BOOT_REFUSED: [f"  Boot unit:  not enabled. {boot.detail}", f"{_PAD}Stop it: [cyan]{STOP_COMMAND}[/cyan]"],
        BOOT_UNSUPPORTED: [f"  Boot unit:  none here ({boot.detail}); the server will not come back at boot", start],
        BOOT_UNREACHABLE: [f"  Boot unit:  not set up: {boot.detail}", start, at_boot],
    }.get(boot.state, [])
    for line in lines:
        console.print(line)
    _steps(boot, dry_run=False)
    if boot.state == BOOT_FAILED:
        console.print(start)
        console.print(at_boot)


def _print_server(ready: PhoneReady, boot: BootSetup) -> None:
    """The Server line, from the probe after the boot unit: serving, answering, or silent."""
    if ready.server == SERVER_SERVING:
        console.print("  Server:     answering, serving the face")
    elif ready.server == SERVER_ANSWERING:
        console.print("  Server:     up, but not serving the face: [cyan]drone @api host-api status[/cyan]")
    elif boot.state in (BOOT_DONE, BOOT_LIVE):
        console.print("  Server:     not answering yet: [cyan]drone @api host-api status[/cyan]")
    elif boot.state == BOOT_NO_DOOR:
        console.print(f"  Server:     not answering. Start it: [cyan]{SERVE_COMMAND}[/cyan]")
        console.print(f"{_PAD}at every boot: [cyan]{AUTOSTART_COMMAND}[/cyan]")
    else:
        console.print("  Server:     not answering")


def _print_pairing(pairing: Pairing) -> None:
    """The install's last block: heading, camera line, QR, url, expiry. QR and url go out raw, unwrapped."""
    console.print()
    console.print(f"[bold cyan]{PAIR_HEADING}[/bold cyan]")
    console.print(PAIR_CAMERA, markup=False, highlight=False)
    console.print(pairing.qr, markup=False, highlight=False, soft_wrap=True)
    console.print()
    console.print(pairing.url, markup=False, highlight=False, soft_wrap=True)
    console.print(f"Expires {pairing.expires} (5 minutes), one use. Later: {PAIR_COMMAND}", markup=False)
    logger.info("[baud] pairing QR shown, expires %s", pairing.expires)


def print_phone_ready(
    ready: PhoneReady,
    dry_run: bool = False,
    bind: BindMove | None = None,
    boot: BootSetup | None = None,
    pairing: Pairing | None = None,
) -> None:
    """aipass install's last print: bind, boot unit, server, the phone URL, the guide, then pairing.

    Never prints a token. ``bind``, ``boot`` and ``pairing`` are what finish_phone
    did; None (nothing attempted) prints the commands that do it by hand. A minted
    pairing ends the print with its QR block, below the guide; any other ends on the
    guide, with the pair command above it.
    """
    console.print()
    console.print("[bold cyan]Your phone[/bold cyan]")
    if dry_run:
        _print_dry_run_phone(ready, bind, boot)
        return
    if not ready.api:
        warning("@api's host config could not be read, so there is no phone URL to give yet")
        console.print(f"  Guide:      {PHONE_GUIDE_URL}")
        return

    bind = bind if bind is not None else BindMove(BIND_NO_DOOR, ready.host, ready.port)
    boot = boot if boot is not None else BootSetup(BOOT_NO_DOOR)
    tailnet_up = is_tailnet(ready.tailnet)
    url_host = ready.tailnet if tailnet_up else ready.host
    console.print(f"  Phone URL:  [cyan]http://{url_host}:{ready.port}/[/cyan]")
    _print_bind(ready, bind)
    _print_boot(boot, bind)
    _print_server(ready, boot)
    pairing = pairing if pairing is not None else Pairing(PAIR_SKIPPED)
    if pairing.state == PAIR_REFUSED:
        console.print(f"  Pairing code not minted: {pairing.detail}", markup=False)
    if pairing.state != PAIR_MINTED:
        console.print(f"  Then pair your phone: [cyan]{PAIR_COMMAND}[/cyan]")
    console.print(f"  Guide:      {PHONE_GUIDE_URL}")
    if not tailnet_up:
        warning(f"Tailscale is {ready.tailnet} here: the phone URL works on this machine only until it is up")
        console.print(f"  Install it: [cyan]{TAILSCALE_INSTALL}[/cyan], then: [cyan]sudo tailscale up[/cyan]")
    if pairing.state == PAIR_MINTED:
        _print_pairing(pairing)


def handle_command(command: str, args: list[str]) -> bool:
    """A helper module: no command of its own. aipass install and aipass baud reach this print."""
    if command != "phone_print":
        return False
    console.print("[dim]Helper module — the phone print ends: aipass install[/dim]")
    json_handler.log_operation("phone_print_usage", {"command": command, "args": len(args)}, module_name="baud")
    return True
