# =================== AIPass ====================
# Name: rollover.py
# Description: Rollover Orchestration Module
# Version: 0.10.0
# Created: 2025-11-16
# Modified: 2026-09-18
# =============================================

"""
Rollover Orchestration Module

Coordinates the memory rollover workflow by calling handlers in sequence:
1. Detect rollover triggers (monitor/detector)
2. Extract oldest memories (rollover/extractor)
3. Generate embeddings (vector/embedder)
4. Store in Chroma (storage/chroma)
5. Roll ONE branch's todo pad to its backlog file (rollover/todo_roll) - own
   branch only, never the fleet walk, never vectors

Purpose:
    Thin orchestration layer - no business logic implementation.
    All domain logic lives in handlers.
"""

import os
import sys
from typing import List

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
from aipass.memory.apps.handlers.cli.branch_flag import read_branch_flag

# =============================================================================
# INFRASTRUCTURE SETUP
# =============================================================================

# Handler imports
from aipass.memory.apps.handlers.monitor import detector
from aipass.memory.apps.handlers.rollover.orchestrator import (
    execute_rollover as _handler_execute_rollover,
    sync_line_counts as _handler_sync_line_counts,
)
from aipass.memory.apps.handlers.rollover import todo_report
from aipass.memory.apps.handlers.repo_root import module_file

# The `config` verbs moved to modules/rollover_config.py when this module reached
# the seedgo length standard, and the `--json` emitter moved on again to
# modules/rollover_json.py when THAT module reached it. Both stayed in the
# modules tier because they are display code and handlers may not print; each
# answers `handle_command` for its own name only, so this module keeps owning
# the `config` word. Every name is re-exported here, unchanged, because the CLI
# and the tests reach all of them through `rollover.<name>`. The dependency runs
# one way: neither of those modules imports this one.
from aipass.memory.apps.modules.rollover_config import (
    _CONFIG_SUBCOMMANDS,
    _MAX_COUNT,
    _MIN_COUNT,
    _VERB_CONFIG,
    _VERB_CONFIG_GET,
    _VERB_CONFIG_SET,
    _VERB_CONFIG_SET_DEFAULT,
    _handle_config,
    _resolve_branch,
    _show_branch_limits,
    _show_defaults,
    _show_overrides,
    _validate_count,
    _validate_type,
    handle_config_get,
    handle_config_set,
    handle_config_set_default,
    print_config_help,
    print_config_introspection,
)
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

__all__ = [
    "_CONFIG_SUBCOMMANDS",
    "_DISPLAY_TYPES",
    "_ENTRY_TYPES",
    "_Json",
    "_MAX_COUNT",
    "_MIN_COUNT",
    "_READ_ONLY_TYPES",
    "_VERB_CONFIG",
    "_VERB_CONFIG_GET",
    "_VERB_CONFIG_SET",
    "_VERB_CONFIG_SET_DEFAULT",
    "_emit",
    "_handle_config",
    "_project_default",
    "_project_overrides",
    "_project_row",
    "_refuse",
    "_resolve_branch",
    "_show_branch_limits",
    "_show_defaults",
    "_show_overrides",
    "_validate_count",
    "_validate_type",
    "handle_config_get",
    "handle_config_set",
    "handle_config_set_default",
    "print_config_help",
    "print_config_introspection",
]


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

_SUBCOMMANDS = {
    "run": "Execute rollover for files exceeding limits (fleet-wide), plus one branch's todo pad",
    "status": "Show rollover statistics for all branches",
    "check": "Check which files need rollover (dry run, fleet-wide), plus one branch's todo pad",
    "report-lines": "Report physical line counts per memory file (read-only)",
    "push": "Overwrite all per_branch limits to defaults (system-wide reset)",
}

# Public alias — the introspection surface and the tests read this name.
SUBCOMMANDS = _SUBCOMMANDS

# `rollover check` prints this under its classic file list. That list is the
# fleet walk (detector.check_all_branches) whatever --branch names; the pad
# line alone is scoped. The scope is unchanged on purpose - this says it.
FLEET_WIDE_NOTE = "The file list is fleet-wide: --branch scopes only the todo pad line below."

