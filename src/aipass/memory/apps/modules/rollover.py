# =================== AIPass ====================
# Name: rollover.py
# Description: Rollover Orchestration Module
# Version: 0.6.0
# Created: 2025-11-16
# Modified: 2026-03-15
# =============================================

"""
Rollover Orchestration Module

Coordinates the memory rollover workflow by calling handlers in sequence:
1. Detect rollover triggers (monitor/detector)
2. Extract oldest memories (rollover/extractor)
3. Generate embeddings (vector/embedder)
4. Store in Chroma (storage/chroma)

Purpose:
    Thin orchestration layer - no business logic implementation.
    All domain logic lives in handlers.
"""

import json
import os
import sys
from pathlib import Path
from typing import List, NamedTuple

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from rich.panel import Panel
from rich import box

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, warning
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.cli.help_flags import wants_help
from aipass.memory.apps.handlers.cli.json_flag import strip_json_flag, wants_json

# =============================================================================
# INFRASTRUCTURE SETUP
# =============================================================================

# Handler imports
from aipass.memory.apps.handlers.monitor import detector
from aipass.memory.apps.handlers.rollover.orchestrator import (
    execute_rollover as _handler_execute_rollover,
    sync_line_counts as _handler_sync_line_counts,
)


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

_SUBCOMMANDS = {
    "run": "Execute rollover for files exceeding limits",
    "status": "Show rollover statistics for all branches",
    "check": "Check which files need rollover (dry run)",
    "report-lines": "Report physical line counts per memory file (read-only)",
    "push": "Overwrite all per_branch limits to defaults (system-wide reset)",
}

# Public alias — the introspection surface and the tests read this name.
SUBCOMMANDS = _SUBCOMMANDS

# `sync-lines` stopped writing anything when the health stamp was deleted from
# the standard on 2026-08-25: its one write was a `status.last_health_check`
# date, and the line count it "synced" was computed, returned and dropped. The
# name outlived the behaviour, which is the exact species of lie DPLAN-0318
# exists to kill — so the verb is renamed, not quietly left alone.
#
# The old name still ROUTES rather than 404-ing. A removed verb tells a caller
# nothing about what replaced it; this one answers, does the same read-only
# work, and says what changed. It also no longer triggers the unscoped
# fleet-wide `refresh_all_tabs()` it used to run on the tail — a reporter that
# rewrites 22 branches' files is the same lie in the other direction.
RENAMED_VERBS = {"sync-lines": "report-lines"}

# `config` is the verb surface over rollover limits — the rollover module owns
# rollover config, so nothing has to hand-edit memory.config.json (DPLAN-0302).
_CONFIG_SUBCOMMANDS = {
    "get": "Show effective limits — all branches, or one with @branch",
    "set": "Set one branch's limit: set @branch <type> <count>",
    "set-default": "Set a global default limit: set-default <type> <count>",
}

# The only three entry types that map onto a rollover limit. Display order.
_ENTRY_TYPES = ("sessions", "key_learnings", "observations")

# A limit of 0 rolls over every entry immediately; past 100 rollover is moot.
_MIN_COUNT = 1
_MAX_COUNT = 100

# Verb names as they appear in the `verb` field of every JSON payload. One
# constant per name so the payload and the routing cannot drift apart.
_VERB_CONFIG = "config"
_VERB_CONFIG_GET = "config get"
_VERB_CONFIG_SET = "config set"
_VERB_CONFIG_SET_DEFAULT = "config set-default"
_VERB_ROLLOVER = "rollover"
_VERB_ROLLOVER_PUSH = "rollover push"


