# =================== AIPass ====================
# Name: provider_wire.py
# Description: Auto-wire provider settings from manifest into user config
# Version: 1.5.1
# Created: 2026-07-11
# Modified: 2026-10-17
# =============================================

"""provider_wire — auto-wire provider settings.

Hooks are strip-and-readd (stale bridge entries go); env, permissions and the
top-level settings scalars are additive only: a value the user set is reported,
never overwritten. The manifest is the single source; this file holds no defaults.
Both doors (setup.sh install, doctor --fix) back up before the write, receipt after.
"""

from __future__ import annotations

import copy
import difflib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, NamedTuple, Optional

from aipass.prax import logger
from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.settings_backup import (
    DOOR_DOCTOR_FIX,
    DOOR_SETUP_SH,
    BackupRecord,
    SettingsBackupError,
    backup_before_write,
    sha256_of,
    write_receipt,
)

HOOK_DESCRIPTIONS: Dict[str, str] = {
    "pre_edit_gate.py": "blocks edits outside agent's branch",
    "subagent_stop_gate.py": "validates agent output on exit",
    "auto_fix_diagnostics.py": "auto-fixes lint issues after edits",
    "global_prompt_loader.py": "injects branch context on each turn",
    "identity_injector.py": "injects agent identity on each turn",
    "email_notification.py": "notifies on incoming agent mail",
    "branch_prompt_loader.py": "loads branch-specific prompts",
    "pre_compact.py": "saves state before context compaction",
}

ENV_DESCRIPTIONS: Dict[str, str] = {
    "AIPASS_HOME": "tells agents where AIPass lives",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "prevents conflict with .trinity/ memory system",
}

BRIDGE_MARKER = "bridges/claude.py"

SETTINGS_SLOT = "settings"

SETTINGS_DESCRIPTIONS: Dict[str, str] = {
    "includeGitInstructions": "drops the ~4k-char gitStatus block Claude Code injects every session",
}

WIRE_COMMAND = "aipass doctor --fix"

MSYS_ENV_KEY = "PYTHONUTF8"
MSYS_ENV_VALUE = "1"

STATE_SET = "set"
STATE_MISSING = "missing"
STATE_DIFFERENT = "different"

_SCALAR_TYPES = (bool, int, float, str)


class SettingsGap(NamedTuple):
    """One manifest settings key measured against the provider settings file."""

    key: str
    wanted: Any
    actual: Any
    state: str  # STATE_SET | STATE_MISSING | STATE_DIFFERENT


def manifest_settings(manifest: dict) -> Dict[str, Any]:
    """The top-level provider-settings keys the manifest wants, and their values.

    Scalars only: a nested block typed into the slot is dropped, never merged.
    """
    slot = manifest.get("cli", {}).get("claude", {}).get(SETTINGS_SLOT, {})
    if not isinstance(slot, dict):
        logger.warning(
            "[provider_wire] manifest %s slot is %s, not a map — ignored", SETTINGS_SLOT, type(slot).__name__
        )
        return {}
    wanted: Dict[str, Any] = {}
    for key, value in slot.items():
        if isinstance(value, _SCALAR_TYPES):
            wanted[key] = value
        else:
            logger.warning("[provider_wire] manifest %s.%s is not a scalar — skipped", SETTINGS_SLOT, key)
    return wanted


def _same_value(actual: Any, wanted: Any) -> bool:
    """True when the provider's value is the manifest's value, false/0 kept distinct."""
    if isinstance(actual, bool) != isinstance(wanted, bool):
        return False
    return actual == wanted


def settings_gaps(wanted: Dict[str, Any], settings: dict) -> List[SettingsGap]:
    """Per-key diff: what the manifest wants vs what the provider settings file has.

    The one reader both lanes use, so `aipass doctor` reports exactly what the wire does.
    """
    gaps: List[SettingsGap] = []
    for key, value in wanted.items():
        if key not in settings:
            gaps.append(SettingsGap(key, value, None, STATE_MISSING))
            continue
        actual = settings[key]
        state = STATE_SET if _same_value(actual, value) else STATE_DIFFERENT
        gaps.append(SettingsGap(key, value, actual, state))
    return gaps


