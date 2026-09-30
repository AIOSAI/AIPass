# =================== AIPass ====================
# Name: test_stop_sound.py
# Version: 1.3.1
# Description: Tests for stop_sound notification handler
# Branch: hooks
# Created: 2026-05-20
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/notification/stop_sound.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — AIPASS_HOME, SOUNDS_DIR and SOUND_FILE's path text
# seedgo: no-test-needed(documentation) — that handle() carries a docstring
# seedgo: no-test-needed(ruff) — that the module parses and imports

from aipass.hooks.apps.handlers.notification.stop_sound import handle


class TestStopSoundHandler:
    """Core handler behavior tests."""

    def test_handle_returns_result_dict(self):
        result = handle({})

        assert isinstance(result, dict)
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_handle_sets_sound_key(self):
        result = handle({})

        assert result["sound"] == "stop sound"

    def test_handle_no_sound_when_stop_hook_active(self):
        result = handle({"stop_hook_active": True})

        assert result.get("sound", "") == ""
        assert result["exit_code"] == 0
