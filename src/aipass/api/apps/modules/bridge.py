# =================== AIPass ====================
# Name: bridge.py
# Description: Generic contract registry — maps contract names to driver functions
# Version: 1.1.0
# Created: 2026-04-15
# Modified: 2026-11-26
# =============================================
"""Generic contract registry for @api driver layer."""

from typing import Callable

from aipass.prax import logger  # noqa: F401
from aipass.api.apps.handlers.json import json_handler
from aipass.cli import console


def print_introspection() -> None:
    """Show bridge registry introspection."""
    console.print()
    console.print("[bold cyan]Bridge — Contract Registry[/bold cyan]")
    console.print()
    console.print("[cyan]Purpose:[/cyan] [dim]Generic contract registry mapping names to driver functions[/dim]")
    console.print()
    contracts = list_contracts()
    if contracts:
        console.print("[cyan]Registered contracts:[/cyan]")
        for name in contracts:
            console.print(f"  • {name}")
    else:
        console.print("[dim]No contracts registered.[/dim]")
    console.print()
    console.print("Run [green]'drone @api --help'[/green] for usage information")
    console.print()
    json_handler.log_operation("bridge_introspection", {"contracts": contracts})


def print_help() -> None:
    """Show the registry's Python API: bridge has no drone command of its own."""
    console.print()
    console.print("[bold cyan]Bridge — Contract Registry[/bold cyan]")
    console.print()
    console.print("[dim]An in-process registry: a contract name maps to the driver function that serves it.[/dim]")
    console.print("[dim]No drone command; drivers register here and `drone @api integrations` dispatches.[/dim]")
    console.print()
    console.print("[bold]Usage (Python):[/bold]")
    console.print("  register(contract_name, driver_fn)  [dim]Register a driver under a contract name[/dim]")
    console.print("  resolve(contract_name)              [dim]The registered driver, or None[/dim]")
    console.print("  list_contracts()                    [dim]All registered contract names, sorted[/dim]")
    console.print("  clear()                             [dim]Drop every registration (test teardown only)[/dim]")
    console.print()
    console.print("[bold]Examples:[/bold]")
    console.print("  from aipass.api.apps.modules.bridge import register, resolve")
    console.print('  register("search", search_driver)')
    console.print('  driver = resolve("search")')
    console.print()


_registry: dict[str, Callable] = {}


def register(contract_name: str, driver_fn: Callable) -> None:
    """Register a driver function under a contract name."""
    _registry[contract_name] = driver_fn


def resolve(contract_name: str) -> Callable | None:
    """Return the registered driver for contract_name, or None."""
    return _registry.get(contract_name)


def list_contracts() -> list[str]:
    """Return all registered contract names, sorted."""
    return sorted(_registry.keys())


def clear() -> None:
    """Clear all registrations. Intended for test teardown only."""
    _registry.clear()


def handle_command(command: str, args: list) -> bool:
    """Bridge is a utility module — no drone commands. Always returns False.

    Silent: bridge is discovered first, so a print here would prepend its banner to every no-arg command.
    """
    return False
