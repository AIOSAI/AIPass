# =================== AIPass ====================
# Name: api.py
# Description: Entry point CLI for drone @api — external clients, secrets, usage and the host API
# Version: 1.1.2
# Created: 2026-03-08
# Modified: 2026-10-22
# =============================================

"""api Branch - Main Orchestrator"""

import os
import sys
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

import importlib
from typing import Any, List

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.cli.apps.modules import console, header, error, reset_command_state, resolve_exit
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns

from aipass.api.apps.handlers.json import json_handler

MODULE_ROOT = Path(__file__).parent

MODULES_DIR = MODULE_ROOT / "modules"


def discover_modules() -> List[Any]:
    """Auto-discover modules from modules/ directory"""
    modules = []

    if not MODULES_DIR.exists():
        logger.warning(f"Modules directory not found: {MODULES_DIR}")
        return modules

    logger.info(f"[{Path(__file__).stem}] Discovering modules...")

    for file_path in MODULES_DIR.glob("*.py"):
        if file_path.name.startswith("_"):
            continue

        module_name = file_path.stem

        try:
            module = importlib.import_module(f"aipass.api.apps.modules.{module_name}")

            if hasattr(module, "handle_command"):
                modules.append(module)
                logger.info(f"  [+] {module_name}")
            else:
                logger.warning(f"  [!] {module_name} - missing handle_command()")

        except Exception as e:
            logger.error(f"  [-] {module_name} - import error: {e}")

    logger.info(f"[{Path(__file__).stem}] Discovered {len(modules)} modules")
    return modules


def print_introspection():
    """Display discovered modules and available commands"""
    console.print()
    console.print("[bold cyan]API Branch - API Operations[/bold cyan]")
    console.print()
    console.print("[dim]Universal API client and key management[/dim]")
    console.print()

    modules = discover_modules()

    if not modules:
        error("No modules discovered", suggestion="Run 'drone @api --help' for usage information")
        console.print()
        return

    console.print(f"[yellow]Discovered Modules:[/yellow] {len(modules)}")
    console.print()

    for module in modules:
        module_name = module.__name__.split(".")[-1]
        console.print(f"  [cyan]•[/cyan] {module_name}")

    console.print()
    console.print("[dim]Run 'drone @api --help' for usage information[/dim]")
    console.print()


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
    console.print("  [cyan]•[/cyan] OpenRouter API client integration")
    console.print("  [cyan]•[/cyan] API key management and validation")
    console.print("  [cyan]•[/cyan] Model discovery and availability")
    console.print("  [cyan]•[/cyan] Usage tracking and statistics")
    console.print("  [cyan]•[/cyan] Connection testing and diagnostics")
    console.print("  [cyan]•[/cyan] Secret storage per provider, read without printing values")
    console.print("  [cyan]•[/cyan] The Stage 0 host API the BAUD phone talks to")
    console.print()

    console.print("[bold cyan]AVAILABLE COMMANDS:[/bold cyan]")
    console.print()

    table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("Command", style="green")
    table.add_column("Description", style="white")

    table.add_row("get-key", "Retrieve API key for provider")
    table.add_row("get-secret", "Show a masked secret from the keyring")
    table.add_row("secrets migrate", "Import the store files into the keyring [--dry-run]")
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
    table.add_row("integrations", "List or call a registered contract")
    table.add_row(
        "host-api",
        "The phone's server: serve, status, stop, autostart, issue-token, list-tokens,"
        " revoke-token, pair, config, set-config",
    )

    console.print(table)
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()

    usage_examples = [
        "[yellow]Quick Commands:[/yellow]\n  [dim]drone @api get-key[/dim]\n  [dim]drone @api validate[/dim]",
        "[yellow]Testing:[/yellow]\n  [dim]drone @api test[/dim]\n  [dim]drone @api models[/dim]",
        "[yellow]Analytics:[/yellow]\n  [dim]drone @api track[/dim]\n  [dim]drone @api stats[/dim]",
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

    console.print("[bold cyan]EXAMPLES:[/bold cyan]")
    console.print()
    console.print("  [yellow]Credentials:[/yellow]")
    console.print("    [dim]drone @api get-key[/dim]                              [dim]# Show OpenRouter key[/dim]")
    console.print("    [dim]drone @api validate[/dim]                             [dim]# Validate OpenRouter key[/dim]")
    console.print("    [dim]drone @api validate google[/dim]                      [dim]# Validate Google OAuth2[/dim]")
    console.print()
    console.print("  [yellow]Models & calls:[/yellow]")
    console.print("    [dim]drone @api models --all[/dim]                         [dim]# List all models[/dim]")
    console.print('    [dim]drone @api call "Summarize this" --model anthropic/claude-3.5-sonnet[/dim]')
    console.print()
    console.print("  [yellow]Usage tracking:[/yellow]")
    console.print("    [dim]drone @api stats[/dim]                                [dim]# Overall usage stats[/dim]")
    console.print("    [dim]drone @api caller-usage flow[/dim]                    [dim]# Usage by caller[/dim]")
    console.print()
    console.print("  [yellow]The phone's server:[/yellow]")
    console.print("    [dim]drone @api host-api status[/dim]                      [dim]# Up? who holds it?[/dim]")
    console.print("    [dim]drone @api host-api --help[/dim]                      [dim]# Its own subcommands[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print(
        "[dim]Commands: get-key, get-secret, secrets, validate, test, models, status, call,"
        " list-providers, init, track, stats, session, caller-usage, cleanup,"
        " integrations, host-api[/dim]"
    )
    console.print()


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """
    Route command to appropriate module
    """
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except Exception as e:
            logger.error(f"Module error: {e}")

    return False


def main():
    """Main entry point - routes commands to modules"""
    try:
        # error()'s failure flag is process-level: a prior command or an imported
        # branch's error would read as ours. Clear it before anything can set it.
        reset_command_state()

        args = sys.argv[1:]

        if len(args) == 0:
            print_introspection()
            json_handler.log_operation("api_introspection_displayed", {"trigger": "no_args"})
            return 0

        if args[0] in ["--version", "-V"]:
            console.print("API v1.0.0")
            return 0

        if args[0] in ["--help", "-h", "help"]:
            print_help()
            json_handler.log_operation("api_help_displayed", {"trigger": args[0]})
            return 0

        modules = discover_modules()

        if not modules:
            logger.error("No modules found")
            error("No modules found")
            return 1

        command = args[0]
        remaining_args = args[1:] if len(args) > 1 else []

        # A help flag ANYWHERE means explain, never run: checking only args[0] let
        # `get-key <provider> --help` print key material and `cleanup 30 --help` clean.
        if any(arg in ("--help", "-h") for arg in remaining_args):
            for module in modules:
                if module.handle_command(command, ["--help"]):
                    return 0
            print_help()
            return 0

        json_handler.log_operation("api_command_attempted", {"command": command, "modules_discovered": len(modules)})

        # True means "recognised", not "worked"; resolve_exit reads error()'s flag:
        # 1 unrecognised, 2 recognised-and-refused, 0 only when no error printed.
        handled = route_command(command, remaining_args, modules)

        if not handled:
            logger.warning(f"Unknown command: {command}")
            error(f"Unknown command: {command}", suggestion="Run 'drone @api --help' for available commands")

        return resolve_exit(handled)

    except Exception as exc:
        logger.error("[api] Unhandled error in main: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
