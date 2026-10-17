# =================== META ====================
# Name: test_checkers_batch7.py
# Description: Unit tests for encapsulation_check sub-functions (the other checkers moved to test_checkers_batch7_*.py)
# Version: 1.3.2
# Created: 2026-04-25
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/aipass_standards/encapsulation_check.py and its sibling checkers (batch 7)."""

# Seedgo checker sub-functions, batch 7: encapsulation. Imports, introspection,
# modules and the cli, documentation, error_handling, handlers, json_structure,
# silent_catch and unused_function rulings live in test_checkers_batch7_<checker>.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that each checker in handlers/aipass_standards/ parses and imports
# seedgo: no-test-needed(stdlib) — ast.parse's parsing; the checkers only walk the tree it returns

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import encapsulation_check
from aipass.seedgo.apps.handlers.aipass_standards.encapsulation_check import (
    check_cross_branch_imports,
    check_cross_package_imports,
    check_direct_handler_imports,
    extract_branch_from_import,
    extract_handler_package,
    get_file_handler_package,
)
from aipass.seedgo.tests.support_checkers_batch7 import _lines

pytestmark = pytest.mark.usefixtures("_pin_bypass_log")


class TestExtractBranchFromImport:
    """Tests for extract_branch_from_import."""

    def test_branch_dot_apps_handlers(self):
        """Extract branch from 'from flow.apps.handlers...' pattern."""
        result = extract_branch_from_import("from flow.apps.handlers.plan.validator import X")
        assert result == "flow"

    def test_aipass_dot_branch_pattern(self):
        """Extract branch from 'from aipass.api.apps.handlers...' pattern."""
        result = extract_branch_from_import("from aipass.api.apps.handlers.openrouter import X")
        assert result == "api"

    def test_local_import_returns_none(self):
        """Local import without branch returns None."""
        result = extract_branch_from_import("from apps.handlers.json import X")
        assert result is None

    def test_import_statement_form(self):
        """Extract branch from 'import branch.apps.handlers...' pattern."""
        result = extract_branch_from_import("import seedgo.apps.handlers.json")
        assert result == "seedgo"

    def test_handlers_nested_under_a_branch_tree_are_that_branchs(self):
        """daemon's telegram_notifier.py:28 imports skills' lib/telegram handlers (measured 10-08)."""
        line = "from aipass.skills.lib.telegram.apps.handlers.notifier import ("
        violation = check_cross_branch_imports([line], "daemon/apps/handlers/schedule/notifier_use.py", "daemon")

        assert extract_branch_from_import(line) == "skills"
        assert violation["message"] == "Line 1: skills.apps.handlers imported (use modules entry point)"


class TestExtractHandlerPackage:
    """Tests for extract_handler_package."""

    def test_extracts_json(self):
        """Extract 'json' from handler import path."""
        result = extract_handler_package("from apps.handlers.json.json_handler import X")
        assert result == "json"

    def test_extracts_dashboard(self):
        """Extract 'dashboard' from handler import path."""
        result = extract_handler_package("from apps.handlers.dashboard.refresh import X")
        assert result == "dashboard"

    def test_cross_branch_handler(self):
        """Extract package from cross-branch handler import."""
        result = extract_handler_package("from flow.apps.handlers.plan.validator import X")
        assert result == "plan"

    def test_no_handlers_returns_none(self):
        """Import without apps.handlers returns None."""
        result = extract_handler_package("from apps.modules.audit import run")
        assert result is None


class TestGetFileHandlerPackage:
    """Tests for get_file_handler_package."""

    def test_handler_file_returns_package(self, tmp_path):
        """File in handlers/json/ returns 'json'."""
        result = get_file_handler_package((tmp_path / "apps" / "handlers" / "json" / "json_handler.py").as_posix())
        assert result == "json"

    def test_non_handler_returns_none(self, tmp_path):
        """File in modules/ returns None."""
        result = get_file_handler_package((tmp_path / "apps" / "modules" / "something.py").as_posix())
        assert result is None


class TestCheckHandlerGuard:
    """Tests for check_handler_guard."""

    def test_guard_present_passes(self, tmp_path, monkeypatch):
        """Branch with inspect.stack guard in handlers/__init__.py passes."""
        monkeypatch.setattr(encapsulation_check, "_handler_guard_cache", {})

        branch = tmp_path / "mybranch"
        handlers_dir = branch / "apps" / "handlers"
        handlers_dir.mkdir(parents=True)
        init_file = handlers_dir / "__init__.py"
        init_file.write_text(
            "import inspect\n"
            "def _guard_branch_access():\n"
            "    frame = inspect.stack()\n"
            "    raise ImportError('blocked')\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(
            encapsulation_check,
            "get_branch_from_path",
            lambda fp: {"name": "mybranch", "path": str(branch)},
        )

        result = encapsulation_check.check_handler_guard(str(handlers_dir / "json" / "handler.py"))
        assert result is not None
        assert result["passed"] is True
        assert "guard present" in result["message"]

    def test_guard_missing_fails(self, tmp_path, monkeypatch):
        """Branch without guard in handlers/__init__.py fails."""
        monkeypatch.setattr(encapsulation_check, "_handler_guard_cache", {})

        branch = tmp_path / "mybranch"
        handlers_dir = branch / "apps" / "handlers"
        handlers_dir.mkdir(parents=True)
        init_file = handlers_dir / "__init__.py"
        init_file.write_text("# empty init\n", encoding="utf-8")

        monkeypatch.setattr(
            encapsulation_check,
            "get_branch_from_path",
            lambda fp: {"name": "mybranch", "path": str(branch)},
        )

        result = encapsulation_check.check_handler_guard(str(handlers_dir / "json" / "handler.py"))
        assert result is not None
        assert result["passed"] is False

    def test_no_handlers_dir_returns_none(self, tmp_path, monkeypatch):
        """Branch without handlers/ directory returns None."""
        monkeypatch.setattr(encapsulation_check, "_handler_guard_cache", {})

        branch = tmp_path / "mybranch"
        branch.mkdir(parents=True)

        monkeypatch.setattr(
            encapsulation_check,
            "get_branch_from_path",
            lambda fp: {"name": "mybranch", "path": str(branch)},
        )

        result = encapsulation_check.check_handler_guard(str(branch / "apps" / "x.py"))
        assert result is None

    @pytest.mark.parametrize(
        "eager_line",
        ["from . import handlers", "from aipass.mybranch.apps import handlers", "import aipass.mybranch.apps.handlers"],
    )
    def test_an_apps_package_that_imports_handlers_fails_the_guard(self, tmp_path, monkeypatch, eager_line):
        """The eager line kills the fence whatever the guard says (DPLAN-0404 leg 1)."""
        monkeypatch.setattr(encapsulation_check, "_handler_guard_cache", {})
        branch = tmp_path / "mybranch"
        handlers_dir = branch / "apps" / "handlers"
        handlers_dir.mkdir(parents=True)
        (handlers_dir / "__init__.py").write_text("def _guard_branch_access():\n    pass\n", encoding="utf-8")
        (branch / "apps" / "__init__.py").write_text(f'"""Apps."""\n{eager_line}\n', encoding="utf-8")
        monkeypatch.setattr(
            encapsulation_check, "get_branch_from_path", lambda fp: {"name": "mybranch", "path": str(branch)}
        )

        result = encapsulation_check.check_handler_guard(str(handlers_dir / "json" / "handler.py"))
        assert result == {
            "name": "Handler security guard",
            "passed": False,
            "message": "apps/__init__.py imports handlers: the fence sees its own package as every caller (2026-04-25)",
        }

    def test_the_v2_guard_call_passes_beside_a_clean_apps_package(self, tmp_path, monkeypatch):
        """A module-level _guard_branch_access() call is the v2 marker; prose naming handlers is not an import."""
        monkeypatch.setattr(encapsulation_check, "_handler_guard_cache", {})
        branch = tmp_path / "mybranch"
        handlers_dir = branch / "apps" / "handlers"
        handlers_dir.mkdir(parents=True)
        (handlers_dir / "__init__.py").write_text(
            "from .guard import _guard_branch_access\n_guard_branch_access()\n", encoding="utf-8"
        )
        (branch / "apps" / "__init__.py").write_text('"""Never: from . import handlers."""\n', encoding="utf-8")
        monkeypatch.setattr(
            encapsulation_check, "get_branch_from_path", lambda fp: {"name": "mybranch", "path": str(branch)}
        )

        result = encapsulation_check.check_handler_guard(str(handlers_dir / "json" / "handler.py"))
        assert result == {
            "name": "Handler security guard",
            "passed": True,
            "message": "Handler security guard present (module-level _guard_branch_access() call)",
        }


class TestCheckCrossBranchImports:
    """Tests for check_cross_branch_imports."""

    def test_no_cross_branch_passes(self, tmp_path):
        """File with no cross-branch handler imports passes."""
        lines = _lines("from apps.handlers.json import json_handler\n")
        result = check_cross_branch_imports(
            lines, (tmp_path / "seedgo" / "apps" / "modules" / "a.py").as_posix(), "seedgo"
        )
        assert result["passed"] is True

    def test_cross_branch_import_fails(self, tmp_path):
        """Importing another branch's handlers fails."""
        lines = _lines("from flow.apps.handlers.plan.validator import X\n")
        result = check_cross_branch_imports(
            lines, (tmp_path / "seedgo" / "apps" / "modules" / "a.py").as_posix(), "seedgo"
        )
        assert result["passed"] is False
        assert "flow" in result["message"]

    def test_same_branch_import_passes(self, tmp_path):
        """Importing own branch's handlers passes."""
        lines = _lines("from seedgo.apps.handlers.json import json_handler\n")
        result = check_cross_branch_imports(
            lines, (tmp_path / "seedgo" / "apps" / "modules" / "a.py").as_posix(), "seedgo"
        )
        assert result["passed"] is True

    def test_import_in_string_ignored(self, tmp_path):
        """Handler import inside a string literal is not flagged."""
        lines = _lines('"from flow.apps.handlers.plan import X"\n')
        result = check_cross_branch_imports(
            lines, (tmp_path / "seedgo" / "apps" / "modules" / "a.py").as_posix(), "seedgo"
        )
        assert result["passed"] is True

    def test_a_string_import_of_another_branch_fails_quoting_the_line(self, tmp_path):
        """A handlers target passed to import_module is an import (DPLAN-0404 leg 1)."""
        lines = _lines('x = 1\nmod = importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")\n')
        result = check_cross_branch_imports(
            lines, (tmp_path / "hooks" / "apps" / "modules" / "a.py").as_posix(), "hooks"
        )
        assert result == {
            "name": "Cross-branch handler imports",
            "passed": False,
            "message": (
                "Line 2: memory.apps.handlers imported (string import) (use modules entry point): "
                'mod = importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")'
            ),
        }

    def test_prose_and_a_same_branch_string_stay_acquitted(self, tmp_path):
        """A string that is not a call's import argument is prose; one naming its own branch is kin."""
        lines = _lines(
            'NOTE = "aipass.memory.apps.handlers.json.entry_limits"\n'
            'logger.info("aipass.memory.apps.handlers.json is memory\'s")\n'
            'mod = importlib.import_module("aipass.hooks.apps.handlers.config.loader")\n'
        )
        result = check_cross_branch_imports(
            lines, (tmp_path / "hooks" / "apps" / "modules" / "a.py").as_posix(), "hooks"
        )
        assert result == {
            "name": "Cross-branch handler imports",
            "passed": True,
            "message": "No cross-branch handler imports detected",
        }


