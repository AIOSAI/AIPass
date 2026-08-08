# =================== AIPass ====================
# Name: test_config_loader.py
# Description: Tests for config_loader handler (FPLAN-0271 Phase 1)
# Version: 1.0.0
# Created: 2026-06-13
# Modified: 2026-06-13
# =============================================

"""
Tests for the config_loader handler (Phase 1 of FPLAN-0271).

Covers:
  1. Missing file      -- NEVER writes to disk, returns defaults, logs the absence.
  2. Malformed JSON    -- does NOT overwrite, logs ERROR, returns defaults.
  4. Partial config                 -- deep_merge fills missing defaults, preserves file values.
  5. Full config                    -- passthrough of file values.
  6. section()                      -- returns named section or empty dict for unknown.
  7. deep_merge()                   -- nested merge, non-mutation, override precedence.
"""

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers: fresh-import the module under test with mocks already in place
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_config_loader(monkeypatch):
    """Drop cached module so each test gets a fresh import.

    The conftest _mock_infrastructure replaces
    aipass.memory.apps.handlers.json with a MagicMock, which prevents
    sub-module discovery.  We pop the json package and its children so
    importlib can re-import the real modules with the prax mock still in
    place.
    """
    sys.modules.pop("aipass.memory.apps.handlers.json", None)
    sys.modules.pop("aipass.memory.apps.handlers.json.json_handler", None)
    sys.modules.pop("aipass.memory.apps.handlers.json.config_loader", None)
    yield


def _get_module():
    """Import and return the config_loader module."""
    return importlib.import_module("aipass.memory.apps.handlers.json.config_loader")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, data: dict) -> Path:
    """Write a memory.config.json into tmp_path/custom_config/ and return its path."""
    config_dir = tmp_path / "custom_config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "memory.config.json"
    config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return config_path


# ===========================================================================
# 1+2. Missing file -- NEVER writes, returns defaults, logs
# ===========================================================================


