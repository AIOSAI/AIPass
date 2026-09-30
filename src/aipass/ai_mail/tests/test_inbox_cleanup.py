# =================== AIPass ====================
# Name: test_inbox_cleanup.py
# Description: Tests for inbox cleanup handler
# Version: 1.0.1
# Created: 2026-04-25
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/email/inbox_cleanup.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(windows_compat) — the sys.platform == "win32" stdout/stderr reconfigure block

import json
from contextlib import contextmanager

import pytest
from pathlib import Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.email.inbox_cleanup as mod
import aipass.ai_mail.apps.handlers.email.inbox_ops as ops_mod


# ---- Fixtures ------------------------------------------------


@contextmanager
def _noop_lock(_path: Path):
    """Dummy context manager replacing the real inbox file lock."""
    yield


@pytest.fixture(autouse=True)
def _silence_json_handler(monkeypatch):
    """Prevent log_operation from writing real JSON files during tests."""
    mock_jh = MagicMock()
    mock_jh.log_operation.return_value = True
    monkeypatch.setattr(mod, "json_handler", mock_jh)
    return mock_jh


@pytest.fixture(autouse=True)
def _mock_inbox_lock(monkeypatch):
    """Replace _get_inbox_lock so it returns a no-op context manager."""
    monkeypatch.setattr(mod, "_get_inbox_lock", lambda: _noop_lock)


@pytest.fixture(autouse=True)
def _mock_central(monkeypatch):
    """Replace _get_update_central with a no-op."""
    monkeypatch.setattr(mod, "_get_update_central", lambda: lambda: None)


@pytest.fixture(autouse=True)
def _mock_deleted_purge(monkeypatch):
    """Replace _trigger_deleted_purge with a no-op."""
    monkeypatch.setattr(mod, "_trigger_deleted_purge", lambda _bp: None)


def _make_inbox(branch_path: Path, messages: list) -> Path:
    """Create a branch with .ai_mail.local/inbox.json containing messages."""
    mailbox = branch_path / ".ai_mail.local"
    mailbox.mkdir(parents=True, exist_ok=True)
    inbox_file = mailbox / "inbox.json"
    unread = sum(
        1 for m in messages if m.get("status") == "new" or (m.get("status") is None and not m.get("read", False))
    )
    data = {
        "mailbox": "inbox",
        "total_messages": len(messages),
        "unread_count": unread,
        "messages": messages,
    }
    inbox_file.write_text(json.dumps(data), encoding="utf-8")
    return inbox_file


# ---- mark_all_read_and_archive tests ---------------------------


def test_mark_all_read_and_archive_success(tmp_path: Path):
    """Archives all messages and clears inbox."""
    branch_path = tmp_path / "branch"
    _make_inbox(
        branch_path,
        [
            {"id": "m1", "status": "new", "subject": "First", "read": False},
            {"id": "m2", "status": "opened", "subject": "Second", "read": True},
        ],
    )

    success, message, count = mod.mark_all_read_and_archive(branch_path)

    assert success is True
    assert count == 2
    assert "Archived 2" in message

    # Inbox should be empty
    inbox_file = branch_path / ".ai_mail.local" / "inbox.json"
    with open(inbox_file, "r", encoding="utf-8") as f:
        inbox_data = json.load(f)
    assert inbox_data["messages"] == []
    assert inbox_data["total_messages"] == 0
    assert inbox_data["unread_count"] == 0

    # Deleted folder should have files
    deleted_dir = branch_path / ".ai_mail.local" / "deleted"
    assert deleted_dir.is_dir()
    deleted_files = list(deleted_dir.glob("*.json"))
    assert len(deleted_files) == 2


def test_mark_all_read_and_archive_empty_inbox(tmp_path: Path):
    """Empty inbox returns success with count 0."""
    branch_path = tmp_path / "branch"
    _make_inbox(branch_path, [])

    success, message, count = mod.mark_all_read_and_archive(branch_path)

    assert success is True
    assert count == 0
    assert "empty" in message.lower()


