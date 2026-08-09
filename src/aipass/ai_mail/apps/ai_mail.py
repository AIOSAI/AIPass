# =================== AIPass ====================
# Name: ai_mail.py
# Description: Entry point CLI for drone @ai_mail — inter-branch email system
# Version: 1.1.0
# Created: 2026-03-08
# Modified: 2026-08-07
# =============================================

"""
ai_mail Branch - Main Orchestrator

Modular architecture with auto-discovered modules.
Main handles routing, modules implement functionality.
"""

# Standard library imports
import os
import sys
import importlib
import signal
from pathlib import Path
from typing import Any, List

# AIPass infrastructure imports
from aipass.prax.apps.modules.logger import system_logger as logger

# CLI services for display
from aipass.cli.apps.modules import console, error, reset_command_state, resolve_exit

# Handle broken pipe gracefully (e.g. output piped to head)
# SIGPIPE does not exist on Windows
if hasattr(signal, "SIGPIPE"):
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

# Dashboard integration (optional, provided by prax)
_UPDATE_SECTION = None  # type: ignore

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

# =============================================================================
# CONSTANTS & CONFIG
# =============================================================================

# Module root
MODULE_ROOT = Path(__file__).parent

# Modules directory
MODULES_DIR = MODULE_ROOT / "modules"

# =============================================================================
# HELP DISPLAY
# =============================================================================


def print_help():
    """Print drone-compliant help output with Rich markup"""
    console.print()
    console.print("[bold cyan]AI_MAIL — Email system for branch communication[/bold cyan]")
    console.print()

    console.print("[yellow]COMMANDS:[/yellow]")
    console.print("  [cyan]dispatch[/cyan]  [dim]Send dispatch email + wake target (one step)[/dim]")
    console.print("  [cyan]email[/cyan]     [dim]Send email to a branch[/dim]")
    console.print("  [cyan]send[/cyan]      [dim]Send email (alias for email)[/dim]")
    console.print("  [cyan]inbox[/cyan]     [dim]List emails (new + opened)[/dim]")
    console.print("  [cyan]view[/cyan]      [dim]View email content (marks as opened)[/dim]")
    console.print("  [cyan]reply[/cyan]     [dim]Reply to email (closes + archives)[/dim]")
    console.print("  [cyan]close[/cyan]     [dim]Close email(s) without reply (archives)[/dim]")
    console.print("  [cyan]sent[/cyan]      [dim]View sent messages[/dim]")
    console.print("  [cyan]contacts[/cyan]  [dim]Manage contacts[/dim]")
    console.print()

    console.print("[yellow]EMAIL LIFECYCLE (v2):[/yellow]")
    console.print("  new → opened → closed")
    console.print("  [dim]new: Just arrived, never viewed[/dim]")
    console.print("  [dim]opened: You've viewed it, not yet resolved[/dim]")
    console.print("  [dim]closed: Resolved (replied or dismissed), auto-archived[/dim]")
    console.print()

    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [cyan]drone @ai_mail[/cyan] <command> [args]")
    console.print("  [cyan]drone @ai_mail --help[/cyan]")
    console.print()

    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print('  [cyan]drone @ai_mail dispatch @branch "Subject" "Body"[/cyan]')
    console.print('  [cyan]drone @ai_mail dispatch @branch "Subject" "Body" --fresh[/cyan]')
    console.print('  [cyan]drone @ai_mail email @seedgo "Subject" "Msg"[/cyan]  [dim]Send to branch[/dim]')
    console.print('  [cyan]drone @ai_mail email @all "Subject" "Msg"[/cyan]     [dim]Broadcast to all[/dim]')
    console.print("  [cyan]drone @ai_mail inbox[/cyan]                          [dim]List all emails[/dim]")
    console.print("  [cyan]drone @ai_mail view abc123[/cyan]                    [dim]View email[/dim]")
    console.print('  [cyan]drone @ai_mail reply abc123 "Thanks!"[/cyan]         [dim]Reply + close + archive[/dim]')
    console.print("  [cyan]drone @ai_mail close abc123[/cyan]                   [dim]Close single email[/dim]")
    console.print("  [cyan]drone @ai_mail close abc123 def456 ghi789[/cyan]     [dim]Close multiple[/dim]")
    console.print("  [cyan]drone @ai_mail close all[/cyan]                      [dim]Close ALL emails[/dim]")
    console.print()


