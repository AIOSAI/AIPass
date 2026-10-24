# =================== AIPass ====================
# Name: broker.py
# Description: Module orchestrator for the drone-broker daemon
# Version: 1.0.1
# Created: 2026-06-09
# Modified: 2026-10-24
# =============================================

"""Module orchestrator for the drone-broker daemon.

Thin orchestrator that delegates to the broker handler package for
daemon lifecycle, path resolution, and client operations.
"""

from __future__ import annotations

from typing import Optional

from aipass.prax import logger
from aipass.cli.apps.modules import console
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.broker.daemon import BrokerDaemon


def handle_command(command: Optional[str] = None, args: Optional[list[str]] = None) -> bool:
    """Route broker subcommands to handler functions."""
    if not args:
        if command is None:
            print_introspection()
            return True
        args = []
    if command in ("--help", "-h") or (args and args[0] in ("--help", "-h")):
        print_help()
        return True

    json_handler.log_operation("broker_command", {"command": command, "args": args})

    if command == "start":
        return _start_broker()
    if command == "status":
        return _show_status()

    logger.warning("broker: unknown command '%s'", command)
    return False


def _start_broker() -> bool:
    """Start the broker daemon in the foreground."""
    from aipass.drone.apps.handlers.router_handler import find_project_root

    repo_root = find_project_root()
    if not repo_root:
        logger.error("No project root found — cannot start broker")
        return False

    console.print(f"[green]Starting broker (repo root: {repo_root})...[/green]")

    daemon = BrokerDaemon(repo_root=repo_root)
    console.print(f"[green]Listening on {daemon.socket_path}[/green]")
    console.print("[dim]Press Ctrl+C to stop[/dim]")
    try:
        daemon.start()
    except KeyboardInterrupt:
        logger.info("broker: interrupted, stopping")
        daemon.stop()
        console.print("[yellow]Broker stopped[/yellow]")
    return True


def _show_status() -> bool:
    """Show broker status."""
    from aipass.drone.apps.handlers.broker.daemon import _default_socket_path

    sock_path = _default_socket_path()
    if sock_path.exists():
        console.print(f"[green]Broker socket exists:[/green] {sock_path}")
        return True
    console.print(f"No broker socket found at: {sock_path}")
    return True


def print_introspection() -> None:
    """Display module overview (no args)."""
    try:
        from aipass.cli.apps.modules.display import console as c
    except ImportError:
        logger.warning("CLI console not available, using fallback")
        from rich.console import Console

        c = Console()

    c.print()
    c.print("[bold cyan]broker Module[/bold cyan]")
    c.print("[dim]Privileged delete daemon for sandboxed agents.[/dim]")
    c.print()
    c.print("[yellow]Connected Handlers:[/yellow]")
    c.print("  [cyan]handlers/broker/[/cyan]")
    c.print("    - [cyan]daemon.py[/cyan] [dim](BrokerDaemon — unix socket listener + openat2 resolver)[/dim]")
    c.print("    - [cyan]client.py[/cyan] [dim](broker_delete — send requests over inherited fd)[/dim]")
    c.print("    - [cyan]path_resolver.py[/cyan] [dim](resolve_beneath — openat2 RESOLVE_BENEATH)[/dim]")
    c.print("    - [cyan]protocol.py[/cyan] [dim](BrokerRequest/BrokerResponse — typed JSON-line IPC)[/dim]")
    c.print()


def print_help() -> None:
    """Display help (--help flag)."""
    console.print("Usage: drone broker <command>")
    console.print()
    console.print("Privileged delete daemon for sandboxed agents.")
    console.print()
    console.print("[bold]Commands:[/bold]")
    console.print("  [green]start[/green]    Start the broker daemon (foreground)")
    console.print("  [green]status[/green]   Check if the broker socket exists")
    console.print()
    console.print("[bold]Environment:[/bold]")
    console.print("  AIPASS_BROKER_FD   Inherited socket fd (set by launch wrapper)")
    console.print()
    console.print("[bold]Socket:[/bold]  $REPO/.ai_central/drone_broker.sock")
    console.print("[bold]Audit:[/bold]   $REPO/.ai_central/drone_broker_audit.jsonl")
