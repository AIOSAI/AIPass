# =================== AIPass ====================
# Name: lint.py
# Description: Lint module — CLI routing for entry limit auditing
# Version: 1.2.0
# Created: 2026-06-13
# Modified: 2026-10-17
# =============================================

"""
Lint Module — Entry Limit Violation Scanner
"""

import os
import sys
from typing import Any

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, success, warning
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.cli.help_flags import wants_help

from aipass.memory.apps.handlers.json.lint_handler import PASSPORT_FILE, run_lint, run_lint_fields

# read_scope, not _read_registry: lint never writes, so externals are in scope.
from aipass.memory.apps.handlers.monitor.detector import read_scope

FIELDS_MODE = "fields"


def handle_command(command: str, args: list[str]) -> bool:
    """Handle lint commands: no args introspects, ``run`` is optional, ``fields`` is the inventory."""
    if command != "lint":
        return False

    if not args:
        print_introspection()
        return True

    # lint takes no free text, so a bare `help` counts in any slot.
    if wants_help(args, allow_bare_word=True):
        print_help()
        return True

    branch_filter = _extract_branch(args)

    filtered_args = [a for a in args if a != "run" and not a.startswith("@")]

    if filtered_args and filtered_args[0] == FIELDS_MODE:
        return _route_fields(filtered_args[1:], branch_filter)

    if filtered_args:
        error(
            f"Unknown lint argument: {filtered_args[0]}",
            suggestion="Run 'drone @memory lint help' for usage",
        )
        return True

    _execute_lint(branch_filter)
    return True


def _extract_branch(args: list[str]) -> str | None:
    """Extract @branch from args, return branch name or None."""
    for arg in args:
        if arg.startswith("@"):
            return arg[1:]
    return None


def _route_fields(rest: list[str], branch_filter: str | None) -> bool:
    """Run the fields mode, refusing any argument it does not understand."""
    if rest:
        error(
            f"Unknown lint fields argument: {rest[0]}",
            suggestion="Run 'drone @memory lint help' for usage",
        )
        return True

    _execute_lint_fields(branch_filter)
    return True


def _resolve_branches(branch_filter: str | None) -> list[dict[str, Any]] | None:
    """Read the fleet and validate @branch; None means stop (already reported).

    Both modes come through here so an unknown branch cannot pass in one of them.
    """
    try:
        branches = read_scope()
    except Exception as exc:
        logger.warning(f"[lint] Failed to read registry: {exc}")
        error(f"Failed to read registry: {exc}")
        return None

    if not branches:
        error("No branches found in registry")
        return None

    # Case-insensitive because the handlers match that way.
    if branch_filter:
        known = {str(b.get("name", "")).lower() for b in branches}
        if branch_filter.lower() not in known:
            logger.warning(f"[lint] Unknown branch requested: {branch_filter}")
            error(
                f"Unknown branch: @{branch_filter}",
                suggestion="Run 'drone systems' to list branches, or 'drone @memory lint run' to scan all",
            )
            return None

    return branches


def _execute_lint(branch_filter: str | None = None) -> None:
    """Run the lint scan and display results."""
    branches = _resolve_branches(branch_filter)
    if branches is None:
        return

    result = run_lint(branches, branch_filter=branch_filter)

    if not result.get("success"):
        error(result.get("error", "Unknown lint error"))
        return

    _display_results(result, branch_filter)


def _execute_lint_fields(branch_filter: str | None = None) -> None:
    """Run the field inventory and display results."""
    branches = _resolve_branches(branch_filter)
    if branches is None:
        return

    result = run_lint_fields(branches, branch_filter=branch_filter)

    if not result.get("success"):
        error(result.get("error", "Unknown lint error"))
        return

    _display_field_results(result, branch_filter)


