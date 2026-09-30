# =================== AIPass ====================
# Name: test_tool_sound.py
# Version: 1.3.1
# Description: Tests for tool_sound notification handler
# Branch: hooks
# Created: 2026-05-19
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/notification/tool_sound.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that tool_sound.py parses and imports, ruff and collection cover it
# seedgo: no-test-needed(documentation) — handle()'s docstring, the documentation standard covers it
# seedgo: no-test-needed(generated) — the spoken audio; handle() only returns the text, the TTS layer renders it

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
