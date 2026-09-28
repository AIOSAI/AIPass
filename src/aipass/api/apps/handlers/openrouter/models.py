# =================== AIPass ====================
# Name: models.py
# Description: OpenRouter Model Management
# Version: 1.0.1
# Created: 2025-11-16
# Modified: 2026-09-28
# =============================================

"""
OpenRouter Model Management Handler

Business logic for querying OpenRouter models:
- Fetch all available models from OpenRouter API
- Parse model data and capabilities
"""

# Standard library imports
from typing import Dict, List

# Third-party imports
import requests

# Logging
from aipass.prax import logger

# JSON handler
from aipass.api.apps.handlers.json import json_handler


# =============================================
# CONSTANTS
# =============================================

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_TIMEOUT = 10
MODULE_NAME = "openrouter.models"


class ModelsUnavailable(Exception):
    """The models endpoint could not be read; the message says why.

    Raised rather than returning [], which a reachable endpoint with no models
    also answers (api, fleet green leg 3).
    """


# =============================================
# CORE FUNCTIONS
# =============================================


def fetch_models_from_api(api_key: str) -> List[Dict]:
    """
    Query OpenRouter models endpoint and parse response

    Makes HTTP request to OpenRouter API and extracts model data.
    Handles authentication, timeouts, and error responses.

    Args:
        api_key: Valid OpenRouter API key

    Returns:
        List of model dictionaries; [] only when the endpoint lists no models

    Raises:
        ModelsUnavailable: the endpoint did not answer, answered non-200, or
            answered something that is not a model list (api, fleet green leg 3).
    """
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    logger.info(f"[{MODULE_NAME}] Requesting models from OpenRouter API")
    try:
        response = requests.get(  # type: ignore[attr-defined]
            OPENROUTER_API_URL, headers=headers, timeout=DEFAULT_TIMEOUT
        )
    except requests.exceptions.Timeout as e:
        logger.error(f"[{MODULE_NAME}] Request timeout - OpenRouter API not responding")
        raise ModelsUnavailable(f"no answer within {DEFAULT_TIMEOUT}s") from e
    except requests.exceptions.RequestException as e:
        logger.error(f"[{MODULE_NAME}] Network error: {e}")
        raise ModelsUnavailable(f"network error: {e}") from e

    if response.status_code != 200:
        logger.error(f"[{MODULE_NAME}] OpenRouter API error: {response.status_code}")
        raise ModelsUnavailable(f"status {response.status_code}")

    try:
        data = response.json()
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
