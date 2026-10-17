# =================== AIPass ====================
# Name: test_reply.py
# Description: Tests for email reply handler
# Version: 1.0.2
# Created: 2026-04-25
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/email/reply.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(windows_compat) — the sys.platform == "win32" stdout/stderr reconfigure block

import json
import pytest
from unittest.mock import patch


from aipass.ai_mail.apps.handlers.email.reply import (
    get_email_by_id,
    send_reply,
)


@pytest.fixture(autouse=True)
def _silence_json_handler():
    """Prevent log_operation from writing real JSON files during tests."""
    with patch("aipass.ai_mail.apps.handlers.email.reply.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


def test_get_email_by_id_found(tmp_path):
    """Returns matching message dict when ID exists in inbox."""
    inbox_file = tmp_path / "inbox.json"
    inbox_data = {
        "messages": [
            {"id": "abc123", "subject": "First", "status": "new"},
            {"id": "def456", "subject": "Second", "status": "opened"},
        ]
    }
    inbox_file.write_text(json.dumps(inbox_data), encoding="utf-8")

    result = get_email_by_id(inbox_file, "def456")

    assert result is not None
    assert result["id"] == "def456"
    assert result["subject"] == "Second"
    assert result["status"] == "opened"


def test_get_email_by_id_not_found(tmp_path):
    """Returns None when no message matches the ID."""
    inbox_file = tmp_path / "inbox.json"
    inbox_data = {
        "messages": [
            {"id": "abc123", "subject": "Only one"},
        ]
    }
    inbox_file.write_text(json.dumps(inbox_data), encoding="utf-8")

    result = get_email_by_id(inbox_file, "nonexistent")

    assert result is None


def test_get_email_by_id_missing_file(tmp_path):
    """Returns None when inbox file does not exist."""
    inbox_file = tmp_path / "does_not_exist.json"

    result = get_email_by_id(inbox_file, "abc123")

    assert result is None


def test_get_email_by_id_corrupt_json(tmp_path):
    """An inbox that cannot be parsed raises; it is not "message not found".

    handle_reply turns the raise into its error line instead of "Message not found".
    """
    inbox_file = tmp_path / "inbox.json"
    inbox_file.write_text("{broken json!!!", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        get_email_by_id(inbox_file, "abc123")


def test_get_email_by_id_empty_messages(tmp_path):
    """Returns None when messages list is empty."""
    inbox_file = tmp_path / "inbox.json"
    inbox_data = {"messages": []}
    inbox_file.write_text(json.dumps(inbox_data), encoding="utf-8")

    result = get_email_by_id(inbox_file, "abc123")

    assert result is None


def test_get_email_by_id_no_messages_key(tmp_path):
    """Returns None when inbox JSON has no messages key."""
    inbox_file = tmp_path / "inbox.json"
    inbox_data = {"mailbox": "inbox"}
    inbox_file.write_text(json.dumps(inbox_data), encoding="utf-8")

    result = get_email_by_id(inbox_file, "abc123")

    assert result is None


def _make_original_email(
    *,
    msg_id: str = "orig-001",
    sender: str = "@devpulse",
    subject: str = "Original subject",
    reply_to: str | None = None,
    dispatched_to: str | None = None,
) -> dict:
    """Build a minimal original email dict for send_reply tests."""
    email = {
        "id": msg_id,
        "from": sender,
        "subject": subject,
        "status": "opened",
    }
    if reply_to is not None:
        email["reply_to"] = reply_to
    if dispatched_to is not None:
        email["dispatched_to"] = dispatched_to
    return email


# Patch paths for lazy imports inside send_reply function body
_PATCH_BRANCH_DETECTION = "aipass.ai_mail.apps.handlers.users.branch_detection.get_branch_info_from_registry"
_PATCH_DELIVERY = "aipass.ai_mail.apps.handlers.email.delivery.deliver_email_to_branch"
_PATCH_ALL_BRANCHES = "aipass.ai_mail.apps.handlers.registry.read.get_all_branches"
_PATCH_CLOSE_ARCHIVE = "aipass.ai_mail.apps.handlers.email.inbox_cleanup.mark_as_closed_and_archive"


def test_send_reply_happy_path(tmp_path):
    """Successful reply returns (True, message, reply_id)."""
    from_branch_path = tmp_path / "trigger"
    from_branch_path.mkdir()

    sender_info = {"email": "@trigger", "name": "TRIGGER"}
    target_branch = {"email": "@devpulse", "name": "DEVPULSE", "path": str(tmp_path / "devpulse")}
    original = _make_original_email()

    with (
        patch(_PATCH_BRANCH_DETECTION, return_value=sender_info),
        patch(_PATCH_DELIVERY, return_value=(True, "")),
        patch(_PATCH_ALL_BRANCHES, return_value=[target_branch]),
        patch(_PATCH_CLOSE_ARCHIVE, return_value=(True, "closed")),
    ):
        success, message, reply_id = send_reply(from_branch_path, original, "Thanks!")

    assert success is True
    assert reply_id is not None
    assert "Reply sent" in message

    sent_folder = from_branch_path / ".ai_mail.local" / "sent"
    assert sent_folder.exists()
    sent_files = list(sent_folder.glob("*.json"))
    assert len(sent_files) == 1

    with open(sent_files[0], "r", encoding="utf-8") as f:
        sent_data = json.load(f)
    assert sent_data["from"] == "@trigger"
    assert sent_data["to"] == "@devpulse"
    assert sent_data["subject"].startswith("RE:")
    assert sent_data["message"] == "Thanks!"
    assert sent_data["in_reply_to"] == "orig-001"


def test_send_reply_no_sender_info(tmp_path):
    """Returns failure when sender branch cannot be detected."""
    from_branch_path = tmp_path / "unknown"
    from_branch_path.mkdir()
    original = _make_original_email()

    with patch(_PATCH_BRANCH_DETECTION, return_value=None):
        success, message, reply_id = send_reply(from_branch_path, original, "Reply text")

    assert success is False
    assert "Could not detect" in message
    assert reply_id is None


def test_send_reply_unknown_recipient(tmp_path):
    """Returns failure when recipient branch is not found in registry."""
    from_branch_path = tmp_path / "trigger"
    from_branch_path.mkdir()
    sender_info = {"email": "@trigger", "name": "TRIGGER"}
    original = _make_original_email(sender="@unknown_branch")

    with (
        patch(_PATCH_BRANCH_DETECTION, return_value=sender_info),
        patch(_PATCH_ALL_BRANCHES, return_value=[]),
    ):
        success, message, reply_id = send_reply(from_branch_path, original, "Reply text")

    assert success is False
    assert "Could not find branch" in message
    assert reply_id is None


def test_send_reply_identity_mismatch_raises(tmp_path):
    """Raises RuntimeError when dispatched_to does not match current sender."""
    from_branch_path = tmp_path / "wrong_branch"
    from_branch_path.mkdir()
    sender_info = {"email": "@wrong_branch", "name": "WRONG"}
    original = _make_original_email(dispatched_to="@correct_branch")

    with (
        patch(_PATCH_BRANCH_DETECTION, return_value=sender_info),
        pytest.raises(RuntimeError, match="IDENTITY MISMATCH"),
    ):
        send_reply(from_branch_path, original, "Reply text")


def test_send_reply_uses_reply_to_field(tmp_path):
    """Reply goes to reply_to address when present, not the from address."""
    from_branch_path = tmp_path / "trigger"
    from_branch_path.mkdir()
    sender_info = {"email": "@trigger", "name": "TRIGGER"}
    target_branch = {"email": "@flow", "name": "FLOW", "path": str(tmp_path / "flow")}
    original = _make_original_email(sender="@devpulse", reply_to="@flow")

    deliver_calls = []

    def mock_deliver(to_branch, email_data):
        """Capture delivery arguments."""
        deliver_calls.append((to_branch, email_data))
        return (True, "")

    with (
        patch(_PATCH_BRANCH_DETECTION, return_value=sender_info),
        patch(_PATCH_DELIVERY, side_effect=mock_deliver),
        patch(_PATCH_ALL_BRANCHES, return_value=[target_branch]),
        patch(_PATCH_CLOSE_ARCHIVE, return_value=(True, "closed")),
    ):
        success, message, reply_id = send_reply(from_branch_path, original, "Thanks!")

    assert success is True
    assert len(deliver_calls) == 1
    assert deliver_calls[0][0] == "@flow"


def test_send_reply_re_prefix_not_duplicated(tmp_path):
    """Subject already starting with RE: does not get double-prefixed."""
    from_branch_path = tmp_path / "trigger"
    from_branch_path.mkdir()
    sender_info = {"email": "@trigger", "name": "TRIGGER"}
    target_branch = {"email": "@devpulse", "name": "DEVPULSE", "path": str(tmp_path / "devpulse")}
    original = _make_original_email(subject="RE: Already replied")

    deliver_calls = []

    def mock_deliver(to_branch, email_data):
        """Capture delivery arguments."""
        deliver_calls.append((to_branch, email_data))
        return (True, "")

    with (
        patch(_PATCH_BRANCH_DETECTION, return_value=sender_info),
        patch(_PATCH_DELIVERY, side_effect=mock_deliver),
        patch(_PATCH_ALL_BRANCHES, return_value=[target_branch]),
        patch(_PATCH_CLOSE_ARCHIVE, return_value=(True, "closed")),
    ):
        success, _message, _reply_id = send_reply(from_branch_path, original, "Thanks!")

    assert success is True
    # Should keep "RE: Already replied", not "RE: RE: Already replied"
    assert deliver_calls[0][1]["subject"] == "RE: Already replied"


def test_send_reply_multiline_body_preserved(tmp_path):
    """Multi-line reply body is stored intact, not truncated to first line."""
    from_branch_path = tmp_path / "hooks"
    from_branch_path.mkdir()
    sender_info = {"email": "@hooks", "name": "HOOKS"}
    target_branch = {"email": "@devpulse", "name": "DEVPULSE", "path": str(tmp_path / "devpulse")}
    original = _make_original_email()

    deliver_calls = []

    def mock_deliver(to_branch, email_data):
        deliver_calls.append((to_branch, email_data))
        return (True, "")

    multiline_body = (
        "Investigation: cadence findings\n\nDetails:\n1. First finding\n2. Second finding\n3. Third finding"
    )

    with (
        patch(_PATCH_BRANCH_DETECTION, return_value=sender_info),
        patch(_PATCH_DELIVERY, side_effect=mock_deliver),
        patch(_PATCH_ALL_BRANCHES, return_value=[target_branch]),
        patch(_PATCH_CLOSE_ARCHIVE, return_value=(True, "closed")),
    ):
        success, _message, _reply_id = send_reply(from_branch_path, original, multiline_body)

    assert success is True
    assert deliver_calls[0][1]["message"] == multiline_body

    sent_folder = from_branch_path / ".ai_mail.local" / "sent"
    sent_files = list(sent_folder.glob("*.json"))
    assert len(sent_files) == 1
    with open(sent_files[0], "r", encoding="utf-8") as f:
        sent_data = json.load(f)
    assert sent_data["message"] == multiline_body


# Cross-project replies: outgoing replies must carry reply_path (GAP 1), and the validator must
# accept any *_REGISTRY.json (GAP 2). Fixtures use MYPROJ_REGISTRY.json so they cannot share a hardcoded name.

_PATCH_NOTIFY = "aipass.ai_mail.apps.handlers.email.delivery._emit_notification_event"


def _make_external_project(root, project="myproj", branch="vera"):
    """Build an external project tree: MYPROJ_REGISTRY.json + branch/.ai_mail.local/inbox.json."""
    ext_root = root / f"{project}_root"
    (ext_root).mkdir(parents=True, exist_ok=True)
    (ext_root / f"{project.upper()}_REGISTRY.json").write_text('{"branches": []}', encoding="utf-8")
    inbox_dir = ext_root / branch / ".ai_mail.local"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    inbox_file = inbox_dir / "inbox.json"
    inbox_file.write_text(json.dumps({"messages": [], "total_messages": 0, "unread_count": 0}), encoding="utf-8")
    return ext_root / branch, inbox_file


def _reply_to_external(tmp_path, reply_path):
    """send_reply from a tmp branch to an external @vera whose message carried `reply_path`."""
    branch_a = tmp_path / "branch_a"
    branch_a.mkdir(exist_ok=True)
    original = _make_original_email(sender="@vera")
    original["reply_path"] = str(reply_path)
    with (
        patch(_PATCH_BRANCH_DETECTION, return_value={"email": "@branch_a", "name": "BRANCH_A"}),
        patch(_PATCH_ALL_BRANCHES, return_value=[]),  # @vera is external -- registry miss is correct
        patch(_PATCH_CLOSE_ARCHIVE, return_value=(True, "closed")),
        patch(_PATCH_NOTIFY),
    ):
        success, msg, _rid = send_reply(branch_a, original, "Reply outbound")
    return success, msg


def test_validate_reply_path_accepts_external_registry(tmp_path):
    """An ancestor holding only MYPROJ_REGISTRY.json must be accepted: the reply lands."""
    _branch, inbox_file = _make_external_project(tmp_path)

    success, msg = _reply_to_external(tmp_path, inbox_file)

    assert success is True, msg
    delivered = json.loads(inbox_file.read_text(encoding="utf-8"))["messages"]
    assert [m["message"] for m in delivered] == ["Reply outbound"]


def test_validate_reply_path_still_rejects_wrong_shape(tmp_path):
    """The .ai_mail.local/inbox.json shape requirement is unchanged."""
    _branch, inbox_file = _make_external_project(tmp_path)
    impostor = inbox_file.parent / "notes.json"
    impostor.write_text("{}", encoding="utf-8")

    success, msg = _reply_to_external(tmp_path, impostor)

    assert success is False
    assert msg.startswith("Invalid reply_path: Path does not end with .ai_mail.local/inbox.json")
    assert impostor.read_text(encoding="utf-8") == "{}"


def test_validate_reply_path_rejects_tree_with_no_registry(tmp_path):
    """A path with no *_REGISTRY.json anywhere above it is still refused."""
    stray = tmp_path / "nowhere" / ".ai_mail.local"
    stray.mkdir(parents=True)
    (stray / "inbox.json").write_text("{}", encoding="utf-8")

    success, msg = _reply_to_external(tmp_path, stray / "inbox.json")

    assert success is False
    assert msg.startswith("Invalid reply_path: No *_REGISTRY.json found in ancestors of")
    assert (stray / "inbox.json").read_text(encoding="utf-8") == "{}"


def test_reply_carries_reply_path_to_own_inbox(tmp_path):
    """A reply built by send_reply points reply_path at the replying branch's inbox."""
    from_branch_path = tmp_path / "branch_a"
    from_branch_path.mkdir()
    captured = {}

    sender_info = {"email": "@branch_a", "name": "BRANCH_A"}
    target_branch = {"email": "@devpulse", "name": "DEVPULSE", "path": str(tmp_path / "devpulse")}

    def _capture(dest, payload, **kwargs):
        captured.update(payload)
        return True, ""

    with (
        patch(_PATCH_BRANCH_DETECTION, return_value=sender_info),
        patch(_PATCH_DELIVERY, side_effect=_capture),
        patch(_PATCH_ALL_BRANCHES, return_value=[target_branch]),
        patch(_PATCH_CLOSE_ARCHIVE, return_value=(True, "closed")),
    ):
        success, _msg, _rid = send_reply(from_branch_path, _make_original_email(), "Thanks!")

    assert success is True
    assert captured["reply_path"] == str(from_branch_path / ".ai_mail.local" / "inbox.json")


def test_cross_project_reply_round_trip(tmp_path):
    """A replies to an external citizen; the delivered reply carries a working return address.

    Proves the whole verb: delivery out (GAP 2), reply_path stamped (GAP 1), and a reply back via that path.
    """
    ext_branch, ext_inbox = _make_external_project(tmp_path)

    branch_a = tmp_path / "aipass_root" / "branch_a"
    a_inbox_dir = branch_a / ".ai_mail.local"
    a_inbox_dir.mkdir(parents=True)
    a_inbox = a_inbox_dir / "inbox.json"
    a_inbox.write_text(json.dumps({"messages": [], "total_messages": 0, "unread_count": 0}), encoding="utf-8")
    (tmp_path / "aipass_root" / "AIPASS_REGISTRY.json").write_text('{"branches": []}', encoding="utf-8")

    # Leg 1: A replies to a message from an external citizen that carried a reply_path.
    original = _make_original_email(sender="@vera")
    original["reply_path"] = str(ext_inbox)

    with (
        patch(_PATCH_BRANCH_DETECTION, return_value={"email": "@branch_a", "name": "BRANCH_A"}),
        patch(_PATCH_ALL_BRANCHES, return_value=[]),  # @vera is external -- registry miss is correct
        patch(_PATCH_CLOSE_ARCHIVE, return_value=(True, "closed")),
        patch(_PATCH_NOTIFY),
    ):
        success, msg, _rid = send_reply(branch_a, original, "Reply outbound")

    assert success is True, msg

    delivered = json.loads(ext_inbox.read_text(encoding="utf-8"))["messages"][0]
    assert delivered["from"] == "@branch_a"
    assert delivered["message"] == "Reply outbound"
    assert delivered["reply_path"] == str(a_inbox)

    # Leg 2: the external citizen replies to THAT message, resolving only via reply_path.
    with (
        patch(_PATCH_BRANCH_DETECTION, return_value={"email": "@vera", "name": "VERA"}),
        patch(_PATCH_ALL_BRANCHES, return_value=[]),  # @branch_a not resolvable from their side
        patch(_PATCH_CLOSE_ARCHIVE, return_value=(True, "closed")),
        patch(_PATCH_NOTIFY),
    ):
        success2, msg2, _rid2 = send_reply(ext_branch, delivered, "Reply back inbound")

    assert success2 is True, msg2

    landed = json.loads(a_inbox.read_text(encoding="utf-8"))["messages"][0]
    assert landed["from"] == "@vera"
    assert landed["message"] == "Reply back inbound"
    assert landed["reply_path"] == str(ext_inbox)
