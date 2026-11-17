# =================== AIPass ====================
# Name: test_checkers_batch7_modules.py
# Description: modules_check sub-functions and the second door it leaves to front_door
# Version: 1.4.0
# Created: 2026-10-08
# Modified: 2026-11-16
# =============================================

"""Tests for apps/handlers/aipass_standards/modules_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that each checker in handlers/aipass_standards/ parses and imports

import pytest

from aipass.sentry.apps.handlers.aipass_standards import modules_check
from aipass.sentry.apps.handlers.aipass_standards.modules_check import (
    check_file_size,
    check_handle_command,
    check_no_business_logic,
    check_no_direct_file_ops,
    check_thin_orchestration,
)
from aipass.sentry.apps.handlers.aipass_standards.prose_lines import UnparseableSource, classify
from aipass.sentry.apps.handlers.bypass.utils import FILE_SCOPE
from aipass.sentry.tests.support_checkers_batch7 import _lines

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


# -- second doors (a retired pattern front_door convicts) --------------------

_DOOR = (
    '"""Door: memory\'s entry limits, for other branches."""\n\n'
    "from __future__ import annotations\n\n"
    "from aipass.memory.apps.handlers.json.entry_limits import check_file_budget, load_entry_limits\n\n"
    '__all__ = ["load_entry_limits", "check_file_budget"]\n'
)


#: Where a door is seated: memory's modules.
_DOOR_PATH = "aipass/memory/apps/modules/door_entry_limits.py"


def _seat(tmp_path, rel: str, body: str) -> str:
    """Write a body at a path under tmp_path and return it."""
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return str(target)


class TestTheSecondDoorShape:
    """check_door reads the retired second-door shape: own handlers re-exported, nothing else."""

    def test_the_shape_is_read_and_its_names_counted(self, tmp_path):
        verdict = modules_check.check_door(_DOOR, _seat(tmp_path, _DOOR_PATH, _DOOR))
        assert (verdict["passed"], verdict["names"]) == (True, 2)

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
    def test_anything_else_in_the_shape_is_named(self, tmp_path, change, named):
        """A foreign import, a non-stdlib import, a def, a missing __all__, an un-imported name."""
        body = _DOOR.replace(*change)
        verdict = modules_check.check_door(body, _seat(tmp_path, _DOOR_PATH, body))
        assert verdict["passed"] is False
        assert named in verdict["message"]

    @pytest.mark.parametrize(
        ("handlers", "passed"),
        [
            ("aipass.skills.lib.drone_commands.apps.handlers.notifier", True),
            ("aipass.daemon.lib.x.apps.handlers.y", False),
        ],
        ids=["nested_under_its_own_branch", "nested_under_another_branch"],
    )
    def test_a_handlers_package_nested_in_the_branch_tree_is_its_own(self, tmp_path, handlers, passed):
        """A skills door re-exporting a handlers package nested in its own lib/ read 38/39.

        The owner is the segment after ``aipass.``, as encapsulation reads it; a
        handlers package nested under another branch's tree is still foreign.
        """
        body = f'"""Door: the notifier."""\n\nfrom {handlers} import send\n\n__all__ = ["send"]\n'
        verdict = modules_check.check_door(body, _seat(tmp_path, "aipass/skills/apps/modules/notifier.py", body))
        assert verdict["passed"] is passed, verdict["message"]


_HELPER = ("__all__ = [", "def helper():\n    return 1\n\n\n__all__ = [")


