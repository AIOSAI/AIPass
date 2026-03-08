
# ===================AIPASS====================
# META DATA HEADER
# Name: task_registry.py - DAEMON Scheduled Tasks Registry
# Date: 2026-02-04
# Version: 1.0.0
# Category: daemon/handlers/schedule
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-02-04): Initial implementation - task storage and operations
#
# CODE STANDARDS:
#   - Handlers implement logic, modules orchestrate
#   - No cross-branch imports, no Prax logger
# =============================================

"""
Handler for scheduled task storage and operations.

Fire-and-forget follow-up system for DAEMON.
Tasks are stored in daemon_json/schedule.json and processed
when their due date arrives.
"""

import json
import uuid
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import re

# =============================================
# CONSTANTS
# =============================================

_DAEMON_ROOT = Path(__file__).resolve().parents[3]  # src/aipass/daemon/
SCHEDULE_JSON_PATH = _DAEMON_ROOT / "daemon_json" / "schedule.json"

DEFAULT_SCHEDULE_DATA: Dict[str, Any] = {
    "tasks": []
}

# =============================================
# JSON FILE OPERATIONS
# =============================================

def _ensure_json_exists() -> None:
    """Ensure schedule.json exists, create with defaults if missing."""
    SCHEDULE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not SCHEDULE_JSON_PATH.exists():
        with open(SCHEDULE_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_SCHEDULE_DATA, f, indent=2, ensure_ascii=False)