def _display_results(result: dict[str, Any], branch_filter: str | None) -> None:
    """Format and display lint results via Rich console."""
    violations = result.get("violations", [])
    scanned = result.get("branches_scanned", 0)
    skipped = result.get("branches_skipped", 0)
    total = result.get("total_violations", 0)

    console.print()

    if not violations:
        scope = f"@{branch_filter}" if branch_filter else "all branches"
        success(f"No violations found across {scope} ({scanned} scanned)")
        console.print()
        return

    warning(f"{total} violation(s) found")
    console.print()

    current_branch: str | None = None
    branch_count = 0

    for v in violations:
        branch = v["branch"]
        if branch != current_branch:
            if current_branch is not None:
                console.print()
            console.print(f"  [bold cyan]{branch}[/bold cyan]")
            current_branch = branch
            branch_count = 0

        branch_count += 1
        # No honest length to print here: "0/300 chars" would read as compliant.
        if v.get("reason") == "missing_field":
            console.print(
                f"    [red]![/red] {v['file']}:{v['container']}/{v['key']} "
                f"[dim]({v['entry_type']})[/dim] "
                f"[red]NO '{v.get('field', '?')}' FIELD[/red] — rename it to the canonical key "
                f"[dim](cap {v['cap']} chars cannot be applied)[/dim]"
            )
        elif v.get("reason") == "unmeasurable":
            console.print(
                f"    [red]![/red] {v['file']}:{v['container']}/{v['key']} "
                f"[dim]({v['entry_type']})[/dim] "
                f"[red]UNMEASURABLE[/red] — {v.get('found_type', 'unknown')}, expected str "
                f"[dim](cap {v['cap']} chars cannot be applied)[/dim]"
            )
        else:
            console.print(
                f"    [red]![/red] {v['file']}:{v['container']}/{v['key']} "
                f"[dim]({v['entry_type']})[/dim] "
                f"{v['length']}/{v['cap']} chars "
                f"[red]+{v['over_by']} over[/red]"
            )

    console.print()
    console.print(f"[dim]Scanned {scanned} branch(es), skipped {skipped}[/dim]")
    console.print()

    json_handler.log_operation(
        "lint_display",
        {"total_violations": total, "branches_scanned": scanned},
        module_name="lint",
    )


def _field_line(row: dict[str, Any]) -> str:
    """Render one summary row: max beside p95 tells one bad entry from a bad cap."""
    cap = str(row["cap"]) if row["cap"] else "-"
    line = (
        f"      {row['field'][:16]:<16} max {row['max']:>5}/{cap:<5} "
        f"p95 {row['p95']:>5}  [dim]{row['units']}, n={row['count']}[/dim]"
    )
    if row["flagged"]:
        return line + f"  [red]! {row['flagged']} outside shape (worst +{row['worst_over']})[/red]"
    if row["canonical"]:
        return line + "  [dim]canonical[/dim]"
    return line


def _passport_line(row: dict[str, Any]) -> str:
    """Render one branch's passport against its whole-file budget."""
    cap = row.get("cap", 0)
    over = max(0, row.get("length", 0) - cap) if cap else 0
    line = f"      {'passport.json':<16} {row.get('length', 0)}/{cap or '-'} chars"
    if over:
        line += f"  [red]+{over} over[/red]"
    if row.get("oversized_strings"):
        line += f"  [red]! {row['oversized_strings']} string(s) over {row.get('string_cap', 0)}[/red]"
    return line


def _flag_line(violation: dict[str, Any]) -> str:
    """Render one flagged field, saying what to DO about it."""
    where = f"{violation.get('file', '')}:{violation.get('container', '')}/{violation.get('key', '')}"
    label = f"[dim]({violation.get('entry_type', '')})[/dim]"
    field = violation.get("field", "?")
    reason = violation.get("reason", "")

    if reason == "file_over_budget":
        return (
            f"    [red]![/red] {violation.get('file', '')} [dim](whole file)[/dim] "
            f"{violation.get('length', 0)}/{violation.get('cap', 0)} chars "
            f"[red]+{violation.get('over_by', 0)} over[/red]"
        )
    if violation.get("entry_type") == PASSPORT_FILE:
        return (
            f"    [red]![/red] {violation.get('file', '')}:{field} "
            f"{violation.get('length', 0)}/{violation.get('cap', 0)} chars "
            f"[red]+{violation.get('over_by', 0)} over[/red]"
        )
    if reason == "unknown_field":
        return (
            f"    [red]![/red] {where} {label} [red]'{field}' NOT IN SHAPE[/red] — "
            f"{violation.get('length', 0)} chars; remove it or declare it in memory.config.json"
        )
    if reason == "missing_field":
        return f"    [red]![/red] {where} {label} [red]NO '{field}' FIELD[/red] — the shape requires it"
    if reason == "unmeasurable":
        return (
            f"    [red]![/red] {where} {label} "
            f"[red]'{field}' is {violation.get('found_type', 'unknown')}[/red] — not the declared type"
        )
    return (
        f"    [red]![/red] {where} {label} '{field}' "
        f"{violation.get('length', 0)}/{violation.get('cap', 0)} {violation.get('units', 'chars')} "
        f"[red]+{violation.get('over_by', 0)} over[/red]"
    )


