# ===================AIPASS====================
# META DATA HEADER
# Name: test_red_flag_detector.py - Red Flag Detector Tests
# Date: 2026-03-24
# Version: 1.0.0
# Category: daemon/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-24): Initial creation - red flag detection engine tests
#
# CODE STANDARDS:
#   - Pytest conventions
#   - unittest.mock.patch for external dependencies
# =============================================

"""Tests for the red flag detection engine."""

from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest

from aipass.daemon.apps.handlers.monitoring import red_flag_detector
from aipass.daemon.apps.handlers.monitoring.red_flag_detector import (
    _parse_iso_datetime,
    get_branch_status,
    detect_red_flags,
    get_red_flag_summary,
    STATUS_RED_FLAG,
    STATUS_OK,
    STATUS_NO_ACTIVITY,
    STATUS_ERROR,
)

MOCK_PATCH_ACTIVITY = "aipass.daemon.apps.handlers.monitoring.activity_collector.scan_branch_activity"
MOCK_PATCH_BRANCHES = "aipass.daemon.apps.handlers.monitoring.activity_collector.get_branch_paths"
MOCK_PATCH_JSON_LOG = "aipass.daemon.apps.handlers.monitoring.red_flag_detector.json_handler.log_operation"


def _make_activity(
    branch_name: str = "TEST",
    code_files: list | None = None,
    memory_files: list | None = None,
) -> dict:
    """Build a mock return value for scan_branch_activity."""
    if code_files is None:
        code_files = []
    if memory_files is None:
        memory_files = []

    all_files = code_files + memory_files
    last_activity = None
    if all_files:
        last_activity = max(f["mtime"] for f in all_files)

    return {
        "branch_name": branch_name,
        "path": f"/fake/path/{branch_name.lower()}",
        "code_files": code_files,
        "memory_files": memory_files,
        "last_activity": last_activity,
        "total_files": len(all_files),
        "scan_time": datetime.now().isoformat(),
    }


# =============================================
# _parse_iso_datetime TESTS
# =============================================

class TestParseIsoDatetime:
    """Tests for ISO datetime string parsing."""

    def test_valid_iso_string(self):
        """Parse a standard ISO datetime string."""
        result = _parse_iso_datetime("2026-03-20T10:00:00")
        assert result is not None
        assert isinstance(result, datetime)
        assert result.year == 2026
        assert result.month == 3
        assert result.day == 20
        assert result.hour == 10

    def test_valid_iso_string_with_microseconds(self):
        """Parse ISO datetime string containing microseconds."""
        result = _parse_iso_datetime("2026-03-20T10:30:00.123456")
        assert result is not None
        assert isinstance(result, datetime)
        assert result.microsecond == 123456

    def test_valid_iso_date_only(self):
        """Parse a date-only ISO string (no time component)."""
        result = _parse_iso_datetime("2026-03-20")
        assert result is not None
        assert result.year == 2026
        assert result.hour == 0

    def test_empty_string_returns_none(self):
        """Empty string returns None."""
        assert _parse_iso_datetime("") is None

    def test_none_returns_none(self):
        """None input returns None (falsy check)."""
        assert _parse_iso_datetime(None) is None  # type: ignore[arg-type]

    def test_invalid_string_returns_none(self):
        """Invalid/garbage string returns None."""
        assert _parse_iso_datetime("not-a-date") is None

    def test_partial_iso_returns_none(self):
        """Malformed ISO string returns None."""
        assert _parse_iso_datetime("2026-13-40T99:99:99") is None


# =============================================
# get_branch_status TESTS
# =============================================

