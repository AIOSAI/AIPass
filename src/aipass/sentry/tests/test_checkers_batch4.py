# =================== META ====================
# Name: test_checkers_batch4.py
# Description: Unit tests for 5 sentry checker handlers (batch 4)
# Version: 1.7.0
# Created: 2026-03-29
# Modified: 2026-11-17
# =============================================

"""Tests for 5 checkers: aipass_standards/stderr_routing_check.py, todo, trigger, dead_code, unused_function."""


# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(retired) — the v4 test_quality checker, retired with its standard in FPLAN-0491
# sentry: no-test-needed(stdlib) — tokenize's own error classes; the fallback they trigger is pinned via check_branch

import tokenize
from pathlib import Path

import pytest
from types import SimpleNamespace
from unittest.mock import patch

from aipass.sentry.apps.handlers.aipass_standards import unused_function_check

from aipass.sentry.apps.handlers.aipass_standards.stderr_routing_check import (
    check_module as stderr_check_module,
)
from aipass.sentry.apps.handlers.aipass_standards.todo_check import (
    check_module as todo_check_module,
)
from aipass.sentry.apps.handlers.aipass_standards.trigger_check import (
    check_module as trigger_check_module,
)
from aipass.sentry.apps.handlers.aipass_standards.dead_code_check import (
    check_branch as dead_code_check_branch,
)
from aipass.sentry.apps.handlers.aipass_standards.unused_function_check import (
    check_branch as unused_function_check_branch,
)


def _write_file(path: Path, content: str) -> None:
    """Write content to a file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_branch(tmp_path: Path) -> Path:
    """Create a minimal branch directory structure for check_branch tests."""
    apps = tmp_path / "apps"
    modules = apps / "modules"
    modules.mkdir(parents=True)
    handlers = apps / "handlers"
    handlers.mkdir(parents=True)
    return tmp_path


@patch("aipass.sentry.apps.handlers.aipass_standards.stderr_routing_check.json_handler")
class TestStderrRoutingCheck:
    """Tests for the stderr_routing_check checker."""

    def test_stderr_routing_clean_passes(self, mock_json, tmp_path: Path) -> None:
        """Clean code with no stderr violations passes with score >= 75."""
        py_file = tmp_path / "clean_module.py"
        _write_file(
            py_file,
            (
                "from aipass.cli import error, warning\n"
                "\n"
                "def do_work():\n"
                "    error('Something failed', suggestion='Try again')\n"
                "    warning('Heads up', details='Check config')\n"
            ),
        )
        result = stderr_check_module(str(py_file))
        assert result["score"] >= 75
        assert result["standard"] == "STDERR_ROUTING"

    def test_stderr_routing_violation_caught(self, mock_json, tmp_path: Path) -> None:
        """Code with Console(stderr=True) is detected as a violation."""
        py_file = tmp_path / "bad_module.py"
        _write_file(
            py_file, ("from rich.console import Console\n\nerr = Console(stderr=True)\nerr.print('bad output')\n")
        )
        result = stderr_check_module(str(py_file))
        failed_names = [c["name"] for c in result["checks"] if not c["passed"]]
        assert "Stderr console creation" in failed_names

    def test_stderr_routing_bypass_respected(self, mock_json, tmp_path: Path) -> None:
        """Bypass rules produce score=100."""
        py_file = tmp_path / "bypassed_module.py"
        _write_file(py_file, ("from rich.console import Console\nerr = Console(stderr=True)\n"))
        bypass = [{"file": py_file.name, "standard": "stderr_routing"}]
        result = stderr_check_module(str(py_file), bypass_rules=bypass)
        assert result["score"] == 100
        assert result["passed"] is True


@patch("aipass.sentry.apps.handlers.aipass_standards.stderr_routing_check.json_handler")
class TestStderrRoutingReadsCodeLinesOnly:
    """The three stderr scans judge code lines; docstring lines are prose."""

    def _failed(self, tmp_path: Path, source: str) -> list:
        py_file = tmp_path / "subject.py"
        _write_file(py_file, source)
        return [c["message"] for c in stderr_check_module(str(py_file))["checks"] if not c["passed"]]

    def test_an_error_print_after_a_one_line_docstring_holding_the_other_delimiter_is_found(self, mock_json, tmp_path):
        source = (
            'def f():\n    """Quotes \'\'\' here."""\n'
            '    console.print("[red]Error: the config failed to load now[/red]")\n'
        )
        assert self._failed(tmp_path, source) == [
            "subject.py: 1 error print(s) on lines [3] — use error() or fatal() instead"
        ]

    def test_an_error_print_inside_a_docstring_past_the_other_delimiter_is_prose(self, mock_json, tmp_path):
        source = (
            "def f():\n    \"\"\"Doc.\n    '''\n"
            '    console.print("[red]Error: the config failed to load now[/red]")\n    """\n'
        )
        assert self._failed(tmp_path, source) == []

    def test_a_stderr_console_on_a_line_opening_a_triple_quoted_literal_is_found(self, mock_json, tmp_path):
        source = 'def f():\n    return Console(stderr=True), """\n    usage\n    """\n'
        assert self._failed(tmp_path, source) == [
            "subject.py: Custom Console(stderr=True) on lines [2] — use from aipass.cli import err_console"
        ]


