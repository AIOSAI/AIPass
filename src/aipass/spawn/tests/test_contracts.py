# =================== AIPass ====================
# Name: test_contracts.py
# Description: Tests for return types, exceptions, data structures, and init
# Version: 1.0.2
# Created: 2026-03-27
# Modified: 2026-09-29
# =============================================

"""Tests for apps/modules/core.py's mint contract and apps/handlers/json/json_handler.py's return/exception types."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/modules/regenerate_registry.py and apps/spawn.py parse and import
# seedgo: no-test-needed(documentation) — docstrings on handle_command, spawn_agent, and read_json

import json
from pathlib import Path
from unittest.mock import patch

from aipass.spawn.apps.handlers.class_registry import get_template_dir
from aipass.spawn.apps.handlers.file_ops import SKIP_NAMES
from aipass.spawn.apps.handlers.json.json_handler import read_json
from aipass.spawn.apps.modules.core import spawn_agent
from aipass.spawn.apps.modules.regenerate_registry import handle_command
from aipass.spawn.apps.spawn import handle_create, main


class TestReturnTypeContracts:
    """Verify functions return documented types."""

    def test_command_returns_bool(self):
        """handle_command answers True for a verb it owns - the value, not just the type.

        Measured 2026-09-08: True. The bool is the ROUTED / NOT-ROUTED answer the
        caller switches on, so a handler that started returning False for its own
        verb would have passed the old isinstance pin unnoticed.

        Mutant: no-args arm's print_introspection() -> pass -> red.
        """

        with patch("aipass.spawn.apps.modules.regenerate_registry.print_introspection") as mock_intro:
            result = handle_command("regenerate-registry", [])
        mock_intro.assert_called_once_with()
        assert isinstance(result, bool)
        assert result is True, result
        assert handle_command("not-a-spawn-verb", []) is False

    def test_load_correct_type(self, tmp_path):
        """read_json returns dict for valid file, None for invalid.

        Mutant: json_service.read_json returns {**json.load(handle), "mutant": 1} -> red.
        """
        f = tmp_path / "test.json"
        f.write_text(json.dumps({"key": "val"}), encoding="utf-8")
        result = read_json(f)
        assert isinstance(result, dict)
        assert result == {"key": "val"}, result

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

    def test_invalid_mode_raises(self, monkeypatch):
        """Unknown command in main() returns error code, not exception.

        main() takes no argv, so the string form of the sys.argv patch stands in.

        Mutant: error(f"Unknown command: {command}", ...) -> error(f"Unknown: {command}", ...) -> red.
        """

        monkeypatch.setattr("sys.argv", ["spawn", "totally_invalid_mode"])
        with patch("aipass.spawn.apps.spawn.error") as mock_error:
            result = main()
        assert result == 1
        mock_error.assert_called_once()
        assert mock_error.call_args.args[0] == "Unknown command: totally_invalid_mode"


class TestDataStructureContracts:
    """Verify data structures have required keys."""

    def test_config_keys(self, tmp_path):
        """spawn_agent result dict contains all required keys.

        Minted into tmp_path against a tmp_path registry — never the live one.
        """
        target = tmp_path / "contract_test"
        result = spawn_agent(str(target), registry_path=tmp_path / "AIPASS_REGISTRY.json")
        assert "success" in result
        assert "branch_name" in result
        assert "path" in result
        assert "files_copied" in result

    def test_returns_dict(self, tmp_path):
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
        spawn_agent resolves the target it is given, so an unresolved
        ``target`` built from an 8.3 short temp-dir name (Windows) would never
        compare equal to the resolved path it actually returns.
        """
        template = get_template_dir()
        expected_files_copied = sum(
            1
            for p in template.rglob("*")
            if p.is_file() and not any(part in SKIP_NAMES for part in p.relative_to(template).parts)
        )

        target = (tmp_path / "init_test").resolve()
        result = spawn_agent(str(target), registry_path=tmp_path.resolve() / "AIPASS_REGISTRY.json")
        assert isinstance(result, dict)
        assert result["success"] is True, result.get("error")
        assert result["branch_name"] == "INIT_TEST", result["branch_name"]
        assert Path(result["path"]) == target, result["path"]
        assert result["files_copied"] == expected_files_copied, result["files_copied"]
        assert result["validation_issues"] == [], result["validation_issues"]
        # The newborn still gets its dropbox and .archive, each with the shipped
        # README, placeholders filled: the walks that skip them after the mint
        # must not reach the copy.
        for sandbox in ("dropbox", ".archive"):
            assert (target / sandbox / "README.md").is_file(), sandbox
            shipped = (template / sandbox / "README.md").read_text(encoding="utf-8").splitlines()
            minted = (target / sandbox / "README.md").read_text(encoding="utf-8").splitlines()
            assert minted[0] == shipped[0]
            assert len(minted) == len(shipped)


class TestInfrastructureMocking:
    """Verify infrastructure mocking patterns."""

    def test_sys_modules_mock(self):
        """Verify sys.modules can be used for import isolation."""
        import sys

        module_key = "aipass.spawn.apps.handlers.json.json_handler"
        assert module_key in sys.modules


class TestSuccessFailurePaths:
    """Verify success and failure code paths."""

    def test_no_args_triggers_help(self):
        """create with no args returns error code 1.

        Mutant: error("target path required", ...) -> error("path required", ...) -> red.
        """

        with patch("aipass.spawn.apps.spawn.error") as mock_error:
            result = handle_create([])
        assert result == 1
        mock_error.assert_called_once()
        assert mock_error.call_args.args[0] == "target path required"
