
# ===================AIPASS====================
# META DATA HEADER
# Name: activity_report.py - Branch Activity Report Generator Module
# Date: 2026-01-30
# Version: 0.1.0
# Category: daemon/modules
#
# CHANGELOG (Max 5 entries):
#   - v0.1.0 (2026-01-30): Initial implementation - FPLAN-0266 Phase 3
#
# CODE STANDARDS:
#   - Module orchestrates handlers - handlers implement logic
#   - Plain text CLI output (no Rich colors for this module)
#   - Type hints on all functions
#   - Standard library only + handler imports
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

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import logging
logger = logging.getLogger(__name__)

# Import monitoring handlers using absolute imports
from aipass.daemon.apps.handlers.monitoring import activity_collector
from aipass.daemon.apps.handlers.monitoring import memory_health
from aipass.daemon.apps.handlers.monitoring import red_flag_detector


# =============================================
# CONSTANTS
# =============================================

MODULE_NAME = "activity_report"

# Status symbols for CLI output
SYMBOL_OK = "[OK]"
SYMBOL_WARNING = "[!]"
SYMBOL_RED = "[X]"
SYMBOL_INACTIVE = "[-]"


# =============================================
# HELPER FUNCTIONS
# =============================================

def _format_time_ago(iso_timestamp: Optional[str]) -> str:
    """
    Format an ISO timestamp as human-readable time ago.

    Args:
        iso_timestamp: ISO format timestamp string or None.

    Returns:
        Human-readable string like "2h ago" or "3d ago".
    """
    if not iso_timestamp:
        return "never"

    try:
        dt = datetime.fromisoformat(iso_timestamp)
        delta = datetime.now() - dt

        hours = delta.total_seconds() / 3600
        if hours < 1:
            minutes = int(delta.total_seconds() / 60)
            return f"{minutes}m ago"
        elif hours < 24:
            return f"{int(hours)}h ago"
        else:
            days = int(hours / 24)
            return f"{days}d ago"
    except (ValueError, TypeError):
        return "unknown"


def _get_status_symbol(status: str) -> str:
    """
    Get CLI symbol for a status code.

    Args:
        status: Status string (OK, WARNING, RED, NO_ACTIVITY, RED_FLAG, ERROR).

    Returns:
        ASCII symbol for display.
    """
    status_upper = status.upper()
    if status_upper in ("OK",):
        return SYMBOL_OK
    elif status_upper in ("WARNING",):
        return SYMBOL_WARNING
    elif status_upper in ("RED", "RED_FLAG", "ERROR"):
        return SYMBOL_RED
    else:
        return SYMBOL_INACTIVE


def _box_header(title: str, width: int = 50) -> str:
    """Generate a boxed header line."""
    return "=" * width + "\n" + title + "\n" + "=" * width


def _section_header(title: str) -> str:
    """Generate a section header line."""
    return f"\n{title}\n" + "-" * len(title)


# =============================================
# DATA AGGREGATION
# =============================================

def _aggregate_data(since_hours: float = 24) -> Dict[str, Any]:
    """
    Aggregate data from all monitoring handlers.

    Args:
        since_hours: Time window in hours to analyze.

    Returns:
        Dict with combined data from all handlers.
    """
    since_timestamp = datetime.now() - timedelta(hours=since_hours)

    # Get red flag summary (includes all branch statuses)
    red_flag_summary = red_flag_detector.get_red_flag_summary(since_timestamp)

    # Get activity data
    activity_data = activity_collector.get_all_branch_activity(since_timestamp)

    # Get memory health for each branch
    branch_paths = activity_collector.get_branch_paths()
    memory_health_data = {}

    for branch_info in branch_paths:
        name = branch_info.get("name", "")
        path = branch_info.get("path", "")
        if name and path:
            health = memory_health.get_memory_health_status(path, name)
            memory_health_data[name] = health

    return {
        "timestamp": datetime.now().isoformat(),
        "time_window_hours": since_hours,
        "red_flag_summary": red_flag_summary,
        "activity_data": activity_data,
        "memory_health": memory_health_data,
    }


