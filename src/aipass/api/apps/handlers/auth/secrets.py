# =================== AIPass ====================
# Name: secrets.py
# Description: Secrets Store Handler
# Version: 1.0.2
# Created: 2026-06-15
# Modified: 2026-10-17
# =============================================

"""Secrets Store Handler"""

import json
import os
from pathlib import Path
from typing import Any, List, Optional, Union

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

SECRETS_BASE = Path.home() / ".secrets" / "aipass"

_TOKEN_KEYS = ("bot_token", "api_key", "token", "secret", "password", "key")


def get_secret(provider: str, slug: str, as_json: bool = False) -> Optional[Any]:
    """Get secret value from provider store."""
    provider_dir = SECRETS_BASE / provider

    if not provider_dir.exists() or not provider_dir.is_dir():
        # The provider's name, never its directory: a path in the secrets base reads as a secret's location.
        logger.warning(f"Provider directory not found under the secrets base: {provider}")
        return None

    json_path = provider_dir / f"{slug}.json"
    if json_path.exists():
        result = _read_json_secret(json_path, as_json)
        if result is not None:
            json_handler.log_operation("secret_retrieved", {"provider": provider, "slug": slug, "format": "json"})
            return result

    raw_path = provider_dir / slug
    if raw_path.exists():
        result = _read_raw_secret(raw_path)
        if result is not None:
            json_handler.log_operation("secret_retrieved", {"provider": provider, "slug": slug, "format": "raw"})
            return result

    # Never the slug: callers pass slugs read out of the store (list_secrets), which CodeQL flags as
    # clear-text logging of sensitive data.
    logger.warning("Secret not found under provider %s: no JSON or raw document for the requested slug", provider)
    return None


def list_secrets(provider: str) -> List[str]:
    """List available secret slugs for a provider."""
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


def set_secret(provider: str, slug: str, value: Union[str, dict], *, as_json: bool = False) -> Path:
    """Write a secret to the provider store."""
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


def _read_json_secret(path: Path, as_json: bool) -> Optional[Any]:
    """Read and parse a JSON secret file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        # No path: a path inside the secrets base reads as a secret's location.
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
    """Read a raw (non-JSON) secret file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError as e:
        logger.warning(f"Error reading a raw secret file: {e}")
        return None
