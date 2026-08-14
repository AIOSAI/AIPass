# =================== AIPass ====================
# Name: symbolic.py
# Description: Symbolic Memory Module — PARKED 2026-08-14
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-08-14
# =============================================

"""
Symbolic Memory Module — PARKED 2026-08-14 (Patrick's ruling).

WHY THIS IS PARKED
    The Agent Memory Atlas published a code-grounded review of AIPass memory at
    revision 0d27e5ef (https://neoneye.github.io/agent-memory-atlas/systems/aipass/).
    It praised the governance/entry-limit/rollover design and made one sharp
    criticism: the symbolic tier's AUDN deduplicator hands an LLM a fragment, takes
    a ``Delete`` verdict, and removes content with no record of what went or why —
    an unauditable deletion inside a memory system. The tier was never wired into a
    live lane: no hook entry, and no caller in rollover, the extractor, auto_process,
    search or verify. Patrick's ruling, 2026-08-14: park it — we may use it later —
    and say where the active piece is.

WHERE THE ACTIVE PIECE IS
    Compass — @devpulse's curated-truth store. src/aipass/devpulse, SQLite + FTS5,
    reached with ``drone @devpulse compass``. It carries the discipline this tier
    lacked: a correcting entry archives and links what it replaces, so a change of
    mind leaves a record instead of a hole.

    Not parked, and not part of this tier: the surfacing governance engine
    (apps/modules/governance.py). It is LIVE on the UserPromptSubmit lane — @hooks'
    compass_recall calls should_surface/record_message/new_state on every prompt to
    decide which Compass decisions may be shown.

THE IMPLEMENTATION IS NOT GONE
    All 1602 lines are at .archive/parked_symbolic_20260814/modules/symbolic.py,
    the handlers at .archive/parked_symbolic_20260814/handlers/. That directory's
    README.md has the revival steps. This stub stays in place so that anyone who
    invokes a parked surface is told what happened rather than met with a bare
    'unknown command'.
"""

import sys
from typing import Any, List

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.cli.help_flags import wants_help

PARKED_DATE = "2026-08-14"

# Subcommands the tier used to answer. Kept so a caller who types one gets the
# ruling, not silence — and so revival knows exactly what it is restoring.
_PARKED_SUBCOMMANDS = {
    "demo": "Run demonstration analysis (v1 + v2 mock)",
    "analyze": "Analyze a conversation JSON file (v1 pipeline)",
    "extract": "Extract fragments via LLM and store (v2 pipeline)",
    "bootstrap": "Populate fragments from session JSONLs",
    "fragments": "Search symbolic fragments (v1 + v2)",
    "hook-test": "Test hook with sample conversation text",
}

_PARKED_REASON = (
    f"PARKED {PARKED_DATE} by Patrick's ruling — unused tier, and the Agent Memory Atlas "
    "review flagged its AUDN deduplicator for acting on an LLM Delete verdict with no "
    "record of what was removed. Parked, not removed."
)

_ACTIVE_PIECE = "Compass — @devpulse's curated-truth store (SQLite/FTS5): drone @devpulse compass"

_ARCHIVE_HINT = "Code + revival steps: memory/.archive/parked_symbolic_20260814/README.md"


class SymbolicTierParked(RuntimeError):
    """Raised when parked symbolic code is reached. Never a silent no-op."""


def __getattr__(name: str) -> Any:
    """
    Answer for the whole old public API — extract_*, store_*, retrieve_*, and the rest.

    Module-level __getattr__ (PEP 562) fires only for names this stub does not
    define, so every parked function reports the ruling instead of raising a bare
    AttributeError that says nothing about why it went.
    """
    if name.startswith("__"):
        raise AttributeError(name)
    raise SymbolicTierParked(f"symbolic.{name} is {_PARKED_REASON}\n  Active: {_ACTIVE_PIECE}\n  {_ARCHIVE_HINT}")


def print_introspection() -> None:
    """Display module introspection (seedgo standard: no args = structure/discovery)."""
    console.print()
    console.print("[bold cyan]symbolic[/bold cyan] — Fragmented Memory Extraction [bold yellow](PARKED)[/bold yellow]")
    console.print(f"[dim]{_PARKED_REASON}[/dim]")
    console.print()

    console.print("[yellow]Active piece:[/yellow]")
    console.print(f"  [green]{_ACTIVE_PIECE}[/green]")
    console.print()

    console.print("[yellow]Parked subcommands:[/yellow]")
    console.print("  [dim]every one of these now exits 1 with the notice above[/dim]")
    for sub, desc in _PARKED_SUBCOMMANDS.items():
        console.print(f"  [dim]{sub:<20} {desc}[/dim]")
    console.print()

    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @devpulse compass[/green]   [dim]# the curated-truth store that is live[/dim]")
    console.print(f"  [dim]{_ARCHIVE_HINT}[/dim]")
    console.print()


def print_help() -> None:
    """Explain the park. A help flag never executes anything — there is nothing to execute."""
    print_introspection()
    console.print("[yellow]The park:[/yellow]")
    console.print("  [dim]Nothing was deleted — revival is a file move, see the README above.[/dim]")
    console.print("  [dim]Fix the Atlas finding before it runs again: a Delete verdict must[/dim]")
    console.print("  [dim]record what it removed, why, and when — or it must not delete.[/dim]")
    console.print()


def _refuse(surface: str) -> None:
    """Report the ruling and exit non-zero. Fail honest: a caller reading exit codes sees it."""
    logger.warning(f"[symbolic] Refused '{surface}' — tier parked {PARKED_DATE}")
    json_handler.log_operation("symbolic_parked", {"surface": surface, "parked_date": PARKED_DATE})
    error(
        f"symbolic {surface} is unavailable — {_PARKED_REASON}",
        suggestion=f"{_ACTIVE_PIECE}\n{_ARCHIVE_HINT}",
    )
    sys.exit(1)


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle symbolic commands — every one of them refuses, loudly.

    Args:
        command: Command name
        args: Additional arguments

    Returns:
        True if the command belonged to this module, False otherwise.
    """
    if command in ("--help", "-h", "help"):
        print_help()
        return True

    if command == "symbolic":
        if not args:
            print_introspection()
            return True

        if wants_help(args):
            print_help()
            return True

        _refuse(args[0])
        return True

    # Backward compat: the entry point may route bare subcommands here.
    if command in _PARKED_SUBCOMMANDS:
        if wants_help(args):
            print_help()
            return True

        _refuse(command)
        return True

    return False
