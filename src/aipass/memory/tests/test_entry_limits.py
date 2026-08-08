# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_entry_limits.py
# Date: 2026-06-13
# Version: 1.1.0
# Category: memory/tests
# =============================================

"""
Tests for the entry_limits config reader (Phase 1 of FPLAN-0270).

Covers:
  - Normal config read returns four default entry types.
  - per_branch override changes a cap.
  - per_branch adds a new entry type.
  - Missing config file returns safe defaults (no crash).
  - Malformed JSON returns safe defaults + error logged (no crash).

Note: entry_limits delegates config reading to config_loader, so tests
patch config_loader._CONFIG_PATH rather than a removed entry_limits attr.
"""

import importlib
import json
import sys
from pathlib import Path
import pytest


# ---------------------------------------------------------------------------
# Helpers: fresh-import the module under test with mocks already in place
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_entry_limits(monkeypatch):
    """Drop cached module so each test gets a fresh import.

    The conftest _mock_infrastructure replaces
    aipass.memory.apps.handlers.json with a MagicMock, which prevents
    sub-module discovery.  We pop the json package and its children so
    importlib can re-import the real modules with the prax mock still in
    place.

    config_loader must also be popped so its _CONFIG_PATH can be
    re-patched per test.
    """
    sys.modules.pop("aipass.memory.apps.handlers.json", None)
    sys.modules.pop("aipass.memory.apps.handlers.json.json_handler", None)
    sys.modules.pop("aipass.memory.apps.handlers.json.config_loader", None)
    sys.modules.pop("aipass.memory.apps.handlers.json.entry_limits", None)
    yield


def _get_modules():
    """Import and return (entry_limits, config_loader) modules."""
    config_loader = importlib.import_module("aipass.memory.apps.handlers.json.config_loader")
    entry_limits = importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")
    return entry_limits, config_loader


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, data: dict) -> Path:
    """Write a memory.config.json into tmp_path/config/ and return its path."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "memory.config.json"
    config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return config_path


def _full_config(**entry_limits_overrides) -> dict:
    """Return a minimal memory.config.json dict with an entry_limits section.

    Any keyword args are merged into the entry_limits section.
    """
    section = {
        "enabled": True,
        "enforce": False,
        "entry_types": {
            "key_learnings": {
                "file": "local.json",
                "container": "key_learnings",
                "kind": "dict",
                "field": "value",
                "max_chars": 200,
            },
            "sessions": {
                "file": "local.json",
                "container": "sessions",
                "kind": "list",
                "field": "summary",
                "max_chars": 300,
            },
            "todos": {
                "file": "local.json",
                "container": "todos",
                "kind": "list",
                "field": "task",
                "max_chars": 200,
            },
            "observations": {
                "file": "observations.json",
                "container": "observations",
                "kind": "list",
                "field": "note",
                "max_chars": 600,
            },
        },
        "per_branch": {},
    }
    section.update(entry_limits_overrides)
    return {"entry_limits": section}


# ===========================================================================
# 1. Normal config returns four default entry types
# ===========================================================================


class TestNormalConfig:
    """Reader returns the four default caps with a normal config."""

    def test_returns_four_entry_types(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = _write_config(tmp_path, _full_config())
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("some_branch")

        assert "entry_types" in result
        assert len(result["entry_types"]) == 4
        assert set(result["entry_types"].keys()) == {"key_learnings", "sessions", "todos", "observations"}

    def test_enabled_is_true(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = _write_config(tmp_path, _full_config())
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("any")

        assert result["enabled"] is True

    def test_enforce_false_on_disk_overrides_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Code defaults to enforce=True; an explicit False on disk must win."""
        config_path = _write_config(tmp_path, _full_config())
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("any")

        assert result["enforce"] is False

    def test_default_max_chars_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = _write_config(tmp_path, _full_config())
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("any")
        types = result["entry_types"]

        assert types["key_learnings"]["max_chars"] == 200
        assert types["sessions"]["max_chars"] == 300
        assert types["todos"]["max_chars"] == 200
        assert types["observations"]["max_chars"] == 600


# ===========================================================================
# 2. per_branch override changes a cap
# ===========================================================================


