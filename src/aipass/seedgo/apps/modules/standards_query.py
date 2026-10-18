# =================== AIPass ====================
# Name: standards_query.py
# Description: Standards Query Module
# Version: 1.1.0
# Created: 2026-03-09
# Modified: 2026-10-17
# =============================================

"""
Standards Query Module
"""

import importlib.util
from pathlib import Path
from typing import List

from aipass.prax import logger

from aipass.cli import console, header
from aipass.cli.apps.modules import error, warning

from aipass.seedgo.apps.handlers.json import json_handler

from aipass.seedgo.apps.handlers.audit_tests import refusal
from aipass.seedgo.apps.handlers.cli.help_flags import wants_help
from aipass.seedgo.apps.modules import CommandRefused

QUERY_COMMAND = "standards_query"

# Short alias: the guide pointer in audit output must be paste-and-go without knowing the pack.
ALIAS_COMMAND = "standard"


def _discover_packs() -> dict:
    """Discover available checker packs from handlers/ directory."""
    handlers_dir = Path(__file__).parent.parent / "handlers"
    packs = {}
    if not handlers_dir.exists():
        return packs
    for d in sorted(handlers_dir.iterdir()):
        if not d.is_dir():
            continue
        if not d.name.endswith("_standards"):
            continue
        check_files = list(d.glob("*_check.py"))
        if check_files:
            packs[d.name] = d
    return packs


def _discover_standards(pack_path: Path) -> dict:
    """Discover available standards content files within a pack."""
    standards = {}
    for f in sorted(pack_path.glob("*_content.py")):
        standard_name = f.stem.removesuffix("_content")
        standards[standard_name] = f
    return standards


def _resolve_standard(standard_name: str) -> list:
    """Find every pack that defines a standard of this name."""
    matches = []
    for pack_name, pack_path in _discover_packs().items():
        standards = _discover_standards(pack_path)
        if standard_name in standards:
            matches.append((pack_name, standards[standard_name]))
    return matches


def _all_standard_names() -> dict:
    """Map every discovered standard name to the list of packs defining it."""
    names: dict = {}
    for pack_name, pack_path in _discover_packs().items():
        for std_name in _discover_standards(pack_path):
            names.setdefault(std_name, []).append(pack_name)
    return names


def _load_content(content_file: Path, standard_name: str) -> str | None:
    """Load and return formatted standards content from a content handler."""
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
            error(f"Content handler missing: {fn_name}() not found in {content_file.name}")
            return None

        return fn()
    except Exception as e:
        logger.error(f"[standards_query] Failed to load {content_file.name}: {e}")
        error(f"Failed to load content: {e}")
        return None


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


def _show_all_standards() -> None:
    """List every standard across all packs — the `standard` alias landing page."""
    names = _all_standard_names()

    console.print()
    header("STANDARDS")
    console.print()

    if not names:
        warning("No content handlers found.")
        console.print("[dim]Add *_content.py files to a handlers/*_standards/ pack[/dim]")
        console.print()
        return

    ordered = sorted(names)
    console.print(f"[yellow]Available Standards:[/yellow] ({len(ordered)})")
    console.print()
    for name in ordered:
        console.print(f"  [cyan]{name}[/cyan]")
    console.print()

    console.print("[yellow]Next:[/yellow]  Pick a standard to see its content")
    console.print(f"  [green]drone @seedgo standard {ordered[0]}[/green]")
    console.print()


def _display_content(pack_name: str, standard_name: str, content_file: Path) -> None:
    """Load a standard's content, log the query, and print it."""
    content = _load_content(content_file, standard_name)
    json_handler.log_operation("standard_queried", {"pack": pack_name, "standard": standard_name})
    if not content:
        # `_load_content` already said why; a quiet return would exit 0 on a standard never printed.
        raise CommandRefused(refusal.EXIT_UNPROVEN, f"{pack_name}/{standard_name}")

    console.print()
    if isinstance(content, list):
        for line in content:
            console.print(line)
    else:
        console.print(content)
    console.print()


