# =================== AIPass ====================
# Name: skills.py
# Description: Entry point CLI for drone @skills
# Version: 1.0.1
# Created: 2026-03-08
# Modified: 2026-03-28
# =============================================

import sys
from pathlib import Path

# Prevent this script's parent dir from shadowing the 'skills' package
_script_dir = str(Path(__file__).resolve().parent)
if _script_dir in sys.path:
    sys.path.remove(_script_dir)

from aipass.prax import logger
from aipass.cli.apps.modules import console, error

"""Skills system entry point.

Provides handle_command(command, args) for drone routing.
Commands: list, info, run, create, validate, --help.
"""


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("skills Entry Point")
    console.print("Capability framework for AI agents — discover, run, create, and validate skills")
    console.print()
    console.print("Connected Modules:")
    console.print("  modules/")
    console.print("    - discovery.py (discover_all — scan search paths for skills)")
    console.print("    - loader.py (load_skill — load SKILL.md metadata, body, and handler)")
    console.print("    - runner.py (run_skill — execute handler-based or markdown-only skills)")
    console.print("    - creator.py (create_skill — scaffold new skills from templates)")
    console.print("    - validator.py (validate_skill — check skill requirements)")
    console.print()


def handle_command(command, args=None):
    """Route a skills command to the appropriate module.

    Args:
        command: The subcommand to execute.
        args: List of additional arguments.

    Returns:
        bool: True if command was handled, False otherwise.
    """
    args = args or []

    if command is None:
        print_introspection()
        return True

    if command in ("--help", "-h", "help"):
        print_help()
        return True

    if command in ("--version", "-V"):
        console.print("SKILLS v1.0.0")
        return True

    if command == "list":
        return _cmd_list()

    if command == "info":
        if not args:
            error("Error: skill name required. Usage: skills info <name>")
            return False
        return _cmd_info(args[0])

    if command == "run":
        if not args:
            error("Error: skill name required. Usage: skills run <name> [action] [args...]")
            return False
        name = args[0]
        action = args[1] if len(args) > 1 else None
        extra_args = _parse_extra_args(args[2:]) if len(args) > 2 else {}
        return _cmd_run(name, action, extra_args)

    if command == "create":
        if not args:
            error("Error: skill name required. Usage: skills create <name> [--with-handler|--full]")
            return False
        return _cmd_create(args)

    if command == "validate":
        if not args:
            error("Error: skill name required. Usage: skills validate <name>")
            return False
        return _cmd_validate(args[0])

    console.print(f"  Unknown command: {command}")
    console.print("  Run 'skills --help' for available commands.")
    return False


def print_help():
    """Print skills help text."""
    console.print("Skills - Capability framework for AI agents")
    console.print()
    console.print("Usage:")
    console.print("  drone @skills <command> [args]")
    console.print()
    console.print("Commands:")
    console.print("  list                         Show all discovered skills")
    console.print("  info <name>                  Display SKILL.md contents")
    console.print("  run <name> [action] [args]   Execute a skill's handler")
    console.print("  create <name>                Scaffold new skill (markdown only)")
    console.print("  create <name> --with-handler Scaffold with handler.py")
    console.print("  create <name> --full         Scaffold with full 3-layer structure")
    console.print("  validate <name>              Check if skill requirements are met")
    console.print("  --help                       Show this help")
    console.print("  --version, -V                Show version")
    console.print()
    console.print("Search paths (first match wins):")
    console.print("  1. .aipass/skills/           Project-local skills")
    console.print("  2. ~/.aipass/skills/         Global user skills")
    console.print("  3. src/skills/catalog/       Built-in skills")


def _cmd_list():
    """List all discovered skills."""
    from skills.apps.modules.discovery import discover_all

    skills = discover_all()

    if not skills:
        console.print("  No skills found.")
        console.print("  Create one with: drone @skills create <name>")
        return True

    console.print(f"  Found {len(skills)} skill(s):")
    console.print()

    # Group by source
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


def _cmd_info(name):
    """Display full SKILL.md contents for a skill."""
    from skills.apps.modules.loader import load_skill

    loaded = load_skill(name)
    if not loaded["success"]:
        error(f"Error: {loaded['error']}")
        return False

    metadata = loaded["metadata"]
    body = loaded["body"]
    path = loaded["path"]

    console.print(f"  Skill: {metadata.get('name', name)}")
    console.print(f"  Version: {metadata.get('version', 'unknown')}")
    console.print(f"  Description: {metadata.get('description', 'No description')}")
    console.print(f"  Path: {path}")
    console.print(f"  Has Handler: {metadata.get('has_handler', False)}")

    tags = metadata.get("tags", [])
    if tags:
        console.print(f"  Tags: {', '.join(tags)}")

    requires = metadata.get("requires", {})
    if requires:
        pip_pkgs = requires.get("pip", [])
        bins = requires.get("bins", [])
        config = requires.get("config", [])
        if pip_pkgs:
            console.print(f"  Requires pip: {', '.join(pip_pkgs)}")
        if bins:
            console.print(f"  Requires bins: {', '.join(bins)}")
        if config:
            console.print(f"  Requires config: {', '.join(config)}")

    if body:
        console.print()
        console.print("  --- SKILL.md Body ---")
        for line in body.splitlines():
            console.print(f"  {line}")

    return True


def _cmd_run(name, action, extra_args):
    """Execute a skill."""
    from skills.apps.modules.runner import run_skill

    result = run_skill(name, action=action, args=extra_args)

    if result["success"]:
        if result["output"]:
            for line in result["output"].splitlines():
                console.print(f"  {line}")
    else:
        err = result.get("error", "Unknown error")
        error(f"Error: {err}")

    return result["success"]


def _cmd_create(args):
    """Create a new skill from a template."""
    from skills.apps.modules.creator import create_skill

    name = args[0]

    # Determine template type from flags
    template_type = "markdown_only"
    if "--with-handler" in args:
        template_type = "with_handler"
    elif "--full" in args:
        template_type = "full"

    result = create_skill(name, template_type=template_type)

    if not result["success"]:
        error(f"Error: {result['error']}")
        return False

    return True


def _cmd_validate(name):
    """Validate a skill's requirements."""
    from skills.apps.modules.loader import load_skill
    from skills.apps.modules.validator import validate_skill

    loaded = load_skill(name)
    if not loaded["success"]:
        error(f"Error: {loaded['error']}")
        return False

    result = validate_skill(loaded["metadata"])

    if result["valid"]:
        console.print(f"  Skill '{name}' - all requirements met.")
    else:
        console.print(f"  Skill '{name}' - requirements NOT met:")
        if result["missing_pip"]:
            console.print(f"    Missing pip packages: {', '.join(result['missing_pip'])}")
        if result["missing_bins"]:
            console.print(f"    Missing CLI tools: {', '.join(result['missing_bins'])}")
        if result["missing_config"]:
            console.print(f"    Missing config/env: {', '.join(result['missing_config'])}")

    return result["valid"]


def _parse_extra_args(arg_list):
    """Parse extra arguments into a dict.

    Supports key=value pairs and positional arguments.

    Args:
        arg_list: List of argument strings.

    Returns:
        dict: Parsed arguments.
    """
    result = {}
    positional_idx = 0

    for arg in arg_list:
        if "=" in arg:
            key, value = arg.split("=", 1)
            result[key] = value
        else:
            result[f"arg{positional_idx}"] = arg
            positional_idx += 1

    return result


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if not args:
        handle_command("--help")
    else:
        command = args[0]
        remaining = args[1:] if len(args) > 1 else []
        handle_command(command, remaining)
