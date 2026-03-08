# ===================AIPASS====================
# META DATA HEADER
# Name: skills.py - Skills system entry point
# Date: 2026-03-07
# Version: 1.0.0
# Category: skills/apps
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-07): Initial implementation
#
# CODE STANDARDS:
#   - Entry point with handle_command() for drone routing
#   - Imports from modules layer only
#   - Formats and prints output
# =============================================

import sys
from pathlib import Path
# Ensure src/ is on sys.path so 'skills' package is resolvable.
# Also remove the script's own directory (apps/) from sys.path to prevent
# this file (skills.py) from shadowing the 'skills' package.
_script_dir = str(Path(__file__).resolve().parent)
if _script_dir in sys.path:
    sys.path.remove(_script_dir)
_src_dir = str(Path(__file__).resolve().parents[2])  # skills/apps/skills.py -> src/
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

"""Skills system entry point.

Provides handle_command(command, args) for drone routing.
Commands: list, info, run, create, validate, --help.
"""


def handle_command(command, args=None):
    """Route a skills command to the appropriate module.

    Args:
        command: The subcommand to execute.
        args: List of additional arguments.

    Returns:
        bool: True if command was handled, False otherwise.
    """
    args = args or []

    if command in ("--help", "help", None):
        _print_help()
        return True

    if command == "list":
        return _cmd_list()

    if command == "info":
        if not args:
            print("  Error: skill name required. Usage: skills info <name>")
            return False
        return _cmd_info(args[0])

    if command == "run":
        if not args:
            print("  Error: skill name required. Usage: skills run <name> [action] [args...]")
            return False
        name = args[0]
        action = args[1] if len(args) > 1 else None
        extra_args = _parse_extra_args(args[2:]) if len(args) > 2 else {}
        return _cmd_run(name, action, extra_args)

    if command == "create":
        if not args:
            print("  Error: skill name required. Usage: skills create <name> [--with-handler|--full]")
            return False
        return _cmd_create(args)

    if command == "validate":
        if not args:
            print("  Error: skill name required. Usage: skills validate <name>")
            return False
        return _cmd_validate(args[0])

    print(f"  Unknown command: {command}")
    print("  Run 'skills --help' for available commands.")
    return False


def _print_help():
    """Print skills help text."""
    print("Skills - Capability framework for AI agents")
    print()
    print("Usage:")
    print("  drone @skills <command> [args]")
    print()
    print("Commands:")
    print("  list                         Show all discovered skills")
    print("  info <name>                  Display SKILL.md contents")
    print("  run <name> [action] [args]   Execute a skill's handler")
    print("  create <name>                Scaffold new skill (markdown only)")
    print("  create <name> --with-handler Scaffold with handler.py")
    print("  create <name> --full         Scaffold with full 3-layer structure")
    print("  validate <name>              Check if skill requirements are met")
    print("  --help                       Show this help")
    print()
    print("Search paths (first match wins):")
    print("  1. .aipass/skills/           Project-local skills")
    print("  2. ~/.aipass/skills/         Global user skills")
    print("  3. src/skills/catalog/       Built-in skills")


def _cmd_list():
    """List all discovered skills."""
    from skills.apps.modules.discovery import discover_all

    skills = discover_all()

    if not skills:
        print("  No skills found.")
        print("  Create one with: drone @skills create <name>")
        return True

    print(f"  Found {len(skills)} skill(s):")
    print()

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
        print(f"  [{label}]")
        for skill in source_skills:
            handler_tag = " [handler]" if skill["has_handler"] else ""
            tags = ""
            if skill.get("tags"):
                tags = f" ({', '.join(skill['tags'])})"
            print(f"    {skill['name']:<25} {skill['description']}{handler_tag}{tags}")
        print()

    return True


def _cmd_info(name):
    """Display full SKILL.md contents for a skill."""
    from skills.apps.modules.loader import load_skill

    loaded = load_skill(name)
    if not loaded["success"]:
        print(f"  Error: {loaded['error']}")
        return False

    metadata = loaded["metadata"]
    body = loaded["body"]
    path = loaded["path"]

    print(f"  Skill: {metadata.get('name', name)}")
    print(f"  Version: {metadata.get('version', 'unknown')}")
    print(f"  Description: {metadata.get('description', 'No description')}")
    print(f"  Path: {path}")
    print(f"  Has Handler: {metadata.get('has_handler', False)}")

    tags = metadata.get("tags", [])
    if tags:
        print(f"  Tags: {', '.join(tags)}")

    requires = metadata.get("requires", {})
    if requires:
        pip_pkgs = requires.get("pip", [])
        bins = requires.get("bins", [])
        config = requires.get("config", [])
        if pip_pkgs:
            print(f"  Requires pip: {', '.join(pip_pkgs)}")
        if bins:
            print(f"  Requires bins: {', '.join(bins)}")
        if config:
            print(f"  Requires config: {', '.join(config)}")

    if body:
        print()
        print("  --- SKILL.md Body ---")
        for line in body.splitlines():
            print(f"  {line}")

    return True


def _cmd_run(name, action, extra_args):
    """Execute a skill."""
    from skills.apps.modules.runner import run_skill

    result = run_skill(name, action=action, args=extra_args)

    if result["success"]:
        if result["output"]:
            for line in result["output"].splitlines():
                print(f"  {line}")
    else:
        error = result.get("error", "Unknown error")
        print(f"  Error: {error}")

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
        print(f"  Error: {result['error']}")
        return False

    return True


def _cmd_validate(name):
    """Validate a skill's requirements."""
    from skills.apps.modules.loader import load_skill
    from skills.apps.handlers.validator import validate_skill

    loaded = load_skill(name)
    if not loaded["success"]:
        print(f"  Error: {loaded['error']}")
        return False

    result = validate_skill(loaded["metadata"])

    if result["valid"]:
        print(f"  Skill '{name}' - all requirements met.")
    else:
        print(f"  Skill '{name}' - requirements NOT met:")
        if result["missing_pip"]:
            print(f"    Missing pip packages: {', '.join(result['missing_pip'])}")
        if result["missing_bins"]:
            print(f"    Missing CLI tools: {', '.join(result['missing_bins'])}")
        if result["missing_config"]:
            print(f"    Missing config/env: {', '.join(result['missing_config'])}")

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
