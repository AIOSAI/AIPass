# =================== AIPass ====================
# Name: shell_programs.py
# Version: 1.5.1
# Description: Which programs only read, and which only take data — the default-deny tables (DPLAN-0356 phase 4)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-10-01
# Modified: 2026-10-24
# =============================================

"""The tables that invert the gates: what is KNOWN safe, so everything else is not (DPLAN-0356 phase 4).

Off the admin seat a protected, other-branch or .trinity path may be an operand only of a READ_ONLY_PROGRAMS
member (drone's services answer for their own writes); shell_reader, git_gate and edit_gate read these.
"""

import os
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

# Launchers: the program they run comes after their own flags (the valued ones take the next
# word) and, for a few, a fixed number of operands of their own (timeout's duration).
LAUNCHER_VALUED = {
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U", "--user", "--group", "--host", "--prompt",
             "--close-from", "--chdir", "--chroot", "--command-timeout", "--other-user"},
    "doas": {"-u", "-C"},
    "env": {"-u", "--unset", "-C", "--chdir"},
    "nohup": set(), "setsid": set(), "unbuffer": set(), "busybox": set(), "builtin": set(),
    "noglob": set(), "nocorrect": set(), "valgrind": set(), "catchsegv": set(),
    "time": {"-f", "--format", "-o", "--output"},
    "nice": {"-n", "--adjustment"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
    "ionice": {"-c", "-n", "-p", "-P", "-u", "--class", "--classdata"},
    "chrt": set(), "taskset": set(),
    "flock": {"-w", "--timeout", "-E", "--conflict-exit-code"},
    "caffeinate": {"-w", "-t"},
    "strace": {"-o", "-e", "-p", "-s", "-u", "-E", "-a", "-b", "-I", "-O", "-S", "-X", "-P"},
    "ltrace": {"-o", "-e", "-p", "-s", "-u", "-n", "-a", "-l"},
    "systemd-run": {"-u", "--unit", "-p", "--property", "-E", "--setenv", "--uid", "--gid", "--working-directory",
                    "-M", "--machine", "--slice", "--description"},
    "xargs": {"-I", "-n", "-L", "-P", "-d", "-E", "-s", "-a", "--max-args", "--max-lines", "--max-procs",
              "--delimiter", "--eof", "--max-chars", "--arg-file", "--replace"},
    "exec": {"-a"},
    "command": set(),
    "su": {"-s", "--shell", "-g", "--group", "-G"},
    "runuser": {"-u", "--user", "-s", "--shell", "-g", "--group", "-G"},
    "script": {"-t", "--timing", "-T", "--log-timing", "-I", "-O", "-B", "-E", "--echo"},
    "watch": {"-n", "--interval", "-d"},
}  # fmt: skip
LAUNCHER_OPERANDS = {"timeout": 1, "chrt": 1, "taskset": 1, "flock": 1}

# A flag after which the launcher's text is a PROGRAM re-read as shell (su -c 'rm x').
LAUNCHER_PROGRAM_FLAGS = {
    "su": ("-c", "--command"), "runuser": ("-c", "--command"), "script": ("-c", "--command"),
    "flock": ("-c", "--command"), "env": ("-S", "--split-string"),
}  # fmt: skip

# Task runners whose `run` (or `exec`) word runs the next program: uv run git push is git.
RUNNERS = {"uv": "run", "poetry": "run", "pipenv": "run", "pdm": "run", "hatch": "run", "conda": "run", "pnpm": "exec"}
RUNNER_VALUED = {"--with", "--python", "-p", "--directory", "--project", "--env-file", "--extra", "--group",
                  "--package", "--index", "--index-url", "-n", "--name", "--prefix", "-e", "--env"}  # fmt: skip

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

#: Programs that delete every operand (rm_gate's verbs, the protected lane's delete role).
DELETE_PROGRAMS = frozenset({"rm", "rmdir", "unlink", "shred", "srm", "wipe", "trash", "trash-put", "rimraf"})

#: The command words a scan of an unknown wrapper's operands looks for (P3).
WATCHED_VERBS = DELETE_PROGRAMS | OWN_GATED


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


def sed_scripts(words: list[str]) -> tuple[list[str], list[str], list[str]]:
    """sed's scripts (-e, --expression, else its first operand), its script files (-f, --file) and its inputs."""
    found: dict[str, list[str]] = {"e": [], "f": [], "l": []}
    operands: list[str] = []
    index = 0
    while index < len(words):
        word = words[index]
        index += 1
        if word == "--":
            operands.extend(words[index:])
            break
        letter, value = _sed_option(word)
        if letter and value is None:
            value = words[index] if index < len(words) else ""
            index += 1
        if letter:
            found[letter].append(value or "")
        elif not word.startswith("-"):
            operands.append(word)
    if found["e"] or found["f"]:
        return found["e"], found["f"], operands
    return operands[:1], [], operands[1:]


