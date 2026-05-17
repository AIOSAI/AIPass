# =================== AIPass ====================
# Name: hooks.py
# Description: Hook Probe, Test, and List Module
# Version: 1.1.0
# Created: 2026-04-20
# Modified: 2026-04-21
# =============================================

"""
Hook Probe, Test, and List Module

Reads last_ping.jsonl produced by .claude/hooks/probes/ scripts and
surfaces probe data via Rich tables and reports.

Run: drone @seedgo hooks probe [--subagent|--matrix]

Subcommands:
  hooks probe             Show recent probe entries as a Rich table
  hooks probe --subagent  Spawn headless Claude, check if PostToolUse/SubagentStop fired
  hooks probe --matrix    Full event matrix + markdown report
  hooks test              Run hook test suite, display per-file pass/fail table
  hooks list              Show every wired hook from project and global settings
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List

# =============================================================================
# INFRASTRUCTURE SETUP
# =============================================================================

# IMPORTS
# =============================================================================

# Prax logger (system-wide, always first)
from aipass.prax import logger

# CLI services (display/output formatting)
from aipass.cli import console
from aipass.cli.apps.modules import warning

# JSON handler for tracking
from aipass.seedgo.apps.handlers.json import json_handler

# File handler — modules must not call open()/write_text() directly
from aipass.seedgo.apps.handlers.file import write_text_safe

# Extended subcommands (test + list)
from aipass.seedgo.apps.modules.hooks_ext import cmd_hooks_list, run_hooks_report, run_hooks_test

# Probe matrix (split to keep this file under 600 lines)
from aipass.seedgo.apps.modules.hooks_probe import run_probe_matrix

# Rich output
from rich.panel import Panel
from rich.table import Table

# =============================================================================
# PATHS
# =============================================================================

_REPO_ROOT: Path | None = None

# Enable snippet shown when no probe data exists — uses a placeholder path
# so the help_text checker does not flag a literal drone command path.
_PROBE_ENABLE_NOTE = (
    "Add probe hook commands to .claude/settings.json (inside the hooks object).\n"
    "See .claude/hooks/probes/README.md for per-event snippets."
)


def _get_repo_root() -> Path:
    """Return the AIPass repo root derived from this file's location."""
    global _REPO_ROOT
    if _REPO_ROOT is not None:
        return _REPO_ROOT
    current = Path(__file__).resolve().parent
    for parent in (current, *current.parents):
        if (parent / ".git").exists():
            _REPO_ROOT = parent
            return parent
    # Fallback: assume 5 levels up from this file
    _REPO_ROOT = Path(__file__).resolve().parents[5]
    return _REPO_ROOT


def _log_file() -> Path:
    """Return path to last_ping.jsonl."""
    return _get_repo_root() / ".claude" / "hooks" / "probes" / "last_ping.jsonl"


def _probes_dir() -> Path:
    """Return path to probes directory."""
    return _get_repo_root() / ".claude" / "hooks" / "probes"


# =============================================================================
# JSONL READING
# =============================================================================


def _parse_jsonl_line(line: str) -> dict | None:
    """Parse a single JSONL line. Returns None on parse failure."""
    stripped = line.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        logger.info("hooks.py: skipping malformed JSONL line: %s", exc)
        return None


def _read_entries(log_path: Path | None = None) -> List[dict]:
    """Read all entries from last_ping.jsonl. Returns empty list if missing or unreadable."""
    path = log_path or _log_file()
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw_lines = fh.readlines()
    except OSError as exc:
        logger.info("hooks.py: could not read %s: %s", path, exc)
        return []
    entries = []
    for line in raw_lines:
        entry = _parse_jsonl_line(line)
        if entry is not None:
            entries.append(entry)
    return entries


def _truncate(s: str, n: int) -> str:
    """Truncate string to n chars with ellipsis."""
    if len(s) <= n:
        return s
    return s[: n - 3] + "..."


# =============================================================================
# SUBCOMMAND: hooks probe (no flags)
# =============================================================================


def _cmd_probe_display(log_path: Path | None = None) -> None:
    """Display recent probe entries as a Rich table."""
    entries = _read_entries(log_path)

    if not entries:
        console.print(
            Panel(
                "[yellow]No probe data yet.[/yellow]\n\n"
                "Enable probes by adding hook commands to [cyan].claude/settings.json[/cyan].\n"
                f"{_PROBE_ENABLE_NOTE}",
                title="[bold cyan][PROBE][/bold cyan]",
                border_style="cyan",
            )
        )
        return

    # Show last 50 entries
    recent = entries[-50:]

    table = Table(
        title="[bold cyan][PROBE][/bold cyan] Recent Hook Pings",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
        expand=False,
    )
    table.add_column("Event", style="cyan", no_wrap=True)
    table.add_column("Tool", style="green")
    table.add_column("Timestamp", style="dim")
    table.add_column("CWD", style="dim")
    table.add_column("Agent ID", style="dim")
    table.add_column("Elapsed ms", justify="right", style="yellow")
    table.add_column("CLI Ver", style="dim")
    table.add_column("ProjectDir", justify="center")
    table.add_column("AIPassHome", justify="center")

    for e in recent:
        table.add_row(
            e.get("event", "?"),
            _truncate(e.get("tool", ""), 20),
            _truncate(e.get("timestamp", ""), 24),
            _truncate(e.get("cwd", ""), 30),
            _truncate(e.get("agent_id", ""), 14),
            str(round(e.get("script_elapsed_ms", 0), 1)),
            _truncate(e.get("cli_version", "?"), 10),
            "[green]Y[/green]" if e.get("env_has_claude_project_dir") else "[red]N[/red]",
            "[green]Y[/green]" if e.get("env_has_aipass_home") else "[red]N[/red]",
        )

    console.print()
    console.print(table)
    console.print(f"\n[dim]Showing {len(recent)} of {len(entries)} total entries from {_log_file()}[/dim]\n")

    json_handler.log_operation("hooks_probe_display", {"entries_shown": len(recent), "total": len(entries)})


