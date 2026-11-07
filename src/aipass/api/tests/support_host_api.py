# =================== AIPass ====================
# Name: support_host_api.py
# Description: Shared helpers for the host API's test files (test_host_api*.py)
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-11-05
# =============================================

"""Helpers shared by the host API test files: config stand-ins, and a fake baud binary for the agent chat lane."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that the module parses and imports

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional

from aipass.api.apps.handlers.host import config as host_config

# An address in TEST-NET-3 (RFC 5737). Guaranteed not to be a real interface.
UNHELD_ADDRESS = "203.0.113.7"
TAILNET_SHAPED = "100.64.0.1"


def _face_bundle(directory: Path) -> Path:
    """A directory shaped like @baud's built phone bundle: phone.html at its root."""
    directory.mkdir(parents=True)
    (directory / host_config.FACE_ENTRY).write_text("<!doctype html>", encoding="utf-8")
    return directory


def _baud_binary(path: Path, mode: int = 0o755) -> Path:
    """A stand-in baud binary: a regular file with the given mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(mode)
    return path


def agent_row(name: str = "devpulse", provider: str = "claude", session: str = "s-1", **extra: Any) -> dict:
    """One @baud roster row, the fields agent_chat reads; a live interactive seat unless *extra* says otherwise."""
    row = {
        "name": name,
        "project": "AIPASS",
        "path": f"/srv/aipass/{name}",
        "provider": provider,
        "run": {"session_id": session},
        "resume_id": session,
        "interactive": True,
        "dispatched": False,
        "own_room_live": True,
        "subagents": 0,
    }
    row.update(extra)
    return row


class FakeBaud:
    """subprocess.run at the baud binary's edge: --roster and --snapshot answer *rows*, --send-room is recorded.
    The send numbered *fail_at* (1-based) answers @baud's refusal envelope."""

    def __init__(self, rows: List[dict], fail_at: Optional[int] = None) -> None:
        self.rows = rows
        self.fail_at = fail_at
        self.sends: List[List[str]] = []
        self.verbs: List[str] = []

    def __call__(self, command: List[str], **kwargs: Any) -> SimpleNamespace:
        self.verbs.append(command[1])
        if command[1] == "--send-room":
            self.sends.append(list(command[2:]))
            sent = len(self.sends) != self.fail_at
            body: dict = {"sent": sent, "error": None if sent else "the room refused the keys"}
        else:
            body = {"project": "AIPASS", "branches": self.rows, "error": None}
        return SimpleNamespace(returncode=0, stdout=json.dumps(body), stderr="")

    def payloads(self) -> List[List[str]]:
        """Each send's payload (--text <s> or --key <K>), the room's name and project stripped."""
        return [send[3:] for send in self.sends]
