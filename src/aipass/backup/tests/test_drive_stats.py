# =================== AIPass ====================
# Name: test_drive_stats.py
# Description: Tests for apps/modules/drive_stats.py's Drive account quota lines, through a stub Drive service
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-17
# =============================================

"""Tests for apps/modules/drive_stats.py's Drive account quota lines."""

# Tests that need a Drive answer replace conftest's two sealed doors with a stub service.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — _human_bytes' unit arithmetic, which show_drive_quota only prints through

from pathlib import Path

import pytest

from aipass.backup.apps.handlers.drive import client as drive_client
from aipass.backup.apps.handlers.drive import tracker as drive_tracker
from aipass.backup.apps.modules import drive_stats


class _Request:
    """One about.get request: remembers what it asked for and holds Drive's answer."""

    def __init__(self, answer: dict | None, fields: str) -> None:
        self.answer = answer
        self.fields = fields


class _StubService:
    """Stands where the Drive v3 service stands, for about() alone."""

    def __init__(self, answer: dict | None) -> None:
        self.answer = answer
        self.requests: list[_Request] = []

    def about(self) -> "_StubService":
        return self

    def get(self, fields: str) -> _Request:
        request = _Request(self.answer, fields)
        self.requests.append(request)
        return request


@pytest.fixture
def drive_answers(monkeypatch: pytest.MonkeyPatch):
    """Open the sealed edge onto a stub service that answers about.get with what the test sets."""

    def _install(answer: dict | None) -> _StubService:
        service = _StubService(answer)
        monkeypatch.setattr(drive_client, "get_drive_service", lambda thread_safe=False: service)
        monkeypatch.setattr(drive_client, "api_call_with_retry", lambda request, max_retries=3: request.answer)
        return service

    return _install


class TestDriveQuota:
    """drive_stats prints the account's storageQuota usage and limit after the tracker."""

    def test_usage_and_limit_print_as_two_lines_from_about_get_storage_quota(
        self, tmp_path: Path, drive_answers, capsys: pytest.CaptureFixture[str]
    ) -> None:
        service = drive_answers({"storageQuota": {"usage": "1610612736", "limit": "16106127360"}})

        assert drive_stats.handle_command("drive_stats", [str(tmp_path)]) is True

        out, err = capsys.readouterr()
        assert [request.fields for request in service.requests] == ["storageQuota"]
        assert "Drive used:  1.5 GB (1,610,612,736 bytes)" in out
        assert "Drive limit: 15.0 GB (16,106,127,360 bytes)" in out
        assert err == ""

    def test_an_account_with_no_limit_says_none_is_reported_and_prints_no_number(
        self, tmp_path: Path, drive_answers, capsys: pytest.CaptureFixture[str]
    ) -> None:
        drive_answers({"storageQuota": {"usage": "2048"}})

        assert drive_stats.run_drive_stats(str(tmp_path)) is True

        out, err = capsys.readouterr()
        assert "Drive used:  2.0 KB (2,048 bytes)" in out
        limit_line = next(line for line in out.splitlines() if "Drive limit:" in line)
        assert "none reported" in limit_line
        assert not any(ch.isdigit() for ch in limit_line)
        assert err == ""

    def test_an_answer_without_storage_quota_is_refused_on_stderr_with_no_numbers(
        self, tmp_path: Path, drive_answers, capsys: pytest.CaptureFixture[str]
    ) -> None:
        drive_answers({"user": {}})

        assert drive_stats.run_drive_stats(str(tmp_path)) is True

        out, err = capsys.readouterr()
        assert "Drive used" not in out
        assert "Drive limit" not in out
        assert "Drive quota unavailable: about.get returned no storageQuota usage" in err

    def test_a_failed_auth_keeps_the_tracker_lines_and_says_why_on_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The conftest seal is left shut: authenticate reaches it and fails.
        drive_tracker.save_tracker(str(tmp_path), {"a.txt": {"drive_id": "x"}})

        assert drive_stats.run_drive_stats(str(tmp_path)) is True

        out, err = capsys.readouterr()
        assert "Total tracked files: 1" in out
        assert "Drive used" not in out
        assert "Drive quota unavailable: a test reached the live Google Drive edge" in err


# =============================================
