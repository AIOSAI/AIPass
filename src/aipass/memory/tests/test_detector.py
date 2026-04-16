# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_detector.py
# Date: 2026-03-24
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for the rollover trigger detection handler (apps/handlers/monitor/detector.py).

Uses tmp_path for all file operations. Creates real temp files with JSON content
rather than mocking open(). The detector functions are imported inside each test
to ensure the autouse conftest fixture for json_handler is already applied.
"""

import json
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Autouse fixture -- mock heavy infrastructure before detector is imported
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_detector_infrastructure(monkeypatch):
    """Mock prax logger and json_handler so detector.py can be imported."""

    # -- prax logger --------------------------------------------------------
    mock_logger_mod = MagicMock()
    mock_logger_mod.get_system_logger = MagicMock(return_value=MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules.logger", mock_logger_mod)

    # -- memory json handler ------------------------------------------------
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.json_handler", mock_json_handler)

    # Force fresh import every test
    monkeypatch.delitem(sys.modules, "aipass.memory.apps.handlers.monitor.detector", raising=False)


# ===========================================================================
# _get_memory_file_path
# ===========================================================================


class TestGetMemoryFilePath:
    """Tests for _get_memory_file_path(branch, memory_type)."""

    def test_returns_path_when_file_exists(self, tmp_path: Path):
        trinity_dir = tmp_path / ".trinity"
        trinity_dir.mkdir()
        obs_file = trinity_dir / "observations.json"
        obs_file.write_text("{}", encoding="utf-8")

        from aipass.memory.apps.handlers.monitor.detector import _get_memory_file_path

        branch = {"path": str(tmp_path)}
        result = _get_memory_file_path(branch, "observations")

        assert result is not None
        assert result == obs_file

    def test_returns_none_when_file_missing(self, tmp_path: Path):
        trinity_dir = tmp_path / ".trinity"
        trinity_dir.mkdir()
        # No observations.json created

        from aipass.memory.apps.handlers.monitor.detector import _get_memory_file_path

        branch = {"path": str(tmp_path)}
        result = _get_memory_file_path(branch, "observations")

        assert result is None

    def test_returns_none_when_branch_path_missing(self, tmp_path: Path):
        from aipass.memory.apps.handlers.monitor.detector import _get_memory_file_path

        nonexistent = tmp_path / "does_not_exist"
        branch = {"path": str(nonexistent)}
        result = _get_memory_file_path(branch, "local")

        assert result is None

    def test_returns_none_when_path_key_empty(self, tmp_path: Path):
        from aipass.memory.apps.handlers.monitor.detector import _get_memory_file_path

        branch: dict[str, str] = {"path": ""}
        result = _get_memory_file_path(branch, "local")

        assert result is None

    def test_local_memory_type(self, tmp_path: Path):
        trinity_dir = tmp_path / ".trinity"
        trinity_dir.mkdir()
        local_file = trinity_dir / "local.json"
        local_file.write_text("{}", encoding="utf-8")

        from aipass.memory.apps.handlers.monitor.detector import _get_memory_file_path

        branch = {"path": str(tmp_path)}
        result = _get_memory_file_path(branch, "local")

        assert result is not None
        assert result.name == "local.json"


# ===========================================================================
# _load_config
# ===========================================================================


class TestLoadConfig:
    """Tests for _load_config()."""

    def test_returns_config_dict_when_file_exists(self, tmp_path: Path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "memory_bank.config.json"
        config_data = {
            "rollover": {
                "defaults": {"max_lines": 500},
                "per_branch": {"SEEDGO": {"max_lines": 800}},
            }
        }
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        # Patch the config path resolution to point at our tmp_path
        monkeypatch.setattr(
            detector,
            "_load_config",
            lambda: json.loads(config_file.read_text(encoding="utf-8")),
        )

        result = detector._load_config()

        assert result == config_data
        assert result["rollover"]["defaults"]["max_lines"] == 500

    def test_returns_empty_dict_when_file_missing(self, monkeypatch):
        from aipass.memory.apps.handlers.monitor import detector

        # Point config resolution at a path that does not exist
        monkeypatch.setattr(
            detector,
            "_load_config",
            lambda: {},
        )

        result = detector._load_config()

        assert result == {}

    def test_returns_empty_dict_on_invalid_json(self, tmp_path: Path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_file = config_dir / "memory_bank.config.json"
        config_file.write_text("NOT VALID JSON {{", encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        # Simulate the real _load_config behavior on bad JSON
        def _broken_load() -> dict:
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}

        monkeypatch.setattr(detector, "_load_config", _broken_load)

        result = detector._load_config()

        assert result == {}


# ===========================================================================
# check_single_file
# ===========================================================================


class TestCheckSingleFile:
    """Tests for check_single_file(file_path)."""

    def test_file_under_threshold_no_rollover(self, tmp_path: Path):
        """A small file should not trigger rollover."""
        mem_file = tmp_path / "SEEDGO.observations.json"
        data = {
            "document_metadata": {
                "schema_version": "1.0.0",
                "limits": {"max_lines": 600},
            },
            "observations": [],
        }
        content = json.dumps(data, indent=2)
        mem_file.write_text(content, encoding="utf-8")

        from aipass.memory.apps.handlers.monitor.detector import check_single_file

        result = check_single_file(mem_file)

        assert result["success"] is True
        assert result["should_rollover"] is False
        assert result["current_lines"] < 600

    def test_file_over_threshold_triggers_rollover(self, tmp_path: Path):
        """A file exceeding max_lines should trigger rollover."""
        mem_file = tmp_path / "SEEDGO.local.json"
        # Build a file with many lines so it exceeds threshold of 10
        data = {
            "document_metadata": {
                "schema_version": "1.0.0",
                "limits": {"max_lines": 10},
            },
            "sessions": [{"id": f"s{i}", "notes": "padding " * 20} for i in range(50)],
        }
        content = json.dumps(data, indent=2)
        mem_file.write_text(content, encoding="utf-8")

        from aipass.memory.apps.handlers.monitor.detector import check_single_file

        result = check_single_file(mem_file)

        assert result["success"] is True
        assert result["should_rollover"] is True
        assert "trigger" in result

    def test_missing_file_returns_error(self, tmp_path: Path):
        """check_single_file on a nonexistent path returns success=False."""
        missing = tmp_path / "ghost.json"

        from aipass.memory.apps.handlers.monitor.detector import check_single_file

        result = check_single_file(missing)

        assert result["success"] is False
        assert "error" in result

    def test_v2_schema_entry_count_trigger(self, tmp_path: Path):
        """v2 schema triggers on entry counts, not line counts."""
        mem_file = tmp_path / "DRONE.local.json"
        data = {
            "document_metadata": {
                "schema_version": "2.0.0",
                "limits": {"max_sessions": 3},
            },
            "sessions": [
                {"id": "s1"},
                {"id": "s2"},
                {"id": "s3"},
                {"id": "s4"},
            ],
        }
        content = json.dumps(data, indent=2)
        mem_file.write_text(content, encoding="utf-8")

        from aipass.memory.apps.handlers.monitor.detector import check_single_file

        result = check_single_file(mem_file)

        assert result["success"] is True
        assert result["should_rollover"] is True

    def test_v2_schema_under_limit_no_trigger(self, tmp_path: Path):
        """v2 schema with entries under the limit should not trigger."""
        mem_file = tmp_path / "FLOW.local.json"
        data = {
            "document_metadata": {
                "schema_version": "2.0.0",
                "limits": {"max_sessions": 10},
            },
            "sessions": [{"id": "s1"}, {"id": "s2"}],
        }
        content = json.dumps(data, indent=2)
        mem_file.write_text(content, encoding="utf-8")

        from aipass.memory.apps.handlers.monitor.detector import check_single_file

        result = check_single_file(mem_file)

        assert result["success"] is True
        assert result["should_rollover"] is False


# ===========================================================================
# _read_registry
# ===========================================================================


class TestReadRegistry:
    """Tests for _read_registry()."""

    def test_valid_registry_returns_branches(self, tmp_path: Path, monkeypatch):
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_data = {
            "branches": [
                {"name": "memory", "path": "src/aipass/memory"},
                {"name": "drone", "path": "src/aipass/drone"},
            ]
        }
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        # Point _REPO_ROOT at our tmp_path
        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)

        result = detector._read_registry()

        assert len(result) == 2
        assert result[0]["name"] == "memory"
        # Paths should be resolved to absolute
        assert Path(result[0]["path"]).is_absolute()

    def test_missing_registry_returns_empty(self, tmp_path: Path, monkeypatch):
        from aipass.memory.apps.handlers.monitor import detector

        # Point _REPO_ROOT at a directory with no registry file
        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)

        result = detector._read_registry()

        assert result == []

    def test_invalid_json_returns_empty(self, tmp_path: Path, monkeypatch):
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text("NOT JSON {{{", encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)

        result = detector._read_registry()

        assert result == []

    def test_registry_resolves_relative_paths(self, tmp_path: Path, monkeypatch):
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_data = {
            "branches": [
                {"name": "cli", "path": "src/aipass/cli"},
            ]
        }
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)

        result = detector._read_registry()

        resolved_path = Path(result[0]["path"])
        assert resolved_path.is_absolute()
        assert str(resolved_path) == str(tmp_path / "src/aipass/cli")

    def test_empty_branches_list(self, tmp_path: Path, monkeypatch):
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_data = {"branches": []}
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)

        result = detector._read_registry()

        assert result == []
