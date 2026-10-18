# =================== AIPass ====================
# Name: keys.py
# Description: API Key Management Handler
# Version: 2.1.0
# Created: 2025-11-16
# Modified: 2026-10-17
# =============================================

"""API Key Management Handler"""

from pathlib import Path
from typing import Optional, Dict, Any

from aipass.api.apps.handlers.json import json_handler


VALIDATION_RULES = {
    "openrouter": {"prefix": "sk-or-v1-", "min_length": 40},
    "openai": {"prefix": "sk-", "min_length": 40},
    "anthropic": {"prefix": "sk-ant-", "min_length": 40},
    "generic": {"min_length": 10},
}


class KeyUnavailable(Exception):
    """The secrets file exists but could not be read.

    Raised from None and named only by strerror or type, so no byte of the file reaches a message or traceback.
    """


def get_api_key(provider: str = "openrouter") -> Optional[str]:
    """Get validated API key for provider from secrets file.

    Raises KeyUnavailable when the file exists but cannot be read; None means no key set.
    """
    key = _read_key_from_secrets(provider)
    if key and validate_key(key, provider):
        json_handler.log_operation("key_retrieved", {"provider": provider, "source": "secrets"})
        return key

    return None


def _read_key_from_secrets(provider: str) -> Optional[str]:
    """Read API key directly from ~/.secrets/aipass/.env."""
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
