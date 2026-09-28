# =================== AIPass ====================
# Name: test_cleanup.py
# Description: Tests for usage data cleanup handler
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-09-28
# =============================================

"""Tests for apps/handlers/usage/cleanup.py, the usage data retention handler."""

# Tests for cleanup.py -- usage data retention and cleanup handler.
#
# Tests:
# - _read_json() file exists, file missing, invalid JSON
# - _write_json() success, parent dir creation, write failure
# - cleanup_old_data() no file, no old entries, entries cleaned, retention period
# - _identify_old_generations() valid timestamps, no timestamp, invalid timestamp, mixed

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — DEFAULT_RETENTION_DAYS's value; the retention tests pass retention_days
# seedgo: no-test-needed(json_handler) — the json_handler.log_operation() audit line cleanup writes

import json
from datetime import datetime, timedelta
from pathlib import Path
import pytest

from aipass.api.apps.handlers.usage.cleanup import (  # seedgo test_coverage detection
    _read_json,
    _write_json,
    cleanup_old_data,
    _identify_old_generations,
)

_CLEANUP_MOD = "aipass.api.apps.handlers.usage.cleanup"


# =============================================
# _read_json tests
# =============================================


class TestReadJson:
    """Tests for _read_json()."""

    def test_file_exists(self, tmp_path: Path):
        """Returns parsed dict when file exists and contains valid JSON."""
        file_path = tmp_path / "data.json"
        data = {"key": "value", "count": 42}
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        result = _read_json(file_path)

        assert result == data

    def test_file_missing(self, tmp_path: Path):
        """Returns None when file does not exist."""
        file_path = tmp_path / "nonexistent.json"

        result = _read_json(file_path)

        assert result is None

    def test_invalid_json(self, tmp_path: Path):
        """Raises when the file does not parse: None is the absent file's answer (api, fleet green leg 3)."""
        file_path = tmp_path / "bad.json"
        file_path.write_text("not valid json {{{", encoding="utf-8")

        with pytest.raises(ValueError):
            _read_json(file_path)


# =============================================
# _write_json tests
# =============================================


