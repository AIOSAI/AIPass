# =================== AIPass ====================
# Name: drone.py
# Description: Drone - Command Router & Discovery
# Version: 1.1.0
# Created: 2026-03-05
# Modified: 2026-03-17
# =============================================

"""
Drone - Command Router & Discovery for AIPass

Routes commands to registered branches and internal modules.
Standard branch entry point (apps/drone.py pattern).
"""

import importlib
import sys
from pathlib import Path
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

VERSION = "1.1.0"
MODULES_DIR = Path(__file__).parent / "modules"


# =============================================================================
# AUTO-DISCOVERY
# =============================================================================

def _discover_modules() -> list[tuple[str, str]]:
    """Auto-discover modules in apps/modules/ with handle_command()."""
    discovered = []
    for file_path in sorted(MODULES_DIR.glob("*.py")):
        if file_path.name.startswith("_"):
            continue
        module_name = file_path.stem
        try:
            module = importlib.import_module(
                f"aipass.drone.apps.modules.{module_name}"
            )
            if hasattr(module, "handle_command"):
                doc = (module.__doc__ or "").strip().split("\n")[0]
                discovered.append((module_name, doc))
        except Exception as exc:
            logger.warning("Failed to discover module %s: %s", module_name, exc)
    return discovered


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
    console.print("  drone scan @target             Discover available commands in a branch")
    console.print("  drone activate @target         Register all commands from a branch")
    console.print("  drone list                     List registered custom commands")
    console.print("  drone remove <name>            Remove a custom command")
    console.print("  drone --help                   Show this help")
    console.print("  drone --version                Show version")
    console.print()
    console.print("Examples:")
    console.print("  drone @seedgo audit aipass")
    console.print("  drone @seedgo list")
    console.print("  drone @flow status")
    console.print("  drone systems")
    console.print("  drone activate @seedgo")
    console.print("  drone audit                    (custom command shortcut)")
    console.print()


def print_help() -> None:
    """Alias for seedgo standard compliance (audit expects print_help)."""
    show_help()


def print_introspection() -> None:
    """Alias for seedgo standard compliance (audit expects print_introspection)."""
    show_introspection()


def show_introspection() -> None:
    """Show discovery view (no args) — auto-discovers modules."""
    console.print()
    console.print("[bold cyan]Drone - Command Router & Discovery[/bold cyan]")
    console.print()
    console.print("[dim]Routes commands to AIPass branches and internal modules[/dim]")
    console.print()

    modules = _discover_modules()

    console.print(f"[yellow]Discovered Modules:[/yellow] {len(modules)}")
    console.print()
    for name, description in modules:
        if description:
            console.print(f"  [cyan]•[/cyan] {name:<20} [dim]{description}[/dim]")
        else:
            console.print(f"  [cyan]•[/cyan] {name}")

    console.print()
    console.print("Run [green]'drone @drone --help'[/green] for usage information")
    console.print()


# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def _cwd_has_registry() -> bool:
    """Check if CWD is within a project that has a *_REGISTRY.json."""
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if list(parent.glob("*_REGISTRY.json")):
            return True
    return False


def _handle_systems() -> int:
    """Handle `drone systems` — list registered branches and modules."""
    if not _cwd_has_registry():
        console.print("No registry found in current directory tree.")
        return 0

    branches = list_branches()
    modules = list_modules()

    # Infrastructure section — drone is the router, not a routable module
    console.print("Infrastructure:")
    console.print(f"  @{'drone':<18} Command routing and module discovery (v{VERSION})")
    console.print()

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
        logger.error("Module @%s not available: %s", name, exc)
        err_console.print(f"drone: module @{name} is registered but not available: {exc}")
        return 1

    if result.get("stdout"):
        console.print(result["stdout"], end="", highlight=False)
    if result.get("stderr"):
        err_console.print(result["stderr"], end="", highlight=False)
    return result.get("exit_code", 0)


def _handle_activate(target: str) -> int:
    """Handle `drone activate @branch` -- scan and register all discovered commands."""
    from aipass.drone.apps.modules.scan import scan
    from aipass.drone.apps.modules.commands import add
    from aipass.drone.apps.modules.commands import format_activation_results

    branch_name = target.lstrip("@").lower()

    results = scan(target)
    if results is None:
        err_console.print(f"drone: could not resolve '{target}'")
        return 1

    if not results:
        return 0

    added: list[str] = []
    skipped: list[str] = []

    for cmd in results:
        name = cmd["name"]
        description = cmd.get("description", "")
        success = add(
            name=name,
            target=f"@{branch_name}",
            command=name,
            description=description,
            source_branch=branch_name,
        )
        if success:
            added.append(name)
        else:
            skipped.append(name)

    format_activation_results(branch_name, added, skipped)
    return 0


def _handle_list() -> int:
    """Handle `drone list` -- show all registered custom commands."""
    from aipass.drone.apps.modules.commands import list_all
    from aipass.drone.apps.modules.commands import format_command_list

    commands = list_all()
    format_command_list(commands)
    return 0


def _handle_remove(name: str) -> int:
    """Handle `drone remove <name>` -- remove a custom command."""
    from aipass.drone.apps.modules.commands import remove
    from aipass.drone.apps.modules.commands import format_removal

    success = remove(name)
    format_removal(name, success)
    return 0 if success else 1


