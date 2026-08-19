# =================== AIPass ====================
# Name: checklist.py
# Description: Per-File Standards Checklist Module
# Version: 1.0.0
# Created: 2026-03-15
# Modified: 2026-03-15
# =============================================

"""
Per-File Standards Checklist Module

Quick pass/fail standards check for a single file.
Designed for hook consumption — runs after every file edit.

Run: drone @seedgo checklist <file>
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional

# =============================================================================
# INFRASTRUCTURE SETUP
# =============================================================================

# IMPORTS
# =============================================================================

# Prax logger (system-wide, always first)
from aipass.prax import logger

# CLI services (display/output formatting)
from aipass.cli import console
from aipass.cli.apps.modules import error

# Checker discovery (reuse existing infrastructure)
from aipass.seedgo.apps.handlers.audit.branch_audit import discover_checkers

# Bypass system
from aipass.seedgo.apps.handlers.bypass.bypass_handler import (
    get_branch_from_path,
    load_bypass_rules,
)

# Throwaway / prototype detection
from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import is_prototype_file, is_throwaway_path

# Where each standard applies (production / tests / everywhere) — shared with the audit lane
from aipass.seedgo.apps.handlers.aipass_standards import applicability

# .seedgoignore — gitignore-style per-directory + global default (tools/)
from aipass.seedgo.apps.handlers.bypass.ignore_handler import is_seedgo_ignored

# JSON handler for tracking
from aipass.seedgo.apps.handlers.json import json_handler

# Whole-sequence help detection (help_flag_safety)
from aipass.seedgo.apps.handlers.cli.help_flags import wants_help


# =============================================================================
# PATH HELPERS
# =============================================================================


def _get_repo_root() -> Path | None:
    """Return the git repo root derived from this file's location.

    Walks up from this module's directory to find the repo root
    (the parent that contains the .git directory).  Falls back to
    None if not inside a git repo.
    """
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        if (parent / ".git").exists():
            return parent
    return None


# =============================================================================
# CHECKER APPLICABILITY
# =============================================================================


def _is_entry_point(file_path: str) -> bool:
    """Check if file is an entry point: apps/{name}.py (directly in apps/, not subdirectory)."""
    p = Path(file_path)
    if not p.name.endswith(".py"):
        return False
    if "apps/" not in file_path:
        return False
    return p.parent.name == "apps"


def _is_applicable(checker, file_path: str) -> bool:
    """Determine if a checker applies to the given file.

    First gate is APPLIES_TO — whether the standard is meaningful for this
    KIND of file (production / tests / everywhere), shared with the audit lane
    via applicability.py so the two can never disagree about scope again.
    Structural standards used to fail on nearly every test file in the fleet
    here while the audit lane never even looked at tests/; that gap is what
    branches were absorbing with bypass rules.

    Then AUDIT_SCOPE — where a result is reported:
      - "entry_point" (default) -> only apps/{name}.py files
      - "all_files"             -> any .py file
      - "branch_level"          -> normally skipped, but eligible if checker
                                   also implements check_module() for per-file use
    """
    if not applicability.applies_to_file(checker, file_path):
        return False

    scope = getattr(checker, "AUDIT_SCOPE", "entry_point")

    # Branch-level checkers skip per-file runs UNLESS they also implement
    # check_module() for targeted single-file validation (e.g., ruff_check)
    if scope == "branch_level":
        return hasattr(checker, "check_module") and file_path.endswith(".py")

    # Only check_module() capable checkers
    if not hasattr(checker, "check_module"):
        return False

    if scope == "all_files":
        return file_path.endswith(".py")

    # Default: entry_point scope
    return _is_entry_point(file_path)


# =============================================================================
# CORE LOGIC
# =============================================================================


def run_checklist(file_path: str, pack_name: str = "aipass", prototype: bool = False) -> List[Dict]:
    """Run applicable standards checkers against a single file.

    Args:
        file_path: Absolute path to the file to check.
        pack_name: Checker pack to use (default: "aipass").
        prototype: If True, skip all standards (disposable code).

    Returns:
        List of result dicts: [{"standard": str, "passed": bool, "detail": str|None}]
    """
    resolved = str(Path(file_path).resolve())

    if not Path(resolved).exists():
        return [{"standard": "(error)", "passed": False, "detail": f"File not found: {resolved}"}]

    if not resolved.endswith(".py"):
        return [{"standard": "(skip)", "passed": True, "detail": "Not a Python file"}]

    if is_throwaway_path(resolved):
        return [{"standard": "(skip)", "passed": True, "detail": "Throwaway path (temp/scratchpad) — skipped"}]

    # Retired code is not lintable. The audit lane has always skipped .archive/;
    # this lane did not, so touching an archived file raised standards nobody
    # can act on without un-retiring the code.
    if applicability.is_retired_path(resolved):
        return [{"standard": "(skip)", "passed": True, "detail": "Retired path (archived/deprecated) — skipped"}]

    if prototype or is_prototype_file(resolved):
        return [{"standard": "(skip)", "passed": True, "detail": "Prototype mode — standards skipped"}]

    branch_path = _resolve_branch_path(resolved)
    if branch_path is not None and is_seedgo_ignored(resolved, branch_path):
        return [{"standard": "(skip)", "passed": True, "detail": "Ignored via .seedgoignore"}]

    # Discover pack path
    pack_path = _resolve_pack_path(pack_name)
    if pack_path is None:
        return [{"standard": "(error)", "passed": False, "detail": f"Pack '{pack_name}' not found"}]

    # Load checkers
    checkers = discover_checkers(pack_path)
    if not checkers:
        return [{"standard": "(error)", "passed": False, "detail": "No checkers discovered"}]

    # Resolve branch and bypass rules
    bypass_rules = _load_bypass_for_file(resolved)

    # Run applicable checkers
    results = []
    for name, checker in sorted(checkers.items()):
        if not _is_applicable(checker, resolved):
            continue

        try:
            r = checker.check_module(resolved, bypass_rules=bypass_rules)  # type: ignore[attr-defined]
        except Exception as e:
            logger.info("Checker %s failed on %s: %s", name, resolved, e)
            results.append({"standard": name, "passed": False, "detail": f"Checker error: {e}"})
            continue

        passed = r.get("passed", True)
        detail = None

        if not passed:
            # Extract concise failure detail from checks
            detail = _format_failure(r)

        results.append({"standard": name, "passed": passed, "detail": detail})

    if not results:
        return [{"standard": "(skip)", "passed": True, "detail": "No applicable checkers for this file"}]

    json_handler.log_operation("checklist_completed", {"file": str(file_path), "standards_run": len(results)})
    return results


def _resolve_pack_path(pack_name: str) -> Optional[Path]:
    """Resolve pack name to its directory path."""
    handlers_dir = Path(__file__).parent.parent / "handlers"
    candidate = handlers_dir / f"{pack_name}_standards"
    if candidate.is_dir() and list(candidate.glob("*_check.py")):
        return candidate
    return None


def _resolve_branch_path(file_path: str) -> Optional[Path]:
    """Resolve the absolute branch root containing file_path, or None."""
    branch = get_branch_from_path(file_path)
    if branch is None:
        return None
    raw_path = branch.get("path", "")
    if not raw_path:
        return None
    bp = Path(raw_path)
    if not bp.is_absolute():
        from aipass.seedgo.apps.handlers.bypass.bypass_handler import _find_registry

        registry_path = _find_registry()
        bp = (registry_path.parent / bp).resolve()
    return bp


def _load_bypass_for_file(file_path: str) -> list:
    """Load bypass rules for the branch containing file_path."""
    bp = _resolve_branch_path(file_path)
    if bp is None:
        return []
    return load_bypass_rules(str(bp))


def _format_failure(result: Dict) -> str:
    """Extract a concise one-line failure description from checker result."""
    checks = result.get("checks", [])
    failed = [c for c in checks if not c.get("passed", False)]

    if not failed:
        return "Failed (no details)"

    # Use first failure's message, trimmed
    msg = failed[0].get("message", "Unknown issue")

    # If multiple failures, indicate count
    if len(failed) > 1:
        msg = f"{msg} (+{len(failed) - 1} more)"

    return msg


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================

# The token a script counts findings by. This lane is consumed by machines as
# much as by people (edit hooks, sweeps over a whole branch), and until now the
# only thing marking a finding was the em dash below -- decoration, not a
# contract. @spawn scripted against it by grepping for a cross, got zero hits
# across all 18 files of a branch, and nearly deleted 41 bypass rules on that
# "proof". Plain ASCII, one per finding, never on a pass.
FINDING_MARKER = "[FAIL]"

# ...and the same token spelled for Rich. The leading bracket MUST be escaped:
# unescaped, Rich reads "[FAIL]" as a style tag and deletes it at render time,
# leaving output that looks clean while the recorded call argument still reads
# perfectly right. That is the exact failure mode this marker exists to end.
_FINDING_MARKUP = "[red]\\[FAIL][/red]"


def _print_results(results: List[Dict], file_path: str) -> None:
    """Print concise pass/fail output for hook consumption.

    Each finding carries :data:`FINDING_MARKER` so a caller can count findings
    with a literal grep. The em dash stays where it was: it is the human
    layout, and a marker is an addition to it, not a replacement for it.
    """
    p = Path(file_path)
    console.print(f"[dim]{p.name}[/dim]")

    all_passed = True
    for r in results:
        std = r["standard"]
        if r["passed"]:
            console.print(f"  [green]\u2713[/green] {std}")
        else:
            all_passed = False
            detail = r.get("detail", "")
            if detail:
                console.print(f"  {_FINDING_MARKUP} \u2014 {std}: {detail}")
            else:
                console.print(f"  {_FINDING_MARKUP} \u2014 {std}")

    if all_passed:
        console.print(f"[green]All {len(results)} standards passed[/green]")


# =============================================================================
# COMMAND HANDLER
# =============================================================================


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle 'checklist' command — per-file standards check.

    Args:
        command: Command name
        args: Additional arguments
            [] -> print_introspection() (standard no-args gate)
            ["--help"] -> print_help()
            ["<file>"] -> run checklist on file
            ["--pack", "<pack>", "<file>"] -> run with specific pack

    Returns:
        True if handled, False if not this module's command
    """
    if command != "checklist":
        return False

    # No args -> introspection
    if not args:
        print_introspection()
        return True

    # A help flag ANYWHERE means explain: `checklist <file> --help` used to run
    # the full per-file audit it was being asked to describe.
    if wants_help(None, args):
        print_help()
        return True

    # Parse arguments
    pack_name = "aipass"
    file_path = None
    prototype = False

    i = 0
    while i < len(args):
        if args[i] in ("--pack", "-p") and i + 1 < len(args):
            pack_name = args[i + 1]
            i += 2
        elif args[i] == "--prototype":
            prototype = True
            i += 1
        elif not args[i].startswith("-"):
            file_path = args[i]
            i += 1
        else:
            i += 1

    if file_path is None:
        error("No file specified", suggestion="Usage: drone @seedgo checklist <file>")
        return True

    # Resolve path — try absolute, then repo root, then CWD
    resolved = Path(file_path)
    if resolved.is_absolute():
        resolved = resolved.resolve()
    else:
        # Try relative to git repo root first (handles cross-CWD invocations)
        repo_root = _get_repo_root()
        candidate = (repo_root / resolved).resolve() if repo_root else None
        if candidate and candidate.exists():
            resolved = candidate
        else:
            # Fallback: resolve relative to CWD
            resolved = (Path.cwd() / resolved).resolve()

    # Directory mode — run checklist on all .py files in directory
    if resolved.is_dir():
        py_files = sorted(resolved.glob("*.py"))
        py_files = [f for f in py_files if not f.name.startswith("_") and "(disabled)" not in f.name]
        if not py_files:
            error("No .py files found in directory", suggestion=f"Directory: {resolved}")
            return True
        console.print(f"\n[bold cyan]Checklist — {resolved.name}/[/bold cyan]  [dim]({len(py_files)} files)[/dim]\n")
        for f in py_files:
            results = run_checklist(str(f), pack_name=pack_name, prototype=prototype)
            _print_results(results, str(f))
            console.print()
        return True

    # Single file mode
    results = run_checklist(str(resolved), pack_name=pack_name, prototype=prototype)

    # Print results
    _print_results(results, str(resolved))

    return True


