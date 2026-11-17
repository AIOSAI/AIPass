"""AIPass Drone's package door: every name another branch takes from drone (docs/routing_and_resolution.md)."""

import importlib
from typing import Any

__version__ = "1.3.0"

_APPS = "aipass.drone.apps"
_REGISTRY = f"{_APPS}.handlers.registry_handler"
_EXCEPTIONS = f"{_APPS}.handlers.exceptions"
_DISCOVERY = f"{_APPS}.modules.discovery"
_RESOLVER = f"{_APPS}.modules.resolver"
_ROUTER = f"{_APPS}.modules.router"
_DELETION_LOG = f"{_APPS}.handlers.deletion_log"

# Each name's real home: the door loads that one module on access, nothing more.
_HOMES = {
    "resolve_branch": _RESOLVER,
    "list_branches": _RESOLVER,
    "branch_exists": _RESOLVER,
    "get_branch_info": _RESOLVER,
    "normalize_branch_arg": _RESOLVER,
    "route_command": _ROUTER,
    "route_all": _ROUTER,
    "discover_modules": _DISCOVERY,
    "get_help": _DISCOVERY,
    "get_system_help": _DISCOVERY,
    "HelpResult": f"{_APPS}.handlers.discovery_handler",
    "CommandResult": f"{_APPS}.handlers.executor",
    "get_registry_path": _REGISTRY,
    "set_registry_path": _REGISTRY,
    "reset_registry_path": _REGISTRY,
    "resolve_aipass_home": _REGISTRY,
    "create_identified_connection": f"{_APPS}.handlers.broker.client",
    "BrokerDaemon": f"{_APPS}.handlers.broker.daemon",
    "record_foreign_deletion": _DELETION_LOG,
    "record_gate_refusal": _DELETION_LOG,
    "RoutingError": _EXCEPTIONS,
    "BranchNotFoundError": _EXCEPTIONS,
    "BranchAlreadyExistsError": _EXCEPTIONS,
    "InvalidPathError": _EXCEPTIONS,
    "RegistryError": _EXCEPTIONS,
    "RegistryNotFoundError": _EXCEPTIONS,
    "RegistryCorruptError": _EXCEPTIONS,
    "RegistryPermissionError": _EXCEPTIONS,
    "CommandExecutionError": _EXCEPTIONS,
}

__all__ = list(_HOMES)


def __getattr__(name: str) -> Any:
    """Hand out a door name from its home on each access; nothing under apps loads at package import."""
    if name not in _HOMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    # Never cached on the package: a patch on the home attribute must reach every caller reading through here.
    return getattr(importlib.import_module(_HOMES[name]), name)


def __dir__() -> list:
    """Public names, whether or not they have been resolved yet."""
    return sorted(set(globals()) | set(__all__))
