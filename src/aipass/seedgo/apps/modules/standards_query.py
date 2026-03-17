# =================== AIPass ====================
# Name: standards_query.py
# Description: Standards Query Module
# Version: 1.0.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""
Standards Query Module

Auto-discovering content query module for standards packs.
Replaces 15 dead _standard.py modules with one pack-aware module.

Run: seedgo standards_query
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

def _discover_packs() -> dict:
    """Discover available checker packs from handlers/ directory.

    Convention: directories named *_standards/ containing *_check.py files.
    Pack identifier is the full directory name (e.g., "aipass_standards").

    Returns:
        Dict mapping pack name to Path, e.g. {"aipass_standards": Path("handlers/aipass_standards")}
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
            packs[d.name] = d
    return packs


# =============================================================================
# STANDARD DISCOVERY
# =============================================================================

def _discover_standards(pack_path: Path) -> dict:
    """Discover available standards content files within a pack.

    Globs *_content.py from the pack directory.

    Returns:
        Dict mapping standard name to Path,
        e.g. {"architecture": Path("architecture_content.py"), ...}
    """
    standards = {}
    for f in sorted(pack_path.glob("*_content.py")):
        # Strip _content.py suffix to get standard name
        standard_name = f.stem.removesuffix("_content")
        standards[standard_name] = f
    return standards


# =============================================================================
# CONTENT LOADING
# =============================================================================

def _load_content(content_file: Path, standard_name: str) -> str | None:
    """Load and return formatted standards content from a content handler.

    Imports the content file and calls get_{standard_name}_standards().

    Args:
        content_file: Path to the *_content.py file
        standard_name: Name of the standard (e.g., "architecture")

    Returns:
        Rich-formatted string, or None on failure
    """
    try:
        spec = importlib.util.spec_from_file_location(content_file.stem, content_file)
        if spec is None or spec.loader is None:
            logger.error(f"[standards_query] Failed to create spec for {content_file}")
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        fn_name = f"get_{standard_name}_standards"
        fn = getattr(mod, fn_name, None)
        if fn is None:
            logger.error(f"[standards_query] No {fn_name}() in {content_file.name}")
            console.print(f"[red]Content handler missing:[/red] {fn_name}() not found in {content_file.name}")
            return None

        return fn()
    except Exception as e:
        logger.error(f"[standards_query] Failed to load {content_file.name}: {e}")
        console.print(f"[red]Failed to load content:[/red] {e}")
        return None


# =============================================================================
# DISPLAY HELPERS
# =============================================================================

def _show_pack_standards(pack_path: Path, pack_name: str) -> None:
    """List all standards available in a pack."""
    standards = _discover_standards(pack_path)

    console.print()
    header(f"STANDARDS IN {pack_name.upper()}")
    console.print()

    if not standards:
        warning("No content handlers found.")
        console.print(f"[dim]Add *_content.py files to handlers/{pack_name}/[/dim]")
        console.print()
        return

    console.print(f"[yellow]Available Standards:[/yellow] ({len(standards)})")
    console.print()
    for name in standards:
        console.print(f"  [cyan]{name}[/cyan]")
    console.print()

    console.print("[yellow]Next:[/yellow]  Pick a standard to see its content")
    first_standard = next(iter(standards))
    console.print(f"  [green]drone @seedgo standards_query {pack_name} {first_standard}[/green]")
    console.print()


# =============================================================================
# COMMAND HANDLER
# =============================================================================

def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle 'standards_query' command with pack-aware drill-down.

    Args:
        command: Command name
        args: Additional arguments
            [] → show introspection (available packs)
            ["aipass_standards"] → list standards in pack
            ["aipass_standards", "architecture"] → show content
            ["--help"] → help

    Returns:
        True if handled, False if not this module's command
    """
    if command != "standards_query":
        return False

    if not args:
        print_introspection()
        return True

    if args[0] in ["--help", "-h", "help"]:
        print_help()
        return True

    # First arg = pack name
    packs = _discover_packs()
    pack_name = args[0]
    if pack_name not in packs:
        console.print(f"[red]Unknown pack:[/red] '{pack_name}'")
        console.print()
        console.print("[yellow]Available packs:[/yellow]")
        for name in packs:
            console.print(f"  [cyan]{name}[/cyan]")
        console.print()
        return True

    # No second arg = list standards in pack
    if len(args) < 2:
        _show_pack_standards(packs[pack_name], pack_name)
        return True

    # Second arg = standard name
    standard_name = args[1]
    standards = _discover_standards(packs[pack_name])
    if standard_name not in standards:
        console.print(f"[red]Unknown standard:[/red] '{standard_name}'")
        console.print()
        warning(f"Available standards in {pack_name}:")
        for name in standards:
            console.print(f"  [cyan]{name}[/cyan]")
        console.print()
        return True

    # Load and display content
    content = _load_content(standards[standard_name], standard_name)
    json_handler.log_operation("standard_queried", {"pack": pack_name, "standard": standard_name})
    if content:
        console.print()
        # Handle both str and List[str] return types from content handlers
        if isinstance(content, list):
            for line in content:
                console.print(line)
        else:
            console.print(content)
        console.print()
    return True


