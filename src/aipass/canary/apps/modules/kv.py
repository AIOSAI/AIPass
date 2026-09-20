# =================== AIPass ====================
# Name: kv.py
# Description: Store command - drone @canary kv FILE set|get|delete|list keeps pairs between runs
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-09-20
# =============================================

"""Key/value store: a pair written in one run, read back in the next.

``kv FILE set KEY VALUE`` files a value, ``kv FILE get KEY`` prints it back,
``kv FILE delete KEY`` removes it, and ``kv FILE list`` prints every pair sorted
by key. ``kv --json FILE list`` prints the same pairs as one JSON object.

Anything that is not a store, a verb or a storable key is refused on stderr with
exit 2 and NOTHING on stdout. This command's stdout is a value somebody is about
to use, so a partial answer printed beside a refusal would be read as the value.

The rulings made where the contract was silent live in the handler docstring,
``apps/handlers/kv/store.py``, next to the code that keeps them - except the two
that belong to this file and are recorded here:

* **``--json`` is only a flag in first position; a help flag is one anywhere.**
  The contract spells the JSON form ``kv --json FILE list``, and after that
  first word every argument is the caller's own text: ``kv store.txt set --json
  red`` files a key named ``--json`` rather than switching output format. Read
  as a flag anywhere it would still never do the wrong thing quietly - stripped
  out of a data position it leaves ``set`` with one operand, which refuses - so
  the first-position reading costs nothing and keeps a caller's own word
  storable. A HELP flag is the opposite case and is honoured anywhere, because
  a question must never execute: ``kv store.txt set --help colour`` is somebody
  who does not know the verb yet, and storing a pair in answer is exactly the
  harm @seedgo's help_flag_safety standard was written for. The cost is stated
  rather than hidden: a key or a value spelled ``--help`` or ``-h`` cannot be
  set or looked up from the command line. The bare word ``help`` stays in first
  position, because ``help`` is a plausible value.
* **Bare ``kv`` prints the short map, ``kv --help`` the full page.** The
  contract says bare kv prints "the usage", and the map does: every routed form
  is on it. The full page is one command further because that is the shape the
  house standard enforces and every other module in this branch already has -
  ``drone @seedgo checklist`` fails a module with no ``print_introspection``.
"""

import json
import sys
from pathlib import Path
from typing import List, Optional

from aipass.canary.apps.handlers.json import json_handler
from aipass.canary.apps.handlers.kv import store
from aipass.cli.apps.modules import console, error
from aipass.prax import logger

JSON_FLAG = "--json"

VERBS = ("set", "get", "delete", "list")

USAGE_HINT = "drone @canary kv store.txt set colour red"


def print_introspection() -> None:
    """Display the kv module's routed forms and the shape of the file it keeps."""
    console.print()
    console.print("[bold cyan]kv Module[/bold cyan]")
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print("  [cyan]kv FILE set KEY VALUE[/cyan]    File a value under a key")
    console.print("  [cyan]kv FILE get KEY[/cyan]          Print that value alone")
    console.print("  [cyan]kv FILE delete KEY[/cyan]       Remove the pair")
    console.print("  [cyan]kv FILE list[/cyan]             Every pair, sorted by key")
    console.print("  [cyan]kv --json FILE list[/cyan]      The same pairs as one JSON object")
    console.print()
    console.print("[dim]The store: UTF-8 text, one line per pair - the key, a single tab, the value[/dim]")
    console.print("[dim]Order: list sorts by key in code point order; the file keeps insertion order[/dim]")
    console.print("[dim]Run 'drone @canary kv --help' for the file format and every refusal[/dim]")
    console.print()


def print_help() -> None:
    """Rich-formatted help for the kv command."""
    console.print()
    console.print("[bold cyan]kv - a key and value store that survives between runs[/bold cyan]")
    console.print()
    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [green]drone @canary kv FILE set KEY VALUE[/green]   File a value; prints nothing")
    console.print("  [green]drone @canary kv FILE get KEY[/green]         Print that value, and nothing else")
    console.print("  [green]drone @canary kv FILE delete KEY[/green]      Remove the pair; prints nothing")
    console.print("  [green]drone @canary kv FILE list[/green]            Every pair as KEY<tab>VALUE, sorted")
    console.print("  [green]drone @canary kv --json FILE list[/green]     The same pairs as one JSON object")
    console.print("  [green]drone @canary kv[/green]                      No arguments: this page, exit 0")
    console.print()

    console.print("[yellow]The store:[/yellow]")
    console.print("  A UTF-8 text file, one pair per line: the key, a single tab, then the value.")
    console.print("  'set' creates it if it is not there; every other verb needs it to exist. Keys")
    console.print("  are unique, and setting one that is already there replaces the value where it")
    console.print("  already sits. 'list' sorts by key in code point order, so 'Z' comes before 'a'.")
    console.print()

    console.print("[yellow]The flags:[/yellow]")
    console.print("  '--help' and '-h' explain from any position and never run the command, so a")
    console.print("  key or a value spelled like one cannot be set or read from here. '--json' is")
    console.print("  read only as the FIRST argument; anywhere else it is your own text, and")
    console.print("  'kv FILE set --json red' files a key named --json.")
    console.print()

    console.print("[yellow]Refusals (exit 2):[/yellow]")
    console.print("  The reason goes to stderr and nothing at all reaches stdout. No FILE; a store")
    console.print("  that is not there, cannot be read, or is not valid UTF-8; no verb, or one that")
    console.print("  is not set, get, delete or list; a KEY that is empty or holds a tab, a newline")
    console.print("  or a carriage return; set with no VALUE; a VALUE holding one of those three; a")
    console.print("  key get or delete cannot find; a store line that is not a key, a tab and a")
    console.print("  value; a repeated key; --json on any verb but list; too many arguments.")
    console.print()

    console.print("[yellow]Examples:[/yellow]")
    console.print("  $ drone @canary kv store.txt set colour red")
    console.print("  $ drone @canary kv store.txt get colour        [dim]-> red[/dim]")
    # Written as <tab> on purpose: the console renders a real one as spaces,
    # which is the whole reason list does not print through it.
    console.print("  $ drone @canary kv store.txt list              [dim]-> colour<tab>red[/dim]")
    console.print('  $ drone @canary kv --json store.txt list       [dim]-> {"colour": "red"}[/dim]')
    console.print("  $ drone @canary kv store.txt delete colour")
    console.print()


