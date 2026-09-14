# =================== AIPass ====================
# Name: host_config_cli.py
# Description: Host API Config Module — showing and setting what the server binds, serves and execs
# Version: 1.0.0
# Created: 2026-09-14
# Modified: 2026-09-14
# =============================================

"""
Host API Config Module

`host-api config` and `host-api set-config` at the CLI: the bind address, the
phone face directory and the baud binary the fleet lanes exec.

Split from host_api.py on 2026-09-14, when the baud_bin setting (FPLAN-0589)
pushed that file past its size cap a second time. The seam is the one
host_serve.py found: everything here is about STORED SETTINGS, everything left
there is about tokens, and host_api.py keeps the cross-branch door onto both.

A sub-router like host_serve.py: host_api.py offers it every host-api call and
owns everything it declines.

Functions:
    handle_command()      - Claim config/set-config, decline everything else
    print_introspection() - This module's live self-map
    _cmd_config()     - Show the effective bind, face and binary
    _cmd_set_config() - Validate every named setting, then store them
"""

import os
from pathlib import Path
from typing import List, Optional

from aipass.cli.apps.modules import console, header, success, error, warning
from aipass.api.apps.handlers.json import json_handler
from aipass.prax import logger
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import face as host_face
from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.modules import host_serve

# set-config's spelling, for --face-dir and --baud-bin alike, of "clear it: back to automatic".
SETTING_DEFAULT = "default"


# =============================================
# COMMANDS
# =============================================


def _cmd_config() -> None:
    """Show the effective server configuration."""
    header("Host API Config")
    console.print()

    config = host_config.load_config()
    console.print(f"  [cyan]host:[/cyan] {config['host']}")
    console.print(f"  [cyan]port:[/cyan] {config['port']}")

    # The face a server starting now would serve, and which source named it.
    face = host_face.face_location()
    servable = face.has_entry()
    console.print(f"  [cyan]face:[/cyan] {face.root} [dim]({face.source})[/dim]")
    entry_state = "[green]present[/green]" if servable else "[yellow]missing[/yellow]"
    console.print(f"  [cyan]{host_face.FACE_ENTRY}:[/cyan] {entry_state}")
    if not servable:
        console.print(f"  [dim]{face.unavailable_message()}[/dim]")
    console.print("  [dim]A running server serves the face it started with.[/dim]")
    console.print()

    # The binary the next fleet request would exec — resolved per request, so no restart.
    binary = host_fleet.locate_binary()
    runnable = "[green]yes[/green]" if binary.runnable() else "[yellow]no[/yellow]"
    console.print(f"  [cyan]binary:[/cyan] {binary.path or 'not found'} [dim]({binary.source})[/dim]")
    console.print(f"  [cyan]executable:[/cyan] {runnable}")
    if binary.problem():
        console.print(f"  [dim]{binary.problem()}[/dim]")
    console.print()

    try:
        host_config.validate_bind(config["host"], int(config["port"]))
        success("Bind address would be accepted")
    except host_config.BindRefused as e:
        logger.info("[host_api] config preview: bind would be refused (%s)", e)
        warning("Bind address would be REFUSED")
        console.print(f"  [dim]{e}[/dim]")
    console.print()


def _cmd_set_config(args: List[str]) -> None:
    """
    Write the server config: the bind address, the face dir, the baud binary.

    Each is a control, so it gets a real command rather than leaving the
    operator to hand-edit JSON in the secrets store. Every value is validated
    BEFORE anything is stored — a config that would be refused later is refused
    at write time, where the person who typed it is still watching.

    One refusal stores nothing. The bind and both paths are all validated first,
    then the paths are stored, and the bind last, onto a config re-read after
    them so it cannot overwrite what they wrote.
    """
    header("Set Host API Config")
    console.print()

    host = host_serve.flag_value(args, "--host")
    port_raw = host_serve.flag_value(args, "--port")
    face_raw = host_serve.flag_value(args, "--face-dir")
    baud_raw = host_serve.flag_value(args, "--baud-bin")

    if all(value is None for value in (host, port_raw, face_raw, baud_raw)):
        error(
            "Nothing to set",
            suggestion=(
                "drone @api host-api set-config --host 127.0.0.1 --port 8787, "
                "or --face-dir <dir>|default, or --baud-bin <path>|default"
            ),
        )
        return

    config = host_config.load_config()
    bind_host = host if host is not None else config["host"]
    bind_port = config["port"]
    if port_raw is not None:
        try:
            bind_port = int(port_raw)
        except ValueError:
            logger.warning("[host_api] non-numeric port rejected at set-config: %s", port_raw)
            error(f"Port must be a number, got: {port_raw}")
            return

    # Validated only when this command changes the bind: a face dir write must
    # not be refused over a stored address its caller never touched.
    bind_changed = host is not None or port_raw is not None
    if bind_changed:
        try:
            host_config.validate_bind(bind_host, int(bind_port))
        except host_config.BindRefused as e:
            logger.warning("[host_api] set-config refused: %s", e)
            error("Refusing to store a bind that would not start", suggestion=str(e))
            return

    if _a_path_setting_is_refused(face_raw, baud_raw):
        return

    if face_raw is not None and not _set_face_dir(face_raw):
        return
    if baud_raw is not None and not _set_baud_bin(baud_raw):
        return

    if bind_changed:
        # Re-read: the path settings above may have just written this same store.
        config = host_config.load_config()
        config["host"], config["port"] = bind_host, bind_port
        path = host_config.save_config(config)
        json_handler.log_operation("host_api_config_saved", {"host": bind_host, "port": bind_port})

        success(f"Config saved: {bind_host}:{bind_port}")
        console.print(f"  [dim]{path}[/dim]")
    console.print()