def load_tasks() -> List[Dict[str, Any]]:
    """
    Load all tasks from schedule.json.

    Returns:
        List of task dictionaries
    """
    _ensure_json_exists()

    try:
        with open(SCHEDULE_JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("tasks", [])
    except (json.JSONDecodeError, IOError):
        return []


def save_tasks(tasks: List[Dict[str, Any]]) -> bool:
    """
    Save tasks to schedule.json.

    Args:
        tasks: List of task dictionaries to save

    Returns:
        True if successful, False otherwise
    """
    _ensure_json_exists()

    try:
        data = {"tasks": tasks}
        with open(SCHEDULE_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except IOError:
        return False


# =============================================
# DATE PARSING
# =============================================

def parse_due_date(date_str: str) -> str:
    """
    Parse various date formats to ISO 8601 date string.

    Supports:
        - "7d" -> 7 days from now
        - "1w" -> 1 week from now
        - "2w" -> 2 weeks from now
        - "2026-02-11" -> exact date (ISO 8601)

    Args:
        date_str: Date string in supported format

    Returns:
        ISO 8601 date string (YYYY-MM-DD)

    Raises:
        ValueError: If date format is invalid
    """
    date_str = date_str.strip()
    today = datetime.now().date()

    # Check for relative day format: "7d", "14d", etc.
    day_match = re.match(r'^(\d+)d$', date_str, re.IGNORECASE)
    if day_match:
        days = int(day_match.group(1))
        future_date = today + timedelta(days=days)
        return future_date.isoformat()

    # Check for relative week format: "1w", "2w", etc.
    week_match = re.match(r'^(\d+)w$', date_str, re.IGNORECASE)
    if week_match:
        weeks = int(week_match.group(1))
        future_date = today + timedelta(weeks=weeks)
        return future_date.isoformat()

    # Check for ISO 8601 date format: "2026-02-11"
    iso_match = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', date_str)
    if iso_match:
        try:
            # Validate it's a real date
            year = int(iso_match.group(1))
            month = int(iso_match.group(2))
            day = int(iso_match.group(3))
            parsed_date = datetime(year, month, day).date()
            return parsed_date.isoformat()
        except ValueError as e:
            raise ValueError(f"Invalid date: {date_str}") from e

    raise ValueError(
        f"Invalid date format: '{date_str}'. "
        "Use '7d' (days), '1w' (weeks), or 'YYYY-MM-DD' (ISO date)"
    )


# =============================================
# TASK OPERATIONS
# =============================================

def _generate_task_id() -> str:
    """Generate 8-character UUID for task ID."""
    return uuid.uuid4().hex[:8]


def create_task(
    task: str,
    due_date: str,
    recipient: str,
    message: str
) -> Dict[str, Any]:
    """
    Create a new scheduled task.

    Args:
        task: Brief description of the task/follow-up
        due_date: When to trigger (supports "7d", "1w", "YYYY-MM-DD")
        recipient: Target branch (e.g., "@dev_central")
        message: Message to deliver when due

    Returns:
        Created task dictionary

    Raises:
        ValueError: If due_date format is invalid
    """
    parsed_due = parse_due_date(due_date)

    new_task: Dict[str, Any] = {
        "id": _generate_task_id(),
        "created": datetime.now().date().isoformat(),
        "due_date": parsed_due,
        "task": task,
        "recipient": recipient,
        "message": message,
        "status": "pending"
    }

    tasks = load_tasks()
    tasks.append(new_task)
    save_tasks(tasks)

    return new_task


def delete_task(task_id: str) -> bool:
    """
    Delete a task by ID.

    Args:
        task_id: 8-character task ID

    Returns:
        True if task was found and deleted, False otherwise
    """
    tasks = load_tasks()
    original_count = len(tasks)

    tasks = [t for t in tasks if t.get("id") != task_id]

    if len(tasks) < original_count:
        save_tasks(tasks)
        return True

    return False


def get_due_tasks() -> List[Dict[str, Any]]:
    """
    Get all tasks that are due (due_date <= today).

    Only returns tasks with status 'pending' - excludes 'dispatching' and 'completed'.

    Returns:
        List of tasks that are due for processing
    """
    tasks = load_tasks()
    today = datetime.now().date().isoformat()

    due_tasks = [
        t for t in tasks
        if t.get("status") == "pending" and t.get("due_date", "") <= today
    ]

    return due_tasks


def mark_dispatching(task_id: str) -> bool:
    """
    Mark a task as currently being dispatched.

    Prevents re-dispatch while email is being sent.

    Args:
        task_id: 8-character task ID

    Returns:
        True if task was found and marked, False otherwise
    """
    tasks = load_tasks()

    for task in tasks:
        if task.get("id") == task_id:
            task["status"] = "dispatching"
            task["dispatch_started"] = datetime.now().isoformat()
            save_tasks(tasks)
            return True

    return False


def mark_pending(task_id: str) -> bool:
    """
    Reset a task to pending status (for retry after failed dispatch).

    Args:
        task_id: 8-character task ID

    Returns:
        True if task was found and reset, False otherwise
    """
    tasks = load_tasks()

    for task in tasks:
        if task.get("id") == task_id:
            task["status"] = "pending"
            task.pop("dispatch_started", None)
            save_tasks(tasks)
            return True

    return False


def recover_stale_dispatches(max_age_minutes: int = 5) -> int:
    """
    Reset tasks stuck in 'dispatching' status for too long.

    Called before processing to recover from crashed dispatches.

    Args:
        max_age_minutes: Maximum time a task can be in dispatching status

    Returns:
        Number of tasks recovered
    """
    tasks = load_tasks()
    recovered = 0
    cutoff = datetime.now() - timedelta(minutes=max_age_minutes)

    for task in tasks:
        if task.get("status") == "dispatching":
            started = task.get("dispatch_started")
            if started:
                try:
                    start_time = datetime.fromisoformat(started)
                    if start_time < cutoff:
                        task["status"] = "pending"
                        task.pop("dispatch_started", None)
                        recovered += 1
                except ValueError:
                    # Invalid timestamp, reset anyway
                    task["status"] = "pending"
                    task.pop("dispatch_started", None)
                    recovered += 1

    if recovered:
        save_tasks(tasks)

    return recovered


def mark_completed(task_id: str) -> bool:
    """
    Mark a task as completed.

    Args:
        task_id: 8-character task ID

    Returns:
        True if task was found and marked, False otherwise
    """
    tasks = load_tasks()

    for task in tasks:
        if task.get("id") == task_id:
            task["status"] = "completed"
            task["completed_date"] = datetime.now().date().isoformat()
            save_tasks(tasks)
            return True

    return False


def get_task_by_id(task_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a single task by ID.

    Args:
        task_id: 8-character task ID

    Returns:
        Task dictionary if found, None otherwise
    """
    tasks = load_tasks()

    for task in tasks:
        if task.get("id") == task_id:
            return task

    return None


def get_pending_tasks() -> List[Dict[str, Any]]:
    """
    Get all pending tasks (not yet due or completed).

    Returns:
        List of pending tasks
    """
    tasks = load_tasks()
    return [t for t in tasks if t.get("status") == "pending"]


# =============================================
# MAIN - Testing
# =============================================

if __name__ == "__main__":
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    console.print()
    console.print(Panel.fit(
        "[bold cyan]TASK REGISTRY - Handler Test[/bold cyan]",
        border_style="bright_blue"
    ))
    console.print()

    # Test date parsing
    console.print("[yellow]Testing date parsing:[/yellow]")
    test_dates = ["7d", "1w", "2w", "2026-03-15"]
    for d in test_dates:
        try:
            result = parse_due_date(d)
            console.print(f"  {d} -> {result}")
        except ValueError as e:
            console.print(f"  {d} -> [red]ERROR: {e}[/red]")

    # Test invalid date
    try:
        parse_due_date("invalid")
    except ValueError as e:
        console.print(f"  invalid -> [green]Correctly raised: {e}[/green]")

    console.print()
    console.print("[yellow]Testing task creation:[/yellow]")

    # Create a test task
    test_task = create_task(
        task="Test backup health check",
        due_date="7d",
        recipient="@dev_central",
        message="Please verify backup systems are healthy"
    )
    console.print(f"  Created task: {test_task['id']}")
    console.print(f"  Due: {test_task['due_date']}")

    # Show all tasks
    console.print()
    console.print("[yellow]Current tasks:[/yellow]")
    all_tasks = load_tasks()

    table = Table(show_header=True)
    table.add_column("ID", style="cyan")
    table.add_column("Task", style="white")
    table.add_column("Due", style="yellow")
    table.add_column("Status", style="green")

    for t in all_tasks:
        table.add_row(
            t.get("id", "?"),
            t.get("task", "?")[:30],
            t.get("due_date", "?"),
            t.get("status", "?")
        )

    console.print(table)
    console.print()
    console.print(f"[dim]Schedule file: {SCHEDULE_JSON_PATH}[/dim]")
    console.print()
