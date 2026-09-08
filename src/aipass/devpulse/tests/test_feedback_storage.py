# META
# module: devpulse.feedback
# description: Tests for feedback storage layer
# END META

"""Tests for feedback storage — load, save, generate_id, directory creation."""

import json
from unittest.mock import patch

import pytest

from aipass.devpulse.apps.handlers.feedback import storage


@pytest.fixture
def mock_feedback_dir(tmp_path):
    """Patch FEEDBACK_DIR to use tmp_path for isolation."""
    feedback_dir = tmp_path / ".feedback.local"
    with patch.object(storage, "FEEDBACK_DIR", feedback_dir):
        yield feedback_dir


class TestGetInboxPath:
    """Tests for get_inbox_path()."""

    def test_returns_inbox_json_under_feedback_dir(self, mock_feedback_dir):
        """Should point to inbox.json inside the feedback directory."""
        result = storage.get_inbox_path()
        assert result == mock_feedback_dir / "inbox.json"


class TestLoadInbox:
    """Tests for load_inbox()."""

    def test_creates_empty_inbox_when_missing(self, mock_feedback_dir):
        """Should create a new inbox.json with empty state if file does not exist."""
        result = storage.load_inbox()

        assert result["mailbox"] == "feedback"
        assert result["total_messages"] == 0
        assert result["unread_count"] == 0
        assert result["messages"] == []

        # File should now exist on disk
        inbox_path = mock_feedback_dir / "inbox.json"
        assert inbox_path.exists()

    def test_creates_directory_if_missing(self, mock_feedback_dir):
        """Should create the .feedback.local/ directory if it does not exist."""
        assert not mock_feedback_dir.exists()
        storage.load_inbox()
        assert mock_feedback_dir.exists()

    def test_loads_existing_inbox(self, mock_feedback_dir):
        """Should load and return existing inbox data."""
        mock_feedback_dir.mkdir(parents=True, exist_ok=True)
        inbox_data = {
            "mailbox": "feedback",
            "total_messages": 1,
            "unread_count": 1,
            "messages": [{"id": "abcd1234", "from": "seedgo", "subject": "test"}],
        }
        inbox_path = mock_feedback_dir / "inbox.json"
        with open(inbox_path, "w", encoding="utf-8") as f:
            json.dump(inbox_data, f)

        result = storage.load_inbox()
        assert result["total_messages"] == 1
        assert result["messages"][0]["id"] == "abcd1234"

    def test_handles_corrupt_json(self, mock_feedback_dir):
        """Should return empty inbox when JSON is corrupt."""
        mock_feedback_dir.mkdir(parents=True, exist_ok=True)
        inbox_path = mock_feedback_dir / "inbox.json"
        with open(inbox_path, "w", encoding="utf-8") as f:
            f.write("{invalid json!!!")

        result = storage.load_inbox()
        assert result["total_messages"] == 0
        assert result["messages"] == []


class TestSaveInbox:
    """Tests for save_inbox()."""

    def test_saves_data_to_disk(self, mock_feedback_dir):
        """Should write inbox data as JSON to disk."""
        data = {
            "mailbox": "feedback",
            "total_messages": 2,
            "unread_count": 1,
            "messages": [{"id": "a"}, {"id": "b"}],
        }
        storage.save_inbox(data)

        inbox_path = mock_feedback_dir / "inbox.json"
        assert inbox_path.exists()

        with open(inbox_path, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["total_messages"] == 2
        assert len(loaded["messages"]) == 2

    def test_creates_directory_on_save(self, mock_feedback_dir):
        """Should create the directory if it does not exist during save."""
        assert not mock_feedback_dir.exists()
        storage.save_inbox({"mailbox": "feedback", "total_messages": 0, "unread_count": 0, "messages": []})
        assert mock_feedback_dir.exists()

    def test_overwrites_existing_file(self, mock_feedback_dir):
        """Should overwrite existing data on save."""
        storage.save_inbox({"mailbox": "feedback", "total_messages": 1, "unread_count": 0, "messages": [{"id": "x"}]})
        storage.save_inbox({"mailbox": "feedback", "total_messages": 0, "unread_count": 0, "messages": []})

        result = storage.load_inbox()
        assert result["total_messages"] == 0
        assert result["messages"] == []


class TestGenerateId:
    """Tests for generate_id()."""

    def test_returns_8_chars(self):
        """Should return exactly 8 characters."""
        result = storage.generate_id()
        assert len(result) == 8

    def test_returns_hex_string(self):
        """Should return only hexadecimal characters."""
        result = storage.generate_id()
        assert all(c in "0123456789abcdef" for c in result)

    def test_returns_unique_ids(self):
        """Should generate different IDs on successive calls."""
        ids = {storage.generate_id() for _ in range(100)}
        # With 8 hex chars (32 bits), 100 IDs should all be unique
        assert len(ids) == 100
