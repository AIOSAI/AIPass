# =================== AIPass ====================
# Name: wire_verify.py
# Version: 1.5.0
# Description: Wire verification — cross-checks provider settings vs project hook config
# Branch: hooks
# Layer: apps/modules
# Created: 2026-07-09
# Modified: 2026-10-28
# =============================================

"""Wire verification — catches silent hook-wiring breaks.

Cross-checks ~/.claude/settings.json (provider hooks) against .aipass/hooks.json (project hook config).
A handler wired only in Codex's user-level hooks.json, or only in the manifest's cli.opencode rows that
OpenCode's plugin runs, counts as wired; that file or plugin missing (or the plugin stale) is an ERROR.
Detects: empty provider hook arrays; enabled handlers with no bridge entry; duplicate and orphaned
entries; a tool a gate guards that the provider's PreToolUse bridge never sees (R7: NotebookEdit).
Invoked via: drone @hooks verify
"""

import json
import re
import sys
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.hooks.apps.handlers.config import gates
from aipass.hooks.apps.handlers.config.opencode_paths import opencode_plugin_path
from aipass.hooks.apps.handlers.config.loader import aipass_home, config_unavailable_reason, find_project_config
from aipass.hooks.apps.modules.context_window import codex_hooks_path
from aipass.hooks.apps.handlers.json import files as json_files
from aipass.hooks.apps.handlers.module_root import module_file
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

HELP_COMMANDS = [
    ("verify", "Cross-check provider settings vs project hook config"),
]

_BRIDGE_MARKER = "bridges/claude.py"
_CODEX_MARKER = "bridges/codex.py"
_OPENCODE_MARKER = "bridges/opencode.py"
OPENCODE_PLUGIN_SOURCE = module_file(__file__).parents[1] / "handlers" / "bridges" / "opencode_plugin.ts"
_META_KEYS = frozenset({"_comment", "hooks_enabled"})


def _read_provider_hooks(path=None):
    """Read hook events from provider settings. Returns {event: [entries]}."""
    settings_path = Path(path) if path else Path.home() / ".claude" / "settings.json"
    try:
        data = json_files.read_json_file(settings_path)
        return data.get("hooks", {})
    except (OSError, json.JSONDecodeError) as exc:
        logger.info("[WIRE_VERIFY] cannot read provider settings: %s", exc)
        return {}


def _extract_bridge_arg(entry, marker=_BRIDGE_MARKER):
    """Extract the bridge event arg from a provider entry's command string.

    Returns e.g. 'UserPromptSubmit:tier0_kernel' or 'Stop', or None if not a bridge entry.
    """
    for hook in entry.get("hooks", []):
        cmd = hook.get("command", "")
        if marker not in cmd:
            continue
        parts = cmd.split()
        for i, part in enumerate(parts):
            if part.endswith(marker.rsplit("/", 1)[-1]) or marker in part:
                if i + 1 < len(parts):
                    return parts[i + 1]
    return None


def _build_provider_index(provider_hooks, errors):
    """Parse provider hook entries into a lookup index.

    Returns {event: {"filtered": {hook_name: {matcher: count}}, "unfiltered": int, "empty": bool}}.
    Appends to *errors* for empty arrays.
    """
    index = {}
    for event, entries in provider_hooks.items():
        idx = {"filtered": {}, "unfiltered": 0, "empty": False}
        if not entries:
            errors.append(f"{event}: provider entry exists but hooks array is EMPTY — nothing fires")
            idx["empty"] = True
        for entry in entries:
            arg = _extract_bridge_arg(entry)
            if arg is None:
                continue
            if ":" in arg:
                hook_name = arg.split(":", 1)[1]
                matcher = entry.get("matcher", "")
                if hook_name not in idx["filtered"]:
                    idx["filtered"][hook_name] = {}
                idx["filtered"][hook_name][matcher] = idx["filtered"][hook_name].get(matcher, 0) + 1
            else:
                idx["unfiltered"] += 1
        index[event] = idx
    return index


def _codex_wired(codex_path, errors) -> frozenset[str]:
    """Every ``Event:hook`` a Codex hooks.json sends through the Codex bridge; none when there is no file.

    A *codex_path* naming no file is an ERROR, and so is a guarded tool its PreToolUse rows miss.
    """
    if codex_path is None:
        return frozenset()
    if not Path(codex_path).is_file():
        errors.append(
            f"Codex hooks file missing: {codex_path}, so a Codex seat runs ungated. "
            "Fix: aipass doctor --fix, then run codex once and choose 'Trust all and continue'"
        )
        return frozenset()
    codex_hooks = _read_provider_hooks(codex_path)
    _check_guarded_tools(codex_hooks, errors, _CODEX_MARKER, _CODEX_GUARDED_TOOLS, " (Codex)")
    wired: set[str] = set()
    for entries in codex_hooks.values():
        for entry in entries:
            arg = _extract_bridge_arg(entry, _CODEX_MARKER)
            if arg:
                wired.add(arg)
    return frozenset(wired)