@patch("aipass.sentry.apps.handlers.aipass_standards.todo_check.json_handler")
class TestTodoCheck:
    """Tests for the todo_check checker."""

    def test_todo_clean_passes(self, mock_json, tmp_path: Path) -> None:
        """Code with no TODO/FIXME/HACK/XXX comments passes with score >= 75."""
        py_file = tmp_path / "clean.py"
        _write_file(py_file, ("def greet(name: str) -> str:\n    return f'Hello, {name}'\n"))
        result = todo_check_module(str(py_file))
        assert result["score"] >= 75
        assert result["passed"] is True
        assert result["standard"] == "TODO"

    def test_todo_violation_caught(self, mock_json, tmp_path: Path) -> None:
        """Code containing TODO and FIXME comments is detected."""
        py_file = tmp_path / "messy.py"
        _write_file(
            py_file,
            ("def compute():\n    # TODO: implement this properly\n    # FIXME: off-by-one error\n    return 42\n"),
        )
        result = todo_check_module(str(py_file))
        assert result["passed"] is False
        assert result["score"] == 0
        assert any("TODO" in c["message"] for c in result["checks"])

    def test_todo_tag_inside_a_string_is_not_a_comment(self, mock_json, tmp_path: Path) -> None:
        """A hash-TODO inside a string literal is text, not a comment (fleet green leg 13)."""
        py_file = tmp_path / "specimen.py"
        _write_file(py_file, ('text = "# TODO: a specimen"\nblock = """\n# FIXME: also text\n"""\n'))
        result = todo_check_module(str(py_file))
        assert result["score"] == 100
        assert result["checks"][0]["message"] == "No TODO/FIXME/HACK/XXX comments found"

    def test_todo_real_comment_beside_a_string_still_convicts(self, mock_json, tmp_path: Path) -> None:
        """Control: a real hash-TODO comment after a string on the same line is still one."""
        py_file = tmp_path / "beside.py"
        _write_file(py_file, ('text = "# fine"  # TODO: real\n'))
        result = todo_check_module(str(py_file))
        assert result["score"] == 0
        assert result["checks"][0]["message"] == "Found 1 TODO-type comment (TODO: 1)"

    def test_todo_untokenizable_file_fails_by_name(self, mock_json, tmp_path: Path) -> None:
        """A file Python cannot tokenize has unknown comments: it fails by name, never reads clean."""
        py_file = tmp_path / "unclosed.py"
        _write_file(py_file, ('text = """never closed\n'))
        result = todo_check_module(str(py_file))
        assert result["score"] == 0
        assert result["checks"][0]["name"] == "File tokenizable"

    def test_todo_bypass_respected(self, mock_json, tmp_path: Path) -> None:
        """Bypass rules produce score=100."""
        py_file = tmp_path / "bypassed.py"
        _write_file(py_file, ("# TODO: this should be bypassed\nx = 1\n"))
        bypass = [{"file": py_file.name, "standard": "todo"}]
        result = todo_check_module(str(py_file), bypass_rules=bypass)
        assert result["score"] == 100
        assert result["passed"] is True


@patch("aipass.sentry.apps.handlers.aipass_standards.trigger_check.json_handler")
class TestTriggerCheck:
    """Tests for the trigger_check checker."""

    def test_trigger_clean_passes(self, mock_json, tmp_path: Path) -> None:
        """Code with no trigger patterns scores >= 75."""
        py_file = tmp_path / "plain.py"
        _write_file(py_file, ("def add(a: int, b: int) -> int:\n    return a + b\n"))
        result = trigger_check_module(str(py_file))
        assert result["score"] >= 75
        assert result["standard"] == "TRIGGER"

    def test_trigger_violation_caught(self, mock_json, tmp_path: Path) -> None:
        """Code with lifecycle functions but no trigger.fire() is detected."""
        py_file = tmp_path / "modules" / "lifecycle.py"
        py_file.parent.mkdir(parents=True, exist_ok=True)
        _write_file(py_file, ("def create_backup(data):\n    pass\n\ndef delete_record(record_id):\n    pass\n"))
        result = trigger_check_module(str(py_file))
        failed_names = [c["name"] for c in result["checks"] if not c["passed"]]
        assert "Missing trigger events" in failed_names

    def test_trigger_bypass_respected(self, mock_json, tmp_path: Path) -> None:
        """Bypass rules produce score=100."""
        py_file = tmp_path / "bypassed_trigger.py"
        _write_file(py_file, ("def create_backup(data):\n    pass\n"))
        bypass = [{"file": py_file.name, "standard": "trigger"}]
        result = trigger_check_module(str(py_file), bypass_rules=bypass)
        assert result["score"] == 100
        assert result["passed"] is True


_LIFECYCLE = "def create_backup(data):\n    pass\n\ndef delete_record(record_id):\n    pass\n\nPath('x').unlink()\n"
_EVENT_HANDLER = 'from prax import logger\n\ndef event_handler(**kwargs):\n    print("fired")\n'
_UNIMPORTED_FIRE = 'def do_work():\n    trigger.fire("x")\n'


