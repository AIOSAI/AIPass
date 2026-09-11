# =================== AIPass ====================
# Name: rm.py
# Description: Module orchestrator for contained safe-delete
# Version: 1.1.1
# Created: 2026-06-02
# Modified: 2026-09-11
# =============================================

"""Module orchestrator for contained safe-delete.

Thin orchestrator that delegates to rm_handler for path containment
checks and deletion. Provider-agnostic alternative to shell ``rm``.
``--stale AGE`` in any slot selects the stale-temp sweep instead (DPLAN-0338).
"""

from __future__ import annotations

import tempfile

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, success
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.rm_handler import (
    format_age,
    format_stale_summary,
    is_stale_request,
    parse_stale_args,
    safe_delete as _safe_delete,
    stale_sweep,
)
from aipass.drone.apps.handlers.broker.client import (
    is_sandboxed as _is_sandboxed,
    broker_delete as _broker_delete,
)
from aipass.drone.apps.handlers.help_flags import wants_help

DRONE_MODULE = {
    "name": "rm",
    "version": "1.1.1",
    "description": "Contained safe-delete (project + tmp)",
}


def safe_delete(paths: list[str]) -> list[tuple[str, bool, str]]:
    """Delete paths with containment checks.

    Returns list of ``(original_path, success, message)`` tuples.
    When sandboxed (AIPASS_BROKER_FD set), routes through the broker daemon.
    """
    logger.info("rm: requested deletion of %d path(s)", len(paths))
    if _is_sandboxed():
        json_handler.log_operation("rm_broker", {"paths": paths})
        results: list[tuple[str, bool, str]] = []
        for path_str in paths:
            ok, message = _broker_delete(path_str)
            results.append((path_str, ok, message))
        return results
    return _safe_delete(paths)


def handle_command(command: str | None = None, args: list[str] | None = None) -> bool:
    """Entry point for ``drone rm`` module routing."""
    if not args:
        if command is None:
            print_introspection()
            return True
        args = []
    if wants_help(command, args):
        print_help()
        return True

    json_handler.log_operation("rm_command", {"command": command, "args": args})

    paths: list[str] = []
    if command is not None:
        paths.append(command)
    if args:
        paths.extend(args)

    if not paths:
        print_help()
        return True

    if is_stale_request(paths):
        return run_stale(paths)

    results = _safe_delete(paths)
    ok = True
    for _path_str, succeeded, message in results:
        if succeeded:
            success(message)
        else:
            error(message)
            ok = False
    return ok


def run_stale(tokens: list[str]) -> bool:
    """``drone rm --stale AGE [--dry-run] DIR...`` — sweep stale staging temps.

    The listing and the summary print with ``soft_wrap``: Rich otherwise wraps
    at 80 columns when piped, and the daemon reads this output as a captured
    tail. No markup and no highlighting: a path is data, not a style tag.
    """
    try:
        request = parse_stale_args(tokens)
    except ValueError as exc:
        error(str(exc))
        return False

    report = stale_sweep(request)
    if request.dry_run:
        for path, age, size in report.candidates:
            _plain(f"  would delete  {format_age(age):>7}  {size:>9} B  {path}")
    for message in report.refusals:
        error(message)
    _plain(format_stale_summary(request, report))
    return not report.refusals


def _plain(line: str) -> None:
    """One unwrapped, unstyled line on stdout."""
    console.print(line, soft_wrap=True, markup=False, highlight=False)


def print_introspection() -> None:
    """Display module overview (no args)."""
    console.print()
    console.print("[bold cyan]rm — Contained Safe-Delete[/bold cyan]")
    console.print()
    console.print("[dim]Deletes files and directories constrained to project root and system tmp.[/dim]")
    console.print()
    console.print("Run [green]'drone rm --help'[/green] for usage information")
    console.print()


def print_help() -> None:
    """Display help (--help flag)."""
    console.print("Usage: drone rm <path> [<path>...]")
    console.print()
    console.print("Contained safe-delete. Removes files and directories using pure Python")
    console.print("(shutil.rmtree), constrained to the project root and system temp directory.")
    console.print()
    console.print("[bold]Rules:[/bold]")
    console.print("  • Path must resolve under the project root or system temp dir")
    console.print("  • Cannot delete the project root or temp root itself")
    console.print("  • Symlinks are resolved; refuses if target escapes allowed roots")
    console.print("  • Nonexistent paths produce a clean error")
    console.print("  • Carve-outs: .git, .trinity, .aipass, .codex, .agents, other citizens' trees")
    console.print("  • A project folder that CONTAINS another citizen is refused, naming the first one")
    console.print()
    console.print("[bold]Every delete is recorded:[/bold]")
    console.print("  Successes AND refusals land in [cyan]<project>/.ai_central/deletions.jsonl[/cyan]")
    console.print("  (timestamp, caller, cwd, resolved path, size/entries) and in the prax logs")
    console.print("  at INFO. Nothing you delete through drone goes unwritten.")
    console.print()
    console.print("[bold]Stale mode — sweep old staging temps:[/bold]")
    console.print("  drone rm --stale AGE [--dry-run] DIR [DIR...]")
    console.print("  AGE is a whole number and a unit: 10d (days), 36h (hours) or 90m (minutes).")
    console.print("  Deletes ONLY regular files named *.tmp directly inside a folder whose name")
    console.print("  ends in _json, with an mtime older than AGE. Symlinks, directories and every")
    console.print("  other file are skipped. Each DIR must sit under the project root; the")
    console.print("  carve-outs stay refused and the walk never enters them.")
    console.print("  Crosses the sibling-branch fence, in this mode only: a stale staging temp is")
    console.print("  no citizen's work, and name + folder + age is the fence instead (DPLAN-0338).")
    console.print("  --dry-run lists every match with its age and size and deletes nothing.")
    console.print("  Ends with one summary line; deletes and refusals are recorded with mode stale.")
    console.print()
    _tmp = tempfile.gettempdir()
    console.print("[bold]Examples:[/bold]")
    console.print(f"  [green]drone rm {_tmp}/scratch_dir[/green]")
    console.print("  [green]drone rm build/ dist/[/green]")
    console.print(f"  [green]drone rm {_tmp}/aipass_test_abc123[/green]")
    console.print("  [green]drone rm --stale 10d --dry-run ..[/green]")
