# =================== AIPass ====================
# Name: {{BRANCH}}.py
# Description: Entry point CLI for drone @{{BRANCH}}
# Version: 1.0.0
# Created: {{DATE}}
# Modified: {{DATE}}
# =============================================

"""
{{BRANCHNAME}} Branch - Main Orchestrator

Auto-discovery architecture:
- Scans modules/ directory for .py files with handle_command()
- Routes commands to discovered modules automatically
- No manual imports or routing needed

Entry point contains no business logic - modules implement functionality.
"""

import importlib
import os
import sys
from pathlib import Path
from typing import Any, List, Tuple

# Set before the prax import: the logger resolves its branch at import time,
# so a later setdefault would name the wrong branch in every log line.
os.environ.setdefault("AIPASS_BRANCH_NAME", "{{BRANCH}}")

# Rich markup below is non-ASCII (bullets, em dashes). On Windows the console
# defaults to cp1252, which raises UnicodeEncodeError mid-render - help output
# dies partway through instead of printing. Force UTF-8 before any console use.
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.cli.apps.modules import console, error  # noqa: E402
from aipass.prax import logger  # noqa: E402

__version__ = "1.0.0"

# =============================================================================
# MODULE DISCOVERY
# =============================================================================

MODULES_DIR = Path(__file__).parent / "modules"


def _module_import_path(stem: str) -> str:
    """Return the correct import path for a module, handling both layouts.

    Args:
        stem: Module filename without the .py suffix.

    Returns:
        The installed-package path when importable, else the local fallback.
    """
    try:
        importlib.import_module(f"aipass.{{BRANCH}}.apps.modules.{stem}")
        return f"aipass.{{BRANCH}}.apps.modules.{stem}"
    except (ImportError, OSError) as e:
        # Not silent: the fallback path is a real branch in behaviour, so the
        # reason it was taken has to stay readable afterwards.
        # OSError as well as ImportError: the package import runs the handler
        # access guard, which touches the filesystem, so an unreadable cwd
        # raises FileNotFoundError here — and the local layout is exactly the
        # right answer in that world too.
        logger.info("[{{BRANCHNAME}}] Package import failed for %s (%s) - using local layout", stem, e)
        return f"apps.modules.{stem}"


def discover_modules() -> List[Any]:
    """Auto-discover modules in modules/ directory.

    Returns:
        List of imported modules exposing handle_command().
    """
    modules: List[Any] = []

    if not MODULES_DIR.exists():
        return modules

    for file_path in MODULES_DIR.glob("*.py"):
        if file_path.name.startswith("_"):
            continue

        module_name = _module_import_path(file_path.stem)

        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "handle_command"):
                modules.append(module)
        except Exception as e:
            logger.error("[{{BRANCHNAME}}] Failed to load module %s: %s", module_name, e)

    return modules


def _module_summary(module: Any) -> Tuple[str, str]:
    """Return the short name and one-line description of a discovered module.

    Args:
        module: An imported module object.

    Returns:
        Tuple of (name, first docstring line or a placeholder).
    """
    name = module.__name__.split(".")[-1]
    doc = (module.__doc__ or "").strip()
    return name, doc.split("\n")[0] if doc else "No description"


# =============================================================================
# INTROSPECTION DISPLAY
# =============================================================================


def print_introspection() -> None:
    """Display the branch self-map: identity, purpose and discovered modules."""
    modules = discover_modules()

    console.print()
    console.print("[bold cyan]{{BRANCHNAME}}[/bold cyan]")
    console.print()
    console.print("[dim]{{PURPOSE_BRIEF}}[/dim]")
    console.print()

    console.print(f"[yellow]Discovered Modules:[/yellow] {len(modules)}")
    console.print()

    for module in modules:
        name, desc = _module_summary(module)
        console.print(f"  [cyan]*[/cyan] {name:20} [dim]{desc}[/dim]")

    if not modules:
        console.print("  [dim]none yet - add a module with handle_command() to modules/[/dim]")

    console.print()
    console.print("[dim]Run 'drone @{{BRANCH}} --help' for usage information[/dim]")
    console.print()


def print_help() -> None:
    """Rich-formatted top-level help for {{BRANCHNAME}}."""
    modules = discover_modules()

    console.print()
    console.print("[bold cyan]{{BRANCHNAME}}[/bold cyan]")
    console.print()
    console.print("[dim]{{PURPOSE_BRIEF}}[/dim]")
    console.print()

    console.print("[bold cyan]Usage:[/bold cyan]")
    console.print("  [green]drone @{{BRANCH}} <command>[/green] [dim]\\[options][/dim]")
    console.print()

    console.print("[yellow]Commands:[/yellow]")
    for module in modules:
        name, desc = _module_summary(module)
        console.print(f"  [green]{name:20}[/green] [dim]{desc}[/dim]")
    if not modules:
        console.print("  [dim]none yet - add a module with handle_command() to modules/[/dim]")
    console.print()

    console.print("[yellow]Flags:[/yellow]")
    console.print("  [cyan]--help, -h[/cyan]      Show this help")
    console.print("  [cyan]--version, -V[/cyan]   Show version")
    console.print()

    console.print("[yellow]Examples:[/yellow]")
    console.print("  $ drone @{{BRANCH}}")
    console.print("  $ drone @{{BRANCH}} --help")
    console.print("  $ drone @{{BRANCH}} --version")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """Route command to appropriate module.

    Args:
        command: Command name.
        args: Remaining arguments for the module.
        modules: Discovered modules to try in order.

    Returns:
        True if a module handled the command, False otherwise.
    """
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except Exception as e:
            logger.error("[{{BRANCHNAME}}] Module %s error: %s", module.__name__, e)
    return False


def _print_subcommand_help(command: str, modules: List[Any]) -> bool:
    """Show a subcommand's own help without executing it.

    Args:
        command: The subcommand the caller asked about.
        modules: Discovered modules to try in order.

    Returns:
        True if a module rendered its help, False if the command is unknown.
    """
    if route_command(command, ["--help"], modules):
        return True

    error(f"Unknown command: {command}")
    return False


# =============================================================================
# MAIN
# =============================================================================


def main() -> int:
    """Main entry point - routes commands or shows help.

    Returns:
        0 on success, 1 on an unknown command.
    """
    args = sys.argv[1:]

    if not args:
        print_introspection()
        return 0

    if args[0] in ("--help", "-h", "help"):
        print_help()
        return 0

    if args[0] in ("--version", "-V"):
        console.print(f"{{BRANCHNAME}} v{__version__}")
        return 0

    command = args[0]
    remaining = args[1:]

    modules = discover_modules()

    # Subcommand help must never execute the command. Checked BEFORE routing,
    # on `remaining` rather than the raw argv, so `{{BRANCH}} <cmd> --help`
    # shows that subcommand's help instead of running it.
    if remaining and remaining[0] in ("--help", "-h"):
        return 0 if _print_subcommand_help(command, modules) else 1

    if route_command(command, remaining, modules):
        return 0

    error(f"Unknown command: {command}")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.warning("[{{BRANCHNAME}}] Interrupted by user (KeyboardInterrupt)")
        sys.exit(130)
    except Exception as exc:
        logger.error("[{{BRANCHNAME}}] Unhandled error in main: %s", exc)
        sys.exit(1)
