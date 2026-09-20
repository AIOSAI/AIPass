# =================== AIPass ====================
# Name: bash_writes.py
# Version: 1.7.0
# Description: Write targets a shell command can be seen to name (edit_gate's scripted lane)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-08-30
# Modified: 2026-09-19
# =============================================

"""Reads a Bash command and reports which paths it can be seen to WRITE.

Why this exists: `edit_gate` is a PreToolUse hook on Edit/Write/MultiEdit/
NotebookEdit, so every fence it draws is invisible to a write made through the
shell. @devpulse measured the gap live on 2026-08-30 — their Edit into a sibling
project was correctly blocked, and `sed -i` on the same file went straight
through. The tool lane was fenced; the scripted lane was open to every seat.

THE BAR, set in the dispatch and kept here: a perfect shell parser is not the
goal and is not achievable. Catching the obvious write-verbs aimed at a foreign
project root is. Everything this parser deliberately cannot see is listed in
:data:`NOT_CAUGHT` — a residual that is documented is a known gap; a residual
that is discovered is a defect.

Two reading modes, because shell commands are two different things:

- **Directed verbs** — redirection, `tee`, in-place `sed`, `cp`, `mv`, `dd of=`.
  The write target is known from the verb's own grammar, so only the target is
  reported and reading a foreign path stays legal (`cat /other/x > ./mine`
  names ./mine, not /other/x).
- **Interpreters** — the set in :data:`_INTERPRETERS`, whether invoked with an
  inline script or a heredoc. These run arbitrary code, so no grammar tells us
  the target. Every path they are handed is reported. This deliberately catches
  a read-only invocation that merely opens a foreign file: an interpreter
  holding a foreign path cannot be distinguished from one writing to it, and
  the caller is told exactly that.
"""

import re
import shlex
from pathlib import Path, PureWindowsPath

from aipass.cli.apps.modules import err_console
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

# Shell operators that end one command and start the next.
_SEPARATORS = frozenset({"&&", "||", ";", "|", "&", "\n"})

# The lexer's operator characters. The newline is one of them ON PURPOSE: shlex
# counts it as blank space by default, so until 2026-09-10 "\n" sat in
# _SEPARATORS and never arrived. Every command after the first line of a
# multi-line Bash call was glued onto line one as extra operands: a write on
# line two was invisible to both gates, and a cd on line two never moved the
# ground (found measuring devpulse's 213c64fd).
_PUNCTUATION = "();<>|&\n"

# A subshell's cd ends with the subshell; the parentheses scope it.
_SUBSHELL_OPEN, _SUBSHELL_CLOSE = "(", ")"

# The lexer glues a run of operator characters into ONE token: ");", "&&\n",
# "\n\n". These are the pieces that end a command, pulled out of such a run.
# Redirections (">>", ">&", "2>&1"'s ">&") contain none of them and stay whole.
_OPERATOR_SPLIT = re.compile(r"(\n|&&|\|\||;|\(|\))")

# Every operand is a write target.
_ALL_OPERANDS = frozenset({"tee", "touch", "mkdir", "truncate"})

# The LAST operand is the destination; the ones before it are sources.
_LAST_OPERAND = frozenset({"cp", "mv", "ln", "install", "rsync"})

# Writes in place, but only with the in-place flag. Without it sed is a filter
# and names nothing — treating every `sed` operand as a target would refuse
# reading a foreign file through a pipe, which is not what the fence is for.
_INPLACE_FLAGS = frozenset({"-i", "--in-place"})

# Runs arbitrary code. No grammar names the target, so every path counts.
_INTERPRETERS = frozenset(
    {"python", "python3", "node", "nodejs", "perl", "ruby", "php", "bash", "sh", "zsh", "awk", "gawk"}
)
#: The interpreters whose program text is shell grammar — what code_text() hands back.
_SHELLS = frozenset({"bash", "sh", "zsh"})

# The executable half of Windows' PATHEXT. `git.exe`, `RM.EXE` and `git.cmd` are
# the SAME invocation as the bare name on a Windows host, and a gate that reads
# only the bare spelling is one rename away from being bypassed silently — the
# command runs, the fence simply never saw it (measured 2026-09-19: git_gate,
# rm_gate and this parser all read `git.exe` and `RM` as some other program).
# Only executable extensions are stripped: stripping any suffix would read
# `some/path/git.py` as git, a file nobody runs and one the gates leave alone
# on purpose.
_EXEC_EXTENSIONS = frozenset({".exe", ".com", ".bat", ".cmd", ".ps1"})

