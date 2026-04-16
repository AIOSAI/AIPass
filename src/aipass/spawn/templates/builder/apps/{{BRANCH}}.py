"""
{{BRANCHNAME}} Branch - Main Orchestrator

Auto-discovery architecture:
- Scans modules/ directory for .py files with handle_command()
- Routes commands to discovered modules automatically
- No manual imports or routing needed
"""

import sys
import importlib
from pathlib import Path
from typing import List, Any

from aipass.prax import logger

# =============================================================================
# MODULE DISCOVERY
# =============================================================================

MODULES_DIR = Path(__file__).parent / "modules"


def discover_modules() -> List[Any]:
    """Auto-discover modules in modules/ directory."""
    modules = []

    if not MODULES_DIR.exists():
        return modules

    for file_path in MODULES_DIR.glob("*.py"):
        if file_path.name.startswith("_"):
            continue

        module_name = f"aipass.{{BRANCH}}.apps.modules.{file_path.stem}"

        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "handle_command"):
                modules.append(module)
        except Exception as e:
            logger.error(f"[{{BRANCHNAME}}] Failed to load module {module_name}: {e}")

    return modules


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """Route command to appropriate module."""
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except Exception as e:
            logger.error(f"[{{BRANCHNAME}}] Module {module.__name__} error: {e}")
    return False


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main():
    """Main entry point - routes commands or shows help."""
    modules = discover_modules()
    args = sys.argv[1:]

    if len(args) == 0 or args[0] in ["--help", "-h", "help"]:
        print(f"{{BRANCHNAME}} - {len(modules)} modules discovered")
        for module in modules:
            name = module.__name__.split(".")[-1]
            desc = (module.__doc__ or "").strip().split("\n")[0] if module.__doc__ else "No description"
            print(f"  {name:20} {desc}")
        return 0

    command = args[0]
    remaining = args[1:] if len(args) > 1 else []

    if route_command(command, remaining, modules):
        return 0

    print(f"Unknown command: {command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
