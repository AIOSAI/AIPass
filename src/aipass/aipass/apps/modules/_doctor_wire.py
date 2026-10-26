# =================== AIPass ====================
# Name: _doctor_wire.py
# Description: Auto-wire provider settings from manifest into user config
# Version: 1.3.0
# Created: 2026-05-08
# Modified: 2026-10-25
# =============================================

"""
doctor_wire — auto-wire provider settings
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, List, NamedTuple, Optional

from aipass.cli.apps.modules import console, success, warning
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
    codex_hooks_document,
    codex_hooks_path,
    manifest_settings,
    plan_codex_hooks,
    plan_wire_provider,
    settings_diff,
    settings_gaps,
)
from aipass.aipass.apps.handlers.settings_backup import DOOR_DOCTOR_FIX, DOOR_INSTALL, SettingsBackupError
from aipass.aipass.apps.handlers.ui.progress import GLYPH_FAIL, GLYPH_PASS, GLYPH_WARN


# Re-exported: callers reach the stale-deny migration through this module.
from aipass.aipass.apps.handlers.provider_reconcile import plan_stale_deny, reconcile_stale_deny  # noqa: F401


class SettingsCheckResult(NamedTuple):
    """One doctor check row (mirrors doctor.CheckResult without importing it)."""

    label: str
    glyph: str
    detail: str
    remediation: str


def merge_manifest_rows(services: List[Any], manifest_results: List[Any]) -> List[Any]:
    """Swap the Services group's provider rows for a fresh manifest pass.

    A settings-scalar row is labelled with the manifest KEY, so filtering on the three
    fixed labels alone would leave the first pass's row and print the gap twice.
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

    Reads the PERSONAL settings file, the only place such a scalar takes effect. A key the
    user set differently is not settable, so doctor never offers to wire over a human
    decision. *settings_path* is a test seam, ``~/.claude/settings.json`` when None.
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


CODEX_HOOKS_LABEL = "codex hooks"


def check_codex_hooks(manifest: dict, manifest_path: Path) -> List[SettingsCheckResult]:
    """One row: does the repo's .codex/hooks.json hold exactly what cli.codex makes? None without rows."""
    wanted = codex_hooks_document(manifest)
    if wanted is None:
        return []
    count = sum(len(entries) for entries in wanted["hooks"].values())
    try:
        plan = plan_codex_hooks(manifest_path)
    except SettingsBackupError as exc:
        logger.warning("[doctor] codex hooks unreadable: %s", exc)
        return [SettingsCheckResult(CODEX_HOOKS_LABEL, GLYPH_WARN, str(exc), f"Run: {WIRE_COMMAND}")]
    if plan is None:
        return [SettingsCheckResult(CODEX_HOOKS_LABEL, GLYPH_PASS, f"{count} Codex hooks match cli.codex", "")]
    state = "differs from" if plan.before else "missing, wanted by"
    detail = f"{codex_hooks_path(manifest_path)} {state} cli.codex ({count} hooks)"
    return [SettingsCheckResult(CODEX_HOOKS_LABEL, GLYPH_WARN, detail, f"Run: {WIRE_COMMAND}")]


SETTINGS_FIX_LABEL = "settings fix"
YES_COMMAND = "aipass doctor --fix --yes"
NOT_APPLIED_NO_TTY = f"not applied: no tty — {YES_COMMAND}"
NOT_APPLIED_DECLINED = "not applied: declined"
NOTHING_CHANGED = "Nothing changed. Re-run with --yes to apply without the question."
CONSENT_TTY = "y (tty)"
CONSENT_YES = "--yes"
CONSENT_INSTALL = "install"


def plan_settings_fix(manifest_path: Optional[Path], settings_path: Optional[Path] = None) -> List[SettingsPlan]:
    """The changes --fix would make: the wire, the stale-deny removal on top of it, the Codex hooks.

    The second is computed from the first's result, so applying both lands exactly the diff shown.
    """
    plans: List[SettingsPlan] = []
    wire = plan_wire_provider(manifest_path, settings_path) if manifest_path is not None else None
    if wire is not None and wire.planned:
        plans.append(wire)
    stale = plan_stale_deny(settings_path, base=plans[0].after if plans else None)
    if stale is not None:
        plans.append(stale)
    codex = plan_codex_hooks(manifest_path) if manifest_path is not None else None
    if codex is not None:
        plans.append(codex)
    return plans


