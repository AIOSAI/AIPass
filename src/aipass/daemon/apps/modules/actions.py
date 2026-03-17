# =================== AIPass ====================
# Name: actions.py
# Description: Action Registry CLI Module
# Version: 1.0.0
# Created: 2026-03-02
# Modified: 2026-03-02
# =============================================

"""
CLI interface for the numbered action registry.
"""

# =============================================
# IMPORTS
# =============================================

import sys
from typing import List

from aipass.prax import logger

from aipass.cli.apps.modules import console, error as cli_error

def _header(text):
    console.print(f"\n[bold cyan]{'='*70}[/bold cyan]")
    console.print(f"[bold cyan]  {text}[/bold cyan]")
    console.print(f"[bold cyan]{'='*70}[/bold cyan]")

def _success(text):
    console.print(f"[green]OK:[/green] {text}")

def _error(text):
    cli_error(text)

from aipass.daemon.apps.handlers.actions.actions_registry import (
    list_actions,
    get_action,
    toggle_action,
    delete_action,
    create_action,
    migrate_plugins,
    next_due_str,
)
from aipass.daemon.apps.handlers.json import json_handler

# =============================================
# CONSTANTS
# =============================================

MODULE_NAME = "actions"


# =============================================
# INTROSPECTION
# =============================================

def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("actions Module")
    console.print("CLI interface for the numbered action registry (DPLAN-043)")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/actions/")
    console.print("    - actions_registry.py (list_actions, get_action, toggle_action, delete_action, create_action, migrate_plugins, next_due_str — registry CRUD)")
    console.print()


# =============================================
# OUTPUT FORMATTING
# =============================================

def _print_actions_table(actions: list) -> None:
    """Display formatted action list as a table."""
    console.print()
    _header("Action Registry")
    console.print()

    if not actions:
        console.print("[dim]No actions registered. Run 'actions migrate' to import plugins.[/dim]")
        console.print()
        return

    # Header row
    console.print(
        f"  {'ID':<6} {'ON':<4} {'NAME':<24} {'TYPE':<10} "
        f"{'TARGET':<16} {'SCHEDULE':<20} {'NEXT DUE':<16}"
    )
    console.print("  " + "-" * 96)

    for action in actions:
        action_id = action.get("id", "????")
        enabled = "[green]ON[/green] " if action.get("enabled") else "[red]OFF[/red]"
        name = action.get("name", "")[:22]
        action_type = action.get("type", "")[:8]
        target = action.get("target_branch", "")[:14]
        schedule_type = action.get("schedule_type", "")

        # Build schedule display
        if schedule_type == "daily":
            schedule_str = f"daily @ {action.get('time', '??:??')}"
        elif schedule_type == "hourly":
            m = action.get("time", "0")
            schedule_str = f"hourly @ :{int(m):02d}"
        elif schedule_type == "interval":
            mins = action.get("interval_minutes", 0)
            if mins >= 60:
                schedule_str = f"every {mins // 60}h"
            else:
                schedule_str = f"every {mins}m"
        elif schedule_type == "once":
            schedule_str = f"once: {action.get('due_date', '?')}"
        else:
            schedule_str = schedule_type

        next_due = next_due_str(action)

        console.print(
            f"  {action_id:<6} {enabled:<4} {name:<24} {action_type:<10} "
            f"  {target:<16} {schedule_str:<20} {next_due:<16}"
        )

    console.print()
    enabled_count = sum(1 for a in actions if a.get("enabled"))
    console.print(f"  [dim]Total: {len(actions)} actions ({enabled_count} enabled)[/dim]")
    console.print()


