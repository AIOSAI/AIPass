# =================== AIPass ====================
# Name: test_inbox_ops.py
# Description: Tests for inbox operations handler
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""Tests for inbox operations handler -- inbox loading and migration."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from aipass.ai_mail.apps.handlers.email.inbox_ops import load_inbox


# ---- Fixtures ------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_json_handler():
    """Prevent log_operation from writing real JSON files during tests."""
    with patch("aipass.ai_mail.apps.handlers.email.inbox_ops.json_handler") as mock_jh:
        mock_jh.log_operation.return_value = True
        yield mock_jh


# ---- Tests ---------------------------------------------------


def test_load_inbox_no_file(tmp_path):
    """Nonexistent inbox file returns empty v2 schema."""
    result = load_inbox(tmp_path / "inbox.json")

    assert isinstance(result, dict)
    assert result == {"messages": []}


def test_load_inbox_valid_v2(tmp_path):
    """Full v2 schema file is returned as-is (no migration needed)."""
    inbox_path = tmp_path / "inbox.json"
    v2_data = {
        "mailbox": "inbox",
        "total_messages": 2,
        "unread_count": 1,
        "messages": [
            {"id": "m1", "status": "new", "subject": "Hello"},
            {"id": "m2", "status": "opened", "subject": "Reply"},
        ],
    }
    inbox_path.write_text(json.dumps(v2_data), encoding="utf-8")

    result = load_inbox(inbox_path)

    assert isinstance(result, dict)
    assert result["mailbox"] == "inbox"
    assert result["total_messages"] == 2
    assert result["unread_count"] == 1
    assert len(result["messages"]) == 2
    assert result["messages"][0]["id"] == "m1"
    assert result["messages"][1]["id"] == "m2"


def test_load_inbox_old_format_migration(tmp_path):
    """Old format {\"inbox\": [...]} migrates to v2 with \"messages\" key."""
    inbox_path = tmp_path / "inbox.json"
    old_data = {
        "inbox": [
            {"id": "msg1", "subject": "First"},
            {"id": "msg2", "subject": "Second"},
        ]
    }
    inbox_path.write_text(json.dumps(old_data), encoding="utf-8")

    result = load_inbox(inbox_path)

    assert isinstance(result, dict)
    assert "inbox" not in result, "Old 'inbox' key should be removed after migration"
    assert len(result["messages"]) == 2
    assert result["messages"][0] == {"id": "msg1", "subject": "First"}
    assert result["messages"][1] == {"id": "msg2", "subject": "Second"}
    # Migration should also add the v2 metadata keys
    assert result["mailbox"] == "inbox"
    assert result["total_messages"] == 2
    assert isinstance(result["unread_count"], int)
    assert result["unread_count"] == 2  # No status key on messages, so both count as unread


def test_load_inbox_missing_messages_key(tmp_path):
    """Dict without 'messages' key gets an empty messages list added."""
    inbox_path = tmp_path / "inbox.json"
    inbox_path.write_text(json.dumps({"mailbox": "inbox"}), encoding="utf-8")

    result = load_inbox(inbox_path)

    assert isinstance(result, dict)
    assert result["messages"] == []
    assert result["mailbox"] == "inbox"
    assert result["total_messages"] == 0
    assert result["unread_count"] == 0


def test_load_inbox_adds_counts(tmp_path):
    """V2-ish data missing total_messages/unread_count gets them added."""
    inbox_path = tmp_path / "inbox.json"
    data = {
        "mailbox": "inbox",
        "messages": [
            {"id": "m1", "status": "new"},
            {"id": "m2", "status": "opened"},
        ],
    }
    inbox_path.write_text(json.dumps(data), encoding="utf-8")

    result = load_inbox(inbox_path)

    assert isinstance(result, dict)
    assert "total_messages" in result
    assert result["total_messages"] == 2
    assert "unread_count" in result
    assert isinstance(result["unread_count"], int)
    assert result["unread_count"] == 1, "Only 'new' messages count as unread"


def test_load_inbox_invalid_json(tmp_path):
    """Non-JSON content raises an Exception mentioning 'Invalid inbox JSON'."""
    inbox_path = tmp_path / "inbox.json"
    inbox_path.write_text("not json", encoding="utf-8")

    with pytest.raises(Exception, match="Invalid inbox JSON"):
        load_inbox(inbox_path)


def test_load_inbox_array_not_dict(tmp_path):
    """Top-level JSON array returns empty v2 schema with messages: []."""
    inbox_path = tmp_path / "inbox.json"
    inbox_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    result = load_inbox(inbox_path)

    assert isinstance(result, dict)
    assert result["messages"] == []
    assert result["total_messages"] == 0
    assert result["unread_count"] == 0
    assert result["mailbox"] == "inbox"


def test_load_inbox_unread_count_calculated(tmp_path):
    """Unread count is calculated from message statuses: 2 new + 1 opened = 2."""
    inbox_path = tmp_path / "inbox.json"
    data = {
        "mailbox": "inbox",
        "messages": [
            {"id": "m1", "status": "new"},
            {"id": "m2", "status": "new"},
            {"id": "m3", "status": "opened"},
        ],
    }
    inbox_path.write_text(json.dumps(data), encoding="utf-8")

    result = load_inbox(inbox_path)

    assert result["unread_count"] == 2
    assert result["total_messages"] == 3


def test_load_inbox_migration_persists(tmp_path):
    """After migrating old format, the file on disk reflects the v2 schema."""
    inbox_path = tmp_path / "inbox.json"
    old_data = {"inbox": [{"id": "msg1", "status": "new"}]}
    inbox_path.write_text(json.dumps(old_data), encoding="utf-8")

    load_inbox(inbox_path)

    # Re-read the file directly to verify persistence
    with open(inbox_path, "r", encoding="utf-8") as f:
        persisted = json.load(f)

    assert isinstance(persisted, dict)
    assert "inbox" not in persisted, "Old key should not remain on disk"
    # Verify all migrated keys have correct values
    assert persisted["messages"] == [{"id": "msg1", "status": "new"}]
    assert persisted["total_messages"] == 1
    assert persisted["unread_count"] == 1
    assert persisted["mailbox"] == "inbox"
    assert set(persisted.keys()) == {"messages", "total_messages", "unread_count", "mailbox"}