class TestASecondDoorIsFrontDoorsToConvict:
    """A second door is a retired pattern: is_second_door names it, front_door convicts, modules does not re-judge."""

    @pytest.mark.parametrize(
        ("rel", "body", "second"),
        [
            (_DOOR_PATH, _DOOR, True),
            (_DOOR_PATH, _DOOR.replace(*_HELPER), True),
            ("aipass/memory/apps/modules/entry_limits.py", _DOOR, True),
            ("aipass/memory/apps/modules/entry_limits.py", _DOOR.replace(*_HELPER), False),
            ("aipass/memory/apps/modules/__init__.py", _DOOR, False),
            ("aipass/memory/apps/handlers/door_entry_limits.py", _DOOR, False),
            ("aipass/memory/apps/modules/empty.py", "__all__ = []\n", False),
        ],
        ids=[
            "by_name",
            "by_name_with_logic",
            "by_shape",
            "real_module",
            "package_marker",
            "under_handlers",
            "no_names",
        ],
    )
    def test_is_second_door_reads_name_or_shape_under_apps_modules(self, tmp_path, rel, body, second):
        assert modules_check.is_second_door(_seat(tmp_path, rel, body), body) is second

    @pytest.mark.parametrize("rel", [_DOOR_PATH, "aipass/memory/apps/modules/entry_limits.py"])
    def test_the_modules_row_leaves_a_second_door_to_front_door(self, tmp_path, rel):
        [check] = modules_check.check_module(_seat(tmp_path, rel, _DOOR))["checks"]
        assert check["declined"] is True and "front_door convicts it" in check["message"]

    def test_a_real_module_is_still_asked_for_its_handle_command(self, tmp_path):
        path = _seat(tmp_path, "aipass/memory/apps/modules/entry_limits.py", _DOOR.replace(*_HELPER))
        names = [check["name"] for check in modules_check.check_module(path)["checks"]]
        assert "handle_command pattern" in names


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


class TestFileOpWordsInStringsAndComments:
    """Only calls are file operations; their names inside a string or a comment are not."""

    def test_names_inside_a_string_and_a_trailing_comment_pass(self):
        content = 'def f():\n    return "never call .read_text( here"  # nor .mkdir( or json.load(\n'
        result = check_no_direct_file_ops(_lines(content))
        assert result is not None
        assert result["passed"] is True

    def test_a_real_mkdir_call_is_still_named_by_its_line(self):
        content = "def f(p):\n    x = 1\n    p.mkdir(parents=True)\n"
        result = check_no_direct_file_ops(_lines(content))
        assert result is not None
        assert result["message"] == (
            "Module has direct file operations: line 3: p.mkdir(parents=True) (use handler for file operations)"
        )


class TestAOneLineDocstringHidesNothing:
    """A one-line docstring opens and closes on its own line, so the code after it is still read."""

    def test_a_read_after_a_one_line_docstring_is_named_by_its_line(self):
        """The permissions.py shape: a one-line module docstring, then a direct read."""
        content = (
            '"""Shared permission definitions."""\n'
            "\n"
            "def identify(passport):\n"
            '    return json.loads(passport.read_text(encoding="utf-8"))\n'
        )
        result = check_no_direct_file_ops(_lines(content))
        assert result is not None
        assert result["passed"] is False
        assert result["message"].startswith("Module has direct file operations: line 4: ")

    def test_file_op_words_inside_a_multi_line_docstring_are_not_code(self):
        """Prose naming read_text( inside a docstring body is skipped, open to close."""
        content = (
            "def identify(passport):\n"
            '    """Return the branch name.\n'
            "\n"
            "    Never calls passport.read_text( directly.\n"
            '    """\n'
            "    return handler.load(passport)\n"
        )
        result = check_no_direct_file_ops(_lines(content))
        assert result is not None
        assert result["passed"] is True

    def test_file_op_words_on_a_one_line_docstring_are_not_code(self):
        """The docstring line itself is prose, even when it opens and closes on that line."""
        content = (
            "def identify(passport):\n"
            '    """Never calls passport.read_text( directly."""\n'
            "    return handler.load(passport)\n"
        )
        result = check_no_direct_file_ops(_lines(content))
        assert result is not None
        assert result["passed"] is True

    def test_a_read_after_a_closed_multi_line_docstring_is_still_read(self):
        """Closing a multi-line docstring turns the reading back on."""
        content = (
            "def identify(passport):\n"
            '    """Return the branch name.\n'
            "\n"
            "    Reads the passport.\n"
            '    """\n'
            "    return passport.read_text()\n"
        )
        result = check_no_direct_file_ops(_lines(content))
        assert result is not None
        assert result["passed"] is False
        assert "line 6: " in result["message"]