def _manifest_path() -> Path | None:
    home = aipass_home()
    return home / ".claude" / "provider_manifest.json" if home is not None else None


def _opencode_wired(plugin, manifest, errors) -> frozenset[str]:
    """Every ``Event:hook`` the manifest's cli.opencode rows send through the OpenCode bridge.

    The plugin missing or stale, or no rows, is an ERROR: the plugin then refuses every tool.
    """
    plugin = Path(plugin)
    cure = f"Fix: cp {OPENCODE_PLUGIN_SOURCE} {plugin}"
    if not plugin.is_file():
        errors.append(f"OpenCode plugin missing: {plugin}, so an OpenCode seat runs ungated. {cure}")
    elif plugin.read_bytes() != OPENCODE_PLUGIN_SOURCE.read_bytes():
        errors.append(f"OpenCode plugin stale: {plugin} differs from the branch copy. {cure}")
    try:
        data = json_files.read_json_file(Path(manifest)) if manifest is not None else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.info("[WIRE_VERIFY] cannot read the provider manifest: %s", exc)
        data = {}
    opencode = data.get("cli", {}).get("opencode", {}) if isinstance(data, dict) else {}
    rows = [row for row in opencode.get("hooks", []) if isinstance(row, dict)] if isinstance(opencode, dict) else []
    args = (_extract_bridge_arg({"hooks": [row]}, _OPENCODE_MARKER) for row in rows)
    wired = {arg for arg in args if arg}
    if not wired:
        errors.append(f"No cli.opencode rows in {manifest}: the OpenCode plugin refuses every tool until they land")
    return frozenset(wired)


def _check_event_wiring(event_type, hooks_group, pidx, errors, warnings, info, elsewhere=None):
    """Check one project config event against its provider index entry; *elsewhere* maps a CLI to its wired set."""
    enabled_hooks = {
        name: defn for name, defn in hooks_group.items() if isinstance(defn, dict) and defn.get("enabled", False)
    }
    if not enabled_hooks:
        return

    if pidx is None:
        if enabled_hooks:
            errors.append(
                f"{event_type}: {len(enabled_hooks)} enabled handler(s) in project config"
                f" but NO provider event entry — handlers never fire"
            )
        return

    if pidx["empty"]:
        return

    filtered = pidx["filtered"]
    if pidx["unfiltered"] > 0:
        if pidx["unfiltered"] > 1:
            warnings.append(f"{event_type}: {pidx['unfiltered']} duplicate unfiltered provider entries")
        info.append(f"{event_type}: unfiltered bridge, {len(enabled_hooks)} enabled hooks OK")
    else:
        for hook_name, hook_defn in enabled_hooks.items():
            if hook_name not in filtered:
                found = [cli for cli, wired in (elsewhere or {}).items() if f"{event_type}:{hook_name}" in wired]
                if found:
                    info.append(f"{event_type}:{hook_name}: wired for {' and '.join(found)} only")
                    continue
                errors.append(
                    f"{event_type}:{hook_name}: enabled in project config"
                    " but no provider bridge entry — handler never fires"
                )
                continue
            for matcher, count in filtered[hook_name].items():
                if count > 1:
                    warnings.append(
                        f"{event_type}:{hook_name}: {count} duplicate provider entries (matcher={matcher or 'none'})"
                    )

    for hook_name in filtered:
        if hook_name not in hooks_group:
            warnings.append(
                f"{event_type}:{hook_name}: provider entry exists but no handler in project config (orphaned)"
            )


def _matcher_reaches(matcher: str, tool: str) -> bool:
    """True when a provider matcher sends *tool* to the bridge: empty or ``*`` is every tool, else a regex."""
    if matcher in ("", "*"):
        return True
    try:
        return re.fullmatch(matcher, tool) is not None
    except re.error as exc:  # a matcher the provider cannot compile reaches nothing
        logger.info("[WIRE_VERIFY] unreadable PreToolUse matcher %r: %s", matcher, exc)
        return False


#: Codex sends a shell call as Bash and every file edit as apply_patch; the bridge splits the patch for the gates.
_CODEX_GUARDED_TOOLS = frozenset({"Bash", "apply_patch"})


