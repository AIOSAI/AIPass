# =================== AIPass ====================
# Name: phone_setup.py
# Description: Finish the phone through @api's installer doors: move the bind to the tailnet, install the boot unit
# Version: 1.2.0
# Created: 2026-10-12
# Modified: 2026-10-13
# =============================================

"""
The acting half of the phone step (FPLAN-0642 slice D); phone_ready.py is the reading half.

Every write goes through @api's host module door, handed in as ``host_config``
(the same edge phone_ready and point.py use; this file never imports @api):

    - ``set_bind(host, port)`` moves the bind to the tailnet address;
    - ``autostart()`` renders the boot unit, and leaves a unit systemd already runs alone;
    - ``install_unit(dry_run)`` and ``enable_unit(dry_run)`` run the steps @api's
      autostart verb prints, each answering ``{dry_run, ok, steps[{step, ok, detail}]}``.

Nothing here shells out and nothing mints a token. A door this @api does not
publish is a state (``*_NO_DOOR``), so an older @api still gets the manual commands.
A dry run never calls set_bind or autostart: autostart has no dry run and renders
a file, so the dry run names it instead.

Where no boot unit will bring the server up (no user systemd, a failed or
unreachable unit), ``serve_detached()`` starts it in its own session (DPLAN-0407),
and ``probe_until_serving`` gives a starting server its few seconds.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from aipass.aipass.apps.handlers.baud.phone_ready import SERVER_ANSWERING, SERVER_SERVING, PhoneReady, is_tailnet
from aipass.aipass.apps.handlers.json import json_handler
from aipass.prax import logger

# bind states
BIND_KEPT = "kept"  # already a tailnet address, or set_bind found it unchanged
BIND_MOVED = "moved"  # set_bind stored the tailnet address
BIND_WOULD_MOVE = "would_move"  # a dry run on a bind that is not a tailnet address
BIND_STAYS = "stays"  # tailscale is not up: there is no tailnet address to move to
BIND_REFUSED = "refused"  # set_bind raised BindRefused; nothing was stored
BIND_NO_DOOR = "no_door"  # this @api publishes no set_bind

# boot states
BOOT_DONE = "done"  # rendered, installed, enabled
BOOT_LIVE = "live"  # systemd already runs the unit: left alone
BOOT_PLANNED = "planned"  # a dry run: the steps named, none run
BOOT_FAILED = "failed"  # a step failed; the last report's last step says why
BOOT_REFUSED = "refused"  # enable refused: a hand-started server holds the port
BOOT_UNSUPPORTED = "unsupported"  # no user-level systemd here (a container, macOS, Windows)
BOOT_UNREACHABLE = "unreachable"  # the supervisor or the serve record could not be read
BOOT_NO_DOOR = "no_door"  # this @api publishes no installer doors

_BOOT_DOORS = ("autostart", "install_unit", "enable_unit")

# server start states (DPLAN-0407)
SERVE_STARTED = "started"  # serve_detached() spawned it; pid is set
SERVE_REFUSED = "refused"  # serve_detached() raised; detail holds the door's words
SERVE_NO_DOOR = "no_door"  # this @api publishes no serve_detached
SERVE_SKIPPED = "skipped"  # served already, or a boot unit (or a hand-started server) holds it
SERVE_PLANNED = "planned"  # a dry run: nothing called

# A unit or a detached server needs a moment to bind: up to 6 asks, 0.5 s apart.
PROBE_TRIES = 6
PROBE_GAP_SECONDS = 0.5
# The boot states under which something other than the install brings the server up.
_UNIT_RUNS_IT = (BOOT_DONE, BOOT_LIVE, BOOT_REFUSED)


class _NeverRaised(Exception):
    """Stands in for an exception name an older @api does not export, so no except clause matches it."""


def _door_error(host_config: Any, name: str) -> type[BaseException]:
    """The exception class @api's door exports as ``name``, or one nothing raises."""
    found = getattr(host_config, name, None)
    return found if isinstance(found, type) and issubclass(found, BaseException) else _NeverRaised


@dataclass
class BindMove:
    """What happened to @api's bind. ``previous`` is the bind before, ``detail`` BindRefused's own words."""

    state: str
    host: str
    port: int
    previous: str = ""
    detail: str = ""


