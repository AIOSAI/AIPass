# =================== AIPass ====================
# Name: aggregation.py
# Description: Usage Aggregation Handler
# Version: 1.0.0
# Created: 2025-11-15
# Modified: 2025-11-15
# =============================================

"""
Usage Aggregation Handler

Business logic for aggregating usage statistics:
- Calculate per-caller stats from usage data
- Daily/monthly rollups and summaries
- Cost, token, and latency aggregation
- Model usage tracking and breakdown

Functions: get_caller_usage(), get_session_summary()
"""

from pathlib import Path

# Standard library imports
from typing import Dict, Any, Optional

# Standard library for JSON operations
import json

# Logging
from aipass.prax import logger

# JSON handler
from aipass.api.apps.handlers.json import json_handler


# =============================================
# MODULE CONSTANTS
# =============================================

MODULE_NAME = "aggregation"
DATA_FILE = "usage_tracker_data.json"  # Standard 3-file pattern
# Navigate: aggregation.py -> usage/ -> handlers/ -> apps/ -> api/
API_JSON_DIR = Path(__file__).resolve().parent.parent.parent.parent / "api_json"


# =============================================
# AGGREGATION FUNCTIONS
# =============================================

def get_caller_usage(caller: str) -> Dict[str, Any]:
    """
    Calculate usage statistics for specific caller

    Args:
        caller: Module name that made API calls

    Returns:
        Dict with requests, total_cost, total_tokens, models_used, last_request
        Returns empty dict {} if no data found
    """
    try:
        # Load usage data from JSON
        data_path = API_JSON_DIR / DATA_FILE
        if not data_path.exists():
            logger.info(f"[{MODULE_NAME}] No usage data file found")
            return {}

        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not data or "data" not in data:
            logger.info(f"[{MODULE_NAME}] No usage data available")
            return {}

        # Extract caller-specific data
        usage_by_caller = data["data"].get("usage_by_caller", {})
        caller_data = usage_by_caller.get(caller, {})

        if not caller_data:
            logger.info(f"[{MODULE_NAME}] No usage data found for caller: {caller}")
            return {}

        logger.info(f"[{MODULE_NAME}] Retrieved usage stats for {caller}: {caller_data.get('requests', 0)} requests")
        json_handler.log_operation("get_caller_usage", {"caller": caller, "requests": caller_data.get("requests", 0)})
        return caller_data

    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Failed to get caller usage for {caller}: {e}")
        return {}


def get_session_summary(session_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Aggregate current session usage totals

    Args:
        session_id: Optional session identifier (unused, for future support)

    Returns:
        Dict with start_time, total_requests, total_cost, total_tokens
        Returns empty dict {} if no session data found
    """
    try:
        # Load usage data from JSON
        data_path = API_JSON_DIR / DATA_FILE
        if not data_path.exists():
            logger.info(f"[{MODULE_NAME}] No session data file found")
            return {}

        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not data or "data" not in data:
            logger.info(f"[{MODULE_NAME}] No session data available")
            return {}

        # Extract session summary
        session_data = data["data"].get("current_session", {})

        if not session_data:
            logger.info(f"[{MODULE_NAME}] No session summary found")
            return {}

        logger.info(f"[{MODULE_NAME}] Retrieved session summary: {session_data.get('total_requests', 0)} requests")
        return session_data

    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Failed to get session summary: {e}")
        return {}


