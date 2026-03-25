"""Tests for backup_timestamps — last-run tracking for backup modes."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock


def _import_timestamps():
    """Import the timestamps module after autouse fixture has mocked prax."""
    import aipass.backup.apps.handlers.utils.backup_timestamps as mod
    return mod


class TestGetTimestamps:
    """get_timestamps reads mode timestamps from disk."""

    def test_get_timestamps_returns_dict(self, tmp_path):
        """Returns a dict keyed by every known backup mode."""
        ts_mod = _import_timestamps()

        ts_file = tmp_path / "backup_timestamps.json"
        ts_file.write_text(json.dumps({"snapshot": "2026-03-01T10:00:00"}), encoding="utf-8")

        with (
            patch.object(ts_mod, "json_handler", MagicMock()),
            patch.object(ts_mod, "TIMESTAMPS_FILE", ts_file),
        ):
            result = ts_mod.get_timestamps()

            assert isinstance(result, dict)
            for mode in ts_mod.MODES:
                assert mode in result
            assert result["snapshot"] == "2026-03-01T10:00:00"

    def test_get_timestamps_missing_file(self, tmp_path):
        """Returns None for every mode when timestamps file does not exist."""
        ts_mod = _import_timestamps()

        ts_file = tmp_path / "nonexistent.json"

        with (
            patch.object(ts_mod, "json_handler", MagicMock()),
            patch.object(ts_mod, "TIMESTAMPS_FILE", ts_file),
        ):
            result = ts_mod.get_timestamps()

            for mode in ts_mod.MODES:
                assert result[mode] is None


class TestUpdateTimestamp:
    """update_timestamp writes ISO timestamps to disk."""

    def test_update_timestamp_creates_file(self, tmp_path):
        """Creates the timestamps file and writes an ISO timestamp for the given mode."""
        ts_mod = _import_timestamps()

        ts_file = tmp_path / "sub" / "backup_timestamps.json"

        with (
            patch.object(ts_mod, "json_handler", MagicMock()),
            patch.object(ts_mod, "TIMESTAMPS_FILE", ts_file),
        ):
            ts_mod.update_timestamp("snapshot")

            assert ts_file.exists()
            data = json.loads(ts_file.read_text(encoding="utf-8"))
            assert "snapshot" in data
            # Verify it is a valid ISO timestamp
            parsed = datetime.fromisoformat(data["snapshot"])
            assert isinstance(parsed, datetime)

    def test_update_timestamp_updates_existing(self, tmp_path):
        """Updates one mode without clobbering other modes already on disk."""
        ts_mod = _import_timestamps()

        ts_file = tmp_path / "backup_timestamps.json"
        existing = {"versioned": "2026-01-15T08:30:00"}
        ts_file.write_text(json.dumps(existing), encoding="utf-8")

        with (
            patch.object(ts_mod, "json_handler", MagicMock()),
            patch.object(ts_mod, "TIMESTAMPS_FILE", ts_file),
        ):
            ts_mod.update_timestamp("snapshot")

            data = json.loads(ts_file.read_text(encoding="utf-8"))
            assert "snapshot" in data
            assert data["versioned"] == "2026-01-15T08:30:00"


class TestFormatAge:
    """format_age converts ISO timestamps to human-readable relative strings."""

    def test_format_age_never(self):
        """Returns 'never' when input is None."""
        ts_mod = _import_timestamps()
        assert ts_mod.format_age(None) == "never"

    def test_format_age_just_now(self):
        """Returns 'just now' for a timestamp less than 60 seconds old."""
        ts_mod = _import_timestamps()

        recent = (datetime.now() - timedelta(seconds=10)).isoformat()
        assert ts_mod.format_age(recent) == "just now"

    def test_format_age_minutes(self):
        """Returns 'X mins ago' for timestamps minutes old."""
        ts_mod = _import_timestamps()

        five_min_ago = (datetime.now() - timedelta(minutes=5)).isoformat()
        result = ts_mod.format_age(five_min_ago)
        assert "mins ago" in result
        assert result == "5 mins ago"

    def test_format_age_hours(self):
        """Returns 'X hours ago' for timestamps hours old."""
        ts_mod = _import_timestamps()

        three_hours_ago = (datetime.now() - timedelta(hours=3)).isoformat()
        result = ts_mod.format_age(three_hours_ago)
        assert "hours ago" in result
        assert result == "3 hours ago"

    def test_format_age_days(self):
        """Returns 'X days ago' for timestamps days old."""
        ts_mod = _import_timestamps()

        two_days_ago = (datetime.now() - timedelta(days=2)).isoformat()
        result = ts_mod.format_age(two_days_ago)
        assert "days ago" in result
        assert result == "2 days ago"

    def test_format_age_empty_string(self):
        """Returns 'never' for an empty string (falsy but not None)."""
        ts_mod = _import_timestamps()
        assert ts_mod.format_age("") == "never"

    def test_format_age_unknown(self):
        """Returns 'unknown' for an unparseable input string."""
        ts_mod = _import_timestamps()
        assert ts_mod.format_age("not-a-date") == "unknown"
