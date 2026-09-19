# =================== AIPass ====================
# Name: rollover_json.py
# Description: The --json surface behind the rollover verbs - the emitter, the refusal writer, the projections
# Version: 1.0.0
# Created: 2026-09-16
# Modified: 2026-09-16
# =============================================

"""
Rollover Machine Output (DPLAN-0302)

The ``--json`` surface every rollover and ``config`` verb answers through: the
payload context ``_Json``, the one-document writer ``_emit``, the refusal writer
``_refuse``, and the projections that shape a resolved limit row for the wire.
Lifted out of ``modules/rollover_config.py`` when that module reached the seedgo
length standard. The code here is the code that was there.

WHY IT SITS IN ``modules/`` AND NOT ``handlers/``. Because it WRITES TO THE
SCREEN. ``_emit`` goes through the shared console and ``_refuse`` calls
``error``; @seedgo's ``cli`` standard fails any file under ``apps/handlers/``
that touches ``console.print()`` or imports ``aipass.cli.apps.modules``, on the
rule that a handler returns data and lets a module render it. A JSON document
on stdout is still a rendering, and there is no version of this file that hands
its payload back instead of writing it - the emitter exists precisely to own
HOW the bytes reach the pipe. That the reader is a machine changes who is
listening, not which tier is allowed to speak.

THE DEPENDENCY RUNS ONE WAY. ``rollover_config.py`` imports every name below
and ``rollover.py`` re-exports them, because the CLI and the tests reach them as
``rollover.<name>``. This module imports neither of those - an emitter that
reached back to its own callers would be an import cycle. That is also why the
entry-type tuples live down here: ``_project_overrides`` reads them, so they
cannot sit on the far side of the arrow.

PATCH IT HERE, NOT NEXT DOOR. ``_emit`` reads ``console`` and ``_refuse`` reads
``error`` from THIS module's globals. A harness standing a mock console in for
the real one has to set the attribute on this module; setting it on
``rollover_config`` no longer reaches either function.

IT OWNS NO VERB. ``handle_command`` at the foot answers only this module's own
name and prints the introspection page. ``apps/memory.py::discover_modules``
duck-types on that function, and ``modules/fleet.py`` records why a modules/
file without one is the wrong answer - three @seedgo standards fail it. It runs
no work of its own: ``config`` is owned and routed by ``modules/rollover.py``,
and a second entrance to one verb is the drift these splits exist to prevent.
"""

import json
from typing import NamedTuple

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from aipass.memory.apps.handlers.json import json_handler


# The only three entry types `config set` writes. Display order.
_ENTRY_TYPES = ("sessions", "key_learnings", "observations")

# Shown by `config get`, never written by `config set` in v1 (like
# auto_compact_cap). The todo roll reads this count for one branch at a time.
_READ_ONLY_TYPES = ("todos",)
_DISPLAY_TYPES = _ENTRY_TYPES + _READ_ONLY_TYPES

# =============================================================================
# MACHINE OUTPUT — THE --json SURFACE
# =============================================================================


class _Json(NamedTuple):
    """Where one verb's answer goes, and the name it stamps on it.

    Attributes:
        verb: The published verb name carried in every payload.
        on: True for machine output; False leaves every human rendering
            exactly as it was.
    """

    verb: str
    on: bool


def _emit(payload: dict) -> None:
    """Write EXACTLY one JSON document to stdout.

    Routed through the shared console like every other line this branch
    prints, but with Rich's three text behaviours turned OFF — they each
    corrupt a machine payload:

    - ``soft_wrap=True``: the console is width-80 with ``is_terminal=False``,
      so by default it hard-wraps a long payload onto two lines, and a wrap
      landing inside a string value inserts a newline INTO the value.
    - ``markup=False``: a ``[...]`` token inside a string is otherwise eaten
      as a style name (how @daemon's lowercase ``[skip]`` markers vanished
      from the screen while tests on the returned string stayed green).
    - ``highlight=False``: the repr highlighter would inject ANSI styling the
      moment this ran attached to a terminal.

    All three corruptions are invisible to a test that asserts on the string
    handed to the printer rather than on what reached the pipe — which is
    exactly how they survive. The tests here read the pipe.

    ``ensure_ascii`` stays at its default, unlike ``_write_config_file``
    which deliberately turns it off — opposite jobs.  That one edits a file an
    operator reads; this one crosses a pipe into a subprocess of unknown
    locale.  Escaping the em-dashes the refusal sentences carry means this
    write can never raise UnicodeEncodeError, and ``json.loads`` hands the
    caller back the exact character either way.
    """
    console.print(json.dumps(payload), markup=False, soft_wrap=True, highlight=False)


def _refuse(ctx: _Json, message: str, suggestion: str | None = None) -> None:
    """Emit one refusal — as a payload when asked, else on the human path.

    ONE wording serves both surfaces.  @api keys on these sentences, so a
    second copy written for machines would be a contract free to drift.
    ``suggestion`` is always present in the payload, null where the refusal
    genuinely has none.

    Args:
        ctx: The verb name and whether machine output was requested.
        message: The refusal sentence.
        suggestion: The remedy line, when the refusal has one.
    """
    if ctx.on:
        _emit({"ok": False, "verb": ctx.verb, "error": message, "suggestion": suggestion})
        return

    error(message, suggestion=suggestion)


def _project_row(row: dict, with_cap: bool = False, read_only: bool = False) -> dict:
    """Project one resolved limit row from ``config_loader`` for a payload.

    A thin projection on purpose: the resolution rules live in
    ``config_loader._resolve_limits`` and must not be re-implemented here,
    or the machine surface becomes a second, divergent answer.

    Args:
        row: One entry from ``get_effective_limits``.
        with_cap: Include ``auto_compact_cap`` when the row carries one.
        read_only: Mark a type ``config set`` cannot write (todos in v1).

    Returns:
        The published per-entry-type shape.
    """
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
    """Project only the entry types that actually deviate for one branch.

    Same rule the human OVERRIDES block applies, so the two surfaces list
    the same rows rather than two different notions of "override".
    """
    return {
        entry_type: _project_row(limits.get(entry_type, {}), read_only=entry_type in _READ_ONLY_TYPES)
        for entry_type in _DISPLAY_TYPES
        if limits.get(entry_type, {}).get("is_override")
    }


# =============================================================================
# INTROSPECTION
# =============================================================================


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
    """Entry point for drone module discovery - describes the --json surface, never runs a verb.

    The verbs that answer through this module are ``drone @memory rollover``
    and ``drone @memory config``, both owned and routed by
    ``modules/rollover.py``. Discovery is duck-typed on this function, and
    ``fleet.py`` records the branch convention: a modules/ file invisible to
    discovery fails three @seedgo standards, so this one is discoverable and
    answers introspection only.

    Running verb work from here would be a second entrance to a word this
    module does not own - one word, one router.
    """
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
