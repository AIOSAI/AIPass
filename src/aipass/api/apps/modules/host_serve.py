# =================== AIPass ====================
# Name: host_serve.py
# Description: Host API Serve Module — starting, watching and stopping the server
# Version: 1.0.2
# Created: 2026-08-19
# Modified: 2026-10-22
# =============================================

"""
Host API Serve Module

A module, not a handler: these commands are presentation. host_api.py offers it every host-api call first.
Reference: docs/host_autostart.md
"""

import sys
from typing import List, Optional

from aipass.cli.apps.modules import console, header, success, error, warning
from aipass.api.apps.handlers.json import json_handler
from aipass.prax import logger
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import lifetime as host_lifetime
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import autostart as host_autostart


def flag_value(args: List[str], flag: str) -> Optional[str]:
    """
    Read the value following *flag*.

    Lives here, shared with host_api.py, because host_api imports this module and not the reverse.
    """
    if flag not in args:
        return None

    index = args.index(flag)
    if index + 1 >= len(args):
        return None

    value = args[index + 1]
    if value.startswith("-"):
        return None

    return value


def cmd_serve(args: List[str]) -> None:
    """Run the server after the bind gate clears, in this process or its own."""
    header("Host API Server")
    console.print()

    if not host_server.is_available():
        error(
            "Server libraries not installed",
            suggestion=host_server.INSTALL_HINT,
        )
        return

    host = flag_value(args, "--host")
    port_raw = flag_value(args, "--port")

    port = None
    if port_raw is not None:
        try:
            port = int(port_raw)
        except ValueError:
            logger.warning("[host_api] non-numeric port rejected: %s", port_raw)
            error(f"Port must be a number, got: {port_raw}")
            return

    if "--detach" in args:
        _serve_detached(host, port)
        return

    _serve_foreground(host, port)


def _serve_foreground(host: Optional[str], port: Optional[int]) -> None:
    """Run the server in this process until it stops."""
    try:
        host_server.serve(host=host, port=port)
    except host_config.BindRefused as e:
        logger.error("[host_api] bind refused, server not started: %s", e)
        error("Bind refused — server not started", suggestion=str(e))
        json_handler.log_operation("host_api_bind_refused", {"reason": str(e)})
        # Non-zero: the unit's Restart=on-failure retries the boot race where tailscaled has not yet
        # assigned the address; a zero exit disarms every retry.
        sys.exit(1)
    except RuntimeError as e:
        logger.error("[host_api] server could not start: %s", e)
        error(str(e))


def _serve_detached(host: Optional[str], port: Optional[int]) -> None:
    """
    Start the server in its own session and hand back where it lives.

    A serve under drone is a child of drone's exec timeout; detached, it owns its session and logs to a file.
    """
    try:
        record = host_lifetime.serve_detached(host=host, port=port)
    except host_autostart.SupervisorUnreachable as e:
        logger.warning("[host_api] detach could not reach the supervisor: %s", e)
        error("Cannot start — the supervisor did not answer", suggestion=str(e))
        return
    except host_config.BindRefused as e:
        # Refused here, not in the child: a refusal found only in a log file reads as a crash.
        logger.error("[host_api] bind refused, nothing detached: %s", e)
        error("Bind refused — server not started", suggestion=str(e))
        json_handler.log_operation("host_api_bind_refused", {"reason": str(e)})
        sys.exit(1)
    except host_lifetime.LifetimeError as e:
        logger.warning("[host_api] detached serve refused: %s", e)
        error(str(e))
        return

    success(f"Server detached: {record['host']}:{record['port']}")
    console.print(f"  [cyan]pid:[/cyan]  {record['pid']}")
    console.print(f"  [cyan]log:[/cyan]  {record['log']} [dim](appended, survives a restart)[/dim]")
    console.print()
    console.print("[dim]Stop it: drone @api host-api stop[/dim]")
    console.print()


def cmd_status() -> None:
    """Say whether a server is running, who holds it, and where to read it."""
    header("Host API Server Status")
    console.print()

    answer = host_lifetime.server_state()

    if answer["state"] == "unknown":
        # Not "no server": a supervised server writes no record file, so a swallowed probe would lie.
        error("Cannot tell — the supervisor did not answer", suggestion=answer["reason"])
        console.print()
        console.print(f"[dim]Ask it directly: systemctl --user status {host_autostart.unit_name()}[/dim]")
        console.print(f"[dim]Its output, either way: {host_lifetime.log_path()}[/dim]")
        return

    if answer["state"] == "none":
        warning("No server is running")
        console.print()
        console.print("[dim]Start one now:      drone @api host-api serve --detach[/dim]")
        console.print("[dim]Start one with your login:  drone @api host-api autostart[/dim]")
        console.print(f"[dim]Its last output, if any: {host_lifetime.log_path()}[/dim]")
        return

    _show_server(answer["record"])


def _show_server(record: dict) -> None:
    """Print a running server's facts."""
    bind_host = record.get("host") or "unknown"
    bind_port = record.get("port") or "unknown"

    success(f"Running: {bind_host}:{bind_port}")
    console.print(f"  [cyan]pid:[/cyan]      {record.get('pid')}")

    if record.get("owner") == host_lifetime.OWNER_SUPERVISOR:
        console.print(f"  [cyan]owner:[/cyan]    systemd [dim]({record.get('unit')})[/dim]")
        console.print("  [cyan]restart:[/cyan]  [dim]on failure, and at each login[/dim]")
    else:
        console.print("  [cyan]owner:[/cyan]    detached [dim](started by hand — dies with a reboot)[/dim]")
        console.print(f"  [cyan]started:[/cyan]  {record.get('started')}")

    console.print(f"  [cyan]log:[/cyan]      {record.get('log')}")
    console.print()


