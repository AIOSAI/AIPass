# =================== AIPass ====================
# Name: rollover_config.py
# Description: The `config` verb surface over rollover limits - get / set / set-default
# Version: 1.3.0
# Created: 2026-09-15
# Modified: 2026-10-17
# =============================================

"""
Rollover Config Verbs (DPLAN-0302)

Display code, so it lives in modules/ (handlers may not print); help text comes from handlers/cli/config_content.py.
rollover.py owns the `config` word and re-exports every name here; this module never imports rollover.
"""

from typing import List

from rich.panel import Panel
from rich import box

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, warning
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.cli.help_flags import wants_help
from aipass.memory.apps.handlers.cli.json_flag import strip_json_flag, wants_json
from aipass.memory.apps.handlers.cli import config_content
from aipass.memory.apps.handlers.monitor import detector

# rollover_json imports nothing from here, so the entry-type tuples live there and come back in.
from aipass.memory.apps.modules.rollover_json import (
    _DISPLAY_TYPES,
    _ENTRY_TYPES,
    _Json,
    _READ_ONLY_TYPES,
    _emit,
    _project_default,
    _project_overrides,
    _project_row,
    _refuse,
)


_CONFIG_SUBCOMMANDS = {
    "get": "Show effective limits — all branches, or one with @branch",
    "set": "Set one branch's limit: set @branch <type> <count>",
    "set-default": "Set a global default limit: set-default <type> <count>",
}

# A limit of 0 rolls over every entry immediately; past 100 rollover is moot.
_MIN_COUNT = 1
_MAX_COUNT = 100

_VERB_CONFIG = "config"
_VERB_CONFIG_GET = "config get"
_VERB_CONFIG_SET = "config set"
_VERB_CONFIG_SET_DEFAULT = "config set-default"


def _handle_config(args: List[str]) -> bool:
    """Route the `config` verb. Always returns True — this module owns the word."""
    if not args:
        print_config_introspection()
        return True

    # A help flag ANYWHERE wins, before --json: asking about `set` must never write.
    if wants_help(args, allow_bare_word=True):
        print_config_help()
        return True

    # --json is removed before positional parsing, whichever slot it rode in.
    json_mode = wants_json(args)
    args = strip_json_flag(args)
    if not args:
        print_config_introspection()
        return True

    sub = args[0]

    if sub == "get":
        handle_config_get(args[1:], _Json(_VERB_CONFIG_GET, json_mode))
        return True

    if sub == "set":
        handle_config_set(args[1:], _Json(_VERB_CONFIG_SET, json_mode))
        return True

    if sub == "set-default":
        handle_config_set_default(args[1:], _Json(_VERB_CONFIG_SET_DEFAULT, json_mode))
        return True

    _refuse(
        _Json(_VERB_CONFIG, json_mode),
        f"Unknown subcommand: '{sub}'",
        suggestion="Available: " + ", ".join(_CONFIG_SUBCOMMANDS),
    )
    return True


def _resolve_branch(raw: str, ctx: _Json) -> str | None:
    """Match *raw* against the registry case-insensitively; the lowercase key, or None after refusing.

    The registry carries uppercase names (BACKUP, DAEMON) while per_branch keys are lowercase.
    """
    name = raw[1:] if raw.startswith("@") else raw

    try:
        branches = detector._read_registry()
    except Exception as exc:
        logger.warning(f"[rollover] Failed to read registry: {exc}")
        _refuse(ctx, f"Failed to read registry: {exc}")
        return None

    known = {str(b.get("name", "")).lower() for b in branches}
    if name.lower() not in known:
        logger.warning(f"[rollover] Unknown branch requested: {name}")
        _refuse(
            ctx,
            f"Unknown branch: @{name}",
            suggestion="Registry is truth — run 'drone systems' to list branches",
        )
        return None

    return name.lower()


def _validate_type(entry_type: str, ctx: _Json) -> bool:
    """Refuse an entry type `config set` cannot write — unknown, or display-only in v1."""
    if entry_type in _ENTRY_TYPES:
        return True

    if entry_type in _READ_ONLY_TYPES:
        _refuse(
            ctx,
            f"'{entry_type}' is display-only in v1: config get shows its count, config set cannot change it",
            suggestion="Settable types: " + ", ".join(_ENTRY_TYPES),
        )
        return False

    _refuse(
        ctx,
        f"Unknown entry type: '{entry_type}'",
        suggestion="Valid types: " + ", ".join(_ENTRY_TYPES),
    )
    return False