def _merge_settings_scalars(settings: dict, wanted: Dict[str, Any]) -> List[str]:
    """Set the manifest's scalars that are absent; report, never overwrite, the rest."""
    actions: List[str] = []
    for gap in settings_gaps(wanted, settings):
        if gap.state == STATE_MISSING:
            settings[gap.key] = gap.wanted
            actions.append(f"Set {gap.key}={json.dumps(gap.wanted)}")
        elif gap.state == STATE_DIFFERENT:
            actions.append(
                f"Kept your {gap.key}={json.dumps(gap.actual)} "
                f"(manifest wants {json.dumps(gap.wanted)}) — your value wins, nothing overwritten"
            )
    return actions


def platform_bridge_command(command: str, os_name: Optional[str] = None) -> str:
    """Write-time OS transform for the venv interpreter path (manifest stays POSIX-canonical).

    Public: doctor's manifest check verifies with this same transform (write and verify
    must agree). *os_name* is a test seam; product callers pass None.
    """
    # Windows hooks run under Git Bash ($AIPASS_HOME still expands) but the venv is .venv/Scripts.
    if (os.name if os_name is None else os_name) == "nt":
        return command.replace("/.venv/bin/python3", "/.venv/Scripts/python.exe")
    return command


def _build_manifest_hook_entries(manifest_hooks: List[dict]) -> Dict[str, List[dict]]:
    """Build the settings.json hook-entry shape per event from manifest hook rows."""
    fresh: Dict[str, List[dict]] = {}
    for hook in manifest_hooks:
        command = platform_bridge_command(hook.get("command", ""))
        event = hook.get("event", "")
        if not command or not event:
            continue
        cmd_entry: Dict[str, object] = {"type": "command", "command": command}
        if hook.get("timeout"):
            cmd_entry["timeout"] = hook["timeout"]
        wrapper: Dict[str, object] = {}
        if hook.get("matcher"):
            wrapper["matcher"] = hook["matcher"]
        wrapper["hooks"] = [cmd_entry]
        fresh.setdefault(event, []).append(wrapper)
    return fresh


def _strip_and_readd_hooks(
    existing_hooks: Dict[str, list], manifest_hooks: List[dict]
) -> "tuple[Dict[str, list], List[str]]":
    """Strip every AIPass bridge-marked hook entry, then re-add the manifest's current set.

    An additive merge left an old-shape bridge entry beside the fresh one and the hook
    fired twice. Non-bridge (user) hooks are preserved untouched.
    """
    fresh = _build_manifest_hook_entries(manifest_hooks)
    actions: List[str] = []
    merged: Dict[str, list] = {}
    for event in sorted(set(existing_hooks) | set(fresh)):
        stale_count = sum(1 for e in existing_hooks.get(event, []) if BRIDGE_MARKER in json.dumps(e))
        user_entries = [e for e in existing_hooks.get(event, []) if BRIDGE_MARKER not in json.dumps(e)]
        event_fresh = fresh.get(event, [])
        combined = event_fresh + user_entries
        if not combined:
            actions.append(f"Dropped orphaned hook event (no live entries): {event}")
            continue
        merged[event] = combined
        if event_fresh:
            note = f" (replaced {stale_count} stale)" if stale_count else ""
            actions.append(f"Refreshed {event}: {len(event_fresh)} bridge hook(s){note}")
    return merged, actions


def _is_msys_shell(environ: Optional[Mapping[str, str]] = None) -> bool:
    """True under Git Bash / MSYS / MinGW on Windows — the one place PYTHONUTF8 belongs."""
    env = os.environ if environ is None else environ
    shell = env.get("MSYSTEM", "") + env.get("OSTYPE", "")
    return "MSYS" in shell or "msys" in shell or "MINGW" in shell


def _merge_env(settings: dict, claude_section: dict, manifest_path: Path) -> List[str]:
    """Additive env merge: the manifest's env keys the file lacks, plus PYTHONUTF8 under MSYS.

    The manifest has no guard syntax, so the wire owns the PYTHONUTF8 conditional
    (Rich output in Windows hook processes needs it).
    """
    actions: List[str] = []
    wanted: Dict[str, str] = {}
    repo_root = str(manifest_path.parent.parent)
    project_root = str(Path.cwd())
    for key, value in claude_section.get("env", {}).items():
        wanted[key] = value.replace("{{REPO_ROOT}}", repo_root).replace("{{PROJECT_ROOT}}", project_root)
    if _is_msys_shell():
        wanted.setdefault(MSYS_ENV_KEY, MSYS_ENV_VALUE)
    if not wanted:
        return actions
    env_block = settings.setdefault("env", {})
    for key, resolved in wanted.items():
        if key not in env_block:
            env_block[key] = resolved
            actions.append(f"Set env {key}={resolved}")
    return actions


