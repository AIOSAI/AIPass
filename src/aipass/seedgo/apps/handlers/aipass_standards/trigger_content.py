# =================== AIPass ====================
# Name: trigger_content.py
# Description: Trigger Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Trigger Standards Content Handler

Provides formatted Trigger event bus standards content.
Module orchestrates, handler implements.
"""

import sys
from pathlib import Path

from aipass.seedgo.apps.handlers.json import json_handler

def get_trigger_standards() -> str:
    """Return formatted trigger standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Replace [yellow]hardcoded cross-branch calls[/yellow] with [yellow]events[/yellow]",
        "  Decouple action from reaction, centralize side effects",
        "",
        "[bold cyan]THE EVENT BUS PATTERN:[/bold cyan]",
        "",
        "  [dim]Branch fires event[/dim] → [dim]trigger.fire('event_name')[/dim]",
        "  [dim]Trigger routes[/dim] → [dim]Calls registered handlers[/dim]",
        "  [dim]Handlers react[/dim] → [dim]Dashboard update, mbank archive, etc.[/dim]",
        "",
        "[bold cyan]IMPORT PATTERNS:[/bold cyan]",
        "",
        "  [yellow]Standard:[/yellow]",
        "  [dim]from trigger import trigger[/dim]",
        "  [dim]trigger.fire('event_name', key=value)[/dim]",
        "",
        "  [yellow]Lazy-load (for circular import safety):[/yellow]",
        "  [dim]try:[/dim]",
        "  [dim]    from trigger.apps.modules.core import trigger[/dim]",
        "  [dim]except ImportError:[/dim]",
        "  [dim]    trigger = None[/dim]",
        "",
        "[bold cyan]EVENT NAMING:[/bold cyan]",
        "",
        "  [yellow]Format:[/yellow] {scope}_{action} or {action}",
        "  [green]startup[/green], [green]plan_created[/green], [green]plan_closed[/green], [green]memory_saved[/green]",
        "  [dim]All lowercase, underscore-separated, past tense for completed actions[/dim]",
        "",
        "[yellow]KEY RULES:[/yellow]",
        "",
        "  1. [bold]Handlers CANNOT import Prax logger[/bold]",
        "     [red]FORBIDDEN:[/red] [dim]from prax.apps.modules.logger import system_logger[/dim]",
        "     [dim]Causes:[/dim] logger → trigger → handler → logger → [red]infinite loop[/red]",
        "",
        "  2. [bold]Handlers CANNOT print()[/bold]",
        "     [red]FORBIDDEN:[/red] [dim]print('Handling event...')[/dim]",
        "     [green]OK:[/green] Events auto-logged by trigger.fire() in core.py",
        "",
        "  3. [bold]Silent failure required[/bold]",
        "     [green]CORRECT:[/green] [dim]except Exception: pass[/dim]",
        "     [red]WRONG:[/red] [dim]except Exception as e: logger.error(e)[/dim]",
        "",
        "  4. [bold]Register handlers in registry.py[/bold]",
        "     [dim]trigger/apps/handlers/events/registry.py[/dim]",
        "     [dim]trigger.on('event_name', handle_function)[/dim]",
        "",
        "[bold cyan]DETECTED PATTERNS (10 categories):[/bold cyan]",
        "",
        "  [yellow]Function definitions that should fire triggers:[/yellow]",
        "  [dim]1.[/dim] FileSystemEventHandler: on_created, on_deleted, on_modified, on_moved",
        "  [dim]2.[/dim] Lifecycle: create_*, close_*, delete_*, restore_*",
        "  [dim]3.[/dim] Messaging: deliver_*, send_*",
        "  [dim]4.[/dim] State changes: mark_as_*, archive_*",
        "  [dim]5.[/dim] Registry: save_registry, ping_registry, sync_*registry, etc.",
        "  [dim]6.[/dim] Central: update_central, write_central_*, push_to_central, aggregate_central",
        "  [dim]7.[/dim] Repair: auto_close_*, recover_*, heal_*",
        "  [dim]8.[/dim] Cleanup/Backup: cleanup_*, backup_*",
        "  [dim]9.[/dim] System lifecycle: initialize_*_system, shutdown_*_system",
        "",
        "  [yellow]Inline operations (method calls):[/yellow]",
        "  [dim]10.[/dim] Filesystem: .unlink() file deletion, .rename() file move",
        "",
        "[bold cyan]WHEN TO FIRE EVENTS:[/bold cyan]",
        "",
        "  [green]DO:[/green] Lifecycle transitions (startup, plan_closed)",
        "  [green]DO:[/green] Cross-branch side effects (dashboard updates)",
        "  [green]DO:[/green] State changes other branches care about",
        "",
        "  [red]DON'T:[/red] Internal operations (same-module calls)",
        "  [red]DON'T:[/red] High-frequency ops (every log, every file read)",
        "  [red]DON'T:[/red] When caller needs return value (use function)",
        "",
        "[bold cyan]REPLACING HARDCODED PATTERNS:[/bold cyan]",
        "",
        "  [red]BEFORE (hardcoded):[/red]",
        "  [dim]update_dashboard_local()  # Direct call[/dim]",
        "  [dim]process_closed_plans()    # Direct call[/dim]",
        "",
        "  [green]AFTER (event-driven):[/green]",
        "  [dim]trigger.fire('plan_closed', plan_number=num)[/dim]",
        "  [dim]# Handlers in trigger/ react automatically[/dim]",
        "",
        "[bold cyan]CURRENT INTEGRATIONS:[/bold cyan]",
        "",
        "  [green]Prax:[/green] trigger.fire('startup') in logger.py",
        "  [green]CLI:[/green] trigger.fire('cli_header_displayed') in display.py",
        "  [yellow]Flow:[/yellow] JSON logging only - needs migration",
        "  [yellow]Drone:[/yellow] No events - ready to adopt",
        "",
        "[bold cyan]DESIGN PRINCIPLES:[/bold cyan]",
        "",
        "  [dim]•[/dim] Auto-initialization on first fire() call",
        "  [dim]•[/dim] Recursion guard prevents logger loops",
        "  [dim]•[/dim] Caller introspection for logging",
        "  [dim]•[/dim] Graceful degradation if Trigger unavailable",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (trigger)[/dim]",
        "  [dim]See: src/aipass/trigger/apps/modules/core.py[/dim]",
        "  [dim]See: src/aipass/trigger/apps/handlers/events/[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "trigger"})
    return "\n".join(lines)
