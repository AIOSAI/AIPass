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
import time
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
from aipass.seedgo.apps.handlers.audit.branch_audit import audit_branch_incremental
from aipass.seedgo.apps.handlers.audit.audit_display import print_branch_summary, print_system_summary
from aipass.seedgo.apps.handlers.audit.artifact import write_audit_artifact

# Bypass system
from aipass.seedgo.apps.handlers.bypass.bypass_handler import load_bypass_rules
from aipass.seedgo.apps.handlers.cli.help_flags import DASHED_HELP_TOKENS

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
    console.print(f"  [green]drone @seedgo audit {first_pack} @flow[/green]        [dim]# Single branch[/dim]")
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
    console.print("    [dim]- artifact.py (write_audit_artifact — complete result set to JSON)[/dim]")
    console.print()
    console.print("  [cyan]handlers/config/[/cyan]")
    console.print("    [dim]- bypass_handler.py (load_bypass_rules — .seedgo/bypass.json)[/dim]")
    console.print()
    console.print("  [cyan]handlers/json/[/cyan]")
    console.print("    [dim]- json_handler.py (log_operation — audit tracking)[/dim]")
    console.print()

    console.print("[yellow]Connected Display Modules:[/yellow]")
    console.print("  [cyan]modules/[/cyan]")
    console.print("    [dim]- audit_display.py (print_branch_summary, print_system_summary)[/dim]")
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


