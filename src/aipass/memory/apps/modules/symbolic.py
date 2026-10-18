# =================== AIPass ====================
# Name: symbolic.py
# Description: Symbolic Memory Module — PARKED 2026-08-14
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-10-17
# =============================================

"""
Symbolic Memory Module — PARKED 2026-08-14 (the owner's ruling).

Its AUDN deduplicator deleted on an LLM verdict with no record. The code and the
revival steps are in tests/parked/symbolic_20260814/; this stub makes every parked
surface say so. governance.py is not part of this tier and is live.
"""

import sys
from typing import Any, List

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.cli.help_flags import wants_help

PARKED_DATE = "2026-08-14"

# Kept so a caller who types one gets the ruling, not 'unknown command'.
_PARKED_SUBCOMMANDS = {
    "demo": "Run demonstration analysis (v1 + v2 mock)",
    "analyze": "Analyze a conversation JSON file (v1 pipeline)",
    "extract": "Extract fragments via LLM and store (v2 pipeline)",
    "bootstrap": "Populate fragments from session JSONLs",
    "fragments": "Search symbolic fragments (v1 + v2)",
    "hook-test": "Test hook with sample conversation text",
}

_PARKED_REASON = (
    f"PARKED {PARKED_DATE} by the owner's ruling — unused tier, and the Agent Memory Atlas "
    "review flagged its AUDN deduplicator for acting on an LLM Delete verdict with no "
    "record of what was removed. Parked, not removed."
)

_ACTIVE_PIECE = "Compass — @devpulse's curated-truth store (SQLite/FTS5): drone @devpulse compass"

_ARCHIVE_HINT = "Code + revival steps: memory/tests/parked/symbolic_20260814/README.md"


class SymbolicTierParked(RuntimeError):
    """Raised when parked symbolic code is reached. Never a silent no-op."""


def __getattr__(name: str) -> Any:
    """Answer for the whole old public API (PEP 562) with the ruling, not a bare AttributeError."""
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
    """Handle symbolic commands — every one of them refuses, loudly."""
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