# =============================================================================
# INTROSPECTION DISPLAY
# =============================================================================


def print_introspection():
    """Display discovered modules only (seedgo pattern)"""
    console.print()
    console.print("[bold cyan]AI_Mail - Branch Communication System[/bold cyan]")
    console.print()
    console.print("[dim]Email system for branch-to-branch communication[/dim]")
    console.print()

    # Discover modules
    modules = discover_modules()

    console.print(f"[yellow]Discovered Modules:[/yellow] {len(modules)}")
    console.print()

    for module in modules:
        module_name = module.__name__.split(".")[-1]
        console.print(f"  [cyan]•[/cyan] {module_name}")

    console.print()
    console.print("[dim]Run 'drone @ai_mail --help' for usage information[/dim]")
    console.print()


# =============================================================================
# MODULE DISCOVERY
# =============================================================================


def discover_modules() -> List[Any]:
    """
    Auto-discover modules from modules/ directory

    Returns:
        List of module objects with handle_command() function
    """
    modules = []

    if not MODULES_DIR.exists():
        logger.warning(f"Modules directory not found: {MODULES_DIR}")
        return modules

    logger.info(f"[{Path(__file__).stem}] Discovering modules...")

    files_found = list(MODULES_DIR.glob("*.py"))

    for file_path in files_found:
        # Skip __init__.py and private files
        if file_path.name.startswith("_"):
            continue

        module_name = f"aipass.ai_mail.apps.modules.{file_path.stem}"

        try:
            # Import module
            module = importlib.import_module(module_name)

            # Check for required interface
            if hasattr(module, "handle_command"):
                modules.append(module)
                logger.info(f"  [+] {module_name}")
            else:
                logger.warning(f"  [!] {module_name} - missing handle_command()")

        except Exception as e:
            logger.error(f"  [-] {module_name} - import error: {e}")

    logger.info(f"[{Path(__file__).stem}] Discovered {len(modules)} modules")
    return modules


# =============================================================================
# COMMAND ROUTING
# =============================================================================


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """
    Route command to appropriate module

    Pattern: Each module's handle_command() returns True if it handled the command

    Args:
        command: Command name (e.g., 'send', 'inbox', 'sent')
        args: Additional arguments
        modules: List of discovered modules

    Returns:
        True if command was handled, False otherwise
    """
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except BrokenPipeError:
            logger.info(f"[ai_mail] Broken pipe in {module.__name__} (stdout closed early)")
            return True
        except Exception as e:
            logger.error(f"Module {module.__name__} error: {e}")

    return False


# =============================================================================
# MAIN
# =============================================================================


def main():
    """Main entry point - routes commands to modules

    Exit codes: 0 success, 1 unroutable command, 2 routed but failed.
    A recognised command that failed (delivery refused, message not found,
    invalid reply_path) still returns True from its handler — that means
    "I handled this", not "it worked". Without the resolve_exit flip those
    failures exited 0 and every script reading the exit code was told a
    reply had been sent when it had not.
    """
    reset_command_state()
    try:
        # Parse arguments
        args = sys.argv[1:]

        # Show introspection when run without arguments
        if len(args) == 0:
            print_introspection()
            return 0

        # Show version
        if args[0] in ["--version", "-V"]:
            console.print("AI_MAIL v1.0.0")
            return 0

        # Show help for explicit help flags
        if args[0] in ["--help", "-h", "help"]:
            print_help()
            return 0

        # Command provided - try to route to modules
        modules = discover_modules()
        command = args[0]
        remaining_args = args[1:] if len(args) > 1 else []

        if not modules:
            error("No modules found")
            return 1

        if remaining_args and remaining_args[0] in ["--help", "-h"]:
            for module in modules:
                if module.handle_command(command, ["--help"]):
                    return 0
            print_help()
            return 0

        # Route command
        if route_command(command, remaining_args, modules):
            return resolve_exit(True)
        else:
            error(f"Unknown command: {command}")
            return 1

    except Exception as exc:
        logger.error("[ai_mail] Unhandled error in main: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
