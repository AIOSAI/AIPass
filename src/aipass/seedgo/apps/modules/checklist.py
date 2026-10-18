# =================== AIPass ====================
# Name: checklist.py
# Description: Per-File Standards Checklist Module
# Version: 1.4.0
# Created: 2026-03-15
# Modified: 2026-10-17
# =============================================

"""Per-File Standards Checklist Module

Designed for hook consumption: runs after every file edit.
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax import logger

from aipass.cli import console
from aipass.cli.apps.modules import error

from aipass.seedgo.apps.handlers.audit.branch_audit import discover_checkers

from aipass.seedgo.apps.handlers.bypass.bypass_handler import (
    get_branch_from_path,
    load_bypass_rules,
    registry_notes,
)

from aipass.seedgo.apps.handlers.checklist.verdicts import (
    format_failure as _format_failure,
    is_applicable as _is_applicable,
    is_skip_or_error as _is_skip_or_error,
)

from aipass.seedgo.apps.handlers.aipass_standards.skip_dirs import is_prototype_file, is_throwaway_path

from aipass.seedgo.apps.handlers.aipass_standards import applicability

from aipass.seedgo.apps.handlers.bypass.ignore_handler import is_seedgo_ignored

from aipass.seedgo.apps.handlers.bypass import inert

from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.audit_tests import refusal
from aipass.seedgo.apps.modules import CommandRefused

from aipass.seedgo.apps.handlers.cli.help_flags import wants_help


def _get_repo_root() -> Path | None:
    """Return the git repo root derived from this file's location."""
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        if (parent / ".git").exists():
            return parent
    return None


def not_judged_here(file_path: str, pack_name: str = "aipass") -> List[str]:
    """Branch-level standards that apply to this file but the checklist cannot run.

    Named so a pass here never reads as a pass in the audit, which judges them.
    """
    resolved = str(Path(file_path).resolve())
    if not resolved.endswith(".py") or not Path(resolved).exists():
        return []
    pack_path = _resolve_pack_path(pack_name)
    if pack_path is None:
        return []
    names = []
    for name, checker in sorted(discover_checkers(pack_path).items()):
        if getattr(checker, "AUDIT_SCOPE", "entry_point") != "branch_level":
            continue
        if not applicability.applies_to_file(checker, resolved):
            continue
        if not _is_applicable(checker, resolved):
            names.append(name)
    return names


def run_checklist(file_path: str, pack_name: str = "aipass", prototype: bool = False) -> List[Dict]:
    """Run applicable standards checkers against a single file.

    A result may carry "bypass_notes" for a bypass whose scope the checker cannot honour;
    the notes never change "passed".
    """
    resolved = str(Path(file_path).resolve())

    if not Path(resolved).exists():
        return [{"standard": "(error)", "passed": False, "detail": f"File not found: {resolved}"}]

    # A non-.py file is judged only by a TEXT_FILES checker that reads its kind
    # (verdicts.reads_text_file); with none, the answer is the one it always was.
    if not resolved.endswith(".py") and not _text_checkers_for(resolved, pack_name):
        return [{"standard": "(skip)", "passed": True, "detail": "Not a Python file"}]

    if is_throwaway_path(resolved):
        return [{"standard": "(skip)", "passed": True, "detail": "Throwaway path (temp/scratchpad) — skipped"}]

    # Retired code is not lintable, matching the audit lane's .archive/ skip.
    if applicability.is_retired_path(resolved):
        return [{"standard": "(skip)", "passed": True, "detail": "Retired path (archived/deprecated) — skipped"}]

    if prototype or is_prototype_file(resolved):
        return [{"standard": "(skip)", "passed": True, "detail": "Prototype mode — standards skipped"}]

    branch_path = _resolve_branch_path(resolved)
    if branch_path is not None and is_seedgo_ignored(resolved, branch_path):
        return [{"standard": "(skip)", "passed": True, "detail": "Ignored via .seedgoignore"}]

    pack_path = _resolve_pack_path(pack_name)
    if pack_path is None:
        return [{"standard": "(error)", "passed": False, "detail": f"Pack '{pack_name}' not found"}]

    checkers = discover_checkers(pack_path)
    if not checkers:
        return [{"standard": "(error)", "passed": False, "detail": "No checkers discovered"}]

    bypass_rules = _load_bypass_for_file(resolved)

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
            detail = _format_failure(r)

        result = {"standard": name, "passed": passed, "detail": detail}
        notes = inert.inert_notes(resolved, name, bypass_rules)
        if notes:
            result["bypass_notes"] = notes
        results.append(result)

    if not results:
        return [{"standard": "(skip)", "passed": True, "detail": "No applicable checkers for this file"}]

    json_handler.log_operation("checklist_completed", {"file": str(file_path), "standards_run": len(results)})
    return results


