# =================== AIPass ====================
# Name: activity_report.py
# Description: Branch Activity Report Generator Module
# Version: 0.2.0
# Created: 2026-01-30
# Modified: 2026-03-08
# =============================================

"""
Branch Activity Report Generator Module

Orchestrates monitoring handlers to generate comprehensive activity reports.
Provides formatted CLI output and programmatic JSON access.

This is a MODULE (orchestration layer) that coordinates:
- activity_collector: Scans branches for file modifications
- memory_health: Checks memory file health status
- red_flag_detector: Detects presence violations (code changed but memory not updated)
"""

from typing import Dict, Any, List

from aipass.prax import logger
# logger imported from aipass.prax

from aipass.cli.apps.modules import console, error
from aipass.daemon.apps.handlers.json import json_handler

# Import report generation handler (implementation lives in handler layer)
from aipass.daemon.apps.handlers.monitoring.report_generator import (
    generate_activity_report,
    generate_branch_report,
    get_json_report,
)


# =============================================
# CONSTANTS
# =============================================

MODULE_NAME = "activity_report"


# =============================================
# INTROSPECTION
# =============================================

def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("activity_report Module")
    console.print("Branch activity report generator — monitors file changes, memory health, and presence violations")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/monitoring/")
    console.print("    - report_generator.py (generate_activity_report, generate_branch_report, get_json_report — report generation and JSON output)")
    console.print()


# =============================================
# COMMAND INTEGRATION (AUTO-DISCOVERY)
# =============================================

def _print_activity_help() -> None:
    """Display help for the activity command."""
    console.print()
    console.print("=" * 60)
    console.print("ACTIVITY - Quick Activity Summary")
    console.print("=" * 60)
    console.print()
    console.print("USAGE:")
    console.print("  drone @daemon activity")
    console.print("  daemon activity")
    console.print("  daemon activity --hours 48")
    console.print()
    console.print("DESCRIPTION:")
    console.print("  Quick 24-hour activity summary (default).")
    console.print("  Shows branch status, red flags, and recommendations.")
    console.print()
    console.print("OPTIONS:")
    console.print("  --hours N, -t N    Time window in hours (default: 24)")
    console.print("  --help, -h         Show this help message")
    console.print()


def _print_activity_report_help() -> None:
    """Display help for the activity-report command."""
    console.print()
    console.print("=" * 60)
    console.print("ACTIVITY-REPORT - Full Detailed Report")
    console.print("=" * 60)
    console.print()
    console.print("USAGE:")
    console.print("  drone @daemon activity-report")
    console.print("  daemon activity-report")
    console.print("  daemon activity-report --hours 48")
    console.print("  daemon activity-report --json")
    console.print()
    console.print("DESCRIPTION:")
    console.print("  Full detailed activity report with file-level changes.")
    console.print("  Includes per-branch breakdown and complete recommendations.")
    console.print()
    console.print("OPTIONS:")
    console.print("  --hours N, -t N    Time window in hours (default: 24)")
    console.print("  --json, -j         Output raw JSON data")
    console.print("  --help, -h         Show this help message")
    console.print()


def _print_branch_health_help() -> None:
    """Display help for the branch-health command."""
    console.print()
    console.print("=" * 60)
    console.print("BRANCH-HEALTH - Single Branch Deep Dive")
    console.print("=" * 60)
    console.print()
    console.print("USAGE:")
    console.print("  drone @daemon branch-health DRONE")
    console.print("  daemon branch-health FLOW")
    console.print("  daemon branch-health SEED --hours 48")
    console.print()
    console.print("DESCRIPTION:")
    console.print("  Deep dive report for a single branch.")
    console.print("  Shows all file changes, memory health, and specific recommendations.")
    console.print()
    console.print("OPTIONS:")
    console.print("  <branch_name>      Required - branch name (e.g., DRONE, FLOW, SEED)")
    console.print("  --hours N, -t N    Time window in hours (default: 24)")
    console.print("  --help, -h         Show this help message")
    console.print()


