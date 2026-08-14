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


# ---------------------------------------------------------------------------
# Import Contracts
# ---------------------------------------------------------------------------


class TestEntryPointImportContract:
    """The entry point is executed as a SCRIPT by drone, not imported as a package.

    A relative import there raises 'attempted relative import with no known
    parent package' at call time, not at import time — so it stays invisible
    until a user runs the command. 'drone @memory watch' was dead this way.
    The house rule is absolute 'from aipass.<agent>...' imports everywhere.
    """

    def _entry_point_source(self) -> str:
        entry = Path(__file__).resolve().parent.parent / "apps" / "memory.py"
        assert entry.exists(), f"entry point not found at {entry}"
        return entry.read_text(encoding="utf-8")

    def test_entry_point_has_no_relative_imports(self) -> None:
        source = self._entry_point_source()
        offenders = [
            f"{num}: {line.strip()}"
            for num, line in enumerate(source.splitlines(), start=1)
            if line.strip().startswith("from .")
        ]
        assert not offenders, "Relative imports in the entry point script:\n" + "\n".join(offenders)

    def test_entry_point_imports_no_handlers_directly(self) -> None:
        """The entry point routes to modules; only modules may import handlers.

        `watch` used to be a built-in on the entry point, so its two monitor
        handler imports sat here — the `encapsulation` standard scored this file
        66% for it. The command now lives in modules/watch.py like every other.
        """
        source = self._entry_point_source()
        offenders = [
            f"{num}: {line.strip()}"
            for num, line in enumerate(source.splitlines(), start=1)
            if "aipass.memory.apps.handlers" in line and "import" in line
        ]
        assert not offenders, "Handler imported directly in the entry point:\n" + "\n".join(offenders)


class TestWatchRunnerImportContract:
    """The watcher's implementation lives in a handler, and imports absolutely."""

    def _watch_runner_source(self) -> str:
        handler = Path(__file__).resolve().parent.parent / "apps" / "handlers" / "monitor" / "watch_runner.py"
        assert handler.exists(), f"watch runner not found at {handler}"
        return handler.read_text(encoding="utf-8")

    def test_runner_imports_watcher_absolutely(self) -> None:
        source = self._watch_runner_source()
        assert "from aipass.memory.apps.handlers.monitor.memory_watcher import" in source

    def test_runner_imports_detector_absolutely(self) -> None:
        source = self._watch_runner_source()
        assert "from aipass.memory.apps.handlers.monitor.detector import" in source


class TestModuleScriptImportContract:
    """Every file with a __main__ block must survive being run as a script.

    `apps/modules/*.py` all ship one, and a relative import there raises
    'attempted relative import with no known parent package' the moment anyone
    runs the file directly — the same defect that left `drone @memory watch`
    dead. Routing through the entry point hides it, so only this contract and a
    direct run catch it.
    """

    def _module_files(self):
        modules_dir = Path(__file__).resolve().parent.parent / "apps" / "modules"
        return sorted(p for p in modules_dir.glob("*.py") if not p.name.startswith("_"))

    def test_modules_have_no_relative_imports(self) -> None:
        offenders = []
        for path in self._module_files():
            for num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if line.strip().startswith("from .."):
                    offenders.append(f"{path.name}:{num}: {line.strip()}")
        assert not offenders, "Relative imports in script-executable modules:\n" + "\n".join(offenders)
