# =================== AIPass ====================
# Name: test_upsert.py
# Description: Tests for upsert_key delivery (repeat-signal collapsing)
# Version: 1.0.0
# Created: 2026-08-10
# Modified: 2026-08-10
# =============================================

"""Tests for upsert_key delivery.

A repeating signal must occupy ONE inbox slot with a climbing counter, never
a stack of identical messages. The rules under test:

- match (same sender + same key + not closed) rewrites in place
- no match creates a normal new message at updates: 1
- a closed predecessor does NOT match — closing re-arms the signature
- an in-place update never wakes and never flips read status back to new
- upsert_key=None is byte-for-byte today's behavior
"""

import json
import pytest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import aipass.ai_mail.apps.handlers.email.delivery as delivery_mod
import aipass.ai_mail.apps.handlers.email.format as format_mod
from aipass.ai_mail.apps.handlers.email.delivery import (
    _apply_upsert_update,
    _coerce_updates,
    _find_upsert_target,
    deliver_email_to_branch,
)
from aipass.ai_mail.apps.handlers.email.send import send_to_single
from aipass.ai_mail.apps.handlers.email.send_args import parse_send_args


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
    with patch.object(delivery_mod, "_send_desktop_notification") as mock_notify:
        yield mock_notify


@pytest.fixture
def _silence_format_log(monkeypatch):
    """Keep format.py's log_operation off the real JSON files."""
    from unittest.mock import MagicMock

    monkeypatch.setattr(format_mod, "json_handler", MagicMock())
    monkeypatch.setattr(format_mod, "lookup_branch_alias", lambda _name: None)


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


def _setup_branch(tmp_path, name: str = "TARGET", email: str = "@target"):
    """Create branch directory with .ai_mail.local/inbox.json and return branch data."""
    branch_path = tmp_path / "branches" / name.lower()
    mailbox_dir = branch_path / ".ai_mail.local"
    mailbox_dir.mkdir(parents=True, exist_ok=True)
    inbox_file = mailbox_dir / "inbox.json"
    inbox_data = {"mailbox": "inbox", "total_messages": 0, "unread_count": 0, "messages": []}
    inbox_file.write_text(json.dumps(inbox_data, indent=2), encoding="utf-8")
    return [{"name": name, "path": str(branch_path), "email": email}]


