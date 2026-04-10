# =================== AIPass ====================
# Name: tracking.py
# Description: Usage Tracking Handler
# Version: 1.0.0
# Created: 2025-11-16
# Modified: 2025-11-16
# =============================================

"""
Usage Tracking Handler

Business logic for tracking API usage from OpenRouter:
- Query OpenRouter /generation endpoint for real metrics
- Retrieve cost, tokens (prompt + completion), latency data
- Store generation tracking data with newest-first ordering
- Handle HTTP requests with proper error handling

Functions: track_usage(), get_generation_metrics(), store_usage_data()
"""

from pathlib import Path

# Standard library imports
import json
import requests
import time
from datetime import datetime
from typing import Dict, Any, Optional

# Logging
from aipass.prax import logger

# JSON handler
from aipass.api.apps.handlers.json import json_handler

# =============================================
# MODULE CONSTANTS
# =============================================

MODULE_NAME = "tracking"
DATA_FILE = "usage_tracker_data.json"  # Standard 3-file pattern
# Navigate: tracking.py -> usage/ -> handlers/ -> apps/ -> api/
API_JSON_DIR = Path(__file__).resolve().parent.parent.parent.parent / "api_json"

# OpenRouter API configuration
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
GENERATION_ENDPOINT = f"{OPENROUTER_BASE_URL}/generation"

# Default configuration values
DEFAULT_GENERATION_CHECK_DELAY = 2  # seconds to wait before querying metrics
DEFAULT_REQUEST_TIMEOUT = 30  # seconds for HTTP request timeout


# =============================================
# CORE TRACKING FUNCTIONS
# =============================================

