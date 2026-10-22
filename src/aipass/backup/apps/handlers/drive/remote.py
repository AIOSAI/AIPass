# =================== AIPass ====================
# Name: remote.py
# Description: What is live on Drive at run start — the tracker heals against it, a create adopts from it
# Version: 1.0.0
# Created: 2026-10-21
# Modified: 2026-10-21
# =============================================

"""What is live on Drive at run start: Drive is the truth for what is remote, the tracker its cache."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..audit import trail
from .client import FOLDER_MIME

if TYPE_CHECKING:
    from .client import DriveClient


def list_live(client: DriveClient) -> dict[str, Any] | None:
    """Every live file the app can see, as ``{"ids": set, "by_place": {(parent_id, name): id}}``.

    The drive.file scope sees only what this app created, so one paged listing is the whole truth.
    None when a page got no answer: the reason is on ``client.last_error``.
    """
    ids: set[str] = set()
    by_place: dict[tuple[str, str], str] = {}
    token = None
    while True:
        request = client.drive_service.files().list(
            q="trashed=false",
            spaces="drive",
            fields="nextPageToken, files(id,name,parents,mimeType)",
            pageSize=1000,
            pageToken=token,
        )
        answer = client._api_call(request)
        if not isinstance(answer, dict):
            return None
        for found in answer.get("files", []):
            ids.add(found["id"])
            if found.get("mimeType") != FOLDER_MIME:
                for parent in found.get("parents", []):
                    by_place.setdefault((parent, found["name"]), found["id"])
        token = answer.get("nextPageToken")
        if not token:
            return {"ids": ids, "by_place": by_place}


def heal_tracker(tracker: dict, live_ids: set[str]) -> int:
    """Drop every entry whose drive_id Drive no longer has, so the file uploads again; how many went."""
    gone = [key for key, entry in tracker.items() if entry.get("drive_id") not in live_ids]
    for key in gone:
        del tracker[key]
    if gone:
        trail.log_operation("tracker_healed", {"gone": len(gone)})
    return len(gone)


# =============================================
