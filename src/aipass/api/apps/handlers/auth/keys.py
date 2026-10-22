# =================== AIPass ====================
# Name: keys.py
# Description: API Key Management Handler
# Version: 2.2.0
# Created: 2025-11-16
# Modified: 2026-10-22
# =============================================

"""API Key Management Handler"""

from typing import Optional, Dict, Any

from aipass.api.apps.handlers.auth import secrets
from aipass.api.apps.handlers.json import json_handler


VALIDATION_RULES = {
    "openrouter": {"prefix": "sk-or-v1-", "min_length": 40},
    "openai": {"prefix": "sk-", "min_length": 40},
    "anthropic": {"prefix": "sk-ant-", "min_length": 40},
    "generic": {"min_length": 10},
}


class KeyUnavailable(Exception):
    """The keyring could not give the key: named by backend class and reason, raised from None."""


def get_api_key(provider: str = "openrouter") -> Optional[str]:
    """Get validated API key for provider from its keyring entry.

    Raises KeyUnavailable when the keyring cannot be read; None means no key set.
    """
    key = _read_key_from_secrets(provider)
    if key and validate_key(key, provider):
        json_handler.log_operation("key_retrieved", {"provider": provider, "source": "secrets"})
        return key

    return None


def _read_key_from_secrets(provider: str) -> Optional[str]:
    """Read the API key from the keyring entry <provider>/api_key."""
    try:
        key = secrets.get_secret(provider, "api_key")
    except secrets.SecretsUnavailable as e:
        raise KeyUnavailable(str(e)) from None
    return None if key is None else str(key)


def validate_key(key: str, provider: str = "openrouter") -> bool:
    """Validate API key format for provider."""
    if not key or not isinstance(key, str):
        return False

    key = key.strip()

    rules = get_validation_rules(provider)

    if "prefix" in rules:
        if not key.startswith(rules["prefix"]):
            return False

    if "min_length" in rules:
        if len(key) < rules["min_length"]:
            return False

    return True


def get_validation_rules(provider: str) -> Dict[str, Any]:
    """Get validation rules for provider."""
    return VALIDATION_RULES.get(provider, VALIDATION_RULES["generic"])


def diagnose_key(provider: str = "openrouter") -> str:
    """Diagnose why get_api_key() returned None."""
    key = _read_key_from_secrets(provider)

    if not key:
        return (
            f"API key for {provider} not found in the keyring entry {provider}/api_key. Run drone @api init, "
            f"fill in {provider.upper()}_API_KEY, then drone @api secrets migrate."
        )

    key = key.strip()
    rules = get_validation_rules(provider)

    if "prefix" in rules and not key.startswith(rules["prefix"]):
        actual_prefix = key[: len(rules["prefix"])] if len(key) >= len(rules["prefix"]) else key[:6]
        return f"Key found (secrets) but invalid — expected prefix '{rules['prefix']}', got '{actual_prefix}...'"

    if "min_length" in rules and len(key) < rules["min_length"]:
        return f"Key found (secrets) but too short — {len(key)} chars, need {rules['min_length']}+"

    return "Key found (secrets) but failed validation"