def _text_checkers_for(file_path: str, pack_name: str) -> List[str]:
    """The pack's checkers that judge this non-.py file (TEXT_FILES and its kind)."""
    pack_path = _resolve_pack_path(pack_name)
    if pack_path is None:
        return []
    return [
        name for name, checker in sorted(discover_checkers(pack_path).items()) if _is_applicable(checker, file_path)
    ]


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


# The token scripts count findings by: plain ASCII, one per finding, never on a pass.
FINDING_MARKER = "[FAIL]"

# The bracket must be escaped: Rich reads "[FAIL]" as a style tag and drops it at render.
_FINDING_MARKUP = "[red]\\[FAIL][/red]"


def _print_results(results: List[Dict], file_path: str) -> None:
    """Print concise pass/fail output for hook consumption."""
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

    # Behind a blank line: hooks' auto_fix rejoins a finding's wrapped detail until one.
    notes = [(r["standard"], note) for r in results for note in r.get("bypass_notes", [])]
    if notes:
        console.print()
    for std, note in notes:
        console.print(f"  [yellow]inert bypass[/yellow] \u2014 {std}: {note}")


def _print_not_judged(names: List[str]) -> None:
    """One line naming the branch-level rows this lane did not judge.

    ``soft_wrap`` keeps one physical line; printed after a blank line so auto_fix never glues it
    onto the last finding.
    """
    if not names:
        return
    console.print()
    console.print(
        f"[dim]Not judged here (branch-level, run by `drone @seedgo audit`): {', '.join(names)}[/dim]",
        highlight=False,
        soft_wrap=True,
    )


def _print_registry_notes(notes: List[str]) -> None:
    """Each unreadable-registry note once, after every verdict, behind a blank line."""
    if notes:
        console.print()
    for note in notes:
        console.print(f"[yellow]note[/yellow] — {note}", highlight=False, soft_wrap=True)


def handle_command(command: str, args: List[str]) -> bool:
    """Handle 'checklist' command — per-file standards check."""
    if command != "checklist":
        return False

    if not args:
        print_introspection()
        return True

    # A help flag anywhere means explain, never run.
    if wants_help(None, args):
        print_help()
        return True

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
        raise CommandRefused(refusal.EXIT_UNKNOWN_ARGUMENT, "checklist with no target")

    # Absolute, then repo root (cross-CWD invocations), then CWD.
    resolved = Path(file_path)
    if resolved.is_absolute():
        resolved = resolved.resolve()
    else:
        repo_root = _get_repo_root()
        candidate = (repo_root / resolved).resolve() if repo_root else None
        if candidate and candidate.exists():
            resolved = candidate
        else:
            resolved = (Path.cwd() / resolved).resolve()

    if resolved.is_dir():
        py_files = sorted(resolved.glob("*.py"))
        py_files = [f for f in py_files if not f.name.startswith("_") and "(disabled)" not in f.name]
        if not py_files:
            error("No .py files found in directory", suggestion=f"Directory: {resolved}")
            raise CommandRefused(refusal.EXIT_NO_UNITS, str(resolved))
        console.print(f"\n[bold cyan]Checklist — {resolved.name}/[/bold cyan]  [dim]({len(py_files)} files)[/dim]\n")
        for f in py_files:
            results = run_checklist(str(f), pack_name=pack_name, prototype=prototype)
            _print_results(results, str(f))
            if not _is_skip_or_error(results):
                _print_not_judged(not_judged_here(str(f), pack_name=pack_name))
            console.print()
        _print_registry_notes(registry_notes())
        return True

    results = run_checklist(str(resolved), pack_name=pack_name, prototype=prototype)

    _print_results(results, str(resolved))
    if not _is_skip_or_error(results):
        _print_not_judged(not_judged_here(str(resolved), pack_name=pack_name))
    _print_registry_notes(registry_notes())

    return True


def print_introspection() -> None:
    """Display module info and connected handlers."""
    console.print()
    console.print("[bold cyan]checklist Module[/bold cyan]")
    console.print("Per-file standards check — quick pass/fail for hook consumption")
    console.print()

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
    console.print("  A non-.py text file is judged only by checkers declaring [cyan]TEXT_FILES = True[/cyan]")
    console.print('  Checkers with [cyan]AUDIT_SCOPE = "branch_level"[/cyan] are skipped (need full branch)')
    console.print("  Skipped branch-level rows that apply to the file are named on one closing line, not counted")
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


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    if len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    logger.info("Prax logger connected to checklist")

    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)

    handle_command("checklist", sys.argv[1:])
