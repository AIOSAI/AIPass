"""Tests for drive_sync_json handler."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestAtomicJsonWrite:
    """Tests for atomic_json_write function."""

    def test_writes_valid_json(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import atomic_json_write

        test_file = tmp_path / "test.json"
        atomic_json_write(test_file, {"key": "value"})
        assert json.loads(test_file.read_text(encoding="utf-8")) == {"key": "value"}

    def test_writes_list_data(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import atomic_json_write

        test_file = tmp_path / "list.json"
        atomic_json_write(test_file, [1, 2, 3])
        assert json.loads(test_file.read_text(encoding="utf-8")) == [1, 2, 3]

    def test_overwrites_existing_file(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import atomic_json_write

        test_file = tmp_path / "overwrite.json"
        atomic_json_write(test_file, {"old": True})
        atomic_json_write(test_file, {"new": True})
        assert json.loads(test_file.read_text(encoding="utf-8")) == {"new": True}

    def test_writes_nested_structures(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import atomic_json_write

        test_file = tmp_path / "nested.json"
        data = {"a": {"b": {"c": [1, 2, {"d": "deep"}]}}}
        atomic_json_write(test_file, data)
        assert json.loads(test_file.read_text(encoding="utf-8")) == data

    def test_cleans_up_temp_on_failure(self, tmp_path, monkeypatch):
        from aipass.backup.apps.handlers.json.drive_sync_json import atomic_json_write
        import os

        test_file = tmp_path / "fail.json"
        # Patch os.replace to raise, simulating a failure after temp write
        monkeypatch.setattr(os, "replace", MagicMock(side_effect=OSError("replace failed")))

        with pytest.raises(OSError, match="replace failed"):
            atomic_json_write(test_file, {"key": "value"})

        # Temp file should have been cleaned up
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_writes_empty_dict(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import atomic_json_write

        test_file = tmp_path / "empty.json"
        atomic_json_write(test_file, {})
        assert json.loads(test_file.read_text(encoding="utf-8")) == {}


class TestSaveConfig:
    """Tests for save_config function."""

    def test_saves_config_to_file(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import save_config

        config_file = tmp_path / "config.json"
        config = {"setting_a": True, "setting_b": "hello"}
        save_config(config_file, config)
        assert json.loads(config_file.read_text(encoding="utf-8")) == config

    def test_creates_parent_directories(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import save_config

        config_file = tmp_path / "deep" / "nested" / "config.json"
        save_config(config_file, {"created": True})
        assert config_file.exists()
        assert json.loads(config_file.read_text(encoding="utf-8")) == {"created": True}

    def test_overwrites_existing_config(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import save_config

        config_file = tmp_path / "config.json"
        save_config(config_file, {"version": 1})
        save_config(config_file, {"version": 2})
        assert json.loads(config_file.read_text(encoding="utf-8")) == {"version": 2}


class TestSaveData:
    """Tests for save_data function."""

    def test_saves_data_with_last_updated(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import save_data

        data_file = tmp_path / "data.json"
        save_data(data_file, {"items": [1, 2, 3]})
        result = json.loads(data_file.read_text(encoding="utf-8"))
        assert result["items"] == [1, 2, 3]
        assert "last_updated" in result

    def test_creates_parent_directories(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import save_data

        data_file = tmp_path / "sub" / "dir" / "data.json"
        save_data(data_file, {"key": "val"})
        assert data_file.exists()

    def test_deepcopy_protects_original(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import save_data

        data_file = tmp_path / "data.json"
        original = {"nested": {"a": 1}}
        save_data(data_file, original)
        # Original should not have last_updated injected
        assert "last_updated" not in original

    def test_retries_on_deepcopy_failure(self, tmp_path, monkeypatch):
        from aipass.backup.apps.handlers.json import drive_sync_json
        import copy

        data_file = tmp_path / "data.json"
        call_count = 0
        original_deepcopy = copy.deepcopy

        def flaky_deepcopy(obj, memo=None):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("dictionary changed during copy")
            return original_deepcopy(obj, memo)

        monkeypatch.setattr(copy, "deepcopy", flaky_deepcopy)
        drive_sync_json.save_data(data_file, {"retry": True})
        result = json.loads(data_file.read_text(encoding="utf-8"))
        assert result["retry"] is True
        assert call_count == 3

    def test_raises_after_max_deepcopy_retries(self, tmp_path, monkeypatch):
        from aipass.backup.apps.handlers.json import drive_sync_json
        import copy

        data_file = tmp_path / "data.json"
        monkeypatch.setattr(
            copy, "deepcopy", MagicMock(side_effect=RuntimeError("always fails"))
        )
        # Patch time.sleep to avoid real delays
        monkeypatch.setattr("time.sleep", lambda _: None)
        with pytest.raises(RuntimeError, match="always fails"):
            drive_sync_json.save_data(data_file, {"fail": True})

    def test_last_updated_is_valid_iso_format(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import save_data
        from datetime import datetime

        data_file = tmp_path / "data.json"
        save_data(data_file, {"check": "timestamp"})
        result = json.loads(data_file.read_text(encoding="utf-8"))
        # Should parse without error
        datetime.fromisoformat(result["last_updated"])


class TestLoadLog:
    """Tests for load_log function."""

    def test_returns_default_when_file_missing(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import load_log

        log_file = tmp_path / "log.json"
        result = load_log(log_file)
        assert result["entries"] == []
        assert result["summary"]["total_entries"] == 0
        assert result["summary"]["last_entry"] is None
        assert result["summary"]["next_id"] == 1

    def test_creates_file_when_missing(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import load_log

        log_file = tmp_path / "log.json"
        load_log(log_file)
        assert log_file.exists()

    def test_loads_existing_log(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import load_log, save_log

        log_file = tmp_path / "log.json"
        log_data = {
            "entries": [{"id": 1, "message": "test"}],
            "summary": {"total_entries": 1, "last_entry": "2026-01-01", "next_id": 2},
        }
        save_log(log_file, log_data)
        result = load_log(log_file)
        assert result["entries"][0]["message"] == "test"
        assert result["summary"]["total_entries"] == 1

    def test_returns_default_on_empty_file(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import load_log

        log_file = tmp_path / "log.json"
        log_file.write_text("", encoding="utf-8")
        result = load_log(log_file)
        assert result["entries"] == []
        assert result["summary"]["next_id"] == 1

    def test_retries_on_json_decode_error(self, tmp_path, monkeypatch):
        from aipass.backup.apps.handlers.json import drive_sync_json

        log_file = tmp_path / "log.json"
        log_file.write_text("{invalid json", encoding="utf-8")
        # Patch time.sleep to avoid delays
        monkeypatch.setattr("time.sleep", lambda _: None)
        result = drive_sync_json.load_log(log_file, max_retries=3)
        # After all retries fail, should return default
        assert result["entries"] == []
        assert result["summary"]["total_entries"] == 0

    def test_returns_default_on_generic_exception(self, tmp_path, monkeypatch):
        from aipass.backup.apps.handlers.json import drive_sync_json

        log_file = tmp_path / "log.json"
        # Create valid file but make _read_json_locked raise
        log_file.write_text('{"entries": []}', encoding="utf-8")
        monkeypatch.setattr(
            drive_sync_json,
            "_read_json_locked",
            MagicMock(side_effect=PermissionError("no access")),
        )
        result = drive_sync_json.load_log(log_file)
        assert result["entries"] == []


class TestSaveLog:
    """Tests for save_log function."""

    def test_saves_log_data(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import save_log

        log_file = tmp_path / "log.json"
        log_data = {
            "entries": [{"id": 1, "op": "test"}],
            "summary": {"total_entries": 1, "last_entry": "now", "next_id": 2},
        }
        save_log(log_file, log_data)
        result = json.loads(log_file.read_text(encoding="utf-8"))
        assert result == log_data

    def test_creates_parent_directories(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import save_log

        log_file = tmp_path / "a" / "b" / "log.json"
        save_log(log_file, {"entries": [], "summary": {}})
        assert log_file.exists()

    def test_creates_lock_file(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import save_log

        log_file = tmp_path / "log.json"
        save_log(log_file, {"entries": []})
        lock_file = tmp_path / "log.lock"
        assert lock_file.exists()

    def test_overwrites_existing_log(self, tmp_path):
        from aipass.backup.apps.handlers.json.drive_sync_json import save_log

        log_file = tmp_path / "log.json"
        save_log(log_file, {"entries": [{"id": 1}], "summary": {"next_id": 2}})
        save_log(log_file, {"entries": [{"id": 1}, {"id": 2}], "summary": {"next_id": 3}})
        result = json.loads(log_file.read_text(encoding="utf-8"))
        assert len(result["entries"]) == 2
        assert result["summary"]["next_id"] == 3
