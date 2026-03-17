# =================== AIPass ====================
# Name: aipass_ignore.py
# Description: AIPass Ignore Configuration
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-17
# =============================================

"""
AIPass Ignore Configuration

Loads and provides ignore configuration for the AIPass standards pack.
"""

from pathlib import Path
from typing import Dict, List

from aipass.seedgo.apps.handlers.json import json_handler

IGNORE_CONFIG_FILE = Path(__file__).resolve().parent / "ignore.json"


def load_ignore_config() -> List[Dict]:
    """Load ignore configuration from config directory."""
    json_handler.log_operation("ignore_config_loaded", {"config_file": str(IGNORE_CONFIG_FILE)})
    return []
