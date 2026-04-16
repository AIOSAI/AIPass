# =================== AIPass ====================
# Name: audit_display.py
# Description: Audit Display Module
# Version: 1.1.0
# Created: 2026-03-05
# Modified: 2026-03-08
# =============================================

"""
Audit Display Module

Formats and prints audit results to console.
Module-level display logic for audit output.
"""

from typing import List, Dict
from collections import defaultdict

# =============================================================================
# INFRASTRUCTURE SETUP
# =============================================================================

# IMPORTS
# =============================================================================

# Prax logger (system-wide, always first)

# CLI services (display/output formatting)
from aipass.cli import console, header
from aipass.cli.apps.modules import error

# JSON handler for tracking
from aipass.seedgo.apps.handlers.json import json_handler


# =============================================================================
# INTROSPECTION
# =============================================================================


def print_introspection() -> None:
    """Display module info and connected handlers."""
    console.print()
    console.print("[bold cyan]audit_display Module[/bold cyan]")
    console.print("Formats and prints audit results to console (branch summaries, system summaries, bypass audits)")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [dim]None — this is a pure display module with no handler imports[/dim]")
    console.print()

    console.print("[yellow]Public API:[/yellow]")
    console.print("  [dim]- print_branch_summary(audit_result, system_averages, overall_system_avg)[/dim]")
    console.print("  [dim]- print_system_summary(audit_results)[/dim]")
    console.print("  [dim]- print_bypass_audit(bypass_results)[/dim]")
    console.print()

    console.print("[yellow]External Dependencies:[/yellow]")
    console.print("  [dim]- aipass.prax (logger)[/dim]")
    console.print("  [dim]- aipass.cli (console, header)[/dim]")
    console.print()

    console.print("[yellow]Consumed By:[/yellow]")
    console.print("  [dim]- modules/standards_audit.py (imports all 3 display functions)[/dim]")
    console.print()


# =============================================================================
# PRIVATE HELPERS — Generic violation rendering
# =============================================================================


def _format_standard_name(name: str) -> str:
    """Convert 'DEEP_NESTING' or 'deep_nesting' to 'Deep Nesting'."""
    return name.replace("_", " ").title()


def _render_violations(standard_name: str, violations: list, console_obj) -> None:
    """Generic renderer for standard violation lists.

    Handles both 'path' and 'file' keys (tries 'path' first, falls back to 'file').
    Shows up to 5 violations with their issues, then a 'and N more...' note.
    """
    console_obj.print()
    console_obj.print(f"  [bold red]{standard_name.upper()} VIOLATIONS ({len(violations)} files):[/bold red]")

    shown = violations[:5]
    for violation in shown:
        file_path = violation.get("path", violation.get("file", ""))
        score = violation.get("score", 0)
        console_obj.print(f"    [red]✗[/red] [magenta]{file_path}[/magenta] [dim](score: {score}%)[/dim]")
        for issue in violation.get("issues", []):
            console_obj.print(f"      [dim]• {issue}[/dim]")
        # Fallback: if no 'issues' key but 'message' exists, show that
        if not violation.get("issues") and violation.get("message"):
            console_obj.print(f"      [dim]• {violation['message']}[/dim]")

    if len(violations) > 5:
        console_obj.print(f"    [dim]... and {len(violations) - 5} more[/dim]")


