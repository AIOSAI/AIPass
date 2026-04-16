# =================== AIPass ====================
# Name: test_json_handler_template.py
# Description: Universal JSON Handler Test Template (DPLAN-0059)
# Version: 1.0.0
# Created: 2026-03-25
# Modified: 2026-03-25
# =============================================

"""
Universal JSON Handler Test Template

Copy this file to any AIPass branch's tests/ directory.
Change BRANCH_MODULE below. Run with pytest.

Covers 43 tests across 8 groups:
  - _create_default / default templates (4)
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
# Change these two lines when deploying to a branch:
BRANCH_MODULE = "seedgo"  # e.g. "prax", "drone", "backup", "cli", etc.
# For commons: "commons" (import path is different: aipass -> just commons)
# For skills: "skills" (import path is different: aipass -> just skills)
# =======================================

# ---------------------------------------------------------------------------
# Dynamic import with cross-branch guard bypass
# ---------------------------------------------------------------------------
# Every branch has an import guard in apps/handlers/__init__.py that blocks
# cross-branch imports. When this template lives in its target branch, the
# guard passes naturally. When testing from devpulse (or any other branch),
# we pre-inject an empty handlers __init__ module to skip the guard.

if BRANCH_MODULE in ("commons", "skills"):
    _handler_pkg = f"{BRANCH_MODULE}.apps.handlers"
    _json_pkg = f"{BRANCH_MODULE}.apps.handlers.json"
    _json_mod_path = f"{BRANCH_MODULE}.apps.handlers.json.json_handler"
else:
    _handler_pkg = f"aipass.{BRANCH_MODULE}.apps.handlers"
    _json_pkg = f"aipass.{BRANCH_MODULE}.apps.handlers.json"
    _json_mod_path = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"

# If the handlers package is not yet loaded, inject a stub to avoid the guard.
# The stub needs __path__ set so Python treats it as a package for sub-imports.
if _handler_pkg not in sys.modules:
    _stub = types.ModuleType(_handler_pkg)
    # Resolve the real filesystem path for the handlers package
    if BRANCH_MODULE in ("commons", "skills"):
        _handlers_dir = Path(__file__).resolve().parents[3] / BRANCH_MODULE / "apps" / "handlers"
    else:
        _handlers_dir = Path(__file__).resolve().parents[3] / "aipass" / BRANCH_MODULE / "apps" / "handlers"
    _stub.__path__ = [str(_handlers_dir)]
    sys.modules[_handler_pkg] = _stub

_mod = importlib.import_module(_json_mod_path)
json_handler = _mod


# ---------------------------------------------------------------------------
# JSON_DIR variable discovery
# ---------------------------------------------------------------------------
# Branches use different names: JSON_DIR, BACKUP_JSON_DIR, PRAX_JSON_DIR,
# BRANCH_JSON_DIR, _JSON_DIR, AI_MAIL_JSON_DIR, etc.
# We find the right one at import time so the isolation fixture can patch it.

_JSON_DIR_ATTR: str | None = None
_JSON_DIR_CANDIDATES = [
    f"{BRANCH_MODULE.upper()}_JSON_DIR",  # SEEDGO_JSON_DIR, BACKUP_JSON_DIR, etc.
    "JSON_DIR",  # seedgo, daemon, memory, cli, drone
    "BRANCH_JSON_DIR",  # commons
    f"{BRANCH_MODULE}_json",  # unlikely but covered
    "_JSON_DIR",  # spawn
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
# Branches use: _create_default, _get_default_template, _get_default,
# _default_template, load_template, or per-type _default_config/_default_data/_default_log.


def _get_default_for_type(json_type: str, module_name: str = "test_mod") -> Any:
    """Call whichever default factory the branch exposes."""
    # Single-function factories (most branches)
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

    # Per-type factories (drone pattern)
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
    # load_template reads files — may raise FileNotFoundError, not ValueError
    # Per-type factories don't have a single entry point for unknown types
    return False


# ---------------------------------------------------------------------------
# Isolation fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_json_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect JSON operations to tmp_path for test isolation."""
    assert _JSON_DIR_ATTR is not None
    original_value = getattr(_mod, _JSON_DIR_ATTR)
    # Some branches store JSON_DIR as a string (commons), others as Path
    if isinstance(original_value, str):
        monkeypatch.setattr(_mod, _JSON_DIR_ATTR, str(tmp_path))
    else:
        monkeypatch.setattr(_mod, _JSON_DIR_ATTR, tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Helper: resolve JSON dir as Path regardless of branch type
# ---------------------------------------------------------------------------


def _json_dir_as_path(tmp_path: Path) -> Path:
    """Return the patched JSON dir as a Path (handles str-typed branches)."""
    assert _JSON_DIR_ATTR is not None
    val = getattr(_mod, _JSON_DIR_ATTR)
    if isinstance(val, str):
        return Path(val)
    return val


# ============================================================================
# Group 1 — _create_default / default templates (4 tests)
# ============================================================================


def test_default_config_returns_dict_with_required_keys() -> None:  # JH-001
    if not _has_default_factory():
        pytest.skip("Branch has no default factory function")
    result = _get_default_for_type("config", "test_mod")
    assert isinstance(result, dict), "Config default must be a dict"
    assert "module_name" in result, "Config default must have module_name"
    assert "version" in result, "Config default must have version"
    assert "config" in result, "Config default must have config"


def test_default_data_returns_dict_with_date_keys() -> None:  # JH-002
    if not _has_default_factory():
        pytest.skip("Branch has no default factory function")
    result = _get_default_for_type("data", "test_mod")
    assert isinstance(result, dict), "Data default must be a dict"
    assert "created" in result, "Data default must have created"
    assert "last_updated" in result, "Data default must have last_updated"


def test_default_log_returns_empty_list() -> None:  # JH-003
    if not _has_default_factory():
        pytest.skip("Branch has no default factory function")
    result = _get_default_for_type("log", "test_mod")
    assert isinstance(result, list), "Log default must be a list"
    assert len(result) == 0, "Log default must be empty"


def test_default_unknown_type_raises_value_error() -> None:  # JH-004
    if not _default_factory_raises_on_unknown():
        pytest.skip("Branch default factory does not raise ValueError for unknown types")
    with pytest.raises(ValueError, match="[Uu]nknown"):
        _get_default_for_type("__nonexistent__", "test_mod")


# ============================================================================
# Group 2 — validate_json_structure (10 tests)
# ============================================================================


def test_validate_valid_config() -> None:  # JH-005
    data = {"module_name": "x", "version": "1.0.0", "config": {}}
    assert json_handler.validate_json_structure(data, "config") is True


def test_validate_config_missing_key() -> None:  # JH-006
    data = {"module_name": "x", "version": "1.0.0"}  # missing config
    assert json_handler.validate_json_structure(data, "config") is False


def test_validate_config_not_dict() -> None:  # JH-007
    assert json_handler.validate_json_structure([1, 2, 3], "config") is False


def test_validate_valid_data() -> None:  # JH-008
    data = {"created": "2026-01-01", "last_updated": "2026-01-01"}
    assert json_handler.validate_json_structure(data, "data") is True


def test_validate_data_missing_key() -> None:  # JH-009
    data = {"created": "2026-01-01"}  # missing last_updated
    assert json_handler.validate_json_structure(data, "data") is False


def test_validate_data_not_dict() -> None:  # JH-010
    assert json_handler.validate_json_structure("not a dict", "data") is False


def test_validate_valid_log() -> None:  # JH-011
    assert json_handler.validate_json_structure([], "log") is True
    assert json_handler.validate_json_structure([{"entry": 1}], "log") is True


def test_validate_log_not_list() -> None:  # JH-012
    assert json_handler.validate_json_structure({"not": "a list"}, "log") is False


def test_validate_unknown_type_returns_false() -> None:  # JH-013
    assert json_handler.validate_json_structure({}, "nonexistent_type") is False


def test_validate_none_input_returns_false() -> None:  # JH-014
    assert json_handler.validate_json_structure(None, "config") is False
    assert json_handler.validate_json_structure(None, "data") is False
    assert json_handler.validate_json_structure(None, "log") is False


# ============================================================================
# Group 3 — get_json_path (3 tests)
# ============================================================================


def test_get_json_path_returns_path_type(tmp_path: Path) -> None:  # JH-015
    result = json_handler.get_json_path("mymod", "config")
    # Some branches return str (commons), most return Path
    assert isinstance(result, (Path, str)), "get_json_path must return Path or str"


def test_get_json_path_filename_pattern(tmp_path: Path) -> None:  # JH-016
    result = json_handler.get_json_path("mymod", "config")
    name = Path(result).name if isinstance(result, str) else result.name
    assert name == "mymod_config.json", f"Expected mymod_config.json, got {name}"


def test_get_json_path_different_combos_differ(tmp_path: Path) -> None:  # JH-017
    path_a = str(json_handler.get_json_path("alpha", "log"))
    path_b = str(json_handler.get_json_path("beta", "data"))
    assert path_a != path_b, "Different module/type combos must produce different paths"


# ============================================================================
# Group 4 — ensure_json_exists (5 tests)
# ============================================================================


def test_ensure_creates_file_when_missing(tmp_path: Path) -> None:  # JH-018
    result = json_handler.ensure_json_exists("ens_mod", "config")
    assert result is True
    json_dir = _json_dir_as_path(tmp_path)
    created = json_dir / "ens_mod_config.json"
    assert created.exists(), "ensure_json_exists must create the file"


def test_ensure_preserves_valid_existing_file(tmp_path: Path) -> None:  # JH-019
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


def test_ensure_regenerates_corrupt_json(tmp_path: Path) -> None:  # JH-020
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "bad_log.json"
    target.write_bytes(b"\x00\x01NOT VALID JSON{{{")

    json_handler.ensure_json_exists("bad", "log")

    data = json.loads(target.read_text(encoding="utf-8"))
    assert isinstance(data, list), "Corrupt JSON must be regenerated to valid log (list)"


def test_ensure_regenerates_invalid_structure(tmp_path: Path) -> None:  # JH-021
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    target = json_dir / "wrong_config.json"
    target.write_text(json.dumps({"wrong": "structure"}), encoding="utf-8")

    json_handler.ensure_json_exists("wrong", "config")

    data = json.loads(target.read_text(encoding="utf-8"))
    assert "module_name" in data, "Invalid structure must be regenerated with correct keys"
    assert "version" in data
    assert "config" in data


def test_ensure_returns_bool(tmp_path: Path) -> None:  # JH-022
    result = json_handler.ensure_json_exists("bool_mod", "data")
    assert isinstance(result, bool), "ensure_json_exists must return bool"
    assert result is True


# ============================================================================
# Group 5 — load_json (4 tests)
# ============================================================================


def test_load_creates_default_when_missing(tmp_path: Path) -> None:  # JH-023
    result = json_handler.load_json("fresh_mod", "log")
    assert result is not None, "load_json must auto-create and return content"
    assert isinstance(result, list), "Default log must be a list"


def test_load_returns_existing_content(tmp_path: Path) -> None:  # JH-024
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    payload = {"created": "2025-01-01", "last_updated": "2025-06-15", "x": 42}
    target = json_dir / "exist_data.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    result = json_handler.load_json("exist", "data")
    assert isinstance(result, dict)
    assert result["x"] == 42, "load_json must return existing file content"


def test_load_returns_dict_for_config(tmp_path: Path) -> None:  # JH-025
    result = json_handler.load_json("cfg_mod", "config")
    assert isinstance(result, dict), "load_json for config must return dict"


def test_load_returns_list_for_log(tmp_path: Path) -> None:  # JH-026
    result = json_handler.load_json("log_mod", "log")
    assert isinstance(result, list), "load_json for log must return list"


# ============================================================================
# Group 6 — save_json (5 tests)
# ============================================================================


def test_save_roundtrip(tmp_path: Path) -> None:  # JH-027
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    data = {"module_name": "rt", "version": "1.0.0", "config": {"key": "val"}}
    json_handler.save_json("rt", "config", data)

    loaded = json_handler.load_json("rt", "config")
    assert loaded is not None
    assert loaded["config"]["key"] == "val", "Saved data must be readable via load_json"


def test_save_returns_true(tmp_path: Path) -> None:  # JH-028
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    data = {"module_name": "sv", "version": "1.0.0", "config": {}}
    result = json_handler.save_json("sv", "config", data)
    assert result is True, "save_json must return True on success"


def test_save_rejects_invalid_structure(tmp_path: Path) -> None:  # JH-029
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="[Ii]nvalid"):
        json_handler.save_json("bad", "config", {"missing": "keys"})


