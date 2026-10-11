# =================== AIPass ====================
# Name: test_pytest_quality_pack_module_eviction.py
# Description: pytest_quality pack, module_eviction checker pins (split from test_pytest_quality_pack.py)
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-10-10
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/module_eviction_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/module_eviction_content.py

import textwrap
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.pytest_quality_standards import module_eviction_check
from aipass.seedgo.tests.support_pytest_quality_pack import _write

# =============================================================================
# MODULE EVICTION - DID THE TEST PUT THE IMPORT CACHE BACK
# =============================================================================

# NOTHING IN THIS SECTION EVICTS A MODULE, and the rule under test is why that is
# written down. A pin for a checker about sys.modules is the one place in this
# file where a real `sys.modules.pop` would read as ordinary setup. There is none:
# every project below is source TEXT written into tmp_path, and every assertion is
# about what the CHECKER reported over that text.


def _eviction_rows(root: Path) -> list:
    """The module_eviction rows over a written project, in report order."""
    return module_eviction_check.check_branch(str(root))["violations"]


def _first_line(path: Path, prefix: str) -> int:
    """The 1-based number of the first line in a written file that starts with prefix, indentation ignored."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return next(number for number, line in enumerate(lines, start=1) if line.strip().startswith(prefix))


def _module_eviction_project(root: Path) -> Path:
    """Six functions, two of which leave the import cache changed.

    The four whose cache is put back are acquitted for four DIFFERENT reasons -
    recorded first, patch.dict, a restore in a finally, a fixture teardown. Three
    of those still re-import after the eviction and leave pkg.modules.rollover
    rebound (PARENT_ATTRIBUTE_REBIND), so the fixture teardown is the one clean
    function and the score is 16.
    """
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
            sys.modules.pop(ROLLOVER, None)
            yield importlib.import_module(ROLLOVER)
            importlib.invalidate_caches()
        """,
    )
    return root


