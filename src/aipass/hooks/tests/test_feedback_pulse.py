# =================== AIPass ====================
# Name: test_feedback_pulse.py
# Version: 1.0.0
# Description: Tests for feedback pulse handler and toggle module
# Branch: hooks
# Layer: tests
# Created: 2026-07-18
# Modified: 2026-07-18
# =============================================

"""Tests for feedback_pulse handler and feedback toggle module."""

import json
from pathlib import Path
from unittest.mock import patch


class TestFeedbackPulseHandler:
    """Tests for the feedback_pulse prompt handler."""

    def _handler(self):
        from aipass.hooks.apps.handlers.prompt.feedback_pulse import handle

        return handle

    def test_no_session_id_returns_empty(self, monkeypatch):
        # _state_path falls back to CLAUDE_CODE_SESSION_ID — set when the suite
        # runs inside a Claude Code session, which pointed this test at a REAL
        # /tmp counter that fired the pulse every 10th run. Clear it so "no
        # session id" is actually true.
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        result = self._handler()({"session_id": ""})
        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_early_turns_return_empty(self, tmp_path):
        with patch(
            "aipass.hooks.apps.handlers.prompt.feedback_pulse._STATE_DIR",
            tmp_path,
        ):
            for i in range(10):
                result = self._handler()({"session_id": "test-session"})
                assert result["stdout"] == "", f"Turn {i} should not fire"

    def test_fires_on_turn_10(self, tmp_path):
        result = {"stdout": "", "exit_code": 0}
        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.feedback_pulse._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.hooks.apps.handlers.prompt.feedback_pulse._is_disabled",
                return_value=False,
            ),
        ):
            for i in range(11):
                result = self._handler()({"session_id": "test-fire"})

        assert "feedback" in result["stdout"].lower()
        assert "https://github.com/AIOSAI/AIPass/issues" in result["stdout"]

    def test_fires_on_turn_20(self, tmp_path):
        result = {"stdout": "", "exit_code": 0}
        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.feedback_pulse._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.hooks.apps.handlers.prompt.feedback_pulse._is_disabled",
                return_value=False,
            ),
        ):
            for i in range(21):
                result = self._handler()({"session_id": "test-fire-20"})

        assert "feedback" in result["stdout"].lower()

    def test_skips_turn_11_through_19(self, tmp_path):
        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.feedback_pulse._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.hooks.apps.handlers.prompt.feedback_pulse._is_disabled",
                return_value=False,
            ),
        ):
            for i in range(11):
                self._handler()({"session_id": "test-skip"})

            for i in range(9):
                result = self._handler()({"session_id": "test-skip"})
                assert result["stdout"] == "", f"Turn {11 + i} should not fire"

    def test_disabled_returns_empty(self, tmp_path):
        result = {"stdout": "", "exit_code": 0}
        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.feedback_pulse._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.hooks.apps.handlers.prompt.feedback_pulse._is_disabled",
                return_value=True,
            ),
        ):
            for i in range(11):
                result = self._handler()({"session_id": "test-disabled"})

        assert result["stdout"] == ""

    def test_disabled_logs_distinguishing_line(self, tmp_path, caplog):
        import logging

        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.feedback_pulse._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.hooks.apps.handlers.prompt.feedback_pulse._is_disabled",
                return_value=True,
            ),
            caplog.at_level(logging.INFO),
        ):
            for i in range(11):
                self._handler()({"session_id": "test-disabled-log"})

        assert "skipped (disabled via .aipass/feedback_off sentinel)" in caplog.text

    def test_output_is_one_line(self, tmp_path):
        result = {"stdout": "", "exit_code": 0}
        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.feedback_pulse._STATE_DIR",
                tmp_path,
            ),
            patch(
                "aipass.hooks.apps.handlers.prompt.feedback_pulse._is_disabled",
                return_value=False,
            ),
        ):
            for i in range(11):
                result = self._handler()({"session_id": "test-oneline"})

        assert "\n" not in result["stdout"]

    def test_state_file_persists(self, tmp_path):
        state_file = tmp_path / "aipass-feedback-pulse-test-persist.json"
        with patch(
            "aipass.hooks.apps.handlers.prompt.feedback_pulse._STATE_DIR",
            tmp_path,
        ):
            self._handler()({"session_id": "test-persist"})

        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["turn"] == 0

    def test_state_increments_across_calls(self, tmp_path):
        with patch(
            "aipass.hooks.apps.handlers.prompt.feedback_pulse._STATE_DIR",
            tmp_path,
        ):
            for i in range(5):
                self._handler()({"session_id": "test-incr"})

        state_file = tmp_path / "aipass-feedback-pulse-test-incr.json"
        data = json.loads(state_file.read_text())
        assert data["turn"] == 4

    def test_corrupted_state_recovers(self, tmp_path):
        state_file = tmp_path / "aipass-feedback-pulse-test-corrupt.json"
        state_file.write_text("not json")
        with patch(
            "aipass.hooks.apps.handlers.prompt.feedback_pulse._STATE_DIR",
            tmp_path,
        ):
            result = self._handler()({"session_id": "test-corrupt"})

        assert result["exit_code"] == 0

    def test_handler_exception_returns_safe(self):
        with patch(
            "aipass.hooks.apps.handlers.prompt.feedback_pulse._state_path",
            side_effect=RuntimeError("boom"),
        ):
            result = self._handler()({"session_id": "test-crash"})

        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_session_id_from_env(self, tmp_path):
        with (
            patch(
                "aipass.hooks.apps.handlers.prompt.feedback_pulse._STATE_DIR",
                tmp_path,
            ),
            patch.dict(
                "os.environ",
                {"CLAUDE_CODE_SESSION_ID": "env-session"},
            ),
        ):
            self._handler()({"session_id": ""})

        state_file = tmp_path / "aipass-feedback-pulse-env-session.json"
        assert state_file.exists()


