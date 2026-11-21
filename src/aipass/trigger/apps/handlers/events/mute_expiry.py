# =================== AIPass ====================
# Name: mute_expiry.py
# Description: medic_mute_sweep event handler - settles expired content mutes and mails their holders
# Version: 1.0.0
# Created: 2026-11-21
# Modified: 2026-11-21
# =============================================

"""
Mute Expiry Sweep

The daemon fires medic_mute_sweep every minute. An expired content mute whose branch still has a live
session re-arms; any other is dropped and its branch gets one mail with the re-mute command.

Live session: the branch's ai_mail session pointer names a transcript (Claude) or rollout file (Codex)
written within ACTIVE_WINDOW_SECONDS. OpenCode keeps one shared store with no per-branch file, so an
OpenCode branch is never re-armed: it gets the mail.
"""

import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from aipass.ai_mail import CLAUDE, CODEX, codex_thread_file, read_pointer, transcript_dir
from aipass.memory import fleet_branches
from aipass.prax import logger
from aipass.trigger.apps.handlers.events.error_detected import BRANCH_REGISTRY_FILE
from aipass.trigger.apps.handlers.json import json_handler
from aipass.trigger.apps.handlers.medic_state import DEFAULT_MUTE_SECONDS, take_expired_content_mutes

ACTIVE_WINDOW_SECONDS = 15 * 60

_send_email: Optional[Callable[..., bool]] = None


def set_send_email_callback(callback: Callable[..., bool]) -> None:
    """Wire the ai_mail delivery adapter; registry.setup_handlers sets it before events fire."""
    global _send_email
    _send_email = callback


def _branch_paths() -> Dict[str, Path]:
    """Mute name (lowercase, no @) to branch directory, from the fleet census."""
    rows = fleet_branches(repo_root=BRANCH_REGISTRY_FILE.parent, name_from="registry", strict=True)
    return {row["email"].lstrip("@").lower(): Path(row["path"]) for row in rows if row.get("email")}


def _session_file(pointer: Dict[str, Any]) -> Optional[Path]:
    """The file the pointer's session appends to while it works, or None when no per-branch file exists."""
    provider = pointer.get("provider", CLAUDE)
    session_id = pointer["session_id"]
    if provider == CODEX:
        return codex_thread_file(session_id)
    if provider == CLAUDE and pointer.get("cwd"):
        directory = transcript_dir(pointer["cwd"])
        return directory / f"{session_id}.jsonl" if directory is not None else None
    return None


def session_is_active(branch_path: Optional[Path], now: Optional[float] = None) -> bool:
    """True when the branch's current session wrote its transcript within ACTIVE_WINDOW_SECONDS."""
    if branch_path is None:
        return False
    pointer = read_pointer(branch_path)
    if pointer is None:
        return False
    session_file = _session_file(pointer)
    if session_file is None or not session_file.exists():
        return False
    age = (time.time() if now is None else now) - session_file.stat().st_mtime
    return age < ACTIVE_WINDOW_SECONDS


def expiry_mail_body(branch: str) -> str:
    """The nudge an expired mute sends: a question, never an alarm."""
    hours = DEFAULT_MUTE_SECONDS // 3600
    return (
        f"Your medic mute on @{branch} has expired, so error lines from your branch dispatch to you again.\n\n"
        f"Still working? Mute again for another {hours}h:\n\n"
        f"    drone @trigger medic mute @{branch}\n\n"
        "Finished? Nothing to do."
    )


def handle_medic_mute_sweep(**_data: Any) -> None:
    """Settle expired content mutes, then mail each dropped one; nothing is sent under the state lock."""
    paths: Dict[str, Path] = {}

    def should_rearm(name: str) -> bool:
        """Read the census once, and only when a mute has expired."""
        if not paths:
            paths.update(_branch_paths())
        return session_is_active(paths.get(name))

    dropped, rearmed = take_expired_content_mutes(should_rearm)
    if not dropped and not rearmed:
        return
    unsent: List[str] = []
    for branch in dropped:
        if _send_email is None or not _send_email(
            to_branch=f"@{branch}", subject=f"Medic mute expired: @{branch}", message=expiry_mail_body(branch)
        ):
            unsent.append(branch)
    if unsent:
        logger.warning("[MEDIC] mute expiry mail not sent to: %s", ", ".join(unsent))
    json_handler.log_operation("medic_mute_sweep", {"dropped": dropped, "rearmed": rearmed, "unsent": unsent})
