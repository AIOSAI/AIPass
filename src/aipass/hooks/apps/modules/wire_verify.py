# =================== AIPass ====================
# Name: wire_verify.py
# Version: 1.0.1
# Description: Wire verification — cross-checks provider settings vs project hook config
# Branch: hooks
# Layer: apps/modules
# Created: 2026-07-09
# Modified: 2026-08-02
# =============================================

"""Wire verification — catches silent hook-wiring breaks.

Cross-checks ~/.claude/settings.json (provider hooks) against
.aipass/hooks.json (project hook config). Detects:
  - Empty provider hook arrays (event key exists but nothing fires)
  - Enabled handlers with no provider bridge entry (handler never dispatched)
  - Duplicate provider entries (handler fires multiple times)
  - Orphaned provider entries (bridge entry with no project config handler)

Invoked via: drone @hooks verify
"""

import json
import sys
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.hooks.apps.handlers.config.loader import config_unavailable_reason, find_project_config
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

HELP_COMMANDS = [
    ("verify", "Cross-check provider settings vs project hook config"),
]

_BRIDGE_MARKER = "bridges/claude.py"
_META_KEYS = frozenset({"_comment", "hooks_enabled"})


def _read_provider_hooks(path=None):
    """Read hook events from provider settings. Returns {event: [entries]}."""
    settings_path = Path(path) if path else Path.home() / ".claude" / "settings.json"
    try:
        raw = settings_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data.get("hooks", {})
    except (OSError, json.JSONDecodeError) as exc:
        logger.info("[WIRE_VERIFY] cannot read provider settings: %s", exc)
        return {}


def _extract_bridge_arg(entry):
    """Extract the bridge event arg from a provider entry's command string.

    Returns e.g. 'UserPromptSubmit:tier0_kernel' or 'Stop', or None if not a bridge entry.
    """
    for hook in entry.get("hooks", []):
        cmd = hook.get("command", "")
        if _BRIDGE_MARKER not in cmd:
            continue
        parts = cmd.split()
        for i, part in enumerate(parts):
            if part.endswith("claude.py") or _BRIDGE_MARKER in part:
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


def _check_event_wiring(event_type, hooks_group, pidx, errors, warnings, info):
    """Check one project config event against its provider index entry."""
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


def verify_wiring(provider_path=None, project_config=None):
    """Cross-check provider settings against project hook config.

    Returns dict with keys: errors (list), warnings (list), info (list), ok (bool).
    """
    errors = []
    warnings = []
    info = []

    provider_hooks = _read_provider_hooks(provider_path)
    if not provider_hooks:
        errors.append("No provider hooks found in ~/.claude/settings.json")
        return {"errors": errors, "warnings": warnings, "info": info, "ok": False}

    config = project_config if project_config is not None else find_project_config()
    if config is None:
        errors.append(config_unavailable_reason())
        return {"errors": errors, "warnings": warnings, "info": info, "ok": False}

    provider_index = _build_provider_index(provider_hooks, errors)

    for event_type, hooks_group in config.items():
        if event_type in _META_KEYS or not isinstance(hooks_group, dict):
            continue
        pidx = provider_index.get(event_type)
        _check_event_wiring(event_type, hooks_group, pidx, errors, warnings, info)

    for event in provider_hooks:
        if event not in config and not provider_index.get(event, {}).get("empty"):
            info.append(f"{event}: provider-only event (no project config section)")

    return {
        "errors": errors,
        "warnings": warnings,
        "info": info,
        "ok": len(errors) == 0,
    }


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
        results = verify_wiring()
        _render_results(results)
        if not results["ok"]:
            # The --help below promises this. Returning True routes as "handled",
            # which hooks.main() turns into exit 0 — a wiring break would print
            # FAILED and still report success to anything reading the exit code.
            sys.exit(1)
        return True

    if wants_help(args):
        CONSOLE.print("[bold cyan]wire_verify[/bold cyan] — Provider ↔ project hook wiring checker")
        CONSOLE.print()
        CONSOLE.print("  drone @hooks verify     Cross-check provider settings vs project config")
        CONSOLE.print()
        CONSOLE.print("Reads ~/.claude/settings.json and .aipass/hooks.json,")
        CONSOLE.print("verifies every enabled handler has a working provider bridge entry.")
        CONSOLE.print("Exits non-zero on any ERROR finding.")
        return True

    return False
