# =================== AIPass ====================
# Name: provider_launch.py
# Version: 1.1.1
# Description: Where a provider CLI started from the Bash tool would run, judged against the caller's own branch
# Branch: hooks
# Layer: apps/modules
# Created: 2026-11-15
# Modified: 2026-11-17
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
import shlex
from pathlib import Path

from aipass.cli import err_console
from aipass.hooks.apps.modules import admin_seat, shell_reader
from aipass.hooks.apps.modules.shell_programs import PROVIDER_CLIS
from aipass.hooks.apps.modules.shell_programs import PROVIDER_DIR_FLAGS as _DIR_FLAGS

CONSOLE = err_console

#: claude --add-dir takes several directories.
_MANY_DIRS = "--add-dir"

#: opencode's positional operand is the directory it starts in; claude's and codex's are prompts.
_DIR_OPERANDS = frozenset({"opencode"})

#: Wrappers that move the directory of the program they carry.
_CARRIER_DIR_FLAGS = {"env": ("-C", "--chdir"), "sudo": ("-D", "--chdir"), "systemd-run": ("--working-directory",)}
_UNIT_DIR = "WorkingDirectory="
#: systemd-run with no directory runs in / (system) or the home dir (--user), per systemd.exec; -d keeps the cwd.
_SAME_DIR = frozenset({"-d", "--same-dir"})

#: Launchers that run a command detached or later. tmux and screen are read below; at, batch, dtach and
#: abduco are not installed to read, so a command naming a provider through them stays refused.
_DEFERRED = frozenset({"tmux", "screen", "at", "batch", "dtach", "abduco"})

#: tmux's own flags that take a value (tmux -h, tmux list-commands). Top-level -c is a shell command.
_TMUX_VALUED = "cfLST"
#: The tmux commands that start a command, and their flags that take a value. -c is the start directory;
#: without it the command runs in the tmux client's cwd (measured, tmux 3.6). Any other command stays refused.
_TMUX_STARTS = {
    "new-session": "cefFnstxy",
    "new": "cefFnstxy",
    "new-window": "ceFnt",
    "neww": "ceFnt",
    "split-window": "ceFlt",
    "splitw": "ceFlt",
}
#: screen runs in the directory it is invoked from (man screen, chdir). -c reads a config that may chdir,
#: -X sends a command to a running session, -x/-r/-R attach one: none of those directories is read here.
_SCREEN_VALUED = "STtpehs"
_SCREEN_UNREAD = frozenset("cXxrR")
_PROVIDER_WORD = re.compile(r"\b(?:claude|codex|opencode)\b")

_UNFOLDED = frozenset("$`")
_GLOB = frozenset("*?[")


def foreign_launch(invocations: list, command: str, cwd: str) -> tuple[str, str] | None:
    """(where, why) for the first provider launch outside the caller's own branch; None when every one is inside."""
    return _first_outside(invocations, command, admin_seat.branch_root(cwd))


def _first_outside(invocations: list, command: str, root: Path | None) -> tuple[str, str] | None:
    for index, inv in enumerate(invocations):
        if inv.program in _DEFERRED and _PROVIDER_WORD.search(command):
            found = _detached_outside(inv, root)
            if found is not None:
                return found
            continue
        if inv.program not in PROVIDER_CLIS or _DEFERRED & set(inv.via.split()):
            continue
        for text, base in _directories(inv, invocations[:index]):
            found = _outside(text, base, root)
            if found is not None:
                return found
    return None


def _detached_outside(inv, root: Path | None) -> tuple[str, str] | None:
    """A tmux or screen launch judged where it starts, its command re-read from there; others refused."""
    readers = {"tmux": _tmux_launch, "screen": _screen_launch}
    launch = readers[inv.program](inv.argv) if inv.program in readers else None
    if launch is None:
        return inv.program, f"{inv.program} would start it where this gate cannot read the directory."
    start, command = launch
    if _GLOB & set(start):
        return start, f"{start} is a pattern, so where {inv.program} would start it is unknown here."
    found = _outside(start, inv.cwd, root)
    if found is not None:
        return found
    place = str((Path(inv.cwd) / os.path.expanduser(start)).resolve())
    return _first_outside(shell_reader.invocations(command, place), command, root)


def _options(argv: tuple[str, ...], start: int, valued: str) -> tuple[dict[str, str], int]:
    """getopt over *argv* from *start*: ({flag: value} for valued flags, index of the first operand)."""
    found: dict[str, str] = {}
    index = start
    while index < len(argv) and argv[index].startswith("-") and argv[index] != "-":
        word = argv[index]
        index += 1
        if word == "--":
            break
        for at, flag in enumerate(word[1:], 1):
            if flag in valued:
                rest = word[at + 1 :]
                found[flag] = rest if rest else (argv[index] if index < len(argv) else "")
                index += 0 if rest else 1
                break
            found.setdefault(flag, "")
    return found, index


def _tmux_launch(argv: tuple[str, ...]) -> tuple[str, str] | None:
    """(start directory, shell command) of a tmux command that starts one; None when it is not read."""
    top, index = _options(argv, 1, _TMUX_VALUED)
    if "c" in top or index >= len(argv) or argv[index] not in _TMUX_STARTS:
        return None
    flags, index = _options(argv, index + 1, _TMUX_STARTS[argv[index]])
    operands = argv[index:]
    if not operands or any(word.endswith(";") for word in operands):
        return None
    return flags.get("c") or ".", operands[0] if len(operands) == 1 else shlex.join(operands)


def _screen_launch(argv: tuple[str, ...]) -> tuple[str, str] | None:
    """(".", the program and its words) for a screen that starts a program here; None when it is not read."""
    if any(word in ("-ls", "-list", "-wipe") for word in argv[1:]):
        return None
    flags, index = _options(argv, 1, _SCREEN_VALUED)
    if _SCREEN_UNREAD & set(flags) or index >= len(argv):
        return None
    return ".", shlex.join(argv[index:])


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
