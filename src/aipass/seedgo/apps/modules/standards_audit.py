# =================== AIPass ====================
# Name: standards_audit.py
# Description: Standards Audit Module
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Standards Audit Module — per-branch compliance against a checker pack.

`audit <pack> [@branch]` scores; `audit tests <target>` is the execution lane
(the same command as `audit-tests <target>`), recognised here and handed off.
"""

import sys
import time
from pathlib import Path
from typing import List
from collections import defaultdict

# IMPORTS — prax logger first, system-wide
from aipass.prax import logger

# CLI services (display/output formatting)
from aipass.cli import console, header
from aipass.cli.apps.modules import error, warning

# JSON handler for tracking
from aipass.seedgo.apps.handlers.json import json_handler

# Audit handlers (implementation)
from aipass.seedgo.apps.handlers.audit import discovery
from aipass.seedgo.apps.handlers.audit.discovery import discover_branches, _is_branch_private, check_internal_access
from aipass.seedgo.apps.handlers.audit.branch_audit import audit_branch_incremental
from aipass.seedgo.apps.handlers.audit.audit_display import print_branch_summary, print_system_summary
from aipass.seedgo.apps.handlers.audit.artifact import write_audit_artifact

# Bypass system
from aipass.seedgo.apps.handlers.bypass.bypass_handler import load_bypass_rules
from aipass.seedgo.apps.handlers.cli.help_flags import DASHED_HELP_TOKENS

# The audit-tests lane's refusal vocabulary, reused rather than re-invented:
# Law ARGV, its exit code and its did-you-mean live in one place so the two
# verbs that share the typo cannot drift into refusing it two different ways.
from aipass.seedgo.apps.handlers.audit_tests import refusal

# The execution lane `audit tests <target>` hands off to, unchanged.
from aipass.seedgo.apps.modules import audit_tests as lane_verb

# Drone services for @ resolution
from aipass.drone.apps.modules import normalize_branch_arg


# =============================================================================
# COMMAND HANDLER
# =============================================================================

#: Every flag this verb accepts — the list a mistyped token is offered against.
AUDIT_FLAGS: tuple = tuple(
    "--show-bypasses --bypasses -b --no-bypass --full --artifact --no-artifact --help -h".split()
)

#: The sibling surfaces one keystroke away. `audit -tests @backup` is
#: `audit tests @backup` with a stray hyphen, and that typo used to run this
#: audit instead. The canonical two-word form is offered first; the hyphenated
#: alias stays a valid spelling and still routes.
SIBLING_VERBS: tuple = ("audit tests", "audit-tests")

#: The first positional that means "not a pack, the execution lane". Recognised
#: here and forwarded whole; `audit-tests <target>` remains the same lane.
LANE_WORD = "tests"

#: Pack, then @branch. A third bare word fills no slot: refused, never dropped.
MAX_POSITIONAL = 2


def _handlers_dir() -> Path:
    """This branch's `handlers/` directory."""
    return Path(__file__).parent.parent / "handlers"


def _discover_packs() -> dict:
    """Scoring packs available to the audit, name -> path.

    Discovery and the `kind` refusal live in the discovery HANDLER: reading a
    manifest off disk is not a module's job.
    """
    return discovery.discover_packs(_handlers_dir())


def non_scoring_packs() -> dict:
    """Packs that exist but belong to another lane. Name -> kind."""
    return discovery.non_scoring_packs(_handlers_dir())


def _print_non_scoring_packs() -> None:
    """Name the packs this audit will NOT score, and say who owns them.

    A pack directory that simply vanished from every listing is
    indistinguishable from one that was never installed.
    """
    other = non_scoring_packs()
    if not other:
        return

    console.print("[bold cyan]Not scored here (other lanes):[/bold cyan]")
    for name, kind in other.items():
        console.print(f"  [dim]{name}[/dim]  [dim]({kind} pack - not a standards pack)[/dim]")
    console.print("  [dim]drone @seedgo audit tests <target> runs the execution lane.[/dim]")
    console.print()


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

    _print_non_scoring_packs()

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

    packs = _discover_packs()
    console.print("[yellow]Discovered Packs:[/yellow]")
    for name, pack_path in packs.items():
        check_files = list(pack_path.glob("*_check.py"))
        console.print(f"  [cyan]{name}[/cyan]  ({len(check_files)} checker{'s' if len(check_files) != 1 else ''})")
    if not packs:
        console.print("  [dim]No packs found[/dim]")
    console.print()

    _print_non_scoring_packs()

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

    The display truncates by design; this file does not. The line names the
    SCOPE as well as the path: naming only the path invites a consumer to read
    a single-branch document as if it covered the fleet, which is the same
    silent-and-plausible failure the artifact exists to end.

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


