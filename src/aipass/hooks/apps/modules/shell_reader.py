# =================== AIPass ====================
# Name: shell_reader.py
# Version: 1.4.0
# Description: The one shell-word reader: every program a Bash command runs, as the shell runs it (rm_gate, git_gate)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-10-01
# Modified: 2026-10-22
# =============================================

"""What a Bash command RUNS, read the way bash reads it (DPLAN-0356 phase 3, R3 to R6).

The red team's R3 (2026-10-01): rm_gate and git_gate read the program name off a
home-rolled split of the raw text, while the shell first removes quotes, honours
escapes, decodes ``$'...'`` and expands braces and globs. ``r\\m x``, ``'r'm x``,
``$'\\x72\\x6d' x``, ``{rm,x}`` and ``/bin/r? x`` all ran rm and all read as some
other program. This module is the one reader both gates use; neither keeps a copy.

  - :func:`invocations` — every program, nested ones included, with what could not be read.
  - :func:`program_delete`, :func:`program_launch`, :func:`program_credential`,
    :func:`program_github_write` — what an interpreter's own program text shows.
  - :func:`mutated_paths` — what a command deletes, moves, overlays, links or writes (the protected lane).

It sits beside modules/bash_writes.py, which keeps the write-target reading that
edit_gate and testwrite_gate ask of a command; the two share ``verb_name`` and the
operand resolution, and this one unions ``write_targets`` into :func:`mutated_paths`.
Split out because one file holding both passed the 1,500-line module cap.
What neither can see is published in ``bash_writes.NOT_CAUGHT``.
"""

import fnmatch
import glob
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.modules.bash_writes import _SOURCE_DELETE_SHAPES, _resolve, verb_name, write_targets
from aipass.hooks.apps.modules.shell_programs import PLAIN_PROGRAMS, SHELL_PROGRAMS, WATCHED_VERBS, syntax_check_only
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console


def print_introspection() -> None:
    """Print module structure for drone routing."""
    CONSOLE.print("[bold cyan]shell_reader[/bold cyan] — every program a Bash command runs, as the shell runs it")
    CONSOLE.print(
        "[dim]Consumed by handlers/security/rm_gate.py and git_gate.py. Residual: bash_writes NOT_CAUGHT.[/dim]"
    )


# =============================================================================
# THE SHELL-WORD READER — what the shell will RUN (DPLAN-0356 phase 3, R3 to R6)
# =============================================================================
#
# The red team's R3: rm_gate and git_gate read the program name off a home-rolled
# split of the raw text, while the shell first removes quotes, honours escapes,
# decodes $'...' and expands braces and globs. `r\m x`, `'r'm x`, `$'\x72\x6d' x`,
# `{rm,x}` and `/bin/r? x` all ran rm and all read as some other program.
#
# This is the one reader both gates use. It lexes the command the way bash does,
# folds what can be folded (a literal assignment earlier in the same command, the
# process environment), and walks every program the command runs: past launchers
# (sudo, env, xargs, timeout ...), into `bash -c` / `eval` / `find -exec` / `trap` /
# aliases / command substitutions, and, since R4, into the script FILES a shell or
# an interpreter is handed. Whatever it cannot read comes back as an Invocation
# carrying `unread`, and rm_gate refuses that off the admin seat: a program the
# gate cannot see is not one it lets through.
#
# What it still cannot see is published in NOT_CAUGHT, like everything else here.

#: The largest script file read at decision time. A bigger one is unread, and refused off the admin seat.
SCRIPT_READ_LIMIT = 512 * 1024

# Nesting past this (bash -c inside eval inside a script ...) is unread, not followed forever.
_MAX_DEPTH = 8

# A brace expansion is cut off past this many words; the first ones are still read.
_MAX_BRACE = 64

_OP_LIST = (
    "&>>", ";;&", "<<<", "<<-",
    "&&", "||", ";;", ";&", "|&", "&>", ">>", ">|", ">&", "<&", "<>", "<<", "((", "))",
    ";", "&", "|", "(", ")", "<", ">",
)  # fmt: skip
_REDIRECT_OPERATORS = frozenset({"<", ">", ">>", ">|", "<>", "&>", "&>>", "<&", ">&"})
_HEREDOC_OPERATORS = frozenset({"<<", "<<-"})
_CASE_ENDS = frozenset({";;", ";&", ";;&"})