# Program text that can CREATE or overwrite a file, asked in the grammar the
# text is actually written in. Split in two because the same characters mean
# different things in each: `>` is a redirection in a shell and a comparison in
# python, and handing one matcher both grammars is how a read-only awk filter
# came to be refused on a live turn (2026-09-16, learning 245).
#
# Read by a caller asking the NARROW question "is a file being created". The
# ownership fence does not read it and must not: a path an interpreter holds
# still cannot be told from one it writes, and that breadth is what fences a
# foreign project.
_SOURCE_WRITE_SHAPES = (
    # open(p, "w") / Path.open("a") — a mode string carrying a writing letter.
    re.compile(r"""open\s*\([^)]*['"][rbt+]*[wax][rbt+]*['"]"""),
    # The write half of pathlib, io and os, by method name.
    re.compile(r"\.\s*(write|write_text|write_bytes|writelines|truncate|touch|mkdir|rename|replace|unlink)\s*\("),
    # Module-level writers: shutil, os, json, pickle, tempfile, pandas.
    re.compile(
        r"\b(makedirs|mkstemp|mkdtemp|copyfile|copytree|copy2|copy|move|rename|replace|remove|dump|savefig|to_csv|to_json)\s*\("
    ),
    # Node, php, perl and ruby spellings of the same act.
    re.compile(
        r"\b(writeFile|writeFileSync|appendFile|appendFileSync|createWriteStream|mkdirSync|renameSync"
        r"|copyFileSync|file_put_contents|fwrite|fputs|fopen)\s*\("
    ),
    # Shelling out. The write verb is then inside a string this parser does not
    # read as code, so the invocation itself has to count as the evidence.
    re.compile(r"\b(system|popen|spawn|exec|execSync|check_call|check_output|subprocess)\b"),
)

# The flags that put an interpreter's whole program INSIDE the command, next
# to the heredoc that does the same. Their absence means the program is a FILE
# on disk: its text was never read, so there is no evidence either way and the
# broad reading stands. Answering "no write verb" about text nobody read would
# be inventing evidence — pinned by test_a_real_creation_is_still_refused.
#
# awk and gawk take their program as a bare operand rather than behind a flag,
# so they land on the unseen side and keep the broad reading. That is why there
# is no awk redirection pattern above: it would have been dead for awk and
# alive for python, where `>` is a comparison — `print(3 > 2, path)` was read
# as a write while this cure was being measured.
_INLINE_SOURCE_FLAGS = frozenset({"-c", "-e", "-E", "--eval", "--exec"})

#: The same question asked of a shell program — `bash -c "..."` or `sh <<EOF`.
_SHELL_WRITE_SHAPES = (
    re.compile(r">"),
    re.compile(r"(^|[\s;&|])(tee|touch|cp|mv|ln|install|rsync|dd|mkdir|truncate|sed)\b"),
)

# NOTE ON TOOLING THAT CARRIES ITS OWN FENCE — `drone`, `aipass`, `git`, `gh`.
# This module first held an explicit skip-list for them. A mutation run killed
# it: removing the skip changed no result, because none of those commands is a
# verb this parser reads a target from, so the list suppressed nothing. A rule
# that has stopped suppressing anything is indistinguishable from a load-bearing
# one (@seedgo's bypass-rot species, mailed 2026-08-29), so it is gone and the
# fact is written here instead. Their fences stay theirs: `drone rm` refuses
# outside its own project and git/gh are git_gate's lane. A redirection they
# carry (`drone x > /foreign/f`) IS still caught — the shell does that write,
# not the tool.

# Redirection tokens. `>&` is a descriptor dup (`2>&1`), never a filename.
_REDIRECT_OPS = frozenset({">", ">>", ">|"})

# A run of characters containing a separator — how a path looks inside
# interpreter source, where quoting has already been stripped or mangled by the
# lexer. BOTH separators count: a regex that only knew "/" returned nothing at
# all for a Windows-spelled path, so the interpreter mode was not merely
# degraded on Windows, it was blind (measured 2026-08-31).
_PATH_RUN = re.compile(r"[~\w.@+\-]*[/\\][~\w./\\@+\-]*")

