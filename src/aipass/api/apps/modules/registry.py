# =================== AIPass ====================
# Name: registry.py
# Description: Auto-discovery walker for apps/integrations/*/driver.py
# Version: 1.0.0
# Created: 2026-04-15
# Modified: 2026-04-15
# =============================================
"""
Driver auto-discovery for @api integrations layer.

On first call to load_drivers(), walks apps/integrations/*/driver.py, imports each module,
and calls its register() hook. Subsequent calls are no-ops (idempotent via _loaded flag).

Each driver module is expected to:
  1. Import bridge: from aipass.api.apps.modules.bridge import register
  2. Implement a register() function that calls bridge.register(contract_name, fn)

Failure modes — all non-fatal:
  - Empty integrations/ dir → no drivers loaded, no log noise
  - Folder without driver.py → skipped silently
  - Import error → logged as WARNING, driver skipped, no crash
"""

import importlib.util
import sys
from pathlib import Path

from aipass.api.apps.handlers.json import json_handler
from aipass.cli.apps.modules import console, header
from aipass.prax.apps.modules.logger import system_logger as logger

_INTEGRATIONS_DIR = Path(__file__).parent.parent / "integrations"
_loaded: bool = False


def print_introspection() -> None:
    """Show registry introspection."""
    console.print()
    header("Registry — Driver Auto-Discovery")
    console.print()
    console.print("[cyan]Purpose:[/cyan] Auto-discover and load integration drivers from apps/integrations/*/driver.py")
    console.print()
    console.print(f"[cyan]Integrations dir:[/cyan] {_INTEGRATIONS_DIR}")
    console.print(f"[cyan]Loaded:[/cyan] {_loaded}")
    console.print()
    json_handler.log_operation("registry_introspection", {"loaded": _loaded, "dir": str(_INTEGRATIONS_DIR)})


def load_drivers(integrations_dir: Path | None = None) -> int:
    """
    Walk integrations_dir and load all driver.py files.

    Args:
        integrations_dir: Override path for testing. Defaults to apps/integrations/.

    Returns:
        Number of drivers successfully loaded.
    """
    global _loaded
    if _loaded and integrations_dir is None:
        return 0  # idempotent for production path

    target = integrations_dir if integrations_dir is not None else _INTEGRATIONS_DIR

    if not target.exists():
        return 0

    loaded = 0
    for project_dir in sorted(target.iterdir()):
        if not project_dir.is_dir():
            continue
        driver_path = project_dir / "driver.py"
        if not driver_path.exists():
            continue
        try:
            _import_driver(driver_path, project_dir.name)
            loaded += 1
        except Exception as exc:
            logger.warning(f"[registry] Skipping driver {project_dir.name}: {exc}")

    if integrations_dir is None:
        _loaded = True

    return loaded


def _import_driver(driver_path: Path, project_name: str) -> None:
    """Import a single driver.py and call its register() hook."""
    module_name = f"_aipass_integration_{project_name}"

    # Remove stale module if present (supports reload in tests)
    sys.modules.pop(module_name, None)

    spec = importlib.util.spec_from_file_location(module_name, driver_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create spec for {driver_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    if hasattr(module, "register"):
        module.register()
    # If no register() hook, driver is still loaded (might use bridge.register directly at module level)


def reset() -> None:
    """Reset loaded state. Intended for test teardown only."""
    global _loaded
    _loaded = False
