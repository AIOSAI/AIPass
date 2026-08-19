# =================== AIPass ====================
# Name: test_hooksound.py
# Version: 1.0.0
# Description: Tests for hooksound module (drone @hooks hooksound)
# Branch: hooks
# Created: 2026-05-22
# Modified: 2026-05-22
# =============================================

"""Tests for modules/hooksound.py — mute/unmute hook audio."""

from unittest.mock import patch


class TestHandleCommand:
    """Command routing tests."""

    def test_returns_false_for_unknown_command(self):
        from aipass.hooks.apps.modules.hooksound import handle_command

        assert handle_command("unknown", []) is False

    def test_routes_hooksound_command(self):
        from aipass.hooks.apps.modules.hooksound import handle_command

        with patch("aipass.hooks.apps.modules.hooksound.is_muted", return_value=False):
            assert handle_command("hooksound", []) is True

    def test_off_mutes_through_sound_module(self):
        """The flag has ONE writer — this module asks sound.py, it does not touch it."""
        from aipass.hooks.apps.modules.hooksound import handle_command

        with patch("aipass.hooks.apps.modules.hooksound.mute") as mock_mute:
            result = handle_command("hooksound", ["off"])

        assert result is True
        mock_mute.assert_called_once_with()

    def test_on_unmutes_through_sound_module(self):
        from aipass.hooks.apps.modules.hooksound import handle_command

        with patch("aipass.hooks.apps.modules.hooksound.unmute") as mock_unmute:
            result = handle_command("hooksound", ["on"])

        assert result is True
        mock_unmute.assert_called_once_with()

    def test_on_is_idempotent_when_already_unmuted(self):
        """unmute() owns the missing-flag case now, so the verb never has to check."""
        from aipass.hooks.apps.modules.hooksound import handle_command

        with patch("aipass.hooks.apps.modules.hooksound.unmute") as mock_unmute:
            assert handle_command("hooksound", ["on"]) is True
            assert handle_command("hooksound", ["on"]) is True

        assert mock_unmute.call_count == 2

    def test_status_shows_muted(self):
        from aipass.hooks.apps.modules.hooksound import handle_command

        with patch("aipass.hooks.apps.modules.hooksound.is_muted", return_value=True):
            assert handle_command("hooksound", []) is True

    def test_status_shows_active(self):
        from aipass.hooks.apps.modules.hooksound import handle_command

        with patch("aipass.hooks.apps.modules.hooksound.is_muted", return_value=False):
            assert handle_command("hooksound", []) is True

    def test_help_flag(self):
        from aipass.hooks.apps.modules.hooksound import handle_command

        assert handle_command("hooksound", ["--help"]) is True

    def test_help_word(self):
        from aipass.hooks.apps.modules.hooksound import handle_command

        assert handle_command("hooksound", ["help"]) is True


class TestPrintIntrospection:
    """Module introspection tests."""

    def test_prints_without_error(self):
        from aipass.hooks.apps.modules.hooksound import print_introspection

        with patch("aipass.hooks.apps.modules.hooksound.is_muted", return_value=False):
            print_introspection()

    def test_shows_muted_status(self):
        from aipass.hooks.apps.modules.hooksound import print_introspection

        with patch("aipass.hooks.apps.modules.hooksound.is_muted", return_value=True):
            print_introspection()
