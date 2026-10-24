# =================== AIPass ====================
# Name: drone.py
# Description: Drone - Command Router & Discovery
# Version: 1.3.1
# Created: 2026-03-05
# Modified: 2026-10-24
# =============================================

"""
Drone - Command Router & Discovery for AIPass
"""

import functools
import importlib
import os
import sys
from pathlib import Path
from typing import Callable, List

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from rich.table import Table
from rich.text import Text

from aipass.prax import logger
from aipass.cli.apps.modules import console, err_console
from aipass.drone.apps.modules import BranchNotFoundError, CommandExecutionError, RegistryError
from aipass.drone.apps.modules.resolver import branch_exists, get_all_branches
from aipass.drone.apps.modules.router import caller_cwd, registries_in, route_command
from aipass.drone.apps.modules.module_registry import (
    is_module,
    list_modules,
    get_module_info,
    get_module_introspective,
    route_module_command,
    get_module_help,
)
from aipass.drone.apps.modules.config import missing_home_tip, passport_fault, resolve_aipass_home

VERSION = "1.1.0"
MODULES_DIR = Path(__file__).parent / "modules"

# Interactive mode — commands/branches that bypass capture + timeout for live terminal output.
INTERACTIVE_COMMANDS = ("monitor", "audit", "watchdog", "status")
INTERACTIVE_BRANCHES = ("cli", "backup")


def _reports_passport_fault(route: Callable[[], int]) -> Callable[[], int]:
    """Wrap main() so that, after routing, a passport fault is said once on stderr.

    The exit code is the route's own; a passport fault never changes it.
    sys.stderr.write, not Rich: the line is one fact and must not wrap when piped.
    """

    @functools.wraps(route)
    def routed() -> int:
        """Run the route, say the passport fault if one was recorded, return the route's code."""
        code = route()
        fault = passport_fault()
        if fault is not None:
            sys.stderr.write(fault + "\n")
        return code

    return routed


def _extract_timeout(args: list[str]) -> tuple[list[str], int | None]:
    """Extract --drone-timeout N from an arg list. Returns (cleaned_args, timeout_or_None)."""
    if "--drone-timeout" not in args:
        return args, None
    idx = args.index("--drone-timeout")
    if idx + 1 >= len(args):
        return args, None
    try:
        timeout = int(args[idx + 1])
    except ValueError:
        logger.info("--drone-timeout value %r is not an integer, ignoring", args[idx + 1])
        return args, None
    if timeout <= 0:
        logger.info("--drone-timeout value %r is not positive, ignoring", args[idx + 1])
        return args, None
    return args[:idx] + args[idx + 2 :], timeout


def _report_inert_timeout(explicit_timeout: int | None, reason: str) -> None:
    """Say so when an accepted ``--drone-timeout`` cannot be applied.

    Module routing (in-process) and interactive commands take no timeout; a silently dropped
    cap is a defect, so warn. A warning, not an error: the command still runs, unbounded.
    """
    if explicit_timeout is None:
        return
    message = f"--drone-timeout {explicit_timeout} not applied — {reason}"
    logger.warning("%s", message)
    err_console.print(f"drone: {message}")


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


def print_help() -> None:
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
    table.add_row(
        "rm [--stale AGE] <path>...",
        "Contained safe-delete; --stale sweeps old *_json temps (drone rm --help)",
    )
    table.add_row(
        "@target ... --drone-timeout <n>",
        "Override subprocess timeout, default 600s (must come AFTER @target)",
    )
    table.add_row("--help", "Show this help")
    table.add_row("--version", "Show version")

    console.print()
    console.print(f"[bold cyan]Drone[/bold cyan] [dim]v{VERSION}[/dim] — Command Router & Discovery")
    console.print()
    console.print("[dim]Routes commands to registered AIPass branches and modules.[/dim]")
    console.print()
    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()
    console.print("  [dim]drone @<target> <command> \\[args...][/dim]")
    console.print("  [dim]drone <built-in> \\[args...][/dim]")
    console.print("  [dim]drone --help[/dim]")
    console.print()
    console.print(table)
    console.print()
    console.print("[bold cyan]EXAMPLES:[/bold cyan]")
    console.print()
    console.print("  [green]drone @seedgo audit aipass[/green]")
    console.print("  [green]drone @flow status[/green]")
    console.print("  [green]drone systems[/green]")
    console.print()


def print_introspection() -> None:
    """Display branch overview — auto-discovers modules."""
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


