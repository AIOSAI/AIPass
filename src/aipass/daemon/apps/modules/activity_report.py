# =================== AIPass ====================
# Name: activity_report.py
# Description: Branch Activity Report Generator Module
# Version: 0.5.0
# Created: 2026-01-30
# Modified: 2026-10-17
# =============================================

"""
Branch Activity Report Generator Module

Reference: docs/monitoring.md
"""

import os
import sys
from typing import List, NoReturn

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger

from aipass.cli.apps.modules import console
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.cli.arg_gate import gate, refuse

from aipass.daemon.apps.handlers.monitoring.report_generator import (
    generate_activity_report,
    generate_branch_report,
    get_json_report,
)

# The same roster generate_branch_report() resolves against, so accepted names are reportable names.
from aipass.daemon.apps.handlers.monitoring import activity_collector


MODULE_NAME = "activity_report"

BRANCH_HEALTH_USAGE = "drone @daemon branch-health <branch_name> [--hours N]"


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


# Severity mapping is @memory's (aipass.memory.apps.modules.health): should_rollover is PENDING, never
# WARNING (it auto-fires at PreCompact); total_violations > 0 is WARNING. Caps are not copied here.
# Markers are UPPERCASE: Rich swallows lowercase "[ok]" as a style tag (test_markers_survive_rich_markup).
SYMBOL_OK = "[OK]"
SYMBOL_WARNING = "[!]"
SYMBOL_PENDING = "[PENDING]"
SYMBOL_SKIP = "[SKIP]"


def _render_entry_health(branch_name: str) -> str:
    """Render entry-count and entry-size health for one branch via @memory.

    Never raises: an unimportable @memory or unknown branch prints a named reason.
    """
    lines: List[str] = ["", "=" * 60, f"MEMORY ENTRY HEALTH: {branch_name} (via @memory)", "=" * 60]

    try:
        from aipass.memory.apps.modules.health import get_branch_health
    # OSError too: a cross-branch import can fail on the filesystem, not only on absence.
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
    """Extract --hours or -t argument from args list (default 24)."""
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
    """Handle activity monitoring commands. Returns False if not our command."""
    # Alias: help shows the module name, so users type it.
    if command == "activity_report":
        if args and args[0] in ("--help", "-h", "help"):
            print_introspection()
            return True
        gate(command, args, value_flags=("--hours", "-t"), usage="drone @daemon activity_report [--hours N]")
        json_handler.log_operation("activity_report", {"command": command})
        hours = _parse_hours_arg(args)
        report = generate_activity_report(since_hours=hours, verbosity="normal")
        console.print(report)
        logger.info("[DAEMON] activity_report: Activity summary generated")
        return True

    if command == "activity":
        if args and args[0] in ("--help", "-h", "help"):
            _print_activity_help()
            return True

        gate(command, args, value_flags=("--hours", "-t"), usage="drone @daemon activity [--hours N]")

        json_handler.log_operation("activity_report", {"command": command})
        hours = _parse_hours_arg(args)
        report = generate_activity_report(since_hours=hours, verbosity="normal")
        console.print(report)
        logger.info("[DAEMON] activity_report: Activity summary generated")
        return True

    if command == "activity-report":
        if args and args[0] in ("--help", "-h", "help"):
            _print_activity_report_help()
            return True

        gate(
            command,
            args,
            flags=("--json", "-j"),
            value_flags=("--hours", "-t"),
            usage="drone @daemon activity-report [--json] [--hours N]",
        )

        json_handler.log_operation("activity_report", {"command": command})
        hours = _parse_hours_arg(args)

        if "--json" in args or "-j" in args:
            import json

            data = get_json_report(hours)
            console.print(json.dumps(data, indent=2))
        else:
            report = generate_activity_report(since_hours=hours, verbosity="detailed")
            console.print(report)
        logger.info("[DAEMON] activity_report: Detailed report generated")
        return True

    if command == "branch-health":
        return _handle_branch_health(args)

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


def _known_branch_names() -> List[str]:
    """Canonical names of every branch the reports can be generated for."""
    return sorted(bp.get("name", "") for bp in activity_collector.get_branch_paths() if bp.get("name"))


def _resolve_branch(branch_name: str) -> str | None:
    """Match *branch_name* case-insensitively to a canonical name, or None."""
    wanted = branch_name.upper()
    for name in _known_branch_names():
        if name.upper() == wanted:
            return name
    return None


def _refuse(verb: str, token: str, usage: str = "") -> NoReturn:
    """Refuse *token* by name and exit non-zero, through the shared gate."""
    refuse(verb, token, usage)


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
        _refuse("branch-health", " ".join(args), BRANCH_HEALTH_USAGE)

    resolved = _resolve_branch(branch_name)
    if resolved is None:
        console.print()
        console.print(f"Known branches: {', '.join(_known_branch_names())}")
        _refuse("branch-health", branch_name, BRANCH_HEALTH_USAGE)

    hours = _parse_hours_arg(args)
    report = generate_branch_report(resolved, since_hours=hours)
    console.print(report)
    console.print(_render_entry_health(resolved))
    logger.info("[DAEMON] activity_report: Branch health report generated for %s", resolved)
    return True


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
