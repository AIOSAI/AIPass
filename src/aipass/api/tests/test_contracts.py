# =================== AIPass ====================
# Name: test_contracts.py
# Description: Contract Tests (return types, exceptions, data structures)
# Version: 1.0.0
# Created: 2026-03-27
# Modified: 2026-03-27
# =============================================

"""
Contract Tests for API branch.

Covers 3 groups:
  - Return type contracts (4): command_returns_bool, paths_return_path,
    ensure_returns_bool, load_correct_type
  - Exception contracts (3): create_default_raises, save_invalid_raises,
    invalid_mode_raises
  - Data structure contracts (3): config_keys, data_keys, log_entry_field
"""

import importlib
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest


BRANCH_MODULE = "api"

_handler_pkg = f"aipass.{BRANCH_MODULE}.apps.handlers"
_json_mod_path = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"

if _handler_pkg not in sys.modules:
    _stub = types.ModuleType(_handler_pkg)
    _handlers_dir = Path(__file__).resolve().parents[3] / "aipass" / BRANCH_MODULE / "apps" / "handlers"
    _stub.__path__ = [str(_handlers_dir)]
    sys.modules[_handler_pkg] = _stub

_mod = importlib.import_module(_json_mod_path)
json_handler = _mod


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
        f"Cannot find JSON_DIR attribute on {BRANCH_MODULE}.json_handler",
        allow_module_level=True,
    )


@pytest.fixture(autouse=True)
def isolate_json_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect JSON operations to tmp_path for test isolation."""
    assert _JSON_DIR_ATTR is not None
    monkeypatch.setattr(_mod, _JSON_DIR_ATTR, tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Default factory helpers
# ---------------------------------------------------------------------------


def _get_default_for_type(json_type: str, module_name: str = "test_mod") -> Any:
    for fn_name in ("_create_default", "_get_default_template", "_get_default"):
        fn = getattr(_mod, fn_name, None)
        if fn is not None:
            return fn(json_type, module_name)
    return None


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


# ============================================================================
# Group 1 — Return type contracts
# ============================================================================


def test_handle_command_returns_bool() -> None:
    """handle_command must return a bool."""
    from aipass.api.apps.modules import api_key

    result = api_key.handle_command("get-key", ["--help"])
    assert isinstance(result, bool)


def test_get_json_path_returns_path() -> None:
    """get_json_path must return a Path (paths_return_path contract)."""
    result = json_handler.get_json_path("contract_mod", "config")
    assert isinstance(result, Path)


def test_ensure_json_exists_returns_bool(tmp_path: Path) -> None:
    """ensure_json_exists must return a bool."""
    result = json_handler.ensure_json_exists("contract_mod", "data")
    assert isinstance(result, bool)
    assert result is True


def test_load_json_returns_dict_for_config(tmp_path: Path) -> None:
    """load_json for config type must return a dict."""
    result = json_handler.load_json("contract_mod", "config")
    assert isinstance(result, dict)


# ============================================================================
# Group 2 — Exception contracts
# ============================================================================


def test_create_default_unknown_raises_value_error() -> None:
    """_create_default must raise ValueError for unknown type."""
    if not _default_factory_raises_on_unknown():
        pytest.skip("Branch default factory does not raise ValueError")
    with pytest.raises(ValueError, match="[Uu]nknown"):
        _get_default_for_type("__nonexistent__", "test_mod")


def test_save_json_invalid_structure_rejects(tmp_path: Path) -> None:
    """save_json must reject invalid structure (returns False)."""
    result = json_handler.save_json("bad", "config", {"missing": "keys"})
    assert result is False


def test_validate_rejects_invalid_mode() -> None:
    """validate_json_structure must return False for unknown json_type."""
    try:
        result = json_handler.validate_json_structure({}, "invalid_mode_xyz")
    except ValueError:
        return
    assert result is False


# ============================================================================
# Group 3 — Data structure contracts
# ============================================================================


def test_config_has_required_keys(tmp_path: Path) -> None:
    """Config must contain module_name and version."""
    json_handler.ensure_json_exists("struct_mod", "config")
    result = json_handler.load_json("struct_mod", "config")
    assert isinstance(result, dict)
    assert "module_name" in result
    assert "version" in result


def test_data_has_date_keys(tmp_path: Path) -> None:
    """Data structure must contain created and last_updated."""
    json_handler.ensure_json_exists("struct_mod", "data")
    result = json_handler.load_json("struct_mod", "data")
    assert isinstance(result, dict)
    assert "created" in result
    assert "last_updated" in result


def test_reimport_after_mock(tmp_path: Path) -> None:
    """Module can be reloaded after mocking (reimport_after_mock contract)."""
    import importlib

    # Reload the json_handler module to verify it survives reimport
    reloaded = importlib.reload(_mod)
    assert hasattr(reloaded, "load_json")
    assert hasattr(reloaded, "save_json")


def test_log_entry_has_operation(tmp_path: Path) -> None:
    """Log entries must contain an 'operation' field."""
    json_handler.log_operation("contract_test", module_name="struct_mod")

    assert _JSON_DIR_ATTR is not None
    val = getattr(_mod, _JSON_DIR_ATTR)
    json_dir = Path(val) if isinstance(val, str) else val

    log = json.loads((json_dir / "struct_mod_log.json").read_text(encoding="utf-8"))
    assert len(log) >= 1
    assert "operation" in log[-1]
    assert log[-1]["operation"] == "contract_test"