def _print_action_detail(action: dict) -> None:
    """Display detailed view of a single action."""
    console.print()
    _header(f"Action {action['id']}: {action['name']}")
    console.print()

    fields = [
        ("ID", action.get("id")),
        ("Name", action.get("name")),
        ("Type", action.get("type")),
        ("Enabled", "[green]ON[/green]" if action.get("enabled") else "[red]OFF[/red]"),
        ("Schedule", action.get("schedule_type")),
        ("Time", action.get("time")),
        ("Interval", f"{action.get('interval_minutes')}m" if action.get("interval_minutes") else None),
        ("Due Date", action.get("due_date")),
        ("Target", action.get("target_branch")),
        ("Fresh", action.get("fresh")),
        ("Max Turns", action.get("max_turns")),
        ("Self Dispatch", action.get("self_dispatch")),
        ("Plugin File", action.get("plugin_file")),
        ("Last Run", action.get("last_run", "never")[:19] if action.get("last_run") else "never"),
        ("Next Run", next_due_str(action)),
        ("Created", action.get("created", "")[:19]),
        ("Completed", action.get("completed")),
    ]

    for label, value in fields:
        if value is None:
            continue
        console.print(f"  [cyan]{label:<16}[/cyan] {value}")

    # Show prompt (truncated for readability)
    prompt = action.get("prompt", "")
    if prompt:
        console.print()
        console.print("  [cyan]Prompt:[/cyan]")
        # Show first 200 chars
        display_prompt = prompt[:200]
        if len(prompt) > 200:
            display_prompt += "..."
        for line in display_prompt.split("\n"):
            console.print(f"    [dim]{line}[/dim]")

    console.print()


def print_help() -> None:
    """Display help using Rich formatted output."""
    console.print()
    _header("Actions -- Numbered Action Registry")
    console.print()

    console.print("[yellow]USAGE:[/yellow]")
    console.print("  drone @daemon actions list")
    console.print("  drone @daemon actions <id> info")
    console.print("  drone @daemon actions <id> on")
    console.print("  drone @daemon actions <id> off")
    console.print('  drone @daemon actions set reminder <date> "message" [--to @branch]')
    console.print('  drone @daemon actions set schedule @branch "prompt" <type> [time]')
    console.print("  drone @daemon actions migrate")
    console.print("  drone @daemon actions delete <id>")
    console.print()

    console.print("[yellow]COMMANDS:[/yellow]")
    console.print("  list         List all registered actions with status")
    console.print("  <id> info    Show detailed view of a single action")
    console.print("  <id> on      Enable an action")
    console.print("  <id> off     Disable an action")
    console.print("  set          Create a new reminder or schedule")
    console.print("  migrate      Import existing plugins into registry")
    console.print("  delete <id>  Remove an action from the registry")
    console.print()

    console.print("[yellow]SET REMINDER:[/yellow]")
    console.print('  set reminder 2026-03-11 "Check VERA progress"')
    console.print('  set reminder 7d "Follow up on PR review" --to @flow')
    console.print("  [dim]Date formats: YYYY-MM-DD, 1d, 7d, 1w, 2w[/dim]")
    console.print()

    console.print("[yellow]SET SCHEDULE:[/yellow]")
    console.print('  set schedule @seed "Run audit" daily 04:00')
    console.print('  set schedule @vera "Heartbeat" interval 240')
    console.print('  set schedule @flow "Check plans" hourly 30')
    console.print("  [dim]Types: daily HH:MM, hourly MM, interval MINUTES[/dim]")
    console.print()

    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  actions list                                    # See all actions")
    console.print("  actions 0003 off                                # Disable action 3")
    console.print("  actions 0003 on                                 # Re-enable it")
    console.print('  actions set reminder 2026-03-11 "check VERA"    # One-shot reminder')
    console.print()


# =============================================
# SUBCOMMAND HANDLERS
# =============================================

def _handle_list(_args: List[str]) -> bool:
    """Handle 'actions list' subcommand."""
    actions = list_actions()
    _print_actions_table(actions)
    return True


def _handle_toggle(action_id: str, enable: bool) -> bool:
    """Handle 'actions <id> on/off' subcommand."""
    action = get_action(action_id)
    if action is None:
        _error(f"Action not found: {action_id}")
        return False

    toggle_action(action_id, enable)
    state = "enabled" if enable else "disabled"
    _success(f"Action {action_id} ({action['name']}) {state}")
    return True