def _trigger_run(tmp_path: Path, rel: str, content: str, rows: list | None) -> dict:
    """check_module on a real file, every row naming it."""
    py_file = tmp_path / rel
    _write_file(py_file, content)
    rules = [{"file": rel, "standard": "trigger", **row} for row in rows] if rows is not None else None
    return trigger_check_module(str(py_file), bypass_rules=rules)


@patch("aipass.sentry.apps.handlers.aipass_standards.trigger_check.json_handler")
class TestTriggerSites:
    """Each finding is a site, at its line inside its function (<file> at module level), waived alone."""

    def test_with_no_row_every_missing_event_is_reported_at_its_line(self, mock_json, tmp_path: Path) -> None:
        result = _trigger_run(tmp_path, "modules/lifecycle.py", _LIFECYCLE, None)
        assert result["passed"] is False
        message = result["checks"][0]["message"]
        assert "[1]" in message and "[4]" in message and "[7]" in message

    @pytest.mark.parametrize(
        "row",
        [{"lines": [1]}, {"functions": ["create_backup"]}],
        ids=["line_row", "function_row"],
    )
    def test_a_scoped_row_waives_its_site_and_the_other_sites_still_fail_the_file(
        self, mock_json, tmp_path: Path, row: dict
    ) -> None:
        result = _trigger_run(tmp_path, "modules/lifecycle.py", _LIFECYCLE, [row])
        message = result["checks"][0]["message"]
        assert result["passed"] is False
        assert "create_*" not in message and "delete_* function on lines [4]" in message and "[7]" in message

    @pytest.mark.parametrize(
        "row",
        [{"lines": [1, 4, 7]}, {"functions": ["create_backup", "delete_record", "<file>"]}],
        ids=["line_row", "function_row"],
    )
    def test_a_row_naming_every_site_passes_the_file(self, mock_json, tmp_path: Path, row: dict) -> None:
        result = _trigger_run(tmp_path, "modules/lifecycle.py", _LIFECYCLE, [row])
        assert (result["passed"], result["score"]) == (True, 100)

    def test_a_module_level_deletion_is_waived_by_a_file_scope_row_alone(self, mock_json, tmp_path: Path) -> None:
        result = _trigger_run(tmp_path, "modules/lifecycle.py", _LIFECYCLE, [{"functions": ["<file>"]}])
        message = result["checks"][0]["message"]
        assert result["passed"] is False
        assert ".unlink()" not in message and "create_* function on lines [1]" in message

    @pytest.mark.parametrize(
        ("row", "open_checks"),
        [
            (None, ["No logger imports", "No print statements", "Handler naming"]),
            ({"lines": [4]}, ["No logger imports", "Handler naming"]),
            ({"functions": ["event_handler"]}, ["No logger imports"]),
            ({"functions": ["<file>"]}, ["No print statements", "Handler naming"]),
            ({"lines": [1, 3, 4]}, []),
        ],
        ids=["no_row", "print_line", "handler_function", "file_scope_import", "every_line"],
    )
    def test_an_event_handlers_logger_print_and_naming_are_sites(
        self, mock_json, tmp_path: Path, row: dict | None, open_checks: list
    ) -> None:
        rel = "trigger/apps/handlers/events/on_x.py"
        result = _trigger_run(tmp_path, rel, _EVENT_HANDLER, None if row is None else [row])
        assert [c["name"] for c in result["checks"] if not c["passed"]] == open_checks
        assert result["passed"] is (not open_checks)

    @pytest.mark.parametrize(("row", "waived"), [({"lines": [1]}, True), ({"functions": ["<file>"]}, False)])
    def test_an_unparseable_file_names_no_function_so_only_a_line_row_reaches_its_site(
        self, mock_json, tmp_path: Path, row: dict, waived: bool
    ) -> None:
        result = _trigger_run(tmp_path, "modules/broken.py", "def create_backup(data):\n    pass\n\ndef (\n", [row])
        assert result["passed"] is waived

    def test_one_waived_print_leaves_the_other_print_failing_the_handler(self, mock_json, tmp_path: Path) -> None:
        content = 'def handle_a(**kwargs):\n    print("a")\n\ndef handle_b(**kwargs):\n    print("b")\n'
        rel = "trigger/apps/handlers/events/on_y.py"
        result = _trigger_run(tmp_path, rel, content, [{"functions": ["handle_a"]}])
        assert [c["message"] for c in result["checks"] if not c["passed"]] == [
            "Handler uses print() (must be silent) on lines [5]"
        ]

    @pytest.mark.parametrize(
        ("row", "waived"),
        [
            (None, False),
            ({"functions": ["<file>"]}, True),
            ({"functions": ["do_work"]}, False),
            ({"lines": [2]}, False),
        ],
        ids=["no_row", "file_scope_row", "function_row", "line_row"],
    )
    def test_a_missing_import_is_a_whole_file_finding(
        self, mock_json, tmp_path: Path, row: dict | None, waived: bool
    ) -> None:
        result = _trigger_run(tmp_path, "modules/worker.py", _UNIMPORTED_FIRE, None if row is None else [row])
        assert result["passed"] is waived
        assert ("Waived by a <file> bypass row" in result["checks"][0]["message"]) is waived


