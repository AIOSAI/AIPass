# =================== AIPass ====================
# Name: test_checkers_batch7_modules.py
# Description: modules_check sub-functions and the door shape (split from test_checkers_batch7.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/aipass_standards/modules_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that each checker in handlers/aipass_standards/ parses and imports

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import modules_check
from aipass.seedgo.apps.handlers.aipass_standards.modules_check import (
    check_file_size,
    check_handle_command,
    check_no_business_logic,
    check_no_direct_file_ops,
    check_thin_orchestration,
)
from aipass.seedgo.tests.support_checkers_batch7 import _lines

pytestmark = pytest.mark.usefixtures("_pin_bypass_log")


# ===========================================================================
# 4. modules_check sub-functions
# ===========================================================================


# -- check_handle_command ----------------------------------------------------


class TestCheckHandleCommand:
    """Tests for check_handle_command."""

    def test_correct_pattern_passes(self):
        """Module with handle_command(command, args) -> bool passes."""
        content = "def handle_command(command: str, args: list) -> bool:\n    return True\n"
        result = check_handle_command(content)
        assert result is not None
        assert result["passed"] is True

    def test_missing_handle_command_fails(self):
        """Module without handle_command fails."""
        content = "def do_work():\n    return True\n"
        result = check_handle_command(content)
        assert result is not None
        assert result["passed"] is False
        assert "Missing handle_command" in result["message"]

    def test_missing_return_type_fails(self):
        """handle_command without -> bool annotation fails."""
        content = "def handle_command(command, args):\n    return True\n"
        result = check_handle_command(content)
        assert result is not None
        assert result["passed"] is False
        assert "missing -> bool" in result["message"]


# -- doors (apps/modules/door_<subject>.py) ---------------------------------

_DOOR = (
    '"""Door: memory\'s entry limits, for other branches."""\n\n'
    "from __future__ import annotations\n\n"
    "from aipass.memory.apps.handlers.json.entry_limits import check_file_budget, load_entry_limits\n\n"
    '__all__ = ["load_entry_limits", "check_file_budget"]\n'
)


