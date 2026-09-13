# =================== AIPass ====================
# Name: git_gate.py
# Version: 1.0.0
# Description: Blocks raw git/gh commands and protected file edits (PreToolUse)
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-05-21
# Modified: 2026-05-21
# =============================================

"""Blocks raw git/gh commands and edits to settings/hooks files."""

import json
import os
import re
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger


RAW_GIT_RE = re.compile(r"(?<![@\w/.])git\s")
RAW_GH_RE = re.compile(r"(?<![@\w/.])gh\s")

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

BLOCKED_EDIT_PATTERNS = [
    re.compile(r"/\.claude/settings(\.local)?\.json$"),
    re.compile(r"/\.claude/hooks/"),
    re.compile(r"/\.git/hooks/"),
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


def _is_allowed_gh(cmd: str) -> bool:
    match = re.search(r"(?<![@\w/.])gh\s+(\w+)", cmd)
    if match:
        return match.group(1) in GH_ALLOWED_SUBCOMMANDS
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
        if word in _EXEC_WRAPPERS or (saw_wrapper and word.startswith("-")):
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
    if exe.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] != name:
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
            return tok
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
    tails = [clause[m.end() :].split() for m in RAW_GIT_RE.finditer(clause)]
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


def _check_bash(tool_input: dict) -> dict:
    cmd = tool_input.get("command", "")
    if not cmd:
        return _BLOCK_ALLOW
    scan = re.sub(r'"(?:[^"\\]|\\.)*"', '""', cmd)
    scan = re.sub(r"'(?:[^'\\]|\\.)*'", "''", scan)
    path_git = any(_path_exec_tail(clause, "git") is not None for clause in _split_clauses(scan))
    if (RAW_GIT_RE.search(scan) or path_git) and not _all_git_reads(scan):
        return _block(GIT_REDIRECT)
    if RAW_GH_RE.search(scan) and not _is_allowed_gh(cmd):
        return _block(GH_REDIRECT)
    path_gh = _path_gh_calls(scan)
    if path_gh and not all(tail and tail[0] in GH_ALLOWED_SUBCOMMANDS for tail in path_gh):
        return _block(GH_REDIRECT)
    return _BLOCK_ALLOW


def _check_edit(tool_input: dict, cwd: str) -> dict:
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not file_path:
        return _BLOCK_ALLOW
    for pat in BLOCKED_EDIT_PATTERNS:
        if pat.search(file_path):
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
