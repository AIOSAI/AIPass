# =================== AIPass ====================
# Name: seedgo_proof.py
# Description: Self-proof orchestrator — discovers and runs proof packs
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""Seedgo Proof — Self-check orchestrator for standards pack integrity.

Discovers *_proof/ directories in handlers/, runs all proof handler .py files
inside, aggregates results, and reports CERTIFIED or NOT CERTIFIED.

Commands:
    seedgo proof              — List available proof packs
    seedgo proof aipass       — Run all proofs for aipass pack
    seedgo proof aipass --json — Machine-readable JSON output

Discovery pattern mirrors standards_audit.py:
    handlers/*_proof/ dirs → handler .py files → scan(pack_dir) interface

Interface per proof handler:
    scan(pack_dir: Path) -> dict with keys: passed, issues, summary

Related:
    DPLAN-0048 (seedgo self-check system)
    tools/ (original prototypes — standalone, not connected)
"""

import json
import importlib.util
from pathlib import Path
from typing import List

from rich.table import Table

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
# PACK DISCOVERY
# =============================================================================


def _discover_proof_packs() -> dict:
    """Discover available proof packs from handlers/ directory.

    Convention: directories named *_proof/ containing at least one .py handler file.
    Pack display name strips the _proof suffix.

    Excludes from handler counting:
        - __init__.py
        - *_content.py
        - files starting with _
        - non-.py files

    Returns:
        Dict mapping pack name to Path, e.g. {"aipass": Path("handlers/aipass_proof")}
    """
    handlers_dir = Path(__file__).parent.parent / "handlers"
    packs = {}
    if not handlers_dir.exists():
        return packs
    for d in sorted(handlers_dir.iterdir()):
        if not d.is_dir():
            continue
        if not d.name.endswith("_proof"):
            continue
        # Must contain at least one valid handler .py file
        handler_files = _discover_proof_handlers(d)
        if handler_files:
            pack_name = d.name.removesuffix("_proof")
            packs[pack_name] = d
    return packs


def _discover_proof_handlers(pack_dir: Path) -> List[Path]:
    """Find all handler .py files in a proof pack directory.

    Skips:
        - __init__.py
        - *_content.py
        - *.md files
        - files starting with _

    Args:
        pack_dir: Path to the *_proof/ directory

    Returns:
        Sorted list of handler Paths
    """
    handlers = []
    if not pack_dir.exists():
        return handlers
    for f in sorted(pack_dir.iterdir()):
        if not f.is_file():
            continue
        if f.suffix != ".py":
            continue
        if f.name.startswith("_"):
            continue
        if f.name.endswith("_content.py"):
            continue
        handlers.append(f)
    return handlers


def _resolve_target_pack(proof_pack_name: str) -> Path | None:
    """Resolve the standards pack directory that a proof pack targets.

    Mapping: strip '_proof' suffix from proof dir name, add '_standards'.
    E.g., handlers/aipass_proof/ -> handlers/aipass_standards/

    Args:
        proof_pack_name: The display name of the proof pack (e.g. "aipass")

    Returns:
        Path to the target standards pack, or None if it does not exist
    """
    handlers_dir = Path(__file__).parent.parent / "handlers"
    target_dir = handlers_dir / f"{proof_pack_name}_standards"
    if target_dir.is_dir():
        return target_dir
    return None


# =============================================================================
# PROOF EXECUTION
# =============================================================================


def _load_and_run_proof(handler_path: Path, pack_dir: Path) -> dict:
    """Import a proof handler module dynamically and call its scan() function.

    Args:
        handler_path: Path to the handler .py file
        pack_dir: Path to the target standards pack directory (passed to scan())

    Returns:
        Result dict from scan(), or error dict on failure
    """
    handler_name = handler_path.stem
    try:
        spec = importlib.util.spec_from_file_location(handler_name, handler_path)
        if spec is None or spec.loader is None:
            logger.error(f"[seedgo_proof] Failed to create spec for {handler_path}")
            return {
                "passed": False,
                "issues": [f"Failed to create import spec for {handler_path.name}"],
                "summary": "Import error",
                "error": True,
            }
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        scan_fn = getattr(mod, "scan", None)
        if scan_fn is None:
            logger.warning(f"[seedgo_proof] No scan() in {handler_path.name} — skipping")
            return {
                "passed": False,
                "issues": [f"No scan() function found in {handler_path.name}"],
                "summary": "Missing scan() interface",
                "error": True,
                "not_implemented": True,
            }

        result = scan_fn(pack_dir)
        if not isinstance(result, dict):
            return {
                "passed": False,
                "issues": [f"scan() returned {type(result).__name__}, expected dict"],
                "summary": "Invalid return type",
                "error": True,
            }
        return result

    except Exception as e:
        logger.error(f"[seedgo_proof] Error running {handler_name}: {e}")
        return {
            "passed": False,
            "issues": [f"Exception: {e}"],
            "summary": f"Error: {e}",
            "error": True,
        }


def _run_proof_pack(pack_name: str, pack_dir: Path) -> dict:
    """Run all proof handlers in a pack against the target standards pack.

    For each handler: load, run scan(), collect results.
    Aggregate: count passed/failed/errors.

    Args:
        pack_name: Display name of the proof pack (e.g. "aipass")
        pack_dir: Path to the proof pack directory (e.g. handlers/aipass_proof/)

    Returns:
        Aggregated dict with keys:
            pack_name, target_dir, results (per-handler), passed, failed,
            errors, total, certified
    """
    handlers = _discover_proof_handlers(pack_dir)
    target_dir = _resolve_target_pack(pack_name)

    if target_dir is None:
        logger.error(f"[seedgo_proof] No target standards pack found for '{pack_name}'")
        return {
            "pack_name": pack_name,
            "target_dir": None,
            "results": {},
            "passed": 0,
            "failed": 0,
            "errors": 1,
            "total": 0,
            "certified": False,
            "error": f"No matching standards pack: {pack_name}_standards",
        }

    results = {}
    passed_count = 0
    failed_count = 0
    error_count = 0

    for handler_path in handlers:
        handler_name = handler_path.stem
        result = _load_and_run_proof(handler_path, target_dir)
        results[handler_name] = result

        if result.get("error"):
            error_count += 1
        elif result.get("passed"):
            passed_count += 1
        else:
            failed_count += 1

    total = len(handlers)
    certified = failed_count == 0 and error_count == 0 and total > 0

    return {
        "pack_name": pack_name,
        "target_dir": str(target_dir),
        "results": results,
        "passed": passed_count,
        "failed": failed_count,
        "errors": error_count,
        "total": total,
        "certified": certified,
    }


# =============================================================================
# DISPLAY
# =============================================================================


def _display_proof_results(pack_name: str, results: dict) -> None:
    """Rich console output for proof pack results.

    Shows header, per-proof results table, and final verdict.

    Args:
        pack_name: Display name of the proof pack
        results: Aggregated results dict from _run_proof_pack()
    """
    console.print()
    header(f"SEEDGO PROOF — {pack_name.upper()}")
    console.print()

    if results.get("error") and not results.get("results"):
        error(results["error"])
        console.print()
        return

    target_dir = results.get("target_dir", "unknown")
    console.print(f"[dim]Target pack: {target_dir}[/dim]")
    console.print(f"[dim]Proof handlers: {results['total']}[/dim]")
    console.print()

    # Per-proof results table
    table = Table(
        title="Proof Results",
        show_header=True,
        header_style="bold cyan",
        show_lines=False,
        pad_edge=True,
    )
    table.add_column("Proof", style="cyan", min_width=20)
    table.add_column("Status", justify="center", min_width=12)
    table.add_column("Summary", min_width=30)

    for proof_name, result in results.get("results", {}).items():
        if result.get("not_implemented"):
            status = "[yellow]PENDING[/yellow]"
        elif result.get("error"):
            status = "[red]ERROR[/red]"
        elif result.get("passed"):
            status = "[green]PASSED[/green]"
        else:
            status = "[red]FAILED[/red]"

        summary = result.get("summary", "No summary")
        issue_count = len(result.get("issues", []))
        if issue_count > 0 and not result.get("not_implemented"):
            summary += f" ({issue_count} issue{'s' if issue_count != 1 else ''})"

        table.add_row(proof_name, status, summary)

    console.print(table)
    console.print()

    # Aggregate summary
    console.print(
        f"  [green]Passed:[/green] {results['passed']}  "
        f"[red]Failed:[/red] {results['failed']}  "
        f"[yellow]Errors:[/yellow] {results['errors']}  "
        f"[dim]Total:[/dim] {results['total']}"
    )
    console.print()

    # Final verdict
    if results["certified"]:
        console.print("[bold green]  CERTIFIED[/bold green]")
    else:
        console.print("[bold red]  NOT CERTIFIED[/bold red]")
    console.print()


# =============================================================================
# INTROSPECTION
# =============================================================================


def _show_proof_introspection() -> None:
    """Show available proof packs and example commands when proof is run with no args."""
    packs = _discover_proof_packs()
    console.print()
    header("SEEDGO PROOF")
    console.print()

    if not packs:
        warning("No proof packs found.")
        console.print("[dim]Add handler .py files to handlers/*_proof/ directories.[/dim]")
        console.print()
        return

    console.print("[yellow]Available Proof Packs:[/yellow]")
    console.print()
    for name, pack_path in packs.items():
        handler_files = _discover_proof_handlers(pack_path)
        target = _resolve_target_pack(name)
        target_status = "[green]target found[/green]" if target else "[red]no target[/red]"
        console.print(
            f"  [cyan]{name}[/cyan]  "
            f"({len(handler_files)} proof{'s' if len(handler_files) != 1 else ''}, "
            f"{target_status})"
        )
    console.print()

    console.print("[yellow]Next:[/yellow]  Pick a pack to run proofs")
    first_pack = next(iter(packs))
    console.print(f"  [green]drone @seedgo proof {first_pack}[/green]              [dim]# Run all proofs[/dim]")
    console.print(f"  [green]drone @seedgo proof {first_pack} --json[/green]       [dim]# JSON output[/dim]")
    console.print()


def print_introspection() -> None:
    """Display module info and connected handlers."""
    _show_proof_introspection()


# =============================================================================
# HELP
# =============================================================================


def print_help() -> None:
    """Print help information."""
    console.print()
    console.print("[bold cyan]Seedgo Proof Module[/bold cyan]")
    console.print("Self-check orchestrator — verifies standards pack integrity")
    console.print()

    console.print("[yellow]COMMANDS:[/yellow]")
    console.print("  [green]drone @seedgo proof[/green]                      [dim]Show available proof packs[/dim]")
    console.print("  [green]drone @seedgo proof aipass[/green]               [dim]Run all proofs for aipass pack[/dim]")
    console.print("  [green]drone @seedgo proof aipass --json[/green]        [dim]JSON output[/dim]")
    console.print("  [green]drone @seedgo proof --help[/green]               [dim]This help message[/dim]")
    console.print()

    console.print("[yellow]PROOF HANDLER INTERFACE:[/yellow]")
    console.print("  Each handler .py file must define:")
    console.print("    [cyan]scan(pack_dir: Path) -> dict[/cyan]")
    console.print("  Return keys: passed (bool), issues (list), summary (str)")
    console.print()

    console.print("[yellow]REFERENCE:[/yellow]")
    console.print("  Proof pack = handlers/*_proof/ directory")
    console.print("  Target = handlers/*_standards/ directory (auto-resolved)")
    console.print("  Verdict: CERTIFIED (all pass) or NOT CERTIFIED (any fail/error)")
    console.print()

    console.print("[dim]Commands: proof, seedgo_proof, --help[/dim]")
    console.print()


# =============================================================================
# COMMAND HANDLER
# =============================================================================


def _validate_pack(args: List[str]) -> tuple:
    pack_name: str | None = None
    json_output = False

    for arg in args:
        if arg == "--json":
            json_output = True
        elif not arg.startswith("-"):
            if pack_name is None:
                pack_name = arg

    packs = _discover_proof_packs()
    if pack_name is None or pack_name not in packs:
        available = ", ".join(packs.keys()) if packs else "(none)"
        error(
            f"Unknown proof pack: '{pack_name}'",
            suggestion=f"Available packs: {available}. Usage: drone @seedgo proof {next(iter(packs), '<pack>')}",
        )
        return None, None, json_output

    return pack_name, packs[pack_name], json_output


def handle_command(command: str, args: List[str]) -> bool:
    """Handle 'proof' command with pack-aware routing.

    Args:
        command: Command name
        args: Additional arguments
            [] -> show proof introspection (available packs)
            ["aipass"] -> run aipass proof pack
            ["aipass", "--json"] -> JSON output
            ["--help"] -> help

    Returns:
        True if handled, False if not this module's command
    """
    if command not in ("proof", "seedgo_proof"):
        return False

    if not args:
        print_introspection()
        return True

    if args[0] in ["--help", "-h", "help"]:
        print_help()
        return True

    pack_name, pack_dir, json_output = _validate_pack(args)
    if pack_name is None:
        return True

    json_handler.log_operation("proof_started", {"pack": pack_name})

    results = _run_proof_pack(pack_name, pack_dir)

    if json_output:
        console.print_json(json.dumps(results, indent=2, default=str))
    else:
        _display_proof_results(pack_name, results)

    json_handler.log_operation(
        "proof_completed",
        {
            "pack": pack_name,
            "passed": results["passed"],
            "failed": results["failed"],
            "errors": results["errors"],
            "certified": results["certified"],
        },
    )

    return True