class TestADoorReExportsItsOwnHandlersOnly:
    """A door is a thin re-export of its own branch's handlers (DPLAN-0404 leg 1)."""

    @staticmethod
    def _door(tmp_path, body: str) -> str:
        """Seat a door in memory's modules and return its path."""
        modules_dir = tmp_path / "aipass" / "memory" / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        door = modules_dir / "door_entry_limits.py"
        door.write_text(body, encoding="utf-8")
        return str(door)

    def test_the_door_shape_passes_without_a_handle_command(self, tmp_path):
        """A door carries no CLI, so the handle_command row is not asked of it."""
        result = modules_check.check_module(self._door(tmp_path, _DOOR))
        door_row = [check for check in result["checks"] if check["name"] == "Door shape"]
        assert door_row == [
            {"name": "Door shape", "passed": True, "message": "Door re-exports only its own handlers (2 names)"}
        ]
        assert "handle_command pattern" not in [check["name"] for check in result["checks"]]
        assert result["score"] == 100

    @pytest.mark.parametrize(
        ("change", "named"),
        [
            (
                ("\n\n__all__", "\nfrom aipass.ai_mail.apps.handlers.wake import wake_branch\n\n__all__"),
                "line 6: imports aipass.ai_mail.apps.handlers.wake",
            ),
            (("from __future__ import annotations", "from aipass.prax import logger"), "line 3: imports aipass.prax"),
            (
                ("__all__ = [", "def handle_command(command, args):\n    return True\n\n\n__all__ = ["),
                "line 7: defines handle_command",
            ),
            (('__all__ = ["load_entry_limits", "check_file_budget"]', "X = 1"), "carries no __all__"),
            (
                ('"check_file_budget"]', '"check_file_budget", "wake"]'),
                "__all__ names 'wake', which it does not import",
            ),
        ],
    )
    def test_anything_else_in_a_door_is_named(self, tmp_path, change, named):
        """A foreign import, a non-stdlib import, a def, a missing __all__, an un-imported name."""
        result = modules_check.check_module(self._door(tmp_path, _DOOR.replace(*change)))
        [door_row] = [check for check in result["checks"] if check["name"] == "Door shape"]
        assert door_row["passed"] is False
        assert named in door_row["message"]

    @pytest.mark.parametrize(
        "change",
        [
            ("__all__ = [", "def helper():\n    return 1\n\n\n__all__ = ["),
            ("\n\n__all__", "\nfrom aipass.ai_mail.apps.handlers.wake import wake_branch\n\n__all__"),
            ('"check_file_budget"]', '"check_file_budget", "wake"]'),
        ],
    )
    def test_a_wrong_shaped_door_fails_the_standard_whatever_else_scores(self, tmp_path, change):
        """The Door shape row is the verdict for a door: an 80 aggregate no longer passes it (DPLAN-0404)."""
        result = modules_check.check_module(self._door(tmp_path, _DOOR.replace(*change)))
        assert (result["passed"], result["score"]) == (False, 0)

    def test_the_same_body_under_a_plain_name_keeps_the_aggregate(self, tmp_path):
        """A non-door modules file at 80 (no handle_command) still passes: the aggregate rule stands."""
        plain = tmp_path / "aipass" / "memory" / "apps" / "modules" / "entry_limits.py"
        plain.parent.mkdir(parents=True)
        plain.write_text(_DOOR, encoding="utf-8")
        result = modules_check.check_module(str(plain))
        assert (result["passed"], result["score"]) == (True, 80)

    @pytest.mark.parametrize(
        ("handlers", "passed"),
        [("aipass.skills.lib.telegram.apps.handlers.notifier", True), ("aipass.daemon.lib.x.apps.handlers.y", False)],
        ids=["nested_under_its_own_branch", "nested_under_another_branch"],
    )
    def test_a_handlers_package_nested_in_the_branch_tree_is_its_own(self, tmp_path, handlers, passed):
        """skills' door_notifier re-exports lib/telegram's handlers (10-08) and read 38/39.

        The owner is the segment after ``aipass.``, as encapsulation reads it; a
        handlers package nested under another branch's tree is still foreign.
        """
        door = tmp_path / "aipass" / "skills" / "apps" / "modules" / "door_notifier.py"
        door.parent.mkdir(parents=True)
        door.write_text(
            f'"""Door: the telegram notifier."""\n\nfrom {handlers} import send\n\n__all__ = ["send"]\n',
            encoding="utf-8",
        )

        [door_row] = [c for c in modules_check.check_module(str(door))["checks"] if c["name"] == "Door shape"]

        assert door_row["passed"] is passed, door_row["message"]


# -- check_file_size (modules) -----------------------------------------------


class TestModulesCheckFileSize:
    """Tests for modules_check.check_file_size."""

    def test_simple_module_passes(self, tmp_path):
        """Under 150 lines is perfect."""
        lines: list[str] = ["x"] * 100
        result = check_file_size(lines, (tmp_path / "branch" / "apps" / "modules" / "audit.py").as_posix())
        assert result["passed"] is True
        assert "simple" in result["message"]

    def test_standard_module_passes(self, tmp_path):
        """150-250 lines is standard."""
        lines: list[str] = ["x"] * 200
        result = check_file_size(lines, (tmp_path / "branch" / "apps" / "modules" / "audit.py").as_posix())
        assert result["passed"] is True
        assert "standard" in result["message"]

    def test_oversized_module_fails(self, tmp_path):
        """600+ lines fails."""
        lines: list[str] = ["x"] * 650
        result = check_file_size(lines, (tmp_path / "branch" / "apps" / "modules" / "audit.py").as_posix())
        assert result["passed"] is False
        assert "too large" in result["message"]


# -- check_no_direct_file_ops -----------------------------------------------


class TestCheckNoDirectFileOps:
    """Tests for check_no_direct_file_ops."""

    def test_clean_module_passes(self):
        """Module without direct file operations passes."""
        content = "def do_work():\n    return handler.load_data()\n"
        lines = _lines(content)
        result = check_no_direct_file_ops(lines)
        assert result is not None
        assert result["passed"] is True

    def test_open_call_fails(self):
        """Module with bare open() call fails."""
        content = 'def do_work():\n    f = open("data.json")\n'
        lines = _lines(content)
        result = check_no_direct_file_ops(lines)
        assert result is not None
        assert result["passed"] is False
        assert "open" in result["message"]

    def test_json_dump_fails(self):
        """Module with json.dump() call fails."""
        content = "def save():\n    json.dump(data, fp)\n"
        lines = _lines(content)
        result = check_no_direct_file_ops(lines)
        assert result is not None
        assert result["passed"] is False

    def test_import_open_not_flagged(self):
        """Import lines containing 'open' are not flagged."""
        content = "from pathlib import Path\nimport os\n"
        lines = _lines(content)
        result = check_no_direct_file_ops(lines)
        assert result is not None
        assert result["passed"] is True