def plans_diff(plans: List[SettingsPlan]) -> List[str]:
    """One unified diff per file the plans touch: its first plan's before against its last plan's after."""
    lines: List[str] = []
    for path in dict.fromkeys(plan.settings_path for plan in plans):
        same_file = [plan for plan in plans if plan.settings_path == path]
        lines.extend(settings_diff(same_file[0].before, same_file[-1].after, str(path)))
    return lines


def _render_settings_plan(plans: List[SettingsPlan]) -> int:
    """Print every planned change, one per line, then the unified diff. Returns the change count."""
    planned = [line for plan in plans for line in plan.planned]
    console.print(f"\n[bold]Planned changes to the provider settings ({len(planned)}):[/bold]")
    for line in planned:
        console.print(f"  • {line}", markup=False, highlight=False)
    for plan in plans:
        for note in plan.notes:
            console.print(f"  {note}", markup=False, highlight=False, style="dim")
    console.print()
    for line in plans_diff(plans):
        console.print(line, markup=False, highlight=False)
    console.print()
    return len(planned)


def _ask_apply(count: int) -> Optional[str]:
    """Ask the one question on a tty. Returns the consent string, or None for n / EOF / Ctrl-C."""
    try:
        answer = input(f"Apply these {count} changes to the provider settings? [y/N]: ").strip().lower()
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

    The install door never asks, ``--yes`` skips the question, no tty without ``--yes`` writes nothing.
    An unreadable or since-changed settings file is a FAIL row and nothing is written.
    """
    try:
        plans = plan_settings_fix(manifest_path)
    except SettingsBackupError as exc:
        logger.error("[doctor] settings plan refused: %s", exc)
        return [SettingsCheckResult(SETTINGS_FIX_LABEL, GLYPH_FAIL, str(exc), "Repair the settings JSON, then re-run")]
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
    try:
        _apply_settings_plans(plans, door, consent)
    except SettingsBackupError as exc:
        logger.error("[doctor] settings write refused: %s", exc)
        return [SettingsCheckResult(SETTINGS_FIX_LABEL, GLYPH_FAIL, str(exc), "Re-run aipass doctor --fix")]
    json_handler.log_operation("settings_fix", {"door": door, "consent": consent, "plans": len(plans)})
    return []


def settings_fix_report(manifest_path: Optional[Path], yes: bool = False) -> dict:
    """The settings plan for ``doctor --fix --json``: written only with ``--yes`` (``applied``)."""
    try:
        plans = plan_settings_fix(manifest_path)
    except SettingsBackupError as exc:
        logger.error("[doctor] settings plan refused: %s", exc)
        return {"planned": [], "notes": [], "diff": [], "applied": False, "error": str(exc)}
    report = {
        "planned": [line for plan in plans for line in plan.planned],
        "notes": [note for plan in plans for note in plan.notes],
        "diff": plans_diff(plans),
        "applied": False,
    }
    if plans and yes:
        _apply_settings_plans(plans, DOOR_DOCTOR_FIX, CONSENT_YES, show=False)
        report["applied"] = True
    json_handler.log_operation("settings_fix_report", {"plans": len(plans), "applied": report["applied"]})
    return report


def _prompt_auto_wire(
    manifest_path: Path,
    missing_hooks: List[str],
    missing_env: List[str],
    missing_deny: List[str],
    missing_ask: List[str],
    missing_settings: List[str] | None = None,
    settings_path: Optional[Path] = None,
) -> bool:
    """Show the planned wire line by line with its diff, ask once, or print the manual warning."""
    missing_settings = missing_settings or []
    logger.warning(
        "[doctor] %d hooks, %d env vars, %d permissions, %d settings missing",
        len(missing_hooks),
        len(missing_env),
        len(missing_deny) + len(missing_ask),
        len(missing_settings),
    )
    try:
        plan = plan_wire_provider(manifest_path, settings_path)
    except SettingsBackupError as exc:
        logger.error("[doctor] auto-wire refused: %s", exc)
        warning(str(exc))
        plan = None
    consent: Optional[str] = None
    if plan is not None and plan.planned:
        count = _render_settings_plan([plan])
        console.print("[dim]Review details: .claude/hooks/README.md[/dim]")
        if not sys.stdin.isatty():
            logger.info("[doctor] non-interactive stdin — auto-wire prompt skipped, treating as decline")
        else:
            consent = _ask_apply(count)

    if plan is not None and consent is not None:
        try:
            for action in apply_settings_plan(plan, consent=consent):
                success(action)
            return True
        except SettingsBackupError as exc:
            logger.error("[doctor] auto-wire write refused: %s", exc)
            warning(str(exc))

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


def handle_command(command: str, args: list[str]) -> bool:
    """Handle command routing. This is a helper module — no standalone commands."""
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
