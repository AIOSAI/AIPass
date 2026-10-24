# =================== AIPass ====================
# Name: test_pytest_quality_pack_module_eviction.py
# Description: pytest_quality pack, module_eviction checker pins (split from test_pytest_quality_pack.py)
# Version: 1.1.1
# Created: 2026-10-08
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/module_eviction_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/module_eviction_content.py

import textwrap
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.pytest_quality_standards import module_eviction_check
from aipass.seedgo.tests.support_pytest_quality_pack import _write


# Every project here is source text in tmp_path: a real `sys.modules.pop` in this file would read as ordinary setup.


def _eviction_rows(root: Path) -> list:
    """The module_eviction rows over a written project, in report order."""
    return module_eviction_check.check_branch(str(root))["violations"]


def _first_line(path: Path, prefix: str) -> int:
    """The 1-based number of the first line in a written file that starts with prefix, indentation ignored."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return next(number for number, line in enumerate(lines, start=1) if line.strip().startswith(prefix))


def _module_eviction_project(root: Path) -> Path:
    """Six functions, two of which leave the import cache changed."""
    _write(
        root,
        "tests/test_reimport.py",
        """
        import importlib
        import sys

        ROLLOVER = "pkg.modules.rollover"


        def _import_rollover_bare():
            sys.modules.pop(ROLLOVER, None)
            return importlib.import_module(ROLLOVER)


        def _import_rollover_recorded(monkeypatch):
            monkeypatch.setitem(sys.modules, ROLLOVER, None)
            del sys.modules[ROLLOVER]
            return importlib.import_module(ROLLOVER)


        def test_the_parent_attribute_is_left_behind():
            parent = importlib.import_module("pkg.modules")
            delattr(parent, "rollover")
            assert importlib.import_module(ROLLOVER)


        def test_the_eviction_sits_inside_patch_dict():
            with patch.dict(sys.modules):
                sys.modules.pop(ROLLOVER, None)
                assert importlib.import_module(ROLLOVER)


        def test_the_eviction_is_put_back_in_a_finally():
            saved = sys.modules.pop(ROLLOVER)
            try:
                assert importlib.import_module(ROLLOVER)
            finally:
                sys.modules[ROLLOVER] = saved


        @pytest.fixture
        def fresh_rollover():
            saved = sys.modules.pop(ROLLOVER, None)
            yield saved
            sys.modules[ROLLOVER] = saved
        """,
    )
    return root


class TestModuleEvictionDetection:
    """What counts as an eviction, and the incident that is the reason for the rule."""

    def test_the_incident_helper_before_its_cure_is_flagged_on_both_lines(self, tmp_path):
        """THE INCIDENT SHAPE: a helper, not a test, evicting both homes of a module bare."""
        path = _write(
            tmp_path,
            "tests/test_reimport.py",
            """
            import sys

            _ROLLOVER_MODULE = "aipass.memory.apps.modules.rollover"


            def _import_rollover(monkeypatch):
                mocks = _prepare_rollover_mocks(monkeypatch)
                sys.modules.pop(_ROLLOVER_MODULE, None)
                parent = sys.modules.get("aipass.memory.apps.modules")
                if parent is not None and hasattr(parent, "rollover"):
                    delattr(parent, "rollover")
                from aipass.memory.apps.modules import rollover
                return rollover, mocks


            def test_rollover_check_routes(monkeypatch):
                rollover, _ = _import_rollover(monkeypatch)
                assert rollover.handle_command("rollover", ["check"]) is True
            """,
        )

        rows = _eviction_rows(tmp_path)

        assert [row["nodeid"] for row in rows] == ["tests/test_reimport.py::_import_rollover"]
        assert rows[0]["line"] == _first_line(path, "sys.modules.pop(")
        assert rows[0]["species"] == "SYS_MODULES_EVICTION"
        assert "sys.modules.pop(_ROLLOVER_MODULE)" in rows[0]["detail"]
        assert f"line {_first_line(path, 'delattr(')} delattr(parent, 'rollover')" in rows[0]["detail"]

    def test_del_sys_modules_in_a_class_level_helper_is_flagged_under_the_class_path(self, tmp_path):
        """`del sys.modules[key]` is the same eviction as `pop`, and a class helper is still a subject."""
        _write(
            tmp_path,
            "tests/test_watcher.py",
            """
            import importlib
            import sys


            class TestWatcherLiveness:
                def _fresh_module(self):
                    for key in list(sys.modules):
                        if key.startswith("pkg.discovery"):
                            del sys.modules[key]
                    return importlib.import_module("pkg.discovery.watcher")

                def test_a_dead_watcher_is_reported(self):
                    assert self._fresh_module()._LIVENESS
            """,
        )

        rows = _eviction_rows(tmp_path)

        assert [(row["nodeid"], row["species"]) for row in rows] == [
            ("tests/test_watcher.py::TestWatcherLiveness::_fresh_module", "SYS_MODULES_EVICTION")
        ]
        assert "del sys.modules[key]" in rows[0]["detail"]

    def test_a_bare_delattr_beside_a_cured_cache_half_is_still_flagged(self, tmp_path):
        """THE HALF-CURE: sys.modules moved onto monkeypatch, the parent attribute left bare."""
        _write(
            tmp_path,
            "tests/test_intake.py",
            """
            import sys


            def _import_pool_processor(monkeypatch):
                for name in ("pkg.handlers.json", "pkg.handlers.intake.pool_processor"):
                    monkeypatch.delitem(sys.modules, name, raising=False)
                parent = sys.modules.get("pkg.handlers.intake")
                if parent is not None and hasattr(parent, "pool_processor"):
                    delattr(parent, "pool_processor")
                from pkg.handlers.intake import pool_processor
                return pool_processor


            def test_find_source_file(monkeypatch):
                assert _import_pool_processor(monkeypatch)
            """,
        )

        rows = _eviction_rows(tmp_path)

        assert [(row["nodeid"], row["species"]) for row in rows] == [
            ("tests/test_intake.py::_import_pool_processor", "PACKAGE_ATTRIBUTE_EVICTION")
        ]

    def test_a_delattr_on_a_module_bound_by_an_import_statement_is_flagged(self, tmp_path):
        """A name an `import ... as` statement binds is a module, at the top of the file or inside the function."""
        _write(
            tmp_path,
            "tests/test_modules.py",
            """
            import pkg.modules as modules_pkg


            def _forget_rollover():
                delattr(modules_pkg, "rollover")


            def test_forget_search():
                import pkg.search_parent as search_parent
                delattr(search_parent, "search")
                assert True
            """,
        )

        rows = _eviction_rows(tmp_path)

        assert [row["nodeid"] for row in rows] == [
            "tests/test_modules.py::_forget_rollover",
            "tests/test_modules.py::test_forget_search",
        ]

    def test_a_delattr_on_anything_not_provably_a_module_is_not_read(self, tmp_path):
        """FEWER FLAGS BY DESIGN: a from-import name, a parameter, a rebound name."""
        _write(
            tmp_path,
            "tests/test_adapters.py",
            """
            import importlib

            from pkg import helper


            def _strip_helper():
                delattr(helper, "cache")


            def _strip(module, key):
                delattr(module, key)


            def test_a_rebound_name_is_not_a_module():
                parent = importlib.import_module("pkg.modules")
                parent = make_fake_module()
                delattr(parent, "rollover")
                assert parent
            """,
        )

        assert _eviction_rows(tmp_path) == []

    def test_monkeypatch_delitem_and_delattr_are_the_cure_and_never_an_eviction(self, tmp_path):
        """The spellings the rule recommends must not be the spellings it flags."""
        _write(
            tmp_path,
            "tests/test_cured.py",
            """
            import importlib
            import sys


            def _import_search(monkeypatch):
                monkeypatch.delitem(sys.modules, "pkg.modules.search", raising=False)
                parent = importlib.import_module("pkg.modules")
                monkeypatch.delattr(parent, "search", raising=False)
                return importlib.import_module("pkg.modules.search")


            def test_search_routes(monkeypatch):
                assert _import_search(monkeypatch)
            """,
        )

        assert _eviction_rows(tmp_path) == []

    def test_a_nested_helper_is_its_own_subject_and_is_reported_once(self, tmp_path):
        """ONE SCOPE, ONE OWNER - a nested def's eviction belongs to the nested def."""
        _write(
            tmp_path,
            "tests/test_nested.py",
            """
            import sys


            def test_the_display_module_is_evicted():
                def _evict():
                    sys.modules.pop("pkg.display", None)

                _evict()
                assert "pkg.display" not in sys.modules
            """,
        )

        rows = _eviction_rows(tmp_path)

        assert [row["nodeid"] for row in rows] == ["tests/test_nested.py::test_the_display_module_is_evicted::_evict"]


