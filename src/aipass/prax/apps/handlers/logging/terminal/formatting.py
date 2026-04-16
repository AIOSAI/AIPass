# =================== AIPass ====================
# Name: formatting.py
# Description: Terminal Output Formatting
# Version: 1.0.0
# Created: 2025-11-10
# Modified: 2026-03-09
# =============================================

"""
PRAX Terminal Formatting

Terminal output formatting with branch-aware display.
"""

import sys

import logging
from typing import Optional

# Import from prax config
from aipass.prax.apps.handlers.config.load import DEFAULT_LOG_LEVEL

# Import filtering
from aipass.prax.apps.handlers.logging.terminal.filtering import should_display_terminal

from aipass.prax.apps.handlers.json import json_handler


def format_terminal_message(record: logging.LogRecord, branch: Optional[str] = None) -> str:
    """Format log record for terminal output

    Format: [BRANCH] module - LEVEL: message
    Example: [prax] test_module - INFO: Test message

    Args:
        record: Logging record to format
        branch: Optional branch name

    Returns:
        Formatted message string
    """
    # Extract module name from logger name
    # Logger names are like "captured_{module_name}"
    logger_name = record.name
    if logger_name.startswith("captured_"):
        module_name = logger_name[9:]  # Remove "captured_" prefix
    else:
        module_name = logger_name

    # Determine branch label
    branch_label = branch if branch else "SYSTEM"

    # Format level name (fixed width for alignment)
    level = record.levelname

    # Format message
    return f"[{branch_label}] {module_name} - {level}: {record.getMessage()}"


class TerminalFormatter(logging.Formatter):
    """Custom formatter for terminal output with branch information"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def format(self, record: logging.LogRecord) -> str:
        """Format the record for terminal output

        Args:
            record: Logging record to format

        Returns:
            Formatted string or empty string if filtered
        """
        # Extract module name
        logger_name = record.name
        if logger_name.startswith("captured_"):
            module_name = logger_name[9:]
        else:
            module_name = logger_name

        # Check if should display
        if not should_display_terminal(module_name):
            return ""  # Skip this message

        # Format and return
        return format_terminal_message(record)


def create_terminal_handler() -> logging.StreamHandler:
    """Create StreamHandler for terminal output

    Returns:
        Configured stream handler with custom formatter
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(DEFAULT_LOG_LEVEL)

    # Use custom formatter
    formatter = TerminalFormatter()
    handler.setFormatter(formatter)

    json_handler.log_operation("terminal_formatted", {"level": str(DEFAULT_LOG_LEVEL)})

    return handler
