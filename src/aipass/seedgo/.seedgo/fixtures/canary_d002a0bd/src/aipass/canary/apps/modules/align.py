# =================== AIPass ====================
# Name: align.py
# Description: Table command - drone @canary align FILE prints a text table with its columns lined up
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-09-20
# =============================================

"""Column aligner: a ragged text table in, a lined-up one out.

``align FILE`` prints every row with each column padded to the widest value in
that column, columns exactly two spaces apart, and nothing trailing at the end
of a line. ``align --json FILE`` prints one JSON array of arrays - every field a
string, every row in file order - and nothing else on stdout, so a caller can
read the table without writing a parser of its own.

Anything that is not a table is refused on stderr with exit 2 and NOTHING on
stdout. A half-aligned table printed beside a refusal would be read as output by
whatever consumes it, and a table is exactly the kind of thing that gets piped.

The rulings made where the contract was silent live in the handler docstring,
``apps/handlers/table/aligner.py``, next to the code that keeps them.
"""

import json
from pathlib import Path
from typing import List

from aipass.canary.apps.handlers.json import json_handler
from aipass.canary.apps.handlers.table import aligner
from aipass.cli.apps.modules import console, error
from aipass.prax import logger

JSON_FLAG = "--json"

USAGE_HINT = "drone @canary align table.txt"


def print_introspection() -> None:
    """Display the align module's usage and the shape of the file it reads."""
    console.print()
    console.print("[bold cyan]align Module[/bold cyan]")
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print("  [cyan]align FILE[/cyan]          Print the table with every column lined up")
    console.print("  [cyan]align --json FILE[/cyan]   Print the same rows as one JSON array of arrays")
    console.print()
    console.print("[dim]The file: two or more fields per non-blank line, separated by spaces or tabs[/dim]")
    console.print("[dim]Order: rows print as written - this lines columns up, it does not sort[/dim]")
    console.print("[dim]Run 'drone @canary align --help' for usage[/dim]")
    console.print()


def print_help() -> None:
    """Rich-formatted help for the align command."""
    console.print()
    console.print("[bold cyan]align - column aligner[/bold cyan]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [green]drone @canary align FILE[/green]          Print the table with its columns lined up")
    console.print("  [green]drone @canary align --json FILE[/green]   One JSON array of arrays, nothing else")
    console.print("  [green]drone @canary align[/green]               No arguments: this usage, exit 0")
    console.print()

    console.print("[yellow]The file:[/yellow]")
    console.print("  Plain UTF-8 text. Every non-blank line is two or more fields separated by one")
    console.print("  or more spaces; a tab separates a column too. Leading and trailing whitespace")
    console.print("  is ignored, blank lines are skipped, and the first non-blank line sets how many")
    console.print("  columns the file has.")
    console.print()

    console.print("[yellow]The layout:[/yellow]")
    console.print("  Every column is left-aligned to the width of its widest value, columns are")
    console.print("  exactly two spaces apart, and no line ends in whitespace - the last column is")
    console.print("  never padded. Rows print in the order they were written; nothing is sorted.")
    console.print("  Width counts code points, so a double-width character counts as one.")
    console.print()

    console.print("[yellow]Refusals (exit 2):[/yellow]")
    console.print("  The reason goes to stderr and nothing at all reaches stdout. No FILE; a FILE")
    console.print("  that does not exist or cannot be read; a file that is not valid UTF-8; a row")
    console.print("  with fewer than two fields; a row whose field count differs from the first")
    console.print("  row's; a file with no non-blank lines at all; more arguments than one FILE.")
    console.print()

    console.print("[yellow]Examples:[/yellow]")
    console.print("  $ drone @canary align table.txt        [dim]-> alice  12  red[/dim]")
    console.print('  $ drone @canary align --json table.txt   [dim]-> [["alice", "12", "red"]][/dim]')
    console.print()


def _render(rows: List[List[str]], as_json: bool) -> None:
    """Write the table to stdout.

    Args:
        rows: The rows in file order, every one the same length.
        as_json: True for one JSON array of arrays, False for aligned lines.
    """
    # markup/highlight/emoji off: a field is caller data, so "[bold]" or ":x:"
    # in one must print as typed rather than be interpreted, and the JSON array
    # must reach stdout byte for byte. soft_wrap keeps one row per line and
    # stops rich from folding a wide table at the terminal width.
    if as_json:
        payload = json.dumps(rows, ensure_ascii=False)
        console.print(payload, markup=False, highlight=False, emoji=False, soft_wrap=True)
        return

    for line in aligner.render(rows):
        console.print(line, markup=False, highlight=False, emoji=False, soft_wrap=True)


def _align(words: List[str], as_json: bool) -> None:
    """Align one file, or refuse the arguments by reason.

    Args:
        words: The positional arguments, the --json flag already removed.
        as_json: True to print the JSON array instead of aligned lines.
    """
    if not words:
        error("align refused: no FILE given (write the table you want lined up)", suggestion=USAGE_HINT)
        return
    if len(words) > 1:
        extra = " ".join(words[1:])
        error(f"align refused: too many arguments (one FILE, then: {extra})", suggestion=USAGE_HINT)
        return

    try:
        rows = aligner.read_rows(Path(words[0]))
    except aligner.TableInvalid as exc:
        logger.warning("[align] refused %r - %s", words, exc.reason)
        error(f"align refused: {exc.reason}", suggestion=USAGE_HINT)
        return

    json_handler.log_operation("table_aligned", {"rows": len(rows), "columns": len(rows[0])})
    _render(rows, as_json)


def handle_command(command: str, args: List[str]) -> bool:
    """Route 'align'.

    Args:
        command: The command name drone routed.
        args: Arguments after the command - FILE and --json.

    Returns:
        True when the command is 'align' (refusals included - the exit code
        carries the failure), False for any other command.
    """
    if command != "align":
        return False

    if not args:
        print_introspection()
        return True

    # Help anywhere never aligns: 'align --help table.txt' prints the page and
    # reads no file.
    if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
        print_help()
        return True

    words = [arg for arg in args if arg != JSON_FLAG]
    _align(words, JSON_FLAG in args)
    return True
