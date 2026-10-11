# =================== AIPass ====================
# Name: keys.py
# Description: API Key Management Handler
# Version: 2.1.0
# Created: 2025-11-16
# Modified: 2026-10-03
# =============================================

"""
API Key Management Handler

Handles API key retrieval and validation for multiple providers.
Keys are read from ~/.secrets/aipass/.env (single source of truth).

Functions:
    get_api_key() - Get validated API key
    validate_key() - Validate key format for provider
    get_validation_rules() - Get provider-specific validation rules
"""

# Standard library
from pathlib import Path
from typing import Optional, Dict, Any

# JSON handler
from aipass.api.apps.handlers.json import json_handler


# ==============================================
# CONSTANTS
# ==============================================

# Provider validation rules (embedded - no config dependency for core validation)
VALIDATION_RULES = {
    "openrouter": {"prefix": "sk-or-v1-", "min_length": 40},
    "openai": {"prefix": "sk-", "min_length": 40},
    "anthropic": {"prefix": "sk-ant-", "min_length": 40},
    # Generic fallback
    "generic": {"min_length": 10},
}


class KeyUnavailable(Exception):
    """The secrets file exists but could not be read.

    Named only by the error's strerror or its type, and raised from None, so
    no byte of the file travels in a message or a traceback (api, fleet green
    leg 11). None stays the answer for a file or a key that is not there.
    """


# ==============================================
# KEY RETRIEVAL
# ==============================================


def get_api_key(provider: str = "openrouter") -> Optional[str]:
    """
    Get validated API key for provider from secrets file.

    Source: ~/.secrets/aipass/.env (single source of truth)

    Args:
        provider: Provider name (default: 'openrouter')

    Returns:
        str: Validated API key or None if not found/invalid

    Raises:
        KeyUnavailable: the secrets file exists but could not be read; None
        used to answer for that too, which read the same as "no key set"
        (api, fleet green leg 11).

    Example:
        >>> key = get_api_key('openrouter')
        >>> if key:
        ...     print(f"Got key: {key[:20]}...")
    """
    key = _read_key_from_secrets(provider)
    if key and validate_key(key, provider):
        json_handler.log_operation("key_retrieved", {"provider": provider, "source": "secrets"})
        return key

    return None


def _read_key_from_secrets(provider: str) -> Optional[str]:
    """
    Read API key directly from ~/.secrets/aipass/.env.

    Args:
        provider: Provider name (e.g., 'openrouter')

    Returns:
        str: API key value or None if not found

    Raises:
        KeyUnavailable: the file exists but could not be read
        (api, fleet green leg 11).
    """
    secrets_path = Path.home() / ".secrets" / "aipass" / ".env"
    if not secrets_path.exists():
        return None

    try:
        env_var = f"{provider.upper()}_API_KEY"
        with open(secrets_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    if key.strip() == env_var:
                        return value.strip()
        return None
    except Exception as e:
        reason = getattr(e, "strerror", None) or type(e).__name__
        raise KeyUnavailable(f"The secrets file could not be read ({reason})") from None


# ==============================================
# KEY VALIDATION
# ==============================================


def validate_key(key: str, provider: str = "openrouter") -> bool:
    """
    Validate API key format for provider.

    Checks:
    - Key is non-empty string
    - Matches provider prefix (if required)
    - Meets minimum length requirement

    Args:
        key: API key to validate
        provider: Provider name for validation rules

    Returns:
        bool: True if key passes validation

    Example:
        >>> key = "sk-or-v1-abc123..."
        >>> if validate_key(key, 'openrouter'):
        ...     print("Valid key")
    """
    # Basic validation
    if not key or not isinstance(key, str):
        # Invalid key type
        return False

    # Strip whitespace
    key = key.strip()

    # Get validation rules
    rules = get_validation_rules(provider)

    # Check prefix if specified
    if "prefix" in rules:
        if not key.startswith(rules["prefix"]):
            # Key missing required prefix
            return False

    # Check minimum length
    if "min_length" in rules:
        if len(key) < rules["min_length"]:
            # Key too short
            return False

    # Key passed validation
    return True


def get_validation_rules(provider: str) -> Dict[str, Any]:
    """
    Get validation rules for provider.

    Returns provider-specific rules or generic fallback.

    Args:
        provider: Provider name

    Returns:
        dict: Validation rules (prefix, min_length)

    Example:
        >>> rules = get_validation_rules('openrouter')
        >>> print(rules['prefix'])
        sk-or-
    """
    return VALIDATION_RULES.get(provider, VALIDATION_RULES["generic"])


# ==============================================
# KEY FORMAT CHECKING
# ==============================================


def diagnose_key(provider: str = "openrouter") -> str:
    """
    Diagnose why get_api_key() returned None.

    Checks secrets file for a raw key (skipping validation) and explains
    exactly why it failed — missing entirely, wrong prefix, too short, etc.

    Args:
        provider: Provider name (default: 'openrouter')

    Returns:
        str: Human-readable explanation of the key issue

    Raises:
        KeyUnavailable: the secrets file could not be read (api, fleet green leg 11).

    Example:
        >>> if not get_api_key('openrouter'):
        ...     print(diagnose_key('openrouter'))
    """
    key = _read_key_from_secrets(provider)

    if not key:
        secrets_path = Path.home() / ".secrets" / "aipass" / ".env"
        return f"API key for {provider} not found. Expected at {secrets_path}. Run drone @api init to configure."

    key = key.strip()
    rules = get_validation_rules(provider)

    if "prefix" in rules and not key.startswith(rules["prefix"]):
        actual_prefix = key[: len(rules["prefix"])] if len(key) >= len(rules["prefix"]) else key[:6]
        return f"Key found (secrets) but invalid — expected prefix '{rules['prefix']}', got '{actual_prefix}...'"

    if "min_length" in rules and len(key) < rules["min_length"]:
        return f"Key found (secrets) but too short — {len(key)} chars, need {rules['min_length']}+"

    return "Key found (secrets) but failed validation"
