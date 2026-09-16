# =================== AIPass ====================
# Name: rollover_config.py
# Description: The `config` verb surface over rollover limits - get / set / set-default
# Version: 1.2.0
# Created: 2026-09-15
# Modified: 2026-09-16
# =============================================

"""
Rollover Config Verbs (DPLAN-0302)

The `config` verb surface over the rollover entry-count limits in
memory.config.json, lifted out of ``modules/rollover.py`` when that module
reached the seedgo length standard. The code here is the code that was there:
the routing, the validation, the rendered views and the introspection and help
pages. The TEXT of the help page and the limit blocks is built by
``handlers/cli/config_content.py``, which returns lines and never prints; this
module prints them. That kept the module under @seedgo's 600-line band without a
bypass, a rename or a fourth split (FPLAN-0593 Phase 5).

WHY IT SITS IN ``modules/`` AND NOT ``handlers/``. This is DISPLAY code - it is
almost nothing but ``console.print``. ``apps/handlers/`` is private
implementation and may not print: @seedgo's ``cli`` standard fails any file
under that tree that calls ``console.print()`` or imports
``aipass.cli.apps.modules``, because a handler is supposed to return data and
let a module render it. There is no rendering-free version of a help page, so
the verbs belong in the public tier that is allowed to speak.

IT DESCRIBES A VERB, IT DOES NOT OWN ONE. ``modules/rollover.py`` keeps owning
the ``config`` word, routes it through ``_handle_config`` here, and re-exports
every name below, because the CLI and the tests reach them through
``rollover.<name>``. The dependency runs one way - this module never imports
``rollover``. The ``handle_command`` at the foot answers only the module's own
name and prints the introspection page: ``apps/memory.py::discover_modules``
duck-types on that function, and ``modules/fleet.py`` records why a modules/
file without one is the wrong answer - three @seedgo standards fail it. It
executes no config work, for the same reason the split happened: one word, one
router.

THE ``--json`` EMITTER IS NEXT DOOR. ``_Json``, ``_emit`` and ``_refuse`` live
in ``modules/rollover_json.py`` and are imported here and re-exported by
``rollover.py``, because both halves of the old module answer through them.
"""

from typing import List

from rich.panel import Panel
from rich import box

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.cli.help_flags import wants_help
from aipass.memory.apps.handlers.cli.json_flag import strip_json_flag, wants_json
from aipass.memory.apps.handlers.cli import config_content
from aipass.memory.apps.handlers.monitor import detector

# The `--json` emitter moved to modules/rollover_json.py when this module reached
# the seedgo length standard. The arrow runs one way — that module imports nothing
# from here, which is why the entry-type tuples moved with it and come back in.
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


# `config` is the verb surface over rollover limits — the rollover module owns
# rollover config, so nothing has to hand-edit memory.config.json (DPLAN-0302).
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

# =============================================================================
# CONFIG VERBS — ROUTING
# =============================================================================


def _handle_config(args: List[str]) -> bool:
    """Route the `config` verb. Always returns True — this module owns the word.

    Args:
        args: Tokens after `config`.

    Returns:
        True — every path either displays, refuses, or writes.
    """
    # No args → introspection (seedgo standard)
    if not args:
        print_config_introspection()
        return True

    # A help flag ANYWHERE wins — asking about `set` must never write.
    # No config subcommand takes free text, so a bare `help` counts too.
    # This is evaluated BEFORE --json: `set ... --help --json` is still a
    # question, so it prints help and writes neither config nor payload.
    if wants_help(args, allow_bare_word=True):
        print_config_help()
        return True

    # Machine output is read and REMOVED before positional parsing, so
    # `set @memory sessions 12 --json` parses identically to the same line
    # without it, whichever slot the flag rode in.
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


# =============================================================================
# CONFIG VERBS — VALIDATION
# =============================================================================