def test_save_data_updates_last_updated(tmp_path: Path) -> None:  # JH-030
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().date().isoformat()
    data = {"created": "2025-01-01", "last_updated": "2025-01-01"}
    json_handler.save_json("ts", "data", data)

    on_disk = json.loads((json_dir / "ts_data.json").read_text(encoding="utf-8"))
    assert on_disk["last_updated"] == today, "Saving data type must auto-stamp last_updated"


def test_save_writes_valid_json_to_disk(tmp_path: Path) -> None:  # JH-031
    json_dir = _json_dir_as_path(tmp_path)
    json_dir.mkdir(parents=True, exist_ok=True)
    entries = [{"timestamp": "t1", "operation": "test"}]
    json_handler.save_json("disk", "log", entries)

    raw = (json_dir / "disk_log.json").read_text(encoding="utf-8")
    parsed = json.loads(raw)  # must not raise
    assert isinstance(parsed, list), "Saved file must be valid JSON on disk"
    assert len(parsed) == 1


# ============================================================================
# Group 7 — log_operation (7 tests)
# ============================================================================


def test_log_operation_appends_entry(tmp_path: Path) -> None:  # JH-032
    json_handler.log_operation("deploy", module_name="logmod")
    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads((json_dir / "logmod_log.json").read_text(encoding="utf-8"))
    assert len(log) >= 1, "log_operation must append at least one entry"
    assert log[-1]["operation"] == "deploy"


