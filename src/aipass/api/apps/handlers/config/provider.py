# =================== AIPass ====================
# Name: provider.py
# Description: Provider Configuration Handler
# Version: 2.0.0
# Created: 2025-11-16
# Modified: 2025-11-16
# =============================================

"""
Provider Configuration Handler

Manages provider configuration for API access:
- Deep merge configuration updates
- Provider defaults and validation rules
"""

# Standard library
from typing import Dict, Any, Optional

# JSON handler
from aipass.api.apps.handlers.json import json_handler

# Logging
from aipass.prax import logger

# =============================================
# CONSTANTS
# =============================================

# Default provider configurations
# NOTE: No default_model - callers must specify their own model from their branch config
PROVIDER_DEFAULTS = {
    "openrouter": {
        "api_key": "",
        "base_url": "https://openrouter.ai/api/v1",
        "temperature": 0.7,
        "timeout_seconds": 30,
    },
    "openai": {"api_key": "", "base_url": "https://api.openai.com/v1", "temperature": 0.7, "timeout_seconds": 30},
}

# Provider validation rules
VALIDATION_RULES = {
    "openrouter": {"prefix": "sk-or-v1-", "min_length": 40},
    "openai": {"prefix": "sk-", "min_length": 40},
}

# =============================================
# CONFIGURATION MERGING
# =============================================


def merge_configs(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge two configuration dictionaries

    Recursively merges 'updates' into 'base', preserving nested structures.
    Modifies 'base' in-place and also returns it for convenience.

    For nested dicts: recursively merges
    For other types: updates overwrites base

    Args:
        base: Base configuration dict (modified in-place)
        updates: Updates to merge in

    Returns:
        The merged base dict (same object as input)

    Example:
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        updates = {"b": {"c": 99}, "e": 4}
        merge_configs(base, updates)
        # base is now: {"a": 1, "b": {"c": 99, "d": 3}, "e": 4}
    """
    for key, value in updates.items():
        if isinstance(value, dict) and key in base and isinstance(base[key], dict):
            # Recursively merge nested dicts
            merge_configs(base[key], value)
        else:
            # Overwrite with new value
            base[key] = value

    json_handler.log_operation("config_merged", {"keys_updated": len(updates)})
    return base


# =============================================
# VALIDATION HELPERS
# =============================================


def get_validation_rules(provider: str) -> Optional[Dict[str, Any]]:
    """
    Get validation rules for provider

    Args:
        provider: Provider name

    Returns:
        Validation rules dict or None if not defined
    """
    rules = VALIDATION_RULES.get(provider)
    if rules is None:
        logger.info(f"No validation rules found for provider: {provider}")
    return rules
