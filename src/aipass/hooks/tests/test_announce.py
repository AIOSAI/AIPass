# =================== AIPass ====================
# Name: test_announce.py
# Version: 1.3.2
# Description: Tests for announce notification handler
# Branch: hooks
# Created: 2026-05-20
# Modified: 2026-11-15
# =============================================

"""Tests for apps/handlers/notification/announce.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(documentation) — handle()'s docstring naming a Piper voice it never plays

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
