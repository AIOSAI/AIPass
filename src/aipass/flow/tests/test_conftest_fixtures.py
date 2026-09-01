# =================== AIPass ====================
# Name: test_conftest_fixtures.py
# Description: The autouse fixtures must actually reach what they claim to mock
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""A mock that reaches nothing passes every test that does not assert on it.

``mock_logger`` patched ``aipass.prax.apps.modules.logger.system_logger`` — the
SOURCE attribute — while every flow module does
``from ... import system_logger as logger`` at import time and holds its own
binding. Patching upstream of a binding already taken reaches nothing, and it
reached nothing for as long as the fixture existed. Nothing failed, because a
mock nobody asserts on is indistinguishable from a mock that works.

@seedgo published the technique next to the standard after @prax ruled
(``drone @seedgo standard imports``). @spawn's note is the one worth keeping:
the correct technique already existed in their tree at one call site, written
before any of this came up — it just was not in the shared fixture. The right
answer existed in the fleet and nobody had written it down.

These tests are the writing-down. They assert the fixture's REACH, not its
existence, so the next upstream/downstream mix-up is a red test rather than a
silent hole.
"""

import sys
from pathlib import Path

import pytest

import aipass.flow.apps.handlers.registry.load_registry as load_registry_module


class TestMockLoggerReachesTheConsumersBinding:
    """The fixture must replace what flow modules actually call."""

    def test_a_consumer_module_sees_the_mock(self, mock_logger):
        """The binding a handler resolves at call time IS the mock."""
        assert load_registry_module.logger is mock_logger, (
            "the autouse mock_logger did not reach a consumer's own binding — "
            "it is patching upstream of an import that already happened"
        )

    def test_calling_the_consumers_logger_records_on_the_mock(self, mock_logger):
        """Reach is not enough: the call has to land."""
        load_registry_module.logger.warning("probe")

        mock_logger.warning.assert_called_once_with("probe")

    def test_every_imported_flow_module_with_a_logger_is_covered(self, mock_logger):
        """No module keeps a live logger while the fixture claims containment.

        Walks ``sys.modules`` rather than a written list, for the same reason
        the dead-cwd pin does: the species is a fix landing on some of N
        identical paths, and a hand-written list is one more place for N to be
        undercounted.
        """
        missed = [
            name
            for name, module in sys.modules.items()
            if name.startswith("aipass.flow.apps")
            and getattr(module, "logger", None) is not None
            and module.logger is not mock_logger
        ]

        assert missed == [], f"modules still holding a live logger: {missed}"

    def test_the_source_attribute_is_patched_too(self, mock_logger):
        """A module imported LATER in a test must bind the mock, not the real one."""
        import aipass.prax.apps.modules.logger as prax_logger

        assert prax_logger.system_logger is mock_logger


class TestTheOptOutIsRealAndNarrow:
    """``real_logger`` exists because caplog reads the real logging module."""

    @pytest.mark.real_logger
    def test_marked_tests_keep_the_real_logger(self):
        """The marker must genuinely restore the real object, not a second mock."""
        from unittest.mock import MagicMock

        assert not isinstance(load_registry_module.logger, MagicMock), (
            "the real_logger marker did not restore the real logger — a caplog assertion under it would be vacuous"
        )

    def test_unmarked_tests_still_get_the_mock(self, mock_logger):
        """Negative control: the opt-out must not leak to its neighbours."""
        assert load_registry_module.logger is mock_logger


class TestThePreImportListIsComplete:
    """A new module-level ``find_repo_root`` caller must not re-arm the landmine.

    ``conftest.py`` pre-imports the six modules that walk for the repo root while
    LOADING, so the fallback's import-time ``log_operation`` cannot land inside a
    test window on a bare checkout. That fix is only as good as the list, and a
    list in a test file is exactly where an undercount hides — so the list is
    MEASURED off the tree by parse and compared against what ``conftest.py``
    actually imports, also by parse. Neither side is hand-copied here.

    Round 5's defect (@devpulse): a count assertion that was green on every dev
    machine and red on all four Python versions of CI, because the marker it
    depended on is gitignored. Measured in a bare world with every
    count-asserting test run in FULL isolation, TWO of the ten failed — CI had
    named one. This pin is why the eighth one cannot come back quietly.
    """

    @staticmethod
    def _module_level_repo_root_callers() -> set[str]:
        """Modules whose repo-root walk is evaluated when they load."""
        import ast

        import aipass.flow.apps as flow_apps

        root = Path(flow_apps.__file__).parent
        callers = set()
        for source in sorted(root.rglob("*.py")):
            if "__pycache__" in source.parts or ".archive" in source.parts:
                continue
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Name)
                        and sub.func.id in ("find_repo_root", "_find_repo_root")
                    ):
                        rel = source.relative_to(root).with_suffix("")
                        parts = [part for part in rel.parts if part != "__init__"]
                        callers.add(".".join(["aipass.flow.apps", *parts]))
        return callers

    @staticmethod
    def _conftest_preimports() -> set[str]:
        """Dotted names ``conftest.py`` imports at module level, by parse."""
        import ast

        conftest = Path(__file__).parent / "conftest.py"
        tree = ast.parse(conftest.read_text(encoding="utf-8"))
        return {alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names}

    def test_every_module_level_caller_is_pre_imported(self):
        missing = self._module_level_repo_root_callers() - self._conftest_preimports()

        assert missing == set(), (
            "a module walks for the repo root at IMPORT time and conftest.py does not "
            "pre-import it — on a bare checkout its fallback log lands in whichever test "
            f"window triggers the first import, and any count assertion there breaks: {sorted(missing)}"
        )

    def test_the_caller_detector_actually_finds_them(self):
        """Control: an empty detector would make the test above vacuously green."""
        callers = self._module_level_repo_root_callers()

        assert len(callers) >= 6, f"the parse found only {len(callers)} module-level callers — it is not measuring"
        assert "aipass.flow.apps.handlers.dashboard.push_central" in callers, (
            "the module CI reddened is not in the measured set"
        )

    def test_the_conftest_parse_actually_reads_the_imports(self):
        """Control for the other side of the comparison."""
        preimports = self._conftest_preimports()

        assert "aipass.flow.apps.handlers.json.json_handler" in preimports, (
            "the conftest parse is not seeing imports that are demonstrably there"
        )