# The opening of a heredoc: << or <<-, an optionally quoted delimiter word.
_HEREDOC_OPEN = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")

# Trailing syntax that rides along when a path is lifted out of source code.
_TRAILING_JUNK = ",;:)]}'\"`"

# Git Bash's own spelling of a drive: /c/Users/me is C:\Users\me. Its pwd prints
# it and every command it runs accepts it, so an agent on Windows copies it
# into the next command.
_GIT_BASH_DRIVE = re.compile(r"/([A-Za-z])(?=/|$)")

#: How an interpreter's held path is labelled. write_ownership reads it: a held path
#: cannot be told from a read, so the branch fence never convicts on one.
HELD_BY_INTERPRETER = "(interpreter — may write any path it holds)"

#: Appended to that label when the interpreter's own text names no verb that
#: creates a file. A caller asking "is a NEW file being created" reads this and
#: stands down; a caller asking "could this write here" ignores it, because an
#: interpreter can still write through a shape no matcher knows. Read from this
#: module rather than restated in the caller — a marker spelled twice is a
#: marker that drifts (auto_fix learned that one the hard way).
NO_WRITE_VERB = " — no write verb in its own text"

# What this parser does NOT see. Stated as data so the reply, the README and the
# tests all quote the same list instead of three drifting prose copies.
NOT_CAUGHT: tuple[str, ...] = (
    "paths built from shell or program variables ($DIR/x, os.environ-derived) — nothing to resolve",
    "paths reached through a symlink that points into another project",
    "find -exec / xargs, which name the write verb but not the operand",
    "background or detached writes (nohup, disown, at, cron, systemd-run)",
    "metadata-only changes: chmod, chown, touch -t on an existing file",
    "git, gh, drone and aipass — they name no write verb this parser reads; their own fences apply",
    "writes made by a process the command merely starts (a server, a test runner)",
    "paths an interpreter receives from ANOTHER command — through a pipe, a file or an argument "
    "list built elsewhere. Only the paths in its own command and its own heredoc are read as held.",
    "a path spelled for the OTHER operating system's filesystem — 'C:\\Proj\\x' read on Linux "
    "names no drive that exists here, so it resolves relative and reads as local. Separators are "
    "understood on every OS; ROOTS are only walkable on the OS that has them.",
    # Measured 2026-09-13 for DPLAN-0342 row 3, the shell lane into .trinity memory files.
    "a file name with no separator inside interpreter source — a bare 'local.json' after a cd. A "
    "bare word cannot be told from json.load, so it is not read as a path; './local.json' is",
    "a path joined in program text — Path('.trinity') / 'local.json' is two strings, neither a path",
    "write verbs this parser has no grammar for: sponge, ed / ex, an interactive editor",
    # Measured 2026-09-19 for DPLAN-0352 finding 2, the interpreter false-positive class.
    "a WRITE an interpreter makes through a shape _SOURCE_WRITE_SHAPES has no pattern for — the "
    "path is still reported, but without the write-verb evidence a narrow caller (testwrite_gate) "
    "stands down on it. The broad callers, edit_gate's fences, are unaffected",
    "which held path a write shape belongs to — the evidence is read per interpreter, not per "
    "path, so a program that writes one file and merely names another claims both",
    "what a SCRIPT FILE does — its text is on disk, never in the command, so an interpreter "
    "handed a path instead of inline source keeps the broad reading and no write-verb evidence "
    "is claimed about it",
)


def print_introspection() -> None:
    """Print module structure for drone routing.

    The residual is printed, not just stored: a gap you can read from a
    terminal is one an agent can plan around. A gap that lives only in a
    constant gets discovered instead.
    """
    CONSOLE.print("[bold cyan]bash_writes[/bold cyan] — write targets a shell command can be seen to name")
    CONSOLE.print("[dim]Consumed by handlers/security/edit_gate.py for the scripted cross-project lane.[/dim]")
    CONSOLE.print()
    CONSOLE.print("[yellow]NOT CAUGHT — the residual, stated rather than discovered:[/yellow]")
    for gap in NOT_CAUGHT:
        CONSOLE.print(f"  - {gap}")


