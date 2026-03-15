# =================== AIPass ====================
# Name: drone.py
# Description: Drone - Command Router & Discovery
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-08
# =============================================

"""
Drone - Command Router & Discovery for AIPass

Routes commands to registered branches and internal modules.
Standard branch entry point (apps/drone.py pattern).
"""

import sys
from typing import List

from aipass.prax import logger
from aipass.cli.apps.modules import console, err_console
from aipass.drone.apps.modules import BranchNotFoundError, CommandExecutionError, RegistryError
from aipass.drone.apps.modules.discovery import get_help
from aipass.drone.apps.modules.resolver import list_branches
from aipass.drone.apps.modules.router import route_command
from aipass.drone.apps.modules.module_registry import (
    is_module,
    list_modules,
    get_module_info,
    get_module_introspective,
    route_module_command,
    get_module_help,
)

VERSION = "1.0.0"


# =============================================================================
# HELP & INTROSPECTION
# =============================================================================

def show_help() -> None:
    """Display drone help."""
    console.print()
    console.print("Drone - Command Router & Discovery")
    console.print()
    console.print("Routes commands to AIPass branches and internal modules.")
    console.print()
    console.print("Usage:")
    console.print("  drone @target command \\[args]   Route command to branch or module")
    console.print("  drone @target --help           Show help for branch or module")
    console.print("  drone systems                  List registered branches and modules")
    console.print("  drone --help                   Show this help")
    console.print("  drone --version                Show version")
    console.print()
    console.print("Examples:")
    console.print("  drone @seedgo audit aipass")
    console.print("  drone @seedgo list")
    console.print("  drone @flow status")
    console.print("  drone systems")
    console.print()


def print_help() -> None:
    """Alias for seedgo standard compliance (audit expects print_help)."""
    show_help()


def print_introspection() -> None:
    """Alias for seedgo standard compliance (audit expects print_introspection)."""
    show_introspection()


def show_introspection() -> None:
    """Show discovery view (no args)."""
    console.print()
    console.print("Drone - Command Router & Discovery")
    console.print()

    modules = list_modules()
    branches = list_branches()

    if modules:
        console.print(f"Internal Modules ({len(modules)}):")
        for name in modules:
            info = get_module_info(name)
            if info:
                console.print(f"  @{name:<18} {info.description}")
            else:
                console.print(f"  @{name:<18} (not available)")
        if branches:
            console.print()

    if branches:
        console.print(f"Registered Branches ({len(branches)}):")
        for name in sorted(branches):
            console.print(f"  {name}")

    if not modules and not branches:
        console.print("No branches or modules registered.")

    console.print()
    console.print("Run 'drone --help' for usage information")
    console.print()


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def _handle_systems() -> int:
    """Handle `drone systems` — list registered branches and modules."""
    branches = list_branches()
    modules = list_modules()

    if not branches and not modules:
        console.print("No branches or modules registered.")
        return 0

    if modules:
        console.print(f"Modules ({len(modules)}):")
        for name in modules:
            info = get_module_info(name)
            if info:
                console.print(f"  @{name:<18} {info.description}")
            else:
                console.print(f"  @{name:<18} (not available)")
        if branches:
            console.print()

    if branches:
        console.print(f"Branches ({len(branches)}):")
        for name in sorted(branches):
            console.print(f"  {name}")

    return 0


def _handle_module(name: str, args: List[str]) -> int:
    """Handle routing to an internal module."""
    if not args:
        intro_text = get_module_introspective(name)
        if intro_text:
            console.print(intro_text, end="")
        else:
            console.print(f"No information available for @{name}.")
        return 0

    if args == ["--help"]:
        help_text = get_module_help(name)
        if help_text:
            console.print(help_text, end="")
        else:
            console.print(f"No help available for @{name}.")
        return 0

    command = args[0]
    cmd_args = args[1:] if len(args) > 1 else None

    try:
        result = route_module_command(name, command, cmd_args)
    except (ImportError, AttributeError) as exc:
        err_console.print(f"drone: module @{name} is registered but not available: {exc}")
        return 1

    if result.get("stdout"):
        print(result["stdout"], end="")
    if result.get("stderr"):
        print(result["stderr"], end="", file=sys.stderr)
    return result.get("exit_code", 0)


def _handle_target(args: List[str]) -> int:
    """Handle `drone @target command [args]` or `drone @target --help`."""
    target = args[0]
    rest = args[1:]
    module_name = target.lstrip("@").lower()

    # Check if this is a registered internal module
    if is_module(module_name):
        return _handle_module(module_name, rest)

    # No args = pass through to branch (introspection)
    if not rest:
        try:
            result = route_command(target)
        except (BranchNotFoundError, CommandExecutionError, RegistryError) as exc:
            err_console.print(f"drone: {exc}")
            return 1
        if result.stdout:
            console.print(result.stdout, end="", highlight=False)
        if result.stderr:
            err_console.print(result.stderr, end="", highlight=False)
        return result.exit_code

    # --help = show help
    if rest == ["--help"]:
        try:
            result = get_help(target)
            if result.text:
                console.print(result.text, end="", highlight=False)
            else:
                console.print(f"No help available for {target}.")
        except (BranchNotFoundError, CommandExecutionError, RegistryError) as exc:
            err_console.print(f"drone: {exc}")
            return 1
        return 0

    # drone @branch command [args...]
    command = rest[0]
    cmd_args = rest[1:]

    # Long-running interactive commands bypass capture + timeout
    interactive = command in ("monitor", "snapshot", "versioned")

    try:
        result = route_command(
            target, command,
            args=cmd_args if cmd_args else None,
            interactive=interactive,
        )
    except (BranchNotFoundError, CommandExecutionError, RegistryError) as exc:
        err_console.print(f"drone: {exc}")
        return 1

    if result.stdout:
        console.print(result.stdout, end="", highlight=False)
    if result.stderr:
        err_console.print(result.stderr, end="", highlight=False)
    return result.exit_code


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main() -> int:
    """Main entry point - routes commands or shows help."""
    args = sys.argv[1:]

    # No args -> introspection
    if not args:
        try:
            show_introspection()
        except RegistryError as exc:
            err_console.print(f"drone: {exc}")
            return 1
        return 0

    # --version
    if args[0] in ["--version", "-V"]:
        console.print(f"drone v{VERSION}")
        return 0

    # --help
    if args[0] in ["--help", "-h", "help"]:
        show_help()
        return 0

    command = args[0]

    # systems — list branches and modules
    if command == "systems":
        try:
            return _handle_systems()
        except RegistryError as exc:
            err_console.print(f"drone: {exc}")
            return 1

    # @target — route to branch or module
    if command.startswith("@"):
        return _handle_target(args)

    # Unknown command
    err_console.print(f"drone: unknown command '{command}'")
    err_console.print("Run 'drone --help' for usage.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