def _print_refusal(refused) -> None:
    """Print a refusal: its one line, the law and code, then the evidence.

    Printing lives here, not beside the rule: a handler that displays is one
    nobody can reuse without its console (the cli standard)."""
    error(refused.stdout_line())
    console.print(f"[dim]law: {refused.law}   exit code: {refused.code}[/dim]")
    for line in refused.detail:
        console.print(f"  [dim]{line}[/dim]")


def _refuse_unknown_argument(token: str, args: List[str]) -> None:
    """Refuse a token this verb never claimed, and print the fix (Law ARGV)."""
    suggestion = refusal.suggested_command(token, "audit", args, AUDIT_FLAGS, SIBLING_VERBS)
    _print_refusal(refusal.refusal_for_unknown_argument(token, suggestion, "audit"))


def _dispatch_lane(args: List[str]) -> bool:
    """Hand `audit tests <target>` to the execution lane, arguments verbatim.

    PARSING ONLY: everything after the word is forwarded untouched and the lane
    never touches this file's scoring engine. A pack really named `tests` would
    give the word two meanings, and a silently preferred meaning is the species
    the dropped `-tests` was, so that collision REFUSES and names both.
    """
    if LANE_WORD in _discover_packs():
        _print_refusal(refusal.refusal_for_ambiguous_lane_word(LANE_WORD, "audit"))
        return True
    return lane_verb.handle_command("audit-tests", args[1:])


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle 'audit' command with pack-aware routing.

    Args:
        command: Command name
        args: [] introspects, ["aipass"] audits every branch, ["aipass",
            "@flow"] audits one, ["tests", ...] is the lane, ["--help"] explains.

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

    # `audit tests <target>` IS the execution lane, forwarded whole.
    if args[0] == LANE_WORD:
        return _dispatch_lane(args)

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
    # Collected, never acted on until the whole list is read: a help flag further
    # along is a question, and a question is answered even beside nonsense.
    unrecognized: List[str] = []
    for arg in args:
        # Before the value slots, never after: '--artifact --help' wrote the
        # artifact to a file named '--help' and ran the audit to fill it.
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
            if len(positional) > MAX_POSITIONAL:
                unrecognized.append(arg)
            continue
        # A dashed token no branch claimed. It used to fall off the end of this
        # loop and be forgotten (Law ARGV).
        unrecognized.append(arg)

    if unrecognized:
        # True, not False: a False has seedgo.py report 'Unknown command: audit'.
        _refuse_unknown_argument(unrecognized[0], args)
        return True

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
            # `aipass_standards` reaches the `aipass` pack: the directory's own
            # name is always an unambiguous spelling for the pack it holds.
            pack_name = positional[0].removesuffix("_standards")
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

    # PRIVATE BRANCH ACCESS CONTROL — a private branch is auditable only from
    # inside its own directory. Isolation per DPLAN-035.
    if specific_branch and _is_branch_private(specific_branch):
        if not check_internal_access(specific_branch):
            console.print(
                f"[red]Branch '{specific_branch}' is private — audit access restricted to internal use only[/red]"
            )
            return True

    # Log audit start
    json_handler.log_operation("standards_audit_started", {"pack": pack_name, "specific_branch": specific_branch})

    # A private branch targeted from inside its own CWD must be discoverable.
    _include_private = specific_branch is not None and _is_branch_private(specific_branch)
    console.print()
    header(f"{pack_name.upper()} BRANCH STANDARDS AUDIT")
    console.print()

    # Any suppression announces itself, and this one inverts the meaning of every
    # number below it — an unlabelled --no-bypass run reads as a branch that got
    # worse. Said here, in the summary, and in the artifact: each is copied alone.
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
        # Elapsed ticks continuously; remaining-time estimates froze on the
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
    console.print("  [green]drone @seedgo audit tests @backup[/green]        [dim]Execution lane[/dim]")
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

    console.print("  [dim]# The execution lane: run @backup's suite under the hygiene gate[/dim]")
    console.print("  [green]drone @seedgo audit tests @backup[/green]")
    console.print()

    console.print("[yellow]REFERENCE:[/yellow]")
    console.print("  Pack name is REQUIRED; checkers auto-discover from the pack's handler dir.")
    console.print()
    console.print("  'tests' is not a pack: 'audit tests <target>' is the EXECUTION lane, the")
    console.print("  same command as 'audit-tests <target>'. Every lane flag is forwarded whole.")
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
    console.print("  so it cannot overwrite the fleet document with one branch's results. The")
    console.print("  console display truncates; the artifact never does. Violations carry branch,")
    console.print("  standard and a branch-relative path, ready for .seedgo/bypass.json rules.")
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
