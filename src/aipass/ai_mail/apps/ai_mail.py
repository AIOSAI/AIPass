# =================== AIPass ====================
# Name: ai_mail.py
# Description: Entry point CLI for drone @ai_mail — inter-branch email system
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
ai_mail Branch - Main Orchestrator

Modular architecture with auto-discovered modules.
Main handles routing, modules implement functionality.
"""

# Standard library imports
import sys
import importlib
import argparse
import signal
from pathlib import Path
from typing import Dict, Any, Optional, List

# Handle broken pipe gracefully (e.g. output piped to head)
# SIGPIPE does not exist on Windows
if hasattr(signal, 'SIGPIPE'):
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

# Dashboard integration (optional, requires dev_central package)
_UPDATE_SECTION = None  # type: ignore

# AIPass infrastructure imports
from aipass.prax.apps.modules.logger import system_logger as logger

# CLI services for display
from aipass.cli.apps.modules import console

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
    """Print drone-compliant help output"""
    parser = argparse.ArgumentParser(
        description='AI_MAIL Branch Operations - Email system for branch communication',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
COMMANDS:
  inbox     - List emails (new + opened)
  view      - View email content (marks as opened)
  reply     - Reply to email (closes + archives)
  close     - Close email(s) without reply (archives)
  send      - Send email to a branch
  sent      - View sent messages
  contacts  - Manage contacts
  ping      - Memory health check
  dispatch  - Dispatch status and log

EMAIL LIFECYCLE (v2):
  new → opened → closed
  - new: Just arrived, never viewed
  - opened: You've viewed it, not yet resolved
  - closed: Resolved (replied or dismissed), auto-archived

USAGE:
  drone @ai_mail <command> [args]
  drone @ai_mail --help

EXAMPLES:
  # Check mail
  drone @ai_mail inbox                        # List all emails
  drone @ai_mail view abc123                  # View email (marks as opened)

  # Resolve emails
  drone @ai_mail reply abc123 "Thanks!"       # Reply + close + archive
  drone @ai_mail close abc123                 # Close single email
  drone @ai_mail close abc123 def456 ghi789   # Close multiple emails
  drone @ai_mail close all                    # Close ALL emails

  # Send mail
  drone @ai_mail send @seed "Subject" "Msg"   # Send to branch
  drone @ai_mail send @all "Subject" "Msg"    # Broadcast to all
        """
    )
    console.print(parser.format_help())


# =============================================================================
# INTROSPECTION DISPLAY
# =============================================================================

def print_introspection():
    """Display discovered modules only (SEED pattern)"""
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
        module_name = module.__name__.split('.')[-1]
        console.print(f"  [cyan]•[/cyan] {module_name}")

    console.print()
    console.print("[dim]Run 'python3 ai_mail.py --help' for usage information[/dim]")
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
            if hasattr(module, 'handle_command'):
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
    """Main entry point - routes commands to modules"""

    # Parse arguments
    args = sys.argv[1:]

    # Show introspection when run without arguments
    if len(args) == 0:
        print_introspection()
        return 0

    # Show version
    if args[0] in ['--version', '-V']:
        console.print("AI_MAIL v1.0.0")
        return 0

    # Show help for explicit help flags
    if args[0] in ['--help', '-h', 'help']:
        print_help()
        return 0

    # Command provided - try to route to modules
    modules = discover_modules()
    command = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    if not modules:
        console.print("❌ ERROR: No modules found")
        return 1

    # Route command
    if route_command(command, remaining_args, modules):
        return 0
    else:
        console.print(f"❌ ERROR: Unknown command: {command}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