class TestTestsAreKinToTheirOwnBranchOnly:
    """A file under tests/ is convicted for another branch's handlers, never its own (DPLAN-0404 leg 1)."""

    @staticmethod
    def _test_file(tmp_path, body: str) -> str:
        """Seat a test file in a tmp branch named hooks and return its path."""
        branch = tmp_path / "aipass" / "hooks"
        (branch / "apps").mkdir(parents=True)
        (branch / "tests").mkdir()
        test_file = branch / "tests" / "test_gate.py"
        test_file.write_text(body, encoding="utf-8")
        return str(test_file)

    @pytest.mark.parametrize(
        "body",
        [
            "from aipass.memory.apps.handlers.json import entry_limits\n",
            (
                "from unittest.mock import patch\n\n"
                'with patch("aipass.memory.apps.handlers.json.entry_limits.load"):\n    pass\n'
            ),
        ],
    )
    def test_another_branchs_handlers_convict_a_test(self, tmp_path, body):
        """An import or a patch string into memory's handlers, from hooks' tests."""
        result = encapsulation_check.check_module(self._test_file(tmp_path, body))
        assert result["score"] == 0
        assert [check["name"] for check in result["checks"]] == ["Cross-branch handler imports"]
        assert result["checks"][0]["message"].startswith("Line ")

    def test_a_nested_package_is_judged_by_the_branch_after_aipass(self, tmp_path):
        """skills' own lib/telegram handlers are kin to skills' tests; the segment before apps is not the branch."""
        body = (
            "from aipass.hooks.lib.telegram.apps.handlers import notifier\n"
            'patch("aipass.hooks.lib.telegram.apps.handlers.notifier.send")\n'
        )
        result = encapsulation_check.check_module(self._test_file(tmp_path, body))
        assert result["score"] == 100

    def test_own_handlers_and_a_source_fixture_stay_allowed(self, tmp_path):
        """Own-branch imports and patches pass; a handlers import inside a triple-quoted fixture is prose."""
        body = (
            "from unittest.mock import patch\n"
            "from aipass.hooks.apps.handlers.security import edit_gate\n"
            'SOURCE = """\n'
            "from aipass.memory.apps.handlers.json import entry_limits\n"
            'patch("aipass.memory.apps.handlers.json.entry_limits.load")\n'
            '"""\n'
            'with patch("aipass.hooks.apps.handlers.security.edit_gate.run"):\n'
            "    pass\n"
        )
        result = encapsulation_check.check_module(self._test_file(tmp_path, body))
        assert result["score"] == 100
        assert result["checks"] == [
            {
                "name": "Cross-branch handler imports",
                "passed": True,
                "message": "No cross-branch handler imports detected",
            }
        ]