def verb_name(token: str) -> str:
    """The program a command token names, spelled one way on every host.

    Three spellings of one invocation reach a gate: a path (``/usr/bin/git``),
    a Windows executable extension (``git.exe``, ``git.cmd``) and any casing of
    either (``RM``, ``Git``). Windows runs all of them, so a gate comparing the
    raw token is bypassed by a rename — see :data:`_EXEC_EXTENSIONS`.

    Reading every host the same way is deliberate. A lowercase read of ``TEE``
    on Linux names a program that is not installed, so the parser reports a
    target for a command that would fail: broader than the truth, which is the
    safe direction for a fence. The reverse — reading ``RM.EXE`` as some other
    program — is how a real deletion goes unseen.

    Args:
        token: A command-position token, path-spelled or bare.

    Returns:
        The lowercase basename with any executable extension removed.
    """
    name = Path(token.replace("\\", "/")).name.lower()
    stem, dot, ext = name.rpartition(".")
    return stem if dot and f".{ext}" in _EXEC_EXTENSIONS else name


def _program_writes(verb: str, segment: list[str], raw: str) -> bool:
    """True when an interpreter can be SEEN to create a file, or was never read.

    Two questions in order, and the order is the whole point:

     1. Is the program even in this command? Inline source and a heredoc are;
        a script path is not. A file's text lives on disk, so a parser that
        reported "no write verb" about it would be stating a fact it never
        checked — and that is exactly how a real creation would walk past.
     2. Only then, does the text show a write shape for ITS OWN grammar?

    Args:
        verb: The interpreter, already through :func:`verb_name`.
        segment: That invocation's tokens, where the inline flags show up.
        raw: That interpreter's own text — its tokens and its heredoc.

    Returns:
        True when a write shape matches, and True whenever the text was unseen.
    """
    inline = "<<" in segment or any(token in _INLINE_SOURCE_FLAGS for token in segment)
    if not inline:
        return True
    shapes = _SHELL_WRITE_SHAPES if verb in _SHELLS else _SOURCE_WRITE_SHAPES
    return any(shape.search(raw) for shape in shapes)


def _strip_heredoc_bodies(command: str) -> str:
    """Blank out heredoc bodies before the command is read as shell syntax.

    A heredoc body is DATA, not shell. The lexer cannot know that, so a mail
    body or a doc that merely QUOTES a shell command had its quoted text read as
    real syntax — found live within minutes of shipping, when this gate blocked
    the reply describing its own proof. That is the "gate that blocks its own
    audit" pattern, and a fence nobody can write about is one people route
    around rather than report.

    The lines are replaced with blanks rather than deleted so nothing shifts:
    the opening line keeps its own tokens (the verb, its flags, any redirection
    that really is shell), and only the body stops being syntax.

    This does NOT weaken the interpreter rule. ``_interpreter_targets`` scans the
    ORIGINAL command text, so a heredoc handed to python still surrenders every
    path it holds — that catch was the point of the interpreter mode and it is
    pinned by its own test.
    """
    return _split_heredocs(command)[0]


def _split_heredocs(command: str) -> tuple[str, list[str]]:
    """The command with heredoc bodies blanked, and the bodies, in opener order.

    The bodies are kept so an interpreter can be handed the heredoc IT opened
    and no one else's text (see :func:`write_targets_by_segment`).
    """
    if "<<" not in command:
        return command, []
    lines = command.split("\n")
    out: list[str] = []
    pending: list[str] = []
    bodies: list[str] = []
    current: list[str] = []
    for line in lines:
        if pending:
            out.append("")
            if line.strip() == pending[0]:
                pending.pop(0)
                bodies.append("\n".join(current))
                current = []
            else:
                current.append(line)
            continue
        out.append(line)
        pending.extend(match.group(2) for match in _HEREDOC_OPEN.finditer(line))
    # An unterminated body is not returned: its opener then has no partner, and
    # the pairing falls back to the whole-command read, which still holds it.
    return "\n".join(out), bodies