# =============================================================================
# SUBCOMMAND: hooks probe --subagent
# =============================================================================


def _run_headless_claude() -> int:
    """Spawn headless claude with a Read tool call. Returns exit code."""
    canary = Path("/tmp/probe_canary.txt")
    if not write_text_safe(canary, "probe canary 2026-04-20\n"):
        logger.info("hooks.py: could not write canary")

    console.print("[dim]Spawning headless claude...[/dim]")
    # --permission-mode bypassPermissions is the AIPass-approved bypass flag
    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                "--permission-mode",
                "bypassPermissions",
                "read the file /tmp/probe_canary.txt",
                "--allowedTools",
                "Read",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        console.print(f"[dim]claude exited: {result.returncode}[/dim]")
        return result.returncode
    except FileNotFoundError as exc:
        logger.info("hooks.py: claude binary not found: %s", exc)
        warning("claude binary not found — skipping spawn test")
        return -1
    except subprocess.TimeoutExpired as exc:
        logger.info("hooks.py: claude timed out: %s", exc)
        warning("claude timed out after 30s")
        return -2
    except OSError as exc:
        logger.info("hooks.py: spawn error: %s", exc)
        warning(f"spawn error: {exc}")
        return -3


def _cmd_probe_subagent() -> None:
    """Spawn a headless Claude Code process and check if PostToolUse/SubagentStop fired."""
    console.print()
    console.print(
        Panel(
            "[bold cyan]Headless Probe — PostToolUse + SubagentStop[/bold cyan]\n\n"
            "This test spawns a headless claude process with a Read tool call, "
            "then checks last_ping.jsonl for "
            "[yellow]PostToolUse[/yellow] and [yellow]SubagentStop[/yellow] entries "
            "created within the last 10 seconds.\n\n"
            "[dim]Requires PostToolUse and SubagentStop probes to be enabled in settings.json.[/dim]",
            title="[bold cyan][PROBE][/bold cyan]",
            border_style="cyan",
        )
    )

    start_ts = time.time()
    _run_headless_claude()

    # Wait a beat for hooks to flush
    time.sleep(0.5)

    # Check last_ping.jsonl for recent entries
    cutoff = start_ts - 1.0  # 1s before spawn
    entries = _read_entries()
    recent_events = {e.get("event") for e in entries if _entry_ts(e) >= cutoff}

    post_tool_use_fired = "PostToolUse" in recent_events
    subagent_stop_fired = "SubagentStop" in recent_events

    result_table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    result_table.add_column("Check", style="cyan")
    result_table.add_column("Result", justify="center")

    result_table.add_row(
        "PostToolUse fired in headless",
        "[green]YES[/green]" if post_tool_use_fired else "[red]NO[/red]",
    )
    result_table.add_row(
        "SubagentStop fired in headless",
        "[green]YES[/green]" if subagent_stop_fired else "[red]NO[/red]",
    )

    console.print(result_table)
    console.print()

    # Manual test section
    console.print(
        Panel(
            "[bold yellow]Manual Interactive Agent-Tool Test[/bold yellow]\n\n"
            "To test hooks fired by the interactive Agent tool:\n\n"
            "1. Enable PostToolUse and SubagentStop probes in .claude/settings.json\n"
            "2. In an interactive Claude Code session, invoke an Agent tool call\n"
            "3. After the agent completes, run:\n"
            "   [cyan]drone @seedgo hooks probe[/cyan]\n"
            "4. Check for SubagentStop and PostToolUse entries near the agent's timestamp\n\n"
            "[dim]Headless (-p) and interactive Agent tool have different session contexts.[/dim]\n"
            "[dim]SubagentStop fires when an agent tool invocation completes.[/dim]",
            title="[bold cyan][PROBE][/bold cyan] Manual Test",
            border_style="dim",
        )
    )

    json_handler.log_operation(
        "hooks_probe_subagent",
        {"post_tool_use_fired": post_tool_use_fired, "subagent_stop_fired": subagent_stop_fired},
    )


