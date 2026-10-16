# =================== AIPass ====================
# Name: drive_sync.py
# Description: Drive sync module — uploads the snapshot store to Google Drive
# Version: 2.4.0
# Created: 2026-04-17
# Modified: 2026-10-16
# =============================================

"""Drive Sync Module — orchestrates file upload to Google Drive.

Scans the snapshot store, checks the tracker for changes, and uploads
new or modified files via the Drive upload engine, under
<BACKUP_FOLDER_NAME>/<project>/snapshot/. The versioned store never leaves the
machine (DPLAN-0411); what an earlier versioned sync put on Drive is left there.

Flow: auth → store path → scan → ignore + never-leaves filter → set aside a
tracker from another lane → tracker filter → headroom (planned bytes against
the account's free space; refuse before the first upload) → upload_batch,
which saves the tracker every 50 files → save tracker.
The whole run announces itself in ``.backup/running/drive_sync.json`` and turns
SIGTERM into a stop: the uploads not yet started never go, the tracker is
saved, and the stopped line ends the run (DPLAN-0412).
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
from aipass.cli.apps.modules import console, mark_command_failed

from aipass.backup.apps.handlers.ignore.patterns import is_ignored, load_spec
from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.path.builder import build_snapshot_path
from aipass.backup.apps.handlers.report.formatter import _human_bytes
from aipass.backup.apps.handlers.report.result import BackupResult
from aipass.backup.apps.handlers.state.changelog import append_changelog
from aipass.backup.apps.handlers.state.metadata import build_metadata
from aipass.backup.apps.handlers.state.progress import LaneProgress
from aipass.backup.apps.handlers.state.stop_flag import catch_sigterm
from aipass.backup.apps.modules.display import show_drive_result
from aipass.backup.apps.modules.stop import report_stopped


MODULE_NAME = "drive_sync"
PRIMARY_COMMAND = "drive_sync"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Status: Phase 4 -- snapshot store to Drive via @api gateway")
    console.print("  Handlers: drive/client, drive/upload, drive/tracker")


def print_help():
    """Display help for this module."""
    print_introspection()
    console.print()
    console.print("Usage: drive_sync <project_root> \\[options]")
    console.print("  Uploads the snapshot store, whatever the project's drive_sync setting says.")
    console.print("  --force       Force re-upload of all files")
    console.print("  --project     Override project name")
    console.print("  --note        Add a note to uploaded files")


def _planned_bytes(files: list[Path]) -> int:
    """Sum the sizes of the files about to upload; a file that cannot be stat'ed counts 0."""
    total = 0
    for path in files:
        try:
            total += path.stat().st_size
        except OSError as exc:
            logger.info(f"[backup] Drive sync: could not stat {path}: {exc}")
    return total


def _weigh_headroom(client, needed: int) -> str | None:
    """Weigh the run against the account's free space, before the first upload.

    Prints the run's headroom line when the run fits. ``free`` is the quota's
    limit minus its usage, never below zero (Drive can report usage over the
    limit). An account that reports no limit passes, and the line says so.

    Args:
        client: The authenticated DriveClient the upload will use.
        needed: Bytes this run is about to upload.

    Returns:
        None when the run may go ahead, else the one sentence that refuses it:
        too little room, or a quota that could not be read.
    """
    from aipass.backup.apps.handlers.drive.quota import read_quota

    quota = read_quota(client)
    if quota["error"]:
        return f"Drive quota unavailable: {quota['error']}. Nothing uploaded."
    if quota["limit"] is None:
        console.print(f"Drive: {_human_bytes(needed)} to upload, no storage limit reported", markup=False)
        return None
    free = max(quota["limit"] - quota["usage"], 0)
    if needed > free:
        return f"Drive has {_human_bytes(free)} free; this run needs {_human_bytes(needed)}. Nothing uploaded."
    console.print(f"Drive: {_human_bytes(needed)} to upload, {_human_bytes(free)} free", markup=False)
    return None


def run_drive_sync(
    project_root: str,
    project_name: str = "",
    note: str = "",
    force: bool = False,
    show_panels: bool = True,
    verb: str = PRIMARY_COMMAND,
) -> dict:
    """Run Drive sync -- upload the snapshot store to Google Drive.

    Args:
        project_root: Absolute path to the project.
        project_name: Override project name (defaults to dir name).
        note: Note attached to uploads.
        force: Force re-upload of all files.
        show_panels: Show rich CLI output.
        verb: What was invoked, for the running file: drive_sync, or all.

    Returns:
        Dict with success, uploaded, failed, skipped, held_back,
        bytes_uploaded, duration, location, total keys. Once there is
        something to upload it also carries bytes_planned. A run refused by
        the headroom check (too little room, or an unreadable quota) has
        success False, error set to the sentence it printed as its last
        stdout line, and error_shown True, so a caller does not print it twice.
        A run stopped by request has stopped True and success False.
    """
    with catch_sigterm(), LaneProgress(project_root, PRIMARY_COMMAND, verb) as running:
        return _drive_sync_run(project_root, project_name, note, force, show_panels, verb, running)


