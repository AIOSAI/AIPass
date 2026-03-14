# =================== AIPass ====================
# Name: standards_audit.py
# Description: Standards Audit Module
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Standards Audit Module

Scans all AIPass branches and generates compliance dashboard.
Shows per-branch scores, system-wide metrics, and top issues.

Run: seedgo audit
"""

import sys
from pathlib import Path
from typing import List
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

# Audit handlers (implementation)
from aipass.seedgo.apps.handlers.audit.discovery import discover_branches, _is_branch_private, check_internal_access
from aipass.seedgo.apps.handlers.audit.branch_audit import audit_branch
from aipass.seedgo.apps.handlers.audit.audit_display import print_branch_summary, print_system_summary, print_bypass_audit

# Bypass system
from aipass.seedgo.apps.handlers.bypass.bypass_handler import load_bypass_rules

# Drone services for @ resolution
from aipass.drone.apps.modules import normalize_branch_arg


# =============================================================================
# COMMAND HANDLER
# =============================================================================

def _discover_packs() -> dict:
    """Discover available checker packs from handlers/ directory.

    Convention: directories named *_standards/ containing *_check.py files.
    Pack display name strips the _standards suffix.

    Returns:
        Dict mapping pack name to Path, e.g. {"aipass": Path("handlers/aipass_standards")}
    """
    handlers_dir = Path(__file__).parent.parent / "handlers"
    packs = {}
    if not handlers_dir.exists():
        return packs
    for d in sorted(handlers_dir.iterdir()):
        if not d.is_dir():
            continue
        if not d.name.endswith("_standards"):
            continue
        # Must contain at least one *_check.py at top level
        check_files = list(d.glob("*_check.py"))
        if check_files:
            pack_name = d.name.removesuffix("_standards")
            packs[pack_name] = d
    return packs


def _show_audit_introspection() -> None:
    """Show available packs and example commands when audit is run with no args."""
    packs = _discover_packs()
    console.print()
    header("SEEDGO AUDIT")
    console.print()

    if not packs:
        warning("No checker packs found.")
        console.print("[dim]Add *_check.py files to handlers/*_standards/ directories.[/dim]")
        console.print()
        return

    console.print("[yellow]Available Checker Packs:[/yellow]")
    console.print()
    for name, pack_path in packs.items():
        check_files = list(pack_path.glob("*_check.py"))
        console.print(f"  [cyan]{name}[/cyan]  ({len(check_files)} checker{'s' if len(check_files) != 1 else ''})")
    console.print()

    console.print("[yellow]Next:[/yellow]  Pick a pack to audit")
    first_pack = next(iter(packs))
    console.print(f"  [green]drone @seedgo audit {first_pack}[/green]              [dim]# All branches[/dim]")
    console.print(f"  [green]drone @seedgo audit {first_pack} flow[/green]         [dim]# Single branch[/dim]")
    console.print()


def print_introspection() -> None:
    """Display module info and connected handlers."""
    console.print()
    console.print("[bold cyan]standards_audit Module[/bold cyan]")
    console.print("Pack-aware audit — scans branches against checker packs")
    console.print()

    # Show discovered packs
    packs = _discover_packs()
    console.print("[yellow]Discovered Packs:[/yellow]")
    for name, pack_path in packs.items():
        check_files = list(pack_path.glob("*_check.py"))
        console.print(f"  [cyan]{name}[/cyan]  ({len(check_files)} checker{'s' if len(check_files) != 1 else ''})")
    if not packs:
        console.print("  [dim]No packs found[/dim]")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/audit/[/cyan]")
    console.print("    [dim]- discovery.py (discover_branches, _is_branch_private, check_internal_access)[/dim]")
    console.print("    [dim]- branch_audit.py (audit_branch — per-branch standards scoring)[/dim]")
    console.print()
    console.print("  [cyan]handlers/config/[/cyan]")
    console.print("    [dim]- bypass_handler.py (load_bypass_rules — .seedgo/bypass.json)[/dim]")
    console.print()
    console.print("  [cyan]handlers/json/[/cyan]")
    console.print("    [dim]- json_handler.py (log_operation — audit tracking)[/dim]")
    console.print()

    console.print("[yellow]Connected Display Modules:[/yellow]")
    console.print("  [cyan]modules/[/cyan]")
    console.print("    [dim]- audit_display.py (print_branch_summary, print_system_summary, print_bypass_audit)[/dim]")
    console.print()

    console.print("[yellow]External Dependencies:[/yellow]")
    console.print("  [dim]- aipass.prax (logger)[/dim]")
    console.print("  [dim]- aipass.cli (console, header)[/dim]")
    console.print("  [dim]- aipass.drone (normalize_branch_arg — @ resolution)[/dim]")
    console.print()

    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @seedgo audit aipass[/green]            [dim]# Full audit[/dim]")
    console.print("  [green]drone @seedgo audit aipass @flow[/green]      [dim]# Single branch[/dim]")
    console.print("  [green]drone @seedgo audit --help[/green]            [dim]# Full usage guide[/dim]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle 'audit' command with pack-aware routing.

    Args:
        command: Command name
        args: Additional arguments
            [] → show audit introspection (available packs)
            ["aipass"] → pack="aipass", branch=None (all branches)
            ["aipass", "flow"] → pack="aipass", branch="FLOW"
            ["--help"] → general help

    Returns:
        True if handled, False if not this module's command
    """
    if command not in ("audit", "standards_audit"):
        return False

    # No args → show audit introspection (available packs)
    if not args:
        _show_audit_introspection()
        return True

    # --help → general help
    if args[0] in ["--help", "-h", "help"]:
        print_help()
        return True

    # Parse pack name (first non-flag arg) and branch name (second non-flag arg)
    pack_name = None
    specific_branch = None
    show_bypasses = False

    positional = []
    for arg in args:
        if arg in ['--show-bypasses', '--bypasses', '-b']:
            show_bypasses = True
        elif arg in ['--help', '-h', 'help']:
            # Pack-specific help (placeholder)
            print_help()
            return True
        elif not arg.startswith('-'):
            positional.append(arg)

    if len(positional) >= 1:
        pack_name = positional[0]
    if len(positional) >= 2:
        specific_branch = normalize_branch_arg(positional[1])

    # Validate pack name
    packs = _discover_packs()
    if pack_name not in packs:
        available = ", ".join(packs.keys())
        error(
            f"Unknown pack: '{pack_name}'",
            suggestion=f"Available packs: {available}. Usage: drone @seedgo audit {next(iter(packs), '<pack>')}"
        )
        return True

    pack_path = packs[pack_name]

    # Handle --show-bypasses mode (placeholder — bypass audit merged into audit per D11)
    if show_bypasses:
        warning("--show-bypasses not yet implemented in seedgo")
        return True

    # =========================================================================
    # PRIVATE BRANCH ACCESS CONTROL
    # =========================================================================
    # If targeting a private branch directly, only allow audit from inside
    # that branch's directory. This enforces isolation per DPLAN-035.
    if specific_branch and _is_branch_private(specific_branch):
        if not check_internal_access(specific_branch):
            console.print(
                f"[red]Branch '{specific_branch}' is private "
                f"— audit access restricted to internal use only[/red]"
            )
            return True

    # Log audit start
    json_handler.log_operation(
        "standards_audit_started",
        {"pack": pack_name, "specific_branch": specific_branch}
    )

    # Discover branches
    # When targeting a specific private branch from inside its CWD,
    # include private branches in discovery so we can find it
    _include_private = specific_branch is not None and _is_branch_private(specific_branch)
    console.print()
    header(f"{pack_name.upper()} BRANCH STANDARDS AUDIT")
    console.print()

    branches = discover_branches(include_private=_include_private)

    if specific_branch:
        branches = [b for b in branches if b['name'].upper() == specific_branch.upper()]
        if not branches:
            console.print(f"[red]Branch '{specific_branch}' not found[/red]")
            return True

    console.print(f"[dim]Discovered {len(branches)} branches to audit...[/dim]")

    # Audit all branches (always full - checks all files)
    audit_results = []
    for branch in branches:
        console.print(f"[dim]Auditing {branch['name']}...[/dim]", end="\r")

        # Load bypass rules for this branch
        bypass_rules = load_bypass_rules(branch['path'])

        result = audit_branch(branch, bypass_rules, pack_path=pack_path)
        audit_results.append(result)

    console.print(" " * 50, end="\r")  # Clear progress line

    # Calculate system-wide averages for each standard
    standard_scores = defaultdict(list)
    for result in audit_results:
        for standard, score in result['scores'].items():
            standard_scores[standard].append(score)

    system_averages = {
        standard: int(sum(scores) / len(scores))
        for standard, scores in standard_scores.items()
    }

    overall_system_avg = int(sum(r['average'] for r in audit_results) / len(audit_results)) if audit_results else 0

    # Print results with system averages
    for result in audit_results:
        print_branch_summary(result, system_averages, overall_system_avg)

    # Print system summary (unless specific branch)
    if not specific_branch:
        print_system_summary(audit_results)

    # Log completion
    json_handler.log_operation(
        "standards_audit_completed",
        {
            "pack": pack_name,
            "branches_audited": len(audit_results),
            "average_compliance": int(sum(r['average'] for r in audit_results) / len(audit_results)) if audit_results else 0
        }
    )

    return True


