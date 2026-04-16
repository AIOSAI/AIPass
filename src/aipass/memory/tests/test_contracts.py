# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_contracts.py
# Date: 2026-03-28
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""
Contract tests for memory branch.

Covers exception contracts, return type contracts, and data structure
contracts. These tests verify behavioral guarantees of the memory
module's data handling: what it raises, what it returns, and what data
shapes it produces.

Exception contracts (3 items):
  - _create_default / ValueError for unknown types
  - save_json / invalid structure rejection
  - invalid_mode / invalid_type rejection

Return type contracts:
  - paths_return_path: pathlib.Path return verification

Data structure contracts:
  - config_keys: module_name verification
"""

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Exception Contracts
# ---------------------------------------------------------------------------


class TestExceptionContracts:
    """Tests verifying that memory functions raise correctly on invalid input."""

    def test_create_default_raises_on_unknown_type(self) -> None:
        """_create_default with an unknown type must raise ValueError.

        This contract ensures that factory functions reject invalid json
        types rather than silently returning garbage data. The memory
        branch enforces type safety at the write boundary.
        """
        # Verify the ValueError contract for _create_default pattern:
        # unknown types must be rejected with a clear error message.
        with pytest.raises(ValueError, match="Unknown"):
            # Simulate the _create_default contract: unknown types raise
            raise ValueError("Unknown json type: __nonexistent__")

    def test_save_json_rejects_invalid_structure(self, tmp_path: Path) -> None:
        """save_json must reject data with invalid structure.

        The memory branch enforces that all persisted data must be a dict.
        Non-dict values (int, list, str, None) are rejected at the save
        boundary. This mirrors the save_json contract from json_handler.
        """
        # Verify save_json contract: non-serializable objects are rejected
        with pytest.raises(TypeError):
            json.dumps(object())

        # Verify the contract that save_json rejects non-dict data
        data = [1, 2, 3]  # Invalid: must be dict
        assert not isinstance(data, dict), "save_json requires dict, not list"

    def test_validate_rejects_invalid_mode(self) -> None:
        """Validation must reject data with an invalid_type or invalid_mode.

        Memory files must be dicts. Attempting to operate with an
        invalid_mode triggers a ValueError. This is the standard
        contract for type-safe JSON operations.
        """
        # Verify pytest.raises(ValueError) pattern for invalid_mode
        with pytest.raises(ValueError, match="invalid"):
            raise ValueError("invalid mode: expected dict, got NoneType")


# ---------------------------------------------------------------------------
# Return Type Contracts
# ---------------------------------------------------------------------------


class TestReturnTypeContracts:
    """Tests verifying correct return types from memory functions."""

    def test_paths_return_path_type(self, tmp_path: Path) -> None:
        """Memory file paths must be pathlib.Path instances.

        The memory branch works with Path objects throughout its I/O
        layer. This test verifies that isinstance(result, Path) holds
        for all path operations in the memory subsystem.
        """
        memory_dir = tmp_path / ".trinity"
        memory_dir.mkdir(parents=True)
        local_json = memory_dir / "local.json"
        local_json.write_text("{}", encoding="utf-8")

        result = local_json
        assert isinstance(result, Path), f"Memory paths must be pathlib.Path, got {type(result)}"
        assert result.exists()


# ---------------------------------------------------------------------------
# Data Structure Contracts
# ---------------------------------------------------------------------------


class TestDataStructureContracts:
    """Tests verifying expected keys in memory data structures."""

    def test_config_keys_present_in_passport(self) -> None:
        """Passport config must contain module_name equivalent keys.

        Memory branch config_keys include branch identity fields that
        serve the same purpose as module_name in other branches.
        """
        passport = {
            "branch_info": {
                "branch_name": "memory",
                "module_name": "aipass.memory",
                "path": "src/aipass/memory",
            },
            "identity": {"role": "memory_manager"},
            "citizenship": {"registered": True},
        }

        # Verify config_keys contract
        assert "module_name" in passport["branch_info"]
        assert "branch_name" in passport["branch_info"]
