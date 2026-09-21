# =================== AIPass ====================
# Name: top.py
# Description: Leaderboard command - drone @canary top N FILE prints the N highest counts
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""Leaderboard reader: a tally file in, the highest counts out.

``top N FILE`` prints the N highest counts, one per line, as the name, a single
space, and the count. ``top --json N FILE`` prints one JSON array of
``{"name": ..., "count": ...}`` objects in the same order and nothing else on
stdout, so a caller can read it without a parser of its own.

Anything that is not a leaderboard is refused on stderr with exit 2 and NOTHING
on stdout - a refusal that printed a partial ranking would be read as an answer
by the next command in the pipe.
"""

import json
from pathlib import Path
from typing import List

from aipass.canary.apps.handlers.json import json_handler
from aipass.canary.apps.handlers.leaderboard import reader
from aipass.cli.apps.modules import console, error
from aipass.prax import logger

JSON_FLAG = "--json"

USAGE_HINT = "drone @canary top 3 scores.txt"


def print_introspection() -> None:
    """Display the top module's usage and the shape of the file it reads."""
    console.print()
    console.print("[bold cyan]top Module[/bold cyan]")
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print("  [cyan]top N FILE[/cyan]          Print the N highest counts, one per line")
    console.print("  [cyan]top --json N FILE[/cyan]   Print the same rows as one JSON array")
    console.print()
    console.print("[dim]The file: one 'name count' per non-blank line, UTF-8, counts added per name[/dim]")
    console.print("[dim]Order: count descending, then name ascending - the same file ranks the same way[/dim]")
    console.print("[dim]Run 'drone @canary top --help' for usage[/dim]")
    console.print()


def print_help() -> None:
    """Rich-formatted help for the top command."""
    console.print()
    console.print("[bold cyan]top - leaderboard reader[/bold cyan]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [green]drone @canary top N FILE[/green]          Print the N highest counts, one per line")
    console.print("  [green]drone @canary top --json N FILE[/green]   One JSON array, nothing else on stdout")
    console.print("  [green]drone @canary top[/green]                 No arguments: this usage, exit 0")
    console.print()

    console.print("[yellow]The file:[/yellow]")
    console.print("  Plain UTF-8 text. Every non-blank line is a name, whitespace, and an integer")
    console.print("  count ('alice 12'). Leading and trailing whitespace is ignored, blank lines are")
    console.print("  skipped, and a name on more than one line has its counts added together before")
    console.print("  anything is ranked.")
    console.print()

    console.print("[yellow]Ordering:[/yellow]")
    console.print("  Count descending, then name ascending by code point within an equal count, so")
    console.print("  the same file always prints the same rows in the same order. Fewer rows than N")
    console.print("  is an answer, not a refusal: what there is gets printed.")
    console.print()

    console.print("[yellow]Refusals (exit 2):[/yellow]")
    console.print("  The reason goes to stderr and nothing at all reaches stdout. No N; an N that is")
    console.print("  not a plain positive integer ('0', '-1', '1.5', a non-ASCII digit); no FILE; a")
    console.print("  FILE that does not exist or cannot be read; a file that is not valid UTF-8; a")
    console.print("  line that is not exactly a name and an integer count; a negative count; more")
    console.print("  arguments than N and FILE.")
    console.print()

    console.print("[yellow]Examples:[/yellow]")
    console.print("  $ drone @canary top 3 scores.txt      [dim]-> alice 12[/dim]")
    console.print('  $ drone @canary top --json 2 scores.txt   [dim]-> [{"name": "alice", "count": 12}][/dim]')
    console.print()


def _render(rows: List[tuple], as_json: bool) -> None:
    """Write the ranked rows to stdout.

    Args:
        rows: The (name, count) pairs already in their final order.
        as_json: True for one JSON array, False for one line per row.
    """
    # markup/highlight/emoji off: a name is caller data, so "[bold]" or ":x:"
    # in one must print as typed rather than be interpreted, and the JSON array
    # must reach stdout byte for byte. soft_wrap keeps one row per line.
    if as_json:
        payload = json.dumps([{"name": name, "count": count} for name, count in rows], ensure_ascii=False)
        console.print(payload, markup=False, highlight=False, emoji=False, soft_wrap=True)
        return

    for name, count in rows:
        console.print(f"{name} {count}", markup=False, highlight=False, emoji=False, soft_wrap=True)


def _top(words: List[str], as_json: bool) -> None:
    """Rank one file, or refuse the arguments by reason.

    Args:
        words: The positional arguments, the --json flag already removed.
        as_json: True to print the JSON array instead of one line per row.
    """
    if not words:
        error("top refused: no N given (write how many rows you want)", suggestion=USAGE_HINT)
        return
    if len(words) < 2:
        error(f"top refused: no FILE given (got N={words[0]!r} and nothing to read)", suggestion=USAGE_HINT)
        return
    if len(words) > 2:
        extra = " ".join(words[2:])
        error(f"top refused: too many arguments (N and FILE, then: {extra})", suggestion=USAGE_HINT)
        return

    try:
        wanted = reader.parse_n(words[0])
        totals = reader.read_totals(Path(words[1]))
    except reader.LeaderboardInvalid as exc:
        logger.warning("[top] refused %r - %s", words, exc.reason)
        error(f"top refused: {exc.reason}", suggestion=USAGE_HINT)
        return

    rows = reader.rank(totals, wanted)
    json_handler.log_operation("top_ranked", {"wanted": wanted, "names": len(totals), "printed": len(rows)})
    _render(rows, as_json)


def handle_command(command: str, args: List[str]) -> bool:
    """Route 'top'.

    Args:
        command: The command name drone routed.
        args: Arguments after the command - N, FILE, and --json.

    Returns:
        True when the command is 'top' (refusals included - the exit code
        carries the failure), False for any other command.
    """
    if command != "top":
        return False

    if not args:
        print_introspection()
        return True

    # Help anywhere never ranks: 'top --help 3 scores.txt' prints the page and
    # reads no file.
    if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
        print_help()
        return True

    words = [arg for arg in args if arg != JSON_FLAG]
    _top(words, JSON_FLAG in args)
    return True
