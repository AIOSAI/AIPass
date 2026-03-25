# =================== AIPass ====================
# Name: scheduler_cron.py
# Description: DAEMON Scheduler Cron Trigger
# Version: 2.0.0
# Created: 2026-02-15
# Modified: 2026-03-24
# =============================================

"""
Cron trigger script for the DAEMON scheduled task system.

Called periodically by cron. Standalone script -- not imported as a module.

Flow:
  1. Acquire single-instance lock
  2. Recover stale dispatches
  3. Process all due tasks (send emails, mark complete)
  4. Process actions from registry
  5. Log summary
"""

# =============================================
# IMPORTS
# =============================================

import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime

import fcntl

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.actions.action_processor import process_actions

# =============================================
# OPTIONAL IMPORTS (via module layer)
# =============================================

# Task registry (via module layer)
try:
    from aipass.daemon.apps.modules.scheduler_ops import (
        get_due_tasks,
        mark_dispatching,
        mark_completed,
        mark_pending,
        recover_stale_dispatches,
        TASK_REGISTRY_AVAILABLE,
    )
except ImportError as e:
    logger.info(f"Optional dependency not available: scheduler_ops task registry ({e})")
    TASK_REGISTRY_AVAILABLE = False
    get_due_tasks = None
    mark_dispatching = None
    mark_completed = None
    mark_pending = None
    recover_stale_dispatches = None

# Email integration via drone subprocess
def _send_email_via_drone(to_branch, subject, message, from_branch='@daemon',
                          auto_execute=True, reply_to=None, **kwargs):
    """Send email via drone @ai_mail send subprocess."""
    cmd = ["drone", "@ai_mail", "send", to_branch, subject, message]
    if auto_execute:
        cmd.append("--dispatch")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning(f"Drone email subprocess failed: {e}")
        return False

AI_MAIL_AVAILABLE = True
send_email_direct = _send_email_via_drone


# =============================================
# CONSTANTS
# =============================================

_DAEMON_ROOT = Path(__file__).resolve().parents[2]  # src/aipass/daemon/
JSON_DIR = _DAEMON_ROOT / "daemon_json"

EVENT_NAME = "cron-run"
LOCK_FILE = JSON_DIR / "schedule.lock"
STALE_DISPATCH_MAX_AGE = 5  # minutes


# =============================================
# LOGGING
# =============================================

def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("scheduler_cron Module")
    console.print("Cron trigger for scheduled tasks and action registry processing")
    console.print()
    console.print("Connected Handlers:")
    console.print("  modules/")
    console.print("    - scheduler_ops.py (task registry ops + action registry ops, notifications archived)")
    console.print()
    console.print("  plugins/")
    console.print("    - discover_plugins (plugin discovery and scheduled execution)")
    console.print()


def print_help() -> None:
    """Display usage information for scheduler_cron."""
    console.print("\n[bold cyan]scheduler_cron.py - DAEMON Scheduler Cron Trigger[/bold cyan]")
    console.print("\n[yellow]USAGE:[/yellow]")
    console.print("  drone @daemon scheduler_cron          Run the cron scheduler")
    console.print("  drone @daemon scheduler_cron --help   Show this help message")
    console.print("\n[yellow]DESCRIPTION:[/yellow]")
    console.print("  Processes due scheduled tasks and actions from the registry.")
    console.print("  Intended to be called periodically by cron.")
    console.print()


