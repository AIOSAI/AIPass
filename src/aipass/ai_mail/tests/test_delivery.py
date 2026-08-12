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
    _check_cross_project_boundary,
    _migrate_inbox_format,
    _is_private_branch_email,
    _resolve_reply_path,
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
    with patch.object(delivery_mod, "_emit_notification_event"):
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


# ---- _resolve_reply_path() tests ------------------------------


def test_resolve_reply_path_no_env(monkeypatch):
    """Returns empty string when AIPASS_CALLER_CWD is not set."""
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
    assert _resolve_reply_path() == ""


def test_resolve_reply_path_inbox_in_cwd(tmp_path, monkeypatch):
    """Returns inbox path when .ai_mail.local/inbox.json exists in caller CWD."""
    inbox_dir = tmp_path / ".ai_mail.local"
    inbox_dir.mkdir(parents=True)
    inbox_file = inbox_dir / "inbox.json"
    inbox_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
    assert _resolve_reply_path() == str(inbox_file)


def test_resolve_reply_path_inbox_in_parent(tmp_path, monkeypatch):
    """Returns inbox path when .ai_mail.local/inbox.json exists in a parent of caller CWD."""
    inbox_dir = tmp_path / ".ai_mail.local"
    inbox_dir.mkdir(parents=True)
    inbox_file = inbox_dir / "inbox.json"
    inbox_file.write_text("{}", encoding="utf-8")

    nested_cwd = tmp_path / "src" / "feature"
    nested_cwd.mkdir(parents=True)
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(nested_cwd))

    assert _resolve_reply_path() == str(inbox_file)


def test_resolve_reply_path_no_inbox(tmp_path, monkeypatch):
    """Returns empty string when no .ai_mail.local/inbox.json found in tree."""
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
    assert _resolve_reply_path() == ""


def test_deliver_stores_reply_path_from_env(tmp_path, repo_root, noop_inbox_lock, monkeypatch):
    """reply_path env detection is stored on delivered message."""
    branches = _setup_branch(tmp_path)
    caller_project = tmp_path / "external_project"
    inbox_dir = caller_project / ".ai_mail.local"
    inbox_dir.mkdir(parents=True)
    inbox_file = inbox_dir / "inbox.json"
    inbox_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("AIPASS_CALLER_CWD", str(caller_project))

    with patch.object(delivery_mod, "get_all_branches", return_value=branches):
        success, _ = deliver_email_to_branch("@target", _make_email_data())

    assert success is True
    inbox_file_target = Path(branches[0]["path"]) / ".ai_mail.local" / "inbox.json"
    with open(inbox_file_target, "r", encoding="utf-8") as f:
        inbox = json.load(f)
    msg = inbox["messages"][0]
    assert "reply_path" in msg
    assert msg["reply_path"] == str(inbox_file)


# ---- _check_cross_project_boundary() tests ------------------------------


def test_cross_project_no_caller_cwd_allows(tmp_path, monkeypatch):
    """No AIPASS_CALLER_CWD → host-internal, always allowed."""
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
    refused, _ = _check_cross_project_boundary(tmp_path, "@sender")
    assert refused is False


def test_cross_project_same_root_allows(tmp_path, monkeypatch):
    """Sender and recipient in the same project → allowed."""
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    sender_dir = tmp_path / "src" / "branch_a"
    sender_dir.mkdir(parents=True)
    recipient_dir = tmp_path / "src" / "branch_b"
    recipient_dir.mkdir(parents=True)

    monkeypatch.setenv("AIPASS_CALLER_CWD", str(sender_dir))
    refused, _ = _check_cross_project_boundary(recipient_dir, "@branch_b")
    assert refused is False


def test_cross_project_different_roots_refuses(tmp_path, monkeypatch):
    """Sender in nested project, recipient in host → refused."""
    host = tmp_path / "host"
    host.mkdir()
    (host / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    recipient_dir = host / "src" / "devpulse"
    recipient_dir.mkdir(parents=True)

    project = host / "projects" / "myproj"
    project.mkdir(parents=True)
    (project / "MYPROJ_REGISTRY.json").write_text("{}", encoding="utf-8")
    sender_dir = project / "src"
    sender_dir.mkdir(parents=True)

    monkeypatch.setenv("AIPASS_CALLER_CWD", str(sender_dir))
    refused, msg = _check_cross_project_boundary(recipient_dir, "@proj_agent")
    assert refused is True
    assert "Cross-project mail refused" in msg
    assert "feedback channel" in msg


def test_cross_project_sender_no_registry_allows(tmp_path, monkeypatch):
    """Sender in dir with no registry → cannot determine boundary, allow."""
    isolated = tmp_path / "nowhere"
    isolated.mkdir()
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(isolated))

    recipient = tmp_path / "host" / "branch"
    recipient.mkdir(parents=True)
    (tmp_path / "host" / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")

    refused, _ = _check_cross_project_boundary(recipient, "@branch")
    assert refused is False


def test_cross_project_recipient_no_registry_allows(tmp_path, monkeypatch):
    """Recipient in dir with no registry → cannot determine boundary, allow."""
    sender_dir = tmp_path / "host" / "src"
    sender_dir.mkdir(parents=True)
    (tmp_path / "host" / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(sender_dir))

    recipient = tmp_path / "orphan"
    recipient.mkdir()

    refused, _ = _check_cross_project_boundary(recipient, "@orphan")
    assert refused is False


def test_cross_project_delivery_e2e_refused(tmp_path, repo_root, noop_inbox_lock, monkeypatch):
    """End-to-end: delivery from nested project to host branch is refused."""
    host_root = repo_root
    (host_root / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")

    branches = _setup_branch(tmp_path)

    project = host_root / "projects" / "testproj"
    project.mkdir(parents=True)
    (project / "TESTPROJ_REGISTRY.json").write_text("{}", encoding="utf-8")
    sender_cwd = project / "src"
    sender_cwd.mkdir()

    monkeypatch.setenv("AIPASS_CALLER_CWD", str(sender_cwd))

    with patch.object(delivery_mod, "get_all_branches", return_value=branches):
        success, error = deliver_email_to_branch(
            "@target",
            _make_email_data(sender="@testproj"),
        )

    assert success is False
    assert "Cross-project mail refused" in error


def test_cross_project_delivery_same_project_allowed(tmp_path, repo_root, noop_inbox_lock, monkeypatch):
    """End-to-end: delivery within the same project is allowed."""
    (repo_root / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")

    branches = _setup_branch(tmp_path)

    sender_cwd = tmp_path / "src" / "other_branch"
    sender_cwd.mkdir(parents=True)

    monkeypatch.setenv("AIPASS_CALLER_CWD", str(sender_cwd))

    with patch.object(delivery_mod, "get_all_branches", return_value=branches):
        success, error = deliver_email_to_branch(
            "@target",
            _make_email_data(),
        )

    assert success is True
    assert error == ""
