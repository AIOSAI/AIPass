# =================== AIPass ====================
# Name: aipass_bypass.py
# Description: AIPass Bypass Configuration
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-17
# =============================================

"""
AIPass Bypass Configuration

Loads and provides bypass configuration for the AIPass standards pack.
"""

from pathlib import Path
from typing import Dict, List

from aipass.seedgo.apps.handlers.json import json_handler

BYPASS_CONFIG_FILE = Path(__file__).resolve().parent / "bypass.json"


def load_bypass_config() -> List[Dict]:
    """Load bypass configuration from config directory."""
    json_handler.log_operation("bypass_config_loaded", {"config_file": str(BYPASS_CONFIG_FILE)})
    return []