class TestWriteJson:
    """Tests for _write_json()."""

    def test_success(self, tmp_path: Path):
        """Returns True and writes valid JSON to file."""
        file_path = tmp_path / "output.json"
        data = {"written": True, "items": [1, 2, 3]}

        result = _write_json(file_path, data)

        assert result is True
        with open(file_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == data

    def test_parent_dir_creation(self, tmp_path: Path):
        """Creates parent directories when they do not exist."""
        file_path = tmp_path / "nested" / "deep" / "output.json"
        data = {"nested": True}

        result = _write_json(file_path, data)

        assert result is True
        assert file_path.exists()
        with open(file_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == data

    def test_write_failure(self, tmp_path: Path):
        """Raises when the write fails, so no caller reports a cleanup that never landed (api, fleet green leg 3).

        The target is a directory; the platform is asked which error that write raises.
        """
        file_path = tmp_path / "fail.json"
        file_path.mkdir()
        with pytest.raises(OSError) as platform:
            file_path.open("w", encoding="utf-8")

        with pytest.raises(type(platform.value)):
            _write_json(file_path, {"data": True})


# =============================================
# cleanup_old_data tests
# =============================================


class TestCleanupOldData:
    """Tests for cleanup_old_data()."""

    def test_no_file(self, tmp_path: Path):
        """Returns 0 when data file does not exist."""
        file_path = tmp_path / "missing.json"

        result = cleanup_old_data(file_path)

        assert result == 0

    def test_a_store_that_does_not_parse_raises_and_is_left_alone(self, tmp_path: Path):
        """0 means 'nothing to clean', so a store that does not parse raises instead (api, fleet green leg 3)."""
        file_path = tmp_path / "usage.json"
        file_path.write_text("{truncated", encoding="utf-8")

        with pytest.raises(ValueError):
            cleanup_old_data(file_path)

        assert file_path.read_text(encoding="utf-8") == "{truncated"

    def test_no_old_entries(self, tmp_path: Path):
        """Returns 0 when all generation entries are within retention period."""
        now = datetime.now()
        data = {
            "data": {
                "generation_tracking": {
                    "gen-1": {"timestamp": now.isoformat()},
                    "gen-2": {"timestamp": (now - timedelta(days=5)).isoformat()},
                }
            }
        }
        file_path = tmp_path / "usage.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        result = cleanup_old_data(file_path, retention_days=30)

        assert result == 0

    def test_entries_cleaned(self, tmp_path: Path):
        """Removes generation entries older than retention period."""
        now = datetime.now()
        data = {
            "data": {
                "generation_tracking": {
                    "gen-old": {"timestamp": (now - timedelta(days=60)).isoformat()},
                    "gen-recent": {"timestamp": now.isoformat()},
                }
            }
        }
        file_path = tmp_path / "usage.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        result = cleanup_old_data(file_path, retention_days=30)

        assert result == 1
        with open(file_path, "r", encoding="utf-8") as f:
            updated = json.load(f)
        tracking = updated["data"]["generation_tracking"]
        assert "gen-old" not in tracking
        assert "gen-recent" in tracking

    def test_retention_period_respected(self, tmp_path: Path):
        """Uses custom retention_days to determine cutoff."""
        now = datetime.now()
        data = {
            "data": {
                "generation_tracking": {
                    "gen-10d": {"timestamp": (now - timedelta(days=10)).isoformat()},
                    "gen-3d": {"timestamp": (now - timedelta(days=3)).isoformat()},
                }
            }
        }
        file_path = tmp_path / "usage.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        result = cleanup_old_data(file_path, retention_days=7)

        assert result == 1
        with open(file_path, "r", encoding="utf-8") as f:
            updated = json.load(f)
        tracking = updated["data"]["generation_tracking"]
        assert "gen-10d" not in tracking
        assert "gen-3d" in tracking


# =============================================
# _identify_old_generations tests
# =============================================


class TestIdentifyOldGenerations:
    """Tests for _identify_old_generations()."""

    def test_entries_with_valid_timestamps(self):
        """Identifies entries older than cutoff date."""
        cutoff = datetime(2026, 5, 1)
        tracking = {
            "gen-old": {"timestamp": "2026-04-15T12:00:00"},
            "gen-new": {"timestamp": "2026-05-10T12:00:00"},
        }

        result = _identify_old_generations(tracking, cutoff)

        assert "gen-old" in result
        assert "gen-new" not in result

    def test_no_timestamp(self):
        """Marks entries without timestamp for cleanup."""
        cutoff = datetime(2026, 5, 1)
        tracking = {
            "gen-none": {"caller": "test"},
            "gen-empty": {"timestamp": None},
        }

        result = _identify_old_generations(tracking, cutoff)

        assert "gen-none" in result
        assert "gen-empty" in result

    def test_invalid_timestamp(self):
        """Marks entries with invalid timestamp for cleanup."""
        cutoff = datetime(2026, 5, 1)
        tracking = {
            "gen-bad": {"timestamp": "not-a-date"},
        }

        result = _identify_old_generations(tracking, cutoff)

        assert "gen-bad" in result

    def test_mixed_entries(self):
        """Handles mix of valid old, valid new, missing, and invalid timestamps."""
        cutoff = datetime(2026, 5, 1)
        tracking = {
            "gen-old": {"timestamp": "2026-03-01T00:00:00"},
            "gen-new": {"timestamp": "2026-05-10T00:00:00"},
            "gen-no-ts": {"caller": "x"},
            "gen-bad-ts": {"timestamp": "garbage"},
        }

        result = _identify_old_generations(tracking, cutoff)

        assert sorted(result) == ["gen-bad-ts", "gen-no-ts", "gen-old"]
        assert "gen-new" not in result
