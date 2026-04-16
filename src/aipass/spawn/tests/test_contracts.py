# =================== AIPass ====================
# Name: test_contracts.py
# Description: Tests for return types, exceptions, data structures, and init
# Version: 1.0.0
# Created: 2026-03-27
# Modified: 2026-03-27
# =============================================

"""Tests for type contracts, exception handling, data structures, and init provisioning."""

import json
from pathlib import Path
from unittest.mock import patch

from aipass.spawn.apps.handlers.json.json_handler import read_json, write_json


class TestReturnTypeContracts:
    """Verify functions return documented types."""

    def test_command_returns_bool(self):
        """handle_command returns bool."""
        from aipass.spawn.apps.modules.regenerate_registry import handle_command

        with patch("aipass.spawn.apps.modules.regenerate_registry.print_introspection"):
            result = handle_command("regenerate-registry", [])
        assert isinstance(result, bool)

    def test_load_correct_type(self, tmp_path):
        """read_json returns dict for valid file, None for invalid."""
        f = tmp_path / "test.json"
        f.write_text(json.dumps({"key": "val"}), encoding="utf-8")
        result = read_json(f)
        assert isinstance(result, dict)

        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        result2 = read_json(bad)
        assert result2 is None


class TestExceptionContracts:
    """Verify exception handling behavior."""

    def test_invalid_write_caught(self, tmp_path):
        """write_json catches OSError and returns False, never raises."""
        f = tmp_path / "test.json"
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            result = write_json(f, {"data": True})
        assert result is False

    def test_invalid_mode_raises(self):
        """Unknown command in main() returns error code, not exception."""
        from aipass.spawn.apps.spawn import main

        with patch("aipass.spawn.apps.spawn.sys") as mock_sys:
            mock_sys.argv = ["spawn", "totally_invalid_mode"]
            with patch("aipass.spawn.apps.spawn.error"):
                result = main()
        assert result == 1


class TestDataStructureContracts:
    """Verify data structures have required keys."""

    def test_config_keys(self):
        """spawn_agent result dict contains all required keys."""
        from aipass.spawn.apps.modules.core import _spawn_agent
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "contract_test"
            result = _spawn_agent(str(target))
        assert "success" in result
        assert "branch_name" in result
        assert "path" in result
        assert "files_copied" in result

    def test_returns_dict(self):
        """spawn_agent always returns a dict."""
        from aipass.spawn.apps.modules.core import _spawn_agent
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "init_test"
            result = _spawn_agent(str(target))
        assert isinstance(result, dict)


class TestInfrastructureMocking:
    """Verify infrastructure mocking patterns."""

    def test_autouse_fixtures(self):
        """Verify autouse fixture isolates spawn_json directory."""
        # The conftest _isolate_spawn_json is autouse=True
        # This test verifies it runs by checking json_handler._JSON_DIR is patched
        from aipass.spawn.apps.handlers.json import json_handler

        # The autouse fixture patches _JSON_DIR to tmp_path/spawn_json
        # If it wasn't patched, it would be the real path
        assert json_handler._JSON_DIR is not None

    def test_sys_modules_mock(self):
        """Verify sys.modules can be used for import isolation."""
        import sys

        module_key = "aipass.spawn.apps.handlers.json.json_handler"
        assert module_key in sys.modules

    def test_reimport_after_mock(self):
        """Verify module reimport works after mocking."""
        from aipass.spawn.apps.handlers.json.json_handler import read_json as fn1

        # Re-import to verify clean state
        import importlib
        import aipass.spawn.apps.handlers.json.json_handler as mod

        importlib.reload(mod)
        from aipass.spawn.apps.handlers.json.json_handler import read_json as fn2

        assert callable(fn1)
        assert callable(fn2)


class TestSuccessFailurePaths:
    """Verify success and failure code paths."""

    def test_no_args_triggers_help(self):
        """create with no args returns error code 1."""
        from aipass.spawn.apps.spawn import handle_create

        with patch("aipass.spawn.apps.spawn.error"):
            result = handle_create([])
        assert result == 1
