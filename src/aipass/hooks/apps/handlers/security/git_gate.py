# =================== AIPass ====================
# Name: git_gate.py
# Version: 1.3.0
# Description: Blocks raw git/gh commands and protected file edits (PreToolUse)
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-05-21
# Modified: 2026-09-19
# =============================================

"""Blocks raw git/gh commands and edits to settings/hooks files."""

import importlib
import json
import os
import re
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger


# CANDIDATE finders, not verdicts. The optional dotted tail matches any
# extension so that ONE list of executable extensions exists in this branch —
# bash_writes.verb_name owns it — and _invocations() is what turns a candidate
# into an invocation. Case-insensitive because Windows is: `GIT`, `Git.EXE` and
# `git` are one program there, and until 2026-09-19 this gate read the last of
# the three and let the other two past (todo 51, the owner's go on 09-19).
RAW_GIT_RE = re.compile(r"(?<![@\w/.])(git(?:\.\w+)?)\s", re.IGNORECASE)
RAW_GH_RE = re.compile(r"(?<![@\w/.])(gh(?:\.\w+)?)\s", re.IGNORECASE)

# The lookbehind above excludes a leading `/` and `.` on purpose — it is what
# keeps `drone @git`, `.git/hooks` and `some/path/git.py` quiet. It is also the
# hole: `/usr/bin/git commit` never matched, and neither did `./git` or
# `~/bin/git`, so the one mechanical layer holding git writes behind drone was a
# full path away from being bypassed (reported 2026-09-11 by an external reader
# of a public drone post, via @devpulse; static finding, nothing run).
#
# A path is only read as an INVOCATION when it stands at a command position.
# `ls /usr/bin/git` and `cat ~/.config/git` name a file and are nobody's write,
# which is why a basename alone can never be the rule.
_EXEC_WRAPPERS = frozenset(
    {"env", "command", "sudo", "nohup", "time", "exec", "builtin", "xargs", "stdbuf", "nice", "setsid"}
)
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_]\w*=")

GH_ALLOWED_SUBCOMMANDS = ("api",)

READ_ALLOWED_GIT_SUBCOMMANDS = frozenset(
    {
        "ls-files",
        "ls-tree",
        "show",
        "cat-file",
        # Reads the ignore rules and answers; every option (-q -v --stdin -z -n
        # --no-index) is output-shaping. Refusing it while GIT_REDIRECT promised
        # read-only verbs run raw taught agents the message was unreliable.
        "check-ignore",
        "rev-parse",
        "rev-list",
        "log",
        "status",
        "diff",
        "blame",
        "describe",
        "for-each-ref",
        "show-ref",
        "symbolic-ref",
        "shortlog",
        "grep",
        "archive",
        "count-objects",
        "var",
        "help",
        "version",
    }
)

_GIT_OPTS_WITH_ARG = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--exec-path", "--namespace"})

# Matched against the path with separators normalised to "/" (_check_edit), and
# case-insensitively: Windows and default macOS filesystems open .Claude\Settings.json
# as the same file. Until 1.2.0 a Windows backslash path never matched and the gate
# ALLOWED the edit (measured on the Windows CI runner, 2026-09-16).
BLOCKED_EDIT_PATTERNS = [
    re.compile(r"/\.claude/settings(\.local)?\.json$", re.IGNORECASE),
    re.compile(r"/\.claude/hooks/", re.IGNORECASE),
    re.compile(r"/\.git/hooks/", re.IGNORECASE),
]

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

TRUSTED_HOOK_EDITORS = ("devpulse", "seedgo")

GIT_REDIRECT = (
    "AIPass enforces git via drone to prevent state conflicts between agents.\n"
    "Read-only verbs (status, log, diff, show, blame, grep, etc.) are allowed raw.\n"
    "\n"
    "For write operations, use drone @git:\n"
    "  drone @git commit <msg> [--all | files]   # commit changes\n"
    "  drone @git smart-sync                     # fetch + rebase\n"
    "  drone @git sync                           # checkout main + pull\n"
    "  drone @git pr <desc>                      # push + create PR\n"
    "  drone @git checkout <main|dev>            # switch branches\n"
    "\n"
    "Run `drone @git --help` for the full command list.\n"
    "To disable this gate for your project: set git_gate.enabled to false\n"
    "in your .aipass/hooks.json (this won't break other AIPass hooks)."
)

GH_REDIRECT = (
    "AIPass enforces gh via drone to prevent state conflicts between agents.\n"
    "Only `gh api` is allowed raw.\n"
    "\n"
    "For GitHub operations, use drone @git:\n"
    "  drone @git issue list     # list issues\n"
    "  drone @git run list       # CI runs\n"
    "  drone @git workflow run   # trigger workflows\n"
    "  drone @git pr <desc>      # push + create PR\n"
    "\n"
    "Run `drone @git --help` for the full command list.\n"
    "To disable this gate for your project: set git_gate.enabled to false\n"
    "in your .aipass/hooks.json (this won't break other AIPass hooks)."
)

