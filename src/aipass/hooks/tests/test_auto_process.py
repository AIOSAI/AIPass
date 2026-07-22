# =================== AIPass ====================
# Name: test_auto_process.py
# Version: 1.1.0
# Description: Tests for auto_process lifecycle handler (TDPLAN-0005)
# Branch: hooks
# Created: 2026-06-06
# Modified: 2026-06-06
# =============================================

"""Tests for handlers/lifecycle/auto_process.py."""

import logging
from unittest.mock import patch, MagicMock


MODULE = "aipass.hooks.apps.handlers.lifecycle.auto_process"


def _make_mock_module(**auto_process_return):
    mock_module = MagicMock()
    mock_module.auto_process.return_value = auto_process_return or {
        "success": True,
        "pool": {},
        "rollover": {},
    }
    return mock_module


class TestAutoProcessHandler:
    def test_success_returns_exit_code_0(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module(
            success=True,
            pool={"success": True, "files_processed": 0, "total_chunks": 0},
            rollover={"skipped": True},
        )

        with patch(f"{MODULE}._already_ran_this_session", return_value=False):
            with patch(f"{MODULE}._mark_session_ran"):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module):
                    result = handle({})

        assert result["exit_code"] == 0
        assert result["stdout"] == ""
        assert result["sound"] == "auto process"

    def test_calls_memory_auto_process_module(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module(success=True, pool={"skipped": True}, rollover={"skipped": True})

        with patch(f"{MODULE}._already_ran_this_session", return_value=False):
            with patch(f"{MODULE}._mark_session_ran"):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module) as mock_import:
                    handle({})

        mock_import.assert_called_once_with("aipass.memory.apps.handlers.intake.auto_process")
        mock_module.auto_process.assert_called_once()

    def test_logs_when_pool_files_processed(self, caplog):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module(
            success=True,
            pool={"success": True, "files_processed": 3, "total_chunks": 42},
            rollover={"skipped": True},
        )

        with patch(f"{MODULE}._already_ran_this_session", return_value=False):
            with patch(f"{MODULE}._mark_session_ran"):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module):
                    with caplog.at_level(logging.INFO):
                        handle({})

        assert "pool=3 files, rollover=0 processed" in caplog.text

    def test_logs_when_rollover_processed(self, caplog):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module(
            success=True,
            pool={"success": True, "files_processed": 0, "total_chunks": 0},
            rollover={"success": True, "processed": 2, "triggers": 2},
        )

        with patch(f"{MODULE}._already_ran_this_session", return_value=False):
            with patch(f"{MODULE}._mark_session_ran"):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module):
                    with caplog.at_level(logging.INFO):
                        handle({})

        assert "pool=0 files, rollover=2 processed" in caplog.text

    def test_logs_noop_when_nothing_processed(self, caplog):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module(success=True, pool={"skipped": True}, rollover={"skipped": True})

        with patch(f"{MODULE}._already_ran_this_session", return_value=False):
            with patch(f"{MODULE}._mark_session_ran"):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module):
                    with caplog.at_level(logging.INFO):
                        handle({})

        assert "no-op (nothing to process)" in caplog.text

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
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = MagicMock()
        mock_module.auto_process.side_effect = RuntimeError("chromadb down")

        with patch(f"{MODULE}._already_ran_this_session", return_value=False):
            with patch(f"{MODULE}.importlib.import_module", return_value=mock_module):
                with caplog.at_level(logging.ERROR):
                    result = handle({})

        assert result["exit_code"] == 1
        assert "chromadb down" in caplog.text

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

    def test_hook_data_dict_accepted(self):
        """Handler accepts any hook_data dict without error."""
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module(success=True, pool={}, rollover={})

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

        mock_module = _make_mock_module(success=True, pool={}, rollover={})

        with patch(f"{MODULE}._already_ran_this_session", return_value=False):
            with patch(f"{MODULE}._mark_session_ran"):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module) as mock_import:
                    handle({})

        mock_import.assert_called_once()

    def test_marks_session_after_success(self):
        from aipass.hooks.apps.handlers.lifecycle.auto_process import handle

        mock_module = _make_mock_module(success=True, pool={}, rollover={})

        with patch(f"{MODULE}._mark_session_ran") as mock_mark:
            with patch(f"{MODULE}._already_ran_this_session", return_value=False):
                with patch(f"{MODULE}.importlib.import_module", return_value=mock_module):
                    handle({})

        mock_mark.assert_called_once()

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
