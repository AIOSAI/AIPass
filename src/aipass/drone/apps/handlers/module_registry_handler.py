# =================== AIPass ====================
# Name: module_registry_handler.py
# Description: Handler for internal module registry operations
# Version: 1.0.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""
Handler for internal module registry operations.

Handles dynamic module loading, adapter introspection, and command
delegation for drone's internal module system.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler


# Maps module name -> import path for its drone_adapter
_MODULE_REGISTRY: dict[str, str] = {
    "cli": "aipass.cli.drone_adapter",
    "drone": "aipass.drone.drone_adapter",
    "seedgo": "aipass.seedgo.drone_adapter",
}


@dataclass
class ModuleInfo:
    """Metadata about a registered module."""

    name: str
    version: str
    description: str
    adapter_path: str


def list_modules() -> list[str]:
    """Return sorted list of registered module names."""
    return sorted(_MODULE_REGISTRY.keys())


def is_module(name: str) -> bool:
    """Check if name is a registered module."""
    return name in _MODULE_REGISTRY


def get_module_info(name: str) -> ModuleInfo | None:
    """Get module metadata by dynamically importing its adapter."""
    adapter_path = _MODULE_REGISTRY.get(name)
    if adapter_path is None:
        return None
    try:
        mod = importlib.import_module(adapter_path)
        meta = getattr(mod, "DRONE_MODULE", {})
        return ModuleInfo(
            name=meta.get("name", name),
            version=meta.get("version", "unknown"),
            description=meta.get("description", ""),
            adapter_path=adapter_path,
        )
    except ImportError:
        return None


def route_module_command(name: str, command: str, args: list[str] | None = None) -> dict:
    """Route a command to a module's drone adapter.

    Returns dict with keys: stdout, stderr, exit_code.
    """
    adapter_path = _MODULE_REGISTRY[name]
    mod = importlib.import_module(adapter_path)
    handler = getattr(mod, "handle_command")
    result = handler(command, args)
    json_handler.log_operation("route_module_command", {"module": name, "command": command})
    return result


def get_module_help(name: str, command: str | None = None) -> str:
    """Get help text from a module's drone adapter."""
    adapter_path = _MODULE_REGISTRY.get(name)
    if adapter_path is None:
        return ""
    try:
        mod = importlib.import_module(adapter_path)
        help_fn = getattr(mod, "get_help", None)
        if help_fn is None:
            return ""
        return help_fn(command)
    except (ImportError, AttributeError):
        return ""


def get_module_introspective(name: str) -> str:
    """Get introspective view from a module's drone adapter.

    Introspective = discovery mode (no args): shows what's connected.
    Falls back to help text if not implemented.
    """
    adapter_path = _MODULE_REGISTRY.get(name)
    if adapter_path is None:
        return ""
    try:
        mod = importlib.import_module(adapter_path)
        intro_fn = getattr(mod, "get_introspective", None)
        if intro_fn is not None:
            return intro_fn()
        help_fn = getattr(mod, "get_help", None)
        if help_fn is not None:
            return help_fn(None)
        return ""
    except (ImportError, AttributeError):
        return ""


def register_module(name: str, adapter_path: str) -> None:
    """Register a new module dynamically."""
    _MODULE_REGISTRY[name] = adapter_path