# Reserved words that stand where a program would and run nothing themselves.
_RESERVED = frozenset({"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "{", "}", "!", "time"})

_ANSI_SIMPLE = {
    "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v",
    "\\": "\\", "'": "'", '"': '"', "?": "?",
}  # fmt: skip

_NAME = re.compile(r"[A-Za-z_]\w*")

#: Shells whose program text is shell grammar, read back through this reader.
_SHELL_PROGRAMS = SHELL_PROGRAMS

# Interpreter names to one language, a version suffix included: python3.12 is python.
_LANGUAGE = re.compile(
    r"(?P<lang>python|pypy|perl|ruby|node|nodejs|php|lua|rscript|deno|bun|tsx|ts-node|osascript|pwsh|powershell"
    r"|awk|gawk|mawk|nawk)(?:\d[\d.]*)?$"
)
_LANGUAGE_ALIASES = {
    "pypy": "python",
    "nodejs": "node",
    "gawk": "awk",
    "mawk": "awk",
    "nawk": "awk",
    "powershell": "pwsh",
}

# Per language: the flags whose value IS the program, the flags that take some other value,
# the flags that name the script file and the flag that runs a module by name.
_INLINE_FLAGS = {
    "python": ("-c",), "node": ("-e", "--eval", "-p", "--print"), "perl": ("-e", "-E"), "ruby": ("-e",),
    "php": ("-r",), "lua": ("-e",), "rscript": ("-e",), "osascript": ("-e",), "pwsh": ("-command", "-c"),
    "bun": ("-e", "--eval"), "tsx": ("-e", "--eval"), "ts-node": ("-e", "--eval"), "deno": (), "awk": (),
}  # fmt: skip
_VALUED_FLAGS = {
    "python": ("-W", "-X"), "node": ("-r", "--require", "--import", "--loader", "--input-type", "-C"),
    "perl": ("-I", "-M", "-m"), "ruby": ("-r", "-I", "-C"), "php": ("-d", "-c", "-z"), "awk": ("-F", "-v"),
}  # fmt: skip
_SCRIPT_FLAGS = {"php": ("-f",), "awk": ("-f",), "pwsh": ("-file", "-f")}
_MODULE_FLAGS = {"python": ("-m",)}

# Launchers: the program they run comes after their own flags (the valued ones take the next
# word) and, for a few, a fixed number of operands of their own (timeout's duration).
_LAUNCHER_VALUED = {
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
_LAUNCHER_OPERANDS = {"timeout": 1, "chrt": 1, "taskset": 1, "flock": 1}

# A flag after which the launcher's text is a PROGRAM re-read as shell (su -c 'rm x').
_LAUNCHER_PROGRAM_FLAGS = {
    "su": ("-c", "--command"), "runuser": ("-c", "--command"), "script": ("-c", "--command"),
    "flock": ("-c", "--command"), "env": ("-S", "--split-string"),
}  # fmt: skip

# Task runners whose `run` (or `exec`) word runs the next program: uv run git push is git.
_RUNNERS = {"uv": "run", "poetry": "run", "pipenv": "run", "pdm": "run", "hatch": "run", "conda": "run", "pnpm": "exec"}
_RUNNER_VALUED = {"--with", "--python", "-p", "--directory", "--project", "--env-file", "--extra", "--group",
                  "--package", "--index", "--index-url", "-n", "--name", "--prefix", "-e", "--env"}  # fmt: skip

_BINARY_MAGIC = (b"\x7fELF", b"MZ", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe")


@dataclass(frozen=True)
class Invocation:
    """One program the shell will run, as the reader read it.

    Attributes:
        program: The command word through :func:`verb_name`, or "" when it could not be read.
        argv: The words as the shell runs them, the command word first.
        via: How the reader reached it ("" at top level; "bash -c ", "eval ", "script ./x.sh " ...).
        unread: Why the reader could not see what runs here; "" when it could.
        language: An interpreter's language ("python", "node" ...), "" for anything else.
        text: That interpreter's own program text: inline, heredoc, here-string or script file.
        cwd: The directory it runs in, "" when a cd the reader could not follow moved it.
    """

    program: str
    argv: tuple[str, ...] = ()
    via: str = ""
    unread: str = ""
    language: str = ""
    text: str = ""
    cwd: str = ""


@dataclass(eq=False)
class _Word:
    """One shell word: atoms ("c", char, quoted) | ("var", name, quoted) | ("dyn", as-written, quoted)."""

    atoms: list = field(default_factory=list)
    subs: list = field(default_factory=list)
    raw: str = ""


@dataclass(eq=False)
class _Simple:
    """One simple command: its words, redirections, heredoc bodies and here-strings."""

    words: list = field(default_factory=list)
    redirs: list = field(default_factory=list)
    heredocs: list = field(default_factory=list)
    herestrings: list = field(default_factory=list)
    stdin_file: _Word | None = None
    piped_in: bool = False
    scope: str = ""  # "(" / ")" for the markers that open and close a subshell


@dataclass
class _Ctx:
    cwd: Path | None
    vars: dict
    depth: int = 0
    via: str = ""

    def child(self, via: str) -> "_Ctx":
        """A nested program's context: its own variables, one level deeper, *via* appended."""
        return _Ctx(self.cwd, dict(self.vars), self.depth + 1, self.via + via)


@dataclass
class _Reading:
    invocations: list = field(default_factory=list)
    redirects: list = field(default_factory=list)


def _ansi_c(text: str, start: int) -> tuple[str, int]:
    """Decode a $'...' body from *start* (just past the quote); (decoded, index past the closing quote)."""
    out: list[str] = []
    i = start
    while i < len(text) and text[i] != "'":
        if text[i] != "\\" or i + 1 >= len(text):
            out.append(text[i])
            i += 1
            continue
        piece, i = _ansi_escape(text, i)
        out.append(piece)
    return "".join(out), i + 1


def _ansi_escape(text: str, i: int) -> tuple[str, int]:
    """One backslash escape of a $'...' string at *i*: (its character, the index after it)."""
    nxt = text[i + 1]
    if nxt in _ANSI_SIMPLE:
        return _ANSI_SIMPLE[nxt], i + 2
    octal = re.match(r"[0-7]{1,3}", text[i + 1 :])
    if octal:
        return chr(int(octal.group(), 8)), i + 1 + len(octal.group())
    if nxt == "c" and i + 2 < len(text):
        return chr(ord(text[i + 2]) & 0x1F), i + 3
    width = {"x": 2, "u": 4, "U": 8}.get(nxt)
    digits = re.match(rf"[0-9A-Fa-f]{{1,{width}}}", text[i + 2 :]) if width else None
    if digits and int(digits.group(), 16) <= 0x10FFFF:
        return chr(int(digits.group(), 16)), i + 2 + len(digits.group())
    return "\\" + nxt, i + 2


def _closing(text: str, start: int, opener: str, closer: str) -> int:
    """Index of the *closer* that balances an *opener* consumed before *start*; len(text) when none."""
    depth = 1
    quote = ""
    i = start
    while i < len(text):
        ch = text[i]
        i += 1
        if ch == "\\" and quote != "'":
            i += 1
            continue
        if quote or ch in "'\"":
            quote = "" if ch == quote else (quote or ch)
            continue
        depth += (ch == opener) - (ch == closer)
        if depth == 0:
            return i - 1
    return len(text)


class _Lexer:
    """Shell words and operators, the way bash splits them, heredoc bodies included."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.i = 0
        self.tokens: list[tuple] = []
        self.word: _Word | None = None
        self.start = 0
        self.pending: list[tuple[str, bool, bool]] = []
        self.want_delim: bool | None = None

    def run(self) -> list[tuple]:
        """The command's tokens, words and operators, in order."""
        while self.i < len(self.text):
            self._step(self.text[self.i])
        self._flush()
        return self.tokens

    def _step(self, ch: str) -> None:
        handler = self._HANDLERS.get(ch)
        if ch in "<>" and self.text[self.i + 1 : self.i + 2] == "(":
            self._process_substitution()
        elif ch == "#" and self.word is None:
            end = self.text.find("\n", self.i)
            self.i = len(self.text) if end < 0 else end
        elif handler is not None:
            handler(self)
        else:
            self._begin()
            self._cur.atoms.append(("c", ch, False))
            self.i += 1

    def _blank(self) -> None:
        self._flush()
        self.i += 1

    def _begin(self) -> None:
        if self.word is None:
            self.word = _Word()
            self.start = self.i

    @property
    def _cur(self) -> _Word:
        """The word being built, begun here when none is."""
        self._begin()
        assert self.word is not None
        return self.word

    def _flush(self) -> None:
        if self.word is None:
            return
        self.word.raw = self.text[self.start : self.i]
        if self.want_delim is not None:
            delim = "".join(str(atom[1]) for atom in self._cur.atoms)
            self.pending.append((delim, self.want_delim, any(atom[2] for atom in self._cur.atoms)))
            self.want_delim = None
        self.tokens.append(("word", self.word))
        self.word = None

    def _newline(self) -> None:
        self._flush()
        self.tokens.append(("op", "\n"))
        self.i += 1
        while self.pending:
            delim, strip_tabs, quoted = self.pending.pop(0)
            body = self._body(delim, strip_tabs)
            self.tokens.append(("heredoc", body, quoted))

    def _body(self, delim: str, strip_tabs: bool) -> str:
        lines: list[str] = []
        while self.i < len(self.text):
            end = self.text.find("\n", self.i)
            end = len(self.text) if end < 0 else end
            line = self.text[self.i : end]
            self.i = min(end + 1, len(self.text))
            line = line.lstrip("\t") if strip_tabs else line
            if line == delim:
                return "\n".join(lines)
            lines.append(line)
        return "\n".join(lines)

    def _escape(self) -> None:
        nxt = self.text[self.i + 1 : self.i + 2]
        if nxt == "\n":
            self.i += 2
            return
        self._begin()
        if nxt:
            self._cur.atoms.append(("c", nxt, True))
        self.i += 2

    def _single(self) -> None:
        self._begin()
        end = self.text.find("'", self.i + 1)
        end = len(self.text) if end < 0 else end
        self._cur.atoms.extend(("c", ch, True) for ch in self.text[self.i + 1 : end])
        self._cur.atoms.append(("c", "", True))
        self.i = end + 1

    def _double(self) -> None:
        self._begin()
        self.i += 1
        while self.i < len(self.text) and self.text[self.i] != '"':
            ch = self.text[self.i]
            if ch == "\\" and self.text[self.i + 1 : self.i + 2] in ("$", "`", '"', "\\", "\n"):
                if self.text[self.i + 1] != "\n":
                    self._cur.atoms.append(("c", self.text[self.i + 1], True))
                self.i += 2
            elif ch == "$":
                self._dollar(quoted=True)
            elif ch == "`":
                self._backtick(quoted=True)
            else:
                self._cur.atoms.append(("c", ch, True))
                self.i += 1
        self._cur.atoms.append(("c", "", True))
        self.i += 1

    def _dollar(self, quoted: bool) -> None:
        self._begin()
        rest = self.text[self.i + 1 : self.i + 3]
        if rest[:1] == "'" and not quoted:
            decoded, self.i = _ansi_c(self.text, self.i + 2)
            self._cur.atoms.extend(("c", ch, True) for ch in decoded)
            self._cur.atoms.append(("c", "", True))
        elif rest[:1] == '"' and not quoted:
            self.i += 1
            self._double()
        elif rest[:1] in ("(", "{"):
            self._dollar_group(rest, quoted)
        else:
            self._dollar_name(quoted)

    def _dollar_group(self, rest: str, quoted: bool) -> None:
        """$(...), $((...)) and ${...}: a substitution's program is kept, every one is an expansion."""
        opener, closer = (rest[0], ")" if rest[0] == "(" else "}")
        end = _closing(self.text, self.i + 2, opener, closer)
        inner = self.text[self.i + 2 : end]
        written = self.text[self.i : end + 1]
        self.i = end + 1
        if rest == "((" or opener == "{":
            simple = opener == "{" and _NAME.fullmatch(inner)
            self._cur.atoms.append(("var", inner, quoted) if simple else ("dyn", written, quoted))
            if not simple:
                self._cur.subs.extend(_substitutions(inner.strip("()")))
            return
        self._cur.subs.append(inner)
        self._cur.atoms.append(("dyn", written, quoted))

    def _dollar_name(self, quoted: bool) -> None:
        name = _NAME.match(self.text, self.i + 1)
        special = self.text[self.i + 1 : self.i + 2]
        if name:
            self._cur.atoms.append(("var", name.group(), quoted))
            self.i = name.end()
        elif special and special in "0123456789@*#?$!-":
            self._cur.atoms.append(("dyn", "$" + special, quoted))
            self.i += 2
        else:
            self._cur.atoms.append(("c", "$", quoted))
            self.i += 1

    def _backtick(self, quoted: bool) -> None:
        self._begin()
        j = self.i + 1
        body: list[str] = []
        while j < len(self.text) and self.text[j] != "`":
            if self.text[j] == "\\" and j + 1 < len(self.text):
                nxt = self.text[j + 1]
                body.append(nxt if nxt in "`\\$" else "\\" + nxt)
                j += 2
                continue
            body.append(self.text[j])
            j += 1
        self._cur.subs.append("".join(body))
        self._cur.atoms.append(("dyn", self.text[self.i : j + 1], quoted))
        self.i = j + 1

    def _process_substitution(self) -> None:
        self._begin()
        end = _closing(self.text, self.i + 2, "(", ")")
        self._cur.subs.append(self.text[self.i + 2 : end])
        self._cur.atoms.append(("dyn", self.text[self.i : end + 1], False))
        self.i = end + 1

    def _operator(self) -> None:
        prefix = ""
        word = self.word
        if self.text[self.i] in "<>" and word is not None and _all_digits(word):
            prefix = "".join(atom[1] for atom in word.atoms)
            self.word = None
        else:
            self._flush()
        op = next(o for o in _OP_LIST if self.text.startswith(o, self.i))
        self.i += len(op)
        self.tokens.append(("op", prefix + op))
        if op in _HEREDOC_OPERATORS:
            self.want_delim = op == "<<-"

    def _unquoted_dollar(self) -> None:
        self._dollar(quoted=False)

    def _unquoted_backtick(self) -> None:
        self._backtick(quoted=False)

    _HANDLERS = {
        **dict.fromkeys(" \t\r", _blank),
        **dict.fromkeys(";&|()<>", _operator),
        "\n": _newline, "\\": _escape, "'": _single, '"': _double, "$": _unquoted_dollar, "`": _unquoted_backtick,
    }  # fmt: skip


def _all_digits(word: _Word) -> bool:
    return bool(word.atoms) and all(a[0] == "c" and not a[2] and a[1].isdigit() for a in word.atoms)


def _substitutions(text: str) -> list[str]:
    """The command and process substitutions inside *text*, read as shell words (none of them run here)."""
    found: list[str] = []
    for token in _Lexer(text).run():
        if token[0] == "word":
            found.extend(token[1].subs)
    return found


def _heredoc_substitutions(body: str) -> list[str]:
    """What an unquoted heredoc body runs: its $(...) and backticks, expanded before the consumer reads it."""
    lexer = _Lexer(body)
    lexer._begin()
    while lexer.i < len(body):
        ch = body[lexer.i]
        if ch == "\\":
            lexer.i += 2
        elif ch == "$":
            lexer._dollar(quoted=True)
        elif ch == "`":
            lexer._backtick(quoted=True)
        else:
            lexer.i += 1
    return lexer._cur.subs


def _plain(word: _Word) -> str | None:
    """The word's text when every atom is an unquoted literal character, else None."""
    if any(atom[0] != "c" or atom[2] for atom in word.atoms):
        return None
    return "".join(atom[1] for atom in word.atoms)


def _brace_expand(word: _Word) -> list[_Word]:
    """Bash brace expansion of the unquoted {a,b} and {1..3} in *word*; the word alone when it has none."""
    atoms = word.atoms
    for open_at, atom in enumerate(atoms):
        if atom != ("c", "{", False):
            continue
        parts = _brace_parts(atoms, open_at)
        if parts is None:
            continue
        close_at, choices = parts
        out: list[_Word] = []
        for choice in choices:
            expanded = _Word(atoms[:open_at] + choice + atoms[close_at + 1 :], word.subs, word.raw)
            out.extend(_brace_expand(expanded))
            if len(out) >= _MAX_BRACE:
                return out[:_MAX_BRACE]
        return out
    return [word]


def _brace_parts(atoms: list, open_at: int) -> tuple[int, list[list]] | None:
    """(close index, the alternatives) of the brace group opening at *open_at*, None when it is no group."""
    depth = 0
    commas: list[int] = []
    for index in range(open_at, len(atoms)):
        atom = atoms[index]
        if atom[0] != "c" or atom[2]:
            continue
        depth += {"{": 1, "}": -1}.get(atom[1], 0)
        if atom[1] == "," and depth == 1:
            commas.append(index)
        if depth == 0:
            inner = atoms[open_at + 1 : index]
            if commas:
                bounds = [open_at, *commas, index]
                return index, [atoms[a + 1 : b] for a, b in zip(bounds, bounds[1:])]
            sequence = _brace_sequence(inner)
            return (index, sequence) if sequence else None
    return None


def _brace_sequence(inner: list) -> list[list] | None:
    """{1..3} / {a..c} as alternatives, None when *inner* is not a sequence."""
    if any(atom[0] != "c" or atom[2] for atom in inner):
        return None
    match = re.fullmatch(r"(-?\d+|[A-Za-z])\.\.(-?\d+|[A-Za-z])", "".join(atom[1] for atom in inner))
    if not match:
        return None
    first, last = match.groups()
    if first.lstrip("-").isdigit() and last.lstrip("-").isdigit():
        step = 1 if int(last) >= int(first) else -1
        values = [str(n) for n in range(int(first), int(last) + step, step)][:_MAX_BRACE]
    elif first.isalpha() and last.isalpha():
        step = 1 if ord(last) >= ord(first) else -1
        values = [chr(n) for n in range(ord(first), ord(last) + step, step)][:_MAX_BRACE]
    else:
        return None
    return [[("c", ch, False) for ch in value] for value in values]


class _Parser:
    """Simple commands out of the token stream; the words of headers, tests and patterns run nothing."""

    def __init__(self, tokens: list[tuple]) -> None:
        self.tokens = tokens
        self.k = 0
        self.cmds: list[_Simple] = []
        self.subs: list[str] = []
        self.awaiting: list[_Simple] = []
        self.cur = _Simple()
        self.mode = ""
        self.case_head = False
        self.case_depth = 0
        self.skip_name = False
        self.after_time = False

    def run(self) -> tuple[list[_Simple], list[str]]:
        """(the simple commands, what could not be parsed) across the token stream."""
        while self.k < len(self.tokens):
            token = self.tokens[self.k]
            self.k += 1
            if token[0] == "heredoc":
                self._heredoc(token[1], token[2])
            elif token[0] == "op":
                self._op(token[1])
            else:
                self._word(token[1])
        self._end("")
        return self.cmds, self.subs

    def _heredoc(self, body: str, quoted: bool) -> None:
        if self.awaiting:
            self.awaiting.pop(0).heredocs.append((body, quoted))
        if not quoted:
            self.subs.extend(_heredoc_substitutions(body))

    def _end(self, separator: str) -> None:
        if self.mode == "header" and not self.case_head:
            self.mode = ""
        cur = self.cur
        if cur.words or cur.redirs or cur.herestrings or any(c is cur for c in self.awaiting):
            self.cmds.append(cur)
        self.cur = _Simple(piped_in=separator in ("|", "|&"))

    def _next_is(self, kind: str, value: str) -> bool:
        if self.k >= len(self.tokens) or self.tokens[self.k][0] != kind:
            return False
        token = self.tokens[self.k][1]
        return token == value if kind == "op" else _plain(token) == value

    def _op(self, op: str) -> None:
        base = op.lstrip("0123456789")
        if base in _REDIRECT_OPERATORS or base in _HEREDOC_OPERATORS or base == "<<<":
            self._redirect(op, base)
            return
        grouping = {"((": self._arithmetic, "(": self._open, ")": self._close}.get(op)
        if grouping is not None:
            grouping()
            return
        if op == "))":
            self._close()
            self._close()
            return
        self._end(op)
        if op in _CASE_ENDS and self.case_depth:
            self.mode = "pattern"

    def _redirect(self, op: str, base: str) -> None:
        target = None
        if self.k < len(self.tokens) and self.tokens[self.k][0] == "word":
            target = self.tokens[self.k][1]
            self.k += 1
        if base in _HEREDOC_OPERATORS:
            self.awaiting.append(self.cur)
        elif target is None:
            return
        elif base == "<<<":
            self.cur.herestrings.append(target)
        else:
            self.cur.redirs.append((op, target))
            if op == "<":
                self.cur.stdin_file = target

    def _arithmetic(self) -> None:
        """(( expr )) runs nothing but its substitutions; with no closing )) it is two subshells."""
        ahead = [i for i in range(self.k, len(self.tokens)) if self.tokens[i] == ("op", "))")]
        if not ahead or self.cur.words:
            self._op("(")
            self._op("(")
            return
        for token in self.tokens[self.k : ahead[0]]:
            if token[0] == "word":
                self.subs.extend(token[1].subs)
        self.k = ahead[0] + 1

    def _open(self) -> None:
        if self.mode == "pattern":
            return
        if len(self.cur.words) == 1 and not self.cur.redirs and self._next_is("op", ")"):
            # name() { ...; } defines a function: the name runs nothing.
            self.subs.extend(self.cur.words[0].subs)
            self.cur.words = []
            self.k += 1
            return
        self._end("(")
        self.cmds.append(_Simple(scope="("))

    def _close(self) -> None:
        if self.mode == "pattern":
            self.mode = ""
            return
        self._end(")")
        self.cmds.append(_Simple(scope=")"))

    def _word(self, word: _Word) -> None:
        text = _plain(word)
        if self.mode:
            self._skipped(word, text)
            return
        if self.skip_name:
            self.skip_name = False
            self.subs.extend(word.subs)
            return
        if self.after_time:
            self.after_time = False
            if text == "-p":
                return
        if not self.cur.words and text is not None and self._reserved(text):
            return
        self.cur.words.extend(_brace_expand(word))

    def _skipped(self, word: _Word, text: str | None) -> None:
        """A word of a for/case header, a [[ test ]] or a case pattern: only its substitutions run."""
        self.subs.extend(word.subs)
        if self.mode == "test" and text == "]]":
            self.mode = ""
        elif self.mode == "header" and self.case_head and text == "in":
            self.mode = "pattern"
            self.case_head = False
        elif self.mode == "pattern" and text == "esac":
            self.mode = ""
            self.case_depth -= 1

    def _reserved(self, text: str) -> bool:
        """Step past a reserved word at a command's start; True when *text* was one."""
        if text in _RESERVED:
            self.after_time = text == "time"
            return True
        if text in ("for", "select", "case"):
            self.mode = "header"
            self.case_head = text == "case"
            self.case_depth += text == "case"
            return True
        if text == "esac":
            self.case_depth -= 1
            return True
        if text == "[[":
            self.mode = "test"
            return True
        if text in ("function", "coproc"):
            following = self.tokens[self.k + 1] if self.k + 1 < len(self.tokens) else None
            self.skip_name = text == "function" or (
                following is not None and following[0] == "word" and _plain(following[1]) == "{"
            )
            return True
        return False


def _assignment(word: _Word) -> tuple[str, list] | None:
    """(name, value atoms) when *word* is NAME=value or NAME+=value, else None."""
    for index, atom in enumerate(word.atoms):
        if atom[0] != "c" or atom[2]:
            return None
        if atom[1] == "=":
            name = "".join(a[1] for a in word.atoms[:index]).rstrip("+")
            return (name, word.atoms[index + 1 :]) if _NAME.fullmatch(name) else None
    return None


def _atom_text(atoms: list, ctx: _Ctx, strict: bool) -> str | None:
    """The text of *atoms*: a variable folds from this command's assignments, then the environment.

    Strict (a command word): an expansion that does not fold answers None. Loose (an
    argument): it stays as written, so a re-read program still sees the expansion.
    """
    out: list[str] = []
    for kind, value, _quoted in atoms:
        if kind == "c":
            out.append(value)
            continue
        folded = None
        if kind == "var":
            folded = ctx.vars[value] if value in ctx.vars else os.environ.get(value)
        if folded is None and strict:
            return None
        out.append(folded if folded is not None else (f"${value}" if kind == "var" else value))
    return "".join(out)


def _text(word: _Word, ctx: _Ctx) -> str:
    return _atom_text(word.atoms, ctx, strict=False) or ""


def _globby(word: _Word) -> bool:
    return any(atom[0] == "c" and not atom[2] and atom[1] in "*?[" for atom in word.atoms)


def _command_candidates(word: _Word, text: str, ctx: _Ctx) -> list[str]:
    """The program names an unquoted glob in the command word can become, against the cwd and PATH."""
    if not _globby(word):
        return [text]
    # A watched verb the glob's last part can spell counts whatever the gate's disk shows: Git Bash's
    # /bin is a mount Windows cannot list, so /bin/r? ran rm and read as r? (CI red, PR #774).
    found = {verb for verb in WATCHED_VERBS if fnmatch.fnmatchcase(verb, text.rsplit("/", 1)[-1])}
    if "/" in text:
        pattern = Path(text).expanduser()
        if not pattern.is_absolute() and ctx.cwd is not None:
            pattern = ctx.cwd / pattern
        found.update(glob.glob(str(pattern)))
        return sorted(found) or [text]
    dirs = [ctx.cwd] if ctx.cwd is not None else []
    dirs.extend(Path(entry) for entry in os.environ.get("PATH", "").split(os.pathsep) if entry)
    for directory in dirs:
        try:
            names = os.listdir(directory)
        except OSError as exc:  # an unlistable PATH entry offers no candidate; the rest still do
            logger.info("[HOOKS] bash_writes: cannot list %s for a glob command word: %s", directory, exc)
            continue
        found.update(name for name in names if fnmatch.fnmatchcase(name, text))
    return sorted(found) or [text]


def _language(name: str) -> str:
    """The interpreter language *name* runs ("python" for python3.12), or "" for any other program."""
    match = _LANGUAGE.match(name.lower())
    if not match:
        return ""
    lang = match.group("lang")
    return _LANGUAGE_ALIASES.get(lang, lang)


def _script_path(path_text: str, ctx: _Ctx) -> Path | None:
    """The script's absolute path; None when it is relative and the cwd is not known."""
    path = Path(path_text).expanduser()
    if path.is_absolute():
        return path
    return ctx.cwd / path if ctx.cwd is not None else None


def _not_yet_written(path: Path, path_text: str) -> bool:
    """True when no file is at *path* yet: allowed and logged, never refused (phase 4, P1).

    Existing but unreadable, not a regular file, or oversized is not this: those stay refused.
    """
    if os.path.lexists(path):
        return False
    logger.info("[HOOKS] shell_reader: script %s does not exist yet at decision time — allowed, not read", path_text)
    return True


def _script_text(path_text: str, ctx: _Ctx) -> tuple[str, str]:
    """(text, "") of a script file the command runs, or ("", why it could not be read).

    Read at decision time (R4). The file can change after the check: NOT_CAUGHT says so.
    A script that does not exist yet is ("", ""): nothing to read, so nothing is
    claimed about it (DPLAN-0356 phase 4, P1 — the write-a-helper-then-run-it idiom).
    """
    path = _script_path(path_text, ctx)
    if path is None:
        return "", f"script {path_text}: the directory it runs from is not known here"
    if _not_yet_written(path, path_text):
        return "", ""
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            return "", f"script {path_text} is not a regular file"
        if info.st_size > SCRIPT_READ_LIMIT:
            return "", f"script {path_text} is {info.st_size} bytes, over the {SCRIPT_READ_LIMIT}-byte read limit"
        data = path.read_bytes()
    except OSError as exc:
        return "", f"script {path_text} cannot be read ({exc.strerror or exc})"
    if b"\0" in data[:4096]:
        return "", f"{path_text} is binary, not a script this reader can read"
    return data.decode("utf-8", errors="replace"), ""


def _file_kind(path_text: str, ctx: _Ctx) -> tuple[str, str, str]:
    """What a path-spelled command word is: ("binary"|"script"|"unread", text, why).

    A binary is judged by its name alone. A text file is a script: its shebang names
    the interpreter, and no shebang means the shell runs it.
    """
    path = _script_path(path_text, ctx) or Path(path_text).expanduser()
    if _not_yet_written(path, path_text):
        return "script", "", ""
    try:
        with path.open("rb") as handle:
            head = handle.read(4096)
    except OSError as exc:  # not there, or not readable: either way nothing here can be read
        return "unread", "", f"{path_text} cannot be read ({exc.strerror or exc})"
    if head.startswith(_BINARY_MAGIC) or b"\0" in head:
        return "binary", "", ""
    text, why = _script_text(path_text, ctx)
    return ("unread", "", why) if why else ("script", text, "")


def _shebang(text: str) -> str:
    """The program a script's #! line names (env's argument when it is env), "" without one."""
    if not text.startswith("#!"):
        return ""
    words = text[2:].split("\n", 1)[0].split()
    if not words:
        return ""
    if verb_name(words[0]) == "env":
        rest = [w for w in words[1:] if not w.startswith("-") and "=" not in w]
        return verb_name(rest[0]) if rest else ""
    return verb_name(words[0])


class _Walker:
    """Every program a command runs, nested ones included, into one _Reading."""

    def __init__(self, out: _Reading) -> None:
        self.out = out

    def read(self, text: str, ctx: _Ctx) -> None:
        """Read *text* as program text in *ctx*, adding every program it runs to the reading."""
        if ctx.depth > _MAX_DEPTH:
            self._unread(ctx, f"programs nested more than {_MAX_DEPTH} deep")
            return
        cmds, stray = _Parser(_Lexer(text).run()).run()
        for sub in stray:
            self.read(sub, ctx.child("$(...) "))
        scopes: list[Path | None] = []
        for cmd in cmds:
            if cmd.scope == "(":
                scopes.append(ctx.cwd)
            elif cmd.scope == ")":
                ctx.cwd = scopes.pop() if scopes else ctx.cwd
            else:
                self._command(cmd, ctx)

    def _unread(self, ctx: _Ctx, why: str, argv: tuple[str, ...] = ()) -> None:
        self.out.invocations.append(Invocation("", argv, ctx.via, why, cwd=str(ctx.cwd or "")))

    def _reread(self, text: str, ctx: _Ctx, via: str, share_cwd: bool = False) -> None:
        child = ctx.child(via)
        self.read(text, child)
        if share_cwd:
            ctx.cwd = child.cwd

    def _command(self, cmd: _Simple, ctx: _Ctx) -> None:
        for word in (*cmd.words, *(target for _op, target in cmd.redirs), *cmd.herestrings):
            for sub in word.subs:
                self.read(sub, ctx.child("$(...) "))
        for op, target in cmd.redirs:
            self._redirect(op, target, ctx)
        words = cmd.words
        index = 0
        while index < len(words) and _assignment(words[index]):
            index += 1
        if index == len(words):
            for word in words:
                pair = _assignment(word)
                if pair is not None:
                    ctx.vars[pair[0]] = _atom_text(pair[1], ctx, strict=True)
            return
        self._program(words[index:], cmd, ctx)

    def _redirect(self, op: str, target: _Word, ctx: _Ctx) -> None:
        base = op.lstrip("0123456789")
        if ">" not in base and base != "<>":
            return
        text = _text(target, ctx)
        if base in (">&", "<&") and (text.isdigit() or text == "-"):
            return
        target_path = Path(text).expanduser()
        if ctx.cwd is None and not target_path.is_absolute():
            return
        path = _resolve(text, ctx.cwd if ctx.cwd is not None else target_path)
        if path is not None:
            self.out.redirects.append((path, op))

    def _program(self, words: list, cmd: _Simple, ctx: _Ctx) -> None:
        head = words[0]
        folded = _atom_text(head.atoms, ctx, strict=True)
        if folded is None:
            self._unread(ctx, f"the program word {head.raw} is an expansion this reader cannot fold", (head.raw,))
            return
        rest = words[1:]
        candidates = _command_candidates(head, folded, ctx)
        if "\\" in head.raw and "'" not in head.raw and '"' not in head.raw and head.raw not in candidates:
            # The separator reading, as _readings() keeps for targets: an unquoted C:\...\rm.exe is the
            # escape reading to bash and a Windows path to the eye. Both are read; neither slips past.
            candidates.append(head.raw)
        for candidate in candidates:
            name = verb_name(candidate)
            argv = (candidate, *(_text(word, ctx) for word in rest))
            self._dispatch(name, candidate, argv, rest, cmd, ctx)

    def _dispatch(self, name: str, candidate: str, argv: tuple, rest: list, cmd: _Simple, ctx: _Ctx) -> None:
        cwd = str(ctx.cwd or "")
        if name in _SHELL_PROGRAMS:
            self.out.invocations.append(Invocation(name, argv, ctx.via, language="shell", cwd=cwd))
            if not syntax_check_only(argv):
                self._shell(name, rest, cmd, ctx)
            return
        language = _language(name)
        if language:
            self._interpreter(name, language, argv, rest, cmd, ctx)
            return
        if "/" in candidate or "\\" in candidate:
            kind, text, why = _file_kind(candidate, ctx)
            if kind != "binary":
                self.out.invocations.append(Invocation(name, argv, ctx.via, why, cwd=cwd))
                if kind == "script":
                    self._script(candidate, text, argv, ctx)
                return
        self.out.invocations.append(Invocation(name, argv, ctx.via, cwd=cwd))
        self._follow(name, rest, cmd, ctx)

    def _script(self, path_text: str, text: str, argv: tuple, ctx: _Ctx) -> None:
        """A text file run as a program: its shebang's interpreter reads it, else the shell does."""
        runner = _shebang(text)
        language = _language(runner) if runner else ""
        if language:
            self.out.invocations.append(
                Invocation(runner, argv, f"{ctx.via}script {path_text} ", language=language, text=text,
                           cwd=str(ctx.cwd or ""))
            )  # fmt: skip
            return
        self._reread(text, ctx, f"script {path_text} ")

    def _follow(self, name: str, rest: list, cmd: _Simple, ctx: _Ctx) -> None:
        """The programs a launcher or a builtin runs in turn."""
        texts = [_text(word, ctx) for word in rest]
        builtin = self._BUILTINS.get(name)
        if builtin is not None:
            builtin(self, rest, texts, cmd, ctx)
        elif name in _RUNNERS and texts[:1] == [_RUNNERS[name]]:
            self._launch(name, rest[1:], cmd, ctx, _RUNNER_VALUED)
        elif name in _LAUNCHER_VALUED:
            self._launch(name, rest, cmd, ctx, _LAUNCHER_VALUED[name])
        elif name not in PLAIN_PROGRAMS and name not in WATCHED_VERBS:
            self._unknown_wrapper(name, texts, rest, cmd, ctx)

    def _unknown_wrapper(self, name: str, texts: list[str], rest: list, cmd: _Simple, ctx: _Ctx) -> None:
        """A command word nobody tabled may launch its operands: read from the first watched verb (phase 4, P3)."""
        for index, text in enumerate(texts):
            if verb_name(text) in WATCHED_VERBS:
                self._program(rest[index:], cmd, ctx.child(f"{name} "))
                return

    def _eval(self, rest: list, texts: list[str], cmd: _Simple, ctx: _Ctx) -> None:
        if texts:
            self._reread(" ".join(texts), ctx, "eval ", share_cwd=True)

    def _dot(self, rest: list, texts: list[str], cmd: _Simple, ctx: _Ctx) -> None:
        if texts:
            self._source(texts[0], ctx)

    def _alias(self, rest: list, texts: list[str], cmd: _Simple, ctx: _Ctx) -> None:
        for text in texts:
            if "=" in text:
                self._reread(text.split("=", 1)[1], ctx, "alias ")

    def _trap(self, rest: list, texts: list[str], cmd: _Simple, ctx: _Ctx) -> None:
        if len(texts) >= 2:
            self._reread(texts[0], ctx, "trap ")

    def _parallel(self, rest: list, texts: list[str], cmd: _Simple, ctx: _Ctx) -> None:
        program = texts[: texts.index(":::")] if ":::" in texts else texts
        self._reread(" ".join(program), ctx, "parallel ")

    def _change_dir(self, rest: list, texts: list[str], cmd: _Simple, ctx: _Ctx) -> None:
        self._cd(rest, ctx)

    def _cd(self, rest: list, ctx: _Ctx) -> None:
        if not rest:
            ctx.cwd = Path.home()
            return
        target = _atom_text(rest[0].atoms, ctx, strict=True)
        if target is None or target == "-":
            ctx.cwd = None
            return
        path = Path(target).expanduser()
        ctx.cwd = path if path.is_absolute() else (ctx.cwd / path if ctx.cwd is not None else None)

    def _source(self, path_text: str, ctx: _Ctx) -> None:
        text, why = _script_text(path_text, ctx)
        if why:
            self._unread(ctx, why, ("source", path_text))
            return
        self._reread(text, ctx, f"source {path_text} ", share_cwd=True)

    def _find(self, rest: list, texts: list[str], cmd: _Simple, ctx: _Ctx) -> None:
        index = 0
        while index < len(texts):
            if texts[index] not in ("-exec", "-execdir", "-ok", "-okdir"):
                index += 1
                continue
            end = index + 1
            while end < len(texts) and texts[end] not in (";", "+"):
                end += 1
            if end > index + 1:
                self._program(rest[index + 1 : end], cmd, ctx.child("find -exec "))
            index = end + 1

    def _launch(self, name: str, rest: list, cmd: _Simple, ctx: _Ctx, valued: set) -> None:
        """Step past a launcher's own flags and operands to the program it runs."""
        index = 0
        program_flags = _LAUNCHER_PROGRAM_FLAGS.get(name, ())
        while index < len(rest):
            word = rest[index]
            text = _text(word, ctx)
            if text == "--":
                index += 1
                break
            if name == "env" and _assignment(word):
                index += 1
                continue
            if not text.startswith("-") or len(text) < 2:
                break
            if name == "command" and text in ("-v", "-V"):
                return
            program = self._program_flag(text, rest, index, program_flags, ctx)
            if program is not None:
                self._reread(program, ctx, f"{name} {text} ")
                return
            if name == "sudo" and text in ("-s", "-i", "--shell", "--login"):
                self._reread(" ".join(_text(w, ctx) for w in rest[index + 1 :]), ctx, "sudo -s ")
                return
            index += 2 if text in valued else 1
        index += _LAUNCHER_OPERANDS.get(name, 0)
        if name == "watch":
            self._reread(" ".join(_text(w, ctx) for w in rest[index:]), ctx, "watch ")
        elif index < len(rest):
            self._program(rest[index:], cmd, ctx.child(f"{name} "))

    @staticmethod
    def _program_flag(text: str, rest: list, index: int, flags: tuple, ctx: _Ctx) -> str | None:
        """The program text a -c / -S style flag carries (next word, or glued on), None when *text* is no such flag."""
        for flag in flags:
            if text == flag:
                tail = [_text(w, ctx) for w in rest[index + 1 :]]
                return " ".join(tail) if flag in ("-S", "--split-string") else (tail[0] if tail else "")
            if flag.startswith("--") and text.startswith(flag + "="):
                return text[len(flag) + 1 :]
            if not flag.startswith("--") and text.startswith(flag) and len(text) > len(flag):
                return text[len(flag) :]
        return None

    def _shell(self, name: str, rest: list, cmd: _Simple, ctx: _Ctx) -> None:
        """A shell's program: -c text, a script operand, or its stdin (heredoc, here-string, file, pipe)."""
        texts = [_text(word, ctx) for word in rest]
        index = 0
        inline = False
        while index < len(texts):
            text = texts[index]
            if text == "--":
                index += 1
                break
            if text in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
                index += 2
                continue
            if len(text) > 1 and text[0] in "-+":
                inline = inline or (not text.startswith("--") and "c" in text[1:])
                index += 1
                continue
            break
        if inline:
            self._reread(texts[index] if index < len(texts) else "", ctx, f"{name} -c ")
        elif index < len(texts):
            text, why = _script_text(texts[index], ctx)
            if why:
                self._unread(ctx, why, (name, texts[index]))
            else:
                self._reread(text, ctx, f"{name} {texts[index]} ")
        else:
            for program in self._stdin_programs(name, cmd, ctx):
                self._reread(program, ctx, f"{name} <<< ")

    def _stdin_programs(self, name: str, cmd: _Simple, ctx: _Ctx) -> list[str]:
        """The program text a shell or interpreter reads on stdin; an unread pipe is recorded as unread."""
        programs = [body for body, _quoted in cmd.heredocs] + [_text(w, ctx) for w in cmd.herestrings]
        if cmd.stdin_file is not None:
            text, why = _script_text(_text(cmd.stdin_file, ctx), ctx)
            if why:
                self._unread(ctx, why, (name,))
            programs.append(text)
        if not programs and cmd.piped_in:
            self._unread(ctx, f"{name} reads its program from a pipe, which this reader cannot see", (name,))
        return programs

    def _interpreter(self, name: str, language: str, argv: tuple, rest: list, cmd: _Simple, ctx: _Ctx) -> None:
        """An interpreter's own program: inline, a script file (R4), or stdin. Recorded with its text."""
        texts = [_text(word, ctx) for word in rest]
        programs: list[str] = []
        script = module = None
        index = 0
        inline = _INLINE_FLAGS.get(language, ())
        while index < len(texts):
            text = texts[index]
            folded = text.lower() if language == "pwsh" else text
            if folded in inline:
                programs.append(texts[index + 1] if index + 1 < len(texts) else "")
                index += 2
                if language != "perl":
                    break
                continue
            glued = next((flag for flag in inline if len(flag) == 2 and text.startswith(flag) and len(text) > 2), "")
            if glued:
                programs.append(text[2:])
                index += 1
                if language != "perl":
                    break
                continue
            if folded in _MODULE_FLAGS.get(language, ()):
                module = texts[index + 1] if index + 1 < len(texts) else ""
                break
            if folded in _SCRIPT_FLAGS.get(language, ()):
                script = texts[index + 1] if index + 1 < len(texts) else ""
                break
            if text == "--" or not text.startswith("-") or text == "-":
                break
            index += 2 if text in _VALUED_FLAGS.get(language, ()) else 1
        if not programs and script is None and module is None and index < len(texts):
            script, programs = self._operand_program(language, texts, index, programs)
        why = ""
        if script is not None and script != "-":
            text, why = _script_text(script, ctx)
            programs.append(text)
        elif not programs and module is None:
            programs.extend(self._stdin_programs(name, cmd, ctx))
        via = ctx.via + (f"script {script} " if script not in (None, "-") else "")
        self.out.invocations.append(
            Invocation(name, argv, via, why, language, "\n".join(p for p in programs if p), str(ctx.cwd or ""))
        )

    @staticmethod
    def _operand_program(language: str, texts: list[str], index: int, programs: list[str]) -> tuple:
        """(script, programs) from the first operand: awk's program, deno/bun's run/eval, else a script path."""
        first = texts[index]
        if language == "awk":
            return None, [*programs, first]
        if language in ("deno", "bun") and first in ("run", "eval"):
            operands = [t for t in texts[index + 1 :] if not t.startswith("-")]
            if first == "eval":
                return None, [*programs, operands[0] if operands else ""]
            return (operands[0] if operands else None), programs
        return first, programs

    _BUILTINS = {
        "cd": _change_dir, "pushd": _change_dir, "eval": _eval, "source": _dot, ".": _dot, "alias": _alias,
        "trap": _trap, "find": _find, "parallel": _parallel,
    }  # fmt: skip


def invocations(command: str, cwd: str = "") -> list[Invocation]:
    """Every program *command* runs, as the shell will run it (DPLAN-0356 phase 3, R3 and R4).

    The one reader rm_gate and git_gate share. Quotes are removed, escapes and
    $'...' decoded, braces expanded and a glob in a command word resolved against
    the working directory and PATH. Launchers are stepped past; ``bash -c``, ``eval``,
    ``find -exec``, ``trap``, aliases and substitutions are read as programs; a script
    file a shell or interpreter is handed is read from disk.

    Args:
        command: The raw Bash command string from the tool input.
        cwd: The session working directory; relative script paths are read from it.

    Returns:
        One :class:`Invocation` per program, in the order the reader met them. An
        entry whose ``unread`` is set names something the reader could not see.
    """
    return _read(command, cwd).invocations


def _read(command: str, cwd: str) -> _Reading:
    out = _Reading()
    if command and command.strip():
        _Walker(out).read(command, _Ctx(Path(cwd) if cwd else None, {}))
    return out


def program_delete(inv: Invocation) -> str:
    """The delete shape *inv*'s own program text shows, as ``program: shape``; "" when none does."""
    if not inv.text or inv.language in ("", "shell"):
        return ""
    for shape in _SOURCE_DELETE_SHAPES:
        match = shape.search(inv.text)
        if match:
            return f"{inv.program}: {match.group(0).strip()}"
    return ""


# git and gh launched from an interpreter's program (R5): a shell-out call, then git or gh
# opening a quoted word or list item; perl/ruby/php backticks and qx; and the libraries that
# drive git or GitHub without the binary.
_SOURCE_LAUNCH_SHAPES = (
    re.compile(
        r"\b(system|popen|Popen|subprocess|spawn\w*|exec\w*|check_call|check_output|call|run|shell_exec|passthru"
        r"|proc_open|capture[23]?|getoutput|getstatusoutput)\b[\s\S]*?['\"`]\s*(?:[^'\"`\s]*[/\\])?(git|gh)"
        r"(?:\.exe)?(?=['\"`\s])",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:import\s+(?:git|github|pygit2|dulwich)\b|from\s+(?:git|github|pygit2|dulwich)(?:\.\w+)*\s+import\b"
        r"|require\s*\(\s*['\"](?:simple-git|isomorphic-git|octokit|@octokit/[\w-]+)['\"]"
        r"|from\s+['\"](?:simple-git|isomorphic-git|octokit|@octokit/[\w-]+)['\"])"
    ),
)
_BACKTICK_LAUNCH = re.compile(r"(?:`|\bqx\s*\W|%x\s*\W)\s*(?:[^\s`]*[/\\])?(git|gh)(?:\.exe)?\s", re.IGNORECASE)
_BACKTICK_LANGUAGES = frozenset({"perl", "ruby", "php"})


def program_launch(inv: Invocation) -> str:
    """The git/gh launch *inv*'s own program text shows (R5), as ``program: shape``; "" when none does."""
    if not inv.text or inv.language in ("", "shell"):
        return ""
    shapes = (
        (*_SOURCE_LAUNCH_SHAPES, _BACKTICK_LAUNCH) if inv.language in _BACKTICK_LANGUAGES else _SOURCE_LAUNCH_SHAPES
    )
    for shape in shapes:
        match = shape.search(inv.text)
        if match:
            return f"{inv.program}: {' '.join(match.group(0).split())[:80]}"
    return ""


# The gh credential, read from an interpreter (R6): the keyring libraries and gh's own files.
_SOURCE_CREDENTIAL_SHAPES = (
    re.compile(r"\bkeyring\b[\s\S]*?\bget_(?:password|credential)\b"),
    re.compile(r"\bsecretstorage\b|\bSecret\s*\.\s*password_lookup|\bgh:github\.com\b"),
    re.compile(r"gh[/\\]hosts\.yml|\.git-credentials\b"),
)
# The secrets store and the @api modules that read it, from an interpreter (R7).
SOURCE_SECRETS_SHAPES = (
    re.compile(r"\.secrets\b|\bSECRETS_BASE\b|\b(?:get_secret|set_secret|list_secrets|get_api_key)\("),
    re.compile(r"aipass\.api\.apps\.(?:modules|handlers\.auth)(?:\.|\s+import\s+)secrets\b"),
    re.compile(r"handlers\.auth(?:\.|\s+import\s+)(?:keys|env)\b"),
)
# A write to the GitHub API from an interpreter's program (R6): the API host, then a method or a body.
GITHUB_API_HOST = re.compile(r"\b(?:api|uploads)\.github\.com\b", re.IGNORECASE)
_SOURCE_HTTP_WRITE = re.compile(r"(?i)\b(?:post|put|patch|delete)\b|\b(?:data|json|body)\s*[=:]")


def program_credential(inv: Invocation, shapes: tuple = _SOURCE_CREDENTIAL_SHAPES) -> str:
    """The credential read *inv*'s own program text shows (R6, or R7 with its shapes); "" when none does."""
    if not inv.text or inv.language in ("", "shell"):
        return ""
    for shape in shapes:
        match = shape.search(inv.text)
        if match:
            return f"{inv.program}: {match.group(0)[:60]}"
    return ""


def program_github_write(inv: Invocation) -> str:
    """The GitHub API write *inv*'s own program text shows (R6): the API host and a method or body."""
    if not inv.text or inv.language in ("", "shell") or not GITHUB_API_HOST.search(inv.text):
        return ""
    match = _SOURCE_HTTP_WRITE.search(inv.text)
    return f"{inv.program}: {match.group(0)} to the GitHub API" if match else ""


# =============================================================================
# WHAT A COMMAND CHANGES ON DISK, by role — the protected lane (R1, R2)
# =============================================================================

#: Every operand is deleted.
_DELETE_PROGRAMS = frozenset({"rm", "rmdir", "unlink", "shred", "srm", "wipe", "trash", "trash-put", "rimraf"})
#: Operands after the first (mode / owner) are changed in place.
_ATTRIBUTE_PROGRAMS = frozenset({"chmod", "chown", "chgrp"})
_MOVE_VALUED = frozenset(
    {"-t", "--target-directory", "-S", "--suffix", "-m", "--mode", "-o", "--owner", "-g", "--group"}
)


def _operand_words(argv: tuple[str, ...], valued: frozenset = frozenset()) -> tuple[list[str], dict]:
    """(operands, flags) of an argv: flags with their values pulled out, everything after -- an operand."""
    operands: list[str] = []
    flags: dict[str, str] = {}
    index = 1
    while index < len(argv):
        word = argv[index]
        if word == "--":
            operands.extend(argv[index + 1 :])
            break
        if word.startswith("-") and len(word) > 1:
            name, _, value = word.partition("=")
            if name in valued and not value:
                value = argv[index + 1] if index + 1 < len(argv) else ""
                index += 1
            flags[name] = value
        else:
            operands.append(word)
        index += 1
    return operands, flags


def _short(flags: dict, letters: str, longs: tuple[str, ...] = ()) -> bool:
    """True when a short flag cluster carries any of *letters*, or a long flag in *longs* is set."""
    return any(
        (not flag.startswith("--") and any(letter in flag[1:] for letter in letters)) or flag in longs for flag in flags
    )


def _landing(dest: str, sources: list[str], base: Path, no_target: bool) -> list[Path]:
    """Where a mv/cp/ln lands: the destination itself, or each source's name inside it when it is a directory."""
    target = _resolve(dest, base)
    if target is None:
        return []
    if not no_target and (dest.endswith(("/", "\\")) or target.is_dir()):
        return [target / Path(source.replace("\\", "/")).name for source in sources] or [target]
    return [target]


def _mutations(inv: Invocation) -> list[tuple[Path, str, str]]:
    """(path, role, how) for one invocation: role is write, delete, move-away, move-over, overlay or link-source."""
    if not inv.cwd or not inv.program:
        return []
    base = Path(inv.cwd)
    program = inv.program
    operands, flags = _operand_words(inv.argv, _MOVE_VALUED)
    paths = [(path, word) for word in operands if (path := _resolve(word, base)) is not None]
    if program in _DELETE_PROGRAMS:
        return [(path, "delete", f"{program} (delete)") for path, _word in paths]
    if program == "find" and ("-delete" in inv.argv or any(w.startswith("-exec") for w in inv.argv)):
        starts = [w for w in inv.argv[1:] if w.startswith(("-", "(", "!", ")"))]
        first = inv.argv.index(starts[0]) if starts else len(inv.argv)
        return [(p, "delete", "find (delete)") for w in inv.argv[1:first] if (p := _resolve(w, base))]
    if program in _ATTRIBUTE_PROGRAMS:
        return [(path, "write", f"{program} (in place)") for path, _word in paths[1:]]
    if program in ("mv", "cp", "install", "ln", "link", "rsync") and operands:
        return _transfers(program, operands, flags, base)
    if program in ("truncate", "touch", "tee", "chattr", "setfacl"):
        return [(path, "write", f"{program} (in place)") for path, word in paths if not word.startswith("+")]
    return []


def _transfers(program: str, operands: list[str], flags: dict, base: Path) -> list[tuple[Path, str, str]]:
    """mv, cp, install, ln, link and rsync: what leaves, what is replaced, and what is linked."""
    target_dir = flags.get("-t") or flags.get("--target-directory")
    sources, dest = (operands, target_dir) if target_dir else (operands[:-1], operands[-1])
    if not sources and program not in ("rsync",):
        return []
    no_target = "-T" in flags or "--no-target-directory" in flags
    hits: list[tuple[Path, str, str]] = []
    symbolic = _short(flags, "s", ("--symbolic",)) and program == "ln"
    hard_link = (program in ("ln", "link") and not symbolic) or (program == "cp" and _short(flags, "l", ("--link",)))
    moves_away = program == "mv" or (program == "rsync" and "--remove-source-files" in flags)
    for source in sources:
        path = _resolve(source, base)
        if path is None:
            continue
        if moves_away:
            hits.append((path, "move-away", f"{program} (moves it away)"))
        if hard_link:
            hits.append((path, "link-source", f"{program} (a hard link to it)"))
    recursive = program == "rsync" or (program == "cp" and _short(flags, "rRa", ("--recursive", "--archive")))
    role = "overlay" if recursive else ("write" if program in ("cp", "install") else "move-over")
    for landing in _landing(dest, sources, base, no_target):
        hits.append((landing, role, f"{program} destination"))
    return hits


def mutated_paths(command: str, cwd: str) -> list[tuple[Path, str, str]]:
    """Every path *command* can be seen to write, delete, move, replace or hard-link, with its role.

    The protected lane's question (git_gate, R1/R2): not only "what does this write",
    which :func:`write_targets` answers, but what it deletes, moves away, moves over,
    overlays with a recursive copy, or names as the source of a hard link. Read
    through :func:`invocations`, so a ``bash -c`` or ``eval`` program counts too, and
    unioned with :func:`write_targets`.

    Args:
        command: The raw Bash command string from the tool input.
        cwd: The session working directory relative paths resolve against.

    Returns:
        (path, role, how) triples; role is one of write, delete, move-away,
        move-over, overlay, link-source.
    """
    reading = _read(command, cwd)
    hits = [(path, "write", f"redirection ({op})") for path, op in reading.redirects]
    for inv in reading.invocations:
        hits.extend(_mutations(inv))
    hits.extend((path, "write", how) for path, how in write_targets(command, cwd))
    return list(dict.fromkeys(hits))