@patch("aipass.sentry.apps.handlers.aipass_standards.dead_code_check.json_handler")
class TestDeadCodeCheck:
    """Tests for the dead_code_check checker."""

    def test_dead_code_clean_passes(self, mock_json, tmp_path: Path) -> None:
        """Branch where all modules are referenced scores >= 75."""
        branch = _make_branch(tmp_path)
        # Create a module
        _write_file(
            branch / "apps" / "modules" / "helper.py",
            "def do_something():\n    return True\n",
        )
        # Create an entry point that imports the module
        _write_file(
            branch / "apps" / (branch.name + ".py"),
            "from aipass.{name}.apps.modules.helper import do_something\ndef handle_command(): do_something()\n".format(
                name=branch.name
            ),
        )
        result = dead_code_check_branch(str(branch))
        assert result["score"] >= 75
        assert result["standard"] == "DEAD_CODE"

    def test_dead_code_finding_tells_the_owner_to_re_run(self, mock_json, tmp_path: Path) -> None:
        """The finding reports the frontier, not the closure — say so in the message."""
        branch = _make_branch(tmp_path)
        _write_file(branch / "apps" / "modules" / "orphan.py", "def unused():\n    return True\n")
        _write_file(branch / "apps" / (branch.name + ".py"), "def handle_command(): pass\n")

        result = dead_code_check_branch(str(branch))

        message = " ".join(c["message"] for c in result["checks"])
        assert "re-run" in message.lower()

    def test_dead_code_violation_caught(self, mock_json, tmp_path: Path) -> None:
        """Branch with unreferenced modules is detected."""
        branch = _make_branch(tmp_path)
        # Create a module that nothing imports
        _write_file(
            branch / "apps" / "modules" / "orphan.py",
            "def lonely_function():\n    return None\n",
        )
        # Create a handler that nothing imports either
        _write_file(
            branch / "apps" / "handlers" / "forgotten.py",
            "def handle_nothing():\n    pass\n",
        )
        # Entry point that imports neither
        _write_file(
            branch / "apps" / (branch.name + ".py"),
            "def handle_command(): pass\n",
        )
        result = dead_code_check_branch(str(branch))
        failed = [c for c in result["checks"] if not c["passed"]]
        assert len(failed) > 0
        assert "unreferenced" in failed[0]["message"]

    def test_dead_code_bypass_respected(self, mock_json, tmp_path: Path) -> None:
        """Bypass rules produce score=100."""
        branch = _make_branch(tmp_path)
        _write_file(
            branch / "apps" / "modules" / "orphan.py",
            "def lonely():\n    pass\n",
        )
        bypass = [{"file": str(branch), "standard": "dead_code"}]
        result = dead_code_check_branch(str(branch), bypass_rules=bypass)
        assert result["score"] == 100
        assert result["passed"] is True

    @pytest.mark.parametrize("spelled", ["apps/handlers/lifecycle/orphan.py", "handlers/lifecycle/orphan.py"])
    def test_a_file_rule_spelled_from_the_branch_root_or_from_apps_silences_its_file_alone(
        self, mock_json, tmp_path: Path, spelled: str
    ) -> None:
        """hooks' rows began 'apps/handlers/...' and dead_code matched only 'handlers/...': they silenced nothing."""
        branch = _make_branch(tmp_path)
        _write_file(branch / "apps" / "handlers" / "lifecycle" / "orphan.py", "def lonely():\n    pass\n")
        _write_file(branch / "apps" / "handlers" / "lifecycle" / "stray.py", "def alone():\n    pass\n")
        _write_file(branch / "apps" / (branch.name + ".py"), "def handle_command(): pass\n")
        result = dead_code_check_branch(str(branch), bypass_rules=[{"file": spelled, "standard": "dead_code"}])
        message = result["checks"][0]["message"]
        assert "stray.py" in message and "orphan.py" not in message

    @pytest.mark.parametrize(
        ("rows", "dead"),
        [
            ([], ["orphan", "stray"]),
            ([{"file": "apps/handlers/orphan.py", "functions": ["<file>"]}], ["stray"]),
            ([{"file": name, "functions": ["<file>"]} for name in ("handlers/orphan.py", "stray.py")], []),
            ([{"file": "apps/handlers/orphan.py", "functions": ["lonely"]}], ["orphan", "stray"]),
            ([{"file": "apps/handlers/orphan.py", "lines": [1]}], ["orphan", "stray"]),
        ],
        ids=["no_row", "file_scope_row", "both_file_scope", "function_row", "line_row"],
    )
    def test_a_dead_file_is_a_whole_file_site_waived_by_a_file_scope_row(
        self, mock_json, tmp_path: Path, rows: list, dead: list
    ) -> None:
        """A dead file has no line and no function: only <file> names it, and only for that file."""
        branch = _make_branch(tmp_path)
        _write_file(branch / "apps" / "handlers" / "orphan.py", "def lonely():\n    pass\n")
        _write_file(branch / "apps" / "handlers" / "stray.py", "def alone():\n    pass\n")
        _write_file(branch / "apps" / (branch.name + ".py"), "def handle_command(): pass\n")
        result = dead_code_check_branch(str(branch), bypass_rules=[{"standard": "dead_code", **row} for row in rows])
        message = result["checks"][0]["message"]
        assert [name for name in ("orphan", "stray") if f"handlers/{name}.py" in message] == dead
        assert result["passed"] is (not dead)

    def test_dead_code_ignores_tools_dir_by_default(self, mock_json, tmp_path: Path) -> None:
        """Orphan modules under apps/tools/ are skipped via the global .sentryignore default."""
        branch = _make_branch(tmp_path)
        _write_file(
            branch / "apps" / "tools" / "scratch.py",
            "def lonely_function():\n    return None\n",
        )
        _write_file(
            branch / "apps" / (branch.name + ".py"),
            "def handle_command(): pass\n",
        )
        result = dead_code_check_branch(str(branch))
        assert result["score"] == 100
        assert result["passed"] is True

    def test_a_handler_imported_only_inside_a_parenthesised_block_is_referenced(
        self, mock_json, tmp_path: Path
    ) -> None:
        """A name inside `from pkg import (\\n    a,\\n    b,\\n)` is an import - @drone, 2026-09-13."""
        branch = _make_branch(tmp_path)
        _write_file(
            branch / "apps" / "handlers" / "git" / "repo_door.py",
            "def extract_repo_flag(args):\n    return args\n",
        )
        _write_file(
            branch / "apps" / (branch.name + ".py"),
            "from aipass.{name}.apps.handlers.git import (\n"
            "    lock_handler,\n"
            "    repo_door,\n"
            ")\n\n"
            "def handle_command(args):\n"
            "    return repo_door.extract_repo_flag(args)\n".format(name=branch.name),
        )

        result = dead_code_check_branch(str(branch))

        assert result["score"] == 100
        assert result["checks"][0]["passed"] is True

    def test_a_stem_named_only_in_a_comment_inside_an_import_block_is_still_dead(
        self, mock_json, tmp_path: Path
    ) -> None:
        """The block's comments are stripped before the name is read."""
        branch = _make_branch(tmp_path)
        _write_file(
            branch / "apps" / "handlers" / "git" / "repo_door.py",
            "def extract_repo_flag(args):\n    return args\n",
        )
        _write_file(
            branch / "apps" / (branch.name + ".py"),
            "from aipass.{name}.apps.handlers.git import (\n"
            "    lock_handler,  # repo_door moved out\n"
            ")\n\n"
            "def handle_command():\n"
            "    return lock_handler\n".format(name=branch.name),
        )

        result = dead_code_check_branch(str(branch))

        assert result["score"] == 0
        assert "repo_door.py" in result["checks"][0]["message"]

    @pytest.mark.parametrize(
        ("name", "tail", "dead"),
        [
            ("door_trail.py", "", False),
            ("door_trail.py", "\n\ndef log_more():\n    return log_operation\n", False),
            ("trail_view.py", "", False),
            ("trail_view.py", "\n\ndef log_more():\n    return log_operation\n", True),
        ],
        ids=["second_door_by_name", "second_door_by_name_with_logic", "second_door_by_shape", "unnamed_real_module"],
    )
    def test_a_second_door_is_left_to_front_door(self, mock_json, tmp_path, name, tail, dead) -> None:
        """front_door convicts a second door (retired pattern); its unreferenced file is the same defect, one report."""
        branch = _make_branch(tmp_path)
        _write_file(branch / "apps" / "handlers" / "trail.py", "def log_operation():\n    return True\n")
        door = f'from aipass.{branch.name}.apps.handlers.trail import log_operation\n\n__all__ = ["log_operation"]\n'
        _write_file(branch / "apps" / "modules" / name, door + tail)
        _write_file(branch / "apps" / (branch.name + ".py"), "def handle_command(): pass\n")

        result = dead_code_check_branch(str(branch))

        assert (name in result["checks"][0]["message"]) is dead