def _handle_custom_command(args: list[str]) -> int:
    """Handle a custom command shortcut by matching and routing.

    Uses greedy multi-word matching to resolve user input to a registered
    custom command, then routes through the same path as ``@target`` commands.
    """
    from aipass.drone.apps.modules.commands import match

    matched = match(args)
    if matched is None:
        return -1  # Signal: not a custom command

    cmd_data, remaining_args = matched
    target = cmd_data["target"]
    command = cmd_data["command"]
    cmd_args = list(cmd_data.get("args", [])) + remaining_args
    module_name = target.lstrip("@").lower()

    # Interactive detection -- same logic as _handle_target
    interactive_commands = ("monitor", "audit")
    interactive_branches = ("cli", "backup")
    interactive = command in interactive_commands or module_name in interactive_branches

    try:
        result = route_command(
            target, command,
            args=cmd_args if cmd_args else None,
            interactive=interactive,
        )
    except (BranchNotFoundError, CommandExecutionError, RegistryError) as exc:
        logger.warning("Custom command failed for target %s: %s", target, exc)
        err_console.print(f"drone: {exc}")
        return 1

    if result.stdout:
        console.print(result.stdout, end="", highlight=False)
    if result.stderr:
        err_console.print(result.stderr, end="", highlight=False)
    return result.exit_code


def _handle_target(args: List[str]) -> int:
    """Handle `drone @target command [args]` or `drone @target --help`."""
    target = args[0]
    rest = args[1:]
    module_name = target.lstrip("@").lower()

    # Interactive mode bypasses capture + timeout for human-facing output.
    # Per-command: specific commands that need live terminal (progress bars, TUI).
    # Per-branch: all commands from that branch get interactive mode (Rich CLI).
    interactive_commands = ("monitor", "audit")
    interactive_branches = ("cli", "backup")
    first_cmd = rest[0] if rest and rest[0] != "--help" else None
    needs_interactive = (
        first_cmd in interactive_commands or module_name in interactive_branches
    )

    # Route to internal module — unless command needs interactive terminal,
    # in which case fall through to branch (subprocess) routing so Rich
    # Progress / TUI output renders live instead of being buffered.
    if is_module(module_name) and not needs_interactive:
        return _handle_module(module_name, rest)

    # No args = pass through to branch (introspection)
    if not rest:
        try:
            result = route_command(target)
        except (BranchNotFoundError, CommandExecutionError, RegistryError) as exc:
            logger.warning("Introspection failed for %s: %s", target, exc)
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
            logger.warning("Help lookup failed for %s: %s", target, exc)
            err_console.print(f"drone: {exc}")
            return 1
        return 0

    # drone @branch command [args...]
    command = rest[0]
    cmd_args = rest[1:]

    # needs_interactive already computed above
    interactive = needs_interactive

    try:
        result = route_command(
            target, command,
            args=cmd_args if cmd_args else None,
            interactive=interactive,
        )
    except (BranchNotFoundError, CommandExecutionError, RegistryError) as exc:
        logger.warning("Command routing failed for %s %s: %s", target, command, exc)
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
            print_introspection()
        except RegistryError as exc:
            logger.warning("Registry error during introspection: %s", exc)
            err_console.print(f"drone: {exc}")
            return 1
        return 0

    # --version
    if args[0] in ["--version", "-V"]:
        console.print(f"drone v{VERSION}")
        return 0

    # --help
    if args[0] in ["--help", "-h", "help"]:
        print_help()
        return 0

    command = args[0]

    # systems — list branches and modules
    if command == "systems":
        try:
            return _handle_systems()
        except RegistryError as exc:
            logger.warning("Registry error during systems listing: %s", exc)
            err_console.print(f"drone: {exc}")
            return 1

    # scan — discover available commands in a branch
    if command == "scan":
        if len(args) < 2:
            err_console.print("drone: scan requires a target (e.g., drone scan @seedgo)")
            return 1
        from aipass.drone.apps.modules.scan import scan
        results = scan(args[1])
        return 0 if results is not None else 1

    # activate — scan + register all discovered commands from a branch
    if command == "activate":
        if len(args) < 2:
            err_console.print("drone: activate requires a target (e.g., drone activate @seedgo)")
            return 1
        return _handle_activate(args[1])

    # list — show registered custom commands
    if command == "list":
        return _handle_list()

    # remove — remove a custom command by name
    if command == "remove":
        if len(args) < 2:
            err_console.print("drone: remove requires a command name (e.g., drone remove audit)")
            return 1
        return _handle_remove(args[1])

    # @target — route to branch or module
    if command.startswith("@"):
        return _handle_target(args)

    # Module routing — discovered modules are routable as bare commands
    # e.g. `drone commands list` or `drone @drone commands list` (via subprocess)
    discovered = _discover_modules()
    module_names = [m[0] for m in discovered]
    if command in module_names:
        remaining = args[1:]
        cmd = remaining[0] if remaining else None
        cmd_args = remaining[1:] if len(remaining) > 1 else None
        try:
            mod = importlib.import_module(f"aipass.drone.apps.modules.{command}")
            result = mod.handle_command(cmd, cmd_args)
        except Exception as exc:
            logger.error("Module %s failed: %s", command, exc)
            err_console.print(f"drone: module '{command}' error: {exc}")
            return 1
        if isinstance(result, dict):
            if result.get("stdout"):
                console.print(result["stdout"], end="", highlight=False)
            if result.get("stderr"):
                err_console.print(result["stderr"], end="", highlight=False)
            return result.get("exit_code", 0)
        return 0 if result else 1

    # Custom command matching (greedy multi-word, before unknown error)
    custom_result = _handle_custom_command(args)
    if custom_result != -1:
        return custom_result

    # Unknown command — check if it's a bare branch name missing @
    try:
        from aipass.drone.apps.modules.resolver import branch_exists
        if branch_exists(command):
            err_console.print(
                f"drone: branch references require @ prefix. "
                f"Use '@{command}' instead of '{command}'."
            )
            return 1
    except Exception as exc:
        logger.warning("Branch existence check failed for '%s': %s", command, exc)

    err_console.print(f"drone: unknown command '{command}'")
    err_console.print("Run 'drone --help' for usage.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
