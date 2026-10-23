# =================== AIPass ====================
# Name: support_telegram_response.py
# Description: Helpers shared by the telegram_response test files: patch targets, transcript lines, pending lookups
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Helpers for the telegram_response tests (no test_ prefix: never collected)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import json
import os
from pathlib import Path
from unittest.mock import patch

from aipass.hooks.apps.handlers.notification.telegram_response import find_pending_file


def _kept_redirect() -> dict[str, str]:
    """The json redirect a clear=True wipe must hand back, or the loggers write the live <branch>_json."""
    return {"AIPASS_TEST_LOG_DIR": os.environ["AIPASS_TEST_LOG_DIR"]}


LOGGER_PATCH = "aipass.hooks.apps.handlers.notification.telegram_response.logger"
MOD = "aipass.hooks.apps.handlers.notification.telegram_response"


def _jsonl_line(entry_type: str, text: str = "", *, sidechain: bool = False, tool_result: bool = False) -> str:
    """Build a single JSONL transcript line."""
    if tool_result and entry_type == "user":
        content = [{"type": "tool_result", "content": "ok"}]
    elif text:
        content = [{"type": "text", "text": text}]
    else:
        content = []

    entry: dict = {"type": entry_type, "message": {"content": content}}
    if sidechain:
        entry["isSidechain"] = True
    return json.dumps(entry)


def _found(tmp_path: Path, data: dict) -> bool:
    """Whether find_pending_file hands back a pending file holding data: an expired one is passed over."""
    pending_dir = tmp_path / "telegram_pending"
    pending_dir.mkdir(exist_ok=True)
    (pending_dir / "bot-1.json").write_text(json.dumps(data), encoding="utf-8")
    with (
        patch(LOGGER_PATCH),
        patch(f"{MOD}.PENDING_DIR", pending_dir),
        patch(f"{MOD}.MIRROR_DIR", tmp_path / "no_mirror"),
        patch.dict("os.environ", {"AIPASS_BOT_ID": "1"}),
    ):
        return find_pending_file() is not None


def _record_waits(monkeypatch) -> list[float]:
    """The retry waits telegram_response asks for, recorded through its _sleep seam; nothing sleeps."""
    waits: list[float] = []
    monkeypatch.setattr(f"{MOD}._sleep", waits.append)
    return waits


def _ok_result(message_id=100, text="mocked"):
    """Build a successful send/edit result dict."""
    return {"ok": True, "message_id": message_id, "text": text}
