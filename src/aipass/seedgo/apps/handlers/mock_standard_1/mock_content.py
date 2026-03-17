# =================== AIPass ====================
# Name: mock_content.py
# Description: Mock Standard Content
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-17
# =============================================

"""
Mock Standard Content

Provides mock standards content for testing the standards_query module.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_mock_standards() -> str:
    """Return mock standards content."""
    json_handler.log_operation("mock_content_queried", {"standard": "mock"})
    return "Mock standard content for testing."
