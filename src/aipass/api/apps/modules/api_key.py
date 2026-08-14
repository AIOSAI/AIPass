# =================== AIPass ====================
# Name: api_key.py
# Description: API Key Management Module
# Version: 1.0.1
# Created: 2025-11-15
# Modified: 2026-08-11
# =============================================

"""
API Key Management Module

Orchestrates API key and credential operations:
- Get/validate keys
- List providers
- Initialize .env template
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

from typing import List
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, header, success, error
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.auth import keys, env, secrets


def print_introspection():
    """Show module introspection - connected handlers and capabilities"""
    console.print()
    header("API Key Module Introspection")
    console.print()

    console.print("[cyan]Purpose:[/cyan] API key management and validation")
    console.print()

    console.print("[cyan]Connected Handlers:[/cyan]")
    console.print("  • api.apps.handlers.auth.keys")
    console.print("  • api.apps.handlers.auth.env (template creation)")
    console.print("  • api.apps.handlers.config.provider")
    console.print("  • api.apps.handlers.json.json_handler")
    console.print()

    console.print("[cyan]Available Workflows:[/cyan]")
    console.print("  • get_key() - Retrieve API key")
    console.print("  • validate_key() - Validate credentials")
    console.print("  • list_providers() - Show providers")
    console.print("  • init_env() - Initialize configuration")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle API key management commands

    Args:
        command: Command name
        args: Command arguments

    Returns:
        True if command was handled, False otherwise
    """
    try:
        if command not in ["get-key", "validate", "list-providers", "init", "get-secret"]:
            return False

        # `validate google` is OAuth2, owned by google_client — google is not in
        # PROVIDER_DEFAULTS. This module is discovered first, so claiming it here
        # shadowed the documented command with "No API key found for google".
        if command == "validate" and args and args[0] == "google":
            return False

        # Help gate — a help flag ANYWHERE means "explain", never "execute".
        # Modules are also reachable via __main__, which bypasses the router's
        # normalisation, so the whole-sequence check is needed here too:
        # `get-key <provider> --help` otherwise reached get_key() and printed
        # masked key material. Bare "help" stays a flag only in first position.
        if args and (args[0] == "help" or any(arg in ("--help", "-h") for arg in args)):
            print_help()
            return True

        # Log operation
        json_handler.log_operation(f"api_key_{command}", {"command": command})

        # Route all commands before introspection gate
        if command == "list-providers":
            list_providers()
            return True
        if command == "init":
            init_env()
            return True
        if command == "get-key":
            get_key(args)
            return True
        if command == "get-secret":
            get_secret_cmd(args)
            return True
        if command == "validate":
            validate_key(args)
            return True

        # NO-ARGS GATE (seedgo standard) — only for unrecognized subcommands
        if not args:
            print_introspection()
            return True

        return True
    except Exception as e:
        logger.error(f"Error in api_key.handle_command: {e}")
        raise


def get_key(args: List[str]):
    """Orchestrate key retrieval workflow"""
    provider_name = args[0] if args else "openrouter"

    header(f"Get API Key - {provider_name}")
    console.print()

    # Call handler to get key
    api_key = keys.get_api_key(provider_name)

    if api_key:
        success(f"API key retrieved for {provider_name}")
        masked = api_key[:6] + "****" + api_key[-4:] if len(api_key) > 10 else "****"
        console.print(f"  Key: {masked}")
    else:
        error(f"Failed to retrieve API key for {provider_name}")


def validate_key(args: List[str]):
    """Orchestrate key validation workflow"""
    provider_name = args[0] if args else "openrouter"

    header(f"Validate API Key - {provider_name}")
    console.print()

    # Get key from handler
    api_key = keys.get_api_key(provider_name)

    if not api_key:
        error(f"No API key found for {provider_name}")
        return

    # Validate via handler
    is_valid = keys.validate_key(api_key, provider_name)

    if is_valid:
        success(f"API key for {provider_name} is valid")
    else:
        error(f"API key for {provider_name} is invalid")


def list_providers():
    """Orchestrate list providers workflow"""
    from aipass.api.apps.handlers.config.provider import PROVIDER_DEFAULTS

    header("Available Providers")
    console.print()

    for provider_name in sorted(PROVIDER_DEFAULTS):
        console.print(f"  - {provider_name}")
    console.print()


def init_env():
    """Orchestrate initialization workflow"""
    header("Initialize API Configuration")
    console.print()

    env_path = Path.home() / ".secrets" / "aipass" / ".env"

    if env_path.exists():
        success(f"Environment file already exists at {env_path}")
        return

    # Create .env template via handler
    if env.create_env_template():
        success(f"Environment template created at {env_path}")
    else:
        error("Failed to create environment template")


