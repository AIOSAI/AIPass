# =================== AIPass ====================
# Name: test_conftest_fixtures.py
# Description: The autouse fixtures must actually reach what they claim to mock
# Version: 1.0.1
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests for tests/conftest.py's mock_logger and pre-import fixtures."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that conftest.py and save_registry parse and import

import sys
from pathlib import Path

import pytest

import aipass.flow.apps as flow_apps
import aipass.prax.apps.modules.logger as prax_logger

import aipass.flow.apps.handlers.registry.save_registry as save_registry_module

# Nothing runs out of a dropbox or .archive. Compared relative to the walk's root.
_WALK_IGNORED_DIRS = frozenset({"dropbox", ".archive", "__pycache__"})


# Patching only the source attribute misses each module's import-time binding, and an
# unasserted mock looks like a working one. These tests assert the fixture's REACH.
class TestMockLoggerReachesTheConsumersBinding:
    """The fixture must replace what flow modules actually call."""

    def test_a_consumer_module_sees_the_mock(self, mock_logger):
        """The binding a handler resolves at call time IS the mock."""
        assert save_registry_module.logger is mock_logger, (
            "the autouse mock_logger did not reach a consumer's own binding — "
            "it is patching upstream of an import that already happened"
        )

    def test_calling_the_consumers_logger_records_on_the_mock(self, mock_logger):
        """Reach is not enough: the call has to land."""
        save_registry_module.logger.warning("probe")

        mock_logger.warning.assert_called_once_with("probe")

    def test_every_imported_flow_module_with_a_logger_is_covered(self, mock_logger):
        """No module keeps a live logger while the fixture claims containment.

        Walks ``sys.modules``: a hand-written list is one more place to undercount.
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
        """The source attribute is patched as well: code binding system_logger after the fixture ran gets the mock."""
        assert prax_logger.system_logger is mock_logger


class TestTheOptOutIsRealAndNarrow:
    """``real_logger`` exists because caplog reads the real logging module."""

    @pytest.mark.real_logger
    def test_marked_tests_keep_the_real_logger(self):
        """The marker must genuinely restore the real object, not a second mock."""
        from unittest.mock import MagicMock

        assert not isinstance(save_registry_module.logger, MagicMock), (
            "the real_logger marker did not restore the real logger — a caplog assertion under it would be vacuous"
        )

    def test_unmarked_tests_still_get_the_mock(self, mock_logger):
        """Negative control: the opt-out must not leak to its neighbours."""
        assert save_registry_module.logger is mock_logger


class TestThePreImportListIsComplete:
    """A new module-level ``find_repo_root`` caller must not re-arm the landmine.

    Both sides are measured by parse, the tree and conftest.py's imports; neither is hand-copied.
    """

    @staticmethod
    def _module_level_repo_root_callers(root: Path | None = None) -> set[str]:
        """Modules whose repo-root walk is evaluated when they load."""
        import ast

        root = root or Path(flow_apps.__file__).parent
        callers = set()
        for source in sorted(root.rglob("*.py")):
            if _WALK_IGNORED_DIRS.intersection(source.relative_to(root).parts):
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

    def test_the_caller_detector_never_enters_a_dropbox(self, tmp_path):
        """Only real.py, the live control, counts: a dropbox, an .archive and a __pycache__ are skipped.

        The root sits inside a dir named dropbox, so a skip reading the whole path drops real.py too.
        """
        root = tmp_path / "dropbox" / "apps"
        for folder in (root, root / "dropbox", root / ".archive", root / "__pycache__"):
            folder.mkdir(parents=True)
            (folder / "caller.py").write_text("ROOT = find_repo_root()\n", encoding="utf-8")
        (root / "caller.py").rename(root / "real.py")

        assert self._module_level_repo_root_callers(root) == {"aipass.flow.apps.real"}

    def test_the_conftest_parse_actually_reads_the_imports(self):
        """Control for the other side of the comparison."""
        preimports = self._conftest_preimports()

        assert "aipass.flow.apps.handlers.json.json_handler" in preimports, (
            "the conftest parse is not seeing imports that are demonstrably there"
        )
