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
import os
import sys
from pathlib import Path
from typing import List

from rich.table import Table
from rich.text import Text

from aipass.prax import logger
from aipass.cli.apps.modules import console, err_console
from aipass.drone.apps.modules import BranchNotFoundError, CommandExecutionError, RegistryError
from aipass.drone.apps.modules.discovery import get_help
from aipass.drone.apps.modules.resolver import get_all_branches
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

# Interactive mode — commands/branches that bypass capture + timeout for live terminal output.
INTERACTIVE_COMMANDS = ("monitor", "audit", "watchdog")
INTERACTIVE_BRANCHES = ("cli",)


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
            module = importlib.import_module(f"aipass.drone.apps.modules.{module_name}")
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
    """Display drone help with Rich formatting."""
    table = Table(show_header=False, box=None, pad_edge=False, show_edge=False)
    table.add_column(style="cyan", no_wrap=True)
    table.add_column(style="dim")

    table.add_row("@target command [args]", "Route command to branch or module")
    table.add_row("@target --help", "Show help for branch or module")
    table.add_row("systems", "List registered branches and modules")
    table.add_row("scan @target", "Discover available commands in a branch")
    table.add_row("activate @target", "Register all commands from a branch")
    table.add_row("list", "List registered custom commands")
    table.add_row("remove <name>", "Remove a custom command")
    table.add_row("hook-sounds on|off", "Toggle hook notification sounds")
    table.add_row("--help", "Show this help")
    table.add_row("--version", "Show version")

    console.print()
    console.print(f"[bold cyan]Drone[/bold cyan] [dim]v{VERSION}[/dim] — Command Router & Discovery")
    console.print()
    console.print("[dim]Routes commands to registered AIPass branches and modules.[/dim]")
    console.print()
    console.print(table)
    console.print()
    console.print("[bold]Examples:[/bold]")
    console.print("  [green]drone @seedgo audit aipass[/green]")
    console.print("  [green]drone @flow status[/green]")
    console.print("  [green]drone systems[/green]")
    console.print("  [green]drone activate @seedgo[/green]")
    console.print("  [green]drone audit[/green]  [dim](custom shortcut)[/dim]")
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


def _cwd_has_registry(max_depth: int = 10) -> bool:
    """Check if CWD is within a project that has a *_REGISTRY.json."""
    cwd = Path.cwd()
    for i, parent in enumerate([cwd] + list(cwd.parents)):
        if i >= max_depth:
            break
        if list(parent.glob("*_REGISTRY.json")):
            return True
    # AIPASS_HOME fallback — for external projects / global drone usage
    aipass_home = os.environ.get("AIPASS_HOME")
    if aipass_home:
        home = Path(aipass_home)
        if home.is_dir() and list(home.glob("*_REGISTRY.json")):
            return True
    return False


def _handle_systems() -> int:
    """Handle `drone systems` — list registered branches and modules."""
    if not _cwd_has_registry():
        console.print("No registry found in current directory tree.")
        return 0

    all_branches = get_all_branches()
    modules = list_modules()

    # Split registry branches into services (profile=library) and project branches
    services = [b for b in all_branches if b.get("profile") == "library"]
    project_branches = [b for b in all_branches if b.get("profile") != "library"]

    # Infrastructure section — drone is the router, not a routable module
    console.print("Infrastructure:")
    console.print(f"  @{'drone':<18} Command routing and module discovery (v{VERSION})")
    console.print()

    # AIPass Services — internal modules + registry services (deduplicated)
    # Exclude registry services that duplicate internal modules or drone itself
    exclude = set(modules) | {"drone"}
    deduped_services = [s for s in services if s.get("name", "").lower() not in exclude]
    service_count = len(modules) + len(deduped_services)
    if service_count:
        console.print(f"AIPass Services ({service_count}):")
        for name in modules:
            info = get_module_info(name)
            if info:
                console.print(f"  @{name:<18} {info.description}")
            else:
                console.print(f"  @{name:<18} (not available)")
        for svc in sorted(deduped_services, key=lambda b: b.get("name", "").lower()):
            name = svc.get("name", "").lower()
            desc = svc.get("description", "")
            console.print(f"  @{name:<18} {desc}")
        if project_branches:
            console.print()

    if project_branches:
        console.print(f"Branches ({len(project_branches)}):")
        for branch in sorted(project_branches, key=lambda b: b.get("name", "").lower()):
            console.print(f"  @{branch.get('name', '').lower()}")

    # Hint for external projects missing AIPass core branches.
    # If AIPASS_HOME is not set AND 'drone' isn't among the local branches,
    # we're in an external project that can't see the core branch set.
    if not os.environ.get("AIPASS_HOME"):
        branch_names = {b.get("name", "").lower() for b in all_branches}
        if "drone" not in branch_names:
            console.print()
            console.print("[dim]Only local registry found. To access AIPass core branches:[/dim]")
            console.print("[dim]  export AIPASS_HOME=/path/to/AIPass[/dim]")

    return 0


