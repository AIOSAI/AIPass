# =================== AIPass ====================
# Name: provider_launch.py
# Version: 1.0.0
# Description: Where a provider CLI started from the Bash tool would run, judged against the caller's own branch
# Branch: hooks
# Layer: apps/modules
# Created: 2026-11-15
# Modified: 2026-11-15
# =============================================

"""Names a provider session (claude, codex, opencode) that would start outside the caller's own branch.

A session's directory makes it that branch's seat for every gate, so off the admin seat a provider CLI
runs only inside the caller's own branch: the directory of the nearest passport above the session cwd.
edit_gate refuses what this names and asks the admin grant; the dispatch services start sessions from
Python, not through an agent's Bash tool, so they never reach this.
"""

import glob
import os
import re
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.modules import admin_seat
from aipass.hooks.apps.modules.shell_programs import PROVIDER_CLIS

CONSOLE = err_console

#: Each CLI's own directory flags, read from its --help: codex -C/--cd and --add-dir; claude --add-dir takes several.
_DIR_FLAGS = ("-C", "--cd", "--add-dir")
_MANY_DIRS = "--add-dir"

#: opencode's positional operand is the directory it starts in; claude's and codex's are prompts.
_DIR_OPERANDS = frozenset({"opencode"})

#: Wrappers that move the directory of the program they carry.
_CARRIER_DIR_FLAGS = {"env": ("-C", "--chdir"), "sudo": ("-D", "--chdir"), "systemd-run": ("--working-directory",)}
_UNIT_DIR = "WorkingDirectory="
#: systemd-run with no directory runs in / (system) or the home dir (--user), per systemd.exec; -d keeps the cwd.
_SAME_DIR = frozenset({"-d", "--same-dir"})

#: Launchers that run a command detached or later: the directory it would run in is not followed.
_DEFERRED = frozenset({"tmux", "screen", "at", "batch", "dtach", "abduco"})
_PROVIDER_WORD = re.compile(r"\b(?:claude|codex|opencode)\b")

_UNFOLDED = frozenset("$`")
_GLOB = frozenset("*?[")


def foreign_launch(invocations: list, command: str, cwd: str) -> tuple[str, str] | None:
    """(where, why) for the first provider launch outside the caller's own branch; None when every one is inside."""
    root = admin_seat.branch_root(cwd)
    for index, inv in enumerate(invocations):
        if inv.program in _DEFERRED and _PROVIDER_WORD.search(command):
            return inv.program, f"{inv.program} would start it detached or later, where this gate cannot follow it."
        if inv.program not in PROVIDER_CLIS:
            continue
        for text, base in _directories(inv, invocations[:index]):
            found = _outside(text, base, root)
            if found is not None:
                return found
    return None


def _directories(inv, outers: list) -> list[tuple[str, str]]:
    """(directory as written, the directory it is read from) for every place this launch runs in or reaches."""
    found = [(".", inv.cwd)]
    argv = inv.argv
    index = 1
    while index < len(argv):
        word = argv[index]
        flag, equals, value = word.partition("=")
        if flag in _DIR_FLAGS and equals:
            found.append((value, inv.cwd))
        elif word in _DIR_FLAGS:
            values = _flag_values(argv, index + 1, many=word == _MANY_DIRS)
            found.extend((value, inv.cwd) for value in values)
            index += len(values)
        elif inv.program in _DIR_OPERANDS and not word.startswith("-"):
            found.append((word, inv.cwd))
        index += 1
    for outer in outers:
        if len(outer.argv) > len(argv) and tuple(outer.argv[-len(argv) :]) == tuple(argv):
            found.extend((text, outer.cwd) for text in _carrier_dirs(outer.program, outer.argv[: -len(argv)]))
    return found


def _flag_values(argv: tuple[str, ...], start: int, many: bool) -> list[str]:
    """The value after a directory flag; with *many*, every word up to the next flag."""
    values = list(argv[start : start + 1])
    while many and start + len(values) < len(argv) and not argv[start + len(values)].startswith("-"):
        values.append(argv[start + len(values)])
    return values


def _carrier_dirs(program: str, words: tuple[str, ...]) -> list[str]:
    """The directories a wrapper (env -C, sudo -D, systemd-run) moves its program into; *words* end before it."""
    flags = _CARRIER_DIR_FLAGS.get(program, ())
    found = []
    for index, word in enumerate(words[1:], 1):
        flag, equals, value = word.partition("=")
        if flag in flags and equals:
            found.append(value)
        elif word in flags and index + 1 < len(words):
            found.append(words[index + 1])
        elif program == "systemd-run" and _UNIT_DIR in word:
            found.append(word.split(_UNIT_DIR, 1)[1])
    if program == "systemd-run" and not found and not _SAME_DIR & set(words):
        found.append("~" if "--user" in words else "/")
    return found


def _outside(text: str, base: str, root: Path | None) -> tuple[str, str] | None:
    """(where, why) when *text*, read from *base*, is not inside *root*; None when it is."""
    if not base and not Path(text).is_absolute():
        return text, "the directory it would run in is unknown here (a cd this gate cannot follow)."
    if _UNFOLDED & set(text):
        return text, f"{text} still expands in the shell, so where it would run is unknown here."
    if _GLOB & set(text):
        matches = glob.glob(os.path.expanduser(text), root_dir=base or None)
        if not matches:
            return text, f"{text} matches nothing this gate can see, so where it would run is unknown here."
    else:
        matches = [os.path.expanduser(text)]
    for match in matches:
        place = (Path(base) / match).resolve()
        if root is None:
            return str(place), "you have no branch: no passport above the session cwd."
        if place != root and root not in place.parents:
            return str(place), f"{place} is not inside your own branch ({root})."
    return None


def print_introspection() -> None:
    """Print the rule for drone routing: the contract, never a live verdict."""
    CONSOLE.print("[bold cyan]provider_launch[/bold cyan] — where a provider session started from Bash would run")
    CONSOLE.print(f"[dim]CLIs: {', '.join(sorted(PROVIDER_CLIS))}; directory flags: {', '.join(_DIR_FLAGS)}.[/dim]")
    CONSOLE.print("[dim]Consumed by edit_gate (handlers/security/); the admin grant is asked there.[/dim]")