class TestCheckCrossPackageImports:
    """Tests for check_cross_package_imports."""

    def test_same_package_passes(self, tmp_path):
        """Importing from same handler package passes."""
        lines = _lines("from apps.handlers.json.utils import helper\n")
        result = check_cross_package_imports(
            lines, (tmp_path / "branch" / "apps" / "handlers" / "json" / "handler.py").as_posix(), "json"
        )
        assert result["passed"] is True

    def test_cross_package_fails(self, tmp_path):
        """Importing from a different handler package fails."""
        lines = _lines("from apps.handlers.error.error_handler import X\n")
        result = check_cross_package_imports(
            lines,
            (tmp_path / "branch" / "apps" / "handlers" / "audit" / "checker.py").as_posix(),
            "audit",
        )
        assert result["passed"] is False
        assert "error" in result["message"]

    def test_allowed_json_handler_passes(self, tmp_path):
        """Importing json_handler (default allowed handler) passes."""
        lines = _lines("from apps.handlers.json.json_handler import log_op\n")
        result = check_cross_package_imports(
            lines,
            (tmp_path / "branch" / "apps" / "handlers" / "audit" / "checker.py").as_posix(),
            "audit",
        )
        assert result["passed"] is True

    def test_relative_import_passes(self, tmp_path):
        """Relative imports within same package pass."""
        lines = _lines("from .utils import helper\n")
        result = check_cross_package_imports(
            lines, (tmp_path / "branch" / "apps" / "handlers" / "json" / "handler.py").as_posix(), "json"
        )
        assert result["passed"] is True


