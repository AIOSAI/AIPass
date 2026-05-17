# =================== AIPass ====================
# Name: profile.py
# Description: User profile read/write — aipass profile command
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-16
# =============================================

"""
aipass profile — show/edit what aipass remembers about the user

Reads and writes the `user` section of .trinity/local.json.
Commands:
    aipass profile               — pretty-print current profile
    aipass profile set <f> <v>   — update a field
    aipass profile clear         — reset (confirm required)
    aipass profile clear --yes   — reset without confirmation (dev/CI)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from aipass.cli.apps.modules import console, error, warning
from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler

COMMAND = "profile"
_BRANCH_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_JSON = _BRANCH_ROOT / ".trinity" / "local.json"

USER_FIELDS = ["name", "os", "shell", "preferred_cli", "install_method", "first_seen"]


def _read_local_json() -> dict:
    if not _LOCAL_JSON.exists():
        return {}
    result = json_handler.load_path(_LOCAL_JSON)
    if result is None:
        return {}
    return result


def _fire_file_deleted(path: str) -> None:
    """Fire trigger event for temp file deletion, ignoring ImportError."""
    try:
        from aipass.trigger.apps.modules.core import trigger

        trigger.fire("file_deleted", path=path, reason="write_failure_cleanup")
    except ImportError as exc:
        logger.warning("[profile] trigger unavailable for file_deleted event: %s", exc)


def _write_local_json(data: dict) -> None:
    dir_ = _LOCAL_JSON.parent
    dir_.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(dir_), prefix=".local_", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, _LOCAL_JSON)
    except OSError as exc:
        logger.warning("[profile] write failed, cleaning up temp file: %s", tmp_path)
        _fire_file_deleted(tmp_path)
        os.unlink(tmp_path)
        logger.warning("[profile] local.json write error: %s", exc)
        raise


def get_user_profile() -> dict:
    """Return user section from local.json, creating defaults if absent."""
    data = _read_local_json()
    if "user" not in data:
        data["user"] = {f: None for f in USER_FIELDS}
        _write_local_json(data)
    return data.get("user", {})


def save_profile(profile: dict) -> None:
    """Write user section to local.json, preserving all other sections."""
    data = _read_local_json()
    data["user"] = profile
    _write_local_json(data)
    json_handler.log_operation("profile_save", {"fields": list(profile.keys())})


def print_introspection() -> None:
    """Display current user profile."""
    from rich.table import Table

    profile = get_user_profile()
    console.print()
    console.print("[bold cyan]aipass profile[/bold cyan]")
    console.print()

    table = Table(show_header=True, header_style="bold yellow")
    table.add_column("Field", style="cyan", width=20)
    table.add_column("Value")
    for field in USER_FIELDS:
        value = profile.get(field)
        display = str(value) if value is not None else "[dim]—[/dim]"
        table.add_row(field, display)
    console.print(table)
    console.print()
    console.print("[dim]Use 'aipass profile set <field> <value>' to update.[/dim]")
    console.print()


def print_help() -> None:
    """Print usage help for the profile command."""
    console.print()
    console.print("[bold cyan]aipass profile[/bold cyan] — user memory read/write")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass profile[/green]                  [dim]# Show current profile[/dim]")
    console.print("  [green]aipass profile set <field> <value>[/green]  [dim]# Update a field[/dim]")
    console.print("  [green]aipass profile clear[/green]            [dim]# Reset profile (interactive confirm)[/dim]")
    console.print("  [green]aipass profile clear --yes[/green]      [dim]# Reset profile (no confirm)[/dim]")
    console.print()
    console.print("[yellow]FIELDS:[/yellow] " + ", ".join(USER_FIELDS))
    console.print()


def handle_command(command: str, args: list[str]) -> bool:
    """Route profile subcommands: show, set <field> <value>, clear, help.

    Returns True if handled, False if command does not match.
    """
    if command != COMMAND:
        return False

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_help()
        return True

    if args[0] == "set":
        if len(args) < 3:
            error("Usage: aipass profile set <field> <value>")
            return True
        field, value = args[1], args[2]
        if field not in USER_FIELDS:
            console.print(f"[red]Unknown field: {field}[/red]")
            console.print("[dim]Valid fields: " + ", ".join(USER_FIELDS) + "[/dim]")
            return True
        profile = get_user_profile()
        profile[field] = value
        save_profile(profile)
        console.print(f"[green]✓[/green] {field} = {value}")
        return True

    if args[0] == "clear":
        # --yes / -y skips the interactive confirmation (CI, dev resets,
        # piped invocations where stdin isn't a TTY).
        skip_confirm = any(a in ("--yes", "-y") for a in args[1:])
        if skip_confirm:
            save_profile({f: None for f in USER_FIELDS})
            console.print("[green]✓[/green] Profile cleared.")
            return True
        warning("Type 'aipass' to confirm clearing your profile (ctrl-C to cancel):")
        try:
            confirm = input("> ").strip()
        except (KeyboardInterrupt, EOFError) as exc:
            logger.info("[profile] clear input interrupted: %s", exc)
            console.print("\n[yellow]Cancelled.[/yellow]")
            return True
        if confirm == "aipass":
            save_profile({f: None for f in USER_FIELDS})
            console.print("[green]✓[/green] Profile cleared.")
        else:
            console.print("[yellow]Cancelled.[/yellow]")
        return True

    print_help()
    return True