def log(message: str) -> None:
    """Print timestamped log line to stdout (captured by cron redirect)."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    console.print(f"[{timestamp}] {message}")


# =============================================
# TASK PROCESSING
# =============================================

def process_due_tasks() -> dict:
    """
    Process all due scheduled tasks.

    Recovers stale dispatches, then iterates due tasks:
    mark dispatching -> send email -> mark completed or reset to pending.

    Returns:
        Dict with keys: due, success, failed, errors (list of error strings)
    """
    results = {
        "due": 0,
        "success": 0,
        "failed": 0,
        "recovered": 0,
        "errors": [],
    }

    if not TASK_REGISTRY_AVAILABLE:
        log("WARNING: Task registry not available, skipping task processing")
        return results

    # Recover any stale dispatches (stuck > 5 minutes)
    try:
        recovered = recover_stale_dispatches(max_age_minutes=STALE_DISPATCH_MAX_AGE)  # type: ignore[misc]
        results["recovered"] = recovered
        if recovered:
            log(f"Recovered {recovered} stale dispatch(es)")
    except Exception as e:
        logger.warning(f"Failed to recover stale dispatches: {e}")
        log(f"WARNING: Failed to recover stale dispatches: {e}")
        results["errors"].append(f"Stale recovery: {e}")

    # Get due tasks
    try:
        due_tasks = get_due_tasks()  # type: ignore[misc]
    except Exception as e:
        logger.error(f"Failed to load due tasks: {e}")
        log(f"ERROR: Failed to load due tasks: {e}")
        results["errors"].append(f"Load tasks: {e}")
        return results

    results["due"] = len(due_tasks)

    if not due_tasks:
        log("No tasks due at this time.")
        return results

    log(f"Found {len(due_tasks)} due task(s)")

    # Process each due task
    for task in due_tasks:
        task_id = task.get("id", "")
        recipient = task.get("recipient", "")
        task_desc = task.get("task", "")
        message = task.get("message", "")

        log(f"Processing: {task_id[:8]} -> {recipient}: {task_desc[:50]}")

        # Mark as dispatching (prevents re-dispatch)
        try:
            mark_dispatching(task_id)  # type: ignore[misc]
        except Exception as e:
            logger.warning(f"Failed to mark dispatching {task_id[:8]}: {e}")
            log(f"WARNING: Failed to mark dispatching {task_id[:8]}: {e}")
            results["errors"].append(f"Mark dispatching {task_id[:8]}: {e}")
            results["failed"] += 1
            continue

        # Build email body
        email_body = f"{task_desc}"
        if message:
            email_body += f"\n\nDetails:\n{message}"

        # Send the email
        if not AI_MAIL_AVAILABLE:
            log(f"SKIP: ai_mail not available, cannot send to {recipient}")
            mark_pending(task_id)  # type: ignore[misc]
            results["failed"] += 1
            results["errors"].append(f"ai_mail unavailable for {task_id[:8]}")
            continue

        try:
            email_sent = send_email_direct(
                to_branch=recipient,
                subject=f"[SCHEDULED] {task_desc}",
                message=email_body,
                from_branch='@daemon',
                auto_execute=True,
                reply_to='@dev_central',
            )

            if email_sent:
                mark_completed(task_id)  # type: ignore[misc]
                log(f"OK: Sent to {recipient}: {task_desc[:40]}")
                results["success"] += 1
            else:
                mark_pending(task_id)  # type: ignore[misc]
                log(f"FAIL: Email returned False for {recipient}: {task_desc[:40]}")
                results["failed"] += 1
                results["errors"].append(f"Email failed: {task_id[:8]} -> {recipient}")

        except Exception as e:
            # Reset to pending for retry on next run
            try:
                mark_pending(task_id)  # type: ignore[misc]
            except Exception as reset_err:
                logger.warning(f"Best-effort reset to pending failed for {task_id[:8]}: {reset_err}")
            logger.error(f"Exception sending to {recipient}: {e}")
            log(f"ERROR: Exception sending to {recipient}: {e}")
            results["failed"] += 1
            results["errors"].append(f"Email error {task_id[:8]}: {e}")

        # Small delay between dispatches (prevents thundering herd)
        time.sleep(1.0)

    return results



def _next_cron_run() -> str:
    """Calculate approximate next scheduler cron run time."""
    now = datetime.now()
    if now.minute < 30:
        next_min = 30
        next_hour = now.hour
    else:
        next_min = 0
        next_hour = (now.hour + 1) % 24
    return f"{next_hour:02d}:{next_min:02d}"




# =============================================
# MAIN
# =============================================

def main() -> int:
    """
    Main cron entry point.

    Returns:
        0 on success, 1 on error
    """
    args = sys.argv[1:]

    if not args:
        print_introspection()
        return 0

    if args[0] in ['--help', '-h']:
        print_help()
        sys.exit(0)

    json_handler.log_operation("cron_run")
    log("=" * 60)
    log("Scheduler cron triggered")

    # Ensure lock directory exists
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Acquire single-instance lock (non-blocking, stdlib fcntl)
    lock_fd = open(LOCK_FILE, "w", encoding="utf-8")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        logger.warning(f"Scheduler lock acquisition failed (another instance running): {e}")
        log("Another instance already running, skipping.")
        lock_fd.close()
        return 0

    try:
        return _run_locked()
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _run_locked() -> int:
    """Execute the cron job while holding the lock."""
    exit_code = 0

    # Step 1: Process due tasks
    try:
        results = process_due_tasks()
    except Exception as e:
        logger.error(f"Unhandled error in process_due_tasks: {e}", exc_info=True)
        log(f"CRITICAL: Unhandled error in process_due_tasks: {e}")
        return 1

    # Step 2: Process actions from registry
    action_results = {
        "total": 0, "enabled": 0, "executed": 0, "failed": 0,
        "errors": [], "executed_actions": [], "skipped_actions": [],
    }
    try:
        action_results = process_actions(log_fn=log, send_email_fn=send_email_direct)
    except Exception as e:
        logger.warning(f"Unhandled error in process_actions: {e}")
        log(f"WARNING: Unhandled error in process_actions: {e}")
        action_results["errors"].append(f"Action processing: {e}")

    # Step 3: Build summary
    lines = []

    # Tasks section
    if results["recovered"]:
        lines.append(f"Recovered {results['recovered']} stale dispatch(es)")
    if results["due"] or results["success"]:
        task_line = f"Tasks: {results['due']} due | {results['success']} sent"
        if results["failed"]:
            task_line += f" | {results['failed']} failed"
        lines.append(task_line)
    else:
        lines.append("Tasks: none due")

    # Actions section
    executed = action_results.get("executed_actions", [])
    skipped = action_results.get("skipped_actions", [])
    if executed:
        for a in executed:
            lines.append(f"  {a['id']} {a['name']} -> {a['branch']} OK")
    if skipped:
        for a in skipped:
            lines.append(f"  {a['id']} {a['name']} -> {a['branch']} (next: {a['next_due']})")
    if not executed and not skipped:
        lines.append("Actions: none enabled")
    if action_results["failed"]:
        lines.append(f"Action failures: {action_results['failed']}")

    # Next run
    lines.append(f"Next: ~{_next_cron_run()}")

    summary = "\n".join(lines)

    log(f"Results: {summary}")

    # Step 4: Determine exit code
    if results["failed"] > 0 or results["errors"] or action_results["failed"] > 0 or action_results["errors"]:
        exit_code = 1

    log("Scheduler cron finished")
    log("=" * 60)
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # Last-resort catch -- never crash silently
        logger.error(f"FATAL scheduler_cron exception: {e}", exc_info=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        console.print(f"[{timestamp}] FATAL: Unhandled exception: {e}")
        sys.exit(1)
