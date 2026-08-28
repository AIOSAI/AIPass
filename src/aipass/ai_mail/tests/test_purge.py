"""Tests for sent/deleted auto-purge handler -- purge_sent_folder, purge_deleted_folder, run_purge."""

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


# ---- Fixtures ------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_json_handler():
    """Prevent log_operation from writing real JSON files during tests."""
    with patch("aipass.ai_mail.apps.handlers.email.purge.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


# ---- Helper --------------------------------------------------


def _populate_folder(folder_path, count):
    """Create count JSON files in folder_path with staggered mtimes.

    Files are named email_000.json through email_{count-1}.json.
    Each file gets a slightly different mtime so sorting by mtime is deterministic.
    """
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
        # Stagger mtimes so sorting is deterministic (newer files have later mtime)
        base_time = 1700000000.0 + i
        os.utime(str(email_file), (base_time, base_time))


# ---- purge_sent_folder tests ---------------------------------


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

    # Verify 10 files remain
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

    # All 13 files should still exist
    remaining = list((tmp_path / "sent").glob("*.json"))
    assert len(remaining) == 13


# ---- purge_deleted_folder tests ------------------------------


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


# ---- run_purge tests -----------------------------------------


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


# ---- The subprocess seam --------------------------------------


class TestVectorizationFailureIsNotSuccess:
    """Reported by @memory (9da1ba52, 2026-08-23) and verified here before fixing.

    purge sent ``"operation": "vectorize_and_store"``. @memory's chroma handler
    accepts six operations and that is not one of them; there is no evidence it
    ever was. Their handler answers an unknown operation on STDOUT with
    ``{"success": false, ...}`` and EXITS 0 — a deliberate choice, since the
    subprocess ran fine, it was the request that was wrong. purge tested only
    ``returncode != 0``, so the refusal sailed past and it returned success.

    THAT IS NOT A COSMETIC BUG. ``_purge_files`` gates deletion on this result
    and then calls ``file_path.unlink()`` under the comment "data is safely in
    @memory". It never was. Reproduced live against the real handler:

        $ echo '{"operation":"vectorize_and_store",...}' | python3 chroma_subprocess.py
        {"success": false, "error": "Unknown operation: vectorize_and_store"}
        EXIT CODE: 0

    And confirmed from the other side: of 37 live collections, ai_mail_observations
    and ai_mail_local exist (the .trinity rollover, working), and no email
    collection exists at all.

    WHY EVERY EXISTING TEST IN THIS FILE MISSED IT: they all monkeypatch
    ``_vectorize_emails`` wholesale, so the seam between purge and the actual
    subprocess had no coverage at any point. The bug lived exactly where the
    mock began — the same shape as the dispatch-register phantoms this branch
    hit on 08-22, where a writer and its first consumer were built separately
    and neither suite covered the join.
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

    def test_an_unknown_operation_is_a_failure_even_though_exit_is_zero(self, monkeypatch):
        """The exact live response, byte for byte."""
        monkeypatch.setattr(
            purge_mod.subprocess,
            "run",
            self._handler_reply('{"success": false, "error": "Unknown operation: vectorize_and_store"}'),
        )

        result = purge_mod._vectorize_emails([{"subject": "s", "message": "m"}], "sent")

        assert result["success"] is False, "exit 0 with success:false is a REFUSAL, not a store"
        assert "Unknown operation" in str(result.get("error", "")), (
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

    def test_unparseable_stdout_is_not_treated_as_success(self, monkeypatch):
        """A handler that returns garbage has not stored anything either.

        Guessing "probably fine" from unreadable output is how the original
        defect would come back wearing a different hat.
        """
        monkeypatch.setattr(purge_mod.subprocess, "run", self._handler_reply("not json at all"))

        result = purge_mod._vectorize_emails([{"subject": "s", "message": "m"}], "sent")

        assert result["success"] is False

    def test_a_real_success_still_succeeds(self, monkeypatch):
        """The fix must not make a working store look broken."""
        monkeypatch.setattr(purge_mod.subprocess, "run", self._handler_reply('{"success": true, "stored": 1}'))

        result = purge_mod._vectorize_emails([{"subject": "s", "message": "m"}], "sent")

        assert result["success"] is True
        assert result["count"] == 1
