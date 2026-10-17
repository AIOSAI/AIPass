# =================== AIPass ====================
# Name: formatting.py
# Description: Terminal Output Formatting
# Version: 1.0.0
# Created: 2025-11-10
# Modified: 2026-10-17
# =============================================

"""PRAX Terminal Formatting"""

import sys

import logging
from typing import Optional

from aipass.prax.apps.handlers.config.load import DEFAULT_LOG_LEVEL

from aipass.prax.apps.handlers.logging.terminal.filtering import should_display_terminal

from aipass.prax.apps.handlers.json import json_handler


def format_terminal_message(record: logging.LogRecord, branch: Optional[str] = None) -> str:
    """Format log record for terminal output: [BRANCH] module - LEVEL: message"""
    logger_name = record.name
    if logger_name.startswith("captured_"):
        module_name = logger_name[9:]  # Remove "captured_" prefix
    else:
        module_name = logger_name

    branch_label = branch if branch else "SYSTEM"

    level = record.levelname

    return f"[{branch_label}] {module_name} - {level}: {record.getMessage()}"


class TerminalFormatter(logging.Formatter):
    """Custom formatter for terminal output with branch information"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def format(self, record: logging.LogRecord) -> str:
        """Format the record for terminal output, or "" when filtered"""
        logger_name = record.name
        if logger_name.startswith("captured_"):
            module_name = logger_name[9:]
        else:
            module_name = logger_name

        if not should_display_terminal(module_name):
            return ""  # Skip this message

        return format_terminal_message(record)


def create_terminal_handler() -> logging.StreamHandler:
    """Create StreamHandler for terminal output"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(DEFAULT_LOG_LEVEL)

    formatter = TerminalFormatter()
    handler.setFormatter(formatter)

    json_handler.log_operation("terminal_formatted", {"level": str(DEFAULT_LOG_LEVEL)})

    return handler