@patch("aipass.sentry.apps.handlers.aipass_standards.unused_function_check.json_handler")
class TestUnusedFunctionCheck:
    """Tests for the unused_function_check checker."""

    def test_unused_function_clean_passes(self, mock_json, tmp_path: Path) -> None:
        """Branch where all functions are referenced scores >= 75."""
        branch = _make_branch(tmp_path)
        _write_file(
            branch / "apps" / "modules" / "utils.py",
            "def helper():\n    return 1\n",
        )
        _write_file(
            branch / "apps" / (branch.name + ".py"),
            "from modules.utils import helper\ndef handle_command():\n    return helper()\n",
        )
        result = unused_function_check_branch(str(branch))
        assert result["score"] >= 75
        assert result["standard"] == "UNUSED_FUNCTION"

    def test_unused_function_violation_caught(self, mock_json, tmp_path: Path) -> None:
        """Branch with unused functions is detected."""
        branch = _make_branch(tmp_path)
        _write_file(
            branch / "apps" / "modules" / "bloat.py",
            (
                "def used_func():\n"
                "    return 1\n"
                "\n"
                "def never_called_alpha():\n"
                "    return 2\n"
                "\n"
                "def never_called_beta():\n"
                "    return 3\n"
                "\n"
                "def never_called_gamma():\n"
                "    return 4\n"
                "\n"
                "def never_called_delta():\n"
                "    return 5\n"
            ),
        )
        _write_file(
            branch / "apps" / (branch.name + ".py"),
            "from modules.bloat import used_func\ndef handle_command():\n    return used_func()\n",
        )
        result = unused_function_check_branch(str(branch))
        # Keyed on the check's own PAYLOAD, not on prose in its message, so rewording never reddens it.
        unused_checks = [c for c in result["checks"] if c.get("unused")]
        assert len(unused_checks) > 0
        assert any("never_called_delta" in u["name"] for c in unused_checks for u in c["unused"])

    def test_a_method_overriding_an_imported_base_is_used_by_the_base(self, mock_json, tmp_path: Path) -> None:
        """socketserver calls handle() by name; the override is used though the branch never names it."""
        branch = _make_branch(tmp_path)
        _write_file(
            branch / "apps" / "handlers" / "server.py",
            (
                "import socketserver\n"
                "from socketserver import BaseRequestHandler\n"
                "\n"
                "class Echo(BaseRequestHandler):\n"
                "    def handle(self):\n"
                "        return 1\n"
                "\n"
                "    def never_overridden(self):\n"
                "        return 2\n"
                "\n"
                "class Dotted(socketserver.BaseRequestHandler):\n"
                "    def finish(self):\n"
                "        return 3\n"
                "\n"
                "class Unresolved(Unknown):\n"
                "    def setup(self):\n"
                "        return 4\n"
            ),
        )
        result = unused_function_check_branch(str(branch))
        names = {u["name"] for c in result["checks"] for u in c.get("unused", [])}
        assert names == {"never_overridden", "setup"}

    def test_unused_function_bypass_respected(self, mock_json, tmp_path: Path) -> None:
        """Bypass rules produce score=100."""
        branch = _make_branch(tmp_path)
        _write_file(
            branch / "apps" / "modules" / "orphan.py",
            "def never_called():\n    pass\n",
        )
        bypass = [{"file": str(branch), "standard": "unused_function"}]
        result = unused_function_check_branch(str(branch), bypass_rules=bypass)
        assert result["score"] == 100
        assert result["passed"] is True

    def test_unused_function_respects_sentry_ignore_dotfile(self, mock_json, tmp_path: Path) -> None:
        """A .sentryignore dropped alongside an unused function's file suppresses the flag."""
        branch = _make_branch(tmp_path)
        experiment_dir = branch / "apps" / "handlers" / "experiment"
        _write_file(experiment_dir / ".sentryignore", "*\n")
        _write_file(
            experiment_dir / "scratch.py",
            "def never_called():\n    pass\n",
        )
        result = unused_function_check_branch(str(branch))
        assert result["score"] == 100
        assert result["passed"] is True


