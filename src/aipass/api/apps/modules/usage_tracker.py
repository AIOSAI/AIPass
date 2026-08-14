# =================== AIPass ====================
# Name: usage_tracker.py
# Description: Usage Tracking Module
# Version: 1.0.1
# Created: 2025-11-15
# Modified: 2026-08-11
# =============================================

"""
Usage Tracking Module

Orchestrates API usage monitoring operations:
- Track generation usage
- Display statistics
- Session summaries
- Cleanup old data
"""

import os
import sys
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from typing import List
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, header, success, error, warning
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.usage import tracking, aggregation, cleanup
from aipass.api.apps.handlers.usage.cleanup import DEFAULT_RETENTION_DAYS


def print_introspection():
    """Show module introspection - connected handlers and capabilities"""
    console.print()
    header("Usage Tracker Module Introspection")
    console.print()

    console.print("[cyan]Purpose:[/cyan] API usage monitoring and cost tracking")
    console.print()

    console.print("[cyan]Connected Handlers:[/cyan]")
    console.print("  • api.apps.handlers.usage.tracking")
    console.print("  • api.apps.handlers.usage.aggregation")
    console.print("  • api.apps.handlers.usage.cleanup")
    console.print("  • api.apps.handlers.json.json_handler")
    console.print()

    console.print("[cyan]Available Workflows:[/cyan]")
    console.print("  • track_usage() - Track usage")
    console.print("  • show_stats() - Show statistics")
    console.print("  • show_session() - Show session")
    console.print("  • show_caller_usage() - Caller stats")
    console.print("  • cleanup_data() - Clean old data")
    console.print()


