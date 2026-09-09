# =================== AIPass ====================
# Name: test_pr_status_sync.py
# Description: Tests for pr_created and pr_merged event handlers
# Version: 1.0.0
# Created: 2026-03-30
# Modified: 2026-03-30
# =============================================

"""Tests for pr_status_sync event handlers."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Mock heavy infrastructure imports."""
    import sys

    from aipass.trigger.apps.config import atomic_write_json

    mock_config = MagicMock()
    mock_config.TRIGGER_ROOT = tmp_path
    mock_config.atomic_write_json = atomic_write_json
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.config", mock_config)

    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json.json_handler", mock_json_handler)

    monkeypatch.delitem(sys.modules, "aipass.trigger.apps.handlers.events.pr_status_sync", raising=False)


def _import_module():
    """Import fresh after mocking."""
    import aipass.trigger.apps.handlers.events.pr_status_sync as m

    return m


class TestHandlePrCreated:
    """Tests for handle_pr_created."""

    @patch("subprocess.Popen")
    def test_fires_subprocess(self, mock_popen: MagicMock) -> None:
        """Calls drone @prax status sync via Popen."""
        mod = _import_module()
        mod.handle_pr_created(branch="flow", pr_url="https://github.com/org/repo/pull/42")

        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert args == ["drone", "@prax", "status", "sync"]

    @patch("subprocess.Popen")
    def test_does_not_block(self, mock_popen: MagicMock) -> None:
        """Popen is used (not run), so it doesn't block."""
        mod = _import_module()
        mod.handle_pr_created(branch="api")
        mock_popen.assert_called_once()
        # Popen returns immediately — no .wait() or .communicate() called
        mock_popen.return_value.wait.assert_not_called()

    @patch("subprocess.Popen", side_effect=FileNotFoundError("drone not found"))
    def test_a_missing_drone_is_named_and_the_event_is_still_logged(self, mock_popen: MagicMock) -> None:
        """No drone on PATH costs the sync, not the event record.

        The sync is fire-and-forget, so its failure has to be survivable — but
        two things have to survive it. The cause reaches the log (a status sync
        that silently never runs is the failure nobody notices for weeks), and
        the handler carries on to record the PR event, which does not depend on
        the sync at all. Not raising was neither of those.
        """
        mod = _import_module()
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

        with patch.object(mod, "logger") as mock_logger:
            mod.handle_pr_created(branch="flow")

        reported = str(mock_logger.info.call_args_list)
        assert "drone not found" in reported, f"the cause must reach the log: {reported}"
        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "pr_created_event",
            {"branch": "flow", "pr_url": ""},
        )

    @patch("subprocess.Popen")
    def test_logs_operation(self, mock_popen: MagicMock) -> None:
        """Logs the event via json_handler."""
        mod = _import_module()
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

        mod.handle_pr_created(branch="spawn", pr_url="https://example.com/pr/1")

        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "pr_created_event",
            {"branch": "spawn", "pr_url": "https://example.com/pr/1"},
        )

    @patch("subprocess.Popen")
    def test_none_defaults(self, mock_popen: MagicMock) -> None:
        """Handles None parameters gracefully."""
        mod = _import_module()
        mod.handle_pr_created()  # All defaults
        mock_popen.assert_called_once()


class TestHandlePrMerged:
    """Tests for handle_pr_merged."""

    @patch("subprocess.Popen")
    def test_fires_subprocess(self, mock_popen: MagicMock) -> None:
        """Calls drone @prax status sync via Popen."""
        mod = _import_module()
        mod.handle_pr_merged(pr_number="42", title="Fix the thing")

        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert args == ["drone", "@prax", "status", "sync"]

    @patch("subprocess.Popen", side_effect=OSError("exec failed"))
    def test_an_exec_failure_is_named_and_the_merge_is_still_logged(self, mock_popen: MagicMock) -> None:
        """A refused exec costs the sync, not the merge record.

        Same contract as the pr_created side, and it is pinned separately
        because the two handlers each build their own payload: a merge that
        reached the log with a blank pr_number would be indistinguishable from
        no merge at all. OSError rather than FileNotFoundError so the catch is
        exercised on a second exception class, not just the obvious one.
        """
        mod = _import_module()
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

        with patch.object(mod, "logger") as mock_logger:
            mod.handle_pr_merged(pr_number="99")

        reported = str(mock_logger.info.call_args_list)
        assert "exec failed" in reported, f"the cause must reach the log: {reported}"
        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "pr_merged_event",
            {"pr_number": "99", "title": ""},
        )

    @patch("subprocess.Popen")
    def test_logs_operation(self, mock_popen: MagicMock) -> None:
        """Logs the event via json_handler."""
        mod = _import_module()
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

        mod.handle_pr_merged(pr_number="7", title="Add feature")

        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "pr_merged_event",
            {"pr_number": "7", "title": "Add feature"},
        )

    @patch("subprocess.Popen")
    def test_none_defaults(self, mock_popen: MagicMock) -> None:
        """Handles None parameters gracefully."""
        mod = _import_module()
        mod.handle_pr_merged()  # All defaults
        mock_popen.assert_called_once()