def _handle_info(action_id: str) -> bool:
    """Handle 'actions <id> info' subcommand."""
    action = get_action(action_id)
    if action is None:
        _error(f"Action not found: {action_id}")
        return False

    _print_action_detail(action)
    return True


def _handle_set_reminder(args: List[str]) -> bool:
    """Handle 'actions set reminder <date> "message" [--to @branch]'."""
    if len(args) < 2:
        _error('Usage: actions set reminder <date> "message" [--to @branch]')
        return False

    date_str = args[0]
    message = args[1]
    target_branch = "@dev_central"  # Default reminder target

    # Parse --to flag
    if "--to" in args:
        to_idx = args.index("--to")
        if to_idx + 1 < len(args):
            target_branch = args[to_idx + 1]

    # Parse date
    due_date = _parse_date(date_str)
    if not due_date:
        _error(f"Invalid date format: {date_str}")
        console.print("[dim]Valid formats: YYYY-MM-DD, 1d, 7d, 1w, 2w[/dim]")
        return False

    action = create_action(
        name=message[:50],
        action_type="reminder",
        schedule_type="once",
        target_branch=target_branch,
        prompt=message,
        due_date=due_date,
        fresh=True,
        max_turns=10,
        enabled=True,
    )

    _success(f"Reminder created: {action['id']}")
    console.print(f"  [dim]Due:[/dim]    {due_date}")
    console.print(f"  [dim]To:[/dim]     {target_branch}")
    console.print(f"  [dim]Message:[/dim] {message[:60]}")
    console.print()
    return True


def _handle_set_schedule(args: List[str]) -> bool:
    """Handle 'actions set schedule @branch "prompt" <type> [time_spec]'."""
    if len(args) < 3:
        _error('Usage: actions set schedule @branch "prompt" <daily|hourly|interval> [time_spec]')
        return False

    target_branch = args[0]
    prompt = args[1]
    schedule_type = args[2]

    time_val = None
    interval_minutes = None

    if schedule_type == "daily":
        if len(args) < 4:
            _error("Daily schedule requires time: actions set schedule @branch \"prompt\" daily HH:MM")
            return False
        time_val = args[3]
    elif schedule_type == "hourly":
        if len(args) < 4:
            _error("Hourly schedule requires minute: actions set schedule @branch \"prompt\" hourly MM")
            return False
        time_val = args[3]
    elif schedule_type == "interval":
        if len(args) < 4:
            _error("Interval schedule requires minutes: actions set schedule @branch \"prompt\" interval MINUTES")
            return False
        try:
            interval_minutes = int(args[3])
        except ValueError:
            _error(f"Invalid interval minutes: {args[3]}")
            return False
    else:
        _error(f"Unknown schedule type: {schedule_type}")
        console.print("[dim]Valid types: daily, hourly, interval[/dim]")
        return False

    # Generate a name from the prompt
    name = prompt[:50].replace(" ", "_").lower()

    action = create_action(
        name=name,
        action_type="schedule",
        schedule_type=schedule_type,
        target_branch=target_branch,
        prompt=prompt,
        time=time_val,
        interval_minutes=interval_minutes,
        fresh=True,
        max_turns=50,
        enabled=True,
    )

    _success(f"Schedule created: {action['id']}")
    console.print(f"  [dim]Name:[/dim]   {action['name']}")
    console.print(f"  [dim]Target:[/dim] {target_branch}")
    console.print(f"  [dim]Type:[/dim]   {schedule_type}")
    if time_val:
        console.print(f"  [dim]Time:[/dim]   {time_val}")
    if interval_minutes:
        console.print(f"  [dim]Every:[/dim]  {interval_minutes} minutes")
    console.print()
    return True


