"""Tests for 6 seedgo checker handlers: stderr_routing, todo, trigger, dead_code, test_quality, unused_function."""

# =================== META ====================
# Name: test_checkers_batch4.py
# Description: Unit tests for 6 seedgo checker handlers (batch 4)
# Version: 1.0.0
# Created: 2026-03-29
# Modified: 2026-03-29
# =============================================

from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.seedgo.apps.handlers.aipass_standards.stderr_routing_check import (
    check_module as stderr_check_module,
)
from aipass.seedgo.apps.handlers.aipass_standards.todo_check import (
    check_module as todo_check_module,
)
from aipass.seedgo.apps.handlers.aipass_standards.trigger_check import (
    check_module as trigger_check_module,
)
from aipass.seedgo.apps.handlers.aipass_standards.dead_code_check import (
    check_branch as dead_code_check_branch,
)
from aipass.seedgo.apps.handlers.aipass_standards.test_quality_check import (
    check_branch as quality_check_branch,
)
from aipass.seedgo.apps.handlers.aipass_standards.unused_function_check import (
    check_branch as unused_function_check_branch,
)


# =============================================
# HELPERS
# =============================================

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


# =============================================
# 1. stderr_routing_check (check_module)
# =============================================

@patch("aipass.seedgo.apps.handlers.aipass_standards.stderr_routing_check.json_handler")
class TestStderrRoutingCheck:
    """Tests for the stderr_routing_check checker."""

    def test_stderr_routing_clean_passes(self, mock_json, tmp_path: Path) -> None:
        """Clean code with no stderr violations passes with score >= 75."""
        py_file = tmp_path / "clean_module.py"
        _write_file(py_file, (
            "from aipass.cli.apps.modules import error, warning\n"
            "\n"
            "def do_work():\n"
            "    error('Something failed', suggestion='Try again')\n"
            "    warning('Heads up', details='Check config')\n"
        ))
        result = stderr_check_module(str(py_file))
        assert result["score"] >= 75
        assert result["standard"] == "STDERR_ROUTING"

    def test_stderr_routing_violation_caught(self, mock_json, tmp_path: Path) -> None:
        """Code with Console(stderr=True) is detected as a violation."""
        py_file = tmp_path / "bad_module.py"
        _write_file(py_file, (
            "from rich.console import Console\n"
            "\n"
            "err = Console(stderr=True)\n"
            "err.print('bad output')\n"
        ))
        result = stderr_check_module(str(py_file))
        failed_names = [c["name"] for c in result["checks"] if not c["passed"]]
        assert "Stderr console creation" in failed_names

    def test_stderr_routing_bypass_respected(self, mock_json, tmp_path: Path) -> None:
        """Bypass rules produce score=100."""
        py_file = tmp_path / "bypassed_module.py"
        _write_file(py_file, (
            "from rich.console import Console\n"
            "err = Console(stderr=True)\n"
        ))
        bypass = [{"standard": "stderr_routing"}]
        result = stderr_check_module(str(py_file), bypass_rules=bypass)
        assert result["score"] == 100
        assert result["passed"] is True


# =============================================
# 2. todo_check (check_module)
# =============================================

@patch("aipass.seedgo.apps.handlers.aipass_standards.todo_check.json_handler")
class TestTodoCheck:
    """Tests for the todo_check checker."""

    def test_todo_clean_passes(self, mock_json, tmp_path: Path) -> None:
        """Code with no TODO/FIXME/HACK/XXX comments passes with score >= 75."""
        py_file = tmp_path / "clean.py"
        _write_file(py_file, (
            "def greet(name: str) -> str:\n"
            "    return f'Hello, {name}'\n"
        ))
        result = todo_check_module(str(py_file))
        assert result["score"] >= 75
        assert result["passed"] is True
        assert result["standard"] == "TODO"

    def test_todo_violation_caught(self, mock_json, tmp_path: Path) -> None:
        """Code containing TODO and FIXME comments is detected."""
        py_file = tmp_path / "messy.py"
        _write_file(py_file, (
            "def compute():\n"
            "    # TODO: implement this properly\n"
            "    # FIXME: off-by-one error\n"
            "    return 42\n"
        ))
        result = todo_check_module(str(py_file))
        assert result["passed"] is False
        assert result["score"] == 0
        assert any("TODO" in c["message"] for c in result["checks"])

    def test_todo_bypass_respected(self, mock_json, tmp_path: Path) -> None:
        """Bypass rules produce score=100."""
        py_file = tmp_path / "bypassed.py"
        _write_file(py_file, (
            "# TODO: this should be bypassed\n"
            "x = 1\n"
        ))
        bypass = [{"standard": "todo"}]
        result = todo_check_module(str(py_file), bypass_rules=bypass)
        assert result["score"] == 100
        assert result["passed"] is True