def _strip_comments(command: str) -> str:
    """Drop shell comments, keeping the newline that ends each one.

    shlex's own comment handling was wrong twice over for this reader: it
    treated ``#`` as a comment ANYWHERE in a word (``curl host/#x && touch f``
    lost everything after the ``#``), and it swallowed the newline with the
    comment, which would merge the next line back into this one. The shell's
    rule is narrower: ``#`` opens a comment only where a word starts, and never
    inside quotes.
    """
    if "#" not in command:
        return command
    out: list[str] = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if char == "\\" and quote != "'" and index + 1 < len(command):
            out.append(command[index : index + 2])
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or command[index - 1] in " \t\n;&|()"):
            end = command.find("\n", index)
            index = len(command) if end < 0 else end
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _tokenize(command: str) -> list[str]:
    """Split a command into tokens, keeping shell operators as their own tokens.

    ``punctuation_chars`` makes shlex emit ``&&``/``||``/``;``/``|``/``>`` as
    tokens instead of gluing them to words, and posix mode strips quotes so a
    quoted path arrives as a path. An unbalanced quote is a lexer error, not a
    reason to give up: fall back to whitespace splitting and say so, because
    silently returning no tokens would read exactly like a command with no
    write targets.
    """
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCTUATION)
        lexer.whitespace_split = True
        lexer.whitespace = " \t\r"
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError as exc:
        logger.info("[HOOKS] bash_writes: lexer fell back to whitespace split (%s)", exc)
        return [token for line in command.split("\n") for token in (*line.split(), "\n")]
    out: list[str] = []
    for token in tokens:
        if len(token) > 1 and all(char in _PUNCTUATION for char in token):
            out.extend(piece for piece in _OPERATOR_SPLIT.split(token) if piece)
        else:
            out.append(token)
    return out


def _readings(command: str) -> list[list[str]]:
    """Every token stream this command could honestly be. Usually one.

    THE BUG THIS EXISTS FOR (@devpulse, windows-test.yml, 2026-08-31): in POSIX
    mode a backslash is an ESCAPE, so shlex ate every separator of a Windows
    path — ``C:\\Users\\me\\Vera-Studio\\f.json`` arrived as the single token
    ``C:UsersmeVera-Studiof.json``. That is not a degraded reading, it is the
    dangerous one: a drive-absolute foreign path became one relative filename,
    resolved under the CALLER'S OWN project, and read as a local write. Every
    catch category the fleet closed on 08-30 returned exit 0 on Windows. The
    class had never been green there.

    A fence must not have to guess which dialect it is reading. Both readings
    are produced and their results are UNIONED, so neither spelling can be used
    to slip past the other:

    - escape reading — shlex's own, correct for POSIX ``cp a\\ b.txt dest``
    - separator reading — backslashes doubled so the lexer emits them literally,
      correct for a Windows path

    Where they agree (no backslash anywhere) there is one reading and no cost.
    Where they disagree the union is strictly safer: reading ``\\`` as a
    separator only ever adds path components, so a local write can never become
    foreign by it — while the reverse, the escape reading, is exactly how a
    foreign write became local on Windows.
    """
    # A backslash-newline is a line continuation: the shell joins the lines, so
    # the reader must too, before a newline starts meaning "next command".
    shell = _strip_comments(_strip_heredoc_bodies(command).replace("\\\n", ""))
    readings = [_tokenize(shell)]
    if "\\" in shell:
        protected = _tokenize(shell.replace("\\", "\\\\"))
        if protected != readings[0]:
            readings.append(protected)
    return readings


def _segments(tokens: list[str]) -> list[list[str]]:
    """Group tokens into individual commands, split on shell separators.

    Subshell parentheses split too and are kept as one-token segments, so the
    caller can scope a cd to the subshell it was made in.
    """
    out: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in (_SUBSHELL_OPEN, _SUBSHELL_CLOSE):
            if current:
                out.append(current)
            out.append([token])
            current = []
            continue
        if token in _SEPARATORS:
            if current:
                out.append(current)
            current = []
            continue
        current.append(token)
    if current:
        out.append(current)
    return out


def _looks_like_path(token: str) -> bool:
    """True for operands that could name a file on disk.

    A token carrying an unexpanded variable is excluded, not guessed at: half a
    path resolved against the wrong root would name a project nobody addressed.
    """
    if not token or token.startswith("-"):
        return False
    if "$" in token or "*" in token or "?" in token:
        return False
    return "/" in token or "\\" in token or "." in token or token.isidentifier()


