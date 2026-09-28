# =================== AIPass ====================
# Name: test_hooksound.py
# Version: 1.0.1
# Description: Tests for hooksound module (drone @hooks hooksound)
# Branch: hooks
# Created: 2026-05-22
# Modified: 2026-09-28
# =============================================

"""Tests for apps/modules/hooksound.py."""

# Mute/unmute hook audio.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — HELP_COMMANDS' display strings
# seedgo: no-test-needed(ruff) — that modules/hooksound.py parses and imports sound.py and help_flags

from unittest.mock import patch

from aipass.hooks.apps.modules.hooksound import handle_command, print_introspection


class TestHandleCommand:
    """Command routing tests."""

    def test_returns_false_for_unknown_command(self):
        assert handle_command("unknown", []) is False

    def test_routes_hooksound_command(self):
        """No args routes to introspection - and touches the flag in neither direction."""
        with (
            patch("aipass.hooks.apps.modules.hooksound.print_introspection") as mock_intro,
            patch("aipass.hooks.apps.modules.hooksound.mute") as mock_mute,
            patch("aipass.hooks.apps.modules.hooksound.unmute") as mock_unmute,
        ):
            assert handle_command("hooksound", []) is True

        mock_intro.assert_called_once_with()
        mock_mute.assert_not_called()
        mock_unmute.assert_not_called()

    def test_off_mutes_through_sound_module(self):
        """The flag has ONE writer — this module asks sound.py, it does not touch it."""
        with patch("aipass.hooks.apps.modules.hooksound.mute") as mock_mute:
            result = handle_command("hooksound", ["off"])

        assert result is True
        mock_mute.assert_called_once_with()

    def test_on_unmutes_through_sound_module(self):
        with patch("aipass.hooks.apps.modules.hooksound.unmute") as mock_unmute:
            result = handle_command("hooksound", ["on"])

        assert result is True
        mock_unmute.assert_called_once_with()

    def test_on_is_idempotent_when_already_unmuted(self):
        """unmute() owns the missing-flag case now, so the verb never has to check."""
        with patch("aipass.hooks.apps.modules.hooksound.unmute") as mock_unmute:
            assert handle_command("hooksound", ["on"]) is True
            assert handle_command("hooksound", ["on"]) is True

        assert mock_unmute.call_count == 2

    def test_status_shows_muted(self, capsys):
        with patch("aipass.hooks.apps.modules.hooksound.is_muted", return_value=True):
            assert handle_command("hooksound", []) is True

        assert "hooksound — Hook sound control (MUTED)" in capsys.readouterr().err

    def test_status_shows_active(self, capsys):
        with patch("aipass.hooks.apps.modules.hooksound.is_muted", return_value=False):
            assert handle_command("hooksound", []) is True

        assert "hooksound — Hook sound control (ACTIVE)" in capsys.readouterr().err

    def test_help_flag(self, capsys):
        with patch("aipass.hooks.apps.modules.hooksound.mute") as mock_mute:
            assert handle_command("hooksound", ["--help"]) is True

        assert "hooksound — Mute/unmute all hook audio" in capsys.readouterr().err
        mock_mute.assert_not_called()

    def test_help_word(self, capsys):
        with patch("aipass.hooks.apps.modules.hooksound.unmute") as mock_unmute:
            assert handle_command("hooksound", ["help"]) is True

        assert "hooksound — Mute/unmute all hook audio" in capsys.readouterr().err
        mock_unmute.assert_not_called()


class TestPrintIntrospection:
    """Module introspection tests."""

    def test_prints_without_error(self, capsys):
        """Unmuted, introspection reports ACTIVE.

        The pair below had no oracle - both called print_introspection and
        asserted nothing, so they passed identically whichever way is_muted
        answered. The mute state IS the thing introspection exists to report.
        """
        with patch("aipass.hooks.apps.modules.hooksound.is_muted", return_value=False):
            print_introspection()

        assert "hooksound — Hook sound control (ACTIVE)" in capsys.readouterr().err

    def test_shows_muted_status(self, capsys):
        """Muted, introspection reports MUTED - the other half of the pair."""
        with patch("aipass.hooks.apps.modules.hooksound.is_muted", return_value=True):
            print_introspection()

        assert "hooksound — Hook sound control (MUTED)" in capsys.readouterr().err
