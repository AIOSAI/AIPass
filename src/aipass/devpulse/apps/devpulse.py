"""
DEVPULSE Branch - Main Orchestrator

Auto-discovery architecture:
- Scans modules/ directory for .py files with handle_command()
- Routes commands to discovered modules automatically
- No manual imports or routing needed
"""

# META
# module: devpulse
# description: Orchestration hub — coordinates via dispatch + agents
# citizen_class: manager
# END META

import sys
import importlib
from pathlib import Path
from typing import Any

from aipass.prax import logger

from rich.console import Console

console = Console(stderr=True)

# =============================================================================
# MODULE DISCOVERY
# =============================================================================

MODULES_DIR = Path(__file__).parent / "modules"


def discover_modules() -> list[Any]:
    """Auto-discover modules in modules/ directory."""
    modules = []

    if not MODULES_DIR.exists():
        return modules

    for file_path in MODULES_DIR.glob("*.py"):
        if file_path.name.startswith("_"):
            continue

        # Try package import first, fall back to relative import
        module_names = [
            f"aipass.devpulse.apps.modules.{file_path.stem}",
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
            except (ImportError, ModuleNotFoundError):
                continue
            except Exception as e:
                logger.error(f"[DEVPULSE] Failed to load module {module_name}: {e}")
                loaded = True
                break

        if not loaded:
            logger.error(f"[DEVPULSE] Could not import module {file_path.stem}")

    return modules


def print_introspection():
    """Print branch introspection — discovered modules and capabilities."""
    modules = discover_modules()
    console.print("[bold cyan]DEVPULSE[/bold cyan] — Orchestration Hub")
    console.print(f"  Modules discovered: {len(modules)}")
    for module in modules:
        name = module.__name__.split(".")[-1]
        desc = (module.__doc__ or "").strip().split("\n")[0] if module.__doc__ else "No description"
        console.print(f"  {name:20} {desc}")


def route_command(command: str, args: list[str], modules: list[Any]) -> bool:
    """Route command to appropriate module."""
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except Exception as e:
            logger.error(f"[DEVPULSE] Module {module.__name__} error: {e}")
    return False


# =============================================================================
# HANDLER SECURITY GUARD
# =============================================================================


def handle_command(command: str, args: list) -> bool:
    """Entry point for drone routing. Guards against cross-branch misuse."""
    caller = Path.cwd().name
    if caller != "devpulse" and not any(p.name == "devpulse" for p in Path.cwd().parents):
        logger.warning(f"[DEVPULSE] Cross-branch call from {caller} — use ai_mail instead")

    return _handle_command(command, args)


def _handle_command(command: str, args: list) -> bool:
    """Internal command handler."""
    modules = discover_modules()

    if command in ["--help", "-h", "help"]:
        print_introspection()
        return True

    if command in ["--version", "-V"]:
        console.print("devpulse 1.0.0")
        return True

    return route_command(command, args, modules)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main():
    """Main entry point - routes commands or shows help."""
    args = sys.argv[1:]

    if len(args) == 0:
        print_introspection()
        return 0

    return 0 if _handle_command(args[0], args[1:]) else 1


if __name__ == "__main__":
    sys.exit(main())