def _validate_count(raw: str, entry_type: str, ctx: _Json, branch: str | None = None) -> int | None:
    """Parse and bound-check a limit, emitting its own refusal; None when refused.

    The budget bound depends on co-tenants: local.json's 25,000 chars are shared by three families.
    """
    try:
        count = int(raw)
    except ValueError:
        logger.warning(f"[rollover] Non-numeric count rejected: {raw!r}")
        _refuse(
            ctx,
            f"Count must be a whole number: '{raw}'",
            suggestion="Example: drone @memory config set @devpulse sessions 12",
        )
        return None

    if count < _MIN_COUNT:
        _refuse(
            ctx,
            f"Count must be at least {_MIN_COUNT} (got {count})",
            suggestion="A limit of 0 would roll over every entry immediately",
        )
        return None

    if count > _MAX_COUNT:
        _refuse(
            ctx,
            f"Count must not exceed {_MAX_COUNT} (got {count})",
            suggestion=f"{_MAX_COUNT} is the cap — larger limits defeat rollover entirely",
        )
        return None

    from aipass.memory.apps.handlers.json import config_loader

    over_budget = config_loader.ceiling_refusal(entry_type, count, branch)
    if over_budget is not None:
        logger.warning(f"[rollover] {entry_type} {count} refused: {over_budget['error']}")
        _refuse(ctx, over_budget["error"], suggestion=over_budget["suggestion"])
        return None

    return count


def _show_defaults(defaults: dict) -> None:
    """Print the global default limits block — content built by handlers/cli/config_content."""
    for line in config_content.defaults_lines(defaults, _DISPLAY_TYPES, _READ_ONLY_TYPES):
        console.print(line)


def _show_overrides(overrides: dict) -> None:
    """Print every branch whose effective limits deviate from the defaults."""
    for line in config_content.overrides_lines(overrides, _DISPLAY_TYPES):
        console.print(line)


def _show_branch_limits(branch: str, limits: dict) -> None:
    """Print one branch's EFFECTIVE limits, each marked default-or-override."""
    for line in config_content.branch_limits_lines(branch, limits, _DISPLAY_TYPES, _READ_ONLY_TYPES):
        console.print(line)


def handle_config_get(args: List[str], ctx: _Json) -> None:
    """Show rollover limits — defaults plus deviations, or one branch."""
    from aipass.memory.apps.handlers.json import config_loader

    # Resolve BEFORE the banner: a refusal under a title panel reads as a failed report.
    branch = None
    if args:
        branch = _resolve_branch(args[0], ctx)
        if branch is None:
            return

    if not ctx.on:
        console.print()
        console.print(
            Panel.fit("[bold cyan]Memory - Rollover Limits[/bold cyan]", border_style="cyan", box=box.ROUNDED)
        )
        console.print()

    if branch is not None:
        limits = config_loader.get_effective_limits(branch)
        if ctx.on:
            _emit(
                {
                    "ok": True,
                    "verb": ctx.verb,
                    "branch": branch,
                    "limits": {
                        entry_type: _project_row(
                            limits.get(entry_type, {}), with_cap=True, read_only=entry_type in _READ_ONLY_TYPES
                        )
                        for entry_type in _DISPLAY_TYPES
                    },
                }
            )
        else:
            _show_branch_limits(branch, limits)
        json_handler.log_operation("config_get", {"branch": branch, "json": ctx.on})
        return

    defaults = config_loader.get_default_limits()
    overrides = config_loader.get_branches_with_overrides()

    if ctx.on:
        _emit(
            {
                "ok": True,
                "verb": ctx.verb,
                "defaults": {
                    entry_type: _project_default(defaults.get(entry_type, {}), read_only=entry_type in _READ_ONLY_TYPES)
                    for entry_type in _DISPLAY_TYPES
                },
                "overrides": {name: _project_overrides(limits) for name, limits in overrides.items()},
            }
        )
    else:
        _show_defaults(defaults)
        _show_overrides(overrides)

    json_handler.log_operation("config_get", {"branches_deviating": len(overrides), "json": ctx.on})


def handle_config_set(args: List[str], ctx: _Json) -> None:
    """Write one branch's rollover limit override."""
    from aipass.memory.apps.handlers.json import config_loader

    if len(args) < 3:
        _refuse(
            ctx,
            "config set needs: @branch <type> <count>",
            suggestion="Example: drone @memory config set @devpulse sessions 12",
        )
        return

    branch = _resolve_branch(args[0], ctx)
    if branch is None:
        return

    entry_type = args[1]
    if not _validate_type(entry_type, ctx):
        return

    count = _validate_count(args[2], entry_type, ctx, branch)
    if count is None:
        return

    before = config_loader.load()
    result = config_loader.set_branch_limit(branch, entry_type, count)
    if not result.get("success"):
        _refuse(ctx, result.get("error", "Unknown error"))
        return
    rendered = _rerender(entry_type, before)

    if ctx.on:
        _emit(
            {
                "ok": True,
                "verb": ctx.verb,
                "branch": result["branch"],
                "entry_type": result["entry_type"],
                "count": result["count"],
                "pushed": result["pushed"],
            }
        )
    else:
        console.print()
        console.print(f"[green]>[/green] @{branch} {entry_type} limit set to {count}")
        if rendered:
            console.print(f"[dim]Meta lines re-rendered: {', '.join('@' + name for name in rendered)}[/dim]")
        console.print("[dim]Reset every branch to defaults with: drone @memory rollover push[/dim]")
        console.print()

    json_handler.log_operation(
        "config_set", {"branch": branch, "entry_type": entry_type, "count": count, "json": ctx.on}
    )


