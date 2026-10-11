# =================== AIPass ====================
# Name: secrets.py
# Description: Secrets Store Handler
# Version: 1.0.1
# Created: 2026-06-15
# Modified: 2026-10-10
# =============================================

"""
Secrets Store Handler

Reads and writes structured secrets in ~/.secrets/aipass/<provider>/<slug>.
Supports JSON config files and raw secret files.

Functions:
    get_secret() - Read a secret by provider/slug
    set_secret() - Write a secret to the provider store
    list_secrets() - List available slugs for a provider
"""

import json
import os
from pathlib import Path
from typing import Any, List, Optional, Union

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

SECRETS_BASE = Path.home() / ".secrets" / "aipass"

# Keys to search for when returning a plain (non-JSON) secret value
_TOKEN_KEYS = ("bot_token", "api_key", "token", "secret", "password", "key")


# ==============================================
# SECRET RETRIEVAL
# ==============================================


def get_secret(provider: str, slug: str, as_json: bool = False) -> Optional[Any]:
    """
    Get secret value from provider store.

    Source: ~/.secrets/aipass/<provider>/<slug>.json or <slug>

    Args:
        provider: Provider directory name (e.g., 'telegram', 'discord')
        slug: Secret file name (without .json extension)
        as_json: If True, return full parsed dict; otherwise extract primary token

    Returns:
        Secret value (str or dict) or None if not found

    Example:
        >>> token = get_secret('telegram', 'bot')
        >>> if token:
        ...     print(f"Got token: {token[:10]}...")
    """
    provider_dir = SECRETS_BASE / provider

    if not provider_dir.exists() or not provider_dir.is_dir():
        # The provider's name, never its directory: a path inside the secrets
        # base reads as a secret's location (seedgo clear_text_secret_logging).
        logger.warning(f"Provider directory not found under the secrets base: {provider}")
        return None

    # Try JSON file first
    json_path = provider_dir / f"{slug}.json"
    if json_path.exists():
        result = _read_json_secret(json_path, as_json)
        if result is not None:
            json_handler.log_operation("secret_retrieved", {"provider": provider, "slug": slug, "format": "json"})
            return result

    # Fall back to raw file
    raw_path = provider_dir / slug
    if raw_path.exists():
        result = _read_raw_secret(raw_path)
        if result is not None:
            json_handler.log_operation("secret_retrieved", {"provider": provider, "slug": slug, "format": "raw"})
            return result

    logger.warning(f"Secret not found: {provider}/{slug}")
    return None


def list_secrets(provider: str) -> List[str]:
    """
    List available secret slugs for a provider.

    Args:
        provider: Provider directory name

    Returns:
        Sorted list of slug names (JSON extensions stripped)

    Example:
        >>> slugs = list_secrets('telegram')
        >>> print(slugs)
        ['bot', 'webhook']
    """
    provider_dir = SECRETS_BASE / provider

    if not provider_dir.exists() or not provider_dir.is_dir():
        return []

    slugs = []
    for entry in provider_dir.iterdir():
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        if not entry.is_file():
            continue

        name = entry.name
        if name.endswith(".json"):
            name = name[:-5]
        slugs.append(name)

    return sorted(slugs)


# ==============================================
# SECRET WRITING
# ==============================================


def set_secret(provider: str, slug: str, value: Union[str, dict], *, as_json: bool = False) -> Path:
    """
    Write a secret to the provider store.

    Destination: ~/.secrets/aipass/<provider>/<slug>.json

    Args:
        provider: Provider directory name (e.g., 'telegram')
        slug: Secret identifier (without .json extension)
        value: Secret value — string or dict
        as_json: If True, json.dump the value; else write as plain string

    Returns:
        Path to the written file

    Raises:
        OSError: If directory creation or file write fails
    """
    provider_dir = SECRETS_BASE / provider
    provider_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(provider_dir, 0o700)

    target = provider_dir / f"{slug}.json"

    if as_json:
        content = json.dumps(value, indent=2).encode("utf-8")
    else:
        content = json.dumps(str(value)).encode("utf-8")

    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, content)
    finally:
        os.close(fd)

    json_handler.log_operation(
        "secret_written",
        {"provider": provider, "slug": slug, "format": "json" if as_json else "raw"},
    )
    return target


# ==============================================
# PRIVATE HELPERS
# ==============================================


def _read_json_secret(path: Path, as_json: bool) -> Optional[Any]:
    """
    Read and parse a JSON secret file.

    Args:
        path: Path to JSON file
        as_json: If True, return full dict; otherwise extract primary token

    Returns:
        Parsed data or extracted token, or None on error
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        # No path: get_secret's "Secret not found: provider/slug" line that
        # follows names which one, without saying where it lives.
        logger.warning(f"Error reading a JSON secret file: {e}")
        return None

    if as_json:
        return data

    if isinstance(data, dict):
        for key in _TOKEN_KEYS:
            if key in data:
                return str(data[key])
        return json.dumps(data)

    return str(data)


def _read_raw_secret(path: Path) -> Optional[str]:
    """
    Read a raw (non-JSON) secret file.

    Args:
        path: Path to raw secret file

    Returns:
        Stripped file contents or None on error
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError as e:
        logger.warning(f"Error reading a raw secret file: {e}")
        return None
