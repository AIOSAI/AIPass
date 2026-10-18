"""
AIPass Drone — Command routing & discovery module.

Reference: docs/routing_and_resolution.md
"""

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # Import-free type visibility; never executed at runtime.
    from aipass.drone.apps.modules.config import get_registry_path, reset_registry_path, set_registry_path
    from aipass.drone.apps.modules.discovery import HelpResult, discover_modules, get_help, get_system_help
    from aipass.drone.apps.modules import (
        BranchAlreadyExistsError,
        BranchNotFoundError,
        CommandExecutionError,
        CommandResult,
        InvalidPathError,
        RegistryCorruptError,
        RegistryError,
        RegistryNotFoundError,
        RegistryPermissionError,
        RoutingError,
    )
    from aipass.drone.apps.modules.resolver import branch_exists, get_branch_info, list_branches, resolve_branch
    from aipass.drone.apps.modules.router import route_all, route_command

__version__ = "1.2.0"

# Lazy (PEP 562): importing this package imports no module, so a foreign `import aipass.drone`
# is not a kin frame standing between a caller and the handlers fence.
_LAZY = {
    **dict.fromkeys(("get_registry_path", "reset_registry_path", "set_registry_path"), "config"),
    **dict.fromkeys(("HelpResult", "discover_modules", "get_help", "get_system_help"), "discovery"),
    **dict.fromkeys(("branch_exists", "get_branch_info", "list_branches", "resolve_branch"), "resolver"),
    **dict.fromkeys(("route_all", "route_command"), "router"),
    **dict.fromkeys(
        (
            "BranchAlreadyExistsError",
            "BranchNotFoundError",
            "CommandExecutionError",
            "CommandResult",
            "InvalidPathError",
            "RegistryCorruptError",
            "RegistryError",
            "RegistryNotFoundError",
            "RegistryPermissionError",
            "RoutingError",
        ),
        "",
    ),
}


def __getattr__(name: str) -> Any:
    """Load a public name from its apps.modules home on first access, then keep it."""
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    home = "aipass.drone.apps.modules" + (f".{_LAZY[name]}" if _LAZY[name] else "")
    value = getattr(importlib.import_module(home), name)
    globals()[name] = value
    return value


__all__ = [
    "resolve_branch",
    "list_branches",
    "branch_exists",
    "get_branch_info",
    "route_command",
    "discover_modules",
    "get_help",
    "CommandResult",
    "HelpResult",
    "get_system_help",
    "route_all",
    "set_registry_path",
    "get_registry_path",
    "reset_registry_path",
    "RoutingError",
    "BranchNotFoundError",
    "BranchAlreadyExistsError",
    "InvalidPathError",
    "RegistryError",
    "RegistryNotFoundError",
    "RegistryCorruptError",
    "RegistryPermissionError",
    "CommandExecutionError",
]