def _print_home_tip(exc: Exception) -> None:
    """Under "Branch not found", say what was tried — only when no AIPass home resolved."""
    if not isinstance(exc, BranchNotFoundError):
        return
    tip = missing_home_tip()
    if tip:
        err_console.print(tip, markup=False, highlight=False, soft_wrap=True)


def _cwd_has_registry(max_depth: int = 10) -> bool:
    """Check if CWD is within a project that has a *_REGISTRY.json.

    A caller whose directory was deleted has no CWD to be "within", so the walk
    is skipped and the AIPass home — which never needed a location — still answers.
    """
    # ``caller_cwd`` is the single CWD reader; do not add a private try/except copy here.
    cwd = caller_cwd()
    if cwd is not None:
        for i, parent in enumerate([cwd] + list(cwd.parents)):
            if i >= max_depth:
                break
            if registries_in(parent):
                return True
    home = resolve_aipass_home().path
    return home is not None and home.is_dir() and bool(registries_in(home))


def _handle_systems() -> int:
    """Handle `drone systems` — list registered branches and modules."""
    if not _cwd_has_registry():
        console.print("No registry found in current directory tree.")
        return 0

    all_branches = get_all_branches()
    modules = list_modules()

    services = [b for b in all_branches if b.get("profile") == "library"]
    project_branches = [b for b in all_branches if b.get("profile") != "library"]

    console.print("Infrastructure:")
    console.print(f"  @{'drone':<18} Command routing and module discovery (v{VERSION})")
    console.print()

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

    # No AIPass home and no local 'drone': an external project that cannot see the core branches.
    if resolve_aipass_home().path is None:
        branch_names = {b.get("name", "").lower() for b in all_branches}
        if "drone" not in branch_names:
            console.print()
            console.print("[dim]Only local registry found. To access AIPass core branches:[/dim]")
            console.print("[dim]  export AIPASS_HOME=/path/to/AIPass[/dim]")

    # A lost routing_config.json empties the external modules; the list above is
    # partial, so say so where the caller is. Exit stays 0, as for scan.
    from aipass.drone.apps.modules.module_registry import external_modules_error

    error = external_modules_error()
    if error:
        err_console.print(f"drone: external modules could not load: {error}", markup=False)

    return 0


def _module_unavailable(name: str, why: str) -> int:
    """Name a registered module that cannot run, on stderr; the exit code is 1."""
    err_console.print(f"drone: module @{name} is registered but not available: {why}")
    return 1


def _handle_module(name: str, args: List[str]) -> int:
    """Handle routing to an internal module."""
    if not args:
        intro_text = get_module_introspective(name)
        if intro_text is None:
            # None is the handler's "the adapter could not load"; "" is a quiet module.
            return _module_unavailable(name, "it could not load (see drone log)")
        if intro_text:
            console.print(Text.from_ansi(intro_text), end="")
        else:
            console.print(f"No information available for @{name}.")
        return 0

    if args == ["--help"]:
        help_text = get_module_help(name)
        if help_text is None:
            return _module_unavailable(name, "it could not load (see drone log)")
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
        return _module_unavailable(name, str(exc))

    if result.get("stdout"):
        sys.stdout.write(result["stdout"])
    if result.get("stderr"):
        sys.stderr.write(result["stderr"])
    return result.get("exit_code", 0)


def _registry_unloadable(exc: Exception) -> int:
    """Name a command registry that cannot load, on stderr; the exit code is 1."""
    logger.error("[drone] command registry could not load: %s", exc)
    err_console.print(f"drone: command registry could not load: {exc}")
    return 1


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
        try:
            success = add(
                name=name,
                target=f"@{branch_name}",
                command=name,
                description=description,
                source_branch=branch_name,
            )
        except RegistryError as exc:
            return _registry_unloadable(exc)
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

    try:
        commands = list_all()
    except RegistryError as exc:
        return _registry_unloadable(exc)
    format_command_list(commands)
    return 0


def _handle_remove(name: str) -> int:
    """Handle `drone remove <name>` -- remove a custom command."""
    from aipass.drone.apps.modules.commands import remove
    from aipass.drone.apps.modules.commands import format_removal

    try:
        success = remove(name)
    except RegistryError as exc:
        return _registry_unloadable(exc)
    format_removal(name, success)
    return 0 if success else 1


def _handle_rm(args: list[str]) -> int:
    """Handle ``drone rm <path> [<path>...]`` — contained safe-delete."""
    from aipass.drone.apps.modules.rm import handle_command, print_help

    if not args or args[0] in ("--help", "-h"):
        print_help()
        return 0

    result = handle_command(args[0], args[1:] if len(args) > 1 else None)
    return 0 if result else 1