class TestMissingFile:
    """A missing config file means "no overrides", which resolves to
    DEFAULT_CONFIG.  load() must never repair the absence by writing:
    snapshotting defaults to disk is what lets code and disk drift apart.
    """

    def test_does_not_create_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        missing_path = tmp_path / "nope" / "memory.config.json"
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", missing_path)

        mod.load()

        assert not missing_path.exists()

    def test_does_not_create_parent_dirs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        missing_path = tmp_path / "nope" / "deep" / "memory.config.json"
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", missing_path)

        mod.load()

        assert not missing_path.parent.exists()

    def test_returns_default_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        missing_path = tmp_path / "nope" / "memory.config.json"
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", missing_path)

        result = mod.load()

        assert result == mod.DEFAULT_CONFIG

    def test_returned_dict_is_not_same_object_as_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        missing_path = tmp_path / "nope" / "memory.config.json"
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", missing_path)

        result = mod.load()

        assert result is not mod.DEFAULT_CONFIG

    def test_repeated_loads_never_materialize_a_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Regression: the old self-heal wrote on the FIRST load, so every
        later read silently served a frozen snapshot instead of code defaults.
        """
        missing_path = tmp_path / "nope" / "memory.config.json"
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", missing_path)

        for _ in range(3):
            assert mod.load() == mod.DEFAULT_CONFIG
            assert not missing_path.exists()

    def test_logs_absence(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        missing_path = tmp_path / "nope" / "memory.config.json"
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", missing_path)

        mock_logger = mod.logger
        mod.load()

        mock_logger.info.assert_called()


# ===========================================================================
# 3. Malformed JSON -- does NOT overwrite, logs ERROR, returns defaults
# ===========================================================================


class TestMalformedJson:
    """When the config file exists but contains invalid JSON, load() must
    NOT overwrite it, must log an ERROR, and must return defaults.
    """

    def test_returns_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_dir = tmp_path / "custom_config"
        config_dir.mkdir(parents=True, exist_ok=True)
        bad_config = config_dir / "memory.config.json"
        bad_config.write_text("{this is not valid json!!!", encoding="utf-8")

        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", bad_config)

        result = mod.load()

        assert result == mod.DEFAULT_CONFIG

    def test_does_not_overwrite_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_dir = tmp_path / "custom_config"
        config_dir.mkdir(parents=True, exist_ok=True)
        bad_config = config_dir / "memory.config.json"
        garbage = "{broken json 12345"
        bad_config.write_text(garbage, encoding="utf-8")

        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", bad_config)

        mod.load()

        # File content must be UNCHANGED -- load() must NOT overwrite existing files
        assert bad_config.read_text(encoding="utf-8") == garbage

    def test_logs_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_dir = tmp_path / "custom_config"
        config_dir.mkdir(parents=True, exist_ok=True)
        bad_config = config_dir / "memory.config.json"
        bad_config.write_text("not json", encoding="utf-8")

        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", bad_config)

        mock_logger = mod.logger
        mod.load()

        mock_logger.error.assert_called()


# ===========================================================================
# 4. Partial config -- deep_merge fills missing defaults, preserves file values
# ===========================================================================


class TestPartialConfig:
    """When the config file exists with only some sections, deep_merge
    fills in missing defaults while preserving file values.
    """

    def test_fills_missing_sections(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """File with only entry_limits should get all other sections from defaults."""
        partial = {"entry_limits": {"enforce": True}}
        config_path = _write_config(tmp_path, partial)
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

        result = mod.load()

        # memory_pool, rollover, plans should be filled in from defaults
        assert "memory_pool" in result
        assert "rollover" in result
        assert "plans" in result

    def test_preserves_file_value_over_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """File has enforce: true (default is false) -- merged result must be true."""
        partial = {"entry_limits": {"enforce": True}}
        config_path = _write_config(tmp_path, partial)
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

        result = mod.load()

        assert result["entry_limits"]["enforce"] is True

    def test_fills_missing_keys_within_section(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Partial entry_limits section should get enabled, entry_types, etc. from defaults."""
        partial = {"entry_limits": {"enforce": True}}
        config_path = _write_config(tmp_path, partial)
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

        result = mod.load()
        el = result["entry_limits"]

        # enabled should come from default
        assert el["enabled"] is True
        # entry_types should be filled from default
        assert "entry_types" in el
        assert "key_learnings" in el["entry_types"]

    def test_partial_memory_pool_preserves_file_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Partial memory_pool with only enabled=false should preserve that override."""
        partial = {"memory_pool": {"enabled": False}}
        config_path = _write_config(tmp_path, partial)
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

        result = mod.load()

        assert result["memory_pool"]["enabled"] is False
        # Other memory_pool keys should be filled from defaults
        assert "supported_extensions" in result["memory_pool"]

    def test_partial_does_not_mutate_default_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Loading a partial config must not change DEFAULT_CONFIG in-place."""
        mod = _get_module()
        original_default = copy.deepcopy(mod.DEFAULT_CONFIG)

        partial = {"entry_limits": {"enforce": True}}
        config_path = _write_config(tmp_path, partial)
        monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

        mod.load()

        assert mod.DEFAULT_CONFIG == original_default


# ===========================================================================
# 5. Full config -- passthrough of file values
# ===========================================================================


class TestFullConfig:
    """When the config file contains a complete config, load() should
    return the file values as-is (deep_merge should be a no-op).
    """

    def test_returns_file_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _get_module()
        full = copy.deepcopy(mod.DEFAULT_CONFIG)
        # Customize some values to differentiate from defaults
        full["memory_pool"]["chunk_size"] = 2000
        full["entry_limits"]["enforce"] = True

        config_path = _write_config(tmp_path, full)
        monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

        result = mod.load()

        assert result["memory_pool"]["chunk_size"] == 2000
        assert result["entry_limits"]["enforce"] is True

    def test_full_config_matches_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _get_module()
        full = copy.deepcopy(mod.DEFAULT_CONFIG)
        config_path = _write_config(tmp_path, full)
        monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

        result = mod.load()

        assert result == full


# ===========================================================================
# 6. section() -- returns named section or empty dict for unknown
# ===========================================================================