def _handle_rollover_verb(args: List[str]) -> bool:
    """Route the `rollover` subcommands. Always returns True — the verb is ours.

    Split out of `handle_command` so each router stays one level deep: the
    combined version nested subcommand dispatch inside command dispatch, and
    a reader had to hold both to answer "what does `rollover push` do?".
    """
    # No args → introspection (seedgo standard)
    if not args:
        print_introspection()
        return True

    # A help flag ANYWHERE wins — asking about `push` must never push.
    # No rollover subcommand takes free text, so a bare `help` counts too.
    if wants_help(args, allow_bare_word=True):
        print_help()
        return True

    # Machine output is read and REMOVED before positional parsing, so a
    # flag in any slot leaves the subcommand where the parser expects it.
    json_mode = wants_json(args)
    args = strip_json_flag(args)
    if not args:
        print_introspection()
        return True

    sub = args[0]

    if sub == "run":
        run_rollover()
        return True

    if sub == "status":
        show_status()
        return True

    if sub == "check":
        check_triggers()
        return True

    if sub in RENAMED_VERBS:
        _announce_rename(sub)
        report_line_counts()
        return True

    if sub == "report-lines":
        report_line_counts()
        return True

    if sub == "push":
        push_defaults(json_mode)
        return True

    _refuse(
        _Json(_VERB_ROLLOVER, json_mode),
        f"Unknown subcommand: '{sub}'",
        suggestion="Available: " + ", ".join(_SUBCOMMANDS.keys()),
    )
    return True


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle rollover commands with seedgo-compliant introspection.

    Routing:
        rollover (no args)        -> print_introspection()
        rollover --help/-h/help   -> print_help()
        rollover run              -> execute rollover
        rollover status           -> show rollover status
        rollover check            -> dry-run check
        rollover report-lines     -> report line counts (read-only)
        rollover push [--json]    -> reset every per_branch entry

    Rollover-limit config verbs (top-level command, routed from entry point):
        config                    -> print_config_introspection()
        config --help/-h/help     -> print_config_help()
        config get [@branch]      -> show effective limits
        config set @b <type> <n>  -> write one per-branch override
        config set-default <t> <n>-> write one global default

    `--json` rides in any slot on the config verbs and on `rollover push`,
    and is stripped before positional parsing. A help flag still outranks
    it — `config set @b sessions 25 --help --json` prints help and writes
    neither the config nor a payload.

    Backward-compatible top-level commands (routed from entry point):
        status, check, report-lines -> forwarded directly

    Args:
        command: Command name
        args: Additional arguments

    Returns:
        True if command handled, False otherwise
    """
    # Top-level help (backward compat — entry point may send these)
    if command in ("--help", "-h", "help"):
        print_help()
        return True

    if command == "config":
        return _handle_config(args)

    if command == "rollover":
        # The no-args gate stays HERE, at the entry seam, even though the verb
        # handler gates again after the flags are stripped. They answer two
        # different questions — "no subcommand was typed" versus "the only
        # arguments were flags" — and a reader (or a checker) looking at the
        # entry point should not have to follow a delegation to learn that a
        # bare `rollover` introspects.
        if not args:
            print_introspection()
            return True
        return _handle_rollover_verb(args)

    # Backward-compatible top-level commands (entry point still routes these).
    # Flat `if`/return, never an elif chain: each arm is independent, and a
    # chain of six nests six deep for a reader and for the nesting checker.
    if command == "status":
        show_status()
        return True

    if command == "check":
        check_triggers()
        return True

    if command in RENAMED_VERBS:
        _announce_rename(command)
        report_line_counts()
        return True

    if command == "report-lines":
        report_line_counts()
        return True

    if command == "process-plans":
        process_plans_command()
        return True

    return False


def print_help() -> None:
    """Display rollover module help"""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]Rollover Module - Memory Rollover Orchestration[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    console.print()
    console.print("[bold]USAGE:[/bold]")
    console.print("  drone @memory rollover <command>")
    console.print()
    console.print("[bold]COMMANDS:[/bold]")
    console.print("  [cyan]rollover[/cyan]    Execute rollover for files exceeding limits")
    console.print("  [cyan]status[/cyan]      Show rollover statistics for all branches")
    console.print("  [cyan]check[/cyan]       Check which files need rollover (dry run)")
    console.print("  [cyan]report-lines[/cyan] Report line counts per memory file (read-only)")
    console.print("  [cyan]push[/cyan]        Reset ALL per_branch limits to defaults (system-wide, use with caution)")
    console.print("  [cyan]help[/cyan]        Show this help message")
    console.print()
    console.print("[bold]FLAGS:[/bold]")
    console.print("  [cyan]--json[/cyan]      Machine output for [cyan]push[/cyan] — one JSON document, no Rich")
    console.print('              {"ok": true, "verb": "rollover push", "branches": 17}')
    console.print("              Rides in any slot. A help flag still outranks it.")
    console.print()
    console.print("[bold]LIMITS:[/bold]")
    console.print("  v2 entry-count based (sessions, key_learnings, observations) from config")
    console.print()
    console.print("[bold]WORKFLOW:[/bold]")
    console.print("  1. Detect files exceeding v2 entry-count limits")
    console.print("  2. Extract oldest entries")
    console.print("  3. Generate embeddings via fastembed")
    console.print("  4. Store vectors in local + global ChromaDB")
    console.print()


# =============================================================================
# MACHINE OUTPUT — THE --json SURFACE
# =============================================================================


class _Json(NamedTuple):
    """Where one verb's answer goes, and the name it stamps on it.

    Attributes:
        verb: The published verb name carried in every payload.
        on: True for machine output; False leaves every human rendering
            exactly as it was.
    """

    verb: str
    on: bool


def _emit(payload: dict) -> None:
    """Write EXACTLY one JSON document to stdout.

    Routed through the shared console like every other line this branch
    prints, but with Rich's three text behaviours turned OFF — they each
    corrupt a machine payload:

    - ``soft_wrap=True``: the console is width-80 with ``is_terminal=False``,
      so by default it hard-wraps a long payload onto two lines, and a wrap
      landing inside a string value inserts a newline INTO the value.
    - ``markup=False``: a ``[...]`` token inside a string is otherwise eaten
      as a style name (how @daemon's lowercase ``[skip]`` markers vanished
      from the screen while tests on the returned string stayed green).
    - ``highlight=False``: the repr highlighter would inject ANSI styling the
      moment this ran attached to a terminal.

    All three corruptions are invisible to a test that asserts on the string
    handed to the printer rather than on what reached the pipe — which is
    exactly how they survive. The tests here read the pipe.

    ``ensure_ascii`` stays at its default, unlike ``_write_config_file``
    which deliberately turns it off — opposite jobs.  That one edits a file an
    operator reads; this one crosses a pipe into a subprocess of unknown
    locale.  Escaping the em-dashes the refusal sentences carry means this
    write can never raise UnicodeEncodeError, and ``json.loads`` hands the
    caller back the exact character either way.
    """
    console.print(json.dumps(payload), markup=False, soft_wrap=True, highlight=False)


def _refuse(ctx: _Json, message: str, suggestion: str | None = None) -> None:
    """Emit one refusal — as a payload when asked, else on the human path.

    ONE wording serves both surfaces.  @api keys on these sentences, so a
    second copy written for machines would be a contract free to drift.
    ``suggestion`` is always present in the payload, null where the refusal
    genuinely has none.

    Args:
        ctx: The verb name and whether machine output was requested.
        message: The refusal sentence.
        suggestion: The remedy line, when the refusal has one.
    """
    if ctx.on:
        _emit({"ok": False, "verb": ctx.verb, "error": message, "suggestion": suggestion})
        return

    error(message, suggestion=suggestion)


def _project_row(row: dict, with_cap: bool = False) -> dict:
    """Project one resolved limit row from ``config_loader`` for a payload.

    A thin projection on purpose: the resolution rules live in
    ``config_loader._resolve_limits`` and must not be re-implemented here,
    or the machine surface becomes a second, divergent answer.

    Args:
        row: One entry from ``get_effective_limits``.
        with_cap: Include ``auto_compact_cap`` when the row carries one.

    Returns:
        The published per-entry-type shape.
    """
    projected: dict = {
        "count": row.get("count"),
        "default_count": row.get("default_count"),
        "is_override": bool(row.get("is_override")),
        "source": row.get("source"),
    }
    cap = row.get("auto_compact_cap")
    if with_cap and cap is not None:
        projected["auto_compact_cap"] = cap
    return projected


def _project_default(row: dict) -> dict:
    """Project one global default limit — count, plus a cap when set."""
    projected: dict = {"count": row.get("count")}
    cap = row.get("auto_compact_cap")
    if cap is not None:
        projected["auto_compact_cap"] = cap
    return projected


def _project_overrides(limits: dict) -> dict:
    """Project only the entry types that actually deviate for one branch.

    Same rule the human OVERRIDES block applies, so the two surfaces list
    the same rows rather than two different notions of "override".
    """
    return {
        entry_type: _project_row(limits.get(entry_type, {}))
        for entry_type in _ENTRY_TYPES
        if limits.get(entry_type, {}).get("is_override")
    }


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
    # `set @memory sessions 25 --json` parses identically to the same line
    # without it, whichever slot the flag rode in.
    json_mode = wants_json(args)
    args = strip_json_flag(args)
    if not args:
        print_config_introspection()
        return True

    sub = args[0]

    if sub == "get":
        config_get(args[1:], _Json(_VERB_CONFIG_GET, json_mode))
        return True

    if sub == "set":
        config_set(args[1:], _Json(_VERB_CONFIG_SET, json_mode))
        return True

    if sub == "set-default":
        config_set_default(args[1:], _Json(_VERB_CONFIG_SET_DEFAULT, json_mode))
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
    """Refuse an entry type the rollover engine has no limit key for."""
    if entry_type in _ENTRY_TYPES:
        return True

    _refuse(
        ctx,
        f"Unknown entry type: '{entry_type}'",
        suggestion="Valid types: " + ", ".join(_ENTRY_TYPES),
    )
    return False


def _validate_count(raw: str, ctx: _Json) -> int | None:
    """Parse and bound-check a limit, emitting its own refusal.

    Args:
        raw: The count token as typed.
        ctx: Verb name and machine-output mode for the refusal.

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
            suggestion="Example: drone @memory config set @devpulse sessions 25",
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

    return count