class TestPerBranchOverride:
    """per_branch override changes a cap for the specified branch."""

    def test_override_max_chars(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _full_config(per_branch={"devpulse": {"sessions": {"max_chars": 400}}})
        config_path = _write_config(tmp_path, cfg)
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("devpulse")

        assert result["entry_types"]["sessions"]["max_chars"] == 400
        # Other fields on sessions should be preserved from base
        assert result["entry_types"]["sessions"]["file"] == "local.json"
        assert result["entry_types"]["sessions"]["container"] == "sessions"

    def test_override_does_not_affect_other_branches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _full_config(per_branch={"devpulse": {"sessions": {"max_chars": 400}}})
        config_path = _write_config(tmp_path, cfg)
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("memory")

        # memory branch should get the default, not devpulse's override
        assert result["entry_types"]["sessions"]["max_chars"] == 300

    def test_override_does_not_affect_other_types(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _full_config(per_branch={"devpulse": {"sessions": {"max_chars": 400}}})
        config_path = _write_config(tmp_path, cfg)
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("devpulse")

        # Other types should be unchanged
        assert result["entry_types"]["key_learnings"]["max_chars"] == 200
        assert result["entry_types"]["observations"]["max_chars"] == 600


# ===========================================================================
# 3. per_branch adds a NEW entry type
# ===========================================================================


class TestPerBranchNewType:
    """per_branch adds a new entry type and the reader includes it."""

    def test_new_type_added(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        new_type = {
            "file": "local.json",
            "container": "custom_notes",
            "kind": "list",
            "field": "text",
            "max_chars": 500,
        }
        cfg = _full_config(per_branch={"special": {"custom_notes": new_type}})
        config_path = _write_config(tmp_path, cfg)
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("special")

        assert "custom_notes" in result["entry_types"]
        assert result["entry_types"]["custom_notes"]["max_chars"] == 500
        assert result["entry_types"]["custom_notes"]["container"] == "custom_notes"
        # Original four types still present
        assert len(result["entry_types"]) == 5

    def test_new_type_not_present_for_other_branch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        new_type = {
            "file": "local.json",
            "container": "custom_notes",
            "kind": "list",
            "field": "text",
            "max_chars": 500,
        }
        cfg = _full_config(per_branch={"special": {"custom_notes": new_type}})
        config_path = _write_config(tmp_path, cfg)
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("other_branch")

        assert "custom_notes" not in result["entry_types"]
        assert len(result["entry_types"]) == 4


# ===========================================================================
# 4. Missing config file returns safe defaults (no crash)
# ===========================================================================


class TestMissingConfig:
    """Missing config file returns safe defaults without crashing."""

    def test_missing_config_returns_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        missing_path = tmp_path / "nonexistent" / "memory.config.json"
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", missing_path)

        result = mod.load_entry_limits("any_branch")

        assert result["enabled"] is True
        assert result["enforce"] is True
        assert len(result["entry_types"]) == 4
        assert result["entry_types"]["sessions"]["max_chars"] == 300

    def test_missing_config_logs_info_and_writes_nothing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """config_loader serves defaults at INFO level and never creates the file."""
        missing_path = tmp_path / "nonexistent" / "memory.config.json"
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", missing_path)

        mock_logger = loader.logger
        mod.load_entry_limits("any_branch")

        mock_logger.info.assert_called()
        info_msg = mock_logger.info.call_args[0][0]
        assert "config" in info_msg.lower()
        assert not missing_path.exists()


# ===========================================================================
# 5. Malformed JSON returns safe defaults + error logged (no crash)
# ===========================================================================


class TestMalformedJson:
    """Malformed JSON returns safe defaults and logs an error."""

    def test_malformed_json_returns_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        bad_config = config_dir / "memory.config.json"
        bad_config.write_text("{this is not valid json!!!", encoding="utf-8")

        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", bad_config)

        result = mod.load_entry_limits("any_branch")

        assert result["enabled"] is True
        assert result["enforce"] is True
        assert len(result["entry_types"]) == 4

    def test_malformed_json_logs_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """config_loader logs malformed JSON at ERROR level (not warning)."""
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        bad_config = config_dir / "memory.config.json"
        bad_config.write_text("{broken json", encoding="utf-8")

        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", bad_config)

        mock_logger = loader.logger
        mod.load_entry_limits("any_branch")

        mock_logger.error.assert_called()
        error_msg = mock_logger.error.call_args[0][0]
        assert "malformed" in error_msg.lower() or "json" in error_msg.lower()

    def test_missing_entry_limits_section_returns_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Config file exists but has no entry_limits section."""
        config_path = _write_config(tmp_path, {"rollover": {"defaults": {"max_lines": 500}}})
        mod, loader = _get_modules()
        monkeypatch.setattr(loader, "_CONFIG_PATH", config_path)

        result = mod.load_entry_limits("any_branch")

        assert result["enabled"] is True
        assert result["enforce"] is True
        assert len(result["entry_types"]) == 4
