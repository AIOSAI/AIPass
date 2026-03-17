# =================== AIPass ====================
# Name: mock_check.py
# Description: Mock Standard Checker
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-17
# =============================================

"""
Mock Standard Checker

Mock checker for testing the audit pipeline. Always passes.
"""

from typing import Dict

from aipass.seedgo.apps.handlers.json import json_handler


def check_module(file_path: str, bypass_rules: list | None = None) -> Dict:
    """Run mock check on a module file."""
    json_handler.log_operation("mock_check_run", {"file": file_path})
    return {
        "passed": True,
        "score": 100,
        "checks": [],
        "standard": "MOCK",
    }
