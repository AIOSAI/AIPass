# =================== AIPass ====================
# Name: baud.py
# Description: aipass baud: install @baud's phone face from a release and point @api at it
# Version: 1.0.0
# Created: 2026-09-13
# Modified: 2026-09-13
# =============================================

"""
aipass baud: the phone face comes from a release, not a checkout (FPLAN-0587 row 2).

A stranger who never cloned baud still gets the phone face: fetch
``baud-phone-<tag>.tar.gz`` and ``SHA256SUMS.txt`` from a baud release, verify
the digest, unpack through a safety filter into ``~/.aipass/baud/phone/``, and
hand that directory to @api's host server. AIPass never vendors the bundle: the
licences stay apart (DPLAN-0313).

Usage:
    aipass baud install                              # latest release
    aipass baud install --tag v0.2.0                 # one release
    aipass baud install --from <tar> --sums <sums>   # a tarball on disk, no network
    aipass baud install --dest <dir>                 # somewhere other than ~/.aipass/baud/phone
    aipass baud install --dry-run                    # say what would happen, touch nothing
    aipass baud status [--dest <dir>]                # what is installed, where @api points

``aipass install`` runs the same install as its best-effort "Phone face" step.
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
    UnpackError,
    VerifyError,
    api_face_dir_state,
    install_from_file,
    install_from_release,
    phone_asset_name,
    phone_url,
    point_api_at,
    read_install,
    validate_tag,
)
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.aipass.apps.handlers.json import json_handler
from aipass.cli.apps.modules import console, error, success, warning
from aipass.prax import logger

COMMAND = "baud"
_MODULE_NAME = "baud"
_VERSION = "1.0.0"
DEFAULT_DEST = Path.home() / ".aipass" / "baud" / "phone"
RETRY_HINT = "Retry anytime: aipass baud install  (or: aipass baud install --from <tarball> --sums <SHA256SUMS.txt>)"

_VALUE_FLAGS = ("--tag", "--from", "--sums", "--dest")
_BAUD_ERRORS = (FetchError, VerifyError, UnpackError)


class UsageError(Exception):
    """The command line was malformed. The message is safe to print."""


def _api_host_config() -> Any:
    """@api's host config module (set_face_dir, face_dir, load_config), or None.

    The one cross-branch edge of this command, held here in the module layer and
    handed to handlers/baud/point.py. FPLAN-0587 pins the in-process call: @api
    validates the directory at write time and aipass never writes api's config.
    """
    try:
        from aipass.api.apps.handlers.host import config as host_config
    except ImportError as exc:
        logger.warning("[baud] @api host config not importable: %s", exc)
        return None
    return host_config


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


def _print_dry_run(tag: str, from_path: str | None, sums_path: str | None, dest: Path) -> None:
    """Walk the install without touching the network or the disk."""
    prefix = "[yellow]\\[dry-run][/yellow]"
    if from_path:
        sums = sums_path or str(Path(from_path).expanduser().parent / SUMS_ASSET)
        console.print(f"  {prefix} would verify {from_path} against {sums}")
    else:
        asset = phone_asset_name("<tag>") if tag == LATEST else phone_asset_name(tag)
        console.print(f"  {prefix} would fetch {asset} and {SUMS_ASSET} from the {tag} baud release")
        console.print(f"  {prefix} would verify the tarball's sha256 against {SUMS_ASSET}")
    console.print(f"  {prefix} would unpack it (safety filter, staging swap) into {dest}")
    console.print(f"  {prefix} would point @api's host server at {dest}")


def _report(message: str, best_effort: bool) -> None:
    """A refusal: a warning inside aipass install, an error on its own."""
    if best_effort:
        warning(f"Phone face not installed: {message}")
    else:
        error(message)


def _install(tag: str, from_path: str | None, sums_path: str | None, dest: Path) -> InstallOutcome:
    """--from installs a file on disk; otherwise the release is fetched."""
    if from_path:
        sums = Path(sums_path).expanduser().resolve() if sums_path else None
        return install_from_file(Path(from_path).expanduser().resolve(), sums, dest, tag)
    console.print(f"  [dim]Fetching the {tag} baud phone bundle…[/dim]")
    return install_from_release(tag, dest)


def _point(outcome: InstallOutcome) -> int:
    """Hand the installed directory to @api, then say how to see it. 0 when @api took it."""
    host_config = _api_host_config()
    pointed = point_api_at(outcome.dest, host_config)
    json_handler.log_operation(
        "baud_install",
        {"tag": outcome.tag, "dest": str(outcome.dest), "pointed": pointed.ok},
        module_name=_MODULE_NAME,
    )
    if not pointed.ok:
        warning(pointed.message)
        return 1
    success(pointed.message)
    console.print(f"  [dim]{RESTART_HINT}[/dim]")
    console.print(f"  [dim]Then open:[/dim] [cyan]{phone_url(host_config)}[/cyan]")
    return 0


def install_phone_face(
    tag: str = LATEST,
    from_path: str | None = None,
    sums_path: str | None = None,
    dest: str | None = None,
    dry_run: bool = False,
    best_effort: bool = False,
) -> int:
    """Fetch (or take), verify, unpack, point. 0 installed and pointed; 1 otherwise.

    best_effort reports refusals as warnings (aipass install's step); dry_run
    prints the steps and changes nothing.
    """
    target = _resolve_dest(dest)
    try:
        validate_tag(tag)
        if dry_run:
            _print_dry_run(tag, from_path, sums_path, target)
            return 0
        outcome = _install(tag, from_path, sums_path, target)
    except _BAUD_ERRORS as exc:
        logger.warning("[baud] install refused: %s", exc)
        _report(str(exc), best_effort)
        return 1
    except OSError as exc:
        logger.error("[baud] install failed on the filesystem: %s", exc)
        _report(f"Install failed: {exc}", best_effort)
        return 1
    success(f"Phone face {outcome.tag} installed at {outcome.dest} ({outcome.files} files, {outcome.sha256[:12]}…)")
    return _point(outcome)


def install_best_effort(dry_run: bool = False) -> bool:
    """aipass install's Phone face step. Never raises, never fails the install.

    Returns:
        True when the face was installed and pointed (or dry-run walked).
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


def show_status(dest: str | None = None) -> int:
    """Print what is installed at dest and where @api's face_dir points."""
    target = _resolve_dest(dest)
    state = read_install(target)
    console.print()
    console.print("[bold cyan]aipass baud status[/bold cyan]")
    console.print(f"  Dest:        [cyan]{target}[/cyan]")
    if state["installed"]:
        console.print(f"  Installed:   {state['tag']} [dim]({state['installed_at']}, {state['source']})[/dim]")
        console.print(f"  sha256:      [dim]{state['sha256']}[/dim]")
    else:
        console.print("  Installed:   nothing [dim](run: aipass baud install)[/dim]")
    console.print(f"  phone.html:  {'present' if state['phone_html'] else 'missing'}")
    console.print(f"  @api face:   {api_face_dir_state(target, _api_host_config())}")
    console.print()
    return 0


def print_help() -> None:
    """Print usage help for the baud command."""
    console.print()
    console.print("[bold cyan]aipass baud[/bold cyan] — install @baud's phone face from a release")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass baud install[/green]                  [dim]# latest release[/dim]")
    console.print("  [green]aipass baud install --tag v0.2.0[/green]     [dim]# one release[/dim]")
    console.print("  [green]aipass baud install --from TAR[/green]       [dim]# a tarball on disk, no network[/dim]")
    console.print("  [green]    ... --sums SUMS[/green]                  [dim]# SHA256SUMS, default beside it[/dim]")
    console.print("  [green]aipass baud install --dest DIR[/green]       [dim]# default ~/.aipass/baud/phone[/dim]")
    console.print("  [green]aipass baud install --dry-run[/green]        [dim]# walk the steps, change nothing[/dim]")
    console.print(
        "  [green]aipass baud status[/green] [dim]\\[--dest DIR][/dim]      [dim]# installed tag, @api face dir[/dim]"
    )
    console.print()
    console.print("[yellow]STEPS:[/yellow] fetch -> verify SHA256SUMS -> unpack (safety filter) -> swap -> point @api")
    console.print()
    console.print("[dim]A private repo needs GITHUB_TOKEN or a gh CLI login. A running host api needs a restart.[/dim]")
    console.print()


def print_introspection() -> None:
    """Show module info for baud."""
    console.print()
    console.print(f"[bold cyan]Module:[/bold cyan] {_MODULE_NAME}")
    console.print(f"[bold cyan]Command:[/bold cyan] {COMMAND}")
    console.print("[bold cyan]Description:[/bold cyan] Install @baud's phone face from a release, point @api at it")
    console.print(f"[bold cyan]Version:[/bold cyan] {_VERSION}")
    console.print(f"[dim]Default dest: {DEFAULT_DEST}[/dim]")
    console.print("[dim]Run 'aipass baud --help' for usage[/dim]")
    console.print()


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
            flags = _parse_flags(rest, (*_VALUE_FLAGS, "--dry-run"))
            if flags.get("--sums") and not flags.get("--from"):
                raise UsageError("--sums goes with --from")
            rc = install_phone_face(
                tag=flags.get("--tag") or LATEST,
                from_path=flags.get("--from"),
                sums_path=flags.get("--sums"),
                dest=flags.get("--dest"),
                dry_run=flags["--dry-run"],
            )
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
