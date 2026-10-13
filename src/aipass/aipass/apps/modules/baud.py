# =================== AIPass ====================
# Name: baud.py
# Description: aipass baud: install @baud's phone face and baud-cli from a release and point @api at them
# Version: 1.3.0
# Created: 2026-09-13
# Modified: 2026-10-12
# =============================================

"""
aipass baud: the phone face and the headless baud-cli come from a release, not a checkout.

A stranger who never cloned baud still gets the phone face and a fleet behind it:
fetch ``baud-phone-<tag>.tar.gz``, ``baud-cli-<tag>-linux-x86_64`` and
``SHA256SUMS.txt`` from one baud release, verify every digest, unpack the face
through a safety filter into ``~/.aipass/baud/phone/``, land the binary at
``~/.aipass/baud/bin/baud-cli``, and hand both to @api's host server
(FPLAN-0587 row 2, FPLAN-0589 row 3). AIPass never vendors either: the licences
stay apart (DPLAN-0313). Releases build baud-cli for linux-x86_64 only; anywhere
else the install says so in one line and lands the face alone.

Usage:
    aipass baud install                              # latest release
    aipass baud install --tag v0.2.1                 # one release
    aipass baud install --from <tar> --sums <sums>   # a tarball on disk, no network
    aipass baud install --from <tar> --binary <bin>  # + a baud-cli on disk, its line in the same sums
    aipass baud install --dest <dir>                 # face in <dir>, baud-cli in <dir>/../bin
    aipass baud install --dry-run                    # say what would happen, touch nothing
    aipass baud status [--dest <dir>]                # what is installed, where @api points

``aipass install`` runs the same install as its best-effort step 4 (its --baud-tag
is this command's --tag), then ends on ``finish_phone``: through @api's module
door it moves the bind to the tailnet address and installs the boot unit, then
prints the phone URL, the token command and the guide (FPLAN-0642 slices B, D).
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, List

from aipass.aipass.apps.handlers.baud import (
    LATEST,
    RESTART_HINT,
    SUMS_ASSET,
    FetchError,
    InstallOutcome,
    PointResult,
    UnpackError,
    VerifyError,
    api_baud_bin_state,
    api_face_dir_state,
    baud_root,
    bin_path,
    binary_asset_name,
    install_from_file,
    install_from_release,
    phone_asset_name,
    phone_url,
    platform_slug,
    point_api_at,
    point_api_at_binary,
    read_binary_install,
    read_install,
    validate_tag,
)
from aipass.aipass.apps.handlers.baud.phone_ready import (
    RECEIPT_REFUSED,
    SERVER_ANSWERING,
    SERVER_SERVING,
    PhoneReady,
    is_tailnet,
    readiness,
    server_answers,
)
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
    BindMove,
    BootSetup,
    move_bind,
    set_up_boot,
)
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.aipass.apps.handlers.json import json_handler
from aipass.cli.apps.modules import console, error, success, warning
from aipass.prax import logger

COMMAND = "baud"
_MODULE_NAME = "baud"
_VERSION = "1.3.0"
DEFAULT_DEST = Path.home() / ".aipass" / "baud" / "phone"
RETRY_HINT = "Retry anytime: aipass baud install  (or: aipass baud install --from <tarball> --sums <SHA256SUMS.txt>)"

_VALUE_FLAGS = ("--tag", "--from", "--sums", "--dest", "--binary")
_FROM_ONLY = ("--sums", "--binary")
_BAUD_ERRORS = (FetchError, VerifyError, UnpackError)

# aipass install's last print (FPLAN-0642 slice B). The token command and its receipt
# are @api's (drone @api host-api --help); the guide is @baud's.
PHONE_GUIDE_URL = "https://github.com/AIOSAI/baud/blob/main/docs/phone-setup-android.md"
TOKEN_COMMAND = "drone @api host-api issue-token <label> --scope operate"
TAILSCALE_INSTALL = "curl -fsSL https://tailscale.com/install.sh | sh"
SERVE_COMMAND = "drone @api host-api serve --detach"
AUTOSTART_COMMAND = "drone @api host-api autostart"
STOP_COMMAND = "drone @api host-api stop"
_DRY = "[yellow]\\[dry-run][/yellow]"
_PAD = " " * 14


class UsageError(Exception):
    """The command line was malformed. The message is safe to print."""


def _api_host_config() -> Any:
    """@api's host-api module door (set_face_dir, face_dir, set_baud_bin, baud_bin, load_config), or None.

    The one cross-branch edge of this command, held here in the module layer and
    handed to handlers/baud/point.py. FPLAN-0587 and FPLAN-0589 pin the in-process
    call: @api validates each path at write time and aipass never writes api's config.
    It goes through @api's MODULE, which re-exports the handler's functions and
    refusal classes (FaceDirRefused, BaudBinRefused), never into its handlers.
    """
    try:
        from aipass.api.apps.modules import host_api
    except ImportError as exc:
        logger.warning("[baud] @api host_api module not importable: %s", exc)
        return None
    return host_api


def _parse_flags(args: List[str], allowed: tuple[str, ...]) -> dict[str, Any]:
    """Parse --flag value pairs and --dry-run; refuse anything else."""
    parsed: dict[str, Any] = {"--dry-run": False}
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--dry-run" and "--dry-run" in allowed:
            parsed["--dry-run"] = True
            index += 1
            continue
        if arg not in allowed or arg == "--dry-run":
            raise UsageError(f"Unknown argument: {arg}")
        if index + 1 >= len(args) or args[index + 1].startswith("--"):
            raise UsageError(f"{arg} needs a value")
        parsed[arg] = args[index + 1]
        index += 2
    return parsed


def _resolve_dest(dest: str | None) -> Path:
    """The install directory, absolute."""
    return Path(dest).expanduser().resolve() if dest else DEFAULT_DEST


def _print_dry_run(tag: str, from_path: str | None, sums_path: str | None, dest: Path, binary_path: str | None) -> None:
    """Walk the install without touching the network or the disk."""
    prefix = "[yellow]\\[dry-run][/yellow]"
    if from_path:
        sums = sums_path or str(Path(from_path).expanduser().parent / SUMS_ASSET)
        lands_binary = bool(binary_path)
        files = f"{from_path} and {binary_path}" if binary_path else from_path
        console.print(f"  {prefix} would verify {files} against {sums}")
        if not binary_path:
            console.print(f"  {prefix} no --binary: the phone face only")
    else:
        shown = "<tag>" if tag == LATEST else tag
        bin_asset = binary_asset_name(shown)
        lands_binary = bin_asset is not None
        assets = f"{phone_asset_name(shown)}{f', {bin_asset}' if bin_asset else ''} and {SUMS_ASSET}"
        console.print(f"  {prefix} would fetch {assets} from the {tag} baud release")
        console.print(f"  {prefix} would verify every file's sha256 against {SUMS_ASSET}")
        if not bin_asset:
            console.print(f"  {prefix} no baud-cli build for {platform_slug()}: the phone face only")
    console.print(f"  {prefix} would unpack the face (safety filter, staging swap) into {dest}")
    if lands_binary:
        console.print(f"  {prefix} would land baud-cli at {bin_path(baud_root(dest))} (0755, old one kept as .prev)")
    console.print(f"  {prefix} would point @api's host server at {dest}{' and at baud-cli' if lands_binary else ''}")


def _report(message: str, best_effort: bool) -> None:
    """A refusal: a warning inside aipass install, an error on its own."""
    if best_effort:
        warning(f"Phone face not installed: {message}")
    else:
        error(message)


def _install(
    tag: str, from_path: str | None, sums_path: str | None, dest: Path, binary_path: str | None
) -> InstallOutcome:
    """--from installs files on disk; otherwise the release is fetched."""
    if from_path:
        sums = Path(sums_path).expanduser().resolve() if sums_path else None
        binary = Path(binary_path).expanduser().resolve() if binary_path else None
        return install_from_file(Path(from_path).expanduser().resolve(), sums, dest, tag, binary)
    console.print(f"  [dim]Fetching the {tag} baud release…[/dim]")
    return install_from_release(tag, dest)


def _say(result: PointResult) -> None:
    """A point result: success when @api took it, a warning with the manual command when not."""
    if result.ok:
        success(result.message)
    else:
        warning(result.message)


def _point(outcome: InstallOutcome) -> int:
    """Hand the face and the binary to @api, then say how to see it. 0 when @api took everything installed."""
    host_config = _api_host_config()
    face = point_api_at(outcome.dest, host_config)
    cli = point_api_at_binary(outcome.binary.path, host_config) if outcome.binary else None
    json_handler.log_operation(
        "baud_install",
        {"tag": outcome.tag, "dest": str(outcome.dest), "pointed": face.ok, "binary_pointed": cli and cli.ok},
        module_name=_MODULE_NAME,
    )
    _say(face)
    if face.ok:
        console.print(f"  [dim]{RESTART_HINT}[/dim]")
        console.print(f"  [dim]Then open:[/dim] [cyan]{phone_url(host_config)}[/cyan]")
    if cli is not None:
        _say(cli)
    return 0 if face.ok and (cli is None or cli.ok) else 1


def install_phone_face(
    tag: str = LATEST,
    from_path: str | None = None,
    sums_path: str | None = None,
    dest: str | None = None,
    dry_run: bool = False,
    best_effort: bool = False,
    binary_path: str | None = None,
) -> int:
    """Fetch (or take), verify, unpack, land, point. 0 installed and pointed; 1 otherwise.

    No baud-cli for this platform, in this release, or on the --from command line
    is one line and still 0: the face alone is a complete install. best_effort
    reports refusals as warnings (aipass install's step); dry_run changes nothing.
    """
    target = _resolve_dest(dest)
    try:
        validate_tag(tag)
        if dry_run:
            _print_dry_run(tag, from_path, sums_path, target, binary_path)
            return 0
        outcome = _install(tag, from_path, sums_path, target, binary_path)
    except _BAUD_ERRORS as exc:
        logger.warning("[baud] install refused: %s", exc)
        _report(str(exc), best_effort)
        return 1
    except OSError as exc:
        logger.error("[baud] install failed on the filesystem: %s", exc)
        _report(f"Install failed: {exc}", best_effort)
        return 1
    success(f"Phone face {outcome.tag} installed at {outcome.dest} ({outcome.files} files, {outcome.sha256[:12]}…)")
    if outcome.binary:
        success(f"baud-cli {outcome.tag} installed at {outcome.binary.path} ({outcome.binary.sha256[:12]}…)")
    else:
        console.print(f"  {outcome.binary_note}")
    return _point(outcome)


def install_best_effort(dry_run: bool = False, tag: str = LATEST) -> bool:
    """aipass install's step 4 (phone face + baud-cli). Never raises, never fails the install.

    ``tag`` is aipass install's --baud-tag, the release a stamped install.sh pins.

    Returns:
        True when the install was pointed (or dry-run walked).
    """
    try:
        rc = install_phone_face(tag=tag, dry_run=dry_run, best_effort=True)
    except Exception as exc:  # best-effort by contract: the install must continue
        logger.error("[baud] phone face step crashed: %s", exc)
        warning(f"Phone face not installed: {exc}")
        rc = 1
    if rc != 0:
        console.print(f"  [dim]{RETRY_HINT}[/dim]")
    return rc == 0


def phone_readiness(dry_run: bool = False, host_config: Any = None) -> PhoneReady:
    """What the phone needs now the face is in: the tailnet address, @api's bind, a live server.

    ``host_config`` is @api's host module door; None reads the real one. A dry run
    reads the config only (no tailscale, no probe).
    """
    return readiness(host_config if host_config is not None else _api_host_config(), dry_run)


def finish_phone(ready: PhoneReady, dry_run: bool = False, host_config: Any = None) -> None:
    """aipass install's last step and its closing lines, FPLAN-0642 slice D.

    Through @api's module door: move the bind to the tailnet address, render,
    install and enable the boot unit, then ask the server once more and print.
    A dry run calls install_unit and enable_unit with dry_run=True and neither
    set_bind nor autostart (autostart renders a file and has no dry run).
    """
    if not ready.api:
        print_phone_ready(ready, dry_run=dry_run)
        return
    door = host_config if host_config is not None else _api_host_config()
    bind = move_bind(door, ready, dry_run)
    boot = set_up_boot(door, dry_run)
    if not dry_run:
        ready = replace(ready, host=bind.host, port=bind.port, server=server_answers(bind.host, bind.port))
    print_phone_ready(ready, dry_run=dry_run, bind=bind, boot=boot)


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
    console.print(f"{_DRY} would print the phone URL, the token command, the sign-in note and the guide")


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


def print_phone_ready(
    ready: PhoneReady, dry_run: bool = False, bind: BindMove | None = None, boot: BootSetup | None = None
) -> None:
    """aipass install's last print: bind, boot unit, server, the phone URL, the token command, the guide.

    Never mints a token and never prints one. ``bind`` and ``boot`` are what
    finish_phone did; None (nothing attempted) prints the commands that do it by hand.
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
    console.print(f"  Token:      [cyan]{TOKEN_COMMAND}[/cyan]")
    if ready.receipt in ("", RECEIPT_REFUSED):
        console.print(f"{_PAD}its 0600 receipt path is printed when it is issued")
    else:
        console.print(f"{_PAD}its 0600 receipt lands at {ready.receipt}")
    console.print(f"{_PAD}paste the token on the sign-in page, the phone URL above")
    console.print(f"  Guide:      {PHONE_GUIDE_URL}")
    if not tailnet_up:
        warning(f"Tailscale is {ready.tailnet} here: the phone URL works on this machine only until it is up")
        console.print(f"  Install it: [cyan]{TAILSCALE_INSTALL}[/cyan], then: [cyan]sudo tailscale up[/cyan]")


def _status_face(target: Path, host_config: Any) -> None:
    """The face rows of aipass baud status."""
    state = read_install(target)
    console.print("  [bold]Phone face[/bold]")
    console.print(f"  Dest:        [cyan]{target}[/cyan]")
    if state["installed"]:
        console.print(f"  Installed:   {state['tag']} [dim]({state['installed_at']}, {state['source']})[/dim]")
        console.print(f"  sha256:      [dim]{state['sha256']}[/dim]")
    else:
        console.print("  Installed:   nothing [dim](run: aipass baud install)[/dim]")
    console.print(f"  phone.html:  {'present' if state['phone_html'] else 'missing'}")
    console.print(f"  @api face:   {api_face_dir_state(target, host_config)}")


def _status_binary(root: Path, host_config: Any) -> None:
    """The baud-cli rows of aipass baud status."""
    state = read_binary_install(root)
    path = Path(state["path"])
    console.print("  [bold]baud-cli[/bold]")
    console.print(f"  Path:        [cyan]{path}[/cyan]")
    if state["installed"]:
        console.print(f"  Installed:   {state['tag']} [dim]({state['installed_at']}, {state['source']})[/dim]")
        console.print(f"  sha256:      [dim]{state['sha256']}[/dim]")
    else:
        console.print("  Installed:   nothing [dim](run: aipass baud install)[/dim]")
    executable = "yes" if state["executable"] else ("no" if state["present"] else "missing")
    console.print(f"  Executable:  {executable}")
    console.print(f"  @api binary: {api_baud_bin_state(path, host_config)}")


def show_status(dest: str | None = None) -> int:
    """Print what is installed (face and baud-cli) and where @api's settings point."""
    target = _resolve_dest(dest)
    host_config = _api_host_config()
    console.print()
    console.print("[bold cyan]aipass baud status[/bold cyan]")
    _status_face(target, host_config)
    _status_binary(baud_root(target), host_config)
    console.print()
    return 0


def print_help() -> None:
    """Print usage help for the baud command."""
    console.print()
    console.print("[bold cyan]aipass baud[/bold cyan] — install @baud's phone face and baud-cli from a release")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass baud install[/green]                  [dim]# latest release[/dim]")
    console.print("  [green]aipass baud install --tag v0.2.1[/green]     [dim]# one release[/dim]")
    console.print("  [green]aipass baud install --from TAR[/green]       [dim]# a tarball on disk, no network[/dim]")
    console.print("  [green]    ... --sums SUMS[/green]                  [dim]# SHA256SUMS, default beside it[/dim]")
    console.print("  [green]    ... --binary BIN[/green]                 [dim]# + baud-cli, same sums file[/dim]")
    console.print("  [green]aipass baud install --dest DIR[/green]       [dim]# face DIR, baud-cli DIR/../bin[/dim]")
    console.print("  [green]aipass baud install --dry-run[/green]        [dim]# walk the steps, change nothing[/dim]")
    console.print(
        "  [green]aipass baud status[/green] [dim]\\[--dest DIR][/dim]      [dim]# installed tags, @api settings[/dim]"
    )
    console.print()
    console.print("[yellow]STEPS:[/yellow] fetch -> verify SHA256SUMS -> unpack face -> land baud-cli -> point @api")
    console.print()
    console.print(f"[dim]Default: {DEFAULT_DEST} and {bin_path(baud_root(DEFAULT_DEST))} (linux-x86_64 builds).[/dim]")
    console.print("[dim]A private repo needs GITHUB_TOKEN or a gh CLI login. A running host api needs a restart.[/dim]")
    console.print()


def print_introspection() -> None:
    """Show module info for baud."""
    console.print()
    console.print(f"[bold cyan]Module:[/bold cyan] {_MODULE_NAME}")
    console.print(f"[bold cyan]Command:[/bold cyan] {COMMAND}")
    console.print("[bold cyan]Description:[/bold cyan] Install @baud's phone face and baud-cli, point @api at them")
    console.print(f"[bold cyan]Version:[/bold cyan] {_VERSION}")
    console.print(f"[dim]Default dest: {DEFAULT_DEST}[/dim]")
    console.print("[dim]Run 'aipass baud --help' for usage[/dim]")
    console.print()


def _run_install(rest: List[str]) -> int:
    """Parse `aipass baud install`'s flags and run it."""
    flags = _parse_flags(rest, (*_VALUE_FLAGS, "--dry-run"))
    for flag in _FROM_ONLY:
        if flags.get(flag) and not flags.get("--from"):
            raise UsageError(f"{flag} goes with --from")
    return install_phone_face(
        tag=flags.get("--tag") or LATEST,
        from_path=flags.get("--from"),
        sums_path=flags.get("--sums"),
        dest=flags.get("--dest"),
        dry_run=flags["--dry-run"],
        binary_path=flags.get("--binary"),
    )


def handle_command(command: str, args: list[str]) -> bool:
    """Route `aipass baud <install|status>`. Returns True if handled."""
    if command != COMMAND:
        return False
    if not args:
        print_introspection()
        return True
    if wants_help(args):
        print_help()
        return True
    if args[0] in ("--info", "info"):
        print_introspection()
        return True

    verb, rest = args[0], args[1:]
    try:
        if verb == "install":
            rc = _run_install(rest)
        elif verb == "status":
            rc = show_status(dest=_parse_flags(rest, ("--dest",)).get("--dest"))
        else:
            raise UsageError(f"Unknown baud command: {verb} (install, status)")
    except UsageError as exc:
        logger.info("[baud] usage error: %s", exc)
        error(str(exc))
        console.print("[dim]Run 'aipass baud --help' for usage[/dim]")
        rc = 2
    json_handler.log_operation("baud_run", {"verb": verb, "exit": rc}, module_name=_MODULE_NAME)
    sys.exit(rc)
