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

from typing import List
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, header, success, error
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
        prog="drone @api",
        description="OpenRouter Client - Manage LLM API connections",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
COMMANDS:
  test             - Test OpenRouter connection
  call             - Make API call to model
  models           - List available models
  status           - Check connection status

USAGE:
  drone @api test
  drone @api call <prompt> [--model MODEL]
  drone @api models
  drone @api status

ARGUMENTS:
  prompt - Prompt to send to the model
  --model - Model to use (optional)

EXAMPLES:
  # Test OpenRouter connection
  drone @api test

  # Make an API call
  drone @api call "What is AI?" --model gpt-4

  # List available models
  drone @api models

  # Check connection status
  drone @api status
        """,
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

        # Route all commands before introspection gate
        if command == "test":
            test_connection()
            return True
        if command == "models":
            list_models(args)
            return True
        if command == "status":
            check_status()
            return True
        if command == "call":
            make_call(args)
            return True

        # NO-ARGS GATE (seedgo standard) — only for unrecognized subcommands
        if not args:
            print_introspection()
            return True

        return True
    except Exception as e:
        logger.error(f"Error in openrouter_client.handle_command: {e}")
        raise


def test_connection():
    """Orchestrate connection test workflow"""
    header("Test OpenRouter Connection")
    console.print()

    console.print("[dim]Testing connection...[/dim]")

    # Get API key via handler
    api_key = keys.get_api_key("openrouter")

    if not api_key:
        diagnosis = keys.diagnose_key("openrouter")
        error(diagnosis)
        return

    # Real API ping — hit /models endpoint
    model_list = models.fetch_models_from_api(api_key)

    if model_list:
        success(f"Connection successful — {len(model_list)} models available")
    else:
        error("Connection failed — could not reach OpenRouter API")


def make_call(args: List[str]):
    """Orchestrate API call workflow"""
    header("OpenRouter API Call")
    console.print()

    if not args:
        error("Prompt required", suggestion='drone @api call "your prompt" --model MODEL')
        return

    # Parse args: first non-flag arg is prompt, --model MODEL is optional
    prompt = None
    model = None
    i = 0
    while i < len(args):
        if args[i] == "--model" and i + 1 < len(args):
            model = args[i + 1]
            i += 2
        elif prompt is None:
            prompt = args[i]
            i += 1
        else:
            i += 1

    if not prompt:
        error("Prompt required", suggestion='drone @api call "your prompt" --model MODEL')
        return

    if not model:
        error("Model required", suggestion='drone @api call "your prompt" --model anthropic/claude-3.5-sonnet')
        return

    console.print(f"[dim]Calling {model}...[/dim]")

    response = client.get_response(prompt, caller="cli", model=model)

    if response:
        success(f"Response received ({len(response['content'])} chars)")
        console.print()
        console.print(response["content"])
    else:
        error("API call failed")


def list_models(args: List[str] | None = None):
    """Orchestrate list models workflow"""
    header("Available Models")
    console.print()

    show_all = args and "--all" in args

    # Get API key via handler
    api_key = keys.get_api_key("openrouter")

    if not api_key:
        diagnosis = keys.diagnose_key("openrouter")
        error(diagnosis)
        return

    console.print("[dim]Fetching available models...[/dim]")

    # Call handler to fetch models
    model_list = models.fetch_models_from_api(api_key)

    if not model_list:
        error("Failed to fetch models")
        return

    success(f"Found {len(model_list)} models")
    console.print()

    # Format as table
    display_count = len(model_list) if show_all else min(10, len(model_list))

    console.print(f"  {'Model':<50} {'Context':>10} {'$/prompt':>10} {'$/compl':>10}")
    console.print(f"  {'─' * 50} {'─' * 10} {'─' * 10} {'─' * 10}")

    for model_data in model_list[:display_count]:
        model_id = model_data.get("id", "unknown")
        context = model_data.get("context_length", 0)
        pricing = model_data.get("pricing", {})
        prompt_cost = pricing.get("prompt", "0")
        completion_cost = pricing.get("completion", "0")

        # Format context length
        if context >= 1_000_000:
            ctx_str = f"{context // 1_000_000}M"
        elif context >= 1_000:
            ctx_str = f"{context // 1_000}k"
        else:
            ctx_str = str(context)

        # Format pricing
        if str(prompt_cost) == "0" and str(completion_cost) == "0":
            p_str = "free"
            c_str = "free"
        else:
            p_str = f"${prompt_cost}"
            c_str = f"${completion_cost}"

        console.print(f"  {model_id:<50} {ctx_str:>10} {p_str:>10} {c_str:>10}")

    if not show_all and len(model_list) > 10:
        console.print()
        console.print(f"  [dim]Showing 10 of {len(model_list)} — use --all for full list[/dim]")


def check_status():
    """Orchestrate status check workflow"""
    header("OpenRouter Client Status")
    console.print()

    # Key status
    api_key = keys.get_api_key("openrouter")

    if api_key:
        masked = api_key[:8] + "..." + api_key[-4:]
        console.print("  [cyan]Key configured:[/cyan]  [green]yes[/green]")
        console.print(f"  [cyan]Key:[/cyan]             {masked}")
    else:
        console.print("  [cyan]Key configured:[/cyan]  [red]no[/red]")
        diagnosis = keys.diagnose_key("openrouter")
        console.print(f"  [cyan]Reason:[/cyan]          {diagnosis}")

    console.print("  [cyan]Provider:[/cyan]        OpenRouter")
    console.print("  [cyan]Base URL:[/cyan]        https://openrouter.ai/api/v1")

    # OpenAI SDK availability
    try:
        import openai  # noqa: F401

        console.print("  [cyan]OpenAI SDK:[/cyan]     [green]available[/green]")
    except ImportError:
        logger.warning("OpenAI SDK not installed")
        console.print("  [cyan]OpenAI SDK:[/cyan]     [red]missing[/red]")

    # Client cache stats
    cache_stats = client.get_cache_stats()
    console.print(f"  [cyan]Cached clients:[/cyan] {cache_stats['cached_clients']}/{cache_stats['max_cache_size']}")
    console.print()


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
    if args[0] in ["--help", "-h", "help"]:
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
        console.print("Run [dim]drone @api --help[/dim] for available commands")
        console.print()
        sys.exit(1)