# A file caught mid-save must not sink the branch


@patch("aipass.sentry.apps.handlers.aipass_standards.unused_function_check.json_handler.log_operation")
def test_unused_function_survives_a_file_that_cannot_be_tokenized(mock_log, tmp_path):
    """IndentationError is a SyntaxError, not a TokenError."""
    branch = tmp_path / "victim"
    (branch / "apps").mkdir(parents=True)
    (branch / "apps" / "good.py").write_text(
        "def alpha():\n    return beta()\n\n\ndef beta():\n    return 1\n", encoding="utf-8"
    )
    (branch / "apps" / "midsave.py").write_text("def helper():\n    return 1\n  stray = 2\n", encoding="utf-8")

    result = unused_function_check_branch(str(branch))

    assert result["score"] > 0
    assert "error" not in result
    # A file Python cannot parse is named, not counted as a file with no functions.
    assert result.get("unparsed") == ["apps/midsave.py"]
    # The completed scan is logged last, with what it measured: alpha has no caller, beta has one.
    # (json_handler is the fleet's shared shim, so the .sentryignore load logs through it first.)
    mock_log.assert_called_with(
        "check_completed",
        {
            "branch": str(branch),
            "score": 50,
            "standard": "unused_function",
            "total_functions": 2,
            "unused_count": 1,
        },
    )


def test_unused_function_counts_a_call_made_from_a_file_that_cannot_be_tokenized(tmp_path):
    """A file caught mid-save still counts as a caller: the tokenizer falls back to the raw corpus."""
    branch = tmp_path / "victim"
    (branch / "apps").mkdir(parents=True)
    (branch / "apps" / "good.py").write_text("def beta():\n    return 1\n", encoding="utf-8")
    # Falls back to the raw corpus rather than raising -- the name must survive.
    (branch / "apps" / "midsave.py").write_text("def helper():\n    return beta()\n  stray = 2\n", encoding="utf-8")

    result = unused_function_check_branch(str(branch))

    assert result["score"] == 100
    assert result["checks"][0]["message"] == "All 1 functions are referenced"


def _fstring_branch(tmp_path: Path, use: str) -> dict:
    """A branch whose one function, helper, is named only by the line *use*."""
    branch = tmp_path / "victim"
    _write_file(branch / "apps" / "lib.py", f"def helper():\n    return 1\n\n\nMESSAGE = {use}\n")
    return unused_function_check_branch(str(branch))