def test_mark_all_read_and_archive_no_inbox(tmp_path: Path):
    """Missing inbox file returns failure."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir(parents=True)

    success, message, count = mod.mark_all_read_and_archive(branch_path)

    assert success is False
    assert count == 0
    assert "not found" in message.lower()


# ---- mark_as_opened tests -------------------------------------


def test_mark_as_opened_success(tmp_path: Path):
    """Marks a message as opened and sets read=True."""
    branch_path = tmp_path / "branch"
    _make_inbox(
        branch_path,
        [
            {"id": "m1", "status": "new", "subject": "Hello", "read": False},
        ],
    )

    success, message, email_data = mod.mark_as_opened(branch_path, "m1")

    assert success is True
    assert "opened" in message.lower()
    assert email_data is not None
    assert email_data["status"] == "opened"
    assert email_data["read"] is True

    # Verify inbox file updated
    inbox_file = branch_path / ".ai_mail.local" / "inbox.json"
    with open(inbox_file, "r", encoding="utf-8") as f:
        inbox_data = json.load(f)
    assert inbox_data["messages"][0]["status"] == "opened"
    assert inbox_data["unread_count"] == 0


def test_mark_as_opened_not_found(tmp_path: Path):
    """Nonexistent message ID returns failure."""
    branch_path = tmp_path / "branch"
    _make_inbox(
        branch_path,
        [{"id": "m1", "status": "new", "subject": "Hello"}],
    )

    success, message, email_data = mod.mark_as_opened(branch_path, "nonexistent")

    assert success is False
    assert "not found" in message.lower()
    assert email_data is None


def test_mark_as_opened_no_inbox(tmp_path: Path):
    """Missing inbox file returns failure."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir(parents=True)

    success, message, email_data = mod.mark_as_opened(branch_path, "m1")

    assert success is False
    assert "not found" in message.lower()
    assert email_data is None


def test_mark_as_opened_updates_unread_count(tmp_path: Path):
    """Opening one of two new messages reduces unread_count by 1."""
    branch_path = tmp_path / "branch"
    _make_inbox(
        branch_path,
        [
            {"id": "m1", "status": "new", "subject": "A", "read": False},
            {"id": "m2", "status": "new", "subject": "B", "read": False},
        ],
    )

    mod.mark_as_opened(branch_path, "m1")

    inbox_file = branch_path / ".ai_mail.local" / "inbox.json"
    with open(inbox_file, "r", encoding="utf-8") as f:
        inbox_data = json.load(f)
    assert inbox_data["unread_count"] == 1


# ---- mark_as_closed_and_archive tests --------------------------


def test_mark_as_closed_and_archive_success(tmp_path: Path):
    """Closes message, removes from inbox, saves to deleted/."""
    branch_path = tmp_path / "branch"
    _make_inbox(
        branch_path,
        [
            {"id": "m1", "status": "opened", "subject": "Task", "read": True},
            {"id": "m2", "status": "new", "subject": "Other", "read": False},
        ],
    )

    success, message = mod.mark_as_closed_and_archive(branch_path, "m1")

    assert success is True
    assert "closed" in message.lower()

    # Inbox should have only m2
    inbox_file = branch_path / ".ai_mail.local" / "inbox.json"
    with open(inbox_file, "r", encoding="utf-8") as f:
        inbox_data = json.load(f)
    assert len(inbox_data["messages"]) == 1
    assert inbox_data["messages"][0]["id"] == "m2"
    assert inbox_data["total_messages"] == 1

    # Deleted folder should have the archived message
    deleted_dir = branch_path / ".ai_mail.local" / "deleted"
    assert deleted_dir.is_dir()
    deleted_files = list(deleted_dir.glob("*.json"))
    assert len(deleted_files) == 1


def test_mark_as_closed_and_archive_not_found(tmp_path: Path):
    """Nonexistent message ID returns failure."""
    branch_path = tmp_path / "branch"
    _make_inbox(
        branch_path,
        [{"id": "m1", "status": "new", "subject": "Hello"}],
    )

    success, message = mod.mark_as_closed_and_archive(branch_path, "nonexistent")

    assert success is False
    assert "not found" in message.lower()


def test_mark_as_closed_and_archive_no_inbox(tmp_path: Path):
    """Missing inbox file returns failure."""
    branch_path = tmp_path / "branch"
    branch_path.mkdir(parents=True)

    success, message = mod.mark_as_closed_and_archive(branch_path, "m1")

    assert success is False
    assert "not found" in message.lower()