def _render_architecture_violations(audit_result: dict, console_obj) -> None:
    """Special renderer for architecture standard — reads from results['checks']."""
    results = audit_result.get("results", {})
    arch_result = results.get("architecture", {})
    checks = arch_result.get("checks", [])
    failed_checks = [c for c in checks if not c.get("passed", False)]

    if not failed_checks:
        return

    console_obj.print()
    console_obj.print(f"  [bold red]ARCHITECTURE VIOLATIONS ({len(failed_checks)} missing):[/bold red]")

    # Group by type for clarity (match both "Dir:" and "Directory:" prefixes)
    missing_dirs = [c for c in failed_checks if "Dir:" in c.get("name", "") or "Directory:" in c.get("name", "")]
    missing_files = [c for c in failed_checks if "File:" in c.get("name", "")]
    other_failures = [c for c in failed_checks if c not in missing_dirs and c not in missing_files]

    if missing_dirs:
        console_obj.print(f"       [dim]Missing directories ({len(missing_dirs)}):[/dim]")
        for check in missing_dirs[:5]:
            name = check.get("name", "").replace("Dir: ", "").replace("Directory: ", "")
            console_obj.print(f"         [red]✗[/red] {name}")
        if len(missing_dirs) > 5:
            console_obj.print(f"         [dim]... and {len(missing_dirs) - 5} more[/dim]")

    if missing_files:
        console_obj.print(f"       [dim]Missing files ({len(missing_files)}):[/dim]")
        for check in missing_files[:5]:
            name = check.get("name", "").replace("File: ", "")
            console_obj.print(f"         [red]✗[/red] {name}")
        if len(missing_files) > 5:
            console_obj.print(f"         [dim]... and {len(missing_files) - 5} more[/dim]")

    if other_failures:
        for check in other_failures:
            console_obj.print(f"         [dim]• {check.get('message', '')}[/dim]")


def _render_type_errors(audit_result: dict, console_obj) -> None:
    """Special renderer for type errors (pyright diagnostics) — different structure."""
    type_errors = audit_result.get("type_errors", 0)
    type_error_files = audit_result.get("type_error_files", [])
    files_checked = audit_result.get("files_checked", 0)

    if type_errors > 0:
        console_obj.print()
        console_obj.print(f"  [bold red]TYPE ERRORS ({type_errors} errors):[/bold red]")
        for file_result in type_error_files[:10]:  # Top 10 files
            if file_result.get("errors", 0) > 0:
                console_obj.print(f"    [red]✗[/red] {file_result['file']} [dim]({file_result['errors']} errors)[/dim]")
                for diag in file_result.get("diagnostics", [])[:3]:  # Top 3 per file
                    msg = diag.get("message", "")[:60]
                    console_obj.print(f"      [dim]L{diag.get('line', '?')}: {msg}[/dim]")
    elif files_checked > 0:
        console_obj.print("  [green]✓[/green] No type errors")


def _render_test_map(audit_result: dict, console_obj) -> None:
    """Show custom function test coverage summary (informational, not scored)."""
    test_map = audit_result.get("test_map")
    if not test_map:
        return
    total = test_map.get("total_functions", 0)
    if total == 0:
        return
    tested = test_map.get("tested_functions", 0)
    branch_name = test_map.get("branch", "")
    console_obj.print(
        f"  [dim]Custom Test Opportunities: {total} public functions, {tested} tested."
        f" Run: drone @seedgo test_map @{branch_name}[/dim]"
    )


def _render_deprecated_patterns(audit_result: dict, console_obj) -> None:
    """Special renderer for deprecated patterns — different structure."""
    deprecated_patterns = audit_result.get("deprecated_patterns", [])

    if not deprecated_patterns:
        return

    console_obj.print()
    console_obj.print(f"  [bold yellow]DEPRECATED PATTERNS ({len(deprecated_patterns)}):[/bold yellow]")
    for pattern in deprecated_patterns:
        console_obj.print(f"    [yellow]⚠[/yellow] {pattern['path']}")
        console_obj.print(f"      [dim]→ {pattern['message']}[/dim]")


# =============================================================================
# PUBLIC API
# =============================================================================


