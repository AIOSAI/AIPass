# =================== AIPass ====================
# Name: cli.py
# Description: CLI event handler for header display events
# Version: 0.1.0
# Created: 2025-12-04
# Modified: 2025-12-04
# =============================================

"""CLI Event Handler - Handle CLI display events"""

from aipass.trigger.apps.handlers.json import json_handler


def handle_cli_header_displayed(**kwargs):
    """Handle cli_header_displayed event - logs when CLI displays headers"""
    # Handlers cannot use logger or print - event is already logged by core.py
    # This handler exists to demonstrate event registration works
    json_handler.log_operation("cli_event", {"success": True})
    pass
