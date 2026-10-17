# =================== AIPass ====================
# Name: override.py
# Description: Logger Override System
# Version: 1.1.0
# Created: 2025-11-10
# Modified: 2026-10-17
# =============================================

"""PRAX Logger Override"""

import logging
import sys
from typing import Optional

from aipass.prax.apps.handlers.config.load import get_debug_prints_enabled, resolve_log_level

from aipass.prax.apps.handlers.logging.setup import setup_individual_logger

from aipass.prax.apps.handlers.logging.introspection import get_calling_module

from aipass.prax.apps.handlers.json import json_handler

_original_getLogger = logging.getLogger
_original_basicConfig = logging.basicConfig


def enhanced_getLogger(name: Optional[str] = None) -> logging.Logger:
    """Enhanced getLogger that redirects to our individual module loggers"""
    # sys.stderr, not a prax logger: this runs while the override is being set up.
    if get_debug_prints_enabled():
        sys.stderr.write(f"[DEBUG] enhanced_getLogger called with name: {name}\n")

    original_logger = _original_getLogger(name)

    module_name = get_calling_module()
    if get_debug_prints_enabled():
        sys.stderr.write(f"[DEBUG] Detected calling module: {module_name}\n")

    if module_name != "unknown_module":
        if get_debug_prints_enabled():
            sys.stderr.write(f"[DEBUG] Setting up individual logger for: {module_name}\n")
        original_logger.handlers.clear()

        individual_logger = setup_individual_logger(module_name)

        for handler in individual_logger.handlers:
            original_logger.addHandler(handler)

        # The copied handlers carry their own per-tier levels; this gate must not be stricter.
        original_logger.setLevel(resolve_log_level())

        # No propagation: the root logger would echo to the console.
        original_logger.propagate = False

    return original_logger


def install_logger_override():
    """Install the enhanced getLogger function globally"""
    logging.getLogger = enhanced_getLogger
    # sys.stderr: the logging system is being replaced, no prax logger to use.
    sys.stderr.write("[prax] Global logger override installed\n")
    json_handler.log_operation("logger_override_applied", {"action": "install"})


def restore_original_logger():
    """Restore original getLogger function"""
    logging.getLogger = _original_getLogger
    sys.stderr.write("[prax] Original logger function restored\n")


def is_override_active() -> bool:
    """Check if logger override is currently active"""
    return logging.getLogger != _original_getLogger
