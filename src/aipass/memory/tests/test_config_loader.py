# =================== AIPass ====================
# Name: test_config_loader.py
# Description: Tests for config_loader handler (FPLAN-0271 Phase 1)
# Version: 1.2.0
# Created: 2026-06-13
# Modified: 2026-09-15
# =============================================

"""
Tests for the config_loader handler (Phase 1 of FPLAN-0271).

Doctrine (Patrick, S193): the JSON file is the runtime authority; code
carries DEFAULT_CONFIG so that file can be regenerated when lost.

Covers:
  1. Missing file      -- REGENERATES the full file from defaults, logs, returns defaults.
  2. Unreadable file   -- left exactly as-is on disk; ERROR logged, defaults served in memory.
  4. Partial config                 -- deep_merge fills missing defaults, preserves file values.
  5. Full config                    -- passthrough of file values.
  6. section()                      -- returns named section or empty dict for unknown.
  7. deep_merge()                   -- nested merge, non-mutation, override precedence.
  8. todos count (DPLAN-0345)      -- count only, display-only, carried into per_branch.
  9. File budgets (FPLAN-0593)     -- worst-case entry/file arithmetic, the per-type
                                      per-file keep-count ceiling and its co-tenants,
                                      the clamp on load, and that no shipped default clamps.
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

    Historically this popped the json package because conftest replaced it
    with a MagicMock, which has no __path__ and so blocked sub-module
    discovery.  Conftest now impersonates the package with a real module
    object carrying the real __path__, so discovery works either way -- the
    eviction here is now only about getting a FRESH config_loader per test.

    It is a ``monkeypatch.delitem`` rather than a bare ``sys.modules.pop``
    because a bare pop is one-way: the eviction outlives the test and every
    later test in the same process inherits it.  Three test files invented
    that same workaround independently and all three leaked; one of them is
    what turned two receipt tests red on a single xdist worker on a single
    run.  delitem gives the same fresh import and puts the real module back.
    """
    for name in (
        "aipass.memory.apps.handlers.json",
        "aipass.memory.apps.handlers.json.json_handler",
        "aipass.memory.apps.handlers.json.config_loader",
    ):
        monkeypatch.delitem(sys.modules, name, raising=False)
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
# 1+2. Missing file -- REGENERATES the full file from defaults
# ===========================================================================