def _resolve(token: str, cwd: Path) -> Path | None:
    """Resolve one operand against the segment's working directory."""
    token = token.strip().strip(_TRAILING_JUNK)
    if not token:
        return None
    # A Windows path cannot hold a Git Bash drive (FPLAN-0537, measured under a
    # Windows flavour): WindowsPath("/c/Users/me") has a root but no drive, so
    # it joined the seat's drive and named C:\c\Users\me. That directory holds
    # no registry, so edit_gate let a foreign write spelled that way through,
    # and testwrite_gate called an edit of an existing test a creation. Read
    # only on a Windows cwd, because on POSIX /c is an ordinary directory.
    # Paths lifted out of interpreter source get the same reading, though python
    # itself would not translate them. That reading is broader than the write,
    # the safe way for a fence to be wrong.
    if isinstance(cwd, PureWindowsPath) and (drive := _GIT_BASH_DRIVE.match(token)):
        token = f"{drive.group(1).upper()}:/{token[drive.end() :].lstrip('/')}"
    # Separators are normalised on EVERY OS, not just Windows. pathlib accepts
    # "/" natively on Windows (WindowsPath("C:/a/b") is absolute and correct),
    # so one spelling reaches Path from both dialects and the parser's reading
    # of a command stops depending on which machine happens to run it. What
    # does NOT become portable is the ROOT: a drive letter names nothing on
    # Linux, so it resolves relative and reads as local — published in
    # NOT_CAUGHT rather than left to be discovered.
    token = token.replace("\\", "/")
    try:
        candidate = Path(token).expanduser()
        return candidate if candidate.is_absolute() else (cwd / candidate)
    except (OSError, ValueError, RuntimeError) as exc:
        logger.info("[HOOKS] bash_writes: unresolvable operand %r: %s", token, exc)
        return None


def _redirect_targets(segment: list[str], cwd: Path) -> list[tuple[Path, str]]:
    """Collect `> file` / `>> file` destinations."""
    hits: list[tuple[Path, str]] = []
    for index, token in enumerate(segment):
        if token not in _REDIRECT_OPS or index + 1 >= len(segment):
            continue
        target = _resolve(segment[index + 1], cwd)
        if target is not None:
            hits.append((target, f"redirection ({token})"))
    return hits


def _operands(segment: list[str]) -> list[str]:
    """Non-flag, non-operator tokens of a command, excluding the command name."""
    out: list[str] = []
    for token in segment[1:]:
        if token in _REDIRECT_OPS or token.startswith(("-", ">", "<", "&")):
            continue
        out.append(token)
    return out


def _verb_targets(segment: list[str], cwd: Path) -> list[tuple[Path, str]]:
    """Collect write targets named by a known verb's own grammar."""
    verb = verb_name(segment[0])
    operands = [t for t in _operands(segment) if _looks_like_path(t)]
    hits: list[tuple[Path, str]] = []

    if verb == "dd":
        for token in segment[1:]:
            if token.startswith("of="):
                target = _resolve(token[3:], cwd)
                if target is not None:
                    hits.append((target, "dd of="))
        return hits

    if verb == "sed":
        if not any(flag in _INPLACE_FLAGS or flag.startswith("-i") for flag in segment[1:] if flag.startswith("-")):
            return hits
        # The first operand is the script when it was not given via -e/-f.
        targets = operands if any(f.startswith(("-e", "-f")) for f in segment[1:]) else operands[1:]
        return [(t, "sed -i") for t in (_resolve(o, cwd) for o in targets) if t is not None]

    if verb in _ALL_OPERANDS:
        return [(t, verb) for t in (_resolve(o, cwd) for o in operands) if t is not None]

    if verb in _LAST_OPERAND and len(operands) >= 2:
        target = _resolve(operands[-1], cwd)
        if target is not None:
            hits.append((target, f"{verb} destination"))
    return hits


