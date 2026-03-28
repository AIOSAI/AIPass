# =================== AIPass ====================
# Name: test_json_handler.py
# Description: Universal JSON Handler Test Template
# Version: 1.0.0
# Created: 2026-03-28
# Modified: 2026-03-28
# =============================================

"""
Universal JSON Handler Test Template for DAEMON branch.

Covers 8 groups:
  - _default_template / default factory (4)
  - validate_json_structure (10)
  - get_json_path (3)
  - ensure_json_exists (5)
  - load_json (4)
  - save_json (5)
  - log_operation (7)
  - ensure_module_jsons (5)
"""

import importlib
import json
import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest


# ============ BRANCH CONFIG ============
BRANCH_MODULE = "daemon"
# =======================================

# ---------------------------------------------------------------------------
# Dynamic import with cross-branch guard bypass
# ---------------------------------------------------------------------------

_handler_pkg = f"aipass.{BRANCH_MODULE}.apps.handlers"
_json_mod_path = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"

if _handler_pkg not in sys.modules:
    _stub = types.ModuleType(_handler_pkg)
    _handlers_dir = (
        Path(__file__).resolve().parents[3] / "aipass" / BRANCH_MODULE / "apps" / "handlers"
    )
    _stub.__path__ = [str(_handlers_dir)]
    sys.modules[_handler_pkg] = _stub

_mod = importlib.import_module(_json_mod_path)
json_handler = _mod


# ---------------------------------------------------------------------------
# JSON_DIR variable discovery
# ---------------------------------------------------------------------------

_JSON_DIR_ATTR: str | None = None
_JSON_DIR_CANDIDATES = [
    f"{BRANCH_MODULE.upper()}_JSON_DIR",
    "JSON_DIR",
    "BRANCH_JSON_DIR",
    f"{BRANCH_MODULE}_json",
    "_JSON_DIR",
]

for _candidate in _JSON_DIR_CANDIDATES:
    if hasattr(_mod, _candidate):
        _JSON_DIR_ATTR = _candidate
        break

