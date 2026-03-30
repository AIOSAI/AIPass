# =================== AIPass ====================
# Name: test_delivery.py
# Description: Tests for email delivery handler
# Version: 1.0.0
# Created: 2026-03-29
# Modified: 2026-03-29
# =============================================

"""Tests for email delivery handler -- inbox migration, private branch check, delivery."""

import json
import pytest
from contextlib import contextmanager
from pathlib import Path
from typing import cast, Dict
from unittest.mock import patch, MagicMock

import aipass.ai_mail.apps.handlers.email.delivery as delivery_mod
from aipass.ai_mail.apps.handlers.email.delivery import (
    _migrate_inbox_format,
    _is_private_branch_email,
    deliver_email_to_branch,
)


# ---- Fixtures ------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_json_handler():
    """Prevent log_operation from writing real JSON files during tests."""
    with patch("aipass.ai_mail.apps.handlers.email.delivery.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


@pytest.fixture(autouse=True)
def _silence_notifications():
    """Prevent desktop notifications during tests."""
    with patch.object(delivery_mod, "_send_desktop_notification"):
        yield


@pytest.fixture
def repo_root(tmp_path, monkeypatch):
    """Point _REPO_ROOT to tmp_path for isolation."""
    monkeypatch.setattr(delivery_mod, "_REPO_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def noop_inbox_lock(monkeypatch):
    """Replace _get_inbox_lock with a no-op context manager."""

    @contextmanager
    def _noop_lock(path):
        yield

    monkeypatch.setattr(delivery_mod, "_get_inbox_lock", lambda: _noop_lock)


def _make_email_data(
    *,
    sender: str = "@sender",
    sender_name: str = "Sender",
    recipient: str = "@target",
    subject: str = "Test subject",
    message: str = "Test body",
    timestamp: str = "2026-03-29T12:00:00Z",
    **extra,
) -> dict:
    """Build a minimal email_data dict for deliver_email_to_branch."""
    data = {
        "from": sender,
        "from_name": sender_name,
        "to": recipient,
        "subject": subject,
        "message": message,
        "timestamp": timestamp,
    }
    data.update(extra)
    return data


# ---- _migrate_inbox_format() tests ------------------------------


def test_migrate_old_inbox_key(tmp_path):
    """Old format {'inbox': [...]} migrates to v2 with 'messages' key."""
    inbox_file = tmp_path / "inbox.json"
    old_data = {"inbox": [{"id": "m1", "status": "new"}]}
    inbox_file.write_text(json.dumps(old_data), encoding="utf-8")

    result = _migrate_inbox_format(old_data, inbox_file)

    assert "inbox" not in result, "Old 'inbox' key should be removed"
    assert result["messages"] == [{"id": "m1", "status": "new"}]
    assert result["mailbox"] == "inbox"
    assert result["total_messages"] == 1
    assert result["unread_count"] == 1


def test_migrate_list_input(tmp_path):
    """Top-level list gets wrapped into {'messages': [...]}."""
    inbox_file = tmp_path / "inbox.json"
    raw_list = [{"id": "m1", "status": "opened"}]
    inbox_file.write_text(json.dumps(raw_list), encoding="utf-8")

    result = _migrate_inbox_format(cast(Dict, raw_list), inbox_file)

    assert isinstance(result, dict)
    assert result["messages"] == [{"id": "m1", "status": "opened"}]
    assert result["total_messages"] == 1
    assert result["unread_count"] == 0  # status=opened is not new


def test_migrate_missing_messages_key(tmp_path):
    """Dict without 'messages' key gets an empty messages list."""
    inbox_file = tmp_path / "inbox.json"
    data = {"mailbox": "inbox"}
    inbox_file.write_text(json.dumps(data), encoding="utf-8")

    result = _migrate_inbox_format(data, inbox_file)

    assert result["messages"] == []
    assert result["total_messages"] == 0
    assert result["unread_count"] == 0


def test_migrate_already_v2_no_write(tmp_path):
    """Fully valid v2 data does not rewrite the file."""
    inbox_file = tmp_path / "inbox.json"
    v2_data = {
        "mailbox": "inbox",
        "total_messages": 1,
        "unread_count": 1,
        "messages": [{"id": "m1", "status": "new"}],
    }
    original_text = json.dumps(v2_data, indent=2, ensure_ascii=False)
    inbox_file.write_text(original_text, encoding="utf-8")

    _migrate_inbox_format(v2_data, inbox_file)

    assert inbox_file.read_text(encoding="utf-8") == original_text


def test_migrate_unread_count_mixed_statuses(tmp_path):
    """Unread count considers 'new' status and missing status without read flag."""
    inbox_file = tmp_path / "inbox.json"
    data = {
        "messages": [
            {"id": "m1", "status": "new"},
            {"id": "m2", "status": "opened"},
            {"id": "m3"},  # no status, no read -> counts as unread
            {"id": "m4", "read": True},  # no status, read=True -> not unread
        ],
    }
    inbox_file.write_text(json.dumps(data), encoding="utf-8")

    result = _migrate_inbox_format(data, inbox_file)

    assert result["unread_count"] == 2  # m1 (new) + m3 (no status, not read)
    assert result["total_messages"] == 4


def test_migrate_persists_to_disk(tmp_path):
    """Migration writes the updated data back to the file."""
    inbox_file = tmp_path / "inbox.json"
    old_data = {"inbox": [{"id": "m1", "status": "new"}]}
    inbox_file.write_text(json.dumps(old_data), encoding="utf-8")

    _migrate_inbox_format(old_data, inbox_file)

    with open(inbox_file, "r", encoding="utf-8") as f:
        persisted = json.load(f)

    assert "inbox" not in persisted
    assert persisted["messages"] == [{"id": "m1", "status": "new"}]
    assert persisted["mailbox"] == "inbox"
    assert persisted["total_messages"] == 1
    assert persisted["unread_count"] == 1


# ---- _is_private_branch_email() tests ----------------------------


def test_private_branch_email_no_registry(repo_root):
    """No registry file -> not private."""
    assert _is_private_branch_email("@secret") is False


def test_private_branch_email_found(repo_root):
    """Email in registry is private."""
    registry_path = repo_root / "PRIVATE_BRANCH_REGISTRY.json"
    registry_data = {
        "branches": [
            {"email": "@secret", "name": "SECRET"},
            {"email": "@hidden", "name": "HIDDEN"},
        ]
    }
    registry_path.write_text(json.dumps(registry_data), encoding="utf-8")

    assert _is_private_branch_email("@secret") is True
    assert _is_private_branch_email("@hidden") is True


def test_private_branch_email_not_found(repo_root):
    """Email not in registry is not private."""
    registry_path = repo_root / "PRIVATE_BRANCH_REGISTRY.json"
    registry_data = {"branches": [{"email": "@secret", "name": "SECRET"}]}
    registry_path.write_text(json.dumps(registry_data), encoding="utf-8")

    assert _is_private_branch_email("@public") is False


def test_private_branch_email_corrupted_json(repo_root):
    """Corrupted registry file -> not private (graceful failure)."""
    registry_path = repo_root / "PRIVATE_BRANCH_REGISTRY.json"
    registry_path.write_text("not json", encoding="utf-8")

    assert _is_private_branch_email("@secret") is False


# ---- deliver_email_to_branch() tests ------------------------------


def _setup_branch(tmp_path, email: str = "@target", name: str = "TARGET"):
    """Create branch directory with .ai_mail.local/inbox.json and return branch data."""
    branch_path = tmp_path / "branches" / name.lower()
    mailbox_dir = branch_path / ".ai_mail.local"
    mailbox_dir.mkdir(parents=True, exist_ok=True)
    inbox_file = mailbox_dir / "inbox.json"
    inbox_data = {
        "mailbox": "inbox",
        "total_messages": 0,
        "unread_count": 0,
        "messages": [],
    }
    inbox_file.write_text(json.dumps(inbox_data, indent=2), encoding="utf-8")
    return [{"name": name, "path": str(branch_path), "email": email}]


def test_deliver_happy_path(tmp_path, repo_root, noop_inbox_lock):
    """Successful delivery writes message to inbox and returns (True, '')."""
    branches = _setup_branch(tmp_path)

    with patch.object(delivery_mod, "get_all_branches", return_value=branches):
        success, error = deliver_email_to_branch(
            "@target",
            _make_email_data(),
        )

    assert success is True
    assert error == ""

    inbox_file = Path(branches[0]["path"]) / ".ai_mail.local" / "inbox.json"
    with open(inbox_file, "r", encoding="utf-8") as f:
        inbox = json.load(f)

    assert inbox["total_messages"] == 1
    assert inbox["unread_count"] == 1
    assert len(inbox["messages"]) == 1
    msg = inbox["messages"][0]
    assert msg["subject"] == "Test subject"
    assert msg["from"] == "@sender"
    assert msg["from_name"] == "Sender"
    assert msg["status"] == "new"
    assert msg["message"] == "Test body"
    assert "id" in msg
    assert msg["priority"] == "normal"
    assert msg["auto_execute"] is False


def test_deliver_unknown_branch(repo_root, noop_inbox_lock):
    """Delivery to unknown email returns (False, error message)."""
    with patch.object(delivery_mod, "get_all_branches", return_value=[]):
        success, error = deliver_email_to_branch(
            "@nonexistent",
            _make_email_data(),
        )

    assert success is False
    assert "Unknown branch email" in error
    assert "@nonexistent" in error


def test_deliver_private_branch_blocked(tmp_path, repo_root, noop_inbox_lock):
    """Delivery to a private branch from another branch is blocked."""
    branches = _setup_branch(tmp_path)

    with (
        patch.object(delivery_mod, "get_all_branches", return_value=branches),
        patch.object(delivery_mod, "_is_private_branch_email", return_value=True),
    ):
        success, error = deliver_email_to_branch(
            "@target",
            _make_email_data(sender="@other"),
        )

    assert success is False
    assert "private branch" in error.lower()


def test_deliver_private_branch_self_send_allowed(tmp_path, repo_root, noop_inbox_lock):
    """Private branch can deliver to itself (self-send is allowed)."""
    branches = _setup_branch(tmp_path)

    with (
        patch.object(delivery_mod, "get_all_branches", return_value=branches),
        patch.object(delivery_mod, "_is_private_branch_email", return_value=True),
    ):
        success, error = deliver_email_to_branch(
            "@target",
            _make_email_data(sender="@target"),
        )

    assert success is True
    assert error == ""


def test_deliver_auto_provisions_inbox(tmp_path, repo_root, noop_inbox_lock):
    """Delivery auto-creates inbox.json if missing (self-healing)."""
    branch_path = tmp_path / "branches" / "newbranch"
    branch_path.mkdir(parents=True)
    branches = [{"name": "NEW", "path": str(branch_path), "email": "@new"}]

    with patch.object(delivery_mod, "get_all_branches", return_value=branches):
        success, error = deliver_email_to_branch(
            "@new",
            _make_email_data(recipient="@new"),
        )

    assert success is True
    assert error == ""

    inbox_file = branch_path / ".ai_mail.local" / "inbox.json"
    assert inbox_file.exists()
    with open(inbox_file, "r", encoding="utf-8") as f:
        inbox = json.load(f)
    assert inbox["total_messages"] == 1
    assert len(inbox["messages"]) == 1


def test_deliver_on_delivered_callback(tmp_path, repo_root, noop_inbox_lock):
    """on_delivered callback is invoked with correct arguments."""
    branches = _setup_branch(tmp_path)
    callback = MagicMock()

    with patch.object(delivery_mod, "get_all_branches", return_value=branches):
        success, error = deliver_email_to_branch(
            "@target",
            _make_email_data(),
            on_delivered=callback,
        )

    assert success is True
    assert error == ""
    callback.assert_called_once()
    args = callback.call_args[0]
    assert args[0] == Path(branches[0]["path"])  # branch_path
    assert args[1] == 1  # new_count
    assert args[2] == 0  # opened_count
    assert args[3] == 1  # total


def test_deliver_reply_to_field(tmp_path, repo_root, noop_inbox_lock):
    """reply_to field is included in delivered message when provided."""
    branches = _setup_branch(tmp_path)

    with patch.object(delivery_mod, "get_all_branches", return_value=branches):
        success, _ = deliver_email_to_branch(
            "@target",
            _make_email_data(reply_to="msg-abc"),
        )

    assert success is True
    inbox_file = Path(branches[0]["path"]) / ".ai_mail.local" / "inbox.json"
    with open(inbox_file, "r", encoding="utf-8") as f:
        inbox = json.load(f)
    assert inbox["messages"][0]["reply_to"] == "msg-abc"


def test_deliver_multiple_messages_prepends(tmp_path, repo_root, noop_inbox_lock):
    """Multiple deliveries prepend newest message first."""
    branches = _setup_branch(tmp_path)

    with patch.object(delivery_mod, "get_all_branches", return_value=branches):
        deliver_email_to_branch("@target", _make_email_data(subject="First"))
        deliver_email_to_branch("@target", _make_email_data(subject="Second"))

    inbox_file = Path(branches[0]["path"]) / ".ai_mail.local" / "inbox.json"
    with open(inbox_file, "r", encoding="utf-8") as f:
        inbox = json.load(f)

    assert inbox["total_messages"] == 2
    assert inbox["unread_count"] == 2
    assert inbox["messages"][0]["subject"] == "Second"
    assert inbox["messages"][1]["subject"] == "First"


def test_deliver_path_input_resolves_to_email(tmp_path, repo_root, noop_inbox_lock):
    """Path-based to_branch (from DRONE @ resolution) resolves to email."""
    branch_path = tmp_path / "branches" / "target"
    mailbox_dir = branch_path / ".ai_mail.local"
    mailbox_dir.mkdir(parents=True, exist_ok=True)
    inbox_file = mailbox_dir / "inbox.json"
    inbox_data = {"mailbox": "inbox", "total_messages": 0, "unread_count": 0, "messages": []}
    inbox_file.write_text(json.dumps(inbox_data, indent=2), encoding="utf-8")

    branches = [{"name": "TARGET", "path": str(branch_path), "email": "@target"}]

    with patch.object(delivery_mod, "get_all_branches", return_value=branches):
        success, error = deliver_email_to_branch(
            str(branch_path),
            _make_email_data(),
        )

    assert success is True
    assert error == ""


def test_deliver_path_input_unresolvable(repo_root, noop_inbox_lock):
    """Unresolvable path returns failure."""
    with patch.object(delivery_mod, "get_all_branches", return_value=[]):
        success, error = deliver_email_to_branch(
            "/nonexistent/path",
            _make_email_data(),
        )

    assert success is False
    assert "Could not resolve path" in error