def _parse_hours_arg(args: List[str]) -> float:
    """
    Extract --hours or -t argument from args list.

    Args:
        args: Command arguments list.

    Returns:
        Hours value (default 24 if not specified).
    """
    hours = 24.0
    i = 0
    while i < len(args):
        if args[i] in ('--hours', '-t') and i + 1 < len(args):
            try:
                hours = float(args[i + 1])
            except ValueError:
                pass
            i += 2
        else:
            i += 1
    return hours


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle activity monitoring commands via auto-discovery.

    Routes commands to appropriate report generation functions.

    Commands:
        - activity: Quick activity summary (verbosity="normal", last 24h)
        - activity-report: Full detailed report (verbosity="detailed")
        - branch-health <branch>: Single branch deep dive

    Args:
        command: Command name (e.g., 'update', 'activity-report', 'branch-health')
        args: Additional arguments (e.g., ['--hours', '48'])

    Returns:
        True if command was handled, False if not our command.
    """
    # Handle 'activity_report' as alias — help shows module name, users expect it to work
    if command == "activity_report":
        if args and args[0] in ('--help', '-h', 'help'):
            print_introspection()
            return True
        json_handler.log_operation("activity_report", {"command": command})
        hours = _parse_hours_arg(args)
        report = generate_activity_report(since_hours=hours, verbosity="normal")
        console.print(report)
        return True

    # Handle 'activity' command - quick summary (runs with no args, defaults to 24h)
    if command == "activity":
        if args and args[0] in ('--help', '-h', 'help'):
            _print_activity_help()
            return True

        json_handler.log_operation("activity_report", {"command": command})
        hours = _parse_hours_arg(args)
        report = generate_activity_report(since_hours=hours, verbosity="normal")
        console.print(report)
        return True

    # Handle 'activity-report' command - detailed report (runs with no args, defaults to 24h)
    if command == "activity-report":
        if args and args[0] in ('--help', '-h', 'help'):
            _print_activity_report_help()
            return True

        json_handler.log_operation("activity_report", {"command": command})
        hours = _parse_hours_arg(args)

        # Check for --json flag
        if '--json' in args or '-j' in args:
            import json
            data = get_json_report(hours)
            console.print(json.dumps(data, indent=2))
        else:
            report = generate_activity_report(since_hours=hours, verbosity="detailed")
            console.print(report)
        return True

    # Handle 'branch-health' command - requires branch name arg
    if command == "branch-health":
        if not args:
            print_introspection()
            return True
        if args[0] in ('--help', '-h', 'help'):
            _print_branch_health_help()
            return True

        # Extract branch name (first non-flag argument)
        branch_name = None
        filtered_args = []
        i = 0
        while i < len(args):
            if args[i] in ('--hours', '-t') and i + 1 < len(args):
                filtered_args.extend([args[i], args[i + 1]])
                i += 2
            elif args[i].startswith('-'):
                i += 1
            else:
                if branch_name is None:
                    branch_name = args[i]
                i += 1

        if not branch_name:
            error("branch-health requires a branch name")
            console.print()
            console.print("Usage: branch-health <branch_name> [--hours N]")
            console.print("Example: branch-health DRONE")
            return True

        hours = _parse_hours_arg(args)
        report = generate_branch_report(branch_name, since_hours=hours)
        console.print(report)
        return True

    # Not our command
    return False


# =============================================
# CLI ENTRY POINT
# =============================================

def main() -> None:
    """Main entry point for direct execution."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Branch Activity Report Generator"
    )
    parser.add_argument(
        "--hours", "-t",
        type=float,
        default=24,
        help="Time window in hours (default: 24)"
    )
    parser.add_argument(
        "--verbosity", "-v",
        choices=["brief", "normal", "detailed"],
        default="normal",
        help="Report detail level (default: normal)"
    )
    parser.add_argument(
        "--branch", "-b",
        type=str,
        default=None,
        help="Generate report for specific branch"
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output raw JSON data"
    )

    args = parser.parse_args()

    if args.json:
        import json
        data = get_json_report(args.hours)
        console.print(json.dumps(data, indent=2))
    elif args.branch:
        report = generate_branch_report(args.branch, args.hours)
        console.print(report)
    else:
        report = generate_activity_report(args.hours, args.verbosity)
        console.print(report)


if __name__ == "__main__":
    main()
