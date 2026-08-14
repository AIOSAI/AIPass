# =================== AIPass ====================
# Name: test_auto_process.py
# Version: 1.2.0
# Description: Tests for auto_process lifecycle handler (TDPLAN-0005, DPLAN-0294 phase 1b)
# Branch: hooks
# Created: 2026-06-06
# Modified: 2026-08-14
# =============================================

"""Tests for handlers/lifecycle/auto_process.py.

DPLAN-0294 phase 1b: the handler no longer does the work inline. It calls
@memory's spawn_background(), which detaches a child and returns immediately.
The old pool/rollover counters are gone at hook time — the child reports them
to memory_json/auto_process_log.json — so nothing here asserts on them.

The session guard now means "kicked once this session", not "ran once".
"""

import logging
from unittest.mock import patch, MagicMock


MODULE = "aipass.hooks.apps.handlers.lifecycle.auto_process"


def _make_mock_module(**spawn_return):
    """Mock @memory's module with spawn_background() returning the given dict."""
    mock_module = MagicMock()
    mock_module.spawn_background.return_value = spawn_return or {
        "success": True,
        "skipped": False,
        "pid": 4242,
    }
    return mock_module


class TestAutoProcessHandler:
    def test_success_returns_exit_code_0(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module(success=True, skipped=False, pid=4242)

        with patch(f"{MODULE}._already_ran_this_session", return_value=False):
            with patch(f"{MODULE}._mark_session_ran"):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module):
                    result = handle({})

        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert result["sound"] == "auto process"

    def test_calls_spawn_background_and_never_the_inline_worker(self):
        """The whole point of 1b: the prompt lane must not run the work itself."""
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module()

        with patch(f"{MODULE}._already_ran_this_session", return_value=False):
            with patch(f"{MODULE}._mark_session_ran"):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module) as mock_import:
                    handle({})

        mock_import.assert_called_once_with("aipass.memory.apps.handlers.intake.auto_process")
        mock_module.spawn_background.assert_called_once()
        mock_module.auto_process.assert_not_called()

    def test_logs_the_pid_on_spawn(self, caplog):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module(success=True, skipped=False, pid=31337)

        with patch(f"{MODULE}._already_ran_this_session", return_value=False):
            with patch(f"{MODULE}._mark_session_ran"):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module):
                    with caplog.at_level(logging.INFO):
                        handle({})

        assert "31337" in caplog.text

    def test_refusal_logs_the_reason_and_stays_silent(self, caplog):
        """A run already live is a non-event: report why, play no sound."""
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module(success=True, skipped=True, reason="already running (pid 99)", pid=None)

        with patch(f"{MODULE}._already_ran_this_session", return_value=False):
            with patch(f"{MODULE}._mark_session_ran"):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module):
                    with caplog.at_level(logging.INFO):
                        result = handle({})

        assert result["exit_code"] == 0
        assert "sound" not in result
        assert "already running (pid 99)" in caplog.text

    def test_spawn_failure_surfaces_with_exit_code_1(self, caplog):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module(success=False, error="Cannot open child log", pid=None)

        with patch(f"{MODULE}._already_ran_this_session", return_value=False):
            with patch(f"{MODULE}._mark_session_ran"):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module):
                    with caplog.at_level(logging.ERROR):
                        result = handle({})

        assert result["exit_code"] == 1
        assert result["stdout"] == ""
        assert "sound" not in result
        assert "Cannot open child log" in caplog.text

    def test_no_pool_or_rollover_counters_are_read_at_hook_time(self, caplog):
        """The child owns those numbers now — the hook must not invent them."""
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module()

        with patch(f"{MODULE}._already_ran_this_session", return_value=False):
            with patch(f"{MODULE}._mark_session_ran"):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module):
                    with caplog.at_level(logging.INFO):
                        handle({})

        assert "pool=" not in caplog.text
        assert "rollover=" not in caplog.text

    def test_import_error_surfaces_with_exit_code_1(self, caplog):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        with patch(f"{MODULE}._already_ran_this_session", return_value=False):
            with patch(f"{MODULE}.importlib.import_module", side_effect=ImportError("no module")):
                with caplog.at_level(logging.ERROR):
                    result = handle({})

        assert result["exit_code"] == 1
        assert result["stdout"] == ""
        assert "no module" in caplog.text

    def test_runtime_error_surfaces_with_exit_code_1(self, caplog):
        """spawn_background() promises never to raise — crash isolation does not take promises."""
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = MagicMock()
        mock_module.spawn_background.side_effect = RuntimeError("fork failed")

        with patch(f"{MODULE}._already_ran_this_session", return_value=False):
            with patch(f"{MODULE}.importlib.import_module", return_value=mock_module):
                with caplog.at_level(logging.ERROR):
                    result = handle({})

        assert result["exit_code"] == 1
        assert "fork failed" in caplog.text

    def test_fires_on_precompact_event_key(self):
        """Verify auto_process is wired in hooks.json under PreCompact."""
        import json
        from pathlib import Path

        hooks_json = Path(__file__).resolve().parent.parent.parent.parent.parent / ".aipass" / "hooks.json"
        config = json.loads(hooks_json.read_text(encoding="utf-8"))

        precompact = config.get("PreCompact", {})
        assert "auto_process" in precompact
        assert precompact["auto_process"]["enabled"] is True
        assert precompact["auto_process"]["handler"] == "aipass.hooks.apps.handlers.lifecycle.auto_process.handle"

    def test_fires_on_user_prompt_submit_event_key(self):
        """Verify auto_process is wired in hooks.json under UserPromptSubmit (with session guard)."""
        import json
        from pathlib import Path

        hooks_json = Path(__file__).resolve().parent.parent.parent.parent.parent / ".aipass" / "hooks.json"
        config = json.loads(hooks_json.read_text(encoding="utf-8"))

        ups = config.get("UserPromptSubmit", {})
        assert "auto_process" in ups
        assert ups["auto_process"]["enabled"] is True
        assert ups["auto_process"]["handler"] == "aipass.hooks.apps.handlers.lifecycle.auto_process.handle"

    def test_both_registered_events_take_the_same_spawn_path(self):
        """One handler serves both events — 1b must not fix only the prompt lane."""
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        for payload in ({"hook_event_name": "UserPromptSubmit"}, {"hook_event_name": "PreCompact"}):
            mock_module = _make_mock_module()
            with patch(f"{MODULE}._already_ran_this_session", return_value=False):
                with patch(f"{MODULE}._mark_session_ran"):
                    with patch(f"{MODULE}.importlib.import_module", return_value=mock_module):
                        result = handle(payload)
            assert result["exit_code"] == 0
            mock_module.spawn_background.assert_called_once()
            mock_module.auto_process.assert_not_called()

    def test_hook_data_dict_accepted(self):
        """Handler accepts any hook_data dict without error."""
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module()

        with patch(f"{MODULE}._already_ran_this_session", return_value=False):
            with patch(f"{MODULE}._mark_session_ran"):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module):
                    result = handle({"tool_name": "Bash", "cwd": "/tmp"})

        assert result["exit_code"] == 0
        assert result["sound"] == "auto process"


