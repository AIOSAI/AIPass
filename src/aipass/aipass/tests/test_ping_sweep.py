# =================== AIPass ====================
# Name: test_ping_sweep.py
# Description: Tests for aipass ping_sweep handler Phase 3
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-16
# =============================================

"""Tests for ping_sweep handler — Phase 3 (FPLAN-0188)."""

import json
import subprocess
from unittest.mock import MagicMock, patch


from aipass.aipass.apps.handlers.ping_sweep import (
    BRANCHES,
    TEST_TOKEN,
    TIMEOUT_PER_BRANCH,
    _send_test_email,
    _wait_for_ack,
    sweep_all_branches,
    sweep_summary,
)


# =============================================================================
# TestConstants
# =============================================================================


class TestConstants:
    def test_test_token_present(self) -> None:
        """TEST_TOKEN contains the required sentinel text."""
        assert "AIPASS-TEST" in TEST_TOKEN
        assert "do not update memories" in TEST_TOKEN
        assert "ack" in TEST_TOKEN

    def test_branches_non_empty(self) -> None:
        """BRANCHES list has at least one entry."""
        assert len(BRANCHES) > 0

    def test_aipass_not_in_branches(self) -> None:
        """aipass branch is not in BRANCHES (avoids pinging itself)."""
        assert "aipass" not in BRANCHES

    def test_timeout_positive(self) -> None:
        """Default timeout is a positive integer."""
        assert TIMEOUT_PER_BRANCH > 0


# =============================================================================
# TestSendTestEmail
# =============================================================================


class TestSendTestEmail:
    def test_success_returns_true(self) -> None:
        """Returns True when drone exits with returncode 0."""
        mock_result = MagicMock(returncode=0, stderr="")
        with patch("aipass.aipass.apps.handlers.ping_sweep.subprocess.run", return_value=mock_result):
            assert _send_test_email("seedgo", "ping body") is True

    def test_nonzero_returncode_returns_false(self) -> None:
        """Returns False when drone exits with non-zero returncode."""
        mock_result = MagicMock(returncode=1, stderr="error msg")
        with patch("aipass.aipass.apps.handlers.ping_sweep.subprocess.run", return_value=mock_result):
            assert _send_test_email("seedgo", "ping body") is False

    def test_drone_not_found_returns_false(self) -> None:
        """Returns False when drone binary is not on PATH."""
        with patch(
            "aipass.aipass.apps.handlers.ping_sweep.subprocess.run",
            side_effect=FileNotFoundError("drone not found"),
        ):
            assert _send_test_email("prax", "ping body") is False

    def test_timeout_returns_false(self) -> None:
        """Returns False when subprocess times out."""
        with patch(
            "aipass.aipass.apps.handlers.ping_sweep.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="drone", timeout=15),
        ):
            assert _send_test_email("flow", "ping body") is False

    def test_calls_drone_with_correct_args(self) -> None:
        """Subprocess is called with the expected drone command."""
        mock_result = MagicMock(returncode=0, stderr="")
        with patch("aipass.aipass.apps.handlers.ping_sweep.subprocess.run", return_value=mock_result) as mock_run:
            _send_test_email("drone", "test body")
        args = mock_run.call_args[0][0]
        assert args[0] == "drone"
        assert "@ai_mail" in args
        assert "@drone" in args


# =============================================================================
# TestWaitForAck
# =============================================================================


class TestWaitForAck:
    def _make_inbox(self, messages: list) -> dict:
        return {"messages": messages}

    def test_returns_timeout_when_no_inbox(self, tmp_path) -> None:
        """Returns 'timeout' when inbox file does not exist."""
        missing = tmp_path / "nonexistent.json"
        with patch("aipass.aipass.apps.handlers.ping_sweep._aipass_inbox_path", return_value=missing):
            with patch("aipass.aipass.apps.handlers.ping_sweep.time.sleep"):
                # Short real timeout — watchdog thread shares time.time, so mocking it is fragile
                result = _wait_for_ack("seedgo", timeout=0)
        assert result == "timeout"

    def test_returns_ack_when_matching_message(self, tmp_path) -> None:
        """Returns 'ack' when inbox has a matching new ack from branch."""
        inbox = tmp_path / "inbox.json"
        inbox.write_text(
            json.dumps(
                {
                    "messages": [
                        {
                            "from": "@seedgo",
                            "subject": "ack",
                            "message": "ack",
                            "status": "new",
                        }
                    ]
                }
            )
        )
        with patch("aipass.aipass.apps.handlers.ping_sweep._aipass_inbox_path", return_value=inbox):
            with patch("aipass.aipass.apps.handlers.ping_sweep.time.sleep"):
                result = _wait_for_ack("seedgo", timeout=5)
        assert result == "ack"

    def test_ignores_message_from_other_branch(self, tmp_path) -> None:
        """Does not match ack from a different branch."""
        inbox = tmp_path / "inbox.json"
        inbox.write_text(
            json.dumps(
                {
                    "messages": [
                        {
                            "from": "@prax",
                            "subject": "ack",
                            "message": "ack",
                            "status": "new",
                        }
                    ]
                }
            )
        )
        with patch("aipass.aipass.apps.handlers.ping_sweep._aipass_inbox_path", return_value=inbox):
            with patch("aipass.aipass.apps.handlers.ping_sweep.time.sleep"):
                result = _wait_for_ack("seedgo", timeout=0)
        assert result == "timeout"

    def test_ignores_non_new_message(self, tmp_path) -> None:
        """Does not match already-read messages."""
        inbox = tmp_path / "inbox.json"
        inbox.write_text(
            json.dumps(
                {
                    "messages": [
                        {
                            "from": "@seedgo",
                            "subject": "ack",
                            "message": "ack",
                            "status": "read",
                        }
                    ]
                }
            )
        )
        with patch("aipass.aipass.apps.handlers.ping_sweep._aipass_inbox_path", return_value=inbox):
            with patch("aipass.aipass.apps.handlers.ping_sweep.time.sleep"):
                result = _wait_for_ack("seedgo", timeout=0)
        assert result == "timeout"

    def test_handles_corrupt_inbox(self, tmp_path) -> None:
        """Gracefully handles corrupt inbox.json (returns 'timeout')."""
        inbox = tmp_path / "inbox.json"
        inbox.write_text("NOT JSON")
        with patch("aipass.aipass.apps.handlers.ping_sweep._aipass_inbox_path", return_value=inbox):
            with patch("aipass.aipass.apps.handlers.ping_sweep.time.sleep"):
                result = _wait_for_ack("seedgo", timeout=0)
        assert result == "timeout"


