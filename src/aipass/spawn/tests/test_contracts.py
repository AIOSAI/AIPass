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

from aipass.spawn.apps.handlers.json.json_handler import read_json


class TestReturnTypeContracts:
    """Verify functions return documented types."""

    def test_command_returns_bool(self):
        """handle_command answers True for a verb it owns - the value, not just the type.

        Measured 2026-09-08: True. The bool is the ROUTED / NOT-ROUTED answer the
        caller switches on, so a handler that started returning False for its own
        verb would have passed the old isinstance pin unnoticed.
        """
        from aipass.spawn.apps.modules.regenerate_registry import handle_command

        with patch("aipass.spawn.apps.modules.regenerate_registry.print_introspection"):
            result = handle_command("regenerate-registry", [])
        assert isinstance(result, bool)
        assert result is True, result
        assert handle_command("not-a-spawn-verb", []) is False

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
    """Verify exception handling behavior.

    write_json's OSError contract used to be pinned here by patching os.write.
    The fleet service (DPLAN-0325) writes through a NamedTemporaryFile, so that
    patch reached nothing and the test passed a True back at an assertion
    expecting False. It is in tests/.archive/; the claim is re-pinned against a
    real unwritable target in tests/test_json_handler.py.
    """

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
        """The VALUES a successful mint reports, beside the key contract above.

        ``test_config_keys`` pins which keys are present; this pins what they say.
        Measured 2026-09-08 on a real mint into a temp dir: success True,
        branch_name upper-cased from the directory, path the target it was given,
        and every non-skipped file the citizen template holds.

        ``files_copied`` used to be pinned to a bare 49 — a fact about this
        machine's template on the day it was measured, not about the copy
        rule. It is measured here instead, the same way copy_template counts:
        every file under the template directory whose relative path does not
        touch a name in SKIP_NAMES. And ``path`` is resolved on both sides —
        _spawn_agent resolves the target it is given, so an unresolved
        ``target`` built from an 8.3 short temp-dir name (Windows) would never
        compare equal to the resolved path it actually returns.
        """
        from aipass.spawn.apps.handlers.class_registry import get_template_dir
        from aipass.spawn.apps.handlers.file_ops import SKIP_NAMES
        from aipass.spawn.apps.modules.core import _spawn_agent
        import tempfile

        template = get_template_dir()
        expected_files_copied = sum(
            1
            for p in template.rglob("*")
            if p.is_file() and not any(part in SKIP_NAMES for part in p.relative_to(template).parts)
        )

        with tempfile.TemporaryDirectory() as td:
            target = (Path(td) / "init_test").resolve()
            result = _spawn_agent(str(target))
            assert isinstance(result, dict)
            assert result["success"] is True, result.get("error")
            assert result["branch_name"] == "INIT_TEST", result["branch_name"]
            assert Path(result["path"]) == target, result["path"]
            assert result["files_copied"] == expected_files_copied, result["files_copied"]
            assert result["validation_issues"] == [], result["validation_issues"]


class TestInfrastructureMocking:
    """Verify infrastructure mocking patterns."""

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