@dataclass
class BootSetup:
    """What happened to the boot unit. ``reports`` are the doors' steps reports, in the order run."""

    state: str
    reports: list[dict] = field(default_factory=list)
    running: int = 0
    unit: str = ""
    detail: str = ""


def move_bind(host_config: Any, ready: PhoneReady, dry_run: bool) -> BindMove:
    """Move @api's bind to this host's tailnet address when tailscale is up and the bind is elsewhere."""
    here = f"{ready.host}:{ready.port}"
    if is_tailnet(ready.host):
        return BindMove(BIND_KEPT, ready.host, ready.port, previous=here)
    if dry_run:
        return BindMove(BIND_WOULD_MOVE, ready.host, ready.port, previous=here)
    if not is_tailnet(ready.tailnet):
        return BindMove(BIND_STAYS, ready.host, ready.port, previous=here)
    set_bind = getattr(host_config, "set_bind", None)
    if set_bind is None:
        return BindMove(BIND_NO_DOOR, ready.host, ready.port, previous=here)
    try:
        stored = set_bind(ready.tailnet, ready.port)
    except _door_error(host_config, "BindRefused") as exc:
        logger.warning("[baud] @api refused the tailnet bind %s:%s: %s", ready.tailnet, ready.port, exc)
        return BindMove(BIND_REFUSED, ready.host, ready.port, previous=here, detail=str(exc))
    state = BIND_MOVED if stored.get("changed") else BIND_KEPT
    moved = BindMove(state, str(stored.get("host", ready.tailnet)), int(stored.get("port", ready.port)), here)
    json_handler.log_operation("baud_phone_bind", {"state": state, "from": here, "to": moved.host}, module_name="baud")
    return moved


def _boot_errors(host_config: Any) -> tuple[type[BaseException], tuple[type[BaseException], ...]]:
    """(AutostartUnsupported, (SupervisorUnreachable, LifetimeError, BindRefused)) as this @api exports them."""
    unreachable = tuple(_door_error(host_config, n) for n in ("SupervisorUnreachable", "LifetimeError", "BindRefused"))
    return _door_error(host_config, "AutostartUnsupported"), unreachable


def _after_enable(enabled: dict, reports: list[dict], unit: str) -> BootSetup:
    """The state an enable_unit report names: refused, failed, or done."""
    if enabled.get("refused"):
        return BootSetup(BOOT_REFUSED, reports, unit=unit, detail=str(enabled["refused"]))
    return BootSetup(BOOT_DONE if enabled.get("ok") else BOOT_FAILED, reports, unit=unit)


def set_up_boot(host_config: Any, dry_run: bool) -> BootSetup:
    """autostart(), then install_unit, then enable_unit; a unit systemd already runs is left alone."""
    autostart, install_unit, enable_unit = (getattr(host_config, name, None) for name in _BOOT_DOORS)
    if autostart is None or install_unit is None or enable_unit is None:
        return BootSetup(BOOT_NO_DOOR)
    unsupported, unreachable = _boot_errors(host_config)
    try:
        if dry_run:
            planned = [install_unit(dry_run=True), enable_unit(dry_run=True)]
            setup = _after_enable(planned[1], planned, unit="")
            return setup if setup.state == BOOT_REFUSED else BootSetup(BOOT_PLANNED, planned)
        report = autostart()
        unit = str(report.get("unit", ""))
        if not report.get("rendered", True):
            setup = BootSetup(BOOT_LIVE, running=int(report.get("running", 0)), unit=unit)
        else:
            installed = install_unit(dry_run=False)
            reports = [installed]
            if installed.get("ok"):
                reports.append(enable_unit(dry_run=False))
                setup = _after_enable(reports[1], reports, unit)
            else:
                setup = BootSetup(BOOT_FAILED, reports, unit=unit)
    except unsupported as exc:
        logger.info("[baud] no boot unit here: %s", exc)
        return BootSetup(BOOT_UNSUPPORTED, detail=str(exc))
    except unreachable as exc:
        logger.warning("[baud] the boot unit could not be set up: %s", exc)
        return BootSetup(BOOT_UNREACHABLE, detail=str(exc))
    json_handler.log_operation("baud_phone_boot", {"state": setup.state, "unit": setup.unit}, module_name="baud")
    return setup


