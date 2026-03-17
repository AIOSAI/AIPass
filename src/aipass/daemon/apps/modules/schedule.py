# =================== AIPass ====================
# Name: schedule.py
# Description: DAEMON Scheduled Follow-ups Module
# Version: 1.0.0
# Created: 2026-02-04
# Modified: 2026-02-04
# =============================================

"""
CLI interface for fire-and-forget scheduled follow-ups.
"""

# =============================================
# IMPORTS
# =============================================

import sys
import argparse
from pathlib import Path
from typing import List

from aipass.prax import logger

from aipass.cli.apps.modules import console, error as cli_error
from aipass.daemon.apps.handlers.json import json_handler

def _header(text):
    console.print(f"\n[bold cyan]{'='*70}[/bold cyan]")
    console.print(f"[bold cyan]  {text}[/bold cyan]")
    console.print(f"[bold cyan]{'='*70}[/bold cyan]")

def _success(text):
    console.print(f"[green]OK:[/green] {text}")

def _error(text):
    cli_error(text)

# Handler imports
from aipass.daemon.apps.handlers.schedule.task_registry import (
    load_tasks, create_task, delete_task, get_due_tasks, mark_completed, parse_due_date,
    mark_dispatching, mark_pending, recover_stale_dispatches, process_due_tasks_batch,
    ensure_lock_dir,
)

# File lock for single-instance execution
try:
    from filelock import FileLock, Timeout
    FILELOCK_AVAILABLE = True
except ImportError:
    FILELOCK_AVAILABLE = False
    FileLock = None  # type: ignore[assignment,misc]
    Timeout = None  # type: ignore[assignment,misc]

# Email integration via drone subprocess
import subprocess

def _send_email_via_drone(to_branch, subject, message, from_branch='@daemon',
                          auto_execute=True, reply_to=None, **kwargs):
    """Send email via drone @ai_mail send subprocess."""
    cmd = ["drone", "@ai_mail", "send", to_branch, subject, message]
    if auto_execute:
        cmd.append("--dispatch")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=DRONE_SUBPROCESS_TIMEOUT)
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False

AI_MAIL_AVAILABLE = True
send_email_direct = _send_email_via_drone

# =============================================
# CONSTANTS
# =============================================

MODULE_NAME = "schedule"

# Constants
DRONE_SUBPROCESS_TIMEOUT = 15  # seconds
STALE_DISPATCH_MAX_AGE = 5     # minutes
LOCK_ACQUIRE_TIMEOUT = 0       # seconds (non-blocking)


# =============================================
# INTROSPECTION
# =============================================

def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("schedule Module")
    console.print("CLI interface for fire-and-forget scheduled follow-ups")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/schedule/")
    console.print("    - task_registry.py (load_tasks, create_task, delete_task, get_due_tasks, mark_completed, parse_due_date, mark_dispatching, mark_pending, recover_stale_dispatches, process_due_tasks_batch, ensure_lock_dir — task CRUD and processing)")
    console.print()

_DAEMON_ROOT = Path(__file__).resolve().parents[3]  # src/aipass/daemon/
JSON_DIR = _DAEMON_ROOT / "daemon_json"

# =============================================
# OUTPUT FORMATTING
# =============================================

def _print_task_list(tasks: List[dict]) -> None:
    """Print formatted task list to console."""
    console.print()
    _header("Scheduled Tasks")
    console.print()

    pending_tasks = [t for t in tasks if t.get("status") == "pending"]
    completed_tasks = [t for t in tasks if t.get("status") == "completed"]

    if not pending_tasks:
        console.print("[dim]No pending scheduled tasks.[/dim]")
    else:
        console.print("[bold cyan]PENDING TASKS[/bold cyan]")
        console.print(f"{'ID':<10} {'DUE':<20} {'TO':<15} {'TASK':<40}")
        console.print("-" * 85)

        for task in pending_tasks:
            task_id = task.get("id", "")[:8]
            due = task.get("due_date", "")
            recipient = task.get("recipient", "")
            task_text = task.get("task", "")[:38]
            console.print(f"{task_id:<10} {due:<20} {recipient:<15} {task_text:<40}")

    console.print()
    console.print(f"[dim]Total: {len(pending_tasks)} pending, {len(completed_tasks)} completed[/dim]")
    console.print()


