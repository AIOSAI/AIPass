# =================== AIPass ====================
# Name: tracking.py
# Description: Usage Tracking Handler
# Version: 1.2.0
# Created: 2025-11-16
# Modified: 2026-10-17
# =============================================

"""Usage Tracking Handler"""

import json
import requests
import time
from datetime import datetime
from typing import Dict, Any, Optional

from aipass.prax import logger

from aipass.api.apps.handlers.module_root import module_file

from aipass.api.apps.handlers.json import json_handler

MODULE_NAME = "tracking"
DATA_FILE = "usage_tracker_data.json"  # Standard 3-file pattern
API_JSON_DIR = module_file(__file__).parent.parent.parent.parent / "api_json"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
GENERATION_ENDPOINT = f"{OPENROUTER_BASE_URL}/generation"

DEFAULT_GENERATION_CHECK_DELAY = 2  # seconds to wait before querying metrics
DEFAULT_REQUEST_TIMEOUT = 30  # seconds for HTTP request timeout
MAX_GENERATION_TRACKING = 500  # Maximum entries in generation_tracking before trimming


def track_usage(
    generation_id: str, caller: str, model: str = "unknown", api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Track API usage for generation ID by querying OpenRouter metrics"""
    try:
        if not api_key:
            # Imported here: a top-level import is circular.
            try:
                from aipass.api.apps.handlers.auth.keys import get_api_key

                api_key = get_api_key("openrouter")
            except Exception as e:
                logger.error(f"[{MODULE_NAME}] Failed to load API key: {e}")
                return {"success": False, "error": "No API key available"}

        if not api_key:
            return {"success": False, "error": "No API key available"}

        # OpenRouter needs a moment before the generation's metrics exist.
        time.sleep(DEFAULT_GENERATION_CHECK_DELAY)

        try:
            metrics = get_generation_metrics(generation_id, api_key)
        except MetricsUnavailable as e:
            return {"success": False, "error": str(e)}

        if store_usage_data(caller, model, generation_id, metrics):
            json_handler.log_operation(
                "usage_tracked", {"caller": caller, "model": model, "generation_id": generation_id}
            )
            return {"success": True, "metrics": metrics}
        else:
            return {"success": False, "error": "Failed to store usage data"}

    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Usage tracking failed: {e}")
        return {"success": False, "error": str(e)}


class MetricsUnavailable(Exception):
    """OpenRouter could not give the metrics of one generation; str(exc) says why."""


def get_generation_metrics(generation_id: str, api_key: str) -> Dict[str, Any]:
    """Query OpenRouter /generation endpoint for real usage metrics"""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        response = requests.get(  # type: ignore[attr-defined]
            GENERATION_ENDPOINT, params={"id": generation_id}, headers=headers, timeout=DEFAULT_REQUEST_TIMEOUT
        )
    except requests.exceptions.Timeout as e:
        logger.warning(f"[{MODULE_NAME}] Request timeout querying generation: {e}")
        raise MetricsUnavailable(f"Request timeout querying generation {generation_id}: {e}") from e
    except requests.exceptions.RequestException as e:
        logger.error(f"[{MODULE_NAME}] Request error querying generation: {e}")
        raise MetricsUnavailable(f"Request error querying generation {generation_id}: {e}") from e

    if response.status_code != 200:
        logger.warning(
            f"[{MODULE_NAME}] OpenRouter API returned status {response.status_code} for generation {generation_id}"
        )
        raise MetricsUnavailable(f"OpenRouter answered status {response.status_code} for generation {generation_id}")

    try:
        data = response.json()
    except ValueError as e:
        logger.error(f"[{MODULE_NAME}] Error parsing metrics: {e}")
        raise MetricsUnavailable(f"OpenRouter answered unreadable JSON for generation {generation_id}: {e}") from e

    if not data or "data" not in data:
        logger.warning(f"[{MODULE_NAME}] Invalid response structure from OpenRouter for generation {generation_id}")
        raise MetricsUnavailable(f"OpenRouter answered without a data block for generation {generation_id}")

    # `or 0`, not a .get default: OpenRouter sends explicit nulls.
    metrics = data["data"]

    try:
        return {
            "total_cost": float(metrics.get("total_cost") or 0),
            "tokens_prompt": int(metrics.get("tokens_prompt") or 0),
            "tokens_completion": int(metrics.get("tokens_completion") or 0),
            "generation_time": int(metrics.get("generation_time") or 0),
            "latency": int(metrics.get("latency") or 0),
            "provider_name": metrics.get("provider_name") or "unknown",
        }
    except (ValueError, TypeError, AttributeError) as e:
        logger.error(f"[{MODULE_NAME}] Error parsing metrics: {e}")
        raise MetricsUnavailable(f"OpenRouter's metrics for generation {generation_id} do not parse: {e}") from e


def store_usage_data(caller: str, model: str, generation_id: str, metrics: Dict[str, Any]) -> bool:
    """Store usage data with aggregation and newest-first ordering"""
    try:
        API_JSON_DIR.mkdir(parents=True, exist_ok=True)
        data_path = API_JSON_DIR / DATA_FILE

        # Read-modify-write: the json service keeps its own keys (operations_total, last_operation) in
        # this file; we own only 'data' and 'timestamp', and 'data' may not exist yet.
        today = datetime.now().date().isoformat()
        document: Dict[str, Any] = {}
        if data_path.exists():
            with open(data_path, "r", encoding="utf-8") as f:
                document = json.load(f)
        document.setdefault("module_name", "usage_tracker")
        document.setdefault("created", today)
        document["last_updated"] = today

        current_data = document.setdefault("data", {})
        current_data.setdefault(
            "current_session",
            {"start_time": datetime.now().isoformat(), "total_requests": 0, "total_cost": 0.0, "total_tokens": 0},
        )
        for section in ("usage_by_caller", "daily_totals", "monthly_totals", "generation_tracking"):
            current_data.setdefault(section, {})

        total_tokens = metrics["tokens_prompt"] + metrics["tokens_completion"]

        current_data["current_session"]["total_requests"] += 1
        current_data["current_session"]["total_cost"] += metrics["total_cost"]
        current_data["current_session"]["total_tokens"] += total_tokens

        if caller not in current_data["usage_by_caller"]:
            current_data["usage_by_caller"][caller] = {
                "requests": 0,
                "total_cost": 0.0,
                "total_tokens": 0,
                "models_used": {},
                "last_request": None,
            }

        caller_data = current_data["usage_by_caller"][caller]
        caller_data["requests"] += 1
        caller_data["total_cost"] += metrics["total_cost"]
        caller_data["total_tokens"] += total_tokens
        caller_data["last_request"] = datetime.now().isoformat()

        if model not in caller_data["models_used"]:
            caller_data["models_used"][model] = 0
        caller_data["models_used"][model] += 1

        if today not in current_data["daily_totals"]:
            current_data["daily_totals"][today] = {"requests": 0, "cost": 0.0, "tokens": 0}

        current_data["daily_totals"][today]["requests"] += 1
        current_data["daily_totals"][today]["cost"] += metrics["total_cost"]
        current_data["daily_totals"][today]["tokens"] += total_tokens

        month = today[:7]  # YYYY-MM
        if month not in current_data["monthly_totals"]:
            current_data["monthly_totals"][month] = {"requests": 0, "cost": 0.0, "tokens": 0}
        current_data["monthly_totals"][month]["requests"] += 1
        current_data["monthly_totals"][month]["cost"] += metrics["total_cost"]
        current_data["monthly_totals"][month]["tokens"] += total_tokens

        new_entry = {"timestamp": datetime.now().isoformat(), "caller": caller, "model": model, "usage_data": metrics}

        # Newest first: the trim below drops from the end.
        current_tracking = current_data["generation_tracking"]
        current_data["generation_tracking"] = {generation_id: new_entry, **current_tracking}

        if len(current_data["generation_tracking"]) > MAX_GENERATION_TRACKING:
            keys = list(current_data["generation_tracking"].keys())
            for old_key in keys[MAX_GENERATION_TRACKING:]:
                del current_data["generation_tracking"][old_key]

        document["timestamp"] = datetime.now().isoformat()

        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(document, f, indent=2, ensure_ascii=False)

        return True

    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Failed to store usage data: {e}")
        return False