class TestGetBranchStatus:
    """Tests for single-branch status detection."""

    @patch(MOCK_PATCH_ACTIVITY)
    def test_no_code_changes_returns_no_activity(self, mock_scan):
        """No code files modified -> NO_ACTIVITY status."""
        mock_scan.return_value = _make_activity(code_files=[], memory_files=[])
        result = get_branch_status("TEST", "/fake/path/test")
        assert result["status"] == STATUS_NO_ACTIVITY
        assert result["branch_name"] == "TEST"
        assert result["code_change_count"] == 0
        assert "No code changes" in result["reason"]

    @patch(MOCK_PATCH_ACTIVITY)
    def test_code_changed_memory_updated_after_returns_ok(self, mock_scan):
        """Code changed, memory updated after code -> OK."""
        mock_scan.return_value = _make_activity(
            code_files=[
                {"path": "/fake/app.py", "name": "app.py", "mtime": "2026-03-20T10:00:00"},
            ],
            memory_files=[
                {"path": "/fake/.trinity/local.json", "name": "local.json", "mtime": "2026-03-20T12:00:00"},
            ],
        )
        result = get_branch_status("TEST", "/fake/path/test")
        assert result["status"] == STATUS_OK
        assert result["code_change_count"] == 1
        assert result["latest_code_change"] is not None
        assert result["memory_last_update"] is not None

    @patch(MOCK_PATCH_ACTIVITY)
    def test_code_changed_memory_at_same_time_returns_ok(self, mock_scan):
        """Code and memory modified at the same timestamp -> OK."""
        timestamp = "2026-03-20T10:00:00"
        mock_scan.return_value = _make_activity(
            code_files=[
                {"path": "/fake/app.py", "name": "app.py", "mtime": timestamp},
            ],
            memory_files=[
                {"path": "/fake/.trinity/local.json", "name": "local.json", "mtime": timestamp},
            ],
        )
        result = get_branch_status("TEST", "/fake/path/test")
        assert result["status"] == STATUS_OK
        assert result["hours_since_code"] == 0.0

    @patch(MOCK_PATCH_ACTIVITY)
    def test_code_changed_no_memory_returns_red_flag(self, mock_scan):
        """Code changed but no memory files modified at all -> RED_FLAG."""
        mock_scan.return_value = _make_activity(
            code_files=[
                {"path": "/fake/app.py", "name": "app.py", "mtime": "2026-03-20T10:00:00"},
            ],
            memory_files=[],
        )
        result = get_branch_status("TEST", "/fake/path/test")
        assert result["status"] == STATUS_RED_FLAG
        assert result["code_change_count"] == 1
        assert "no memory updates" in result["reason"]

    @patch(MOCK_PATCH_ACTIVITY)
    def test_code_changed_memory_way_before_returns_red_flag(self, mock_scan):
        """Memory updated long before code changes (outside threshold) -> RED_FLAG."""
        mock_scan.return_value = _make_activity(
            code_files=[
                {"path": "/fake/app.py", "name": "app.py", "mtime": "2026-03-20T10:00:00"},
            ],
            memory_files=[
                {"path": "/fake/.trinity/local.json", "name": "local.json", "mtime": "2026-03-19T01:00:00"},
            ],
        )
        result = get_branch_status("TEST", "/fake/path/test", threshold_hours=2.0)
        assert result["status"] == STATUS_RED_FLAG
        assert "BEFORE code" in result["reason"]

    @patch(MOCK_PATCH_ACTIVITY)
    def test_memory_slightly_before_within_threshold_returns_ok(self, mock_scan):
        """Memory updated slightly before code but within threshold -> OK."""
        mock_scan.return_value = _make_activity(
            code_files=[
                {"path": "/fake/app.py", "name": "app.py", "mtime": "2026-03-20T10:00:00"},
            ],
            memory_files=[
                {"path": "/fake/.trinity/local.json", "name": "local.json", "mtime": "2026-03-20T09:00:00"},
            ],
        )
        # threshold_hours=2.0 means 1 hour before is acceptable
        result = get_branch_status("TEST", "/fake/path/test", threshold_hours=2.0)
        assert result["status"] == STATUS_OK
        assert "within threshold" in result["reason"].lower()

    @patch(MOCK_PATCH_ACTIVITY)
    def test_scanner_exception_returns_error(self, mock_scan):
        """If scan_branch_activity raises an exception -> ERROR status."""
        mock_scan.side_effect = RuntimeError("disk on fire")
        result = get_branch_status("TEST", "/fake/path/test")
        assert result["status"] == STATUS_ERROR
        assert "disk on fire" in result["reason"]

    @patch(MOCK_PATCH_ACTIVITY)
    def test_multiple_code_files_uses_latest(self, mock_scan):
        """When multiple code files exist, the latest mtime drives the decision."""
        mock_scan.return_value = _make_activity(
            code_files=[
                {"path": "/fake/a.py", "name": "a.py", "mtime": "2026-03-20T08:00:00"},
                {"path": "/fake/b.py", "name": "b.py", "mtime": "2026-03-20T14:00:00"},
            ],
            memory_files=[
                {"path": "/fake/.trinity/local.json", "name": "local.json", "mtime": "2026-03-20T15:00:00"},
            ],
        )
        result = get_branch_status("TEST", "/fake/path/test")
        assert result["status"] == STATUS_OK
        assert result["code_change_count"] == 2
        # latest_code_change should be the 14:00 file
        assert "14:00:00" in result["latest_code_change"]

    @patch(MOCK_PATCH_ACTIVITY)
    def test_result_dict_has_required_keys(self, mock_scan):
        """Verify all expected keys are present in the returned dict."""
        mock_scan.return_value = _make_activity(code_files=[], memory_files=[])
        result = get_branch_status("TEST", "/fake/path/test")
        required_keys = {
            "branch_name", "branch_path", "status", "code_changes",
            "code_change_count", "latest_code_change", "memory_files_modified",
            "memory_last_update", "hours_since_code", "threshold_hours",
            "reason", "check_time",
        }
        assert required_keys.issubset(result.keys())

    @patch(MOCK_PATCH_ACTIVITY)
    def test_since_timestamp_passed_to_scanner(self, mock_scan):
        """Verify that since_timestamp is forwarded to the activity collector."""
        mock_scan.return_value = _make_activity(code_files=[], memory_files=[])
        since = datetime(2026, 3, 1, 0, 0, 0)
        get_branch_status("TEST", "/fake/path/test", since_timestamp=since)
        mock_scan.assert_called_once_with("TEST", "/fake/path/test", since)

    @patch(MOCK_PATCH_ACTIVITY)
    def test_default_threshold_is_two_hours(self, mock_scan):
        """Default threshold_hours should be 2.0."""
        mock_scan.return_value = _make_activity(code_files=[], memory_files=[])
        result = get_branch_status("TEST", "/fake/path/test")
        assert result["threshold_hours"] == 2.0

    @patch(MOCK_PATCH_ACTIVITY)
    def test_custom_threshold_respected(self, mock_scan):
        """Memory 3 hours before code is OK with threshold=4 but RED_FLAG with threshold=2."""
        mock_scan.return_value = _make_activity(
            code_files=[
                {"path": "/fake/app.py", "name": "app.py", "mtime": "2026-03-20T10:00:00"},
            ],
            memory_files=[
                {"path": "/fake/.trinity/local.json", "name": "local.json", "mtime": "2026-03-20T07:00:00"},
            ],
        )
        # 3 hours before code -- threshold=4 should be OK
        result_ok = get_branch_status("TEST", "/fake/path/test", threshold_hours=4.0)
        assert result_ok["status"] == STATUS_OK

        # Same data -- threshold=2 should be RED_FLAG
        result_red = get_branch_status("TEST", "/fake/path/test", threshold_hours=2.0)
        assert result_red["status"] == STATUS_RED_FLAG


