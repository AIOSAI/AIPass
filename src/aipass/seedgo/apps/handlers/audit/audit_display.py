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

from pathlib import Path
from typing import List, Dict
from collections import defaultdict

# =============================================================================
# INFRASTRUCTURE SETUP
# =============================================================================

# IMPORTS
# =============================================================================

# Prax logger (system-wide, always first)
from aipass.prax import logger

# CLI services (display/output formatting)
from aipass.cli import console, header
from aipass.cli.apps.modules import error, warning

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
# PUBLIC API
# =============================================================================

def print_branch_summary(audit_result: Dict, system_averages: Dict[str, int] | None = None, overall_system_avg: int = 0):
    """Print summary for a single branch - always shows full details (audit = comprehensive)"""
    json_handler.log_operation("audit_display_rendered", {"branch": audit_result['branch']['name']})
    branch = audit_result['branch']
    scores = audit_result['scores']
    avg = audit_result['average']
    cli_violations = audit_result.get('cli_violations', [])
    modules_violations = audit_result.get('modules_violations', [])
    files_checked = audit_result.get('files_checked', 0)

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

    # Always show failures (audit = comprehensive)
    results = audit_result['results']
    for standard_name, result in results.items():
        # Show issues if standard failed OR if it's architecture with violations
        has_failures = any(not check.get('passed', False) for check in result.get('checks', []))

        if not result.get('passed', False) or (standard_name == 'architecture' and has_failures):
            # Count failures for architecture
            if standard_name == 'architecture' and has_failures:
                failed_checks = [c for c in result.get('checks', []) if not c.get('passed', False)]
                warning(f"  └─ Architecture violations ({len(failed_checks)} missing):")

                # Group by type for clarity (match both "Dir:" and "Directory:" prefixes)
                missing_dirs = [c for c in failed_checks if 'Dir:' in c.get('name', '') or 'Directory:' in c.get('name', '')]
                missing_files = [c for c in failed_checks if 'File:' in c.get('name', '')]
                other_failures = [c for c in failed_checks if c not in missing_dirs and c not in missing_files]

                if missing_dirs:
                    console.print(f"       [dim]Missing directories ({len(missing_dirs)}):[/dim]")
                    for check in missing_dirs[:5]:
                        name = check.get('name', '').replace('Dir: ', '').replace('Directory: ', '')
                        console.print(f"         [red]✗[/red] {name}")
                    if len(missing_dirs) > 5:
                        console.print(f"         [dim]... and {len(missing_dirs) - 5} more[/dim]")

                if missing_files:
                    console.print(f"       [dim]Missing files ({len(missing_files)}):[/dim]")
                    for check in missing_files[:5]:
                        name = check.get('name', '').replace('File: ', '')
                        console.print(f"         [red]✗[/red] {name}")
                    if len(missing_files) > 5:
                        console.print(f"         [dim]... and {len(missing_files) - 5} more[/dim]")

                if other_failures:
                    for check in other_failures:
                        console.print(f"         [dim]• {check.get('message', '')}[/dim]")
            else:
                # Non-architecture failures - show as before
                console.print(f"    [red]└─ {standard_name.title()} issues:[/red]")
                for check in result.get('checks', []):
                    if not check.get('passed', False):
                        console.print(f"       [dim]• {check.get('message', 'Unknown error')}[/dim]")

    # Always show CLI violations (audit = comprehensive)
    # Use absolute paths for reliable VS Code clickability
    if cli_violations:
        console.print()
        console.print(f"  [bold red]CLI VIOLATIONS ({len(cli_violations)} files):[/bold red]")
        for violation in cli_violations:
            console.print(f"    [red]✗[/red] {violation['path']} [dim](score: {violation['score']}%)[/dim]")
            for issue in violation['issues']:
                console.print(f"      [dim]• {issue}[/dim]")
    elif files_checked > 0 and not cli_violations:
        console.print(f"  [green]✓ All {files_checked} files pass CLI standard[/green]")

    # Show MODULES violations (business logic in modules)
    if modules_violations:
        console.print()
        console.print(f"  [bold red]MODULES VIOLATIONS ({len(modules_violations)} files):[/bold red]")
        for violation in modules_violations:
            console.print(f"    [red]✗[/red] {violation['path']} [dim](score: {violation['score']}%)[/dim]")
            console.print(f"      [dim]• {violation['message']}[/dim]")

    # Show ENCAPSULATION violations (cross-branch/package handler imports)
    encapsulation_violations = audit_result.get('encapsulation_violations', [])
    if encapsulation_violations:
        console.print()
        console.print(f"  [bold red]ENCAPSULATION VIOLATIONS ({len(encapsulation_violations)} files):[/bold red]")
        for violation in encapsulation_violations:
            console.print(f"    [red]✗[/red] {violation['path']} [dim](score: {violation['score']}%)[/dim]")
            for issue in violation.get('issues', []):
                console.print(f"      [dim]• {issue}[/dim]")

    # Show ERROR_HANDLING violations (3-tier: entry/modules/handlers)
    error_handling_violations = audit_result.get('error_handling_violations', [])
    if error_handling_violations:
        console.print()
        console.print(f"  [bold red]ERROR_HANDLING VIOLATIONS ({len(error_handling_violations)} files):[/bold red]")
        for violation in error_handling_violations:
            console.print(f"    [red]✗[/red] {violation['path']} [dim](score: {violation['score']}%)[/dim]")
            for issue in violation.get('issues', []):
                console.print(f"      [dim]• {issue}[/dim]")

    # Show TRIGGER violations (event bus patterns in handlers)
    trigger_violations = audit_result.get('trigger_violations', [])
    if trigger_violations:
        console.print()
        console.print(f"  [bold red]TRIGGER VIOLATIONS ({len(trigger_violations)} files):[/bold red]")
        for violation in trigger_violations:
            console.print(f"    [red]✗[/red] {violation['path']} [dim](score: {violation['score']}%)[/dim]")
            for issue in violation.get('issues', []):
                console.print(f"      [dim]• {issue}[/dim]")

    # Show LOG_LEVEL violations (ERROR vs WARNING hygiene)
    log_level_violations = audit_result.get('log_level_violations', [])
    if log_level_violations:
        console.print()
        console.print(f"  [bold red]LOG_LEVEL VIOLATIONS ({len(log_level_violations)} files):[/bold red]")
        for violation in log_level_violations:
            console.print(f"    [red]✗[/red] {violation['path']} [dim](score: {violation['score']}%)[/dim]")
            for issue in violation.get('issues', []):
                console.print(f"      [dim]• {issue}[/dim]")

    # Show LOG_VISIBILITY violations (raw getLogger without prax)
    log_visibility_violations = audit_result.get('log_visibility_violations', [])
    if log_visibility_violations:
        console.print()
        console.print(f"  [bold red]LOG_VISIBILITY VIOLATIONS ({len(log_visibility_violations)} files):[/bold red]")
        for violation in log_visibility_violations:
            console.print(f"    [red]✗[/red] {violation['path']} [dim](score: {violation['score']}%)[/dim]")
            for issue in violation.get('issues', []):
                console.print(f"      [dim]• {issue}[/dim]")

    # Show JSON_STRUCTURE violations (json_handler misconfiguration)
    json_structure_violations = audit_result.get('json_structure_violations', [])
    if json_structure_violations:
        console.print()
        console.print(f"  [bold red]JSON_STRUCTURE VIOLATIONS ({len(json_structure_violations)} files):[/bold red]")
        for violation in json_structure_violations:
            console.print(f"    [red]✗[/red] {violation['path']} [dim](score: {violation['score']}%)[/dim]")
            for issue in violation.get('issues', []):
                console.print(f"      [dim]• {issue}[/dim]")

    # Show META violations (META block at top of every .py file)
    meta_violations = audit_result.get('meta_violations', [])
    if meta_violations:
        console.print()
        console.print(f"  [bold red]META VIOLATIONS ({len(meta_violations)} files):[/bold red]")
        for violation in meta_violations:
            console.print(f"    [red]✗[/red] {violation['file']} [dim](score: {violation['score']}%)[/dim]")
            for issue in violation.get('issues', []):
                console.print(f"      [dim]• {issue}[/dim]")

    # Show STDERR_ROUTING violations (console.print red/yellow → use error()/warning())
    stderr_routing_violations = audit_result.get('stderr_routing_violations', [])
    if stderr_routing_violations:
        console.print()
        console.print(f"  [bold red]STDERR_ROUTING VIOLATIONS ({len(stderr_routing_violations)} files):[/bold red]")
        for violation in stderr_routing_violations:
            console.print(f"    [red]✗[/red] {violation['path']} [dim](score: {violation['score']}%)[/dim]")
            for issue in violation.get('issues', []):
                console.print(f"      [dim]• {issue}[/dim]")

    # Show SHEBANG violations (no #!/... in pip packages)
    shebang_violations = audit_result.get('shebang_violations', [])
    if shebang_violations:
        console.print()
        console.print(f"  [bold red]SHEBANG VIOLATIONS ({len(shebang_violations)} files):[/bold red]")
        for violation in shebang_violations:
            console.print(f"    [red]✗[/red] {violation['path']} [dim](score: {violation['score']}%)[/dim]")
            for issue in violation.get('issues', []):
                console.print(f"      [dim]• {issue}[/dim]")

    # Show LOG_STRUCTURE violations (log directory/file structure)
    log_structure_violations = audit_result.get('log_structure_violations', [])
    if log_structure_violations:
        console.print()
        console.print(f"  [bold red]LOG_STRUCTURE VIOLATIONS ({len(log_structure_violations)} files):[/bold red]")
        for violation in log_structure_violations:
            console.print(f"    [red]✗[/red] {violation['path']} [dim](score: {violation['score']}%)[/dim]")
            for issue in violation.get('issues', []):
                console.print(f"      [dim]• {issue}[/dim]")

    # Show INTROSPECTION violations
    introspection_violations = audit_result.get('introspection_violations', [])
    if introspection_violations:
        console.print()
        console.print(f"  [bold red]INTROSPECTION VIOLATIONS ({len(introspection_violations)} files):[/bold red]")
        for violation in introspection_violations:
            console.print(f"    [red]✗[/red] {violation['file']} [dim](score: {violation['score']}%)[/dim]")
            for issue in violation.get('issues', []):
                console.print(f"      [dim]• {issue}[/dim]")

    # Show TYPE ERRORS (pyright diagnostics)
    type_errors = audit_result.get('type_errors', 0)
    type_error_files = audit_result.get('type_error_files', [])
    if type_errors > 0:
        console.print()
        console.print(f"  [bold red]TYPE ERRORS ({type_errors} errors):[/bold red]")
        for file_result in type_error_files[:10]:  # Top 10 files
            if file_result.get('errors', 0) > 0:
                console.print(f"    [red]✗[/red] {file_result['file']} [dim]({file_result['errors']} errors)[/dim]")
                for diag in file_result.get('diagnostics', [])[:3]:  # Top 3 per file
                    msg = diag.get('message', '')[:60]
                    console.print(f"      [dim]L{diag.get('line', '?')}: {msg}[/dim]")
    elif files_checked > 0:
        console.print(f"  [green]✓[/green] No type errors")

    # Show DEPRECATED PATTERNS (DOCUMENTS/ → docs/)
    deprecated_patterns = audit_result.get('deprecated_patterns', [])
    if deprecated_patterns:
        console.print()
        console.print(f"  [bold yellow]DEPRECATED PATTERNS ({len(deprecated_patterns)}):[/bold yellow]")
        for pattern in deprecated_patterns:
            console.print(f"    [yellow]⚠[/yellow] {pattern['path']}")
            console.print(f"      [dim]→ {pattern['message']}[/dim]")


