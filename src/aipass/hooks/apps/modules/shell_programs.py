# =================== AIPass ====================
# Name: shell_programs.py
# Version: 1.5.0
# Description: Which programs only read, and which only take data — the default-deny tables (DPLAN-0356 phase 4)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-10-01
# Modified: 2026-10-17
# =============================================

"""The tables that invert the gates: what is KNOWN safe, so everything else is not (DPLAN-0356 phase 4).

Off the admin seat a protected, other-branch or .trinity path may be an operand only of a READ_ONLY_PROGRAMS
member (drone's services answer for their own writes); shell_reader, git_gate and edit_gate read these.
"""

import re
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

READ_ONLY_PROGRAMS = frozenset(
    {
        "cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg", "jq", "wc", "stat",
        "ls", "dir", "tree", "diff", "cmp", "file", "du", "realpath", "readlink", "basename", "dirname",
        "sha256sum", "sha1sum", "sha512sum", "md5sum", "b2sum", "cksum", "test", "[", "drone",
        "cd", "pushd", "popd", "read",
    }
)  # fmt: skip

#: find reads, unless one of these makes it act (its -exec programs are read as programs anyway).
_FIND_ACTIONS = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"})

#: sed flags that only change how it reads and prints; -i, -f, -l and any other flag keep sed off the read list.
_SED_SHORT_FLAGS = frozenset("nErsuz")
_SED_LONG_FLAGS = frozenset(
    {"--quiet", "--silent", "--regexp-extended", "--separate", "--null-data", "--unbuffered", "--posix"}
)

#: A sed script of addresses and p, d, q, = only: no s, w, W, e, r or R, so it neither writes nor runs.
_SED_PRINT_SCRIPT = re.compile(r"[0-9$,;!~pdq= ]+")

#: The shells: with -n (noexec) among their leading options they parse a script and run nothing.
SHELL_PROGRAMS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "mksh", "ash", "yash"})
_SHELL_OPTION_ARGS = frozenset({"-o", "+o", "-O", "+O", "--rcfile", "--init-file"})

#: Programs whose operands are data or files, never a program to run (P3).
PLAIN_PROGRAMS = READ_ONLY_PROGRAMS | frozenset(
    {
        "echo", "printf", "find", "mv", "cp", "mkdir", "touch", "ln", "chmod", "chown", "install",
        "sort", "uniq", "cut", "tr", "sed", "awk", "tee", "date", "pwd", "which", "type", "man",
        "true", "false", "sleep", "pytest", "ruff", "mypy", "pyright", "black", "pip", "pip3",
        "git", "gh",  # their operands are subcommands; git_gate reads them
    }
)  # fmt: skip

#: pytest's config flags name a file it only reads; the value alone is carved, every other operand is judged.
_PYTEST_CONFIG_FLAGS = ("-c", "--config-file")

#: Programs whose first plain word is a format string, never a path (devpulse 729ffaa9).
_FORMAT_FIRST = frozenset({"printf", "echo"})

#: Programs a gate of their own answers for (git_gate): their operands are not judged twice.
OWN_GATED = frozenset({"git", "gh"})

#: The command words a scan of an unknown wrapper's operands looks for (P3).
WATCHED_VERBS = frozenset(
    {"rm", "rmdir", "unlink", "shred", "srm", "wipe", "trash", "trash-put", "rimraf", "git", "gh"}
)


def read_only(program: str, argv: tuple[str, ...]) -> bool:
    """True when *program* run with *argv* only reads its operands."""
    if program == "find":
        return not any(arg in _FIND_ACTIONS for arg in argv[1:])
    if program == "sed":
        return _sed_only_prints(argv)
    if program in SHELL_PROGRAMS:
        return syntax_check_only(argv)
    if program == "aipass":
        return argv[1:3] == ("init", "update") and "--dry-run" in argv[3:]
    return program in READ_ONLY_PROGRAMS


def syntax_check_only(argv: tuple[str, ...]) -> bool:
    """True when a shell's options before its script carry -n: it parses and runs nothing (hooks todo 89)."""
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg in _SHELL_OPTION_ARGS:
            index += 2
            continue
        if arg == "--" or len(arg) < 2 or arg[0] not in "-+":
            return False
        if arg[0] == "-" and not arg.startswith("--") and "n" in arg[1:]:
            return True
        index += 1
    return False


