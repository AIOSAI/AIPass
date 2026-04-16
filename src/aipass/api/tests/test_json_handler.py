# =================== AIPass ====================
# Name: test_json_handler.py
# Description: JSON Handler Tests (from seedgo template)
# Version: 1.0.0
# Created: 2026-03-27
# Modified: 2026-03-27
# =============================================

"""
JSON Handler Tests for API branch.

Adapted from seedgo universal template (DPLAN-0059).
Covers 8 test quality categories for json_handler:
  - default_factory, validate, get_path, ensure_exists,
    load, save, log_operation, ensure_module
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
BRANCH_MODULE = "api"
# =======================================

# ---------------------------------------------------------------------------
# Dynamic import with cross-branch guard bypass
# ---------------------------------------------------------------------------

_handler_pkg = f"aipass.{BRANCH_MODULE}.apps.handlers"
_json_pkg = f"aipass.{BRANCH_MODULE}.apps.handlers.json"
_json_mod_path = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"

if _handler_pkg not in sys.modules:
    _stub = types.ModuleType(_handler_pkg)
    _handlers_dir = Path(__file__).resolve().parents[3] / "aipass" / BRANCH_MODULE / "apps" / "handlers"
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
    "_JSON_DIR",
]

for _candidate in _JSON_DIR_CANDIDATES:
    if hasattr(_mod, _candidate):
        _JSON_DIR_ATTR = _candidate
        break

if _JSON_DIR_ATTR is None:
    pytest.skip(
        f"Cannot find JSON_DIR attribute on {BRANCH_MODULE}.json_handler — tried: {_JSON_DIR_CANDIDATES}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Default factory discovery
# ---------------------------------------------------------------------------


def _get_default_for_type(json_type: str, module_name: str = "test_mod") -> Any:
    """Call whichever default factory the branch exposes."""
    for fn_name in ("_create_default", "_get_default_template", "_get_default"):
        fn = getattr(_mod, fn_name, None)
        if fn is not None:
            return fn(json_type, module_name)
    return None


def _has_default_factory() -> bool:
    for fn_name in ("_create_default", "_get_default_template", "_get_default"):
        if hasattr(_mod, fn_name):
            return True
    return False


def _default_factory_raises_on_unknown() -> bool:
    for fn_name in ("_create_default", "_get_default_template", "_get_default"):
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
    monkeypatch.setattr(_mod, _JSON_DIR_ATTR, tmp_path)
    return tmp_path


def _json_dir_as_path(tmp_path: Path) -> Path:
    assert _JSON_DIR_ATTR is not None
    val = getattr(_mod, _JSON_DIR_ATTR)
    return Path(val) if isinstance(val, str) else val


# ============================================================================
# Group 1 — _create_default / default templates
# ============================================================================


def test_default_config_returns_dict_with_required_keys() -> None:
    if not _has_default_factory():
        pytest.skip("Branch has no default factory function")
    result = _get_default_for_type("config", "test_mod")
    assert isinstance(result, dict)
    assert "module_name" in result
    assert "version" in result
    assert "config" in result


def test_default_data_returns_dict_with_date_keys() -> None:
    if not _has_default_factory():
        pytest.skip("Branch has no default factory function")
    result = _get_default_for_type("data", "test_mod")
    assert isinstance(result, dict)
    assert "created" in result
    assert "last_updated" in result


def test_default_log_returns_empty_list() -> None:
    if not _has_default_factory():
        pytest.skip("Branch has no default factory function")
    result = _get_default_for_type("log", "test_mod")
    assert isinstance(result, list)
    assert len(result) == 0


def test_default_unknown_type_raises_value_error() -> None:
    if not _default_factory_raises_on_unknown():
        pytest.skip("Branch default factory does not raise ValueError")
    with pytest.raises(ValueError, match="[Uu]nknown"):
        _get_default_for_type("__nonexistent__", "test_mod")


# ============================================================================
# Group 2 — validate_json_structure
# ============================================================================


def test_validate_valid_config() -> None:
    data = {"module_name": "x", "version": "1.0.0", "config": {}}
    assert json_handler.validate_json_structure(data, "config") is True


def test_validate_config_missing_key() -> None:
    data = {"module_name": "x", "version": "1.0.0"}
    assert json_handler.validate_json_structure(data, "config") is False


def test_validate_config_not_dict() -> None:
    assert json_handler.validate_json_structure([1, 2, 3], "config") is False


def test_validate_valid_data() -> None:
    data = {"created": "2026-01-01", "last_updated": "2026-01-01"}
    assert json_handler.validate_json_structure(data, "data") is True


def test_validate_data_missing_key() -> None:
    data = {"created": "2026-01-01"}
    assert json_handler.validate_json_structure(data, "data") is False


def test_validate_data_not_dict() -> None:
    assert json_handler.validate_json_structure("not a dict", "data") is False


def test_validate_valid_log() -> None:
    assert json_handler.validate_json_structure([], "log") is True
    assert json_handler.validate_json_structure([{"entry": 1}], "log") is True


def test_validate_log_not_list() -> None:
    assert json_handler.validate_json_structure({"not": "a list"}, "log") is False


def test_validate_unknown_type_returns_false() -> None:
    assert json_handler.validate_json_structure({}, "nonexistent_type") is False


def test_validate_none_input_returns_false() -> None:
    assert json_handler.validate_json_structure(None, "config") is False
    assert json_handler.validate_json_structure(None, "data") is False
    assert json_handler.validate_json_structure(None, "log") is False


# ============================================================================
# Group 3 — get_json_path
# ============================================================================


def test_get_json_path_returns_path_type(tmp_path: Path) -> None:
    result = json_handler.get_json_path("mymod", "config")
    assert isinstance(result, (Path, str))


def test_get_json_path_filename_pattern(tmp_path: Path) -> None:
    result = json_handler.get_json_path("mymod", "config")
    name = Path(result).name if isinstance(result, str) else result.name
    assert name == "mymod_config.json"


def test_get_json_path_different_combos_differ(tmp_path: Path) -> None:
    path_a = str(json_handler.get_json_path("alpha", "log"))
    path_b = str(json_handler.get_json_path("beta", "data"))
    assert path_a != path_b


# ============================================================================
# Group 4 — ensure_json_exists
# ============================================================================


def test_ensure_creates_file_when_missing(tmp_path: Path) -> None:
    result = json_handler.ensure_json_exists("ens_mod", "config")
    assert result is True
    json_dir = _json_dir_as_path(tmp_path)
    created = json_dir / "ens_mod_config.json"
    assert created.exists()


def test_ensure_preserves_valid_existing_file(tmp_path: Path) -> None:
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "keep_data.json"
    original = {"created": "2025-01-01", "last_updated": "2025-06-01", "custom_key": "preserve_me"}
    target.write_text(json.dumps(original), encoding="utf-8")

    json_handler.ensure_json_exists("keep", "data")

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["custom_key"] == "preserve_me"


def test_ensure_regenerates_corrupt_json(tmp_path: Path) -> None:
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "bad_log.json"
    target.write_bytes(b"\x00\x01NOT VALID JSON{{{")

    json_handler.ensure_json_exists("bad", "log")

    data = json.loads(target.read_text(encoding="utf-8"))
    assert isinstance(data, list)


def test_ensure_regenerates_invalid_structure(tmp_path: Path) -> None:
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "wrong_config.json"
    target.write_text(json.dumps({"wrong": "structure"}), encoding="utf-8")

    json_handler.ensure_json_exists("wrong", "config")

    data = json.loads(target.read_text(encoding="utf-8"))
    assert "module_name" in data
    assert "version" in data
    assert "config" in data


def test_ensure_returns_bool(tmp_path: Path) -> None:
    result = json_handler.ensure_json_exists("bool_mod", "data")
    assert isinstance(result, bool)
    assert result is True


# ============================================================================
# Group 5 — load_json
# ============================================================================


def test_load_creates_default_when_missing(tmp_path: Path) -> None:
    result = json_handler.load_json("fresh_mod", "log")
    assert result is not None
    assert isinstance(result, list)


def test_load_returns_existing_content(tmp_path: Path) -> None:
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    payload = {"created": "2025-01-01", "last_updated": "2025-06-15", "x": 42}
    target = json_dir / "exist_data.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    result = json_handler.load_json("exist", "data")
    assert isinstance(result, dict)
    assert result["x"] == 42


def test_load_returns_dict_for_config(tmp_path: Path) -> None:
    result = json_handler.load_json("cfg_mod", "config")
    assert isinstance(result, dict)


def test_load_returns_list_for_log(tmp_path: Path) -> None:
    result = json_handler.load_json("log_mod", "log")
    assert isinstance(result, list)


# ============================================================================
# Group 6 — save_json
# ============================================================================


def test_save_roundtrip(tmp_path: Path) -> None:
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    data = {"module_name": "rt", "version": "1.0.0", "config": {"key": "val"}}
    json_handler.save_json("rt", "config", data)

    loaded = json_handler.load_json("rt", "config")
    assert loaded is not None
    assert loaded["config"]["key"] == "val"


def test_save_returns_true(tmp_path: Path) -> None:
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    data = {"module_name": "sv", "version": "1.0.0", "config": {}}
    result = json_handler.save_json("sv", "config", data)
    assert result is True


def test_save_rejects_invalid_structure(tmp_path: Path) -> None:
    """save_json returns False for invalid structure."""
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    result = json_handler.save_json("bad", "config", {"missing": "keys"})
    assert result is False


def test_save_data_updates_last_updated(tmp_path: Path) -> None:
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().date().isoformat()
    data = {"created": "2025-01-01", "last_updated": "2025-01-01"}
    json_handler.save_json("ts", "data", data)

    on_disk = json.loads((json_dir / "ts_data.json").read_text(encoding="utf-8"))
    assert on_disk["last_updated"] == today


def test_save_writes_valid_json_to_disk(tmp_path: Path) -> None:
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    entries = [{"timestamp": "t1", "operation": "test"}]
    json_handler.save_json("disk", "log", entries)

    raw = (json_dir / "disk_log.json").read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert isinstance(parsed, list)
    assert len(parsed) == 1


# ============================================================================
# Group 7 — log_operation
# ============================================================================


def test_log_operation_appends_entry(tmp_path: Path) -> None:
    json_handler.log_operation("deploy", module_name="logmod")
    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads((json_dir / "logmod_log.json").read_text(encoding="utf-8"))
    assert len(log) >= 1
    assert log[-1]["operation"] == "deploy"


def test_log_operation_returns_bool(tmp_path: Path) -> None:
    result = json_handler.log_operation("test_op", module_name="boolmod")
    assert isinstance(result, bool)
    assert result is True


def test_log_operation_entry_has_timestamp(tmp_path: Path) -> None:
    json_handler.log_operation("check_ts", module_name="tsmod")
    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads((json_dir / "tsmod_log.json").read_text(encoding="utf-8"))
    assert "timestamp" in log[-1]


def test_log_operation_includes_data_when_provided(tmp_path: Path) -> None:
    json_handler.log_operation("with_data", data={"count": 5}, module_name="datamod")
    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads((json_dir / "datamod_log.json").read_text(encoding="utf-8"))
    assert "data" in log[-1]
    assert log[-1]["data"]["count"] == 5


def test_log_operation_multiple_calls_accumulate(tmp_path: Path) -> None:
    json_handler.log_operation("first", module_name="accmod")
    json_handler.log_operation("second", module_name="accmod")
    json_handler.log_operation("third", module_name="accmod")
    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads((json_dir / "accmod_log.json").read_text(encoding="utf-8"))
    assert len(log) >= 3
    ops = [e["operation"] for e in log[-3:]]
    assert ops == ["first", "second", "third"]


# ============================================================================
# Group 8 — ensure_module_jsons
# ============================================================================


def test_ensure_module_jsons_creates_all_three(tmp_path: Path) -> None:
    json_handler.ensure_module_jsons("triple")
    json_dir = _json_dir_as_path(tmp_path)
    assert (json_dir / "triple_config.json").exists()
    assert (json_dir / "triple_data.json").exists()
    assert (json_dir / "triple_log.json").exists()


def test_ensure_module_jsons_returns_true(tmp_path: Path) -> None:
    result = json_handler.ensure_module_jsons("retmod")
    assert result is True


def test_ensure_module_jsons_files_pass_validation(tmp_path: Path) -> None:
    json_handler.ensure_module_jsons("valid_mod")
    json_dir = _json_dir_as_path(tmp_path)

    config = json.loads((json_dir / "valid_mod_config.json").read_text(encoding="utf-8"))
    assert json_handler.validate_json_structure(config, "config") is True

    data = json.loads((json_dir / "valid_mod_data.json").read_text(encoding="utf-8"))
    assert json_handler.validate_json_structure(data, "data") is True

    log = json.loads((json_dir / "valid_mod_log.json").read_text(encoding="utf-8"))
    assert json_handler.validate_json_structure(log, "log") is True


def test_ensure_module_jsons_data_has_correct_keys(tmp_path: Path) -> None:
    json_handler.ensure_module_jsons("keymod")
    json_dir = _json_dir_as_path(tmp_path)
    data = json.loads((json_dir / "keymod_data.json").read_text(encoding="utf-8"))
    assert "created" in data
    assert "last_updated" in data


def test_ensure_module_jsons_log_is_empty_list(tmp_path: Path) -> None:
    json_handler.ensure_module_jsons("listmod")
    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads((json_dir / "listmod_log.json").read_text(encoding="utf-8"))
    assert isinstance(log, list)
    assert len(log) == 0
