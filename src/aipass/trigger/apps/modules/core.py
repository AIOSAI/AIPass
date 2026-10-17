# =================== AIPass ====================
# Name: core.py
# Description: Trigger event bus for AIPass system-wide event handling
# Version: 1.4.0
# Created: 2026-02-03
# Modified: 2026-10-17
# =============================================

"""
Core Trigger class - Event bus for AIPass"""

import os
import sys
from typing import Callable

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.trigger.apps.handlers.json import json_handler

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    # OSError too: an uncured peer's import guard raises FileNotFoundError.
    except (ImportError, OSError):
        from rich.console import Console

        console = Console()

    console.print()
    console.print("[bold cyan]core Module[/bold cyan]")
    console.print("[dim]Trigger event bus — fire events, register handlers, deferred queue processing[/dim]")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/events/[/cyan]")
    console.print(
        "    [cyan]•[/cyan] registry.py [dim](setup_handlers — auto-register all event handlers on first use)[/dim]"
    )
    console.print()


# Renamed events, old name -> current name. An entry lives ONE release: both
# names work, the old one logs a deprecation, then the entry is deleted.
DEPRECATED_EVENT_ALIASES: dict[str, str] = {}


class Trigger:
    """Event bus for AIPass system"""

    _alias_warned = set()  # deprecated names already logged, once per process
    _handlers = {}
    _history = []  # Optional: track recent events
    _initialized = False
    _firing = False  # Recursion guard
    _deferred_queue = []  # Queue for events fired during handling
    _draining_deferred = False  # Prevents nested deferred processing
    _log_watcher_started = False  # Lazy-start flag for log watcher
    _handler_failures = {}  # (handler, branch) -> consecutive failure count
    _disabled_handlers = set()  # (handler, branch) tuples auto-disabled
    _HANDLER_FAILURE_THRESHOLD = 5  # consecutive failures before auto-disable

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

        A watcher per process exhausts inotify instances; a persistent process owns log watching."""
        pass

    @classmethod
    def _canonical(cls, event: str) -> str:
        """Resolve a deprecated event name to the name that replaced it.

        Warns once per name per process; unknown names pass through (a rename table, not a whitelist)."""
        replacement = DEPRECATED_EVENT_ALIASES.get(event)
        if replacement is None:
            return event
        if event not in cls._alias_warned:
            cls._alias_warned.add(event)
            logger.warning(
                f"[TRIGGER] Event '{event}' is deprecated and will be removed next release; "
                f"delivered as '{replacement}'. Update the fire site and any Trigger.on() registration."
            )
        return replacement

    @classmethod
    def on(cls, event: str, handler: Callable):
        """Register handler for event, at most once.

        Idempotent by design: setup_handlers() can run twice, and a doubled handler
        delivers one event twice, which walks a one-off past medic's count >= 2 gate."""
        event = cls._canonical(event)
        handlers = cls._handlers.setdefault(event, [])
        if handler not in handlers:
            handlers.append(handler)

    @classmethod
    def off(cls, event: str, handler: Callable):
        """Remove handler.

        Resolves the alias too, or `off("old")` would miss what `on("old")` registered."""
        event = cls._canonical(event)
        if event in cls._handlers and handler in cls._handlers[event]:
            cls._handlers[event].remove(handler)

    @classmethod
    def _fire_to_handlers(cls, event: str, data: dict) -> dict:
        """Fire a single event to its registered handlers."""
        handlers = cls._handlers.get(event, [])
        data = dict(data)  # Copy to avoid mutating caller's dict
        data["fire_event"] = cls.fire
        branch = data.get("branch", "__global__")
        ran = failed = 0
        for handler in handlers:
            key = (handler, branch)
            if key in cls._disabled_handlers:
                continue
            try:
                handler(**data)
                cls._handler_failures.pop(key, None)  # Reset on success
                ran += 1
            except Exception as e:
                failed += 1
                count = cls._handler_failures.get(key, 0) + 1
                cls._handler_failures[key] = count
                if count >= cls._HANDLER_FAILURE_THRESHOLD:
                    cls._disabled_handlers.add(key)
                    logger.error(
                        f"[TRIGGER] Handler {getattr(handler, '__name__', handler)} "
                        f"disabled for branch '{branch}' after {count} consecutive failures"
                    )
                else:
                    logger.error(f"[TRIGGER] Handler error for {event}: {e}")

        return {"event": event, "handlers": len(handlers), "ran": ran, "failed": failed}

    @classmethod
    def _drain_deferred(cls) -> None:
        """Process queued events from nested fire() calls."""
        if cls._draining_deferred:
            return
        cls._draining_deferred = True
        try:
            while cls._deferred_queue:
                deferred_event, deferred_data = cls._deferred_queue.pop(0)
                cls._firing = True
                try:
                    cls._fire_to_handlers(deferred_event, dict(deferred_data))
                finally:
                    cls._firing = False
        finally:
            cls._draining_deferred = False

    @classmethod
    def fire(cls, event: str, **data) -> dict:
        """Fire event to all registered handlers

        Handler exceptions never propagate, so the returned counts are how a caller tells
        "all ran" from "all raised" from "nobody listening"; a nested fire is queued."""
        # Before the recursion guard, so a deferred summary names the event that runs.
        event = cls._canonical(event)

        if cls._firing:
            cls._deferred_queue.append((event, data))
            return {"event": event, "deferred": True}

        cls._firing = True
        try:
            cls._ensure_initialized()
            cls._ensure_log_watcher()
            return cls._fire_to_handlers(event, data)
        finally:
            cls._firing = False
            cls._drain_deferred()

    @classmethod
    def status(cls) -> dict:
        """Show registered handlers"""
        cls._ensure_initialized()
        return {event: len(handlers) for event, handlers in cls._handlers.items()}


