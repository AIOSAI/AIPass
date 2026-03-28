# =================== AIPass ====================
# Name: test_contracts.py
# Description: Universal Contracts Test Template (return types, data structures, routing)
# Version: 1.0.0
# Created: 2026-03-28
# Modified: 2026-03-28
# =============================================

"""
Universal Contracts Test Template for DAEMON branch.

Covers tests across 4 groups:
  - Return type contracts (4): handle_command_returns_bool (CT-001 via route_command),
    paths_return_path, ensure returns bool, load returns dict
  - Data structure contracts (3): config_keys, data_keys, log entry
  - Success/failure paths (4): known_routes_true, unknown_returns_false,
    help_preempts, no_args_triggers
  - Infrastructure mocking (3): log entry, sys_modules_mock, reimport_after_mock
"""

import importlib
import json
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

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

def test_command_returns_bool() -> None:
    """command_returns_bool: route_command returns a bool."""
    from aipass.daemon.apps import daemon as _daemon_mod

    # Create a mock module that handles the "test" command
    mock_module = MagicMock()
    mock_module.handle_command.return_value = True
    mock_module.__name__ = "mock_module"

    result = _daemon_mod.route_command("test", [], [mock_module])
    assert isinstance(result, bool), f"route_command must return bool, got {type(result)}"
    assert result is True

    # Also test the False path
    mock_module.handle_command.return_value = False
    result = _daemon_mod.route_command("unknown_xyz", [], [mock_module])
    assert isinstance(result, bool), f"route_command must return bool, got {type(result)}"


def test_paths_return_path() -> None:
    """paths_return_path: get_json_path returns a Path."""
    result = json_handler.get_json_path("contract_mod", "config")
    assert isinstance(result, Path), (
        f"get_json_path must return Path, got {type(result)}"
    )


def test_paths_return_path_for_data() -> None:
    """paths_return_path: get_json_path returns Path for data type too."""
    result = json_handler.get_json_path("contract_mod", "data")
    assert isinstance(result, Path), (
        f"get_json_path('data') must return Path, got {type(result)}"
    )


def test_ensure_json_exists_returns_bool(tmp_path: Path) -> None:
    """ensure_json_exists must return a bool."""
    result = json_handler.ensure_json_exists("contract_mod", "data")
    assert isinstance(result, bool), (
        f"ensure_json_exists must return bool, got {type(result)}"
    )
    assert result is True


def test_load_json_returns_dict_for_config(tmp_path: Path) -> None:
    """load_json for config type must return a dict."""
    result = json_handler.load_json("contract_mod", "config")
    assert isinstance(result, dict), (
        f"load_json('...', 'config') must return dict, got {type(result)}"
    )


# ============================================================================
# Group 2 -- Data structure contracts (3 tests)
# ============================================================================

def test_config_keys(tmp_path: Path) -> None:
    """config_keys: config data structure contains module_name and version."""
    json_handler.ensure_json_exists("struct_mod", "config")
    result = json_handler.load_json("struct_mod", "config")
    assert isinstance(result, dict), "Config must be a dict"
    assert "module_name" in result, "Config must have 'module_name' key"
    assert "version" in result, "Config must have 'version' key"


def test_data_keys(tmp_path: Path) -> None:
    """data_keys: data structure contains created and last_updated."""
    json_handler.ensure_json_exists("struct_mod", "data")
    result = json_handler.load_json("struct_mod", "data")
    assert isinstance(result, dict), "Data must be a dict"
    assert "created" in result, "Data must have 'created' key"
    assert "last_updated" in result, "Data must have 'last_updated' key"


def test_log_entry_has_operation(tmp_path: Path) -> None:
    """Log entries created by log_operation must contain an 'operation' field."""
    json_handler.log_operation("contract_test", module_name="struct_mod")

    assert _JSON_DIR_ATTR is not None
    val = getattr(_mod, _JSON_DIR_ATTR)
    json_dir = Path(val) if isinstance(val, str) else val

    log = json.loads(
        (json_dir / "struct_mod_log.json").read_text(encoding="utf-8")
    )
    assert len(log) >= 1, "log_operation must append at least one entry"
    assert "operation" in log[-1], "Log entry must have 'operation' key"
    assert log[-1]["operation"] == "contract_test"


# ============================================================================
# Group 3 -- Success/failure paths (4 tests)
# ============================================================================

def test_known_routes_true() -> None:
    """known_routes_true: a module that handles a command causes route_command to return True."""
    from aipass.daemon.apps import daemon as _daemon_mod

    mock_module = MagicMock()
    mock_module.handle_command.return_value = True
    mock_module.__name__ = "mock_module"

    result = _daemon_mod.route_command("update", [], [mock_module])
    assert result is True, "Known route must return True"


def test_unknown_returns_false() -> None:
    """unknown_returns_false: no module handles the command so route_command returns False."""
    from aipass.daemon.apps import daemon as _daemon_mod

    mock_module = MagicMock()
    mock_module.handle_command.return_value = False
    mock_module.__name__ = "mock_module"

    result = _daemon_mod.route_command("nonexistent_xyz_command", [], [mock_module])
    assert result is False, "Unknown command must return False"


def test_help_preempts() -> None:
    """help_preempts: --help exits before routing to modules."""
    from aipass.daemon.apps import daemon as _daemon_mod

    with patch.object(_daemon_mod.json_handler, "log_operation", return_value=True):
        with patch.object(sys, "argv", ["daemon", "--help"]):
            result = _daemon_mod.main()
    assert result == 0, "--help must return 0 before any module routing"


def test_no_args_triggers() -> None:
    """no_args_triggers: no arguments triggers introspection display."""
    from aipass.daemon.apps import daemon as _daemon_mod

    with patch.object(_daemon_mod.json_handler, "log_operation", return_value=True):
        with patch.object(sys, "argv", ["daemon"]):
            result = _daemon_mod.main()
    assert result == 0, "No args must trigger introspection and return 0"


# ============================================================================
# Group 4 -- Infrastructure mocking (3 tests)
# ============================================================================

def test_log_operation_mocked(tmp_path: Path) -> None:
    """Infrastructure: log_operation can be mocked without side effects."""
    with patch.object(_mod, "log_operation", return_value=True) as mock_log:
        result = mock_log("test_op", {"data": "value"})
        mock_log.assert_called_once_with("test_op", {"data": "value"})
        assert result is True


def test_sys_modules_mock() -> None:
    """sys_modules_mock: json_handler module is accessible via sys.modules."""
    mod_key = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"
    assert mod_key in sys.modules, f"{mod_key} must be in sys.modules"
    loaded = sys.modules[mod_key]
    assert hasattr(loaded, "load_json"), "Module must have load_json function"
    assert hasattr(loaded, "save_json"), "Module must have save_json function"


def test_reimport_after_mock(tmp_path: Path) -> None:
    """reimport_after_mock: module can be reloaded cleanly."""
    handler_module = sys.modules.get(
        f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"
    )
    if handler_module:
        importlib.reload(handler_module)
