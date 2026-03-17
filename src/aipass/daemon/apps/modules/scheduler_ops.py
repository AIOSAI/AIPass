# =================== AIPass ====================
# Name: scheduler_ops.py
# Description: Scheduler Cron Operations Module
# Version: 2.0.0
# Created: 2026-03-08
# Modified: 2026-03-10
# =============================================

"""
Scheduler operations module -- facade for cron entry point.

Provides a clean module-layer interface over handler functions
used by scheduler_cron.py.
"""

from aipass.daemon.apps.handlers.json import json_handler

try:
    from aipass.cli.apps.modules.display import console
except ImportError:
    from rich.console import Console
    console = Console()

# =============================================
# TASK REGISTRY
# =============================================

try:
    from aipass.daemon.apps.handlers.schedule.task_registry import (
        get_due_tasks as get_due_tasks,
        mark_dispatching as mark_dispatching,
        mark_completed as mark_completed,
        mark_pending as mark_pending,
        recover_stale_dispatches as recover_stale_dispatches,
    )
    TASK_REGISTRY_AVAILABLE = True
except ImportError:
    TASK_REGISTRY_AVAILABLE = False
    get_due_tasks = None  # type: ignore[assignment]
    mark_dispatching = None  # type: ignore[assignment]
    mark_completed = None  # type: ignore[assignment]
    mark_pending = None  # type: ignore[assignment]
    recover_stale_dispatches = None  # type: ignore[assignment]

# =============================================
# ACTION REGISTRY (DPLAN-043)
# =============================================

try:
    from aipass.daemon.apps.handlers.actions.actions_registry import (
        load_registry as load_registry,
        is_action_due as is_action_due,
        update_last_run as update_last_run,
        mark_reminder_completed as mark_reminder_completed,
        migrate_plugins as migrate_plugins,
        next_due_str as next_due_str,
    )
    ACTION_REGISTRY_AVAILABLE = True
except ImportError:
    ACTION_REGISTRY_AVAILABLE = False
    load_registry = None  # type: ignore[assignment]
    is_action_due = None  # type: ignore[assignment]
    update_last_run = None  # type: ignore[assignment]
    mark_reminder_completed = None  # type: ignore[assignment]
    migrate_plugins = None  # type: ignore[assignment]
    next_due_str = None  # type: ignore[assignment]


# =============================================
# INTROSPECTION
# =============================================

def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("scheduler_ops Module")
    console.print("Facade for scheduler_cron.py — re-exports handler functions for cron entry point")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/schedule/")
    console.print("    - task_registry.py (get_due_tasks, mark_dispatching, mark_completed, mark_pending, recover_stale_dispatches — task lifecycle)")
    console.print()
    console.print("  handlers/actions/")
    console.print("    - actions_registry.py (load_registry, is_action_due, update_last_run, mark_reminder_completed, migrate_plugins, next_due_str — action registry)")
    console.print()


# =============================================
# DRONE ROUTING
# =============================================

def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point."""
    if command == "scheduler-ops":
        if not args:
            print_introspection()
            return True
        json_handler.log_operation("scheduler_ops_status")
        console.print()
        console.print("[bold cyan]Scheduler Ops[/bold cyan] - Cron operations facade")
        console.print()
        console.print(f"  [dim]Notifications:[/dim]    archived (Telegram removed)")
        console.print(f"  [dim]Task registry:[/dim]    {TASK_REGISTRY_AVAILABLE}")
        console.print(f"  [dim]Action registry:[/dim]  {ACTION_REGISTRY_AVAILABLE}")
        console.print()
        console.print("[dim]This module is a facade used by scheduler_cron.py.[/dim]")
        console.print()
        return True
    return False