# =============================================================================
# CONFIG VERBS — GET
# =============================================================================


def _fmt_count(value: object) -> str:
    """Render a limit for display — an absent limit says so, never shows 0."""
    return "unset" if value is None else str(value)


def _show_defaults(defaults: dict) -> None:
    """Print the global default limits block."""
    console.print("[bold]DEFAULTS[/bold] [dim](drone @memory config set-default <type> <count>)[/dim]")
    for entry_type in _ENTRY_TYPES:
        row = defaults.get(entry_type, {})
        cap = row.get("auto_compact_cap")
        suffix = "" if cap is None else f"  [dim]auto_compact_cap {cap} (read-only)[/dim]"
        console.print(f"  [cyan]{entry_type:<14}[/cyan] {_fmt_count(row.get('count'))}{suffix}")
    console.print()


def _show_overrides(overrides: dict) -> None:
    """Print every branch whose effective limits deviate from the defaults."""
    if not overrides:
        console.print("[green]>[/green] All branches at defaults — no per-branch overrides")
        console.print()
        return

    console.print(f"[bold]OVERRIDES[/bold] [dim]({len(overrides)} branch(es) deviating from defaults)[/dim]")
    for branch, limits in overrides.items():
        console.print(f"  [bold]@{branch}[/bold]")
        for entry_type in _ENTRY_TYPES:
            row = limits.get(entry_type, {})
            if not row.get("is_override"):
                continue
            console.print(
                f"    [cyan]{entry_type:<14}[/cyan] {_fmt_count(row.get('count'))} "
                f"[yellow][OVERRIDE][/yellow] [dim](default {_fmt_count(row.get('default_count'))})[/dim]"
            )
    console.print()


