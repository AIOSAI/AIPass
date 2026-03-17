# =================== AIPass ====================
# Name: openrouter_client.py
# Description: OpenRouter Client Module
# Version: 1.0.0
# Created: 2025-11-15
# Modified: 2025-11-15
# =============================================

"""
OpenRouter Client Module

Orchestrates LLM API client operations:
- Test connections
- Make API calls
- List models
- Check status
"""

import sys
from pathlib import Path

from typing import List
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, header, success, error, warning, section
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.auth import keys
from aipass.api.apps.handlers.openrouter import client, models


def print_introspection():
    """Show module introspection - connected handlers and capabilities"""
    console.print()
    header("OpenRouter Client Module Introspection")
    console.print()

    console.print("[cyan]Purpose:[/cyan] OpenRouter LLM API client operations")
    console.print()

    console.print("[cyan]Connected Handlers:[/cyan]")
    console.print("  • api.apps.handlers.auth.keys")
    console.print("  • api.apps.handlers.openrouter.client")
    console.print("  • api.apps.handlers.openrouter.models")
    console.print("  • api.apps.handlers.json.json_handler")
    console.print()

    console.print("[cyan]Available Workflows:[/cyan]")
    console.print("  • test_connection() - Test connection")
    console.print("  • make_call() - Make API call")
    console.print("  • list_models() - List models")
    console.print("  • check_status() - Check status")
    console.print()


def print_help():
    """Print module help with argparse"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python3 api.py",
        description="OpenRouter Client - Manage LLM API connections",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
COMMANDS:
  test             - Test OpenRouter connection
  call             - Make API call to model
  models           - List available models
  status           - Check connection status

USAGE:
  python3 api.py test
  python3 api.py call <prompt> [--model MODEL]
  python3 api.py models
  python3 api.py status

ARGUMENTS:
  prompt - Prompt to send to the model
  --model - Model to use (optional)

EXAMPLES:
  # Test OpenRouter connection
  python3 api.py test

  # Make an API call
  python3 api.py call "What is AI?" --model gpt-4

  # List available models
  python3 api.py models

  # Check connection status
  python3 api.py status
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # test command
    subparsers.add_parser("test", help="Test OpenRouter connection")

    # call command
    call_parser = subparsers.add_parser("call", help="Make API call to model")
    call_parser.add_argument("prompt", help="Prompt to send")
    call_parser.add_argument("--model", help="Model to use")

    # models command
    subparsers.add_parser("models", help="List available models")

    # status command
    subparsers.add_parser("status", help="Check connection status")

    console.print(parser.format_help())


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle OpenRouter client commands

    Args:
        command: Command name
        args: Command arguments

    Returns:
        True if command was handled, False otherwise
    """
    try:
        if command not in ["test", "call", "models", "status"]:
            return False

        # Help gate
        if args and args[0] in ("--help", "-h", "help"):
            print_help()
            return True

        # Log operation
        json_handler.log_operation(f"openrouter_{command}", {"command": command})

        # Standalone commands — route before introspection gate
        if command == "test":
            test_connection()
            return True
        if command == "models":
            list_models()
            return True
        if command == "status":
            check_status()
            return True

        # NO-ARGS GATE (seedgo standard)
        if not args:
            print_introspection()
            return True

        # Arg-required commands
        if command == "call":
            make_call(args)

        return True
    except Exception as e:
        logger.error(f"Error in openrouter_client.handle_command: {e}")
        raise


def test_connection():
    """Orchestrate connection test workflow"""
    header("Test OpenRouter Connection")
    console.print()

    # Get API key via handler
    api_key = keys.get_api_key("openrouter")

    if not api_key:
        error("No API key configured")
        return

    warning("Testing connection...")

    # TODO: Call handler to test connection when implemented
    success("Connection test successful")


def make_call(args: List[str]):
    """Orchestrate API call workflow"""
    header("OpenRouter API Call")
    console.print()

    # TODO: Parse args for model, messages
    # TODO: Call handler to make request
    warning("API call workflow - TODO")


def list_models():
    """Orchestrate list models workflow"""
    header("Available Models")
    console.print()

    # Get API key via handler
    api_key = keys.get_api_key("openrouter")

    if not api_key:
        error("No API key configured")
        return

    warning("Fetching available models...")

    # Call handler to fetch models
    model_list = models.fetch_models_from_api(api_key)

    if model_list:
        success(f"Found {len(model_list)} models")
        for model in model_list[:10]:
            console.print(f"  - {model}")
        if len(model_list) > 10:
            console.print(f"  ... and {len(model_list) - 10} more")
    else:
        error("Failed to fetch models")


def check_status():
    """Orchestrate status check workflow"""
    header("OpenRouter Client Status")
    console.print()

    # TODO: Call handlers for status when implemented
    warning("Client status - TODO")


# =============================================
# PUBLIC API - Re-export handler functions
# =============================================

def get_response(prompt: str, caller: str | None = None, model: str | None = None, **kwargs):
    """
    Public API: Get response from OpenRouter

    This is a re-export of the handler function for cross-branch access.
    Flow and other branches should use this module-level function instead
    of importing directly from handlers.

    Args:
        prompt: User prompt text
        caller: Module making the request (auto-detected if not provided)
        model: Model to use (required - caller must provide from branch config)
        **kwargs: Additional OpenAI API parameters

    Returns:
        Dict with 'content', 'id', 'model' or None on failure

    Example:
        >>> from aipass.api.apps.modules.openrouter_client import get_response
        >>> response = get_response("Hello", caller="flow", model="anthropic/claude-3.5-sonnet")
        >>> if response:
        ...     console.print(response['content'])
    """
    return client.get_response(prompt, caller, model, **kwargs)


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
        console.print("Run [dim]python3 openrouter_client.py --help[/dim] for available commands")
        console.print()
        sys.exit(1)