def print_help():
    """Print drone-compliant help output with Rich markup"""
    console.print()
    console.print("[bold cyan]USAGE_TRACKER — Monitor API usage and costs[/bold cyan]")
    console.print()
    console.print("[yellow]COMMANDS:[/yellow]")
    console.print("  [cyan]track[/cyan]         [dim]Track API usage[/dim]")
    console.print("  [cyan]stats[/cyan]         [dim]Show usage statistics[/dim]")
    console.print("  [cyan]session[/cyan]       [dim]Show session data[/dim]")
    console.print("  [cyan]caller-usage[/cyan]  [dim]Show usage by caller[/dim]")
    console.print("  [cyan]cleanup[/cyan]       [dim]Clean up old usage data[/dim]")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [cyan]drone @api track[/cyan] <caller>")
    console.print("  [cyan]drone @api stats[/cyan]")
    console.print("  [cyan]drone @api session[/cyan]")
    console.print("  [cyan]drone @api caller-usage[/cyan] <caller>")
    console.print("  [cyan]drone @api cleanup[/cyan] \\[days]")
    console.print()
    console.print("[yellow]ARGUMENTS:[/yellow]")
    console.print("  [cyan]caller[/cyan]  [dim]Caller identifier[/dim]")
    console.print("  [cyan]days[/cyan]    [dim]Number of days to retain (default: 30)[/dim]")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]# Track usage for a caller[/dim]")
    console.print("  [cyan]drone @api track my_application[/cyan]")
    console.print()
    console.print("  [dim]# Show usage statistics[/dim]")
    console.print("  [cyan]drone @api stats[/cyan]")
    console.print()
    console.print("  [dim]# Show session data[/dim]")
    console.print("  [cyan]drone @api session[/cyan]")
    console.print()
    console.print("  [dim]# Show usage for specific caller[/dim]")
    console.print("  [cyan]drone @api caller-usage my_application[/cyan]")
    console.print()
    console.print("  [dim]# Cleanup data older than 60 days[/dim]")
    console.print("  [cyan]drone @api cleanup 60[/cyan]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle usage tracking commands

    Args:
        command: Command name
        args: Command arguments

    Returns:
        True if command was handled, False otherwise
    """
    try:
        if command not in ["track", "stats", "session", "caller-usage", "cleanup"]:
            return False

        # Help gate — a help flag ANYWHERE means "explain", never "execute".
        # api.py's guard only inspects the first arg after the command, so
        # `cleanup 30 --help` arrives here with args[0] == "30"; parsing that
        # as a retention window ran a real, data-deleting cleanup.
        # Bare "help" is only a flag in first position, so it stays usable as
        # a caller name in `track <id> help`.
        if args and (args[0] == "help" or any(arg in ("--help", "-h") for arg in args)):
            print_help()
            return True

        # Log operation
        json_handler.log_operation(f"usage_{command}", {"command": command})

        # Route all commands before introspection gate
        if command == "stats":
            show_stats()
            return True
        if command == "session":
            show_session()
            return True
        if command == "track":
            track_usage(args)
            return True
        if command == "caller-usage":
            show_caller_usage(args)
            return True
        if command == "cleanup":
            cleanup_data(args)
            return True

        # NO-ARGS GATE (seedgo standard) — only for unrecognized subcommands
        if not args:
            print_introspection()
            return True

        return True
    except Exception as e:
        logger.error(f"Error in usage_tracker.handle_command: {e}")
        raise


def track_usage(args: List[str]):
    """Orchestrate usage tracking workflow"""
    header("Track API Usage")
    console.print()

    if not args:
        error("Generation ID required", suggestion="drone @api track <generation_id> [caller]")
        return

    generation_id = args[0]
    caller = args[1] if len(args) > 1 else "manual"

    console.print(f"[dim]Tracking generation {generation_id}...[/dim]")

    result = tracking.track_usage(generation_id, caller)

    if result.get("success"):
        metrics = result.get("metrics", {})
        prompt_t = metrics.get("tokens_prompt", 0)
        comp_t = metrics.get("tokens_completion", 0)
        cost = metrics.get("total_cost", 0)
        success(f"Tracked: {prompt_t} prompt + {comp_t} completion tokens, ${cost:.6f}")
    else:
        error(f"Tracking failed: {result.get('error', 'unknown')}")


def show_stats():
    """Orchestrate overall statistics display workflow (aggregate across all callers)"""
    header("Usage Statistics")
    console.print()

    stats = aggregation.get_overall_stats()

    if stats:
        console.print(f"  Total Requests: {stats.get('total_requests', 0)}")
        console.print(f"  Total Cost: ${stats.get('total_cost', 0.0):.6f}")
        console.print(f"  Total Tokens: {stats.get('total_tokens', 0)}")
        console.print(f"  Callers: {stats.get('callers', 0)}")
        models = stats.get("models_used", [])
        if models:
            console.print(f"  Models Used: {', '.join(models)}")
    else:
        warning("No usage data available")


def show_session():
    """Orchestrate session summary workflow"""
    header("Session Summary")
    console.print()

    # Call handler for session data
    summary = aggregation.get_session_summary()

    if summary:
        console.print(f"  Session Requests: {summary.get('total_requests', 0)}")
        console.print(f"  Session Cost: ${summary.get('total_cost', 0.0):.6f}")
        console.print(f"  Session Tokens: {summary.get('total_tokens', 0)}")
    else:
        warning("No session data available")


def show_caller_usage(args: List[str]):
    """Orchestrate caller usage display workflow"""
    if not args:
        error("Caller name required")
        return

    caller = args[0]

    header(f"Usage for Caller: {caller}")
    console.print()

    # Call handler for caller stats
    usage = aggregation.get_caller_usage(caller)

    if usage:
        console.print(f"  Requests: {usage.get('requests', 0)}")
        console.print(f"  Total Cost: ${usage.get('total_cost', 0.0):.6f}")
        console.print(f"  Total Tokens: {usage.get('total_tokens', 0)}")
    else:
        warning(f"No usage data found for caller: {caller}")


def cleanup_data(args: List[str]):
    """Orchestrate cleanup workflow"""
    days = int(args[0]) if args else DEFAULT_RETENTION_DAYS

    header(f"Cleanup Old Data (retain {days} days)")
    console.print()

    # Call handler for cleanup
    # Navigate: usage_tracker.py -> modules/ -> apps/ -> api/
    API_JSON_DIR = Path(__file__).resolve().parent.parent.parent / "api_json"
    data_path = API_JSON_DIR / "usage_tracker_data.json"

    if not data_path.exists():
        warning("No usage data file found — nothing to clean")
        return

    removed = cleanup.cleanup_old_data(data_path, days)

    if removed > 0:
        success(f"Cleaned up {removed} entries older than {days} days")

        # Fire trigger event
        try:
            from aipass.trigger.apps.modules.core import trigger

            trigger.fire("usage_data_cleaned", days=days, data_path=str(data_path))
        except ImportError:
            logger.warning("Trigger module not available — skipping event fire")
    else:
        success(f"Nothing to clean — no entries older than {days} days")


if __name__ == "__main__":
    """Standalone execution mode"""
    args = sys.argv[1:]

    # Show introspection when run without arguments
    if len(args) == 0:
        print_introspection()
        sys.exit(0)

    # Show help for explicit help flags
    if args[0] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    # Execute command
    command = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    if handle_command(command, remaining_args):
        sys.exit(0)
    else:
        error(f"Unknown command: {command}", suggestion="Run 'drone @api --help' for available commands")
        sys.exit(1)