def _show_branch_limits(branch: str, limits: dict) -> None:
    """Print one branch's EFFECTIVE limits, each marked default-or-override.

    Markers are UPPERCASE on purpose: Rich reads `[default]` as a style name
    and deletes it silently, so a lowercase marker would look right in the
    source and be invisible on screen.
    """
    console.print(f"[bold]@{branch}[/bold] [dim](effective limits — what the rollover engine applies)[/dim]")
    console.print()

    for entry_type in _ENTRY_TYPES:
        row = limits.get(entry_type, {})
        marker = "[yellow][OVERRIDE][/yellow]" if row.get("is_override") else "[green][DEFAULT][/green]"
        console.print(
            f"  [cyan]{entry_type:<14}[/cyan] {_fmt_count(row.get('count')):<6} {marker} "
            f"[dim](default {_fmt_count(row.get('default_count'))}, resolved from {row.get('source')})[/dim]"
        )
        cap = row.get("auto_compact_cap")
        if cap is not None:
            console.print(f"                 [dim]auto_compact_cap {cap} — read-only in v1[/dim]")

    console.print()
    console.print("[dim]Change with: drone @memory config set @" + branch + " sessions <count>[/dim]")
    console.print()


def config_get(args: List[str], ctx: _Json) -> None:
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
                        entry_type: _project_row(limits.get(entry_type, {}), with_cap=True)
                        for entry_type in _ENTRY_TYPES
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
                "defaults": {entry_type: _project_default(defaults.get(entry_type, {})) for entry_type in _ENTRY_TYPES},
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


def config_set(args: List[str], ctx: _Json) -> None:
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
            suggestion="Example: drone @memory config set @devpulse sessions 25",
        )
        return

    branch = _resolve_branch(args[0], ctx)
    if branch is None:
        return

    entry_type = args[1]
    if not _validate_type(entry_type, ctx):
        return

    count = _validate_count(args[2], ctx)
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