def test_log_operation_returns_bool(tmp_path: Path) -> None:  # JH-033
    result = json_handler.log_operation("test_op", module_name="boolmod")
    assert isinstance(result, bool), "log_operation must return bool"
    assert result is True


def test_log_operation_entry_has_timestamp(tmp_path: Path) -> None:  # JH-034
    json_handler.log_operation("check_ts", module_name="tsmod")
    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads((json_dir / "tsmod_log.json").read_text(encoding="utf-8"))
    assert "timestamp" in log[-1], "Log entry must have a timestamp field"


def test_log_operation_includes_data_when_provided(tmp_path: Path) -> None:  # JH-035
    json_handler.log_operation("with_data", data={"count": 5}, module_name="datamod")
    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads((json_dir / "datamod_log.json").read_text(encoding="utf-8"))
    assert "data" in log[-1], "Log entry must include data dict when provided"
    assert log[-1]["data"]["count"] == 5


def test_log_operation_multiple_calls_accumulate(tmp_path: Path) -> None:  # JH-039
    json_handler.log_operation("first", module_name="accmod")
    json_handler.log_operation("second", module_name="accmod")
    json_handler.log_operation("third", module_name="accmod")
    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads((json_dir / "accmod_log.json").read_text(encoding="utf-8"))
    assert len(log) >= 3, "Multiple log_operation calls must accumulate entries"
    ops = [e["operation"] for e in log[-3:]]
    assert ops == ["first", "second", "third"]


