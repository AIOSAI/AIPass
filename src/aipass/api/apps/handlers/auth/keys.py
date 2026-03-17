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
Uses fallback chain: config → env → .env files.

Functions:
    get_api_key() - Get validated API key with fallback chain
    validate_key() - Validate key format for provider
    get_key_from_config() - Retrieve key from config JSON
    get_key_from_env() - Retrieve key from environment variable
    get_validation_rules() - Get provider-specific validation rules
"""

# Infrastructure
from pathlib import Path
import sys

# Standard library
import os
from typing import Optional, Dict, Any

# Internal handlers
from aipass.api.apps.handlers.auth.env import read_env_file

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
    "openrouter": {
        "prefix": "sk-or-",
        "min_length": 20
    },
    "openai": {
        "prefix": "sk-",
        "min_length": 20
    },
    "anthropic": {
        "prefix": "sk-ant-",
        "min_length": 20
    },
    # Generic fallback
    "generic": {
        "min_length": 10
    }
}


# ==============================================
# KEY RETRIEVAL
# ==============================================

def get_api_key(provider: str = "openrouter") -> Optional[str]:
    """
    Get validated API key for provider with fallback chain.

    Fallback order:
    1. Config JSON file (api_json/api_connect_config.json)
    2. Environment variable
    3. .env file (multi-path search)

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
            # Using key from config
            source = "config"

        # 2. Try environment variable
        if not source:
            key = get_key_from_env(provider)
            if key and validate_key(key, provider):
                # Using key from environment
                source = "env"

        # 3. Try .env file
        if not source:
            env_var = f"{provider.upper()}_API_KEY"
            key = read_env_file(env_var)
            if key and validate_key(key, provider):
                # Using key from .env file
                source = "dotenv"

        if source:
            json_handler.log_operation("key_retrieved", {"provider": provider, "source": source})
            return key

        # No valid key found
        return None

    except Exception as e:
        # Failed to get key
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
        with open(config_path, 'r', encoding='utf-8') as f:
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
        return None


def get_key_from_env(provider: str) -> Optional[str]:
    """
    Retrieve API key from environment variable.

    Checks os.environ for {PROVIDER}_API_KEY.

    Args:
        provider: Provider name (e.g., 'openrouter')

    Returns:
        str: API key from environment or None if not found

    Example:
        >>> key = get_key_from_env('openrouter')
        >>> # Checks OPENROUTER_API_KEY env variable
    """
    env_var = f"{provider.upper()}_API_KEY"
    key = os.getenv(env_var)

    if key:
        # Found key in environment variable
        return key

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

def check_key_format(key: str) -> Dict[str, Any]:
    """
    Analyze key format and return details.

    Useful for debugging key issues. Returns information about
    the key without validating against a specific provider.

    Args:
        key: API key to analyze

    Returns:
        dict: Key format details (length, prefix, etc.)

    Example:
        >>> info = check_key_format('sk-or-v1-abc123')
        >>> print(info['detected_provider'])
        openrouter
    """
    if not key or not isinstance(key, str):
        return {
            "valid": False,
            "error": "Key is not a string"
        }

    key = key.strip()

    # Detect provider from prefix
    detected_provider = None
    for provider, rules in VALIDATION_RULES.items():
        if provider == "generic":
            continue
        if "prefix" in rules and key.startswith(rules["prefix"]):
            detected_provider = provider
            break

    return {
        "valid": True,
        "length": len(key),
        "prefix": key[:10] if len(key) >= 10 else key,
        "detected_provider": detected_provider,
        "meets_generic_length": len(key) >= VALIDATION_RULES["generic"]["min_length"]
    }


def validate_multiple_keys(keys: Dict[str, str]) -> Dict[str, bool]:
    """
    Validate multiple provider keys at once.

    Useful for validating entire config at once.

    Args:
        keys: Dictionary of {provider: key}

    Returns:
        dict: Dictionary of {provider: is_valid}

    Example:
        >>> keys = {'openrouter': 'sk-or-...', 'openai': 'sk-...'}
        >>> results = validate_multiple_keys(keys)
        >>> print(results)
        {'openrouter': True, 'openai': True}
    """
    results = {}

    for provider, key in keys.items():
        results[provider] = validate_key(key, provider)

    return results
