# =================== AIPass ====================
# Name: share.py
# Description: Share module — single-file Drive upload with shareable link
# Version: 1.1.1
# Created: 2026-07-01
# Modified: 2026-10-17
# =============================================

"""Share Module — upload a single file to Drive and return a shareable link."""

import os
import sys
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger
from aipass.cli.apps.modules import console, error as cli_error

from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.path.caller import resolve_caller_path

MODULE_NAME = "share"
PRIMARY_COMMAND = "share"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: Live — single-file Drive upload + share link")
    console.print("  Handlers: drive/client, drive/upload, drive/share")


def print_help():
    """Display help for this module."""
    print_introspection()
    console.print()
    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()
    console.print("  [dim]drone @backup share <file_path> [--public][/dim]")
    console.print()
    console.print("[bold cyan]OPTIONS:[/bold cyan]")
    console.print()
    console.print("  [green]--public[/green]   Share with anyone (default: restricted to owner)")
    console.print()
    console.print("[bold cyan]OUTPUT:[/bold cyan]")
    console.print()
    console.print("  Final stdout line is the shareable Google Drive link.")
    console.print()


def run_share(file_path: str, *, public: bool = False) -> dict:
    """Upload a single file to Drive and return a shareable link."""
    from aipass.backup.apps.handlers.drive.client import DriveClient
    from aipass.backup.apps.handlers.drive.share import share_file

    # Backup runs as an installed entry point, so a relative path would resolve
    # against backup's own branch dir. Re-anchor it to where the user actually is.
    resolved_path = str(resolve_caller_path(file_path))

    # A missing path is a local answer: refuse it before authenticating to Drive.
    if not Path(resolved_path).is_file():
        err_msg = f"Not a file: {resolved_path}"
        cli_error(f"Share failed: {err_msg}")
        logger.warning(f"[backup] Share failed: {err_msg}")
        return {"success": False, "link": None, "file_id": None, "error": err_msg}

    client = DriveClient()
    if not client.authenticate():
        err_msg = f"Drive authentication failed: {client.last_error}"
        cli_error(err_msg)
        logger.warning(f"[backup] {err_msg}")
        return {"success": False, "link": None, "file_id": None, "error": err_msg}

    console.print(f"[dim]Uploading {resolved_path}...[/dim]")
    result = share_file(client, resolved_path, public=public)

    if result["success"]:
        mode = "public" if public else "restricted"
        console.print(f"[green]Shared ({mode}):[/green] {result['link']}")
        logger.info(f"[backup] Shared {resolved_path} ({mode})")
    else:
        cli_error(f"Share failed: {result['error']}")
        logger.warning(f"[backup] Share failed: {result['error']}")

    if result.get("link"):
        console.print(result["link"], highlight=False)

    trail.log_operation(
        "share_command",
        {
            "file": resolved_path,
            "public": public,
            "success": result["success"],
        },
    )

    return result


def handle_command(command: str, args: list) -> bool:
    """Handle the share command. Returns True if handled."""
    if command != PRIMARY_COMMAND:
        return False

    if not args:
        print_introspection()
        return True

    # Screen every arg: the standalone __main__ skips the router's help normalisation.
    # Bare "help" is first-position only; later args are user values.
    if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
        print_help()
        return True

    # Split flags from operands: `share --public f.pdf` must not hand "--public" to run_share
    # as the filename, which authenticates against the real Drive before the path is checked.
    public = "--public" in args
    operands = [arg for arg in args if not arg.startswith("--")]

    if not operands:
        cli_error(
            "share needs a file path",
            suggestion="drone @backup share <file_path> [--public]",
        )
        return True

    run_share(operands[0], public=public)
    return True


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
    sys.exit(0)
