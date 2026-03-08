
# ===================AIPASS====================
# META DATA HEADER
# Name: schedule.py - DAEMON Scheduled Follow-ups Module
# Date: 2026-02-04
# Version: 1.0.0
# Category: daemon/modules
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-02-04): Initial implementation - fire-and-forget scheduled tasks
#
# CODE STANDARDS:
#   - Seed pattern compliance - console.print() for all output
#   - Thin orchestration - handlers implement logic
#   - Type hints on all functions
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

import logging
logger = logging.getLogger(__name__)

from rich.console import Console
console = Console()

def _header(text):
    console.print(f"\n[bold cyan]{'='*70}[/bold cyan]")
    console.print(f"[bold cyan]  {text}[/bold cyan]")
    console.print(f"[bold cyan]{'='*70}[/bold cyan]")

def _success(text):
    console.print(f"[green]OK:[/green] {text}")

def _error(text):
    console.print(f"[red]ERROR:[/red] {text}")

# Handler imports
from aipass.daemon.apps.handlers.schedule.task_registry import (
    load_tasks, create_task, delete_task, get_due_tasks, mark_completed, parse_due_date,
    mark_dispatching, mark_pending, recover_stale_dispatches
)

# File lock for single-instance execution
try:
    from filelock import FileLock, Timeout
    FILELOCK_AVAILABLE = True
except ImportError:
    FILELOCK_AVAILABLE = False

# Email integration (optional)
try:
    from ai_mail.apps.modules.email import send_email_direct
    AI_MAIL_AVAILABLE = True
except ImportError:
    AI_MAIL_AVAILABLE = False
    send_email_direct = None

# =============================================
# CONSTANTS
# =============================================

MODULE_NAME = "schedule"

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
        console.print("[red]Usage: schedule create \"task\" --due <date> --to @branch [--message \"details\"][/red]")
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
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    # Try to acquire lock (non-blocking)
    lock = FileLock(lock_file, timeout=0)
    try:
        with lock.acquire(timeout=0):
            return _process_due_tasks()
    except Timeout:
        console.print("[dim]Schedule run-due already in progress, skipping.[/dim]")
        return True


def _process_due_tasks() -> bool:
    """Process due tasks sequentially with status tracking."""
    import time

    try:
        # Recover any stale dispatches (stuck > 5 minutes)
        recovered = recover_stale_dispatches(max_age_minutes=5)
        if recovered:
            console.print(f"[dim]Recovered {recovered} stale dispatch(es)[/dim]")

        due_tasks = get_due_tasks()

        if not due_tasks:
            console.print("[dim]No tasks due at this time.[/dim]")
            return True

        console.print()
        _header(f"Running {len(due_tasks)} Due Task(s)")
        console.print()

        success_count = 0
        fail_count = 0

        for task in due_tasks:
            task_id = task.get("id", "")
            recipient = task.get("recipient", "")
            task_desc = task.get("task", "")
            message = task.get("message", "")

            # Mark as dispatching (prevents re-dispatch)
            mark_dispatching(task_id)

            # Build email body
            email_body = f"{task_desc}"
            if message:
                email_body += f"\n\nDetails:\n{message}"

            # Send the email
            if not AI_MAIL_AVAILABLE:
                mark_pending(task_id)
                _error(f"ai_mail not available, cannot send to {recipient}")
                fail_count += 1
                continue

            try:
                email_sent = send_email_direct(
                    to_branch=recipient,
                    subject=f"[SCHEDULED] {task_desc}",
                    message=email_body,
                    from_branch='@daemon',
                    auto_execute=True,
                    reply_to='@dev_central'
                )

                if email_sent:
                    mark_completed(task_id)
                    _success(f"Sent to {recipient}: {task_desc[:40]}")
                    success_count += 1
                    logger.info(f"[DAEMON] Scheduled email sent: {task_id[:8]} -> {recipient}")
                else:
                    # Reset to pending for retry
                    mark_pending(task_id)
                    _error(f"Failed to send to {recipient}: {task_desc[:40]}")
                    fail_count += 1
                    logger.error(f"[DAEMON] Scheduled email failed: {task_id[:8]} -> {recipient}")

            except Exception as e:
                # Reset to pending for retry
                mark_pending(task_id)
                _error(f"Error sending to {recipient}: {e}")
                fail_count += 1
                logger.error(f"[DAEMON] Scheduled email error: {task_id[:8]} -> {recipient}: {e}")

            # Small delay between dispatches (prevents thundering herd)
            time.sleep(1.0)

        console.print()
        console.print(f"[bold]Results:[/bold] {success_count} sent, {fail_count} failed")
        console.print()

        return fail_count == 0

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
        # Handle help flag
        if not args or args[0] in ['--help', '-h', 'help']:
            _print_help()
            return True

        subcommand = args[0]
        subargs = args[1:]

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
