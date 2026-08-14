# =================== AIPass ====================
# Name: drive_sync.py
# Description: Drive sync module — uploads versioned store to Google Drive
# Version: 2.0.1
# Created: 2026-04-17
# Modified: 2026-08-11
# =============================================

"""Drive Sync Module — orchestrates file upload to Google Drive.

Scans the versioned store, checks the tracker for changes, and uploads
new or modified files via the Drive upload engine.

Flow: auth → store path → scan → tracker filter → upload_batch → save tracker.
No pre-resolve — workers create folders on demand via the client's lock pattern.
"""

import os
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger
from aipass.cli.apps.modules import console

from aipass.backup.apps.handlers.ignore.patterns import is_ignored, load_spec
from aipass.backup.apps.handlers.json import json_handler
from aipass.backup.apps.handlers.path.builder import build_versioned_store
from aipass.backup.apps.modules.display import show_drive_result


MODULE_NAME = "drive_sync"
PRIMARY_COMMAND = "drive_sync"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: Phase 4 -- Drive sync via @api gateway")
    console.print("  Handlers: drive/client, drive/upload, drive/tracker")


def print_help():
    """Display help for this module."""
    print_introspection()
    console.print()
    console.print("Usage: drive_sync <project_root> \\[options]")
    console.print("  --force       Force re-upload of all files")
    console.print("  --project     Override project name")
    console.print("  --note        Add a note to uploaded files")


def run_drive_sync(
    project_root: str,
    project_name: str = "",
    note: str = "",
    force: bool = False,
    show_panels: bool = True,
) -> dict:
    """Run Drive sync -- upload versioned store to Google Drive.

    Args:
        project_root: Absolute path to the project.
        project_name: Override project name (defaults to dir name).
        note: Note attached to uploads.
        force: Force re-upload of all files.
        show_panels: Show rich CLI output.

    Returns:
        Dict with success, uploaded, failed, skipped, bytes_uploaded,
        duration, location, total keys.
    """
    from aipass.backup.apps.handlers.drive.client import DriveClient
    from aipass.backup.apps.handlers.drive.tracker import (
        check_needs_upload,
        load_tracker,
        save_tracker,
    )
    from aipass.backup.apps.handlers.drive.upload import upload_batch

    start = time.time()

    result: dict = {
        "success": False,
        "uploaded": 0,
        "failed": 0,
        "skipped": 0,
        "total": 0,
        "bytes_uploaded": 0,
        "duration": 0.0,
        "location": "",
        "error": None,
    }

    # 1. Authenticate
    client = DriveClient()
    if not client.authenticate():
        result["error"] = client.last_error or "Drive authentication failed"
        result["duration"] = time.time() - start
        logger.warning(f"[backup] Drive sync auth failed: {result['error']}")
        return result

    # 2. Build versioned store path
    store_path = build_versioned_store(project_root)
    result["location"] = str(store_path)
    if not store_path.exists():
        result["error"] = f"Versioned store not found: {store_path}"
        result["duration"] = time.time() - start
        logger.warning(f"[backup] {result['error']}")
        return result

    # 3. Scan store and re-filter through .backupignore (legacy stores may
    #    contain files swept in before an ignore rule was added).
    spec = load_spec(str(project_root))
    raw_files = [f for f in store_path.rglob("*") if f.is_file()]
    all_files = [f for f in raw_files if not is_ignored(str(f.relative_to(store_path)), spec)]
    ignored_count = len(raw_files) - len(all_files)
    if ignored_count:
        logger.info(f"[backup] Drive sync: filtered {ignored_count} ignored files from store")

    result["total"] = len(all_files)

    if not all_files:
        result["success"] = True
        result["duration"] = time.time() - start
        if show_panels:
            console.print("[dim]No files found in versioned store.[/dim]")
        return result

    # 4. Resolve project name
    if not project_name:
        project_name = Path(project_root).name

    # 5. Load tracker + filter
    tracker = load_tracker(project_root)
    if force:
        files_to_upload = all_files
    else:
        files_to_upload = [f for f in all_files if check_needs_upload(tracker, f, store_path)]

    skipped = len(all_files) - len(files_to_upload)
    result["skipped"] = skipped

    if not files_to_upload:
        result["success"] = True
        result["duration"] = time.time() - start
        if show_panels:
            console.print(f"[green]All {len(all_files)} files up to date.[/green]")
        return result

    # 6. Upload with progress
    progress_fn = None
    progress = None
    task = None

    if show_panels:
        try:
            from rich.progress import Progress

            progress = Progress(console=console)
            progress.start()
            task = progress.add_task(
                "Uploading to Drive...",
                total=len(files_to_upload),
            )

            def _advance():
                if progress is not None and task is not None:
                    progress.advance(task)

            progress_fn = _advance
        except ImportError:
            logger.info("Rich progress not available for Drive upload display")

    try:
        batch_result = upload_batch(
            client,
            files_to_upload,
            project_name,
            store_path,
            tracker,
            note=note,
            progress_fn=progress_fn,
        )
    finally:
        if progress is not None:
            progress.stop()

    result["uploaded"] = batch_result.get("uploaded", 0)
    result["failed"] = batch_result.get("failed", 0)
    result["bytes_uploaded"] = batch_result.get("bytes_uploaded", 0)
    result["success"] = batch_result.get("success", False)
    result["duration"] = time.time() - start

    # 7. Save tracker
    save_tracker(project_root, tracker)

    json_handler.log_operation(
        "drive_sync_complete",
        {
            "project_root": project_root,
            "uploaded": result["uploaded"],
            "failed": result["failed"],
            "skipped": skipped,
            "bytes_uploaded": result["bytes_uploaded"],
        },
    )
    logger.info(f"[backup] Drive sync: {result['uploaded']} uploaded, {result['failed']} failed, {skipped} skipped")

    if show_panels:
        show_drive_result(result)

    return result


def handle_command(command: str, args: list) -> bool:
    """Handle the drive_sync command. Returns True if handled."""
    if command != PRIMARY_COMMAND:
        return False

    if not args:
        print_introspection()
        return True

    # Screen the WHOLE sequence, not just args[0]. This module has a
    # standalone __main__ entry that never reaches the router's help
    # normalisation, so a trailing flag used to fall through and run the
    # verb for real. Bare "help" stays first-position-only: later
    # positions are user values (filenames), not flags.
    if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
        print_help()
        return True

    project_root = args[0]
    force = "--force" in args
    note = ""
    project_name = ""

    for i, arg in enumerate(args):
        if arg == "--note" and i + 1 < len(args):
            note = args[i + 1]
        if arg == "--project" and i + 1 < len(args):
            project_name = args[i + 1]

    run_drive_sync(
        project_root,
        project_name=project_name,
        note=note,
        force=force,
    )
    return True


# =============================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