def print_help():
    """Print help information"""
    console.print()
    console.print("[bold cyan]Standards Audit Module[/bold cyan]")
    console.print("Pack-aware audit — check compliance across all branches")
    console.print()

    console.print("[yellow]COMMANDS:[/yellow]")
    console.print("  [green]drone @seedgo audit[/green]                      [dim]Show available packs[/dim]")
    console.print("  [green]drone @seedgo audit aipass[/green]               [dim]All branches, aipass pack[/dim]")
    console.print("  [green]drone @seedgo audit aipass flow[/green]          [dim]Single branch[/dim]")
    console.print("  [green]drone @seedgo audit --help[/green]               [dim]This help message[/dim]")
    console.print()

    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]# Full system audit (all branches, aipass pack)[/dim]")
    console.print("  [green]drone @seedgo audit aipass[/green]")
    console.print()
    console.print("  [dim]# Audit specific branch[/dim]")
    console.print("  [green]drone @seedgo audit aipass spawn[/green]")
    console.print()

    console.print("[yellow]REFERENCE:[/yellow]")
    console.print("  Pack name is REQUIRED. Auto-discovers checkers from pack's handler directory.")
    console.print("  Shows per-branch scores, system-wide metrics, and top issues.")
    console.print()


if __name__ == "__main__":
    # Handle help flag
    if len(sys.argv) > 1 and sys.argv[1] in ['--help', '-h', 'help']:
        print_help()
        sys.exit(0)

    # Confirm Prax logger connection
    logger.info("Prax logger connected to standards_audit")

    # Log standalone execution
    json_handler.log_operation(
        "audit_run",
        {"command": "standalone", "args": sys.argv[1:]}
    )

    # Run audit
    handle_command("audit", sys.argv[1:])
