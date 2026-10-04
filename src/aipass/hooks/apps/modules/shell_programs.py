# =================== AIPass ====================
# Name: shell_programs.py
# Version: 1.0.1
# Description: Which programs only read, and which only take data — the default-deny tables (DPLAN-0356 phase 4)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-10-01
# Modified: 2026-10-04
# =============================================

"""The tables that invert the gates: what is KNOWN safe, so everything else is not (DPLAN-0356 phase 4).

Phases 1 to 3 listed what writes, deletes and launches. The final review's
verdict: that list is permanently incomplete — a write verb nobody listed passed
every file fence at once. Phase 4 turns it around for the paths that matter:

  - :data:`READ_ONLY_PROGRAMS` (P2). Off the admin seat, a protected path, a path
    in another branch or a ``.trinity`` path may appear as an operand only of a
    program on this short list. Anything else naming it is refused, whatever it is.
  - :data:`PLAIN_PROGRAMS` (P3). Programs whose operands are data or files, never a
    program to run. Every OTHER command word may be a launcher nobody tabled, so
    modules/shell_reader scans its operands for a delete verb, git or gh and reads
    from there as a nested command.

``drone`` is on both: it is the router, and every service it reaches answers for
its own writes. modules/shell_reader, handlers/security/git_gate and edit_gate
read these; no other copy exists.
"""

from pathlib import Path

from aipass.cli.apps.modules import err_console

CONSOLE = err_console

#: Programs that read their operands and write nothing of their own (P2).
READ_ONLY_PROGRAMS = frozenset(
    {
        "cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg", "jq", "wc", "stat",
        "ls", "dir", "tree", "diff", "cmp", "file", "du", "realpath", "readlink", "basename", "dirname",
        "sha256sum", "sha1sum", "sha512sum", "md5sum", "b2sum", "cksum", "test", "[", "drone",
        # A directory change writes nothing (trigger a837a4c7: `cd <dir> && pytest` was refused as a write).
        "cd", "pushd", "popd",
    }
)  # fmt: skip

#: find reads, unless one of these makes it act (its -exec programs are read as programs anyway).
_FIND_ACTIONS = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"})

#: Programs whose operands are data or files, never a program to run (P3).
PLAIN_PROGRAMS = READ_ONLY_PROGRAMS | frozenset(
    {
        "echo", "printf", "find", "mv", "cp", "mkdir", "touch", "ln", "chmod", "chown", "install",
        "sort", "uniq", "cut", "tr", "sed", "awk", "tee", "date", "pwd", "which", "type", "man",
        "true", "false", "sleep", "pytest", "ruff", "mypy", "pyright", "black", "pip", "pip3",
        "git", "gh",  # their operands are subcommands; git_gate reads them
    }
)  # fmt: skip

#: Programs a gate of their own answers for (git_gate): their operands are not judged twice.
OWN_GATED = frozenset({"git", "gh"})

#: The command words a scan of an unknown wrapper's operands looks for (P3).
WATCHED_VERBS = frozenset(
    {"rm", "rmdir", "unlink", "shred", "srm", "wipe", "trash", "trash-put", "rimraf", "git", "gh"}
)


def read_only(program: str, argv: tuple[str, ...]) -> bool:
    """True when *program* run with *argv* only reads its operands.

    Args:
        program: The program the shell runs, as shell_reader names it.
        argv: Its whole argument vector, the program word first.

    Returns:
        True for a READ_ONLY_PROGRAMS member, and for find without an acting flag.
    """
    if program == "find":
        return not any(arg in _FIND_ACTIONS for arg in argv[1:])
    return program in READ_ONLY_PROGRAMS


def _carriers(invocations: list) -> set[int]:
    """Indexes of invocations that only carry a later one (sudo cat x carries cat x): judged through it."""
    carried = set()
    for index, outer in enumerate(invocations):
        for inner in invocations[index + 1 :]:
            size = len(inner.argv)
            if 0 < size < len(outer.argv) and tuple(outer.argv[-size:]) == tuple(inner.argv):
                carried.add(index)
                break
    return carried


def _operand_texts(argv: tuple[str, ...]) -> list[str]:
    """Every operand a path could hide in: plain words, and the value of a --flag=value."""
    texts = []
    for arg in argv[1:]:
        if arg.startswith("-"):
            if "=" in arg:
                texts.append(arg.split("=", 1)[1])
            continue
        texts.append(arg)
    return [text for text in texts if text]


def named_operands(invocations: list) -> list[tuple[str, Path]]:
    """(program, path) for every operand of a program that does not only read (P2), resolved from its cwd.

    Args:
        invocations: shell_reader.invocations() of one command.

    Returns:
        Each operand of each acting program, as the absolute path it would name.
        A launcher that only carries a later program is judged through that program.
    """
    carried = _carriers(invocations)
    found = []
    for index, inv in enumerate(invocations):
        if index in carried or not inv.program or read_only(inv.program, inv.argv) or inv.program in OWN_GATED:
            continue
        for text in _operand_texts(inv.argv):
            if inv.text and text == inv.text:  # an interpreter's -c program text is read as a program, not a path
                continue
            path = Path(text).expanduser()
            if not path.is_absolute() and inv.cwd:
                path = Path(inv.cwd) / path
            found.append((inv.program, path))
    return found


def named_paths(invocations: list, judge) -> tuple[str, str, str] | None:
    """(program, path, what) for the first operand *judge* names, in a program that does not only read (P2).

    Args:
        invocations: shell_reader.invocations() of one command.
        judge: Called as judge(path, cwd); returns what the path is, or None.

    Returns:
        The first refused (program, path, what), or None when every naming program only reads.
    """
    for program, path in named_operands(invocations):
        what = judge(path, "")
        if what:
            return program, str(path), what
    return None


def print_introspection() -> None:
    """Print module structure for drone routing: the tables, as they stand."""
    CONSOLE.print("[bold cyan]shell_programs[/bold cyan] — the default-deny tables (DPLAN-0356 phase 4)")
    CONSOLE.print(f"  read-only ({len(READ_ONLY_PROGRAMS)}): {', '.join(sorted(READ_ONLY_PROGRAMS))}")
    CONSOLE.print(f"  plain ({len(PLAIN_PROGRAMS)}), watched in unknown wrappers: {', '.join(sorted(WATCHED_VERBS))}")
