# =================== AIPass ====================
# Name: settings.py
# Description: Settings module — sets a project's drive_sync on or off; the settings UI is deferred
# Version: 0.2.0
# Created: 2026-04-17
# Modified: 2026-10-16
# =============================================

"""Settings Module — one live key, drive_sync, written through the project config handler.

``settings drive_sync on|off <project_path|@name>`` switches whether ``all``
runs the Drive step for a project. Every other setting still refuses: the
settings UI is deferred (Phase 3).
"""

import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger
from aipass.cli.apps.modules import console, error, warning
from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.path.builder import backup_root
from aipass.backup.apps.handlers.project.config import set_project_setting
from aipass.backup.apps.modules.register import resolve_project


MODULE_NAME = "settings"
PRIMARY_COMMAND = "settings"
DRIVE_SYNC_KEY = "drive_sync"
DRIVE_SYNC_USAGE = "Usage: settings drive_sync on|off <project_path|@name>"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: drive_sync on|off is live; the settings UI awaits Phase 3")
    console.print("  Handlers: project/config")


def print_help():
    """Display help for this module."""
    print_introspection()
    console.print()
    console.print(DRIVE_SYNC_USAGE, markup=False)
    console.print("  on: 'all' runs the Drive step for this project; off: it skips it.")
    console.print("  The bare drive_sync verb uploads whatever this says.")


def set_drive_sync(args: list) -> bool:
    """Write drive_sync for one project and print the new value.

    Args:
        args: The words after ``drive_sync``: ``on|off`` and the project.

    Returns:
        True when the value was written. A refusal calls error(), which
        makes the exit non-zero.
    """
    if len(args) != 2 or args[0] not in ("on", "off"):
        error(DRIVE_SYNC_USAGE)
        return False

    word, target = args
    project_root = resolve_project(target)
    if project_root is None:
        error(f"Cannot resolve project: {target}")
        return False

    # A store is what makes a directory a backup project. Writing the config
    # into a bare directory would scaffold half a store as a side effect.
    if not backup_root(project_root).is_dir():
        error(f"No backup store at {backup_root(project_root)} — register or snapshot the project first")
        return False

    if not set_project_setting(project_root, DRIVE_SYNC_KEY, word == "on"):
        error(f"Could not write {DRIVE_SYNC_KEY} for {project_root}")
        return False

    trail.log_operation("settings_drive_sync", {"project_root": project_root, "drive_sync": word == "on"})
    logger.info(f"[backup] settings: drive_sync {word} for {project_root}")
    console.print(f"drive_sync: {word} ({project_root})", markup=False)
    return True


def handle_command(command: str, args: list) -> bool:
    """Handle the settings command. Returns True if handled."""
    if command != PRIMARY_COMMAND:
        return False

    if not args:
        print_introspection()
        return True

    # Screen the WHOLE sequence, not just args[0]: a trailing flag on a real
    # write ("drive_sync on @x --help") must explain, never write.
    if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
        print_help()
        return True

    if args[0] == DRIVE_SYNC_KEY:
        set_drive_sync(args[1:])
        return True

    # Say it out loud, and REFUSE. Returning True here printed a warning and
    # exited 0 -- indistinguishable from a settings UI that opened and closed,
    # which is the one thing a deferred command must never look like
    # (refusal sweep 2026-09-07). Raising reaches route_command's handler in
    # apps/backup.py, which names the module and the reason and exits 1.
    logger.warning(f"[backup] {MODULE_NAME} stub invoked with args={args} — awaiting Phase 3")
    trail.log_operation(f"{MODULE_NAME}_stub_invoked", {"args": args})
    raise NotImplementedError(
        f"{PRIMARY_COMMAND} sets one key today, drive_sync on|off <project_path|@name>; "
        "the settings UI is deferred (Phase 3). Edit .backup/config.json in the project directly for anything else."
    )


# =============================================

if __name__ == "__main__":
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)
    try:
        result = handle_command(sys.argv[1], sys.argv[2:])
    except NotImplementedError as exc:
        # Standalone entry has no router to catch it -- report, do not traceback.
        warning(str(exc))
        sys.exit(1)
    sys.exit(0 if result else 1)
