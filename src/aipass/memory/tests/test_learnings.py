# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_learnings.py
# Date: 2026-04-03
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for the learnings manager handler.

Covers:
    parse_timestamp, add_timestamp, get_entry_age,
    get_max_learnings, get_max_recently_completed,
    ensure_timestamps, enforce_limit,
    ensure_timestamps_completed, enforce_limit_completed,
    add_learning, update_status_counts, process_file

All tests use mocks or tmp_path -- no live filesystem or infrastructure access.
"""

import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helper: import learnings manager with mocked dependencies
# ---------------------------------------------------------------------------


def _import_learnings_manager(monkeypatch):
    """Import manager with mocked dependencies."""
    # Mock memory_files since it's imported at module level
    mock_memory_files = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "aipass.memory.apps.handlers.json.memory_files",
        mock_memory_files,
    )

    sys.modules.pop("aipass.memory.apps.handlers.learnings.manager", None)
    parent = sys.modules.get("aipass.memory.apps.handlers.learnings")
    if parent is not None and hasattr(parent, "manager"):
        delattr(parent, "manager")
    from aipass.memory.apps.handlers.learnings import manager

    return manager, mock_memory_files


# ---------------------------------------------------------------------------
# Fixture: fresh manager per test
# ---------------------------------------------------------------------------


@pytest.fixture()
def mgr(monkeypatch):
    """Yield (manager_module, mock_memory_files) with a fresh import."""
    manager, mock_mf = _import_learnings_manager(monkeypatch)
    return manager, mock_mf


# ===========================================================================
# TIMESTAMP OPERATIONS
# ===========================================================================


class TestParseTimestamp:
    """Tests for parse_timestamp()."""

    def test_with_timestamp(self, mgr):
        manager, _ = mgr
        clean, ts = manager.parse_timestamp("some learning [2026-02-04]")
        assert clean == "some learning"
        assert ts == "2026-02-04"

    def test_without_timestamp(self, mgr):
        manager, _ = mgr
        clean, ts = manager.parse_timestamp("no date here")
        assert clean == "no date here"
        assert ts is None

    def test_timestamp_in_middle_not_matched(self, mgr):
        """Only trailing [YYYY-MM-DD] should match."""
        manager, _ = mgr
        clean, ts = manager.parse_timestamp("found [2026-01-01] in the middle")
        assert ts is None
        assert clean == "found [2026-01-01] in the middle"

    def test_with_trailing_whitespace(self, mgr):
        manager, _ = mgr
        clean, ts = manager.parse_timestamp("value [2026-03-15]  ")
        assert clean == "value"
        assert ts == "2026-03-15"

    def test_empty_string(self, mgr):
        manager, _ = mgr
        clean, ts = manager.parse_timestamp("")
        assert clean == ""
        assert ts is None


class TestAddTimestamp:
    """Tests for add_timestamp()."""

    def test_adds_date_to_plain_value(self, mgr):
        manager, _ = mgr
        result = manager.add_timestamp("my learning", date="2026-04-03")
        assert result == "my learning [2026-04-03]"

    def test_replaces_existing_date(self, mgr):
        manager, _ = mgr
        result = manager.add_timestamp("old learning [2025-01-01]", date="2026-04-03")
        assert result == "old learning [2026-04-03]"

    def test_defaults_to_today(self, mgr):
        manager, _ = mgr
        today = datetime.now().strftime("%Y-%m-%d")
        result = manager.add_timestamp("test value")
        assert result == f"test value [{today}]"

    def test_explicit_date(self, mgr):
        manager, _ = mgr
        result = manager.add_timestamp("explicit", date="2030-12-31")
        assert result == "explicit [2030-12-31]"


class TestGetEntryAge:
    """Tests for get_entry_age()."""

    def test_recent_timestamp(self, mgr):
        manager, _ = mgr
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        age = manager.get_entry_age(f"learning [{yesterday}]")
        assert age == 1

    def test_today_timestamp(self, mgr):
        manager, _ = mgr
        today = datetime.now().strftime("%Y-%m-%d")
        age = manager.get_entry_age(f"learning [{today}]")
        assert age == 0

    def test_no_timestamp_returns_sentinel(self, mgr):
        manager, _ = mgr
        age = manager.get_entry_age("no timestamp")
        assert age == 999999

    def test_invalid_timestamp_returns_sentinel(self, mgr):
        manager, _ = mgr
        age = manager.get_entry_age("bad date [9999-99-99]")
        assert age == 999999


# ===========================================================================
# CONFIG OPERATIONS
# ===========================================================================


class TestGetMaxLearnings:
    """Tests for get_max_learnings()."""

    def test_with_limits_set(self, mgr):
        manager, _ = mgr
        data = {"document_metadata": {"limits": {"max_learnings": 50}}}
        assert manager.get_max_learnings(data) == 50

    def test_without_limits_returns_default(self, mgr):
        manager, _ = mgr
        assert manager.get_max_learnings({}) == 100

    def test_without_max_learnings_key(self, mgr):
        manager, _ = mgr
        data = {"document_metadata": {"limits": {}}}
        assert manager.get_max_learnings(data) == 100


class TestGetMaxRecentlyCompleted:
    """Tests for get_max_recently_completed()."""

    def test_with_limits_set(self, mgr):
        manager, _ = mgr
        data = {"document_metadata": {"limits": {"max_recently_completed": 10}}}
        assert manager.get_max_recently_completed(data) == 10

    def test_without_limits_returns_default(self, mgr):
        manager, _ = mgr
        assert manager.get_max_recently_completed({}) == 20


# ===========================================================================
# CORE OPERATIONS -- ensure_timestamps
# ===========================================================================


class TestEnsureTimestamps:
    """Tests for ensure_timestamps()."""

    def test_file_not_found(self, mgr, tmp_path):
        manager, _ = mgr
        missing = tmp_path / "missing.json"
        result = manager.ensure_timestamps(missing)
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_adds_timestamps_to_entries_missing_them(self, mgr, tmp_path):
        manager, mock_mf = mgr
        fp = tmp_path / "TEST.local.json"
        fp.write_text("{}", encoding="utf-8")

        sample_data = {
            "key_learnings": {
                "has_ts": "already stamped [2026-01-01]",
                "no_ts": "needs a stamp",
            }
        }
        mock_mf.read_memory_file_data.return_value = sample_data
        mock_mf.write_memory_file_simple.return_value = None

        result = manager.ensure_timestamps(fp)

        assert result["success"] is True
        assert result["updated"] == 1
        assert result["total"] == 2
        mock_mf.write_memory_file_simple.assert_called_once()

    def test_all_have_timestamps_no_write(self, mgr, tmp_path):
        manager, mock_mf = mgr
        fp = tmp_path / "TEST.local.json"
        fp.write_text("{}", encoding="utf-8")

        sample_data = {
            "key_learnings": {
                "a": "value [2026-01-01]",
                "b": "value [2026-02-01]",
            }
        }
        mock_mf.read_memory_file_data.return_value = sample_data

        result = manager.ensure_timestamps(fp)

        assert result["success"] is True
        assert result["updated"] == 0
        mock_mf.write_memory_file_simple.assert_not_called()

    def test_no_key_learnings_section(self, mgr, tmp_path):
        manager, mock_mf = mgr
        fp = tmp_path / "TEST.local.json"
        fp.write_text("{}", encoding="utf-8")

        mock_mf.read_memory_file_data.return_value = {"sessions": []}

        result = manager.ensure_timestamps(fp)

        assert result["success"] is True
        assert result["updated"] == 0

    def test_returns_error_on_none_data(self, mgr, tmp_path):
        manager, mock_mf = mgr
        fp = tmp_path / "TEST.local.json"
        fp.write_text("{}", encoding="utf-8")

        mock_mf.read_memory_file_data.return_value = None

        result = manager.ensure_timestamps(fp)
        assert result["success"] is False


# ===========================================================================
# CORE OPERATIONS -- enforce_limit
# ===========================================================================


class TestEnforceLimit:
    """Tests for enforce_limit()."""

    def test_file_not_found(self, mgr, tmp_path):
        manager, _ = mgr
        missing = tmp_path / "missing.json"
        result = manager.enforce_limit(missing)
        assert result["success"] is False

    def test_under_limit_no_removal(self, mgr, tmp_path):
        manager, mock_mf = mgr
        fp = tmp_path / "TEST.local.json"
        fp.write_text("{}", encoding="utf-8")

        data = {
            "key_learnings": {"a": "val [2026-01-01]"},
            "document_metadata": {"limits": {"max_learnings": 5}},
        }
        mock_mf.read_memory_file_data.return_value = data

        result = manager.enforce_limit(fp)
        assert result["success"] is True
        assert result["removed"] == 0

    def test_over_limit_removes_oldest(self, mgr, tmp_path, monkeypatch):
        manager, mock_mf = mgr
        fp = tmp_path / "TEST.local.json"
        fp.write_text("{}", encoding="utf-8")

        old_date = (datetime.now() - timedelta(days=300)).strftime("%Y-%m-%d")
        new_date = datetime.now().strftime("%Y-%m-%d")

        data = {
            "key_learnings": {
                "old1": f"old learning [{old_date}]",
                "old2": f"ancient [{old_date}]",
                "new1": f"recent [{new_date}]",
            },
            "document_metadata": {"limits": {"max_learnings": 2}},
        }
        mock_mf.read_memory_file_data.return_value = data
        mock_mf.write_memory_file_simple.return_value = None

        # Mock _vectorize_learnings to avoid subprocess
        monkeypatch.setattr(
            manager,
            "_vectorize_learnings",
            lambda branch, learnings: {"success": True},
        )

        result = manager.enforce_limit(fp)

        assert result["success"] is True
        assert result["removed"] == 1
        assert result["remaining"] == 2
        assert result["max"] == 2
        mock_mf.write_memory_file_simple.assert_called_once()

    def test_no_learnings_section(self, mgr, tmp_path):
        manager, mock_mf = mgr
        fp = tmp_path / "TEST.local.json"
        fp.write_text("{}", encoding="utf-8")

        mock_mf.read_memory_file_data.return_value = {"sessions": []}

        result = manager.enforce_limit(fp)
        assert result["success"] is True
        assert result["removed"] == 0


# ===========================================================================
# RECENTLY_COMPLETED OPERATIONS
# ===========================================================================


class TestEnsureTimestampsCompleted:
    """Tests for ensure_timestamps_completed()."""

    def test_file_not_found(self, mgr, tmp_path):
        manager, _ = mgr
        missing = tmp_path / "nope.json"
        result = manager.ensure_timestamps_completed(missing)
        assert result["success"] is False

    def test_adds_timestamps_to_list_entries(self, mgr, tmp_path):
        manager, mock_mf = mgr
        fp = tmp_path / "TEST.local.json"
        fp.write_text("{}", encoding="utf-8")

        data = {
            "recently_completed": [
                "Task A [2026-01-01]",
                "Task B without stamp",
            ]
        }
        mock_mf.read_memory_file_data.return_value = data
        mock_mf.write_memory_file_simple.return_value = None

        result = manager.ensure_timestamps_completed(fp)

        assert result["success"] is True
        assert result["updated"] == 1
        assert result["total"] == 2

    def test_no_recently_completed(self, mgr, tmp_path):
        manager, mock_mf = mgr
        fp = tmp_path / "TEST.local.json"
        fp.write_text("{}", encoding="utf-8")

        mock_mf.read_memory_file_data.return_value = {}

        result = manager.ensure_timestamps_completed(fp)
        assert result["success"] is True
        assert result["updated"] == 0


class TestEnforceLimitCompleted:
    """Tests for enforce_limit_completed()."""

    def test_file_not_found(self, mgr, tmp_path):
        manager, _ = mgr
        missing = tmp_path / "missing.json"
        result = manager.enforce_limit_completed(missing)
        assert result["success"] is False

    def test_under_limit(self, mgr, tmp_path):
        manager, mock_mf = mgr
        fp = tmp_path / "TEST.local.json"
        fp.write_text("{}", encoding="utf-8")

        data = {
            "recently_completed": ["Task [2026-01-01]"],
            "document_metadata": {"limits": {"max_recently_completed": 10}},
        }
        mock_mf.read_memory_file_data.return_value = data

        result = manager.enforce_limit_completed(fp)
        assert result["success"] is True
        assert result["removed"] == 0

    def test_over_limit_removes_oldest(self, mgr, tmp_path, monkeypatch):
        manager, mock_mf = mgr
        fp = tmp_path / "TEST.local.json"
        fp.write_text("{}", encoding="utf-8")

        old_date = (datetime.now() - timedelta(days=200)).strftime("%Y-%m-%d")
        new_date = datetime.now().strftime("%Y-%m-%d")

        data = {
            "recently_completed": [
                f"Old task [{old_date}]",
                f"Another old [{old_date}]",
                f"Recent task [{new_date}]",
            ],
            "document_metadata": {"limits": {"max_recently_completed": 2}},
        }
        mock_mf.read_memory_file_data.return_value = data
        mock_mf.write_memory_file_simple.return_value = None

        # Mock _vectorize_completed_tasks to avoid subprocess
        monkeypatch.setattr(
            manager,
            "_vectorize_completed_tasks",
            lambda branch, tasks: {"success": True},
        )

        result = manager.enforce_limit_completed(fp)

        assert result["success"] is True
        assert result["removed"] == 1
        assert result["remaining"] == 2
        assert result["max"] == 2


# ===========================================================================
# ADD LEARNING
# ===========================================================================


class TestAddLearning:
    """Tests for add_learning()."""

    def test_file_not_found(self, mgr, tmp_path):
        manager, _ = mgr
        missing = tmp_path / "missing.json"
        result = manager.add_learning(missing, "key", "value")
        assert result["success"] is False

    def test_adds_new_entry(self, mgr, tmp_path, monkeypatch):
        manager, mock_mf = mgr
        fp = tmp_path / "TEST.local.json"
        fp.write_text("{}", encoding="utf-8")

        data = {
            "key_learnings": {},
            "document_metadata": {"limits": {"max_learnings": 100}},
        }
        mock_mf.read_memory_file_data.return_value = data
        mock_mf.write_memory_file_simple.return_value = None

        # Mock enforce_limit inside add_learning
        monkeypatch.setattr(
            manager,
            "enforce_limit",
            lambda fp: {"success": True, "removed": 0},
        )

        result = manager.add_learning(fp, "test_key", "test value")

        assert result["success"] is True
        assert result["action"] == "added"
        assert result["key"] == "test_key"
        assert "[" in result["value"]  # has timestamp

    def test_updates_existing_entry(self, mgr, tmp_path, monkeypatch):
        manager, mock_mf = mgr
        fp = tmp_path / "TEST.local.json"
        fp.write_text("{}", encoding="utf-8")

        data = {
            "key_learnings": {"existing_key": "old value [2025-01-01]"},
            "document_metadata": {"limits": {"max_learnings": 100}},
        }
        mock_mf.read_memory_file_data.return_value = data
        mock_mf.write_memory_file_simple.return_value = None

        monkeypatch.setattr(
            manager,
            "enforce_limit",
            lambda fp: {"success": True, "removed": 0},
        )

        result = manager.add_learning(fp, "existing_key", "updated value")

        assert result["success"] is True
        assert result["action"] == "updated"


# ===========================================================================
# UPDATE STATUS COUNTS
# ===========================================================================


class TestUpdateStatusCounts:
    """Tests for update_status_counts()."""

    def test_file_not_found(self, mgr, tmp_path):
        manager, _ = mgr
        missing = tmp_path / "missing.json"
        result = manager.update_status_counts(missing)
        assert result["success"] is False

    def test_updates_counts_correctly(self, mgr, tmp_path):
        manager, mock_mf = mgr
        fp = tmp_path / "TEST.local.json"
        fp.write_text("{}", encoding="utf-8")

        data = {
            "key_learnings": {
                "a": "val [2026-01-01]",
                "b": "val [2026-01-02]",
                "c": "val [2026-01-03]",
            },
            "recently_completed": ["task1 [2026-01-01]", "task2 [2026-01-02]"],
            "document_metadata": {
                "status": {
                    "current_key_learnings": 0,
                    "current_recently_completed": 0,
                }
            },
        }
        mock_mf.read_memory_file_data.return_value = data
        mock_mf.write_memory_file_simple.return_value = None

        result = manager.update_status_counts(fp)

        assert result["success"] is True
        assert result["current_key_learnings"] == 3
        assert result["current_recently_completed"] == 2
        assert result["changed"] is True

    def test_no_change_skips_write(self, mgr, tmp_path):
        manager, mock_mf = mgr
        fp = tmp_path / "TEST.local.json"
        fp.write_text("{}", encoding="utf-8")

        data = {
            "key_learnings": {"a": "val [2026-01-01]"},
            "recently_completed": ["task [2026-01-01]"],
            "document_metadata": {
                "status": {
                    "current_key_learnings": 1,
                    "current_recently_completed": 1,
                }
            },
        }
        mock_mf.read_memory_file_data.return_value = data

        result = manager.update_status_counts(fp)

        assert result["success"] is True
        assert result["changed"] is False
        mock_mf.write_memory_file_simple.assert_not_called()

    def test_creates_missing_metadata_structure(self, mgr, tmp_path):
        manager, mock_mf = mgr
        fp = tmp_path / "TEST.local.json"
        fp.write_text("{}", encoding="utf-8")

        data = {
            "key_learnings": {"a": "val [2026-01-01]"},
            "recently_completed": [],
        }
        mock_mf.read_memory_file_data.return_value = data
        mock_mf.write_memory_file_simple.return_value = None

        result = manager.update_status_counts(fp)

        assert result["success"] is True
        assert result["current_key_learnings"] == 1
        assert result["current_recently_completed"] == 0


# ===========================================================================
# BATCH -- process_file
# ===========================================================================


class TestProcessFile:
    """Tests for process_file()."""

    def test_file_not_found(self, mgr, tmp_path):
        manager, _ = mgr
        missing = tmp_path / "missing.json"
        result = manager.process_file(missing)
        assert result["success"] is False

    def test_processes_both_sections(self, mgr, tmp_path, monkeypatch):
        manager, mock_mf = mgr
        fp = tmp_path / "TEST.local.json"
        fp.write_text("{}", encoding="utf-8")

        today = datetime.now().strftime("%Y-%m-%d")
        data = {
            "key_learnings": {
                "a": f"val [{today}]",
            },
            "recently_completed": [f"task [{today}]"],
            "document_metadata": {
                "limits": {"max_learnings": 100, "max_recently_completed": 20},
                "status": {
                    "current_key_learnings": 0,
                    "current_recently_completed": 0,
                },
            },
        }
        mock_mf.read_memory_file_data.return_value = data
        mock_mf.write_memory_file_simple.return_value = None

        # Mock vectorization helpers to avoid subprocess calls
        monkeypatch.setattr(
            manager,
            "_vectorize_learnings",
            lambda branch, learnings: {"success": True},
        )
        monkeypatch.setattr(
            manager,
            "_vectorize_completed_tasks",
            lambda branch, tasks: {"success": True},
        )

        result = manager.process_file(fp)

        assert result["success"] is True
        assert "key_learnings" in result
        assert "recently_completed" in result
        assert "status" in result
