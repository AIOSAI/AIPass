# =================== AIPass ====================
# Name: upload.py
# Description: Google Drive upload engine — single + batch with threading
# Version: 1.4.0
# Created: 2026-04-16
# Modified: 2026-10-21
# =============================================

"""Google Drive upload engine."""

from __future__ import annotations

import mimetypes
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aipass.prax import logger

from ..audit import trail
from ..state.stop_flag import stop_requested
from . import tracker as tracker_mod

try:
    from googleapiclient.http import MediaFileUpload  # pyright: ignore[reportMissingImports]

    MEDIA_UPLOAD_AVAILABLE = True
except ImportError:
    logger.info("Google API HTTP library not available")
    MEDIA_UPLOAD_AVAILABLE = False
    MediaFileUpload = None  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    from .client import DriveClient

#: Failures in a row, no success between, before a batch gives up: an outage fails every file in milliseconds.
BREAKER_FAILURES = 20


def upload_single_file(
    client: DriveClient,
    local_file: Path,
    project_name: str,
    backup_root: Path,
    note: str = "",
    lane_folder: str = "",
) -> bool:
    """Upload one file with resumable MediaFileUpload, updating the tracked drive_id when there is one.

    lane_folder prefixes the Drive folder only; tracker keys stay relative to backup_root.
    """
    if not local_file.is_file():
        return False

    project_folder_id = client.get_or_create_project_folder(project_name)
    if not project_folder_id:
        return False

    try:
        rel_path = local_file.relative_to(backup_root)
    except ValueError:
        logger.info(f"File {local_file} not relative to {backup_root}")
        rel_path = Path(local_file.name)

    parent_dir = str(Path(lane_folder) / rel_path.parent)
    if parent_dir and parent_dir != ".":
        target_folder_id = client.get_or_create_nested_folder(
            project_folder_id,
            parent_dir,
        )
        if not target_folder_id:
            return False
    else:
        target_folder_id = project_folder_id

    try:
        rel_key = str(local_file.relative_to(backup_root))
    except ValueError:
        logger.info(f"File {local_file} not relative to {backup_root}, using absolute path")
        rel_key = str(local_file)

    existing_drive_id = client.file_tracker.get(rel_key, {}).get("drive_id")

    mime_type, _ = mimetypes.guess_type(str(local_file))
    if mime_type is None:
        mime_type = "application/octet-stream"

    try:
        if not MEDIA_UPLOAD_AVAILABLE:
            return False

        media = MediaFileUpload(  # type: ignore[misc]
            str(local_file),
            mimetype=mime_type,
            resumable=True,
        )

        if existing_drive_id:
            request = client.drive_service.files().update(  # type: ignore[union-attr]
                fileId=existing_drive_id,
                media_body=media,
                fields="id",
            )
        else:
            file_metadata: dict[str, Any] = {
                "name": local_file.name,
                "parents": [target_folder_id],
            }
            if note:
                file_metadata["description"] = note
            request = client.drive_service.files().create(  # type: ignore[union-attr]
                body=file_metadata,
                media_body=media,
                fields="id",
            )

        result = client._api_call(request)
        if result:
            drive_file_id = result.get("id", existing_drive_id or "")
            tracker_mod.update_entry(
                client.file_tracker,
                local_file,
                backup_root,
                drive_file_id,
            )
            trail.log_operation(
                "upload_file",
                {
                    "file": str(local_file),
                    "drive_id": drive_file_id,
                    "action": "update" if existing_drive_id else "create",
                },
            )
            return True
    except Exception as exc:
        logger.warning(f"Failed to upload {local_file}: {exc}")
        trail.log_operation(
            "upload_file_error",
            {"file": str(local_file), "error": str(exc)},
        )

    return False


def _file_size(path: Path) -> int:
    """Return file size in bytes, 0 on error."""
    try:
        return path.stat().st_size
    except OSError as exc:
        logger.info(f"Could not stat {path}: {exc}")
        return 0