def test_mark_as_closed_and_archive_skip_post_ops(tmp_path: Path):
    """With skip_post_ops=True, message is still archived but post-ops skipped."""
    branch_path = tmp_path / "branch"
    _make_inbox(
        branch_path,
        [{"id": "m1", "status": "opened", "subject": "Task", "read": True}],
    )

    success, message = mod.mark_as_closed_and_archive(branch_path, "m1", skip_post_ops=True)

    assert success is True

    # Inbox should be empty
    inbox_file = branch_path / ".ai_mail.local" / "inbox.json"
    with open(inbox_file, "r", encoding="utf-8") as f:
        inbox_data = json.load(f)
    assert len(inbox_data["messages"]) == 0

    # Deleted folder should still have the archived file
    deleted_dir = branch_path / ".ai_mail.local" / "deleted"
    deleted_files = list(deleted_dir.glob("*.json"))
    assert len(deleted_files) == 1


def test_mark_as_closed_and_archive_updates_counts(tmp_path: Path):
    """Closing a message updates total_messages and unread_count."""
    branch_path = tmp_path / "branch"
    _make_inbox(
        branch_path,
        [
            {"id": "m1", "status": "new", "subject": "A", "read": False},
            {"id": "m2", "status": "new", "subject": "B", "read": False},
        ],
    )

    mod.mark_as_closed_and_archive(branch_path, "m1")

    inbox_file = branch_path / ".ai_mail.local" / "inbox.json"
    with open(inbox_file, "r", encoding="utf-8") as f:
        inbox_data = json.load(f)
    assert inbox_data["total_messages"] == 1
    assert inbox_data["unread_count"] == 1


# ---- _sweep_closed tests ----------------------------------------


def test_sweep_closed_removes_closed_messages(tmp_path: Path):
    """Messages with status=closed are archived to deleted/ and removed."""
    mailbox = tmp_path / ".ai_mail.local"
    mailbox.mkdir(parents=True)
    inbox_data = {
        "messages": [
            {"id": "m1", "status": "new", "subject": "Active"},
            {"id": "m2", "status": "closed", "subject": "Done"},
            {"id": "m3", "status": "opened", "subject": "Read"},
        ]
    }

    swept = mod._sweep_closed(inbox_data, mailbox)

    assert swept == 1
    assert len(inbox_data["messages"]) == 2
    assert all(m["id"] != "m2" for m in inbox_data["messages"])
    deleted_files = list((mailbox / "deleted").glob("*.json"))
    assert len(deleted_files) == 1


def test_sweep_closed_no_closed_messages_is_noop(tmp_path: Path):
    """Inbox with zero closed messages returns 0 and makes no changes."""
    mailbox = tmp_path / ".ai_mail.local"
    mailbox.mkdir(parents=True)
    original_messages = [
        {"id": "m1", "status": "new", "subject": "A"},
        {"id": "m2", "status": "opened", "subject": "B"},
    ]
    inbox_data = {"messages": list(original_messages)}

    swept = mod._sweep_closed(inbox_data, mailbox)

    assert swept == 0
    assert len(inbox_data["messages"]) == 2
    assert not (mailbox / "deleted").exists()


def test_sweep_closed_multiple_closed(tmp_path: Path):
    """Multiple closed messages are all swept in one pass."""
    mailbox = tmp_path / ".ai_mail.local"
    mailbox.mkdir(parents=True)
    inbox_data = {
        "messages": [
            {"id": "m1", "status": "closed", "subject": "Done1"},
            {"id": "m2", "status": "closed", "subject": "Done2"},
            {"id": "m3", "status": "new", "subject": "Active"},
        ]
    }

    swept = mod._sweep_closed(inbox_data, mailbox)

    assert swept == 2
    assert len(inbox_data["messages"]) == 1
    assert inbox_data["messages"][0]["id"] == "m3"
    deleted_files = list((mailbox / "deleted").glob("*.json"))
    assert len(deleted_files) == 2


def test_sweep_closed_archive_failure_still_removes(tmp_path: Path, monkeypatch):
    """If archival fails for one message, it's still removed from inbox."""
    mailbox = tmp_path / ".ai_mail.local"
    mailbox.mkdir(parents=True)

    call_count = [0]
    original_save = mod._save_to_deleted_folder

    def _failing_save(mp, msg):
        call_count[0] += 1
        if call_count[0] == 1:
            raise OSError("disk full")
        return original_save(mp, msg)

    monkeypatch.setattr(mod, "_save_to_deleted_folder", _failing_save)

    inbox_data = {
        "messages": [
            {"id": "m1", "status": "closed", "subject": "Fail"},
            {"id": "m2", "status": "closed", "subject": "OK"},
            {"id": "m3", "status": "new", "subject": "Active"},
        ]
    }

    swept = mod._sweep_closed(inbox_data, mailbox)

    assert swept == 2
    assert len(inbox_data["messages"]) == 1


