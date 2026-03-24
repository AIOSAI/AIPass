# =================== AIPass ====================
# Name: models.py
# Description: OpenRouter Model Management
# Version: 1.0.0
# Created: 2025-11-16
# Modified: 2025-11-16
# =============================================

"""
OpenRouter Model Management Handler

Business logic for querying and filtering OpenRouter models:
- Fetch all available models from OpenRouter API
- Filter models by pricing (free models)
- Parse model data and capabilities
- Extract model metadata (context, pricing, capabilities)

Extracted from legacy archive files (openrouter.py, find_free_models.py).
"""

# AIPASS_ROOT import pattern
import sys
from pathlib import Path

# Standard library imports
from typing import Dict, List, Optional

# Third-party imports
import requests

# Logging
from aipass.prax import logger

# Internal imports
from aipass.api.apps.handlers.auth.keys import get_api_key

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

def get_available_models(api_key: Optional[str] = None) -> List[Dict]:
    """
    Fetch all models from OpenRouter API

    Returns full model data including pricing, context length,
    and capabilities for all available models.

    Args:
        api_key: Optional OpenRouter API key (fetches from keys handler if None)

    Returns:
        List of model dictionaries with full metadata, empty list on failure

    Example:
        >>> models = get_available_models()
        >>> logger.info(f"Found {len(models)} models")
    """
    try:
        # Get API key if not provided
        if not api_key:
            api_key = get_api_key("openrouter")

        if not api_key:
            logger.info(f"[{MODULE_NAME}] No API key available for OpenRouter")
            logger.warning("No OpenRouter API key found")
            return []

        # Fetch models from API
        models = fetch_models_from_api(api_key)

        if models:
            logger.info(f"[{MODULE_NAME}] Fetched {len(models)} models from OpenRouter")
            json_handler.log_operation("models_listed", {"count": len(models)})
            return models
        else:
            logger.info(f"[{MODULE_NAME}] No models returned from API")
            return []

    except Exception as e:
        logger.info(f"[{MODULE_NAME}] Failed to get available models: {e}")
        logger.error(f"Error fetching models: {e}")
        return []


def get_free_models(api_key: Optional[str] = None) -> List[Dict]:
    """
    Fetch only free models ($0 pricing) from OpenRouter

    Filters models where both prompt and completion costs are zero.
    Useful for finding models that can be used without charges.

    Args:
        api_key: Optional OpenRouter API key (fetches from keys handler if None)

    Returns:
        List of free model dictionaries with full metadata, empty list on failure

    Example:
        >>> free_models = get_free_models()
        >>> for model in free_models:
        ...     logger.info(f"Free: {model['id']}")
    """
    try:
        # Get all models first
        all_models = get_available_models(api_key)

        if not all_models:
            return []

        # Filter for free models
        free_models = filter_by_pricing(all_models, max_cost=0.0)

        logger.info(f"[{MODULE_NAME}] Found {len(free_models)} free models")
        return free_models

    except Exception as e:
        logger.info(f"[{MODULE_NAME}] Failed to get free models: {e}")
        logger.error(f"Error fetching free models: {e}")
        return []


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
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        # Make API request
        logger.info(f"[{MODULE_NAME}] Requesting models from OpenRouter API")
        response = requests.get(
            OPENROUTER_API_URL,
            headers=headers,
            timeout=DEFAULT_TIMEOUT
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


def filter_by_pricing(models: List[Dict], max_cost: float = 0.0) -> List[Dict]:
    """
    Filter models by maximum pricing threshold

    Filters models where both prompt and completion costs are at or
    below the specified maximum. Default of 0.0 returns only free models.

    Args:
        models: List of model dictionaries from API
        max_cost: Maximum cost threshold (0.0 for free only)

    Returns:
        Filtered list of models matching pricing criteria

    Example:
        >>> all_models = get_available_models()
        >>> free = filter_by_pricing(all_models, 0.0)
        >>> cheap = filter_by_pricing(all_models, 0.0001)
    """
    filtered = []

    try:
        for model in models:
            # Extract pricing data
            pricing = model.get("pricing", {})

            # Convert pricing to float (handles string values)
            try:
                prompt_cost = float(pricing.get("prompt", "0"))
                completion_cost = float(pricing.get("completion", "0"))
            except (ValueError, TypeError) as e:
                # Skip models with invalid pricing data
                logger.warning(f"Skipping model with invalid pricing data: {e}")
                continue

            # Check if both costs are at or below threshold
            if prompt_cost <= max_cost and completion_cost <= max_cost:
                filtered.append(model)

        logger.info(f"[{MODULE_NAME}] Filtered {len(filtered)}/{len(models)} models at max_cost={max_cost}")
        return filtered

    except Exception as e:
        logger.error(f"Error filtering models: {e}")
        return []