EDIT_REDIRECT = (
    "{path} is protected — settings.json, .claude/hooks/, and .git/hooks/ "
    "govern the enforcement layer itself.\n"
    "If a real change is needed, ask devpulse to make it directly.\n"
    "To disable this protection: set git_gate.enabled to false in .aipass/hooks.json."
)

_BLOCK_ALLOW = {"stdout": "", "exit_code": 0}


def _cwd_branch(cwd: str) -> str:
    parts = Path(cwd).parts
    for i, part in enumerate(parts):
        if part == "aipass" and i > 0 and parts[i - 1] == "src" and i + 1 < len(parts):
            return parts[i + 1]
    return ""


def _verb(token: str) -> str:
    """The program *token* names, read through the branch's one shell reader.

    Three spellings reach this gate as one program on Windows — a path, an
    executable extension and any casing. bash_writes.verb_name is where that
    reading lives, so this gate does not grow a second copy of a list that must
    not drift.

    Falls back to the raw basename with a WARNING rather than going quiet: a
    gate that cannot reach the reader keeps its old, narrower reading, and the
    log says which spelling it is now one short of.

    Args:
        token: A command-position token.

    Returns:
        The normalised program name, or the raw basename when the reader is away.
    """
    try:
        bw = importlib.import_module("aipass.hooks.apps.modules.bash_writes")
        return bw.verb_name(token)
    except Exception as exc:  # noqa: BLE001 - any reader failure falls back to the raw name
        logger.warning("[HOOKS] git_gate: bash_writes unavailable, reading %r raw: %s", token, exc)
        return Path(token).name


def _invocations(pattern: re.Pattern, text: str, name: str) -> list[re.Match]:
    """The matches of *pattern* in *text* that really invoke *name*.

    The pattern finds candidates; this drops the ones whose dotted tail is not
    an executable extension. `git.exe` is git on any host that runs it;
    `git.py ` is a python file nobody invokes as git, and reading it as one is
    the noise that made an earlier version of this rule unusable.

    Args:
        pattern: RAW_GIT_RE or RAW_GH_RE, whose group 1 is the spelled name.
        text: The clause or scan text to search.
        name: The program being asked about, lowercase.

    Returns:
        The surviving matches, in order.
    """
    return [m for m in pattern.finditer(text) if _verb(m.group(1)) == name]


def _is_allowed_gh(cmd: str) -> bool:
    for match in _invocations(RAW_GH_RE, cmd, "gh"):
        tail = cmd[match.end() :].split()
        return bool(tail) and tail[0].lower() in GH_ALLOWED_SUBCOMMANDS
    return False


def _command_words(clause: str) -> list[str]:
    """The clause's tokens from its command position on, prefixes stepped past.

    `VAR=1 env -i /usr/bin/git commit` invokes git: a leading assignment and a
    wrapper that runs its own argument are not the executable. Option tokens are
    skipped only once a wrapper has been seen, so a clause that merely STARTS
    with a flag is left alone.
    """
    words = clause.split()
    index = 0
    saw_wrapper = False
    while index < len(words):
        word = words[index]
        if _ASSIGNMENT_RE.match(word):
            index += 1
            continue
        if _verb(word) in _EXEC_WRAPPERS or (saw_wrapper and word.startswith("-")):
            saw_wrapper = True
            index += 1
            continue
        break
    return words[index:]


def _path_exec_tail(clause: str, name: str) -> list[str] | None:
    """argv after `name` spelled as a PATH at this clause's command position.

    Returns None when the clause runs something else — including when the path
    merely appears as an argument, which is the whole point of asking about
    command position rather than about the text.
    """
    words = _command_words(clause)
    if not words:
        return None
    exe = words[0]
    if "/" not in exe and "\\" not in exe:
        return None
    if _verb(exe.rstrip("/").rstrip("\\")) != name:
        return None
    return words[1:]


def _split_clauses(cmd: str) -> list[str]:
    """Split on compound operators and subshell boundaries."""
    parts = re.split(r"&&|\|\||[;|]", cmd)
    clauses: list[str] = []
    for part in parts:
        clauses.extend(re.split(r"[$()`]", part))
    return clauses


def _extract_git_verb(tokens: list[str]) -> str | None:
    """Extract the git subcommand verb, skipping global options."""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if not tok.startswith("-"):
            # Lowercased for the membership test that follows it: the verb is
            # read on every host the same way the program name is.
            return tok.lower()
        if tok in _GIT_OPTS_WITH_ARG:
            i += 2
            continue
        i += 1
    return None


