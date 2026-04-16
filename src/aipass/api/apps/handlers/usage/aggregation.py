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


def get_overall_stats() -> Dict[str, Any]:
    """
    Aggregate usage statistics across all callers.

    Returns:
        Dict with total_requests, total_cost, total_tokens, callers (count),
        models_used (set of model names).
        Returns empty dict {} if no data found.
    """
    try:
        data_path = API_JSON_DIR / DATA_FILE
        if not data_path.exists():
            logger.info(f"[{MODULE_NAME}] No usage data file found")
            return {}

        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not data or "data" not in data:
            logger.info(f"[{MODULE_NAME}] No usage data available")
            return {}

        usage_by_caller = data["data"].get("usage_by_caller", {})

        if not usage_by_caller:
            logger.info(f"[{MODULE_NAME}] No caller usage data found")
            return {}

        total_requests = 0
        total_cost = 0.0
        total_tokens = 0
        models_used: set = set()

        for caller_data in usage_by_caller.values():
            total_requests += caller_data.get("requests", 0)
            total_cost += caller_data.get("total_cost", 0.0)
            total_tokens += caller_data.get("total_tokens", 0)
            for model in caller_data.get("models_used", []):
                models_used.add(model)

        result = {
            "total_requests": total_requests,
            "total_cost": total_cost,
            "total_tokens": total_tokens,
            "callers": len(usage_by_caller),
            "models_used": sorted(models_used),
        }

        logger.info(f"[{MODULE_NAME}] Overall stats: {total_requests} requests across {len(usage_by_caller)} callers")
        json_handler.log_operation("get_overall_stats", {"total_requests": total_requests})
        return result

    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Failed to get overall stats: {e}")
        return {}


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

        with open(data_path, "r", encoding="utf-8") as f:
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

        with open(data_path, "r", encoding="utf-8") as f:
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
