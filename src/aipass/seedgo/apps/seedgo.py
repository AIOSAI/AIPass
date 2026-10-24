# =================== AIPass ====================
# Name: seedgo.py
# Description: SEEDGO - Standards Platform for AIPass
# Version: 2.0.5
# Created: 2026-03-05
# Modified: 2026-10-24
# =============================================

"""
SEEDGO - Standards Platform for AIPass
"""

import sys
import importlib.util
import traceback
from pathlib import Path
from typing import List, Any

from aipass.prax import logger
from aipass.cli import console, header
from aipass.cli.apps.modules import error
from aipass.seedgo.apps.modules import CommandRefused
from aipass.seedgo.apps.modules import standards_audit

# The header and this constant both carry the version; --version and the README read this one.
VERSION = "2.0.5"
SEEDGO_ROOT = Path(__file__).parent
MODULES_DIR = SEEDGO_ROOT / "modules"
# refusal.EXIT_UNPROVEN, "the lane could not run"; spelled here because an entry point never imports handlers.
EXIT_LANE_COULD_NOT_RUN = 2


def discover_modules() -> List[Any]:
    """Auto-discover seedgo-level modules in modules/ directory."""
    modules = []

    if not MODULES_DIR.exists():
        return modules

    for file_path in sorted(MODULES_DIR.glob("*.py")):
        if file_path.name.startswith("_"):
            continue

        try:
            spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "handle_command"):
                modules.append(module)
        except Exception as e:
            logger.error(f"[SEEDGO] Failed to load module {file_path.stem}: {e}")

    return modules


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """Route command to appropriate module.

    A CommandRefused is the module's answer, not an error: it passes untouched so its exit code reaches the
    shell. Any other raise is a crash, never "unknown command": it is logged whole and refused with exit 2.
    """
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except CommandRefused:
            raise
        except Exception as e:
            name = getattr(module, "__name__", "unknown")
            logger.error("[SEEDGO] Module %s crashed on '%s': %s\n%s", name, command, e, traceback.format_exc())
            error(
                f"'{command}' crashed in module {name}: {type(e).__name__}: {e}", suggestion="Traceback in seedgo's log"
            )
            raise CommandRefused(EXIT_LANE_COULD_NOT_RUN, command) from e
    return False


def discover_handler_packs() -> list:
    """The scoring checker packs, as the audit discovers them."""
    return [
        {
            "name": d.name,
            "path": d,
            "check_count": len(list(d.glob("*_check.py"))),
            "content_count": len(list(d.glob("*_content.py"))),
        }
        for d in standards_audit.scoring_packs().values()
    ]


def print_introspection() -> None:
    """Display discovered modules and handler packs."""
    modules = discover_modules()
    packs = discover_handler_packs()

    console.print()
    console.print("[bold cyan]SEEDGO - Standards Platform for AIPass[/bold cyan]")
    console.print(f"  Version: {VERSION}")
    console.print()

    console.print(f"[yellow]Discovered Modules:[/yellow] {len(modules)}")
    for module in modules:
        name = getattr(module, "__name__", "unknown").split(".")[-1]
        desc = (module.__doc__ or "").strip().split("\n")[0] if module.__doc__ else "No description"
        console.print(f"  [cyan]•[/cyan] {name} — {desc}")
    if not modules:
        console.print("  [dim]No modules discovered[/dim]")
    console.print()

    if packs:
        console.print(f"[yellow]Checker Packs:[/yellow] {len(packs)}")
        for pack in packs:
            console.print(
                f"  [cyan]•[/cyan] {pack['name']} "
                f"({pack['check_count']} checkers, {pack['content_count']} content modules)"
            )
        console.print()

    console.print("[yellow]Next:[/yellow]  Explore a module")
    console.print("  [green]drone @seedgo standards_query[/green]       [dim]# Browse standards content[/dim]")
    console.print("  [green]drone @seedgo audit aipass[/green]          [dim]# Run compliance audit[/dim]")
    console.print("  [green]drone @seedgo checklist <file>[/green]      [dim]# Per-standard checklist on a file[/dim]")
    console.print("  [green]drone @seedgo home-paths scan[/green]       [dim]# Home paths in the tracked tree[/dim]")
    console.print("  [green]drone @seedgo --help[/green]              [dim]# Full usage guide[/dim]")
    console.print()