def print_branch_summary(
    audit_result: Dict, system_averages: Dict[str, int] | None = None, overall_system_avg: int = 0
):
    """Print summary for a single branch - always shows full details (audit = comprehensive)"""
    json_handler.log_operation("audit_display_rendered", {"branch": audit_result["branch"]["name"]})
    branch = audit_result["branch"]
    scores = audit_result["scores"]
    avg = audit_result["average"]
    files_checked = audit_result.get("files_checked", 0)

    # Branch header - always show files checked
    console.print()
    console.print(f"[bold cyan]{branch['name']}[/bold cyan] [dim]({files_checked} files checked)[/dim]")

    # Scores in a grid
    score_items = list(scores.items())

    # Print in rows of 2
    for i in range(0, len(score_items), 2):
        left_name, left_score = score_items[i]
        left_icon = "✅" if left_score >= 90 else "⚠️" if left_score >= 75 else "❌"
        left_display = f"  {left_name.title():15} {left_score:3}% {left_icon}"

        if i + 1 < len(score_items):
            right_name, right_score = score_items[i + 1]
            right_icon = "✅" if right_score >= 90 else "⚠️" if right_score >= 75 else "❌"
            right_display = f"  {right_name.title():15} {right_score:3}% {right_icon}"
            console.print(f"{left_display}  {right_display}")
        else:
            console.print(left_display)

    # Overall score
    overall_icon = "✅" if avg >= 90 else "⚠️" if avg >= 75 else "❌"
    console.print(f"  [bold]Overall:{' ' * 8} {avg:3}% {overall_icon}[/bold]")

    # Display violation details for any standard with violations
    rendered_standards = set()
    for standard_name, score in sorted(audit_result.get("scores", {}).items()):
        if score >= 100:
            continue
        violations_key = f"{standard_name}_violations"
        violations = audit_result.get(violations_key, [])
        if standard_name == "architecture":
            _render_architecture_violations(audit_result, console)
            rendered_standards.add(standard_name)
        elif violations:
            _render_violations(standard_name, violations, console)
            rendered_standards.add(standard_name)
        else:
            # Branch-level checkers: no violations list, read from results[standard]['checks']
            result_data = audit_result.get("results", {}).get(standard_name, {})
            failed_checks = [c for c in result_data.get("checks", []) if not c.get("passed", True)]
            if failed_checks:
                formatted = _format_standard_name(standard_name)
                console.print(f"    [red]└─ {formatted} issues:[/red]")
                for check in failed_checks:
                    console.print(f"       [dim]• {check.get('message', '')}[/dim]")
                rendered_standards.add(standard_name)

    # Catch any violation lists not represented in scores (defensive)
    for key in audit_result:
        if not key.endswith("_violations"):
            continue
        standard_name = key.removesuffix("_violations")
        if standard_name in rendered_standards:
            continue
        violations = audit_result[key]
        if violations:
            _render_violations(standard_name, violations, console)

    # Type errors (separate from standards)
    _render_type_errors(audit_result, console)

    # Custom function test coverage (informational)
    _render_test_map(audit_result, console)

    # Deprecated patterns
    _render_deprecated_patterns(audit_result, console)


