# =================== AIPass ====================
# Name: lifecycle.py
# Description: Logging System Lifecycle Handler
# Version: 1.1.0
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""PRAX Logging Lifecycle Handler"""

from typing import Dict, Any

from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.logging.setup import (
    setup_system_logger,
)
from aipass.prax.apps.handlers.logging.override import (
    install_logger_override,
    restore_original_logger,
)
from aipass.prax.apps.handlers.logging.operations import (
    log_operation,
    create_config_file,
)
from aipass.prax.apps.handlers.discovery.scanner import discover_python_modules
from aipass.prax.apps.handlers.discovery.watcher import (
    start_file_watcher,
    stop_file_watcher,
)
from aipass.prax.apps.handlers.registry.save import save_module_registry
from aipass.prax.apps.handlers.config.load import (
    get_system_logs_dir,
    get_module_logs_dir,
)


def run_initialize(module_name: str) -> Dict[str, Any]:
    """Execute the logging system initialization sequence; returns modules_count and the two log dirs."""
    create_config_file()

    modules = discover_python_modules()

    save_module_registry(modules)

    system_logger_instance = setup_system_logger()

    system_logger_instance.info("Prax logging system initialized")
    system_logger_instance.info(f"System logs: {get_system_logs_dir()}, Module logs: {get_module_logs_dir('prax')}")
    system_logger_instance.info(f"Found {len(modules)} modules for logging setup")

    install_logger_override()
    system_logger_instance.info("Logger override system installed")

    start_file_watcher()

    log_operation(
        "Logging system initialized",
        {"initiated_by": module_name, "modules_discovered": len(modules), "consolidated_logger": True},
    )

    json_handler.log_operation("lifecycle_event", {"event": "initialized", "modules_count": len(modules)})

    return {
        "modules_count": len(modules),
        "system_logs_dir": str(get_system_logs_dir()),
        "module_logs_dir": str(get_module_logs_dir("prax")),
    }


def run_shutdown(module_name: str) -> None:
    """Execute the logging system shutdown sequence."""
    stop_file_watcher()

    restore_original_logger()

    log_operation("Logging system shutdown", {"initiated_by": module_name})
