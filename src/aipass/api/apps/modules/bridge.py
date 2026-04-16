# =================== AIPass ====================
# Name: bridge.py
# Description: Generic contract registry — maps contract names to driver functions
# Version: 1.0.0
# Created: 2026-04-15
# Modified: 2026-04-15
# =============================================
"""
Generic contract registry for @api driver layer.

Contracts are string names (e.g. "memory", "search") that map to driver functions.
Drivers register themselves; callers resolve by name.
Bridge itself is stateless beyond the registry dict — no threading, no startup side effects.
"""

from typing import Callable

from aipass.api.apps.handlers.json import json_handler
from aipass.cli.apps.modules import console, header


def print_introspection() -> None:
    """Show bridge registry introspection."""
    console.print()
    header("Bridge — Contract Registry")
    console.print()
    console.print("[cyan]Purpose:[/cyan] Generic contract registry mapping names to driver functions")
    console.print()
    contracts = list_contracts()
    if contracts:
        console.print("[cyan]Registered contracts:[/cyan]")
        for name in contracts:
            console.print(f"  • {name}")
    else:
        console.print("[dim]No contracts registered.[/dim]")
    console.print()
    json_handler.log_operation("bridge_introspection", {"contracts": contracts})


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