class TestProseLinesSortsDocstringsAndCommentsFromCode:
    """The shared helper every line-based checker reads: docstrings and comment lines are prose."""

    def test_a_one_line_docstring_is_prose_and_the_next_line_is_code(self):
        kinds = classify('"""Doc."""\nx = 1\n')
        assert (1 in kinds.prose, 2 in kinds.code) == (True, True)

    def test_every_line_of_a_multi_line_docstring_is_prose(self):
        kinds = classify('def f():\n    """Open.\n\n    Body.\n    """\n    return 1\n')
        assert sorted(kinds.docstrings) == [2, 3, 4, 5]
        assert 6 in kinds.code

    def test_the_other_delimiter_inside_a_docstring_closes_nothing(self):
        kinds = classify("def f():\n    '''Uses \"\"\".\n    \"\"\"\n    Body.\n    '''\n    return 1\n")
        assert sorted(kinds.docstrings) == [2, 3, 4, 5]

    def test_a_triple_quoted_literal_in_code_is_code_and_its_body_is_marked(self):
        kinds = classify('X = """\nbody\n"""\nprint("""inline""")\n')
        assert kinds.prose == frozenset()
        assert sorted(kinds.string_bodies) == [2, 3]

    def test_text_only_adds_string_bodies_to_prose_and_keeps_the_opening_line_code(self):
        kinds = classify('# c\nX = """\nbody\n"""\n')
        assert sorted(kinds.text_only) == [1, 3, 4]

    def test_a_comment_line_is_prose_and_an_inline_comment_leaves_code(self):
        kinds = classify("# note\nx = 1  # inline\n")
        assert (sorted(kinds.comments), 2 in kinds.code) == ([1], True)

    def test_a_docstring_sharing_its_def_line_leaves_that_line_code(self):
        kinds = classify('def f(): """Doc."""\n')
        assert 1 in kinds.code

    def test_a_source_that_does_not_parse_raises_rather_than_answer_all_code(self):
        with pytest.raises(UnparseableSource):
            classify("def broken(:\n")


class TestModulesReadsCodeLinesOnly:
    """check_handle_command and check_no_direct_file_ops judge code lines, never docstrings."""

    def test_a_handle_command_named_only_in_a_docstring_is_missing(self):
        content = "'''\n\"\"\"\ndef handle_command(command, args) -> bool: is the shape.\n'''\n"
        result = check_handle_command(content)
        assert result is not None
        assert result["passed"] is False

    def test_a_handle_command_def_carrying_a_triple_quoted_default_is_found(self):
        content = 'def handle_command(command: str, args: list, doc: str = """x""") -> bool:\n    return True\n'
        result = check_handle_command(content)
        assert result is not None
        assert result["passed"] is True

    def test_the_other_delimiter_in_a_docstring_does_not_end_it(self):
        content = (
            'def f(p):\n    """Quotes with\n    \'\'\'\n    and names p.read_text( in prose.\n    """\n    return p\n'
        )
        result = check_no_direct_file_ops(_lines(content))
        assert result is not None
        assert result["passed"] is True

    def test_a_write_wrapping_a_triple_quoted_literal_is_a_file_operation(self):
        content = 'def save(p):\n    p.write_text("""body""")\n'
        result = check_no_direct_file_ops(_lines(content))
        assert result is not None
        assert result["message"].startswith("Module has direct file operations: line 2: ")

    def test_a_quoted_open_skips_only_the_open_finding_and_the_read_is_still_named(self):
        content = 'def f(p):\n    x = "open(" if p.read_text() else 0\n'
        result = check_no_direct_file_ops(_lines(content))
        assert result is not None
        assert result["message"].endswith("(use json_handler instead)")

    def test_a_file_op_inside_a_string_literal_body_is_text_not_a_call(self):
        content = 'TEMPLATE = """\nwith open(path) as f:\n"""\n'
        result = check_no_direct_file_ops(_lines(content))
        assert result is not None
        assert result["passed"] is True

    def test_a_source_that_does_not_parse_fails_handle_command(self):
        result = check_handle_command("def handle_command(command, args) -> bool\n")
        assert result is not None
        assert result["message"].startswith("Source does not parse")


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


