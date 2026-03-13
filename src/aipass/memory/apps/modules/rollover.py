# =================== AIPass ====================
# Name: rollover.py
# Description: Rollover Orchestration Module
# Version: 0.5.0
# Created: 2025-11-16
# Modified: 2026-03-08
# =============================================

"""
Rollover Orchestration Module

Coordinates the memory rollover workflow by calling handlers in sequence:
1. Detect rollover triggers (monitor/detector)
2. Extract oldest memories (rollover/extractor)
3. Generate embeddings (vector/embedder)
4. Store in Chroma (storage/chroma)

Purpose:
    Thin orchestration layer - no business logic implementation.
    All domain logic lives in handlers.
"""

import sys
from typing import List

from rich.panel import Panel
from rich import box

from aipass.prax import logger
from aipass.cli.apps.modules import console

# =============================================================================
# INFRASTRUCTURE SETUP
# =============================================================================

# Handler imports
from ..handlers.monitor import detector
from ..handlers.rollover.orchestrator import (
    execute_rollover as _handler_execute_rollover,
    sync_line_counts as _handler_sync_line_counts,
)


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:  # noqa: ARG001
    """
    Handle rollover commands

    Commands supported:
    - rollover: Execute rollover for triggered branches
    - status: Show rollover statistics
    - check: Check which branches need rollover
    - sync-lines: Update line count metadata for all branches

    Args:
        command: Command name
        args: Additional arguments

    Returns:
        True if command handled, False otherwise
    """
    if command in ('--help', '-h', 'help'):
        print_help()
        return True

    if command == 'rollover':
        run_rollover()
        return True

    elif command == 'status':
        show_status()
        return True

    elif command == 'check':
        check_triggers()
        return True

    elif command == 'sync-lines':
        sync_line_counts()
        return True

    return False


def print_help() -> None:
    """Display rollover module help"""
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Rollover Module - Memory Rollover Orchestration[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED
    ))
    console.print()
    console.print("[bold]USAGE:[/bold]")
    console.print("  python3 -m aipass.memory.apps.modules.rollover <command>")
    console.print()
    console.print("[bold]COMMANDS:[/bold]")
    console.print("  [cyan]rollover[/cyan]    Execute rollover for files exceeding limits")
    console.print("  [cyan]status[/cyan]      Show rollover statistics for all branches")
    console.print("  [cyan]check[/cyan]       Check which files need rollover (dry run)")
    console.print("  [cyan]sync-lines[/cyan]  Update line count metadata for all branches")
    console.print("  [cyan]help[/cyan]        Show this help message")
    console.print()
    console.print("[bold]LIMITS:[/bold]")
    console.print("  v1 (schema <2.0): Line-count based (max_lines, default 600)")
    console.print("  v2 (schema 2.0+): Entry-count based (max_sessions, max_key_learnings)")
    console.print()
    console.print("[bold]WORKFLOW:[/bold]")
    console.print("  1. Detect files exceeding limits (line count or entry count)")
    console.print("  2. Extract oldest entries")
    console.print("  3. Generate embeddings via sentence-transformers")
    console.print("  4. Store vectors in local + global ChromaDB")
    console.print()


# =============================================================================
# ROLLOVER ORCHESTRATION
# =============================================================================

def run_rollover() -> bool:
    """
    Execute rollover workflow for all triggered branches.

    Delegates to handler and renders results with Rich.
    """
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Memory - Rollover Execution[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED
    ))
    console.print()

    console.print("[cyan]Checking for rollover triggers...[/cyan]")

    result = _handler_execute_rollover()

    if not result.get('success') and result.get('error'):
        console.print(f"[red]x[/red] {result['error']}")
        return False

    triggers_count = result.get('triggers_count', 0)
    if triggers_count == 0:
        console.print("[green]>[/green] No files need rollover")
        return True

    console.print(f"[green]>[/green] Found {triggers_count} files ready for rollover")
    console.print()

    # Display individual results
    for item in result.get('results', []):
        local_status = "> local" if item.get('local_stored') else "x local"
        console.print(
            f"  [green]>[/green] Rolled over {item['memories_count']} items -> {item['global_collection']} "
            f"({item['old_lines']} -> {item['new_lines']} lines, global: {item['global_total']} vectors, {local_status})"
        )

    # Report results
    success_count = result.get('success_count', 0)
    failed = result.get('failed', [])

    console.print()
    if success_count > 0:
        console.print(f"[green]>[/green] Rollover complete: {success_count}/{triggers_count} successful")

    if failed:
        console.print()
        console.print("[red]Failed operations:[/red]")
        for fail in failed:
            console.print(f"  [red]x[/red] {fail['trigger']} - {fail['stage']}: {fail['error']}")

    return success_count > 0


# =============================================================================
# LINE COUNT SYNC
# =============================================================================

