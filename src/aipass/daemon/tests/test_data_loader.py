# ===================AIPASS====================
# META DATA HEADER
# Name: test_data_loader.py - Data Loader Tests
# Date: 2026-03-24
# Version: 1.0.0
# Category: daemon/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-24): Initial creation - data_loader handler tests
#
# CODE STANDARDS:
#   - Pytest conventions
#   - Temp dir isolation (no reads from real data files)
# =============================================

"""Tests for the data_loader handler."""

import json
from pathlib import Path

import pytest

from aipass.daemon.apps.handlers.update import data_loader as _dl_mod

load_inbox = _dl_mod.load_inbox
load_local = _dl_mod.load_local
categorize_messages = _dl_mod.categorize_messages
get_session_summary = _dl_mod.get_session_summary
get_escalations = _dl_mod.get_escalations


# =============================================
# FIXTURES
# =============================================

@pytest.fixture(autouse=True)
def isolate_paths(tmp_path, monkeypatch):
    """Redirect INBOX_PATH and LOCAL_PATH to tmp_path for every test."""
    inbox = tmp_path / "inbox.json"
    local = tmp_path / "DAEMON.local.json"
    monkeypatch.setattr(_dl_mod, "INBOX_PATH", inbox)
    monkeypatch.setattr(_dl_mod, "LOCAL_PATH", local)
    yield {"inbox": inbox, "local": local}


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


@pytest.fixture()
def sample_local_data():
    """Standard local.json payload for reuse across tests."""
    return {
        "document_metadata": {"version": "1.0.0"},
        "sessions": [
            {"session_number": 1, "date": "2026-03-01", "summary": "Initial setup", "status": "completed"},
        ],
        "active_tasks": {"current_plan": "Test plan"},
    }


def _write_json(path: Path, data: object) -> None:
    """Helper to write JSON to a path."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


# =============================================
# LOAD INBOX TESTS
# =============================================

class TestLoadInbox:
    def test_load_valid_inbox(self, isolate_paths, sample_inbox_data, monkeypatch):
        """Loading a well-formed inbox.json returns its full contents."""
        monkeypatch.setattr(_dl_mod.json_handler, "log_operation", lambda *a, **kw: None)
        _write_json(isolate_paths["inbox"], sample_inbox_data)
        result = load_inbox()
        assert result["mailbox"] == "inbox"
        assert result["total_messages"] == 2
        assert len(result["messages"]) == 2

    def test_load_inbox_missing_file(self, isolate_paths, monkeypatch):
        """Missing inbox.json returns empty default structure."""
        monkeypatch.setattr(_dl_mod.json_handler, "log_operation", lambda *a, **kw: None)
        result = load_inbox()
        assert result == {"messages": [], "total_messages": 0, "unread_count": 0}

    def test_load_inbox_malformed_json(self, isolate_paths, monkeypatch):
        """Malformed JSON falls back to empty default structure."""
        monkeypatch.setattr(_dl_mod.json_handler, "log_operation", lambda *a, **kw: None)
        isolate_paths["inbox"].write_text("{not valid json!!!", encoding="utf-8")
        result = load_inbox()
        assert result == {"messages": [], "total_messages": 0, "unread_count": 0}

    def test_load_inbox_empty_messages(self, isolate_paths, monkeypatch):
        """Inbox with zero messages returns its original data."""
        monkeypatch.setattr(_dl_mod.json_handler, "log_operation", lambda *a, **kw: None)
        data = {"mailbox": "inbox", "total_messages": 0, "unread_count": 0, "messages": []}
        _write_json(isolate_paths["inbox"], data)
        result = load_inbox()
        assert result["messages"] == []
        assert result["total_messages"] == 0


# =============================================
# LOAD LOCAL TESTS
# =============================================

class TestLoadLocal:
    def test_load_valid_local(self, isolate_paths, sample_local_data):
        """Loading a well-formed local.json returns its full contents."""
        _write_json(isolate_paths["local"], sample_local_data)
        result = load_local()
        assert result["document_metadata"]["version"] == "1.0.0"
        assert len(result["sessions"]) == 1
        assert result["active_tasks"]["current_plan"] == "Test plan"

    def test_load_local_missing_file(self, isolate_paths):
        """Missing local.json returns empty default structure."""
        result = load_local()
        assert result == {"sessions": [], "active_tasks": {}}

    def test_load_local_malformed_json(self, isolate_paths):
        """Malformed JSON falls back to empty default structure."""
        isolate_paths["local"].write_text("<<<bad>>>", encoding="utf-8")
        result = load_local()
        assert result == {"sessions": [], "active_tasks": {}}

    def test_load_local_empty_sessions(self, isolate_paths):
        """Local file with empty sessions still loads correctly."""
        data = {"sessions": [], "active_tasks": {}}
        _write_json(isolate_paths["local"], data)
        result = load_local()
        assert result["sessions"] == []
        assert result["active_tasks"] == {}


# =============================================
# CATEGORIZE MESSAGES TESTS
# =============================================

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


# =============================================
# GET SESSION SUMMARY TESTS
# =============================================

class TestGetSessionSummary:
    def test_summary_with_sessions(self, sample_local_data):
        """Session summary extracts totals and latest session."""
        result = get_session_summary(sample_local_data)
        assert result["total_sessions"] == 1
        assert result["latest_session"]["session_number"] == 1

    def test_summary_empty_sessions(self):
        """Empty sessions list yields zero count and None latest."""
        result = get_session_summary({"sessions": [], "active_tasks": {}})
        assert result["total_sessions"] == 0
        assert result["latest_session"] is None

    def test_summary_today_focus(self):
        """today_focus is extracted from active_tasks when present."""
        data = {"sessions": [], "active_tasks": {"today_focus": "Write tests"}}
        result = get_session_summary(data)
        assert result["today_focus"] == "Write tests"

    def test_summary_today_focus_default(self):
        """today_focus falls back to 'None' string when absent."""
        data = {"sessions": [], "active_tasks": {}}
        result = get_session_summary(data)
        assert result["today_focus"] == "None"

    def test_summary_recently_completed(self):
        """recently_completed list is extracted from active_tasks."""
        data = {"sessions": [], "active_tasks": {"recently_completed": ["task-a", "task-b"]}}
        result = get_session_summary(data)
        assert result["recently_completed"] == ["task-a", "task-b"]

    def test_summary_recently_completed_default(self):
        """recently_completed defaults to empty list when absent."""
        data = {"sessions": [], "active_tasks": {}}
        result = get_session_summary(data)
        assert result["recently_completed"] == []


# =============================================
# GET ESCALATIONS TESTS
# =============================================

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
