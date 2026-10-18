# =================== AIPass ====================
# Name: provider.py
# Description: Provider Configuration Handler
# Version: 2.0.0
# Created: 2025-11-16
# Modified: 2026-10-17
# =============================================

"""Provider Configuration Handler"""

from typing import Dict, Any, Optional

from aipass.api.apps.handlers.json import json_handler

from aipass.prax import logger

# No default_model: callers name their own model from their branch config.
PROVIDER_DEFAULTS = {
    "openrouter": {
        "api_key": "",
        "base_url": "https://openrouter.ai/api/v1",
        "temperature": 0.7,
        "timeout_seconds": 30,
    },
    "openai": {"api_key": "", "base_url": "https://api.openai.com/v1", "temperature": 0.7, "timeout_seconds": 30},
}

VALIDATION_RULES = {
    "openrouter": {"prefix": "sk-or-v1-", "min_length": 40},
    "openai": {"prefix": "sk-", "min_length": 40},
}


def merge_configs(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two configuration dictionaries"""
    for key, value in updates.items():
        if isinstance(value, dict) and key in base and isinstance(base[key], dict):
            merge_configs(base[key], value)
        else:
            base[key] = value

    json_handler.log_operation("config_merged", {"keys_updated": len(updates)})
    return base


def get_validation_rules(provider: str) -> Optional[Dict[str, Any]]:
    """Get validation rules for provider"""
    rules = VALIDATION_RULES.get(provider)
    if rules is None:
        logger.info(f"No validation rules found for provider: {provider}")
    return rules
