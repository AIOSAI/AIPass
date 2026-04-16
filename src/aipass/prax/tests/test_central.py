# =================== AIPass ====================
# Name: test_central.py
# Description: Tests for central file reader handler
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""Tests for apps/handlers/central/reader.py -- read_all_centrals().

Covers: valid central files, empty directory, missing directory,
malformed JSON, mixed valid/invalid files, service name derivation.
"""

import json
import sys


# =============================================
# HELPERS
# =============================================


def _fresh_import_reader(monkeypatch, tmp_path):
    """Import reader module with a fresh state, patching _find_repo_root to tmp_path.

    Evicts cached modules so the module-level logger and json_handler
    pick up the mocked sys.modules entries from conftest.
    """
    for key in list(sys.modules.keys()):
        if "aipass.prax.apps.handlers.central" in key:
            sys.modules.pop(key, None)

    import aipass.prax.apps.handlers.central.reader as reader_mod

    # Patch _find_repo_root so it returns tmp_path (our fake repo root)
    monkeypatch.setattr(reader_mod, "_find_repo_root", lambda: tmp_path)

    return reader_mod


# =============================================
# TESTS: read_all_centrals
# =============================================


class TestReadAllCentrals:
    """Tests for read_all_centrals()."""

    def test_returns_dict(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        reader = _fresh_import_reader(monkeypatch, tmp_path)
        result = reader.read_all_centrals()
        assert isinstance(result, dict)

    def test_empty_dict_when_dir_missing(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """No .ai_central directory should return empty dict."""
        reader = _fresh_import_reader(monkeypatch, tmp_path)
        # Do NOT create .ai_central
        result = reader.read_all_centrals()
        assert result == {}

    def test_empty_dict_when_dir_empty(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Empty .ai_central directory should return empty dict."""
        reader = _fresh_import_reader(monkeypatch, tmp_path)
        (tmp_path / ".ai_central").mkdir()
        result = reader.read_all_centrals()
        assert result == {}

    def test_reads_single_central_file(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """A single valid .central.json should be returned keyed by lowered service name."""
        reader = _fresh_import_reader(monkeypatch, tmp_path)
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()

        payload = {"status": "active", "version": "1.0.0"}
        (central_dir / "AI_MAIL.central.json").write_text(json.dumps(payload), encoding="utf-8")

        result = reader.read_all_centrals()
        assert "ai_mail" in result
        assert result["ai_mail"] == payload

    def test_reads_multiple_central_files(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Multiple central files should all appear in the result."""
        reader = _fresh_import_reader(monkeypatch, tmp_path)
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
        reader = _fresh_import_reader(monkeypatch, tmp_path)
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()

        (central_dir / "MyService.central.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

        result = reader.read_all_centrals()
        assert "myservice" in result
        assert "MyService" not in result

    def test_skips_malformed_json(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Malformed JSON file should be skipped, not crash."""
        reader = _fresh_import_reader(monkeypatch, tmp_path)
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()

        (central_dir / "BAD.central.json").write_text("{not valid json!!", encoding="utf-8")

        result = reader.read_all_centrals()
        assert "bad" not in result
        assert result == {}

    def test_malformed_file_does_not_block_valid_files(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """A broken file should not prevent other valid files from loading."""
        reader = _fresh_import_reader(monkeypatch, tmp_path)
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
        reader = _fresh_import_reader(monkeypatch, tmp_path)
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

    def test_logs_warning_on_malformed_json(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Should call logger.warning when a file has bad JSON."""
        reader = _fresh_import_reader(monkeypatch, tmp_path)
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()

        (central_dir / "BROKEN.central.json").write_text("not json", encoding="utf-8")

        reader.read_all_centrals()
        reader.logger.warning.assert_called()  # type: ignore[union-attr]

    def test_calls_json_handler_log_operation(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Should log the operation via json_handler after reading."""
        reader = _fresh_import_reader(monkeypatch, tmp_path)
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()

        (central_dir / "SVC.central.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

        reader.read_all_centrals()
        reader.json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "central_data_read", {"services_found": 1}
        )

    def test_empty_json_object_is_valid(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """An empty JSON object {} is still valid and should be included."""
        reader = _fresh_import_reader(monkeypatch, tmp_path)
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()

        (central_dir / "EMPTY.central.json").write_text(json.dumps({}), encoding="utf-8")

        result = reader.read_all_centrals()
        assert "empty" in result
        assert result["empty"] == {}

    def test_nested_json_structure_preserved(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Deeply nested JSON data should be preserved as-is."""
        reader = _fresh_import_reader(monkeypatch, tmp_path)
        central_dir = tmp_path / ".ai_central"
        central_dir.mkdir()

        nested = {"level1": {"level2": {"items": [1, 2, 3], "flag": True}}}
        (central_dir / "NESTED.central.json").write_text(json.dumps(nested), encoding="utf-8")

        result = reader.read_all_centrals()
        assert result["nested"] == nested
        assert result["nested"]["level1"]["level2"]["items"] == [1, 2, 3]

    def test_no_json_handler_call_when_dir_missing(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """When directory is missing, should return early without calling json_handler."""
        reader = _fresh_import_reader(monkeypatch, tmp_path)
        # No .ai_central directory
        reader.read_all_centrals()
        reader.json_handler.log_operation.assert_not_called()  # type: ignore[union-attr]
