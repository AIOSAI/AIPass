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
    cmd_status()  - Whether a server is running, who holds it, and where to read it
    cmd_stop()    - Stop the running server through whoever owns it
    cmd_autostart() - Render the boot unit and print the host-side install steps
"""

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
    except host_autostart.SupervisorUnreachable as e:
        logger.warning("[host_api] detach could not reach the supervisor: %s", e)
        error("Cannot start — the supervisor did not answer", suggestion=str(e))
        return
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
    """Say whether a server is running, who holds it, and where to read it."""
    header("Host API Server Status")
    console.print()

    answer = host_lifetime.server_state()

    if answer["state"] == "unknown":
        # NOT "no server". This host runs the server under a unit that writes no
        # record file, so a swallowed probe would print a confident "nothing is
        # running" about a server answering requests.
        error("Cannot tell — the supervisor did not answer", suggestion=answer["reason"])
        console.print()
        console.print(f"[dim]Ask it directly: systemctl --user status {host_autostart.unit_name()}[/dim]")
        console.print(f"[dim]Its output, either way: {host_lifetime.log_path()}[/dim]")
        return

    if answer["state"] == "none":
        warning("No server is running")
        console.print()
        # NOT a restart. A dead server that stays dead and says so is the honest
        # failure — and the answer to "who restarts it" is now systemd, named
        # here so nobody has to find the autostart verb by accident.
        console.print("[dim]Start one now:      drone @api host-api serve --detach[/dim]")
        console.print("[dim]Start one at boot:  drone @api host-api autostart[/dim]")
        console.print(f"[dim]Its last output, if any: {host_lifetime.log_path()}[/dim]")
        return

    _show_server(answer["record"])


def _show_server(record: dict) -> None:
    """
    Print a running server's facts.

    Args:
        record: The live server's record.
    """
    # An unknown bind prints as a word rather than as None. A status line
    # reading "None:None" is a bug report waiting to be filed against the wrong
    # thing.
    bind_host = record.get("host") or "unknown"
    bind_port = record.get("port") or "unknown"

    success(f"Running: {bind_host}:{bind_port}")
    console.print(f"  [cyan]pid:[/cyan]      {record.get('pid')}")

    if record.get("owner") == host_lifetime.OWNER_SUPERVISOR:
        console.print(f"  [cyan]owner:[/cyan]    systemd [dim]({record.get('unit')})[/dim]")
        console.print("  [cyan]restart:[/cyan]  [dim]on failure, and at boot[/dim]")
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
        # Refusing beats signalling into the dark: if a unit IS holding the
        # server, a bare SIGTERM is a stop its restart policy may undo.
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
        # Said plainly, because a supervised stop is the one an operator is
        # entitled to distrust: it is the case where a naive implementation
        # would have been undone seconds later.
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
        # D1 reaches the unit too: an address refused at the CLI must not be
        # baked into something that retries it at every boot forever.
        logger.error("[host_api] bind refused, no unit written: %s", e)
        error("Bind refused — no unit written", suggestion=str(e))
        json_handler.log_operation("host_api_bind_refused", {"reason": str(e)})
        return
    except OSError as e:
        logger.error("[host_api] the unit could not be written: %s", e)
        error(f"The unit could not be written: {e}")
        return

    _show_installation(report)


def _show_installation(report: dict) -> None:
    """
    Print a rendered unit's install steps and what stands in their way.

    Args:
        report: The handler's installation report, including any conflict.
    """
    success(f"Unit rendered: {report['unit']}")
    console.print()
    console.print("[dim]It is NOT installed — these steps run outside this tree, and are yours:[/dim]")
    console.print()

    for step in report["steps"]:
        console.print(f"  [cyan]{step}[/cyan]")

    console.print()

    linger = report["linger"]

    if linger is True:
        console.print("[dim]Lingering is already on for this account — the unit starts at boot without a login.[/dim]")
    elif linger is False:
        # A real warning, routed as one: without the last step the unit waits
        # for a login that a headless reboot never provides, which is the exact
        # failure this build exists to end.
        warning("Lingering is OFF — without the last step the unit waits for a login that a reboot never brings")
    else:
        console.print("[dim]Lingering could not be read — run the last step anyway, it is idempotent.[/dim]")

    # THE TRAP THIS CATCHES, and it is live on this host right now: a
    # hand-started server already holds the port, so `enable --now` starts a
    # unit that cannot bind, exits non-zero, retries its whole window and ends
    # in `failed`. The operator reads that as "autostart is broken" when the
    # actual cause is the server they started themselves this morning.
    conflict = report.get("conflict")

    if conflict is not None:
        console.print()
        warning(f"A hand-started server is on the port now (pid {conflict.get('pid')})")
        console.print("  [dim]Stop it BEFORE 'enable --now', or the unit cannot bind and ends in failed:[/dim]")
        console.print("  [cyan]drone @api host-api stop[/cyan]")

    console.print()


# =============================================
# DRONE ROUTING
# =============================================


SUBCOMMANDS = {"serve", "status", "stop", "autostart"}


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