class TestModuleEvictionAcquittals:
    """The difference between a rule and a nuisance."""

    def test_the_cure_on_disk_records_first_then_evicts_and_is_not_flagged(self, tmp_path):
        """THE CURE memory shipped for the incident, in its own shape: record, then evict."""
        _write(
            tmp_path,
            "tests/test_reimport.py",
            """
            import importlib
            import sys

            _ROLLOVER_MODULE = "aipass.memory.apps.modules.rollover"


            def _import_rollover(monkeypatch):
                mocks = _prepare_rollover_mocks(monkeypatch)
                monkeypatch.setitem(sys.modules, _ROLLOVER_MODULE, None)
                del sys.modules[_ROLLOVER_MODULE]
                parent = importlib.import_module("aipass.memory.apps.modules")
                monkeypatch.setattr(parent, "rollover", None, raising=False)
                delattr(parent, "rollover")
                from aipass.memory.apps.modules import rollover
                return rollover, mocks


            def test_rollover_check_routes(monkeypatch):
                rollover, _ = _import_rollover(monkeypatch)
                assert rollover.handle_command("rollover", ["check"]) is True
            """,
        )

        result = module_eviction_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_record_made_after_the_eviction_restores_the_hole_and_does_not_acquit(self, tmp_path):
        """EARLIER, NOT MERELY PRESENT - monkeypatch restores what it saw when it was called."""
        _write(
            tmp_path,
            "tests/test_reimport.py",
            """
            import sys


            def test_the_record_comes_too_late(monkeypatch):
                del sys.modules["pkg.modules.rollover"]
                monkeypatch.setitem(sys.modules, "pkg.modules.rollover", None)
                assert True
            """,
        )

        rows = _eviction_rows(tmp_path)

        assert [row["nodeid"] for row in rows] == ["tests/test_reimport.py::test_the_record_comes_too_late"]

    def test_a_record_of_a_different_key_does_not_acquit(self, tmp_path):
        """The key has to be the same key - prax's logger test records one module and pops another."""
        path = _write(
            tmp_path,
            "tests/test_logger_module.py",
            """
            import sys

            MODULE_NAME = "pkg.modules.logger"


            def test_fallback_to_rich_when_cli_unavailable(monkeypatch):
                monkeypatch.delitem(sys.modules, "pkg.cli.modules.display", raising=False)
                sys.modules.pop(MODULE_NAME, None)
                assert True
            """,
        )

        rows = _eviction_rows(tmp_path)

        assert [row["line"] for row in rows] == [_first_line(path, "sys.modules.pop(")]

    def test_patch_dict_around_or_above_a_cache_eviction_acquits_it(self, tmp_path):
        """patch.dict snapshots the whole dict and restores it on exit, in the spellings people write."""
        _write(
            tmp_path,
            "tests/test_drive.py",
            """
            import importlib
            import sys
            import unittest.mock
            from unittest import mock
            from unittest.mock import patch


            def _fresh_import(module_path, mocks):
                with patch.dict(sys.modules, mocks):
                    if module_path in sys.modules:
                        del sys.modules[module_path]
                    return importlib.import_module(module_path)


            @mock.patch.dict("sys.modules", {})
            def test_the_drive_client_is_reimported():
                sys.modules.pop("pkg.drive.client", None)
                assert importlib.import_module("pkg.drive.client")


            def test_the_share_module_is_reimported():
                with unittest.mock.patch.dict(sys.modules, clear=False):
                    sys.modules.pop("pkg.drive.share", None)
                    assert importlib.import_module("pkg.drive.share")
            """,
        )

        rows = _eviction_rows(tmp_path)

        # patch.dict restores the dict, never pkg.drive's attribute: the re-import rows are PARENT_ATTRIBUTE_REBIND.
        assert [row["detail"] for row in rows if "evicted with nothing recording" in row["detail"]] == []
        assert [(row["nodeid"], row["species"]) for row in rows] == [
            ("tests/test_drive.py::test_the_drive_client_is_reimported", "PARENT_ATTRIBUTE_REBIND"),
            ("tests/test_drive.py::test_the_share_module_is_reimported", "PARENT_ATTRIBUTE_REBIND"),
        ]

    def test_patch_dict_never_restores_a_package_attribute_so_a_delattr_inside_it_is_still_read(self, tmp_path):
        """backup's conftest names it exactly: patch.dict restores the DICT, never the parent's ATTRIBUTE."""
        _write(
            tmp_path,
            "tests/test_drive.py",
            """
            import importlib
            import sys
            from unittest.mock import patch


            def test_the_twin_is_left_on_the_parent():
                with patch.dict(sys.modules, {"pkg.drive.client": object()}):
                    parent = importlib.import_module("pkg.drive")
                    delattr(parent, "share")
                    assert importlib.import_module("pkg.drive.share")
            """,
        )

        rows = _eviction_rows(tmp_path)

        assert [(row["nodeid"], row["species"]) for row in rows] == [
            ("tests/test_drive.py::test_the_twin_is_left_on_the_parent", "PACKAGE_ATTRIBUTE_EVICTION")
        ]

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(
                """
                saved = sys.modules.pop("pkg.cli.display", None)
                sys.modules["pkg.cli.display"] = None
                try:
                    assert reload_the_registry()
                finally:
                    if saved is not None:
                        sys.modules["pkg.cli.display"] = saved
                    else:
                        sys.modules.pop("pkg.cli.display", None)
                """,
                id="a-restore-in-the-finally-covers-the-pop-beside-it",
            ),
            pytest.param(
                """
                parent = importlib.import_module("pkg.modules")
                saved = parent.rollover
                delattr(parent, "rollover")
                setattr(parent, "rollover", saved)
                """,
                id="setattr-after-delattr",
            ),
            pytest.param(
                """
                parent = sys.modules["pkg.modules"]
                saved = parent.rollover
                delattr(parent, "rollover")
                parent.rollover = saved
                """,
                id="attribute-assignment-after-delattr",
            ),
        ],
    )
    def test_an_explicit_restore_after_the_eviction_or_in_a_finally_acquits_it(self, tmp_path, body):
        """A restore written out by hand is a restore, on every path the reader can see."""
        source = (
            "import importlib\nimport sys\n\n\ndef test_the_restore_is_written_out():\n"
            + textwrap.indent(textwrap.dedent(body).strip(), "    ")
            + "\n"
        )
        _write(tmp_path, "tests/test_restore.py", source)

        assert _eviction_rows(tmp_path) == []

    def test_a_re_import_or_a_restore_of_another_key_is_not_a_restore(self, tmp_path):
        """A RE-IMPORT IS THE POLLUTION, NOT THE CURE - and putting back a different module puts back nothing."""
        _write(
            tmp_path,
            "tests/test_dashboard.py",
            """
            import importlib
            import sys


            def _load(module_path):
                sys.modules.pop(module_path, None)
                module = importlib.import_module(module_path)
                return importlib.reload(module)


            def test_the_status_handler_is_reloaded():
                saved = sys.modules.get("pkg.dashboard")
                sys.modules.pop("pkg.dashboard.status", None)
                sys.modules["pkg.dashboard"] = saved
                assert True
            """,
        )

        rows = _eviction_rows(tmp_path)

        assert [row["nodeid"] for row in rows] == [
            "tests/test_dashboard.py::_load",
            "tests/test_dashboard.py::test_the_status_handler_is_reloaded",
        ]

    def test_only_a_teardown_that_puts_the_module_back_acquits_a_fixture(self, tmp_path):
        """A statement after the yield is a teardown, but only a restore there undoes the eviction."""
        _write(
            tmp_path,
            "tests/test_fixtures.py",
            """
            import importlib
            import sys

            import pytest


            @pytest.fixture
            def rollover_with_teardown():
                saved = sys.modules.pop("pkg.modules.rollover", None)
                yield saved
                sys.modules["pkg.modules.rollover"] = saved


            @pytest.fixture
            def rollover_with_idle_teardown():
                sys.modules.pop("pkg.modules.rollover", None)
                yield importlib.import_module("pkg.modules.rollover")
                importlib.invalidate_caches()


            @pytest.fixture
            def rollover_without_teardown():
                sys.modules.pop("pkg.modules.rollover", None)
                yield importlib.import_module("pkg.modules.rollover")


            def _rollover_generator():
                sys.modules.pop("pkg.modules.rollover", None)
                yield importlib.import_module("pkg.modules.rollover")
                importlib.invalidate_caches()


            @pytest.fixture
            def verbs(tmp_path):
                sys.modules.pop("pkg.modules.rollover", None)
                return importlib.import_module("pkg.modules.rollover")


            def test_the_verbs_route(verbs):
                assert verbs
            """,
        )

        rows = _eviction_rows(tmp_path)

        assert [row["nodeid"] for row in rows] == [
            "tests/test_fixtures.py::rollover_with_idle_teardown",
            "tests/test_fixtures.py::rollover_without_teardown",
            "tests/test_fixtures.py::_rollover_generator",
            "tests/test_fixtures.py::verbs",
        ]

    def test_a_mock_put_into_the_evicted_slot_is_no_restore(self, tmp_path):
        _write(
            tmp_path,
            "tests/test_mock.py",
            """
            import sys
            from unittest.mock import MagicMock


            def test_swaps_in_a_mock():
                sys.modules.pop("pkg.modules.rollover")
                try:
                    assert True
                finally:
                    sys.modules["pkg.modules.rollover"] = MagicMock()
            """,
        )
        assert [row["nodeid"] for row in _eviction_rows(tmp_path)] == ["tests/test_mock.py::test_swaps_in_a_mock"]

    def test_an_autouse_fixture_in_the_same_file_that_records_the_key_acquits_a_bare_helper(self, tmp_path):
        """MEASURED ON THE FLEET: memory's test_symbolic_extras, five rows, zero leaks."""
        _write(
            tmp_path,
            "tests/test_symbolic_extras.py",
            """
            import sys

            import pytest

            RETRIEVER = "pkg.symbolic.retriever"
            CLIENTS = ("pkg.symbolic.chroma_client",)


            @pytest.fixture(autouse=True)
            def _mock_handler_deps(monkeypatch):
                for mod_name in ["pkg.symbolic.hook", "pkg.symbolic.storage"]:
                    monkeypatch.delitem(sys.modules, mod_name, raising=False)
                for client in CLIENTS:
                    monkeypatch.delitem(sys.modules, client, raising=False)
                monkeypatch.setitem(sys.modules, RETRIEVER, None)


            def _import_hook():
                sys.modules.pop("pkg.symbolic.hook", None)
                from pkg.symbolic.hook import process_hook
                return process_hook


            def _import_chroma_client():
                sys.modules.pop("pkg.symbolic.chroma_client", None)
                from pkg.symbolic.chroma_client import get_chroma_client
                return get_chroma_client


            def _import_retriever():
                del sys.modules[RETRIEVER]
                from pkg.symbolic.retriever import retrieve_fragments
                return retrieve_fragments


            def test_the_hook_processes():
                assert _import_hook()
            """,
        )

        rows = _eviction_rows(tmp_path)

        # The autouse record puts the cache back; the from-import still rebinds pkg.symbolic's attribute.
        assert [row["detail"] for row in rows if "evicted with nothing recording" in row["detail"]] == []
        assert {row["species"] for row in rows} == {"PARENT_ATTRIBUTE_REBIND"}

    def test_what_an_autouse_record_does_not_cover_is_still_flagged(self, tmp_path):
        """Autouse, the same literal key, resolvable at all - each boundary pinned."""
        _write(
            tmp_path,
            "tests/test_symbolic_extras.py",
            """
            import sys

            import pytest


            @pytest.fixture(autouse=False)
            def _record_storage(monkeypatch):
                monkeypatch.delitem(sys.modules, "pkg.symbolic.storage", raising=False)


            @pytest.fixture(autouse=True)
            def _record_hook(monkeypatch):
                monkeypatch.delitem(sys.modules, "pkg.symbolic.hook", raising=False)


            def _import_storage():
                sys.modules.pop("pkg.symbolic.storage", None)


            def _import_deduplicator():
                sys.modules.pop("pkg.symbolic.deduplicator", None)


            def _import_leaf(leaf):
                sys.modules.pop(f"pkg.symbolic.{leaf}", None)


            def test_the_hook_processes():
                assert True
            """,
        )

        rows = _eviction_rows(tmp_path)

        assert [row["nodeid"] for row in rows] == [
            "tests/test_symbolic_extras.py::_import_storage",
            "tests/test_symbolic_extras.py::_import_deduplicator",
            "tests/test_symbolic_extras.py::_import_leaf",
        ]


