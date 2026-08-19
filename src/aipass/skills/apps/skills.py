# =================== AIPass ====================
# Name: skills.py
# Description: Entry point CLI for drone @skills
# Version: 1.0.2
# Created: 2026-03-08
# Modified: 2026-08-11
# =============================================

import sys
from pathlib import Path

# Prevent this script's parent dir from shadowing the 'skills' package
_script_dir = str(Path(__file__).resolve().parent)
if _script_dir in sys.path:
    sys.path.remove(_script_dir)

from aipass.prax import logger  # noqa: E402
from aipass.cli.apps.modules import console, error  # noqa: E402

"""Skills system entry point.

Provides handle_command(command, args) for drone routing.
Commands: list, info, run, create, validate, --help.
"""


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]skills Entry Point[/bold cyan]")
    console.print("[dim]Capability framework for AI agents — discover, run, create, and validate skills[/dim]")
    console.print()
    console.print("[bold]Connected Modules:[/bold]")
    console.print("  [cyan]modules/[/cyan]")
    console.print("    [dim]- discovery.py (discover_all — scan search paths for skills)[/dim]")
    console.print("    [dim]- loader.py (load_skill — load SKILL.md metadata, body, and handler)[/dim]")
    console.print("    [dim]- runner.py (run_skill — execute handler-based or markdown-only skills)[/dim]")
    console.print("    [dim]- creator.py (create_skill — scaffold new skills from templates)[/dim]")
    console.print("    [dim]- validator.py (validate_skill — check skill requirements)[/dim]")
    console.print("    [dim]- switch.py (turn_on/turn_off — per-skill off-switch)[/dim]")
    console.print()
    console.print("[dim]Run 'drone @skills --help' for usage information[/dim]")
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
        # `run <skill> --help` must document the skill, not be dispatched as an
        # action named "--help": handlers that fall through to a default reading
        # (branch_health, inbox_check) answered with "Branch '--help' not found".
        if action in ("--help", "-h", "help"):
            return _cmd_info(name)
        extra_args = _parse_extra_args(args[2:]) if len(args) > 2 else {}
        return _cmd_run(name, action, extra_args)

    if command == "create":
        if not args:
            error("Error: skill name required. Usage: skills create <name> [--with-handler|--full]")
            return False
        if args[0] in ("--help", "-h", "help"):
            _print_create_help()
            return True
        return _cmd_create(args)

    if command == "validate":
        if not args:
            error("Error: skill name required. Usage: skills validate <name>")
            return False
        return _cmd_validate(args[0])

    if command in ("on", "off", "switch"):
        return _cmd_switch(command, args)

    console.print(f"  Unknown command: {command}")
    console.print("  Run 'skills --help' for available commands.")
    return False


def print_help():
    """Print skills help text."""
    console.print("Skills - Capability framework for AI agents")
    console.print()
    console.print("Usage:")
    console.print("  drone @skills <command> \\[args]")
    console.print()
    console.print("Commands:")
    console.print("  list                         Show all discovered skills")
    console.print("  info <name>                  Display SKILL.md contents")
    console.print("  run <name> \\[action] \\[args]   Execute a skill's handler")
    console.print("  create <name>                Scaffold new skill (markdown only)")
    console.print("  create <name> --with-handler Scaffold with handler.py")
    console.print("  create <name> --full         Scaffold with full 3-layer structure")
    console.print("  validate <name>              Check if skill requirements are met")
    console.print("  on <name>                    Reconnect a skill and start its processes")
    console.print("  off <name> \\[reason]         Disconnect a skill and stop its processes")
    console.print("  switch \\[name]               Show each skill's on/off state")
    console.print("  --help                       Show this help")
    console.print("  --version, -V                Show version")
    console.print()
    console.print("Search paths (first match wins):")
    console.print("  1. .aipass/skills/           Project-local skills")
    console.print("  2. ~/.aipass/skills/         Global user skills")
    console.print("  3. src/aipass/skills/lib/     Built-in skills")
    console.print()
    console.print("Examples:")
    console.print()
    console.print("  [dim]# List all available skills[/dim]")
    console.print("  [green]drone @skills list[/green]")
    console.print()
    console.print("  [dim]# Get info about a skill[/dim]")
    console.print("  [green]drone @skills info telegram[/green]")
    console.print()
    console.print("  [dim]# Create a new skill[/dim]")
    console.print("  [green]drone @skills create my-skill --with-handler[/green]")
    console.print()
    console.print("  [dim]# Disconnect a skill from AIPass (stops its processes, survives reboot)[/dim]")
    console.print('  [green]drone @skills off telegram "retired 2026-08-18"[/green]')


