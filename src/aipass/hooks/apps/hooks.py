# =================== AIPass ====================
# Name: hooks.py
# Version: 1.1.1
# Description: Hook infrastructure — drone entry point
# Branch: hooks
# Layer: apps
# Created: 2026-05-18
# Modified: 2026-08-11
# =============================================

"""
HOOKS Branch - Main Orchestrator

Auto-discovery architecture:
- Scans modules/ directory for .py files with handle_command()
- Routes commands to discovered modules automatically
- No manual imports or routing needed
"""

import os
import sys
import importlib
from pathlib import Path
from typing import Any

os.environ.setdefault("AIPASS_BRANCH_NAME", "hooks")

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax.apps.modules.logger import system_logger as logger  # noqa: E402
from aipass.cli.apps.modules import console  # noqa: E402

# =============================================================================
# MODULE DISCOVERY
# =============================================================================

MODULES_DIR = Path(__file__).parent / "modules"


def discover_modules() -> list[Any]:
    """Auto-discover modules in modules/ directory."""
    modules = []

    if not MODULES_DIR.exists():
        return modules

    for file_path in sorted(MODULES_DIR.glob("*.py")):
        if file_path.name.startswith("_"):
            continue

        module_names = [
            f"aipass.hooks.apps.modules.{file_path.stem}",
            f"apps.modules.{file_path.stem}",
        ]

        loaded = False
        for module_name in module_names:
            try:
                module = importlib.import_module(module_name)
                if hasattr(module, "handle_command"):
                    modules.append(module)
                loaded = True
                break
            except (ImportError, ModuleNotFoundError) as e:
                logger.info("[HOOKS] Module %s not found: %s", module_name, e)
                continue
            except Exception as e:
                logger.error("[HOOKS] Failed to load module %s: %s", module_name, e)
                loaded = True
                break

        if not loaded:
            logger.error("[HOOKS] Could not import module %s", file_path.stem)

    return modules


def print_introspection():
    """Print branch introspection — discovered modules and capabilities."""
    modules = discover_modules()
    console.print()
    console.print("[bold cyan]HOOKS — Hook Infrastructure for AIPass[/bold cyan]")
    console.print()
    console.print("[dim]Dispatches hooks across platforms with per-project config, logging, and crash isolation.[/dim]")
    console.print()

    console.print(f"[yellow]Discovered Modules:[/yellow] {len(modules)}")
    console.print()
    for module in modules:
        name = module.__name__.split(".")[-1]
        desc = (module.__doc__ or "").strip().split("\n")[0] if module.__doc__ else "No description"
        console.print(f"  [cyan]•[/cyan] {name:20} [dim]{desc}[/dim]")

    console.print()
    console.print("Run [green]'drone @hooks --help'[/green] for usage information")
    console.print()


def print_help():
    """Print CLI help — usage instructions and available commands."""
    modules = discover_modules()
    console.print()
    console.print("[bold cyan]HOOKS[/bold cyan] [dim]v1.1.0[/dim] — Hook Infrastructure for AIPass")
    console.print()
    console.print("[dim]Dispatches hooks across platforms with per-project config, logging, and crash isolation.[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()
    console.print("  [dim]drone @hooks <command> \\[args...][/dim]")
    console.print("  [dim]drone @hooks --help[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]COMMANDS:[/bold cyan]")
    console.print()
    for module in modules:
        commands = getattr(module, "HELP_COMMANDS", None)
        if commands:
            for cmd, desc in commands:
                console.print(f"  [green]{cmd:26}[/green] [dim]{desc}[/dim]")
        else:
            name = module.__name__.split(".")[-1]
            desc = (module.__doc__ or "").strip().split("\n")[0] if module.__doc__ else "No description"
            console.print(f"  [green]{name:26}[/green] [dim]{desc}[/dim]")

    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]BRIDGES:[/bold cyan]")
    console.print()
    console.print(
        "  [green]claude[/green]                     [dim]Claude Code bridge (provider settings entry point)[/dim]"
    )
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]EXAMPLES:[/bold cyan]")
    console.print()
    console.print("  [dim]drone @hooks status[/dim]              [dim]# Show hook config for current project[/dim]")
    console.print("  [dim]drone @hooks log[/dim]                 [dim]# Tail recent hook activity[/dim]")
    console.print("  [dim]drone @hooks hooksound off[/dim]       [dim]# Mute all hook sounds[/dim]")
    console.print("  [dim]drone @hooks hooksound on[/dim]        [dim]# Unmute all hook sounds[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]FLAGS:[/bold cyan]")
    console.print()
    console.print("  [green]--help, -h[/green]                 [dim]Show this help message[/dim]")
    console.print("  [green]--version, -V[/green]              [dim]Show version[/dim]")
    console.print()
    console.print("[bold]TIP:[/bold] For command-specific help:")
    console.print("  [dim]drone @hooks <command> --help[/dim]")
    console.print()


def route_command(command: str, args: list[str], modules: list[Any]) -> bool:
    """Route command to appropriate module."""
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except Exception as e:
            logger.error("[HOOKS] Module %s error: %s", module.__name__, e)
    return False


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def handle_command(command: str, args: list) -> bool:
    """Entry point for drone routing."""
    modules = discover_modules()

    if command in ["--help", "-h", "help"]:
        print_help()
        return True

    if command in ["--version", "-V"]:
        console.print("hooks 1.1.0")
        return True

    return route_command(command, args, modules)


def main() -> int:
    """Main entry point — routes commands or shows help."""
    args = sys.argv[1:]

    if not args:
        print_introspection()
        return 0

    if handle_command(args[0], args[1:]):
        return 0

    console.print(f"Unknown command: {args[0]}. Try: drone @hooks --help")
    return 1


if __name__ == "__main__":
    sys.exit(main())
