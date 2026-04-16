# =================== AIPass ====================
# Name: keys.py
# Description: API Key Management Handler
# Version: 2.0.0
# Created: 2025-11-16
# Modified: 2025-11-16
# =============================================

"""
API Key Management Handler

Handles API key retrieval and validation for multiple providers.
Keys are read from config JSON or directly from ~/.secrets/aipass/.env.

Functions:
    get_api_key() - Get validated API key
    validate_key() - Validate key format for provider
    get_key_from_config() - Retrieve key from config JSON
    get_validation_rules() - Get provider-specific validation rules
"""

# Standard library
from pathlib import Path
from typing import Optional, Dict, Any

# Logging
from aipass.prax import logger

# JSON handler
from aipass.api.apps.handlers.json import json_handler


# ==============================================
# CONSTANTS
# ==============================================

# Navigate: keys.py -> auth/ -> handlers/ -> apps/ -> api/
API_ROOT = Path(__file__).resolve().parent.parent.parent.parent
API_JSON_DIR = API_ROOT / "api_json"

# Provider validation rules (embedded - no config dependency for core validation)
VALIDATION_RULES = {
    "openrouter": {"prefix": "sk-or-v1-", "min_length": 40},
    "openai": {"prefix": "sk-", "min_length": 40},
    "anthropic": {"prefix": "sk-ant-", "min_length": 40},
    # Generic fallback
    "generic": {"min_length": 10},
}


# ==============================================
# KEY RETRIEVAL
# ==============================================


def get_api_key(provider: str = "openrouter") -> Optional[str]:
    """
    Get validated API key for provider.

    Sources (in order):
    1. Config JSON file (api_json/api_connect_config.json)
    2. Secrets file (~/.secrets/aipass/.env)

    Args:
        provider: Provider name (default: 'openrouter')

    Returns:
        str: Validated API key or None if not found/invalid

    Example:
        >>> key = get_api_key('openrouter')
        >>> if key:
        ...     print(f"Got key: {key[:20]}...")
    """
    try:
        source = ""

        # 1. Try config file
        key = get_key_from_config(provider)
        if key and validate_key(key, provider):
            source = "config"

        # 2. Try secrets file
        if not source:
            key = _read_key_from_secrets(provider)
            if key and validate_key(key, provider):
                source = "secrets"

        if source:
            json_handler.log_operation("key_retrieved", {"provider": provider, "source": source})
            return key

        # No valid key found
        return None

    except Exception as e:
        logger.error(f"Failed to get API key for provider '{provider}': {e}")
        return None


def _read_key_from_secrets(provider: str) -> Optional[str]:
    """
    Read API key directly from ~/.secrets/aipass/.env.

    Args:
        provider: Provider name (e.g., 'openrouter')

    Returns:
        str: API key value or None if not found
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
        logger.warning(f"Error reading secrets file: {e}")
        return None


def get_key_from_config(provider: str) -> Optional[str]:
    """
    Retrieve API key from config JSON file.

    Reads from: <api_root>/api_json/api_connect_config.json

    Args:
        provider: Provider name (e.g., 'openrouter')

    Returns:
        str: API key from config or None if not found

    Example:
        >>> key = get_key_from_config('openrouter')
    """
    try:
        config_path = API_JSON_DIR / "api_connect_config.json"

        if not config_path.exists():
            # Config file not found
            return None

        import json

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # Navigate config structure
        if "config" in config:
            providers = config["config"].get("providers", {})
            if provider in providers:
                key = providers[provider].get("api_key", "")
                if key:
                    return key

        # No key in config file
        return None

    except Exception as e:
        # Error reading config
        logger.error(f"Error reading config for provider '{provider}': {e}")
        return None


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

    Checks all sources for a raw key (skipping validation) and explains
    exactly why it failed — missing entirely, wrong prefix, too short, etc.

    Args:
        provider: Provider name (default: 'openrouter')

    Returns:
        str: Human-readable explanation of the key issue

    Example:
        >>> if not get_api_key('openrouter'):
        ...     print(diagnose_key('openrouter'))
    """
    # Check all sources for raw key (without validation)
    key = get_key_from_config(provider)
    source = "config"

    if not key:
        key = _read_key_from_secrets(provider)
        source = "secrets"

    if not key:
        secrets_path = Path.home() / ".secrets" / "aipass" / ".env"
        return f"API key for {provider} not found. Expected at {secrets_path}. Run drone @api setup to configure."

    # Key exists but failed validation — explain why
    key = key.strip()
    rules = get_validation_rules(provider)

    if "prefix" in rules and not key.startswith(rules["prefix"]):
        actual_prefix = key[: len(rules["prefix"])] if len(key) >= len(rules["prefix"]) else key[:6]
        return f"Key found ({source}) but invalid — expected prefix '{rules['prefix']}', got '{actual_prefix}...'"

    if "min_length" in rules and len(key) < rules["min_length"]:
        return f"Key found ({source}) but too short — {len(key)} chars, need {rules['min_length']}+"

    return f"Key found ({source}) but failed validation"
