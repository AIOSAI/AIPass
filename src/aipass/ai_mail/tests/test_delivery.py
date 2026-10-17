# =================== AIPass ====================
# Name: test_delivery.py
# Description: Tests for email delivery handler
# Version: 1.1.0
# Created: 2026-03-29
# Modified: 2026-10-16
# =============================================

"""Tests for apps/handlers/email/delivery.py."""

# Inbox migration, private branch check, delivery.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — _auto_register_sender()'s broad except Exception around contact auto-registration
# seedgo: no-test-needed(shared) — a wake event carries no mail address: tests/test_wake.py pins its exact call

import json
import pytest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch, MagicMock

import aipass.ai_mail.apps.handlers.email.delivery as delivery_mod
import aipass.ai_mail.apps.handlers.notify as notify_mod
from aipass.memory.apps.modules import fleet
from aipass.ai_mail.apps.handlers.email.delivery import deliver_email_to_branch


# ---- Fixtures ------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_json_handler():
    """Prevent log_operation from writing real JSON files during tests."""
    with patch("aipass.ai_mail.apps.handlers.email.delivery.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


@pytest.fixture(autouse=True)
def _fresh_notification_rate_limit(monkeypatch):
    """The 3-per-30s feed limit is module state; one test's events must not mute the next's."""
    monkeypatch.setattr(delivery_mod, "_NOTIFICATION_TIMESTAMPS", {})


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

    result = _deliver_onto(inbox_file)

    assert "inbox" not in result, "Old 'inbox' key should be removed"
    assert result["messages"][1:] == [{"id": "m1", "status": "new"}]
    assert result["mailbox"] == "inbox"
    assert result["total_messages"] == 2
    assert result["unread_count"] == 1


def test_migrate_list_input(tmp_path):
    """Top-level list gets wrapped into {'messages': [...]}."""
    inbox_file = tmp_path / "inbox.json"
    raw_list = [{"id": "m1", "status": "opened"}]
    inbox_file.write_text(json.dumps(raw_list), encoding="utf-8")

    result = _deliver_onto(inbox_file)

    assert isinstance(result, dict)
    assert result["messages"][1:] == [{"id": "m1", "status": "opened"}]
    assert result["total_messages"] == 2
    assert result["unread_count"] == 0  # status=opened is not new


def test_migrate_missing_messages_key(tmp_path):
    """Dict without 'messages' key gets an empty messages list."""
    inbox_file = tmp_path / "inbox.json"
    data = {"mailbox": "inbox"}
    inbox_file.write_text(json.dumps(data), encoding="utf-8")

    result = _deliver_onto(inbox_file)

    assert result["messages"][1:] == []
    assert result["total_messages"] == 1
    assert result["unread_count"] == 0


# test_migrate_already_v2_no_write retired (ai_mail, leg 15, @devpulse's leg 14
# ruling): "already v2 is not rewritten" cannot be seen through any caller, as
# both delivery lanes rewrite the inbox inside the same lock, so it proved nothing.


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

    result = _deliver_onto(inbox_file)

    assert result["unread_count"] == 2  # m1 (new) + m3 (no status, not read); the delivered one is opened
    assert result["total_messages"] == 5


def test_migrate_persists_to_disk(tmp_path):
    """Migration writes the updated data back to the file."""
    inbox_file = tmp_path / "inbox.json"
    old_data = {"inbox": [{"id": "m1", "status": "new"}]}
    inbox_file.write_text(json.dumps(old_data), encoding="utf-8")

    _deliver_onto(inbox_file)

    with open(inbox_file, "r", encoding="utf-8") as f:
        persisted = json.load(f)

    assert "inbox" not in persisted
    assert persisted["messages"][1:] == [{"id": "m1", "status": "new"}]
    assert persisted["mailbox"] == "inbox"
    assert persisted["total_messages"] == 2
    assert persisted["unread_count"] == 1


# ---- _is_private_branch_email() tests ----------------------------


def test_private_branch_email_no_registry(repo_root):
    """No registry file -> not private."""
    assert _private_refusal(repo_root, "@secret") == ""


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

    assert _private_refusal(repo_root, "@secret") == "Cannot deliver to private branch: @secret"
    assert _private_refusal(repo_root, "@hidden") == "Cannot deliver to private branch: @hidden"


def test_private_branch_email_not_found(repo_root):
    """Email not in registry is not private."""
    registry_path = repo_root / "PRIVATE_BRANCH_REGISTRY.json"
    registry_data = {"branches": [{"email": "@secret", "name": "SECRET"}]}
    registry_path.write_text(json.dumps(registry_data), encoding="utf-8")

    assert _private_refusal(repo_root, "@public") == ""


def test_private_branch_email_corrupted_json(repo_root):
    """Corrupted registry file -> not private (graceful failure)."""
    registry_path = repo_root / "PRIVATE_BRANCH_REGISTRY.json"
    registry_path.write_text("not json", encoding="utf-8")

    assert _private_refusal(repo_root, "@secret") == ""


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


# The helpers below reach delivery's private checks through its public lanes
# instead of calling them (ai_mail, leg 14).


def _deliver_into(recipient: Path, to_branch: str = "@target", sender: str = "@sender"):
    """deliver_email_to_branch with the registry stubbed so `to_branch` names `recipient`.

    Returns (success, message); the tmp inbox is provisioned and written when it passes.
    """
    lookup = MagicMock(return_value=[{"name": "T", "path": str(recipient), "email": to_branch}])
    with patch.object(delivery_mod, "get_all_branches", lookup):
        success, msg = deliver_email_to_branch(to_branch, _make_email_data(sender=sender, recipient=to_branch))
    lookup.assert_called_with()
    return success, msg


def _boundary(recipient: Path, sender: str):
    """The cross-project verdict as delivery acts on it: (refused, message)."""
    success, msg = _deliver_into(recipient, sender=sender)
    return not success, msg


def _private_refusal(repo_root: Path, to_branch: str) -> str:
    """The refusal a delivery to `to_branch` meets, "" when it is delivered."""
    success, msg = _deliver_into(repo_root / "seats" / to_branch.lstrip("@"), to_branch=to_branch)
    return "" if success else msg


def _reply_path_stamped(tmp_path: Path) -> str:
    """The reply_path a delivered message carries, "" when none was stamped."""
    recipient = tmp_path / "recipient" / "target"
    success, msg = _deliver_into(recipient)
    assert success is True, msg
    inbox = json.loads((recipient / ".ai_mail.local" / "inbox.json").read_text(encoding="utf-8"))
    return inbox["messages"][0].get("reply_path", "")


_DELIVERED = {"id": "d1", "from": "@sender", "subject": "S", "message": "M", "status": "opened"}


def _deliver_onto(inbox_file: Path) -> dict:
    """deliver_to_inbox_file onto `inbox_file` (migrated on the way); the inbox as it lands."""
    success, err, _rid = delivery_mod.deliver_to_inbox_file(inbox_file, dict(_DELIVERED))
    assert success is True, err
    return json.loads(inbox_file.read_text(encoding="utf-8"))


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


def test_deliver_says_so_when_the_external_tier_cannot_answer(repo_root, noop_inbox_lock, monkeypatch):
    """A gateway that cannot answer is not "unknown address": delivery names it.

    Before leg 11 get_external_branches answered {} on any gateway failure, so a
    dispatch to an external citizen was refused as an unknown branch while the
    tier that knows it was down. The refusal keeps delivery's (False, message)
    shape that trigger already handles. Its proof is the mutant that answers {}
    again (ai_mail, leg 11).
    """

    def _gateway_down(**kwargs):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(fleet, "external_branches", _gateway_down)

    with patch.object(delivery_mod, "get_all_branches", return_value=[]):
        success, error = deliver_email_to_branch("@nonexistent", _make_email_data())

    assert success is False
    assert error == "External citizen tier unavailable, @nonexistent not resolved: gateway down"


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
    """Delivery auto-creates inbox.json if missing (self-healing).

    Directory and email deliberately match — a mismatched pair here
    (path .../newbranch, email @new) once left a "new" row in the live
    contacts.json that read as a truncated key when it was only ever an
    inconsistent fixture (found live, 2026-08-16, @devpulse).
    """
    branch_path = tmp_path / "branches" / "newbranch"
    branch_path.mkdir(parents=True)
    branches = [{"name": "NEWBRANCH", "path": str(branch_path), "email": "@newbranch"}]

    with patch.object(delivery_mod, "get_all_branches", return_value=branches):
        success, error = deliver_email_to_branch(
            "@newbranch",
            _make_email_data(recipient="@newbranch"),
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


def test_deliver_path_input_unresolvable(repo_root, noop_inbox_lock, tmp_path):
    """Unresolvable path returns failure."""
    with patch.object(delivery_mod, "get_all_branches", return_value=[]):
        success, error = deliver_email_to_branch(
            str(tmp_path / "nonexistent" / "path"),
            _make_email_data(),
        )

    assert success is False
    assert "Could not resolve path" in error


# ---- _resolve_reply_path() tests ------------------------------


def test_resolve_reply_path_no_env(tmp_path, monkeypatch):
    """Returns empty string when AIPASS_CALLER_CWD is not set."""
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
    assert _reply_path_stamped(tmp_path) == ""


def test_resolve_reply_path_inbox_in_cwd(tmp_path, monkeypatch):
    """Returns inbox path when .ai_mail.local/inbox.json exists in caller CWD."""
    inbox_dir = tmp_path / ".ai_mail.local"
    inbox_dir.mkdir(parents=True)
    inbox_file = inbox_dir / "inbox.json"
    inbox_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
    assert _reply_path_stamped(tmp_path) == str(inbox_file)


def test_resolve_reply_path_inbox_in_parent(tmp_path, monkeypatch):
    """Returns inbox path when .ai_mail.local/inbox.json exists in a parent of caller CWD."""
    inbox_dir = tmp_path / ".ai_mail.local"
    inbox_dir.mkdir(parents=True)
    inbox_file = inbox_dir / "inbox.json"
    inbox_file.write_text("{}", encoding="utf-8")

    nested_cwd = tmp_path / "src" / "feature"
    nested_cwd.mkdir(parents=True)
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(nested_cwd))

    assert _reply_path_stamped(tmp_path) == str(inbox_file)


def test_resolve_reply_path_no_inbox(tmp_path, monkeypatch):
    """Returns empty string when no .ai_mail.local/inbox.json found in tree."""
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
    assert _reply_path_stamped(tmp_path) == ""


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
    refused, _ = _boundary(tmp_path, "@sender")
    assert refused is False


def test_cross_project_same_root_allows(tmp_path, monkeypatch):
    """Sender and recipient in the same project → allowed."""
    (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    sender_dir = tmp_path / "src" / "branch_a"
    sender_dir.mkdir(parents=True)
    recipient_dir = tmp_path / "src" / "branch_b"
    recipient_dir.mkdir(parents=True)

    monkeypatch.setenv("AIPASS_CALLER_CWD", str(sender_dir))
    refused, _ = _boundary(recipient_dir, "@branch_b")
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
    refused, msg = _boundary(recipient_dir, "@proj_agent")
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

    refused, _ = _boundary(recipient, "@branch")
    assert refused is False


def test_cross_project_recipient_no_registry_allows(tmp_path, monkeypatch):
    """Recipient in dir with no registry → cannot determine boundary, allow."""
    sender_dir = tmp_path / "host" / "src"
    sender_dir.mkdir(parents=True)
    (tmp_path / "host" / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(sender_dir))

    recipient = tmp_path / "orphan"
    recipient.mkdir()

    refused, _ = _boundary(recipient, "@orphan")
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


# ---- #754: an unverifiable sender at the external tier ------------------------


def _write_json(path: Path, data: dict) -> None:
    """Write one JSON document, creating its directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _empty_inbox() -> dict:
    """The inbox document delivery appends to."""
    return {"mailbox": "inbox", "total_messages": 0, "unread_count": 0, "messages": []}


@pytest.fixture
def external_world(tmp_path, monkeypatch, noop_inbox_lock):
    """AIPass home with two fleet branches, plus a declared sibling root holding @vera.

    The seam is delivery's _REPO_ROOT, as in test_external_tier_resolution.py:
    @memory's real gateway reads the AIPASS_ROOTS.json written here, so @vera
    resolves through the external tier exactly as it does live. Patching the
    gateway would only prove the mock answers. Caller env is cleared - this suite
    runs inside dispatched agents that carry their own.
    """
    home = tmp_path / "AIPass"
    target = home / "src" / "aipass" / "target"
    devpulse = home / "src" / "aipass" / "devpulse"
    _write_json(target / ".ai_mail.local" / "inbox.json", _empty_inbox())
    _write_json(devpulse / ".trinity" / "passport.json", {"branch_info": {"branch_name": "devpulse"}})
    fleet_rows = [
        {"name": "target", "email": "@target", "path": str(target)},
        {"name": "devpulse", "email": "@devpulse", "path": str(devpulse)},
    ]
    _write_json(home / "AIPASS_REGISTRY.json", {"branches": fleet_rows})

    studio = tmp_path / "Vera-Studio"
    vera = studio / "src" / "vera_studio" / "vera"
    _write_json(vera / ".trinity" / "passport.json", {"branch_info": {"branch_name": "vera", "email": "@vera"}})
    _write_json(
        studio / "VERA-STUDIO_REGISTRY.json",
        {"branches": [{"name": "vera", "email": "@vera", "status": "active", "path": str(vera)}]},
    )
    _write_json(
        home / "AIPASS_ROOTS.json",
        {"roots": [{"path": "../Vera-Studio", "label": "vera-studio", "status": "active"}]},
    )

    monkeypatch.setattr(delivery_mod, "_REPO_ROOT", home)
    monkeypatch.setattr(delivery_mod, "get_all_branches", lambda *a, **kw: fleet_rows)
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
    monkeypatch.delenv("AIPASS_CALLER_BRANCH", raising=False)
    return {"tmp": tmp_path, "target": target, "devpulse": devpulse, "vera": vera}


def _set_unverifiable_caller(world: dict, shape: str, monkeypatch) -> None:
    """The two ways a sender cannot be placed in any project."""
    if shape == "cwd_in_no_project":
        nowhere = world["tmp"] / "nowhere"
        nowhere.mkdir()
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(nowhere))


_UNVERIFIABLE = ["no_caller_cwd", "cwd_in_no_project"]


@pytest.mark.parametrize("shape", _UNVERIFIABLE)
def test_unverified_sender_is_refused_at_the_external_tier(external_world, monkeypatch, shape):
    """#754 pin 1: once the external tier resolves @vera, the boundary check is the last wall."""
    _set_unverifiable_caller(external_world, shape, monkeypatch)

    success, error = deliver_email_to_branch("@vera", _make_email_data(sender="@trigger", recipient="@vera"))

    assert success is False
    assert "Unknown branch email" not in error, "the address resolved - the wall must refuse it, not the map"
    assert "@vera" in error and "external root 'Vera-Studio'" in error and "cannot be verified" in error
    assert not (external_world["vera"] / ".ai_mail.local").exists(), "no inbox may be provisioned"


def test_a_reply_stamp_buys_nothing_without_a_sender_project(external_world):
    """A reply's proof is bounded by the sender's project; with none, a stamp could name any mailbox."""
    laundering_inbox = external_world["target"] / ".ai_mail.local" / "inbox.json"
    _write_json(laundering_inbox, {**_empty_inbox(), "messages": [{"id": "m-vera", "from": "@vera"}]})
    email = _make_email_data(
        sender="@trigger", recipient="@vera", in_reply_to="m-vera", reply_path=str(laundering_inbox)
    )

    success, error = deliver_email_to_branch("@vera", email)

    assert success is False
    assert "cannot be verified" in error
    assert not (external_world["vera"] / ".ai_mail.local").exists()


@pytest.mark.parametrize("shape", _UNVERIFIABLE)
def test_same_sender_to_a_fleet_branch_still_lands(external_world, monkeypatch, shape):
    """#754 pin 2: trigger's in-process path - no caller cwd, fleet recipient - is untouched."""
    _set_unverifiable_caller(external_world, shape, monkeypatch)

    success, error = deliver_email_to_branch("@target", _make_email_data(sender="@trigger", recipient="@target"))

    assert (success, error) == (True, "")
    inbox = json.loads((external_world["target"] / ".ai_mail.local" / "inbox.json").read_text(encoding="utf-8"))
    assert [m["from"] for m in inbox["messages"]] == ["@trigger"]


@pytest.mark.parametrize("caller_cwd", ["no_caller_cwd", "admin_seat"])
def test_verified_admin_still_crosses_to_the_external_tier(external_world, monkeypatch, caller_cwd):
    """#754 pin 3: the verified-admin bridge, with and without a caller cwd."""
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
    if caller_cwd == "admin_seat":
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(external_world["devpulse"]))

    with patch(
        "aipass.ai_mail.apps.handlers.users.verified_caller.verify_admin_caller",
        return_value=(True, "admin grant verified"),
    ):
        success, error = deliver_email_to_branch("@vera", _make_email_data(sender="@devpulse", recipient="@vera"))

    assert (success, error) == (True, "")
    inbox = json.loads((external_world["vera"] / ".ai_mail.local" / "inbox.json").read_text(encoding="utf-8"))
    assert [m["from"] for m in inbox["messages"]] == ["@devpulse"]


def test_an_unreadable_caller_registry_refuses_rather_than_serving_a_namesake(external_world, monkeypatch):
    """A project whose registry cannot be read never has its mail served to another project's namesake.

    Lab has its own @vera, and its LAB_REGISTRY.json is not JSON. Before leg 12
    the caller's registry answered {} on that, the walk climbed on, and the
    external tier served Vera-Studio's @vera; a verified admin is exempt from the
    boundary, so the mail meant for Lab's @vera landed in Vera-Studio. Now
    delivery refuses and names the registry (ai_mail, leg 12).
    """
    lab = external_world["tmp"] / "Lab"
    lab_vera = lab / "src" / "lab" / "vera"
    lab_vera.mkdir(parents=True)
    (lab / "LAB_REGISTRY.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(lab_vera))
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")

    with patch(
        "aipass.ai_mail.apps.handlers.users.verified_caller.verify_admin_caller",
        return_value=(True, "admin grant verified"),
    ):
        success, error = deliver_email_to_branch("@vera", _make_email_data(sender="@devpulse", recipient="@vera"))

    assert success is False
    assert error.startswith("Caller's project registry unreadable, @vera not resolved: LAB_REGISTRY.json ")
    assert not (external_world["vera"] / ".ai_mail.local").exists(), "the namesake must not be served"


def test_an_unreadable_hosted_registry_refuses_the_admin_rather_than_serving_a_namesake(external_world, monkeypatch):
    """The admin sweep never hands a hosted project's mail to another root's namesake.

    projects/lab hosts its own @vera and its registry is not JSON. Before leg 12
    the sweep skipped it, the external tier served Vera-Studio's @vera, and the
    verified admin is exempt from the boundary, so the mail landed there. Green
    from its first run on the cured tree; its proof is the mutant that skips the
    registry again (ai_mail, leg 12).
    """
    lab = external_world["tmp"] / "AIPass" / "projects" / "lab"
    (lab / "vera").mkdir(parents=True)
    (lab / "LAB_REGISTRY.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(external_world["devpulse"]))

    with patch(
        "aipass.ai_mail.apps.handlers.users.verified_caller.verify_admin_caller",
        return_value=(True, "admin grant verified"),
    ):
        success, error = deliver_email_to_branch("@vera", _make_email_data(sender="@devpulse", recipient="@vera"))

    assert success is False
    assert error.startswith("Hosted project registry unreadable, @vera not resolved: LAB_REGISTRY.json ")
    assert not (external_world["vera"] / ".ai_mail.local").exists(), "the namesake must not be served"


def test_an_unreadable_aipass_registry_refuses_rather_than_serving_a_hosted_namesake(external_world, monkeypatch):
    """Mail for an AIPass citizen never lands on a hosted project's citizen of the same name.

    AIPASS_REGISTRY.json is not JSON, so get_all_branches answers [] (stood in
    here: the real one reads this checkout's registry). Before leg 12 the admin
    sweep then found projects/lab's @target and the verified admin, exempt from
    the boundary, had the mail delivered there. Now delivery refuses and names
    the AIPass registry (ai_mail, leg 12).
    """
    home = external_world["tmp"] / "AIPass"
    (home / "AIPASS_REGISTRY.json").write_text("{not json", encoding="utf-8")
    lab_target = home / "projects" / "lab" / "target"
    lab_target.mkdir(parents=True)
    (home / "projects" / "lab" / "LAB_REGISTRY.json").write_text(
        json.dumps({"branches": [{"name": "target", "email": "@target", "path": str(lab_target)}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(delivery_mod, "get_all_branches", lambda *a, **kw: [])
    # No caller cwd: from the admin seat's cwd the caller-project walk already
    # reaches AIPASS_REGISTRY.json and refuses; this is the lane with no walk.
    monkeypatch.setenv("AIPASS_CALLER_BRANCH", "devpulse")

    with patch(
        "aipass.ai_mail.apps.handlers.users.verified_caller.verify_admin_caller",
        return_value=(True, "admin grant verified"),
    ):
        success, error = deliver_email_to_branch("@target", _make_email_data(sender="@devpulse", recipient="@target"))

    assert success is False
    assert error.startswith("AIPass registry unreadable, @target not resolved: AIPASS_REGISTRY.json ")
    assert not (lab_target / ".ai_mail.local").exists(), "the namesake must not be served"


# ---- The feed event names the delivered message (DPLAN-0414 C-A) ----


@pytest.fixture
def baud_project(tmp_path, monkeypatch):
    """A project of its own whose registry is BAUD's (the feed itself is in tmp_path: conftest)."""
    root = tmp_path / "baud"
    root.mkdir()
    (root / "BAUD_REGISTRY.json").write_text(json.dumps({"branches": []}), encoding="utf-8")
    monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
    return root


def _feed_events() -> list:
    return [json.loads(line) for line in notify_mod.FEED_PATH.read_text(encoding="utf-8").splitlines()]


def test_a_delivered_mails_event_names_the_written_message_its_recipient_and_project(baud_project, noop_inbox_lock):
    branches = _setup_branch(baud_project)

    with patch.object(delivery_mod, "get_all_branches", return_value=branches):
        success, error = deliver_email_to_branch("@target", _make_email_data())

    assert success is True, error
    written = json.loads((Path(branches[0]["path"]) / ".ai_mail.local" / "inbox.json").read_text(encoding="utf-8"))
    [event] = _feed_events()
    assert event["kind"] == "mail"
    assert event["body"] == "Test subject\nTest body"
    assert (event["mail_id"], event["recipient"], event["project"]) == (written["messages"][0]["id"], "target", "baud")


def test_a_mail_delivered_onto_an_inbox_file_names_it_the_same_way(baud_project, noop_inbox_lock):
    inbox_file = baud_project / "target" / ".ai_mail.local" / "inbox.json"
    inbox_file.parent.mkdir(parents=True)
    inbox_file.write_text(json.dumps(_empty_inbox()), encoding="utf-8")

    success, err, reply_id = delivery_mod.deliver_to_inbox_file(inbox_file, {**_DELIVERED, "to": "@target"})

    assert success is True, err
    [event] = _feed_events()
    assert (event["mail_id"], event["recipient"], event["project"]) == (reply_id, "target", "baud")
    assert json.loads(inbox_file.read_text(encoding="utf-8"))["messages"][0]["id"] == reply_id
