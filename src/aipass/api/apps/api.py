# =================== AIPass ====================
# Name: api.py
# Description: Entry point CLI for drone @api — LLM client via OpenRouter
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
api Branch - Main Orchestrator

Modular architecture with auto-discovered modules.
Main handles routing, modules implement functionality.
"""

# INFRASTRUCTURE IMPORT PATTERN
import sys
from pathlib import Path

# Standard library imports
import importlib
from typing import Any, List

# AIPass infrastructure imports
from aipass.prax.apps.modules.logger import system_logger as logger

# CLI services for formatted output
from aipass.cli.apps.modules import console, header, error
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns

# JSON handler for api tracking
from aipass.api.apps.handlers.json import json_handler

# =============================================================================
# CONSTANTS & CONFIG
# =============================================================================

# Module root
MODULE_ROOT = Path(__file__).parent

# Modules directory
MODULES_DIR = MODULE_ROOT / "modules"

# =============================================================================
# MODULE DISCOVERY
# =============================================================================

def discover_modules() -> List[Any]:
    """
    Auto-discover modules from modules/ directory

    Returns:
        List of module objects with handle_command() function
    """
    modules = []

    if not MODULES_DIR.exists():
        logger.warning(f"Modules directory not found: {MODULES_DIR}")
        return modules

    logger.info(f"[{Path(__file__).stem}] Discovering modules...")

    for file_path in MODULES_DIR.glob("*.py"):
        # Skip __init__.py and private files
        if file_path.name.startswith("_"):
            continue

        module_name = file_path.stem

        try:
            # Import module via pip namespace
            module = importlib.import_module(f"aipass.api.apps.modules.{module_name}")

            # Check for required interface
            if hasattr(module, 'handle_command'):
                modules.append(module)
                logger.info(f"  [+] {module_name}")
            else:
                logger.warning(f"  [!] {module_name} - missing handle_command()")

        except Exception as e:
            logger.error(f"  [-] {module_name} - import error: {e}")

    logger.info(f"[{Path(__file__).stem}] Discovered {len(modules)} modules")
    return modules

# =============================================================================
# INTROSPECTION DISPLAY
# =============================================================================

def print_introspection():
    """Display discovered modules and available commands"""
    console.print()
    console.print("[bold cyan]API Branch - API Operations[/bold cyan]")
    console.print()
    console.print("[dim]Universal API client and key management[/dim]")
    console.print()

    # Discover modules
    modules = discover_modules()

    if not modules:
        error("No modules discovered", suggestion="Run 'drone @api --help' for usage information")
        console.print()
        return

    console.print(f"[yellow]Discovered Modules:[/yellow] {len(modules)}")
    console.print()

    for module in modules:
        module_name = module.__name__.split('.')[-1]
        console.print(f"  [cyan]•[/cyan] {module_name}")

    console.print()
    console.print("[dim]Run 'drone @api --help' for usage information[/dim]")
    console.print()


# =============================================================================
# DRONE COMPLIANCE - HELP SYSTEM
# =============================================================================

def print_help():
    """Display Rich-formatted help"""

    console.print()
    header("API Branch - API Operations")
    console.print()

    console.print("[dim]Universal API client and key management system[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]WHAT IS API?[/bold cyan]")
    console.print()
    console.print("API Branch provides:")
    console.print("  [green]✓[/green] OpenRouter API client integration")
    console.print("  [green]✓[/green] API key management and validation")
    console.print("  [green]✓[/green] Model discovery and availability")
    console.print("  [green]✓[/green] Usage tracking and statistics")
    console.print("  [green]✓[/green] Connection testing and diagnostics")
    console.print()

    console.print("[bold cyan]AVAILABLE COMMANDS:[/bold cyan]")
    console.print()

    table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("Command", style="green")
    table.add_column("Description", style="white")

    table.add_row("get-key", "Retrieve API key for provider")
    table.add_row("validate", "Validate API credentials and connection")
    table.add_row("validate google", "Validate Google OAuth2 credentials")
    table.add_row("reauth google", "Re-authenticate Google OAuth2")
    table.add_row("test", "Test OpenRouter connection status")
    table.add_row("models", "List available models from provider")
    table.add_row("status", "Check OpenRouter client status")
    table.add_row("call", "Make API call to model")
    table.add_row("list-providers", "List available API providers")
    table.add_row("init", "Initialize .env template")
    table.add_row("track", "Track API usage metrics")
    table.add_row("stats", "Display API usage statistics")
    table.add_row("session", "Show session usage data")
    table.add_row("caller-usage", "Show usage by caller module")
    table.add_row("cleanup", "Clean up old usage data")

    console.print(table)
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()

    usage_examples = [
        "[yellow]Quick Commands:[/yellow]\n  [dim]drone @api get-key[/dim]\n  [dim]drone @api validate[/dim]",
        "[yellow]Testing:[/yellow]\n  [dim]drone @api test[/dim]\n  [dim]drone @api models[/dim]",
        "[yellow]Analytics:[/yellow]\n  [dim]drone @api track[/dim]\n  [dim]drone @api stats[/dim]"
    ]

    console.print(Columns(usage_examples, equal=True, expand=True))
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]CONFIGURATION:[/bold cyan]")
    console.print()

    config_text = """[bold]API configuration is managed through:[/bold]

  [green]•[/green] Environment variables for credentials
  [green]•[/green] Configuration files in handlers/config/
  [green]•[/green] Provider-specific settings in handlers/"""

    console.print(Panel(config_text, border_style="cyan", padding=(1, 2)))
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[dim]Commands: get-key, validate, test, models, status, call, list-providers, init, track, stats, session, caller-usage, cleanup[/dim]")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """
    Route command to appropriate module

    Args:
        command: Command name (e.g., 'get-key', 'validate')
        args: Additional command arguments
        modules: List of discovered modules

    Returns:
        True if command was handled, False otherwise
    """
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except Exception as e:
            logger.error(f"Module error: {e}")

    return False

# =============================================================================
# MAIN
# =============================================================================

def main():
    """Main entry point - routes commands to modules"""

    # Parse arguments directly from sys.argv
    args = sys.argv[1:]

    # Show introspection when run without arguments
    if len(args) == 0:
        print_introspection()
        json_handler.log_operation("api_introspection_displayed", {"trigger": "no_args"})
        return 0

    # Show version
    if args[0] in ['--version', '-V']:
        console.print("API v1.0.0")
        return 0

    # Show help for explicit help flags
    if args[0] in ['--help', '-h', 'help']:
        print_help()
        json_handler.log_operation("api_help_displayed", {"trigger": args[0]})
        return 0

    # Discover modules
    modules = discover_modules()

    if not modules:
        logger.error("No modules found")
        error("No modules found")
        return 1

    # Extract command and remaining args (matching seedgo pattern)
    command = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    # Log api command attempt
    json_handler.log_operation(
        "api_command_attempted",
        {"command": command, "modules_discovered": len(modules)}
    )

    # Route command to modules
    if route_command(command, remaining_args, modules):
        return 0
    else:
        logger.warning(f"Unknown command: {command}")
        error(f"Unknown command: {command}", suggestion="Run 'drone @api --help' for available commands")
        return 1

if __name__ == "__main__":
    sys.exit(main())