def print_help() -> None:
    """Show seedgo help with usage and available commands."""
    packs = discover_handler_packs()

    console.print()
    header("SEEDGO - Standards Platform for AIPass")
    console.print()
    console.print("[dim]Code standards reference and automated compliance for all AIPass branches[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]WHAT IS SEEDGO?[/bold cyan]")
    console.print()
    console.print("Seedgo is the [bold]AIPass Standards Platform[/bold] — it:")
    console.print("  [cyan]•[/cyan] Provides [green]queryable code standards[/green] via content modules")
    console.print("  [cyan]•[/cyan] Runs automated checkers that score files 0-100 per standard")
    console.print("  [cyan]•[/cyan] Audits all branches with a single command")
    console.print("  [cyan]•[/cyan] Supports bypass rules for deliberate exceptions")
    console.print()

    if packs:
        console.print("[bold cyan]CHECKER PACKS:[/bold cyan]")
        console.print()
        for pack in packs:
            console.print(
                f"  [cyan]•[/cyan] {pack['name']}  "
                f"({pack['check_count']} checkers, {pack['content_count']} content modules)"
            )
        console.print(
            "  [dim]standards_query also lists tests_pytest_standards: the execution pack behind"
            " audit-tests, nominators that are never scored[/dim]"
        )
        console.print()

    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()

    console.print("[yellow]Audit:[/yellow]")
    console.print(
        "  [green]drone @seedgo audit[/green]                          [dim]# Show available checker packs[/dim]"
    )
    console.print("  [green]drone @seedgo audit aipass[/green]                   [dim]# Audit all branches[/dim]")
    console.print("  [green]drone @seedgo audit aipass @flow[/green]             [dim]# Audit single branch[/dim]")
    console.print("  [green]drone @seedgo standards_audit aipass @flow[/green]   [dim]# Same verb, long name[/dim]")
    console.print(
        "  [green]drone @seedgo audit pytest_quality @flow[/green]     "
        "[dim]# 15 AST rules over a branch's tests (shadow: scores, gates nothing)[/dim]"
    )
    console.print(
        "  [green]drone @seedgo audit pytest_quality[/green]           [dim]# The same over every citizen[/dim]"
    )
    console.print(
        "  [green]drone @seedgo audit context[/green]                  "
        "[dim]# Startup-budget fleet table: 6 files per branch vs their owners' caps (advisory)[/dim]"
    )
    console.print()

    console.print("[yellow]Test Quality:[/yellow]")
    console.print(
        "  [green]drone @seedgo audit-tests @flow[/green]              "
        "[dim]# Run a suite under the write gate; advisory artifact[/dim]"
    )
    console.print(
        "  [green]drone @seedgo test-inventory <path>[/green]          "
        "[dim]# Every test function in a tree, ranked for reading[/dim]"
    )
    console.print(
        "  [green]drone @seedgo test-inventory <path> --twins[/green]  [dim]# Same-named tests across branches[/dim]"
    )
    console.print(
        "  [green]drone @seedgo shadow-cycle run[/green]               "
        "[dim]# The three weekly passes, one mail (--no-mail to print)[/dim]"
    )
    console.print(
        "  [green]drone @seedgo ratchet pick[/green]                   "
        "[dim]# The execution ratchet: pick / run / record @branch[/dim]"
    )
    console.print(
        "  [green]drone @seedgo tests retired[/green]                  "
        "[dim]# The retire lane; restore <name>, template-status, template bump[/dim]"
    )
    console.print()

    console.print("[yellow]Query Standards:[/yellow]")
    console.print("  [green]drone @seedgo standards_query[/green]                [dim]# List available packs[/dim]")
    console.print(
        "  [green]drone @seedgo standards_query aipass_standards[/green]        [dim]# List standards in pack[/dim]"
    )
    console.print(
        "  [green]drone @seedgo standards_query aipass_standards cli[/green]    [dim]# Show standard content[/dim]"
    )
    console.print()

    console.print("[yellow]Checklist:[/yellow]")
    console.print(
        "  [green]drone @seedgo checklist[/green]                      [dim]# Show checklist introspection[/dim]"
    )
    console.print(
        "  [green]drone @seedgo checklist <file>[/green]               [dim]# Run per-standard checklist on file[/dim]"
    )
    console.print()

    console.print("[yellow]Diagnostics:[/yellow]")
    console.print(
        "  [green]drone @seedgo diagnostics[/green]                    "
        "[dim]# Pyright runs inside `audit aipass`; this shows how (takes no branch)[/dim]"
    )
    console.print()

    console.print("[yellow]README:[/yellow]")
    console.print("  [green]drone @seedgo readme update @flow[/green]            [dim]# Update a branch README[/dim]")
    console.print("  [green]drone @seedgo readme check @flow[/green]             [dim]# Dry run[/dim]")
    console.print()

    console.print("[yellow]Proof (Self-Check):[/yellow]")
    console.print(
        "  [green]drone @seedgo proof[/green]                          [dim]# List available proof packs[/dim]"
    )
    console.print(
        "  [green]drone @seedgo proof aipass[/green]                   [dim]# Run all proofs for aipass pack[/dim]"
    )
    console.print("  [green]drone @seedgo proof_query[/green]                    [dim]# Query proof pack content[/dim]")
    console.print()

    console.print("[yellow]Test Map:[/yellow]")
    console.print(
        "  [green]drone @seedgo test_map @flow[/green]"
        "                 [dim]# Function test coverage map for branch[/dim]"
    )
    console.print()

    console.print("[yellow]Housekeeping:[/yellow]")
    console.print(
        "  [green]drone @seedgo permissions[/green]                    "
        "[dim]# Who may write outside their own branch[/dim]"
    )
    console.print(
        "  [green]drone @seedgo inbox_audit[/green]                    "
        "[dim]# Flag malformed mail ids across every inbox[/dim]"
    )
    console.print(
        "  [green]drone @seedgo home-paths scan[/green]                "
        "[dim]# No developer home path in a tracked text file (the CI gate)[/dim]"
    )
    console.print(
        "  [green]drone @seedgo bypass prune @flow[/green]             "
        "[dim]# Remove bypass rules that match nothing (--dry-run to preview)[/dim]"
    )
    console.print()

    console.print("─" * 70)
    console.print()

    console.print("[yellow]Examples:[/yellow]")
    console.print()
    console.print("  [dim]# Check a single file against all standards[/dim]")
    console.print("  [green]drone @seedgo checklist src/aipass/flow/apps/flow.py[/green]")
    console.print()
    console.print("  [dim]# Audit a specific branch[/dim]")
    console.print("  [green]drone @seedgo audit aipass @flow[/green]")
    console.print()
    console.print("  [dim]# Look up what a standard checks[/dim]")
    console.print("  [green]drone @seedgo standard cli[/green]")
    console.print()

    console.print("─" * 70)
    console.print()

    # Commands line for drone discovery
    console.print(
        "[dim]Commands: audit, audit-tests, test-inventory, shadow-cycle, standards_audit, standards_query,"
        " standard, checklist, diagnostics, diagnostics_audit, proof, proof_query, test_map, readme,"
        " readme_update, permissions, inbox_audit, home-paths, ratchet, tests, bypass, --help[/dim]"
    )
    console.print()