# =============================================
# PRIVATE HELPERS
# =============================================


def _path_target(raw: str) -> Optional[Path]:
    """
    The path a --face-dir or --baud-bin value names.

    Args:
        raw: A path, "~" expanded here, or SETTING_DEFAULT.

    Returns:
        The path, or None for SETTING_DEFAULT: clear it, back to automatic.
    """
    return None if raw == SETTING_DEFAULT else Path(os.path.expanduser(raw))


def _a_path_setting_is_refused(face_raw: Optional[str], baud_raw: Optional[str]) -> bool:
    """
    Validate every path this command names before any of them is stored.

    Args:
        face_raw: --face-dir's value, or None when it was not given.
        baud_raw: --baud-bin's value, or None when it was not given.

    Returns:
        True when one was refused, its error already shown; False when all may be stored.
    """
    face_target = _path_target(face_raw) if face_raw is not None else None
    baud_target = _path_target(baud_raw) if baud_raw is not None else None

    try:
        if face_target is not None:
            host_config.validate_face_dir(face_target)
    except host_config.FaceDirRefused as e:
        logger.warning("[host_api] set-config refused the face dir: %s", e)
        error("Refusing to store a face dir that would not serve", suggestion=str(e))
        return True

    try:
        if baud_target is not None:
            host_config.validate_baud_bin(baud_target)
    except host_config.BaudBinRefused as e:
        logger.warning("[host_api] set-config refused the baud binary: %s", e)
        error("Refusing to store a baud binary that would not run", suggestion=str(e))
        return True

    return False


def _set_baud_bin(raw: str) -> bool:
    """
    Store or clear the baud binary named by set-config's --baud-bin.

    Args:
        raw: An executable file, "~" expanded here, or SETTING_DEFAULT to clear.

    Returns:
        True when stored or cleared; False when refused, the error already shown.
    """
    try:
        stored = host_config.set_baud_bin(_path_target(raw))
    except host_config.BaudBinRefused as e:
        # Validated a moment ago, so the file changed in between.
        logger.warning("[host_api] set-config refused the baud binary: %s", e)
        error("Refusing to store a baud binary that would not run", suggestion=str(e))
        return False

    if stored is None:
        now = host_fleet.locate_binary()
        success(f"Baud binary cleared: the automatic lookup answers ({now.path or 'nothing found'}, {now.source})")
    else:
        success(f"Baud binary saved: {stored}")
    console.print("  [dim]Used from the next fleet request: no restart.[/dim]")
    return True


def _set_face_dir(raw: str) -> bool:
    """
    Store or clear the face dir named by set-config's --face-dir.

    Args:
        raw: A directory, "~" expanded here, or SETTING_DEFAULT to clear.

    Returns:
        True when stored or cleared; False when refused, the error already shown.
    """
    try:
        stored = host_config.set_face_dir(_path_target(raw))
    except host_config.FaceDirRefused as e:
        # Validated a moment ago, so the directory changed in between.
        logger.warning("[host_api] set-config refused the face dir: %s", e)
        error("Refusing to store a face dir that would not serve", suggestion=str(e))
        return False

    if stored is None:
        success(f"Face dir cleared: the checkout build is served from {host_face.face_root()}")
    else:
        success(f"Face dir saved: {stored}")
    console.print("  [dim]A running server keeps the face it started with: restart it to serve this one.[/dim]")
    return True


# =============================================
# DRONE ROUTING
# =============================================


SUBCOMMANDS = {"config", "set-config"}


def handle_command(command: str, args: List[str]) -> bool:
    """
    Claim the stored-settings subcommands of `host-api`.

    Args:
        command: The routed command name.
        args: Everything after it, subcommand first.

    Returns:
        True if this module handled it. False means "not mine" — host_api.py
        offers every host-api call here and owns everything declined, so an
        unknown subcommand still reaches its error message.
    """
    # Both spellings, matching host_api.py and host_serve.py.
    if command not in ("host-api", "host_api"):
        return False

    # NO-ARGS GATE and HELP GATE (seedgo standard), as in host_serve.py: host_api.py
    # reaches both first today, and a router only correct given its caller is a trap.
    if not args:
        print_introspection()
        return True

    if any(arg in ("--help", "-h", "help") for arg in args):
        print_introspection()
        return True

    if args[0] not in SUBCOMMANDS:
        return False

    if args[0] == "config":
        _cmd_config()
    else:
        _cmd_set_config(args[1:])

    return True


def print_introspection() -> None:
    """Show what this module answers for."""
    console.print()
    console.print("[bold cyan]host_config_cli — what the host API binds, serves and execs[/bold cyan]")
    console.print()
    console.print("  [cyan]host-api config[/cyan]      [dim]The effective bind, face and baud binary[/dim]")
    console.print("  [cyan]host-api set-config[/cyan]  [dim]Bind, face dir or baud binary (validated first)[/dim]")
    console.print()
