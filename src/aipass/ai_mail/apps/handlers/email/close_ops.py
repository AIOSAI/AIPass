# =================== AIPass ====================
# Name: close_ops.py
# Description: Email Close Operations Handler
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""
Email Close Operations Handler
"""

from pathlib import Path
from typing import List, Tuple, Callable, Optional

from aipass.prax import logger
from aipass.ai_mail.apps.handlers.json import json_handler


def batch_close(
    branch_path: Path,
    message_ids: List[str],
    mark_closed_fn: Callable,
) -> Tuple[List[Tuple[str, bool, str]], int, int]:
    """Close multiple emails by ID.

    Returns (results, closed_count, failed_count); results holds (message_id, success, message).
    """
    json_handler.log_operation("batch_close", {"branch_path": str(branch_path), "count": len(message_ids)})
    batch_mode = len(message_ids) > 1
    results = []
    closed_count = 0
    failed_count = 0

    for message_id in message_ids:
        success, message = mark_closed_fn(branch_path, message_id, skip_post_ops=batch_mode)
        results.append((message_id, success, message))
        if success:
            closed_count += 1
        else:
            failed_count += 1

    return results, closed_count, failed_count


def batch_close_post_ops(
    branch_path: Path,
    update_central_fn: Optional[Callable] = None,
    purge_deleted_fn: Optional[Callable] = None,
) -> None:
    """Run post-operations after a batch close (central update + purge)."""
    if update_central_fn:
        try:
            update_central_fn()
        except Exception as e:
            logger.warning("[close] update_central_fn failed: %s", e)
    if purge_deleted_fn:
        try:
            mailbox_path = branch_path / ".ai_mail.local"
            purge_deleted_fn(mailbox_path)
        except Exception as e:
            logger.warning("[close] purge_deleted_fn failed for %s: %s", branch_path, e)
