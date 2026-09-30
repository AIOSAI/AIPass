# =================== AIPass ====================
# Name: test_system_pr.py
# Description: Tests for devpulse_ops plugin — git module routing for pr/system-pr
# Version: 2.0.1
# Created: 2026-03-30
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/git_module.py routing of the pr verb and the retired system-pr."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the wording of get_introspective()'s handler roster beyond the plugin name

from __future__ import annotations

from unittest.mock import MagicMock, patch

from aipass.drone.apps.modules.git_module import get_help, get_introspective, handle_command

_AUTH = "aipass.drone.apps.plugins.devpulse_ops.auth.verify_git_access"


def _available_verbs(stderr: str) -> list[str]:
    """The verb roster an unknown-command refusal prints after 'Available: '."""
    return stderr.split("Available: ", 1)[1].split(", ")


# ===========================================================================
# git_module routing for pr command (replaced system-pr in S151)
# ===========================================================================


class TestGitModulePrRouting:
    """Test that git_module routes pr correctly."""

    @patch(_AUTH, return_value="devpulse")
    def test_pr_is_offered_among_the_available_verbs(self, mock_verify: MagicMock) -> None:
        """Mutant: 'pr' dropped from _COMMANDS — the refusal's roster stops offering it."""
        result = handle_command("system-pr", ["x"])
        assert "pr" in _available_verbs(result["stderr"])
        mock_verify.assert_called_once_with("system-pr")

    @patch(_AUTH, return_value="devpulse")
    def test_system_pr_is_not_offered_among_the_available_verbs(self, mock_verify: MagicMock) -> None:
        """Mutant: "system-pr" added back to _COMMANDS — the roster advertises a retired verb."""
        result = handle_command("system-pr", ["y"])
        assert "system-pr" not in _available_verbs(result["stderr"])
        mock_verify.assert_called_once_with("system-pr")

    def test_get_help_includes_pr(self) -> None:
        """Generic get_help() output mentions 'pr'."""
        help_text = get_help()
        assert "pr" in help_text

    def test_get_introspective_includes_plugin(self) -> None:
        """get_introspective() output mentions the devpulse_ops plugin."""
        intro = get_introspective()
        assert "devpulse_ops" in intro

    @patch(_AUTH, return_value="devpulse")
    def test_handle_system_pr_returns_unknown(self, mock_verify: MagicMock) -> None:
        """handle_command('system-pr', []) returns unknown command error."""
        result = handle_command("system-pr", [])
        assert result["exit_code"] == 1
        assert "unknown" in result["stderr"].lower()

    @patch(_AUTH, side_effect=PermissionError("not authorized"))
    def test_handle_system_pr_unauthorized(self, mock_verify: MagicMock) -> None:
        """handle_command propagates PermissionError as exit_code 1 with the message."""
        result = handle_command("system-pr", ["test"])
        assert result["exit_code"] == 1
        assert "not authorized" in result["stderr"]
