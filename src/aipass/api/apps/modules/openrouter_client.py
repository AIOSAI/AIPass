# =================== AIPass ====================
# Name: openrouter_client.py
# Description: OpenRouter Client Module
# Version: 1.0.3
# Created: 2025-11-15
# Modified: 2026-10-17
# =============================================
# pyright: reportMissingImports=false

"""OpenRouter Client Module"""

import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from typing import List
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, header, success, error, warning
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
    """Print drone-compliant help output with Rich markup"""
    console.print()
    console.print("[bold cyan]OPENROUTER_CLIENT — Manage LLM API connections[/bold cyan]")
    console.print()
    console.print("[yellow]COMMANDS:[/yellow]")
    console.print("  [cyan]test[/cyan]     [dim]Test OpenRouter connection[/dim]")
    console.print("  [cyan]call[/cyan]     [dim]Make API call to model[/dim]")
    console.print("  [cyan]models[/cyan]   [dim]List available models[/dim]")
    console.print("  [cyan]status[/cyan]   [dim]Check connection status[/dim]")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [cyan]drone @api test[/cyan]")
    console.print("  [cyan]drone @api call[/cyan] <prompt> [--model MODEL]")
    console.print("  [cyan]drone @api models[/cyan]")
    console.print("  [cyan]drone @api status[/cyan]")
    console.print()
    console.print("[yellow]ARGUMENTS:[/yellow]")
    console.print("  [cyan]prompt[/cyan]   [dim]Prompt to send to the model[/dim]")
    console.print("  [cyan]--model[/cyan]  [dim]Model to use (optional)[/dim]")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]# Test OpenRouter connection[/dim]")
    console.print("  [cyan]drone @api test[/cyan]")
    console.print()
    console.print("  [dim]# Make an API call[/dim]")
    console.print('  [cyan]drone @api call "What is AI?" --model gpt-4[/cyan]')
    console.print()
    console.print("  [dim]# List available models[/dim]")
    console.print("  [cyan]drone @api models[/cyan]")
    console.print()
    console.print("  [dim]# Check connection status[/dim]")
    console.print("  [cyan]drone @api status[/cyan]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle OpenRouter client commands"""
    try:
        if command not in ["test", "call", "models", "status"]:
            return False

        # A help flag anywhere means explain (__main__ bypasses the router's check); bare "help" counts
        # only first, so a prompt containing "help" is still sent.
        if args and (args[0] == "help" or any(arg in ("--help", "-h") for arg in args)):
            print_help()
            return True

        json_handler.log_operation(f"openrouter_{command}", {"command": command})

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

    try:
        api_key = keys.get_api_key("openrouter")
    except keys.KeyUnavailable as e:
        error(str(e))
        return

    if not api_key:
        diagnosis = keys.diagnose_key("openrouter")
        error(diagnosis)
        return

    try:
        model_list = models.fetch_models_from_api(api_key)
    except models.ModelsUnavailable as e:
        error(f"Connection failed — {e}")
        return

    success(f"Connection successful — {len(model_list)} models available")


def make_call(args: List[str]):
    """Orchestrate API call workflow"""
    header("OpenRouter API Call")
    console.print()

    if not args:
        error("Prompt required", suggestion='drone @api call "your prompt" --model MODEL')
        return

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

    try:
        response = client.get_response(prompt, caller="cli", model=model)
    except (client.OpenRouterUnavailable, keys.KeyUnavailable) as e:
        error(str(e))
        return

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

    try:
        api_key = keys.get_api_key("openrouter")
    except keys.KeyUnavailable as e:
        error(str(e))
        return

    if not api_key:
        diagnosis = keys.diagnose_key("openrouter")
        error(diagnosis)
        return

    console.print("[dim]Fetching available models...[/dim]")

    try:
        model_list = models.fetch_models_from_api(api_key)
    except models.ModelsUnavailable as e:
        error(f"Failed to fetch models — {e}")
        return

    success(f"Found {len(model_list)} models")
    console.print()

    display_count = len(model_list) if show_all else min(10, len(model_list))

    console.print(f"  {'Model':<50} {'Context':>10} {'$/prompt':>10} {'$/compl':>10}")
    console.print(f"  {'─' * 50} {'─' * 10} {'─' * 10} {'─' * 10}")

    for model_data in model_list[:display_count]:
        model_id = model_data.get("id", "unknown")
        context = model_data.get("context_length", 0)
        pricing = model_data.get("pricing", {})
        prompt_cost = pricing.get("prompt", "0")
        completion_cost = pricing.get("completion", "0")

        if context >= 1_000_000:
            ctx_str = f"{context // 1_000_000}M"
        elif context >= 1_000:
            ctx_str = f"{context // 1_000}k"
        else:
            ctx_str = str(context)

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

    try:
        api_key = keys.get_api_key("openrouter")
    except keys.KeyUnavailable as e:
        error(str(e))
        return

    if api_key:
        masked = api_key[:8] + "..." + api_key[-4:]
        console.print("  [cyan]Key configured:[/cyan]  [green]yes[/green]")
        console.print(f"  [cyan]Key:[/cyan]             {masked}")
    else:
        warning("API key not configured")
        diagnosis = keys.diagnose_key("openrouter")
        console.print(f"  [cyan]Reason:[/cyan]          {diagnosis}")

    console.print("  [cyan]Provider:[/cyan]        OpenRouter")
    console.print("  [cyan]Base URL:[/cyan]        https://openrouter.ai/api/v1")

    try:
        import openai  # noqa: F401

        console.print("  [cyan]OpenAI SDK:[/cyan]     [green]available[/green]")
    except ImportError:
        logger.warning("OpenAI SDK not installed")
        warning("OpenAI SDK not installed")

    cache_stats = client.get_cache_stats()
    console.print(f"  [cyan]Cached clients:[/cyan] {cache_stats['cached_clients']}/{cache_stats['max_cache_size']}")
    console.print()


def get_response(prompt: str, caller: str | None = None, model: str | None = None, **kwargs):
    """
    Public API: Get response from OpenRouter

    Raises client.OpenRouterUnavailable or keys.KeyUnavailable with the reason.
    """
    return client.get_response(prompt, caller, model, **kwargs)


def extract_response(response):
    """Public API: Extract content from an OpenRouter API response object."""
    return client.extract_response(response)


if __name__ == "__main__":
    """Standalone execution mode"""
    args = sys.argv[1:]

    if len(args) == 0:
        print_introspection()
        sys.exit(0)

    if args[0] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    command = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    if handle_command(command, remaining_args):
        sys.exit(0)
    else:
        error(f"Unknown command: {command}", suggestion="Run 'drone @api --help' for available commands")
        sys.exit(1)
