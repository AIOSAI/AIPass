# =================== AIPass ====================
# Name: doctor_wire.py
# Description: Auto-wire provider settings from manifest into user config
# Version: 1.0.0
# Created: 2026-05-08
# Modified: 2026-05-08
# =============================================

"""
doctor_wire — auto-wire provider settings

Extracted from doctor.py to keep module sizes manageable.
Provides:
  - HOOK_DESCRIPTIONS / ENV_DESCRIPTIONS — human-readable hook/env purpose
  - _resolve_hook_source() — locate hook scripts (repo or pip package)
  - _auto_wire_provider()  — additive merge of manifest into ~/.claude/settings.json
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from aipass.cli.apps.modules import console
from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler

# =============================================================================
# HOOK & ENV DESCRIPTIONS (for interactive "no" warning)
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


# =============================================================================
# HOOK SOURCE RESOLUTION
# =============================================================================


def _resolve_hook_source(manifest_path: Path) -> Path | None:
    """Find where hook scripts live.

    First: look for ``.claude/hooks/`` relative to the manifest path (clone/fork users).
    Fallback: find the pip-installed package location via ``aipass/_hooks/``.
    Returns the directory Path, or None if neither found.
    """
    # Repo-local hooks (manifest lives in .claude/, hooks are in .claude/hooks/)
    repo_hooks = manifest_path.parent / "hooks"
    if repo_hooks.is_dir():
        return repo_hooks

    # Pip-installed package — _hooks directory next to top-level aipass __init__.py
    try:
        import importlib.resources as _resources

        ref = _resources.files("aipass").joinpath("_hooks")
        pkg_hooks = Path(str(ref))
        if pkg_hooks.is_dir():
            return pkg_hooks
    except Exception as exc:
        logger.info("[doctor] importlib.resources lookup failed: %s", exc)

    # Manual fallback: walk up from this file to find the aipass package root
    pkg_root = Path(__file__).resolve()
    for _ in range(10):
        pkg_root = pkg_root.parent
        candidate = pkg_root / "_hooks"
        if candidate.is_dir():
            return candidate
        if pkg_root == pkg_root.parent:
            break

    return None


# =============================================================================
# AUTO-WIRE
# =============================================================================


def _auto_wire_provider(manifest_path: Path, interactive: bool = True) -> List[str]:
    """Auto-wire provider settings from manifest into ~/.claude/settings.json.

    Additive merge only — never removes or overwrites existing keys/values.
    Returns list of action descriptions (for logging/display).
    """
    actions: List[str] = []

    manifest = json_handler.load_path(manifest_path)
    if manifest is None:
        return actions
    claude_section = manifest.get("cli", {}).get("claude", {})
    if not claude_section:
        return actions

    # Read existing settings
    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        settings = json_handler.load_path(settings_path) or {}
    else:
        settings = {}

    # Backup
    if settings_path.exists():
        date_stamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        backup_path = settings_path.with_suffix(f".json.bak.{date_stamp}")
        shutil.copy2(settings_path, backup_path)
        actions.append(f"Backed up settings to {backup_path.name}")

    # Hooks — copy user-source scripts and add settings entries
    manifest_hooks = claude_section.get("hooks", [])
    hook_source_dir = _resolve_hook_source(manifest_path)
    user_hooks_dir = Path.home() / ".claude" / "hooks"

    for hook in manifest_hooks:
        script = hook.get("script", "")
        if not script:
            continue
        source_type = hook.get("source", "repo")

        # Only user-source hooks get copied to ~/.claude/hooks/
        if source_type == "user":
            target = user_hooks_dir / script
            if not target.exists() and hook_source_dir:
                src_file = hook_source_dir / script
                if src_file.exists():
                    os.makedirs(user_hooks_dir, exist_ok=True)
                    shutil.copy2(src_file, target)
                    actions.append(f"Copied hook {script} to ~/.claude/hooks/")

        # Add hook entry to settings.json if not already present
        if "hooks" not in settings:
            settings["hooks"] = {}
        event = hook.get("event", "")
        if event not in settings["hooks"]:
            settings["hooks"][event] = []
        event_hooks = settings["hooks"][event]
        if not isinstance(event_hooks, list):
            event_hooks = [event_hooks]
            settings["hooks"][event] = event_hooks

        already_wired = any(isinstance(h, dict) and script in json.dumps(h) for h in event_hooks)
        if not already_wired:
            if source_type == "user":
                hook_path = f"~/.claude/hooks/{script}"
            else:
                hook_path = f".claude/hooks/{script}"
            cmd_entry: Dict[str, object] = {
                "type": "command",
                "command": f"{sys.executable} {hook_path}",
            }
            if hook.get("timeout"):
                cmd_entry["timeout"] = hook["timeout"]
            wrapper: Dict[str, object] = {
                "matcher": hook.get("matcher", ""),
                "hooks": [cmd_entry],
            }
            event_hooks.append(wrapper)
            actions.append(f"Wired hook {script} -> {event}")

    # Env vars
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

    # Permissions
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

    # Write settings back
    json_handler.save_path(settings_path, settings)
    actions.append("Updated ~/.claude/settings.json")

    return actions


# =============================================================================
# INTERACTIVE WIRE PROMPTS
# =============================================================================


def prompt_auto_wire(
    manifest_path: Path,
    missing_hooks: List[str],
    missing_env: List[str],
    missing_deny: List[str],
    missing_ask: List[str],
) -> bool:
    """Prompt user to auto-wire provider settings, or print manual warning.

    Returns True if wiring was performed.
    """
    hook_count = len(missing_hooks)
    env_count = len(missing_env)
    perm_count = len(missing_deny) + len(missing_ask)
    logger.warning("[doctor] %d hooks, %d env vars, %d permissions missing", hook_count, env_count, perm_count)
    parts = []
    if hook_count:
        parts.append(f"{hook_count} hooks")
    if env_count:
        parts.append(f"{env_count} env vars")
    if perm_count:
        parts.append(f"{perm_count} permissions")
    console.print(f"\n[bold]{', '.join(parts)} missing[/bold]")
    console.print("[dim]Review details: .claude/hooks/README.md[/dim]")

    try:
        answer = input("Auto-wire provider settings? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt) as exc:
        logger.info("[doctor] auto-wire prompt interrupted: %s", type(exc).__name__)
        answer = "n"

    if answer in ("y", "yes"):
        actions = _auto_wire_provider(manifest_path, interactive=True)
        for action in actions:
            console.print(f"[green]✓[/green] {action}")
        return bool(actions)

    _print_manual_wire_warning(missing_hooks, missing_env, missing_deny, missing_ask)
    return False


def _print_manual_wire_warning(
    missing_hooks: List[str],
    missing_env: List[str],
    missing_deny: List[str],
    missing_ask: List[str],
) -> None:
    """Print detailed warning when user declines auto-wire."""
    logger.warning("[doctor] provider settings not wired — user declined auto-wire")
    console.print("\n[bold]Provider settings not wired. Required for full AIPass functionality:[/bold]\n")
    if missing_hooks:
        console.print("[bold]Hooks (code quality enforcement):[/bold]")
        for hook in missing_hooks:
            desc = HOOK_DESCRIPTIONS.get(hook, hook)
            console.print(f"  [dim]•[/dim] {hook} — {desc}")
        console.print()
    if missing_env:
        console.print("[bold]Env vars:[/bold]")
        for var in missing_env:
            desc = ENV_DESCRIPTIONS.get(var, var)
            console.print(f"  [dim]•[/dim] {var} — {desc}")
        console.print()
    if missing_deny or missing_ask:
        console.print(
            f"{len(missing_deny)} deny rules + {len(missing_ask)} ask rules"
            " (protect ~/.secrets/, block destructive git)"
        )
        console.print()
    console.print("[dim]Wire manually when ready — see .claude/hooks/README.md[/dim]")


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================


def print_introspection() -> None:
    """Display module info for doctor_wire."""
    console.print()
    console.print("[bold cyan]doctor_wire Module[/bold cyan]")
    console.print("Auto-wire provider settings from manifest into user config")
    console.print()
    console.print("[yellow]Provides:[/yellow]")
    console.print("  [dim]- HOOK_DESCRIPTIONS / ENV_DESCRIPTIONS[/dim]")
    console.print("  [dim]- _resolve_hook_source() — locate hook scripts[/dim]")
    console.print("  [dim]- _auto_wire_provider() — additive merge into settings[/dim]")
    console.print()


# =============================================================================
# COMMAND HANDLER
# =============================================================================


def handle_command(command: str, args: list[str]) -> bool:
    """Handle command routing. This is a helper module — no standalone commands.

    Args:
        command: Command name.
        args: Additional arguments.

    Returns:
        True if handled, False otherwise.
    """
    if command != "doctor_wire":
        return False

    if not args:
        print_introspection()
        json_handler.log_operation("doctor_wire_info", {"command": command})
        return True

    if args[0] in ("--help", "-h", "help"):
        print_introspection()
        json_handler.log_operation("doctor_wire_info", {"command": command})
        return True

    if args[0] in ("--info", "info"):
        print_introspection()
        json_handler.log_operation("doctor_wire_info", {"command": command})
        return True

    json_handler.log_operation("doctor_wire_noop", {"command": command})
    return False
