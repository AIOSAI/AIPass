# =================== AIPass ====================
# Name: test_central.py
# Description: Tests for central file reader handler
# Version: 1.2.0
# Created: 2026-04-03
# Modified: 2026-09-29
# =============================================

"""Tests for apps/handlers/central/reader.py."""

# read_all_centrals().
# Covers: valid central files, empty directory, missing directory,
# malformed JSON, mixed valid/invalid files, service name derivation.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(json_structure) — the shape of read_all_centrals' log_operation record, covered by that row

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aipass.prax.apps.handlers.central import reader

# =============================================
# FIXTURES
# =============================================


@pytest.fixture(autouse=True)
def central_world(monkeypatch, tmp_path):
    """Every edge of reader.py, replaced where reader binds it.

    The repo root is tmp_path, so .ai_central is the test's own. The logger and
    json_handler are recorders, so no line reaches a live log or prax_json, and
    AIPASS_TEST_LOG_DIR points at tmp_path for anything that still writes.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(reader, "_find_repo_root", lambda: tmp_path)
    world = SimpleNamespace(logger=MagicMock(), json_handler=MagicMock())
    monkeypatch.setattr(reader, "logger", world.logger)
    monkeypatch.setattr(reader, "json_handler", world.json_handler)
    return world


# =============================================
# TESTS: read_all_centrals
# =============================================


class TestReadAllCentrals:
    """Tests for read_all_centrals()."""

    def test_returns_dict(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()
        payload = {"status": "active"}
        (central_dir / "AI_MAIL.central.json").write_text(json.dumps(payload), encoding="utf-8")

        result = reader.read_all_centrals()
        assert isinstance(result, dict)
        # Which dict: the whole mapping, not just a key spot-check -- one
        # entry in, one entry out, keyed by the lowered service name.
        assert result == {"ai_mail": payload}

    def test_empty_dict_when_dir_missing(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """No .ai_central directory should return empty dict."""
        # Do NOT create .ai_central
        result = reader.read_all_centrals()
        assert result == {}

    def test_empty_dict_when_dir_empty(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Empty .ai_central directory should return empty dict."""
        (tmp_path / ".ai_central").mkdir()
        result = reader.read_all_centrals()
        assert result == {}

    def test_reads_single_central_file(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """A single valid .central.json should be returned keyed by lowered service name."""
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()

        payload = {"status": "active", "version": "1.0.0"}
        (central_dir / "AI_MAIL.central.json").write_text(json.dumps(payload), encoding="utf-8")

        result = reader.read_all_centrals()
        assert "ai_mail" in result
        assert result["ai_mail"] == payload

    def test_reads_multiple_central_files(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Multiple central files should all appear in the result."""
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()

        services = {
            "AI_MAIL": {"type": "mail", "count": 5},
            "PLANS": {"type": "planner", "active": True},
            "DEVPULSE": {"type": "monitor", "uptime": 99.9},
        }
        for name, data in services.items():
            (central_dir / f"{name}.central.json").write_text(json.dumps(data), encoding="utf-8")

        result = reader.read_all_centrals()
        assert len(result) == 3
        assert result["ai_mail"] == services["AI_MAIL"]
        assert result["plans"] == services["PLANS"]
        assert result["devpulse"] == services["DEVPULSE"]

    def test_service_name_lowercased(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Service name key should be the filename stem lowercased."""
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()

        (central_dir / "MyService.central.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

        result = reader.read_all_centrals()
        assert "myservice" in result
        assert "MyService" not in result

    def test_skips_malformed_json(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Malformed JSON file should be skipped, not crash."""
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()

        (central_dir / "BAD.central.json").write_text("{not valid json!!", encoding="utf-8")

        result = reader.read_all_centrals()
        assert "bad" not in result
        assert result == {}

    def test_malformed_file_does_not_block_valid_files(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """A broken file should not prevent other valid files from loading."""
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()

        good_data = {"healthy": True}
        (central_dir / "GOOD.central.json").write_text(json.dumps(good_data), encoding="utf-8")
        (central_dir / "BAD.central.json").write_text("<<<broken>>>", encoding="utf-8")

        result = reader.read_all_centrals()
        assert len(result) == 1
        assert result["good"] == good_data
        assert "bad" not in result

    def test_ignores_non_central_json_files(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Files not matching *.central.json pattern should be ignored."""
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()

        # A valid central file
        (central_dir / "VALID.central.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
        # Files that should NOT be picked up
        (central_dir / "notes.txt").write_text("just a note", encoding="utf-8")
        (central_dir / "config.json").write_text(json.dumps({"nope": True}), encoding="utf-8")

        result = reader.read_all_centrals()
        assert len(result) == 1
        assert "valid" in result

    def test_logs_warning_on_malformed_json(self, central_world, tmp_path):
        """Should call logger.warning when a file has bad JSON, naming the file.

        Mutant: dropping central_file.name from the warning's arguments reddens this.
        """
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()

        (central_dir / "BROKEN.central.json").write_text("not json", encoding="utf-8")

        reader.read_all_centrals()
        central_world.logger.warning.assert_called_once()
        assert central_world.logger.warning.call_args.args[1] == "BROKEN.central.json"

    def test_calls_json_handler_log_operation(self, central_world, tmp_path):
        """Should log the operation via json_handler after reading."""
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()

        (central_dir / "SVC.central.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

        reader.read_all_centrals()
        central_world.json_handler.log_operation.assert_called_once_with("central_data_read", {"services_found": 1})

    def test_empty_json_object_is_valid(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """An empty JSON object {} is still valid and should be included."""
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()

        (central_dir / "EMPTY.central.json").write_text(json.dumps({}), encoding="utf-8")

        result = reader.read_all_centrals()
        assert "empty" in result
        assert result["empty"] == {}

    def test_nested_json_structure_preserved(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Deeply nested JSON data should be preserved as-is."""
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()

        nested = {"level1": {"level2": {"items": [1, 2, 3], "flag": True}}}
        (central_dir / "NESTED.central.json").write_text(json.dumps(nested), encoding="utf-8")

        result = reader.read_all_centrals()
        assert result["nested"] == nested
        assert result["nested"]["level1"]["level2"]["items"] == [1, 2, 3]

    def test_no_json_handler_call_when_dir_missing(self, central_world):
        """When directory is missing, should return early without calling json_handler."""
        # No .ai_central directory
        reader.read_all_centrals()
        central_world.json_handler.log_operation.assert_not_called()
