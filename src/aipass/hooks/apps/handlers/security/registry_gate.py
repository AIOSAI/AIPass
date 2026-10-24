# =================== AIPass ====================
# Name: registry_gate.py
# Version: 1.3.0
# Description: Blocks raw writes, edits, and deletions of *_REGISTRY.json (PreToolUse)
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-07-10
# Modified: 2026-10-24
# =============================================

"""Blocks raw writes, edits, and deletions of *_REGISTRY.json files.

Only drone @spawn (tier-gated) writes the registry, ownership's one source of truth. A crash refuses the call.
"""

import functools
import glob
import importlib
import json
import re
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger


REGISTRY_RE = re.compile(r"\w+_REGISTRY\.json$")
_GLOB_CHARS = re.compile(r"[*?[{]")
_GLOB_TOKEN = re.compile(r"\[[^]]*\]|\{[^}]*\}|.", re.S)
_REGISTRY_TOKENS = ("?", "*", *"_REGISTRY.json")
_TRANSFERS = frozenset({"cp", "install", "ln", "link", "rsync"})
_WRITERS = _TRANSFERS | {"mv", "truncate", "touch", "tee", "chattr", "setfacl", "chmod", "chown", "sed", "dd"}

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

REGISTRY_REDIRECT = (
    "{file} is a sealed registry — direct writes are blocked.\nUse drone @spawn to manage registry entries."
)

_BLOCK_ALLOW = {"stdout": "", "exit_code": 0}


GATE_CRASHED = (
    "registry_gate could not check this call ({error}), so it is refused: a gate that cannot read a call "
    "does not let it through.\n"
    'Mail @hooks and @devpulse: drone @ai_mail email @hooks "Gate broken: registry_gate" "<what you ran, and this text>"'
)


def _block(reason: str) -> dict:
    return {"stdout": json.dumps({"decision": "block", "reason": reason}), "exit_code": 2, "sound": "registry gate"}


def _is_registry_file(name: str) -> bool:
    return bool(REGISTRY_RE.search(Path(name).name))


def _glob_tokens(name: str) -> tuple[str, ...]:
    """A glob as tokens: "*" any run (a {...} group too), "?" any one character (a [...] class too), else a literal."""
    tokens = _GLOB_TOKEN.findall(name)
    return tuple(
        "*" if t == "*" or t[0] == "{" else "?" if t == "?" or (t[0] == "[" and len(t) > 1) else t for t in tokens
    )


@functools.cache
def _meets(p: tuple[str, ...], q: tuple[str, ...], i: int = 0, j: int = 0) -> bool:
    """True when the globs *p* and *q* (as tokens) match at least one name in common."""
    if i == len(p) and j == len(q):
        return True
    if i < len(p) and p[i] == "*" and (_meets(p, q, i + 1, j) or (j < len(q) and _meets(p, q, i, j + 1))):
        return True
    if j < len(q) and q[j] == "*" and (_meets(p, q, i, j + 1) or (i < len(p) and _meets(p, q, i + 1, j))):
        return True
    if i == len(p) or j == len(q) or "*" in (p[i], q[j]):
        return False
    return (p[i] == q[j] or "?" in (p[i], q[j])) and _meets(p, q, i + 1, j + 1)


def _names_a_registry(name: str, folder: Path | None) -> bool:
    """True when *name* is a registry, or as a glob could expand to one; a folder on disk answers for its glob."""
    if not _GLOB_CHARS.search(name):
        return _is_registry_file(name)
    if folder is not None and "{" not in name and not _GLOB_CHARS.search(str(folder)) and folder.is_dir():
        return any(_is_registry_file(hit) for hit in glob.glob(name, root_dir=folder))
    return _meets(_glob_tokens(name), _REGISTRY_TOKENS)


def _unseen_operands(reader, inv) -> list[str]:
    """Operands mutated_paths cannot see: every one past a cd the reader lost, and a glob word anywhere."""
    words = [w for w in inv.argv[1:] if not w.startswith("-")]
    in_place = any(w.startswith("--in-place") or (w[:1] == "-" and w[1:2] != "-" and "i" in w) for w in inv.argv[1:])
    if inv.program == "dd":
        words = [w[3:] for w in words if w.startswith("of=")]
    elif inv.program in _TRANSFERS:
        words = words[-1:]
    elif (inv.program == "sed" and not in_place) or (
        inv.program not in _WRITERS and inv.program not in reader.DELETE_PROGRAMS
    ):
        return []
    return [w for w in words if not inv.cwd or _GLOB_CHARS.search(w)]


def _reader():
    """The branch's one shell-word reader (modules/shell_reader), imported at call time (crash isolation)."""
    return importlib.import_module("aipass.hooks.apps.modules.shell_reader")


def _check_bash(tool_input: dict, cwd: str) -> dict:
    """Refuse what shell_reader sees writing, deleting, moving or linking a registry; drone @spawn names none."""
    command = tool_input.get("command", "")
    if not command:
        return _BLOCK_ALLOW
    if not cwd:
        raise ValueError("the Bash call carries no cwd, so the paths it names cannot be resolved")
    reader = _reader()
    # The shell expands a glob after this gate reads it: a word that could match a registry is one.
    for path, role, _how in reader.mutated_paths(command, cwd):
        if _names_a_registry(path.name, path.parent):
            logger.info("[HOOKS] registry_gate: refused a %s of %s", role, path)
            return _block(REGISTRY_REDIRECT.format(file=path.name))
    for inv in reader.invocations(command, cwd):
        for word in _unseen_operands(reader, inv):
            path = Path(word)
            if _names_a_registry(path.name, Path(inv.cwd) / path.parent if inv.cwd else None):
                logger.info("[HOOKS] registry_gate: refused %s on %s", inv.program, word)
                return _block(REGISTRY_REDIRECT.format(file=path.name))
    return _BLOCK_ALLOW


def _check_edit(tool_input: dict) -> dict:
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not file_path:
        return _BLOCK_ALLOW
    if _is_registry_file(file_path):
        return _block(REGISTRY_REDIRECT.format(file=Path(file_path).name))
    return _BLOCK_ALLOW


def handle(hook_data: dict) -> dict:
    """The engine's hook event in, {stdout: block JSON or "", exit_code} out."""
    tool_name = hook_data.get("tool_name", "") if isinstance(hook_data, dict) else ""
    try:
        tool_input = hook_data.get("tool_input", {})

        if tool_name == "Bash":
            return _check_bash(tool_input, hook_data.get("cwd", ""))
        if tool_name in EDIT_TOOLS:
            return _check_edit(tool_input)
        return _BLOCK_ALLOW
    except Exception as exc:  # fail closed on what this gate guards (DPLAN-0356 item 2)
        logger.error("[HOOKS] registry_gate: crashed on %s, refusing it: %s", tool_name or "(no tool)", exc)
        if tool_name == "Bash" or tool_name in EDIT_TOOLS:
            return _block(GATE_CRASHED.format(error=f"{type(exc).__name__}: {exc}"))
        return _BLOCK_ALLOW