def _sed_option(word: str) -> tuple[str, str | None]:
    """("e"|"f"|"l", its value or None when the next word is it) for an option taking one; ("", None) else."""
    long = {"--expression": "e", "--file": "f", "--line-length": "l"}
    name, eq, value = word.partition("=")
    if name in long:
        return long[name], value if eq else None
    if word.startswith("--") or not word.startswith("-"):
        return "", None
    for at, letter in enumerate(word[1:], 2):
        if letter == "i":
            break
        if letter in "efl":
            return letter, word[at:] or None
    return "", None


def _line_end(script: str, index: int) -> int:
    end = script.find("\n", index)
    return len(script) if end < 0 else end


def _sed_past(script: str, index: int, delimiter: str) -> int:
    """The index just past the unescaped *delimiter* that closes a regex or replacement; -1 when none does."""
    while 0 <= index < len(script):
        if script[index] == "\\":
            index += 2
        elif script[index] == delimiter:
            return index + 1
        else:
            index += 1
    return -1


def _sed_address(script: str, index: int) -> int:
    """The index of the command letter after a line's addresses and any `!`; -1 on an unclosed regex."""
    while 0 <= index < len(script):
        char = script[index]
        if char in "0123456789$~,+ \t!":
            index += 1
            continue
        if char not in "/\\":
            break
        delimiter = "/" if char == "/" else script[index + 1 : index + 2]
        index = _sed_past(script, index + (1 if char == "/" else 2), delimiter or "\n")
        while 0 <= index < len(script) and script[index] in "IM":
            index += 1
    return index


def _sed_substitute(script: str, index: int, command: str, writes: list[str]) -> tuple[int, str]:
    """Past an s or y command from its delimiter: (the next index, why it is unread or "")."""
    if index >= len(script) or script[index] in "\\\n":
        return index, f"a sed {command} command with no usable delimiter"
    delimiter = script[index]
    index = _sed_past(script, _sed_past(script, index + 1, delimiter), delimiter)
    if index < 0:
        return index, f"a sed {command} command is never closed"
    while command == "s" and index < len(script) and script[index] not in ";\n}":
        if script[index] == "e":
            return index, "sed's s///e flag runs the pattern space, text this reader never sees"
        if script[index] == "w":
            end = _line_end(script, index)
            writes.append(script[index + 1 : end].strip())
            return end, ""
        index += 1
    return index, ""


def _sed_command(script: str, index: int, runs: list[str], writes: list[str]) -> tuple[int, str]:
    """Past the sed command whose letter is at *index*: (the next index, why it is unread or "")."""
    command = script[index]
    index += 1
    end = _line_end(script, index)
    if command in "{}=dDgGhHnNpPxzFlLqQ":
        return index, ""
    if command == "#":
        return end, ""
    if command in ":btTv":
        semicolon = script.find(";", index, end)
        return (end if semicolon < 0 else semicolon), ""
    if command in "aic":
        while index < len(script) and script[index] != "\n":
            index += 2 if script[index] == "\\" else 1
        return index, ""
    if command in "sy":
        return _sed_substitute(script, index, command, writes)
    if command not in "rRwWe":
        return index, f"sed command {command!r} is one this reader has no grammar for"
    argument = script[index:end].strip()
    if command == "e" and not argument:
        return end, "sed's e runs the pattern space, text this reader never sees"
    {"w": writes, "W": writes, "e": runs}.get(command, []).append(argument)
    return end, ""


def sed_actions(script: str) -> tuple[list[str], list[str], str]:
    """What one sed script runs (`e COMMAND`), the files it writes (w, W, s///w) and, if unread, why.

    `e` alone and the s///e flag run the pattern space, text no reader sees before sed builds it.
    """
    runs: list[str] = []
    writes: list[str] = []
    index = 0
    while index < len(script):
        if script[index] in " \t\n;":
            index += 1
            continue
        index = _sed_address(script, index)
        if index < 0:
            return runs, writes, "a sed address regex is never closed"
        if index >= len(script):
            break
        index, why = _sed_command(script, index, runs, writes)
        if why:
            return runs, writes, why
    return runs, writes, ""


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
            path = Path(os.path.expanduser(text))
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