def _sed_only_prints(argv: tuple[str, ...]) -> bool:
    """True when sed's every script is a print script and every flag is a reading one (hooks todo 80)."""
    scripts: list[str] = []
    plain: list[str] = []
    script_next = False
    for arg in argv[1:]:
        if script_next:
            scripts.append(arg)
            script_next = False
            continue
        kind = _sed_word(arg)
        if kind == "unread":
            return False
        script_next = kind == "script"
        if kind == "inline":
            scripts.append(arg.split("=", 1)[1])
        elif kind == "operand":
            plain.append(arg)
    if script_next or not (scripts or plain):
        return False
    return all(_SED_PRINT_SCRIPT.fullmatch(script) for script in (scripts or plain[:1]))


def _sed_word(arg: str) -> str:
    """What one sed word is: operand, flag, script (the next word is one), inline (--expression=) or unread."""
    if arg.startswith("--expression="):
        return "inline"
    if arg == "--expression":
        return "script"
    if arg.startswith("--"):
        return "flag" if arg in _SED_LONG_FLAGS else "unread"
    if not arg.startswith("-") or arg == "-":
        return "operand"
    cluster = arg[1:]
    if not set(cluster.removesuffix("e")) <= _SED_SHORT_FLAGS:
        return "unread"
    return "script" if cluster.endswith("e") else "flag"


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


def _operand_texts(argv: tuple[str, ...], program: str = "") -> list[str]:
    """Every operand a path could hide in: plain words, and the value of a --flag=value.

    printf's and echo's first plain word is a FORMAT, never a path; bash_writes reads their redirect.
    """
    texts = []
    format_pending = program in _FORMAT_FIRST
    pytest_from = _pytest_args_start(program, argv)
    config_next = False
    for index, arg in enumerate(argv[1:], 1):
        if config_next:
            config_next = False
            continue
        if pytest_from is not None and index >= pytest_from and arg.split("=", 1)[0] in _PYTEST_CONFIG_FLAGS:
            config_next = "=" not in arg
            continue
        if arg.startswith("-"):
            if "=" in arg:
                texts.append(arg.split("=", 1)[1])
            continue
        if format_pending:
            format_pending = False
            continue
        texts.append(arg)
    return [text for text in texts if text]


def _pytest_args_start(program: str, argv: tuple[str, ...]) -> int | None:
    """Where pytest's own arguments begin: after ``pytest``, or after an interpreter's ``-m pytest``; None otherwise."""
    if program == "pytest":
        return 1
    if program.startswith("python") and argv[1:3] == ("-m", "pytest"):
        return 3
    return None


def first_existing(path: Path) -> Path:
    """*path* itself when it exists, else its nearest existing ancestor (the filesystem root at worst)."""
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return Path(path.anchor)


def _names_a_place(path: Path, places) -> bool:
    """True when *path* exists, or its first existing ancestor is one *places* accepts (devpulse 73358617).

    A flag's value (``-k cd_into``) resolves to a nonexistent path under no branch: it names no file.
    """
    try:
        found = first_existing(path)
    except OSError as exc:
        logger.warning("[HOOKS] shell_programs: %s could not be checked on disk, kept as an operand: %s", path, exc)
        return True
    return found == path or bool(places(found))


def named_operands(invocations: list, places=None) -> list[tuple[str, Path]]:
    """(program, path) for every operand of a program that does not only read (P2), resolved from its cwd.

    A nonexistent operand is kept only when places(its first existing ancestor) is true; None keeps every one.
    """
    carried = _carriers(invocations)
    found = []
    for index, inv in enumerate(invocations):
        if index in carried or not inv.program or read_only(inv.program, inv.argv) or inv.program in OWN_GATED:
            continue
        for text in _operand_texts(inv.argv, inv.program):
            if inv.text and text == inv.text:  # an interpreter's -c program text is read as a program, not a path
                continue
            path = Path(text).expanduser()
            if not path.is_absolute() and inv.cwd:
                path = Path(inv.cwd) / path
            if places is None or _names_a_place(path, places):
                found.append((inv.program, path))
    return found


def named_paths(invocations: list, judge) -> tuple[str, str, str] | None:
    """(program, path, what) for the first operand *judge* names, in a program that does not only read (P2)."""
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
