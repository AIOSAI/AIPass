# =================== AIPass ====================
# Name: core.py
# Description: Trigger event bus for AIPass system-wide event handling
# Version: 1.2.0
# Created: 2026-02-03
# Modified: 2026-02-03
# =============================================

"""
Core Trigger class - Event bus for AIPass

Branches fire events, Trigger handles reactions.
Pattern: Like Prax logger but for events.
"""

import inspect
from pathlib import Path


from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.trigger.apps.handlers.json import json_handler

from typing import Callable


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        from rich.console import Console
        console = Console()

    console.print()
    console.print("core Module")
    console.print("Trigger event bus — fire events, register handlers, deferred queue processing")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/events/")
    console.print("    - registry.py (setup_handlers — auto-register all event handlers on first use)")
    console.print()


def _get_caller() -> str:
    """Get the calling module/file name"""
    stack = inspect.stack()
    for frame in stack[2:]:  # Skip _get_caller and fire
        filepath = frame.filename
        if 'trigger/apps/modules/core.py' not in filepath:
            # Extract meaningful name from path
            path = Path(filepath)
            # Try to get branch/module name
            parts = path.parts
            for i, part in enumerate(parts):
                if part == 'aipass':
                    if i + 1 < len(parts):
                        return parts[i + 1]  # Return branch name
            return path.stem  # Fallback to filename
    return 'unknown'


class Trigger:
    """Event bus for AIPass system"""

    _handlers = {}
    _history = []  # Optional: track recent events
    _initialized = False
    _firing = False  # Recursion guard
    _deferred_queue = []  # Queue for events fired during handling
    _draining_deferred = False  # Prevents nested deferred processing
    _log_watcher_started = False  # Lazy-start flag for log watcher

    @classmethod
    def _ensure_initialized(cls):
        """Auto-register handlers on first use"""
        if not cls._initialized:
            try:
                from aipass.trigger.apps.handlers.events.registry import setup_handlers
                setup_handlers()
            except ImportError as e:
                logger.warning(f"[TRIGGER] Handlers not available: {e}")
            cls._initialized = True

    @classmethod
    def _ensure_log_watcher(cls):
        """Lazy-start log watcher - DISABLED to prevent inotify exhaustion.

        The lazy-start pattern causes each process to start its own watchers,
        exhausting the system's inotify instance limit (128 by default).

        Log watching should be done by a dedicated persistent process:
        - Use `prax monitor` for real-time log watching
        - Or use the catch-up pattern to scan logs on demand

        See ERROR 1b5dd1af for details on inotify exhaustion issue.
        """
        # DISABLED: Each process starting watchers exhausts inotify instances
        # The lock mechanism only prevented simultaneous starts, not accumulation
        # over time as processes start/stop throughout the day.
        #
        # Architecture decision: Log watching belongs in prax monitor (persistent)
        # not lazy-started in every trigger.fire() call.
        pass

    @classmethod
    def on(cls, event: str, handler: Callable):
        """Register handler for event"""
        cls._handlers.setdefault(event, []).append(handler)

    @classmethod
    def off(cls, event: str, handler: Callable):
        """Remove handler"""
        if event in cls._handlers and handler in cls._handlers[event]:
            cls._handlers[event].remove(handler)

    @classmethod
    def fire(cls, event: str, **data):
        """Fire event to all registered handlers

        Supports nested event firing via deferred queue - events fired during
        handler execution are queued and processed after current handler completes.
        """
        # If already firing, queue this event for later (prevents recursion, enables nesting)
        if cls._firing:
            cls._deferred_queue.append((event, data))
            return

        cls._firing = True
        try:
            cls._ensure_initialized()
            cls._ensure_log_watcher()
            handlers = cls._handlers.get(event, [])

            # Provide fire_event callback so handlers can fire events without importing
            data['fire_event'] = cls.fire

            for handler in handlers:
                try:
                    handler(**data)
                except Exception as e:
                    logger.error(f"[TRIGGER] Handler error for {event}: {e}")
        finally:
            cls._firing = False

            # Process deferred events iteratively (NOT recursively)
            # Each fire() during drain just appends to queue, loop picks it up
            if not cls._draining_deferred:
                cls._draining_deferred = True
                try:
                    while cls._deferred_queue:
                        deferred_event, deferred_data = cls._deferred_queue.pop(0)
                        cls._firing = True
                        try:
                            handlers = cls._handlers.get(deferred_event, [])
                            data_copy = dict(deferred_data)
                            data_copy['fire_event'] = cls.fire
                            for handler in handlers:
                                try:
                                    handler(**data_copy)
                                except Exception:
                                    pass  # Silent - avoid logger recursion
                        finally:
                            cls._firing = False
                finally:
                    cls._draining_deferred = False

    @classmethod
    def status(cls) -> dict:
        """Show registered handlers"""
        cls._ensure_initialized()
        return {event: len(handlers) for event, handlers in cls._handlers.items()}


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point.

    Commands:
        fire <event> [key=value ...]  - Fire an event with optional data
        status                        - Show registered event handlers
        list                          - Alias for status

    Args:
        command: Command to execute (fire, status, list)
        args: Additional arguments

    Returns:
        True if command was handled, False otherwise
    """
    from aipass.cli.apps.modules import console, error

    # Handle module-name routing (drone @trigger core <subcmd>)
    if command == "core":
        if not args:
            print_introspection()
            return True
        if args[0] in ['--help', '-h', 'help']:
            _print_help(console)
            return True
        return handle_command(args[0], args[1:])

    if command not in ["fire", "status", "list"]:
        return False

    if args and args[0] in ['--help', '-h', 'help']:
        _print_help(console)
        return True

    if command == "fire":
        if not args:
            error("Usage: drone @trigger fire <event> [key=value ...]")
            return True
        event_name = args[0]
        # Parse key=value pairs from remaining args
        data = {}
        for arg in args[1:]:
            if "=" in arg:
                key, value = arg.split("=", 1)
                data[key] = value
            else:
                logger.warning(f"[TRIGGER] Ignoring unparseable arg: {arg}")
        Trigger.fire(event_name, **data)
        console.print(f"[green]Fired event:[/green] {event_name}")
        json_handler.log_operation("event_fired", {"event": event_name})
        if data:
            for k, v in data.items():
                console.print(f"  [dim]{k}={v}[/dim]")
        return True

    elif command in ["status", "list"]:
        handler_map = Trigger.status()
        if not handler_map:
            console.print("[dim]No event handlers registered[/dim]")
            return True
        console.print("[bold cyan]Registered Event Handlers[/bold cyan]")
        console.print()
        for event, count in sorted(handler_map.items()):
            console.print(f"  [green]{event:30}[/green] {count} handler(s)")
        console.print()
        console.print(f"[dim]Total: {len(handler_map)} events, "
                       f"{sum(handler_map.values())} handlers[/dim]")
        return True

    return False


def _print_help(console):
    """Display help for core trigger commands."""
    console.print()
    console.print("[bold cyan]TRIGGER CORE - Event Bus[/bold cyan]")
    console.print()
    console.print("[bold]COMMANDS:[/bold]")
    console.print("  fire <event> [key=value ...]  Fire an event with optional data")
    console.print("  status                        Show registered event handlers")
    console.print("  list                          Alias for status")
    console.print()
    console.print("[bold]EXAMPLES:[/bold]")
    console.print("  drone @trigger fire deploy_complete branch=main")
    console.print("  drone @trigger status")
    console.print()


# Create instance for import
trigger = Trigger()