class TestModuleEvictionBranchCheck:
    """The scoring-API contract, and the paths where silence reads as clean."""

    def test_the_score_is_the_share_of_functions_that_leave_the_cache_as_they_found_it(self, tmp_path):
        """Clean over every function read, and four different acquittals hold it up."""
        result = module_eviction_check.check_branch(str(_module_eviction_project(tmp_path)))

        assert result["score"] == 16
        assert [(row["nodeid"], row["species"]) for row in result["violations"]] == [
            ("tests/test_reimport.py::_import_rollover_bare", "SYS_MODULES_EVICTION"),
            ("tests/test_reimport.py::_import_rollover_recorded", "PARENT_ATTRIBUTE_REBIND"),
            ("tests/test_reimport.py::test_the_parent_attribute_is_left_behind", "PACKAGE_ATTRIBUTE_EVICTION"),
            ("tests/test_reimport.py::test_the_eviction_sits_inside_patch_dict", "PARENT_ATTRIBUTE_REBIND"),
            ("tests/test_reimport.py::test_the_eviction_is_put_back_in_a_finally", "PARENT_ATTRIBUTE_REBIND"),
        ]
        assert (
            "5/6 test functions, fixtures and helpers evict a cached module with no visible restore"
            in result["checks"][0]["message"]
        )

    def test_the_result_passes_and_stays_advisory_even_when_functions_are_flagged(self, tmp_path):
        """SHADOW MODE GATES NOTHING - this rule scores before it is calibrated."""
        result = module_eviction_check.check_branch(str(_module_eviction_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "MODULE_EVICTION"
        assert result["checks"][0]["passed"] is False
        assert sorted(result) == ["advisory", "checks", "passed", "score", "standard", "violations"]

    def test_a_project_with_no_test_files_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND."""
        _write(tmp_path, "apps/loader.py", "import sys\n\n\ndef reload():\n    sys.modules.pop('pkg', None)\n")

        result = module_eviction_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin."""
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    sys.modules.pop('pkg')")

        result = module_eviction_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_test_file_is_named_beside_a_scored_result(self, tmp_path):
        """AN UNREAD FILE EVICTS NOTHING, so for this rule silence biases toward clean."""
        _module_eviction_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    sys.modules.pop('pkg')")

        result = module_eviction_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 16
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]

    def test_only_twelve_flagged_functions_are_named_and_the_rest_are_counted(self, tmp_path):
        """A CHECK MESSAGE PRINTING HUNDREDS OF LINES IS ONE NOBODY READS."""
        helpers = "\n\n\n".join(
            f"def _load_{index:02d}():\n    sys.modules.pop('pkg.m{index:02d}', None)" for index in range(14)
        )
        _write(
            tmp_path, "tests/test_many_loaders.py", f"import sys\n\n\n{helpers}\n\n\ndef test_a():\n    assert True\n"
        )

        result = module_eviction_check.check_branch(str(tmp_path))
        message = result["checks"][0]["message"]

        assert len(result["violations"]) == 14
        assert message.count("::_load_") == 12
        assert message.endswith("(+2 more)")


class TestModuleEvictionParentRebind:
    """A re-import after a monkeypatch eviction rebinds the parent package's attribute, which monkeypatch never saw."""

    def test_memory_reimport_before_its_cure_is_flagged_at_the_re_import(self, tmp_path):
        """Minimised from memory tests/test_trinity_standard.py before 66960830 (PR #774, 3.10/3.11 rows)."""
        path = _write(
            tmp_path,
            "tests/test_trinity_standard.py",
            """
            import importlib
            import sys


            def test_no_status_writer_after_a_clean_reimport(monkeypatch):
                for name in [n for n in sys.modules if n.startswith("aipass.memory.apps.handlers.json")]:
                    monkeypatch.delitem(sys.modules, name, raising=False)
                memory_files = importlib.import_module("aipass.memory.apps.handlers.json.memory_files")
                importlib.reload(memory_files)
                assert not hasattr(memory_files, "update_metadata")
            """,
        )

        rows = _eviction_rows(tmp_path)

        assert [(row["species"], row["line"]) for row in rows] == [
            ("PARENT_ATTRIBUTE_REBIND", _first_line(path, "memory_files = importlib.import_module("))
        ]
        assert "aipass.memory.apps.handlers.json" in rows[0]["detail"]
        assert "'json'" in rows[0]["detail"]

    def test_memory_cure_pins_the_parent_attribute_first_and_is_acquitted(self, tmp_path):
        """The cure on disk: monkeypatch.setattr(handlers_pkg, "json", ...) before the eviction."""
        _write(
            tmp_path,
            "tests/test_trinity_standard.py",
            """
            import importlib
            import sys


            def test_no_status_writer_after_a_clean_reimport(monkeypatch):
                handlers_pkg = sys.modules["aipass.memory.apps.handlers"]
                monkeypatch.setattr(handlers_pkg, "json", handlers_pkg.json)
                for name in [n for n in sys.modules if n.startswith("aipass.memory.apps.handlers.json")]:
                    monkeypatch.delitem(sys.modules, name, raising=False)
                memory_files = importlib.import_module("aipass.memory.apps.handlers.json.memory_files")
                importlib.reload(memory_files)
                assert not hasattr(memory_files, "update_metadata")
            """,
        )

        assert _eviction_rows(tmp_path) == []

    def test_a_pin_made_after_the_eviction_or_an_unrelated_re_import_reads_as_written(self, tmp_path):
        """A pin after the re-import recorded the new module; a re-import of a module never evicted rebinds nothing."""
        _write(
            tmp_path,
            "tests/test_reimport.py",
            """
            import importlib
            import sys


            def test_the_pin_comes_too_late(monkeypatch):
                monkeypatch.delitem(sys.modules, "pkg.modules.rollover", raising=False)
                from pkg.modules import rollover
                parent = importlib.import_module("pkg.modules")
                monkeypatch.setattr(parent, "rollover", None, raising=False)
                assert rollover


            def test_another_module_is_imported(monkeypatch):
                monkeypatch.delitem(sys.modules, "pkg.modules.rollover", raising=False)
                assert importlib.import_module("pkg.other")


            def test_the_denier_actually_denies(monkeypatch):
                for name in [m for m in sys.modules if m.startswith("pkg.memory")]:
                    monkeypatch.delitem(sys.modules, name, raising=False)
                with pytest.raises(FileNotFoundError):
                    importlib.import_module("pkg.memory.apps.modules.door_tab_renderer")
            """,
        )

        rows = _eviction_rows(tmp_path)

        assert [row["nodeid"] for row in rows] == ["tests/test_reimport.py::test_the_pin_comes_too_late"]