def _cmd_list():
    """List all discovered skills."""
    from aipass.skills.apps.handlers.switch_handler import SwitchStateUnreadable, read_state
    from aipass.skills.apps.modules.discovery import discover_all

    skills = discover_all()

    # A switched-off skill is still LISTED, marked. A dark skill you cannot see
    # is a dark skill you cannot turn back on.
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
            entry = switch_state.get(skill["name"])
            off_tag = ""
            if isinstance(entry, dict) and not entry.get("enabled", True):
                off_tag = " [red]\\[OFF][/red]"
            tags = ""
            if skill.get("tags"):
                tags = f" ({', '.join(skill['tags'])})"
            console.print(f"    {skill['name']:<25} {skill['description']}{handler_tag}{off_tag}{tags}")
        console.print()

    return True


def _cmd_info(name):
    """Display full SKILL.md contents for a skill."""
    from aipass.skills.apps.modules.loader import load_skill

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

    logger.info(f"info: loaded skill '{name}'")
    return True


def _cmd_run(name, action, extra_args):
    """Execute a skill."""
    from aipass.skills.apps.modules.runner import run_skill

    result = run_skill(name, action=action, args=extra_args)

    if result["success"]:
        logger.info(f"run: executed skill '{name}' action={action}")
        if result["output"]:
            for line in result["output"].splitlines():
                console.print(f"  {line}")
    else:
        err = result.get("error", "Unknown error")
        error(f"Error: {err}")

    return result["success"]


def _print_create_help():
    """Print help text for the create subcommand."""
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


def _cmd_create(args):
    """Create a new skill from a template."""
    from aipass.skills.apps.modules.creator import create_skill

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

    logger.info(f"create: scaffolded skill '{name}' ({template_type})")
    return True


def _cmd_validate(name):
    """Validate a skill's requirements."""
    from aipass.skills.apps.modules.loader import load_skill
    from aipass.skills.apps.modules.validator import validate_skill

    loaded = load_skill(name)
    if not loaded["success"]:
        error(f"Error: {loaded['error']}")
        return False

    result = validate_skill(loaded["metadata"])

    if result["valid"]:
        logger.info(f"validate: skill '{name}' passed all requirements")
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


def _cmd_switch(command, args):
    """Route an off-switch command to the switch module.

    Args:
        command: One of on, off, switch.
        args: Skill name, plus an optional reason for `off`.

    Returns:
        bool: True when the command succeeded.
    """
    from aipass.skills.apps.modules.switch import show_switch, switch_off, switch_on

    if command == "switch":
        return show_switch(args[0] if args else None)

    if not args:
        error(f"Error: skill name required. Usage: skills {command} <name>")
        return False

    if command == "on":
        return switch_on(args[0])

    reason = " ".join(args[1:]) if len(args) > 1 else None
    return switch_off(args[0], reason)


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
    import os
    import sys

    if sys.platform == "win32":
        os.environ.setdefault("PYTHONUTF8", "1")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = sys.argv[1:]
    if not args:
        ok = handle_command("--help")
    else:
        command = args[0]
        remaining = args[1:] if len(args) > 1 else []
        ok = handle_command(command, remaining)

    # drone runs a branch command as a subprocess and propagates its return code.
    # Discarding the result here made every failure — unknown skill, missing
    # argument, unknown command — exit 0, so `drone @skills validate x && ...`
    # ran the second half on a failed validate.
    sys.exit(0 if ok else 1)
