# =================== AIPass ====================
# Name: models.py
# Description: OpenRouter Model Management
# Version: 1.0.0
# Created: 2025-11-16
# Modified: 2025-11-16
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
        List of model dictionaries, empty list on failure

    Raises:
        No exceptions raised - returns empty list on all errors
    """
    try:
        # Prepare request headers
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        # Make API request
        logger.info(f"[{MODULE_NAME}] Requesting models from OpenRouter API")
        response = requests.get(  # type: ignore[attr-defined]
            OPENROUTER_API_URL, headers=headers, timeout=DEFAULT_TIMEOUT
        )

        # Check response status
        if response.status_code != 200:
            logger.info(f"[{MODULE_NAME}] API request failed with status {response.status_code}")
            logger.error(f"OpenRouter API error: {response.status_code}")
            return []

        # Parse JSON response
        data = response.json()

        # Extract models from response
        if "data" in data and isinstance(data["data"], list):
            models = data["data"]
            logger.info(f"[{MODULE_NAME}] Successfully parsed {len(models)} models")
            json_handler.log_operation("models_fetched", {"count": len(models)})
            return models
        else:
            logger.info(f"[{MODULE_NAME}] Invalid response format - no 'data' field")
            return []

    except requests.exceptions.Timeout:
        logger.info(f"[{MODULE_NAME}] API request timeout after {DEFAULT_TIMEOUT}s")
        logger.error("Request timeout - OpenRouter API not responding")
        return []

    except requests.exceptions.RequestException as e:
        logger.info(f"[{MODULE_NAME}] Network error: {e}")
        logger.error(f"Network error: {e}")
        return []

    except ValueError as e:
        logger.info(f"[{MODULE_NAME}] JSON parse error: {e}")
        logger.error("Invalid JSON response from API")
        return []

    except Exception as e:
        logger.info(f"[{MODULE_NAME}] Unexpected error fetching models: {e}")
        logger.error(f"Error: {e}")
        return []
