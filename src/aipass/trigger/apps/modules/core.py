# =================== AIPass ====================
# Name: core.py
# Description: Trigger event bus for AIPass system-wide event handling
# Version: 1.3.0
# Created: 2026-02-03
# Modified: 2026-08-12
# =============================================

"""
Core Trigger class - Event bus for AIPass

Branches fire events, Trigger handles reactions.
Pattern: Like Prax logger but for events.
"""

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
    except ImportError:
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


class Trigger:
    """Event bus for AIPass system"""

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
        """Register handler for event, at most once.

        Registration is idempotent BY DESIGN, not as a convenience. Two wiring
        passes over the same handler set are routine here — setup_handlers() can
        be called explicitly and does not set _initialized, so the next fire()
        runs _ensure_initialized() and wires everything again. Appending blindly
        made the bus deliver one event twice, and downstream that defeats medic
        gate 3: the gate needs count >= 2 before it dispatches, so a single
        occurrence counted twice walks straight through it and mails a branch
        about a one-off. Registering the same callable twice for one event has
        no legitimate meaning — an event fires a handler once.
        """
        handlers = cls._handlers.setdefault(event, [])
        if handler not in handlers:
            handlers.append(handler)

    @classmethod
    def off(cls, event: str, handler: Callable):
        """Remove handler"""
        if event in cls._handlers and handler in cls._handlers[event]:
            cls._handlers[event].remove(handler)

    @classmethod
    def _fire_to_handlers(cls, event: str, data: dict) -> dict:
        """Fire a single event to its registered handlers.

        Returns a summary of what actually happened: how many handlers were
        registered, how many completed, how many raised. Handler failures stay
        isolated — the count is what lets a caller tell isolation from silence.
        """
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

        Supports nested event firing via deferred queue - events fired during
        handler execution are queued and processed after current handler completes.

        Returns an execution summary — `{event, handlers, ran, failed}`, or
        `{event, deferred: True}` for a nested fire that was queued. Handler
        exceptions never propagate to the caller (isolation is the point of a
        bus), so the counts are the only way a caller can tell "all handlers
        completed" from "every handler raised" from "nothing was listening".
        Callers are free to ignore it; the CLI does not.
        """
        # If already firing, queue this event for later (prevents recursion, enables nesting)
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

    Typing is by LOSSLESS ROUND TRIP, not by shape: a token is only converted
    when `str(number) == val_str`. Event data carries identity tokens as well
    as numbers — `handle_error_detected` annotates `fingerprint`, `error_hash`
    and `registry_id` as `str` — and an 8-char `uuid4()[:8]` is all digits
    2.3% of the time, (10/16)**8. A shape test ("it looks like a number")
    turns `fingerprint=00123456` into int 123456: the type contract breaks and
    a character of the user's token is deleted on the way through. `int()` is
    wider than it looks and would also eat `1_0`, `+5` and ` 5`; `float()`
    reshapes `1.50` and `1e3`. Round-tripping catches all of them at once.

    Reported by @drone (2026-08-13) after the same shape test in their own
    `view N` index shortcut ate real message IDs — the collision is between
    the token spaces themselves, so only a lossless check removes the class.
    """
    for cast in (int, float):
        try:
            number = cast(val_str)
        except ValueError:
            continue
        if str(number) == val_str:
            return number
    return val_str


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

    from aipass.trigger.apps.handlers.cli.help_flags import wants_help

    # Handle module-name routing (drone @trigger core <subcmd>)
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

    # Whole-sequence help gate, AFTER the ownership check above: claiming a
    # command this module does not own would hijack every other module's
    # --help at the entry point. `help` counts only at position 0 — later it
    # is event payload (`fire evt message=help`).
    if wants_help(args):
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


# Create instance for import
trigger = Trigger()
