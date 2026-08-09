# =================== AIPass ====================
# Name: provider_wire.py
# Description: Auto-wire provider settings from manifest into user config
# Version: 1.0.1
# Created: 2026-07-11
# Modified: 2026-08-09
# =============================================

"""provider_wire — auto-wire provider settings.

Hooks use manifest-driven strip-and-readd (removes stale AIPass bridge entries);
env vars and permissions remain additive-only merges into ~/.claude/settings.json.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

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
    manifest = json_handler.load_path(manifest_path)
    if manifest is None:
        raise FileNotFoundError(f"provider manifest unreadable: {manifest_path}")
    manifest_hooks = manifest.get("cli", {}).get("claude", {}).get("hooks", [])

    settings_path = Path.home() / ".claude" / "settings.json"
    settings = (json_handler.load_path(settings_path) if settings_path.exists() else {}) or {}

    merged_hooks, actions = _strip_and_readd_hooks(settings.get("hooks", {}) or {}, manifest_hooks)
    settings["hooks"] = merged_hooks

    json_handler.save_path(settings_path, settings)
    actions.append("Updated ~/.claude/settings.json (hooks)")
    json_handler.log_operation("refresh_provider_hooks", {"actions": len(actions)})
    return actions


def auto_wire_provider(manifest_path: Path, interactive: bool = True) -> List[str]:
    """Auto-wire provider settings from manifest into ~/.claude/settings.json.

    Hooks: manifest-driven strip-and-readd (removes stale AIPass bridge entries).
    Env vars and permissions: additive merge only — never removed or overwritten.
    Returns list of action descriptions (for logging/display).
    """
    actions: List[str] = []

    manifest = json_handler.load_path(manifest_path)
    if manifest is None:
        return actions
    claude_section = manifest.get("cli", {}).get("claude", {})
    if not claude_section:
        return actions

    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        settings = json_handler.load_path(settings_path) or {}
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

    json_handler.save_path(settings_path, settings)
    actions.append("Updated ~/.claude/settings.json")

    json_handler.log_operation("auto_wire_provider", {"actions": len(actions)})
    return actions
