# =================== AIPass ====================
# Name: discovery.py
# Description: Find skills across search paths
# Version: 1.2.0
# Created: 2026-03-07
# Modified: 2026-10-24
# =============================================

"""Skill discovery module."""

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, escape
from aipass.skills.apps.handlers.discovery_handler import get_search_paths, discover_skills_in_path
from aipass.skills.apps.handlers.registry import build_registry
from aipass.skills.apps.handlers.switch_handler import SwitchStateUnreadable, read_state
from aipass.skills.apps.handlers.json import json_handler


def handle_command(command: str, args: list) -> bool:
    """Handle the list command routed by the entry point."""
    if any(arg in ("--help", "-h", "help") for arg in args):
        print_introspection()
        return True
    if command != "list":
        return False
    return list_skills()


def list_skills():
    """Print every discovered skill grouped by source, OFF ones marked; False only when the switch state is unreadable."""
    skills = discover_all()

    # A switched-off skill is still listed, marked, so it can be turned back on.
    try:
        switch_state = read_state()
    except SwitchStateUnreadable as exc:
        logger.error("Cannot list skills — switch state unreadable: %s", exc)
        error(f"Error: {exc}")
        return False

    if not skills:
        console.print("  No skills found.")
        console.print("  Create one with: drone @skills create <name>")
        return True

    logger.info(f"list: found {len(skills)} skill(s)")
    console.print(f"  Found {len(skills)} skill(s):")
    console.print()

    sources = {}
    for skill in skills:
        sources.setdefault(skill["source"], []).append(skill)

    source_labels = {"project": "Project", "global": "Global", "builtin": "Built-in"}

    for source, source_skills in sources.items():
        console.print(f"  \\[{source_labels.get(source, source)}]")
        for skill in source_skills:
            handler_tag = " \\[handler]" if skill["has_handler"] else ""
            entry = switch_state.get(skill["name"])
            off_tag = ""
            if isinstance(entry, dict) and not entry.get("enabled", True):
                off_tag = " [red]\\[OFF][/red]"
            tags = f" ({escape(', '.join(map(str, skill['tags'])))})" if skill.get("tags") else ""
            name = escape(f"{skill['name']:<25}")
            console.print(f"    {name} {escape(str(skill['description']))}{handler_tag}{off_tag}{tags}")
        console.print()

    return True


def discover_all():
    """Discover all skills across all search paths, deduplicated by name (first match wins)."""
    search_paths = get_search_paths()
    result = build_registry(search_paths, discover_skills_in_path)
    json_handler.log_operation("skills_discovered", {"count": len(result)})
    return result


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]discovery Module[/bold cyan]")
    console.print("[dim]Find skills across search paths — project, global, and built-in[/dim]")
    console.print()
    console.print("[bold]Connected Handlers:[/bold]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print(
        "    [dim]- discovery_handler.py (get_search_paths, discover_skills_in_path — path scanning and SKILL.md parsing)[/dim]"
    )
    console.print("    [dim]- registry.py (build_registry — deduplicated skill registry from search paths)[/dim]")
    console.print()