def _write(line: str) -> None:
    """Write one line to stdout, byte for byte.

    Deliberately not the shared console: rich expands a tab to the next
    8-column tab stop, so ``console.print("a\\tb")`` renders 'a' and seven
    spaces (measured 2026-09-20). The contract says a key, a single tab and a
    value, and a caller cutting the second field would get nothing. Values print
    through here too, so both forms carry exactly what the store holds. Refusals
    and help keep the shared console, so this branch's error contract is
    unchanged.

    Args:
        line: The text to write; the newline is added here.
    """
    sys.stdout.write(line + "\n")


def _operands(verb: str, operands: List[str]) -> Optional[List[str]]:
    """Check a verb was given the arguments it needs, or refuse by reason.

    Args:
        verb: The verb, already known to be one of VERBS.
        operands: Everything after the verb.

    Returns:
        The operands when the count is right, None when the call was refused.
    """
    if verb == "set":
        if not operands:
            error("kv refused: set needs a KEY and a VALUE (neither given)", suggestion=USAGE_HINT)
            return None
        if len(operands) == 1:
            error(f"kv refused: set with no VALUE (key '{operands[0]}')", suggestion=USAGE_HINT)
            return None
    elif verb in ("get", "delete") and not operands:
        error(f"kv refused: {verb} needs a KEY", suggestion=USAGE_HINT)
        return None

    wanted = {"set": 2, "get": 1, "delete": 1, "list": 0}[verb]
    if len(operands) > wanted:
        extra = " ".join(operands[wanted:])
        error(f"kv refused: too many arguments for {verb} (then: {extra})", suggestion=USAGE_HINT)
        return None

    return operands


def _run(path: Path, verb: str, operands: List[str], as_json: bool) -> None:
    """Carry out one verb against the store and print whatever it answers.

    Args:
        path: The store file.
        verb: One of VERBS.
        operands: The verb's arguments, already counted.
        as_json: True for the JSON form of list.

    Raises:
        StoreInvalid: The store, the key or the value is refused; caught by the
            caller so the reason reaches stderr rather than a traceback.
    """
    if verb == "set":
        store.set_value(path, operands[0], operands[1])
        json_handler.log_operation("kv_set", {"key": operands[0]})
        return

    if verb == "get":
        value = store.get_value(path, operands[0])
        json_handler.log_operation("kv_read", {"key": operands[0]})
        _write(value)
        return

    if verb == "delete":
        store.delete_key(path, operands[0])
        json_handler.log_operation("kv_deleted", {"key": operands[0]})
        return

    pairs = store.list_pairs(path)
    json_handler.log_operation("kv_listed", {"pairs": len(pairs)})
    if as_json:
        # An empty store prints {} rather than nothing: the JSON form is parsed,
        # and a caller reading zero bytes cannot tell an empty store from a
        # command that printed nothing at all (canary key learning 31).
        _write(json.dumps(dict(pairs), ensure_ascii=False))
        return

    for key, value in pairs:
        _write(f"{key}{store.SEPARATOR}{value}")


def _kv(words: List[str], as_json: bool) -> None:
    """Read the arguments, then run the verb or refuse by reason.

    Args:
        words: The arguments with the leading --json already removed.
        as_json: True when the caller asked for the JSON form.
    """
    if not words:
        error("kv refused: no FILE given (the store to read or write)", suggestion=USAGE_HINT)
        return

    path, rest = Path(words[0]), words[1:]
    if not rest:
        error(f"kv refused: no verb given (one of: {', '.join(VERBS)})", suggestion=USAGE_HINT)
        return

    verb, operands = rest[0], rest[1:]
    if verb not in VERBS:
        error(f"kv refused: '{verb}' is not a kv verb (one of: {', '.join(VERBS)})", suggestion=USAGE_HINT)
        return
    if as_json and verb != "list":
        error(f"kv refused: --json is only for list, not {verb}", suggestion=USAGE_HINT)
        return

    checked = _operands(verb, operands)
    if checked is None:
        return

    try:
        _run(path, verb, checked, as_json)
    except store.StoreInvalid as exc:
        logger.warning("[kv] refused %r - %s", words, exc.reason)
        error(f"kv refused: {exc.reason}", suggestion=USAGE_HINT)


def handle_command(command: str, args: List[str]) -> bool:
    """Route 'kv'.

    Args:
        command: The command name drone routed.
        args: Arguments after the command - the flag, FILE, the verb and its own
            arguments.

    Returns:
        True when the command is 'kv' (refusals included - the exit code carries
        the failure), False for any other command.
    """
    if command != "kv":
        return False

    if not args:
        print_introspection()
        return True

    # Help ANYWHERE explains and never executes, including in a position that
    # would otherwise be a key or a value. 'kv FILE set --help x' is a question
    # from somebody who does not know the verb yet, and answering it with a
    # write is the failure this rule was written for.
    # The bare word stays in first position: 'help' is a plausible VALUE.
    if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
        print_help()
        return True

    as_json = args[0] == JSON_FLAG
    _kv(args[1:] if as_json else args, as_json)
    return True
