# =================== AIPass ====================
# Name: integrations_manager.py
# Description: Integrations command module — list and call generic contracts
# Version: 1.0.2
# Created: 2026-04-15
# Modified: 2026-10-22
# =============================================
"""Integrations Module"""

import sys
from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.api.apps.handlers.json import json_handler
from aipass.cli.apps.modules import console, header, error
from aipass.api.apps.modules import registry
from aipass.api.apps.modules.bridge import list_contracts, resolve
from aipass.api.apps.handlers.integrations.list import get_contracts
from aipass.api.apps.handlers.integrations.call import invoke


def _ensure_loaded() -> None:
    """Load drivers on first command invocation."""
    registry.load_drivers()


def print_introspection() -> None:
    """Show module introspection — connected handlers and capabilities."""
    console.print()
    header("Integrations Module Introspection")
    console.print()
    console.print("[cyan]Purpose:[/cyan] Generic contract dispatch for private integration drivers")
    console.print()
    console.print("[cyan]Subcommands:[/cyan]")
    console.print("  • integrations list              — list registered contracts")
    console.print("  • integrations call <name> ...   — invoke a contract driver")
    console.print()
    json_handler.log_operation("integrations_introspection", {})


def print_help() -> None:
    """Print usage help for the integrations command."""
    console.print()
    header("Integrations Module")
    console.print()
    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print("  drone @api integrations list")
    console.print("  drone @api integrations call <contract> \\[args...]")
    console.print()
    console.print("[dim]Drivers live in apps/integrations/{project}/driver.py (gitignored)[/dim]")
    console.print()


def _run_list() -> int:
    """Fetch contracts from bridge, pass to handler, display result."""
    contracts = list_contracts()
    result = get_contracts(contracts)

    console.print()
    header("Integrations — Registered Contracts")
    console.print()

    if not result["contracts"]:
        console.print("[dim]No integrations configured.[/dim]")
        console.print()
        console.print("[dim]Drop a driver in apps/integrations/{project}/driver.py to register one.[/dim]")
        console.print()
        return 0

    for name in result["contracts"]:
        console.print(f"  [cyan]•[/cyan] {name}")
    console.print()
    return 0


def _run_call(contract_name: str, args: List[str]) -> int:
    """Resolve contract from bridge, pass driver to handler, display result."""
    driver_fn = resolve(contract_name)

    if driver_fn is None:
        error(
            f"contract '{contract_name}' not registered",
            suggestion="Configure a driver in apps/integrations/",
        )
        return 1

    result = invoke(driver_fn, contract_name, args)

    if not result["success"]:
        error(f"Driver '{contract_name}' failed: {result['error']}")
        return 1

    if result["result"] is not None:
        # A result is data (JSON, a URL): never wrapped, read as markup or highlighted.
        console.print(result["result"], markup=False, highlight=False, soft_wrap=True)
    return 0


def fetch_contracts() -> dict:
    """Return contract listing result dict. Called from tests/test_integrations.py."""
    return get_contracts(list_contracts())


def call_contract(contract_name: str, args: list) -> dict:
    """Resolve and invoke a contract driver. Called from tests/test_integrations.py."""
    driver_fn = resolve(contract_name)
    if driver_fn is None:
        return {"result": None, "success": False, "error": f"contract '{contract_name}' not registered"}
    return invoke(driver_fn, contract_name, args)


def handle_command(command: str, args: List[str]) -> bool:
    """Handle integrations subcommands."""
    if command != "integrations":
        return False

    try:
        # A help flag anywhere means explain, never dispatch: api.py checks only the first arg, and
        # `call <driver> --help` would run a live driver. Bare "help" counts only first, so it stays an argument.
        if args and (args[0] == "help" or any(arg in ("--help", "-h") for arg in args)):
            print_help()
            return True

        if not args:
            print_introspection()
            return True

        subcommand = args[0]
        sub_args = args[1:]

        if subcommand == "list":
            _ensure_loaded()
            sys.exit(_run_list())

        if subcommand == "call":
            if not sub_args:
                error("Usage: drone @api integrations call <contract> [args...]")
                sys.exit(1)
            _ensure_loaded()
            sys.exit(_run_call(sub_args[0], sub_args[1:]))

        error(f"Unknown integrations subcommand: {subcommand}", suggestion="list, call")
        sys.exit(1)

    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"Error in integrations_manager.handle_command: {e}")
        raise