# `rollover run` rolls the pad FIRST, so its line sits above the file list. The
# run is fleet-wide on purpose: @hooks' PreCompact passes --branch for the pad
# and relies on the same call to drain every branch's files, and a project that
# never compacts (Vera Studio's residents) only drains through someone else's
# compaction. Scoping the files to --branch would stop that without a word, so
# the scope stays and the output says it where it happens.
FLEET_WIDE_RUN_NOTE = (
    "The file list is fleet-wide: --branch scopes only the todo pad line above; every branch's files below are rolled."
)

# Printed under the files rollover cannot drain. Never the phrase @hooks'
# PreCompact greps for: another run changes nothing for these files.
UNDRAINABLE_NOTE = (
    "Rollover drains lists only. These need their container migrated to the 3.0.0 list shape - "
    "another run changes nothing."
)

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

# Verb names as they appear in the `verb` field of every JSON payload. One
# constant per name so the payload and the routing cannot drift apart.
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
        branch, refused = _branch_flag(args[1:], "run")
        if not refused:
            run_rollover(branch)
        return True

    if sub == "status":
        show_status()
        return True

    if sub == "check":
        branch, refused = _branch_flag(args[1:], "check")
        if not refused:
            check_triggers(branch)
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
        rollover run [--branch @b]   -> execute rollover (+ one todo pad)
        rollover status              -> show rollover status
        rollover check [--branch @b] -> dry-run check (+ one todo pad)
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
    it — `config set @b sessions 12 --help --json` prints help and writes
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
        branch, refused = _branch_flag(args, "check")
        if not refused:
            check_triggers(branch)
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
    console.print("  drone @memory rollover run [--branch @name]")
    console.print("  drone @memory rollover check [--branch @name]")
    console.print()
    console.print("[bold]COMMANDS:[/bold]")
    console.print("  [cyan]rollover[/cyan]    Execute rollover for files exceeding limits, plus ONE branch's todo pad")
    console.print("              The files rolled are fleet-wide; only the todo pad follows --branch.")
    console.print("  [cyan]status[/cyan]      Show rollover statistics for all branches")
    console.print("  [cyan]check[/cyan]       Check which files need rollover (dry run), plus ONE branch's todo pad")
    console.print("              The file list is fleet-wide; only the todo pad follows --branch.")
    console.print("  [cyan]report-lines[/cyan] Report line counts per memory file (read-only)")
    console.print("  [cyan]push[/cyan]        Reset ALL per_branch limits to defaults (system-wide, use with caution)")
    console.print("  [cyan]help[/cyan]        Show this help message")
    console.print()
    console.print("[bold]FLAGS:[/bold]")
    console.print("  [cyan]--branch @name[/cyan]  run / check: the ONE branch whose todo pad is rolled / checked.")
    console.print("              Absent: the branch your working directory sits in (drone's caller cwd).")
    console.print("              At the repo root or outside every branch, no pad is touched and one line says so.")
    console.print("              The sessions / key_learnings / observations file list stays fleet-wide.")
    console.print("  [cyan]--json[/cyan]      Machine output for [cyan]push[/cyan] — one JSON document, no Rich")
    console.print('              {"ok": true, "verb": "rollover push", "branches": 17}')
    console.print("              Rides in any slot. A help flag still outranks it.")
    console.print()
    console.print("[bold]LIMITS:[/bold]")
    console.print("  v2 entry-count based (sessions, key_learnings, observations) from config")
    console.print("  A container held as a dict (schema 2.0.0) cannot be drained: check, run and status")
    console.print("  list it as UNDRAINABLE, never as ready, until it is migrated to the 3.0.0 list shape")
    console.print("  todos: count only (rollover.defaults.local.todos.count) — own branch, never the fleet walk")
    console.print()
    console.print("[bold]TODO ROLL (one branch, file only, never vectors):[/bold]")
    console.print("  Over its count, the OLDEST todos by number move to .backup/todo/<branch>/backlog.json.")
    console.print("  The backlog is appended, replaced atomically and read back; the pad is pruned only")
    console.print("  after every rolled todo reads back json-equal. check says 'ready for rollover' when over.")
    console.print()
    console.print("[bold]WORKFLOW:[/bold]")
    console.print("  1. Detect files exceeding v2 entry-count limits")
    console.print("  2. Extract oldest entries")
    console.print("  3. Generate embeddings via fastembed")
    console.print("  4. Store vectors in local + global ChromaDB")
    console.print()


