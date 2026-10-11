# =================== AIPass ====================
# Name: span.py
# Description: Duration command - drone @canary span TEXT prints the total in seconds
# Version: 1.0.0
# Created: 2026-09-19
# Modified: 2026-09-19
# =============================================

"""Duration parser command: a written duration in, a total in seconds out.

``span TEXT`` prints the number. ``span --json TEXT`` prints one JSON object
with the single key ``seconds`` and nothing else on stdout, so a caller can
read it without a parser of its own. Anything that is not a duration is refused
on stderr with exit 2 and NOTHING on stdout - a refusal that printed a number
would be read as an answer by the next command in the pipe.
"""

import json
from typing import List

from aipass.canary.apps.handlers.duration import parser
from aipass.canary.apps.handlers.json import json_handler
from aipass.cli.apps.modules import console, error
from aipass.prax import logger

JSON_FLAG = "--json"

USAGE_HINT = 'drone @canary span "2d 4h"'


def print_introspection() -> None:
    """Display the span module's usage, its units and its limit."""
    console.print()
    console.print("[bold cyan]span Module[/bold cyan]")
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print("  [cyan]span TEXT[/cyan]          Print the duration as a total number of seconds")
    console.print('  [cyan]span --json TEXT[/cyan]   Print {"seconds": N} and nothing else')
    console.print()
    console.print(f"[dim]Units: {parser.UNIT_LIST} - order free, whitespace optional, each unit once[/dim]")
    console.print(f"[dim]Limit: {parser.MAX_DAYS} days ({parser.MAX_SECONDS} seconds)[/dim]")
    console.print("[dim]Run 'drone @canary span --help' for usage[/dim]")
    console.print()


def print_help() -> None:
    """Rich-formatted help for the span command."""
    console.print()
    console.print("[bold cyan]span - duration text to seconds[/bold cyan]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [green]drone @canary span TEXT[/green]          Print the total number of seconds")
    console.print('  [green]drone @canary span --json TEXT[/green]   Print {"seconds": N}, nothing else on stdout')
    console.print("  [green]drone @canary span[/green]               No text: this usage, exit 0")
    console.print()

    console.print("[yellow]The text:[/yellow]")
    console.print(f"  Units are [cyan]{parser.UNIT_LIST}[/cyan], lowercase. Order is free and whitespace is")
    console.print("  optional, so '1h30m', '1h 30m' and '30m 1h' are one and the same duration.")
    console.print(f"  Leading zeros are fine. The total may not exceed {parser.MAX_DAYS} days.")
    console.print()

    console.print("[yellow]Refusals (exit 2):[/yellow]")
    console.print("  The reason goes to stderr and nothing at all reaches stdout. Empty or")
    console.print("  whitespace-only text; a unit given twice; an unknown unit ('2H' is unknown -")
    console.print("  the parser never case-folds); a number that is not a plain non-negative")
    console.print("  integer ('1.5h', '-3h', a non-ASCII digit); a bare number with no unit")
    console.print(f"  ('90'); a total over {parser.MAX_DAYS} days.")
    console.print()

    console.print("[yellow]Examples:[/yellow]")
    console.print("  $ drone @canary span '2d 4h'        [dim]-> 187200[/dim]")
    console.print("  $ drone @canary span 1h30m          [dim]-> 5400[/dim]")
    console.print('  $ drone @canary span --json 45s     [dim]-> {"seconds": 45}[/dim]')
    console.print()


def _span(text: str, as_json: bool) -> None:
    """Print one duration as seconds, or refuse it by reason.

    Args:
        text: The duration as written, already rejoined from the arguments.
        as_json: True to print the single-key JSON object instead of the bare number.
    """
    try:
        seconds = parser.parse_duration(text)
    except parser.DurationInvalid as exc:
        logger.warning("[span] refused %r - %s", text, exc.reason)
        error(f"span refused: {exc.reason}", suggestion=USAGE_HINT)
        return

    json_handler.log_operation("span_parsed", {"seconds": seconds, "as_json": as_json})

    # markup/highlight off: the text is caller data and the JSON object must
    # reach stdout byte for byte, with no Rich colouring or number styling.
    payload = json.dumps({"seconds": seconds}) if as_json else str(seconds)
    console.print(payload, markup=False, highlight=False, soft_wrap=True)


def handle_command(command: str, args: List[str]) -> bool:
    """Route 'span'.

    Args:
        command: The command name drone routed.
        args: Arguments after the command - the duration text, and --json.

    Returns:
        True when the command is 'span' (refusals included - the exit code
        carries the failure), False for any other command.
    """
    if command != "span":
        return False

    if not args:
        print_introspection()
        return True

    # Help anywhere never parses: 'span --help 2d' prints the page, no number.
    if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
        print_help()
        return True

    words = [arg for arg in args if arg != JSON_FLAG]
    _span(" ".join(words), JSON_FLAG in args)
    return True