class TestFeedbackPulseToggle:
    """Tests for the _is_disabled toggle and sentinel file."""

    def test_no_aipass_dir_is_disabled(self, tmp_path):
        from aipass.hooks.apps.handlers.prompt import feedback_pulse

        # The walk climbs to the drive root, so a real .aipass in any ancestor
        # (e.g. the CI runner's home after windows-setup installs AIPass) leaks
        # into the result — the no-dir case is only constructible by patching.
        with patch.object(feedback_pulse, "_find_aipass_dir", return_value=None):
            assert feedback_pulse._is_disabled(str(tmp_path)) is True

    def test_aipass_dir_no_sentinel_is_enabled(self, tmp_path):
        (tmp_path / ".aipass").mkdir()
        from aipass.hooks.apps.handlers.prompt.feedback_pulse import _is_disabled

        assert _is_disabled(str(tmp_path)) is False

    def test_sentinel_exists_is_disabled(self, tmp_path):
        aipass_dir = tmp_path / ".aipass"
        aipass_dir.mkdir()
        (aipass_dir / "feedback_off").touch()
        from aipass.hooks.apps.handlers.prompt.feedback_pulse import _is_disabled

        assert _is_disabled(str(tmp_path)) is True


class TestFeedbackToggleModule:
    """Tests for the feedback toggle CLI module (drone @hooks feedback)."""

    def test_handle_command_feedback_shows_status(self, capsys):
        from aipass.hooks.apps.modules.feedback import handle_command

        with patch(
            "aipass.hooks.apps.modules.feedback._sentinel",
            return_value=Path("/nonexistent/sentinel"),
        ):
            assert handle_command("feedback", []) is True

        captured = capsys.readouterr()
        assert "ENABLED" in captured.err

    def test_handle_command_feedback_disabled(self, capsys, tmp_path):
        sentinel = tmp_path / "feedback_off"
        sentinel.touch()
        from aipass.hooks.apps.modules.feedback import handle_command

        with patch(
            "aipass.hooks.apps.modules.feedback._sentinel",
            return_value=sentinel,
        ):
            assert handle_command("feedback", []) is True

        captured = capsys.readouterr()
        assert "DISABLED" in captured.err

    def test_handle_command_feedback_off(self, tmp_path):
        sentinel = tmp_path / "feedback_off"
        from aipass.hooks.apps.modules.feedback import handle_command

        with patch(
            "aipass.hooks.apps.modules.feedback._sentinel",
            return_value=sentinel,
        ):
            assert handle_command("feedback", ["off"]) is True

        assert sentinel.exists()

    def test_handle_command_feedback_on(self, tmp_path):
        sentinel = tmp_path / "feedback_off"
        sentinel.touch()
        from aipass.hooks.apps.modules.feedback import handle_command

        with patch(
            "aipass.hooks.apps.modules.feedback._sentinel",
            return_value=sentinel,
        ):
            assert handle_command("feedback", ["on"]) is True

        assert not sentinel.exists()

    def test_handle_command_feedback_on_no_sentinel(self, tmp_path):
        sentinel = tmp_path / "feedback_off"
        from aipass.hooks.apps.modules.feedback import handle_command

        with patch(
            "aipass.hooks.apps.modules.feedback._sentinel",
            return_value=sentinel,
        ):
            assert handle_command("feedback", ["on"]) is True

    def test_handle_command_feedback_help(self, capsys):
        from aipass.hooks.apps.modules.feedback import handle_command

        assert handle_command("feedback", ["--help"]) is True
        captured = capsys.readouterr()
        assert "drone @hooks feedback" in captured.err

    def test_handle_command_no_aipass_dir(self, capsys):
        from aipass.hooks.apps.modules.feedback import handle_command

        with patch(
            "aipass.hooks.apps.modules.feedback._sentinel",
            return_value=None,
        ):
            assert handle_command("feedback", []) is True

        captured = capsys.readouterr()
        assert "NO PROJECT" in captured.err

    def test_handle_command_off_no_aipass_dir(self, capsys):
        from aipass.hooks.apps.modules.feedback import handle_command

        with patch(
            "aipass.hooks.apps.modules.feedback._sentinel",
            return_value=None,
        ):
            assert handle_command("feedback", ["off"]) is True

        captured = capsys.readouterr()
        assert "No .aipass/" in captured.err

    def test_unrelated_command_returns_false(self):
        from aipass.hooks.apps.modules.feedback import handle_command

        assert handle_command("other", []) is False

    def test_state_survives_session_restart(self, tmp_path):
        """Toggle state persists on disk — survives session restarts."""
        sentinel = tmp_path / "feedback_off"
        from aipass.hooks.apps.modules.feedback import handle_command

        with patch(
            "aipass.hooks.apps.modules.feedback._sentinel",
            return_value=sentinel,
        ):
            handle_command("feedback", ["off"])

        assert sentinel.exists()

        with patch(
            "aipass.hooks.apps.modules.feedback._sentinel",
            return_value=sentinel,
        ):
            handle_command("feedback", ["on"])

        assert not sentinel.exists()
