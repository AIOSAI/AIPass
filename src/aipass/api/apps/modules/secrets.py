# =================== AIPass ====================
# Name: secrets.py
# Description: Secrets Module — cross-branch in-process door
# Version: 1.0.0
# Created: 2026-06-15
# Modified: 2026-06-15
# =============================================

"""
Secrets Module

Cross-branch in-process API for the secrets provider store.
Consumers import directly instead of shelling out to the CLI.

Functions:
    get_secret() - Read a secret by provider/slug
    set_secret() - Write a secret to the provider store
    list_secrets() - List available slugs for a provider
    handle_command() - Route CLI commands (seedgo module discovery)
"""

import os
import sys
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")
from typing import Any, List, Optional, Union

from aipass.prax import logger  # noqa: F401 — seedgo imports standard
from aipass.cli.apps.modules import console, header, error
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.auth import secrets as _handler


def print_introspection():
    """Show module introspection - connected handlers and capabilities"""
    console.print()
    header("Secrets Module Introspection")
    console.print()

    console.print("[cyan]Purpose:[/cyan] Cross-branch secrets access (in-process)")
    console.print()

    console.print("[cyan]Connected Handlers:[/cyan]")
    console.print("  • api.apps.handlers.auth.secrets")
    console.print()

    console.print("[cyan]Available Workflows:[/cyan]")
    console.print("  • get_secret() - Read secret by provider/slug")
    console.print("  • set_secret() - Write secret to provider store")
    console.print("  • list_secrets() - List slugs for a provider")
    console.print()


def print_help():
    """Print help output for secrets module"""
    print_introspection()


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle secrets commands (module discovery hook).

    This module does not own any CLI commands — get-secret is routed
    through api_key.py. This exists for seedgo module discovery only.

    Args:
        command: Command name
        args: Command arguments

    Returns:
        False — no commands handled here
    """
    return False


def get_secret(provider: str, slug: str, as_json: bool = False) -> Optional[Any]:
    """
    Read a secret from the provider store.

    This is the sanctioned cross-branch import path. Consumers call this
    instead of shelling out to 'drone @api get-secret'.

    Args:
        provider: Provider directory name (e.g., 'telegram', 'openrouter')
        slug: Secret identifier (without .json extension)
        as_json: If True, return full parsed dict; otherwise extract primary token

    Returns:
        Secret value (str or dict) or None if not found
    """
    result = _handler.get_secret(provider, slug, as_json=as_json)
    json_handler.log_operation("secrets_get", {"provider": provider, "slug": slug, "found": result is not None})
    return result


def set_secret(provider: str, slug: str, value: Union[str, dict], *, as_json: bool = False) -> Path:
    """
    Write a secret to the provider store.

    This is the sanctioned cross-branch write path. Consumers call this
    instead of shelling out to the CLI.

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
    result = _handler.set_secret(provider, slug, value, as_json=as_json)
    json_handler.log_operation("secrets_set", {"provider": provider, "slug": slug, "wrote": str(result)})
    return result


def list_secrets(provider: str) -> List[str]:
    """
    List available secret slugs for a provider.

    Args:
        provider: Provider directory name

    Returns:
        Sorted list of slug names
    """
    return _handler.list_secrets(provider)


if __name__ == "__main__":
    """Standalone execution mode"""
    args = sys.argv[1:]

    if len(args) == 0:
        print_introspection()
        sys.exit(0)

    if args[0] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    error(f"Unknown command: {args[0]}")
    sys.exit(1)