# =============================================
# 3. trigger_check (check_module)
# =============================================

@patch("aipass.seedgo.apps.handlers.aipass_standards.trigger_check.json_handler")
class TestTriggerCheck:
    """Tests for the trigger_check checker."""

    def test_trigger_clean_passes(self, mock_json, tmp_path: Path) -> None:
        """Code with no trigger patterns scores >= 75."""
        py_file = tmp_path / "plain.py"
        _write_file(py_file, (
            "def add(a: int, b: int) -> int:\n"
            "    return a + b\n"
        ))
        result = trigger_check_module(str(py_file))
        assert result["score"] >= 75
        assert result["standard"] == "TRIGGER"

    def test_trigger_violation_caught(self, mock_json, tmp_path: Path) -> None:
        """Code with lifecycle functions but no trigger.fire() is detected."""
        py_file = tmp_path / "modules" / "lifecycle.py"
        py_file.parent.mkdir(parents=True, exist_ok=True)
        _write_file(py_file, (
            "def create_backup(data):\n"
            "    pass\n"
            "\n"
            "def delete_record(record_id):\n"
            "    pass\n"
        ))
        result = trigger_check_module(str(py_file))
        failed_names = [c["name"] for c in result["checks"] if not c["passed"]]
        assert "Missing trigger events" in failed_names

    def test_trigger_bypass_respected(self, mock_json, tmp_path: Path) -> None:
        """Bypass rules produce score=100."""
        py_file = tmp_path / "bypassed_trigger.py"
        _write_file(py_file, (
            "def create_backup(data):\n"
            "    pass\n"
        ))
        bypass = [{"standard": "trigger"}]
        result = trigger_check_module(str(py_file), bypass_rules=bypass)
        assert result["score"] == 100
        assert result["passed"] is True


# =============================================
# 4. dead_code_check (check_branch)
# =============================================

@patch("aipass.seedgo.apps.handlers.aipass_standards.dead_code_check.json_handler")
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
            "from aipass.{name}.apps.modules.helper import do_something\n"
            "def handle_command(): do_something()\n".format(name=branch.name),
        )
        result = dead_code_check_branch(str(branch))
        assert result["score"] >= 75
        assert result["standard"] == "DEAD_CODE"

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
        bypass = [{"standard": "dead_code"}]
        result = dead_code_check_branch(str(branch), bypass_rules=bypass)
        assert result["score"] == 100
        assert result["passed"] is True


# =============================================
# 5. test_quality_check (check_branch)
# =============================================