if _JSON_DIR_ATTR is None:
    pytest.skip(
        f"Cannot find JSON_DIR attribute on {BRANCH_MODULE}.json_handler -- "
        f"tried: {_JSON_DIR_CANDIDATES}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Default factory discovery
# ---------------------------------------------------------------------------

def _get_default_for_type(json_type: str, module_name: str = "test_mod") -> Any:
    """Call whichever default factory the branch exposes."""
    for fn_name in (
        "_create_default",
        "_get_default_template",
        "_get_default",
        "_default_template",
        "load_template",
    ):
        fn = getattr(_mod, fn_name, None)
        if fn is not None:
            return fn(json_type, module_name)

    if json_type == "config" and hasattr(_mod, "_default_config"):
        return _mod._default_config(module_name)
    if json_type == "data" and hasattr(_mod, "_default_data"):
        return _mod._default_data(module_name)
    if json_type == "log" and hasattr(_mod, "_default_log"):
        return _mod._default_log(module_name)

    return None


def _has_default_factory() -> bool:
    """Return True if the branch has any callable default factory."""
    for fn_name in (
        "_create_default",
        "_get_default_template",
        "_get_default",
        "_default_template",
        "load_template",
        "_default_config",
    ):
        if hasattr(_mod, fn_name):
            return True
    return False


def _default_factory_raises_on_unknown() -> bool:
    """Return True if the default factory raises ValueError for unknown types."""
    for fn_name in (
        "_create_default",
        "_get_default_template",
        "_get_default",
        "_default_template",
    ):
        fn = getattr(_mod, fn_name, None)
        if fn is not None:
            try:
                fn("__nonexistent_type__", "test_mod")
            except ValueError:
                return True
            except Exception:
                return False
            return False
    return False


# ---------------------------------------------------------------------------
# Isolation fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_json_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect JSON operations to tmp_path for test isolation."""
    assert _JSON_DIR_ATTR is not None
    original_value = getattr(_mod, _JSON_DIR_ATTR)
    if isinstance(original_value, str):
        monkeypatch.setattr(_mod, _JSON_DIR_ATTR, str(tmp_path))
    else:
        monkeypatch.setattr(_mod, _JSON_DIR_ATTR, tmp_path)
    return tmp_path


def _json_dir_as_path(tmp_path: Path) -> Path:
    """Return the patched JSON dir as a Path."""
    assert _JSON_DIR_ATTR is not None
    val = getattr(_mod, _JSON_DIR_ATTR)
    if isinstance(val, str):
        return Path(val)
    return val


# ============================================================================
# Group 1 -- default_factory (4 tests)
# ============================================================================

def test_default_factory_config_returns_dict() -> None:
    """default_factory: config template returns a dict with required keys."""
    if not _has_default_factory():
        pytest.skip("Branch has no default factory function")
    result = _get_default_for_type("config", "test_mod")
    assert isinstance(result, dict), "Config default must be a dict"
    assert "module_name" in result, "Config default must have module_name"
    assert "version" in result, "Config default must have version"
    assert "config" in result, "Config default must have config"


def test_default_factory_data_returns_dict() -> None:
    """default_factory: data template returns a dict with date keys."""
    if not _has_default_factory():
        pytest.skip("Branch has no default factory function")
    result = _get_default_for_type("data", "test_mod")
    assert isinstance(result, dict), "Data default must be a dict"
    assert "created" in result, "Data default must have created"
    assert "last_updated" in result, "Data default must have last_updated"


def test_default_factory_log_returns_empty_list() -> None:
    """default_factory: log template returns an empty list."""
    if not _has_default_factory():
        pytest.skip("Branch has no default factory function")
    result = _get_default_for_type("log", "test_mod")
    assert isinstance(result, list), "Log default must be a list"
    assert len(result) == 0, "Log default must be empty"


def test_default_factory_unknown_type_raises() -> None:
    """default_factory: unknown json_type raises ValueError."""
    if not _default_factory_raises_on_unknown():
        pytest.skip("Branch default factory does not raise ValueError for unknown types")
    with pytest.raises(ValueError, match="[Uu]nknown"):
        _get_default_for_type("__nonexistent__", "test_mod")


# ============================================================================
# Group 2 -- validate (10 tests)
# ============================================================================

def test_validate_valid_config() -> None:
    """validate: valid config structure passes."""
    data = {"module_name": "x", "version": "1.0.0", "config": {}}
    assert json_handler.validate_json_structure(data, "config") is True


def test_validate_config_missing_key() -> None:
    """validate: config missing required key fails."""
    data = {"module_name": "x", "version": "1.0.0"}
    assert json_handler.validate_json_structure(data, "config") is False


def test_validate_config_not_dict() -> None:
    """validate: non-dict config fails."""
    assert json_handler.validate_json_structure([1, 2, 3], "config") is False


def test_validate_valid_data() -> None:
    """validate: valid data structure passes."""
    data = {"created": "2026-01-01", "last_updated": "2026-01-01"}
    assert json_handler.validate_json_structure(data, "data") is True


def test_validate_data_missing_key() -> None:
    """validate: data missing required key fails."""
    data = {"created": "2026-01-01"}
    assert json_handler.validate_json_structure(data, "data") is False


def test_validate_data_not_dict() -> None:
    """validate: non-dict data fails."""
    assert json_handler.validate_json_structure("not a dict", "data") is False


def test_validate_valid_log() -> None:
    """validate: valid log structure (list) passes."""
    assert json_handler.validate_json_structure([], "log") is True
    assert json_handler.validate_json_structure([{"entry": 1}], "log") is True


def test_validate_log_not_list() -> None:
    """validate: non-list log fails."""
    assert json_handler.validate_json_structure({"not": "a list"}, "log") is False


def test_validate_unknown_type_returns_false() -> None:
    """validate: unknown json_type returns False."""
    assert json_handler.validate_json_structure({}, "nonexistent_type") is False


def test_validate_none_input_returns_false() -> None:
    """validate: None input returns False for all types."""
    assert json_handler.validate_json_structure(None, "config") is False
    assert json_handler.validate_json_structure(None, "data") is False
    assert json_handler.validate_json_structure(None, "log") is False


# ============================================================================
# Group 3 -- get_path (3 tests)
# ============================================================================

def test_get_path_returns_path_type(tmp_path: Path) -> None:
    """get_path: returns Path or str."""
    result = json_handler.get_json_path("mymod", "config")
    assert isinstance(result, (Path, str)), "get_json_path must return Path or str"


def test_get_path_filename_pattern(tmp_path: Path) -> None:
    """get_path: filename follows module_type.json pattern."""
    result = json_handler.get_json_path("mymod", "config")
    name = Path(result).name if isinstance(result, str) else result.name
    assert name == "mymod_config.json", f"Expected mymod_config.json, got {name}"


def test_get_path_different_combos_differ(tmp_path: Path) -> None:
    """get_path: different module/type combos produce different paths."""
    path_a = str(json_handler.get_json_path("alpha", "log"))
    path_b = str(json_handler.get_json_path("beta", "data"))
    assert path_a != path_b, "Different module/type combos must produce different paths"


# ============================================================================
# Group 4 -- ensure_exists (5 tests)
# ============================================================================

def test_ensure_exists_creates_file(tmp_path: Path) -> None:
    """ensure_exists: creates file when missing."""
    result = json_handler.ensure_json_exists("ens_mod", "config")
    assert result is True
    json_dir = _json_dir_as_path(tmp_path)
    created = json_dir / "ens_mod_config.json"
    assert created.exists(), "ensure_json_exists must create the file"


def test_ensure_exists_preserves_valid(tmp_path: Path) -> None:
    """ensure_exists: does not overwrite valid existing file."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "keep_data.json"
    original = {
        "created": "2025-01-01",
        "last_updated": "2025-06-01",
        "custom_key": "preserve_me",
    }
    target.write_text(json.dumps(original), encoding="utf-8")

    json_handler.ensure_json_exists("keep", "data")

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["custom_key"] == "preserve_me", "Valid existing file must not be overwritten"


def test_ensure_exists_regenerates_corrupt(tmp_path: Path) -> None:
    """ensure_exists: regenerates corrupt JSON file."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "bad_log.json"
    target.write_bytes(b"\x00\x01NOT VALID JSON{{{")

    json_handler.ensure_json_exists("bad", "log")

    data = json.loads(target.read_text(encoding="utf-8"))
    assert isinstance(data, list), "Corrupt JSON must be regenerated to valid log (list)"


def test_ensure_exists_regenerates_invalid_structure(tmp_path: Path) -> None:
    """ensure_exists: regenerates file with invalid structure."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "wrong_config.json"
    target.write_text(json.dumps({"wrong": "structure"}), encoding="utf-8")

    json_handler.ensure_json_exists("wrong", "config")

    data = json.loads(target.read_text(encoding="utf-8"))
    assert "module_name" in data, "Invalid structure must be regenerated with correct keys"
    assert "version" in data
    assert "config" in data


def test_ensure_exists_returns_bool(tmp_path: Path) -> None:
    """ensure_exists: returns a bool."""
    result = json_handler.ensure_json_exists("bool_mod", "data")
    assert isinstance(result, bool), "ensure_json_exists must return bool"
    assert result is True


# ============================================================================
# Group 5 -- load (4 tests)
# ============================================================================

def test_load_creates_default_when_missing(tmp_path: Path) -> None:
    """load: auto-creates default when file is missing."""
    result = json_handler.load_json("fresh_mod", "log")
    assert result is not None, "load_json must auto-create and return content"
    assert isinstance(result, list), "Default log must be a list"


def test_load_returns_existing_content(tmp_path: Path) -> None:
    """load: returns content of existing file."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    payload = {"created": "2025-01-01", "last_updated": "2025-06-15", "x": 42}
    target = json_dir / "exist_data.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    result = json_handler.load_json("exist", "data")
    assert isinstance(result, dict)
    assert result["x"] == 42, "load_json must return existing file content"


def test_load_returns_dict_for_config(tmp_path: Path) -> None:
    """load: config type returns a dict."""
    result = json_handler.load_json("cfg_mod", "config")
    assert isinstance(result, dict), "load_json for config must return dict"


def test_load_returns_list_for_log(tmp_path: Path) -> None:
    """load: log type returns a list."""
    result = json_handler.load_json("log_mod", "log")
    assert isinstance(result, list), "load_json for log must return list"


# ============================================================================
# Group 6 -- save (5 tests)
# ============================================================================

def test_save_roundtrip(tmp_path: Path) -> None:
    """save: data survives save-then-load roundtrip."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    data = {"module_name": "rt", "version": "1.0.0", "config": {"key": "val"}}
    json_handler.save_json("rt", "config", data)

    loaded = json_handler.load_json("rt", "config")
    assert loaded is not None
    assert loaded["config"]["key"] == "val", "Saved data must be readable via load_json"


def test_save_returns_true(tmp_path: Path) -> None:
    """save: returns True on success."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    data = {"module_name": "sv", "version": "1.0.0", "config": {}}
    result = json_handler.save_json("sv", "config", data)
    assert result is True, "save_json must return True on success"


def test_save_rejects_invalid_structure(tmp_path: Path) -> None:
    """save: raises ValueError for invalid structure."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="[Ii]nvalid"):
        json_handler.save_json("bad", "config", {"missing": "keys"})


def test_save_data_updates_last_updated(tmp_path: Path) -> None:
    """save: auto-stamps last_updated on data type."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().date().isoformat()
    data = {"created": "2025-01-01", "last_updated": "2025-01-01"}
    json_handler.save_json("ts", "data", data)

    on_disk = json.loads(
        (json_dir / "ts_data.json").read_text(encoding="utf-8")
    )
    assert on_disk["last_updated"] == today, "Saving data type must auto-stamp last_updated"


def test_save_writes_valid_json(tmp_path: Path) -> None:
    """save: writes valid parseable JSON to disk."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    entries = [{"timestamp": "t1", "operation": "test"}]
    json_handler.save_json("disk", "log", entries)

    raw = (json_dir / "disk_log.json").read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert isinstance(parsed, list), "Saved file must be valid JSON on disk"
    assert len(parsed) == 1


# ============================================================================
# Group 7 -- log_operation (7 tests)
# ============================================================================

def test_log_operation_appends_entry(tmp_path: Path) -> None:
    """log_operation appends an entry to the log file."""
    json_handler.log_operation("deploy", module_name="logmod")
    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads(
        (json_dir / "logmod_log.json").read_text(encoding="utf-8")
    )
    assert len(log) >= 1, "log_operation must append at least one entry"
    assert log[-1]["operation"] == "deploy"


def test_log_operation_returns_bool(tmp_path: Path) -> None:
    """log_operation returns a bool."""
    result = json_handler.log_operation("test_op", module_name="boolmod")
    assert isinstance(result, bool), "log_operation must return bool"
    assert result is True


def test_log_operation_entry_has_timestamp(tmp_path: Path) -> None:
    """log_operation entries include a timestamp field."""
    json_handler.log_operation("check_ts", module_name="tsmod")
    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads(
        (json_dir / "tsmod_log.json").read_text(encoding="utf-8")
    )
    assert "timestamp" in log[-1], "Log entry must have a timestamp field"


def test_log_operation_includes_data(tmp_path: Path) -> None:
    """log_operation includes data dict when provided."""
    json_handler.log_operation(
        "with_data", data={"count": 5}, module_name="datamod"
    )
    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads(
        (json_dir / "datamod_log.json").read_text(encoding="utf-8")
    )
    assert "data" in log[-1], "Log entry must include data dict when provided"
    assert log[-1]["data"]["count"] == 5


def test_log_operation_multiple_calls_accumulate(tmp_path: Path) -> None:
    """log_operation: multiple calls accumulate entries."""
    json_handler.log_operation("first", module_name="accmod")
    json_handler.log_operation("second", module_name="accmod")
    json_handler.log_operation("third", module_name="accmod")
    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads(
        (json_dir / "accmod_log.json").read_text(encoding="utf-8")
    )
    assert len(log) >= 3, "Multiple log_operation calls must accumulate entries"
    ops = [e["operation"] for e in log[-3:]]
    assert ops == ["first", "second", "third"]


def test_log_operation_fifo_rotation(tmp_path: Path) -> None:
    """log_operation: FIFO rotation trims old entries."""
    max_entries = getattr(_mod, "MAX_LOG_ENTRIES", getattr(_mod, "max_log_entries", None))
    if max_entries is None:
        for attr in ("MAX_LOG_ENTRIES", "max_log_entries", "LOG_MAX_ENTRIES", "_MAX_LOG_ENTRIES"):
            max_entries = getattr(_mod, attr, None)
            if max_entries is not None:
                break
    if max_entries is None:
        pytest.skip("Cannot find max_log_entries constant on module")

    for i in range(max_entries + 5):
        json_handler.log_operation(f"op_{i}", module_name="fifomod")

    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads(
        (json_dir / "fifomod_log.json").read_text(encoding="utf-8")
    )
    assert len(log) <= max_entries, f"Log must not exceed {max_entries} entries"
    assert log[-1]["operation"] == f"op_{max_entries + 4}", "Most recent entry must be last"


def test_log_operation_empty_dict_not_attached(tmp_path: Path) -> None:
    """log_operation: empty dict data should not create non-empty data field."""
    json_handler.log_operation("no_data", data={}, module_name="emptymod")
    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads(
        (json_dir / "emptymod_log.json").read_text(encoding="utf-8")
    )
    entry = log[-1]
    if "data" in entry:
        assert entry["data"] == {} or entry["data"] is None


# ============================================================================
# Group 8 -- ensure_module (5 tests)
# ============================================================================

def test_ensure_module_creates_all_three(tmp_path: Path) -> None:
    """ensure_module: creates config, data, and log files."""
    if not hasattr(json_handler, "ensure_module_jsons"):
        pytest.skip("Branch does not have ensure_module_jsons")
    json_handler.ensure_module_jsons("triple")
    json_dir = _json_dir_as_path(tmp_path)
    assert (json_dir / "triple_config.json").exists(), "Config file must exist"
    assert (json_dir / "triple_data.json").exists(), "Data file must exist"
    assert (json_dir / "triple_log.json").exists(), "Log file must exist"


def test_ensure_module_returns_true(tmp_path: Path) -> None:
    """ensure_module: returns True on success."""
    if not hasattr(json_handler, "ensure_module_jsons"):
        pytest.skip("Branch does not have ensure_module_jsons")
    result = json_handler.ensure_module_jsons("retmod")
    assert result is True, "ensure_module_jsons must return True"


def test_ensure_module_files_pass_validation(tmp_path: Path) -> None:
    """ensure_module: all created files pass validation."""
    if not hasattr(json_handler, "ensure_module_jsons"):
        pytest.skip("Branch does not have ensure_module_jsons")
    json_handler.ensure_module_jsons("valid_mod")
    json_dir = _json_dir_as_path(tmp_path)

    config = json.loads(
        (json_dir / "valid_mod_config.json").read_text(encoding="utf-8")
    )
    assert json_handler.validate_json_structure(config, "config") is True

    data = json.loads(
        (json_dir / "valid_mod_data.json").read_text(encoding="utf-8")
    )
    assert json_handler.validate_json_structure(data, "data") is True

    log = json.loads(
        (json_dir / "valid_mod_log.json").read_text(encoding="utf-8")
    )
    assert json_handler.validate_json_structure(log, "log") is True


def test_ensure_module_data_has_correct_keys(tmp_path: Path) -> None:
    """ensure_module: data file has created and last_updated keys."""
    if not hasattr(json_handler, "ensure_module_jsons"):
        pytest.skip("Branch does not have ensure_module_jsons")
    json_handler.ensure_module_jsons("keymod")
    json_dir = _json_dir_as_path(tmp_path)
    data = json.loads(
        (json_dir / "keymod_data.json").read_text(encoding="utf-8")
    )
    assert "created" in data, "Data file must have 'created' key"
    assert "last_updated" in data, "Data file must have 'last_updated' key"


def test_ensure_module_log_is_empty_list(tmp_path: Path) -> None:
    """ensure_module: log file is an empty list."""
    if not hasattr(json_handler, "ensure_module_jsons"):
        pytest.skip("Branch does not have ensure_module_jsons")
    json_handler.ensure_module_jsons("listmod")
    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads(
        (json_dir / "listmod_log.json").read_text(encoding="utf-8")
    )
    assert isinstance(log, list), "Log file must be a list"
    assert len(log) == 0, "Initial log file must be an empty list"