# -- check_no_business_logic -------------------------------------------------


class TestCheckNoBusinessLogic:
    """Tests for check_no_business_logic."""

    def test_clean_module_passes(self, tmp_path):
        """Module without hardcoded data passes."""
        content = "CONSTANT = 42\ndef do_work():\n    return True\n"
        lines = _lines(content)
        result = check_no_business_logic(content, lines, (tmp_path / "module.py").as_posix())
        assert result is not None
        assert result["passed"] is True

    def test_hardcoded_list_fails(self, tmp_path):
        """Module-level hardcoded list fails."""
        content = 'allowed_types = ["alpha", "beta", "gamma"]\n'
        lines = _lines(content)
        result = check_no_business_logic(content, lines, (tmp_path / "module.py").as_posix())
        assert result is not None
        assert result["passed"] is False
        assert "hardcoded" in result["message"]

    def test_all_caps_constant_passes(self, tmp_path):
        """ALL_CAPS constant is not flagged."""
        content = 'ALLOWED = ["alpha", "beta", "gamma"]\n'
        lines = _lines(content)
        result = check_no_business_logic(content, lines, (tmp_path / "module.py").as_posix())
        assert result is not None
        assert result["passed"] is True

    def test_empty_list_passes(self, tmp_path):
        """Empty list assignment is not flagged."""
        content = "results = []\n"
        lines = _lines(content)
        result = check_no_business_logic(content, lines, (tmp_path / "module.py").as_posix())
        assert result is not None
        assert result["passed"] is True


# -- check_thin_orchestration ------------------------------------------------


class TestCheckThinOrchestration:
    """Tests for check_thin_orchestration."""

    def test_thin_module_passes(self, tmp_path):
        """Module with only standard functions passes."""
        content = (
            "def handle_command(command, args):\n"
            "    return True\n"
            "def print_help():\n"
            "    pass\n"
            "def print_introspection():\n"
            "    pass\n"
        )
        result = check_thin_orchestration(content, (tmp_path / "module.py").as_posix())
        assert result is not None
        assert result["passed"] is True

    def test_implementation_function_fails(self, tmp_path):
        """Module with large non-standard function fails."""
        # Build a function with > 40 lines (THIN_WRAPPER_MAX_LINES)
        func_body = "\n".join(f"    x{i} = {i}" for i in range(45))
        content = f"def compute_results(data):\n{func_body}\n"
        result = check_thin_orchestration(content, (tmp_path / "module.py").as_posix())
        assert result is not None
        assert result["passed"] is False
        assert "compute_results" in result["message"]

    def test_private_helper_passes(self, tmp_path):
        """Private helper functions (_prefixed) are allowed."""
        func_body = "\n".join(f"    x{i} = {i}" for i in range(45))
        content = f"def _internal_helper():\n{func_body}\n"
        result = check_thin_orchestration(content, (tmp_path / "module.py").as_posix())
        assert result is not None
        assert result["passed"] is True

    def test_orchestration_prefix_passes(self, tmp_path):
        """Functions with orchestration prefixes (handle_, show_, etc.) pass."""
        func_body = "\n".join(f"    x{i} = {i}" for i in range(45))
        content = f"def handle_audit(args):\n{func_body}\n"
        result = check_thin_orchestration(content, (tmp_path / "module.py").as_posix())
        assert result is not None
        assert result["passed"] is True

    def test_small_function_passes(self, tmp_path):
        """Non-standard function under 40 lines is treated as thin wrapper."""
        content = "def compute_results(data):\n    return data\n"
        result = check_thin_orchestration(content, (tmp_path / "module.py").as_posix())
        assert result is not None
        assert result["passed"] is True
