# =================== AIPass ====================
# Name: models.py
# Description: OpenRouter Model Management
# Version: 1.1.0
# Created: 2025-11-16
# Modified: 2026-10-28
# =============================================

"""OpenRouter Model Management Handler"""

import json
from http.client import HTTPException
from typing import Dict, List
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from aipass.prax import logger

from aipass.api.apps.handlers.json import json_handler


OPENROUTER_API_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_TIMEOUT = 10
MODULE_NAME = "openrouter.models"


class ModelsUnavailable(Exception):
    """The models endpoint could not be read; the message says why.

    Raised rather than returning [], which a reachable endpoint with no models also answers.
    """


def fetch_models_from_api(api_key: str) -> List[Dict]:
    """Query OpenRouter models endpoint and parse response"""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    logger.info(f"[{MODULE_NAME}] Requesting models from OpenRouter API")
    try:
        with urlopen(Request(OPENROUTER_API_URL, headers=headers), timeout=DEFAULT_TIMEOUT) as response:
            body = response.read()
    except HTTPError as e:
        logger.error(f"[{MODULE_NAME}] OpenRouter API error: {e.code}")
        raise ModelsUnavailable(f"status {e.code}") from e
    except (OSError, HTTPException) as e:
        # A connect timeout arrives wrapped in URLError; a read timeout arrives bare.
        reason = getattr(e, "reason", e)
        if isinstance(reason, TimeoutError):
            logger.error(f"[{MODULE_NAME}] Request timeout - OpenRouter API not responding")
            raise ModelsUnavailable(f"no answer within {DEFAULT_TIMEOUT}s") from e
        logger.error(f"[{MODULE_NAME}] Network error: {reason}")
        raise ModelsUnavailable(f"network error: {reason}") from e

    try:
        data = json.loads(body)
    except ValueError as e:
        logger.error(f"[{MODULE_NAME}] Invalid JSON response from API")
        raise ModelsUnavailable("the answer is not JSON") from e

    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        logger.error(f"[{MODULE_NAME}] Invalid response format - no 'data' list")
        raise ModelsUnavailable("the answer holds no 'data' list")

    models = data["data"]
    logger.info(f"[{MODULE_NAME}] Successfully parsed {len(models)} models")
    json_handler.log_operation("models_fetched", {"count": len(models)})
    return models