def _make_email_data(
    *,
    sender: str = "@trigger",
    sender_name: str = "TRIGGER",
    recipient: str = "@target",
    subject: str = "WARNING: disk 91%",
    message: str = "disk at 91%",
    timestamp: str = "2026-08-10T12:00:00Z",
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


def _read_inbox(branches) -> dict:
    """Load the inbox JSON written by delivery."""
    inbox_file = Path(branches[0]["path"]) / ".ai_mail.local" / "inbox.json"
    with open(inbox_file, "r", encoding="utf-8") as f:
        return json.load(f)


def _deliver(branches, email_data, **kwargs):
    """Deliver to @target with get_all_branches patched."""
    with patch.object(delivery_mod, "get_all_branches", return_value=branches):
        return deliver_email_to_branch("@target", email_data, **kwargs)


# ---- _coerce_updates() ---------------------------------------


def test_coerce_updates_reads_int():
    """A normal stored counter reads back unchanged."""
    assert _coerce_updates(4) == 4


def test_coerce_updates_floors_at_one():
    """Zero or negative counters floor to 1 — a message exists, so it fired at least once."""
    assert _coerce_updates(0) == 1
    assert _coerce_updates(-3) == 1


def test_coerce_updates_survives_garbage():
    """A hand-edited or missing counter must not crash a delivery."""
    assert _coerce_updates(None) == 1
    assert _coerce_updates("lots") == 1
    assert _coerce_updates({}) == 1


def test_coerce_updates_accepts_numeric_string():
    """A counter that round-tripped through a string still counts."""
    assert _coerce_updates("7") == 7


# ---- _find_upsert_target() -----------------------------------


def test_find_upsert_target_matches_sender_and_key():
    """Match requires same key AND same sender AND not closed."""
    messages = [{"id": "aa", "from": "@trigger", "upsert_key": "disk", "status": "new"}]
    match = _find_upsert_target(messages, "@trigger", "disk")
    assert match is not None
    assert match["id"] == "aa"


def test_find_upsert_target_ignores_other_sender():
    """Same key from a different sender is a different signal."""
    messages = [{"id": "aa", "from": "@other", "upsert_key": "disk", "status": "new"}]
    assert _find_upsert_target(messages, "@trigger", "disk") is None


def test_find_upsert_target_ignores_other_key():
    """Different signature, different message."""
    messages = [{"id": "aa", "from": "@trigger", "upsert_key": "cpu", "status": "new"}]
    assert _find_upsert_target(messages, "@trigger", "disk") is None


def test_find_upsert_target_ignores_closed():
    """A closed message is spent — it must not absorb the next send."""
    messages = [{"id": "aa", "from": "@trigger", "upsert_key": "disk", "status": "closed"}]
    assert _find_upsert_target(messages, "@trigger", "disk") is None


def test_find_upsert_target_ignores_keyless_messages():
    """Ordinary mail carries no key and can never be matched into."""
    messages = [{"id": "aa", "from": "@trigger", "status": "new"}]
    assert _find_upsert_target(messages, "@trigger", "disk") is None


def test_find_upsert_target_returns_newest_open_match():
    """Messages are newest-first, so the first hit is the most recent one."""
    messages = [
        {"id": "new", "from": "@trigger", "upsert_key": "disk", "status": "opened"},
        {"id": "old", "from": "@trigger", "upsert_key": "disk", "status": "new"},
    ]
    match = _find_upsert_target(messages, "@trigger", "disk")
    assert match is not None
    assert match["id"] == "new"


# ---- _apply_upsert_update() ----------------------------------


def test_apply_upsert_update_preserves_identity_and_status():
    """The rewrite keeps id, original timestamp and read status."""
    existing = {
        "id": "abc12345",
        "timestamp": "2026-08-10T10:00:00Z",
        "subject": "old",
        "message": "old body",
        "status": "opened",
        "updates": 1,
    }
    _apply_upsert_update(existing, _make_email_data(subject="new", message="new body"))

    assert existing["id"] == "abc12345"
    assert existing["status"] == "opened"
    assert existing["timestamp"] == "2026-08-10T10:00:00Z"
    assert existing["subject"] == "new"
    assert existing["message"] == "new body"
    assert existing["last_updated"] == "2026-08-10T12:00:00Z"
    assert existing["updates"] == 2


# ---- match: updates in place ---------------------------------


def test_upsert_match_updates_in_place(tmp_path, repo_root, noop_inbox_lock):
    """Second send with the same key rewrites the first message, not a second one."""
    branches = _setup_branch(tmp_path)

    _deliver(branches, _make_email_data(), upsert_key="warn:disk")
    first_id = _read_inbox(branches)["messages"][0]["id"]

    _deliver(
        branches,
        _make_email_data(subject="WARNING: disk 97%", message="disk at 97%", timestamp="2026-08-10T12:05:00Z"),
        upsert_key="warn:disk",
    )

    inbox = _read_inbox(branches)
    assert len(inbox["messages"]) == 1
    msg = inbox["messages"][0]
    assert msg["id"] == first_id
    assert msg["subject"] == "WARNING: disk 97%"
    assert msg["message"] == "disk at 97%"
    assert msg["updates"] == 2
    assert msg["last_updated"] == "2026-08-10T12:05:00Z"
    assert msg["timestamp"] == "2026-08-10T12:00:00Z"


def test_upsert_counter_climbs_across_many_sends(tmp_path, repo_root, noop_inbox_lock):
    """Five repeats = one message reading x5."""
    branches = _setup_branch(tmp_path)

    for _ in range(5):
        _deliver(branches, _make_email_data(), upsert_key="warn:disk")

    inbox = _read_inbox(branches)
    assert len(inbox["messages"]) == 1
    assert inbox["messages"][0]["updates"] == 5
    assert inbox["total_messages"] == 1


def test_upsert_update_preserves_opened_status(tmp_path, repo_root, noop_inbox_lock):
    """An update must never flip a read message back to new — the whole point."""
    branches = _setup_branch(tmp_path)
    _deliver(branches, _make_email_data(), upsert_key="warn:disk")

    inbox_file = Path(branches[0]["path"]) / ".ai_mail.local" / "inbox.json"
    inbox = json.loads(inbox_file.read_text(encoding="utf-8"))
    inbox["messages"][0]["status"] = "opened"
    inbox["unread_count"] = 0
    inbox_file.write_text(json.dumps(inbox), encoding="utf-8")

    _deliver(branches, _make_email_data(subject="WARNING: disk 99%"), upsert_key="warn:disk")

    inbox = _read_inbox(branches)
    assert inbox["messages"][0]["status"] == "opened"
    assert inbox["unread_count"] == 0
    assert inbox["messages"][0]["subject"] == "WARNING: disk 99%"


def test_upsert_update_keeps_new_status_new(tmp_path, repo_root, noop_inbox_lock):
    """An unread repeat stays unread — and stays counted once."""
    branches = _setup_branch(tmp_path)
    _deliver(branches, _make_email_data(), upsert_key="warn:disk")
    _deliver(branches, _make_email_data(), upsert_key="warn:disk")

    inbox = _read_inbox(branches)
    assert inbox["messages"][0]["status"] == "new"
    assert inbox["unread_count"] == 1


def test_upsert_reports_action_through_email_data(tmp_path, repo_root, noop_inbox_lock):
    """Callers learn created-vs-updated without re-reading the inbox."""
    branches = _setup_branch(tmp_path)

    first = _make_email_data()
    _deliver(branches, first, upsert_key="warn:disk")
    assert first["upsert_action"] == "created"

    second = _make_email_data()
    _deliver(branches, second, upsert_key="warn:disk")
    assert second["upsert_action"] == "updated"


def test_upsert_key_accepted_via_email_data(tmp_path, repo_root, noop_inbox_lock):
    """email_data['upsert_key'] works too — trigger builds its own payload dict."""
    branches = _setup_branch(tmp_path)

    _deliver(branches, _make_email_data(upsert_key="warn:disk"))
    _deliver(branches, _make_email_data(upsert_key="warn:disk"))

    inbox = _read_inbox(branches)
    assert len(inbox["messages"]) == 1
    assert inbox["messages"][0]["updates"] == 2


def test_upsert_update_suppresses_desktop_notification(tmp_path, repo_root, noop_inbox_lock, _silence_notifications):
    """The first send pops a toast; repeats do not re-demand attention."""
    branches = _setup_branch(tmp_path)

    _deliver(branches, _make_email_data(), upsert_key="warn:disk")
    assert _silence_notifications.call_count == 1

    _deliver(branches, _make_email_data(), upsert_key="warn:disk")
    assert _silence_notifications.call_count == 1


# ---- no match: creates new -----------------------------------


def test_upsert_first_send_creates_new_message(tmp_path, repo_root, noop_inbox_lock):
    """First send is an ordinary new message carrying the key at updates: 1."""
    branches = _setup_branch(tmp_path)

    success, err = _deliver(branches, _make_email_data(), upsert_key="warn:disk")

    assert success is True
    assert err == ""
    inbox = _read_inbox(branches)
    assert len(inbox["messages"]) == 1
    msg = inbox["messages"][0]
    assert msg["upsert_key"] == "warn:disk"
    assert msg["updates"] == 1
    assert msg["status"] == "new"
    assert inbox["unread_count"] == 1


def test_upsert_different_key_creates_second_message(tmp_path, repo_root, noop_inbox_lock):
    """Two distinct signals keep two distinct messages."""
    branches = _setup_branch(tmp_path)

    _deliver(branches, _make_email_data(), upsert_key="warn:disk")
    _deliver(branches, _make_email_data(subject="WARNING: cpu"), upsert_key="warn:cpu")

    inbox = _read_inbox(branches)
    assert len(inbox["messages"]) == 2
    assert {m["upsert_key"] for m in inbox["messages"]} == {"warn:disk", "warn:cpu"}


def test_upsert_different_sender_creates_second_message(tmp_path, repo_root, noop_inbox_lock):
    """Same key from another sender is another signal, not the same one."""
    branches = _setup_branch(tmp_path)

    _deliver(branches, _make_email_data(sender="@trigger"), upsert_key="warn:disk")
    _deliver(branches, _make_email_data(sender="@devpulse"), upsert_key="warn:disk")

    inbox = _read_inbox(branches)
    assert len(inbox["messages"]) == 2


def test_upsert_after_close_creates_new_message(tmp_path, repo_root, noop_inbox_lock):
    """Closing re-arms the signature: the next send is a fresh message at 1."""
    branches = _setup_branch(tmp_path)
    _deliver(branches, _make_email_data(), upsert_key="warn:disk")

    inbox_file = Path(branches[0]["path"]) / ".ai_mail.local" / "inbox.json"
    inbox = json.loads(inbox_file.read_text(encoding="utf-8"))
    inbox["messages"][0]["status"] = "closed"
    closed_id = inbox["messages"][0]["id"]
    inbox_file.write_text(json.dumps(inbox), encoding="utf-8")

    fresh = _make_email_data(timestamp="2026-08-10T13:00:00Z")
    _deliver(branches, fresh, upsert_key="warn:disk")

    inbox = _read_inbox(branches)
    open_msgs = [m for m in inbox["messages"] if m.get("status") != "closed"]
    assert len(open_msgs) == 1
    assert open_msgs[0]["id"] != closed_id
    assert open_msgs[0]["updates"] == 1
    assert fresh["upsert_action"] == "created"


# ---- updates never wake --------------------------------------


def test_upsert_update_forces_auto_execute_off(tmp_path, repo_root, noop_inbox_lock):
    """An in-place update never wakes, whatever the sender asked for."""
    branches = _setup_branch(tmp_path)
    _deliver(branches, _make_email_data(), upsert_key="warn:disk")

    _deliver(branches, _make_email_data(auto_execute=True), upsert_key="warn:disk")

    inbox = _read_inbox(branches)
    assert len(inbox["messages"]) == 1
    assert inbox["messages"][0]["auto_execute"] is False


def test_upsert_update_disarms_a_previously_dispatchable_message(tmp_path, repo_root, noop_inbox_lock):
    """Even if the first send was a dispatch, the repeat leaves nothing armed."""
    branches = _setup_branch(tmp_path)
    _deliver(branches, _make_email_data(auto_execute=True), upsert_key="warn:disk")
    assert _read_inbox(branches)["messages"][0]["auto_execute"] is True

    _deliver(branches, _make_email_data(), upsert_key="warn:disk")

    assert _read_inbox(branches)["messages"][0]["auto_execute"] is False


# ---- default None: untouched behavior ------------------------


def test_no_upsert_key_stacks_as_before(tmp_path, repo_root, noop_inbox_lock):
    """Default None: three identical sends are still three messages."""
    branches = _setup_branch(tmp_path)

    for _ in range(3):
        _deliver(branches, _make_email_data())

    inbox = _read_inbox(branches)
    assert len(inbox["messages"]) == 3
    assert inbox["total_messages"] == 3
    assert inbox["unread_count"] == 3


def test_no_upsert_key_leaves_message_shape_clean(tmp_path, repo_root, noop_inbox_lock):
    """Ordinary mail gains no upsert fields at all."""
    branches = _setup_branch(tmp_path)

    data = _make_email_data()
    _deliver(branches, data)

    msg = _read_inbox(branches)["messages"][0]
    assert "upsert_key" not in msg
    assert "updates" not in msg
    assert "last_updated" not in msg
    assert "upsert_action" not in data


def test_no_upsert_key_still_honors_auto_execute(tmp_path, repo_root, noop_inbox_lock):
    """Dispatch delivery is unchanged when no key is in play."""
    branches = _setup_branch(tmp_path)

    _deliver(branches, _make_email_data(auto_execute=True))

    assert _read_inbox(branches)["messages"][0]["auto_execute"] is True


def test_empty_upsert_key_is_treated_as_no_key(tmp_path, repo_root, noop_inbox_lock):
    """An empty string is not a signature — it must not collapse unrelated mail."""
    branches = _setup_branch(tmp_path)

    _deliver(branches, _make_email_data(), upsert_key="")
    _deliver(branches, _make_email_data(), upsert_key="")

    inbox = _read_inbox(branches)
    assert len(inbox["messages"]) == 2
    assert "upsert_key" not in inbox["messages"][0]


# ---- the counter has to be visible ---------------------------


def test_format_update_count_ignores_ordinary_mail():
    """No counter on plain mail, and none on a first send — nothing to show."""
    assert format_mod.format_update_count({}) == 0
    assert format_mod.format_update_count({"updates": 1}) == 0


def test_format_update_count_reports_repeats():
    """From the second fire onward the number is the news."""
    assert format_mod.format_update_count({"updates": 2}) == 2
    assert format_mod.format_update_count({"updates": 31}) == 31


def test_format_update_count_survives_garbage():
    """A corrupt counter renders as absent, never as a crash on the read path."""
    assert format_mod.format_update_count({"updates": "many"}) == 0
    assert format_mod.format_update_count({"updates": None}) == 0


def test_inbox_row_shows_repeat_marker(_silence_format_log):
    """Patrick sees the ping number at a glance in the listing."""
    row = format_mod.format_email_list_item(
        1,
        {
            "id": "abc12345",
            "from": "@trigger",
            "from_name": "TRIGGER",
            "subject": "WARN",
            "status": "new",
            "timestamp": "2026-08-10",
            "message": "body",
            "updates": 12,
        },
    )
    assert "x12" in row


def test_inbox_row_has_no_marker_without_repeats(_silence_format_log):
    """One-shot mail reads exactly as it did before."""
    row = format_mod.format_email_list_item(
        1,
        {
            "id": "abc12345",
            "from": "@trigger",
            "from_name": "TRIGGER",
            "subject": "WARN",
            "status": "new",
            "timestamp": "2026-08-10",
            "message": "body",
        },
    )
    assert " x" not in row


def test_view_header_shows_counter_and_last_fire(_silence_format_log):
    """The single email states how many times it fired and when it last did."""
    header = format_mod.format_email_header(
        {
            "from": "@trigger",
            "from_name": "TRIGGER",
            "subject": "WARN",
            "timestamp": "2026-08-10T12:00:00Z",
            "updates": 3,
            "last_updated": "2026-08-10T12:30:00Z",
        },
    )
    assert "Updates: 3" in header
    assert "2026-08-10T12:30:00Z" in header


def test_view_header_omits_counter_for_ordinary_mail(_silence_format_log):
    """No upsert, no extra line."""
    header = format_mod.format_email_header(
        {"from": "@devpulse", "from_name": "DEVPULSE", "subject": "hi", "timestamp": "2026-08-10T12:00:00Z"},
    )
    assert "Updates:" not in header


# ---- CLI + send-path wiring ----------------------------------


def test_parse_send_args_extracts_upsert_key():
    """--upsert-key is consumed as a flag, never mistaken for the subject."""
    result = parse_send_args(["@target", "--upsert-key", "warn:disk", "Subject", "Body"])

    assert result["upsert_key"] == "warn:disk"
    assert result["mode"] == "direct"
    assert result["subject"] == "Subject"
    assert result["message"] == "Body"


def test_parse_send_args_upsert_key_without_value_errors():
    """A dangling flag fails loudly instead of sending with no signature."""
    result = parse_send_args(["@target", "Subject", "Body", "--upsert-key"])

    assert result["mode"] == "error"
    assert "--upsert-key requires" in (result["error"] or "")


def test_parse_send_args_defaults_upsert_key_to_none():
    """Every ordinary send parses to upsert_key None."""
    assert parse_send_args(["@target", "Subject", "Body"])["upsert_key"] is None


def test_send_to_single_forwards_upsert_key():
    """The mid-layer hands the key to delivery on email_data."""
    captured = {}

    def _fake_deliver(to_branch, email_data, on_delivered=None):
        captured.update(email_data)
        email_data["upsert_action"] = "updated"
        return True, ""

    ok, err = send_to_single(
        "@target",
        "Subject",
        "Body",
        {"email": "@sender"},
        False,
        False,
        None,
        None,
        lambda *a, **k: "email_file",
        lambda _f: _make_email_data(),
        _fake_deliver,
        None,
        lambda *a, **k: None,
        None,
        upsert_key="warn:disk",
    )

    assert ok is True
    assert err is None
    assert captured["upsert_key"] == "warn:disk"


def test_send_to_single_without_key_sends_nothing_extra():
    """Default None leaves the payload exactly as it is today."""
    captured = {}

    def _fake_deliver(to_branch, email_data, on_delivered=None):
        captured.update(email_data)
        return True, ""

    send_to_single(
        "@target",
        "Subject",
        "Body",
        {"email": "@sender"},
        False,
        False,
        None,
        None,
        lambda *a, **k: "email_file",
        lambda _f: _make_email_data(),
        _fake_deliver,
        None,
        lambda *a, **k: None,
        None,
    )

    assert "upsert_key" not in captured