def cmd_stop() -> None:
    """Ask a detached server to exit."""
    header("Stop Host API Server")
    console.print()

    try:
        record = host_lifetime.stop()
    except host_autostart.SupervisorUnreachable as e:
        # Refuse: if a unit holds the server, a bare SIGTERM is a stop its restart policy may undo.
        logger.warning("[host_api] stop could not reach the supervisor: %s", e)
        error("Cannot stop — the supervisor did not answer", suggestion=str(e))
        return
    except host_lifetime.LifetimeError as e:
        logger.warning("[host_api] stop did not complete: %s", e)
        error(str(e))
        return

    if record is None:
        warning("No server was running")
        console.print()
        return

    success(f"Stopped pid {record.get('pid')}")

    if record.get("owner") == host_lifetime.OWNER_SUPERVISOR:
        console.print(f"  [dim]through systemd ({record.get('unit')}) — it stays down until started[/dim]")
        console.print(f"  [dim]Start it again: systemctl --user start {record.get('unit')}[/dim]")

    console.print()


def cmd_autostart(args: List[str]) -> None:
    """Render the boot unit into this branch and print the host-side steps."""
    header("Host API Autostart")
    console.print()

    host = flag_value(args, "--host")
    port_raw = flag_value(args, "--port")

    port = None
    if port_raw is not None:
        try:
            port = int(port_raw)
        except ValueError:
            logger.warning("[host_api] non-numeric port rejected: %s", port_raw)
            error(f"Port must be a number, got: {port_raw}")
            return

    try:
        report = host_lifetime.autostart_report(host, port)
    except host_autostart.AutostartUnsupported as e:
        logger.warning("[host_api] autostart is unavailable on this platform: %s", e)
        error("Autostart is not available here", suggestion=str(e))
        return
    except host_config.BindRefused as e:
        logger.error("[host_api] bind refused, no unit written: %s", e)
        error("Bind refused — no unit written", suggestion=str(e))
        json_handler.log_operation("host_api_bind_refused", {"reason": str(e)})
        # Non-zero so a scripted `autostart && systemctl --user enable ...` stops here.
        sys.exit(1)
    except OSError as e:
        logger.error("[host_api] the unit could not be written: %s", e)
        error(f"The unit could not be written: {e}")
        return

    _show_installation(report)


def _show_installation(report: dict) -> None:
    """Print a rendered unit's install steps and what stands in their way."""
    success(f"Unit rendered: {report['unit']}")
    console.print()
    console.print("[dim]It is NOT installed — these steps run outside this tree, and are yours:[/dim]")
    console.print()

    for step in report["steps"]:
        console.print(f"  [cyan]{step}[/cyan]")

    console.print()
    console.print("[dim]The unit starts with your graphical session and stops with it.[/dim]")

    # A hand-started server on the port makes `enable --now` fail to bind, which reads as broken autostart.
    conflict = report.get("conflict")

    if conflict is not None:
        console.print()
        warning(f"A hand-started server is on the port now (pid {conflict.get('pid')})")
        console.print("  [dim]Stop it BEFORE 'enable --now', or the unit cannot bind and ends in failed:[/dim]")
        console.print("  [cyan]drone @api host-api stop[/cyan]")

    console.print()


SUBCOMMANDS = {"serve", "status", "stop", "autostart"}


def handle_command(command: str, args: List[str]) -> bool:
    """
    Claim the server-lifecycle subcommands of `host-api`.

    False means "not mine": host_api.py owns every declined call, so an unknown subcommand reaches its error.
    """
    # Both spellings: `drone @api` bare advertises the module name while the command is host-api.
    if command not in ("host-api", "host_api"):
        return False

    # The help gate claims only owned subcommands (`host-api --help` is host_api.py's); a help flag
    # anywhere means explain, never run.
    if not args:
        print_introspection()
        return True

    if args[0] not in SUBCOMMANDS:
        return False

    if any(arg in ("--help", "-h", "help") for arg in args):
        print_introspection()
        return True

    subcommand, rest = args[0], args[1:]

    if subcommand == "serve":
        cmd_serve(rest)
    elif subcommand == "status":
        cmd_status()
    elif subcommand == "autostart":
        cmd_autostart(rest)
    else:
        cmd_stop()

    return True


def print_introspection() -> None:
    """Show what this module answers for."""
    console.print()
    console.print("[bold cyan]host_serve — the host API server's lifecycle[/bold cyan]")
    console.print()
    console.print("  [cyan]host-api serve [--detach][/cyan]  [dim]Run it, here or in its own session[/dim]")
    console.print("  [cyan]host-api status[/cyan]            [dim]Is a server up, who holds it, and where[/dim]")
    console.print("  [cyan]host-api stop[/cyan]              [dim]Stop it, through whoever owns it[/dim]")
    console.print("  [cyan]host-api autostart[/cyan]         [dim]Render the boot unit + the install steps[/dim]")
    console.print()