# ---------------------------------------------------------------------------
# Scoped bypass rows: one finding per site
# ---------------------------------------------------------------------------

_TWO_OPS = (
    "import json\n"
    "\n"
    "def handle_command(command: str, args: list) -> bool:\n"
    "    return True\n"
    "\n"
    "def _load(path):\n"
    "    return json.loads(path.read_text())\n"
    "\n"
    "def _save(path, data):\n"
    "    path.write_text(data)\n"
)
_LOAD_LINE, _SAVE_LINE = 7, 10


class TestScopedBypassRows:
    """A modules row naming a line or a function waives that site alone; a whole-file row waives the file."""

    def _check(self, tmp_path, source, **scope):
        target = tmp_path / "apps" / "modules" / "store.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
        rules = [{"file": "apps/modules/store.py", "standard": "modules", "reason": "test", **scope}] if scope else []
        result = modules_check.check_module(str(target), bypass_rules=rules)
        rows = {c["name"]: c for c in result["checks"]}
        return result, rows

    def test_every_direct_file_operation_is_named_not_only_the_first(self, tmp_path):
        _result, rows = self._check(tmp_path, _TWO_OPS)
        message = rows["No direct file operations"]["message"]
        assert f"line {_LOAD_LINE}:" in message and f"line {_SAVE_LINE}:" in message

    def test_a_line_row_waives_its_operation_and_the_other_still_convicts(self, tmp_path):
        _result, rows = self._check(tmp_path, _TWO_OPS, lines=[_LOAD_LINE])
        row = rows["No direct file operations"]
        assert row["passed"] is False
        assert f"line {_SAVE_LINE}:" in row["message"] and f"line {_LOAD_LINE}:" not in row["message"]

    def test_line_rows_on_every_operation_pass_the_check(self, tmp_path):
        result, rows = self._check(tmp_path, _TWO_OPS, lines=[_LOAD_LINE, _SAVE_LINE])
        assert rows["No direct file operations"]["passed"] is True
        assert result["score"] == 100

    def test_a_function_row_waives_the_operations_inside_that_function_only(self, tmp_path):
        _result, rows = self._check(tmp_path, _TWO_OPS, functions=["_load"])
        row = rows["No direct file operations"]
        assert row["passed"] is False
        assert f"line {_SAVE_LINE}:" in row["message"] and f"line {_LOAD_LINE}:" not in row["message"]

    def test_a_whole_file_row_still_waives_the_whole_file(self, tmp_path):
        result, rows = self._check(tmp_path, _TWO_OPS, lines=None)
        assert result["score"] == 100 and "Bypassed" in rows

    def test_a_file_level_finding_is_waived_by_the_file_scope_name_and_not_by_a_line(self, tmp_path):
        oversized = "def handle_command(command: str, args: list) -> bool:\n    return True\n" + "X = 1\n" * 620
        _result, by_name = self._check(tmp_path, oversized, functions=[FILE_SCOPE])
        _result, by_line = self._check(tmp_path, oversized, lines=[1])
        assert by_name["File size"]["passed"] is True
        assert by_line["File size"]["passed"] is False

    def test_a_function_row_waives_a_long_implementation_function_by_its_name(self, tmp_path):
        body = "".join(f"    x{i} = {i}\n" for i in range(45))
        source = "def handle_command(command: str, args: list) -> bool:\n    return True\n\ndef build():\n" + body
        _result, waived = self._check(tmp_path, source, functions=["build"])
        _result, plain = self._check(tmp_path, source)
        assert plain["Thin orchestration"]["passed"] is False
        assert waived["Thin orchestration"]["passed"] is True
