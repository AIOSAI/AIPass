# =================== AIPass ====================
# Name: quota.py
# Description: Drive account quota — about.get storageQuota through an authenticated client
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================

"""Drive account quota.

One read, shared by drive_stats (which prints it) and drive_sync (which weighs
a run against it before the first upload, DPLAN-0412). Drive sends the numbers
as strings and leaves ``limit`` out for an account with unlimited storage; an
absent field is reported as None, never filled in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aipass.prax import logger

from ..audit import trail

if TYPE_CHECKING:
    from .client import DriveClient


def read_quota(client: DriveClient) -> dict[str, Any]:
    """Read the account's storage usage and limit through ``about.get(fields="storageQuota")``.

    Args:
        client: An authenticated DriveClient.

    Returns:
        Dict with ``usage`` (int bytes, or None), ``limit`` (int bytes, or None
        when Drive reports no limit) and ``error`` (None, or the reason the
        quota could not be read -- then ``usage`` and ``limit`` are None).
        A read that succeeds writes one ``drive_quota_read`` trail row.
    """
    request = client.drive_service.about().get(fields="storageQuota")
    answer = client._api_call(request)
    quota = answer.get("storageQuota") if isinstance(answer, dict) else None
    if not isinstance(quota, dict) or quota.get("usage") is None:
        reason = (
            (client.last_error or "about.get got no answer")
            if answer is None
            else "about.get returned no storageQuota usage"
        )
        return {"usage": None, "limit": None, "error": reason}
    try:
        usage = int(quota["usage"])
        limit = None if quota.get("limit") is None else int(quota["limit"])
    except (TypeError, ValueError) as exc:
        logger.info(f"[backup] Drive quota not a number: {quota!r} ({exc})")
        return {"usage": None, "limit": None, "error": "about.get returned a storageQuota that is not a number"}
    trail.log_operation("drive_quota_read", {"usage": usage, "limit": limit})
    return {"usage": usage, "limit": limit, "error": None}


# =============================================