class TestCheckDirectHandlerImports:
    """Tests for check_direct_handler_imports."""

    def test_no_handler_import_passes(self, tmp_path):
        """Entry point without handler imports passes."""
        lines = _lines("from apps.modules.audit import run_audit\n")
        result = check_direct_handler_imports(lines, (tmp_path / "branch" / "apps" / "branch.py").as_posix())
        assert result["passed"] is True

    def test_direct_handler_import_fails(self, tmp_path):
        """Entry point importing handlers directly fails."""
        lines = _lines("from apps.handlers.openrouter.client import get_response\n")
        result = check_direct_handler_imports(lines, (tmp_path / "branch" / "apps" / "branch.py").as_posix())
        assert result["passed"] is False
        assert "Handler imported directly" in result["message"]

    def test_allowed_json_handler_passes(self, tmp_path):
        """Default handlers (json_handler) are allowed from entry points."""
        lines = _lines("from apps.handlers.json.json_handler import log_op\n")
        result = check_direct_handler_imports(lines, (tmp_path / "branch" / "apps" / "branch.py").as_posix())
        assert result["passed"] is True


class TestEncapsulationDerivesItsInfrastructureAllowList:
    """@daemon, 2026-08-31: two adjacent lines in their entry point, the
    json_handler import passing and the module_root import scoring the file 66%."""

    def _allowed(self, branch_root, handler):
        """Entry point may import ``handler``. Mutant: allow list not derived in encapsulation_check.py — killed."""
        line = f"from aipass.{branch_root.name}.apps.handlers.{handler} import x"
        entry = str(branch_root / "apps" / f"{branch_root.name}.py")
        return check_direct_handler_imports([line], entry)["passed"]

    def test_a_handler_that_publishes_the_guarded_spelling_is_infrastructure(self, tmp_path):
        branch = tmp_path / "aipass" / "mybranch"
        handlers = branch / "apps" / "handlers"
        handlers.mkdir(parents=True)
        (handlers / "module_root.py").write_text("def module_file(f):\n    return f\n", encoding="utf-8")
        assert self._allowed(branch, "module_root") is True

    def test_the_canonical_json_shim_does_not_take_the_allow_list_with_it(self, tmp_path):
        """THE REGRESSION PIN. This is the CI red, reproduced."""
        branch = tmp_path / "aipass" / "mybranch"
        handlers = branch / "apps" / "handlers"
        (handlers / "json").mkdir(parents=True)
        (handlers / "module_root.py").write_text("def module_file(f):\n    return f\n", encoding="utf-8")
        (handlers / "json" / "json_handler.py").write_text(
            "from aipass.prax import json_handler\n\n_h = json_handler.for_module(__file__)\n", encoding="utf-8"
        )
        assert self._allowed(branch, "module_root") is True, (
            "the shim's arrival emptied the infrastructure set — this is the defect that reddened daemon on f8d7867f"
        )

    def test_the_file_name_varies_by_branch_and_the_function_name_does_not(self, tmp_path):
        """Four spellings ship in the fleet: module_root.py, paths.py,
        repo_root.py, module_paths.py. Keying on the file name would exempt
        some branches and not others for no reason a reader could defend."""
        spellings = {
            "paths": "def find_repo_root():\n    return None\n",
            "repo_root": "def source_root():\n    return None\n",
            "module_paths": "def module_file(f):\n    return f\n",
        }
        verdicts = []
        for index, (name, source) in enumerate(spellings.items()):
            branch = tmp_path / "aipass" / f"branch{index}"
            handlers = branch / "apps" / "handlers"
            handlers.mkdir(parents=True)
            (handlers / f"{name}.py").write_text(source, encoding="utf-8")
            (handlers / "openrouter.py").write_text("def get_response():\n    return None\n", encoding="utf-8")
            verdicts.append((name, self._allowed(branch, name), self._allowed(branch, "openrouter")))
        assert verdicts == [
            ("paths", True, False),
            ("repo_root", True, False),
            ("module_paths", True, False),
        ]

    def test_a_domain_handler_is_not_infrastructure(self, tmp_path):
        """Negative control: the set is DERIVED, not a longer allow-list. A
        domain handler stays behind its module entry point."""
        branch = tmp_path / "aipass" / "mybranch"
        handlers = branch / "apps" / "handlers"
        handlers.mkdir(parents=True)
        (handlers / "openrouter.py").write_text("def get_response():\n    return None\n", encoding="utf-8")
        assert self._allowed(branch, "openrouter") is False

    def test_calling_the_guarded_spelling_is_not_publishing_it(self, tmp_path):
        """The discriminator is DEFINING the function, not naming it."""
        branch = tmp_path / "aipass" / "mybranch"
        handlers = branch / "apps" / "handlers"
        handlers.mkdir(parents=True)
        (handlers / "consumer.py").write_text(
            "from aipass.mybranch.apps.handlers.module_root import module_file\n\nROOT = module_file(__file__)\n",
            encoding="utf-8",
        )
        assert self._allowed(branch, "consumer") is False

    def test_a_nested_definition_does_not_publish_it(self, tmp_path):
        """Module level only. A local function of the same name inside some
        other handler's body is not the branch's resolution shim."""
        branch = tmp_path / "aipass" / "mybranch"
        handlers = branch / "apps" / "handlers"
        handlers.mkdir(parents=True)
        (handlers / "sneaky.py").write_text(
            "def unrelated():\n    def module_file(f):\n        return f\n    return module_file\n",
            encoding="utf-8",
        )
        assert self._allowed(branch, "sneaky") is False

    def test_an_unreadable_handler_grants_nothing(self, tmp_path):
        """Ignorance is not evidence: a handler that cannot be parsed keeps the
        ordinary rule rather than being exempted by the failure."""
        branch = tmp_path / "aipass" / "mybranch"
        handlers = branch / "apps" / "handlers"
        handlers.mkdir(parents=True)
        (handlers / "module_root.py").write_text("def module_file(:\n", encoding="utf-8")
        assert self._allowed(branch, "module_root") is False


