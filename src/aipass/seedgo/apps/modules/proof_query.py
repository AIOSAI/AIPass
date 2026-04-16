# =================== AIPass ====================
# Name: proof_query.py
# Description: Proof Query Module
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Proof Query Module

Auto-discovering content query module for proof packs.
Mirrors standards_query.py pattern but for proof content.

Run: seedgo proof_query
"""

import importlib.util
from pathlib import Path
from typing import List

# =============================================================================
# INFRASTRUCTURE SETUP
# =============================================================================

# IMPORTS
# =============================================================================

# Prax logger (system-wide, always first)
from aipass.prax import logger

# CLI services (display/output formatting)
from aipass.cli import console, header
from aipass.cli.apps.modules import warning

# JSON handler for tracking
from aipass.seedgo.apps.handlers.json import json_handler


# =============================================================================
# PACK DISCOVERY
# =============================================================================


def _discover_proof_packs() -> dict:
    """Discover available proof packs from handlers/ directory.

    Convention: directories named *_proof/ containing *_content.py files.
    Pack identifier is the full directory name (e.g., "aipass_proof").

    Returns:
        Dict mapping pack name to Path, e.g. {"aipass_proof": Path("handlers/aipass_proof")}
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
        # Must contain at least one *_content.py file
        content_files = list(d.glob("*_content.py"))
        if content_files:
            packs[d.name] = d
    return packs


# =============================================================================
# PROOF CONTENT DISCOVERY
# =============================================================================


def _discover_proof_content(pack_dir: Path) -> dict:
    """Discover available proof content files within a pack.

    Globs *_content.py from the pack directory.

    Args:
        pack_dir: Path to the *_proof/ directory

    Returns:
        Dict mapping proof name to Path,
        e.g. {"triplet": Path("triplet_content.py"), ...}
    """
    proofs = {}
    for f in sorted(pack_dir.glob("*_content.py")):
        # Strip _content.py suffix to get proof name
        proof_name = f.stem.removesuffix("_content")
        proofs[proof_name] = f
    return proofs


# =============================================================================
# CONTENT LOADING
# =============================================================================


def _load_proof_content(content_file: Path, proof_name: str) -> str | None:
    """Load and return formatted proof content from a content handler.

    Imports the content file and calls get_{proof_name}_proof().

    Args:
        content_file: Path to the *_content.py file
        proof_name: Name of the proof (e.g., "triplet")

    Returns:
        Rich-formatted string, or None on failure
    """
    try:
        spec = importlib.util.spec_from_file_location(content_file.stem, content_file)
        if spec is None or spec.loader is None:
            logger.error(f"[proof_query] Failed to create spec for {content_file}")
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        fn_name = f"get_{proof_name}_proof"
        fn = getattr(mod, fn_name, None)
        if fn is None:
            logger.error(f"[proof_query] No {fn_name}() in {content_file.name}")
            console.print(f"[red]Content handler missing:[/red] {fn_name}() not found in {content_file.name}")
            return None

        return fn()
    except Exception as e:
        logger.error(f"[proof_query] Failed to load {content_file.name}: {e}")
        console.print(f"[red]Failed to load content:[/red] {e}")
        return None


# =============================================================================
# DISPLAY HELPERS
# =============================================================================


def _show_query_introspection() -> None:
    """No-args display: list available proof packs with content counts."""
    console.print()
    console.print("[bold cyan]proof_query Module[/bold cyan]")
    console.print("Pack-aware content query — browse proof content by pack and name")
    console.print()

    # Show discovered packs
    packs = _discover_proof_packs()
    console.print("[yellow]Discovered Proof Packs:[/yellow]")
    for name, pack_path in packs.items():
        proofs = _discover_proof_content(pack_path)
        console.print(f"  [cyan]{name}[/cyan]  ({len(proofs)} proof{'s' if len(proofs) != 1 else ''})")
    if not packs:
        console.print("  [dim]No proof packs found[/dim]")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    for name, pack_path in packs.items():
        console.print(f"  [cyan]handlers/{name}/[/cyan]")
        proofs = _discover_proof_content(pack_path)
        for proof_name, proof_path in proofs.items():
            console.print(f"    [dim]- {proof_path.name} (get_{proof_name}_proof)[/dim]")
    console.print()

    # Navigation hints with drone commands
    if packs:
        console.print("[yellow]Next:[/yellow]  Pick a pack to see its proofs")
        for name in packs:
            console.print(f"  [green]drone @seedgo proof_query {name}[/green]")
        console.print()