class TestSessionGuard:
    def test_skips_when_already_ran(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        with patch(f"{MODULE}._already_ran_this_session", return_value=True):
            with patch(f"{MODULE}.importlib.import_module") as mock_import:
                result = handle({})

        assert result["exit_code"] == 0
        mock_import.assert_not_called()

    def test_runs_when_not_yet_ran(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module()

        with patch(f"{MODULE}._already_ran_this_session", return_value=False):
            with patch(f"{MODULE}._mark_session_ran"):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module) as mock_import:
                    handle({})

        mock_import.assert_called_once()

    def test_marks_session_after_a_successful_kick(self):
        """Guard now means kicked-once, not ran-once."""
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module()

        with patch(f"{MODULE}._mark_session_ran") as mock_mark:
            with patch(f"{MODULE}._already_ran_this_session", return_value=False):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module):
                    handle({})

        mock_mark.assert_called_once()

    def test_marks_session_when_a_run_is_already_live(self):
        """A refusal still means the work is happening — do not re-kick every prompt."""
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module(success=True, skipped=True, reason="already running (pid 7)", pid=None)

        with patch(f"{MODULE}._mark_session_ran") as mock_mark:
            with patch(f"{MODULE}._already_ran_this_session", return_value=False):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module):
                    handle({})

        mock_mark.assert_called_once()

    def test_does_not_mark_session_on_spawn_failure(self):
        """A failed kick must stay retryable on the next prompt."""
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module(success=False, error="no fork for you", pid=None)

        with patch(f"{MODULE}._mark_session_ran") as mock_mark:
            with patch(f"{MODULE}._already_ran_this_session", return_value=False):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module):
                    handle({})

        mock_mark.assert_not_called()

    def test_does_not_mark_session_on_error(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        with patch(f"{MODULE}._mark_session_ran") as mock_mark:
            with patch(f"{MODULE}._already_ran_this_session", return_value=False):
                with patch(f"{MODULE}.importlib.import_module", side_effect=ImportError("boom")):
                    handle({})

        mock_mark.assert_not_called()

    def test_guard_path_uses_session_id(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import _session_guard_path

        with patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "abc-123"}):
            path = _session_guard_path()

        assert path is not None
        assert "abc-123" in str(path)
        assert "aipass-auto-process-" in str(path)

    def test_guard_path_none_without_session_id(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import _session_guard_path

        with patch.dict("os.environ", {}, clear=True):
            path = _session_guard_path()

        assert path is None

    def test_already_ran_false_without_session_id(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import _already_ran_this_session

        with patch.dict("os.environ", {}, clear=True):
            assert not _already_ran_this_session()

    def test_already_ran_false_when_guard_missing(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import _already_ran_this_session

        with patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-no-file"}):
            with patch(f"{MODULE}._GUARD_DIR", tmp_path):
                assert not _already_ran_this_session()

    def test_already_ran_true_when_guard_exists(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import _already_ran_this_session

        (tmp_path / "aipass-auto-process-test-exists").touch()
        with patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-exists"}):
            with patch(f"{MODULE}._GUARD_DIR", tmp_path):
                assert _already_ran_this_session()

    def test_mark_creates_guard_file(self, tmp_path):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import _mark_session_ran

        with patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-mark"}):
            with patch(f"{MODULE}._GUARD_DIR", tmp_path):
                _mark_session_ran()

        assert (tmp_path / "aipass-auto-process-test-mark").exists()
