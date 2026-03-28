# =================== AIPass ====================
# Name: test_contracts.py
# Description: Contract Tests (return types, exceptions, data structures)
# Version: 1.0.0
# Created: 2026-03-28
# Modified: 2026-03-28
# =============================================

"""
Contract Tests for skills branch.

Covers 3 groups:
  - Return type contracts (4): command_returns_bool, paths_return_path,
    ensure_returns_bool, load_correct_type
  - Exception contracts (3): create_default_raises, save_invalid_raises,
    invalid_mode_raises
  - Data structure contracts (3): config_keys, data_keys, log_entry_field
"""

import importlib
import json
from pathlib import Path


BRANCH_MODULE = "skills"
_json_mod_path = f"{BRANCH_MODULE}.apps.handlers.json.json_handler"


def _import_handler():
    """Import json_handler."""
    return importlib.import_module(_json_mod_path)


# ============================================================================
# Group 1 -- Return type contracts
# ============================================================================

def test_handle_command_returns_bool() -> None:
    """handle_command must return a bool (command_returns_bool)."""
    from skills.apps.skills import handle_command
    result = handle_command("--help")
    assert isinstance(result, bool)


def test_get_json_path_returns_path() -> None:
    """get_json_path must return a Path (paths_return_path contract)."""
    handler = _import_handler()
    result = handler.get_json_path("contract_mod", "config")
    assert isinstance(result, Path)


def test_ensure_json_exists_returns_bool() -> None:
    """ensure_json_exists must return a bool."""
    handler = _import_handler()
    result = handler.ensure_json_exists("contract_mod", "data")
    assert isinstance(result, bool)
    assert result is True


def test_load_json_returns_dict_for_config() -> None:
    """load_json for config type must return a dict."""
    handler = _import_handler()
    result = handler.load_json("contract_mod", "config")
    assert isinstance(result, dict)


# ============================================================================
# Group 2 -- Exception contracts
# ============================================================================

def test_save_json_invalid_structure_rejects() -> None:
    """save_json must reject invalid structure -- save_invalid_raises contract."""
    handler = _import_handler()
    result = handler.save_json("bad", "config", {"missing": "keys"})
    assert result is False


def test_validate_rejects_invalid_mode() -> None:
    """validate_json_structure must return False for unknown json_type (invalid_mode_raises)."""
    handler = _import_handler()
    try:
        result = handler.validate_json_structure({}, "invalid_mode_xyz")
    except ValueError:
        return
    assert result is False


def test_save_invalid_raises_no_exception() -> None:
    """save_json with invalid data returns False, no exception (save_invalid_raises)."""
    handler = _import_handler()
    result = handler.save_json("x", "config", "not_a_dict")
    assert result is False


# ============================================================================
# Group 3 -- Data structure contracts
# ============================================================================

def test_config_has_required_keys() -> None:
    """Config must contain module_name and version (config_keys)."""
    handler = _import_handler()
    handler.ensure_json_exists("struct_mod", "config")
    result = handler.load_json("struct_mod", "config")
    assert isinstance(result, dict)
    assert "module_name" in result
    assert "version" in result


def test_data_has_date_keys() -> None:
    """Data structure must contain created and last_updated (data_keys)."""
    handler = _import_handler()
    handler.ensure_json_exists("struct_mod", "data")
    result = handler.load_json("struct_mod", "data")
    assert isinstance(result, dict)
    assert "created" in result
    assert "last_updated" in result


def test_log_entry_has_operation_field() -> None:
    """Log entries must contain an 'operation' field (log_entry_field)."""
    handler = _import_handler()
    handler.log_operation("contract_test", module_name="struct_mod")

    log_path = handler.get_json_path("struct_mod", "log")
    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(log) >= 1
    assert "operation" in log[-1]
    assert log[-1]["operation"] == "contract_test"
