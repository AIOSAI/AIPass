# =================== AIPass ====================
# Name: bypass.config.py
# Description: Mock Bypass Configuration
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-17
# =============================================

"""
Mock Bypass Configuration

Bypass configuration for the mock_standard_1 handler pack.
"""

from typing import Dict, List

from aipass.seedgo.apps.handlers.json import json_handler

BYPASS_RULES: List[Dict] = []


def get_bypass_rules() -> List[Dict]:
    """Return bypass rules for mock standard."""
    json_handler.log_operation("mock_bypass_config_loaded", {"rules_count": len(BYPASS_RULES)})
    return BYPASS_RULES.copy()
