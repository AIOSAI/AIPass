# =================== AIPass ====================
# Name: skills.py
# Description: Entry point CLI for drone @skills
# Version: 1.2.0
# Created: 2026-03-08
# Modified: 2026-10-24
# =============================================

"""Skills system entry point."""

import importlib
import os
import sys
from pathlib import Path

# Runs before any aipass import: the script dir would shadow the 'skills' package.
# resolve() reads the cwd on Windows, so a dead cwd falls back to abspath.
try:
    _script_dir = str(Path(__file__).resolve().parent)
except OSError as _resolve_error:
    # No logger yet (prax is not importable before this block): stderr is the last resort.
    sys.stderr.write(f"[skills] resolve() unavailable ({_resolve_error}); using the unresolved absolute spelling\n")
    _script_dir = str(Path(os.path.abspath(__file__)).parent)
if _script_dir in sys.path:
    sys.path.remove(_script_dir)

from aipass.prax import logger
from aipass.cli.apps.modules import console, escape

VERSION = "1.2.0"


def _header_description(path):
    """Return a module's '# Description:' header value, or None when it has none."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# Description:"):
            return line.split(":", 1)[1].strip()
    return None


def print_introspection(modules_dir=None):
    """Display module introspection info, derived from the modules directory."""
    modules_dir = Path(modules_dir) if modules_dir else Path(_script_dir) / "modules"
    console.print()
    console.print("[bold cyan]skills Entry Point[/bold cyan]")
    console.print("[dim]Capability framework for AI agents — discover, run, create, and validate skills[/dim]")
    console.print()
    console.print("[bold]Connected Modules:[/bold]")
    console.print("  [cyan]modules/[/cyan]")
    for path in sorted(modules_dir.glob("*.py")):
        # A '(disabled)' file is parked, not connected: its stem cannot be imported.
        if path.name == "__init__.py" or not path.stem.isidentifier():
            continue
        description = _header_description(path)
        suffix = f" ({description})" if description else ""
        console.print(f"    [dim]- {path.name}{suffix}[/dim]")
    console.print()
    console.print("[dim]Run 'drone @skills --help' for usage information[/dim]")
    console.print()


# Each verb is owned by one module; its handle_command is the only copy of the command.
_ROUTES = {
    "list": "discovery",
    "info": "loader",
    "run": "runner",
    "create": "creator",
    "validate": "validator",
    "on": "switch",
    "off": "switch",
    "switch": "switch",
}


def handle_command(command, args=None):
    """Route a skills command to the module that owns it."""
    args = args or []

    if command is None:
        print_introspection()
        return True

    if command in ("--help", "-h", "help"):
        print_help()
        return True

    if command in ("--version", "-V"):
        console.print(f"SKILLS v{VERSION}")
        return True

    module_name = _ROUTES.get(command)
    if module_name is None:
        logger.warning(f"unknown command: {command}")
        console.print(f"  Unknown command: {escape(command)}")
        console.print("  Run 'skills --help' for available commands.")
        return False

    # Imported per call: a bare self-map or --help loads no skill machinery.
    module = importlib.import_module(f"aipass.skills.apps.modules.{module_name}")
    return module.handle_command(command, args)


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
    console.print("  run <name> --help            Show a skill's SKILL.md instead of running it")
    console.print("  create <name>                Scaffold new skill (markdown only)")
    console.print("  create <name> --with-handler Scaffold with handler.py")
    console.print("  create <name> --full         Scaffold with full 3-layer structure")
    console.print("  create <name> --help         Scaffold flags and what each tier writes")
    console.print("  validate <name>              Check if skill requirements are met")
    console.print("  on <name>                    Reconnect a skill and start its processes")
    console.print("  off <name> \\[reason]          Disconnect a skill and stop its processes")
    console.print("  switch \\[name]                Show each skill's on/off state")
    console.print("  --help, -h, help             Show this help")
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
    console.print("  [green]drone @skills info screen_lock[/green]")
    console.print()
    console.print("  [dim]# Create a new skill[/dim]")
    console.print("  [green]drone @skills create my-skill --with-handler[/green]")
    console.print()
    console.print("  [dim]# Disconnect a skill from AIPass (stops its processes, survives reboot)[/dim]")
    console.print('  [green]drone @skills off screen_lock "not on this host"[/green]')


if __name__ == "__main__":
    if sys.platform == "win32":
        os.environ.setdefault("PYTHONUTF8", "1")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    args = sys.argv[1:]
    if not args:
        # Bare `drone @skills` is the live self-map; --help is the reference.
        ok = handle_command(None)
    else:
        command = args[0]
        remaining = args[1:] if len(args) > 1 else []
        ok = handle_command(command, remaining)

    # drone propagates this exit code; callers chain on it (`validate x && ...`).
    sys.exit(0 if ok else 1)