# =============================================================================
# INTROSPECTION & HELP
# =============================================================================

def print_introspection() -> None:
    """Display module info, discovered packs, and connected handlers."""
    console.print()
    console.print("[bold cyan]standards_query Module[/bold cyan]")
    console.print("Pack-aware content query — browse standards by pack and name")
    console.print()

    # Show discovered packs
    packs = _discover_packs()
    console.print("[yellow]Discovered Packs:[/yellow]")
    for name, pack_path in packs.items():
        standards = _discover_standards(pack_path)
        console.print(f"  [cyan]{name}[/cyan]  ({len(standards)} standard{'s' if len(standards) != 1 else ''})")
    if not packs:
        console.print("  [dim]No packs found[/dim]")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    for name, pack_path in packs.items():
        console.print(f"  [cyan]handlers/{name}/[/cyan]")
        standards = _discover_standards(pack_path)
        for std_name, std_path in standards.items():
            console.print(f"    [dim]- {std_path.name} (get_{std_name}_standards)[/dim]")
    console.print()

    # Navigation hints with drone commands
    if packs:
        console.print("[yellow]Next:[/yellow]  Pick a pack to see its standards")
        for name in packs:
            console.print(f"  [green]drone @seedgo standards_query {name}[/green]")
        console.print()


def print_help():
    """Print help information."""
    console.print()
    console.print("[bold cyan]Standards Query Module[/bold cyan]")
    console.print("Pack-aware content query — browse and display standards content")
    console.print()

    console.print("[yellow]COMMANDS:[/yellow]")
    console.print("  [green]drone @seedgo standards_query[/green]                        [dim]List available packs[/dim]")
    console.print("  [green]drone @seedgo standards_query <pack>[/green]                 [dim]List standards in pack[/dim]")
    console.print("  [green]drone @seedgo standards_query <pack> <standard>[/green]      [dim]Show standard content[/dim]")
    console.print("  [green]drone @seedgo standards_query --help[/green]                 [dim]This help message[/dim]")
    console.print()

    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]# List all packs[/dim]")
    console.print("  [green]drone @seedgo standards_query[/green]")
    console.print()
    console.print("  [dim]# List standards in aipass pack[/dim]")
    console.print("  [green]drone @seedgo standards_query aipass_standards[/green]")
    console.print()
    console.print("  [dim]# Show architecture standard content[/dim]")
    console.print("  [green]drone @seedgo standards_query aipass_standards architecture[/green]")
    console.print()

    console.print("[yellow]REFERENCE:[/yellow]")
    console.print("  Auto-discovers *_content.py handlers from pack directories.")
    console.print("  Each content handler provides get_<name>_standards() returning Rich-formatted text.")
    console.print()

    console.print("[dim]Commands: standards_query, --help[/dim]")
    console.print()
