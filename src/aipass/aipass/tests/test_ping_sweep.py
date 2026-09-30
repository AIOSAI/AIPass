# =================== AIPass ====================
# Name: test_ping_sweep.py
# Description: Tests for aipass ping_sweep handler Phase 3
# Version: 1.1.2
# Created: 2026-04-16
# Modified: 2026-09-28
# =============================================

"""Tests for apps/handlers/ping_sweep/__init__.py — Phase 3 (FPLAN-0188)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — _discover_branches and _aipass_inbox_path; every test mocks both

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch


from aipass.aipass.apps.handlers.ping_sweep import (
    BRANCHES,
    TEST_TOKEN,
    TIMEOUT_PER_BRANCH,
    sweep_all_branches,
    sweep_summary,
)

_PS = "aipass.aipass.apps.handlers.ping_sweep"


def _sweep_one(branch: str, inbox: Path, timeout: int, run: MagicMock) -> tuple[dict, MagicMock]:
    """Sweep exactly one branch through sweep_all_branches with every live edge sealed.

    The mail send is `subprocess.run(["drone", "@ai_mail", "email", ...])` inside ping_sweep:
    `run` replaces it (the process edge), so no real mail leaves. The inbox is `inbox` under
    tmp_path and the audit log is an autospec json_handler. Returns (results, run).
    """
    with (
        patch(f"{_PS}._discover_branches", return_value=[branch]),
        patch(f"{_PS}._aipass_inbox_path", return_value=inbox),
        patch(f"{_PS}.subprocess.run", run),
        patch(f"{_PS}.json_handler", autospec=True),
    ):
        results = sweep_all_branches(timeout=timeout)
    return results, run


def _run_rc(returncode: int) -> MagicMock:
    """A stand-in for subprocess.run whose drone send exits with returncode."""
    return MagicMock(return_value=MagicMock(returncode=returncode, stderr="error msg" if returncode else ""))


def _ack_inbox(tmp_path: Path, sender: str, status: str) -> Path:
    """Write an inbox.json under tmp_path holding one ack message from sender with status."""
    inbox = tmp_path / "inbox.json"
    msg = {"from": f"@{sender}", "subject": "ack", "message": "ack", "status": status}
    inbox.write_text(json.dumps({"messages": [msg]}), encoding="utf-8")
    return inbox


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
    """The mail send, reached through sweep_all_branches with subprocess.run replaced."""

    def test_success_returns_true(self, tmp_path) -> None:
        """A send drone accepts (rc 0) is not an error: the sweep goes on to wait for the ack.

        Mutant: `if result.returncode != 0:` -> `if result.returncode == 0:` -> red.
        """
        results, _run = _sweep_one("seedgo", tmp_path / "inbox.json", 0, _run_rc(0))
        assert results == {"seedgo": "timeout"}

    def test_nonzero_returncode_returns_false(self, tmp_path) -> None:
        """A send drone refuses (non-zero rc) marks the branch 'error'."""
        results, _run = _sweep_one("seedgo", tmp_path / "inbox.json", 0, _run_rc(1))
        assert results == {"seedgo": "error"}

    def test_drone_not_found_returns_false(self, tmp_path) -> None:
        """drone missing from PATH marks the branch 'error', not a traceback."""
        run = MagicMock(side_effect=FileNotFoundError("drone not found"))
        results, _run = _sweep_one("prax", tmp_path / "inbox.json", 0, run)
        assert results == {"prax": "error"}

    def test_timeout_returns_false(self, tmp_path) -> None:
        """A send that times out marks the branch 'error', not a traceback."""
        run = MagicMock(side_effect=subprocess.TimeoutExpired(cmd="drone", timeout=15))
        results, _run = _sweep_one("flow", tmp_path / "inbox.json", 0, run)
        assert results == {"flow": "error"}

    def test_calls_drone_with_correct_args(self, tmp_path) -> None:
        """The one send is drone @ai_mail email @<branch> with the ping body carrying TEST_TOKEN.

        Mutant: `f"@{branch}"` -> `f"{branch}"` in the send command -> red.
        """
        _results, run = _sweep_one("drone", tmp_path / "inbox.json", 0, _run_rc(0))
        run.assert_called_once()
        args = run.call_args[0][0]
        assert args[:5] == ["drone", "@ai_mail", "email", "@drone", "AIPASS PING"]
        assert TEST_TOKEN in args[5]


# =============================================================================
# TestWaitForAck
# =============================================================================


class TestWaitForAck:
    """The ack poll, reached through sweep_all_branches after a send drone accepts.

    time.sleep is not patched: timeout=1 enters the poll once and sleeps the product's real
    2 s, so each test that reads the inbox costs 2 s. A poll-interval seam on _wait_for_ack
    would exist for these tests alone; aipass's decision, fleet green leg 3: pay the 2 s.
    """

    def test_returns_timeout_when_no_inbox(self, tmp_path) -> None:
        """Returns 'timeout' when inbox file does not exist."""
        results, _run = _sweep_one("seedgo", tmp_path / "nonexistent.json", 1, _run_rc(0))
        assert results == {"seedgo": "timeout"}

    def test_returns_ack_when_matching_message(self, tmp_path) -> None:
        """Returns 'ack' when inbox has a matching new ack from branch.

        Mutant: `return "ack"` -> `return "timeout"` in the poll -> red.
        """
        results, _run = _sweep_one("seedgo", _ack_inbox(tmp_path, "seedgo", "new"), 1, _run_rc(0))
        assert results == {"seedgo": "ack"}

    def test_ignores_message_from_other_branch(self, tmp_path) -> None:
        """Does not match ack from a different branch.

        Mutant: `msg_from == branch and` dropped from the match -> red.
        """
        results, _run = _sweep_one("seedgo", _ack_inbox(tmp_path, "prax", "new"), 1, _run_rc(0))
        assert results == {"seedgo": "timeout"}

    def test_ignores_non_new_message(self, tmp_path) -> None:
        """Does not match already-read messages."""
        results, _run = _sweep_one("seedgo", _ack_inbox(tmp_path, "seedgo", "read"), 1, _run_rc(0))
        assert results == {"seedgo": "timeout"}

    def test_handles_corrupt_inbox(self, tmp_path) -> None:
        """Gracefully handles corrupt inbox.json (returns 'timeout')."""
        inbox = tmp_path / "inbox.json"
        inbox.write_text("NOT JSON", encoding="utf-8")
        results, _run = _sweep_one("seedgo", inbox, 1, _run_rc(0))
        assert results == {"seedgo": "timeout"}


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
