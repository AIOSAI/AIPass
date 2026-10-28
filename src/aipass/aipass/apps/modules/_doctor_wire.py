# =================== AIPass ====================
# Name: _doctor_wire.py
# Description: Auto-wire provider settings from manifest into user config
# Version: 1.6.0
# Created: 2026-05-08
# Modified: 2026-10-28
# =============================================

"""
doctor_wire — auto-wire provider settings
"""

from __future__ import annotations

import json
import shutil
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
    CODEX_PINS,
    codex_config_path,
    codex_hooks_document,
    codex_hooks_path,
    codex_trust_keys,
    install_opencode_plugin,
    manifest_settings,
    opencode_config_dir,
    opencode_plugin_plan,
    opencode_plugin_path,
    opencode_plugin_source,
    opencode_plugin_state,
    plan_codex_hooks,
    plan_wire_provider,
    read_codex_config,
    repo_codex_double_fire,
    settings_diff,
    settings_gaps,
)
from aipass.aipass.apps.handlers.opencode_cli import check_opencode_cli
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
CODEX_TRUST_LABEL = "codex trust"
CODEX_DOUBLE_FIRE_LABEL = "codex double-fire"
TRUST_ALL = "Run `codex` once and choose 'Trust all and continue'"


def check_codex_hooks(manifest: dict, manifest_path: Path) -> List[SettingsCheckResult]:
    """The user-level hooks file, its trust, and a repo file firing the bridge twice. None without rows."""
    rows = _codex_hooks_rows(manifest, manifest_path)
    double = repo_codex_double_fire(manifest_path) if rows else None
    if double is not None:
        detail = f"Codex hooks double-fire: {double} still holds bridge rows"
        rows.append(
            SettingsCheckResult(
                CODEX_DOUBLE_FIRE_LABEL, GLYPH_FAIL, detail, "Remove them by hand: --fix leaves the project's file"
            )
        )
    return rows


def _codex_trust_row(wanted: dict) -> SettingsCheckResult:
    """Does config.toml hold a trusted_hash for every AIPass row of the user-level file?"""
    config, problem = read_codex_config(codex_config_path())
    if problem:
        return SettingsCheckResult(CODEX_TRUST_LABEL, GLYPH_WARN, problem, TRUST_ALL)
    state = config.get("hooks", {}).get("state", {})
    keys = codex_trust_keys(codex_hooks_path(), wanted)
    untrusted = [k for k in keys if "trusted_hash" not in (state.get(k) or {})]
    if untrusted:
        return SettingsCheckResult(
            CODEX_TRUST_LABEL, GLYPH_WARN, f"Codex hooks not trusted ({len(untrusted)} of {len(keys)} rows)", TRUST_ALL
        )
    return SettingsCheckResult(CODEX_TRUST_LABEL, GLYPH_PASS, f"{len(keys)} AIPass rows trusted", "")


def _codex_hooks_rows(manifest: dict, manifest_path: Path) -> List[SettingsCheckResult]:
    """Does the user-level hooks file hold cli.codex's rows first, and are they trusted?"""
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
        return [
            SettingsCheckResult(CODEX_HOOKS_LABEL, GLYPH_PASS, f"{count} Codex hooks match cli.codex", ""),
            _codex_trust_row(wanted),
        ]
    state = "differs from" if plan.before else "missing, wanted by"
    detail = f"{codex_hooks_path()} {state} cli.codex ({count} hooks)"
    return [SettingsCheckResult(CODEX_HOOKS_LABEL, GLYPH_WARN, detail, f"Run: {WIRE_COMMAND}")]


CODEX_BINARY_LABEL = "codex binary"
CODEX_LOGIN_LABEL = "codex login"
CODEX_MODEL_LABEL = "codex model"
CODEX_PINS_LABEL = "codex pins"
OPENCODE_PLUGIN_LABEL = "opencode plugin"
# Seams: the suite's conftest makes codex absent, so no test runs the real binary.
_codex_which = shutil.which
_codex_run = subprocess.run


