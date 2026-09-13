# =================== AIPass ====================
# Name: note.py
# Description: Note store command - drone @canary note add|list
# Version: 1.0.0
# Created: 2026-09-12
# Modified: 2026-09-12
# =============================================

"""Append-only note store: add a note, list the notes.

A store that will not parse is refused by file name with a non-zero exit, and
is never reset or rewritten.
"""

from typing import List

from aipass.canary.apps.handlers.json import json_handler
from aipass.canary.apps.handlers.notes import store
from aipass.cli.apps.modules import console, error
from aipass.prax import logger

REPAIR_HINT = "inspect or move the file by hand - canary never rewrites a store it cannot read"


def print_introspection() -> None:
    """Display the note module's commands and where its store lives."""
    console.print()
    console.print("[bold cyan]note Module[/bold cyan]")
    console.print()
    console.print("[yellow]Commands:[/yellow]")
    console.print("  [cyan]note add TEXT[/cyan]   Append one note with a timestamp")
    console.print("  [cyan]note list[/cyan]       Print every note in order")
    console.print()
    console.print(f"[dim]Store: {store.STORE_PATH}[/dim]", markup=True, highlight=False)
    console.print("[dim]Run 'drone @canary note --help' for usage[/dim]")
    console.print()


def print_help() -> None:
    """Rich-formatted help for the note command."""
    console.print()
    console.print("[bold cyan]note - append-only note store[/bold cyan]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [green]drone @canary note add TEXT[/green]   Append one note (text + timestamp)")
    console.print("  [green]drone @canary note list[/green]       Print notes in order, with index and timestamp")
    console.print()
    console.print("[yellow]Refusals (exit 2):[/yellow]")
    console.print("  A store that will not parse is named and left exactly as it is - never reset")
    console.print("  note add with no text, note list with arguments, an unknown subcommand")
    console.print()
    console.print("[yellow]Examples:[/yellow]")
    console.print('  $ drone @canary note add "check the tick-5 interrupt"')
    console.print("  $ drone @canary note list")
    console.print()


def _refuse_corrupt(action: str, exc: store.StoreCorrupt) -> None:
    """Refuse a command because the store will not parse, naming the file.

    Args:
        action: The subcommand that was refused.
        exc: The parse failure, carrying the file and the reason.
    """
    logger.warning("[note] %s refused - store will not parse: %s", action, exc)
    error(
        f"note {action} refused: store will not parse: {exc.path} - {exc.reason}. Store left untouched.",
        suggestion=REPAIR_HINT,
    )


def _add(words: List[str]) -> None:
    """Append one note built from the remaining arguments.

    Args:
        words: The note text, possibly split across several arguments.
    """
    text = " ".join(words)
    if not text.strip():
        error("note add needs text", suggestion='drone @canary note add "remember this"')
        return

    try:
        record = store.append_note(store.STORE_PATH, text)
    except store.StoreCorrupt as exc:
        _refuse_corrupt("add", exc)
        return
    except OSError as exc:
        logger.error("[note] add failed on %s: %s", store.STORE_PATH, exc)
        error(f"note add failed: cannot use store {store.STORE_PATH}: {exc}")
        return

    json_handler.log_operation("note_added", {"chars": len(text)})
    console.print(f"Added note at {record['timestamp']}", markup=False, highlight=False)


def _list(extra: List[str]) -> None:
    """Print every note in store order with its index and timestamp.

    Args:
        extra: Arguments after 'list' - there must be none.
    """
    if extra:
        error(f"note list takes no arguments (got: {' '.join(extra)})", suggestion="drone @canary note list")
        return

    try:
        records = store.read_notes(store.STORE_PATH)
    except store.StoreCorrupt as exc:
        _refuse_corrupt("list", exc)
        return
    except OSError as exc:
        logger.error("[note] list failed on %s: %s", store.STORE_PATH, exc)
        error(f"note list failed: cannot read store {store.STORE_PATH}: {exc}")
        return

    json_handler.log_operation("notes_listed", {"count": len(records)})
    if not records:
        console.print(f"No notes yet - store: {store.STORE_PATH}", markup=False, highlight=False)
        return

    # markup/emoji off: note text is user data, and "[bold]" or ":x:" in a note
    # must print as typed, not be interpreted. soft_wrap keeps one note per line.
    for index, record in enumerate(records, start=1):
        console.print(
            f"{index}. [{record['timestamp']}] {record['text']}",
            markup=False,
            highlight=False,
            emoji=False,
            soft_wrap=True,
        )


def handle_command(command: str, args: List[str]) -> bool:
    """Route 'note add' and 'note list'.

    Args:
        command: The command name drone routed.
        args: Arguments after the command.

    Returns:
        True when the command is 'note' (refusals included - the exit code
        carries the failure), False for any other command.
    """
    if command != "note":
        return False

    if not args:
        print_introspection()
        return True

    # Help anywhere never executes: 'note add --help' must not store "--help".
    if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
        print_help()
        return True

    subcommand, rest = args[0], args[1:]
    if subcommand == "add":
        _add(rest)
    elif subcommand == "list":
        _list(rest)
    else:
        error(f"Unknown note subcommand: {subcommand}", suggestion="drone @canary note --help")
    return True
