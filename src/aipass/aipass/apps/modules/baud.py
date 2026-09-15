# =================== AIPass ====================
# Name: baud.py
# Description: aipass baud: install @baud's phone face and baud-cli from a release and point @api at them
# Version: 1.1.0
# Created: 2026-09-13
# Modified: 2026-09-14
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

``aipass install`` runs the same install as its best-effort step 4.
"""

from __future__ import annotations

import sys
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
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.aipass.apps.handlers.json import json_handler
from aipass.cli.apps.modules import console, error, success, warning
from aipass.prax import logger

COMMAND = "baud"
_MODULE_NAME = "baud"
_VERSION = "1.1.0"
DEFAULT_DEST = Path.home() / ".aipass" / "baud" / "phone"
RETRY_HINT = "Retry anytime: aipass baud install  (or: aipass baud install --from <tarball> --sums <SHA256SUMS.txt>)"

_VALUE_FLAGS = ("--tag", "--from", "--sums", "--dest", "--binary")
_FROM_ONLY = ("--sums", "--binary")
_BAUD_ERRORS = (FetchError, VerifyError, UnpackError)


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


def install_best_effort(dry_run: bool = False) -> bool:
    """aipass install's step 4 (phone face + baud-cli). Never raises, never fails the install.

    Returns:
        True when the install was pointed (or dry-run walked).
    """
    try:
        rc = install_phone_face(dry_run=dry_run, best_effort=True)
    except Exception as exc:  # best-effort by contract: the install must continue
        logger.error("[baud] phone face step crashed: %s", exc)
        warning(f"Phone face not installed: {exc}")
        rc = 1
    if rc != 0:
        console.print(f"  [dim]{RETRY_HINT}[/dim]")
    return rc == 0


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
