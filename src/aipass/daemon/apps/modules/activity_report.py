# =================== AIPass ====================
# Name: activity_report.py
# Description: Branch Activity Report Generator Module
# Version: 0.4.0
# Created: 2026-01-30
# Modified: 2026-08-31
# =============================================

"""
Branch Activity Report Generator Module

Orchestrates monitoring handlers to generate comprehensive activity reports.
Provides formatted CLI output and programmatic JSON access.

This is a MODULE (orchestration layer) that coordinates:
- activity_collector: Scans branches for file modifications
- memory_health: Checks memory file health status
- red_flag_detector: Detects presence violations (code changed but memory not updated)
- @memory's get_branch_health: entry-count + entry-size facts (cross-branch)

The @memory call lives HERE, in the module layer, deliberately: seedgo blocks
handler-to-other-branch imports, so apps/handlers/monitoring/memory_health.py
must never reach for it.
"""

import os
import sys
from typing import List

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger

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
    console.print("[bold cyan]activity_report Module[/bold cyan]")
    console.print()
    console.print(
        "[dim]Branch activity report generator — monitors file changes, memory health, and presence violations[/dim]"
    )
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  handlers/monitoring/")
    console.print(
        "  [cyan]*[/cyan] report_generator.py"
        " [dim](generate_activity_report,"
        " generate_branch_report, get_json_report"
        " — report generation and JSON output)[/dim]"
    )
    console.print()
    console.print("[yellow]Cross-branch:[/yellow]")
    console.print(
        "  [cyan]*[/cyan] @memory get_branch_health"
        " [dim](entry-count + entry-size facts for branch-health — severity applied here)[/dim]"
    )
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
    console.print("  daemon branch-health SEEDGO --hours 48")
    console.print()
    console.print("DESCRIPTION:")
    console.print("  Deep dive report for a single branch.")
    console.print("  Shows all file changes, memory health, and specific recommendations.")
    console.print()
    console.print("OPTIONS:")
    console.print("  <branch_name>      Required - branch name (e.g., DRONE, FLOW, SEEDGO)")
    console.print("  --hours N, -t N    Time window in hours (default: 24)")
    console.print("  --help, -h         Show this help message")
    console.print()


# =============================================
# MEMORY ENTRY HEALTH (@memory's public API)
# =============================================

# Severity is the CALLER's call — get_branch_health reports facts only. The
# mapping below is @memory's, pinned in words in their module docstring
# (aipass.memory.apps.modules.health) and restated here so no consumer
# silently redecides it:
#
#   should_rollover True  -> INFO / pending. Rollover being due is not a
#                            fault; it auto-fires at the next PreCompact.
#                            NEVER WARNING.
#   total_violations > 0  -> WARNING. A write got past the character-cap gate.
#
# The caps themselves are NOT re-encoded here. They live in @memory's
# memory.config.json (defaults deep-merged with per-branch overrides); a copy
# on this side would be a snapshot that drifts.
#
# Markers are UPPERCASE deliberately. console.print() parses Rich markup, and a
# lowercase bracket tag like "[ok]" or "[info]" reads as a style name and is
# silently swallowed — the marker vanishes from the live output while a test
# asserting on the returned string still passes. Uppercase is not a valid style,
# so it survives. Verified live, and pinned by test_markers_survive_rich_markup.

SYMBOL_OK = "[OK]"
SYMBOL_WARNING = "[!]"
SYMBOL_PENDING = "[PENDING]"
SYMBOL_SKIP = "[SKIP]"


