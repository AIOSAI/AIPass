# =================== AIPass ====================
# Name: settings_backup.py
# Version: 1.0.1
# Description: Backs up ~/.claude/settings*.json and appends a receipt before any tool writes it (PreToolUse)
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-10-15
# Modified: 2026-10-24
# =============================================

"""The tool doors of the settings-backup contract (FPLAN-0645).

Contract: no ``~/.claude/settings*.json`` write without a copy and a receipt in
``~/.claude/.backup/settings/``; @aipass's Python doors write the same shape there.
A failed copy or append, or any crash, refuses the call. The Bash lane sees only
what shell_reader sees (bash_writes.NOT_CAUGHT).
"""

import datetime
import fnmatch
import hashlib
import importlib
import json
import os
import shutil
from pathlib import Path

DOORS = {
    "Edit": "edit-tool",
    "Write": "write-tool",
    "MultiEdit": "multiedit-tool",
    "NotebookEdit": "notebookedit-tool",
    "Bash": "bash",
}

SETTINGS_PATTERN = "settings*.json"

_BLOCK_ALLOW = {"stdout": "", "exit_code": 0}

UNBACKED = (
    "{file} was not changed: its backup failed, and the owner's rule is no change without a copy and a receipt "
    "(FPLAN-0645).\n"
    "Backup: {where}\n"
    "Error: {error}\n"
    "Free the folder or fix its permissions, then run the call again. "
    'Mail @hooks if it persists: drone @ai_mail email @hooks "settings_backup refused" "<this text>"'
)

GATE_CRASHED = (
    "settings_backup could not check this call ({error}), so it is refused: a write to ~/.claude/settings*.json "
    "never goes through unbacked.\n"
    "Mail @hooks and @devpulse: "
    'drone @ai_mail email @hooks "Gate broken: settings_backup" "<what you ran, and this text>"'
)


def _claude_dir() -> Path:
    """The provider settings directory, read per call. A seam: the tests point it at a tmp home."""
    return Path.home() / ".claude"


def _now() -> datetime.datetime:
    """Local time, aware. A seam: the tests pin the clock to put two backups in one second."""
    return datetime.datetime.now().astimezone()


def _block(reason: str) -> dict:
    return {"stdout": json.dumps({"decision": "block", "reason": reason}), "exit_code": 2, "sound": "settings backup"}


def _log_refusal(message: str, *args: object) -> None:
    """The refusal line in prax, imported here so the allowing path stays stdlib only."""
    from aipass.prax.apps.modules.logger import system_logger as logger

    logger.warning(message, *args)


def _settings_file(raw: str, cwd: str, claude_dir: Path) -> Path | None:
    """The ~/.claude/settings*.json file *raw* writes, spelled in that directory, or None.

    A symlink counts from either end: a link in ~/.claude, or one elsewhere landing there.
    """
    spelled = Path(os.path.expanduser(raw))
    if not spelled.is_absolute():
        spelled = Path(cwd) / spelled
    if not fnmatch.fnmatchcase(spelled.name.lower(), SETTINGS_PATTERN) and not spelled.is_symlink():
        return None
    home = os.path.normcase(str(claude_dir.resolve()))
    for candidate in (spelled.parent.resolve() / spelled.name, spelled.resolve()):
        if os.path.normcase(str(candidate.parent)) == home and fnmatch.fnmatchcase(
            candidate.name.lower(), SETTINGS_PATTERN
        ):
            return candidate
    return None


def _bash_paths(command: str, cwd: str) -> list[str]:
    """Every path the shell reader sees *command* change: git_gate's protected lane, read the same way."""
    reader = importlib.import_module("aipass.hooks.apps.modules.shell_reader")
    programs = importlib.import_module("aipass.hooks.apps.modules.shell_programs")
    paths = [str(path) for path, _role, _how in reader.mutated_paths(command, cwd)]
    paths.extend(str(path) for _program, path in programs.named_operands(reader.invocations(command, cwd)))
    return paths


def _actor(cwd: str) -> str:
    """The branch the seat stands in, found as branch_loader finds it (.trinity/ or apps/), else the cwd path."""
    here = Path(cwd).resolve()
    search = here
    while search.parent != search:
        if (search / ".trinity").is_dir() or (search / "apps").is_dir():
            return search.name
        if (search / "pyproject.toml").exists() or (search / ".git").is_dir():
            break
        search = search.parent
    return str(here)


