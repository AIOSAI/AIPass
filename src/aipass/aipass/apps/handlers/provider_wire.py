# =================== AIPass ====================
# Name: provider_wire.py
# Description: Auto-wire provider settings from manifest into user config
# Version: 1.1.0
# Created: 2026-07-11
# Modified: 2026-09-15
# =============================================

"""provider_wire — auto-wire provider settings.

Hooks use manifest-driven strip-and-readd (removes stale AIPass bridge entries);
env vars, permissions and the settings scalar slot remain additive-only merges
into ~/.claude/settings.json.

THE SETTINGS SCALAR SLOT (DPLAN-0347)
-------------------------------------
`cli.claude.settings` in provider_manifest.json is a small map of TOP-LEVEL
provider-settings keys and the values AIPass wants — first entry
`includeGitInstructions: false`, which only takes effect in the personal
settings file (the project copy is ignored, measured S470/S471).

The manifest is the single source: this file never carries a default of its own.
The merge is additive and one-directional — a key AIPass wants and the user has
not set gets set; a key the user has set to a DIFFERENT value is reported and
left alone, because an explicit human value outranks the manifest. No other key
in the file is read or written.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, NamedTuple

from aipass.prax import logger
from aipass.aipass.apps.handlers.json import json_handler

# =============================================================================
# HOOK & ENV DESCRIPTIONS
# =============================================================================

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

# --- The settings scalar slot (DPLAN-0347) ---
SETTINGS_SLOT = "settings"

SETTINGS_DESCRIPTIONS: Dict[str, str] = {
    "includeGitInstructions": "drops the ~4k-char gitStatus block Claude Code injects every session",
}

WIRE_COMMAND = "aipass doctor --fix"

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


# =============================================================================
# SETTINGS SCALAR SLOT
# =============================================================================


def manifest_settings(manifest: dict) -> Dict[str, Any]:
    """The top-level provider-settings keys the manifest wants, and their values.

    Scalars only (bool/int/float/str). A non-scalar in the slot is dropped with a
    log line rather than merged: this slot writes top-level scalars, so a nested
    block typed into it can never reach settings.json through here.
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

    The one reader both lanes use, so `aipass doctor` reports exactly what the wire
    verb would do — a MISSING key gets set, a DIFFERENT one is left to its owner.
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
    """Set the manifest's scalars that are absent; report, never overwrite, the rest.

    Mutates `settings` in place — only keys the manifest names, and only when the
    file does not have them yet.
    """
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


# =============================================================================
# AUTO-WIRE
# =============================================================================


def _platform_bridge_command(command: str) -> str:
    """Write-time OS transform for the venv interpreter path (manifest stays POSIX-canonical)."""
    # DPLAN-0234 Strand C: CC on Windows runs hooks via Git Bash so $AIPASS_HOME expansion still
    # works, but the venv interpreter itself lives at .venv/Scripts/python.exe there, not .venv/bin/python3.
    if os.name == "nt":
        return command.replace("/.venv/bin/python3", "/.venv/Scripts/python.exe")
    return command


def _build_manifest_hook_entries(manifest_hooks: List[dict]) -> Dict[str, List[dict]]:
    """Build the settings.json hook-entry shape per event from manifest hook rows."""
    fresh: Dict[str, List[dict]] = {}
    for hook in manifest_hooks:
        command = _platform_bridge_command(hook.get("command", ""))
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

    Prevents a stale bridge entry (old matcher/command shape from a prior manifest
    version) from surviving alongside a fresh one after an upgrade — the additive-merge
    double-fire bug (DPLAN-0279). User-wired (non-bridge) hooks in any event are always
    preserved untouched.
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