# =============================================================================
# INTROSPECTION & HELP
# =============================================================================


def print_introspection() -> None:
    """Display module info and connected handlers."""
    console.print()
    console.print("[bold cyan]checklist Module[/bold cyan]")
    console.print("Per-file standards check — quick pass/fail for hook consumption")
    console.print()

    # Show discovered packs
    handlers_dir = Path(__file__).parent.parent / "handlers"
    packs = {}
    if handlers_dir.exists():
        for d in sorted(handlers_dir.iterdir()):
            if d.is_dir() and d.name.endswith("_standards"):
                check_files = list(d.glob("*_check.py"))
                if check_files:
                    packs[d.name.removesuffix("_standards")] = len(check_files)

    console.print("[yellow]Discovered Packs:[/yellow]")
    for name, count in packs.items():
        console.print(f"  [cyan]{name}[/cyan]  ({count} checker{'s' if count != 1 else ''})")
    if not packs:
        console.print("  [dim]No packs found[/dim]")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/audit/[/cyan]")
    console.print("    [dim]- branch_audit.py (discover_checkers — dynamic checker loading)[/dim]")
    console.print()
    console.print("  [cyan]handlers/bypass/[/cyan]")
    console.print("    [dim]- bypass_handler.py (get_branch_from_path, load_bypass_rules)[/dim]")
    console.print()

    console.print("[yellow]External Dependencies:[/yellow]")
    console.print("  [dim]- aipass.prax (logger)[/dim]")
    console.print("  [dim]- aipass.cli (console)[/dim]")
    console.print()

    console.print("[yellow]Next:[/yellow]")
    console.print("  [green]drone @seedgo checklist <file>[/green]       [dim]# Check a single file[/dim]")
    console.print("  [green]drone @seedgo checklist --help[/green]       [dim]# Full usage guide[/dim]")
    console.print()