def _one_string_per_fstring(readline):
    """The 3.10/3.11 token shape on any interpreter: an f-string as ONE STRING token.

    3.12+ tokenizes an f-string as FSTRING_START/MIDDLE/END around real tokens;
    this folds each such run back into the single STRING the older tokenizer
    hands over. On 3.10/3.11 there is nothing to fold. Single-line specimens only.
    """
    start, end = getattr(tokenize, "FSTRING_START", None), getattr(tokenize, "FSTRING_END", None)
    depth, opened = 0, (0, 0)
    for tok in tokenize.generate_tokens(readline):
        if start is not None and tok.type == start:
            opened = tok.start if depth == 0 else opened
            depth += 1
        elif end is not None and tok.type == end:
            depth -= 1
            if depth == 0:
                text = tok.line[opened[1] : tok.end[1]]
                yield tokenize.TokenInfo(tokenize.STRING, text, opened, tok.end, tok.line)
        elif depth == 0:
            yield tok


@pytest.fixture
def older_tokenizer(monkeypatch):
    """Hand the checker the 3.10/3.11 tokenizer where the checker looks for it (compass 493)."""
    older = SimpleNamespace(
        generate_tokens=_one_string_per_fstring,
        STRING=tokenize.STRING,
        COMMENT=tokenize.COMMENT,
        TokenError=tokenize.TokenError,
    )
    monkeypatch.setattr(unused_function_check, "tokenize", older)


FSTRING_FIELD_USES = ['f"{helper()}"', 'f"total {helper() + 1:>{helper()}}"', "f'{obj.helper}'"]


@pytest.mark.parametrize("tokenizer", ["host", "older"])
@pytest.mark.parametrize("use", FSTRING_FIELD_USES)
def test_a_name_in_an_fstring_field_is_a_reference(tmp_path, request, tokenizer, use):
    """A replacement field is code, so the name in it is a caller (sentry, fleet green leg 9)."""
    if tokenizer == "older":
        request.getfixturevalue("older_tokenizer")

    result = _fstring_branch(tmp_path, use)

    assert result["checks"][0]["message"] == "All 1 functions are referenced", result


DOTTED_PATH_USES = ['f"{ROOT}.lib.helper"', '"aipass.victim.lib.helper"']


@pytest.mark.parametrize("tokenizer", ["host", "older"])
@pytest.mark.parametrize("use", DOTTED_PATH_USES)
def test_a_string_that_is_a_dotted_path_names_its_last_segment(tmp_path, request, tokenizer, use):
    """A registry names a handler by its import path, and a loader calls it (sentry, fleet green leg 11)."""
    if tokenizer == "older":
        request.getfixturevalue("older_tokenizer")

    result = _fstring_branch(tmp_path, use)

    assert result["checks"][0]["message"] == "All 1 functions are referenced", result


FSTRING_TEXT_USES = [
    'f"call helper later {1}"',
    "f'helper'",
    'f"{1:helper}"',
    '"see lib.helper for details"',
    '"lib.helper.txt"',
    'f"{ROOT}.lib.helper()"',
    '".helper"',
    "\"use 'lib.helper' here\"",
    "f\"use '{ROOT}.lib.helper' here\"",
]


@pytest.mark.parametrize("tokenizer", ["host", "older"])
@pytest.mark.parametrize("use", FSTRING_TEXT_USES)
def test_a_name_in_fstring_text_is_not_a_reference(tmp_path, request, tokenizer, use):
    """The literal text of an f-string is prose, as in any string: helper still has no caller."""
    if tokenizer == "older":
        request.getfixturevalue("older_tokenizer")

    result = _fstring_branch(tmp_path, use)

    assert result["score"] == 0, result
    assert [row["name"] for row in result["checks"][0]["unused"]] == ["helper"], result


def _charged_with_a_live_copy(root):
    """(file, name) of every row check_branch charges: apps/m.py and its .live-* copy define g."""
    body = "def g():\n    return 1\n"
    (root / "apps").mkdir(parents=True)
    (root / "apps" / "m.py").write_text(body, encoding="utf-8")
    copy = root / ".live-20260101T000000Z"
    copy.mkdir()
    (copy / "m.py").write_text(body, encoding="utf-8")
    checks = unused_function_check.check_branch(str(root))["checks"]
    return [(Path(row["file"]), row["name"]) for row in checks[0].get("unused", [])]


def test_a_top_level_dot_directory_copy_is_not_charged(tmp_path):
    """hooks keeps promoted engine copies under .live-<stamp>/ (sentry, fleet green leg 16)."""
    assert _charged_with_a_live_copy(tmp_path / "branchroot") == [(Path("apps", "m.py"), "g")]


def test_a_root_standing_inside_a_dotted_directory_is_still_read(tmp_path):
    """The skip reads the parts relative to the branch root, never the whole path."""
    assert _charged_with_a_live_copy(tmp_path / ".live-x" / "branchroot") == [(Path("apps", "m.py"), "g")]


def _charged_names(root: Path, files: dict[str, str]) -> list[str]:
    """Sorted names check_branch charges for a branch made of ``files``."""
    for relative, body in files.items():
        _write_file(root / relative, body)
    return sorted(row["name"] for row in unused_function_check.check_branch(str(root))["checks"][0].get("unused", []))


