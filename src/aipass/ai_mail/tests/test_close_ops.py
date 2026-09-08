# =================== AIPass ====================
# Name: test_close_ops.py
# Description: Tests for email close operations handler
# Version: 1.0.0
# Created: 2026-04-25
# Modified: 2026-04-25
# =============================================

"""Tests for email close operations handler -- batch close and post-ops."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

import aipass.ai_mail.apps.handlers.email.close_ops as mod


# ---- Fixtures ------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_json_handler(monkeypatch):
    """Prevent log_operation from writing real JSON files during tests."""
    mock_jh = MagicMock()
    mock_jh.log_operation.return_value = True
    monkeypatch.setattr(mod, "json_handler", mock_jh)
    return mock_jh


# ---- batch_close tests ----------------------------------------


def test_batch_close_single_message_success(tmp_path: Path):
    """Single message close calls mark_closed_fn without skip_post_ops."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()

    mock_fn = MagicMock(return_value=(True, "Closed msg-1"))

    results, closed, failed = mod.batch_close(branch_path, ["msg-1"], mock_fn)

    assert len(results) == 1
    assert results[0] == ("msg-1", True, "Closed msg-1")
    assert closed == 1
    assert failed == 0
    # Single message: skip_post_ops should be False
    mock_fn.assert_called_once_with(branch_path, "msg-1", skip_post_ops=False)


def test_batch_close_multiple_messages_skip_post_ops(tmp_path: Path):
    """Multiple messages pass skip_post_ops=True to mark_closed_fn."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()

    mock_fn = MagicMock(return_value=(True, "Closed"))

    results, closed, failed = mod.batch_close(branch_path, ["msg-1", "msg-2", "msg-3"], mock_fn)

    assert len(results) == 3
    assert closed == 3
    assert failed == 0
    # All calls should have skip_post_ops=True for batch mode
    for call in mock_fn.call_args_list:
        assert call.kwargs["skip_post_ops"] is True


def test_batch_close_mixed_results(tmp_path: Path):
    """Mixed success/failure results are counted correctly."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()

    def _side_effect(_bp: Path, msg_id: str, skip_post_ops: bool = False):
        if msg_id == "msg-2":
            return False, "Not found"
        return True, f"Closed {msg_id}"

    mock_fn = MagicMock(side_effect=_side_effect)

    results, closed, failed = mod.batch_close(branch_path, ["msg-1", "msg-2", "msg-3"], mock_fn)

    assert len(results) == 3
    assert closed == 2
    assert failed == 1
    assert results[1] == ("msg-2", False, "Not found")


def test_batch_close_empty_list(tmp_path: Path):
    """Empty message list returns empty results."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()

    mock_fn = MagicMock()

    results, closed, failed = mod.batch_close(branch_path, [], mock_fn)

    assert results == []
    assert closed == 0
    assert failed == 0
    mock_fn.assert_not_called()


def test_batch_close_all_failures(tmp_path: Path):
    """All failures increment failed_count, closed_count stays 0."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()

    mock_fn = MagicMock(return_value=(False, "Error"))

    results, closed, failed = mod.batch_close(branch_path, ["msg-1", "msg-2"], mock_fn)

    assert closed == 0
    assert failed == 2


# ---- batch_close_post_ops tests --------------------------------


def test_batch_close_post_ops_all_fns_called(tmp_path: Path):
    """All provided functions are called with correct arguments."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()

    central_fn = MagicMock()
    purge_fn = MagicMock()

    mod.batch_close_post_ops(branch_path, central_fn, purge_fn)

    central_fn.assert_called_once_with()
    purge_fn.assert_called_once_with(branch_path / ".ai_mail.local")


def test_batch_close_post_ops_none_fns(tmp_path: Path):
    """None callables are SKIPPED, and the skip is silent.

    Had no oracle — the call was the whole test, so "did not raise" was doing
    the work. But not raising is also what a version that swallowed a real
    TypeError would do. The two limbs each log a warning when they run and fail,
    so an untouched logger is the evidence that neither limb was entered.
    """
    branch_path = tmp_path / "branch"
    branch_path.mkdir()

    with patch.object(mod, "logger") as mock_logger:
        mod.batch_close_post_ops(branch_path, None, None)

    mock_logger.warning.assert_not_called()


def test_batch_close_post_ops_central_exception_suppressed(tmp_path: Path):
    """Exception in update_central_fn is caught; purge still called."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()

    central_fn = MagicMock(side_effect=RuntimeError("central failed"))
    purge_fn = MagicMock()

    mod.batch_close_post_ops(branch_path, central_fn, purge_fn)

    purge_fn.assert_called_once()


def test_batch_close_post_ops_purge_exception_suppressed(tmp_path: Path):
    """Exception in purge_deleted_fn is caught silently."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()

    central_fn = MagicMock()
    purge_fn = MagicMock(side_effect=RuntimeError("purge failed"))

    mod.batch_close_post_ops(branch_path, central_fn, purge_fn)

    central_fn.assert_called_once()


def test_batch_close_post_ops_partial_fns(tmp_path: Path):
    """Only provided functions are called; others default to None."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir()

    central_fn = MagicMock()

    mod.batch_close_post_ops(branch_path, central_fn, None)

    central_fn.assert_called_once_with()