def _entry_ts(entry: dict) -> float:
    """Parse entry timestamp to unix float. Returns 0 on failure."""
    ts_str = entry.get("timestamp", "")
    if not ts_str:
        return 0.0
    try:
        normalized = ts_str[:-1] + "+00:00" if ts_str.endswith("Z") else ts_str
        dt = datetime.fromisoformat(normalized)
        return dt.timestamp()
    except ValueError as exc:
        logger.info("hooks.py: could not parse timestamp %r: %s", ts_str, exc)
        return 0.0


# =============================================================================
# SUBCOMMAND: hooks probe --matrix (delegated to hooks_probe)
# =============================================================================


def _cmd_probe_matrix() -> None:
    """Group entries by event, show matrix, write markdown report — delegates to hooks_probe."""
    run_probe_matrix(_read_entries, _probes_dir)


# =============================================================================
# SUBCOMMAND: hooks test + hooks list (delegated to hooks_ext)
# =============================================================================


def _cmd_hooks_test() -> None:
    """Run hook test suite — delegates to hooks_ext."""
    run_hooks_test(_get_repo_root())


def _cmd_hooks_list() -> None:
    """Show wired hooks — delegates to hooks_ext."""
    cmd_hooks_list(_get_repo_root())


def _cmd_hooks_report(args: list) -> None:
    """Run hook execution report — delegates to hooks_ext."""
    run_hooks_report(_get_repo_root(), args)


# =============================================================================
# INTROSPECTION
# =============================================================================


def print_help() -> None:
    """CLI --help entry point — delegates to print_introspection."""
    print_introspection()


def print_introspection() -> None:
    """Display module info and usage."""
    console.print()
    console.print("[bold cyan]hooks Module[/bold cyan]")
    console.print("Hook probe display — reads last_ping.jsonl from .claude/hooks/probes/")
    console.print()

    log = _log_file()
    if log.exists():
        entries = _read_entries()
        console.print(f"[yellow]Probe log:[/yellow] {log}  ([green]{len(entries)} entries[/green])")
    else:
        console.print(f"[yellow]Probe log:[/yellow] {log}  [dim](not yet created — enable probes first)[/dim]")
    console.print()

    console.print("[yellow]Subcommands:[/yellow]")
    console.print("  [green]drone @seedgo hooks probe[/green]             [dim]# Display recent entries table[/dim]")
    console.print(
        "  [green]drone @seedgo hooks probe --subagent[/green]  [dim]# Test headless PostToolUse/SubagentStop[/dim]"
    )
    console.print(
        "  [green]drone @seedgo hooks probe --matrix[/green]    [dim]# Full event matrix + markdown report[/dim]"
    )
    console.print("  [green]drone @seedgo hooks test[/green]              [dim]# Run hook test suite[/dim]")
    console.print("  [green]drone @seedgo hooks report[/green]             [dim]# Hook execution log report[/dim]")
    console.print("  [green]drone @seedgo hooks list[/green]              [dim]# List all wired hooks[/dim]")
    console.print()

    console.print("[yellow]Probe scripts:[/yellow]")
    probes_dir = _probes_dir()
    for script in sorted(probes_dir.glob("probe_*.py")):
        console.print(f"  [dim]{script.name}[/dim]")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/json/[/cyan]")
    console.print("    [dim]- json_handler.py (log_operation — operation tracking)[/dim]")
    console.print()

    console.print("[yellow]External Dependencies:[/yellow]")
    console.print("  [dim]- aipass.prax (logger)[/dim]")
    console.print("  [dim]- aipass.cli (console)[/dim]")
    console.print()


# =============================================================================
# COMMAND HANDLER
# =============================================================================


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle 'hooks' command — hook probe display and testing.

    Args:
        command: Command name
        args: Additional arguments
            [] -> print_introspection()
            ["probe"] -> display last_ping.jsonl table
            ["probe", "--subagent"] -> headless probe test
            ["probe", "--matrix"] -> full event matrix + report
            ["--help"] | ["help"] -> print_introspection()

    Returns:
        True if handled, False if not this module's command
    """
    if command != "hooks":
        return False

    if not args:
        print_introspection()
        return True
    if args[0] in ("--help", "-h", "help"):
        print_help()
        return True

    subcommand = args[0]

    if subcommand == "probe":
        sub_args = args[1:]
        if "--subagent" in sub_args:
            _cmd_probe_subagent()
        elif "--matrix" in sub_args:
            _cmd_probe_matrix()
        else:
            _cmd_probe_display()
        return True

    if subcommand == "test":
        _cmd_hooks_test()
        return True

    if subcommand == "report":
        _cmd_hooks_report(args[1:])
        return True

    if subcommand == "list":
        _cmd_hooks_list()
        return True

    # Unknown subcommand — show introspection
    console.print(f"[dim]Unknown subcommand: {subcommand!r} — showing help[/dim]")
    print_introspection()
    return True


# =============================================================================
# STANDALONE EXECUTION
# =============================================================================

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h", "help"):
        print_introspection()
        sys.exit(0)

    logger.info("Prax logger connected to hooks")
    handle_command("hooks", sys.argv[1:])
