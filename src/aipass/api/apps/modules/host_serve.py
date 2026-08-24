# =================== AIPass ====================
# Name: host_serve.py
# Description: Host API Serve Module — starting, watching and stopping the server
# Version: 1.0.0
# Created: 2026-08-19
# Modified: 2026-08-19
# =============================================

"""
Host API Serve Module

The server's lifecycle at the CLI: run it here, run it detached, ask whether it
is up, ask it to stop.

Split from host_api.py on 2026-08-19, when adding --detach/status/stop pushed
that file past its size cap. The seam is a real one rather than an arbitrary
cut: everything here is about a PROCESS, and everything left there is about
tokens and stored config.

A MODULE RATHER THAN A HANDLER, after trying it the other way. Handlers do
not print, and these three commands are almost entirely presentation — so the
first cut put it under handlers/ and seedgo was right to refuse it. It carries
its own handle_command() because it genuinely IS a command surface: host_api.py
offers it the subcommands first and owns everything it declines.

Functions:
    handle_command()      - Claim serve/status/stop, decline everything else
    print_introspection() - This module's live self-map
    flag_value()          - Read the value following a flag
    cmd_serve()   - Run the server, in this process or its own
    cmd_status()  - Whether a detached server is running, and where to read it
    cmd_stop()    - Ask a detached server to exit
"""

from typing import List, Optional

from aipass.cli.apps.modules import console, header, success, error, warning
from aipass.api.apps.handlers.json import json_handler
from aipass.prax import logger
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import lifetime as host_lifetime
from aipass.api.apps.handlers.host import server as host_server


def flag_value(args: List[str], flag: str) -> Optional[str]:
    """
    Read the value following *flag*.

    Shared with host_api.py's token commands. It lives HERE rather than
    there because host_api imports this module and not the reverse — and a
    third module for one seven-line function would cost more to find than
    the slightly odd address does.

    Args:
        args: Argument list.
        flag: Flag name, e.g. "--host".

    Returns:
        The value, or None if the flag is absent or has no value after it.
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

    try:
        host_server.serve(host=host, port=port)
    except host_config.BindRefused as e:
        # The whole point of D1: refuse, explain, and do not start.
        logger.error("[host_api] bind refused, server not started: %s", e)
        error("Bind refused — server not started", suggestion=str(e))
        json_handler.log_operation("host_api_bind_refused", {"reason": str(e)})
    except RuntimeError as e:
        logger.error("[host_api] server could not start: %s", e)
        error(str(e))


def _serve_detached(host: Optional[str], port: Optional[int]) -> None:
    """
    Start the server in its own session and hand back where it lives.

    A serve routed through drone is a CHILD of drone's exec timeout — twelve
    hours on the tailnet server, and @baud read fourteen death-and-restart
    cycles out of the pane on 2026-08-19. The restart churn cost more than the
    downtime did: uvicorn's access log goes to stdout, stdout was that pane, and
    a day of history scrolled out of it. Detached, the child owns its own
    session and writes to a file, so drone times a launcher that exits in under
    a second and nothing it does reaches the server.

    Args:
        host: Bind address override, already parsed.
        port: Port override, already parsed.
    """
    try:
        record = host_lifetime.serve_detached(host=host, port=port)
    except host_config.BindRefused as e:
        # D1 again, and it fires HERE rather than inside the child on purpose:
        # a refusal an operator has to go and find in a log file is a refusal
        # that reads as a crash.
        logger.error("[host_api] bind refused, nothing detached: %s", e)
        error("Bind refused — server not started", suggestion=str(e))
        json_handler.log_operation("host_api_bind_refused", {"reason": str(e)})
        return
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
    """Say whether a detached server is running, and where to read it."""
    header("Host API Server Status")
    console.print()

    record = host_lifetime.running()

    if record is None:
        warning("No detached server is running")
        console.print()
        # NOT a restart. A dead server that stays dead and says so is the
        # honest failure; a supervisor of my own would be the second one in
        # this system, and the first is in somebody's pane.
        console.print("[dim]Start one: drone @api host-api serve --detach[/dim]")
        console.print(f"[dim]Its last output, if any: {host_lifetime.log_path()}[/dim]")
        return

    success(f"Running: {record.get('host')}:{record.get('port')}")
    console.print(f"  [cyan]pid:[/cyan]      {record.get('pid')}")
    console.print(f"  [cyan]started:[/cyan]  {record.get('started')}")
    console.print(f"  [cyan]log:[/cyan]      {record.get('log')}")
    console.print()


def cmd_stop() -> None:
    """Ask a detached server to exit."""
    header("Stop Host API Server")
    console.print()

    try:
        record = host_lifetime.stop()
    except host_lifetime.LifetimeError as e:
        logger.warning("[host_api] stop did not complete: %s", e)
        error(str(e))
        return

    if record is None:
        warning("No detached server was running")
        console.print()
        return

    success(f"Stopped pid {record.get('pid')}")
    console.print()


# =============================================
# DRONE ROUTING
# =============================================


SUBCOMMANDS = {"serve", "status", "stop"}


def handle_command(command: str, args: List[str]) -> bool:
    """
    Claim the server-lifecycle subcommands of `host-api`.

    Args:
        command: The routed command name.
        args: Everything after it, subcommand first.

    Returns:
        True if this module handled it. False means "not mine" — host_api.py
        offers every host-api call here first and owns everything declined, so
        an unknown subcommand still reaches its error message rather than
        disappearing into a silent True.
    """
    # Both spellings, matching host_api.py — `drone @api` bare advertises the
    # MODULE name while the command is host-api, and a surface that publishes a
    # spelling which does not work is the surface's bug.
    if command not in ("host-api", "host_api"):
        return False

    # NO-ARGS GATE and HELP GATE (seedgo standard). host_api.py reaches both
    # first today, so neither fires in practice — they are here because a
    # router that is only correct given its current caller is a trap for the
    # next one. A help flag ANYWHERE means "explain", never "run": checking
    # only args[0] is what once let `cleanup 30 --help` run a real cleanup.
    if not args:
        print_introspection()
        return True

    if any(arg in ("--help", "-h", "help") for arg in args):
        print_introspection()
        return True

    if args[0] not in SUBCOMMANDS:
        return False

    subcommand, rest = args[0], args[1:]

    if subcommand == "serve":
        cmd_serve(rest)
    elif subcommand == "status":
        cmd_status()
    else:
        cmd_stop()

    return True


def print_introspection() -> None:
    """Show what this module answers for."""
    console.print()
    console.print("[bold cyan]host_serve — the host API server's lifecycle[/bold cyan]")
    console.print()
    console.print("  [cyan]host-api serve [--detach][/cyan]  [dim]Run it, here or in its own session[/dim]")
    console.print("  [cyan]host-api status[/cyan]            [dim]Is a detached server up, and where[/dim]")
    console.print("  [cyan]host-api stop[/cyan]              [dim]Ask a detached server to exit[/dim]")
    console.print()
