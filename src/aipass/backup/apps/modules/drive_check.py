# =================== AIPass ====================
# Name: drive_check.py
# Description: Drive check module — verifies Google Drive connectivity via @api
# Version: 1.0.0
# Created: 2026-04-17
# Modified: 2026-06-12
# =============================================

"""Drive Check Module — tests Drive auth through @api gateway."""

import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger
from aipass.cli.apps.modules import console, error as cli_error

from aipass.backup.apps.handlers.audit import trail


MODULE_NAME = "drive_check"
PRIMARY_COMMAND = "drive_check"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: Phase 4 -- auth test via @api gateway")
    console.print("  Handlers: drive/client, drive/test")


def print_help():
    """Display help for this module."""
    print_introspection()
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print("  drive_check run — test Drive auth and folder access")
    console.print()
    console.print("The check is account-wide; it takes no project argument.")


def run_drive_check() -> bool:
    """Test Drive auth through @api gateway.

    Creates a DriveClient, authenticates, tests folder access, and
    displays results.

    Returns:
        True if connectivity test passed, False otherwise.
    """
    from aipass.backup.apps.handlers.drive.client import DriveClient
    from aipass.backup.apps.handlers.drive.test import test_connectivity

    client = DriveClient()
    result = test_connectivity(client)

    if result["success"]:
        console.print("[green]Drive connectivity test PASSED[/green]")
        console.print(f"  Backup folder ID: {result['folder_id']}")
        logger.info("[backup] Drive test passed")
    else:
        cli_error(f"Drive connectivity test FAILED: {result['error']}")
        logger.warning(f"[backup] Drive test failed: {result['error']}")

    trail.log_operation(
        "drive_check_complete",
        {"success": result["success"]},
    )
    return result["success"]


def handle_command(command: str, args: list) -> bool:
    """Handle the drive-check command. Returns True if handled."""
    if command != PRIMARY_COMMAND:
        return False

    if not args:
        print_introspection()
        return True

    # Screen the WHOLE sequence, not just args[0]. There used to be a default
    # branch below that ran the check for ANY unrecognised first arg, so
    # 'drive_check foo --help' made a live Drive auth call (proven
    # 2026-08-13). Bare "help" stays first-position-only.
    if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
        print_help()
        return True

    if args[0] == "run":
        run_drive_check()
        return True

    # There is NO default branch any more. Until now the bottom of this
    # function was a bare run_drive_check(), so every unrecognised first
    # argument -- 'drive_check statuss', 'drive_check --froce' -- was a LIVE
    # Google Drive auth against the real account. The --help shape of that
    # hole was closed 2026-08-13 by the gate above; the plain typo was not.
    #
    # Refuse by name, through error(): it writes to stderr and calls
    # mark_command_failed(), so main()'s resolve_exit reports 2 instead of 0.
    # Return True, not False: route_command stops at the first module that
    # claims the command, and a False here makes main() print its own
    # "Unknown command: drive_check" -- naming the command that exists rather
    # than the verb that does not, while this refusal scrolls past above it.
    cli_error(
        f"Unknown drive_check verb: {args[0]}",
        suggestion="drive_check run  (verbs: run, help; flags: --help, -h)",
    )
    return True


# =============================================

if __name__ == "__main__":
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
    sys.exit(0)
