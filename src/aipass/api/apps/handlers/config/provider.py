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
- Load provider configurations from JSON
- Deep merge configuration updates
- Provider defaults and validation
- Config file management (create/update)
- Configuration merging helpers

Extracted from api_connect.py archive for new handler structure.
"""

# Infrastructure
import sys
from pathlib import Path

# Standard library
import json
from datetime import datetime
from typing import Dict, Any, Optional

# Internal handlers
from aipass.api.apps.handlers.json.json_handler import load_json, save_json

# JSON handler
from aipass.api.apps.handlers.json import json_handler

# Logging
from aipass.prax import logger

# =============================================
# CONSTANTS
# =============================================

# Navigate: provider.py -> config/ -> handlers/ -> apps/ -> api/
API_ROOT = Path(__file__).resolve().parent.parent.parent.parent
API_JSON_DIR = API_ROOT / "api_json"
CONFIG_FILE = "api_config.json"

# Default provider configurations
# NOTE: No default_model - callers must specify their own model from their branch config
PROVIDER_DEFAULTS = {
    "openrouter": {
        "api_key": "",
        "base_url": "https://openrouter.ai/api/v1",
        "temperature": 0.7,
        "timeout_seconds": 30
    },
    "openai": {
        "api_key": "",
        "base_url": "https://api.openai.com/v1",
        "temperature": 0.7,
        "timeout_seconds": 30
    }
}

# Provider validation rules
VALIDATION_RULES = {
    "openrouter": {
        "prefix": "sk-or-v1-",
        "min_length": 40
    },
    "openai": {
        "prefix": "sk-",
        "min_length": 40
    }
}

# =============================================
# CONFIGURATION LOADING
# =============================================

def load_provider_config(provider: str = "openrouter") -> Optional[Dict[str, Any]]:
    """
    Load provider configuration from config JSON

    Reads the main API config file and extracts provider-specific settings.
    Returns None if provider not found or config file doesn't exist.

    Args:
        provider: Provider name (e.g., "openrouter", "openai")

    Returns:
        Provider configuration dict or None if not found

    Example:
        config = load_provider_config("openrouter")
        # Returns: {
        #     "api_key": "sk-or-v1-...",
        #     "base_url": "https://openrouter.ai/api/v1",
        #     "temperature": 0.7,
        #     "timeout_seconds": 30
        # }
        # NOTE: No default_model - callers provide their own
    """
    try:
        config_path = API_JSON_DIR / CONFIG_FILE

        if not config_path.exists():
            # Config file not found, creating default
            _create_default_config()

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # Extract provider config from main config
        if "config" in config and "providers" in config["config"]:
            provider_config = config["config"]["providers"].get(provider)

            if provider_config:
                # Loaded config for provider
                json_handler.log_operation("config_loaded", {"provider": provider})
                return provider_config
            else:
                # Provider not found in config
                return None
        else:
            # Config structure missing 'providers' section
            return None

    except json.JSONDecodeError as e:
        # Invalid JSON in config file
        return None
    except Exception as e:
        # Failed to load provider config
        return None


def get_full_config() -> Optional[Dict[str, Any]]:
    """
    Load the complete API configuration

    Returns:
        Full config dict or None if load fails
    """
    try:
        config_path = API_JSON_DIR / CONFIG_FILE

        if not config_path.exists():
            # Config file not found, creating default
            _create_default_config()

        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    except Exception as e:
        # Failed to load full config
        return None


# =============================================
# CONFIGURATION UPDATES
# =============================================

def update_provider_config(provider: str, updates: Dict[str, Any]) -> bool:
    """
    Deep merge updates into provider configuration

    Updates the provider's configuration with new values, preserving
    existing values not specified in updates. Uses deep merge to handle
    nested dictionaries properly.

    Args:
        provider: Provider name (e.g., "openrouter")
        updates: Configuration updates to apply

    Returns:
        True if update successful, False otherwise

    Example:
        success = update_provider_config("openrouter", {
            "api_key": "sk-or-v1-new-key",
            "temperature": 0.8
        })
    """
    try:
        config_path = API_JSON_DIR / CONFIG_FILE

        # Load existing config or create default
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        else:
            config = _get_default_config_structure()

        # Ensure providers section exists
        if "config" not in config:
            config["config"] = {}
        if "providers" not in config["config"]:
            config["config"]["providers"] = {}

        # Get or create provider config
        if provider not in config["config"]["providers"]:
            config["config"]["providers"][provider] = get_default_config(provider)

        # Deep merge updates into provider config
        merge_configs(config["config"]["providers"][provider], updates)

        # Update timestamp
        config["timestamp"] = datetime.now().isoformat()

        # Save updated config
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        # Updated config for provider
        logger.info(f"Provider config updated: {provider}")
        return True

    except Exception as e:
        # Failed to update provider config
        logger.error(f"Failed to update provider config: {e}")
        return False


def update_full_config(updates: Dict[str, Any]) -> bool:
    """
    Update the complete API configuration with deep merge

    Args:
        updates: Configuration updates to apply

    Returns:
        True if successful
    """
    try:
        config_path = API_JSON_DIR / CONFIG_FILE

        # Load existing or create default
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        else:
            config = _get_default_config_structure()

        # Deep merge updates
        merge_configs(config, updates)

        # Update timestamp
        config["timestamp"] = datetime.now().isoformat()

        # Save
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        # Updated full API config
        return True

    except Exception as e:
        # Failed to update full config
        return False


# =============================================
# DEFAULT CONFIGURATIONS
# =============================================

def get_default_config(provider: str) -> Dict[str, Any]:
    """
    Get default configuration for provider

    Returns the default configuration structure for a specific provider.
    If provider not in defaults, returns empty config structure.

    Args:
        provider: Provider name

    Returns:
        Default configuration dict

    Example:
        config = get_default_config("openrouter")
        # Returns default OpenRouter configuration
    """
    if provider in PROVIDER_DEFAULTS:
        # Return a copy to avoid mutation
        return PROVIDER_DEFAULTS[provider].copy()
    else:
        # No default config for provider
        return {
            "api_key": "",
            "base_url": "",
            "timeout_seconds": 30
        }


def _get_default_config_structure() -> Dict[str, Any]:
    """
    Get complete default configuration structure

    Returns:
        Default config dict with all providers
    """
    return {
        "module_name": "api",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "enabled": True,
            "auto_save": True,
            "providers": {
                "openrouter": PROVIDER_DEFAULTS["openrouter"].copy(),
                "openai": PROVIDER_DEFAULTS["openai"].copy()
            },
            "default_provider": "openrouter",
            "key_validation": VALIDATION_RULES.copy()
        }
    }


def _create_default_config() -> bool:
    """
    Create default configuration file

    Returns:
        True if successful
    """
    try:
        config_path = API_JSON_DIR / CONFIG_FILE
        config_path.parent.mkdir(parents=True, exist_ok=True)

        default_config = _get_default_config_structure()

        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)

        # Created default config
        logger.info(f"Created default config: {config_path}")
        return True

    except Exception as e:
        # Failed to create default config
        return False


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
    return VALIDATION_RULES.get(provider)


def list_available_providers() -> list[str]:
    """
    List all available providers with defaults

    Returns:
        List of provider names
    """
    return list(PROVIDER_DEFAULTS.keys())


def provider_exists(provider: str) -> bool:
    """
    Check if provider exists in configuration

    Args:
        provider: Provider name

    Returns:
        True if provider configured, False otherwise
    """
    config = load_provider_config(provider)
    return config is not None