@patch("aipass.seedgo.apps.handlers.aipass_standards.test_quality_check.json_handler")
class TestTestQualityCheck:
    """Tests for the test_quality_check checker."""

    def test_test_quality_clean_passes(self, mock_json, tmp_path: Path) -> None:
        """Branch with test files containing relevant patterns scores >= 75."""
        branch = _make_branch(tmp_path)
        tests_dir = branch / "tests"
        tests_dir.mkdir()

        # Create a module so module_coverage has something to find
        _write_file(
            branch / "apps" / "modules" / "core.py",
            "def run(): pass\n",
        )

        # Write a comprehensive conftest that covers many pattern categories
        _write_file(tests_dir / "conftest.py", (
            "import pytest\n"
            "from pathlib import Path\n"
            "from unittest.mock import MagicMock\n"
            "import importlib\n"
            "\n"
            "@pytest.fixture\n"
            "def tmp_path(tmp_path):\n"
            "    return tmp_path\n"
            "\n"
            "@pytest.fixture\n"
            "def sample_test_data():\n"
            "    return {'key': 'value'}\n"
            "\n"
            "@pytest.fixture(autouse=True)\n"
            "def mock_infrastructure():\n"
            "    yield\n"
            "\n"
            "@pytest.fixture\n"
            "def mock_logger():\n"
            "    return MagicMock()\n"
            "\n"
            "@pytest.fixture\n"
            "def mock_json_handler():\n"
            "    return MagicMock()\n"
            "\n"
            "@pytest.fixture\n"
            "def cleanup(tmp_path):\n"
            "    from shutil import rmtree\n"
            "    yield tmp_path\n"
            "    rmtree(tmp_path, ignore_errors=True)\n"
        ))

        # Write a test file that covers many standard categories
        _write_file(tests_dir / "test_core.py", (
            "import pytest\n"
            "import sys\n"
            "import importlib\n"
            "from pathlib import Path\n"
            "from aipass.{name}.apps.modules.core import run\n"
            "\n"
            "def test_json_handler_create_default():\n"
            "    result = _create_default()\n"
            "    assert validate_json_structure(result)\n"
            "    p = get_json_path('test')\n"
            "    assert ensure_json_exists(p) is True\n"
            "    data = load_json(p)\n"
            "    save_json(p, data)\n"
            "    log_operation('test', {{}})\n"
            "    ensure_module_jsons('mod')\n"
            "\n"
            "def test_cli_routing():\n"
            "    result = run('--help')\n"
            '    run("-h")\n'
            "    run('help')\n"
            "    # test_no_args path\n"
            "    assert 'unknown_command' or True\n"
            "    assert result is True\n"
            "    assert result is False\n"
            "    print_help()\n"
            "    print_introspection()\n"
            "    capsys = None\n"
            "\n"
            "def test_error_resilience():\n"
            "    with pytest.raises(FileNotFoundError):\n"
            "        pass\n"
            "    # corrupt json\n"
            "    from json import JSONDecodeError\n"
            "    # empty_file test\n"
            "    empty_content = ''\n"
            "    # nonexistent dir\n"
            "    pass\n"
            "\n"
            "def test_return_type_contracts():\n"
            "    assert isinstance(result, bool)\n"
            "    assert isinstance(result, Path)\n"
            "    assert ensure_json_exists(p) is True\n"
            "    assert isinstance(result, dict)\n"
            "\n"
            "def test_exception_contracts():\n"
            "    with pytest.raises(ValueError):\n"
            "        _create_default()\n"
            "    with pytest.raises(Exception):\n"
            "        save_json(None, None)\n"
            "    # invalid_mode test\n"
            "    pass\n"
            "\n"
            "def test_data_structure_contracts():\n"
            "    assert 'module_name' in result\n"
            "    assert 'last_updated' in result\n"
            "    assert 'log_entry' in result\n"
            "\n"
            "def test_success_failure_paths():\n"
            "    assert result is True\n"
            "    assert result is False\n"
            "    run('--help')\n"
            "    print_introspection()\n"
            "\n"
            "def test_init_provisioning():\n"
            "    assert p.exists()\n"
            "    ensure_json_exists(p)\n"
            "    import os; os.makedirs('x', exist_ok=True)\n"
            "    # no_overwrite / already_exists check\n"
            "    already_exists = True\n"
            "    assert isinstance(result, dict)\n"
            "\n"
            "def test_infrastructure_mocking():\n"
            "    # autouse=True fixture\n"
            "    sys.modules['fake'] = MagicMock()\n"
            "    importlib.reload(mod)\n"
            "\n".format(name=branch.name)
        ))

        result = quality_check_branch(str(branch))
        assert result["score"] >= 75
        assert result["standard"] == "TEST_QUALITY"

    def test_test_quality_violation_caught(self, mock_json, tmp_path: Path) -> None:
        """Branch with no test files scores 0."""
        branch = _make_branch(tmp_path)
        # No tests/ directory at all
        result = quality_check_branch(str(branch))
        assert result["score"] == 0
        assert result["passed"] is False

    def test_test_quality_bypass_respected(self, mock_json, tmp_path: Path) -> None:
        """Bypass rules produce score=100."""
        branch = _make_branch(tmp_path)
        bypass = [{"standard": "test_quality"}]
        result = quality_check_branch(str(branch), bypass_rules=bypass)
        assert result["score"] == 100
        assert result["passed"] is True


# =============================================
# 6. unused_function_check (check_branch)
# =============================================

@patch("aipass.seedgo.apps.handlers.aipass_standards.unused_function_check.json_handler")
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
            "from modules.utils import helper\n"
            "def handle_command():\n"
            "    return helper()\n",
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
            "from modules.bloat import used_func\n"
            "def handle_command():\n"
            "    return used_func()\n",
        )
        result = unused_function_check_branch(str(branch))
        unused_checks = [c for c in result["checks"] if "unused" in c["message"].lower()]
        assert len(unused_checks) > 0

    def test_unused_function_bypass_respected(self, mock_json, tmp_path: Path) -> None:
        """Bypass rules produce score=100."""
        branch = _make_branch(tmp_path)
        _write_file(
            branch / "apps" / "modules" / "orphan.py",
            "def never_called():\n    pass\n",
        )
        bypass = [{"standard": "unused_function"}]
        result = unused_function_check_branch(str(branch), bypass_rules=bypass)
        assert result["score"] == 100
        assert result["passed"] is True