def test_log_operation_fifo_rotation(tmp_path: Path) -> None:  # JH-040
    # Find the max log entries constant
    max_entries = getattr(_mod, "MAX_LOG_ENTRIES", getattr(_mod, "max_log_entries", None))
    if max_entries is None:
        # Try to find it by checking common names
        for attr in ("MAX_LOG_ENTRIES", "max_log_entries", "LOG_MAX_ENTRIES", "_MAX_LOG_ENTRIES"):
            max_entries = getattr(_mod, attr, None)
            if max_entries is not None:
                break
    if max_entries is None:
        pytest.skip("Cannot find max_log_entries constant on module")

    # Fill to max + 5
    for i in range(max_entries + 5):
        json_handler.log_operation(f"op_{i}", module_name="fifomod")

    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads((json_dir / "fifomod_log.json").read_text(encoding="utf-8"))
    assert len(log) <= max_entries, f"Log must not exceed {max_entries} entries after rotation"
    # First entries should have been rotated out
    assert log[-1]["operation"] == f"op_{max_entries + 4}", "Most recent entry must be last"


def test_log_operation_empty_dict_not_attached(tmp_path: Path) -> None:  # JH-041
    json_handler.log_operation("no_data", data={}, module_name="emptymod")
    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads((json_dir / "emptymod_log.json").read_text(encoding="utf-8"))
    entry = log[-1]
    # Empty dict should either not be attached or be an empty dict
    # The key test: the entry should not have a non-empty "data" field from an empty input
    if "data" in entry:
        assert entry["data"] == {} or entry["data"] is None, "Empty dict data should not create non-empty data field"