def upload_batch(
    client: DriveClient,
    files: list[Path],
    project_name: str,
    backup_root: Path,
    tracker: dict,
    note: str = "",
    max_workers: int = 3,
    batch_save_interval: int = 50,
    progress_fn: Any = None,
    lane_folder: str = "",
    project_root: str | None = None,
    on_file: Any = None,
) -> dict:
    """Threaded batch upload; each thread builds its own Drive service, which is not thread-safe.

    project_root set: the tracker is saved every batch_save_interval files, so a dying run keeps what it uploaded.
    A stop cancels unstarted futures; uploads in flight finish and count; success is then False.
    So do BREAKER_FAILURES failures in a row, and "aborted" then names the last error.
    """
    if not files:
        return {"success": True, "uploaded": 0, "failed": 0}

    skipped = object()

    client.file_tracker = tracker
    uploaded = 0
    failed = 0
    bytes_uploaded = 0
    # Counted in the workers: they start the next file before the main thread sees the last one fail.
    breaker = {"in_a_row": 0, "aborted": ""}
    breaker_lock = threading.Lock()

    def _count(ok: object) -> None:
        """Reset the failure run on a success; the BREAKER_FAILURES-th failure in a row trips it."""
        with breaker_lock:
            breaker["in_a_row"] = 0 if ok else breaker["in_a_row"] + 1
            if breaker["in_a_row"] >= BREAKER_FAILURES and not breaker["aborted"]:
                breaker["aborted"] = (
                    f"Drive upload aborted after {BREAKER_FAILURES} consecutive failures: {client.last_error}"
                )

    def _upload_one(file_path: Path) -> object:
        """Upload a single file in a worker thread; ``skipped`` when a stop or the breaker came first."""
        if stop_requested() or breaker["aborted"]:
            return skipped
        if not getattr(client._thread_local, "service", None):
            client._thread_local.service = client._build_thread_service()
        ok: object = False
        try:
            ok = upload_single_file(
                client,
                file_path,
                project_name,
                backup_root,
                note=note,
                lane_folder=lane_folder,
            )
            return ok
        finally:
            _count(ok)

    def _process_future(future: object) -> object:
        """Process a completed upload future: its answer, or False when it raised."""
        try:
            return future.result()  # type: ignore[union-attr]
        except Exception as exc:
            logger.info(f"Upload future failed: {exc}")
            return False

    def _rel(path: Path) -> str:
        """The store-relative name of a file, its own path when it is outside the store."""
        try:
            return str(path.relative_to(backup_root))
        except ValueError as exc:
            logger.info(f"File {path} not relative to {backup_root}, naming it whole: {exc}")
            return str(path)

    def _maybe_batch_save(count: int) -> None:
        """Save tracker periodically during batch upload."""
        if project_root and count % batch_save_interval == 0:
            try:
                tracker_mod.save_tracker(project_root, tracker)
            except Exception as exc:
                logger.info(f"Batch tracker save failed: {exc}")

    cancelled = False
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_upload_one, f): f for f in files}
        completed = 0

        for future in as_completed(futures):
            if future.cancelled():
                continue
            answer = _process_future(future)
            if answer is skipped:
                continue
            completed += 1
            nbytes = 0
            if answer:
                uploaded += 1
                nbytes = _file_size(futures[future])
                bytes_uploaded += nbytes
            else:
                failed += 1

            if progress_fn:
                progress_fn()
            if on_file:
                on_file(_rel(futures[future]), nbytes, bool(answer))

            _maybe_batch_save(completed)

            if stop_requested() and not cancelled:
                cancelled = True
                for pending in futures:
                    pending.cancel()

    # A stop that lands after the last upload finished stopped nothing.
    stopped = stop_requested() and completed < len(files)
    aborted = breaker["aborted"]
    if aborted:
        logger.warning(f"[backup] {aborted}")

    trail.log_operation(
        "upload_batch_complete",
        {"uploaded": uploaded, "failed": failed, "total": len(files), "stopped": stopped, "aborted": bool(aborted)},
    )

    return {
        "success": failed == 0 and not stopped,
        "uploaded": uploaded,
        "failed": failed,
        "bytes_uploaded": bytes_uploaded,
        "stopped": stopped,
        "aborted": aborted,
    }
