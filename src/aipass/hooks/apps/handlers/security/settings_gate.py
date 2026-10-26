# =================== AIPass ====================
# Name: settings_gate.py
# Version: 1.1.0
# Description: No AI changes a provider's top-level settings alone: Claude asks the owner, Codex and headless deny
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-10-25
# Modified: 2026-10-25
# =============================================

"""The provider-settings gate (DPLAN-0424): the owner accepts every change to a CLI's own settings.

Protected: Codex's top level (~/.codex/*.toml, hooks.json, auth.json, rules/**, and the same under
$CODEX_HOME), Claude's (~/.claude/settings.json, settings.local.json), the repo wiring
(.claude/provider_manifest.json, .codex/hooks.json), and the installers that write them
(aipass doctor --fix, setup.sh, provider_wire.py) run from Bash.

Interactive Claude asks the owner for Codex's files, the wiring and the installers; its own settings
need no second ask (Claude Code prompts on them natively). Codex cannot ask (an ask is a failed hook
and the call runs), so a Codex caller is denied, as is every headless seat.
"""

import importlib
import json
import os
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

DOORS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"})
CODEX, CLAUDE, WIRING, INSTALLER = "Codex settings", "Claude settings", "AIPass provider wiring", "provider installer"
_CODEX_FILES = frozenset({"hooks.json", "auth.json"})
_CLAUDE_FILES = frozenset({"settings.json", "settings.local.json"})
_INSTALLER_SCRIPTS = frozenset({"setup.sh", "provider_wire.py"})
_HEADLESS_TYPES = frozenset({"dispatched", "headless"})
_ALLOW = {"stdout": "", "exit_code": 0}

ASK = (
    "Provider settings: {what} on {file} ({kind}). No AI changes a provider's settings without the owner "
    "accepting it. Accept only if you asked for this change."
)
DENY_CODEX = (
    "{file} ({kind}) was not changed: no AI changes a provider's settings alone, and Codex cannot ask the owner. "
    'Mail @devpulse, who asks Patrick: drone @ai_mail email @devpulse "Provider settings change" '
    '"<file>: <the change, and why>"'
)
DENY_HEADLESS = (
    "{file} ({kind}) was not changed: no AI changes a provider's settings alone, and a headless seat has nobody "
    'to ask. Mail @devpulse, who asks Patrick: drone @ai_mail email @devpulse "Provider settings change" '
    '"<file>: <the change, and why>"'
)


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _codex_dirs() -> list[Path]:
    dirs = [Path.home() / ".codex"]
    if os.environ.get("CODEX_HOME"):
        dirs.append(Path(os.environ["CODEX_HOME"]))
    return [d.resolve() for d in dirs]


def _holds(path: Path, folder: Path, whole: bool) -> bool:
    """*path* is *folder*, or a call that moves or deletes *path* whole takes an ancestor of it (and so *folder*).

    A copy into an ancestor (`cp notes ~/`) changes only the copied file."""
    return _same(path, folder) or (whole and any(_same(path, parent) for parent in folder.parents))


def _kind(path: Path, whole: bool = False) -> str | None:
    """Which protected class an absolute, resolved path is, or None. *whole*: the call moves or deletes *path*."""
    for codex in _codex_dirs():
        if _holds(path, codex, whole):
            return CODEX
        if _same(path.parent, codex) and (path.suffix.lower() == ".toml" or path.name.lower() in _CODEX_FILES):
            return CODEX
        if any(_same(folder, codex / "rules") for folder in (path, *path.parents)):
            return CODEX
    claude = (Path.home() / ".claude").resolve()
    if _holds(path, claude, whole) or (_same(path.parent, claude) and path.name.lower() in _CLAUDE_FILES):
        return CLAUDE
    loader = importlib.import_module("aipass.hooks.apps.handlers.config.loader")
    root = loader.aipass_home()
    if root is not None:
        root = root.resolve()
        if _same(path, root / ".claude" / "provider_manifest.json") or _same(path, root / ".codex" / "hooks.json"):
            return WIRING
    return None


def _protected(raw: str, cwd: str, whole: bool = False) -> tuple[Path, str] | None:
    """(file, kind) when *raw* lands on a protected file. A symlink counts from either end."""
    spelled = Path(os.path.expanduser(raw))
    if not spelled.is_absolute():
        spelled = Path(cwd) / spelled
    for candidate in (spelled.parent.resolve() / spelled.name, spelled.resolve()):
        kind = _kind(candidate, whole)
        if kind is not None:
            return candidate, kind
    return None