def get_secret_cmd(args: List[str]):
    """Orchestrate secret retrieval workflow (masked output only — no raw values to stdout)"""
    import json
    import os

    if not args:
        error("Usage: drone @api get-secret <provider/slug> [--out FILE] [--json] [--list]")
        return

    has_json = "--json" in args
    has_list = "--list" in args
    has_out = "--out" in args
    out_file = None
    if has_out:
        out_idx = args.index("--out")
        if out_idx + 1 < len(args):
            out_file = args[out_idx + 1]
        else:
            error("--out requires a file path argument")
            return

    clean_args = [a for a in args if not a.startswith("--")]
    if has_out and out_file in clean_args:
        clean_args.remove(out_file)

    if not clean_args:
        error("Usage: drone @api get-secret <provider/slug> [--out FILE] [--json] [--list]")
        return

    parts = clean_args[0].split("/", 1)
    provider = parts[0]

    if has_list:
        slugs = secrets.list_secrets(provider)
        for slug in slugs:
            # codeql[py/clear-text-logging-sensitive-data]  # slug names are identifiers, not secret values
            console.print(slug)
        return

    if len(parts) != 2 or not parts[1]:
        error("Expected format: <provider>/<slug>  (e.g. telegram/bot)")
        return

    slug = parts[1]
    result = secrets.get_secret(provider, slug, as_json=has_json)

    if result is None:
        error(f"Secret not found: {provider}/{slug}")
        return

    if out_file:
        content = json.dumps(result, indent=2) if has_json else str(result)
        fd = os.open(out_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, content.encode("utf-8"))
        finally:
            os.close(fd)
        success(f"Wrote {provider}/{slug} to {out_file}")
    else:
        value_len = len(json.dumps(result)) if has_json else len(str(result))
        success(f"{provider}/{slug}: set ({value_len} chars)")


def fetch_api_key(provider: str = "openrouter"):
    """Retrieve a validated API key for a provider from secrets."""
    return keys.get_api_key(provider)


def fetch_validate_key(key: str, provider: str = "openrouter") -> bool:
    """Validate an API key format for a given provider."""
    return keys.validate_key(key, provider)


def get_validation_rules(provider: str) -> dict:
    """Retrieve validation rules for a provider from the auth handler."""
    return keys.get_validation_rules(provider)


def print_help():
    """Print drone-compliant help output with Rich markup"""
    console.print()
    console.print("[bold cyan]API_KEY — Manage API keys and credentials[/bold cyan]")
    console.print()
    console.print("[yellow]COMMANDS:[/yellow]")
    console.print("  [cyan]get-key[/cyan]         [dim]Retrieve API key for a provider[/dim]")
    console.print("  [cyan]get-secret[/cyan]      [dim]Read secret from provider store[/dim]")
    console.print("  [cyan]validate[/cyan]        [dim]Validate API key[/dim]")
    console.print("  [cyan]list-providers[/cyan]  [dim]List available providers[/dim]")
    console.print("  [cyan]init[/cyan]            [dim]Initialize .env template[/dim]")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [cyan]drone @api[/cyan] <command> \\[args]")
    console.print("  [cyan]drone @api[/cyan] --help")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [cyan]drone @api get-key openrouter[/cyan]")
    console.print()
    console.print("  [dim]# Check if a secret exists (masked summary, no raw value)[/dim]")
    console.print("  [cyan]drone @api get-secret telegram/bot[/cyan]")
    console.print()
    console.print("  [dim]# Write secret to a protected file[/dim]")
    console.print("  [cyan]drone @api get-secret telegram/bot --out token.txt[/cyan]")
    console.print()
    console.print("  [dim]# Write secret as JSON to a protected file[/dim]")
    console.print("  [cyan]drone @api get-secret telegram/bot --out bot.json --json[/cyan]")
    console.print()
    console.print("  [dim]# List secrets for a provider[/dim]")
    console.print("  [cyan]drone @api get-secret telegram --list[/cyan]")
    console.print()
    console.print("  [dim]# Programmatic access (in-process, no stdout):[/dim]")
    console.print("  [dim]from aipass.api.apps.modules.secrets import get_secret[/dim]")
    console.print()
    console.print("  [dim]# Validate key[/dim]")
    console.print("  [cyan]drone @api validate openrouter[/cyan]")
    console.print()
    console.print("  [dim]# List providers[/dim]")
    console.print("  [cyan]drone @api list-providers[/cyan]")
    console.print()
    console.print("  [dim]# Initialize environment[/dim]")
    console.print("  [cyan]drone @api init[/cyan]")
    console.print()


if __name__ == "__main__":
    """Standalone execution mode"""
    args = sys.argv[1:]

    # Show introspection when run without arguments
    if len(args) == 0:
        print_introspection()
        sys.exit(0)

    # Show help for explicit help flags
    if args[0] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    # Execute command
    command = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    if handle_command(command, remaining_args):
        sys.exit(0)
    else:
        error(f"Unknown command: {command}", suggestion="Run 'drone @api --help' for available commands")
        sys.exit(1)