def check_codex_side(manifest: dict, manifest_path: Path) -> List[SettingsCheckResult]:
    """The codex hooks row, then Codex's binary, login, model and config pins."""
    rows = check_codex_hooks(manifest, manifest_path)
    return rows + check_codex_cli(codex_config_path()) if rows else rows


def _codex_proc(args: List[str]) -> Optional[subprocess.CompletedProcess]:
    """Run one read-only codex verb; None when it could not run at all."""
    try:
        return _codex_run(args, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("[doctor] %s failed: %s", " ".join(args), exc)
        return None


def _first_line(proc: Optional[subprocess.CompletedProcess]) -> str:
    text = "" if proc is None else (proc.stdout or proc.stderr or "").strip()
    return text.splitlines()[0] if text else "no output"


def check_codex_cli(config_path: Path) -> List[SettingsCheckResult]:
    """Codex's binary, login, model and config pins. Read-only: config.toml is the owner's to edit."""
    codex = _codex_which("codex")
    if not codex:
        return [
            SettingsCheckResult(CODEX_BINARY_LABEL, GLYPH_PASS, "not on PATH — Codex is optional, rows skipped", "")
        ]
    version = _codex_proc([codex, "--version"])
    if version is None or version.returncode != 0:
        rows = [SettingsCheckResult(CODEX_BINARY_LABEL, GLYPH_WARN, f"{codex}: --version failed", "Reinstall Codex")]
    else:
        rows = [SettingsCheckResult(CODEX_BINARY_LABEL, GLYPH_PASS, _first_line(version), "")]
    login = _codex_proc([codex, "login", "status"])
    if login is not None and login.returncode == 0:
        rows.append(SettingsCheckResult(CODEX_LOGIN_LABEL, GLYPH_PASS, _first_line(login), ""))
    else:
        rows.append(SettingsCheckResult(CODEX_LOGIN_LABEL, GLYPH_WARN, _first_line(login), "Run: codex login"))
    config, problem = read_codex_config(config_path)
    rows.append(_codex_model_row(codex, config, problem, config_path))
    rows.extend(_codex_pin_rows(config, problem, config_path))
    return rows


def _codex_model_row(codex: str, config: dict, problem: str, path: Path) -> SettingsCheckResult:
    """Is the configured model in the catalog `codex debug models` fetches for this login?"""
    if problem:
        return SettingsCheckResult(CODEX_MODEL_LABEL, GLYPH_WARN, problem, "")
    model = config.get("model")
    if not model:
        return SettingsCheckResult(CODEX_MODEL_LABEL, GLYPH_PASS, "none set — Codex's default", "")
    proc = _codex_proc([codex, "debug", "models"])
    try:
        catalog = json.loads(proc.stdout)["models"] if proc is not None and proc.returncode == 0 else None
        slugs = {m["slug"]: m.get("visibility") for m in catalog} if catalog is not None else None
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("[doctor] codex model catalog unreadable: %s", exc)
        slugs = None
    if slugs is None:
        return SettingsCheckResult(CODEX_MODEL_LABEL, GLYPH_WARN, f"{model}: model catalog unreadable", "")
    if model in slugs:
        return SettingsCheckResult(CODEX_MODEL_LABEL, GLYPH_PASS, f"{model} in this login's catalog", "")
    listed = ", ".join(slug for slug, shown in slugs.items() if shown == "list")
    fix = f"Set model in {path} by hand to one of: {listed}"
    return SettingsCheckResult(CODEX_MODEL_LABEL, GLYPH_WARN, f"{model} not in this login's catalog", fix)


def _codex_pin_rows(config: dict, problem: str, path: Path) -> List[SettingsCheckResult]:
    """One PASS row when every pin reads false; else one WARN per pin, its fix the line to add by hand."""
    if problem:
        return [SettingsCheckResult(CODEX_PINS_LABEL, GLYPH_WARN, problem, "")]
    rows = []
    for keys, table in CODEX_PINS:
        value: Any = config
        for key in keys:
            value = value.get(key) if isinstance(value, dict) else None
        if value is False:
            continue
        name = ".".join(keys)
        detail = f"{name} missing" if value is None else f"{name} is {json.dumps(value)}"
        where = f"under {table}" if table else "above the first [table]"
        rows.append(
            SettingsCheckResult(CODEX_PINS_LABEL, GLYPH_WARN, detail, f"Add to {path} {where}: {keys[-1]} = false")
        )
    return rows or [SettingsCheckResult(CODEX_PINS_LABEL, GLYPH_PASS, f"{len(CODEX_PINS)} config pins set", "")]


def check_provider_sides(manifest: dict, manifest_path: Path) -> List[SettingsCheckResult]:
    """Doctor's per-CLI rows after the Claude ones: Codex's, then OpenCode's."""
    return check_codex_side(manifest, manifest_path) + check_opencode_side(manifest_path)


def check_opencode_side(manifest_path: Path) -> List[SettingsCheckResult]:
    """The opencode plugin row, then OpenCode's binary, login and model. None without cli.opencode rows."""
    state = opencode_plugin_state(manifest_path)
    if state is None:
        return []
    plugin = opencode_plugin_path()
    if state == STATE_SET:
        row = SettingsCheckResult(OPENCODE_PLUGIN_LABEL, GLYPH_PASS, f"{plugin} matches the hooks branch copy", "")
    else:
        what = "missing" if state == STATE_MISSING else "stale (differs from the hooks branch copy)"
        cure = f"Run: {WIRE_COMMAND} (or cp {opencode_plugin_source(manifest_path)} {plugin})"
        row = SettingsCheckResult(OPENCODE_PLUGIN_LABEL, GLYPH_WARN, f"OpenCode plugin {what}: {plugin}", cure)
    return [row, *(SettingsCheckResult(*r) for r in check_opencode_cli(opencode_config_dir()))]


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


def _render_settings_plan(plans: List[SettingsPlan], extra: Optional[List[str]] = None) -> int:
    """Print every planned change, one per line, then the unified diff. Returns the change count."""
    planned = [line for plan in plans for line in plan.planned] + (extra or [])
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


def _apply_settings_plans(
    plans: List[SettingsPlan], door: str, consent: str, show: bool = True, manifest_path: Optional[Path] = None
) -> None:
    """Write each plan through its backed-up door (the wire plan takes *door*), then the OpenCode plugin."""
    for plan in plans:
        actions = apply_settings_plan(plan, door if plan.door == DOOR_DOCTOR_FIX else None, consent)
        for action in actions if show else []:
            success(action)
    plugin = install_opencode_plugin(manifest_path, door, consent) if manifest_path is not None else []
    for action in plugin if show else []:
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
    plugin = opencode_plugin_plan(manifest_path)
    if not plans and not plugin:
        return []
    if door == DOOR_INSTALL:
        consent: Optional[str] = CONSENT_INSTALL
    elif yes:
        consent = CONSENT_YES
    else:
        count = _render_settings_plan(plans, plugin)
        if not sys.stdin.isatty():
            logger.info("[doctor] --fix with no tty and no --yes — settings plan shown, nothing written")
            return [SettingsCheckResult(SETTINGS_FIX_LABEL, GLYPH_WARN, NOT_APPLIED_NO_TTY, YES_COMMAND)]
        consent = _ask_apply(count)
        if consent is None:
            _print_manual_wire_warning([], [], [], [], [])
            console.print(NOTHING_CHANGED)
            return [SettingsCheckResult(SETTINGS_FIX_LABEL, GLYPH_WARN, NOT_APPLIED_DECLINED, YES_COMMAND)]
    try:
        _apply_settings_plans(plans, door, consent, manifest_path=manifest_path)
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
    plugin = opencode_plugin_plan(manifest_path)
    report = {
        "planned": [line for plan in plans for line in plan.planned] + plugin,
        "notes": [note for plan in plans for note in plan.notes],
        "diff": plans_diff(plans),
        "applied": False,
    }
    if (plans or plugin) and yes:
        _apply_settings_plans(plans, DOOR_DOCTOR_FIX, CONSENT_YES, show=False, manifest_path=manifest_path)
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