# =============================================
# REPORT GENERATION
# =============================================

def generate_activity_report(
    since_hours: float = 24,
    verbosity: str = "normal"
) -> str:
    """
    Generate a formatted CLI-ready activity report.

    Aggregates data from all monitoring handlers and produces a
    human-readable report with branch status, red flags, and recommendations.

    Args:
        since_hours: Time window in hours to analyze (default: 24).
        verbosity: Report detail level - "brief", "normal", or "detailed".

    Returns:
        Formatted string report suitable for CLI display.
    """
    data = _aggregate_data(since_hours)

    red_flags = data["red_flag_summary"]
    activity = data["activity_data"]
    health_data = data["memory_health"]

    lines: List[str] = []

    # Header
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append(_box_header(f"BRANCH ACTIVITY REPORT - {timestamp}\nTime window: Last {since_hours:.0f} hours"))

    # Summary section
    total_branches = red_flags.get("total_branches", 0)
    active_branches = red_flags.get("ok", 0)
    red_flag_count = red_flags.get("red_flags", 0)
    no_activity_count = red_flags.get("no_activity", 0)
    error_count = red_flags.get("errors", 0)

    # Count memory health statuses
    health_ok = sum(1 for h in health_data.values() if h.get("overall_status") == "OK")
    health_warning = sum(1 for h in health_data.values() if h.get("overall_status") == "WARNING")
    health_red = sum(1 for h in health_data.values() if h.get("overall_status") == "RED")

    lines.append(_section_header("SUMMARY"))
    lines.append(f"Active branches: {active_branches}/{total_branches}")
    lines.append(f"RED FLAGS: {red_flag_count}")
    lines.append(f"Memory health: {health_ok} OK, {health_warning} warning, {health_red} red")
    if error_count > 0:
        lines.append(f"Scan errors: {error_count}")

    # Red Flags section
    lines.append(_section_header("RED FLAGS (requires attention)"))
    violations = red_flags.get("violations", [])
    if violations:
        for v in violations:
            branch = v.get("branch_name", "UNKNOWN")
            reason = v.get("reason", "Unknown reason")
            code_count = v.get("code_change_count", 0)
            lines.append(f"  {SYMBOL_RED} {branch}")
            lines.append(f"      Reason: {reason}")
            lines.append(f"      Code changes: {code_count} files")
    else:
        lines.append("  [None - all active branches updated memories]")

    # Branch Status section
    lines.append(_section_header("BRANCH STATUS"))

    all_branches = red_flags.get("all_branches", [])

    if verbosity == "brief":
        # Just counts, no individual branches
        pass
    else:
        for branch_status in all_branches:
            name = branch_status.get("branch_name", "UNKNOWN")
            status = branch_status.get("status", "UNKNOWN")
            reason = branch_status.get("reason", "")

            # Get memory health for this branch
            branch_health = health_data.get(name, {})
            mem_status = branch_health.get("overall_status", "UNKNOWN")

            symbol = _get_status_symbol(status)

            # Format status line
            if status == "NO_ACTIVITY":
                lines.append(f"  {SYMBOL_INACTIVE} {name} - inactive (no changes)")
            elif status == "RED_FLAG":
                lines.append(f"  {SYMBOL_RED} {name} - RED FLAG: {reason}")
            elif status == "ERROR":
                lines.append(f"  {SYMBOL_RED} {name} - ERROR: {reason}")
            else:
                # Get memory update time
                mem_update = branch_status.get("memory_last_update")
                time_ago = _format_time_ago(mem_update)

                mem_symbol = _get_status_symbol(mem_status)
                if mem_status == "OK":
                    lines.append(f"  {SYMBOL_OK} {name} - OK (memory updated {time_ago})")
                else:
                    lines.append(f"  {SYMBOL_WARNING} {name} - {mem_status} (memory updated {time_ago})")

            # Detailed mode: show file changes
            if verbosity == "detailed" and status != "NO_ACTIVITY":
                code_changes = branch_status.get("code_changes", [])
                memory_modified = branch_status.get("memory_files_modified", [])

                if code_changes:
                    lines.append(f"      Code files: {len(code_changes)}")
                    for cf in code_changes[:5]:
                        lines.append(f"        - {cf.get('file', 'unknown')}")
                    if len(code_changes) > 5:
                        lines.append(f"        ... and {len(code_changes) - 5} more")

                if memory_modified:
                    lines.append(f"      Memory files: {len(memory_modified)}")
                    for mf in memory_modified[:3]:
                        lines.append(f"        - {mf.get('file', 'unknown')}")

    # Recommendations section
    lines.append(_section_header("RECOMMENDATIONS"))
    recommendations: List[str] = []

    # Add recommendations for red flags
    for v in violations:
        branch = v.get("branch_name", "UNKNOWN")
        recommendations.append(f"- {branch}: Update memory files to reflect code changes")

    # Add recommendations for warning health status
    for name, health in health_data.items():
        if health.get("overall_status") == "WARNING":
            issues = health.get("issues", [])
            if issues:
                recommendations.append(f"- {name}: {issues[0]}")
        elif health.get("overall_status") == "RED":
            issues = health.get("issues", [])
            if issues:
                recommendations.append(f"- {name}: URGENT - {issues[0]}")

    if recommendations:
        for rec in recommendations[:10]:  # Limit to 10 recommendations
            lines.append(f"  {rec}")
        if len(recommendations) > 10:
            lines.append(f"  ... and {len(recommendations) - 10} more")
    else:
        lines.append("  [None - system healthy]")

    lines.append("")  # Trailing newline

    return "\n".join(lines)


