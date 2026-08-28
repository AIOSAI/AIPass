# =================== AIPass ====================
# Name: profile.py
# Description: User profile read/write — aipass profile command
# Version: 1.2.0
# Created: 2026-04-16
# Modified: 2026-08-27
# =============================================

"""
aipass profile — show/edit what aipass remembers about the user

Reads and writes ``aipass_json/user_profile.json``.

The profile used to live as a top-level ``user`` section inside
.trinity/local.json. It does not any more: .trinity/local.json's top-level
key set is a CLOSED set under the trinity standard, so a module writing its
own section there drifts the branch off 100 every time it runs. The profile
is module state, not memory, so it lives in this module's own data dir with
the rest of the branch's json. A legacy ``user`` section is still READ as a
fallback so no profile is lost on an old file -- never written back.
Commands:
    aipass profile               — pretty-print current profile
    aipass profile set <f> <v>   — update a field
    aipass profile clear         — reset (confirm required)
    aipass profile clear --yes   — reset without confirmation (dev/CI)
"""

from __future__ import annotations

from pathlib import Path

from aipass.cli.apps.modules import console, error, success, warning
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler

COMMAND = "profile"
_BRANCH_ROOT = Path(__file__).resolve().parents[2]
# NOT profile_data.json: <module>_{config,data,log}.json is json_handler's OWN
# managed triplet, and ensure_module_jsons REGENERATES any of the three that
# fails its shape check. save_profile's own log_operation call auto-detects
# module "profile" and would therefore destroy the profile it had just written
# -- observed 2026-08-27, the store came back as {created, last_updated}.
_PROFILE_FILENAME = "user_profile.json"
_PROFILE_JSON = _BRANCH_ROOT / "aipass_json" / _PROFILE_FILENAME

# Read-only legacy source. Pre-1.1.0 the profile was a top-level "user" section
# in local.json; a file still carrying one is migrated forward on first read.
# Never written -- .trinity/ belongs to the memory standard, not to this module.
_LEGACY_LOCAL_JSON = _BRANCH_ROOT / ".trinity" / "local.json"

USER_FIELDS = ["name", "os", "shell", "preferred_cli", "install_method", "first_seen"]


def _read_json_file(path: Path) -> dict:
    """Load a JSON object from path; {} when absent, unreadable or not a dict."""
    if not path.exists():
        return {}
    result = json_handler.load_path(path)
    if not isinstance(result, dict):
        return {}
    return result


def _fire_file_deleted(path: str) -> None:
    """Fire the write-failure trigger event, ignoring an absent trigger branch.

    Same event name and reason as before the handler refactor, so any consumer
    of this signal sees exactly what it saw when the writer was hand-rolled.
    Only ``path`` changed meaning, and it had to: json_handler owns its temp
    file and unlinks it internally, so this module never learns that name. The
    path is therefore the STORE the failed write targeted, and ``detail`` says
    plainly that the store itself was not the thing deleted -- an event that
    named the store under a bare "file_deleted" with no qualifier would read as
    "the profile was deleted", which is not what happened.
    """
    try:
        from aipass.trigger.apps.modules.core import trigger

        trigger.fire(
            "file_deleted",
            path=path,
            reason="write_failure_cleanup",
            detail="json_handler removed its own temp file; the store was left untouched",
        )
    except ImportError as exc:
        logger.warning("[profile] trigger unavailable for file_deleted event: %s", exc)


def _write_profile_json(data: dict) -> None:
    """Write the store through json_handler, raising when it cannot be written.

    The handler's save is atomic -- temp file, fsync, then a retried replace --
    so an OSError mid-write leaves the previous store byte-intact rather than
    half-written, and the temp file is unlinked on any exception. That is the
    durability the hand-rolled writer provided, kept.

    What the handler does NOT do is raise: it answers False and logs. Answering
    False up to save_profile would make a failed save look identical to a
    successful one at every call site, so the False is turned back into the
    OSError the callers were already written against. A profile that quietly
    failed to save is worse than one that says so.
    """
    if json_handler.save_path(_PROFILE_JSON, data):
        return
    logger.warning("[profile] user_profile.json write failed: %s", _PROFILE_JSON)
    _fire_file_deleted(str(_PROFILE_JSON))
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

    Order: this module's own store, then a legacy local.json "user" section,
    then None-filled defaults. Whatever is found is written to the store, so
    the legacy read happens at most once and local.json is never written.
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
    """Route profile subcommands: show, set <field> <value>, clear, help.

    Returns True if handled, False if command does not match.
    """
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
        # --yes / -y skips the interactive confirmation (CI, dev resets,
        # piped invocations where stdin isn't a TTY).
        skip_confirm = any(a in ("--yes", "-y") for a in args[1:])
        if skip_confirm:
            save_profile({f: None for f in USER_FIELDS})
            success("Profile cleared.")
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
            success("Profile cleared.")
        else:
            console.print("[yellow]Cancelled.[/yellow]")
        return True

    print_help()
    return True