def _emit_artifact(
    audit_results: List[dict], artifact_path, pack_name: str, specific_branch: str | None, no_bypass: bool = False
):
    """Write the complete-violation-set artifact and announce its path.

    The display truncates by design; this file does not. Telling the user where
    it landed is what makes it discoverable — one dim line, never a banner.

    The line names the SCOPE as well as the path. Naming only the path invites a
    consumer to read a single-branch document as if it covered the fleet, which
    is the same silent-and-plausible failure the artifact exists to end. A
    --no-bypass run is the same hazard one step further on — same tree, same
    pack, lower numbers — so it says so here and lands in its own file.

    A write failure is reported loudly and never re-raised: the artifact is a
    side channel, so a full-disk or bad --artifact path must not swallow the
    audit the user actually asked for. Returns the Path, or None on failure.
    """
    try:
        written = write_audit_artifact(
            audit_results,
            output_path=artifact_path,
            pack=pack_name,
            specific_branch=specific_branch,
            no_bypass=no_bypass,
        )
    except Exception as e:
        logger.error("[standards_audit] Audit artifact write failed for %s: %s", artifact_path, e)
        error(
            f"Could not write audit artifact: {e}",
            suggestion="Audit results above are still valid. Check the path is writable, or pass --no-artifact.",
        )
        return None
    scope = f"single-branch: {specific_branch}" if specific_branch else "full-fleet"
    if no_bypass:
        scope += ", BYPASSES DISABLED"
    console.print(f"[dim]Complete violation set (untruncated, {scope}): {written}[/dim]")
    console.print()
    return written


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
    no_bypass = False
    force_full = False
    write_artifact = True
    artifact_path = None
    expect_artifact_path = False

    positional = []
    for arg in args:
        # Before the value slots, never after: a flag consumed as a destination
        # path is a flag nobody reads. '--artifact --help' wrote the artifact to
        # a file named '--help' and ran the whole audit to fill it.
        if arg in DASHED_HELP_TOKENS:
            print_help()
            return True
        if expect_artifact_path:
            artifact_path = arg
            expect_artifact_path = False
            continue
        if arg in ["--show-bypasses", "--bypasses", "-b"]:
            show_bypasses = True
            continue
        if arg == "--no-bypass":
            no_bypass = True
            continue
        if arg == "--full":
            force_full = True
            continue
        if arg == "--artifact":
            expect_artifact_path = True
            continue
        if arg.startswith("--artifact="):
            artifact_path = arg.split("=", 1)[1]
            continue
        if arg == "--no-artifact":
            write_artifact = False
            continue
        if arg in ["--help", "-h", "help"]:
            # Pack-specific help (placeholder)
            print_help()
            return True
        if not arg.startswith("-"):
            positional.append(arg)

    if expect_artifact_path:
        error(
            "--artifact needs a destination path",
            suggestion="Usage: drone @seedgo audit aipass --artifact <path>",
        )
        return True

    if len(positional) >= 1:
        if positional[0].startswith("@"):
            pack_name = "aipass"
            specific_branch = normalize_branch_arg(positional[0])
        else:
            pack_name = positional[0]
    if len(positional) >= 2 and specific_branch is None:
        branch_arg = positional[1]
        if not branch_arg.startswith("@"):
            error(
                f"Branch name must use @ prefix: '@{branch_arg}'",
                suggestion=f"Usage: drone @seedgo audit {pack_name} @{branch_arg}",
            )
            return True
        specific_branch = normalize_branch_arg(branch_arg)

    # Validate pack name
    packs = _discover_packs()
    if pack_name is None or pack_name not in packs:
        available = ", ".join(packs.keys())
        error(
            f"Unknown pack: '{pack_name}'",
            suggestion=f"Available packs: {available}. Usage: drone @seedgo audit {next(iter(packs), '<pack>')}",
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
                f"[red]Branch '{specific_branch}' is private — audit access restricted to internal use only[/red]"
            )
            return True

    # Log audit start
    json_handler.log_operation("standards_audit_started", {"pack": pack_name, "specific_branch": specific_branch})

    # Discover branches
    # When targeting a specific private branch from inside its CWD,
    # include private branches in discovery so we can find it
    _include_private = specific_branch is not None and _is_branch_private(specific_branch)
    console.print()
    header(f"{pack_name.upper()} BRANCH STANDARDS AUDIT")
    console.print()

    # Any suppression announces itself, and this one inverts the meaning of every
    # number below it — an unlabelled --no-bypass run reads as a branch that just
    # got worse. Said here, again next to the scores in the summary, and recorded
    # in the artifact's metadata, because each of those is copied out on its own.
    if no_bypass:
        console.print("[bold yellow]BYPASSES DISABLED[/bold yellow] [dim](--no-bypass) — every rule ignored[/dim]")
        console.print("[dim]Raw scores. Not comparable with a normal audit; expect them to read lower.[/dim]")
        console.print()

    branches = discover_branches(include_private=_include_private)

    if specific_branch:
        branches = [b for b in branches if b["name"].upper() == specific_branch.upper()]
        if not branches:
            error(f"Branch '{specific_branch}' not found")
            return True

    from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, SpinnerColumn

    is_compact = specific_branch is None  # Full audit = compact, single branch = detailed

    total_branches = len(branches)
    console.print(f"[dim]Discovered {total_branches} branch{'es' if total_branches != 1 else ''} to audit...[/dim]")
    console.print()

    # Audit all branches with live progress
    audit_results = []
    audit_start = time.monotonic()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        # Elapsed ticks continuously — remaining-time estimates froze on the
        # bimodal cache workload (12 branches at 0.2s, then a 40s fresh one).
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Scanning...", total=total_branches)

        for idx, branch in enumerate(branches, 1):
            branch_name = branch["name"]
            progress.update(task, description=f"[cyan]{branch_name}[/cyan]")

            # Load bypass rules for this branch — unless --no-bypass, where the
            # whole point is to score the branch as if it had none.
            bypass_rules = [] if no_bypass else load_bypass_rules(branch["path"])

            branch_start = time.monotonic()
            result = audit_branch_incremental(
                branch, bypass_rules, pack_path=pack_path, force_full=force_full, no_bypass=no_bypass
            )
            branch_elapsed = time.monotonic() - branch_start

            result["elapsed"] = branch_elapsed
            audit_results.append(result)

            # Print completed branch result (persists above progress bar)
            avg = result.get("average", 0)
            style = "green" if avg >= 90 else "yellow" if avg >= 75 else "red"
            cached_tag = " [dim](cached)[/dim]" if result.get("_cache_hit") else ""
            progress.console.print(
                f"  [dim][{idx}/{total_branches}][/dim] [cyan]{branch_name:<12}[/cyan]"
                f" [{style}]{avg:>3}%[/{style}] [dim]({branch_elapsed:.1f}s)[/dim]{cached_tag}"
            )
            progress.advance(task)

    total_elapsed = time.monotonic() - audit_start
    console.print()
    console.print(f"[dim]Audit complete — {total_branches} branches in {total_elapsed:.1f}s[/dim]")
    console.print()

    # Calculate system-wide averages for each standard
    standard_scores = defaultdict(list)
    for result in audit_results:
        for standard, score in result["scores"].items():
            standard_scores[standard].append(score)

    system_averages = {standard: int(sum(scores) / len(scores)) for standard, scores in standard_scores.items()}

    overall_system_avg = int(sum(r["average"] for r in audit_results) / len(audit_results)) if audit_results else 0

    # Print results — detailed for single branch, skip for full audit
    if not is_compact:
        for result in audit_results:
            print_branch_summary(result, system_averages, overall_system_avg, no_bypass=no_bypass)

    # Print system summary (full audit only)
    if is_compact:
        print_system_summary(audit_results, no_bypass=no_bypass)

    # Machine-readable complete result set (no display budget)
    if write_artifact:
        _emit_artifact(audit_results, artifact_path, pack_name, specific_branch, no_bypass)

    # Log completion
    json_handler.log_operation(
        "standards_audit_completed",
        {
            "pack": pack_name,
            "branches_audited": len(audit_results),
            "average_compliance": int(sum(r["average"] for r in audit_results) / len(audit_results))
            if audit_results
            else 0,
        },
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
    console.print("  [green]drone @seedgo audit aipass @flow[/green]         [dim]Single branch[/dim]")
    console.print("  [green]drone @seedgo audit aipass --no-bypass[/green]   [dim]Score with rules OFF[/dim]")
    console.print("  [green]drone @seedgo audit aipass --full[/green]        [dim]Force full re-scan[/dim]")
    console.print("  [green]drone @seedgo audit aipass --artifact <path>[/green]  [dim]Artifact destination[/dim]")
    console.print("  [green]drone @seedgo audit aipass --no-artifact[/green]      [dim]Skip the artifact[/dim]")
    console.print("  [green]drone @seedgo audit --help[/green]               [dim]This help message[/dim]")
    console.print()

    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]# Full system audit (all branches, aipass pack)[/dim]")
    console.print("  [green]drone @seedgo audit aipass[/green]")
    console.print()
    console.print("  [dim]# Audit specific branch[/dim]")
    console.print("  [green]drone @seedgo audit aipass @spawn[/green]")
    console.print()
    console.print("  [dim]# The honest score: same audit, every bypass rule switched off[/dim]")
    console.print("  [green]drone @seedgo audit aipass @flow --no-bypass[/green]")
    console.print()

    console.print("  [dim]# Force a full re-scan, bypassing the incremental fingerprint cache[/dim]")
    console.print("  [green]drone @seedgo audit aipass --full[/green]")
    console.print()

    console.print("  [dim]# Write the complete violation set somewhere else[/dim]")
    console.print("  [green]drone @seedgo audit aipass --artifact reports/audit.json[/green]")
    console.print()

    console.print("[yellow]REFERENCE:[/yellow]")
    console.print("  Pack name is REQUIRED. Auto-discovers checkers from pack's handler directory.")
    console.print("  Shows per-branch scores, system-wide metrics, and top issues.")
    console.print()
    console.print("  --no-bypass runs the identical audit with an EMPTY rule set: no .seedgo/")
    console.print("  bypass.json rule applies, so the score is the branch's raw compliance — the")
    console.print("  second number every APLAN publishes. Flag order does not matter. The run")
    console.print("  labels itself on screen, caches separately from a normal run (neither can")
    console.print("  ever be served the other's score), and writes its own *_no_bypass.json")
    console.print("  artifact rather than overwriting the normal one.")
    console.print()
    console.print("  Every run also writes the COMPLETE result set as JSON: a fleet run writes")
    console.print("  .seedgo/last_audit.json, a scoped run writes .seedgo/last_audit_{branch}.json")
    console.print("  so it cannot overwrite the fleet document with one branch's results.")
    console.print("  The console display truncates (10 files, 3 diagnostics, 5 violations, 60-char")
    console.print("  messages); the artifact never does. Violations carry branch, standard and a")
    console.print("  branch-relative file path, so they join straight onto .seedgo/bypass.json rules.")
    console.print()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    # Handle help flag
    if len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    # Confirm Prax logger connection
    logger.info("Prax logger connected to standards_audit")

    # Log standalone execution
    json_handler.log_operation("audit_run", {"command": "standalone", "args": sys.argv[1:]})

    # Run audit
    handle_command("audit", sys.argv[1:])