def print_help() -> None:
    """Print help information."""
    console.print()
    console.print("[bold cyan]Per-File Standards Checklist[/bold cyan]")
    console.print("Quick pass/fail check for a single file against applicable standards")
    console.print()

    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]drone @seedgo checklist <file>[/green]                    [dim]# Check single file[/dim]")
    console.print(
        "  [green]drone @seedgo checklist <directory>[/green]"
        "               [dim]# Check all .py files in directory[/dim]"
    )
    console.print(
        "  [green]drone @seedgo checklist --pack <pack> <file>[/green]      [dim]# Check with specific pack[/dim]"
    )
    console.print("  [green]drone @seedgo checklist --help[/green]                    [dim]# This help message[/dim]")
    console.print()

    console.print("[yellow]OUTPUT FORMAT:[/yellow]")
    console.print("  [green]\u2713[/green] standard_name                              [dim]# Passed[/dim]")
    console.print(f"  {_FINDING_MARKUP} \u2014 standard_name: failure detail   [dim]# Failed with reason[/dim]")
    console.print()
    console.print(
        f"  Every finding carries the literal marker {_FINDING_MARKUP} \u2014 one per finding, never on a pass."
    )
    console.print("  [dim]Count findings with: drone @seedgo checklist <file> | grep -c '\\[FAIL]'[/dim]")
    console.print("  [dim]Do not count the em dash: it is layout, not a contract.[/dim]")
    console.print()

    console.print("[yellow]SCOPE RULES:[/yellow]")
    console.print('  Checkers with [cyan]AUDIT_SCOPE = "entry_point"[/cyan] only run on apps/{name}.py files')
    console.print('  Checkers with [cyan]AUDIT_SCOPE = "all_files"[/cyan] run on any .py file')
    console.print('  Checkers with [cyan]AUDIT_SCOPE = "branch_level"[/cyan] are skipped (need full branch)')
    console.print()

    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]# Check a module file (only all_files checkers apply)[/dim]")
    console.print("  [green]drone @seedgo checklist src/aipass/flow/apps/modules/step_runner.py[/green]")
    console.print()
    console.print("  [dim]# Check an entry point (all checkers apply)[/dim]")
    console.print("  [green]drone @seedgo checklist src/aipass/flow/apps/flow.py[/green]")
    console.print()

    console.print("[yellow]REFERENCE:[/yellow]")
    console.print("  Runs after every file edit via hook. Bypass rules from .seedgo/bypass.json are respected.")
    console.print("  For full branch audit, use: [green]drone @seedgo audit aipass[/green]")
    console.print()


# =============================================================================
# STANDALONE EXECUTION
# =============================================================================

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
    logger.info("Prax logger connected to checklist")

    # No args -> introspection
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)

    # Run checklist
    handle_command("checklist", sys.argv[1:])
