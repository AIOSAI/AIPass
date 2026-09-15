# =================== AIPass ====================
# Name: todo.py
# Description: Todo module — the pad at a glance, its backlog, and restore (CLI routing only)
# Version: 1.0.0
# Created: 2026-09-15
# Modified: 2026-09-15
# =============================================

"""
Todo Module — the sticky-note pad and its backlog (DPLAN-0345, FPLAN-0590 row 5)

    drone @memory todo [@name]             ONE line: the pad against its configured count, and the backlog count
    drone @memory todo backlog [@name]     the backlog: number, date, priority, rolled, reason, task
    drone @memory todo restore <number>    one backlog todo back onto YOUR pad, under the next number

Routing and printing only. What resolves, what is read and what is refused
lives in handlers/rollover/todo_report.py; the roll and the restore
themselves in handlers/rollover/todo_roll.py.

Bare ``todo`` answers with the pad line, not an introspection page: that line
IS the verb (DPLAN-0345 @memory review §4 - one line, pad count and backlog
count). The module map prints after a refused argument; the manual under
``--help``.

Every refusal goes through ``error()``, so the entry point exits 2 - a refusal
that exits 0 is only half a refusal. ``--json`` is not taken: no consumer reads
these verbs by machine, and the flag is refused like any other unknown
argument rather than silently ignored.
"""

import os
import sys
from typing import List

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from rich import box
from rich.panel import Panel

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, warning
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.cli.help_flags import wants_help
from aipass.memory.apps.handlers.cli.branch_flag import BRANCH_FLAG, read_branch_arg
from aipass.memory.apps.handlers.rollover import todo_report

MODULE_NAME = "todo"

_SUBCOMMANDS = {
    "backlog": "List a branch's backlog, one record per line (the task, never status)",
    "restore": "Move one backlog todo back onto your own pad under the next number",
}

# Named in every refusal, so a mistyped line says what would have worked.
_FORMS = (
    "drone @memory todo [@name]",
    "drone @memory todo backlog [@name]",
    "drone @memory todo restore <number>",
)


# =============================================================================
# COMMAND HANDLER
# =============================================================================


def handle_command(command: str, args: List[str]) -> bool:
    """
    Route the ``todo`` verbs.

    Routing:
        todo [@name | --branch @name]          -> one pad line
        todo backlog [@name | --branch @name]  -> the backlog, one record per line
        todo restore <number>                  -> restore onto the caller's own pad
        todo --help / -h / help (any slot)     -> print_help()

    Args:
        command: Command name
        args: Tokens after ``todo``

    Returns:
        True for ``todo`` (handled, possibly refused), False for any other command
    """
    if command != "todo":
        return False

    # A help flag ANYWHERE wins: `todo restore 3 --help` must never restore.
    if wants_help(args, allow_bare_word=True):
        print_help()
        return True

    json_handler.log_operation("todo_command", {"args": list(args)}, module_name=MODULE_NAME)

    if not args or args[0].startswith(("@", BRANCH_FLAG)):
        _print_pad(args)
        return True

    sub, rest = args[0], args[1:]
    if sub == "backlog":
        _print_backlog(rest)
        return True
    if sub == "restore":
        _restore(rest)
        return True

    _refuse(f"Unknown todo argument: '{sub}'")
    print_introspection()
    return True


# =============================================================================
# ROUTING HELPERS
# =============================================================================


def _refuse(message: str) -> None:
    """One refusal naming the valid forms; ``error()`` marks the command failed (exit 2)."""
    logger.info(f"[todo] Refused: {message}")
    error(message, suggestion="Valid forms: " + " | ".join(_FORMS))


def _print(report: dict) -> None:
    """Print one todo report; an ``error`` report goes through error(), so the command exits non-zero.

    ``markup`` and ``highlight`` off so a task or a path prints as written;
    ``soft_wrap`` so a long line is never folded in two on an 80-column pipe.
    """
    text = str(report.get("text"))
    if report.get("level") == todo_report.ERROR:
        error(text)
        return
    if report.get("level") == todo_report.WARNING:
        warning(text)
        return
    console.print(text, markup=False, highlight=False, soft_wrap=True)


def _branch(tokens: List[str], verb: str) -> tuple[str | None, bool]:
    """``@name`` or ``--branch @name`` -> ``(branch, refused)``; a refusal is printed."""
    branch, problem = read_branch_arg(tokens)
    if problem:
        _refuse(f"{problem} ({verb})")
        return None, True
    return branch, False


def _print_pad(tokens: List[str]) -> None:
    """Bare ``todo``: the one pad line."""
    branch, refused = _branch(tokens, "todo")
    if not refused:
        _print(todo_report.pad_summary(branch))