# =============================================
# detect_red_flags (scan all branches) TESTS
# =============================================

class TestScanAllBranches:
    """Tests for multi-branch scanning and sorting via detect_red_flags."""

    @patch(MOCK_PATCH_JSON_LOG)
    @patch(MOCK_PATCH_ACTIVITY)
    @patch(MOCK_PATCH_BRANCHES)
    def test_scans_all_branches(self, mock_paths, mock_scan, mock_log):
        """detect_red_flags scans every branch returned by get_branch_paths."""
        mock_paths.return_value = [
            {"name": "ALPHA", "path": "/fake/alpha"},
            {"name": "BRAVO", "path": "/fake/bravo"},
        ]
        mock_scan.return_value = _make_activity(code_files=[], memory_files=[])
        results = detect_red_flags(since_timestamp=datetime(2026, 3, 1))
        assert len(results) == 2
        assert mock_scan.call_count == 2

    @patch(MOCK_PATCH_JSON_LOG)
    @patch(MOCK_PATCH_ACTIVITY)
    @patch(MOCK_PATCH_BRANCHES)
    def test_red_flag_sorted_first(self, mock_paths, mock_scan, mock_log):
        """RED_FLAG branches appear before OK and NO_ACTIVITY branches."""
        mock_paths.return_value = [
            {"name": "OK_BRANCH", "path": "/fake/ok"},
            {"name": "BAD_BRANCH", "path": "/fake/bad"},
            {"name": "IDLE_BRANCH", "path": "/fake/idle"},
        ]

        def side_effect(name, path, since):
            if name == "BAD_BRANCH":
                return _make_activity(
                    branch_name="BAD_BRANCH",
                    code_files=[{"path": "/f.py", "name": "f.py", "mtime": "2026-03-20T10:00:00"}],
                    memory_files=[],
                )
            if name == "OK_BRANCH":
                return _make_activity(
                    branch_name="OK_BRANCH",
                    code_files=[{"path": "/f.py", "name": "f.py", "mtime": "2026-03-20T10:00:00"}],
                    memory_files=[{"path": "/m.json", "name": "local.json", "mtime": "2026-03-20T12:00:00"}],
                )
            return _make_activity(branch_name="IDLE_BRANCH", code_files=[], memory_files=[])

        mock_scan.side_effect = side_effect
        results = detect_red_flags(since_timestamp=datetime(2026, 3, 1))

        assert results[0]["status"] == STATUS_RED_FLAG
        assert results[0]["branch_name"] == "BAD_BRANCH"
        # OK comes before NO_ACTIVITY in sort order
        statuses = [r["status"] for r in results]
        assert statuses.index(STATUS_RED_FLAG) < statuses.index(STATUS_OK)
        assert statuses.index(STATUS_OK) < statuses.index(STATUS_NO_ACTIVITY)

    @patch(MOCK_PATCH_JSON_LOG)
    @patch(MOCK_PATCH_ACTIVITY)
    @patch(MOCK_PATCH_BRANCHES)
    def test_empty_branch_list(self, mock_paths, mock_scan, mock_log):
        """No branches registered -> empty results list."""
        mock_paths.return_value = []
        results = detect_red_flags(since_timestamp=datetime(2026, 3, 1))
        assert results == []
        mock_scan.assert_not_called()

    @patch(MOCK_PATCH_JSON_LOG)
    @patch(MOCK_PATCH_ACTIVITY)
    @patch(MOCK_PATCH_BRANCHES)
    def test_skips_branches_missing_name_or_path(self, mock_paths, mock_scan, mock_log):
        """Branches with empty name or path are skipped."""
        mock_paths.return_value = [
            {"name": "", "path": "/fake/noname"},
            {"name": "VALID", "path": ""},
            {"name": "GOOD", "path": "/fake/good"},
        ]
        mock_scan.return_value = _make_activity(code_files=[], memory_files=[])
        results = detect_red_flags(since_timestamp=datetime(2026, 3, 1))
        assert len(results) == 1
        assert results[0]["branch_name"] == "GOOD"

    @patch(MOCK_PATCH_JSON_LOG)
    @patch(MOCK_PATCH_ACTIVITY)
    @patch(MOCK_PATCH_BRANCHES)
    def test_alphabetical_sort_within_same_status(self, mock_paths, mock_scan, mock_log):
        """Branches with the same status are sorted alphabetically by name."""
        mock_paths.return_value = [
            {"name": "ZULU", "path": "/fake/zulu"},
            {"name": "ALPHA", "path": "/fake/alpha"},
            {"name": "MIKE", "path": "/fake/mike"},
        ]
        mock_scan.return_value = _make_activity(code_files=[], memory_files=[])
        results = detect_red_flags(since_timestamp=datetime(2026, 3, 1))
        names = [r["branch_name"] for r in results]
        assert names == ["ALPHA", "MIKE", "ZULU"]


