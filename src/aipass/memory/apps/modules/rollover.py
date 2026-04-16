# =================== AIPass ====================
# Name: rollover.py
# Description: Rollover Orchestration Module
# Version: 0.6.0
# Created: 2025-11-16
# Modified: 2026-03-15
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
from pathlib import Path
from typing import List

from rich.panel import Panel
from rich import box

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, warning
from aipass.memory.apps.handlers.json import json_handler

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

_SUBCOMMANDS = {
    "run": "Execute rollover for files exceeding limits",
    "status": "Show rollover statistics for all branches",
    "check": "Check which files need rollover (dry run)",
    "sync-lines": "Update line count metadata for all branches",
}


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle rollover commands with seedgo-compliant introspection.

    Routing:
        rollover (no args)        -> print_introspection()
        rollover --help/-h/help   -> print_help()
        rollover run              -> execute rollover
        rollover status           -> show rollover status
        rollover check            -> dry-run check
        rollover sync-lines       -> sync line counts

    Backward-compatible top-level commands (routed from entry point):
        status, check, sync-lines -> forwarded directly

    Args:
        command: Command name
        args: Additional arguments

    Returns:
        True if command handled, False otherwise
    """
    # Top-level help (backward compat — entry point may send these)
    if command in ("--help", "-h", "help"):
        print_help()
        return True

    if command == "rollover":
        # No args → introspection (seedgo standard)
        if not args:
            print_introspection()
            return True

        # --help / -h / help → full help
        if args[0] in ("--help", "-h", "help"):
            print_help()
            return True

        # Subcommand routing
        sub = args[0]

        if sub == "run":
            run_rollover()
            return True

        if sub == "status":
            show_status()
            return True

        if sub == "check":
            check_triggers()
            return True

        if sub == "sync-lines":
            sync_line_counts()
            return True

        # Unknown subcommand
        error(
            f"Unknown subcommand: '{sub}'",
            suggestion="Available: " + ", ".join(_SUBCOMMANDS.keys()),
        )
        return True

    # Backward-compatible top-level commands (entry point still routes these)
    if command == "status":
        show_status()
        return True

    elif command == "check":
        check_triggers()
        return True

    elif command == "sync-lines":
        sync_line_counts()
        return True

    elif command == "process-plans":
        process_plans_command()
        return True

    return False


def print_help() -> None:
    """Display rollover module help"""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]Rollover Module - Memory Rollover Orchestration[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    console.print()
    console.print("[bold]USAGE:[/bold]")
    console.print("  drone @memory rollover <command>")
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
    console.print(Panel.fit("[bold cyan]Memory - Rollover Execution[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()

    console.print("[cyan]Checking for rollover triggers... (first run may take 30s for model loading)[/cyan]")

    try:
        result = _handler_execute_rollover()
    except Exception as e:
        logger.error(f"[rollover] Rollover execution failed: {e}", exc_info=True)
        error(f"Rollover failed: {e}")
        return False

    if not result.get("success") and result.get("error"):
        error(result["error"])
        return False

    triggers_count = result.get("triggers_count", 0)
    if triggers_count == 0:
        console.print("[green]>[/green] No files need rollover")
        return True

    console.print(f"[green]>[/green] Found {triggers_count} files ready for rollover")
    console.print()

    # Display individual results
    for item in result.get("results", []):
        local_status = "> local" if item.get("local_stored") else "x local"
        console.print(
            f"  [green]>[/green] Rolled over {item['memories_count']} items -> {item['global_collection']} "
            f"({item['old_lines']} -> {item['new_lines']} lines, global: {item['global_total']} vectors, {local_status})"
        )

    # Report results
    success_count = result.get("success_count", 0)
    failed = result.get("failed", [])

    console.print()
    if success_count > 0:
        console.print(f"[green]>[/green] Rollover complete: {success_count}/{triggers_count} successful")

    if failed:
        console.print()
        for fail in failed:
            error(f"{fail['trigger']} - {fail['stage']}: {fail['error']}")

    json_handler.log_operation("rollover_execute", {"triggers": triggers_count, "success_count": success_count})
    return success_count > 0


# =============================================================================
# PLAN VECTORIZATION
# =============================================================================


def process_plans_command() -> None:
    """
    Process pending plan files into vector storage.

    Batches all chunks from all files into a single embed + store call.
    """
    console.print()
    console.print(Panel.fit("[bold cyan]Memory - Process Plans[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()

    console.print("[cyan]Processing plan files into vector storage...[/cyan]")
    console.print()

    try:
        from ..handlers.intake.plans_processor import process_plans

        result = process_plans()
    except Exception as e:
        logger.error(f"[rollover] Plan processing failed: {e}")
        error(f"Plan processing failed: {e}")
        return

    if not result.get("success"):
        error(result.get("error", "Unknown error"))
        if result.get("errors"):
            for err in result["errors"]:
                error(err)
        return

    files_processed = result.get("files_processed", 0)
    total_chunks = result.get("total_chunks", 0)
    reason = result.get("reason", "")

    if files_processed == 0 and reason:
        console.print(f"[green]>[/green] {reason}")
    elif files_processed == 0:
        console.print("[green]>[/green] No new plans to process")
    else:
        console.print(f"[green]>[/green] Processed {files_processed} files ({total_chunks} chunks vectorized)")

    if result.get("errors"):
        console.print()
        for err in result["errors"]:
            error(err)

    console.print()
    json_handler.log_operation(
        "process_plans_command", {"files_processed": files_processed, "total_chunks": total_chunks}
    )


# =============================================================================
# LINE COUNT SYNC
# =============================================================================


def sync_line_counts() -> None:
    """
    Update line count metadata for all branch memory files.

    Delegates to handler and renders results with Rich.
    """
    console.print()
    console.print(Panel.fit("[bold cyan]Memory - Sync Line Counts[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()

    console.print("[cyan]Updating line counts for all memory files...[/cyan]")
    console.print()

    result = _handler_sync_line_counts()

    if result["success"]:
        console.print(f"[green]>[/green] Updated {result['updated']} files")
        if result["failed"] > 0:
            warning(f"{result['failed']} files failed")
            for branch, mem_type, err_msg in result.get("failures", []):
                error(f"{branch}.{mem_type}: {err_msg}")
        json_handler.log_operation("rollover_sync_lines", {"updated": result["updated"], "failed": result["failed"]})
    else:
        error("Failed to sync line counts")

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
    console.print(Panel.fit("[bold cyan]Memory - Rollover Status[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()

    # Get stats from detector
    stats_result = detector.get_rollover_stats()

    if not stats_result["success"]:
        error(f"Failed to get status: {stats_result.get('error', 'Unknown error')}")
        logger.error(f"[rollover] Failed to get status: {stats_result.get('error')}")
        return

    stats = stats_result

    # Summary
    console.print(f"[cyan]Branches:[/cyan] {stats['total_branches']}")
    console.print(f"[cyan]Files checked:[/cyan] {stats['files_checked']}")
    console.print(f"[cyan]Ready for rollover:[/cyan] {stats['files_ready']}")
    console.print()

    # Per-branch details
    if stats["branches"]:
        console.print("[bold cyan]Branch Details:[/bold cyan]")
        console.print()

        for branch_name, branch_stats in stats["branches"].items():
            console.print(f"  [bold]{branch_name}[/bold]")

            for memory_type, file_stats in branch_stats.items():
                current = file_stats["current"]
                max_val = file_stats["max"]
                ready = file_stats["ready"]
                remaining = file_stats["remaining"]
                schema_ver = file_stats.get("schema_version", "1.0.0")
                v2_reason = file_stats.get("v2_reason", "")

                status_marker = "[red]![/red]" if ready else "[green]OK[/green]"

                if schema_ver.startswith("2"):
                    status_text = f"READY ({v2_reason})" if ready else "OK (v2)"
                    console.print(f"    {status_marker} {memory_type}: {status_text}")
                else:
                    status_text = "READY" if ready else f"{remaining} remaining"
                    console.print(f"    {status_marker} {memory_type}: {current}/{max_val} lines ({status_text})")

            console.print()

    json_handler.log_operation(
        "rollover_status", {"branches_checked": stats["total_branches"], "files_ready": stats["files_ready"]}
    )


def check_triggers() -> None:
    """
    Check which branches need rollover (without executing)

    Displays list of files that hit rollover threshold
    """
    console.print()
    console.print(Panel.fit("[bold cyan]Memory - Rollover Check[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()

    triggers_result = detector.check_all_branches()

    if not triggers_result["success"]:
        error(f"Failed to check triggers: {triggers_result.get('error', 'Unknown error')}")
        logger.error(f"[rollover] Failed to check triggers: {triggers_result.get('error')}")
        return

    triggers = triggers_result.get("triggers", [])

    if not triggers:
        console.print("[green]>[/green] No files need rollover")
        json_handler.log_operation("rollover_check", {"files_needing_rollover": 0})
        return

    console.print(f"[bold cyan]Found {len(triggers)} files ready for rollover:[/bold cyan]")
    console.print()

    for trigger in triggers:
        console.print(f"  * {trigger}")

    console.print()
    console.print("[dim]Run 'drone @memory rollover' to process these files[/dim]")
    console.print()
    json_handler.log_operation("rollover_check", {"files_needing_rollover": len(triggers)})


# =============================================================================
# INTROSPECTION
# =============================================================================


def _discover_handlers() -> dict[str, list[str]]:
    """Auto-discover handler directories and their Python files.

    Scans the handlers/ directory relative to this module.

    Returns:
        Dict mapping handler directory name to list of .py filenames
        (excluding __init__.py and __pycache__).
    """
    handlers_dir = Path(__file__).resolve().parent.parent / "handlers"
    result: dict[str, list[str]] = {}
    if not handlers_dir.exists():
        return result
    for d in sorted(handlers_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("__"):
            continue
        py_files = sorted(f.name for f in d.iterdir() if f.is_file() and f.suffix == ".py" and f.name != "__init__.py")
        if py_files:
            result[d.name] = py_files
    return result


def print_introspection() -> None:
    """Display module introspection info (seedgo standard).

    Called when 'rollover' is invoked with no arguments.
    Shows module identity, connected handlers, available subcommands,
    and next-step hints.
    """
    console.print()
    console.print("[bold cyan]rollover Module[/bold cyan]")
    console.print("Orchestrates memory rollover workflow: trigger detection, extraction, embedding, and vector storage")
    console.print()

    # Connected handlers (auto-discovered)
    handlers = _discover_handlers()
    console.print("[yellow]Connected Handlers:[/yellow]")
    if handlers:
        for dir_name, files in handlers.items():
            file_list = ", ".join(files)
            console.print(f"  [cyan]handlers/{dir_name}/[/cyan]  [dim]{file_list}[/dim]")
    else:
        console.print("  [dim]No handlers found[/dim]")
    console.print()

    # Available subcommands
    console.print("[yellow]Subcommands:[/yellow]")
    for sub, desc in _SUBCOMMANDS.items():
        console.print(f"  [green]{sub:<14}[/green] {desc}")
    console.print()

    # Next-step hints
    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @memory rollover run[/green]          [dim]# Execute rollover[/dim]")
    console.print("  [green]drone @memory rollover status[/green]       [dim]# View rollover stats[/dim]")
    console.print("  [green]drone @memory rollover check[/green]        [dim]# Dry-run check[/dim]")
    console.print("  [green]drone @memory rollover --help[/green]       [dim]# Full usage guide[/dim]")
    console.print()


# =============================================================================
# STANDALONE EXECUTION
# =============================================================================

if __name__ == "__main__":
    import sys

    # No args → introspection (seedgo standard)
    if len(sys.argv) < 2:
        handle_command("rollover", [])
        sys.exit(0)

    # --help → full help
    if sys.argv[1] in ("--help", "-h", "help"):
        handle_command("rollover", ["--help"])
        sys.exit(0)

    # Execute command via handle_command
    command = sys.argv[1]
    if not handle_command(command, sys.argv[2:]):
        console.print(f"[red]Unknown command:[/red] {command}")
        console.print("Run with [cyan]help[/cyan] for available commands")
        sys.exit(1)
