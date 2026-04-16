# =================== AIPass ====================
# Name: module_registry_handler.py
# Description: Handler for internal module registry operations
# Version: 2.0.0
# Created: 2026-03-09
# Modified: 2026-03-29
# =============================================

"""Handler for internal module registry operations.

Handles dynamic module loading, adapter introspection, and command
delegation for drone's internal module system.

Internal modules (e.g. git) use their own adapter files inside drone.
External modules (e.g. seedgo, cli) are declared in routing_config.json
and routed through the generic_adapter capture mechanism.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.generic_adapter import capture_main


# ---------------------------------------------------------------------------
# Internal modules — live inside drone, act as their own adapter
# ---------------------------------------------------------------------------
_INTERNAL_MODULES: dict[str, str] = {
    "git": "aipass.drone.apps.modules.git_module",
}


# ---------------------------------------------------------------------------
# External modules — loaded from routing_config.json
# ---------------------------------------------------------------------------
_ROUTING_CONFIG_PATH: Path = Path(__file__).resolve().parent / "routing_config.json"


@dataclass
class _ExternalModuleConfig:
    """Parsed config entry for an external module."""

    name: str
    entry_point: str
    description: str
    version: str


def _load_external_modules() -> dict[str, _ExternalModuleConfig]:
    """Load external module declarations from routing_config.json."""
    if not _ROUTING_CONFIG_PATH.exists():
        logger.warning("_load_external_modules: config not found at %s", _ROUTING_CONFIG_PATH)
        return {}
    try:
        with open(_ROUTING_CONFIG_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        modules_data = data.get("modules", {})
        result: dict[str, _ExternalModuleConfig] = {}
        for name, cfg in modules_data.items():
            result[name] = _ExternalModuleConfig(
                name=name,
                entry_point=cfg["entry_point"],
                description=cfg.get("description", ""),
                version=cfg.get("version", "unknown"),
            )
        return result
    except Exception as exc:
        logger.warning("_load_external_modules: failed to load config: %s", exc)
        return {}


_EXTERNAL_MODULES: dict[str, _ExternalModuleConfig] = _load_external_modules()


def refresh_external_modules() -> None:
    """Reload external module declarations from routing_config.json.

    Call after modifying routing_config.json at runtime.
    """
    global _EXTERNAL_MODULES
    _EXTERNAL_MODULES = _load_external_modules()


@dataclass
class ModuleInfo:
    """Metadata about a registered module."""

    name: str
    version: str
    description: str
    adapter_path: str


def list_modules() -> list[str]:
    """Return sorted list of registered module names."""
    all_names = set(_INTERNAL_MODULES.keys()) | set(_EXTERNAL_MODULES.keys())
    return sorted(all_names)


def is_module(name: str) -> bool:
    """Check if name is a registered module."""
    return name in _INTERNAL_MODULES or name in _EXTERNAL_MODULES


def get_module_info(name: str) -> ModuleInfo | None:
    """Get module metadata.

    For internal modules: dynamically imports the adapter and reads DRONE_MODULE.
    For external modules: returns metadata from routing_config.json.
    """
    # External module — config-driven
    ext = _EXTERNAL_MODULES.get(name)
    if ext is not None:
        return ModuleInfo(
            name=ext.name,
            version=ext.version,
            description=ext.description,
            adapter_path=ext.entry_point,
        )

    # Internal module — import-driven
    adapter_path = _INTERNAL_MODULES.get(name)
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
    except ImportError as exc:
        logger.warning(
            "get_module_info: failed to import adapter '%s': %s",
            adapter_path,
            exc,
        )
        return None


def route_module_command(name: str, command: str, args: list[str] | None = None) -> dict:
    """Route a command to a module.

    For external modules: uses generic_adapter.capture_main().
    For internal modules: imports and calls handle_command() directly.

    Returns dict with keys: stdout, stderr, exit_code.
    """
    ext = _EXTERNAL_MODULES.get(name)
    if ext is not None:
        result = capture_main(ext.entry_point, ext.name, command, args)
        json_handler.log_operation("route_module_command", {"module": name, "command": command})
        return result

    adapter_path = _INTERNAL_MODULES[name]
    mod = importlib.import_module(adapter_path)
    handler = getattr(mod, "handle_command")
    result = handler(command, args)
    # Internal modules may return bool (standard) instead of dict (adapter)
    if isinstance(result, bool):
        result = {"stdout": "", "stderr": "", "exit_code": 0 if result else 1}
    json_handler.log_operation("route_module_command", {"module": name, "command": command})
    return result


def get_module_help(name: str, command: str | None = None) -> str:
    """Get help text from a module.

    For external modules: captures branch's own --help output via
    generic_adapter. For internal modules: calls get_help() directly.
    """
    ext = _EXTERNAL_MODULES.get(name)
    if ext is not None:
        if command:
            result = capture_main(ext.entry_point, ext.name, command, ["--help"])
        else:
            result = capture_main(ext.entry_point, ext.name, "--help")
        return result.get("stdout", "") or result.get("stderr", "")

    adapter_path = _INTERNAL_MODULES.get(name)
    if adapter_path is None:
        return ""
    try:
        mod = importlib.import_module(adapter_path)
        help_fn = getattr(mod, "get_help", None)
        if help_fn is None:
            return ""
        return help_fn(command)
    except (ImportError, AttributeError) as exc:
        logger.warning("get_module_help: failed for module '%s': %s", name, exc)
        return ""


def get_module_introspective(name: str) -> str:
    """Get introspective view from a module.

    For external modules: captures branch's own no-args output via
    generic_adapter.  For internal modules: calls get_introspective()
    or falls back to get_help().
    """
    ext = _EXTERNAL_MODULES.get(name)
    if ext is not None:
        result = capture_main(ext.entry_point, ext.name)
        return result.get("stdout", "") or result.get("stderr", "")

    adapter_path = _INTERNAL_MODULES.get(name)
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
    except (ImportError, AttributeError) as exc:
        logger.warning("get_module_introspective: failed for module '%s': %s", name, exc)
        return ""


def register_module(name: str, adapter_path: str) -> None:
    """Register a new internal module dynamically."""
    _INTERNAL_MODULES[name] = adapter_path
