# =================== AIPass ====================
# Name: flow.py
# Description: Entry point CLI for drone @flow — plan lifecycle management
# Version: 1.1.0
# Created: 2026-03-08
# Modified: 2026-09-15
# =============================================

"""
Flow Branch - Main Orchestrator

Auto-discovery architecture:
- Scans modules/ directory for .py files with handle_command()
- Routes commands to discovered modules automatically
- No manual imports or routing needed
"""

# ruff: noqa: E402
# INFRASTRUCTURE IMPORT PATTERN
import sys
import os

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path

# NOTE: this file has no module-level path resolution. _PKG_ROOT used to sit
# here as Path(__file__).resolve().parents[2] — a cwd read on Windows at import
# time — and it was assigned once and never read. Removed 2026-08-31 rather than
# routed through handlers/repo_root: the entry point should not reach into
# handlers, and the value was dead. MODULES_DIR below uses Path(__file__).parent
# with no resolve(), which touches no filesystem at all.

# Standard library imports
import importlib
import signal
from typing import List, Any

# Handle broken pipe gracefully (e.g. output piped to head)
# SIGPIPE does not exist on Windows
if hasattr(signal, "SIGPIPE"):
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

# Prax logger
from aipass.prax.apps.modules.logger import system_logger as logger

# CLI services for formatted output
from aipass.cli.apps.modules import console, header, error

# =============================================================================
# MODULE DISCOVERY
# =============================================================================

MODULES_DIR = Path(__file__).parent / "modules"


def discover_modules() -> List[Any]:
    """
    Auto-discover modules in modules/ directory

    Modules must implement handle_command(command: str, args: List[str]) -> bool

    Returns:
        List of module objects with handle_command function
    """
    modules = []

    if not MODULES_DIR.exists():
        logger.warning(f"[FLOW] Modules directory not found: {MODULES_DIR}")
        return modules

    # Discover all .py files (except __init__.py and those starting with _)
    for file_path in MODULES_DIR.glob("*.py"):
        if file_path.name.startswith("_"):
            continue

        module_name = f"aipass.flow.apps.modules.{file_path.stem}"

        try:
            module = importlib.import_module(module_name)

            # Check if module has handle_command function
            if hasattr(module, "handle_command"):
                modules.append(module)
                logger.info(f"[FLOW] Loaded module: {file_path.stem}")
            else:
                logger.info(f"[FLOW] Skipped {file_path.stem} - no handle_command()")

        except Exception as e:
            logger.error(f"[FLOW] Failed to load module {module_name}: {e}")

    return modules


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """
    Route command to appropriate module

    Args:
        command: Command name (e.g., 'create', 'delete', 'list')
        args: Additional arguments
        modules: List of discovered modules

    Returns:
        True if command was handled, False otherwise
    """
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except BrokenPipeError:
            logger.info(f"[FLOW] Broken pipe in {module.__name__} (stdout closed early)")
            return True
        except Exception as e:
            logger.error(f"[FLOW] Module {module.__name__} error: {e}")

    return False


# =============================================================================
# MAIN
# =============================================================================


def main():
    """Main entry point - routes commands or shows help"""
    try:
        return _main_impl()
    except Exception as exc:
        logger.error("[flow] Unhandled error in main: %s", exc)
        error(f"Unexpected error: {exc}")
        return 1


def _main_impl():
    """Internal implementation of main — separated for catch-all handler."""

    # Discover available modules
    modules = discover_modules()

    if not modules:
        logger.warning("[FLOW] No modules discovered")
        error("No modules available")
        return 1

    # Parse arguments
    args = sys.argv[1:]

    # Show introspection when run with no arguments
    if len(args) == 0:
        print_introspection(modules)
        return 0

    # Show version
    if args[0] in ["--version", "-V"]:
        console.print(f"FLOW v{BRANCH_VERSION}")
        return 0

    # Show help for explicit help flags
    if args[0] in ["--help", "-h", "help"]:
        print_help(modules)
        return 0

    # Extract command and remaining args
    # Pattern: flow <command> <args...>
    # Example: flow create . "Subject"
    command = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    # Route to modules (modules handle their own --help internally)
    if route_command(command, remaining_args, modules):
        return 0

    # Fallback: try module-specific help if command wasn't handled
    if remaining_args and remaining_args[0] in ["--help", "-h"]:
        print_module_help(command, modules)
        return 0
    else:
        console.print()
        error(f"Unknown command: {command}")
        console.print()
        console.print("Run [dim]drone @flow --help[/dim] for available commands")
        console.print()
        return 1


def print_introspection(modules: List[Any]):
    """Display discovered modules with Rich formatting (run with no args)"""
    console.print()
    console.print("[bold cyan]Flow - PLAN Management System[/bold cyan]")
    console.print()
    console.print("[dim]Task orchestration and workflow management[/dim]")
    console.print()

    console.print(f"[yellow]Discovered Modules:[/yellow] {len(modules)}")
    console.print()

    if modules:
        for module in modules:
            module_name = module.__name__.split(".")[-1]
            # Get first line of docstring
            description = "No description"
            if module.__doc__:
                description = module.__doc__.strip().split("\n")[0]
            console.print(f"  [cyan]•[/cyan] {module_name:20} [dim]{description}[/dim]")
    else:
        console.print("  [dim]No modules discovered[/dim]")

    console.print()
    console.print("[dim]Run 'drone @flow --help' for usage information[/dim]")
    console.print()


