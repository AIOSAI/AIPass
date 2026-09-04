# =================== AIPass ====================
# Name: share.py
# Description: Drive sharing — upload + permission + shareable link retrieval
# Version: 1.0.0
# Created: 2026-07-01
# Modified: 2026-07-01
# =============================================

"""Drive file sharing.

Uploads a single file to Drive (under ``AIPass Backups/Shared``),
sets a read permission, and retrieves a shareable webViewLink.
Idempotent: reuses an existing file if one is found by name.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from aipass.prax import logger

from ..audit import trail
from . import upload as upload_mod

if TYPE_CHECKING:
    from .client import DriveClient

SHARE_PROJECT_NAME = "Shared"


def _get_authenticated_email(client: DriveClient) -> str | None:
    """Derive the authenticated user's email from Drive ``about`` API."""
    try:
        request = client.drive_service.about().get(fields="user")  # type: ignore[union-attr]
        result = client._api_call(request)
        if result and result.get("user"):
            return result["user"].get("emailAddress")
    except Exception as exc:
        logger.info(f"Failed to get authenticated email: {exc}")
    return None


def upload_for_share(
    client: DriveClient,
    local_file: Path,
    note: str = "",
) -> str | None:
    """Upload a file for sharing.  Returns the Drive file ID or ``None``.

    Idempotent: checks the ``Shared`` project folder first and reuses an
    existing file (matched by name) instead of re-uploading.  Falls back
    to :func:`upload_single_file` for the actual upload.
    """
    folder_id = client.get_or_create_project_folder(SHARE_PROJECT_NAME)
    if not folder_id:
        return None

    existing = client._find_existing_file(local_file.name, folder_id)
    if existing:
        logger.info(f"File already on Drive: {existing['id']}")
        return existing["id"]

    client.file_tracker = {}
    success = upload_mod.upload_single_file(
        client,
        local_file,
        SHARE_PROJECT_NAME,
        local_file.parent,
        note=note,
    )
    if not success:
        return None

    entry = client.file_tracker.get(local_file.name, {})
    return entry.get("drive_id")


def set_share_permission(
    client: DriveClient,
    file_id: str,
    *,
    public: bool = False,
) -> str | None:
    """Set a read permission on *file_id*.

    *public* ``False`` (default): restricted to the authenticated user
    (``type=user``, ``role=reader``).  ``True``: anyone with the link
    (``type=anyone``, ``role=reader``).

    Returns the permission ID, or ``None`` on failure.
    """
    if public:
        body: dict[str, Any] = {"type": "anyone", "role": "reader"}
    else:
        email = _get_authenticated_email(client)
        if not email:
            client.last_error = "Could not determine authenticated email"
            return None
        body = {"type": "user", "role": "reader", "emailAddress": email}

    try:
        request = client.drive_service.permissions().create(  # type: ignore[union-attr]
            fileId=file_id,
            body=body,
            fields="id",
        )
        result = client._api_call(request)
        if result:
            return result.get("id")
    except Exception as exc:
        client.last_error = str(exc)
        logger.warning(f"Failed to set permission on {file_id}: {exc}")

    return None


def get_share_link(client: DriveClient, file_id: str) -> str | None:
    """Retrieve the shareable link for *file_id*.

    Prefers ``webViewLink``; falls back to ``webContentLink``.
    """
    try:
        request = client.drive_service.files().get(  # type: ignore[union-attr]
            fileId=file_id,
            fields="webViewLink,webContentLink",
        )
        result = client._api_call(request)
        if result:
            return result.get("webViewLink") or result.get("webContentLink")
    except Exception as exc:
        client.last_error = str(exc)
        logger.warning(f"Failed to get share link for {file_id}: {exc}")

    return None


def share_file(
    client: DriveClient,
    local_file: str | Path,
    *,
    public: bool = False,
    note: str = "",
) -> dict[str, Any]:
    """Upload, share, and return a link — the complete pipeline.

    Returns a dict with ``success``, ``link``, ``file_id``, and
    ``error`` keys.
    """
    local_file = Path(local_file).resolve()

    if not local_file.is_file():
        return {
            "success": False,
            "link": None,
            "file_id": None,
            "error": f"Not a file: {local_file}",
        }

    file_id = upload_for_share(client, local_file, note=note)
    if not file_id:
        return {
            "success": False,
            "link": None,
            "file_id": None,
            "error": f"Upload failed: {client.last_error or 'unknown'}",
        }

    perm_id = set_share_permission(client, file_id, public=public)
    if not perm_id:
        return {
            "success": False,
            "link": None,
            "file_id": file_id,
            "error": f"Permission failed: {client.last_error or 'unknown'}",
        }

    link = get_share_link(client, file_id)
    if not link:
        return {
            "success": False,
            "link": None,
            "file_id": file_id,
            "error": f"Link retrieval failed: {client.last_error or 'unknown'}",
        }

    trail.log_operation(
        "share_file",
        {
            "file": str(local_file),
            "file_id": file_id,
            "public": public,
            "link": link,
        },
    )

    return {"success": True, "link": link, "file_id": file_id, "error": None}


# =============================================