def _check_guarded_tools(provider_hooks, errors, marker=_BRIDGE_MARKER, tools=None, side=""):
    """ERROR for every tool a gate guards that no PreToolUse bridge entry sends to the engine (R7)."""
    matchers = [
        entry.get("matcher", "")
        for entry in provider_hooks.get("PreToolUse", [])
        if _extract_bridge_arg(entry, marker) == "PreToolUse"
    ]
    for tool in sorted(gates.guarded_tools() if tools is None else tools):
        if not any(_matcher_reaches(matcher, tool) for matcher in matchers):
            errors.append(
                f"PreToolUse{side}: {tool} is guarded by the gates but no provider bridge matcher reaches it"
                " — its gates never run (add it to the manifest's PreToolUse matcher)"
            )


def verify_wiring(provider_path=None, project_config=None, codex_path=None, opencode_plugin=None, manifest_path=None):
    """Cross-check provider settings against project hook config; *codex_path* is Codex's user-level hooks.json.

    A *codex_path* that names no file is an ERROR: a Codex seat with no hooks file runs ungated.
    *opencode_plugin* is OpenCode's installed plugin, run on *manifest_path*'s cli.opencode rows.

    Returns dict with keys: errors (list), warnings (list), info (list), ok (bool).
    """
    errors, warnings, info = [], [], []
    provider_hooks = _read_provider_hooks(provider_path)
    if not provider_hooks:
        errors.append("No provider hooks found in ~/.claude/settings.json")
        return {"errors": errors, "warnings": warnings, "info": info, "ok": False}

    config = project_config if project_config is not None else find_project_config()
    if config is None:
        errors.append(config_unavailable_reason())
        return {"errors": errors, "warnings": warnings, "info": info, "ok": False}

    provider_index = _build_provider_index(provider_hooks, errors)
    _check_guarded_tools(provider_hooks, errors)
    elsewhere = {"Codex": _codex_wired(codex_path, errors)}
    if opencode_plugin is not None:
        elsewhere["OpenCode"] = _opencode_wired(opencode_plugin, manifest_path, errors)

    for event_type, hooks_group in config.items():
        if event_type in _META_KEYS or not isinstance(hooks_group, dict):
            continue
        pidx = provider_index.get(event_type)
        _check_event_wiring(event_type, hooks_group, pidx, errors, warnings, info, elsewhere)

    for event in provider_hooks:
        if event not in config and not provider_index.get(event, {}).get("empty"):
            info.append(f"{event}: provider-only event (no project config section)")

    return {"errors": errors, "warnings": warnings, "info": info, "ok": len(errors) == 0}


def _render_results(results):
    """Render verification results to console."""
    CONSOLE.print()

    if results["ok"]:
        CONSOLE.print("[bold green]✓ Wire check passed[/bold green]")
    else:
        CONSOLE.print("[bold red]✗ Wire check FAILED[/bold red]")

    CONSOLE.print()

    for error in results["errors"]:
        CONSOLE.print(f"  [red]ERROR[/red]  {error}")

    for warning in results["warnings"]:
        CONSOLE.print(f"  [yellow]WARN[/yellow]   {warning}")

    for item in results["info"]:
        CONSOLE.print(f"  [dim]OK[/dim]     {item}")

    CONSOLE.print()
    CONSOLE.print(f"[bold]{len(results['errors'])} errors, {len(results['warnings'])} warnings[/bold]")


def print_introspection():
    """Print module structure for drone routing."""
    CONSOLE.print("[bold cyan]wire_verify[/bold cyan] — Provider ↔ project hook wiring checker")


def handle_command(command, args) -> bool:
    """Route verify commands from drone @hooks."""
    if command != "verify":
        return False

    if not args:
        print_introspection()
        results = verify_wiring(
            codex_path=codex_hooks_path(), opencode_plugin=opencode_plugin_path(), manifest_path=_manifest_path()
        )
        _render_results(results)
        if not results["ok"]:
            # Returning True would become exit 0: a wiring break must fail anything reading the exit code.
            sys.exit(1)
        return True

    if wants_help(args):
        CONSOLE.print("[bold cyan]wire_verify[/bold cyan] — Provider ↔ project hook wiring checker")
        CONSOLE.print()
        CONSOLE.print("  drone @hooks verify     Cross-check provider settings vs project config")
        CONSOLE.print()
        CONSOLE.print("Reads ~/.claude/settings.json, .aipass/hooks.json and Codex's user-level hooks.json")
        CONSOLE.print("($CODEX_HOME, else ~/.codex) and OpenCode's plugin with the manifest's cli.opencode rows;")
        CONSOLE.print("a missing Codex file or OpenCode plugin is an ERROR. It")
        CONSOLE.print("verifies every enabled handler has a working provider bridge entry.")
        CONSOLE.print("Exits non-zero on any ERROR finding.")
        return True

    return False
