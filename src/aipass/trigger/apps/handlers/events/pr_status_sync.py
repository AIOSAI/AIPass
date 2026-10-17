# =================== AIPass ====================
# Name: pr_status_sync.py
# Description: PR event handlers — sync STATUS.md on PR create/merge
# Version: 1.1.0
# Created: 2026-03-30
# Modified: 2026-10-17
# =============================================

"""
PR Status Sync Event Handlers
"""

import subprocess
from typing import Any

from aipass.trigger.apps.config import TRIGGER_ROOT, trail_logger
from aipass.trigger.apps.handlers.json import json_handler

# Not prax: a prax line would be watched and fired back here; watchers skip `.jsonl`.
logger = trail_logger(TRIGGER_ROOT / "logs" / "pr_status_sync_handler.jsonl")


def _run_status_sync(reason: str) -> None:
    """Fire-and-forget: run drone @prax status sync."""
    try:
        subprocess.Popen(
            ["drone", "@prax", "status", "sync"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info(f"status sync launched ({reason})")
    except Exception as exc:
        logger.info(f"status sync failed ({reason}): {exc}")


def handle_pr_created(
    branch: str | None = None,
    pr_url: str | None = None,
    **kwargs: Any,
) -> None:
    """Handle pr_created event — trigger STATUS.md sync."""
    _run_status_sync(f"pr_created by {branch or 'unknown'}")
    json_handler.log_operation(
        "pr_created_event",
        {
            "branch": branch or "unknown",
            "pr_url": pr_url or "",
        },
    )


def handle_pr_merged(
    pr_number: str | None = None,
    title: str | None = None,
    **kwargs: Any,
) -> None:
    """Handle pr_merged event — trigger STATUS.md sync."""
    _run_status_sync(f"pr_merged #{pr_number or '?'}")
    json_handler.log_operation(
        "pr_merged_event",
        {
            "pr_number": pr_number or "",
            "title": title or "",
        },
    )