def config_set_default(args: List[str], ctx: _Json) -> None:
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
            suggestion="Example: drone @memory config set-default sessions 25",
        )
        return

    entry_type = args[0]
    if not _validate_type(entry_type, ctx):
        return

    count = _validate_count(args[1], ctx)
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
    """Display config-verb introspection (seedgo standard)."""
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
    console.print("  [green]drone @memory config set @devpulse sessions 25[/green] [dim]# Override[/dim]")
    console.print("  [green]drone @memory config get --json[/green]                [dim]# Machine surface[/dim]")
    console.print("  [green]drone @memory config --help[/green]                    [dim]# Full usage guide[/dim]")
    console.print()


def print_config_help() -> None:
    """Display config-verb help."""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]config Verb - Rollover Limit Settings[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    console.print()
    console.print("[bold]USAGE:[/bold]")
    console.print("  drone @memory config get                        Defaults + branches that deviate")
    console.print("  drone @memory config get @<branch>              One branch's effective limits")
    console.print("  drone @memory config set @<branch> <type> <n>   Override one branch")
    console.print("  drone @memory config set-default <type> <n>     Change the global default")
    console.print()
    console.print("[bold]--json — THE MACHINE SURFACE:[/bold]")
    console.print("  Every verb above takes [cyan]--json[/cyan] in ANY slot; it is stripped before")
    console.print("  positional parsing, so `set @b sessions 25 --json` parses like `set @b sessions 25`.")
    console.print("  Exactly ONE JSON document reaches stdout — no panels, no banners, no Rich.")
    console.print("  A help flag OUTRANKS it: `set ... --help --json` prints this page and writes nothing.")
    console.print()
    console.print("  Every payload carries [cyan]ok[/cyan] and [cyan]verb[/cyan]. [cyan]ok[/cyan] is the signal,")
    console.print("  because refusals exit 0 — a refusal is [cyan]ok: false[/cyan] plus [cyan]error[/cyan] and")
    console.print("  [cyan]suggestion[/cyan], carrying the SAME sentences the human path prints.")
    console.print()
    console.print("[bold]ENTRY TYPES:[/bold]")
    console.print("  [cyan]sessions[/cyan]        local.json -> sessions")
    console.print("  [cyan]key_learnings[/cyan]   local.json -> key_learnings")
    console.print("  [cyan]observations[/cyan]    observations.json -> observations")
    console.print()
    console.print(f"[bold]BOUNDS:[/bold] a whole number, {_MIN_COUNT}-{_MAX_COUNT} inclusive")
    console.print(
        f"  {_MIN_COUNT - 1} would roll over every entry immediately; past {_MAX_COUNT} rollover is defeated entirely."
    )
    console.print()
    console.print("[bold]EFFECTIVE LIMITS:[/bold]")
    console.print("  Resolution is per FILE KEY, not per entry type — exactly what the")
    console.print("  rollover engine does. Once per_branch -> <branch> -> local exists,")
    console.print("  the default local block is never consulted for that branch again.")
    console.print("  A value is marked [yellow][OVERRIDE][/yellow] when it differs from the default,")
    console.print("  [green][DEFAULT][/green] when it matches.")
    console.print()
    console.print("[bold]SET-DEFAULT DOES NOT PUSH:[/bold]")
    console.print("  set-default writes defaults only and leaves per_branch untouched.")
    console.print("  drone @memory rollover push stays the one explicit fleet-wide reset.")
    console.print()
    console.print("[bold]READ-ONLY:[/bold] auto_compact_cap is displayed but not settable in v1.")
    console.print()


# =============================================================================
# ROLLOVER ORCHESTRATION
# =============================================================================


def run_rollover() -> bool:
    """
    Execute rollover workflow for all triggered branches.

    Delegates to handler and renders results with Rich.
    """
    console.print()
    console.print(Panel.fit("[bold cyan]Memory - Rollover Execution[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()

    console.print("[cyan]Checking for rollover triggers... (first run may take 30s for model loading)[/cyan]")

    try:
        result = _handler_execute_rollover()
    except Exception as e:
        logger.error(f"[rollover] Rollover execution failed: {e}", exc_info=True)
        error(f"Rollover failed: {e}")
        return False

    if not result.get("success") and result.get("error"):
        error(result["error"])
        return False

    triggers_count = result.get("triggers_count", 0)
    if triggers_count == 0:
        console.print("[green]>[/green] No files need rollover")
        return True

    console.print(f"[green]>[/green] Found {triggers_count} files ready for rollover")
    console.print()

    # Display individual results
    for item in result.get("results", []):
        local_status = "> local" if item.get("local_stored") else "x local"
        console.print(
            f"  [green]>[/green] Rolled over {item['memories_count']} items -> {item['global_collection']} "
            f"({item['old_lines']} -> {item['new_lines']} lines, "
            f"global: {item['global_total']} vectors, {local_status})"
        )

    # Report results
    success_count = result.get("success_count", 0)
    failed = result.get("failed", [])

    console.print()
    if success_count > 0:
        console.print(f"[green]>[/green] Rollover complete: {success_count}/{triggers_count} successful")

    if failed:
        console.print()
        for fail in failed:
            error(f"{fail['trigger']} - {fail['stage']}: {fail['error']}")

    json_handler.log_operation("rollover_execute", {"triggers": triggers_count, "success_count": success_count})

    # Refresh state-tabs for the branches THIS run actually rolled (counts may
    # have changed). Scoped deliberately: unscoped, one citizen's overdue file
    # rewrote all 38 memory files fleet-wide on 2026-08-25, shipping a renderer
    # change to every branch from a PreCompact hook nobody was watching.
    rolled = sorted({item["branch"] for item in result.get("results", []) if item.get("branch")})
    if rolled:
        try:
            from aipass.memory.apps.handlers.tracking.tab_renderer import refresh_all_tabs

            refresh_all_tabs(branches=rolled)
        except Exception as e:
            logger.warning(f"[rollover] Tab refresh failed: {e}")

        _normalize_rolled(rolled)

    return success_count > 0


def _normalize_rolled(rolled: List[str]) -> None:
    """Re-render the machine frame of each branch THIS run actually rolled.

    Self-healing on touch, the marker-7 shape: a branch that rolls heals its
    own frame in the same breath — nothing watches, nothing polls, and a
    branch that never rolls is never touched.

    Scoped to `rolled` for the reason the tab refresh above is: an unscoped
    version of this rewrote all 38 memory files in the fleet on 2026-08-25.
    Failures are logged, never raised — the rollover already succeeded and
    reported, and a cosmetic re-render must not retract that.
    """
    from aipass.memory.apps.handlers.monitor import registry_scope
    from aipass.memory.apps.handlers.rollover import normalizer
    from aipass.memory.apps.handlers.json import config_loader

    wanted = {name.lower() for name in rolled}
    try:
        config = config_loader.load()
        targets = [item for item in registry_scope.fleet_branches() if item["name"].lower() in wanted]
    except Exception as e:
        logger.warning(f"[rollover] Frame normalize skipped — cannot resolve scope: {e}")
        return

    healed = 0
    for item in targets:
        try:
            if normalizer.normalize_branch(item["name"], item["path"], config)["success"]:
                healed += 1
        except Exception as e:
            logger.warning(f"[rollover] Frame normalize failed for {item['name']}: {e}")

    missing = wanted - {item["name"].lower() for item in targets}
    if missing:
        # Named, never silent: a rolled branch the fleet scope cannot see is
        # exactly the invisibility item 7 closed, and it would come back here.
        logger.warning(f"[rollover] Rolled but not in fleet scope, frame NOT normalized: {sorted(missing)}")
    if healed:
        logger.info(f"[rollover] Machine frame re-rendered for {healed} rolled branch(es)")


# =============================================================================
# PLAN VECTORIZATION
# =============================================================================


def process_plans_command() -> None:
    """
    Process pending plan files into vector storage.

    Batches all chunks from all files into a single embed + store call.
    """
    console.print()
    console.print(Panel.fit("[bold cyan]Memory - Process Plans[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()

    console.print("[cyan]Processing plan files into vector storage...[/cyan]")
    console.print()

    try:
        from aipass.memory.apps.handlers.intake.plans_processor import process_plans

        result = process_plans()
    except Exception as e:
        logger.error(f"[rollover] Plan processing failed: {e}")
        error(f"Plan processing failed: {e}")
        return

    if not result.get("success"):
        error(result.get("error", "Unknown error"))
        if result.get("errors"):
            for err in result["errors"]:
                error(err)
        return

    files_processed = result.get("files_processed", 0)
    total_chunks = result.get("total_chunks", 0)
    reason = result.get("reason", "")

    if files_processed == 0 and reason:
        console.print(f"[green]>[/green] {reason}")
    elif files_processed == 0:
        console.print("[green]>[/green] No new plans to process")
    else:
        console.print(f"[green]>[/green] Processed {files_processed} files ({total_chunks} chunks vectorized)")

    if result.get("errors"):
        console.print()
        for err in result["errors"]:
            error(err)

    console.print()
    json_handler.log_operation(
        "process_plans_command", {"files_processed": files_processed, "total_chunks": total_chunks}
    )


# =============================================================================
# LINE COUNT SYNC
# =============================================================================


def _announce_rename(old_verb: str) -> None:
    """Tell a caller of a renamed verb what it is running and why."""
    new_verb = RENAMED_VERBS[old_verb]
    console.print()
    warning(
        f"'{old_verb}' is now '{new_verb}' — it never synced anything: its only write was a "
        f"health stamp deleted from the standard on 2026-08-25. Running the reporter."
    )


def report_line_counts() -> None:
    """Report physical line counts for every branch memory file. Read-only.

    Writes nothing — not the files, not the tabs. The rename exists because
    the old name promised a sync; re-rendering the fleet's meta lines from a
    reporter would have kept the promise in the worst possible way.

    Meta lines are re-rendered by the lanes that have a reason to: the trinity
    push (per branch, gated), and a rollover's own scoped normalize.
    """
    console.print()
    console.print(Panel.fit("[bold cyan]Memory - Line Count Report[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()

    console.print("[cyan]Measuring every branch memory file (read-only)...[/cyan]")
    console.print()

    result = _handler_sync_line_counts()

    if result["success"]:
        console.print(f"[green]>[/green] Measured {result['updated']} files")
        if result["failed"] > 0:
            warning(f"{result['failed']} files could not be read")
            for branch, mem_type, err_msg in result.get("failures", []):
                error(f"{branch}.{mem_type}: {err_msg}")
        json_handler.log_operation("rollover_report_lines", {"measured": result["updated"], "failed": result["failed"]})
    else:
        error("Failed to measure line counts")

    console.print()


# =============================================================================
# PUSH DEFAULTS
# =============================================================================


def push_defaults(json_mode: bool = False) -> None:
    """Overwrite every per_branch entry in memory.config.json with defaults.

    Args:
        json_mode: Emit one machine payload instead of the rendered report.
    """
    from aipass.memory.apps.handlers.json import config_loader

    ctx = _Json(_VERB_ROLLOVER_PUSH, json_mode)

    if not ctx.on:
        console.print()
        console.print(Panel.fit("[bold cyan]Memory - Push Defaults[/bold cyan]", border_style="cyan", box=box.ROUNDED))
        console.print()

        console.print("[cyan]Overwriting all per_branch limits with defaults...[/cyan]")
        console.print()

    result = config_loader.push_defaults_to_per_branch()

    if not result.get("success"):
        _refuse(ctx, result.get("error", "Unknown error"))
        return

    count = result.get("branches", 0)
    if ctx.on:
        _emit({"ok": True, "verb": ctx.verb, "branches": count})
    else:
        console.print(f"[green]>[/green] Pushed defaults to {count} branches")
        console.print()

    json_handler.log_operation("push_defaults", {"branches": count, "json": ctx.on})


# =============================================================================
# STATUS & CHECKING
# =============================================================================


def show_status() -> None:
    """
    Show rollover statistics for all branches

    Displays:
    - Files checked
    - Files ready for rollover
    - Per-branch status (current/max lines)
    """
    console.print()
    console.print(Panel.fit("[bold cyan]Memory - Rollover Status[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()

    # Get stats from detector
    stats_result = detector.get_rollover_stats()

    if not stats_result["success"]:
        error(f"Failed to get status: {stats_result.get('error', 'Unknown error')}")
        logger.error(f"[rollover] Failed to get status: {stats_result.get('error')}")
        return

    stats = stats_result

    # Summary
    console.print(f"[cyan]Branches:[/cyan] {stats['total_branches']}")
    console.print(f"[cyan]Files checked:[/cyan] {stats['files_checked']}")
    console.print(f"[cyan]Ready for rollover:[/cyan] {stats['files_ready']}")
    console.print()

    # Per-branch details
    if stats["branches"]:
        console.print("[bold cyan]Branch Details:[/bold cyan]")
        console.print()

        for branch_name, branch_stats in stats["branches"].items():
            console.print(f"  [bold]{branch_name}[/bold]")

            for memory_type, file_stats in branch_stats.items():
                ready = file_stats["ready"]
                v2_reason = file_stats.get("v2_reason", "")

                status_marker = "[red]![/red]" if ready else "[green]OK[/green]"
                status_text = f"READY ({v2_reason})" if ready else "OK"
                console.print(f"    {status_marker} {memory_type}: {status_text}")

            console.print()

    json_handler.log_operation(
        "rollover_status", {"branches_checked": stats["total_branches"], "files_ready": stats["files_ready"]}
    )


def check_triggers() -> None:
    """
    Check which branches need rollover (without executing)

    Displays list of files that hit rollover threshold
    """
    console.print()
    console.print(Panel.fit("[bold cyan]Memory - Rollover Check[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()

    triggers_result = detector.check_all_branches()

    if not triggers_result["success"]:
        error(f"Failed to check triggers: {triggers_result.get('error', 'Unknown error')}")
        logger.error(f"[rollover] Failed to check triggers: {triggers_result.get('error')}")
        return

    triggers = triggers_result.get("triggers", [])

    if not triggers:
        console.print("[green]>[/green] No files need rollover")
        json_handler.log_operation("rollover_check", {"files_needing_rollover": 0})
        return

    console.print(f"[bold cyan]Found {len(triggers)} files ready for rollover:[/bold cyan]")
    console.print()

    for trigger in triggers:
        console.print(f"  * {trigger}")

    console.print()
    console.print("[dim]Run 'drone @memory rollover' to process these files[/dim]")
    console.print()
    json_handler.log_operation("rollover_check", {"files_needing_rollover": len(triggers)})


# =============================================================================
# INTROSPECTION
# =============================================================================


def _discover_handlers() -> dict[str, list[str]]:
    """Auto-discover handler directories and their Python files.

    Scans the handlers/ directory relative to this module.

    Returns:
        Dict mapping handler directory name to list of .py filenames
        (excluding __init__.py and __pycache__).
    """
    handlers_dir = Path(__file__).resolve().parent.parent / "handlers"
    result: dict[str, list[str]] = {}
    if not handlers_dir.exists():
        return result
    for d in sorted(handlers_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("__"):
            continue
        py_files = sorted(f.name for f in d.iterdir() if f.is_file() and f.suffix == ".py" and f.name != "__init__.py")
        if py_files:
            result[d.name] = py_files
    return result


def print_introspection() -> None:
    """Display module introspection info (seedgo standard).

    Called when 'rollover' is invoked with no arguments.
    Shows module identity, connected handlers, available subcommands,
    and next-step hints.
    """
    console.print()
    console.print("[bold cyan]rollover Module[/bold cyan]")
    console.print("Orchestrates memory rollover workflow: trigger detection, extraction, embedding, and vector storage")
    console.print()

    # Connected handlers (auto-discovered)
    handlers = _discover_handlers()
    console.print("[yellow]Connected Handlers:[/yellow]")
    if handlers:
        for dir_name, files in handlers.items():
            file_list = ", ".join(files)
            console.print(f"  [cyan]handlers/{dir_name}/[/cyan]  [dim]{file_list}[/dim]")
    else:
        console.print("  [dim]No handlers found[/dim]")
    console.print()

    # Available subcommands
    console.print("[yellow]Subcommands:[/yellow]")
    for sub, desc in _SUBCOMMANDS.items():
        console.print(f"  [green]{sub:<14}[/green] {desc}")
    console.print()

    # Next-step hints
    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @memory rollover run[/green]          [dim]# Execute rollover[/dim]")
    console.print("  [green]drone @memory rollover status[/green]       [dim]# View rollover stats[/dim]")
    console.print("  [green]drone @memory rollover check[/green]        [dim]# Dry-run check[/dim]")
    console.print("  [green]drone @memory rollover --help[/green]       [dim]# Full usage guide[/dim]")
    console.print()


# =============================================================================
# STANDALONE EXECUTION
# =============================================================================

if __name__ == "__main__":
    import sys

    # No args → introspection (seedgo standard)
    if len(sys.argv) < 2:
        handle_command("rollover", [])
        sys.exit(0)

    # --help → full help
    if sys.argv[1] in ("--help", "-h", "help"):
        handle_command("rollover", ["--help"])
        sys.exit(0)

    # Execute command via handle_command
    command = sys.argv[1]
    if not handle_command(command, sys.argv[2:]):
        error(f"Unknown command: {command}", suggestion="Run 'drone @memory rollover --help' for available commands")
        sys.exit(1)