def generate_branch_report(
    branch_name: str,
    since_hours: float = 24
) -> str:
    """
    Generate a detailed report for a single branch.

    Provides a deep dive on one branch including all file changes,
    memory status, and specific recommendations.

    Args:
        branch_name: Name of the branch (uppercase, e.g., "DRONE").
        since_hours: Time window in hours to analyze.

    Returns:
        Formatted string report for the specified branch.
    """
    since_timestamp = datetime.now() - timedelta(hours=since_hours)

    # Find the branch path
    branch_paths = activity_collector.get_branch_paths()
    branch_path = None
    for bp in branch_paths:
        if bp.get("name", "").upper() == branch_name.upper():
            branch_path = bp.get("path")
            branch_name = bp.get("name", branch_name)  # Use canonical name
            break

    if not branch_path:
        return f"ERROR: Branch '{branch_name}' not found in registry."

    lines: List[str] = []

    # Header
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append(_box_header(f"BRANCH REPORT: {branch_name}\n{timestamp} | Last {since_hours:.0f} hours"))

    # Get branch data
    red_flag_status = red_flag_detector.get_branch_status(
        branch_name, branch_path, since_timestamp
    )
    health_status = memory_health.get_memory_health_status(branch_path, branch_name)
    activity_data = activity_collector.scan_branch_activity(
        branch_name, branch_path, since_timestamp
    )

    # Status Overview
    lines.append(_section_header("STATUS OVERVIEW"))

    rf_status = red_flag_status.get("status", "UNKNOWN")
    rf_reason = red_flag_status.get("reason", "")
    mem_status = health_status.get("overall_status", "UNKNOWN")

    symbol = _get_status_symbol(rf_status)
    lines.append(f"Activity Status: {symbol} {rf_status}")
    lines.append(f"  Reason: {rf_reason}")

    mem_symbol = _get_status_symbol(mem_status)
    lines.append(f"Memory Health: {mem_symbol} {mem_status}")

    lines.append(f"Path: {branch_path}")

    # File Changes
    lines.append(_section_header("FILE CHANGES"))

    code_files = activity_data.get("code_files", [])
    memory_files = activity_data.get("memory_files", [])

    lines.append(f"Code files modified: {len(code_files)}")
    for cf in code_files:
        mtime = _format_time_ago(cf.get("mtime"))
        lines.append(f"  - {cf.get('name', 'unknown')} ({mtime})")

    lines.append(f"\nMemory files modified: {len(memory_files)}")
    for mf in memory_files:
        mtime = _format_time_ago(mf.get("mtime"))
        lines.append(f"  - {mf.get('name', 'unknown')} ({mtime})")

    if not code_files and not memory_files:
        lines.append("  [No files modified in time window]")

    # Memory Health Details
    lines.append(_section_header("MEMORY HEALTH DETAILS"))

    file_check = health_status.get("file_check", {})
    lines.append("Required files:")
    for fname, exists in file_check.get("required", {}).items():
        symbol = SYMBOL_OK if exists else SYMBOL_RED
        lines.append(f"  {symbol} {fname}")

    lines.append("\nOptional files:")
    for fname, exists in file_check.get("optional", {}).items():
        symbol = SYMBOL_OK if exists else SYMBOL_WARNING
        lines.append(f"  {symbol} {fname}")

    # Freshness
    freshness = health_status.get("freshness_checks", {})
    if freshness:
        lines.append("\nFreshness:")
        for fname, fresh in freshness.items():
            status = fresh.get("status", "UNKNOWN")
            message = fresh.get("message", "")
            symbol = _get_status_symbol(status)
            lines.append(f"  {symbol} {fname}: {message}")

    # Issues
    issues = health_status.get("issues", [])
    if issues:
        lines.append(_section_header("ISSUES"))
        for issue in issues:
            lines.append(f"  - {issue}")

    # Recommendations
    lines.append(_section_header("RECOMMENDATIONS"))
    recommendations: List[str] = []

    if rf_status == "RED_FLAG":
        recommendations.append("Update memory files to document recent code changes")

    for issue in issues:
        if "Missing required" in issue:
            recommendations.append(f"Create missing file: {issue.split(':')[-1].strip()}")
        elif "stale" in issue.lower() or "not modified" in issue.lower():
            recommendations.append("Review and update memory files")

    if recommendations:
        for rec in recommendations:
            lines.append(f"  - {rec}")
    else:
        lines.append("  [None - branch is healthy]")

    lines.append("")

    return "\n".join(lines)


