# =================== AIPass ====================
# Name: _doctor_wire.py
# Description: Auto-wire provider settings from manifest into user config
# Version: 1.1.0
# Created: 2026-05-08
# Modified: 2026-09-15
# =============================================

"""
doctor_wire — auto-wire provider settings

Extracted from doctor.py to keep module sizes manageable.
Provides:
  - HOOK_DESCRIPTIONS / ENV_DESCRIPTIONS / SETTINGS_DESCRIPTIONS — what each one is for
  - Bridge pattern — hooks wired as $AIPASS_HOME bridge commands (no script copying)
  - _auto_wire_provider()  — hooks: manifest-driven strip-and-readd; env/permissions/settings: additive merge
  - check_settings_scalars() — doctor's diff row per manifest settings key, with the cure command
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, List, NamedTuple

from aipass.cli.apps.modules import console, success
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.provider_wire import (  # noqa: F401
    HOOK_DESCRIPTIONS,
    ENV_DESCRIPTIONS,
    SETTINGS_DESCRIPTIONS,
    STATE_DIFFERENT,
    STATE_MISSING,
    STATE_SET,
    WIRE_COMMAND,
    SettingsGap,
    auto_wire_provider as _auto_wire_provider,
    manifest_settings,
    settings_gaps,
)
from aipass.aipass.apps.handlers.ui.progress import GLYPH_PASS, GLYPH_WARN


# =============================================================================
# STALE DENY RULE MIGRATION (implementation in handler; re-exported here)
# =============================================================================

from aipass.aipass.apps.handlers.provider_reconcile import reconcile_stale_deny  # noqa: E402, F401


# =============================================================================
# SETTINGS SCALAR SLOT — doctor's diff rows (DPLAN-0347)
# =============================================================================


class SettingsCheckResult(NamedTuple):
    """One doctor check row (mirrors doctor.CheckResult without importing it)."""

    label: str
    glyph: str
    detail: str
    remediation: str


def merge_manifest_rows(services: List[Any], manifest_results: List[Any]) -> List[Any]:
    """Swap the Services group's provider rows for a fresh manifest pass.

    Replaces every label the fresh pass carries, plus the three fixed provider labels
    so an empty/failed pass still clears them. A settings-scalar row is labelled with
    the manifest KEY, not a fixed name — filtering on the fixed three alone left the
    first pass's row beside the new one and doctor printed the same gap twice
    (measured on a scratch HOME, DPLAN-0347).
    """
    replaced = {row.label for row in manifest_results} | {"hooks", "env vars", "permissions"}
    return [row for row in services if row.label not in replaced] + manifest_results


def _settings_cure(gap: SettingsGap) -> str:
    """The exact command that closes this gap — teach by command, never a hand edit."""
    if gap.state == STATE_DIFFERENT:
        return (
            f'Your value stands — aipass never overwrites it. To take the manifest\'s: drop "{gap.key}" '
            f"from ~/.claude/settings.json, then run: {WIRE_COMMAND}"
        )
    return f"Run: {WIRE_COMMAND}"


def check_settings_scalars(manifest: dict) -> "tuple[List[SettingsCheckResult], List[str]]":
    """One diff row per manifest settings key: what it wants, what the provider file has.

    Reads the PERSONAL settings file — for a scalar like includeGitInstructions that is
    the only place it takes effect, so the project copy would be a false green
    (DPLAN-0347). Returns the rows plus the keys the wire verb would actually set: a key
    the user set to a different value is not one of them, so doctor does not offer to
    wire over a human decision.
    """
    wanted = manifest_settings(manifest)
    if not wanted:
        return [], []

    settings_path = Path.home() / ".claude" / "settings.json"
    read = json_handler.read_json(settings_path) if settings_path.exists() else {}
    if not isinstance(read, dict):
        logger.warning("[doctor] provider settings unreadable for the settings scalars: %s", settings_path)
        read = {}
    provider_settings: dict = read

    rows: List[SettingsCheckResult] = []
    settable: List[str] = []
    for gap in settings_gaps(wanted, provider_settings):
        if gap.state == STATE_SET:
            rows.append(SettingsCheckResult(gap.key, GLYPH_PASS, f"{json.dumps(gap.wanted)} as wanted", ""))
            continue
        has = "MISSING" if gap.state == STATE_MISSING else json.dumps(gap.actual)
        detail = f"manifest wants {json.dumps(gap.wanted)}, provider has {has}"
        rows.append(SettingsCheckResult(gap.key, GLYPH_WARN, detail, _settings_cure(gap)))
        if gap.state == STATE_MISSING:
            settable.append(gap.key)
    return rows, settable


# =============================================================================
# INTERACTIVE WIRE PROMPTS
# =============================================================================


def _prompt_auto_wire(
    manifest_path: Path,
    missing_hooks: List[str],
    missing_env: List[str],
    missing_deny: List[str],
    missing_ask: List[str],
    missing_settings: List[str] | None = None,
) -> bool:
    """Prompt user to auto-wire provider settings, or print manual warning.

    Returns True if wiring was performed.
    """
    missing_settings = missing_settings or []
    hook_count = len(missing_hooks)
    env_count = len(missing_env)
    perm_count = len(missing_deny) + len(missing_ask)
    logger.warning(
        "[doctor] %d hooks, %d env vars, %d permissions, %d settings missing",
        hook_count,
        env_count,
        perm_count,
        len(missing_settings),
    )
    parts = []
    if hook_count:
        parts.append(f"{hook_count} hooks")
    if env_count:
        parts.append(f"{env_count} env vars")
    if perm_count:
        parts.append(f"{perm_count} permissions")
    if missing_settings:
        parts.append(f"{len(missing_settings)} settings")
    console.print(f"\n[bold]{', '.join(parts)} missing[/bold]")
    console.print("[dim]Review details: .claude/hooks/README.md[/dim]")

    if not sys.stdin.isatty():
        logger.info("[doctor] non-interactive stdin — auto-wire prompt skipped, treating as decline")
        answer = "n"
    else:
        try:
            answer = input("Auto-wire provider settings? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt) as exc:
            logger.info("[doctor] auto-wire prompt interrupted: %s", type(exc).__name__)
            answer = "n"

    if answer in ("y", "yes"):
        actions = _auto_wire_provider(manifest_path, interactive=True)
        for action in actions:
            success(action)
        return bool(actions)

    _print_manual_wire_warning(missing_hooks, missing_env, missing_deny, missing_ask, missing_settings)
    return False


def _print_manual_wire_warning(
    missing_hooks: List[str],
    missing_env: List[str],
    missing_deny: List[str],
    missing_ask: List[str],
    missing_settings: List[str] | None = None,
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
    if missing_settings:
        console.print("[bold]Settings (personal ~/.claude/settings.json):[/bold]")
        for key in missing_settings:
            desc = SETTINGS_DESCRIPTIONS.get(key, key)
            console.print(f"  [dim]•[/dim] {key} — {desc}")
        console.print()
    console.print(f"[dim]Wire when ready: {WIRE_COMMAND} — see .claude/hooks/README.md[/dim]")


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
    console.print("  [dim]- Bridge pattern — hooks wired as $AIPASS_HOME bridge commands[/dim]")
    console.print("  [dim]- _auto_wire_provider() — hooks: strip-and-readd; env/permissions: additive merge[/dim]")
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
        console.print("[dim]Helper module — use: aipass doctor (auto-wire runs when needed)[/dim]")
        json_handler.log_operation("doctor_wire_usage", {"command": command})
        return True

    if wants_help(args):
        console.print("[dim]Helper module — use: aipass doctor (auto-wire runs when needed)[/dim]")
        json_handler.log_operation("doctor_wire_help", {"command": command})
        return True

    if args[0] in ("--info", "info"):
        print_introspection()
        json_handler.log_operation("doctor_wire_info", {"command": command})
        return True

    json_handler.log_operation("doctor_wire_noop", {"command": command})
    return False


# =============================================================================
# WIRE VERIFY GUARD (doctor check row)
# =============================================================================


class WireCheckResult(NamedTuple):
    """Single doctor check result (mirrors doctor.CheckResult without importing it)."""

    label: str
    glyph: str
    detail: str
    remediation: str


_GLYPH_PASS = "[green]✓[/green]"
_GLYPH_FAIL = "[red]✗[/red]"
_GLYPH_WARN = "[yellow]![/yellow]"


def check_wire_verify() -> list[WireCheckResult]:
    """Run the hooks wire_verify guard — catch empty/orphaned/duplicate provider entries."""
    try:
        proc = subprocess.run(
            ["drone", "@hooks", "verify"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            return [WireCheckResult("wire verify", _GLYPH_PASS, "provider hooks wired correctly", "")]
        lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
        detail = lines[-1] if lines else "errors detected"
        return [
            WireCheckResult(
                "wire verify",
                _GLYPH_FAIL,
                detail,
                "Run 'aipass doctor --fix' to re-wire, then re-run doctor to confirm",
            )
        ]
    except FileNotFoundError as exc:
        logger.warning("[doctor] drone not found for wire_verify: %s", exc)
        return [WireCheckResult("wire verify", _GLYPH_WARN, "drone not found", "")]
    except subprocess.TimeoutExpired as exc:
        logger.warning("[doctor] wire_verify timed out: %s", exc)
        return [WireCheckResult("wire verify", _GLYPH_WARN, "timed out", "")]