# ============================================================================
# Group 8 — ensure_module_jsons (5 tests)
# ============================================================================


def test_ensure_module_jsons_creates_all_three(tmp_path: Path) -> None:  # JH-036
    if not hasattr(json_handler, "ensure_module_jsons"):
        pytest.skip("Branch does not have ensure_module_jsons")
    json_handler.ensure_module_jsons("triple")
    json_dir = _json_dir_as_path(tmp_path)
    assert (json_dir / "triple_config.json").exists(), "Config file must exist"
    assert (json_dir / "triple_data.json").exists(), "Data file must exist"
    assert (json_dir / "triple_log.json").exists(), "Log file must exist"


def test_ensure_module_jsons_returns_true(tmp_path: Path) -> None:  # JH-037
    if not hasattr(json_handler, "ensure_module_jsons"):
        pytest.skip("Branch does not have ensure_module_jsons")
    result = json_handler.ensure_module_jsons("retmod")
    assert result is True, "ensure_module_jsons must return True"


def test_ensure_module_jsons_files_pass_validation(tmp_path: Path) -> None:  # JH-038
    if not hasattr(json_handler, "ensure_module_jsons"):
        pytest.skip("Branch does not have ensure_module_jsons")
    json_handler.ensure_module_jsons("valid_mod")
    json_dir = _json_dir_as_path(tmp_path)

    config = json.loads((json_dir / "valid_mod_config.json").read_text(encoding="utf-8"))
    assert json_handler.validate_json_structure(config, "config") is True

    data = json.loads((json_dir / "valid_mod_data.json").read_text(encoding="utf-8"))
    assert json_handler.validate_json_structure(data, "data") is True

    log = json.loads((json_dir / "valid_mod_log.json").read_text(encoding="utf-8"))
    assert json_handler.validate_json_structure(log, "log") is True


def test_ensure_module_jsons_data_has_correct_keys(tmp_path: Path) -> None:  # JH-042
    if not hasattr(json_handler, "ensure_module_jsons"):
        pytest.skip("Branch does not have ensure_module_jsons")
    json_handler.ensure_module_jsons("keymod")
    json_dir = _json_dir_as_path(tmp_path)
    data = json.loads((json_dir / "keymod_data.json").read_text(encoding="utf-8"))
    assert "created" in data, "Data file must have 'created' key"
    assert "last_updated" in data, "Data file must have 'last_updated' key"


def test_ensure_module_jsons_log_is_empty_list(tmp_path: Path) -> None:  # JH-043
    if not hasattr(json_handler, "ensure_module_jsons"):
        pytest.skip("Branch does not have ensure_module_jsons")
    json_handler.ensure_module_jsons("listmod")
    json_dir = _json_dir_as_path(tmp_path)
    log = json.loads((json_dir / "listmod_log.json").read_text(encoding="utf-8"))
    assert isinstance(log, list), "Log file must be a list"
    assert len(log) == 0, "Initial log file must be an empty list"