def _resolve_branch(raw: str, ctx: _Json) -> str | None:
    """Match *raw* against the registry, or refuse.

    Registry is truth. Matching is case-INSENSITIVE because the registry
    carries uppercase names (BACKUP, DAEMON) while per_branch keys are
    lowercase; the refusal echoes the branch exactly as the operator typed it.

    Args:
        raw: A `@branch` or bare branch token.
        ctx: Verb name and machine-output mode for the refusal.

    Returns:
        The lowercase branch key, or None when the refusal was emitted.
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
    """Parse and bound-check a limit, emitting its own refusal.

    Three bounds, widening in what each one knows: the count is a whole
    number, it is inside ``_MIN_COUNT``/``_MAX_COUNT``, and the file it grows
    still fits its budget. Only the third depends on the entry type and on
    what its CO-TENANTS hold — a keep-count multiplies an entry cap, and
    local.json's 25,000 chars are shared by three families.

    Args:
        raw: The count token as typed.
        entry_type: The type the count is for — the ceiling is per type.
        ctx: Verb name and machine-output mode for the refusal.
        branch: The branch being written, whose own counts are the co-tenants.
            None for ``set-default``, where the fleet defaults are.

    Returns:
        The count, or None when the refusal was emitted.
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


# =============================================================================
# CONFIG VERBS — GET
# =============================================================================


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
    """Show rollover limits — defaults plus deviations, or one branch.

    Args:
        args: Optional `@branch` (or bare branch name) in the first slot.
        ctx: Verb name and whether to answer as JSON instead of on screen.
    """
    from aipass.memory.apps.handlers.json import config_loader

    # Resolve BEFORE the banner: a refusal that prints a title panel first
    # reads as a report that then failed, rather than a request declined.
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


# =============================================================================
# CONFIG VERBS — SET
# =============================================================================


def handle_config_set(args: List[str], ctx: _Json) -> None:
    """Write one branch's rollover limit override.

    Args:
        args: `@branch <type> <count>`.
        ctx: Verb name and whether to answer as JSON instead of on screen.
    """
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

    result = config_loader.set_branch_limit(branch, entry_type, count)
    if not result.get("success"):
        _refuse(ctx, result.get("error", "Unknown error"))
        return

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
        console.print("[dim]Reset every branch to defaults with: drone @memory rollover push[/dim]")
        console.print()

    json_handler.log_operation(
        "config_set", {"branch": branch, "entry_type": entry_type, "count": count, "json": ctx.on}
    )


def handle_config_set_default(args: List[str], ctx: _Json) -> None:
    """Write one global default rollover limit, leaving per_branch alone.

    Args:
        args: `<type> <count>`.
        ctx: Verb name and whether to answer as JSON instead of on screen.
    """
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

    result = config_loader.set_default_limit(entry_type, count)
    if not result.get("success"):
        _refuse(ctx, result.get("error", "Unknown error"))
        return

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
        console.print("[dim]per_branch untouched — apply fleet-wide with: drone @memory rollover push[/dim]")
        console.print()

    json_handler.log_operation("config_set_default", {"entry_type": entry_type, "count": count, "json": ctx.on})


# =============================================================================
# CONFIG VERBS — INTROSPECTION & HELP
# =============================================================================


def print_config_introspection() -> None:
    """Display config-verb introspection — the page under the CLI's name for it.

    Two names for one page, and the body lives under the OTHER one. @seedgo's
    introspection standard reads the source for ``console.print`` calls inside
    a function literally named ``print_introspection``, so a delegation there
    reads as a module that prints nothing. ``rollover.py`` re-exports this name
    and routes the bare ``config`` verb to it, and the verb's name is part of
    the CLI contract — so this is the alias and that is the body.
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
    """Display config-verb help — the BOUNDS block reads the LIVE ceilings.

    The page's text lives in handlers/cli/config_content.py, which returns it as
    lines and never prints; the panel and the printing stay here, where the cli
    standard allows them (FPLAN-0593 Phase 5).
    """
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

    The verb itself is ``drone @memory config``, owned and routed by
    ``modules/rollover.py``; this module is where its implementation lives
    after the FPLAN-0593 Phase 5 split. Discovery is duck-typed on this
    function, and ``fleet.py`` records the branch convention it settled on:
    a modules/ file that is invisible to discovery fails three @seedgo
    standards, so it is discoverable and answers introspection only.

    Executing config work from here would be a second entry to the same verb,
    which is the drift the split was meant to avoid — one word, one router.
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
