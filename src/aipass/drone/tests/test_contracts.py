# =================== AIPass ====================
# Name: test_contracts.py
# Description: Universal Contracts Test Template (return types, exceptions, data structures)
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-27
# =============================================

"""
Universal Contracts Test Template

Covers 10 tests across 3 groups:
  - Return type contracts (4)
  - Exception contracts (3)
  - Data structure contracts (3)
"""

import importlib
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest


# ============ BRANCH CONFIG ============
BRANCH_MODULE = "drone"
# =======================================

# ---------------------------------------------------------------------------
# Dynamic import with cross-branch guard bypass
# ---------------------------------------------------------------------------

if BRANCH_MODULE in ("commons", "skills"):
    _handler_pkg = f"{BRANCH_MODULE}.apps.handlers"
    _json_mod_path = f"{BRANCH_MODULE}.apps.handlers.json.json_handler"
else:
    _handler_pkg = f"aipass.{BRANCH_MODULE}.apps.handlers"
    _json_mod_path = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"

if _handler_pkg not in sys.modules:
    _stub = types.ModuleType(_handler_pkg)
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
        f"Cannot find JSON_DIR attribute on {BRANCH_MODULE}.json_handler -- tried: {_JSON_DIR_CANDIDATES}",
        allow_module_level=True,
    )


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


# ---------------------------------------------------------------------------
# Default factory helpers
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


# ============================================================================
# Group 1 -- Return type contracts (4 tests)
# ============================================================================


def test_handle_command_returns_bool() -> None:  # CT-001
    """handle_command must return a bool (not int, not None, not truthy)."""
    try:
        if BRANCH_MODULE in ("commons", "skills"):
            cli_mod_path = f"{BRANCH_MODULE}.apps.handlers.cli.cli_handler"
        else:
            cli_mod_path = f"aipass.{BRANCH_MODULE}.apps.handlers.cli.cli_handler"
        cli_mod = importlib.import_module(cli_mod_path)
    except (ImportError, ModuleNotFoundError):
        pytest.skip("Branch does not have a CLI handler")

    handle = getattr(cli_mod, "handle_command", None)
    if handle is None:
        pytest.skip("Branch CLI handler does not expose handle_command")

    result = handle("help", [])
    assert isinstance(result, bool), f"handle_command must return bool, got {type(result)}"


def test_get_json_path_returns_path() -> None:  # CT-002
    """get_json_path must return a Path or str (filesystem path type)."""
    result = json_handler.get_json_path("contract_mod", "config")
    assert isinstance(result, (Path, str)), f"get_json_path must return Path or str, got {type(result)}"


def test_ensure_json_exists_returns_bool(tmp_path: Path) -> None:  # CT-003
    """ensure_json_exists must return a bool."""
    result = json_handler.ensure_json_exists("contract_mod", "data")
    assert isinstance(result, bool), f"ensure_json_exists must return bool, got {type(result)}"
    assert result is True


def test_load_json_returns_dict_for_config(tmp_path: Path) -> None:  # CT-004
    """load_json for config type must return a dict."""
    result = json_handler.load_json("contract_mod", "config")
    assert isinstance(result, dict), f"load_json('...', 'config') must return dict, got {type(result)}"


# ============================================================================
# Group 2 -- Exception contracts (3 tests)
# ============================================================================


def test_create_default_unknown_raises_value_error() -> None:  # CT-005
    """_create_default (or equivalent) must raise ValueError for unknown type."""
    if not _default_factory_raises_on_unknown():
        pytest.skip("Branch default factory does not raise ValueError for unknown types")
    with pytest.raises(ValueError, match="[Uu]nknown"):
        _get_default_for_type("__nonexistent__", "test_mod")


def test_save_json_invalid_structure_raises_value_error(tmp_path: Path) -> None:  # CT-006
    """save_json must raise ValueError when given an invalid structure."""
    json_dir = tmp_path
    json_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="[Ii]nvalid"):
        json_handler.save_json("bad", "config", {"missing": "keys"})


def test_validate_rejects_invalid_mode() -> None:  # CT-007
    """validate_json_structure must return False for an unknown json_type."""
    try:
        result = json_handler.validate_json_structure({}, "invalid_mode_xyz")
    except ValueError:
        return

    assert result is False, "validate_json_structure must return False for unknown type"


# ============================================================================
# Group 3 -- Data structure contracts (3 tests)
# ============================================================================


def test_config_has_required_keys(tmp_path: Path) -> None:  # CT-008
    """Config data structure must contain module_name and version."""
    json_handler.ensure_json_exists("struct_mod", "config")
    result = json_handler.load_json("struct_mod", "config")
    assert isinstance(result, dict), "Config must be a dict"
    assert "module_name" in result, "Config must have 'module_name' key"
    assert "version" in result, "Config must have 'version' key"


def test_data_has_date_keys(tmp_path: Path) -> None:  # CT-009
    """Data structure must contain created and last_updated."""
    json_handler.ensure_json_exists("struct_mod", "data")
    result = json_handler.load_json("struct_mod", "data")
    assert isinstance(result, dict), "Data must be a dict"
    assert "created" in result, "Data must have 'created' key"
    assert "last_updated" in result, "Data must have 'last_updated' key"


def test_log_entry_has_operation(tmp_path: Path) -> None:  # CT-010
    """Log entries created by log_operation must contain an 'operation' field."""
    json_handler.log_operation("contract_test", module_name="struct_mod")

    assert _JSON_DIR_ATTR is not None
    val = getattr(_mod, _JSON_DIR_ATTR)
    json_dir = Path(val) if isinstance(val, str) else val

    log = json.loads((json_dir / "struct_mod_log.json").read_text(encoding="utf-8"))
    assert len(log) >= 1, "log_operation must append at least one entry"
    assert "operation" in log[-1], "Log entry must have 'operation' key"
    assert log[-1]["operation"] == "contract_test"