class TestMissingFile:
    """The file on disk is the runtime authority the operator edits.  When it
    is missing, load() regenerates it in full from DEFAULT_CONFIG — that is
    the reason code carries defaults at all.
    """

    def test_creates_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        missing_path = tmp_path / "nope" / "memory.config.json"
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", missing_path)

        mod.load()

        assert missing_path.exists()

    def test_creates_parent_dirs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        missing_path = tmp_path / "nope" / "deep" / "memory.config.json"
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", missing_path)

        mod.load()

        assert missing_path.parent.is_dir()
        assert missing_path.exists()

    def test_regenerated_file_is_the_full_default_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Not a stub and not a subset -- every section, with default values."""
        missing_path = tmp_path / "nope" / "memory.config.json"
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", missing_path)

        mod.load()
        on_disk = json.loads(missing_path.read_text(encoding="utf-8"))

        assert on_disk == mod.DEFAULT_CONFIG
        for expected_section in ("memory_pool", "entry_limits", "plans", "rollover"):
            assert expected_section in on_disk

    def test_regenerated_file_reloads_identically(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The regenerated file must parse back to the same effective config.

        A regen that produced a file the loader then read differently would
        make the on-disk authority and the running config disagree.
        """
        missing_path = tmp_path / "nope" / "memory.config.json"
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", missing_path)

        first = mod.load()
        second = mod.load()

        assert first == second == mod.DEFAULT_CONFIG

    def test_operator_edit_survives_the_next_load(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Regeneration happens ONCE, on absence -- it must never re-stamp
        defaults over a file the operator has since edited.
        """
        missing_path = tmp_path / "nope" / "memory.config.json"
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", missing_path)

        mod.load()
        edited = json.loads(missing_path.read_text(encoding="utf-8"))
        edited["rollover"]["defaults"]["local"]["sessions"]["count"] = 42
        missing_path.write_text(json.dumps(edited, indent=2), encoding="utf-8")

        result = mod.load()

        assert result["rollover"]["defaults"]["local"]["sessions"]["count"] == 42
        on_disk = json.loads(missing_path.read_text(encoding="utf-8"))
        assert on_disk["rollover"]["defaults"]["local"]["sessions"]["count"] == 42

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

    def test_still_usable_when_the_write_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A read-only filesystem must not take the branch down: log the
        failure, hand back a working config anyway.
        """
        missing_path = tmp_path / "nope" / "memory.config.json"
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", missing_path)
        monkeypatch.setattr(mod, "_write_config_file", lambda config: False)

        result = mod.load()

        assert result == mod.DEFAULT_CONFIG
        mod.logger.error.assert_not_called()  # _write_config_file owns that log

    def test_logs_absence(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        missing_path = tmp_path / "nope" / "memory.config.json"
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", missing_path)

        mock_logger = mod.logger
        mod.load()

        mock_logger.info.assert_called()


# ===========================================================================
# 3. Unreadable file -- NEVER written over; ERROR logged, defaults in memory
# ===========================================================================


class TestMalformedJson:
    """A file that EXISTS but will not parse is the operator's problem to fix,
    not the loader's to heal (DPLAN-0206 red flag, seedgo-consulted).  It may
    be one stray comma from correct and carry hand-tuned per_branch limits.
    load() logs an ERROR, serves defaults in memory, and leaves the bytes on
    disk untouched.
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

    def test_original_bytes_are_left_untouched(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Healing a typo must never cost the operator their tuning."""
        config_dir = tmp_path / "custom_config"
        config_dir.mkdir(parents=True, exist_ok=True)
        bad_config = config_dir / "memory.config.json"
        garbage = '{"rollover": {"per_branch": {"seedgo": {"count": 99,}}}'
        bad_config.write_text(garbage, encoding="utf-8")

        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", bad_config)

        mod.load()

        assert bad_config.read_text(encoding="utf-8") == garbage

    def test_writes_nothing_at_all_beside_the_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No regen, no archive copy, no stray temp -- the directory is inert."""
        config_dir = tmp_path / "custom_config"
        config_dir.mkdir(parents=True, exist_ok=True)
        bad_config = config_dir / "memory.config.json"
        bad_config.write_text("{broken json 12345", encoding="utf-8")

        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", bad_config)

        mod.load()

        assert sorted(p.name for p in config_dir.iterdir()) == ["memory.config.json"]

    def test_valid_json_of_the_wrong_shape_is_also_left_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A JSON list parses fine and then explodes in deep_merge -- it is
        corruption by any useful definition, so it takes the same no-clobber path.
        """
        config_dir = tmp_path / "custom_config"
        config_dir.mkdir(parents=True, exist_ok=True)
        bad_config = config_dir / "memory.config.json"
        original = '["not", "an", "object"]'
        bad_config.write_text(original, encoding="utf-8")

        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", bad_config)

        result = mod.load()

        assert result == mod.DEFAULT_CONFIG
        assert bad_config.read_text(encoding="utf-8") == original

    def test_repeated_loads_never_wear_the_file_down(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The watcher calls load() on a loop -- corruption must stay a
        no-op every time, not repair itself on the second pass.
        """
        config_dir = tmp_path / "custom_config"
        config_dir.mkdir(parents=True, exist_ok=True)
        bad_config = config_dir / "memory.config.json"
        original = "still corrupt"
        bad_config.write_text(original, encoding="utf-8")

        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", bad_config)

        for _ in range(3):
            assert mod.load() == mod.DEFAULT_CONFIG

        assert bad_config.read_text(encoding="utf-8") == original

    def test_fixing_the_file_takes_effect_immediately(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Serving defaults must not latch -- the moment the operator fixes
        their typo, their values are live again.
        """
        config_dir = tmp_path / "custom_config"
        config_dir.mkdir(parents=True, exist_ok=True)
        bad_config = config_dir / "memory.config.json"
        bad_config.write_text('{"entry_limits": {"enforce": false},', encoding="utf-8")

        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", bad_config)

        assert mod.load()["entry_limits"]["enforce"] is True  # the default, not their value

        bad_config.write_text('{"entry_limits": {"enforce": false}}', encoding="utf-8")

        assert mod.load()["entry_limits"]["enforce"] is False

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
# 3b. Unreadable for any OTHER reason -- bad bytes, bad permissions
# ===========================================================================


class TestUnreadableFile:
    """json_structure v3.0.0: unreadable for ANY reason takes the malformed
    path.  A file with bad bytes or the wrong permissions is exactly as
    unreadable as one with a stray comma, and neither may reach the caller
    as a raw exception -- callers asked for a config, not for a traceback.
    """

    def _bad_bytes_config(self, tmp_path: Path) -> Path:
        """Write a file that is valid on disk but undecodable as UTF-8."""
        config_dir = tmp_path / "custom_config"
        config_dir.mkdir(parents=True, exist_ok=True)
        bad_config = config_dir / "memory.config.json"
        bad_config.write_bytes(b'{"entry_limits": \x80\x81\xfe}')
        return bad_config

    def test_bad_bytes_returns_defaults_instead_of_raising(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bad_config = self._bad_bytes_config(tmp_path)
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", bad_config)

        result = mod.load()

        assert result == mod.DEFAULT_CONFIG

    def test_bad_bytes_leaves_the_file_untouched(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        bad_config = self._bad_bytes_config(tmp_path)
        original = bad_config.read_bytes()
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", bad_config)

        mod.load()

        assert bad_config.read_bytes() == original

    def test_bad_bytes_logs_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        bad_config = self._bad_bytes_config(tmp_path)
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", bad_config)

        mock_logger = mod.logger
        mod.load()

        mock_logger.error.assert_called()
        assert "UnicodeDecodeError" in mock_logger.error.call_args[0][0]

    def test_unopenable_file_returns_defaults_instead_of_raising(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PermissionError and friends: simulated via read_text, because a
        real chmod 000 is a no-op for root and unreliable on Windows.
        """
        config_dir = tmp_path / "custom_config"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "memory.config.json"
        config_path.write_text("{}", encoding="utf-8")

        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

        def _denied(*args, **kwargs):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(type(config_path), "read_text", _denied)

        result = mod.load()

        assert result == mod.DEFAULT_CONFIG

    def test_push_refuses_on_bad_bytes_rather_than_crashing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The push path reads the file too -- it had the same raw-escape hole,
        and refusing is what keeps the operator's bytes theirs.
        """
        bad_config = self._bad_bytes_config(tmp_path)
        original = bad_config.read_bytes()
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", bad_config)
        monkeypatch.setattr(mod, "materialize_per_branch", lambda: {"memory": {"local": {}}})

        result = mod.push_defaults_to_per_branch()

        assert result["success"] is False
        assert "unreadable" in result["error"]
        assert bad_config.read_bytes() == original


# ===========================================================================
# 4. Partial config -- deep_merge fills missing defaults, preserves file values
# ===========================================================================


class TestPartialConfig:
    """When the config file exists with only some sections, deep_merge
    fills in missing defaults while preserving file values.
    """

    def test_fills_missing_sections(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """File with only entry_limits should get all other sections from defaults."""
        partial = {"entry_limits": {"enforce": False}}
        config_path = _write_config(tmp_path, partial)
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

        result = mod.load()

        # memory_pool, rollover, plans should be filled in from defaults
        assert "memory_pool" in result
        assert "rollover" in result
        assert "plans" in result

    def test_preserves_file_value_over_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """File has enforce: false (default is true) -- merged result must be false."""
        partial = {"entry_limits": {"enforce": False}}
        config_path = _write_config(tmp_path, partial)
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

        result = mod.load()

        assert result["entry_limits"]["enforce"] is False

    def test_fills_missing_keys_within_section(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Partial entry_limits section should get enabled, entry_types, etc. from defaults."""
        partial = {"entry_limits": {"enforce": False}}
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

        partial = {"entry_limits": {"enforce": False}}
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
        full["entry_limits"]["enforce"] = False

        config_path = _write_config(tmp_path, full)
        monkeypatch.setattr(mod, "_CONFIG_PATH", config_path)

        result = mod.load()

        assert result["memory_pool"]["chunk_size"] == 2000
        assert result["entry_limits"]["enforce"] is False

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


# ===========================================================================
# 8. Todos count (DPLAN-0345) -- count only, display-only, carried into per_branch
# ===========================================================================


def _keys_anywhere(node):
    """Every dict key anywhere in a JSON tree."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _keys_anywhere(value)
    elif isinstance(node, list):
        for item in node:
            yield from _keys_anywhere(item)


def _rollover_section(mod, per_branch: dict | None = None) -> dict:
    """The regeneration seed's rollover section with a chosen per_branch."""
    rollover = copy.deepcopy(mod.DEFAULT_CONFIG["rollover"])
    rollover["per_branch"] = per_branch or {}
    return rollover


class TestTodosCount:
    """todos joins the resolver as a COUNT; it never becomes settable or a vector family."""

    def test_the_regeneration_seed_carries_a_todos_count_of_10(self) -> None:
        assert _get_module().DEFAULT_CONFIG["rollover"]["defaults"]["local"]["todos"] == {"count": 10}

    def test_the_todos_task_cap_is_100_chars(self) -> None:
        assert _get_module().DEFAULT_CONFIG["entry_limits"]["entry_types"]["todos"]["max_chars"] == 100

    def test_no_max_entries_anywhere(self) -> None:
        """A pad's size is ONE number, rollover.defaults.local.todos.count - never a second knob.

        The seed ships; the operator file is gitignored, so it is walked where this machine has one.
        """
        mod = _get_module()
        trees = [mod.DEFAULT_CONFIG]
        if mod._CONFIG_PATH.exists():
            trees.append(json.loads(mod._CONFIG_PATH.read_text(encoding="utf-8")))
        for tree in trees:
            assert "max_entries" not in set(_keys_anywhere(tree))

    def test_todos_is_a_count_only_type(self) -> None:
        mod = _get_module()
        assert mod.ENTRY_TYPE_KEYS["todos"] == ("local", "todos")
        assert "todos" in mod.COUNT_ONLY_ENTRY_TYPES
        assert "todos" not in mod.SETTABLE_ENTRY_TYPES

    def test_the_resolver_reports_the_todos_count(self) -> None:
        mod = _get_module()
        row = mod.resolve_limits(_rollover_section(mod), "Guinea")["todos"]
        assert (row["count"], row["default_count"], row["source"], row["is_override"]) == (10, 10, "defaults", False)

    def test_a_local_block_without_todos_falls_back_for_todos_only(self) -> None:
        mod = _get_module()
        limits = mod.resolve_limits(
            _rollover_section(mod, {"guinea": {"local": {"sessions": {"count": 30}}}}), "guinea"
        )
        assert (limits["todos"]["count"], limits["todos"]["source"]) == (10, "defaults")
        assert limits["key_learnings"]["count"] is None, "the per-file-key rule still holds for the vector families"

    def test_a_per_branch_todos_count_wins(self) -> None:
        mod = _get_module()
        rollover = _rollover_section(mod, {"guinea": {"local": {"todos": {"count": 4}}}})
        assert mod.get_todos_count("GUINEA", rollover) == 4

    @pytest.mark.parametrize("unusable", [True, 0, -3, "10", 2.5, None])
    def test_an_unusable_count_is_no_count(self, unusable) -> None:
        mod = _get_module()
        rollover = _rollover_section(mod)
        rollover["defaults"]["local"]["todos"] = {"count": unusable}
        assert mod.get_todos_count("guinea", rollover) is None

    def test_get_todos_count_reads_the_config_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mod = _get_module()
        config = copy.deepcopy(mod.DEFAULT_CONFIG)
        config["rollover"]["per_branch"] = {"guinea": {"local": {"todos": {"count": 6}}}}
        monkeypatch.setattr(mod, "_CONFIG_PATH", _write_config(tmp_path, config))
        assert mod.get_todos_count("guinea") == 6


class TestTodosCountMaterializes:
    """Every per_branch local block a write creates or touches carries the todos count."""

    @staticmethod
    def _world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mod, config: dict) -> Path:
        registry = {
            "branches": [
                {"name": "Guinea", "path": "src/aipass/guinea", "status": "active"},
                {"name": "pig", "path": "src/aipass/pig", "status": "active"},
            ]
        }
        (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)
        path = _write_config(tmp_path, config)
        monkeypatch.setattr(mod, "_CONFIG_PATH", path)
        return path

    def test_materialize_carries_the_configured_todos_count(self, tmp_path: Path, monkeypatch) -> None:
        mod = _get_module()
        config = copy.deepcopy(mod.DEFAULT_CONFIG)
        config["rollover"]["defaults"]["local"]["todos"] = {"count": 7}
        self._world(tmp_path, monkeypatch, mod, config)

        per_branch = mod.materialize_per_branch()

        assert set(per_branch) == {"guinea", "pig"}
        assert all(entry["local"]["todos"] == {"count": 7} for entry in per_branch.values())

    def test_a_set_on_an_existing_block_without_todos_writes_it(self, tmp_path: Path, monkeypatch) -> None:
        mod = _get_module()
        config = copy.deepcopy(mod.DEFAULT_CONFIG)
        config["rollover"]["per_branch"] = {
            "guinea": {"local": {"sessions": {"count": 30}, "key_learnings": {"count": 15}}}
        }
        path = self._world(tmp_path, monkeypatch, mod, config)

        assert mod.set_branch_limit("guinea", "sessions", 20)["success"] is True

        local = json.loads(path.read_text(encoding="utf-8"))["rollover"]["per_branch"]["guinea"]["local"]
        assert local["sessions"] == {"count": 20}
        assert local["todos"] == {"count": 10}

    def test_todos_is_refused_by_both_writers_and_nothing_is_written(self, tmp_path: Path, monkeypatch) -> None:
        mod = _get_module()
        path = self._world(tmp_path, monkeypatch, mod, copy.deepcopy(mod.DEFAULT_CONFIG))
        before = path.read_bytes()
        display_only = {"success": False, "error": "'todos' count is display-only in v1 - not settable"}

        assert mod.set_branch_limit("guinea", "todos", 5) == display_only
        assert mod.set_default_limit("todos", 5) == display_only
        assert mod.set_default_limit("wizard", 5) == {"success": False, "error": "Unknown entry type: 'wizard'"}
        assert path.read_bytes() == before


# ===========================================================================
# 9. File budgets (FPLAN-0593) -- a keep-count is a MULTIPLIER on an entry cap
# ===========================================================================


def _budget_module():
    """Import and return the pure budget-arithmetic module."""
    return importlib.import_module("aipass.memory.apps.handlers.json.budget")


def _entry_limits(mod) -> dict:
    """The regeneration seed's entry_limits section -- shapes and budgets."""
    return copy.deepcopy(mod.DEFAULT_CONFIG["entry_limits"])


def _shape(mod, entry_type: str) -> dict:
    """The closed field shape the seed publishes for *entry_type*."""
    return mod.DEFAULT_CONFIG["entry_limits"]["entry_types"][entry_type]["fields"]


def _default_counts(mod) -> dict:
    """Every entry type at the count the fleet actually ships with."""
    return {name: row["count"] for name, row in _shipped_rows(mod).items()}


def _shipped_rows(mod) -> dict:
    """The seed's default limits, resolved for a branch with no per_branch entry."""
    return mod.resolve_limits(_rollover_section(mod), "nobody")


class TestWorstEntryChars:
    """The largest an entry can legally be is MEASURED, never hand-summed."""

    def test_a_bigger_shape_is_a_bigger_entry(self) -> None:
        """sessions carries the most capped text, todos the least."""
        mod, bud = _get_module(), _budget_module()
        sessions = bud.worst_entry_chars(_shape(mod, "sessions"))
        key_learnings = bud.worst_entry_chars(_shape(mod, "key_learnings"))
        todos = bud.worst_entry_chars(_shape(mod, "todos"))
        assert sessions > key_learnings > todos

    def test_it_equals_what_a_real_container_pays_for_one_more_entry(self) -> None:
        """The number IS the delta, at the indent an entry sits at on disk.

        Pinned against a second serialization rather than a literal: a
        hand-summed count of braces, quotes and indentation is exactly the
        arithmetic this function exists to stop anyone doing.
        """
        mod, bud = _get_module(), _budget_module()
        entry = {"number": 999, "date": "x" * 10, "task": "x" * 100, "priority": "x" * 10}
        one = len(json.dumps({"todos": [entry]}, indent=2, ensure_ascii=False))
        two = len(json.dumps({"todos": [entry, entry]}, indent=2, ensure_ascii=False))
        assert bud.worst_entry_chars(_shape(mod, "todos")) == two - one

    def test_a_tag_list_is_measured_at_max_items_and_max_joined_chars(self) -> None:
        """Ten tags of joined 120 chars cost more than the same text in one."""
        mod, bud = _get_module(), _budget_module()
        shape = copy.deepcopy(_shape(mod, "sessions"))
        shape["tags"] = {"type": "list[str]", "required": False, "max_items": 1, "max_chars": 120}
        assert bud.worst_entry_chars(_shape(mod, "sessions")) > bud.worst_entry_chars(shape)

    def test_an_unpublished_shape_is_not_guessed_at(self) -> None:
        assert _budget_module().worst_entry_chars({}) == 0


class TestWorstFileChars:
    """A file's worst case is its entries plus the structure they sit in."""

    def test_it_sums_only_the_types_that_live_in_that_file(self) -> None:
        mod, bud = _get_module(), _budget_module()
        entry_types = _entry_limits(mod)["entry_types"]
        counts = _default_counts(mod)
        observations = bud.worst_file_chars("observations.json", counts, entry_types)
        expected = bud.FILE_STRUCTURE_ALLOWANCE["observations.json"] + 15 * bud.worst_entry_chars(
            _shape(mod, "observations")
        )
        assert observations == expected

    def test_the_auto_compact_sessions_are_budgeted_on_top_of_the_keep_count(self) -> None:
        """The 3 auto-compact sessions are EXTRA; a ceiling that skips them under-counts."""
        mod, bud = _get_module(), _budget_module()
        entry_types = _entry_limits(mod)["entry_types"]
        counts = _default_counts(mod)
        per_session = bud.worst_entry_chars(_shape(mod, "sessions"))
        expected = (
            bud.FILE_STRUCTURE_ALLOWANCE["local.json"]
            + (counts["sessions"] + 3) * per_session
            + counts["key_learnings"] * bud.worst_entry_chars(_shape(mod, "key_learnings"))
            + counts["todos"] * bud.worst_entry_chars(_shape(mod, "todos"))
        )
        assert bud.worst_file_chars("local.json", counts, entry_types) == expected
        assert bud.AUTO_COMPACT_EXTRA["sessions"] == 3

    def test_an_unusable_count_is_zero_entries_not_a_crash(self) -> None:
        mod, bud = _get_module(), _budget_module()
        entry_types = _entry_limits(mod)["entry_types"]
        broken = {"sessions": None, "key_learnings": "15", "todos": True, "observations": -4}
        assert (
            bud.worst_file_chars("observations.json", broken, entry_types)
            == (bud.FILE_STRUCTURE_ALLOWANCE["observations.json"])
        )


class TestCountCeilingCoTenancy:
    """local.json is SHARED, so no type's ceiling is a property of that type."""

    def test_raising_key_learnings_lowers_the_sessions_ceiling(self) -> None:
        mod, bud = _get_module(), _budget_module()
        limits = _entry_limits(mod)
        counts = _default_counts(mod)
        roomy = bud.count_ceiling("sessions", counts, limits["entry_types"], limits["file_budgets"])
        crowded = bud.count_ceiling(
            "sessions",
            {**counts, "key_learnings": counts["key_learnings"] + 5},
            limits["entry_types"],
            limits["file_budgets"],
        )
        assert crowded < roomy

    def test_emptying_the_file_raises_it(self) -> None:
        mod, bud = _get_module(), _budget_module()
        limits = _entry_limits(mod)
        counts = _default_counts(mod)
        alone = {**counts, "key_learnings": 0, "todos": 0}
        assert bud.count_ceiling("sessions", alone, limits["entry_types"], limits["file_budgets"]) > bud.count_ceiling(
            "sessions", counts, limits["entry_types"], limits["file_budgets"]
        )

    def test_a_sole_tenant_has_no_company(self) -> None:
        mod, bud = _get_module(), _budget_module()
        entry_types = _entry_limits(mod)["entry_types"]
        counts = _default_counts(mod)
        assert bud.co_tenants("observations.json", counts, entry_types, exclude="observations") == {}
        assert bud.co_tenants("local.json", counts, entry_types, exclude="sessions") == {
            "key_learnings": counts["key_learnings"],
            "todos": counts["todos"],
        }

    def test_the_ceiling_at_the_edge_is_the_largest_count_that_still_fits(self) -> None:
        """One more entry than the ceiling busts the budget; the ceiling itself does not."""
        mod, bud = _get_module(), _budget_module()
        limits = _entry_limits(mod)
        counts = _default_counts(mod)
        ceiling = bud.count_ceiling("sessions", counts, limits["entry_types"], limits["file_budgets"])
        budget_chars = limits["file_budgets"]["local.json"]["max_chars"]
        assert (
            bud.worst_file_chars("local.json", {**counts, "sessions": ceiling}, limits["entry_types"]) <= budget_chars
        )
        assert (
            bud.worst_file_chars("local.json", {**counts, "sessions": ceiling + 1}, limits["entry_types"])
            > budget_chars
        )

    def test_a_budget_too_small_for_one_entry_still_reports_one(self) -> None:
        """Zero would roll every entry away on sight -- that is a config to fix, not a limit."""
        mod, bud = _get_module(), _budget_module()
        limits = _entry_limits(mod)
        assert (
            bud.count_ceiling("sessions", _default_counts(mod), limits["entry_types"], {"local.json": {"max_chars": 1}})
            == 1
        )

    def test_nothing_measurable_refuses_nothing(self) -> None:
        mod, bud = _get_module(), _budget_module()
        limits = _entry_limits(mod)
        counts = _default_counts(mod)
        assert (
            bud.count_ceiling("wizard", counts, limits["entry_types"], limits["file_budgets"]) == bud.UNBOUNDED_CEILING
        )
        assert bud.count_ceiling("sessions", counts, limits["entry_types"], {}) == bud.UNBOUNDED_CEILING


class TestClampOnLoad:
    """A hand-edited over-budget count is LOWERED at the resolver, and said so."""

    @staticmethod
    def _over_budget(mod, count: int = 40) -> dict:
        return _rollover_section(mod, {"guinea": {"local": {"sessions": {"count": count}}}})

    def test_the_count_is_lowered_to_the_ceiling(self) -> None:
        mod, bud = _get_module(), _budget_module()
        limits = _entry_limits(mod)
        row = mod.resolve_limits(self._over_budget(mod), "guinea", limits)["sessions"]
        counts = {name: r["count"] for name, r in mod.resolve_limits(self._over_budget(mod), "guinea").items()}
        assert row["count"] == bud.count_ceiling("sessions", counts, limits["entry_types"], limits["file_budgets"])
        assert row["count"] < 40

    def test_what_the_operator_wrote_is_still_readable(self) -> None:
        mod = _get_module()
        row = mod.resolve_limits(self._over_budget(mod), "guinea", _entry_limits(mod))["sessions"]
        assert row["requested_count"] == 40

    def test_a_count_that_fits_is_left_exactly_as_written(self) -> None:
        mod = _get_module()
        row = mod.resolve_limits(self._over_budget(mod, 5), "guinea", _entry_limits(mod))["sessions"]
        assert (row["count"], row["requested_count"]) == (5, 5)

    def test_the_warning_names_both_numbers_the_file_its_budget_and_the_company(self) -> None:
        mod = _get_module()
        mod.resolve_limits(self._over_budget(mod), "guinea", _entry_limits(mod))
        said = " ".join(str(call) for call in mod.logger.warning.call_args_list)
        assert "40" in said and "local.json" in said and "25,000" in said and "todos" in said

    def test_without_ceiling_data_there_is_no_clamp(self) -> None:
        """The resolver promises no I/O, so a caller that has not loaded the
        budgets gets the number as written rather than a silent extra read."""
        mod = _get_module()
        assert mod.resolve_limits(self._over_budget(mod), "guinea")["sessions"]["count"] == 40

    def test_the_clamp_reaches_the_effective_limits_read(self, tmp_path: Path, monkeypatch) -> None:
        mod = _get_module()
        config = copy.deepcopy(mod.DEFAULT_CONFIG)
        config["rollover"]["per_branch"] = {"guinea": {"local": {"sessions": {"count": 40}}}}
        monkeypatch.setattr(mod, "_CONFIG_PATH", _write_config(tmp_path, config))
        row = mod.get_effective_limits("guinea")["sessions"]
        assert row["count"] < 40 and row["requested_count"] == 40

    def test_the_clamp_reaches_the_todo_pad(self, tmp_path: Path, monkeypatch) -> None:
        mod = _get_module()
        config = copy.deepcopy(mod.DEFAULT_CONFIG)
        config["rollover"]["per_branch"] = {"guinea": {"local": {"todos": {"count": 400}}}}
        monkeypatch.setattr(mod, "_CONFIG_PATH", _write_config(tmp_path, config))
        assert 0 < mod.get_todos_count("guinea") < 400

    def test_every_ceiling_is_measured_against_the_same_company(self) -> None:
        """Clamping one type must not silently buy room for the next one in iteration order."""
        mod = _get_module()
        rollover = _rollover_section(
            mod,
            {"guinea": {"local": {"sessions": {"count": 40}, "key_learnings": {"count": 40}, "todos": {"count": 10}}}},
        )
        rows = mod.resolve_limits(rollover, "guinea", _entry_limits(mod))
        assert rows["sessions"]["count"] < 40
        assert rows["key_learnings"]["count"] < 40


class TestShippedDefaultsDoNotClamp:
    """FPLAN-0593 changes NOTHING for a fleet sitting on the defaults."""

    def test_every_shipped_default_is_under_its_own_ceiling(self) -> None:
        mod, bud = _get_module(), _budget_module()
        limits = _entry_limits(mod)
        counts = _default_counts(mod)
        for entry_type, count in counts.items():
            ceiling = bud.count_ceiling(entry_type, counts, limits["entry_types"], limits["file_budgets"])
            assert count <= ceiling, f"{entry_type} ships at {count} but its ceiling is {ceiling}"

    def test_resolving_the_seed_changes_no_count(self) -> None:
        mod = _get_module()
        clamped = mod.resolve_limits(_rollover_section(mod), "nobody", _entry_limits(mod))
        assert {name: row["count"] for name, row in clamped.items()} == _default_counts(mod)
        assert all(row["count"] == row["requested_count"] for row in clamped.values())

    def test_the_defaults_fit_their_files_with_room_to_spare(self) -> None:
        mod, bud = _get_module(), _budget_module()
        limits = _entry_limits(mod)
        counts = _default_counts(mod)
        for file_key, spec in limits["file_budgets"].items():
            if file_key == "passport.json":
                continue
            assert bud.worst_file_chars(file_key, counts, limits["entry_types"]) <= spec["max_chars"]


class TestFileBudgetAccessor:
    """config_loader owns config reads, so the budgets are read through it."""

    def test_it_serves_the_three_configured_budgets(self, tmp_path: Path, monkeypatch) -> None:
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", _write_config(tmp_path, copy.deepcopy(mod.DEFAULT_CONFIG)))
        budgets = mod.get_file_budgets()
        assert budgets["local.json"]["max_chars"] == 25000
        assert budgets["observations.json"]["max_chars"] == 15000
        assert budgets["passport.json"]["max_string_chars"] == 600

    def test_a_caller_cannot_edit_the_fleet_budgets_by_mutating_what_it_got(self, tmp_path: Path, monkeypatch) -> None:
        mod = _get_module()
        monkeypatch.setattr(mod, "_CONFIG_PATH", _write_config(tmp_path, copy.deepcopy(mod.DEFAULT_CONFIG)))
        mod.get_file_budgets()["local.json"]["max_chars"] = 1
        assert mod.get_file_budgets()["local.json"]["max_chars"] == 25000

    def test_ceilings_read_the_configured_budget_not_a_literal(self, tmp_path: Path, monkeypatch) -> None:
        """Halve local.json's budget and every local.json ceiling must move."""
        mod = _get_module()
        config = copy.deepcopy(mod.DEFAULT_CONFIG)
        config["entry_limits"]["file_budgets"]["local.json"]["max_chars"] = 12500
        monkeypatch.setattr(mod, "_CONFIG_PATH", _write_config(tmp_path, config))
        tightened = mod.get_count_ceilings()
        assert tightened["sessions"]["ceiling"] < 15
        assert tightened["observations"]["ceiling"] >= 15, "observations.json's budget did not move"
