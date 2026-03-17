# =================== AIPass ====================
# Name: bypass.py
# Description: Bypass Check Entry Point
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-17
# =============================================

"""
Bypass Check Entry Point

Thin entry point for bypass checking. Delegates to bypass_handler for logic.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def check_bypass(file_path: str, standard: str) -> bool:
    """Check if a file/standard combination is bypassed."""
    json_handler.log_operation("bypass_checked", {"file": file_path, "standard": standard})
    return False