def _git_arg_tails(clause: str) -> list[list[str]]:
    """argv tails of every git invocation in one clause, both spellings.

    A bare `git` can appear anywhere in a clause (`env git commit`), a
    path-spelled one only at the command position.
    """
    tails = [clause[m.end() :].split() for m in _invocations(RAW_GIT_RE, clause, "git")]
    path_tail = _path_exec_tail(clause, "git")
    if path_tail is not None:
        tails.append(path_tail)
    return tails


def _path_gh_calls(scan: str) -> list[list[str]]:
    """argv tails of every gh spelled as a path at a command position.

    Same hole as git, same lookbehind, same file: `/usr/bin/gh pr create` was
    never read as gh at all.
    """
    tails = [_path_exec_tail(clause, "gh") for clause in _split_clauses(scan)]
    return [tail for tail in tails if tail is not None]


def _all_git_reads(scan: str) -> bool:
    """Return True only if every git invocation in scan is a read-only verb."""
    found_any = False
    for clause in _split_clauses(scan):
        for after in _git_arg_tails(clause):
            found_any = True
            verb = _extract_git_verb(after)
            if verb is None or verb not in READ_ALLOWED_GIT_SUBCOMMANDS:
                return False
    return found_any


def _block(reason: str) -> dict:
    return {"stdout": json.dumps({"decision": "block", "reason": reason}), "exit_code": 2, "sound": "git gate"}


def _scan_text(cmd: str) -> str:
    """The command text this gate is entitled to convict on.

    Quoted spans were already blanked here — an argument is not a command. A
    heredoc body was NOT, because it carries no quotes, so a mail body that
    merely QUOTED a write-shaped line was refused as if it ran one. @ai_mail hit
    that twice on 2026-09-15 and shipped its replies through a file instead, and
    every dispatch brief since has carried a line telling recipients not to
    quote such a line — a workaround issued over and over in place of a cure.

    The distinction between code and data lives in ``bash_writes``, the branch's
    one shell reader: it blanks a heredoc body whose consumer merely reads it,
    and hands back the program text of a real interpreter, tokenized. Tokenized
    is what closes the opposite hole in the same move: ``bash -c "<write>"`` had
    its whole script blanked as a quoted argument and read as no invocation at
    all.

    Fails to the OLD, BROADER reading. If the reader raises, this gate scans the
    raw command as it always did: a gate that cannot parse a command must not
    become permissive on it.
    """
    try:
        bw = importlib.import_module("aipass.hooks.apps.modules.bash_writes")
        code = bw.code_text(cmd)
    except Exception as exc:  # noqa: BLE001 - any reader failure falls back to the raw text
        logger.warning("[HOOKS] git_gate: bash_writes unavailable, scanning raw command: %s", exc)
        code = cmd
    scan = re.sub(r'"(?:[^"\\]|\\.)*"', '""', code)
    return re.sub(r"'(?:[^'\\]|\\.)*'", "''", scan)


def _check_bash(tool_input: dict) -> dict:
    cmd = tool_input.get("command", "")
    if not cmd:
        return _BLOCK_ALLOW
    scan = _scan_text(cmd)
    path_git = any(_path_exec_tail(clause, "git") is not None for clause in _split_clauses(scan))
    if (_invocations(RAW_GIT_RE, scan, "git") or path_git) and not _all_git_reads(scan):
        return _block(GIT_REDIRECT)
    if _invocations(RAW_GH_RE, scan, "gh") and not _is_allowed_gh(cmd):
        return _block(GH_REDIRECT)
    path_gh = _path_gh_calls(scan)
    if path_gh and not all(tail and tail[0].lower() in GH_ALLOWED_SUBCOMMANDS for tail in path_gh):
        return _block(GH_REDIRECT)
    return _BLOCK_ALLOW


def _check_edit(tool_input: dict, cwd: str) -> dict:
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not file_path:
        return _BLOCK_ALLOW
    spelled = file_path.replace("\\", "/")
    for pat in BLOCKED_EDIT_PATTERNS:
        if pat.search(spelled):
            if _cwd_branch(cwd) in TRUSTED_HOOK_EDITORS:
                return _BLOCK_ALLOW
            return _block(EDIT_REDIRECT.format(path=file_path))
    return _BLOCK_ALLOW


def handle(hook_data: dict) -> dict:
    """Block raw git/gh commands and protected file edits.

    Args:
        hook_data: Parsed hook event dict from engine.

    Returns:
        Result dict with stdout (block JSON or empty) and exit_code.
    """
    try:
        tool_name = hook_data.get("tool_name", "")
        tool_input = hook_data.get("tool_input", {})
        cwd = hook_data.get("cwd", "") or os.getcwd()
        if tool_name == "Bash":
            return _check_bash(tool_input)
        if tool_name in EDIT_TOOLS:
            return _check_edit(tool_input, cwd)
        return _BLOCK_ALLOW
    except Exception as exc:
        logger.info("[HOOKS] git_gate: unexpected error (allowing): %s", exc)
        return _BLOCK_ALLOW