def _handle_module(name: str, args: List[str]) -> int:
    """Handle routing to an internal module."""
    if not args:
        intro_text = get_module_introspective(name)
        if intro_text:
            # Text.from_ansi handles both pre-formatted ANSI (external modules)
            # and plain text (internal modules) correctly
            console.print(Text.from_ansi(intro_text), end="")
        else:
            console.print(f"No information available for @{name}.")
        return 0

    if args == ["--help"]:
        help_text = get_module_help(name)
        if help_text:
            console.print(Text.from_ansi(help_text), end="")
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

    interactive = command in INTERACTIVE_COMMANDS or module_name in INTERACTIVE_BRANCHES

    try:
        result = route_command(
            target,
            command,
            args=cmd_args if cmd_args else None,
            interactive=interactive,
        )
    except (BranchNotFoundError, CommandExecutionError, RegistryError) as exc:
        if isinstance(exc, BranchNotFoundError) and is_module(module_name):
            logger.info(
                "Falling back to module routing for custom command @%s %s (not in local registry)", module_name, command
            )
            return _handle_module(module_name, [command] + cmd_args)
        logger.warning("Custom command failed for target %s: %s", target, exc)
        err_console.print(f"drone: {exc}")
        if isinstance(exc, BranchNotFoundError) and not os.environ.get("AIPASS_HOME"):
            err_console.print("  Tip: set AIPASS_HOME=/path/to/AIPass to access core branches.")
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

    first_cmd = rest[0] if rest and rest[0] != "--help" else None
    needs_interactive = first_cmd in INTERACTIVE_COMMANDS or module_name in INTERACTIVE_BRANCHES

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
            if isinstance(exc, BranchNotFoundError) and is_module(module_name):
                logger.info("Falling back to module routing for @%s (not in local registry)", module_name)
                return _handle_module(module_name, rest)
            logger.warning("Introspection failed for %s: %s", target, exc)
            err_console.print(f"drone: {exc}")
            if isinstance(exc, BranchNotFoundError) and not os.environ.get("AIPASS_HOME"):
                err_console.print("  Tip: set AIPASS_HOME=/path/to/AIPass to access core branches.")
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
            if isinstance(exc, BranchNotFoundError) and is_module(module_name):
                logger.info("Falling back to module routing for @%s --help (not in local registry)", module_name)
                return _handle_module(module_name, rest)
            logger.warning("Help lookup failed for %s: %s", target, exc)
            err_console.print(f"drone: {exc}")
            if isinstance(exc, BranchNotFoundError) and not os.environ.get("AIPASS_HOME"):
                err_console.print("  Tip: set AIPASS_HOME=/path/to/AIPass to access core branches.")
            return 1
        return 0

    # drone @branch command [args...]
    command = rest[0]
    cmd_args = rest[1:]

    # needs_interactive already computed above
    interactive = needs_interactive

    try:
        result = route_command(
            target,
            command,
            args=cmd_args if cmd_args else None,
            interactive=interactive,
        )
    except (BranchNotFoundError, CommandExecutionError, RegistryError) as exc:
        if isinstance(exc, BranchNotFoundError) and is_module(module_name):
            logger.info("Falling back to module routing for @%s %s (not in local registry)", module_name, command)
            return _handle_module(module_name, rest)
        logger.warning("Command routing failed for %s %s: %s", target, command, exc)
        err_console.print(f"drone: {exc}")
        if isinstance(exc, BranchNotFoundError) and not os.environ.get("AIPASS_HOME"):
            err_console.print("  Tip: set AIPASS_HOME=/path/to/AIPass to access core branches.")
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
        except Exception as exc:
            logger.error("[drone] Unhandled error in systems: %s", exc)
            err_console.print(f"drone: unexpected error: {exc}")
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
        if len(args) < 2 or args[1] in ("--help", "-h"):
            console.print("Usage: drone activate @branch")
            console.print()
            console.print("Scan a branch for available commands and register them as shortcuts.")
            console.print("Example: drone activate @seedgo")
            return 0
        return _handle_activate(args[1])

    # list — show registered custom commands
    if command == "list":
        return _handle_list()

    # hook-sounds — toggle hook notification sounds
    if command == "hook-sounds":
        from aipass.drone.apps.plugins.hook_sounds.hook_sounds_plugin import handle_command as hs_handle

        cmd = args[1] if len(args) > 1 else None
        hs_handle(cmd)
        return 0

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
    #
    # The @ prefix is a hard contract: it's our routing convention and cannot be
    # silently auto-inferred. Bare `drone prax` must error — any relaxation makes
    # typos route to branches and hides bugs.
    #
    # Windows caveat: PowerShell treats `@` as a splatting operator, so
    # `drone @prax` reaches drone as `drone prax` — the @ is consumed before we
    # ever see it. This is NOT fixed here. It is fixed via a PowerShell profile
    # wrapper (setup.sh writes it for Windows users) that uses $MyInvocation.Line
    # to reconstruct the original command string with @ intact. See issue #340.
    # Git Bash on Windows is fine — it passes @ through like Linux.
    try:
        from aipass.drone.apps.modules.resolver import branch_exists

        if branch_exists(command):
            err_console.print(f"drone: branch references require @ prefix. Use '@{command}' instead of '{command}'.")
            return 1
    except Exception as exc:
        logger.warning("Branch existence check failed for '%s': %s", command, exc)

    err_console.print(f"drone: unknown command '{command}'")
    err_console.print("Run 'drone --help' for usage.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
