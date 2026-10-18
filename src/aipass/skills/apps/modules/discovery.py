# =================== AIPass ====================
# Name: discovery.py
# Description: Find skills across search paths
# Version: 1.1.0
# Created: 2026-03-07
# Modified: 2026-10-17
# =============================================

"""Skill discovery module."""

from aipass.prax import logger  # noqa: F401
from aipass.cli.apps.modules import console
from aipass.skills.apps.handlers.discovery_handler import (
    get_search_paths,
    discover_skills_in_path,
    parse_frontmatter,  # noqa: F401
)
from aipass.skills.apps.handlers.registry import build_registry
from aipass.skills.apps.handlers.json import json_handler


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point."""
    if not args:
        print_introspection()
        return True
    if "--help" in args:
        print_introspection()
        return True

    if command in ("discover", "list"):
        skills = discover_all()

        if not skills:
            console.print("  No skills found.")
            console.print("  Create one with: drone @skills create <name>")
            return True

        console.print(f"  Found {len(skills)} skill(s):")
        console.print()

        sources = {}
        for skill in skills:
            source = skill["source"]
            if source not in sources:
                sources[source] = []
            sources[source].append(skill)

        source_labels = {"project": "Project", "global": "Global", "builtin": "Built-in"}

        for source, source_skills in sources.items():
            label = source_labels.get(source, source)
            console.print(f"  \\[{label}]")
            for skill in source_skills:
                handler_tag = " \\[handler]" if skill["has_handler"] else ""
                tags = ""
                if skill.get("tags"):
                    tags = f" ({', '.join(skill['tags'])})"
                console.print(f"    {skill['name']:<25} {skill['description']}{handler_tag}{tags}")
            console.print()

        return True

    return False


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
        "    [dim]- discovery_handler.py (get_search_paths, discover_skills_in_path,"
        " parse_frontmatter — path scanning and SKILL.md parsing)[/dim]"
    )
    console.print("    [dim]- registry.py (build_registry — deduplicated skill registry from search paths)[/dim]")
    console.print()