def _print_help() -> None:
    """Display help using Rich formatted output."""
    console.print()
    _header("Schedule Module - Fire-and-Forget Follow-ups")
    console.print()

    console.print("[yellow]USAGE:[/yellow]")
    console.print('  drone @daemon schedule create "task" --due 7d --to @branch --message "details"')
    console.print("  drone @daemon schedule list")
    console.print("  drone @daemon schedule delete <id>")
    console.print("  drone @daemon schedule run-due")
    console.print()

    console.print("[yellow]COMMANDS:[/yellow]")
    console.print("  create    Create a new scheduled task")
    console.print("  list      List all pending scheduled tasks")
    console.print("  delete    Delete a scheduled task by ID")
    console.print("  run-due   Execute all due tasks (sends emails, marks complete)")
    console.print()

    console.print("[yellow]CREATE OPTIONS:[/yellow]")
    console.print("  --due     (Required) Due date: 1d, 7d, 2w, 1m, or ISO date (2026-02-15)")
    console.print("  --to      (Required) Recipient branch (e.g., @flow, @seed)")
    console.print("  --message (Optional) Additional details for the follow-up")
    console.print()

    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print('  # Remind Flow to check on a plan in 7 days')
    console.print('  schedule create "Check FPLAN-0290 status" --due 7d --to @flow')
    console.print()
    console.print('  # Follow up with Seed about code review in 2 weeks')
    console.print('  schedule create "Code review follow-up" --due 2w --to @seed --message "Review PR #45"')
    console.print()
    console.print('  # Check all due tasks and send reminder emails')
    console.print('  schedule run-due')
    console.print()


# =============================================
# SUBCOMMAND HANDLERS
# =============================================

def _handle_create(args: List[str]) -> bool:
    """Handle schedule create subcommand."""
    parser = argparse.ArgumentParser(prog="schedule create", add_help=False)
    parser.add_argument("task", nargs="?", help="Task description")
    parser.add_argument("--due", required=True, help="Due date (1d, 7d, 2w, 1m, or ISO date)")
    parser.add_argument("--to", required=True, dest="recipient", help="Recipient branch")
    parser.add_argument("--message", default="", help="Additional message details")

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        _error('Usage: schedule create "task" --due <date> --to @branch [--message "details"]')
        return False

    if not parsed.task:
        _error("Task description is required")
        console.print("[dim]Usage: schedule create \"task\" --due <date> --to @branch[/dim]")
        return False

    # Parse and validate due date
    due_date = parse_due_date(parsed.due)
    if not due_date:
        _error(f"Invalid due date format: {parsed.due}")
        console.print("[dim]Valid formats: 1d, 7d, 2w, 1m, or ISO date (2026-02-15)[/dim]")
        return False

    # Create the task
    try:
        new_task = create_task(
            task=parsed.task,
            due_date=due_date,
            recipient=parsed.recipient,
            message=parsed.message
        )
        task_id = new_task.get("id", "")

        _success(f"Scheduled task created: {task_id[:8]}")
        console.print(f"  [dim]Task:[/dim] {parsed.task}")
        console.print(f"  [dim]Due:[/dim]  {due_date}")
        console.print(f"  [dim]To:[/dim]   {parsed.recipient}")
        if parsed.message:
            console.print(f"  [dim]Msg:[/dim]  {parsed.message[:50]}...")
        console.print()

        logger.info(f"[DAEMON] Scheduled task created: {task_id[:8]} -> {parsed.recipient}")
        return True

    except Exception as e:
        _error(f"Failed to create task: {e}")
        logger.error(f"[DAEMON] Failed to create scheduled task: {e}", exc_info=True)
        return False


def _handle_list(_args: List[str]) -> bool:
    """Handle schedule list subcommand."""
    try:
        tasks = load_tasks()
        _print_task_list(tasks)
        return True

    except Exception as e:
        _error(f"Failed to load tasks: {e}")
        logger.error(f"[DAEMON] Failed to load scheduled tasks: {e}", exc_info=True)
        return False


def _handle_delete(args: List[str]) -> bool:
    """Handle schedule delete subcommand."""
    if not args:
        _error("Task ID is required")
        console.print("[dim]Usage: schedule delete <task_id>[/dim]")
        return False

    task_id = args[0]

    try:
        deleted = delete_task(task_id)
        if deleted:
            _success(f"Task deleted: {task_id[:8]}")
            logger.info(f"[DAEMON] Scheduled task deleted: {task_id[:8]}")
            return True
        else:
            _error(f"Task not found: {task_id[:8]}")
            return False

    except Exception as e:
        _error(f"Failed to delete task: {e}")
        logger.error(f"[DAEMON] Failed to delete scheduled task: {e}", exc_info=True)
        return False