# =============================================
# get_red_flag_summary TESTS
# =============================================

class TestGetRedFlagSummary:
    """Tests for the get_red_flag_summary aggregation function."""

    @patch(MOCK_PATCH_JSON_LOG)
    @patch(MOCK_PATCH_ACTIVITY)
    @patch(MOCK_PATCH_BRANCHES)
    def test_mixed_status_counts(self, mock_paths, mock_scan, mock_log):
        """Verify counts with a mix of RED_FLAG, OK, and NO_ACTIVITY branches."""
        mock_paths.return_value = [
            {"name": "RED_ONE", "path": "/fake/red1"},
            {"name": "OK_ONE", "path": "/fake/ok1"},
            {"name": "IDLE_ONE", "path": "/fake/idle1"},
            {"name": "RED_TWO", "path": "/fake/red2"},
        ]

        def side_effect(name, path, since):
            if name.startswith("RED"):
                return _make_activity(
                    branch_name=name,
                    code_files=[{"path": "/f.py", "name": "f.py", "mtime": "2026-03-20T10:00:00"}],
                    memory_files=[],
                )
            if name.startswith("OK"):
                return _make_activity(
                    branch_name=name,
                    code_files=[{"path": "/f.py", "name": "f.py", "mtime": "2026-03-20T10:00:00"}],
                    memory_files=[{"path": "/m.json", "name": "local.json", "mtime": "2026-03-20T12:00:00"}],
                )
            return _make_activity(branch_name=name, code_files=[], memory_files=[])

        mock_scan.side_effect = side_effect
        summary = get_red_flag_summary(since_timestamp=datetime(2026, 3, 1))

        assert summary["total_branches"] == 4
        assert summary["red_flags"] == 2
        assert summary["ok"] == 1
        assert summary["no_activity"] == 1

    @patch(MOCK_PATCH_JSON_LOG)
    @patch(MOCK_PATCH_ACTIVITY)
    @patch(MOCK_PATCH_BRANCHES)
    def test_empty_branch_list_zero_counts(self, mock_paths, mock_scan, mock_log):
        """Empty branch list yields zero counts across the board."""
        mock_paths.return_value = []
        summary = get_red_flag_summary(since_timestamp=datetime(2026, 3, 1))

        assert summary["total_branches"] == 0
        assert summary["red_flags"] == 0
        assert summary["ok"] == 0
        assert summary["no_activity"] == 0
        assert summary["violations"] == []

    @patch(MOCK_PATCH_JSON_LOG)
    @patch(MOCK_PATCH_ACTIVITY)
    @patch(MOCK_PATCH_BRANCHES)
    def test_violations_only_contains_red_flag(self, mock_paths, mock_scan, mock_log):
        """The violations list should only contain RED_FLAG branches."""
        mock_paths.return_value = [
            {"name": "BAD", "path": "/fake/bad"},
            {"name": "GOOD", "path": "/fake/good"},
            {"name": "IDLE", "path": "/fake/idle"},
        ]

        def side_effect(name, path, since):
            if name == "BAD":
                return _make_activity(
                    branch_name="BAD",
                    code_files=[{"path": "/f.py", "name": "f.py", "mtime": "2026-03-20T10:00:00"}],
                    memory_files=[],
                )
            if name == "GOOD":
                return _make_activity(
                    branch_name="GOOD",
                    code_files=[{"path": "/f.py", "name": "f.py", "mtime": "2026-03-20T10:00:00"}],
                    memory_files=[{"path": "/m.json", "name": "local.json", "mtime": "2026-03-20T12:00:00"}],
                )
            return _make_activity(branch_name="IDLE", code_files=[], memory_files=[])

        mock_scan.side_effect = side_effect
        summary = get_red_flag_summary(since_timestamp=datetime(2026, 3, 1))

        assert len(summary["violations"]) == 1
        assert all(v["status"] == STATUS_RED_FLAG for v in summary["violations"])
        assert summary["violations"][0]["branch_name"] == "BAD"

    @patch(MOCK_PATCH_JSON_LOG)
    @patch(MOCK_PATCH_ACTIVITY)
    @patch(MOCK_PATCH_BRANCHES)
    def test_summary_has_expected_keys(self, mock_paths, mock_scan, mock_log):
        """Summary dict contains all documented keys."""
        mock_paths.return_value = []
        summary = get_red_flag_summary(since_timestamp=datetime(2026, 3, 1))

        expected_keys = {
            "total_branches", "red_flags", "ok", "no_activity",
            "violations", "scan_time", "threshold_hours",
            "time_window_hours", "errors", "all_branches",
        }
        assert expected_keys.issubset(set(summary.keys()))

    @patch(MOCK_PATCH_JSON_LOG)
    @patch(MOCK_PATCH_ACTIVITY)
    @patch(MOCK_PATCH_BRANCHES)
    def test_all_branches_matches_total(self, mock_paths, mock_scan, mock_log):
        """The all_branches list length should match total_branches count."""
        mock_paths.return_value = [
            {"name": "A", "path": "/fake/a"},
            {"name": "B", "path": "/fake/b"},
            {"name": "C", "path": "/fake/c"},
        ]
        mock_scan.return_value = _make_activity(code_files=[], memory_files=[])
        summary = get_red_flag_summary(since_timestamp=datetime(2026, 3, 1))

        assert len(summary["all_branches"]) == summary["total_branches"]
        assert summary["total_branches"] == 3