def _render_entry_health(branch_name: str) -> str:
    """
    Render entry-count and entry-size health for one branch via @memory.

    Read-only. Degrades visibly, never silently: an unimportable @memory or an
    unknown branch prints a named reason instead of an empty section.

    Args:
        branch_name: Branch to check, matched case-insensitively by @memory.

    Returns:
        Formatted report block (never raises).
    """
    lines: List[str] = ["", "=" * 60, f"MEMORY ENTRY HEALTH: {branch_name} (via @memory)", "=" * 60]

    try:
        from aipass.memory.apps.modules.health import get_branch_health
    # OSError as well: a cross-branch optional import can fail on the FILESYSTEM,
    # not only on absence. @memory imports clean under a dead cwd today (measured
    # 2026-08-31); this catches the condition rather than today's measurement.
    except (ImportError, OSError) as e:
        logger.warning("[DAEMON] activity_report: @memory health API unavailable: %s", e)
        lines.append(f"  {SYMBOL_WARNING} UNAVAILABLE - @memory health API not importable: {e}")
        return "\n".join(lines)

    health = get_branch_health(branch_name)

    if not health.get("success"):
        reason = health.get("error", "unknown error")
        logger.warning("[DAEMON] activity_report: entry health refused for %s: %s", branch_name, reason)
        lines.append(f"  {SYMBOL_WARNING} {reason}")
        return "\n".join(lines)

    lines.append("Entry count (rollover trigger):")
    for memory_type, result in (health.get("entry_count") or {}).items():
        if result is None:
            lines.append(f"  {SYMBOL_SKIP} {memory_type}: no file")
            continue
        current_lines = result.get("current_lines")
        if result.get("should_rollover"):
            reason = result.get("reason") or "over trigger"
            lines.append(f"  {SYMBOL_PENDING} {memory_type}: rollover pending ({current_lines} lines) - {reason}")
        else:
            lines.append(f"  {SYMBOL_OK} {memory_type}: {current_lines} lines")

    entry_size = health.get("entry_size") or {}
    total_violations = entry_size.get("total_violations", 0)
    lines.append("")

    if not total_violations:
        lines.append(f"Entry size: {SYMBOL_OK} no cap violations")
        return "\n".join(lines)

    lines.append(f"Entry size: {SYMBOL_WARNING} WARNING - {total_violations} cap violation(s)")
    for violation in entry_size.get("violations", []):
        lines.append(
            f"  - {violation.get('file')} {violation.get('container')} "
            f"'{violation.get('key')}': {violation.get('length')} chars "
            f"(cap {violation.get('cap')}, over by {violation.get('over_by')})"
        )

    return "\n".join(lines)


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
        if args[i] in ("--hours", "-t") and i + 1 < len(args):
            try:
                hours = float(args[i + 1])
            except ValueError as e:
                logger.warning("Invalid --hours value '%s': %s", args[i + 1], e)
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
        if args and args[0] in ("--help", "-h", "help"):
            print_introspection()
            return True
        json_handler.log_operation("activity_report", {"command": command})
        hours = _parse_hours_arg(args)
        report = generate_activity_report(since_hours=hours, verbosity="normal")
        console.print(report)
        logger.info("[DAEMON] activity_report: Activity summary generated")
        return True

    # Handle 'activity' command - quick summary (runs with no args, defaults to 24h)
    if command == "activity":
        if args and args[0] in ("--help", "-h", "help"):
            _print_activity_help()
            return True

        json_handler.log_operation("activity_report", {"command": command})
        hours = _parse_hours_arg(args)
        report = generate_activity_report(since_hours=hours, verbosity="normal")
        console.print(report)
        logger.info("[DAEMON] activity_report: Activity summary generated")
        return True

    # Handle 'activity-report' command - detailed report (runs with no args, defaults to 24h)
    if command == "activity-report":
        if args and args[0] in ("--help", "-h", "help"):
            _print_activity_report_help()
            return True

        json_handler.log_operation("activity_report", {"command": command})
        hours = _parse_hours_arg(args)

        # Check for --json flag
        if "--json" in args or "-j" in args:
            import json

            data = get_json_report(hours)
            console.print(json.dumps(data, indent=2))
        else:
            report = generate_activity_report(since_hours=hours, verbosity="detailed")
            console.print(report)
        logger.info("[DAEMON] activity_report: Detailed report generated")
        return True

    # Handle 'branch-health' command - requires branch name arg
    if command == "branch-health":
        return _handle_branch_health(args)

    # Not our command
    return False


def _extract_branch_name(args: List[str]) -> str | None:
    """Extract the first non-flag argument as the branch name."""
    i = 0
    while i < len(args):
        if args[i] in ("--hours", "-t") and i + 1 < len(args):
            i += 2
        elif args[i].startswith("-"):
            i += 1
        else:
            return args[i]
    return None


def _handle_branch_health(args: List[str]) -> bool:
    """Handle 'branch-health [branch]' command. No args = all branches summary."""
    if not args:
        json_handler.log_operation("branch_health_all", {"command": "branch-health"})
        report = generate_activity_report(since_hours=24, verbosity="normal")
        console.print(report)
        return True
    if args[0] in ("--help", "-h", "help"):
        _print_branch_health_help()
        return True

    branch_name = _extract_branch_name(args)
    if not branch_name:
        error("branch-health requires a branch name")
        console.print()
        console.print("Usage: branch-health <branch_name> [--hours N]")
        console.print("Example: branch-health DRONE")
        return True

    hours = _parse_hours_arg(args)
    report = generate_branch_report(branch_name, since_hours=hours)
    console.print(report)
    console.print(_render_entry_health(branch_name))
    logger.info("[DAEMON] activity_report: Branch health report generated for %s", branch_name)
    return True


# =============================================
# CLI ENTRY POINT
# =============================================


def main() -> None:
    """Main entry point for direct execution."""
    import argparse

    parser = argparse.ArgumentParser(description="Branch Activity Report Generator")
    parser.add_argument("--hours", "-t", type=float, default=24, help="Time window in hours (default: 24)")
    parser.add_argument(
        "--verbosity",
        "-v",
        choices=["brief", "normal", "detailed"],
        default="normal",
        help="Report detail level (default: normal)",
    )
    parser.add_argument("--branch", "-b", type=str, default=None, help="Generate report for specific branch")
    parser.add_argument("--json", "-j", action="store_true", help="Output raw JSON data")

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