def _handle_run_due(_args: List[str]) -> bool:
    """Handle schedule run-due subcommand with single-instance lock."""
    if not FILELOCK_AVAILABLE:
        console.print("[dim]filelock not available, running without lock.[/dim]")
        return _process_due_tasks()

    lock_file = JSON_DIR / "schedule.lock"
    ensure_lock_dir()

    # Try to acquire lock (non-blocking)
    # FILELOCK_AVAILABLE guard above ensures these are not None
    lock = FileLock(lock_file, timeout=LOCK_ACQUIRE_TIMEOUT)  # type: ignore[misc]
    try:
        with lock.acquire(timeout=LOCK_ACQUIRE_TIMEOUT):
            return _process_due_tasks()
    except Timeout:  # type: ignore[misc]
        console.print("[dim]Schedule run-due already in progress, skipping.[/dim]")
        return True


def _process_due_tasks() -> bool:
    """Process due tasks -- delegates to handler, formats output."""
    try:
        # Delegate to handler for all implementation logic
        email_fn = send_email_direct if AI_MAIL_AVAILABLE else None
        results = process_due_tasks_batch(send_email_fn=email_fn, stale_max_age=STALE_DISPATCH_MAX_AGE)

        # Display results (module responsibility)
        if results["recovered"]:
            console.print(f"[dim]Recovered {results['recovered']} stale dispatch(es)[/dim]")

        if results["due"] == 0:
            console.print("[dim]No tasks due at this time.[/dim]")
            return True

        console.print()
        _header(f"Running {results['due']} Due Task(s)")
        console.print()

        for task_result in results.get("processed_tasks", []):
            task_id = task_result.get("id", "")[:8]
            recipient = task_result.get("recipient", "")
            task_desc = task_result.get("task", "")[:40]
            status = task_result.get("status", "")

            if status == "sent":
                _success(f"Sent to {recipient}: {task_desc}")
                logger.info(f"[DAEMON] Scheduled email sent: {task_id} -> {recipient}")
            elif status == "skipped":
                _error(f"ai_mail not available, cannot send to {recipient}")
            elif status == "failed":
                _error(f"Failed to send to {recipient}: {task_desc}")
                logger.error(f"[DAEMON] Scheduled email failed: {task_id} -> {recipient}")
            elif status == "error":
                _error(f"Error sending to {recipient}: {task_result.get('error', '')}")
                logger.error(f"[DAEMON] Scheduled email error: {task_id} -> {recipient}: {task_result.get('error', '')}")

        console.print()
        console.print(f"[bold]Results:[/bold] {results['success']} sent, {results['failed']} failed")
        console.print()

        return results["failed"] == 0

    except Exception as e:
        _error(f"Failed to run due tasks: {e}")
        logger.error(f"[DAEMON] Failed to run due tasks: {e}", exc_info=True)
        return False


# =============================================
# ORCHESTRATION
# =============================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle 'schedule' command.

    Args:
        command: Command name (should be 'schedule')
        args: Command arguments (subcommand + subcommand args)

    Returns:
        True if handled, False otherwise
    """
    if command != "schedule":
        return False

    try:
        # No args -- introspection gate
        if not args:
            print_introspection()
            return True

        # Handle help flag
        if args[0] in ['--help', '-h', 'help']:
            _print_help()
            return True

        subcommand = args[0]
        subargs = args[1:]

        json_handler.log_operation("schedule_command", {"subcommand": args[0] if args else "list"})

        # Route to subcommand handlers
        if subcommand == "create":
            return _handle_create(subargs)
        elif subcommand == "list":
            return _handle_list(subargs)
        elif subcommand == "delete":
            return _handle_delete(subargs)
        elif subcommand == "run-due":
            return _handle_run_due(subargs)
        else:
            _error(f"Unknown subcommand: {subcommand}")
            console.print("[dim]Run 'schedule --help' for available commands[/dim]")
            return False

    except Exception as e:
        logger.error(f"[DAEMON] Error in schedule command: {e}", exc_info=True)
        _error(f"Error: {e}")
        return False


# =============================================
# MAIN ENTRY
# =============================================

def main() -> None:
    """Main entry point for direct execution."""
    args = sys.argv[1:]

    if len(args) == 0 or args[0] in ['--help', '-h', 'help']:
        _print_help()
        return

    # First arg is subcommand when called directly
    handle_command('schedule', args)


if __name__ == "__main__":
    main()
