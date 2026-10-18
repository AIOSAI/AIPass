# =================== AIPass ====================
# Name: profile.py
# Description: User profile read/write — aipass profile command
# Version: 1.2.1
# Created: 2026-04-16
# Modified: 2026-10-17
# =============================================

"""
aipass profile — show/edit what aipass remembers about the user

Store: ``aipass_json/user_profile.json``; .trinity/local.json's keys are a closed set (read only).
"""

from __future__ import annotations

from pathlib import Path

from aipass.cli.apps.modules import console, error, success, warning
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.module_root import module_file

COMMAND = "profile"
# module_file, not resolve(): import-time cwd read on Windows (module_root).
_BRANCH_ROOT = module_file(__file__).parents[2]
# NOT profile_data.json: json_handler regenerates its own <module>_{config,data,log}.json
# triplet, so save_profile's log_operation would wipe the profile it just wrote.
_PROFILE_FILENAME = "user_profile.json"
_PROFILE_JSON = _BRANCH_ROOT / "aipass_json" / _PROFILE_FILENAME

# Read-only legacy source, migrated forward on first read; .trinity/ is never written here.
_LEGACY_LOCAL_JSON = _BRANCH_ROOT / ".trinity" / "local.json"

USER_FIELDS = ["name", "os", "shell", "preferred_cli", "install_method", "first_seen"]


def _read_json_file(path: Path) -> dict:
    """Load a JSON object from path; {} when absent, unreadable or not a dict."""
    if not path.exists():
        return {}
    result = json_handler.read_json(path)
    if not isinstance(result, dict):
        return {}
    return result


def _fire_profile_write_failed(path: str) -> None:
    """Fire the write-failure trigger event, ignoring an absent trigger branch.

    ``path`` is the store the write targeted; json_handler owns and unlinks its temp file.
    """
    try:
        from aipass.trigger.apps.modules.core import trigger

        trigger.fire(
            "profile_write_failed",
            path=path,
            reason="write_failure_cleanup",
            detail="json_handler removed its own temp file; the store was left untouched",
        )
    except ImportError as exc:
        logger.warning("[profile] trigger unavailable for profile_write_failed event: %s", exc)


def _write_profile_json(data: dict) -> None:
    """Write the store through json_handler, raising when it cannot be written.

    The handler answers False; callers expect OSError, so a failed save never looks saved.
    """
    if json_handler.write_json(_PROFILE_JSON, data):
        return
    logger.warning("[profile] user_profile.json write failed: %s", _PROFILE_JSON)
    _fire_profile_write_failed(str(_PROFILE_JSON))
    raise OSError(f"[profile] could not write {_PROFILE_JSON}")


def _legacy_profile() -> dict:
    """Return a pre-1.1.0 profile from local.json's "user" section, or {}."""
    legacy = _read_json_file(_LEGACY_LOCAL_JSON).get("user")
    if not isinstance(legacy, dict) or not legacy:
        return {}
    logger.info("[profile] adopting legacy user section from %s", _LEGACY_LOCAL_JSON)
    return legacy


def get_user_profile() -> dict:
    """Return the stored profile, creating defaults if absent.

    Whatever is found is written to the store, so the legacy read happens at most once.
    """
    data = _read_json_file(_PROFILE_JSON)
    profile = data.get("profile")
    if not isinstance(profile, dict):
        profile = {f: None for f in USER_FIELDS}
        profile.update(_legacy_profile())
        _write_profile_json({"profile": profile})
        return profile
    # A field added to USER_FIELDS after this file was written must still show.
    return {f: profile.get(f) for f in USER_FIELDS} | {k: v for k, v in profile.items() if k not in USER_FIELDS}


def save_profile(profile: dict) -> None:
    """Write the profile to this module's own store."""
    _write_profile_json({"profile": profile})
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
    """Route profile subcommands: show, set <field> <value>, clear, help."""
    if command != COMMAND:
        return False

    if not args:
        print_introspection()
        return True

    if wants_help(args):
        print_help()
        return True

    if args[0] == "--info":
        print_introspection()
        return True

    if args[0] == "set":
        if len(args) < 3:
            error("Usage: aipass profile set <field> <value>")
            return True
        field, value = args[1], args[2]
        if field not in USER_FIELDS:
            error(f"Unknown field: {field}")
            console.print("[dim]Valid fields: " + ", ".join(USER_FIELDS) + "[/dim]")
            return True
        profile = get_user_profile()
        profile[field] = value
        save_profile(profile)
        success(f"{field} = {value}")
        return True

    if args[0] == "clear":
        skip_confirm = any(a in ("--yes", "-y") for a in args[1:])
        if skip_confirm:
            save_profile({f: None for f in USER_FIELDS})
            success("Profile cleared.")
            return True
        warning("Type 'aipass' to confirm clearing your profile (ctrl-C to cancel):")
        try:
            confirm = input("> ").strip()
        except (KeyboardInterrupt, EOFError) as exc:
            # Nothing was cleared, so this must not exit 0.
            logger.info("[profile] clear input interrupted: %s", exc)
            error("Cancelled — no confirmation read, profile NOT cleared.")
            raise SystemExit(1) from exc
        if confirm == "aipass":
            save_profile({f: None for f in USER_FIELDS})
            success("Profile cleared.")
            return True
        error(f"Cancelled — confirmation was {confirm!r}, not 'aipass'. Profile NOT cleared.")
        raise SystemExit(1)

    print_help()
    return True