class TestSection:
    """section(name) returns the named section from the loaded config,
    or an empty dict for unknown section names.
    """

    def test_returns_known_section(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _get_module()
        config_path = _write_config(tmp_path, copy.deepcopy(mod.DEFAULT_CONFIG))
        monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

        result = mod.section("memory_pool")

        assert isinstance(result, dict)
        assert "enabled" in result

    def test_returns_entry_limits_section(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _get_module()
        config_path = _write_config(tmp_path, copy.deepcopy(mod.DEFAULT_CONFIG))
        monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

        result = mod.section("entry_limits")

        assert "enforce" in result
        assert "entry_types" in result

    def test_returns_empty_dict_for_unknown_section(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _get_module()
        config_path = _write_config(tmp_path, copy.deepcopy(mod.DEFAULT_CONFIG))
        monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

        result = mod.section("totally_nonexistent_section")

        assert result == {}

    def test_section_values_match_loaded_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _get_module()
        full = copy.deepcopy(mod.DEFAULT_CONFIG)
        full["rollover"]["defaults"]["max_lines"] = 999
        config_path = _write_config(tmp_path, full)
        monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

        result = mod.section("rollover")

        assert result["defaults"]["max_lines"] == 999


# ===========================================================================
# 7. deep_merge() -- nested merge, non-mutation, override precedence
# ===========================================================================


class TestDeepMerge:
    """deep_merge(base, overrides) performs a recursive non-mutating dict merge."""

    def test_overrides_take_precedence(self) -> None:
        mod = _get_module()
        base = {"a": 1, "b": 2}
        overrides = {"b": 99}

        result = mod.deep_merge(base, overrides)

        assert result["b"] == 99
        assert result["a"] == 1

    def test_nested_override(self) -> None:
        mod = _get_module()
        base = {"outer": {"inner": 1, "keep": True}}
        overrides = {"outer": {"inner": 42}}

        result = mod.deep_merge(base, overrides)

        assert result["outer"]["inner"] == 42
        assert result["outer"]["keep"] is True

    def test_adds_new_keys(self) -> None:
        mod = _get_module()
        base = {"a": 1}
        overrides = {"b": 2}

        result = mod.deep_merge(base, overrides)

        assert result == {"a": 1, "b": 2}

    def test_does_not_mutate_base(self) -> None:
        mod = _get_module()
        base = {"outer": {"inner": 1}}
        base_copy = copy.deepcopy(base)
        overrides = {"outer": {"inner": 99}}

        mod.deep_merge(base, overrides)

        assert base == base_copy

    def test_does_not_mutate_overrides(self) -> None:
        mod = _get_module()
        base = {"a": 1}
        overrides = {"a": 2, "b": {"c": 3}}
        overrides_copy = copy.deepcopy(overrides)

        mod.deep_merge(base, overrides)

        assert overrides == overrides_copy

    def test_deeply_nested_merge(self) -> None:
        mod = _get_module()
        base = {"l1": {"l2": {"l3": {"val": "original", "other": True}}}}
        overrides = {"l1": {"l2": {"l3": {"val": "changed"}}}}

        result = mod.deep_merge(base, overrides)

        assert result["l1"]["l2"]["l3"]["val"] == "changed"
        assert result["l1"]["l2"]["l3"]["other"] is True

    def test_empty_overrides_returns_copy_of_base(self) -> None:
        mod = _get_module()
        base = {"a": 1, "b": {"c": 2}}

        result = mod.deep_merge(base, {})

        assert result == base
        assert result is not base

    def test_empty_base_returns_copy_of_overrides(self) -> None:
        mod = _get_module()
        overrides = {"a": 1, "b": {"c": 2}}

        result = mod.deep_merge({}, overrides)

        assert result == overrides
        assert result is not overrides

    def test_non_dict_override_replaces_dict(self) -> None:
        """When an override value is a non-dict (e.g., list or scalar),
        it should replace the base value even if base has a dict there.
        """
        mod = _get_module()
        base = {"a": {"nested": True}}
        overrides = {"a": "flat_string"}

        result = mod.deep_merge(base, overrides)

        assert result["a"] == "flat_string"
