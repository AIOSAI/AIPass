# =================== AIPass ====================
# Name: drone_adapter.py
# Description: CLI drone adapter — bridges drone routing to CLI commands
# Version: 2.0.0
# Created: 2025-11-13
# Modified: 2026-03-23
# =============================================

"""CLI drone adapter — bridges drone routing to CLI commands.

Drone discovers this module via aipass.drone.modules._MODULE_REGISTRY
and routes `drone @cli <command> [args]` here.
"""

import sys
from io import StringIO

DRONE_MODULE = {
    "name": "cli",
    "version": "2.0.0",
    "description": "Universal Display & Output Service Provider",
}


def handle_command(command: str, args: list[str] | None = None) -> dict:
    """Route a drone command to CLI's entry point.

    Captures stdout/stderr and returns as dict for drone CLI to print.
    """
    if args is None:
        args = []

    # Build argv as if `cli <command> [args]` was called
    original_argv = sys.argv
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    captured_out = StringIO()
    captured_err = StringIO()

    try:
        sys.argv = ["cli", command] + args
        sys.stdout = captured_out
        sys.stderr = captured_err

        # Import here to avoid circular imports at module level
        from aipass.cli.apps.cli import main
        exit_code = main()
    except SystemExit as e:
        exit_code = e.code if e.code is not None else 0
    except Exception as e:
        captured_err.write(str(e))
        exit_code = 1
    finally:
        sys.argv = original_argv
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    return {
        "stdout": captured_out.getvalue(),
        "stderr": captured_err.getvalue(),
        "exit_code": exit_code if isinstance(exit_code, int) else 1,
    }


def get_help(command: str | None = None) -> str:
    """Return help text for CLI as Rich markup strings.

    Returns Rich markup (not captured ANSI) so drone's console.print()
    renders it cleanly — same pattern as get_introspective().
    """
    if command:
        result = handle_command(command, ["--help"])
        return result.get("stdout", "") or result.get("stderr", "")

    # Build help as Rich markup strings (drone renders these)
    try:
        from aipass.cli.apps.cli import discover_modules, VERSION
        modules = discover_modules()
    except Exception:
        return "cli — Universal Display & Output Service Provider\nRun 'drone @cli --help' for usage\n"

    lines = []
    lines.append("")
    lines.append("[bold cyan]CLI - Display & Templates Service Provider[/bold cyan]")
    lines.append(f"  Version: {VERSION}")
    lines.append("")
    lines.append("[dim]Universal display and output formatting for all AIPass branches[/dim]")
    lines.append("")
    lines.append("\u2500" * 70)
    lines.append("")

    # What is CLI
    lines.append("[bold cyan]WHAT IS CLI?[/bold cyan]")
    lines.append("")
    lines.append("CLI is the [bold]Display & Templates Service[/bold] \u2014 it:")
    lines.append("  [green]\u2713[/green] Provides [green]centralized display formatting[/green] (headers, tables, panels)")
    lines.append("  [green]\u2713[/green] Reusable templates for common operations")
    lines.append("  [green]\u2713[/green] Rich library integration for beautiful output")
    lines.append("  [green]\u2713[/green] Consistent styling across all AIPass branches")
    lines.append("")

    # Discovered modules
    if modules:
        lines.append("[bold cyan]DISCOVERED MODULES:[/bold cyan]")
        lines.append("")
        for module in modules:
            name = getattr(module, "__name__", "unknown").split(".")[-1]
            desc = (module.__doc__ or "").strip().split("\n")[0] if module.__doc__ else "No description"
            lines.append(f"  [cyan]\u2022[/cyan] {name} \u2014 {desc}")
        lines.append("")

    lines.append("\u2500" * 70)
    lines.append("")

    # Usage
    lines.append("[bold cyan]USAGE:[/bold cyan]")
    lines.append("")
    lines.append("[yellow]Commands:[/yellow]")
    lines.append("  [dim]drone @cli                              # Show discovered modules[/dim]")
    lines.append("  [dim]drone @cli aipass                       # Project commands[/dim]")
    lines.append("  [dim]drone @cli aipass init                  # Bootstrap a project[/dim]")
    lines.append("  [dim]drone @cli aipass init /path MyProj     # Bootstrap with name[/dim]")
    lines.append("  [dim]drone @cli display                      # Display module info[/dim]")
    lines.append("  [dim]drone @cli display demo                 # Run display demo[/dim]")
    lines.append("  [dim]drone @cli --help                       # Full usage guide[/dim]")
    lines.append("")

    lines.append("\u2500" * 70)
    lines.append("")

    # Commands line for drone discovery
    lines.append("[dim]Commands: aipass, display, templates, demo, --help[/dim]")
    lines.append("")

    return "\n".join(lines)


def get_introspective() -> str:
    """Discovery mode: show what CLI has connected."""
    try:
        from aipass.cli.apps.cli import discover_modules, VERSION, SERVICE_MODULES

        modules = discover_modules()

        # Separate command modules from service modules
        command_modules = [m for m in modules
                           if getattr(m, "__name__", "").split(".")[-1] not in SERVICE_MODULES]
        service_modules = [m for m in modules
                           if getattr(m, "__name__", "").split(".")[-1] in SERVICE_MODULES]

        lines = []
        lines.append("[bold cyan]CLI - Display & Templates Service Provider[/bold cyan]")
        lines.append(f"  Version: {VERSION}")
        lines.append("")

        # Command modules
        lines.append(f"[yellow]Discovered Modules:[/yellow] {len(command_modules)}")
        for module in command_modules:
            mod_name = getattr(module, "__name__", "unknown").split(".")[-1]
            desc = (module.__doc__ or "").strip().split("\n")[0] if module.__doc__ else "No description"
            lines.append(f"  [cyan]\u2022[/cyan] {mod_name} \u2014 {desc}")
        if not command_modules:
            lines.append("  [dim]No command modules discovered[/dim]")
        lines.append("")

        # Service modules
        if service_modules:
            lines.append(f"[yellow]Services:[/yellow] {len(service_modules)}")
            for module in service_modules:
                mod_name = getattr(module, "__name__", "unknown").split(".")[-1]
                desc = (module.__doc__ or "").strip().split("\n")[0] if module.__doc__ else "No description"
                lines.append(f"  [cyan]\u2022[/cyan] {mod_name} \u2014 {desc}")
            lines.append("")

        lines.append("[dim]Run 'drone @cli --help' for usage[/dim]")
        lines.append("")

        return "\n".join(lines)
    except Exception:
        return "@cli \u2014 Universal Display & Output Service Provider (run 'drone @cli --help' for usage)\n"
