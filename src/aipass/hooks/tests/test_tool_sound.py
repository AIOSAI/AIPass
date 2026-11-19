# =================== AIPass ====================
# Name: test_tool_sound.py
# Version: 1.4.0
# Description: Tests for tool_sound notification handler
# Branch: hooks
# Created: 2026-05-19
# Modified: 2026-11-17
# =============================================

"""Tests for apps/handlers/notification/tool_sound.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that tool_sound.py parses and imports, ruff and collection cover it
# sentry: no-test-needed(documentation) — handle()'s docstring, the documentation standard covers it
# sentry: no-test-needed(generated) — the spoken audio; handle() only returns the text, the TTS layer renders it

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.hooks.apps.handlers.notification import tool_sound
from aipass.hooks.apps.handlers.notification.tool_sound import handle


class TestToolSoundHandler:
    """Core handler behavior tests."""

    def test_handle_returns_result_dict(self):
        result = handle({"tool_name": "Bash"})

        assert isinstance(result, dict)
        assert "stdout" in result
        assert "exit_code" in result
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_sound_key_includes_tool_name(self):
        result = handle({"tool_name": "Edit"})

        assert result["sound"] == "tool sound: Edit"

    def test_no_sound_when_no_tool_name(self):
        result = handle({})

        assert result.get("sound", "") == ""

    def test_no_sound_when_empty_tool_name(self):
        result = handle({"tool_name": ""})

        assert result.get("sound", "") == ""


class TestEveryCallLeavesATrailEntry:
    """Each handle() call appends one entry to tool_sound's own json trail: exit code and seat, never the tool input."""

    COMMAND = "echo do-not-record-me"

    @pytest.fixture
    def trail(self, tmp_path, monkeypatch) -> Path:
        monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
        return tmp_path / "hooks" / "hooks_json" / "tool_sound_log.json"

    def _call(self, seat: str) -> dict:
        return handle({"tool_name": "Bash", "tool_input": {"command": self.COMMAND}, "cwd": seat})

    def test_a_call_writes_its_exit_code_and_seat_and_not_the_tool_input(self, trail: Path, tmp_path):
        self._call(str(tmp_path))
        text = trail.read_text(encoding="utf-8")
        assert [(entry["operation"], entry["data"]) for entry in json.loads(text)] == [
            ("handle", {"exit_code": 0, "seat": str(tmp_path)})
        ]
        assert "do-not-record-me" not in text

    def test_a_trail_that_cannot_be_written_changes_no_result(self, trail: Path, tmp_path):
        with patch.object(tool_sound.json_handler, "log_operation", return_value=False) as logged:
            result = self._call(str(tmp_path))
        assert result == {"stdout": "", "exit_code": 0, "sound": "tool sound: Bash"}
        assert logged.call_count == 1
        assert not trail.exists()
