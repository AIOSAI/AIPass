# =================== AIPass ====================
# Name: test_purge.py
# Description: Tests for sent/deleted auto-purge handler
# Version: 1.0.2
# Created: 2026-04-25
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/email/purge.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(windows_compat) — the sys.platform == "win32" stdout/stderr reconfigure block

import json
import os
import pytest
from unittest.mock import patch

import aipass.ai_mail.apps.handlers.email.purge as purge_mod
from aipass.ai_mail.apps.handlers.email.purge import (
    purge_sent_folder,
    purge_deleted_folder,
    run_purge,
)


@pytest.fixture(autouse=True)
def _silence_json_handler():
    """Prevent log_operation from writing real JSON files during tests."""
    with patch("aipass.ai_mail.apps.handlers.email.purge.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


def _populate_folder(folder_path, count):
    """Create count JSON files (email_000.json ...) in folder_path with staggered mtimes."""
    folder_path.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        email_file = folder_path / f"email_{i:03d}.json"
        email_data = {
            "id": f"msg-{i:03d}",
            "from": "@sender",
            "to": "@recipient",
            "subject": f"Email {i}",
            "message": f"Body {i}",
            "timestamp": f"2026-01-01 12:{i:02d}:00",
        }
        email_file.write_text(json.dumps(email_data), encoding="utf-8")
        base_time = 1700000000.0 + i
        os.utime(str(email_file), (base_time, base_time))


def test_purge_sent_folder_no_folder(tmp_path):
    """Returns success with 0 purged when sent folder does not exist."""
    result = purge_sent_folder(tmp_path)

    assert result["success"] is True
    assert result["purged_count"] == 0


def test_purge_sent_folder_below_threshold(tmp_path):
    """Returns success with 0 purged when file count is at or below threshold."""
    _populate_folder(tmp_path / "sent", 10)

    result = purge_sent_folder(tmp_path)

    assert result["success"] is True
    assert result["purged_count"] == 0
    assert "Below threshold" in result["message"]


def test_purge_sent_folder_above_threshold_vectorize_success(tmp_path, monkeypatch):
    """Purges oldest files when count exceeds threshold and vectorization succeeds."""
    _populate_folder(tmp_path / "sent", 13)

    monkeypatch.setattr(
        purge_mod, "_vectorize_emails", lambda emails, folder_type: {"success": True, "count": len(emails)}
    )

    result = purge_sent_folder(tmp_path)

    assert result["success"] is True
    assert result["purged_count"] == 3  # 13 - 10 = 3 files purged
    assert result["vectorized"] is True

    remaining = list((tmp_path / "sent").glob("*.json"))
    assert len(remaining) == 10


def test_purge_sent_folder_above_threshold_vectorize_fails(tmp_path, monkeypatch):
    """Preserves all files when vectorization fails."""
    _populate_folder(tmp_path / "sent", 13)

    monkeypatch.setattr(
        purge_mod, "_vectorize_emails", lambda emails, folder_type: {"success": False, "error": "timeout"}
    )

    result = purge_sent_folder(tmp_path)

    assert result["success"] is False
    assert result["purged_count"] == 0
    assert result["vectorized"] is False

    remaining = list((tmp_path / "sent").glob("*.json"))
    assert len(remaining) == 13


def test_purge_deleted_folder_no_folder(tmp_path):
    """Returns success with 0 purged when deleted folder does not exist."""
    result = purge_deleted_folder(tmp_path)

    assert result["success"] is True
    assert result["purged_count"] == 0


def test_purge_deleted_folder_below_threshold(tmp_path):
    """Returns success with 0 purged when file count is at or below threshold."""
    _populate_folder(tmp_path / "deleted", 5)

    result = purge_deleted_folder(tmp_path)

    assert result["success"] is True
    assert result["purged_count"] == 0


def test_purge_deleted_folder_above_threshold(tmp_path, monkeypatch):
    """Purges oldest files from deleted folder when count exceeds threshold."""
    _populate_folder(tmp_path / "deleted", 15)

    monkeypatch.setattr(
        purge_mod, "_vectorize_emails", lambda emails, folder_type: {"success": True, "count": len(emails)}
    )

    result = purge_deleted_folder(tmp_path)

    assert result["success"] is True
    assert result["purged_count"] == 5  # 15 - 10 = 5 files purged

    remaining = list((tmp_path / "deleted").glob("*.json"))
    assert len(remaining) == 10


def test_run_purge_both_below_threshold(tmp_path):
    """Both folders below threshold returns success with 0 purged."""
    _populate_folder(tmp_path / "sent", 3)
    _populate_folder(tmp_path / "deleted", 2)

    result = run_purge(tmp_path)

    assert result["success"] is True
    assert result["sent"]["purged_count"] == 0
    assert result["deleted"]["purged_count"] == 0


def test_run_purge_no_folders(tmp_path):
    """No folders at all returns success."""
    result = run_purge(tmp_path)

    assert result["success"] is True
    assert result["sent"]["purged_count"] == 0
    assert result["deleted"]["purged_count"] == 0


def test_run_purge_mixed_results(tmp_path, monkeypatch):
    """Sent over threshold and deleted below returns combined result."""
    _populate_folder(tmp_path / "sent", 12)
    _populate_folder(tmp_path / "deleted", 5)

    monkeypatch.setattr(
        purge_mod, "_vectorize_emails", lambda emails, folder_type: {"success": True, "count": len(emails)}
    )

    result = run_purge(tmp_path)

    assert result["success"] is True
    assert result["sent"]["purged_count"] == 2  # 12 - 10
    assert result["deleted"]["purged_count"] == 0


def test_run_purge_failure_propagates(tmp_path, monkeypatch):
    """Overall success is False when either folder purge fails."""
    _populate_folder(tmp_path / "sent", 15)

    monkeypatch.setattr(
        purge_mod, "_vectorize_emails", lambda emails, folder_type: {"success": False, "error": "broken"}
    )

    result = run_purge(tmp_path)

    assert result["success"] is False
    assert result["sent"]["success"] is False


class TestVectorizationFailureIsNotSuccess:
    """A handler reply of exit 0 with success:false is a refusal, so nothing may be deleted.

    The other tests here mock ``_vectorize_emails`` wholesale; these cover the subprocess seam.
    """

    @staticmethod
    def _handler_reply(stdout: str, returncode: int = 0):
        """Stand in for subprocess.run with a real handler response."""

        class _Result:
            def __init__(self):
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = ""

        return lambda *a, **k: _Result()

    def test_an_unknown_operation_is_a_failure_even_though_exit_is_zero(self, tmp_path, monkeypatch):
        """The exact live response, byte for byte, and its reason reaches the caller under "error"."""
        _populate_folder(tmp_path / "sent", 15)
        monkeypatch.setattr(
            purge_mod.subprocess,
            "run",
            self._handler_reply('{"success": false, "error": "Unknown operation: vectorize_and_store"}'),
        )

        result = purge_sent_folder(tmp_path)

        assert result["success"] is False, "exit 0 with success:false is a REFUSAL, not a store"
        assert result.get("error") == "Unknown operation: vectorize_and_store", (
            f"the handler's own reason must survive to the caller. Got: {result}"
        )

    def test_nothing_is_deleted_when_the_handler_refuses(self, tmp_path, monkeypatch):
        """The consequence that matters: originals must outlive a failed archive."""
        folder = tmp_path / "sent"
        folder.mkdir()
        _populate_folder(folder, 15)
        before = len(list(folder.glob("*.json")))

        monkeypatch.setattr(
            purge_mod.subprocess,
            "run",
            self._handler_reply('{"success": false, "error": "Unknown operation: vectorize_and_store"}'),
        )

        result = purge_sent_folder(tmp_path)

        assert result["success"] is False
        assert len(list(folder.glob("*.json"))) == before, "purge deleted originals it never archived"

    def test_unparseable_stdout_is_not_treated_as_success(self, tmp_path, monkeypatch):
        """A handler that returns garbage has not stored anything either."""
        folder = tmp_path / "sent"
        _populate_folder(folder, 15)
        monkeypatch.setattr(purge_mod.subprocess, "run", self._handler_reply("not json at all"))

        result = purge_sent_folder(tmp_path)

        assert result["success"] is False
        assert len(list(folder.glob("*.json"))) == 15, "purge deleted originals on an unreadable reply"

    def test_a_real_success_still_succeeds(self, tmp_path, monkeypatch):
        """The fix must not make a working store look broken: the 5 oldest go, 10 stay."""
        folder = tmp_path / "sent"
        _populate_folder(folder, 15)
        monkeypatch.setattr(purge_mod.subprocess, "run", self._handler_reply('{"success": true, "stored": 5}'))

        result = purge_sent_folder(tmp_path)

        assert result["success"] is True
        assert result["purged_count"] == 5
        assert sorted(f.name for f in folder.glob("*.json")) == [f"email_{i:03d}.json" for i in range(5, 15)]


def test_a_file_that_failed_to_load_is_never_deleted(tmp_path, monkeypatch):
    """A mail the purge could not read was never vectorized, so deleting it would lose it for good."""
    _populate_folder(tmp_path / "sent", 12)
    oldest = tmp_path / "sent" / "email_000.json"
    kept_mtime = oldest.stat().st_mtime
    oldest.write_text("{not json", encoding="utf-8")
    os.utime(oldest, (kept_mtime, kept_mtime))
    monkeypatch.setattr(
        purge_mod, "_vectorize_emails", lambda emails, folder_type: {"success": True, "count": len(emails)}
    )

    result = purge_sent_folder(tmp_path)

    assert result["success"] is True
    assert result["purged_count"] == 1, "two files were past the threshold; only the readable one is purged"
    assert not (tmp_path / "sent" / "email_001.json").exists(), "the vectorized mail is purged"
    assert oldest.exists(), "the unreadable mail stays on disk: nothing holds a copy"
    assert result["load_errors"] and oldest.name in result["load_errors"][0]