def print_system_summary(audit_results: List[Dict]):
    """Print system-wide summary with standard averages"""
    total_branches = len(audit_results)
    avg_compliance = int(sum(r['average'] for r in audit_results) / total_branches) if total_branches else 0

    excellent = sum(1 for r in audit_results if r['average'] >= 90)
    good = sum(1 for r in audit_results if 75 <= r['average'] < 90)
    needs_work = sum(1 for r in audit_results if r['average'] < 75)

    # Calculate total type errors
    total_type_errors = sum(r.get('type_errors', 0) for r in audit_results)
    branches_with_type_errors = sum(1 for r in audit_results if r.get('type_errors', 0) > 0)

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
        console.print(f"  Type errors:           [green]0 ✓[/green]")
    console.print()

    # Calculate standard averages
    standard_scores = defaultdict(list)
    for result in audit_results:
        for standard, score in result['scores'].items():
            standard_scores[standard].append(score)

    standard_averages = {
        standard: int(sum(scores) / len(scores))
        for standard, scores in standard_scores.items()
    }

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
            branches_failing = sum(1 for r in audit_results if r['scores'].get(standard, 100) < 75)
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
        by_branch[result['branch']].append(result)

    removable_count = 0
    total_count = len(bypass_results)

    for branch_name, results in sorted(by_branch.items()):
        console.print(f"[bold cyan]{branch_name}[/bold cyan] ({len(results)} bypass{'es' if len(results) > 1 else ''})")

        for r in results:
            file_name = r['file']
            standard = r['standard']
            reason = r['reason']
            status = r['status']

            if status == 'file_missing':
                console.print(f"  [red]✗[/red] {file_name} [{standard}]")
                error("FILE MISSING - bypass can be removed")
                removable_count += 1
            elif status == 'checked':
                score = r['current_score']
                would_pass = r['would_pass']

                if would_pass:
                    console.print(f"  [green]✓[/green] {file_name} [{standard}] → {score}%")
                    console.print(f"    [green]PASSES NOW - bypass can be removed![/green]")
                    console.print(f"    [dim]Reason was: {reason}[/dim]")
                    removable_count += 1
                else:
                    console.print(f"  [yellow]⚠[/yellow] {file_name} [{standard}] → {score}%")
                    console.print(f"    [dim]Reason: {reason}[/dim]")
                    for v in r.get('violations', [])[:3]:
                        console.print(f"    [dim]• {v}[/dim]")
            elif status == 'error':
                console.print(f"  [red]✗[/red] {file_name} [{standard}]")
                console.print(f"    [red]Error: {r.get('error', 'Unknown')}[/red]")
            else:
                console.print(f"  [dim]?[/dim] {file_name} [{standard}]")
                console.print(f"    [dim]Unknown standard or status[/dim]")

        console.print()

    # Summary
    console.print("─" * 70)
    console.print(f"[bold]BYPASS SUMMARY:[/bold]")
    console.print(f"  Total bypasses:     {total_count}")
    console.print(f"  Can be removed:     {removable_count} [green]{'← clean these up!' if removable_count > 0 else ''}[/green]")
    console.print(f"  Still needed:       {total_count - removable_count}")
    console.print("─" * 70)
    console.print()