# =============================================================================
# ROLLOVER ORCHESTRATION
# =============================================================================


def _branch_flag(tokens: List[str], verb: str) -> tuple[str | None, bool]:
    """`--branch @name` for `rollover run` / `rollover check` -> ``(branch, refused)``; a refusal is printed."""
    branch, problem = read_branch_flag(tokens)
    if problem:
        error(f"{problem} (rollover {verb})", suggestion=f"Usage: drone @memory rollover {verb} [--branch @name]")
        return None, True
    return branch, False


def _todo_report(report: dict) -> None:
    """Print one todo-pad report from handlers/rollover/todo_report.

    ``soft_wrap`` because the console is 80 wide on a pipe, and a hard wrap
    inside "ready for rollover" would hide it from @hooks' PreCompact grep;
    ``markup`` and ``highlight`` off so a path or a number prints as written.
    """
    text = str(report.get("text"))
    if report.get("level") == "error":
        error(text)
        return
    if report.get("level") == "warning":
        warning(text)
        return
    console.print(text, markup=False, highlight=False, soft_wrap=True)


def _print_undrainable(items: list) -> None:
    """Print the files over a limit that rollover cannot drain; nothing when there are none."""
    if not items:
        return
    listing = "\n".join(f"  ! {item}" for item in items)
    header = f"{len(items)} files over their limit that rollover cannot drain (fleet-wide):"
    warning(f"{header}\n{listing}", UNDRAINABLE_NOTE)