def _list_pack_proofs(pack_name: str, pack_dir: Path) -> None:
    """List all proofs available in a pack.

    Args:
        pack_name: Full pack directory name (e.g., "aipass_proof")
        pack_dir: Path to the pack directory
    """
    proofs = _discover_proof_content(pack_dir)

    console.print()
    header(f"PROOFS IN {pack_name.upper()}")
    console.print()

    if not proofs:
        warning("No content handlers found.")
        console.print(f"[dim]Add *_content.py files to handlers/{pack_name}/[/dim]")
        console.print()
        return

    console.print(f"[yellow]Available Proofs:[/yellow] ({len(proofs)})")
    console.print()
    for name in proofs:
        console.print(f"  [cyan]{name}[/cyan]")
    console.print()

    console.print("[yellow]Next:[/yellow]  Pick a proof to see its content")
    first_proof = next(iter(proofs))
    console.print(f"  [green]drone @seedgo proof_query {pack_name} {first_proof}[/green]")
    console.print()


def _show_proof_content(pack_name: str, pack_dir: Path, proof_name: str) -> None:
    """Display specific proof content.

    Args:
        pack_name: Full pack directory name (e.g., "aipass_proof")
        pack_dir: Path to the pack directory
        proof_name: Name of the proof (e.g., "triplet")
    """
    proofs = _discover_proof_content(pack_dir)
    if proof_name not in proofs:
        console.print(f"[red]Unknown proof:[/red] '{proof_name}'")
        console.print()
        warning(f"Available proofs in {pack_name}:")
        for name in proofs:
            console.print(f"  [cyan]{name}[/cyan]")
        console.print()
        return

    content = _load_proof_content(proofs[proof_name], proof_name)
    json_handler.log_operation("proof_queried", {"pack": pack_name, "proof": proof_name})
    if content:
        console.print()
        # Handle both str and List[str] return types from content handlers
        if isinstance(content, list):
            for line in content:
                console.print(line)
        else:
            console.print(content)
        console.print()


# =============================================================================
# COMMAND HANDLER
# =============================================================================


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle 'proof_query' command with pack-aware drill-down.

    Args:
        command: Command name
        args: Additional arguments
            [] → show introspection (available packs)
            ["aipass_proof"] → list proofs in pack
            ["aipass_proof", "triplet"] → show proof content
            ["--help"] → help

    Returns:
        True if handled, False if not this module's command
    """
    if command != "proof_query":
        return False

    if not args:
        print_introspection()
        return True

    if args[0] in ["--help", "-h", "help"]:
        print_help()
        return True

    # First arg = pack name
    packs = _discover_proof_packs()
    pack_name = args[0]
    if pack_name not in packs:
        console.print(f"[red]Unknown pack:[/red] '{pack_name}'")
        console.print()
        console.print("[yellow]Available packs:[/yellow]")
        for name in packs:
            console.print(f"  [cyan]{name}[/cyan]")
        console.print()
        return True

    # No second arg = list proofs in pack
    if len(args) < 2:
        _list_pack_proofs(pack_name, packs[pack_name])
        return True

    # Second arg = proof name
    _show_proof_content(pack_name, packs[pack_name], args[1])
    return True


# =============================================================================
# INTROSPECTION & HELP
# =============================================================================


def print_introspection() -> None:
    """Display module info for seedgo introspection system."""
    _show_query_introspection()


def print_help() -> None:
    """Print help information."""
    console.print()
    console.print("[bold cyan]Proof Query Module[/bold cyan]")
    console.print("Pack-aware content query — browse and display proof content")
    console.print()

    console.print("[yellow]COMMANDS:[/yellow]")
    console.print(
        "  [green]drone @seedgo proof_query[/green]                        [dim]List available proof packs[/dim]"
    )
    console.print("  [green]drone @seedgo proof_query <pack>[/green]                 [dim]List proofs in pack[/dim]")
    console.print("  [green]drone @seedgo proof_query <pack> <proof>[/green]         [dim]Show proof content[/dim]")
    console.print("  [green]drone @seedgo proof_query --help[/green]                 [dim]This help message[/dim]")
    console.print()

    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]# List all proof packs[/dim]")
    console.print("  [green]drone @seedgo proof_query[/green]")
    console.print()
    console.print("  [dim]# List proofs in aipass proof pack[/dim]")
    console.print("  [green]drone @seedgo proof_query aipass_proof[/green]")
    console.print()
    console.print("  [dim]# Show triplet proof content[/dim]")
    console.print("  [green]drone @seedgo proof_query aipass_proof triplet[/green]")
    console.print()

    console.print("[yellow]REFERENCE:[/yellow]")
    console.print("  Auto-discovers *_content.py handlers from proof pack directories.")
    console.print("  Each content handler provides get_<name>_proof() returning Rich-formatted text.")
    console.print()

    console.print("[dim]Commands: proof_query, --help[/dim]")
    console.print()
