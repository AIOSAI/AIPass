# =================== AIPass ====================
# Name: trigger.py
# Description: Entry point CLI for drone @trigger — event bus and error registry
# Version: 1.2.0
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""
TRIGGER Branch - Main Orchestrator
"""

import os
import sys
from pathlib import Path

import importlib
from typing import List, Any

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.cli.apps.modules import console, header, error, reset_command_state, resolve_exit

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

# Pinned to the README header version by test_trigger_entry.py.
__version__ = "3.0.0"


MODULES_DIR = Path(__file__).parent / "modules"


def discover_modules() -> List[Any]:
    """Auto-discover modules in modules/ directory"""
    modules = []

    if not MODULES_DIR.exists():
        logger.warning(f"[TRIGGER] Modules directory not found: {MODULES_DIR}")
        return modules

    for file_path in MODULES_DIR.glob("*.py"):
        if file_path.name.startswith("_"):
            continue

        module_name = f"aipass.trigger.apps.modules.{file_path.stem}"

        try:
            module = importlib.import_module(module_name)

            if hasattr(module, "handle_command"):
                modules.append(module)
                pass  # Module loaded successfully
            else:
                pass  # No handle_command() - skip silently

        except Exception as e:
            logger.error(f"[TRIGGER] Failed to load module {module_name}: {e}")

    return modules


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """Route command to appropriate module"""
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except Exception as e:
            logger.error(f"[TRIGGER] Module {module.__name__} error: {e}")

    return False


def print_introspection(modules: List[Any]):
    """Display discovered modules when run without arguments"""
    console.print()
    console.print("[bold cyan]TRIGGER - Branch Management System[/bold cyan]")
    console.print()
    console.print("[dim]Auto-discovered module orchestration[/dim]")
    console.print()

    console.print(f"[yellow]Discovered Modules:[/yellow] {len(modules)}")
    console.print()

    if modules:
        for module in modules:
            module_name = module.__name__.split(".")[-1]
            description = "No description"
            if module.__doc__:
                description = module.__doc__.strip().split("\n")[0]
            console.print(f"  [cyan]•[/cyan] {module_name:20} [dim]{description}[/dim]")
    else:
        console.print("  [dim]No modules discovered[/dim]")

    console.print()
    console.print("[dim]Run 'drone @trigger --help' for usage information[/dim]")
    console.print()


def print_help(modules: List[Any]):
    """Display Rich-formatted help"""
    console.print()
    header("TRIGGER - Branch Management System")
    console.print()

    console.print("[dim]Auto-discovered module orchestration[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()
    console.print("  [dim]drone @trigger <command> \\[args...][/dim]")
    console.print("  [dim]drone @trigger --help[/dim]")
    console.print("  [dim]drone @trigger --version[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]AVAILABLE COMMANDS:[/bold cyan]")
    console.print()

    if modules:
        for module in modules:
            module_name = module.__name__.split(".")[-1]
            description = "No description"
            if module.__doc__:
                description = module.__doc__.strip().split("\n")[0]

            console.print(f"  [green]{module_name:20}[/green] [dim]{description}[/dim]")
    else:
        console.print("  [dim]No modules discovered[/dim]")

    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]EXAMPLES:[/bold cyan]")
    console.print()
    console.print("  [dim]drone @trigger fire error_detected branch=api error_type=ImportError[/dim]")
    console.print("  [dim]drone @trigger errors list[/dim]")
    console.print("  [dim]drone @trigger medic status[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold]TIP:[/bold] For module-specific help:")
    console.print("  [dim]drone @trigger <command> --help[/dim]")
    console.print()
    console.print("[dim]The bus verbs are typed directly, not under a module name:[/dim]")
    console.print("  [dim]fire <event> \\[key=value ...] · list · status  →  drone @trigger core --help[/dim]")
    console.print()


def main(argv: list[str] | None = None):
    """Main entry point - routes commands or shows help."""
    # error() only sets a process flag; reset it here so a prior in-process
    # command cannot colour this one, and resolve_exit turns it into the exit code.
    reset_command_state()

    modules = discover_modules()

    args = sys.argv[1:] if argv is None else list(argv)

    if len(args) == 0:
        print_introspection(modules)
        return 0

    if args[0] in ["--version", "-V"]:
        console.print(f"TRIGGER v{__version__}")
        return 0

    if args[0] in ["--help", "-h", "help"]:
        print_help(modules)
        return 0

    command = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    if remaining_args and remaining_args[0] in ["--help", "-h"]:
        for module in modules:
            if module.handle_command(command, ["--help"]):
                return 0
        print_help(modules)
        return 0

    if route_command(command, remaining_args, modules):
        # Handled is not succeeded: resolve_exit returns 2 when the module refused via error().
        return resolve_exit(True)
    else:
        # Routing cannot tell which word was unknown, so name the whole invocation.
        attempted = " ".join([command, *remaining_args])
        console.print()
        error(f"Unknown command: {attempted}", suggestion="Run 'drone @trigger --help' for available commands")
        console.print()
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        console.print("\n\nOperation cancelled by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"TRIGGER entry point error: {e}", exc_info=True)
        error(f"Error: {e}")
        sys.exit(1)