def run_rollover(branch: str | None = None) -> bool:
    """
    Execute rollover: ONE branch's todo pad first, then the fleet vector rollover.

    The todo roll is file-only and takes milliseconds, so it runs before the
    model load a vector rollover may wait on. Delegates to handlers and
    renders results with Rich.

    Args:
        branch: `@name` from --branch, or None to resolve the caller's branch
            from its working directory (nothing is rolled at the repo root).

    Returns:
        The vector rollover's outcome, exactly as before the todo roll existed.
    """
    console.print()
    console.print(Panel.fit("[bold cyan]Memory - Rollover Execution[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()

    _todo_report(todo_report.roll_pad(branch))

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
    undrainable = result.get("undrainable", [])
    if triggers_count == 0:
        console.print("[green]>[/green] No files need rollover")
        _print_undrainable(undrainable)
        return True

    console.print(f"[green]>[/green] Found {triggers_count} files ready for rollover (fleet-wide)")
    console.print(f"[dim]{FLEET_WIDE_RUN_NOTE}[/dim]", soft_wrap=True)
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
    # 0/N is a result, not a reason to say nothing. Gated on success_count > 0,
    # a run where every trigger failed ended on a blank line under "Found N
    # files ready for rollover" — the same shape on screen as a run with
    # nothing to do. The per-failure detail below says what broke; this says
    # what the run achieved.
    marker = "[green]>[/green]" if success_count else "[yellow]>[/yellow]"
    console.print(f"{marker} Rollover complete: {success_count}/{triggers_count} successful")

    # A trigger the extractor declined is neither a win nor a break, and printing
    # neither left "0/1 successful" above an empty failure list — a count saying
    # something went wrong beside a list saying nothing did.
    for item in result.get("skipped", []):
        console.print(f"  [yellow]-[/yellow] {item['trigger']} skipped: {item['reason']}")

    if failed:
        console.print()
        for fail in failed:
            error(f"{fail['trigger']} - {fail['stage']}: {fail['error']}")

    _print_undrainable(undrainable)

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
        # STOPS AT THE REPO EDGE, like the push and the rollover detector.
        # normalize_branch WRITES — it re-renders the machine frame in place —
        # and this lane matches rolled branches BY NAME across whatever scope it
        # is given. Handed the whole fleet it would, the day any external
        # project names a branch `api` or `flow`, rewrite a file in a sibling
        # repository because one of ours happened to roll. There is no collision
        # today; that is luck, and luck is not a scope.
        targets = [
            item
            for item in registry_scope.fleet_branches()
            if item["name"].lower() in wanted and item.get("residency") != registry_scope.RESIDENCY_EXTERNAL
        ]
    except Exception as e:
        logger.warning(f"[rollover] Frame normalize skipped — cannot resolve scope: {e}")
        return

    healed = 0
    for item in targets:
        try:
            # The normalizer reports failure by RETURN VALUE and promises never
            # to raise, so this `except` cannot be the thing that catches a
            # failed write — reading only ["success"] dropped the error string
            # it hands back. A branch whose frame could not be written was
            # invisible, while an out-of-scope branch below is named by name.
            outcome = normalizer.normalize_branch(item["name"], item["path"], config)
            if outcome["success"]:
                healed += 1
            else:
                logger.warning(
                    f"[rollover] Frame NOT re-rendered for {item['name']}: "
                    f"{outcome.get('error') or 'nothing could be written'}"
                )
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
    console.print(f"[cyan]Over, and rollover cannot drain them:[/cyan] {stats.get('files_undrainable', 0)}")
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
                # Never "OK": the file is over its limit, and no run will change that.
                undrainable = file_stats.get("undrainable", [])

                status_marker = "[red]![/red]" if ready or undrainable else "[green]OK[/green]"
                parts = [f"READY ({v2_reason})"] if ready else []
                parts += [f"UNDRAINABLE ({reason})" for reason in undrainable]
                status_text = "; ".join(parts) or "OK"
                console.print(f"    {status_marker} {memory_type}: {status_text}")

            console.print()

    json_handler.log_operation(
        "rollover_status", {"branches_checked": stats["total_branches"], "files_ready": stats["files_ready"]}
    )


def check_triggers(branch: str | None = None) -> None:
    """
    Check which branches need rollover (without executing), then ONE branch's todo pad.

    Displays list of files that hit rollover threshold

    Args:
        branch: `@name` from --branch, or None to resolve the caller's branch
            from its working directory (no pad is checked at the repo root).
    """
    console.print()
    console.print(Panel.fit("[bold cyan]Memory - Rollover Check[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()

    _check_fleet_triggers()
    _todo_report(todo_report.check_pad(branch))


def _check_fleet_triggers() -> None:
    """The fleet walk for sessions, key_learnings and observations — never todos, never scoped by --branch."""
    triggers_result = detector.check_all_branches()

    if not triggers_result["success"]:
        error(f"Failed to check triggers: {triggers_result.get('error', 'Unknown error')}")
        logger.error(f"[rollover] Failed to check triggers: {triggers_result.get('error')}")
        return

    triggers = triggers_result.get("triggers", [])
    undrainable = triggers_result.get("undrainable", [])

    if not triggers:
        console.print("[green]>[/green] No files need rollover")
        _print_undrainable(undrainable)
        json_handler.log_operation("rollover_check", {"files_needing_rollover": 0, "undrainable": len(undrainable)})
        return

    # The file list is the fleet walk's, whatever --branch named: --branch scopes
    # only the todo pad line. "ready for rollover" stays literal and unwrapped on
    # the first line - @hooks' PreCompact greps this output for it.
    header = f"Found {len(triggers)} files ready for rollover (fleet-wide):"
    console.print(f"[bold cyan]{header}[/bold cyan]", soft_wrap=True)
    console.print(f"[dim]{FLEET_WIDE_NOTE}[/dim]", soft_wrap=True)
    console.print()

    for trigger in triggers:
        console.print(f"  * {trigger}")

    console.print()
    console.print("[dim]Run 'drone @memory rollover' to process these files[/dim]")
    _print_undrainable(undrainable)
    console.print()
    json_handler.log_operation(
        "rollover_check", {"files_needing_rollover": len(triggers), "undrainable": len(undrainable)}
    )


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
    handlers_dir = module_file(__file__).parent.parent / "handlers"
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
    console.print("  [green]drone @memory rollover check --branch @devpulse[/green] [dim]# One branch's todo pad[/dim]")
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
