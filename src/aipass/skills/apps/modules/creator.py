# =================== AIPass ====================
# Name: creator.py
# Description: Scaffold new skills from templates
# Version: 1.3.0
# Created: 2026-03-07
# Modified: 2026-10-24
# =============================================

"""Skill creator module."""

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from aipass.skills.apps.handlers.creator_handler import create_skill as _handler_create_skill
from aipass.skills.apps.handlers.json import json_handler

try:
    from aipass.trigger.apps.modules.core import trigger
except ImportError:
    logger.warning("trigger module not available — skill events disabled")
    trigger = None


def handle_command(command: str, args: list) -> bool:
    """Handle the create command routed by the entry point."""
    if command != "create":
        return False
    if not args:
        print_introspection()
        error("Error: skill name required. Usage: skills create <name> [--with-handler|--full]")
        return False
    # A help flag anywhere is a question, never a skill name to scaffold.
    if any(arg in ("--help", "-h", "help") for arg in args):
        print_create_help()
        return True

    name = args[0]
    template_type = "markdown_only"
    if "--with-handler" in args:
        template_type = "with_handler"
    elif "--full" in args:
        template_type = "full"

    result = create_skill(name, template_type=template_type)
    if not result["success"]:
        error(f"Error: {result['error']}")
        return False

    logger.info(f"create: scaffolded skill '{name}' ({template_type})")
    return True


def print_create_help():
    """Print the create usage page: flags and what each tier writes."""
    console.print("Skills Create - Scaffold a new skill from a template")
    console.print()
    console.print("Usage:")
    console.print("  drone @skills create <name>                Create a markdown-only skill")
    console.print("  drone @skills create <name> --with-handler Create with handler.py")
    console.print("  drone @skills create <name> --full         Create with full 3-layer structure")
    console.print()
    console.print("Templates:")
    console.print("  markdown_only   SKILL.md with instructions (AI reads and follows)")
    console.print("  with_handler    SKILL.md + handler.py (programmatic execution)")
    console.print("  full            SKILL.md + apps/ structure (complex skills)")


def create_skill(name, template_type="markdown_only", target_dir=None):
    """Create a new skill from a template (target_dir defaults to ./.aipass/skills/)."""
    result = _handler_create_skill(name, template_type=template_type, target_dir=target_dir)

    if result["success"]:
        if trigger is not None:
            trigger.fire("skill_created", name=name, template_type=template_type, path=result["path"])

        console.print(f"  Created skill '{name}' at {result['path']}")
        console.print(f"  Template: {template_type}")
        console.print(f"  Files: {len(result['files'])}")
        for f in result["files"]:
            console.print(f"    - {f}")

    json_handler.log_operation(
        "skill_created",
        {
            "name": name,
            "template_type": template_type,
            "success": result["success"],
        },
    )
    return result


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]creator Module[/bold cyan]")
    console.print("[dim]Scaffold new skills from templates into a target location[/dim]")
    console.print()
    console.print("[bold]Connected Handlers:[/bold]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print(
        "    [dim]- creator_handler.py (create_skill — validate name, resolve template, copy to target)[/dim]"
    )
    console.print("    [dim]- template.py (copy_template, get_template — template resolution and file copy)[/dim]")
    console.print()