# =============================================================================
# TestSweepAllBranches
# =============================================================================


class TestSweepAllBranches:
    def test_returns_dict_with_all_branches(self) -> None:
        """Result has an entry for every branch in BRANCHES."""
        with patch("aipass.aipass.apps.handlers.ping_sweep._discover_branches", return_value=BRANCHES):
            with patch("aipass.aipass.apps.handlers.ping_sweep._send_test_email", return_value=False):
                with patch("aipass.aipass.apps.handlers.ping_sweep.json_handler", autospec=True):
                    results = sweep_all_branches(timeout=1)
        assert set(results.keys()) == set(BRANCHES)

    def test_send_failure_marks_error(self) -> None:
        """Branches where send fails are marked 'error'."""
        with patch("aipass.aipass.apps.handlers.ping_sweep._discover_branches", return_value=BRANCHES):
            with patch("aipass.aipass.apps.handlers.ping_sweep._send_test_email", return_value=False):
                with patch("aipass.aipass.apps.handlers.ping_sweep.json_handler", autospec=True):
                    results = sweep_all_branches(timeout=1)
        assert all(v == "error" for v in results.values())

    def test_send_success_waits_for_ack(self) -> None:
        """Branches where send succeeds get _wait_for_ack called."""
        with patch("aipass.aipass.apps.handlers.ping_sweep._discover_branches", return_value=BRANCHES):
            with patch("aipass.aipass.apps.handlers.ping_sweep._send_test_email", return_value=True):
                with patch("aipass.aipass.apps.handlers.ping_sweep._wait_for_ack", return_value="timeout") as mock_wait:
                    with patch("aipass.aipass.apps.handlers.ping_sweep.json_handler", autospec=True):
                        results = sweep_all_branches(timeout=1)
        assert mock_wait.call_count == len(BRANCHES)
        assert all(v == "timeout" for v in results.values())

    def test_logs_operation(self) -> None:
        """json_handler.log_operation is called after sweep."""
        mock_jh = MagicMock()
        with patch("aipass.aipass.apps.handlers.ping_sweep._discover_branches", return_value=BRANCHES):
            with patch("aipass.aipass.apps.handlers.ping_sweep._send_test_email", return_value=False):
                with patch("aipass.aipass.apps.handlers.ping_sweep.json_handler", mock_jh):
                    sweep_all_branches(timeout=1)
        mock_jh.log_operation.assert_called_once_with("ping_sweep", {"results": {b: "error" for b in BRANCHES}})


# =============================================================================
# TestSweepSummary
# =============================================================================


class TestSweepSummary:
    def test_all_ack(self) -> None:
        """All-ack result shows correct counts."""
        results = {b: "ack" for b in BRANCHES}
        summary = sweep_summary(results)
        assert f"{len(BRANCHES)} ack" in summary
        assert "0 timeout" in summary
        assert "0 error" in summary

    def test_all_timeout(self) -> None:
        """All-timeout result shows correct counts."""
        results = {b: "timeout" for b in BRANCHES}
        summary = sweep_summary(results)
        assert "0 ack" in summary
        assert f"{len(BRANCHES)} timeout" in summary

    def test_mixed_results(self) -> None:
        """Mixed results are counted correctly."""
        results = {"drone": "ack", "prax": "timeout", "cli": "error"}
        summary = sweep_summary(results)
        assert "1 ack" in summary
        assert "1 timeout" in summary
        assert "1 error" in summary

    def test_empty_results(self) -> None:
        """Empty results return all-zero summary."""
        summary = sweep_summary({})
        assert "0 ack" in summary
        assert "0 timeout" in summary
        assert "0 error" in summary
