# =================== AIPass ====================
# Name: pr_status_sync.py
# Description: PR event handlers — sync STATUS.md on PR create/merge
# Version: 1.1.0
# Created: 2026-03-30
# Modified: 2026-08-09
# =============================================

"""
PR Status Sync Event Handlers

Handles pr_created and pr_merged events by running
'drone @prax status sync' in a fire-and-forget subprocess.

Events:
    pr_created  — fired when a PR is opened
        data: {branch: str, pr_url: str}
    pr_merged   — fired when a PR is merged
        data: {pr_number: str, title: str}
"""

import subprocess
from typing import Any

from aipass.trigger.apps.config import TRIGGER_ROOT, trail_logger
from aipass.trigger.apps.handlers.json import json_handler

# Deliberately NOT prax: this handler runs on the event path the log watchers
# read, so a line through prax would be detected and fired straight back at it.
# The sidecar is `.jsonl`, which the watchers skip — they read only `*.log`.
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
    """Handle pr_created event — trigger STATUS.md sync.

    Args:
        branch: Branch that created the PR
        pr_url: URL of the created PR
        **kwargs: Additional event data (ignored)
    """
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
    """Handle pr_merged event — trigger STATUS.md sync.

    Args:
        pr_number: PR number that was merged
        title: PR title
        **kwargs: Additional event data (ignored)
    """
    _run_status_sync(f"pr_merged #{pr_number or '?'}")
    json_handler.log_operation(
        "pr_merged_event",
        {
            "pr_number": pr_number or "",
            "title": title or "",
        },
    )
