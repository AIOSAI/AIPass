# =================== AIPass ====================
# Name: test_pr_status_sync.py
# Description: Tests for pr_created and pr_merged event handlers
# Version: 1.0.0
# Created: 2026-03-30
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/events/pr_status_sync.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(behaviour) — the event wiring in apps/handlers/events/registry.py; the bus tests cover delivery

import subprocess

import pytest
from unittest.mock import MagicMock, patch

from aipass.trigger.apps.handlers.events import pr_status_sync


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the handler's two outward writes on the real module.

    logger is a trail logger bound at import to the live logs/ directory, and
    json_handler writes the live operation log; both are replaced with mocks.
    Popen is patched per test, so no test launches a real drone.
    """
    monkeypatch.setattr(pr_status_sync, "logger", MagicMock())
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(pr_status_sync, "json_handler", mock_json_handler)


def _import_module():
    """Return the real pr_status_sync module the fixture patched."""
    return pr_status_sync


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
        json_handler = mod.json_handler

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
        json_handler = mod.json_handler

        mod.handle_pr_created(branch="spawn", pr_url="https://example.com/pr/1")

        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "pr_created_event",
            {"branch": "spawn", "pr_url": "https://example.com/pr/1"},
        )

    @patch("subprocess.Popen")
    def test_none_defaults(self, mock_popen: MagicMock) -> None:
        """Handles None parameters gracefully and still launches the sync.

        Mutant run: the sync launched with a truncated command reddens this.
        """
        mod = _import_module()
        mod.handle_pr_created()  # All defaults
        mock_popen.assert_called_once_with(
            ["drone", "@prax", "status", "sync"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


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
        json_handler = mod.json_handler

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
        json_handler = mod.json_handler

        mod.handle_pr_merged(pr_number="7", title="Add feature")

        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "pr_merged_event",
            {"pr_number": "7", "title": "Add feature"},
        )

    @patch("subprocess.Popen")
    def test_none_defaults(self, mock_popen: MagicMock) -> None:
        """Handles None parameters gracefully and still launches the sync.

        Mutant run: the sync launched with a truncated command reddens this.
        """
        mod = _import_module()
        mod.handle_pr_merged()  # All defaults
        mock_popen.assert_called_once_with(
            ["drone", "@prax", "status", "sync"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