def _coerce_value(val_str: str) -> int | float | str:
    """Coerce a string value to int, float, or leave as string.

    Only on a lossless round trip: an all-digit hex id like `00123456` must stay a str."""
    for cast in (int, float):
        try:
            number = cast(val_str)
        except ValueError:
            continue
        if str(number) == val_str:
            return number
    return val_str


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point."""
    from aipass.cli.apps.modules import console, error

    from aipass.trigger.apps.handlers.cli.help_flags import wants_help

    if command == "core":
        if not args:
            print_introspection()
            return True
        if wants_help(args):
            _print_help(console)
            return True
        return handle_command(args[0], args[1:])

    if command not in ["fire", "status", "list"]:
        return False

    # After the ownership check, or this would hijack other modules' --help.
    if wants_help(args):
        _print_help(console)
        return True

    if command == "fire":
        if not args:
            error("Usage: drone @trigger fire <event> [key=value ...]")
            return True
        event_name = args[0]
        data = {}
        for arg in args[1:]:
            if "=" in arg:
                key, val_str = arg.split("=", 1)
                data[key] = _coerce_value(val_str)
            else:
                logger.warning(f"[TRIGGER] Ignoring unparseable arg: {arg}")
        result = Trigger.fire(event_name, **data)
        ran, failed = result.get("ran", 0), result.get("failed", 0)
        if failed:
            console.print(
                f"[yellow]Fired event:[/yellow] {event_name} — "
                f"{ran} handler(s) ran, [red]{failed} failed[/red] (see logs/core.log)"
            )
        elif not result.get("handlers"):
            console.print(
                f"[yellow]Fired event:[/yellow] {event_name} — [dim]no handlers registered, nothing ran[/dim]"
            )
        else:
            console.print(f"[green]Fired event:[/green] {event_name} — {ran} handler(s) ran")
        json_handler.log_operation("event_fired", {"event": event_name, **result})
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
        console.print(f"[dim]Total: {len(handler_map)} events, {sum(handler_map.values())} handlers[/dim]")
        return True

    return False


def _print_help(console):
    """Display help for core trigger commands."""
    console.print()
    console.print("[bold cyan]TRIGGER CORE - Event Bus[/bold cyan]")
    console.print()
    console.print("[bold]COMMANDS:[/bold]")
    console.print("  fire <event> \\[key=value ...]  Fire an event with optional data")
    console.print("  status                        Show registered event handlers")
    console.print("  list                          Alias for status")
    console.print()
    console.print("[bold]EXAMPLES:[/bold]")
    console.print("  drone @trigger fire deploy_complete branch=main")
    console.print("  drone @trigger status")
    console.print()


trigger = Trigger()