# pairing states (DPLAN-0406 slice C)
PAIR_MINTED = "minted"  # a one-use code minted; qr and url are set
PAIR_PLANNED = "planned"  # a dry run: nothing minted
PAIR_SKIPPED = "skipped"  # the server does not answer on a tailnet bind: no code, the pair command instead
PAIR_REFUSED = "refused"  # the door raised PairingError; detail holds its words
PAIR_NO_DOOR = "no_door"  # this @api publishes no mint_pairing / render_qr
PAIR_DECLINED = "declined"  # EOF or Ctrl-C at the pause: a stated skip (DPLAN-0407)
PAIR_LABEL = "phone"
PAIR_SCOPE = "operate"


@dataclass
class Pairing:
    """The pairing QR's facts. Never carries the code apart from the url it sits in."""

    state: str
    url: str = ""
    qr: str = ""
    expires: str = ""
    detail: str = ""


def _local_hhmm(expires_at: str) -> str:
    """ISO 8601 UTC from the door, as HH:MM local; the raw value when it does not parse."""
    try:
        return datetime.fromisoformat(expires_at.replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except ValueError as exc:
        logger.info("[baud] pairing expiry %r not ISO 8601: %s", expires_at, exc)
        return f"at {expires_at}"


def can_pair(ready: PhoneReady) -> bool:
    """A pairing code is worth minting only when the server serves the face on a tailnet bind."""
    return ready.server == SERVER_SERVING and is_tailnet(ready.host)


def mint_pair(host_config: Any, ready: PhoneReady, dry_run: bool) -> Pairing:
    """Mint the phone's pairing code and its QR, only when the server serves the face on a tailnet bind."""
    if dry_run:
        return Pairing(PAIR_PLANNED)
    if not can_pair(ready):
        return Pairing(PAIR_SKIPPED)
    mint = getattr(host_config, "mint_pairing", None)
    render = getattr(host_config, "render_qr", None)
    if mint is None or render is None:
        return Pairing(PAIR_NO_DOOR)
    try:
        minted = mint(PAIR_LABEL, PAIR_SCOPE)
        url = str(minted["url"])
        qr = render(url)
    except _door_error(host_config, "PairingError") as exc:
        logger.warning("[baud] pairing code not minted: %s", exc)
        return Pairing(PAIR_REFUSED, detail=str(exc))
    json_handler.log_operation("baud_phone_pairing", {"label": PAIR_LABEL, "scope": PAIR_SCOPE}, module_name="baud")
    return Pairing(PAIR_MINTED, url=url, qr=qr, expires=_local_hhmm(str(minted.get("expires_at", ""))))


@dataclass
class ServerStart:
    """What the install did about a silent server. ``detail`` is serve_detached's refusal, in its words."""

    state: str
    pid: int = 0
    detail: str = ""


def probe_until_serving(
    probe: Callable[[str, int], str], host: str, port: int, sleep: Callable[[float], None] = time.sleep
) -> str:
    """Ask the server up to PROBE_TRIES times, PROBE_GAP_SECONDS apart; the last answer, serving or not."""
    answer = probe(host, port)
    for _ in range(PROBE_TRIES - 1):
        if answer == SERVER_SERVING:
            break
        sleep(PROBE_GAP_SECONDS)
        answer = probe(host, port)
    return answer


def start_server(host_config: Any, ready: PhoneReady, boot: BootSetup, dry_run: bool) -> ServerStart:
    """Start the server detached when it does not answer and no boot unit will bring it up.

    An answering port (serving or not) and a unit that is done, live, or refused
    over a hand-started server are skipped: a second server there could only fail.
    """
    if dry_run:
        return ServerStart(SERVE_PLANNED)
    if ready.server in (SERVER_SERVING, SERVER_ANSWERING) or boot.state in _UNIT_RUNS_IT:
        return ServerStart(SERVE_SKIPPED)
    serve = getattr(host_config, "serve_detached", None)
    if serve is None:
        return ServerStart(SERVE_NO_DOOR)
    refusals = tuple(_door_error(host_config, n) for n in ("BindRefused", "LifetimeError", "SupervisorUnreachable"))
    try:
        record = serve()
    except refusals as exc:
        logger.warning("[baud] the server could not be started detached: %s", exc)
        start = ServerStart(SERVE_REFUSED, detail=str(exc))
    else:
        start = ServerStart(SERVE_STARTED, pid=int(record.get("pid", 0)))
    json_handler.log_operation("baud_phone_serve", {"state": start.state, "pid": start.pid}, module_name="baud")
    return start
