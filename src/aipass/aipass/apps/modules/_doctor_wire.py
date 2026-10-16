# =================== AIPass ====================
# Name: _doctor_wire.py
# Description: Auto-wire provider settings from manifest into user config
# Version: 1.2.0
# Created: 2026-05-08
# Modified: 2026-10-15
# =============================================

"""
doctor_wire — auto-wire provider settings

Extracted from doctor.py to keep module sizes manageable.
Provides:
  - HOOK_DESCRIPTIONS / ENV_DESCRIPTIONS / SETTINGS_DESCRIPTIONS — what each one is for
  - Bridge pattern — hooks wired as $AIPASS_HOME bridge commands (no script copying)
  - fix_provider_settings() — --fix's settings step: plan, show the diff, ask once, write (FPLAN-0646)
  - check_settings_scalars() — doctor's diff row per manifest settings key, with the cure command
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, List, NamedTuple, Optional

from aipass.cli.apps.modules import console, success
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.provider_wire import (
    HOOK_DESCRIPTIONS,
    ENV_DESCRIPTIONS,
    SETTINGS_DESCRIPTIONS,
    STATE_DIFFERENT,
    STATE_MISSING,
    STATE_SET,
    WIRE_COMMAND,
    SettingsGap,
    SettingsPlan,
    apply_settings_plan,
    manifest_settings,
    plan_wire_provider,
    settings_diff,
    settings_gaps,
)
from aipass.aipass.apps.handlers.settings_backup import DOOR_DOCTOR_FIX, DOOR_INSTALL
from aipass.aipass.apps.handlers.ui.progress import GLYPH_PASS, GLYPH_WARN


# =============================================================================
# STALE DENY RULE MIGRATION (implementation in handler; re-exported here)
# =============================================================================

from aipass.aipass.apps.handlers.provider_reconcile import plan_stale_deny, reconcile_stale_deny  # noqa: F401


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


def check_settings_scalars(
    manifest: dict, settings_path: "Path | None" = None
) -> "tuple[List[SettingsCheckResult], List[str]]":
    """One diff row per manifest settings key: what it wants, what the provider file has.

    Reads the PERSONAL settings file — for a scalar like includeGitInstructions that is
    the only place it takes effect, so the project copy would be a false green
    (DPLAN-0347). Returns the rows plus the keys the wire verb would actually set: a key
    the user set to a different value is not one of them, so doctor does not offer to
    wire over a human decision.

    *settings_path* is ``~/.claude/settings.json`` when None, resolved at call time.
    doctor.check_provider_manifest hands on its own settings_path seam (None in the
    product), so a test that hands a tmp settings file is never read against the live
    one (aipass, fleet green leg 6: the seam is for the tests).
    """
    wanted = manifest_settings(manifest)
    if not wanted:
        return [], []

    if settings_path is None:
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
# SHOW THE PLAN, ASK ONCE (FPLAN-0646)
# =============================================================================

SETTINGS_FIX_LABEL = "settings fix"
YES_COMMAND = "aipass doctor --fix --yes"
NOT_APPLIED_NO_TTY = f"not applied: no tty — {YES_COMMAND}"
NOT_APPLIED_DECLINED = "not applied: declined"
NOTHING_CHANGED = "Nothing changed. Re-run with --yes to apply without the question."
CONSENT_TTY = "y (tty)"
CONSENT_YES = "--yes"
CONSENT_INSTALL = "install"


def plan_settings_fix(manifest_path: Optional[Path], settings_path: Optional[Path] = None) -> List[SettingsPlan]:
    """The settings changes --fix would make: the wire, then the stale-deny removal on top of it.

    Only plans that change the file are returned; the second is computed from the
    first's result, so applying both in order lands exactly the diff shown.
    """
    plans: List[SettingsPlan] = []
    wire = plan_wire_provider(manifest_path, settings_path) if manifest_path is not None else None
    if wire is not None and wire.planned:
        plans.append(wire)
    stale = plan_stale_deny(settings_path, base=plans[0].after if plans else None)
    if stale is not None:
        plans.append(stale)
    return plans


def _render_settings_plan(plans: List[SettingsPlan]) -> int:
    """Print every planned change, one per line, then the unified diff. Returns the change count."""
    planned = [line for plan in plans for line in plan.planned]
    console.print(f"\n[bold]Planned changes to ~/.claude/settings.json ({len(planned)}):[/bold]")
    for line in planned:
        console.print(f"  • {line}", markup=False, highlight=False)
    for plan in plans:
        for note in plan.notes:
            console.print(f"  {note}", markup=False, highlight=False, style="dim")
    console.print()
    for line in settings_diff(plans[0].before, plans[-1].after):
        console.print(line, markup=False, highlight=False)
    console.print()
    return len(planned)


def _ask_apply(count: int) -> Optional[str]:
    """Ask the one question on a tty. Returns the consent string, or None for n / EOF / Ctrl-C."""
    try:
        answer = input(f"Apply these {count} changes to ~/.claude/settings.json? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt) as exc:
        logger.info("[doctor] settings question interrupted: %s", type(exc).__name__)
        answer = "n"
    return CONSENT_TTY if answer in ("y", "yes") else None


def _apply_settings_plans(plans: List[SettingsPlan], door: str, consent: str, show: bool = True) -> None:
    """Write each plan through its backed-up door; the wire plan takes *door*, the reconcile its own."""
    for plan in plans:
        actions = apply_settings_plan(plan, door if plan.door == DOOR_DOCTOR_FIX else None, consent)
        if show:
            for action in actions:
                success(action)


def fix_provider_settings(
    manifest_path: Optional[Path], door: str = DOOR_DOCTOR_FIX, yes: bool = False
) -> List[SettingsCheckResult]:
    """--fix's settings step: plan, show, ask once, write — or say why nothing was written.

    The install door (``install``) never asks; ``--yes`` writes without the question;
    a doctor-fix run with no tty and no ``--yes`` writes nothing. Returns the rows to
    add to the Services group: empty when written or when nothing needed changing.
    """
    plans = plan_settings_fix(manifest_path)
    if not plans:
        return []
    if door == DOOR_INSTALL:
        consent: Optional[str] = CONSENT_INSTALL
    elif yes:
        consent = CONSENT_YES
    else:
        count = _render_settings_plan(plans)
        if not sys.stdin.isatty():
            logger.info("[doctor] --fix with no tty and no --yes — settings plan shown, nothing written")
            return [SettingsCheckResult(SETTINGS_FIX_LABEL, GLYPH_WARN, NOT_APPLIED_NO_TTY, YES_COMMAND)]
        consent = _ask_apply(count)
        if consent is None:
            _print_manual_wire_warning([], [], [], [], [])
            console.print(NOTHING_CHANGED)
            return [SettingsCheckResult(SETTINGS_FIX_LABEL, GLYPH_WARN, NOT_APPLIED_DECLINED, YES_COMMAND)]
    _apply_settings_plans(plans, door, consent)
    json_handler.log_operation("settings_fix", {"door": door, "consent": consent, "plans": len(plans)})
    return []


def settings_fix_report(manifest_path: Optional[Path], yes: bool = False) -> dict:
    """The settings plan for ``doctor --fix --json``: written only with ``--yes`` (``applied``)."""
    plans = plan_settings_fix(manifest_path)
    report = {
        "planned": [line for plan in plans for line in plan.planned],
        "notes": [note for plan in plans for note in plan.notes],
        "diff": settings_diff(plans[0].before, plans[-1].after) if plans else [],
        "applied": False,
    }
    if plans and yes:
        _apply_settings_plans(plans, DOOR_DOCTOR_FIX, CONSENT_YES, show=False)
        report["applied"] = True
    json_handler.log_operation("settings_fix_report", {"plans": len(plans), "applied": report["applied"]})
    return report


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
    settings_path: Optional[Path] = None,
) -> bool:
    """Show the planned wire line by line with its diff, ask once, or print the manual warning.

    Returns True if wiring was performed.
    """
    missing_settings = missing_settings or []
    logger.warning(
        "[doctor] %d hooks, %d env vars, %d permissions, %d settings missing",
        len(missing_hooks),
        len(missing_env),
        len(missing_deny) + len(missing_ask),
        len(missing_settings),
    )
    plan = plan_wire_provider(manifest_path, settings_path)
    consent: Optional[str] = None
    if plan is not None and plan.planned:
        count = _render_settings_plan([plan])
        console.print("[dim]Review details: .claude/hooks/README.md[/dim]")
        if not sys.stdin.isatty():
            logger.info("[doctor] non-interactive stdin — auto-wire prompt skipped, treating as decline")
        else:
            consent = _ask_apply(count)

    if plan is not None and consent is not None:
        for action in apply_settings_plan(plan, consent=consent):
            success(action)
        return True

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
    console.print("  [dim]- fix_provider_settings() — plan, show, ask once, write through the backed-up doors[/dim]")
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