def _handle_alias(args: List[str]) -> bool:
    """Handle the short `standard [<name>]` form — pack resolved automatically."""
    if not args:
        _show_all_standards()
        return True

    # A help flag anywhere means explain, never print the whole standard.
    if wants_help(None, args):
        print_alias_help()
        return True

    standard_name = args[0]
    matches = _resolve_standard(standard_name)

    if not matches:
        error(f"Unknown standard: '{standard_name}'")
        _show_all_standards()
        raise CommandRefused(refusal.EXIT_UNKNOWN_ARGUMENT, standard_name)

    # Two packs claiming one name: refuse to guess, show the explicit form.
    if len(matches) > 1:
        error(f"Ambiguous standard: '{standard_name}' is defined in {len(matches)} packs")
        console.print()
        warning("Name the pack explicitly:")
        for pack_name, _ in matches:
            console.print(f"  [green]drone @seedgo {QUERY_COMMAND} {pack_name} {standard_name}[/green]")
        console.print()
        raise CommandRefused(refusal.EXIT_UNKNOWN_ARGUMENT, standard_name)

    pack_name, content_file = matches[0]
    _display_content(pack_name, standard_name, content_file)
    return True


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle 'standards_query' command with pack-aware drill-down.
    """
    if command == ALIAS_COMMAND:
        return _handle_alias(args)

    if command != QUERY_COMMAND:
        return False

    if not args:
        print_introspection()
        return True

    # A help flag anywhere means explain, never a standard named '--help'.
    if wants_help(None, args):
        print_help()
        return True

    packs = _discover_packs()
    pack_name = args[0]
    if pack_name not in packs:
        error(f"Unknown pack: '{pack_name}'")
        console.print()
        console.print("[yellow]Available packs:[/yellow]")
        for name in packs:
            console.print(f"  [cyan]{name}[/cyan]")
        console.print()
        raise CommandRefused(refusal.EXIT_UNKNOWN_ARGUMENT, pack_name)

    if len(args) < 2:
        _show_pack_standards(packs[pack_name], pack_name)
        return True

    standard_name = args[1]
    standards = _discover_standards(packs[pack_name])
    if standard_name not in standards:
        error(f"Unknown standard: '{standard_name}'")
        console.print()
        warning(f"Available standards in {pack_name}:")
        for name in standards:
            console.print(f"  [cyan]{name}[/cyan]")
        console.print()
        raise CommandRefused(refusal.EXIT_UNKNOWN_ARGUMENT, standard_name)

    _display_content(pack_name, standard_name, standards[standard_name])
    return True


def print_introspection() -> None:
    """Display module info, discovered packs, and connected handlers."""
    console.print()
    console.print("[bold cyan]standards_query Module[/bold cyan]")
    console.print("Pack-aware content query — browse standards by pack and name")
    console.print()

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

    if packs:
        console.print("[yellow]Next:[/yellow]  Pick a pack to see its standards")
        for name in packs:
            console.print(f"  [green]drone @seedgo standards_query {name}[/green]")
        console.print()


def print_alias_help() -> None:
    """Print help for the short `standard` alias."""
    console.print()
    console.print("[bold cyan]Standard (short alias)[/bold cyan]")
    console.print("Show a standard's content by name — the pack is resolved for you")
    console.print()

    console.print("[yellow]COMMANDS:[/yellow]")
    console.print("  [green]drone @seedgo standard[/green]                   [dim]List every standard[/dim]")
    console.print("  [green]drone @seedgo standard <standard>[/green]        [dim]Show standard content[/dim]")
    console.print("  [green]drone @seedgo standard --help[/green]            [dim]This help message[/dim]")
    console.print()

    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]# Show the json_structure standard[/dim]")
    console.print("  [green]drone @seedgo standard json_structure[/green]")
    console.print()

    console.print("[yellow]REFERENCE:[/yellow]")
    console.print("  Short form of [green]standards_query <pack> <standard>[/green].")
    console.print("  If two packs define the same name, the explicit form is required.")
    console.print()

    console.print("[dim]Commands: standard, --help[/dim]")
    console.print()


def print_help():
    """Print help information."""
    console.print()
    console.print("[bold cyan]Standards Query Module[/bold cyan]")
    console.print("Pack-aware content query — browse and display standards content")
    console.print()

    console.print("[yellow]COMMANDS:[/yellow]")
    console.print(
        "  [green]drone @seedgo standards_query[/green]                        [dim]List available packs[/dim]"
    )
    console.print(
        "  [green]drone @seedgo standards_query <pack>[/green]                 [dim]List standards in pack[/dim]"
    )
    console.print(
        "  [green]drone @seedgo standards_query <pack> <standard>[/green]      [dim]Show standard content[/dim]"
    )
    console.print("  [green]drone @seedgo standards_query --help[/green]                 [dim]This help message[/dim]")
    console.print(
        "  [green]drone @seedgo standard <standard>[/green]                    [dim]Short alias, no pack needed[/dim]"
    )
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
    console.print("  [dim]# Same thing, short form[/dim]")
    console.print("  [green]drone @seedgo standard architecture[/green]")
    console.print()

    console.print("[yellow]REFERENCE:[/yellow]")
    console.print("  Auto-discovers *_content.py handlers from pack directories.")
    console.print("  Each content handler provides get_<name>_standards() returning Rich-formatted text.")
    console.print()

    console.print("[dim]Commands: standards_query, standard, --help[/dim]")
    console.print()
