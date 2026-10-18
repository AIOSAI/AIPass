# =================== AIPass ====================
# Name: test.py
# Description: Drive connectivity test — auth + folder access verification
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-10-17
# =============================================

"""Drive connectivity test."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..audit import trail

if TYPE_CHECKING:
    from .client import DriveClient


def test_connectivity(client: DriveClient) -> dict:
    """Test Drive connectivity (auth + folder access); returns success, folder_id and error keys."""
    result: dict = {
        "success": False,
        "folder_id": None,
        "error": None,
    }

    if not client.authenticate():
        result["error"] = client.last_error or "Authentication failed"
        trail.log_operation(
            "test_connectivity",
            {"success": False, "step": "auth", "error": result["error"]},
        )
        return result

    folder_id = client.get_or_create_backup_folder()
    if not folder_id:
        result["error"] = client.last_error or "Failed to access backup folder"
        trail.log_operation(
            "test_connectivity",
            {"success": False, "step": "folder", "error": result["error"]},
        )
        return result

    result["success"] = True
    result["folder_id"] = folder_id
    trail.log_operation(
        "test_connectivity",
        {"success": True, "folder_id": folder_id},
    )
    return result