def sync_line_counts() -> None:
    """
    Update line count metadata for all branch memory files.

    Delegates to handler and renders results with Rich.
    """
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Memory - Sync Line Counts[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED
    ))
    console.print()

    console.print("[cyan]Updating line counts for all memory files...[/cyan]")
    console.print()

    result = _handler_sync_line_counts()

    if result['success']:
        console.print(f"[green]>[/green] Updated {result['updated']} files")
        if result['failed'] > 0:
            console.print(f"[yellow]![/yellow] {result['failed']} files failed:")
            for branch, mem_type, error in result.get('failures', []):
                console.print(f"    [red]x[/red] {branch}.{mem_type}: {error}")
    else:
        console.print("[red]x[/red] Failed to sync line counts")

    console.print()


# =============================================================================
# STATUS & CHECKING
# =============================================================================

def show_status() -> None:
    """
    Show rollover statistics for all branches

    Displays:
    - Files checked
    - Files ready for rollover
    - Per-branch status (current/max lines)
    """
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Memory - Rollover Status[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED
    ))
    console.print()

    # Get stats from detector
    stats_result = detector.get_rollover_stats()

    if not stats_result['success']:
        console.print(f"[red]x[/red] Failed to get status: {stats_result.get('error', 'Unknown error')}")
        logger.error(f"[rollover] Failed to get status: {stats_result.get('error')}")
        return

    stats = stats_result

    # Summary
    console.print(f"[cyan]Branches:[/cyan] {stats['total_branches']}")
    console.print(f"[cyan]Files checked:[/cyan] {stats['files_checked']}")
    console.print(f"[cyan]Ready for rollover:[/cyan] {stats['files_ready']}")
    console.print()

    # Per-branch details
    if stats['branches']:
        console.print("[yellow]Branch Details:[/yellow]")
        console.print()

        for branch_name, branch_stats in stats['branches'].items():
            console.print(f"  [bold]{branch_name}[/bold]")

            for memory_type, file_stats in branch_stats.items():
                current = file_stats['current']
                max_val = file_stats['max']
                ready = file_stats['ready']
                remaining = file_stats['remaining']
                schema_ver = file_stats.get('schema_version', '1.0.0')
                v2_reason = file_stats.get('v2_reason', '')

                status_marker = "[red]![/red]" if ready else "[green]OK[/green]"

                if schema_ver.startswith('2'):
                    status_text = f"READY ({v2_reason})" if ready else "OK (v2)"
                    console.print(f"    {status_marker} {memory_type}: {status_text}")
                else:
                    status_text = "READY" if ready else f"{remaining} remaining"
                    console.print(
                        f"    {status_marker} {memory_type}: {current}/{max_val} lines ({status_text})"
                    )

            console.print()


def check_triggers() -> None:
    """
    Check which branches need rollover (without executing)

    Displays list of files that hit rollover threshold
    """
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Memory - Rollover Check[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED
    ))
    console.print()

    triggers_result = detector.check_all_branches()

    if not triggers_result['success']:
        console.print(f"[red]x[/red] Failed to check triggers: {triggers_result.get('error', 'Unknown error')}")
        logger.error(f"[rollover] Failed to check triggers: {triggers_result.get('error')}")
        return

    triggers = triggers_result.get('triggers', [])

    if not triggers:
        console.print("[green]>[/green] No files need rollover")
        return

    console.print(f"[yellow]Found {len(triggers)} files ready for rollover:[/yellow]")
    console.print()

    for trigger in triggers:
        console.print(f"  * {trigger}")

    console.print()
    console.print("[dim]Run 'drone @memory rollover' to process these files[/dim]")
    console.print()


# =============================================================================
# INTROSPECTION
# =============================================================================

def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("rollover Module")
    console.print("Orchestrates memory rollover workflow: trigger detection, extraction, embedding, and vector storage")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/monitor/")
    console.print("    - detector.py (check_all_branches — detect branches exceeding rollover threshold)")
    console.print("    - detector.py (get_rollover_stats — retrieve rollover statistics for all branches)")
    console.print("  handlers/rollover/")
    console.print("    - orchestrator.py (execute_rollover — run full rollover pipeline for triggered branches)")
    console.print("    - orchestrator.py (sync_line_counts — update line count metadata for all memory files)")
    console.print()


# =============================================================================
# STANDALONE EXECUTION
# =============================================================================

if __name__ == "__main__":
    import sys

    # Handle --help before argparse (module standard)
    if len(sys.argv) < 2 or sys.argv[1] in ('--help', '-h', 'help'):
        handle_command('help', [])
        sys.exit(0)

    # Execute command via handle_command
    command = sys.argv[1]
    if not handle_command(command, sys.argv[2:]):
        console.print(f"[red]Unknown command:[/red] {command}")
        console.print("Run with [cyan]help[/cyan] for available commands")
        sys.exit(1)
