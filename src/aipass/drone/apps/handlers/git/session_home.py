# =================== AIPass ====================
# Name: session_home.py
# Description: Where the running agent session started, read from its transcript
# Version: 1.0.0
# Created: 2026-10-26
# Modified: 2026-10-26
# =============================================

"""Where the running agent session started, from the transcript Claude Code files under its launch directory.

A ``cd`` cannot move it, and a second session on the seat cannot overwrite it as it does ``session.json``.
"""

from __future__ import annotations

import os
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler

# shortcut: Claude Code only; a Codex or plain shell has no id and stays cwd-bound, upgrade when Codex exports one.
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"

UNPLACED = "an unplaced session"


def session_id() -> str:
    """The running agent session's id, or '' when the caller is no agent session."""
    return os.environ.get(SESSION_ENV, "").strip()


def _transcript_dir(directory: Path) -> Path | None:
    """@ai_mail's encoding of a launch directory into Claude's projects dir; None when it cannot be named."""
    from aipass.ai_mail.apps.modules.door_session_pointer import transcript_dir

    return transcript_dir(directory)


def launched_within(sid: str, seat: Path, project_root: Path) -> bool:
    """True when session *sid* started at *seat* or at a directory above it inside *project_root*.

    Fails closed: a transcript that cannot be looked for places the session nowhere.
    """
    candidates = [seat, *seat.parents]
    try:
        for directory in candidates:
            if directory != project_root and not directory.is_relative_to(project_root):
                break
            transcripts = _transcript_dir(directory)
            if transcripts is not None and (transcripts / f"{sid}.jsonl").is_file():
                json_handler.log_operation("git_session_placed", {"session": sid, "launched_at": str(directory)})
                return True
    except Exception as exc:
        logger.warning("git session fence: cannot look for session %s's transcript: %s", sid, exc)
    return False


def stamp() -> dict:
    """The running session for a log record: its id and where it started, empty when there is none."""
    sid = session_id()
    return {"id": sid, "started_in": describe(sid)} if sid else {}


def describe(sid: str) -> str:
    """The launch directory of session *sid* as Claude encodes it, home shortened to '~', else UNPLACED."""
    if not sid:
        return ""
    try:
        projects = _transcript_dir(Path.home())
        if projects is None:
            return UNPLACED
        home_name = projects.name
        names = sorted(path.parent.name for path in projects.parent.glob(f"*/{sid}.jsonl"))
    except Exception as exc:
        logger.warning("git session fence: cannot name session %s's launch directory: %s", sid, exc)
        return UNPLACED
    if not names:
        return UNPLACED
    return ", ".join("~" + name[len(home_name) :] if name.startswith(home_name) else name for name in names)