def track_usage(generation_id: str, caller: str, model: str = "unknown", api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Track API usage for generation ID by querying OpenRouter metrics

    This is the main entry point for usage tracking. It:
    1. Waits for OpenRouter to process the generation
    2. Queries the /generation endpoint for real metrics
    3. Stores the usage data with newest-first ordering

    Args:
        generation_id: OpenRouter generation ID from API response
        caller: Module name that made the API call (e.g., "flow_mbank")
        model: Model name used for the request (default: "unknown")
        api_key: OpenRouter API key (optional, loads from config if not provided)

    Returns:
        Dict with success status and metrics or error message
        Example: {"success": True, "metrics": {...}} or {"success": False, "error": "..."}
    """
    try:
        # Tracking usage for caller - generation

        # Get API key if not provided
        if not api_key:
            # Import here to avoid circular dependencies
            try:
                from aipass.api.apps.handlers.auth.keys import get_api_key
                api_key = get_api_key("openrouter")
            except Exception as e:
                logger.error(f"[{MODULE_NAME}] Failed to load API key: {e}")
                return {"success": False, "error": "No API key available"}

        if not api_key:
            # No API key available for tracking
            return {"success": False, "error": "No API key available"}

        # Wait for OpenRouter to process the generation
        time.sleep(DEFAULT_GENERATION_CHECK_DELAY)

        # Query OpenRouter for real metrics
        metrics = get_generation_metrics(generation_id, api_key)

        if not metrics:
            # Failed to retrieve generation metrics
            return {"success": False, "error": "Failed to retrieve generation metrics"}

        # Store the usage data
        if store_usage_data(caller, model, generation_id, metrics):
            # Successfully tracked usage
            json_handler.log_operation("usage_tracked", {"caller": caller, "model": model, "generation_id": generation_id})
            return {"success": True, "metrics": metrics}
        else:
            # Failed to store usage data
            return {"success": False, "error": "Failed to store usage data"}

    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Usage tracking failed: {e}")
        return {"success": False, "error": str(e)}


def get_generation_metrics(generation_id: str, api_key: str) -> Optional[Dict[str, Any]]:
    """
    Query OpenRouter /generation endpoint for real usage metrics

    Makes HTTP GET request to:
    https://openrouter.ai/api/v1/generation?id={generation_id}

    Args:
        generation_id: OpenRouter generation ID
        api_key: OpenRouter API key for authentication

    Returns:
        Dict with metrics:
        - total_cost: Total cost in USD
        - tokens_prompt: Number of prompt tokens
        - tokens_completion: Number of completion tokens
        - generation_time: Generation time in milliseconds
        - latency: Total latency in milliseconds
        - provider_name: Provider that served the request

        Returns None if request fails or data is invalid
    """
    try:
        # Set up request headers
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        # Query the generation endpoint
        response = requests.get(  # type: ignore[attr-defined]
            GENERATION_ENDPOINT,
            params={"id": generation_id},
            headers=headers,
            timeout=DEFAULT_REQUEST_TIMEOUT
        )

        # Check response status
        if response.status_code == 200:
            data = response.json()

            # Validate response structure
            if not data or "data" not in data:
                logger.warning(f"[{MODULE_NAME}] Invalid response structure from OpenRouter for generation {generation_id}")
                return None

            # Extract metrics from response
            metrics = data["data"]
            result = {
                "total_cost": float(metrics.get("total_cost", 0)),
                "tokens_prompt": int(metrics.get("tokens_prompt", 0)),
                "tokens_completion": int(metrics.get("tokens_completion", 0)),
                "generation_time": int(metrics.get("generation_time", 0)),
                "latency": int(metrics.get("latency", 0)),
                "provider_name": metrics.get("provider_name", "unknown")
            }

            # Retrieved metrics for generation_id
            return result

        else:
            logger.warning(f"[{MODULE_NAME}] OpenRouter API returned status {response.status_code} for generation {generation_id}")
            return None

    except requests.exceptions.Timeout as e:
        logger.warning(f"[{MODULE_NAME}] Request timeout querying generation: {e}")
        return None

    except requests.exceptions.RequestException as e:
        logger.error(f"[{MODULE_NAME}] Request error querying generation: {e}")
        return None

    except (ValueError, KeyError) as e:
        logger.error(f"[{MODULE_NAME}] Error parsing metrics: {e}")
        return None

    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Unexpected error getting generation metrics: {e}")
        return None


def store_usage_data(caller: str, model: str, generation_id: str, metrics: Dict[str, Any]) -> bool:
    """
    Store usage data with aggregation and newest-first ordering

    Updates:
    - current_session: Total requests, cost, tokens
    - usage_by_caller: Per-caller statistics and model tracking
    - daily_totals: Daily aggregated statistics
    - generation_tracking: Individual generation details (newest first)

    Args:
        caller: Module name that made the call
        model: Model name used
        generation_id: OpenRouter generation ID
        metrics: Usage metrics from get_generation_metrics()

    Returns:
        True if successfully stored, False on error
    """
    try:
        # Ensure API JSON directory exists
        API_JSON_DIR.mkdir(parents=True, exist_ok=True)
        data_path = API_JSON_DIR / DATA_FILE

        # Load current data or create initial structure
        if data_path.exists():
            with open(data_path, 'r', encoding='utf-8') as f:
                data_wrapper = json.load(f)
            current_data = data_wrapper.get("data", {})
        else:
            current_data = {
                "current_session": {
                    "start_time": datetime.now().isoformat(),
                    "total_requests": 0,
                    "total_cost": 0.0,
                    "total_tokens": 0
                },
                "usage_by_caller": {},
                "daily_totals": {},
                "monthly_totals": {},
                "generation_tracking": {}
            }

        # Calculate total tokens
        total_tokens = metrics["tokens_prompt"] + metrics["tokens_completion"]

        # Update session totals
        current_data["current_session"]["total_requests"] += 1
        current_data["current_session"]["total_cost"] += metrics["total_cost"]
        current_data["current_session"]["total_tokens"] += total_tokens

        # Update per-caller tracking
        if caller not in current_data["usage_by_caller"]:
            current_data["usage_by_caller"][caller] = {
                "requests": 0,
                "total_cost": 0.0,
                "total_tokens": 0,
                "models_used": {},
                "last_request": None
            }

        caller_data = current_data["usage_by_caller"][caller]
        caller_data["requests"] += 1
        caller_data["total_cost"] += metrics["total_cost"]
        caller_data["total_tokens"] += total_tokens
        caller_data["last_request"] = datetime.now().isoformat()

        # Track models used by caller
        if model not in caller_data["models_used"]:
            caller_data["models_used"][model] = 0
        caller_data["models_used"][model] += 1

        # Update daily totals
        today = datetime.now().date().isoformat()
        if today not in current_data["daily_totals"]:
            current_data["daily_totals"][today] = {
                "requests": 0,
                "cost": 0.0,
                "tokens": 0
            }

        current_data["daily_totals"][today]["requests"] += 1
        current_data["daily_totals"][today]["cost"] += metrics["total_cost"]
        current_data["daily_totals"][today]["tokens"] += total_tokens

        # Store generation details with newest-first ordering
        new_entry = {
            "timestamp": datetime.now().isoformat(),
            "caller": caller,
            "model": model,
            "usage_data": metrics
        }

        # Create new dict with new entry first, then existing entries
        current_tracking = current_data["generation_tracking"]
        current_data["generation_tracking"] = {generation_id: new_entry, **current_tracking}

        # Save updated data with proper wrapper structure
        data_wrapper = {
            "module_name": "api_usage",
            "timestamp": datetime.now().isoformat(),
            "data": current_data
        }

        with open(data_path, 'w', encoding='utf-8') as f:
            json.dump(data_wrapper, f, indent=2, ensure_ascii=False)

        # Stored usage data for caller
        return True

    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Failed to store usage data: {e}")
        return False