def get_json_report(since_hours: float = 24) -> Dict[str, Any]:
    """
    Get raw report data as a dictionary for programmatic access.

    Useful for storing report snapshots, API responses, or further processing.

    Args:
        since_hours: Time window in hours to analyze.

    Returns:
        Dict containing all aggregated data from handlers.
    """
    data = _aggregate_data(since_hours)

    red_flags = data["red_flag_summary"]
    health_data = data["memory_health"]
    activity = data["activity_data"]

    # Build summary
    health_ok = sum(1 for h in health_data.values() if h.get("overall_status") == "OK")
    health_warning = sum(1 for h in health_data.values() if h.get("overall_status") == "WARNING")
    health_red = sum(1 for h in health_data.values() if h.get("overall_status") == "RED")

    summary = {
        "total_branches": red_flags.get("total_branches", 0),
        "active_branches": red_flags.get("ok", 0),
        "red_flags": red_flags.get("red_flags", 0),
        "no_activity": red_flags.get("no_activity", 0),
        "errors": red_flags.get("errors", 0),
        "health_ok": health_ok,
        "health_warning": health_warning,
        "health_red": health_red,
    }

    # Build per-branch data
    branches_data: Dict[str, Any] = {}
    all_branches = red_flags.get("all_branches", [])

    for branch_status in all_branches:
        name = branch_status.get("branch_name", "")
        if not name:
            continue

        branches_data[name] = {
            "red_flag_status": branch_status,
            "memory_health": health_data.get(name, {}),
            "activity": activity.get("branches", {}).get(name, {}),
        }

    return {
        "timestamp": data["timestamp"],
        "time_window_hours": data["time_window_hours"],
        "summary": summary,
        "violations": red_flags.get("violations", []),
        "branches": branches_data,
    }