def test_sweep_closed_on_read_via_load_inbox(tmp_path: Path, monkeypatch):
    """Closed message injected by raw JSON edit is swept on next load_inbox."""
    monkeypatch.setattr(ops_mod, "_get_inbox_lock", lambda: _noop_lock)

    mailbox = tmp_path / ".ai_mail.local"
    mailbox.mkdir(parents=True)
    inbox_file = mailbox / "inbox.json"
    data = {
        "mailbox": "inbox",
        "total_messages": 2,
        "unread_count": 1,
        "messages": [
            {"id": "m1", "status": "new", "subject": "Active", "read": False},
            {"id": "m2", "status": "closed", "subject": "Stale", "read": True},
        ],
    }
    inbox_file.write_text(json.dumps(data), encoding="utf-8")

    result = ops_mod.load_inbox(inbox_file)

    assert len(result["messages"]) == 1
    assert result["messages"][0]["id"] == "m1"
    # Verify persistence — file should be updated
    with open(inbox_file, "r", encoding="utf-8") as f:
        persisted = json.load(f)
    assert len(persisted["messages"]) == 1
    # Verify archived
    deleted_files = list((mailbox / "deleted").glob("*.json"))
    assert len(deleted_files) == 1


def test_sweep_on_mark_as_opened_cleans_stale_closed(tmp_path: Path):
    """Opening a message also sweeps any stale closed messages in inbox."""
    branch_path = tmp_path / "branch"
    _make_inbox(
        branch_path,
        [
            {"id": "m1", "status": "new", "subject": "Target", "read": False},
            {"id": "m2", "status": "closed", "subject": "Stale", "read": True},
        ],
    )

    success, _, _ = mod.mark_as_opened(branch_path, "m1")
    assert success is True

    inbox_file = branch_path / ".ai_mail.local" / "inbox.json"
    with open(inbox_file, "r", encoding="utf-8") as f:
        inbox_data = json.load(f)
    assert len(inbox_data["messages"]) == 1
    assert inbox_data["messages"][0]["id"] == "m1"
    assert inbox_data["total_messages"] == 1


def test_sweep_on_mark_as_closed_cleans_other_stale(tmp_path: Path):
    """Closing one message also sweeps other stale closed messages."""
    branch_path = tmp_path / "branch"
    _make_inbox(
        branch_path,
        [
            {"id": "m1", "status": "opened", "subject": "Close Me", "read": True},
            {"id": "m2", "status": "closed", "subject": "Stale", "read": True},
            {"id": "m3", "status": "new", "subject": "Active", "read": False},
        ],
    )

    success, _ = mod.mark_as_closed_and_archive(branch_path, "m1")
    assert success is True

    inbox_file = branch_path / ".ai_mail.local" / "inbox.json"
    with open(inbox_file, "r", encoding="utf-8") as f:
        inbox_data = json.load(f)
    assert len(inbox_data["messages"]) == 1
    assert inbox_data["messages"][0]["id"] == "m3"
    assert inbox_data["total_messages"] == 1
    assert inbox_data["unread_count"] == 1
    # Both m1 (properly closed) and m2 (swept) should be in deleted/
    deleted_files = list((branch_path / ".ai_mail.local" / "deleted").glob("*.json"))
    assert len(deleted_files) == 2


def test_proper_close_does_not_double_archive(tmp_path: Path):
    """Closing via mark_as_closed_and_archive does not produce duplicate archives."""
    branch_path = tmp_path / "branch"
    _make_inbox(
        branch_path,
        [{"id": "m1", "status": "opened", "subject": "Normal Close", "read": True}],
    )

    success, _ = mod.mark_as_closed_and_archive(branch_path, "m1")
    assert success is True

    deleted_files = list((branch_path / ".ai_mail.local" / "deleted").glob("*.json"))
    assert len(deleted_files) == 1