def _installer(command: str, cwd: str) -> str | None:
    """The installer a Bash command executes (aipass doctor --fix, setup.sh, provider_wire.py), or None.

    Executed means the program itself, or an interpreter's first operand: `cat setup.sh` only reads it."""
    reader = importlib.import_module("aipass.hooks.apps.modules.shell_reader")
    for inv in reader.invocations(command, cwd):
        if inv.program == "aipass" and "doctor" in inv.argv and "--fix" in inv.argv:
            return "aipass doctor --fix"
        if inv.program in _INSTALLER_SCRIPTS:
            return inv.program
        script = next((word for word in inv.argv[1:] if not word.startswith("-")), "") if inv.language else ""
        if Path(script).name in _INSTALLER_SCRIPTS:
            return Path(script).name
    return None


def _targets(tool_name: str, tool_input: dict, cwd: str) -> list[tuple[str, str]]:
    """(file, kind) for every protected file this call writes, in call order, each once."""
    found: dict[str, tuple[str, str]] = {}
    whole: set[str] = set()
    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        if not command:
            return []
        installer = _installer(command, cwd)
        if installer is not None:
            found[installer] = (installer, INSTALLER)
        raws = importlib.import_module("aipass.hooks.apps.modules.bash_writes").changed_paths(command, cwd)
        reader = importlib.import_module("aipass.hooks.apps.modules.shell_reader")
        # A mutated path is the very thing changed (a copy into a folder is resolved to the file); a bare
        # operand (`cp x ~/` names `~`) is not, so only the former takes a folder holding settings whole.
        whole = {str(path) for path, _role, _how in reader.mutated_paths(command, cwd)}
    else:
        raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        raws = [str(raw)] if raw else []
    for raw in raws:
        hit = _protected(raw, cwd, raw in whole)
        if hit is not None:
            found.setdefault(os.path.normcase(str(hit[0])), (str(hit[0]), hit[1]))
    return list(found.values())


def _headless() -> bool:
    """A dispatched or headless seat: AIPASS_SESSION_TYPE says so, or no interactive claude runs this call."""
    if os.environ.get("AIPASS_SESSION_TYPE", "") in _HEADLESS_TYPES:
        return True
    args = importlib.import_module("aipass.hooks.apps.modules.cc_sessions").cli_ancestor("claude")
    return args is None or bool({"-p", "--print"} & set(args[1:]))


def _what(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Bash":
        return f"Bash `{str(tool_input.get('command', ''))[:200]}`"
    return tool_name


def _branch(cwd: str) -> str:
    window = importlib.import_module("aipass.hooks.apps.modules.context_window")
    found = window.find_branch_dir(cwd)
    return found.name if found is not None else cwd


def handle(hook_data: dict) -> dict:
    """Ask (interactive Claude) or deny (Codex, headless) a write to a provider's settings; allow everything else."""
    tool_name = hook_data.get("tool_name", "") if isinstance(hook_data, dict) else ""
    if tool_name not in DOORS:
        return _ALLOW
    tool_input = hook_data.get("tool_input") or {}
    cwd = hook_data.get("cwd", "") or os.getcwd()
    targets = _targets(tool_name, tool_input, cwd)
    if not targets:
        return _ALLOW
    cli = hook_data.get("provider") or "claude"
    file, kind = targets[0]
    if cli == "codex" or _headless():
        reason = (DENY_CODEX if cli == "codex" else DENY_HEADLESS).format(file=file, kind=kind)
        logger.warning(
            "[HOOKS] settings_gate: deny caller=%s cli=%s path=%s tool=%s", _branch(cwd), cli, file, tool_name
        )
        return {"stdout": json.dumps({"decision": "block", "reason": reason}), "exit_code": 2}
    asked = [(f, k) for f, k in targets if k != CLAUDE]
    if not asked:
        return _ALLOW
    file, kind = asked[0]
    reason = ASK.format(what=_what(tool_name, tool_input), file=", ".join(f for f, _ in asked), kind=kind)
    logger.warning("[HOOKS] settings_gate: ask caller=%s cli=%s path=%s tool=%s", _branch(cwd), cli, file, tool_name)
    answer = {"hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": reason}
    return {"stdout": json.dumps({"hookSpecificOutput": answer}), "exit_code": 0}
