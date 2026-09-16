# =================== AIPass ====================
# Name: lint.py
# Description: Lint module — CLI routing for entry limit auditing
# Version: 1.2.0
# Created: 2026-06-13
# Modified: 2026-09-15
# =============================================

"""
Lint Module — Entry Limit Violation Scanner

Thin CLI routing layer that discovers branches via the registry,
delegates scanning to the lint handler, and formats results for
the console.

Strictly **read-only** — never writes, modifies, truncates, or
deletes any file.

Two modes, both read-only:

    ``lint`` / ``lint run``   the canonical scan — entries over their
                             character cap.  Unchanged.
    ``lint fields``           the closed-shape INVENTORY (FPLAN-0593) —
                             every string field listed by characters, with
                             the ones outside the shape flagged.

Usage:
    drone @memory lint                    # Scan all branches
    drone @memory lint @devpulse          # Scan one branch
    drone @memory lint fields             # Field inventory, all branches
    drone @memory lint fields @devpulse   # Field inventory, one branch
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

# Handler import (same package family — json handlers)
from aipass.memory.apps.handlers.json.lint_handler import PASSPORT_FILE, run_lint, run_lint_fields

# Cross-handler access for branch discovery (module layer bridges handlers)
from aipass.memory.apps.handlers.monitor.detector import _read_registry

# The mode word, named once: the router matches it and the help prints it.
FIELDS_MODE = "fields"


# =============================================================================
# COMMAND HANDLER
# =============================================================================


def handle_command(command: str, args: list[str]) -> bool:
    """Handle lint commands with seedgo-compliant introspection.

    Routing:
        lint (no args)            -> print_introspection()
        lint --help / -h / help   -> print_help()
        lint @branch              -> scan one branch
        lint run                  -> scan all branches
        lint run @branch          -> scan one branch
        lint fields               -> field inventory, all branches
        lint fields @branch       -> field inventory, one branch

    Args:
        command: Command name.
        args: Additional arguments.

    Returns:
        True if command handled, False otherwise.
    """
    if command != "lint":
        return False

    # No args -> introspection (seedgo standard)
    if not args:
        print_introspection()
        return True

    # Help — a flag ANYWHERE wins; lint takes no free-text arguments,
    # so a bare `help` counts in any slot too
    if wants_help(args, allow_bare_word=True):
        print_help()
        return True

    # Parse optional @branch filter
    branch_filter = _extract_branch(args)

    # "run" subcommand is accepted but optional — lint always runs
    filtered_args = [a for a in args if a != "run" and not a.startswith("@")]

    # FIELDS MODE (FPLAN-0593) — additive by construction: the mode is a word
    # the old syntax never accepted, so every invocation that parsed yesterday
    # takes exactly the path it took yesterday.
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


# =============================================================================
# ARGUMENT HELPERS
# =============================================================================


def _extract_branch(args: list[str]) -> str | None:
    """Extract @branch from args, return branch name or None."""
    for arg in args:
        if arg.startswith("@"):
            return arg[1:]
    return None


def _route_fields(rest: list[str], branch_filter: str | None) -> bool:
    """Run the fields mode, refusing any argument it does not understand.

    Args:
        rest: The arguments after the ``fields`` mode word.
        branch_filter: The @branch filter already parsed off the line.

    Returns:
        True — the command is handled either way, refusal included.
    """
    if rest:
        error(
            f"Unknown lint fields argument: {rest[0]}",
            suggestion="Run 'drone @memory lint help' for usage",
        )
        return True

    _execute_lint_fields(branch_filter)
    return True


# =============================================================================
# LINT EXECUTION
# =============================================================================


def _resolve_branches(branch_filter: str | None) -> list[dict[str, Any]] | None:
    """Read the registry and validate the @branch filter against it.

    Branch discovery happens in the module layer (bridges handlers), and both
    modes come through here so an unknown branch cannot be a refusal in one of
    them and a clean bill of health in the other.

    Args:
        branch_filter: The requested branch, or None for the whole fleet.

    Returns:
        The registry rows, or None when the caller must stop — every failure
        path has already reported itself through ``error()``.
    """
    try:
        branches = _read_registry()
    except Exception as exc:
        logger.warning(f"[lint] Failed to read registry: {exc}")
        error(f"Failed to read registry: {exc}")
        return None

    if not branches:
        error("No branches found in registry")
        return None

    # An unknown branch must not read as a clean bill of health. The handlers
    # match case-insensitively, so the guard has to as well.
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
    """Run the lint scan and display results.

    Args:
        branch_filter: If provided, only lint this branch.
    """
    branches = _resolve_branches(branch_filter)
    if branches is None:
        return

    result = run_lint(branches, branch_filter=branch_filter)

    if not result.get("success"):
        error(result.get("error", "Unknown lint error"))
        return

    _display_results(result, branch_filter)


def _execute_lint_fields(branch_filter: str | None = None) -> None:
    """Run the field inventory and display results.

    Args:
        branch_filter: If provided, only inventory this branch.
    """
    branches = _resolve_branches(branch_filter)
    if branches is None:
        return

    result = run_lint_fields(branches, branch_filter=branch_filter)

    if not result.get("success"):
        error(result.get("error", "Unknown lint error"))
        return

    _display_field_results(result, branch_filter)


# =============================================================================
# DISPLAY
# =============================================================================


def _display_results(result: dict[str, Any], branch_filter: str | None) -> None:
    """Format and display lint results via Rich console.

    Args:
        result: Result dict from ``run_lint``.
        branch_filter: The branch filter used (for display context).
    """
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

    # Per-violation detail (sorted worst-first by handler)
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
        # An unmeasurable field has no honest length to print: "0/300 chars"
        # would read as compliant, which is the exact silence this violation
        # exists to break. Say what was found instead.
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


# =============================================================================
# DISPLAY — FIELDS MODE
# =============================================================================


def _field_line(row: dict[str, Any]) -> str:
    """Render one summary row: a field's worst and typical size against its cap.

    ``max`` beside ``p95`` is the whole point of the inventory — a field whose
    max is 917 and whose p95 is 12 has one bad entry, not a bad cap, and the
    two numbers say which without opening a file.
    """
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
    """Render one flagged field, saying what to DO about it.

    Four species, four sentences: a field outside the shape is removed or
    declared, a missing one is added, a wrongly-typed one is retyped, and an
    over-cap one is shortened. "Violation" alone is not an instruction.
    """
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
    """Print the per-branch field inventory, passport row first.

    Args:
        summary: Summary rows from ``run_lint_fields``.
        passports: Whole-file passport rows for the same scan.
    """
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

    # A branch with a passport but no measurable entries still gets its row —
    # an empty block says "scanned and empty", a missing one says nothing.
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
    """Format and display the field inventory via Rich console.

    Args:
        result: Result dict from ``run_lint_fields``.
        branch_filter: The branch filter used (for display context).
    """
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
        # A clean fleet says so. An empty screen is indistinguishable from a
        # scan that never ran.
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


# =============================================================================
# INTROSPECTION
# =============================================================================


def print_introspection() -> None:
    """Display module introspection (seedgo standard).

    Called when ``lint`` is invoked with no arguments.
    """
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
