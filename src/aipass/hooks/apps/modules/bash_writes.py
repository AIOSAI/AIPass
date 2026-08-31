# =================== AIPass ====================
# Name: bash_writes.py
# Version: 1.1.0
# Description: Write targets a shell command can be seen to name (edit_gate's scripted lane)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-08-30
# Modified: 2026-08-30
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
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

# Shell operators that end one command and start the next.
_SEPARATORS = frozenset({"&&", "||", ";", "|", "&", "\n"})

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

# A run of characters containing a slash — how a path looks inside interpreter
# source, where quoting has already been stripped or mangled by the lexer.
_PATH_RUN = re.compile(r"[~\w.@+\-]*/[~\w./@+\-]*")

# The opening of a heredoc: << or <<-, an optionally quoted delimiter word.
_HEREDOC_OPEN = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")

# Trailing syntax that rides along when a path is lifted out of source code.
_TRAILING_JUNK = ",;:)]}'\"`"

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
    if "<<" not in command:
        return command
    lines = command.split("\n")
    out: list[str] = []
    pending: list[str] = []
    for line in lines:
        if pending:
            if line.strip() == pending[0]:
                pending.pop(0)
                out.append("")
                continue
            out.append("")
            continue
        out.append(line)
        pending.extend(match.group(2) for match in _HEREDOC_OPEN.finditer(line))
    return "\n".join(out)


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
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError as exc:
        logger.info("[HOOKS] bash_writes: lexer fell back to whitespace split (%s)", exc)
        return command.split()


def _segments(tokens: list[str]) -> list[list[str]]:
    """Group tokens into individual commands, split on shell separators."""
    out: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
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
    return "/" in token or "." in token or token.isidentifier()


def _resolve(token: str, cwd: Path) -> Path | None:
    """Resolve one operand against the segment's working directory."""
    token = token.strip().strip(_TRAILING_JUNK)
    if not token:
        return None
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
    verb = Path(segment[0]).name
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

    The raw segment text is scanned, not just the tokens: a heredoc body reaches
    the lexer as mangled words — an open-call arrives with its quotes stripped
    and its arguments glued to the path — and lifting the
    slash-bearing run out of the raw text is the only reading that survives it.
    """
    verb = Path(segment[0]).name
    if verb not in _INTERPRETERS:
        return []
    seen: set[str] = set()
    hits: list[tuple[Path, str]] = []
    for match in _PATH_RUN.findall(raw):
        token = match.strip(_TRAILING_JUNK)
        if not token or token in seen or "$" in token:
            continue
        seen.add(token)
        target = _resolve(token, cwd)
        if target is not None:
            hits.append((target, f"{verb} (interpreter — may write any path it holds)"))
    return hits


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
    tokens = _tokenize(_strip_heredoc_bodies(command))
    hits: list[tuple[Path, str]] = []
    current = base
    for segment in _segments(tokens):
        if not segment:
            continue
        verb = Path(segment[0]).name

        # `cd` inside a chain moves the ground the next segment stands on. Not
        # tracking it would let `cd ../Other && sed -i s/a/b/ f.json` resolve
        # f.json against the caller's own project and read as a local write.
        if verb == "cd" and len(segment) > 1:
            moved = _resolve(segment[1], current)
            if moved is not None:
                current = moved
            continue

        hits.extend(_redirect_targets(segment, current))
        hits.extend(_verb_targets(segment, current))
        hits.extend(_interpreter_targets(segment, command, current))

    return hits
