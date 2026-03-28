# =================== AIPass ====================
# Name: branch_ping.py
# Description: Branch Ping Orchestration Module
# Version: 1.0.0
# Created: 2025-11-15
# Modified: 2025-11-15
# =============================================

"""
Branch Ping Orchestration Module

Orchestrates branch memory health monitoring - delegates all logic to handlers.
Commands: ping, status, registry, thresholds
"""

import sys
import argparse
from pathlib import Path
from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

# CLI services for formatting
from aipass.cli.apps.modules import console, error
from rich.panel import Panel

# Import handlers
from aipass.ai_mail.apps.handlers.monitoring.memory import count_file_lines, get_status_from_count, get_health_info
from aipass.ai_mail.apps.handlers.registry.update import (
    ping_registry,
    get_branch_context,
    update_json_memory_health
)
from aipass.ai_mail.apps.handlers.json import json_handler

MODULE_NAME = "branch_ping"
THRESHOLDS = {"green": (0, 400), "yellow": (401, 550), "red": (551, float('inf'))}

def handle_ping(verbose: bool = False) -> bool:
    """Execute ping command - orchestrate health check"""
    try:
        branch_name, cwd = get_branch_context()
        local_file = cwd / ".trinity" / "local.json"
        obs_file = cwd / ".trinity" / "observations.json"

        local_count = count_file_lines(local_file)
        obs_count = count_file_lines(obs_file)
        local_status_code = get_status_from_count(local_count)
        obs_status_code = get_status_from_count(obs_count)

        update_json_memory_health(local_file, local_count, local_status_code)
        update_json_memory_health(obs_file, obs_count, obs_status_code)

        local_status = {"line_count": local_count, "status": local_status_code}
        obs_status = {"line_count": obs_count, "status": obs_status_code}
        ping_registry(branch_name, cwd, local_status, obs_status)

        json_handler.log_operation("ping_executed", {"branch": branch_name, "local_count": local_count, "obs_count": obs_count})

        if verbose:
            console.print(f"Ping successful for {branch_name}")
            console.print(f"  .trinity/local.json: {local_count} lines ({local_status_code})")
            console.print(f"  .trinity/observations.json: {obs_count} lines ({obs_status_code})")
        return True
    except Exception as e:
        logger.error(f"Ping failed: {e}")
        if verbose:
            error(f"Ping failed: {e}")
        return False


def handle_status() -> bool:
    """Show current memory health status"""
    try:
        branch_name, cwd = get_branch_context()
        local_file = cwd / ".trinity" / "local.json"
        obs_file = cwd / ".trinity" / "observations.json"

        local_health = get_health_info(local_file)
        obs_health = get_health_info(obs_file)

        console.print(f"\nBranch: {branch_name}\nDirectory: {cwd}")
        console.print(f"\nMemory Health Status:")
        console.print(f"  .trinity/local.json:        {local_health['line_count']} lines ({local_health['status']})")
        console.print(f"  .trinity/observations.json: {obs_health['line_count']} lines ({obs_health['status']})\n")
        return True
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        error(f"Error getting status: {e}")
        return False


def handle_registry() -> bool:
    """View registry contents"""
    try:
        from aipass.ai_mail.apps.handlers.registry.update import REGISTRY_PATH
        from aipass.ai_mail.apps.handlers.registry.load import load_registry

        if not REGISTRY_PATH.exists():
            console.print("Registry not yet created")
            return True

        registry = load_registry(REGISTRY_PATH)

        console.print("\nMemory Health Registry")
        console.print(f"Last Updated: {registry.get('last_updated', 'N/A')}\n")
        stats = registry.get('statistics', {})
        console.print(f"Statistics:")
        console.print(f"  Total Branches: {stats.get('total_branches', 0)}")
        console.print(f"  Green: {stats.get('green_status', 0)}, Yellow: {stats.get('yellow_status', 0)}, Red: {stats.get('red_status', 0)}\n")
        return True
    except Exception as e:
        logger.error(f"Registry read failed: {e}")
        error(f"Error reading registry: {e}")
        return False