def _repoint_aipass_home(settings: dict, manifest_path: Path) -> List[str]:
    """Install only: point env.AIPASS_HOME at the tree being installed, whatever it said.

    doctor --fix never calls this: a fix from a second checkout must not take the home
    from the first.
    """
    env_block = settings.get("env")
    if not isinstance(env_block, dict) or "AIPASS_HOME" not in env_block:
        return []
    repo_root = str(manifest_path.parent.parent)
    old = env_block["AIPASS_HOME"]
    if old == repo_root:
        return []
    env_block["AIPASS_HOME"] = repo_root
    return [f"Re-pointed AIPASS_HOME {old} -> {repo_root}"]


def _merge_permissions(settings: dict, claude_section: dict) -> List[str]:
    """Additive deny + ask merge: a manifest rule the file lacks is appended, none removed."""
    actions: List[str] = []
    manifest_perms = claude_section.get("permissions", {})
    manifest_deny = manifest_perms.get("deny", [])
    manifest_ask = manifest_perms.get("ask", [])
    if not (manifest_deny or manifest_ask):
        return actions
    permissions = settings.setdefault("permissions", {})
    for kind, rules in (("deny", manifest_deny), ("ask", manifest_ask)):
        current = permissions.setdefault(kind, [])
        existing = set(current)
        for rule in rules:
            if rule not in existing:
                current.append(rule)
                existing.add(rule)
                actions.append(f"Added {kind} rule: {rule}")
    return actions


def _write_with_receipt(
    settings_path: Path,
    settings: dict,
    record: BackupRecord,
    actions: List[str],
    updated_line: str,
    consent: Optional[str] = None,
) -> None:
    """Write the settings a door merged, then its receipt; the backup lines go in *actions*.

    The fleet writer returns False instead of raising; that becomes SettingsBackupError, no receipt.
    """
    if record.backup is not None:
        actions.append(f"Backed up settings to {record.backup}")
    else:
        actions.append("No settings file yet — nothing to back up")
    if not json_handler.write_json(settings_path, settings):
        logger.error("[provider_wire] settings write failed at %s; no receipt written", settings_path)
        raise SettingsBackupError(f"settings write failed at {settings_path}; no receipt written")
    actions.append(updated_line)
    summary = ([f"consent: {consent}"] if consent else []) + actions
    receipt = write_receipt(record, sha256_of(settings_path), summary)
    actions.append(f"Receipt: {receipt}")


class SettingsPlan(NamedTuple):
    """A change to the provider settings file, computed and not yet written.

    *actions* are past tense (reported after the write); *planned* only the lines that
    change the file, in planned tense; *notes* the lines that change nothing.
    """

    settings_path: Path
    before: dict
    after: dict
    actions: List[str]
    planned: List[str]
    notes: List[str]
    door: str
    updated_line: str


_REFRESHED = re.compile(
    r"^Refreshed (?P<event>\S+): (?P<n>\d+) bridge hook\(s\)(?: \(replaced (?P<stale>\d+) stale\))?$"
)

_PLANNED_PREFIXES = (
    ("Added deny rule: ", "Add deny rule "),
    ("Added ask rule: ", "Add ask rule "),
    ("Dropped orphaned hook event (no live entries): ", "Drop orphaned hook event "),
    ("Set ", "Set "),
)


def _planned_line(action: str) -> Optional[str]:
    """The planned-tense form of a past-tense action line; None for a line that changes nothing."""
    refreshed = _REFRESHED.match(action)
    if refreshed:
        stale = f" (replace {refreshed['stale']} stale)" if refreshed["stale"] else ""
        return f"Re-add {refreshed['n']} bridge hook(s) in {refreshed['event']}{stale}"
    for past, planned in _PLANNED_PREFIXES:
        if action.startswith(past):
            return planned + action[len(past) :]
    return None


def _make_plan(
    settings_path: Path, before: dict, after: dict, actions: List[str], door: str, updated_line: str
) -> SettingsPlan:
    """Split a door's action lines into the planned changes and the notes."""
    planned: List[str] = []
    notes: List[str] = []
    for action in actions:
        line = _planned_line(action)
        if line is None:
            notes.append(action)
        else:
            planned.append(line)
    return SettingsPlan(settings_path, before, after, actions, planned, notes, door, updated_line)