def _summary(tool_name: str, tool_input: dict) -> list[str]:
    """The receipt's summary: the tool, then the Edit pairs (120 chars a side) or the command (200 chars)."""
    lines = [tool_name]
    if tool_name == "Edit":
        lines.append(f"{str(tool_input.get('old_string', ''))[:120]} → {str(tool_input.get('new_string', ''))[:120]}")
    elif tool_name == "MultiEdit":
        for edit in tool_input.get("edits") or []:
            if isinstance(edit, dict):
                lines.append(f"{str(edit.get('old_string', ''))[:120]} → {str(edit.get('new_string', ''))[:120]}")
    elif tool_name == "Bash":
        lines.append(str(tool_input.get("command", ""))[:200])
    return lines


def _ensure_folder(folder: Path) -> None:
    """Create the backup folder 0700 on first use; an existing one is left as it is."""
    if folder.is_dir():
        return
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":  # POSIX mode bits; Windows ACLs are not set from here
        os.chmod(folder, 0o700)


def _reserve(folder: Path, base: str) -> Path:
    """Claim a backup name nobody holds: *base*, then base-2, base-3, … An existing backup is never overwritten."""
    suffix = 1
    candidate = folder / base
    while candidate.exists():
        suffix += 1
        candidate = folder / f"{base}-{suffix}"
    os.close(os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    return candidate


def _keep(target: Path, tool_name: str, tool_input: dict, cwd: str, claude_dir: Path) -> dict | None:
    """Copy *target* and append its receipt. None when both landed, else the refusal naming where it failed."""
    door = DOORS[tool_name]
    folder = claude_dir / ".backup" / "settings"
    where = folder
    now = _now()
    record: dict = {
        "time": now.isoformat(timespec="seconds"),
        "door": door,
        "file": target.name,
        "actor": _actor(cwd),
        "pid": os.getpid(),
        "backup": None,
        "before_sha256": None,
        "after_sha256": None,
        "summary": _summary(tool_name, tool_input),
    }
    try:
        _ensure_folder(folder)
        if target.is_file():
            where = _reserve(folder, f"{target.name}.{now.strftime('%Y-%m-%dT%H-%M-%S')}.{door}")
            shutil.copy2(target, where)
            if os.name != "nt":  # the settings file is 0600; its copy is too
                os.chmod(where, 0o600)
            record["backup"] = where.name
            record["before_sha256"] = hashlib.sha256(where.read_bytes()).hexdigest()
        else:
            record["note"] = "no file existed"
        where = folder / "receipts.jsonl"
        with open(where, "a", encoding="utf-8") as receipts:
            receipts.write(json.dumps(record) + "\n")
    except OSError as exc:
        _log_refusal(
            "[HOOKS] settings_backup: refused %s on %s, backup failed at %s: %s", tool_name, target, where, exc
        )
        return _block(UNBACKED.format(file=target, where=where, error=exc))
    return None


def handle(hook_data: dict) -> dict:
    """Back up every ~/.claude/settings*.json file this call writes, then allow; refuse if a backup fails."""
    tool_name = hook_data.get("tool_name", "") if isinstance(hook_data, dict) else ""
    if tool_name not in DOORS:
        return _BLOCK_ALLOW
    try:
        tool_input = hook_data.get("tool_input") or {}
        cwd = hook_data.get("cwd", "") or os.getcwd()
        if tool_name == "Bash":
            command = str(tool_input.get("command", ""))
            raws = _bash_paths(command, cwd) if command else []
        else:
            raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
            raws = [str(raw)] if raw else []
        claude_dir = _claude_dir()
        targets: dict[str, Path] = {}
        for raw in raws:
            target = _settings_file(raw, cwd, claude_dir)
            if target is not None:
                targets.setdefault(os.path.normcase(str(target)), target)
        for target in targets.values():
            refused = _keep(target, tool_name, tool_input, cwd, claude_dir)
            if refused is not None:
                return refused
        return _BLOCK_ALLOW
    except Exception as exc:  # fail closed: a write this gate cannot check never goes through unbacked
        _log_refusal("[HOOKS] settings_backup: crashed on %s, refusing it: %s", tool_name, exc)
        return _block(GATE_CRASHED.format(error=f"{type(exc).__name__}: {exc}"))
