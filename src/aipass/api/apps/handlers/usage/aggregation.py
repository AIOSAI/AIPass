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

Extracted from legacy archive (api_usage.py).
Functions: get_caller_usage(), get_session_summary(), get_daily_usage()
"""

import sys
from pathlib import Path

# Standard library imports
from datetime import datetime
from typing import Dict, Any, List, Optional

# Standard library for JSON operations
import json

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
            # logger.info(f"[{MODULE_NAME}] No usage data file found")
            return {}

        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not data or "data" not in data:
            # logger.info(f"[{MODULE_NAME}] No usage data available")
            return {}

        # Extract caller-specific data
        usage_by_caller = data["data"].get("usage_by_caller", {})
        caller_data = usage_by_caller.get(caller, {})

        if not caller_data:
            # logger.info(f"[{MODULE_NAME}] No usage data found for caller: {caller}")
            return {}

        # logger.info(f"[{MODULE_NAME}] Retrieved usage stats for {caller}: {caller_data.get('requests', 0)} requests")
        return caller_data

    except Exception as e:
        # logger.error(f"[{MODULE_NAME}] Failed to get caller usage for {caller}: {e}")
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
            # logger.info(f"[{MODULE_NAME}] No session data file found")
            return {}

        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not data or "data" not in data:
            # logger.info(f"[{MODULE_NAME}] No session data available")
            return {}

        # Extract session summary
        session_data = data["data"].get("current_session", {})

        if not session_data:
            # logger.info(f"[{MODULE_NAME}] No session summary found")
            return {}

        # logger.info(f"[{MODULE_NAME}] Retrieved session summary: {session_data.get('total_requests', 0)} requests")
        return session_data

    except Exception as e:
        # logger.error(f"[{MODULE_NAME}] Failed to get session summary: {e}")
        return {}


def get_daily_usage(date: Optional[str] = None) -> Dict[str, Any]:
    """
    Calculate daily usage rollup

    Args:
        date: Date string YYYY-MM-DD format (None = today)

    Returns:
        Dict with requests, cost, tokens for the date
        Returns empty dict {} if no data found
    """
    try:
        # Default to today if no date provided
        if not date:
            date = datetime.now().date().isoformat()

        # Load usage data from JSON
        data_path = API_JSON_DIR / DATA_FILE
        if not data_path.exists():
            # logger.info(f"[{MODULE_NAME}] No daily usage data file found")
            return {}

        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not data or "data" not in data:
            # logger.info(f"[{MODULE_NAME}] No daily usage data available")
            return {}

        # Extract daily totals
        daily_totals = data["data"].get("daily_totals", {})
        daily_data = daily_totals.get(date, {})

        if not daily_data:
            # logger.info(f"[{MODULE_NAME}] No usage data found for date: {date}")
            return {}

        # logger.info(f"[{MODULE_NAME}] Retrieved daily usage for {date}: {daily_data.get('requests', 0)} requests")
        return daily_data

    except Exception as e:
        # logger.error(f"[{MODULE_NAME}] Failed to get daily usage for {date}: {e}")
        return {}


def calculate_totals(usage_data: List[Dict]) -> Dict[str, float]:
    """
    Aggregate cost, tokens, latency from usage records

    Args:
        usage_data: List of dicts with total_cost, tokens_prompt, tokens_completion, latency

    Returns:
        Dict with total_cost, total_tokens, total_requests, avg_latency, total_latency
    """
    try:
        if not usage_data:
            # logger.info(f"[{MODULE_NAME}] No usage data provided for totals calculation")
            return {
                "total_cost": 0.0,
                "total_tokens": 0,
                "total_requests": 0,
                "avg_latency": 0.0,
                "total_latency": 0
            }

        total_cost = 0.0
        total_tokens = 0
        total_latency = 0
        latency_count = 0

        for record in usage_data:
            # Aggregate cost
            total_cost += float(record.get("total_cost", 0))

            # Aggregate tokens (prompt + completion)
            tokens_prompt = int(record.get("tokens_prompt", 0))
            tokens_completion = int(record.get("tokens_completion", 0))
            total_tokens += tokens_prompt + tokens_completion

            # Aggregate latency (optional field)
            if "latency" in record:
                total_latency += int(record.get("latency", 0))
                latency_count += 1

        # Calculate average latency
        avg_latency = total_latency / latency_count if latency_count > 0 else 0.0

        result = {
            "total_cost": total_cost,
            "total_tokens": total_tokens,
            "total_requests": len(usage_data),
            "avg_latency": avg_latency,
            "total_latency": total_latency
        }

        # logger.info(f"[{MODULE_NAME}] Calculated totals: {result['total_requests']} requests, ${result['total_cost']:.6f}")
        json_handler.log_operation("usage_aggregated", {"total_requests": result["total_requests"], "total_cost": result["total_cost"]})
        return result

    except Exception as e:
        # logger.error(f"[{MODULE_NAME}] Failed to calculate totals: {e}")
        return {
            "total_cost": 0.0,
            "total_tokens": 0,
            "total_requests": 0,
            "avg_latency": 0.0,
            "total_latency": 0
        }


def get_model_breakdown(caller: Optional[str] = None) -> Dict[str, Dict[str, int]]:
    """
    Calculate model usage breakdown by caller or globally

    Args:
        caller: Optional caller name to filter by (None = all callers)

    Returns:
        Dict of {model_name: {"requests": count}}
        Returns empty dict {} if no data found
    """
    try:
        data_path = API_JSON_DIR / DATA_FILE
        if not data_path.exists():
            # logger.info(f"[{MODULE_NAME}] No model breakdown data file found")
            return {}

        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not data or "data" not in data:
            # logger.info(f"[{MODULE_NAME}] No model breakdown data available")
            return {}

        model_stats = {}
        usage_by_caller = data["data"].get("usage_by_caller", {})

        if caller:
            # Single caller breakdown
            caller_data = usage_by_caller.get(caller, {})
            models_used = caller_data.get("models_used", {})
            for model, count in models_used.items():
                model_stats[model] = {"requests": count}
        else:
            # Global breakdown across all callers
            for caller_name, caller_data in usage_by_caller.items():
                models_used = caller_data.get("models_used", {})
                for model, count in models_used.items():
                    if model not in model_stats:
                        model_stats[model] = {"requests": 0}
                    model_stats[model]["requests"] += count

        # logger.info(f"[{MODULE_NAME}] Retrieved model breakdown: {len(model_stats)} models")
        return model_stats

    except Exception as e:
        # logger.error(f"[{MODULE_NAME}] Failed to get model breakdown: {e}")
        return {}
