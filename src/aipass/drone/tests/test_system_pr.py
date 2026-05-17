# =================== AIPass ====================
# Name: test_system_pr.py
# Description: Tests for devpulse_ops plugin — git module routing for pr/system-pr
# Version: 2.0.0
# Created: 2026-03-30
# Modified: 2026-05-16
# =============================================

"""Tests for devpulse_ops plugin — git module routing for pr/system-pr."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ===========================================================================
# git_module routing for pr command (replaced system-pr in S151)
# ===========================================================================


class TestGitModulePrRouting:
    """Test that git_module routes pr correctly."""

    def test_pr_in_commands(self) -> None:
        """The _COMMANDS registry includes the 'pr' verb."""
        from aipass.drone.apps.modules.git_module import _COMMANDS

        assert "pr" in _COMMANDS

    def test_system_pr_removed_from_commands(self) -> None:
        """system-pr was removed in S151."""
        from aipass.drone.apps.modules.git_module import _COMMANDS

        assert "system-pr" not in _COMMANDS

    def test_get_help_includes_pr(self) -> None:
        """Generic get_help() output mentions 'pr'."""
        from aipass.drone.apps.modules.git_module import get_help

        help_text = get_help()
        assert "pr" in help_text

    def test_get_introspective_includes_plugin(self) -> None:
        """get_introspective() output mentions the devpulse_ops plugin."""
        from aipass.drone.apps.modules.git_module import get_introspective

        intro = get_introspective()
        assert "devpulse_ops" in intro

    @patch("aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access", return_value="devpulse")
    def test_handle_system_pr_returns_unknown(self, mock_verify: MagicMock) -> None:
        """handle_command('system-pr', []) returns unknown command error."""
        from aipass.drone.apps.modules.git_module import handle_command

        result = handle_command("system-pr", [])
        assert result["exit_code"] == 1
        assert "unknown" in result["stderr"].lower()

    @patch(
        "aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access",
        side_effect=PermissionError("not authorized"),
    )
    def test_handle_system_pr_unauthorized(self, mock_verify: MagicMock) -> None:
        """handle_command propagates PermissionError as exit_code 1 with the message."""
        from aipass.drone.apps.modules.git_module import handle_command

        result = handle_command("system-pr", ["test"])
        assert result["exit_code"] == 1
        assert "not authorized" in result["stderr"]
