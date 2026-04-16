# =================== AIPass ====================
# Name: lifecycle.py
# Description: Logging System Lifecycle Handler
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-09
# =============================================

"""
PRAX Logging Lifecycle Handler

Implementation logic for initializing, shutting down, and running
continuous logging. Extracted from modules/logger.py to follow
the 3-tier architecture (modules = orchestration, handlers = implementation).
"""

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
    """Execute the logging system initialization sequence.

    Steps:
    1. Create config file if missing
    2. Discover all Python modules
    3. Save module registry
    4. Setup system logger
    5. Install logger override
    6. Start file watcher

    Args:
        module_name: Name of the calling module (for log prefixes)

    Returns:
        Dict with initialization results:
        - modules_count: Number of discovered modules
        - system_logs_dir: Path to system logs
        - module_logs_dir: Path to module logs
    """
    # Create config file if missing
    create_config_file()

    # Discover all modules
    modules = discover_python_modules()

    # Save registry
    save_module_registry(modules)

    # Setup prax_logger's own logging
    system_logger_instance = setup_system_logger()

    # Log system startup
    system_logger_instance.info("Prax logging system initialized")
    system_logger_instance.info(f"System logs: {get_system_logs_dir()}, Module logs: {get_module_logs_dir('prax')}")
    system_logger_instance.info(f"Found {len(modules)} modules for logging setup")

    # Install logger override
    install_logger_override()
    system_logger_instance.info("Logger override system installed")

    # Start file watcher
    start_file_watcher()

    log_operation("Logging system initialized", {"modules_discovered": len(modules), "consolidated_logger": True})

    json_handler.log_operation("lifecycle_event", {"event": "initialized", "modules_count": len(modules)})

    return {
        "modules_count": len(modules),
        "system_logs_dir": str(get_system_logs_dir()),
        "module_logs_dir": str(get_module_logs_dir("prax")),
    }


def run_shutdown(module_name: str) -> None:
    """Execute the logging system shutdown sequence.

    Steps:
    1. Stop file watcher
    2. Restore original logger
    3. Log shutdown operation

    Args:
        module_name: Name of the calling module (for log prefixes)
    """
    # Stop file watcher
    stop_file_watcher()

    # Restore original logger
    restore_original_logger()

    log_operation("Logging system shutdown", {})
