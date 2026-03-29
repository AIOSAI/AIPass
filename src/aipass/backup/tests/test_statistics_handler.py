"""Tests for statistics_handler — backup statistics tracking."""

from unittest.mock import MagicMock


def _empty_data() -> dict:
    """Return a minimal valid data structure matching what load_json would return."""
    return {
        "last_updated": "2026-01-01T00:00:00",
        "runtime_state": {},
        "statistics": {
            "total_backups": 0,
            "successful_backups": 0,
            "failed_backups": 0,
            "snapshot_backups": 0,
            "versioned_backups": 0,
            "total_files_processed": 0,
        },
        "recent_backups": [],
    }


class TestUpdateDataFile:
    """update_data_file persists backup statistics via load_json / save_json."""

    def test_updates_runtime_state_on_success(self, monkeypatch):
        """Runtime state reflects a successful backup."""
        import aipass.backup.apps.handlers.json.statistics_handler as sh

        result = MagicMock()
        result.success = True
        result.mode = "snapshot"
        result.files_copied = 12
        result.files_checked = 20
        result.errors = 0

        captured: dict = {}

        def fake_save(_module: str, _json_type: str, data: dict) -> bool:
            captured.update(data)
            return True

        monkeypatch.setattr(sh, "load_json", lambda *_a, **_kw: _empty_data())
        monkeypatch.setattr(sh, "save_json", fake_save)

        sh.update_data_file(result)

        assert captured["runtime_state"]["current_status"] == "completed"
        assert captured["runtime_state"]["active_mode"] == "snapshot"
        assert captured["runtime_state"]["total_files_backed_up"] == 12
        assert captured["runtime_state"]["backup_in_progress"] is False

    def test_updates_runtime_state_on_failure(self, monkeypatch):
        """Runtime state reflects a failed backup."""
        import aipass.backup.apps.handlers.json.statistics_handler as sh

        result = MagicMock()
        result.success = False
        result.mode = "versioned"
        result.files_copied = 0
        result.files_checked = 5
        result.errors = 3

        captured: dict = {}

        def fake_save(_module: str, _json_type: str, data: dict) -> bool:
            captured.update(data)
            return True

        monkeypatch.setattr(sh, "load_json", lambda *_a, **_kw: _empty_data())
        monkeypatch.setattr(sh, "save_json", fake_save)

        sh.update_data_file(result)

        assert captured["runtime_state"]["current_status"] == "failed"
        assert captured["statistics"]["failed_backups"] == 1
        assert captured["statistics"]["successful_backups"] == 0

    def test_increments_statistics_counters(self, monkeypatch):
        """Total, successful, and mode-specific counters increment correctly."""
        import aipass.backup.apps.handlers.json.statistics_handler as sh

        result = MagicMock()
        result.success = True
        result.mode = "versioned"
        result.files_copied = 3
        result.files_checked = 10
        result.errors = 0

        existing_data = {
            "last_updated": "2026-01-01",
            "runtime_state": {},
            "statistics": {
                "total_backups": 5,
                "successful_backups": 4,
                "failed_backups": 1,
                "snapshot_backups": 3,
                "versioned_backups": 2,
                "total_files_processed": 100,
            },
            "recent_backups": [],
        }

        captured: dict = {}

        def fake_save(_module: str, _json_type: str, data: dict) -> bool:
            captured.update(data)
            return True

        monkeypatch.setattr(sh, "load_json", lambda *_a, **_kw: existing_data)
        monkeypatch.setattr(sh, "save_json", fake_save)

        sh.update_data_file(result)

        assert captured["statistics"]["total_backups"] == 6
        assert captured["statistics"]["successful_backups"] == 5
        assert captured["statistics"]["versioned_backups"] == 3
        assert captured["statistics"]["total_files_processed"] == 110

    def test_snapshot_mode_counter(self, monkeypatch):
        """Snapshot mode increments snapshot_backups counter."""
        import aipass.backup.apps.handlers.json.statistics_handler as sh

        result = MagicMock()
        result.success = True
        result.mode = "snapshot"
        result.files_copied = 1
        result.files_checked = 1
        result.errors = 0

        captured: dict = {}

        def fake_save(_module: str, _json_type: str, data: dict) -> bool:
            captured.update(data)
            return True

        monkeypatch.setattr(sh, "load_json", lambda *_a, **_kw: _empty_data())
        monkeypatch.setattr(sh, "save_json", fake_save)

        sh.update_data_file(result)

        assert captured["statistics"]["snapshot_backups"] == 1
        assert captured["statistics"]["versioned_backups"] == 0

    def test_recent_backups_capped_at_ten(self, monkeypatch):
        """Recent backups list never exceeds 10 entries."""
        import aipass.backup.apps.handlers.json.statistics_handler as sh

        result = MagicMock()
        result.success = True
        result.mode = "snapshot"
        result.files_copied = 1
        result.files_checked = 1
        result.errors = 0

        existing_data = {
            "last_updated": "2026-01-01",
            "runtime_state": {},
            "statistics": {
                "total_backups": 10,
                "successful_backups": 10,
                "failed_backups": 0,
                "snapshot_backups": 10,
                "versioned_backups": 0,
                "total_files_processed": 50,
            },
            "recent_backups": [{"idx": i} for i in range(10)],
        }

        captured: dict = {}

        def fake_save(_module: str, _json_type: str, data: dict) -> bool:
            captured.update(data)
            return True

        monkeypatch.setattr(sh, "load_json", lambda *_a, **_kw: existing_data)
        monkeypatch.setattr(sh, "save_json", fake_save)

        sh.update_data_file(result)

        assert len(captured["recent_backups"]) == 10

    def test_handles_exception_gracefully(self, monkeypatch):
        """Does not raise when load_json throws; logs the error instead."""
        import aipass.backup.apps.handlers.json.statistics_handler as sh

        result = MagicMock()
        result.success = True
        result.mode = "snapshot"
        result.files_copied = 0
        result.files_checked = 0
        result.errors = 0

        mock_print = MagicMock()
        monkeypatch.setattr(sh, "load_json", MagicMock(side_effect=RuntimeError("boom")))
        monkeypatch.setattr(sh, "safe_print", mock_print)

        # Should not raise
        sh.update_data_file(result)

        mock_print.assert_called_once()
        assert "boom" in mock_print.call_args[0][0]