def _handle_migrate(_args: List[str]) -> bool:
    """Handle 'actions migrate' -- import plugins into registry."""
    console.print()
    console.print("[dim]Scanning plugins/ for unregistered plugins...[/dim]")

    count = migrate_plugins()

    if count > 0:
        _success(f"Migrated {count} plugin(s) into the action registry")
    else:
        console.print("[dim]All plugins already registered (or none found).[/dim]")

    # Show the updated list
    actions = list_actions()
    _print_actions_table(actions)
    return True


def _handle_delete(args: List[str]) -> bool:
    """Handle 'actions delete <id>'."""
    if not args:
        _error("Action ID required: actions delete <id>")
        return False

    action_id = args[0]
    action = get_action(action_id)
    if action is None:
        _error(f"Action not found: {action_id}")
        return False

    delete_action(action_id)
    _success(f"Deleted action {action_id}: {action['name']}")
    return True


# =============================================
# DATE PARSING
# =============================================

def _parse_date(date_str: str) -> str:
    """
    Parse a date string into ISO format.

    Supports: YYYY-MM-DD, 1d, 7d, 1w, 2w

    Returns:
        ISO date string or empty string on failure.
    """
    from datetime import datetime, timedelta

    date_str = date_str.strip()

    # Relative dates
    if date_str.endswith("d"):
        try:
            days = int(date_str[:-1])
            return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        except ValueError:
            return ""
    elif date_str.endswith("w"):
        try:
            weeks = int(date_str[:-1])
            return (datetime.now() + timedelta(weeks=weeks)).strftime("%Y-%m-%d")
        except ValueError:
            return ""

    # ISO date
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        return ""


# =============================================
# ORCHESTRATION
# =============================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle 'actions' command and route to subcommands.

    Args:
        command: Command name (should be 'actions')
        args: Command arguments

    Returns:
        True if handled, False otherwise
    """
    if command != "actions":
        return False

    try:
        # No args -- introspection gate
        if not args:
            print_introspection()
            return True

        # Help flag
        if args[0] in ['--help', '-h', 'help']:
            print_help()
            return True

        subcommand = args[0]

        json_handler.log_operation("actions_command", {"subcommand": args[0] if args else "introspection"})

        # Named subcommands
        if subcommand == "list":
            return _handle_list(args[1:])
        elif subcommand == "migrate":
            return _handle_migrate(args[1:])
        elif subcommand == "delete":
            return _handle_delete(args[1:])
        elif subcommand == "set":
            # actions set reminder ... / actions set schedule ...
            if len(args) < 2:
                _error("Usage: actions set <reminder|schedule> ...")
                return False
            set_type = args[1]
            if set_type == "reminder":
                return _handle_set_reminder(args[2:])
            elif set_type == "schedule":
                return _handle_set_schedule(args[2:])
            else:
                _error(f"Unknown set type: {set_type}. Use 'reminder' or 'schedule'.")
                return False

        # Check if first arg is an action ID (4-digit numeric)
        if subcommand.isdigit() and len(subcommand) == 4:
            action_id = subcommand
            if len(args) < 2:
                # Default to info
                return _handle_info(action_id)
            sub_action = args[1]
            if sub_action == "on":
                return _handle_toggle(action_id, True)
            elif sub_action == "off":
                return _handle_toggle(action_id, False)
            elif sub_action == "info":
                return _handle_info(action_id)
            else:
                _error(f"Unknown action command: {sub_action}. Use 'on', 'off', or 'info'.")
                return False

        _error(f"Unknown subcommand: {subcommand}")
        console.print("[dim]Run 'actions --help' for available commands[/dim]")
        return False

    except Exception as e:
        logger.error("[actions] Error in actions command: %s", e, exc_info=True)
        _error(f"Error: {e}")
        return False


# =============================================
# MAIN ENTRY
# =============================================

def main() -> None:
    """Main entry point for direct execution."""
    args = sys.argv[1:]

    if not args or args[0] in ['--help', '-h', 'help']:
        print_help()
        return

    handle_command('actions', args)


if __name__ == "__main__":
    main()