def main() -> int:
    """Main entry point - routes to modules."""
    try:
        modules = discover_modules()
        args = sys.argv[1:]

        if not args:
            print_introspection()
            return 0

        if args[0] in ["--help", "-h", "help"]:
            print_help()
            return 0

        if args[0] in ["--version", "-V"]:
            console.print(f"seedgo v{VERSION}")
            return 0

        command = args[0]
        remaining = args[1:] if len(args) > 1 else []

        # A help flag anywhere after the command is a question about it, never an instruction to run.
        # Scanned inline because an entry point uses modules, never handlers; the bare word `help` is
        # left to the modules, where a later slot may legitimately hold it.
        if any(arg in ("--help", "-h") for arg in remaining):
            for module in modules:
                if module.handle_command(command, ["--help"]):
                    return 0
            error(f"Unknown command: {command}", suggestion="Run 'seedgo --help' for usage")
            print_help()
            return 1

        if route_command(command, remaining, modules):
            return 0

        error(f"Unknown command: {command}", suggestion="Run 'seedgo --help' for usage")
        return 1
    except CommandRefused as refused:
        # The module already printed why; an unknown command or argument exits non-zero.
        return refused.code
    except Exception as exc:
        logger.error("[seedgo] Unhandled error in main: %s", exc)
        raise


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.exit(main())