def _drive_sync_run(
    project_root: str,
    project_name: str,
    note: str,
    force: bool,
    show_panels: bool,
    verb: str,
    running: LaneProgress,
) -> dict:
    """The Drive sync proper, inside the stop handler and the running file."""
    from aipass.backup.apps.handlers.drive.client import DriveClient
    from aipass.backup.apps.handlers.drive.floor import hold_back
    from aipass.backup.apps.handlers.drive.tracker import (
        DRIVE_LANE,
        check_needs_upload,
        load_tracker,
        save_tracker,
        set_aside_foreign_tracker,
    )
    from aipass.backup.apps.handlers.drive.upload import upload_batch

    start = time.time()

    result: dict = {
        "success": False,
        "uploaded": 0,
        "failed": 0,
        "skipped": 0,
        "held_back": 0,
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

    # 2. Build snapshot store path
    store_path = build_snapshot_path(project_root)
    result["location"] = str(store_path)
    if not store_path.exists():
        result["error"] = f"Snapshot store not found: {store_path}"
        result["duration"] = time.time() - start
        logger.warning(f"[backup] {result['error']}")
        return result

    # 3. Scan store and re-filter through .backupignore (legacy stores may
    #    contain files swept in before an ignore rule was added).
    spec = load_spec(str(project_root))
    raw_files = [f for f in store_path.rglob("*") if f.is_file()]
    kept = [f for f in raw_files if not is_ignored(str(f.relative_to(store_path)), spec)]
    ignored_count = len(raw_files) - len(kept)
    if ignored_count:
        logger.info(f"[backup] Drive sync: filtered {ignored_count} ignored files from store")

    # 3b. The never-leaves floor, a spec of its own so .backupignore cannot
    #     negate it. The snapshot keeps these files; Drive never gets them.
    all_files, result["held_back"] = hold_back(kept, store_path)
    if result["held_back"]:
        logger.info(f"[backup] Drive sync: held back {result['held_back']} files the never-leaves floor matches")

    result["total"] = len(all_files)

    if not all_files:
        result["success"] = True
        result["duration"] = time.time() - start
        if show_panels:
            console.print("[dim]No files found in snapshot store.[/dim]")
        return result

    # 4. Resolve project name
    if not project_name:
        project_name = Path(project_root).name

    # 5. Load tracker + filter. A tracker from the versioned era is moved
    #    aside first: its keys name versioned-store paths.
    set_aside_foreign_tracker(project_root)
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

    # 5b. Headroom (DPLAN-0412): weigh what is about to leave against the
    #     account's free space. A run that cannot fit, or a quota that cannot
    #     be read, uploads nothing; its sentence is the run's last stdout line
    #     and mark_command_failed() makes the verb (drive_sync, or all) exit 2.
    planned = _planned_bytes(files_to_upload)
    result["bytes_planned"] = planned
    refusal = _weigh_headroom(client, planned)
    if refusal:
        result["error"] = refusal
        result["error_shown"] = True
        result["duration"] = time.time() - start
        logger.warning(f"[backup] {refusal}")
        trail.log_operation(
            "drive_sync_refused",
            {"project_root": project_root, "bytes_planned": planned, "reason": refusal},
        )
        console.print(refusal, markup=False)
        mark_command_failed()
        return result

    running.plan(len(files_to_upload), bytes_total=planned)

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
            lane_folder=DRIVE_LANE,
            project_root=project_root,
            on_file=running.file_done,
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

    # 7b. Stopped by request: what went is tracked (saved just above), no
    #     changelog entry (lanes.drive_sync.last means a run that completed),
    #     and the stopped line is the last word.
    if batch_result.get("stopped"):
        result["stopped"] = True
        result["success"] = False
        report_stopped(
            PRIMARY_COMMAND,
            verb,
            project_root,
            done=result["uploaded"] + result["failed"],
            total=len(files_to_upload),
            failed=result["failed"],
            bytes_done=result["bytes_uploaded"],
        )
        return result

    # 8. One changelog entry per run that uploaded cleanly, the shape snapshot
    #    and versioned write; status --json reads the Drive lane's last run
    #    from it. A run with a failed upload, or with nothing to upload,
    #    writes none -- the snapshot lane's rule for a run that copied nothing.
    if result["success"]:
        run = BackupResult(
            mode=PRIMARY_COMMAND,
            project_root=project_root,
            files_copied=result["uploaded"],
            files_checked=len(all_files),
            files_skipped=skipped,
            bytes_copied=result["bytes_uploaded"],
            duration_seconds=result["duration"],
        )
        append_changelog(project_root, build_metadata(run))

    trail.log_operation(
        "drive_sync_complete",
        {
            "project_root": project_root,
            "uploaded": result["uploaded"],
            "failed": result["failed"],
            "skipped": skipped,
            "held_back": result["held_back"],
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