def _interpreter_targets(segment: list[str], raw: str, cwd: Path) -> list[tuple[Path, str]]:
    """Collect every path an interpreter invocation is handed.

    *raw* is the interpreter's OWN text — its command and the heredoc it opened
    — scanned as text, not just tokens, so a path glued into source code by the
    lexer (an open-call with its quotes stripped) still comes out whole.

    Until 2026-09-10 the caller passed the WHOLE command here, although this
    docstring already said "the segment". So an interpreter claimed every path
    the command held and resolved it against its OWN directory. A python step
    standing before ``cd ../../..`` took the later pytest argument, resolved it
    from the wrong place, and named a doubled path that does not exist, which
    testwrite_gate refused as a new test (devpulse 213c64fd, @aipass hit it
    twice while curing PR #761).
    """
    verb = verb_name(segment[0])
    if verb not in _INTERPRETERS:
        return []
    # Asked once per interpreter, not once per path: the evidence is a property
    # of the program's text, and which held path a write shape belongs to is
    # published in NOT_CAUGHT rather than guessed at.
    writes = _program_writes(verb, segment, raw)
    why = f"{verb} {HELD_BY_INTERPRETER}" if writes else f"{verb} {HELD_BY_INTERPRETER}{NO_WRITE_VERB}"
    seen: set[str] = set()
    hits: list[tuple[Path, str]] = []
    for match in _PATH_RUN.findall(raw):
        token = match.strip(_TRAILING_JUNK)
        if not token or token in seen or "$" in token:
            continue
        # Separators alone are not a path. Widening the run to accept "\\" made
        # every escaped quote inside a python -c body (\\") match as one, which
        # would have put filesystem root in a refusal that named a real target
        # elsewhere. Harmless to the verdict — root holds no registry — but a
        # refusal listing paths the command never named is one nobody believes.
        if not any(char.isalnum() for char in token):
            continue
        seen.add(token)
        target = _resolve(token, cwd)
        if target is not None:
            hits.append((target, why))
    return hits


def write_targets_by_segment(command: str, cwd: str) -> list[tuple[list[str], list[tuple[Path, str]]]]:
    """Same reading as :func:`write_targets`, but grouped by the segment that earned it.

    A caller asking a NARROWER question than "can this write" needs to know
    which segment a target came from — ``pytest x && touch y`` is one command
    with two very different halves, and a verdict that cannot tell them apart
    must refuse both or neither. testwrite_gate is that caller: a test RUN
    creates nothing, so it drops interpreter-attributed targets from runner
    segments while leaving every other segment's targets alone.

    Split out so there is still exactly ONE shell reader in this branch.
    :func:`write_targets` flattens this and is unchanged in behaviour, dedupe
    included — the seam exists to avoid a second parser, not to add one.

    Args:
        command: The raw Bash command string from the tool input.
        cwd: The session working directory relative paths resolve against.

    Returns:
        (segment tokens, hits) pairs, in command order. Segments that name no
        target are included with an empty hit list, so a caller can see the
        shape of the whole command rather than only its writing half.
    """
    if not command or not command.strip():
        return []
    try:
        base = Path(cwd) if cwd else Path.cwd()
    except OSError as exc:
        logger.info("[HOOKS] bash_writes: no usable cwd (%s)", exc)
        return []

    # Two texts, deliberately: heredoc bodies are stripped for the SYNTAX read
    # (a quoted command in a mail body is not a command) and kept for the
    # interpreter read (a heredoc handed to python really can write anything).
    grouped: list[tuple[list[str], list[tuple[Path, str]]]] = []
    seen: set[tuple[Path, str]] = set()
    bodies = _split_heredocs(command)[1]
    for tokens in _readings(command):
        current = base
        subshells: list[Path] = []
        segments = _segments(tokens)
        owned = _heredocs_by_segment(segments, bodies)
        for index, segment in enumerate(segments):
            if not segment:
                continue
            if segment == [_SUBSHELL_OPEN]:
                subshells.append(current)
                continue
            if segment == [_SUBSHELL_CLOSE]:
                current = subshells.pop() if subshells else current
                continue
            verb = verb_name(segment[0])

            # `cd` inside a chain moves the ground the next segment stands on.
            # Not tracking it would let `cd ../Other && sed -i s/a/b/ f.json`
            # resolve f.json against the caller's own project and read as a
            # local write.
            if verb == "cd" and len(segment) > 1:
                moved = _resolve(segment[1], current)
                if moved is not None:
                    current = moved
                continue

            hits: list[tuple[Path, str]] = []
            for hit in (
                *_redirect_targets(segment, current),
                *_verb_targets(segment, current),
                *_interpreter_targets(segment, owned.get(index, command), current),
            ):
                # The two readings overlap heavily; a caller told the same
                # thing twice would see a refusal that names one write as two.
                if hit in seen:
                    continue
                seen.add(hit)
                hits.append(hit)
            grouped.append((segment, hits))

    return grouped


