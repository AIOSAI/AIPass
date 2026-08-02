# =================== AIPass ====================
# Name: _doctor_wire.py
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
  - Bridge pattern — hooks wired as $AIPASS_HOME bridge commands (no script copying)
  - _auto_wire_provider()  — hooks: manifest-driven strip-and-readd; env/permissions: additive merge
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List, NamedTuple

from aipass.cli.apps.modules import console, success
from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.provider_wire import (  # noqa: F401
    HOOK_DESCRIPTIONS,
    ENV_DESCRIPTIONS,
    auto_wire_provider as _auto_wire_provider,
)


# =============================================================================
# STALE DENY RULE MIGRATION (implementation in handler; re-exported here)
# =============================================================================

from aipass.aipass.apps.handlers.provider_reconcile import reconcile_stale_deny  # noqa: E402, F401


# =============================================================================
# INTERACTIVE WIRE PROMPTS
# =============================================================================


def _prompt_auto_wire(
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

    if args[0] in ("--help", "-h", "help"):
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
