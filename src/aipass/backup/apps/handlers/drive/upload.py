# =================== AIPass ====================
# Name: upload.py
# Description: Google Drive upload engine — single + batch with threading
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-06-12
# =============================================

"""Google Drive upload engine.

Uploads files to Drive using resumable MediaFileUpload.  Supports single
file uploads and threaded batch uploads via ThreadPoolExecutor.
"""

from __future__ import annotations

import mimetypes
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aipass.prax import logger

from ..audit import trail
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


def upload_single_file(
    client: DriveClient,
    local_file: Path,
    project_name: str,
    backup_root: Path,
    note: str = "",
) -> bool:
    """Upload one file with resumable MediaFileUpload.

    Calculates relative path from backup_root for folder structure in
    Drive.  Uses tracker for dedup (cached drive_id).  Updates or creates
    the file accordingly.

    Args:
        client: Authenticated DriveClient instance.
        local_file: Absolute path to the file to upload.
        project_name: Project name for Drive folder hierarchy.
        backup_root: Root path for computing relative file paths.
        note: Optional note for logging.

    Returns:
        True on success, False on failure.
    """
    if not local_file.is_file():
        return False

    # Get project folder
    project_folder_id = client.get_or_create_project_folder(project_name)
    if not project_folder_id:
        return False

    # Compute relative path and target folder
    try:
        rel_path = local_file.relative_to(backup_root)
    except ValueError:
        logger.info(f"File {local_file} not relative to {backup_root}")
        rel_path = Path(local_file.name)

    parent_dir = str(rel_path.parent)
    if parent_dir and parent_dir != ".":
        target_folder_id = client.get_or_create_nested_folder(
            project_folder_id,
            parent_dir,
        )
        if not target_folder_id:
            return False
    else:
        target_folder_id = project_folder_id

    # Check tracker for existing drive_id
    try:
        rel_key = str(local_file.relative_to(backup_root))
    except ValueError:
        logger.info(f"File {local_file} not relative to {backup_root}, using absolute path")
        rel_key = str(local_file)

    existing_drive_id = client.file_tracker.get(rel_key, {}).get("drive_id")

    # Detect MIME type
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
            # Update existing file
            request = client.drive_service.files().update(  # type: ignore[union-attr]
                fileId=existing_drive_id,
                media_body=media,
                fields="id",
            )
        else:
            # Create new file
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
) -> dict:
    """Threaded batch upload using ThreadPoolExecutor.

    Each thread gets its own Drive service for thread safety.

    Args:
        client: Authenticated DriveClient instance.
        files: List of files to upload.
        project_name: Project name for Drive folder hierarchy.
        backup_root: Root path for computing relative file paths.
        tracker: File tracker dict (shared, thread-safe updates).
        note: Optional note for logging.
        max_workers: Max concurrent upload threads.
        batch_save_interval: Save tracker every N uploads.
        progress_fn: Optional callback called after each upload.

    Returns:
        Dict with success, uploaded, failed counts.
    """
    if not files:
        return {"success": True, "uploaded": 0, "failed": 0}

    client.file_tracker = tracker
    uploaded = 0
    failed = 0
    bytes_uploaded = 0

    def _upload_one(file_path: Path) -> bool:
        """Upload a single file in a worker thread."""
        # Ensure thread has its own service
        if not getattr(client._thread_local, "service", None):
            client._thread_local.service = client._build_thread_service()
        return upload_single_file(
            client,
            file_path,
            project_name,
            backup_root,
            note=note,
        )

    def _process_future(future: object) -> bool:
        """Process a completed upload future. Returns True on success."""
        try:
            return bool(future.result())  # type: ignore[union-attr]
        except Exception as exc:
            logger.info(f"Upload future failed: {exc}")
            return False

    def _maybe_batch_save(count: int) -> None:
        """Save tracker periodically during batch upload."""
        if count % batch_save_interval == 0 and hasattr(client, "_project_root"):
            try:
                tracker_mod.save_tracker(client._project_root, tracker)  # type: ignore[attr-defined]
            except Exception as exc:
                logger.info(f"Batch tracker save failed: {exc}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_upload_one, f): f for f in files}
        completed = 0

        for future in as_completed(futures):
            completed += 1
            if _process_future(future):
                uploaded += 1
                bytes_uploaded += _file_size(futures[future])
            else:
                failed += 1

            if progress_fn:
                progress_fn()

            _maybe_batch_save(completed)

    trail.log_operation(
        "upload_batch_complete",
        {"uploaded": uploaded, "failed": failed, "total": len(files)},
    )

    return {
        "success": failed == 0,
        "uploaded": uploaded,
        "failed": failed,
        "bytes_uploaded": bytes_uploaded,
    }


# =============================================
