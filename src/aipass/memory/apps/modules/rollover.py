# =================== AIPass ====================
# Name: rollover.py
# Description: Rollover Orchestration Module
# Version: 0.10.1
# Created: 2025-11-16
# Modified: 2026-10-17
# =============================================

"""
Rollover Orchestration Module
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


from aipass.memory.apps.handlers.monitor import detector
from aipass.memory.apps.handlers.rollover.orchestrator import (
    execute_rollover as _handler_execute_rollover,
    sync_line_counts as _handler_sync_line_counts,
)
from aipass.memory.apps.handlers.rollover import todo_report
from aipass.memory.apps.handlers.repo_root import module_file

# Re-exported unchanged: the CLI and the tests reach these as `rollover.<name>`. Neither module imports this one.
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


_SUBCOMMANDS = {
    "run": "Execute rollover for files exceeding limits (fleet-wide), plus one branch's todo pad",
    "status": "Show rollover statistics for all branches",
    "check": "Check which files need rollover (dry run, fleet-wide), plus one branch's todo pad",
    "report-lines": "Report physical line counts per memory file (read-only)",
    "push": "Overwrite all per_branch limits to defaults (system-wide reset)",
}

# Public alias — the introspection surface and the tests read this name.
SUBCOMMANDS = _SUBCOMMANDS

FLEET_WIDE_NOTE = "The file list is fleet-wide: --branch scopes only the todo pad line below."

# Fleet-wide on purpose: @hooks' PreCompact passes --branch for the pad and relies on the same call
# to drain every branch's files; a project that never compacts drains only through another's run.
FLEET_WIDE_RUN_NOTE = (
    "The file list is fleet-wide: --branch scopes only the todo pad line above; every branch's files below are rolled."
)

# Never the phrase @hooks' PreCompact greps for: another run changes nothing for these files.
UNDRAINABLE_NOTE = (
    "Rollover drains lists only. These need their container migrated to the 3.0.0 list shape - "
    "another run changes nothing."
)

# The old name still routes, so a caller learns what replaced it; the new verb writes nothing.
RENAMED_VERBS = {"sync-lines": "report-lines"}

# The `verb` field of every JSON payload; one constant so payload and routing cannot drift.
_VERB_ROLLOVER = "rollover"
_VERB_ROLLOVER_PUSH = "rollover push"


def _handle_rollover_verb(args: List[str]) -> bool:
    """Route the `rollover` subcommands. Always returns True — the verb is ours."""
    if not args:
        print_introspection()
        return True

    # A help flag ANYWHERE wins — asking about `push` must never push.
    if wants_help(args, allow_bare_word=True):
        print_help()
        return True

    # --json is removed before positional parsing, whichever slot it rode in.
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
    """Handle rollover and config commands with seedgo-compliant introspection."""
    # The entry point may still route top-level help here.
    if command in ("--help", "-h", "help"):
        print_help()
        return True

    if command == "config":
        return _handle_config(args)

    if command == "rollover":
        # Not redundant with the verb handler's gate: that one fires when the only args were flags.
        if not args:
            print_introspection()
            return True
        return _handle_rollover_verb(args)

    # Flat `if`/return, never an elif chain: a chain of six nests six deep for the nesting checker.
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


def _branch_flag(tokens: List[str], verb: str) -> tuple[str | None, bool]:
    """`--branch @name` for `rollover run` / `rollover check` -> ``(branch, refused)``; a refusal is printed."""
    branch, problem = read_branch_flag(tokens)
    if problem:
        error(f"{problem} (rollover {verb})", suggestion=f"Usage: drone @memory rollover {verb} [--branch @name]")
        return None, True
    return branch, False


def _todo_report(report: dict) -> None:
    """Print one todo-pad report from handlers/rollover/todo_report.

    soft_wrap: a hard wrap inside "ready for rollover" on an 80-wide pipe hides it from @hooks' PreCompact grep.
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
    """Execute rollover: ONE branch's todo pad first, then the fleet vector rollover.

    Returns the vector rollover's outcome only; the todo roll never changes it.
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

    for item in result.get("results", []):
        local_status = "> local" if item.get("local_stored") else "x local"
        console.print(
            f"  [green]>[/green] Rolled over {item['memories_count']} items -> {item['global_collection']} "
            f"({item['old_lines']} -> {item['new_lines']} lines, "
            f"global: {item['global_total']} vectors, {local_status})"
        )

    success_count = result.get("success_count", 0)
    failed = result.get("failed", [])

    console.print()
    # 0/N is a result, not a reason to say nothing: it must not look like a run with nothing to do.
    marker = "[green]>[/green]" if success_count else "[yellow]>[/yellow]"
    console.print(f"{marker} Rollover complete: {success_count}/{triggers_count} successful")

    # A declined trigger is neither win nor break; unprinted, "0/1 successful" sat above an empty failure list.
    for item in result.get("skipped", []):
        console.print(f"  [yellow]-[/yellow] {item['trigger']} skipped: {item['reason']}")

    if failed:
        console.print()
        for fail in failed:
            error(f"{fail['trigger']} - {fail['stage']}: {fail['error']}")

    _print_undrainable(undrainable)

    json_handler.log_operation("rollover_execute", {"triggers": triggers_count, "success_count": success_count})

    # Scoped to the branches THIS run rolled: unscoped, one overdue file rewrote every memory file in the fleet.
    rolled = sorted({item["branch"] for item in result.get("results", []) if item.get("branch")})
    if rolled:
        try:
            from aipass.memory.apps.handlers.tracking.tab_renderer import refresh_all_tabs

            refresh_all_tabs(branches=rolled)
        except Exception as e:
            # The rollover landed, so the run stands; a failed refresh is a fault, not a degradation.
            logger.error(f"[rollover] Tab refresh failed: {e}")

        _normalize_rolled(rolled)

    return success_count > 0


def _normalize_rolled(rolled: List[str]) -> None:
    """Re-render the machine frame of each branch THIS run actually rolled.

    Failures are logged, never raised: a cosmetic re-render must not retract a rollover that succeeded.
    """
    from aipass.memory.apps.handlers.monitor import registry_scope
    from aipass.memory.apps.handlers.rollover import normalizer
    from aipass.memory.apps.handlers.json import config_loader

    wanted = {name.lower() for name in rolled}
    try:
        config = config_loader.load()
        # Stops at the repo edge: normalize_branch WRITES and matches by name, so an external
        # project's branch sharing a name with one of ours would be rewritten.
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
            # The normalizer reports failure by RETURN VALUE, never raising: read its error string.
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
        # Named, never silent: a rolled branch the fleet scope cannot see.
        logger.warning(f"[rollover] Rolled but not in fleet scope, frame NOT normalized: {sorted(missing)}")
    if healed:
        logger.info(f"[rollover] Machine frame re-rendered for {healed} rolled branch(es)")


def process_plans_command() -> None:
    """Process pending plan files into vector storage in one embed + store call."""
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


def _announce_rename(old_verb: str) -> None:
    """Tell a caller of a renamed verb what it is running and why."""
    new_verb = RENAMED_VERBS[old_verb]
    console.print()
    warning(
        f"'{old_verb}' is now '{new_verb}' — it never synced anything: its only write was a "
        f"health stamp deleted from the standard on 2026-08-25. Running the reporter."
    )


def report_line_counts() -> None:
    """Report physical line counts for every branch memory file. Read-only: not the files, not the tabs."""
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


def push_defaults(json_mode: bool = False) -> None:
    """Overwrite every per_branch entry in memory.config.json with defaults."""
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


def show_status() -> None:
    """Show rollover statistics for all branches."""
    console.print()
    console.print(Panel.fit("[bold cyan]Memory - Rollover Status[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()

    stats_result = detector.get_rollover_stats()

    if not stats_result["success"]:
        error(f"Failed to get status: {stats_result.get('error', 'Unknown error')}")
        logger.error(f"[rollover] Failed to get status: {stats_result.get('error')}")
        return

    stats = stats_result

    console.print(f"[cyan]Branches:[/cyan] {stats['total_branches']}")
    console.print(f"[cyan]Files checked:[/cyan] {stats['files_checked']}")
    console.print(f"[cyan]Ready for rollover:[/cyan] {stats['files_ready']}")
    console.print(f"[cyan]Over, and rollover cannot drain them:[/cyan] {stats.get('files_undrainable', 0)}")
    console.print()

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
    """Check which branches need rollover (without executing), then ONE branch's todo pad."""
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

    # "ready for rollover" stays literal and unwrapped: @hooks' PreCompact greps this output for it.
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


