# =================== AIPass ====================
# Name: usage_tracker.py
# Description: Usage Tracking Module
# Version: 1.0.0
# Created: 2025-11-15
# Modified: 2025-11-15
# =============================================

"""
Usage Tracking Module

Orchestrates API usage monitoring operations:
- Track generation usage
- Display statistics
- Session summaries
- Cleanup old data
"""

import sys
from pathlib import Path

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
    """Print module help with argparse"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="drone @api",
        description="Usage Tracker - Monitor API usage and costs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
COMMANDS:
  track            - Track API usage
  stats            - Show usage statistics
  session          - Show session data
  caller-usage     - Show usage by caller
  cleanup          - Clean up old usage data

USAGE:
  drone @api track <caller>
  drone @api stats
  drone @api session
  drone @api caller-usage <caller>
  drone @api cleanup [days]

ARGUMENTS:
  caller - Caller identifier
  days - Number of days to retain (default: 30)

EXAMPLES:
  # Track usage for a caller
  drone @api track my_application

  # Show usage statistics
  drone @api stats

  # Show session data
  drone @api session

  # Show usage for specific caller
  drone @api caller-usage my_application

  # Cleanup data older than 60 days
  drone @api cleanup 60
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # track command
    track_parser = subparsers.add_parser("track", help="Track API usage")
    track_parser.add_argument("caller", help="Caller identifier")

    # stats command
    subparsers.add_parser("stats", help="Show usage statistics")

    # session command
    subparsers.add_parser("session", help="Show session data")

    # caller-usage command
    caller_parser = subparsers.add_parser("caller-usage", help="Show usage by caller")
    caller_parser.add_argument("caller", help="Caller identifier")

    # cleanup command
    cleanup_parser = subparsers.add_parser("cleanup", help="Clean up old usage data")
    cleanup_parser.add_argument(
        "days",
        nargs="?",
        default=str(DEFAULT_RETENTION_DAYS),
        help=f"Days to retain (default: {DEFAULT_RETENTION_DAYS})",
    )

    console.print(parser.format_help())


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

        # Help gate
        if args and args[0] in ("--help", "-h", "help"):
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
        success(
            f"Tracked: {metrics.get('tokens_prompt', 0)} prompt + {metrics.get('tokens_completion', 0)} completion tokens, ${metrics.get('total_cost', 0):.6f}"
        )
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
        console.print()
        console.print(f"[red]Unknown command: {command}[/red]")
        console.print()
        console.print("Run [dim]drone @api --help[/dim] for available commands")
        console.print()
        sys.exit(1)