def _serialized(settings: dict) -> List[str]:
    """The settings as the fleet json writer lays them out, one entry per line."""
    return json.dumps(settings, indent=2, ensure_ascii=False).splitlines()


def settings_diff(before: dict, after: dict) -> List[str]:
    """A unified diff of the settings as they are against the settings as they would land."""
    return list(
        difflib.unified_diff(
            _serialized(before), _serialized(after), "settings.json (now)", "settings.json (after)", lineterm=""
        )
    )


def plan_wire_provider(manifest_path: Path, settings_path: Optional[Path] = None) -> Optional[SettingsPlan]:
    """What the doctor's wire door would write, computed without writing.

    None when the manifest is unreadable or has no ``cli.claude`` section. A hook refresh
    that leaves an event as it was is not a change, so a fully wired file plans nothing.
    """
    manifest = json_handler.read_json(manifest_path)
    if manifest is None:
        return None
    claude_section = manifest.get("cli", {}).get("claude", {})
    if not claude_section:
        return None

    if settings_path is None:
        settings_path = Path.home() / ".claude" / "settings.json"
    settings = (json_handler.read_json(settings_path) if settings_path.exists() else {}) or {}
    before = copy.deepcopy(settings)

    existing_hooks = settings.get("hooks", {}) or {}
    merged_hooks, hook_actions = _strip_and_readd_hooks(existing_hooks, claude_section.get("hooks", []))
    settings["hooks"] = merged_hooks
    unchanged = {event for event in merged_hooks if existing_hooks.get(event) == merged_hooks[event]}
    actions = [a for a in hook_actions if not any(a.startswith(f"Refreshed {e}:") for e in unchanged)]

    actions.extend(_merge_env(settings, claude_section, manifest_path))
    actions.extend(_merge_permissions(settings, claude_section))
    actions.extend(_merge_settings_scalars(settings, manifest_settings(manifest)))
    return _make_plan(settings_path, before, settings, actions, DOOR_DOCTOR_FIX, "Updated ~/.claude/settings.json")


def apply_settings_plan(plan: SettingsPlan, door: Optional[str] = None, consent: Optional[str] = None) -> List[str]:
    """Write a plan through its backed-up door: backup, write, receipt. Returns the action lines."""
    actions = list(plan.actions)
    record = backup_before_write(plan.settings_path, door or plan.door)
    _write_with_receipt(plan.settings_path, copy.deepcopy(plan.after), record, actions, plan.updated_line, consent)
    json_handler.log_operation("apply_settings_plan", {"door": door or plan.door, "actions": len(actions)})
    return actions


def refresh_provider_hooks(manifest_path: Path, settings_path: Optional[Path] = None) -> List[str]:
    """Write the manifest's hooks, env, permissions and settings scalars into ~/.claude/settings.json.

    setup.sh is the only caller; doctor --fix uses plan_wire_provider, sharing the merge
    helpers. The scalars land here so a fresh clone is wired from its first session.
    Raises on an unreadable manifest rather than leave stale wiring in place.
    """
    manifest = json_handler.read_json(manifest_path)
    if manifest is None:
        raise FileNotFoundError(f"provider manifest unreadable: {manifest_path}")
    manifest_hooks = manifest.get("cli", {}).get("claude", {}).get("hooks", [])

    if settings_path is None:
        settings_path = Path.home() / ".claude" / "settings.json"
    settings = (json_handler.read_json(settings_path) if settings_path.exists() else {}) or {}

    merged_hooks, actions = _strip_and_readd_hooks(settings.get("hooks", {}) or {}, manifest_hooks)
    settings["hooks"] = merged_hooks
    claude_section = manifest.get("cli", {}).get("claude", {})
    actions.extend(_merge_env(settings, claude_section, manifest_path))
    actions.extend(_repoint_aipass_home(settings, manifest_path))
    actions.extend(_merge_permissions(settings, claude_section))
    actions.extend(_merge_settings_scalars(settings, manifest_settings(manifest)))

    record = backup_before_write(settings_path, DOOR_SETUP_SH)
    _write_with_receipt(
        settings_path, settings, record, actions, "Updated ~/.claude/settings.json (hooks, env, permissions, settings)"
    )
    json_handler.log_operation("refresh_provider_hooks", {"actions": len(actions)})
    return actions