def refresh_provider_hooks(manifest_path: Path) -> List[str]:
    """Strip-and-readd AIPass bridge hooks from manifest into ~/.claude/settings.json.

    The install-time entry point: setup.sh's venv-python heredoc is its only caller.
    The in-process path (`doctor --fix`, the interactive wire-prompt) goes through
    auto_wire_provider instead — the two are siblings, not a chain. What they share
    is _strip_and_readd_hooks, the single source of truth for the merge itself, so
    upgrades never leave a stale bridge entry from an old manifest version alongside
    the current one.

    Fails honestly: raises if the manifest can't be read/parsed rather than silently
    leaving stale wiring in place.
    """
    manifest = json_handler.read_json(manifest_path)
    if manifest is None:
        raise FileNotFoundError(f"provider manifest unreadable: {manifest_path}")
    manifest_hooks = manifest.get("cli", {}).get("claude", {}).get("hooks", [])

    settings_path = Path.home() / ".claude" / "settings.json"
    settings = (json_handler.read_json(settings_path) if settings_path.exists() else {}) or {}

    merged_hooks, actions = _strip_and_readd_hooks(settings.get("hooks", {}) or {}, manifest_hooks)
    settings["hooks"] = merged_hooks

    json_handler.write_json(settings_path, settings)
    actions.append("Updated ~/.claude/settings.json (hooks)")
    json_handler.log_operation("refresh_provider_hooks", {"actions": len(actions)})
    return actions


def auto_wire_provider(manifest_path: Path, interactive: bool = True) -> List[str]:
    """Auto-wire provider settings from manifest into ~/.claude/settings.json.

    Hooks: manifest-driven strip-and-readd (removes stale AIPass bridge entries).
    Env vars, permissions and the settings scalar slot: additive merge only — never
    removed or overwritten. A settings key the user has set to a different value is
    reported in the returned actions and left as the user set it.
    Returns list of action descriptions (for logging/display).
    """
    actions: List[str] = []

    manifest = json_handler.read_json(manifest_path)
    if manifest is None:
        return actions
    claude_section = manifest.get("cli", {}).get("claude", {})
    if not claude_section:
        return actions

    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        settings = json_handler.read_json(settings_path) or {}
    else:
        settings = {}

    if settings_path.exists():
        date_stamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        backup_path = settings_path.with_suffix(f".json.bak.{date_stamp}")
        shutil.copy2(settings_path, backup_path)
        actions.append(f"Backed up settings to {backup_path.name}")

    manifest_hooks = claude_section.get("hooks", [])
    merged_hooks, hook_actions = _strip_and_readd_hooks(settings.get("hooks", {}) or {}, manifest_hooks)
    settings["hooks"] = merged_hooks
    actions.extend(hook_actions)

    manifest_env = claude_section.get("env", {})
    if manifest_env:
        if "env" not in settings:
            settings["env"] = {}
        repo_root = str(manifest_path.parent.parent)
        project_root = str(Path.cwd())
        for key, value in manifest_env.items():
            if key not in settings["env"]:
                resolved = value.replace("{{REPO_ROOT}}", repo_root)
                resolved = resolved.replace("{{PROJECT_ROOT}}", project_root)
                settings["env"][key] = resolved
                actions.append(f"Set env {key}={resolved}")

    manifest_perms = claude_section.get("permissions", {})
    manifest_deny = manifest_perms.get("deny", [])
    manifest_ask = manifest_perms.get("ask", [])

    if manifest_deny or manifest_ask:
        if "permissions" not in settings:
            settings["permissions"] = {}
        if "deny" not in settings["permissions"]:
            settings["permissions"]["deny"] = []
        if "ask" not in settings["permissions"]:
            settings["permissions"]["ask"] = []

        existing_deny = set(settings["permissions"]["deny"])
        for rule in manifest_deny:
            if rule not in existing_deny:
                settings["permissions"]["deny"].append(rule)
                actions.append(f"Added deny rule: {rule}")

        existing_ask = set(settings["permissions"]["ask"])
        for rule in manifest_ask:
            if rule not in existing_ask:
                settings["permissions"]["ask"].append(rule)
                actions.append(f"Added ask rule: {rule}")

    # Top-level scalars the manifest names (DPLAN-0347) — same write, same backup.
    actions.extend(_merge_settings_scalars(settings, manifest_settings(manifest)))

    json_handler.write_json(settings_path, settings)
    actions.append("Updated ~/.claude/settings.json")

    json_handler.log_operation("auto_wire_provider", {"actions": len(actions)})
    return actions