class TestAWindowsPathIsReadLikeAPosixOne:
    """Windows hands the checker C:\\...\\apps\\modules\\door.py, and the checker asked for "apps/modules/"."""

    _DOOR = (
        '"""Door: memory\'s entry limits, for other branches."""\n\n'
        "from aipass.memory.apps.handlers.json.entry_limits import check_file_budget, load_entry_limits\n\n"
        '__all__ = ["load_entry_limits", "check_file_budget"]\n'
    )

    def _windows_spelled(self, tmp_path, monkeypatch, *parts):
        """Write the door at tmp_path\\aipass\\memory\\apps\\<parts>, spelled as Windows spells it; return it."""
        door = "\\".join([str(tmp_path), "aipass", "memory", "apps", *parts])
        Path(door).parent.mkdir(parents=True, exist_ok=True)
        Path(door).write_text(self._DOOR, encoding="utf-8")
        # Windows infers the branch from Path.parts; this pins it on every host.
        monkeypatch.setattr(encapsulation_check, "get_branch_from_path", lambda fp: {"name": "memory", "path": "x"})
        return door

    def test_a_door_under_a_backslashed_modules_path_passes(self, tmp_path, monkeypatch):
        """Mutant: the separator normalisation dropped from check_module's module test — killed."""
        door = self._windows_spelled(tmp_path, monkeypatch, "modules", "door_entry_limits.py")
        assert "\\apps\\modules\\" in door

        result = encapsulation_check.check_module(door)

        assert [c["name"] for c in result["checks"] if not c["passed"]] == []

    def test_the_same_door_outside_modules_is_still_convicted(self, tmp_path, monkeypatch):
        """Control: an entry point under a backslashed apps path keeps the direct-import rule."""
        entry = self._windows_spelled(tmp_path, monkeypatch, "door_entry_limits.py")
        assert "\\apps\\door_entry_limits.py" in entry

        result = encapsulation_check.check_module(entry)

        assert [c["name"] for c in result["checks"] if not c["passed"]] == ["Direct handler imports"]

    def test_a_backslashed_handler_path_names_its_package(self):
        """get_file_handler_package read the same slash; a Windows handler was no handler."""
        assert get_file_handler_package("C:\\runner\\aipass\\memory\\apps\\handlers\\json\\entry_limits.py") == "json"
