# =================== AIPass ====================
# Name: test_data_loader.py
# Description: Data loader tests — inbox and local.json loading, message triage, the real mailbox path
# Version: 1.2.1
# Created: 2026-03-24
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/update/data_loader.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — json.load's own parse of a well-formed file

import json
from pathlib import Path

import pytest

from aipass.daemon.apps.handlers.update import data_loader as _dl_mod

# Taken before isolate_paths patches INBOX_PATH: the path the code really reads.
_REAL_INBOX_PATH = _dl_mod.INBOX_PATH
_BRANCH_MAILBOX = Path(__file__).resolve().parents[1] / ".ai_mail.local" / "inbox.json"

load_inbox = _dl_mod.load_inbox
categorize_messages = _dl_mod.categorize_messages
get_escalations = _dl_mod.get_escalations


@pytest.fixture(autouse=True)
def isolate_paths(tmp_path, monkeypatch):
    """Redirect INBOX_PATH to tmp_path for every test."""
    inbox = tmp_path / "inbox.json"
    monkeypatch.setattr(_dl_mod, "INBOX_PATH", inbox)
    yield {"inbox": inbox}


@pytest.fixture()
def sample_inbox_data():
    """Standard inbox payload for reuse across tests."""
    return {
        "mailbox": "inbox",
        "total_messages": 2,
        "unread_count": 1,
        "messages": [
            {"id": "abc123", "status": "new", "subject": "Test", "from": "@devpulse", "priority": "normal"},
            {"id": "def456", "status": "opened", "subject": "FYI", "from": "@drone", "priority": "normal"},
        ],
    }


def _write_json(path: Path, data: object) -> None:
    """Helper to write JSON to a path."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


class TestLoadInbox:
    def test_load_valid_inbox(self, isolate_paths, sample_inbox_data, monkeypatch):
        """Loading a well-formed inbox.json returns its full contents and logs the load.

        Mutant killed: the json_handler.log_operation("data_loaded") call removed from load_inbox.
        """
        ops = []
        monkeypatch.setattr(_dl_mod.json_handler, "log_operation", lambda *a, **kw: ops.append(a))
        _write_json(isolate_paths["inbox"], sample_inbox_data)
        result = load_inbox()
        assert ops == [("data_loaded",)]
        assert result["mailbox"] == "inbox"
        assert result["total_messages"] == 2
        assert len(result["messages"]) == 2

    def test_load_inbox_missing_file(self, isolate_paths):
        """Missing inbox.json returns empty default structure."""
        result = load_inbox()
        assert result == {"messages": [], "total_messages": 0, "unread_count": 0}

    def test_load_inbox_malformed_json(self, isolate_paths):
        """Malformed JSON raises: answered as empty, the digest would report a false zero."""
        isolate_paths["inbox"].write_text("{not valid json!!!", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_inbox()

    def test_load_inbox_empty_messages(self, isolate_paths):
        """Inbox with zero messages returns its original data."""
        data = {"mailbox": "inbox", "total_messages": 0, "unread_count": 0, "messages": []}
        _write_json(isolate_paths["inbox"], data)
        result = load_inbox()
        assert result["messages"] == []
        assert result["total_messages"] == 0


class TestInboxPathIsTheRealMailbox:
    """The inbox reader must point at the branch's dotted .ai_mail.local mailbox."""

    def test_data_loader_reads_the_dotted_mailbox(self):
        assert _REAL_INBOX_PATH == _BRANCH_MAILBOX


class TestCategorizeMessages:
    def test_new_and_opened_split(self):
        """Messages are split into new and opened buckets by status."""
        messages = [
            {"id": "1", "status": "new", "subject": "Hello"},
            {"id": "2", "status": "opened", "subject": "World"},
        ]
        cats = categorize_messages(messages)
        assert len(cats["new"]) == 1
        assert cats["new"][0]["id"] == "1"
        assert len(cats["opened"]) == 1
        assert cats["opened"][0]["id"] == "2"

    def test_actionable_keywords(self):
        """Subjects with action keywords land in the actionable bucket."""
        messages = [
            {"id": "1", "status": "new", "subject": "TASK: Deploy v2"},
            {"id": "2", "status": "new", "subject": "BUILD: nightly"},
            {"id": "3", "status": "new", "subject": "FIX: broken pipe"},
            {"id": "4", "status": "new", "subject": "PROPOSAL: new module"},
            {"id": "5", "status": "new", "subject": "REQUEST: access"},
        ]
        cats = categorize_messages(messages)
        assert len(cats["actionable"]) == 5

    def test_informational_keywords(self):
        """Subjects with info keywords land in the informational bucket."""
        messages = [
            {"id": "1", "status": "new", "subject": "FYI: update deployed"},
            {"id": "2", "status": "opened", "subject": "RE: earlier thread"},
            {"id": "3", "status": "new", "subject": "INFO dashboard ready"},
            {"id": "4", "status": "new", "subject": "NOTIFICATION: backup done"},
        ]
        cats = categorize_messages(messages)
        assert len(cats["informational"]) == 4

    def test_message_can_appear_in_multiple_categories(self):
        """A new message with an actionable subject appears in both new and actionable."""
        messages = [
            {"id": "1", "status": "new", "subject": "TASK: urgent fix"},
        ]
        cats = categorize_messages(messages)
        assert len(cats["new"]) == 1
        assert len(cats["actionable"]) == 1
        assert cats["new"][0] is cats["actionable"][0]

    def test_empty_messages(self):
        """Empty message list returns all empty categories."""
        cats = categorize_messages([])
        assert cats == {"new": [], "opened": [], "actionable": [], "informational": []}

    def test_unknown_status_defaults_to_new(self):
        """A message with no status field defaults to new bucket."""
        messages = [{"id": "1", "subject": "No status field"}]
        cats = categorize_messages(messages)
        assert len(cats["new"]) == 1

    def test_unrecognised_status_skips_status_buckets(self):
        """A message with a status other than new/opened does not land in status buckets."""
        messages = [{"id": "1", "status": "closed", "subject": "Done"}]
        cats = categorize_messages(messages)
        assert len(cats["new"]) == 0
        assert len(cats["opened"]) == 0


class TestGetEscalations:
    def test_urgent_message_detected(self):
        """Messages with URGENT in subject are escalated."""
        messages = [
            {"id": "1", "subject": "URGENT: seedgo audit failed"},
            {"id": "2", "subject": "Normal update"},
        ]
        result = get_escalations(messages)
        assert len(result) == 1
        assert result[0]["id"] == "1"

    def test_blocked_message_detected(self):
        """Messages with BLOCKED in subject are escalated."""
        messages = [
            {"id": "1", "subject": "BLOCKED: waiting on upstream"},
        ]
        result = get_escalations(messages)
        assert len(result) == 1
        assert result[0]["id"] == "1"

    def test_no_escalations(self):
        """Messages without escalation keywords return empty list."""
        messages = [
            {"id": "1", "subject": "FYI: all clear"},
            {"id": "2", "subject": "RE: weekly sync"},
        ]
        result = get_escalations(messages)
        assert result == []

    def test_empty_messages(self):
        """Empty message list returns empty escalations."""
        assert get_escalations([]) == []

    def test_case_insensitive_detection(self):
        """Escalation keywords are detected case-insensitively."""
        messages = [
            {"id": "1", "subject": "urgent build failure"},
            {"id": "2", "subject": "Blocked on review"},
        ]
        result = get_escalations(messages)
        assert len(result) == 2

    def test_missing_subject_field(self):
        """Messages without a subject field are not escalated."""
        messages = [{"id": "1"}]
        result = get_escalations(messages)
        assert result == []
