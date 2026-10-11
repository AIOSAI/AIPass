# =================== AIPass ====================
# Name: test_announce.py
# Version: 1.3.1
# Description: Tests for announce notification handler
# Branch: hooks
# Created: 2026-05-20
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/notification/announce.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — SOUND_FILE and SOUNDS_DIR, paths built once from AIPASS_HOME
# seedgo: no-test-needed(documentation) — handle()'s docstring naming a Piper voice it never plays
# seedgo: no-test-needed(stdlib) — os.environ.get and pathlib joining behind AIPASS_HOME

from aipass.hooks.apps.handlers.notification.announce import handle


class TestAnnounceHandler:
    """Core handler behavior tests."""

    def test_handle_returns_result_dict(self):
        result = handle({})

        assert isinstance(result, dict)
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_handle_sets_sound_key(self):
        result = handle({})

        assert result["sound"] == "notification sound"