# =============================================
# COMMAND INTEGRATION (AUTO-DISCOVERY)
# =============================================

def _print_activity_help() -> None:
    """Display help for the activity command."""
    print()
    print("=" * 60)
    print("ACTIVITY - Quick Activity Summary")
    print("=" * 60)
    print()
    print("USAGE:")
    print("  drone @daemon activity")
    print("  daemon activity")
    print("  daemon activity --hours 48")
    print()
    print("DESCRIPTION:")
    print("  Quick 24-hour activity summary (default).")
    print("  Shows branch status, red flags, and recommendations.")
    print()
    print("OPTIONS:")
    print("  --hours N, -t N    Time window in hours (default: 24)")
    print("  --help, -h         Show this help message")
    print()


def _print_activity_report_help() -> None:
    """Display help for the activity-report command."""
    print()
    print("=" * 60)
    print("ACTIVITY-REPORT - Full Detailed Report")
    print("=" * 60)
    print()
    print("USAGE:")
    print("  drone @daemon activity-report")
    print("  daemon activity-report")
    print("  daemon activity-report --hours 48")
    print("  daemon activity-report --json")
    print()
    print("DESCRIPTION:")
    print("  Full detailed activity report with file-level changes.")
    print("  Includes per-branch breakdown and complete recommendations.")
    print()
    print("OPTIONS:")
    print("  --hours N, -t N    Time window in hours (default: 24)")
    print("  --json, -j         Output raw JSON data")
    print("  --help, -h         Show this help message")
    print()


def _print_branch_health_help() -> None:
    """Display help for the branch-health command."""
    print()
    print("=" * 60)
    print("BRANCH-HEALTH - Single Branch Deep Dive")
    print("=" * 60)
    print()
    print("USAGE:")
    print("  drone @daemon branch-health DRONE")
    print("  daemon branch-health FLOW")
    print("  daemon branch-health SEED --hours 48")
    print()
    print("DESCRIPTION:")
    print("  Deep dive report for a single branch.")
    print("  Shows all file changes, memory health, and specific recommendations.")
    print()
    print("OPTIONS:")
    print("  <branch_name>      Required - branch name (e.g., DRONE, FLOW, SEED)")
    print("  --hours N, -t N    Time window in hours (default: 24)")
    print("  --help, -h         Show this help message")
    print()


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
    # Handle 'activity' command - quick summary
    if command == "activity":
        if args and args[0] in ('--help', '-h', 'help'):
            _print_activity_help()
            return True

        hours = _parse_hours_arg(args)
        report = generate_activity_report(since_hours=hours, verbosity="normal")
        print(report)
        return True

    # Handle 'activity-report' command - detailed report
    if command == "activity-report":
        if args and args[0] in ('--help', '-h', 'help'):
            _print_activity_report_help()
            return True

        hours = _parse_hours_arg(args)

        # Check for --json flag
        if '--json' in args or '-j' in args:
            import json
            data = get_json_report(hours)
            print(json.dumps(data, indent=2))
        else:
            report = generate_activity_report(since_hours=hours, verbosity="detailed")
            print(report)
        return True

    # Handle 'branch-health' command - single branch report
    if command == "branch-health":
        if args and args[0] in ('--help', '-h', 'help'):
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
            print("ERROR: branch-health requires a branch name")
            print()
            print("Usage: branch-health <branch_name> [--hours N]")
            print("Example: branch-health DRONE")
            return True

        hours = _parse_hours_arg(args)
        report = generate_branch_report(branch_name, since_hours=hours)
        print(report)
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
        print(json.dumps(data, indent=2))
    elif args.branch:
        report = generate_branch_report(args.branch, args.hours)
        print(report)
    else:
        report = generate_activity_report(args.hours, args.verbosity)
        print(report)


if __name__ == "__main__":
    main()
