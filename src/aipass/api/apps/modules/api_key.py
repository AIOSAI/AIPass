# =================== AIPass ====================
# Name: api_key.py
# Description: API Key Management Module
# Version: 1.0.0
# Created: 2025-11-15
# Modified: 2025-11-15
# =============================================

"""
API Key Management Module

Orchestrates API key and credential operations:
- Get/validate keys
- List providers
- Initialize .env template
"""

import sys
from pathlib import Path

from typing import List
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, header, success, error, warning, section
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.auth import keys, env
from aipass.api.apps.handlers.config import provider


def print_introspection():
    """Show module introspection - connected handlers and capabilities"""
    console.print()
    header("API Key Module Introspection")
    console.print()

    console.print("[cyan]Purpose:[/cyan] API key management and validation")
    console.print()

    console.print("[cyan]Connected Handlers:[/cyan]")
    console.print("  • api.apps.handlers.auth.keys")
    console.print("  • api.apps.handlers.auth.env")
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
        if command not in ["get-key", "validate", "list-providers", "init"]:
            return False

        # Help gate
        if args and args[0] in ("--help", "-h", "help"):
            print_help()
            return True

        # Log operation
        json_handler.log_operation(f"api_key_{command}", {"command": command})

        # Standalone commands — route before introspection gate
        if command == "list-providers":
            list_providers()
            return True
        if command == "init":
            init_env()
            return True

        # NO-ARGS GATE (seedgo standard)
        if not args:
            print_introspection()
            return True

        # Arg-required commands
        if command == "get-key":
            get_key(args)
        elif command == "validate":
            validate_key(args)

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
        console.print(f"  Key (first 20 chars): {api_key[:20]}...")
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
    header("Available Providers")
    console.print()

    # TODO: Get from handler when implemented
    console.print("  - openrouter")
    console.print()


def init_env():
    """Orchestrate initialization workflow"""
    header("Initialize API Configuration")
    console.print()

    # Create .env template via handler
    if env.create_env_template():
        success("Environment template created")
    else:
        error("Failed to create environment template")


def print_help():
    """Print help output for API key management"""
    import argparse

    parser = argparse.ArgumentParser(
        description='API Key Management Module - Manage API keys and credentials',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
COMMANDS:
  get-key          - Retrieve API key for a provider
  validate         - Validate API key
  list-providers   - List available providers
  init             - Initialize .env template

USAGE:
  python3 api_key.py <command> [args]
  python3 api_key.py --help

EXAMPLES:
  # Get key for provider
  python3 api_key.py get-key openrouter

  # Validate key
  python3 api_key.py validate openrouter

  # List providers
  python3 api_key.py list-providers

  # Initialize environment
  python3 api_key.py init
        """
    )
    console.print(parser.format_help())


if __name__ == "__main__":
    """Standalone execution mode"""
    args = sys.argv[1:]

    # Show introspection when run without arguments
    if len(args) == 0:
        print_introspection()
        sys.exit(0)

    # Show help for explicit help flags
    if args[0] in ['--help', '-h', 'help']:
        print_help()
        sys.exit(0)

    # Execute command
    command = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    if handle_command(command, remaining_args):
        sys.exit(0)
    else:
        console.print()
        console.print(f"[red]Unknown command: {command}[/red]")
        console.print()
        console.print("Run [dim]python3 api_key.py --help[/dim] for available commands")
        console.print()
        sys.exit(1)
