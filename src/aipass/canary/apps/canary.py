"""
CANARY Branch - Main Orchestrator

Auto-discovery architecture:
- Scans modules/ directory for .py files with handle_command()
- Routes commands to discovered modules automatically
- No manual imports or routing needed
"""

import importlib
import os
import sys
from pathlib import Path
from typing import List, Any

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("AIPASS_BRANCH_NAME", "canary")

from aipass.prax import logger  # noqa: E402

# =============================================================================
# MODULE DISCOVERY
# =============================================================================

MODULES_DIR = Path(__file__).parent / "modules"


def _module_import_path(stem: str) -> str:
    """Return the correct import path for a module, handling both layouts."""
    try:
        importlib.import_module(f"aipass.canary.apps.modules.{stem}")
        return f"aipass.canary.apps.modules.{stem}"
    except ImportError:
        return f"apps.modules.{stem}"


def discover_modules() -> List[Any]:
    """Auto-discover modules in modules/ directory."""
    modules = []

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
            logger.error(f"[CANARY] Failed to load module {module_name}: {e}")

    return modules


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """Route command to appropriate module."""
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except Exception as e:
            logger.error(f"[CANARY] Module {module.__name__} error: {e}")
    return False


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main():
    """Main entry point - routes commands or shows help."""
    modules = discover_modules()
    args = sys.argv[1:]

    if len(args) == 0 or args[0] in ["--help", "-h", "help"]:
        print(f"CANARY - {len(modules)} modules discovered")
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