# The branch version --version prints. It lived as a literal inside the print
# call and drifted from the README header (2.2.1 printed against 2.6.0
# documented) because nothing could read it. One name, one place.
BRANCH_VERSION = "2.7.0"


def module_verbs(module: Any) -> str:
    """
    Render the verbs a module actually answers to, for the help table.

    A module owning ONE verb is named by the first segment of its filename
    (`create_plan` -> `create`). That derivation is wrong for a module owning
    several: `template_manager` answers to `templates`, `register`, `unregister`
    and `scan`, and never to `template`, so the derived name published a verb
    that does not exist. A module owning more than one declares them in
    COMMAND_VERBS and that list wins.

    Args:
        module: A discovered command module

    Returns:
        Comma-separated verbs, the string the help table prints
    """
    declared = getattr(module, "COMMAND_VERBS", None)
    if declared:
        return ", ".join(declared)
    module_name = module.__name__.split(".")[-1]
    return module_name.split("_")[0] if "_" in module_name else module_name


def print_help(modules: List[Any]):
    """Display Rich-formatted help (run with --help)"""
    console.print()
    header("Flow - PLAN Management System")
    console.print()

    console.print("[dim]Task orchestration and workflow management for AIPass[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()
    console.print("  [dim]drone @flow <command> \\[args...][/dim]")
    console.print("  [dim]drone @flow --help[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]AVAILABLE COMMANDS:[/bold cyan]")
    console.print()
    console.print("[dim]Call a command by the verb shown. The module's full name is not a command.[/dim]")
    console.print()

    if modules:
        # Width follows the longest verb list, so a module owning four verbs
        # does not push every description out of its column.
        verbs = {module: module_verbs(module) for module in modules}
        width = max((len(v) for v in verbs.values()), default=20)
        for module, verb_list in verbs.items():
            # Get first line of docstring
            description = "No description"
            if module.__doc__:
                description = module.__doc__.strip().split("\n")[0]

            console.print(f"  [green]{verb_list:{width}}[/green] [dim]{description}[/dim]")
    else:
        console.print("  [dim]No modules discovered[/dim]")

    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]EXAMPLES:[/bold cyan]")
    console.print()
    console.print("  [yellow]Create plans:[/yellow]")
    console.print('    [dim]drone @flow create . "Implementation task"[/dim]          [dim]# FPLAN (default)[/dim]')
    console.print(
        '    [dim]drone @flow create . "subject" master[/dim]               [dim]# FPLAN master template[/dim]'
    )
    console.print('    [dim]drone @flow create . "Design topic" dplan[/dim]           [dim]# DPLAN[/dim]')
    console.print()
    console.print("  [yellow]Close plans:[/yellow]")
    console.print("    [dim]drone @flow close FPLAN-0042[/dim]")
    console.print("    [dim]drone @flow close DPLAN-0005[/dim]")
    console.print("    [dim]drone @flow close --all[/dim]")
    console.print("    [dim]drone @flow close --all --dry-run[/dim]              [dim]# Preview, change nothing[/dim]")
    console.print(
        "    [dim]drone @flow close --all --exclude-type APLAN[/dim]   [dim]# Hold a type back (repeatable)[/dim]"
    )
    console.print()
    console.print("  [yellow]List plans:[/yellow]")
    console.print("    [dim]drone @flow list open[/dim]                             [dim]# Open plans[/dim]")
    console.print("    [dim]drone @flow list all[/dim]                              [dim]# All plans[/dim]")
    console.print()
    console.print("  [yellow]Templates:[/yellow]")
    console.print("    [dim]drone @flow templates[/dim]                             [dim]# List registered types[/dim]")
    console.print(
        "    [dim]drone @flow scan[/dim]                                  [dim]# Find unregistered dirs[/dim]"
    )
    console.print("    [dim]drone @flow register testing TPLAN[/dim]                [dim]# Register new type[/dim]")
    console.print("    [dim]drone @flow unregister testing[/dim]                    [dim]# Remove type[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold]TIP:[/bold] For module-specific help:")
    console.print("  [dim]drone @flow <command> --help[/dim]")
    console.print("  [dim]drone @flow --version[/dim]                              [dim]# Branch version[/dim]")
    console.print()


def print_module_help(command: str, modules: List[Any]):
    """Display module-specific help with Rich formatting"""
    # Try to find the module that handles this command
    target_module = None
    for module in modules:
        module_name = module.__name__.split(".")[-1]
        # Check if module name matches command (e.g., create_plan matches "create" or "create_plan")
        if command == module_name or module_name.startswith(command):
            target_module = module
            break

    if not target_module:
        console.print()
        error(f"Unknown command: {command}")
        console.print()
        console.print("Run [dim]drone @flow --help[/dim] for available commands")
        console.print()
        return

    console.print()
    module_name = target_module.__name__.split(".")[-1]
    header(f"Flow - {module_name} Command")
    console.print()

    # Display full docstring if available
    if target_module.__doc__:
        docstring = target_module.__doc__.strip()
        console.print(f"[dim]{docstring}[/dim]")
    else:
        console.print("[dim]No documentation available[/dim]")

    console.print()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        import os

        logger.info("[FLOW] Broken pipe in main (stdout closed early)")
        try:
            sys.stdout.close()
        except Exception as e:
            logger.warning(f"[FLOW] Error closing stdout after broken pipe: {e}")
        os._exit(0)