def test_one_pass_over_the_corpus_counts_as_the_per_name_scans_did(tmp_path):
    """Words and definition lines are counted once per branch (sentry, fleet green leg 18)."""
    body = (
        "async def  idle():\n    return run_all()\n\n\n"
        "def run_all():\n    return 1\n\n\n"
        "def run():\n    return 2\n\n\n"
        "def  helper():\n    return 3\n"
    )
    files = {"apps/a.py": body, "apps/b.py": "x = helper()\n"}
    assert _charged_names(tmp_path / "branchroot", files) == ["idle", "run"]


def test_a_name_with_a_mark_no_word_pattern_reads_is_still_counted(tmp_path):
    """A name holding a character ``\\w`` does not match is counted by its own scan."""
    name = "aिb"
    files = {"apps/a.py": f"def {name}():\n    return 1\n", "apps/b.py": f"x = {name}()\n"}
    assert _charged_names(tmp_path / "branchroot", files) == []


def _dead(branch: Path) -> list[str]:
    """The unreferenced files dead_code names, relative to apps/."""
    message = dead_code_check_branch(str(branch))["checks"][0]["message"]
    return sorted(message.split(": ", 1)[1].split(" -- ")[0].split(", ")) if "unreferenced" in message else []


class TestDeadCodeReadsTheProjectConfig:
    """A handler the engine dispatches by dotted path in .aipass/*.json is referenced (sentry, leg fed78ad8)."""

    HANDLERS = ("lifecycle/boot.py", "security/gate.py")

    def _project(self, tmp_path, config, registry=True, config_name="x.json"):
        project = tmp_path / "proj"
        branch = project / "src" / "aipass" / "mybranch"
        _make_branch(branch)
        _write_file(branch / "apps" / "mybranch.py", "def handle_command():\n    pass\n")
        for handler in self.HANDLERS:
            _write_file(branch / "apps" / "handlers" / handler, "def handle(data):\n    return data\n")
        if registry:
            _write_file(project / "PROJ_REGISTRY.json", "{}")
        _write_file(project / ".aipass" / config_name, config)
        return branch

    @pytest.mark.parametrize("registry", [True, False], ids=["seat", "clean_checkout"])
    def test_the_install_config_references_a_handler_with_or_without_the_registry(self, tmp_path, registry):
        """AIPASS_REGISTRY.json is git-ignored: CI read hooks 88 where the seat read 100 (addendum d13d7c68 B)."""
        config = '{"a": "aipass.mybranch.apps.handlers.lifecycle.boot.handle"}'
        branch = self._project(tmp_path, config, registry=registry, config_name="hooks.json")
        assert _dead(branch) == ["handlers/security/gate.py"]

    def test_a_dotted_path_in_the_config_references_a_handler_and_a_stem_does_not(self, tmp_path):
        config = '{"a": "aipass.mybranch.apps.handlers.lifecycle.boot.handle", "b": "gate"}'
        assert _dead(self._project(tmp_path, config)) == ["handlers/security/gate.py"]

    def test_a_longer_module_name_does_not_reference_its_prefix(self, tmp_path):
        config = (
            '{"a": "aipass.mybranch.apps.handlers.lifecycle.boot_extra.handle", '
            '"b": "x.aipass.mybranch.apps.handlers.security.gate"}'
        )
        assert _dead(self._project(tmp_path, config)) == ["handlers/lifecycle/boot.py", "handlers/security/gate.py"]

    def test_a_config_with_no_registry_root_above_the_branch_references_nothing(self, tmp_path):
        config = '{"a": "aipass.mybranch.apps.handlers.lifecycle.boot.handle"}'
        assert _dead(self._project(tmp_path, config, registry=False)) == [
            "handlers/lifecycle/boot.py",
            "handlers/security/gate.py",
        ]


class TestASkipNamedPackageIsSource:
    """commons keeps live code in apps/handlers/artifacts/, a SOURCE_SKIP_DIRS name (sentry, leg fed78ad8)."""

    def _commons_shape(self, tmp_path):
        branch = _make_branch(tmp_path)
        _write_file(branch / "apps" / (branch.name + ".py"), "def handle_command():\n    pass\n")
        _write_file(branch / "apps" / "handlers" / "artifacts" / "__init__.py", "")
        _write_file(branch / "apps" / "handlers" / "artifacts" / "trade_ops.py", "def never_traded():\n    return 1\n")
        return branch

    def test_dead_code_reads_a_skip_named_package(self, tmp_path):
        assert _dead(self._commons_shape(tmp_path)) == ["handlers/artifacts/trade_ops.py"]

    def test_unused_function_reads_a_skip_named_package(self, tmp_path):
        checks = unused_function_check_branch(str(self._commons_shape(tmp_path)))["checks"]
        assert [u["name"] for c in checks if c.get("unused") for u in c["unused"]] == ["never_traded"]

    def test_an_archive_beside_the_package_is_still_skipped(self, tmp_path):
        branch = self._commons_shape(tmp_path)
        _write_file(branch / "apps" / "handlers" / ".archive" / "old_ops.py", "def retired():\n    return 1\n")
        assert _dead(branch) == ["handlers/artifacts/trade_ops.py"]
