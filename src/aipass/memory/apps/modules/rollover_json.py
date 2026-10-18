# =================== AIPass ====================
# Name: rollover_json.py
# Description: The --json surface behind the rollover verbs - the emitter, the refusal writer, the projections
# Version: 1.0.0
# Created: 2026-09-16
# Modified: 2026-10-17
# =============================================

"""
Rollover Machine Output (DPLAN-0302)

In ``modules/`` because it writes to the screen; imports neither rollover module (cycle).
Patch ``console`` and ``error`` on THIS module, not on rollover_config.
"""

import json
from typing import NamedTuple

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from aipass.memory.apps.handlers.json import json_handler


_ENTRY_TYPES = ("sessions", "key_learnings", "observations")

# Shown by `config get`, never written by `config set` in v1.
_READ_ONLY_TYPES = ("todos",)
_DISPLAY_TYPES = _ENTRY_TYPES + _READ_ONLY_TYPES


class _Json(NamedTuple):
    """Where one verb's answer goes, and the name it stamps on it."""

    verb: str
    on: bool


def _emit(payload: dict) -> None:
    """Write EXACTLY one JSON document to stdout.

    soft_wrap/markup/highlight off: a wrap, a ``[...]`` style or ANSI corrupts the payload.
    ``ensure_ascii`` stays on so an unknown-locale pipe never raises UnicodeEncodeError.
    """
    console.print(json.dumps(payload), markup=False, soft_wrap=True, highlight=False)


def _refuse(ctx: _Json, message: str, suggestion: str | None = None) -> None:
    """Emit one refusal — as a payload when asked, else on the human path.

    ONE wording for both surfaces: @api keys on these sentences.
    """
    if ctx.on:
        _emit({"ok": False, "verb": ctx.verb, "error": message, "suggestion": suggestion})
        return

    error(message, suggestion=suggestion)


def _project_row(row: dict, with_cap: bool = False, read_only: bool = False) -> dict:
    """Project one resolved limit row; resolution stays in ``config_loader._resolve_limits``."""
    projected: dict = {
        "count": row.get("count"),
        "default_count": row.get("default_count"),
        "is_override": bool(row.get("is_override")),
        "source": row.get("source"),
    }
    cap = row.get("auto_compact_cap")
    if with_cap and cap is not None:
        projected["auto_compact_cap"] = cap
    if read_only:
        projected["read_only"] = True
    return projected


def _project_default(row: dict, read_only: bool = False) -> dict:
    """Project one global default limit — count, plus a cap when set, plus a read-only mark."""
    projected: dict = {"count": row.get("count")}
    cap = row.get("auto_compact_cap")
    if cap is not None:
        projected["auto_compact_cap"] = cap
    if read_only:
        projected["read_only"] = True
    return projected


def _project_overrides(limits: dict) -> dict:
    """Project only the entry types that deviate; same rule as the human OVERRIDES block."""
    return {
        entry_type: _project_row(limits.get(entry_type, {}), read_only=entry_type in _READ_ONLY_TYPES)
        for entry_type in _DISPLAY_TYPES
        if limits.get(entry_type, {}).get("is_override")
    }


def print_introspection() -> None:
    """Display module introspection (seedgo standard)."""
    console.print()
    console.print("[bold cyan]rollover_json Module[/bold cyan]")
    console.print("The --json surface the rollover and config verbs answer through")
    console.print()

    console.print("[yellow]Library API:[/yellow]")
    console.print("  [green]_Json(verb, on)[/green]        [dim]# The verb name, and whether to answer as JSON[/dim]")
    console.print("  [green]_emit(payload)[/green]         [dim]# EXACTLY one JSON document on stdout[/dim]")
    console.print("  [green]_refuse(ctx, ...)[/green]      [dim]# One refusal, machine or human, one wording[/dim]")
    console.print("  [green]_project_row(row)[/green]      [dim]# One resolved limit row, projected[/dim]")
    console.print("  [green]_project_default(row)[/green]  [dim]# One global default, projected[/dim]")
    console.print("  [green]_project_overrides(l)[/green]  [dim]# Only the types that deviate for a branch[/dim]")
    console.print()

    console.print("[yellow]Contract:[/yellow]")
    console.print("  Every payload carries [cyan]ok[/cyan] and [cyan]verb[/cyan]; refusals exit 0 and")
    console.print("  carry the SAME sentences the human path prints.")
    console.print()

    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @memory config get --json[/green]   [dim]# The surface, exercised[/dim]")
    console.print("  [green]drone @memory config --help[/green]       [dim]# Full usage guide[/dim]")
    console.print()

    console.print("[dim]Library module - import from: aipass.memory.apps.modules.rollover_json[/dim]")
    console.print()


def handle_command(command: str, args: list) -> bool:
    """Entry point for drone module discovery - describes the --json surface, never runs a verb."""
    if command != "rollover_json":
        return False

    json_handler.log_operation("rollover_json_command", {"args": args})
    logger.debug(f"[rollover_json] introspection requested with args={args}")

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_introspection()
        return True

    error(f"rollover_json: unknown subcommand '{args[0]}' - the verbs are 'drone @memory rollover' and 'config'")
    print_introspection()
    return True
