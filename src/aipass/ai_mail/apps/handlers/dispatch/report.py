# =================== AIPass ====================
# Name: report.py
# Description: Dispatch Completion Report
# Version: 1.0.1
# Created: 2026-08-22
# Modified: 2026-10-17
# =============================================

"""The completion report — what the finishing agent says about its own run.

Reference: docs/dispatch_register_and_feed.md
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root

REPORTS_DIRNAME = "dispatch_reports"

# Set on the spawn env by wake.py and read at send time to stamp the agent's mail.
DISPATCH_ID_ENV = "AIPASS_DISPATCH_ID"

REPORTS_MAX_FILES = 400
REPORTS_KEEP_FILES = 200

RESULT_EXCERPT_CHARS = 600


def reports_dir(repo_root: Optional[Path] = None) -> Path:
    """Where completion reports wait to be read.

    A caller who passes ``repo_root`` is never handed the live directory.
    """
    root = find_repo_root()
    resolved = root / ".aipass" / REPORTS_DIRNAME
    if repo_root is None:
        return resolved

    return repo_root / resolved.relative_to(root)


def memories_edited(branch_path: Path, since: float) -> bool:
    """Whether any ``.trinity`` memory file was WRITTEN after *since*.

    Detects a write, not a good one. Raises OSError if unlistable: False would mean "untouched".
    """
    trinity = Path(branch_path) / ".trinity"
    candidates = list(trinity.glob("*.json"))

    for memory_file in candidates:
        try:
            if memory_file.stat().st_mtime > since:
                return True
        except OSError as e:
            logger.warning("[report] could not stat %s: %s", memory_file, e)

    return False


def emails_sent(branch_path: Path, dispatch_id: Optional[str]) -> List[Dict[str, str]]:
    """Every mail this dispatch sent, read from the sender's own sent records.

    Attribution is by the stamped dispatch_id, never by mtime. Raises OSError if unlistable.
    """
    if not dispatch_id:
        return []

    sent_folder = Path(branch_path) / ".ai_mail.local" / "sent"
    records = sorted(sent_folder.glob("*.json"))

    found = []
    for record in records:
        try:
            data = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("[report] unreadable sent record %s: %s", record, e)
            continue

        if data.get("dispatch_id") != dispatch_id:
            continue

        found.append(
            {
                "to": str(data.get("to", "")),
                "kind": "reply" if data.get("in_reply_to") else "send",
                "subject": str(data.get("subject", "")),
            }
        )

    return found


def build_report(
    dispatch_id: Optional[str],
    sender: str,
    target: str,
    branch_path: Path,
    start_time: float,
    duration: int,
    exit_code: int,
    status: str,
    attempts: List[Dict],
    bg_orphaned: bool,
    max_turns_hit: bool,
    wake_result: str,
    result_json: Optional[Dict] = None,
) -> Dict:
    """Assemble the completion report from what is already known at the terminal moment.

    bg_orphaned/max_turns_hit always ship beside emails_sent: they explain a zero. A failed listing is None.
    """
    parsed = result_json or {}

    sent: Optional[List[Dict[str, str]]]
    try:
        sent = emails_sent(branch_path, dispatch_id)
    except OSError as e:
        logger.warning("[report] sent mail of %s could not be listed, recorded as unknown: %s", branch_path, e)
        sent = None

    edited: Optional[bool]
    try:
        edited = memories_edited(branch_path, start_time)
    except OSError as e:
        logger.warning("[report] memories of %s could not be listed, recorded as unknown: %s", branch_path, e)
        edited = None

    return {
        "dispatch_id": dispatch_id,
        "sender": sender,
        "target": target,
        "dispatched_at": datetime.fromtimestamp(start_time).astimezone().isoformat(),
        "reported_at": datetime.now().astimezone().isoformat(),
        "duration_s": duration,
        "exit_code": exit_code,
        "status": status,
        "attempts": len(attempts),
        "bg_orphaned": bg_orphaned,
        "max_turns_hit": max_turns_hit,
        "wake_result": wake_result,
        "total_cost_usd": parsed.get("total_cost_usd"),
        "output_tokens": _output_tokens(parsed),
        "num_turns": parsed.get("num_turns"),
        "result_excerpt": str(parsed.get("result", ""))[:RESULT_EXCERPT_CHARS],
        "memories_edited": edited,
        "emails_sent": sent,
        "agents_contacted": None if sent is None else sorted({mail["to"] for mail in sent if mail.get("to")}),
    }


def _output_tokens(parsed: Dict) -> Optional[int]:
    """Output tokens from the result JSON's usage block, or None when absent."""
    usage = parsed.get("usage")
    if isinstance(usage, dict):
        return usage.get("output_tokens")
    return None


def write_report(report: Dict, repo_root: Optional[Path] = None) -> Optional[str]:
    """Write the report where it can wait, and prune the directory's tail.

    None means a LOST DISPATCH RECORD: the caller must say so at warning level.
    """
    dispatch_id = report.get("dispatch_id") or "unregistered"
    json_handler.log_operation("write_dispatch_report", {"dispatch_id": dispatch_id})

    directory = reports_dir(repo_root)
    path = directory / f"{dispatch_id}.json"

    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        logger.error("[report] could not write %s: %s", path, e)
        return None

    _prune_reports(directory)
    return str(path)


def _prune_reports(directory: Path) -> int:
    """Drop the oldest reports once the directory passes its ceiling."""
    try:
        reports = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime)
    except OSError as e:
        logger.warning("[report] could not list %s for prune: %s", directory, e)
        return 0

    if len(reports) <= REPORTS_MAX_FILES:
        return 0

    removed = 0
    for stale in reports[: len(reports) - REPORTS_KEEP_FILES]:
        try:
            stale.unlink()
            removed += 1
        except OSError as e:
            logger.warning("[report] could not prune %s: %s", stale, e)

    if removed:
        logger.info("[report] pruned %d old reports from %s", removed, directory)

    return removed


def fire_completed(dispatch_id: Optional[str], sender: str, target: str, report_path: Optional[str]) -> bool:
    """Push the completion to in-process consumers via @trigger's existing bus.

    In-process only: the feed line is what carries the event to other processes.
    """
    try:
        from aipass.trigger.apps.modules.core import trigger

        trigger.fire(
            "dispatch_completed",
            dispatch_id=dispatch_id,
            sender=sender,
            target=target,
            report_path=report_path,
        )
        return True
    except Exception as e:
        logger.warning("[report] dispatch_completed trigger fire failed: %s", e)
        return False


def current_dispatch_id() -> Optional[str]:
    """This process's own dispatch id, or None when not running under one."""
    value = os.environ.get(DISPATCH_ID_ENV, "").strip()
    return value or None


def stamp_dispatch_id(email_data: Dict) -> Dict:
    """Stamp a sent record with the dispatch that authored it, if there is one.

    The one stamping site for both sends and replies; do not hand-roll a copy.
    """
    dispatch_id = current_dispatch_id()
    if dispatch_id:
        email_data["dispatch_id"] = dispatch_id
    return email_data