def _print_backlog(tokens: List[str]) -> None:
    """``todo backlog [@name]``: a header, then one line per record."""
    branch, refused = _branch(tokens, "todo backlog")
    if refused:
        return
    for report in todo_report.backlog_listing(branch):
        _print(report)


def _restore(tokens: List[str]) -> None:
    """``todo restore <number> [--branch @name]``: the caller's own pad only."""
    if not tokens or todo_report.parse_todo_number(tokens[0]) is None:
        got = f"'{tokens[0]}'" if tokens else "nothing"
        _refuse(f"todo restore needs the todo's number from the backlog, got {got}")
        return
    branch, refused = _branch(tokens[1:], "todo restore")
    if not refused:
        _print(todo_report.restore_pad(tokens[0], branch))


# =============================================================================
# INTROSPECTION & HELP
# =============================================================================


def print_introspection() -> None:
    """Display module introspection (seedgo standard): handlers, subcommands, next steps."""
    console.print()
    console.print("[bold cyan]todo Module[/bold cyan]")
    console.print("[dim]The sticky-note pad and its backlog file: count, list, restore[/dim]")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/rollover/[/cyan]  [dim]todo_report.py, todo_roll.py[/dim]")
    console.print("  [cyan]handlers/cli/[/cyan]       [dim]help_flags.py, branch_flag.py[/dim]")
    console.print()
    console.print("[yellow]Subcommands:[/yellow]")
    for sub, desc in _SUBCOMMANDS.items():
        console.print(f"  [green]{sub:<10}[/green] {desc}")
    console.print()
    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @memory todo[/green]              [dim]# One line: your pad and your backlog[/dim]")
    console.print("  [green]drone @memory todo backlog[/green]      [dim]# Your backlog, one record per line[/dim]")
    console.print("  [green]drone @memory todo restore 7[/green]    [dim]# #7 back onto your pad, re-numbered[/dim]")
    console.print("  [green]drone @memory todo --help[/green]       [dim]# Full usage guide[/dim]")
    console.print()


def print_help() -> None:
    """Display todo module help."""
    console.print()
    console.print(
        Panel.fit("[bold cyan]todo Module - The Pad and the Backlog[/bold cyan]", border_style="cyan", box=box.ROUNDED)
    )
    console.print()
    console.print("[bold]USAGE:[/bold]")
    # `\\[` renders `[`: Rich reads `[@name]` as a tag. One source char wider, same column on screen.
    console.print("  drone @memory todo \\[@name]            One line: pad N of COUNT, backlog M")
    console.print("  drone @memory todo --branch @name     The same line, for a named branch")
    console.print("  drone @memory todo backlog \\[@name]    List a backlog, one record per line")
    console.print("  drone @memory todo restore <number>   Put one backlog todo back on YOUR pad")
    console.print()
    console.print("[bold]WHICH BRANCH:[/bold]")
    console.print("  Absent: the branch your working directory sits in (drone's caller cwd).")
    console.print("  At the repo root nothing resolves, and one line says so - pass @name.")
    console.print()
    console.print("[bold]THE PAD:[/bold]")
    console.print("  COUNT: rollover.defaults.local.todos.count, per branch (config get).")
    console.print("  [cyan]drone @memory rollover run[/cyan] rolls the oldest by number to")
    console.print("  .backup/todo/<branch>/backlog.json, one branch at a time; the trinity")
    console.print("  push moves non-canonical todos there too. File only, never vectors.")
    console.print()
    console.print("[bold]BACKLOG:[/bold]")
    console.print("  Each record: number · date · priority (when set) · rolled · reason · task.")
    console.print("  The number is the todo's ORIGINAL number. status is never printed.")
    console.print("  No file yet is a state, not an error (exit 0): .backup/ is gitignored,")
    console.print("  so a fresh clone has no backlog. An unreadable file is refused (non-zero).")
    console.print()
    console.print("[bold]RESTORE:[/bold]")
    console.print("  Your own branch only: restore writes .trinity/local.json, so a --branch")
    console.print("  naming another branch is refused, and so is a caller in no branch.")
    console.print("  Refused when the pad already holds COUNT, when no record carries the")
    console.print("  number, or when several do (the candidates are named). The todo returns")
    console.print("  as max(pad and backlog numbers) + 1; task, date and priority unchanged.")
    console.print("  Every refusal exits non-zero.")
    console.print()
    console.print("[bold]EXAMPLES:[/bold]")
    console.print("  drone @memory todo")
    console.print("  drone @memory todo backlog @devpulse")
    console.print("  drone @memory todo restore 7")
    console.print()