def print_system_summary(audit_results: List[Dict]):
    """Print system-wide summary with standard averages"""
    total_branches = len(audit_results)
    avg_compliance = int(sum(r["average"] for r in audit_results) / total_branches) if total_branches else 0

    excellent = sum(1 for r in audit_results if r["average"] >= 90)
    good = sum(1 for r in audit_results if 75 <= r["average"] < 90)
    needs_work = sum(1 for r in audit_results if r["average"] < 75)

    # Calculate total type errors
    total_type_errors = sum(r.get("type_errors", 0) for r in audit_results)
    branches_with_type_errors = sum(1 for r in audit_results if r.get("type_errors", 0) > 0)

    console.print()
    console.print("─" * 70)
    console.print("[bold]SYSTEM SUMMARY:[/bold]")
    console.print(f"  Total branches:        {total_branches}")
    console.print(f"  Average compliance:    {avg_compliance}%")
    console.print(f"  Branches ≥90%:         {excellent} ✅")
    console.print(f"  Branches 75-89%:       {good} ⚠️")
    console.print(f"  Branches <75%:         {needs_work} ❌")
    if total_type_errors > 0:
        console.print(f"  [red]Type errors:           {total_type_errors} ({branches_with_type_errors} branches)[/red]")
    else:
        console.print("  Type errors:           [green]0 ✓[/green]")
    console.print()

    # Calculate standard averages
    standard_scores = defaultdict(list)
    for result in audit_results:
        for standard, score in result["scores"].items():
            standard_scores[standard].append(score)

    standard_averages = {standard: int(sum(scores) / len(scores)) for standard, scores in standard_scores.items()}

    # Print standard averages section
    console.print("[bold]STANDARD AVERAGES:[/bold]")
    standard_items = sorted(standard_averages.items(), key=lambda x: x[0])

    # Print in rows of 2
    for i in range(0, len(standard_items), 2):
        left_name, left_avg = standard_items[i]
        left_icon = "✅" if left_avg >= 90 else "⚠️" if left_avg >= 75 else "❌"
        left_display = f"  {left_name.title():15} {left_avg:3}% {left_icon}"

        if i + 1 < len(standard_items):
            right_name, right_avg = standard_items[i + 1]
            right_icon = "✅" if right_avg >= 90 else "⚠️" if right_avg >= 75 else "❌"
            right_display = f"  {right_name.title():15} {right_avg:3}% {right_icon}"
            console.print(f"{left_display}  {right_display}")
        else:
            console.print(left_display)

    console.print()

    # Top improvement areas
    top_issues = sorted(standard_averages.items(), key=lambda x: x[1])[:3]

    if top_issues:
        console.print("[bold]TOP IMPROVEMENT AREAS:[/bold]")
        for i, (standard, avg_score) in enumerate(top_issues, 1):
            branches_failing = sum(1 for r in audit_results if r["scores"].get(standard, 100) < 75)
            console.print(f"  {i}. {standard.title():15} (avg: {avg_score}%, {branches_failing} branches <75%)")

    console.print("─" * 70)
    console.print()


def print_bypass_audit(bypass_results: List[Dict]):
    """Print bypass audit results"""
    if not bypass_results:
        console.print("[green]No bypasses configured in any branch[/green]")
        return

    console.print()
    header("BYPASS AUDIT - Current State of Bypassed Files")
    console.print()

    # Group by branch
    by_branch = defaultdict(list)
    for result in bypass_results:
        by_branch[result["branch"]].append(result)

    removable_count = 0
    total_count = len(bypass_results)

    for branch_name, results in sorted(by_branch.items()):
        console.print(f"[bold cyan]{branch_name}[/bold cyan] ({len(results)} bypass{'es' if len(results) > 1 else ''})")

        for r in results:
            file_name = r["file"]
            standard = r["standard"]
            reason = r["reason"]
            status = r["status"]

            if status == "file_missing":
                console.print(f"  [red]✗[/red] {file_name} [{standard}]")
                error("FILE MISSING - bypass can be removed")
                removable_count += 1
            elif status == "checked":
                score = r["current_score"]
                would_pass = r["would_pass"]

                if would_pass:
                    console.print(f"  [green]✓[/green] {file_name} [{standard}] → {score}%")
                    console.print("    [green]PASSES NOW - bypass can be removed![/green]")
                    console.print(f"    [dim]Reason was: {reason}[/dim]")
                    removable_count += 1
                else:
                    console.print(f"  [yellow]⚠[/yellow] {file_name} [{standard}] → {score}%")
                    console.print(f"    [dim]Reason: {reason}[/dim]")
                    for v in r.get("violations", [])[:3]:
                        console.print(f"    [dim]• {v}[/dim]")
            elif status == "error":
                console.print(f"  [red]✗[/red] {file_name} [{standard}]")
                console.print(f"    [red]Error: {r.get('error', 'Unknown')}[/red]")
            else:
                console.print(f"  [dim]?[/dim] {file_name} [{standard}]")
                console.print("    [dim]Unknown standard or status[/dim]")

        console.print()

    # Summary
    console.print("─" * 70)
    console.print("[bold]BYPASS SUMMARY:[/bold]")
    console.print(f"  Total bypasses:     {total_count}")
    console.print(
        f"  Can be removed:     {removable_count} [green]{'← clean these up!' if removable_count > 0 else ''}[/green]"
    )
    console.print(f"  Still needed:       {total_count - removable_count}")
    console.print("─" * 70)
    console.print()