def _heredocs_by_segment(segments: list[list[str]], bodies: list[str]) -> dict[int, str]:
    """Each segment's own text: its tokens plus the heredoc bodies it opened.

    Openers and bodies are matched in order. If they do not pair up one to one
    (a ``<<`` the lexer and the heredoc reader disagree on), nothing is returned
    and every interpreter falls back to reading the whole command, which is the
    old, broader reading: a fence that cannot tell whose text is whose keeps
    all of it.
    """
    openers = [sum(1 for token in segment if token == "<<") for segment in segments]
    if sum(openers) != len(bodies):
        if bodies:
            logger.info(
                "[HOOKS] bash_writes: %d heredoc bodies, %d openers - whole-command read", len(bodies), sum(openers)
            )
        return {}
    owned: dict[int, str] = {}
    taken = 0
    for index, segment in enumerate(segments):
        own = bodies[taken : taken + openers[index]]
        taken += openers[index]
        owned[index] = "\n".join([" ".join(segment), *own])
    return owned


def write_targets(command: str, cwd: str) -> list[tuple[Path, str]]:
    """Return every (path, why) this command can be seen to write.

    Args:
        command: The raw Bash command string from the tool input.
        cwd: The session working directory relative paths resolve against.

    Returns:
        A list of (resolved path, human-readable reason) pairs. Empty when the
        command names no write target this parser can see — which is not the
        same as "writes nothing"; see :data:`NOT_CAUGHT`.
    """
    return [hit for _segment, hits in write_targets_by_segment(command, cwd) for hit in hits]


def code_text(command: str) -> str:
    """The parts of *command* that are shell CODE, with data blanked.

    A mail body is an ARGUMENT, not a command. Any gate that pattern-matches a
    whole Bash command string convicts prose: @ai_mail was refused twice on
    2026-09-15 for a reply whose body merely QUOTED a write-shaped version
    control line, and the standing workaround was a line in every dispatch brief
    telling recipients not to quote one. The distinction lives here, in the
    reader that already knows where a heredoc starts and which verbs run code,
    so a caller asking "is there a real invocation in this command" gets one
    answer and this module keeps the only shell grammar in the branch.

    Two rules, opposite directions, one principle — text is data unless a
    shell owns it:

    * A heredoc body is blanked, because its consumer reads it as input.
    * A SHELL's own text is appended back, tokenized, because ``bash <<'EOF'``
      and ``bash -c "..."`` really are shell programs. Tokenized matters: the
      caller blanks quoted spans next, and an inline script that arrives
      already unquoted survives that blanking, which is what closes the hole
      where ``bash -c "<write verb>"`` read as an empty string.

    Shells only (:data:`_SHELLS`), not every interpreter. The caller reads shell
    grammar; an awk or python program is not shell, and the first version that
    appended them refused a read-only ``awk '/^diff --git a/…/'`` on a real turn
    (2026-09-16). Their quoted programs were blanked before this function
    existed, so leaving them out restores that reading and opens nothing new.

    A command whose heredoc openers and bodies do not pair up falls back to the
    whole command per segment, the old broader reading: a reader that cannot
    tell whose text is whose keeps all of it.

    Args:
        command: The raw Bash command string from the tool input.

    Returns:
        The command with heredoc bodies blanked, followed by the program text of
        each shell invocation. Never raises on unparseable input: shlex failures
        surface as an empty reading, and the shell half is still returned.
    """
    shell = _strip_heredoc_bodies(command)
    bodies = _split_heredocs(command)[1]
    programs: list[str] = []
    for tokens in _readings(command):
        segments = _segments(tokens)
        owned = _heredocs_by_segment(segments, bodies)
        for index, segment in enumerate(segments):
            if segment and verb_name(segment[0]) in _SHELLS:
                programs.append(owned.get(index, " ".join(segment)))
    return "\n".join([shell, *dict.fromkeys(programs)])
