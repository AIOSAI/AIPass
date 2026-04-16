# =================== AIPass ====================
# Name: test_registry.py
# Description: Tests for registry load and save handlers
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""Tests for apps/handlers/registry/load.py and save.py.

Covers: load_module_registry (valid file, missing file, corrupt file,
missing modules key) and save_module_registry (writes valid JSON,
creates directory, round-trip with load, error handling).
"""

import json
import sys
from unittest.mock import MagicMock


# =============================================
# HELPERS
# =============================================


def _fresh_import_registry_load(monkeypatch, tmp_path):
    """Import registry load module with paths redirected to tmp_path."""
    for key in list(sys.modules.keys()):
        if "aipass.prax.apps.handlers.registry" in key:
            sys.modules.pop(key, None)

    import aipass.prax.apps.handlers.registry.load as load_mod

    prax_json_dir = tmp_path / "prax_json"
    prax_json_dir.mkdir(exist_ok=True)
    registry_file = prax_json_dir / "prax_registry.json"

    monkeypatch.setattr(load_mod, "PRAX_JSON_DIR", prax_json_dir)
    monkeypatch.setattr(load_mod, "REGISTRY_FILE", registry_file)

    # Replace stdlib logger with a MagicMock so tests can assert on calls
    mock_logger = MagicMock()
    monkeypatch.setattr(load_mod, "logger", mock_logger)

    return load_mod


def _fresh_import_registry_save(monkeypatch, tmp_path):
    """Import registry save module with paths redirected to tmp_path."""
    for key in list(sys.modules.keys()):
        if "aipass.prax.apps.handlers.registry" in key:
            sys.modules.pop(key, None)

    import aipass.prax.apps.handlers.registry.save as save_mod

    prax_json_dir = tmp_path / "prax_json"
    # Do NOT create the dir here -- save should create it itself
    registry_file = prax_json_dir / "prax_registry.json"

    monkeypatch.setattr(save_mod, "PRAX_JSON_DIR", prax_json_dir)
    monkeypatch.setattr(save_mod, "REGISTRY_FILE", registry_file)
    monkeypatch.setattr(save_mod, "ECOSYSTEM_ROOT", tmp_path / "ecosystem")

    # Replace stdlib logger with a MagicMock so tests can assert on calls
    mock_logger = MagicMock()
    monkeypatch.setattr(save_mod, "logger", mock_logger)

    return save_mod


# =============================================
# TESTS: load_module_registry
# =============================================


class TestLoadModuleRegistry:
    """Tests for load_module_registry()."""

    def test_returns_dict(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        load_mod = _fresh_import_registry_load(monkeypatch, tmp_path)
        result = load_mod.load_module_registry()
        assert isinstance(result, dict)

    def test_empty_dict_when_file_missing(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Missing registry file should return empty dict."""
        load_mod = _fresh_import_registry_load(monkeypatch, tmp_path)
        result = load_mod.load_module_registry()
        assert result == {}

    def test_loads_modules_from_valid_file(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Valid registry file should return the modules dict."""
        load_mod = _fresh_import_registry_load(monkeypatch, tmp_path)

        modules = {
            "prax": {"relative_path": "src/aipass/prax", "size": 1024},
            "flow": {"relative_path": "src/aipass/flow", "size": 2048},
        }
        registry = {
            "registry_version": "1.0.0",
            "timestamp": "2026-04-03T00:00:00+00:00",
            "modules": modules,
            "statistics": {"total_modules": 2},
        }
        load_mod.REGISTRY_FILE.write_text(json.dumps(registry), encoding="utf-8")

        result = load_mod.load_module_registry()
        assert len(result) == 2
        assert result["prax"]["relative_path"] == "src/aipass/prax"
        assert result["flow"]["size"] == 2048

    def test_empty_dict_on_corrupt_json(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Corrupt JSON should return empty dict, not raise."""
        load_mod = _fresh_import_registry_load(monkeypatch, tmp_path)
        load_mod.REGISTRY_FILE.write_text("<<<not json>>>", encoding="utf-8")

        result = load_mod.load_module_registry()
        assert result == {}

    def test_empty_dict_when_modules_key_missing(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Registry without 'modules' key should return empty dict."""
        load_mod = _fresh_import_registry_load(monkeypatch, tmp_path)
        load_mod.REGISTRY_FILE.write_text(json.dumps({"registry_version": "1.0.0"}), encoding="utf-8")

        result = load_mod.load_module_registry()
        assert result == {}

    def test_empty_modules_returns_empty_dict(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Registry with empty modules dict should return empty dict."""
        load_mod = _fresh_import_registry_load(monkeypatch, tmp_path)
        load_mod.REGISTRY_FILE.write_text(json.dumps({"modules": {}}), encoding="utf-8")

        result = load_mod.load_module_registry()
        assert result == {}

    def test_logs_operation_on_success(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Should call json_handler.log_operation on successful load."""
        load_mod = _fresh_import_registry_load(monkeypatch, tmp_path)

        registry = {
            "modules": {"mod_a": {"path": "a"}, "mod_b": {"path": "b"}},
        }
        load_mod.REGISTRY_FILE.write_text(json.dumps(registry), encoding="utf-8")

        load_mod.load_module_registry()
        load_mod.json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "registry_loaded", {"module_count": 2}
        )

    def test_logs_warning_on_corrupt_file(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Should log warning when file is corrupt."""
        load_mod = _fresh_import_registry_load(monkeypatch, tmp_path)
        load_mod.REGISTRY_FILE.write_text("broken!", encoding="utf-8")

        load_mod.load_module_registry()
        load_mod.logger.warning.assert_called()  # type: ignore[union-attr]


# =============================================
# TESTS: save_module_registry
# =============================================


class TestSaveModuleRegistry:
    """Tests for save_module_registry()."""

    def test_returns_true_on_success(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        save_mod = _fresh_import_registry_save(monkeypatch, tmp_path)
        result = save_mod.save_module_registry({"mod": {"path": "x"}})
        assert result is True

    def test_creates_directory_if_missing(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Should create prax_json directory if it doesn't exist."""
        save_mod = _fresh_import_registry_save(monkeypatch, tmp_path)
        prax_json_dir = save_mod.PRAX_JSON_DIR
        assert not prax_json_dir.exists()

        save_mod.save_module_registry({"mod": {"path": "x"}})
        assert prax_json_dir.exists()
        assert prax_json_dir.is_dir()

    def test_writes_valid_json(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Saved file should contain valid JSON."""
        save_mod = _fresh_import_registry_save(monkeypatch, tmp_path)
        modules = {"test_mod": {"relative_path": "test/mod.py", "size": 100}}

        save_mod.save_module_registry(modules)

        data = json.loads(save_mod.REGISTRY_FILE.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_saved_structure_has_required_keys(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Saved JSON should contain registry_version, timestamp, modules, statistics."""
        save_mod = _fresh_import_registry_save(monkeypatch, tmp_path)
        modules = {"alpha": {"relative_path": "src/alpha.py"}}

        save_mod.save_module_registry(modules)

        data = json.loads(save_mod.REGISTRY_FILE.read_text(encoding="utf-8"))
        assert "registry_version" in data
        assert "timestamp" in data
        assert "modules" in data
        assert "statistics" in data

    def test_saved_modules_match_input(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """The modules dict in the saved file should match what was passed in."""
        save_mod = _fresh_import_registry_save(monkeypatch, tmp_path)
        modules = {
            "alpha": {"relative_path": "src/alpha.py", "size": 500},
            "beta": {"relative_path": "src/beta.py", "size": 750},
        }

        save_mod.save_module_registry(modules)

        data = json.loads(save_mod.REGISTRY_FILE.read_text(encoding="utf-8"))
        assert data["modules"] == modules

    def test_statistics_total_modules(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Statistics should reflect the correct total_modules count."""
        save_mod = _fresh_import_registry_save(monkeypatch, tmp_path)
        modules = {f"mod_{i}": {"path": f"p{i}"} for i in range(5)}

        save_mod.save_module_registry(modules)

        data = json.loads(save_mod.REGISTRY_FILE.read_text(encoding="utf-8"))
        assert data["statistics"]["total_modules"] == 5

    def test_registry_version_is_string(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """registry_version should be a version string."""
        save_mod = _fresh_import_registry_save(monkeypatch, tmp_path)
        save_mod.save_module_registry({"x": {"p": "q"}})

        data = json.loads(save_mod.REGISTRY_FILE.read_text(encoding="utf-8"))
        assert data["registry_version"] == "1.0.0"

    def test_timestamp_is_iso_format(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Timestamp should be a valid ISO-format UTC string."""
        from datetime import datetime

        save_mod = _fresh_import_registry_save(monkeypatch, tmp_path)
        save_mod.save_module_registry({"x": {"p": "q"}})

        data = json.loads(save_mod.REGISTRY_FILE.read_text(encoding="utf-8"))
        # Should not raise on valid ISO format
        parsed = datetime.fromisoformat(data["timestamp"])
        assert parsed is not None

    def test_save_empty_modules(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Saving empty modules dict should succeed with total_modules=0."""
        save_mod = _fresh_import_registry_save(monkeypatch, tmp_path)
        result = save_mod.save_module_registry({})
        assert result is True

        data = json.loads(save_mod.REGISTRY_FILE.read_text(encoding="utf-8"))
        assert data["modules"] == {}
        assert data["statistics"]["total_modules"] == 0

    def test_returns_false_on_write_error(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Should return False when the file write fails."""
        save_mod = _fresh_import_registry_save(monkeypatch, tmp_path)

        # Make PRAX_JSON_DIR point to a path that will fail mkdir
        # by setting it to a file (not a directory)
        blocker = tmp_path / "blocker_file"
        blocker.write_text("I am a file", encoding="utf-8")
        monkeypatch.setattr(save_mod, "PRAX_JSON_DIR", blocker / "subdir")
        monkeypatch.setattr(save_mod, "REGISTRY_FILE", blocker / "subdir" / "reg.json")

        result = save_mod.save_module_registry({"x": {}})
        assert result is False

    def test_logs_operation_on_success(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Should call json_handler.log_operation after successful save."""
        save_mod = _fresh_import_registry_save(monkeypatch, tmp_path)
        modules = {"a": {"p": "1"}, "b": {"p": "2"}, "c": {"p": "3"}}

        save_mod.save_module_registry(modules)
        save_mod.json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "registry_saved", {"total_modules": 3}
        )

    def test_logs_error_on_failure(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Should log error when save fails."""
        save_mod = _fresh_import_registry_save(monkeypatch, tmp_path)

        blocker = tmp_path / "blocker_file"
        blocker.write_text("I am a file", encoding="utf-8")
        monkeypatch.setattr(save_mod, "PRAX_JSON_DIR", blocker / "subdir")
        monkeypatch.setattr(save_mod, "REGISTRY_FILE", blocker / "subdir" / "reg.json")

        save_mod.save_module_registry({"x": {}})
        save_mod.logger.error.assert_called()  # type: ignore[union-attr]


# =============================================
# TESTS: round-trip (save then load)
# =============================================


class TestRegistryRoundTrip:
    """Integration-style tests: save then load."""

    def test_round_trip_preserves_data(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Data saved by save_module_registry should be loadable by load_module_registry."""
        # Import both with the same tmp_path
        save_mod = _fresh_import_registry_save(monkeypatch, tmp_path)
        save_mod.save_module_registry(
            {
                "alpha": {"relative_path": "src/alpha.py", "size": 100},
                "beta": {"relative_path": "src/beta.py", "size": 200},
            }
        )

        # Now import load pointing at the same directory
        load_mod = _fresh_import_registry_load(monkeypatch, tmp_path)

        result = load_mod.load_module_registry()
        assert len(result) == 2
        assert result["alpha"]["relative_path"] == "src/alpha.py"
        assert result["beta"]["size"] == 200

    def test_round_trip_empty_modules(self, mock_prax_infrastructure, monkeypatch, tmp_path):
        """Round-trip with empty modules should yield empty dict."""
        save_mod = _fresh_import_registry_save(monkeypatch, tmp_path)
        save_mod.save_module_registry({})

        load_mod = _fresh_import_registry_load(monkeypatch, tmp_path)
        result = load_mod.load_module_registry()
        assert result == {}