def handle_thresholds() -> bool:
    """Show compression thresholds"""
    console.print("\nMemory Compression Thresholds:")
    console.print(f"  Green:  0 - {THRESHOLDS['green'][1]} lines")
    console.print(f"  Yellow: {THRESHOLDS['yellow'][0]} - {THRESHOLDS['yellow'][1]} lines")
    console.print(f"  Red:    {THRESHOLDS['red'][0]}+ lines (compression required)")
    console.print()
    return True


def print_help():
    """Print help output using argparse"""
    parser = argparse.ArgumentParser(
        description='Branch Ping - Memory Health Monitoring Module',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
COMMANDS:
  ping        - Execute health check and update registry
  status      - Show current memory status for this branch
  registry    - View registry contents and statistics
  thresholds  - Show compression thresholds

USAGE:
  drone @ai_mail branch_ping <command>
  drone @ai_mail branch_ping --help

EXAMPLES:
  # Check memory health and update registry
  drone @ai_mail branch_ping ping

  # View current status
  drone @ai_mail branch_ping status

  # View registry
  drone @ai_mail branch_ping registry

  # Show thresholds
  drone @ai_mail branch_ping thresholds
        """
    )
    console.print(parser.format_help())


def handle_command(command: str, args: List[str]) -> bool:
    """Handle incoming command - main orchestration entry point"""
    # Check if this module handles this command
    if command not in ["ping", "status", "registry", "thresholds"]:
        return False

    # Handle help flag
    if args and args[0] in ['--help', '-h', 'help']:
        print_help()
        return True

    if not args:
        print_introspection()
        return True

    if command == "ping":
        return handle_ping("--verbose" in args or "-v" in args)
    elif command == "status":
        return handle_status()
    elif command == "registry":
        return handle_registry()
    elif command == "thresholds":
        return handle_thresholds()
    return False


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("branch_ping Module")
    console.print("Orchestrates branch memory health monitoring: ping, status, registry, and thresholds.")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/monitoring/")
    console.print("    - memory.py (count_file_lines — count lines in a memory file)")
    console.print("    - memory.py (get_status_from_count — derive health status from line count)")
    console.print("  handlers/registry/")
    console.print("    - update.py (ping_registry — update memory health registry for a branch)")
    console.print("    - update.py (get_branch_context — resolve current branch name and directory)")
    console.print("    - update.py (update_json_memory_health — write health metadata into memory file)")
    console.print("    - load.py (load_registry — load the memory health registry file)")
    console.print("  handlers/json_utils/")
    console.print("    - json_handler.py (log_operation — log structured operation to JSON)")
    console.print()


if __name__ == "__main__":
    # Handle --help flag
    if len(sys.argv) > 1 and sys.argv[1] in ['--help', '-h', 'help']:
        console.print()
        console.print(Panel("[bold cyan]BRANCH PING - Memory Health Monitoring[/bold cyan]", expand=False))
        console.print()
        console.print("[yellow]Commands:[/yellow] ping, status, registry, thresholds, --help")
        console.print()
        console.print("[bold]USAGE:[/bold]")
        console.print("  drone @ai_mail branch_ping <command>")
        console.print("  drone @ai_mail branch_ping --help")
        console.print()
        console.print("[bold]COMMANDS:[/bold]")
        console.print("  [cyan]ping[/cyan]        - Execute health check")
        console.print("  [cyan]status[/cyan]      - Show current memory status")
        console.print("  [cyan]registry[/cyan]    - View registry contents")
        console.print("  [cyan]thresholds[/cyan]  - Show compression thresholds")
        console.print()
        sys.exit(0)

    console.print()
    console.print(Panel("[bold cyan]BRANCH PING ORCHESTRATION MODULE[/bold cyan]", expand=False))
    console.print()
    console.print("[yellow]Commands:[/yellow] ping, status, registry, thresholds")
    console.print("[dim]Usage: drone @ai_mail branch_ping [command][/dim]")
    console.print()