def handle_config_set_default(args: List[str], ctx: _Json) -> None:
    """Write one global default rollover limit, leaving per_branch alone."""
    from aipass.memory.apps.handlers.json import config_loader

    if len(args) < 2:
        _refuse(
            ctx,
            "config set-default needs: <type> <count>",
            suggestion="Example: drone @memory config set-default sessions 12",
        )
        return

    entry_type = args[0]
    if not _validate_type(entry_type, ctx):
        return

    count = _validate_count(args[1], entry_type, ctx)
    if count is None:
        return

    before = config_loader.load()
    result = config_loader.set_default_limit(entry_type, count)
    if not result.get("success"):
        _refuse(ctx, result.get("error", "Unknown error"))
        return
    rendered = _rerender(entry_type, before)

    if ctx.on:
        _emit(
            {
                "ok": True,
                "verb": ctx.verb,
                "entry_type": result["entry_type"],
                "count": result["count"],
                "pushed": result["pushed"],
            }
        )
    else:
        console.print()
        console.print(f"[green]>[/green] Default {entry_type} limit set to {count}")
        if rendered:
            console.print(f"[dim]Meta lines re-rendered: {', '.join('@' + name for name in rendered)}[/dim]")
        console.print("[dim]per_branch untouched — apply fleet-wide with: drone @memory rollover push[/dim]")
        console.print()

    json_handler.log_operation("config_set_default", {"entry_type": entry_type, "count": count, "json": ctx.on})


def _rerender(entry_type: str, before: dict) -> List[str]:
    """Re-render the meta lines the write moved (tab_renderer decides whose); each left stale is a warning."""
    from aipass.memory.apps.handlers.json import config_loader
    from aipass.memory.apps.handlers.tracking import tab_renderer

    result = tab_renderer.refresh_moved_limits(entry_type, before, config_loader.load())
    if result is None:
        warning("Meta lines not re-rendered: the registry is unreadable (logs/tab_renderer.log)")
        return []
    for problem in result["errors"]:
        warning(f"Meta line not re-rendered: {problem}")
    return result["branches"]


def print_config_introspection() -> None:
    """Display config-verb introspection — the page under the CLI's name for it.

    The alias, not the body: seedgo reads console.print calls inside print_introspection literally.
    """
    print_introspection()


def print_introspection() -> None:
    """Display module introspection (seedgo standard)."""
    console.print()
    console.print("[bold cyan]config Verb - Rollover Limits[/bold cyan]")
    console.print("Reads and writes the rollover entry-count limits in memory.config.json")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/json/[/cyan]     [dim]config_loader.py[/dim]")
    console.print("  [cyan]handlers/monitor/[/cyan]  [dim]detector.py (registry — branch names)[/dim]")
    console.print()

    console.print("[yellow]Subcommands:[/yellow]")
    for sub, desc in _CONFIG_SUBCOMMANDS.items():
        console.print(f"  [green]{sub:<14}[/green] {desc}")
    console.print()

    console.print("[yellow]Flags:[/yellow]")
    console.print("  [green]--json[/green]         One JSON document on stdout instead of the rendered view")
    console.print()

    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @memory config get[/green]                       [dim]# Defaults + deviations[/dim]")
    console.print("  [green]drone @memory config get @devpulse[/green]             [dim]# One branch[/dim]")
    console.print("  [green]drone @memory config set @devpulse sessions 12[/green] [dim]# Override[/dim]")
    console.print("  [green]drone @memory config get --json[/green]                [dim]# Machine surface[/dim]")
    console.print("  [green]drone @memory config --help[/green]                    [dim]# Full usage guide[/dim]")
    console.print()


def print_config_help() -> None:
    """Display config-verb help — the BOUNDS block reads the LIVE ceilings."""
    from aipass.memory.apps.handlers.json import config_loader

    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]config Verb - Rollover Limit Settings[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    console.print()
    for line in config_content.help_lines(_MIN_COUNT, _MAX_COUNT, config_loader.get_count_ceilings()):
        console.print(line)


def handle_command(command: str, args: list) -> bool:
    """Entry point for drone module discovery — describes the `config` verb, never runs it.

    Running config work here would be a second entry to the verb rollover.py routes: one word, one router.
    """
    if command != "rollover_config":
        return False

    json_handler.log_operation("rollover_config_command", {"args": args})
    logger.debug(f"[rollover_config] introspection requested with args={args}")

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_introspection()
        return True

    error(f"rollover_config: unknown subcommand '{args[0]}' — the verb is 'drone @memory config'")
    print_introspection()
    return True