class TestModuleEvictionDetection:
    """What counts as an eviction, and the incident that is the reason for the rule.

    Each test names the one-line mutation of `module_eviction_check` it was
    confirmed RED against, so a later reader can check the pin still bites.
    """

    def test_the_incident_helper_before_its_cure_is_flagged_on_both_lines(self, tmp_path):
        """THE INCIDENT SHAPE: a helper, not a test, evicting both homes of a module bare.

        memory's `_import_rollover` popped the rollover module and deleted the
        parent package's attribute with nothing recording either, then re-imported
        it against a MagicMock cli. The mock-bound module outlived the test and a
        later in-process `memory.main()` exited 0 where the contract says 2. The
        site is a module-level helper, so a rule reading only test units would be
        blind to it, and the row has to name both lines or a reader fixes one half
        and ships the other. Mutation caught: `if dotted == "sys.modules.pop" and
        node.args:` becoming `... == "sys.modules.popitem" ...`, which leaves the
        delattr half standing and drops the cache half from the row.
        """
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
        """`del sys.modules[key]` is the same eviction as `pop`, and a class helper is still a subject.

        prax and backup evict by prefix in a loop, and some of those loops live in
        methods of a test class that are not tests themselves. The row has to carry
        the class in its nodeid or a reader cannot tell which `_fresh_module` it
        means. Mutations caught: the Delete arm's `corpus.dotted_name(target.value)
        == SYS_MODULES` becoming `== "sys.nothing"`, which reads no `del` at all;
        and `ast.ClassDef` dropped from the nodes that extend the path in
        `functions_in`, which names a module-level function that does not exist.
        """
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
        """THE HALF-CURE: sys.modules moved onto monkeypatch, the parent attribute left bare.

        memory's intake helper evicts its names with `monkeypatch.delitem` and then
        deletes `parent.pool_processor` with a bare delattr on a `parent` read
        through `sys.modules.get`. The attribute is the second home of the same
        module - `from package import name` reads it - so leaving it changed is the
        same leak. Mutation caught: "sys.modules.get" removed from MODULE_BINDERS,
        which cannot prove `parent` a module and reports nothing.
        """
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
        """A name an `import ... as` statement binds is a module, at the top of the file or inside the function.

        `import pkg.modules as modules_pkg` can only bind a module, so deleting an
        attribute from it evicts a cached submodule as surely as the
        `sys.modules.get` spelling does. Mutation caught: `alias.asname or
        alias.name.split(".")[0]` becoming `alias.name.split(".")[0]`, which binds
        `pkg` and never the alias, so neither deletion reads as one from a module.
        """
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
        """FEWER FLAGS BY DESIGN: a from-import name, a parameter, a rebound name.

        `from pkg import helper` may bind a function; a parameter may hold
        anything; a name bound from `import_module` and then rebound from a factory
        holds whichever ran last, and a reader cannot tell which. seedgo's own
        suite deletes keys from a `types.ModuleType` it built in the test, which is
        not a cached module at all. Mutation caught: `return (module_imports |
        proven) - disproven` becoming `return module_imports | proven`, which keeps
        the rebound name proven.
        """
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
        """The spellings the rule recommends must not be the spellings it flags.

        `monkeypatch.delattr(parent, "search")` ends in the same word as the
        eviction it replaces; a reader matching the tail would convict the cure
        and teach every owner to go back to the bare call. Mutation caught: `elif
        dotted == "delattr"` becoming `elif dotted.endswith("delattr")`.
        """
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
        """ONE SCOPE, ONE OWNER - a nested def's eviction belongs to the nested def.

        Walking the whole outer function would report the inner eviction twice,
        once under each name, and let a restore written in the outer body acquit
        an eviction that runs whenever the inner function is called. Mutation
        caught: `ast.FunctionDef, ast.AsyncFunctionDef` dropped from
        SEPARATE_SCOPES, which folds the inner body into the outer one and reports
        the outer test as a second row.
        """
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
    """The difference between a rule and a nuisance.

    Every acquittal below is a line a later edit could delete without any test
    noticing. These are those tests.
    """

    def test_the_cure_on_disk_records_first_then_evicts_and_is_not_flagged(self, tmp_path):
        """THE CURE memory shipped for the incident, in its own shape: record, then evict.

        `monkeypatch.setitem(sys.modules, K, None)` then `del sys.modules[K]`, and
        `monkeypatch.setattr(parent, "rollover", None, raising=False)` then
        `delattr(parent, "rollover")`. monkeypatch saw the real module before the
        eviction and puts it back at teardown. If the cure does not acquit, the
        rule has nothing to recommend. Mutations caught: the cache arm's `method in
        RECORDING_ITEM_METHODS` becoming `method in ()`, and the attribute arm's
        `method in RECORDING_ATTR_METHODS` becoming `method in ()`.
        """
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
        """EARLIER, NOT MERELY PRESENT - monkeypatch restores what it saw when it was called.

        Called after the eviction, it saw the eviction, and teardown faithfully
        puts the hole back. Order is the whole cure, so it is the whole pin.
        Mutation caught: the position comparison in `_recorded_first` becoming
        `if False:`, which lets a later record acquit an earlier eviction.
        """
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
        """The key has to be the same key - prax's logger test records one module and pops another.

        `monkeypatch.delitem(sys.modules, "...display")` first, then a bare
        `sys.modules.pop(MODULE_NAME)`: the display module comes back at teardown
        and the logger module does not. Mutation caught: the cache arm's `and
        _same(second, eviction.target)` dropped, which lets any sys.modules record
        acquit every cache eviction in its function.
        """
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
        """patch.dict snapshots the whole dict and restores it on exit, in the spellings people write.

        A `with patch.dict(sys.modules, mocks):` block, a
        `@mock.patch.dict("sys.modules", {})` decorator, and the fully qualified
        `unittest.mock.patch.dict`. prax wraps thirty-six of its evictions this
        way; convicting them would be convicting the idiom. Mutations caught: the
        `with` arm of `_patch_dict_guarded` becoming `if False:`, and its
        decorator arm becoming `if False:`.
        """
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
        """backup's conftest names it exactly: patch.dict restores the DICT, never the parent's ATTRIBUTE.

        So a `delattr(parent, ...)` inside the block leaves the package pointing at
        whatever the re-import bound, after the dict is put back. Mutation caught:
        the `cache and` guard on the patch.dict acquittal dropped, which lets
        patch.dict acquit the attribute too.
        """
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
        """A restore written out by hand is a restore, on every path the reader can see.

        The finally case is drone's registry test in shape: pop, block the name,
        try, and in the finally either put the saved module back or pop the
        blocker. The second pop sits AFTER the only restore in the file, and it is
        still correct code - a restore in a finally covers the key on every path.
        Mutations caught, one per case: `and id(node) not in finally_ids` dropped
        from `_restored_explicitly`; `_restores_attribute`'s `== "setattr"`
        becoming `== "settattr"`; and its `t.attr == eviction.attr.value` becoming
        `t.attr != eviction.attr.value`.
        """
        source = (
            "import importlib\nimport sys\n\n\ndef test_the_restore_is_written_out():\n"
            + textwrap.indent(textwrap.dedent(body).strip(), "    ")
            + "\n"
        )
        _write(tmp_path, "tests/test_restore.py", source)

        assert _eviction_rows(tmp_path) == []

    def test_a_re_import_or_a_restore_of_another_key_is_not_a_restore(self, tmp_path):
        """A RE-IMPORT IS THE POLLUTION, NOT THE CURE - and putting back a different module puts back nothing.

        `importlib.import_module(K)` after the eviction caches a NEW module object,
        which is precisely the object the incident left behind. And
        `sys.modules[OTHER] = saved` restores OTHER. Mutations caught:
        `_restores_cache`'s last line becoming `return isinstance(node, ast.Call)`,
        which reads any later call as a restore; and `and _same(t.slice,
        eviction.target)` dropped, which reads any assignment into sys.modules as
        this one.
        """
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

    def test_a_fixture_with_a_teardown_is_acquitted_and_one_without_is_not(self, tmp_path):
        """host_state's convention: any statement after the last yield is the teardown.

        A fixture that yields and stops has handed over a changed cache with
        nothing to put it back, and a fixture that `return`s - memory's `verbs`,
        which pops the rollover module and returns a namespace - never had a
        teardown at all. A plain generator is not a fixture, so nothing runs its
        tail when a test fails. Mutations caught: `teardown_after_yield`'s last
        line becoming `return True`, and its `if not _is_fixture(function):`
        becoming `if False:`.
        """
        _write(
            tmp_path,
            "tests/test_fixtures.py",
            """
            import importlib
            import sys

            import pytest


            @pytest.fixture
            def rollover_with_teardown():
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
            "tests/test_fixtures.py::rollover_without_teardown",
            "tests/test_fixtures.py::_rollover_generator",
            "tests/test_fixtures.py::verbs",
        ]

    def test_an_autouse_fixture_in_the_same_file_that_records_the_key_acquits_a_bare_helper(self, tmp_path):
        """MEASURED ON THE FLEET: memory's test_symbolic_extras, five rows, zero leaks.

        Its autouse `_mock_handler_deps` runs `monkeypatch.delitem(sys.modules,
        mod_name)` over a literal list of five symbolic modules, and five
        `_import_*` helpers then pop the same five bare. A runtime probe found
        every one of those module objects unchanged after teardown, because the
        autouse record puts back what stood there before each test. Resolved one
        hop on both sides: a loop over a literal list, a loop over a module-level
        tuple, a module-level string constant. Mutation caught: `facts.autouse_keys
        |= _cache_keys_recorded(function, facts)` becoming `facts.autouse_keys |=
        set()`.
        """
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
        """Autouse, the same literal key, resolvable at all - each boundary pinned.

        A fixture declared `autouse=False` runs only for the tests that request it, and
        a helper cannot be followed to them. A key no autouse fixture recorded comes
        back to nothing. A key assembled at runtime resolves to no name, and a key
        that resolves to nothing must acquit nothing - the empty set is a subset of
        everything. Mutations caught: `_is_autouse_fixture`'s keyword test becoming
        `if True:`; `return bool(names) and names <= facts.autouse_keys` becoming
        `return bool(names)`; and becoming `return names <= facts.autouse_keys`.
        """
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
        """Clean over every function read, and four different acquittals hold it up.

        Two of six functions leave the cache changed. The denominator is every
        function the rule reads, not the units alone: one of the two rows is a
        helper, and scoring helper rows against a count of tests lets a file of
        helpers drive a project below zero. Mutation caught: `population =
        function_count(scanned)` becoming `population = total`, which reports 33
        over three units where the honest answer is 16 over six functions (two
        cache rows, three parent-attribute rebinds).
        """
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
        """SHADOW MODE GATES NOTHING - this rule scores before it is calibrated.

        Top-level `passed` must stay True while flags exist and `advisory` must
        stay True, so a caller can tell a report from a verdict. Mutation caught:
        `"passed": True,` becoming `"passed": not flagged,` in the scored return,
        which turns an uncalibrated advisory into a board failure on every branch
        with one of these sites.
        """
        result = module_eviction_check.check_branch(str(_module_eviction_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "MODULE_EVICTION"
        assert result["checks"][0]["passed"] is False
        assert sorted(result) == ["advisory", "checks", "passed", "score", "standard", "violations"]

    def test_a_project_with_no_test_files_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        Production that evicts modules is not a test that does, and a project with
        no tests has nothing this rule can score. Losing the early return here does
        not print a wrong number, it divides by zero. Mutation caught:
        `"not_applicable": True,` becoming `"not_applicable": False,`.
        """
        _write(tmp_path, "apps/loader.py", "import sys\n\n\ndef reload():\n    sys.modules.pop('pkg', None)\n")

        result = module_eviction_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin.

        An unparseable file contributes no functions, so it cannot lower a score,
        and silence about it reads as clean. Mutation caught: the `measured`
        ternary's `if not scanned.unparseable` becoming `if True`, which makes the
        two cases indistinguishable.
        """
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    sys.modules.pop('pkg')")

        result = module_eviction_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_test_file_is_named_beside_a_scored_result(self, tmp_path):
        """AN UNREAD FILE EVICTS NOTHING, so for this rule silence biases toward clean.

        The scored path has to append the unreadable line deliberately; dropping it
        leaves a healthy number and no hint a file was never read. Mutation caught:
        `checks.extend(unreadable)` becoming `checks.extend([])`.
        """
        _module_eviction_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    sys.modules.pop('pkg')")

        result = module_eviction_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 16
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]

    def test_only_twelve_flagged_functions_are_named_and_the_rest_are_counted(self, tmp_path):
        """A CHECK MESSAGE PRINTING HUNDREDS OF LINES IS ONE NOBODY READS.

        prax alone carries thirty rows. Fourteen flagged helpers, twelve named, and
        the remainder stated as a number rather than dropped; the violations list
        itself is never truncated. Mutation caught: `MAX_REPORTED: int = 12`
        becoming `MAX_REPORTED: int = 24`.
        """
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