def _print_inventory(summary: list[dict[str, Any]], passports: list[dict[str, Any]]) -> None:
    """Print the per-branch field inventory, passport row first."""
    pending = {row["branch"]: row for row in passports}
    current_branch: str | None = None
    current_type: str | None = None

    for row in summary:
        if row["branch"] != current_branch:
            if current_branch is not None:
                console.print()
            console.print(f"  [bold cyan]{row['branch']}[/bold cyan]")
            current_branch, current_type = row["branch"], None
            passport = pending.pop(row["branch"], None)
            if passport is not None:
                console.print(_passport_line(passport))
        if row["entry_type"] != current_type:
            current_type = row["entry_type"]
            console.print(f"    [yellow]{current_type}[/yellow] [dim]{row['file']}[/dim]")
        console.print(_field_line(row))

    # A passport-only branch still gets its row: absence would say nothing.
    for row in pending.values():
        console.print()
        console.print(f"  [bold cyan]{row['branch']}[/bold cyan]")
        console.print(_passport_line(row))


def _print_flags(violations: list[dict[str, Any]]) -> None:
    """Print flagged fields worst-first, grouped by branch as the walk meets them."""
    current_branch: str | None = None
    for violation in violations:
        branch = violation.get("branch", "")
        if branch != current_branch:
            if current_branch is not None:
                console.print()
            console.print(f"  [bold cyan]{branch}[/bold cyan]")
            current_branch = branch
        console.print(_flag_line(violation))


def _display_field_results(result: dict[str, Any], branch_filter: str | None) -> None:
    """Format and display the field inventory via Rich console."""
    summary = result.get("summary", [])
    violations = result.get("violations", [])
    passports = result.get("passport", [])
    scanned = result.get("branches_scanned", 0)
    skipped = result.get("branches_skipped", 0)
    scope = f"@{branch_filter}" if branch_filter else "all branches"

    console.print()

    if not summary and not passports and not violations:
        warning(f"No .trinity fields to measure across {scope} ({scanned} scanned)")
        console.print()
        return

    _print_inventory(summary, passports)
    console.print()

    if violations:
        warning(f"{len(violations)} field(s) outside the shape")
        console.print()
        _print_flags(violations)
    else:
        success(f"No fields outside the shape across {scope} ({scanned} scanned)")

    console.print()
    console.print(
        f"[dim]Scanned {scanned} branch(es), skipped {skipped} — "
        f"{result.get('total_fields', 0)} field measurement(s)[/dim]"
    )
    console.print()

    json_handler.log_operation(
        "lint_fields_display",
        {"total_violations": len(violations), "branches_scanned": scanned},
        module_name="lint",
    )


def print_introspection() -> None:
    """Display module introspection (seedgo standard)."""
    console.print()
    console.print("[bold cyan]lint Module[/bold cyan]")
    console.print("Audits .trinity entries for over-limit character violations (read-only)")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/json/[/cyan]  [dim]lint_handler.py, entry_limits.py[/dim]")
    console.print()

    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @memory lint run[/green]          [dim]# Scan all branches[/dim]")
    console.print("  [green]drone @memory lint @devpulse[/green]    [dim]# Scan one branch[/dim]")
    console.print("  [green]drone @memory lint fields[/green]       [dim]# Field inventory vs the closed shape[/dim]")
    console.print("  [green]drone @memory lint help[/green]         [dim]# Full usage guide[/dim]")
    console.print()


def print_help() -> None:
    """Display lint module help."""
    console.print()
    console.print("[bold cyan]Lint Module - Entry Limit Violation Scanner[/bold cyan]")
    console.print()
    console.print("[bold]USAGE:[/bold]")
    console.print("  drone @memory lint                    Scan all branches")
    console.print("  drone @memory lint @<branch>          Scan a specific branch")
    console.print("  drone @memory lint run                Scan all branches (explicit)")
    console.print("  drone @memory lint fields             Field inventory, all branches")
    console.print("  drone @memory lint fields @<branch>   Field inventory, one branch")
    console.print()
    console.print("[bold]WHAT IT DOES:[/bold]")
    console.print("  Reads .trinity/local.json and .trinity/observations.json for every")
    console.print("  registered branch. Checks each entry against configured character")
    console.print("  caps from memory.config.json. Reports violations sorted worst-first.")
    console.print()
    console.print("[bold]FIELDS MODE:[/bold]")
    console.print("  [cyan]lint fields[/cyan] measures every OTHER field against the closed shape")
    console.print("  (entry_types.<type>.fields in memory.config.json): every string field")
    console.print("  is listed by characters with max and p95 beside its cap, and anything")
    console.print("  outside the shape is flagged — unknown fields, missing required ones,")
    console.print("  wrong types, and fields over their own cap or item count.")
    console.print("  The passport row comes with it: the whole file against 6,000 chars and")
    console.print("  any single string in it against 600.")
    console.print("  The canonical field is listed but not flagged here — [cyan]lint run[/cyan] owns it,")
    console.print("  so no entry is ever reported twice for one defect.")
    console.print()
    console.print("[bold]NOTE:[/bold]")
    console.print("  This command is strictly [green]read-only[/green]. It never modifies any file.")
    console.print()