def _discover_handlers() -> dict[str, list[str]]:
    """Map each handlers/ subdirectory to its .py files, __init__.py excluded."""
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
    """Display module introspection info (seedgo standard)."""
    console.print()
    console.print("[bold cyan]rollover Module[/bold cyan]")
    console.print("Orchestrates memory rollover workflow: trigger detection, extraction, embedding, and vector storage")
    console.print()

    handlers = _discover_handlers()
    console.print("[yellow]Connected Handlers:[/yellow]")
    if handlers:
        for dir_name, files in handlers.items():
            file_list = ", ".join(files)
            console.print(f"  [cyan]handlers/{dir_name}/[/cyan]  [dim]{file_list}[/dim]")
    else:
        console.print("  [dim]No handlers found[/dim]")
    console.print()

    console.print("[yellow]Subcommands:[/yellow]")
    for sub, desc in _SUBCOMMANDS.items():
        console.print(f"  [green]{sub:<14}[/green] {desc}")
    console.print()

    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @memory rollover run[/green]          [dim]# Execute rollover[/dim]")
    console.print("  [green]drone @memory rollover status[/green]       [dim]# View rollover stats[/dim]")
    console.print("  [green]drone @memory rollover check[/green]        [dim]# Dry-run check[/dim]")
    console.print("  [green]drone @memory rollover check --branch @devpulse[/green] [dim]# One branch's todo pad[/dim]")
    console.print("  [green]drone @memory rollover --help[/green]       [dim]# Full usage guide[/dim]")
    console.print()


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        handle_command("rollover", [])
        sys.exit(0)

    if sys.argv[1] in ("--help", "-h", "help"):
        handle_command("rollover", ["--help"])
        sys.exit(0)

    command = sys.argv[1]
    if not handle_command(command, sys.argv[2:]):
        error(f"Unknown command: {command}", suggestion="Run 'drone @memory rollover --help' for available commands")
        sys.exit(1)