def _handle_custom_command(args: list[str]) -> int:
    """Handle a custom command shortcut by matching and routing."""
    from aipass.drone.apps.modules.commands import match

    # A registry that cannot load is a named failure, never "no match" and never a traceback.
    try:
        matched = match(args)
    except Exception as exc:
        return _registry_unloadable(exc)
    if matched is None:
        return -1  # Signal: not a custom command

    cmd_data, remaining_args = matched
    target = cmd_data["target"]
    command = cmd_data["command"]
    cmd_args = list(cmd_data.get("args", [])) + remaining_args
    cmd_args, explicit_timeout = _extract_timeout(cmd_args)
    module_name = target.lstrip("@").lower()

    interactive = command in INTERACTIVE_COMMANDS or module_name in INTERACTIVE_BRANCHES
    if interactive:
        _report_inert_timeout(explicit_timeout, "interactive commands inherit the terminal and are not timed")

    try:
        result = route_command(
            target,
            command,
            args=cmd_args if cmd_args else None,
            timeout=explicit_timeout,
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
        _print_home_tip(exc)
        return 1

    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.exit_code


def _read_inbox_message_id(inbox: Path, n: int) -> str | None:
    """Return the ID of the Nth message (1-based, display order) from inbox.json.

    The inbox display reverses the array (oldest first), so display position 1
    is the last element in the JSON array, not the first.
    """
    import json as _json

    try:
        data = _json.loads(inbox.read_text(encoding="utf-8"))
        messages = data.get("messages", [])
        if 1 <= n <= len(messages):
            return messages[len(messages) - n]["id"]
    except Exception as exc:
        logger.warning("Failed to resolve mail index %d: %s", n, exc)
    return None


def _read_inbox_ids(inbox: Path) -> set[str]:
    """Return every message ID present in inbox.json, or an empty set."""
    import json as _json

    try:
        data = _json.loads(inbox.read_text(encoding="utf-8"))
        return {m["id"] for m in data.get("messages", []) if "id" in m}
    except Exception as exc:
        logger.warning("Failed to read inbox IDs from %s: %s", inbox, exc)
        return set()


def _find_seat_inbox() -> Path | None:
    """Walk up from CWD to the nearest citizen seat and return its inbox.json.

    The first passport found is the only seat this caller may address, even if its inbox is absent.
    No CWD means no seat.
    """
    cwd = caller_cwd()
    if cwd is None:
        return None
    for parent in [cwd] + list(cwd.parents):
        if not (parent / ".trinity" / "passport.json").exists():
            continue
        inbox = parent / ".ai_mail.local" / "inbox.json"
        return inbox if inbox.exists() else None
    return None


def _resolve_mail_token(token: str) -> str:
    """Resolve a `view` argument to a message ID — a real ID always wins.

    ai_mail IDs are 8 hex chars; about 2.3% are all digits and look like an inbox index, so
    the ID set is consulted before the index. On any failure the ORIGINAL token is returned:
    ``str(int("08532166"))`` drops the leading zero and names an ID the user never typed.
    """
    inbox = _find_seat_inbox()

    if inbox is not None and token in _read_inbox_ids(inbox):
        return token

    if token.isdigit() and inbox is not None:
        msg_id = _read_inbox_message_id(inbox, int(token))
        if msg_id is not None:
            return msg_id

    return token


def _handle_target(args: List[str]) -> int:
    """Handle `drone @target command [args]` or `drone @target --help`."""
    target = args[0]
    rest = args[1:]
    rest, explicit_timeout = _extract_timeout(rest)
    module_name = target.lstrip("@").lower()

    first_cmd = rest[0] if rest and rest[0] not in ("--help", "-h") else None
    is_presentational = not rest or first_cmd is None
    needs_interactive = is_presentational or first_cmd in INTERACTIVE_COMMANDS or module_name in INTERACTIVE_BRANCHES

    # Interactive mode exists only for branch routing (_handle_module is in-process), so a
    # module-only target (@git) never defers to branch routing: that costs a BranchNotFoundError
    # per call. Module-and-branch names (@seedgo, @cli) needing a live terminal take the subprocess.
    if is_module(module_name) and not (needs_interactive and branch_exists(target)):
        _report_inert_timeout(explicit_timeout, "module routing runs in-process and is not timed")
        return _handle_module(module_name, rest)

    if needs_interactive:
        _report_inert_timeout(explicit_timeout, "interactive commands inherit the terminal and are not timed")

    if not rest:
        try:
            result = route_command(target, interactive=True)
        except (BranchNotFoundError, CommandExecutionError, RegistryError) as exc:
            logger.warning("Introspection failed for %s: %s", target, exc)
            err_console.print(f"drone: {exc}")
            _print_home_tip(exc)
            return 1
        return result.exit_code

    if rest in (["--help"], ["-h"]):
        try:
            result = route_command(target, rest[0], interactive=True)
        except (BranchNotFoundError, CommandExecutionError, RegistryError) as exc:
            logger.warning("Help lookup failed for %s: %s", target, exc)
            err_console.print(f"drone: {exc}")
            _print_home_tip(exc)
            return 1
        return result.exit_code

    command = rest[0]
    cmd_args = rest[1:]

    # No .isdigit() guard: an all-digit token can be a real message ID; the lookup decides.
    if module_name == "ai_mail" and command == "view" and cmd_args:
        cmd_args = [_resolve_mail_token(cmd_args[0])] + cmd_args[1:]

    interactive = needs_interactive

    try:
        result = route_command(
            target,
            command,
            args=cmd_args if cmd_args else None,
            timeout=explicit_timeout,
            interactive=interactive,
        )
    except (BranchNotFoundError, CommandExecutionError, RegistryError) as exc:
        logger.warning("Command routing failed for %s %s: %s", target, command, exc)
        err_console.print(f"drone: {exc}")
        _print_home_tip(exc)
        return 1

    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.exit_code


@_reports_passport_fault
def main() -> int:
    """Main entry point - routes commands or shows help."""
    args = sys.argv[1:]

    if not args:
        try:
            print_introspection()
        except RegistryError as exc:
            logger.warning("Registry error during introspection: %s", exc)
            err_console.print(f"drone: {exc}")
            return 1
        return 0

    if args[0] in ["--version", "-V"]:
        console.print(f"drone v{VERSION}")
        return 0

    if args[0] in ["--help", "-h", "help"]:
        print_help()
        return 0

    command = args[0]

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

    if command == "scan":
        if len(args) < 2:
            err_console.print("drone: scan requires a target (e.g., drone scan @seedgo)")
            return 1
        from aipass.drone.apps.modules.scan import scan

        results = scan(args[1])
        return 0 if results is not None else 1

    if command == "activate":
        if len(args) < 2 or args[1] in ("--help", "-h"):
            console.print("Usage: drone activate @branch")
            console.print()
            console.print("Scan a branch for available commands and register them as shortcuts.")
            console.print("Example: drone activate @seedgo")
            return 0
        return _handle_activate(args[1])

    if command == "list":
        return _handle_list()

    if command == "remove":
        if len(args) < 2:
            err_console.print("drone: remove requires a command name (e.g., drone remove audit)")
            return 1
        return _handle_remove(args[1])

    if command == "rm":
        return _handle_rm(args[1:])

    # aipass is a user-facing CLI, not a drone-routable branch
    if command.lstrip("@") == "aipass":
        err_console.print(
            "aipass isn't reachable through drone — it's your own front-door CLI,"
            " the AIPass concierge (onboarding, doctor, help, OS/system questions)."
            " drone routes the agent citizens (@git, @devpulse, @memory...);"
            " aipass is separate and serves you directly.\n"
            "\n"
            "  Use aipass:   aipass          ·  aipass --help\n"
            "  See agents:   drone systems"
        )
        return 1

    if command.startswith("@"):
        return _handle_target(args)

    # Import only the named module, not all of them: a shortcut must not pay for discovery.
    mod = None
    if not command.startswith("_") and command in {p.stem for p in MODULES_DIR.glob("*.py")}:
        try:
            mod = importlib.import_module(f"aipass.drone.apps.modules.{command}")
        except Exception as exc:
            logger.warning("Failed to discover module %s: %s", command, exc)
    if mod is not None and hasattr(mod, "handle_command"):
        remaining = args[1:]
        cmd = remaining[0] if remaining else None
        cmd_args = remaining[1:] if len(remaining) > 1 else None
        try:
            result = mod.handle_command(cmd, cmd_args)
        except Exception as exc:
            logger.error("Module %s failed: %s", command, exc)
            err_console.print(f"drone: module '{command}' error: {exc}")
            return 1
        if isinstance(result, dict):
            if result.get("stdout"):
                sys.stdout.write(result["stdout"])
            if result.get("stderr"):
                sys.stderr.write(result["stderr"])
            return result.get("exit_code", 0)
        return 0 if result else 1

    custom_result = _handle_custom_command(args)
    if custom_result != -1:
        return custom_result

    # The @ prefix is a hard contract: bare `drone prax` must error, or typos route to branches.
    # PowerShell eats `@` (splatting); the setup.sh profile wrapper restores it, not this code.
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
