# =================== AIPass ====================
# Name: test_pytest_quality_pack_mock_drift.py
# Description: pytest_quality pack, mock_drift checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/mock_drift_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/mock_drift_content.py

from pathlib import Path

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus, mock_drift_check
from aipass.seedgo.tests.support_pytest_quality_pack import _write

# =============================================================================
# MOCK DRIFT - DOES A PATCH REPLACE A FUNCTION OR A WHOLE MODULE
# =============================================================================
#
# Every test below was confirmed RED against a named one-line mutation of
# mock_drift_check.py before it shipped, per the owner's standing rule. The
# mutation each one catches is named in its docstring, so a future reader can
# re-run the experiment instead of trusting this comment.


def _drift_rows(root: Path) -> list:
    """Every module-patch finding in a written-out project."""
    return mock_drift_check.find_module_patches(
        corpus.build(root, test_dirs=mock_drift_check.TEST_DIRS, with_production=True)
    )


def _drift_targets(root: Path) -> list:
    """Just the patch targets that were flagged, for a compact assertion."""
    return [row["target"] for row in _drift_rows(root)]


def _mock_drift_project(root: Path) -> Path:
    """A four-unit project where exactly one unit patches a whole module.

    The three clean units are clean for THREE DIFFERENT reasons - an object the
    parent imports from outside the project, an `autospec=True` acquittal, and a
    target one segment deeper than the module. Built that way on purpose: a
    project whose safe units were all safe for the same reason would still score
    75 with two of the three exemptions deleted.
    """
    _write(root, "src/mypkg/json_handler.py", "def read_json(path):\n    return {}")
    _write(
        root,
        "src/mypkg/worker.py",
        """
        from src.mypkg import json_handler
        from thirdparty.ui import console


        def run(path):
            console.print(path)
            return json_handler.read_json(path)
        """,
    )
    _write(
        root,
        "tests/test_worker.py",
        """
        from unittest.mock import patch

        _MOD = "src.mypkg.worker"


        @patch(f"{_MOD}.json_handler")
        def test_patches_a_module(mock_handler):
            assert run("x") is not None


        @patch(f"{_MOD}.console")
        def test_patches_an_object(mock_console):
            assert run("x") is not None


        @patch(f"{_MOD}.json_handler", autospec=True)
        def test_patches_with_autospec(mock_handler):
            assert run("x") is not None


        @patch(f"{_MOD}.json_handler.read_json")
        def test_patches_an_attribute(mock_read):
            assert run("x") is not None
        """,
    )
    return root


class TestMockDriftTargetResolution:
    """Which dotted targets resolve to a module - the whole rule rests here."""

    def test_a_target_that_names_a_module_file_is_flagged(self, tmp_path):
        """The module-file arm: `patch('a.b.c')` where `c.py` exists in the tree.

        MUTATION CAUGHT: deleting the `if target in modules:` arm of
        `_drift_reason` - a patch naming a file outright then reads as an
        ordinary attribute patch, which is the plainest form of the defect.
        """
        _write(tmp_path, "src/mypkg/json_handler.py", "def read_json(path):\n    return {}")
        _write(
            tmp_path,
            "tests/test_direct.py",
            """
            from unittest.mock import patch


            @patch("src.mypkg.json_handler")
            def test_reads_the_row(mock_handler):
                assert mock_handler is not None
            """,
        )

        rows = _drift_rows(tmp_path)

        assert [row["target"] for row in rows] == ["src.mypkg.json_handler"]
        assert rows[0]["nodeid"] == "tests/test_direct.py::test_reads_the_row"
        assert rows[0]["species"] == "MOCK-DRIFT"
        assert "resolves to a module file" in rows[0]["reason"]

    def test_an_fstring_target_resolves_through_a_module_level_constant(self, tmp_path):
        """`patch(f"{_MOD}.thing")` is the dominant real spelling and must resolve.

        MUTATION CAUGHT: deleting the `ast.JoinedStr` arm of `_patch_target` (or
        making it return None). The first version of this rule required a plain
        `ast.Constant` and scored a branch holding 25 known module patches as
        completely clean - a detector that only reads the spelling nobody uses
        measures nothing.
        """
        assert _drift_targets(_mock_drift_project(tmp_path)) == ["src.mypkg.worker.json_handler"]

    def test_a_computed_fstring_target_is_never_flagged(self, tmp_path):
        """NEGATIVE CONTROL: a target the reader cannot resolve is left alone.

        MUTATION CAUGHT: making the `FormattedValue` arm of `_patch_target` fall
        back to "" instead of returning None when the interpolated name is not a
        module-level string constant. The rule would then invent a target from
        half an f-string and flag whatever it happened to spell.
        """
        _write(tmp_path, "src/mypkg/json_handler.py", "def read_json(path):\n    return {}")
        _write(
            tmp_path,
            "tests/test_computed.py",
            """
            from unittest.mock import patch


            def test_reads_the_row():
                where = "src.mypkg"
                with patch(f"{where}.json_handler"):
                    assert True
            """,
        )

        assert _drift_targets(tmp_path) == []

    def test_a_name_the_parent_file_binds_to_a_module_by_import_is_flagged(self, tmp_path):
        """The import-binding arm: `worker.json_handler` IS a module inside worker.

        MUTATION CAUGHT: deleting the second arm of `_drift_reason` (the
        `attribute in bound.get(owner, set())` branch). That arm is what finds
        the shape that left 46 of 46 tests green - the target names no file
        itself, it names a module through the file that imported it.
        """
        rows = _drift_rows(_mock_drift_project(tmp_path))

        assert [row["target"] for row in rows] == ["src.mypkg.worker.json_handler"]
        assert "binds 'json_handler' to a MODULE by import" in rows[0]["reason"]

    def test_an_object_imported_from_outside_the_project_is_not_flagged(self, tmp_path):
        """NEGATIVE CONTROL: `worker.console` is an object, not a module.

        To a last-segment match this is identical to `worker.json_handler`, and
        flagging it would make the rule a name-collision guess on ordinary
        correct code. MUTATION CAUGHT: dropping the `if alias.name in modules`
        condition from the `ast.ImportFrom` arm of `_imported_module_names` -
        every imported name then reads as a module and the console patch, the
        autospec patch and the attribute patch all flag together.
        """
        rows = _drift_rows(_mock_drift_project(tmp_path))

        assert "src.mypkg.worker.console" not in [row["target"] for row in rows]
        assert len(rows) == 1

    def test_a_plain_import_with_an_alias_binds_the_alias_to_the_module(self, tmp_path):
        """`import mypkg.json_handler as json_handler` binds a module to a name.

        MUTATION CAUGHT: deleting the `ast.Import` arm of
        `_imported_module_names` (or its `alias.asname or ...` half). The
        `from x import y` spelling is not the only way a file ends up holding a
        module under a short name, and a rule blind to the other one reports a
        clean file that is not.
        """
        _write(tmp_path, "src/mypkg/json_handler.py", "def read_json(path):\n    return {}")
        _write(
            tmp_path,
            "src/mypkg/legacy.py",
            "import mypkg.json_handler as json_handler\n\n\ndef run(path):\n    return json_handler.read_json(path)",
        )
        _write(
            tmp_path,
            "tests/test_legacy.py",
            """
            from unittest.mock import patch


            @patch("src.mypkg.legacy.json_handler")
            def test_reads_the_row(mock_handler):
                assert mock_handler is not None
            """,
        )

        assert _drift_targets(tmp_path) == ["src.mypkg.legacy.json_handler"]

    def test_every_suffix_of_a_module_path_resolves_not_just_the_full_one(self, tmp_path):
        """A test patches `pkg.thing`, never the path relative to the project root.

        MUTATION CAUGHT: collapsing the `for start in range(len(parts))` loop in
        `_module_paths` to a single `found.add(".".join(parts))`. Only projects
        whose tests spell the target from the checkout root would then resolve,
        which is essentially none of them - the rule would report clean fleetwide.
        """
        _write(tmp_path, "src/deep/pkg/thing.py", "VALUE = 1")
        _write(
            tmp_path,
            "tests/test_suffix.py",
            """
            from unittest.mock import patch


            @patch("pkg.thing")
            def test_reads_the_value(mock_thing):
                assert mock_thing is not None
            """,
        )

        assert _drift_targets(tmp_path) == ["pkg.thing"]

    def test_two_files_sharing_a_stem_have_their_bindings_unioned(self, tmp_path):
        """A second file with the same stem must not erase the first one's imports.

        MUTATION CAUGHT: replacing `bound.setdefault(stem, set()).update(...)` in
        `_module_bound_names` with `bound[stem] = ...`. Two `worker.py` files in
        different packages is an ordinary layout, and the loser's bindings vanish
        silently - a hole that always moves the score toward clean, which is the
        direction nobody goes looking.
        """
        _write(tmp_path, "src/mypkg/json_handler.py", "def read_json(path):\n    return {}")
        _write(tmp_path, "src/a/worker.py", "import mypkg.json_handler as json_handler\n\nVALUE = json_handler")
        _write(tmp_path, "src/b/worker.py", "VALUE = 2")
        _write(
            tmp_path,
            "tests/test_stems.py",
            """
            from unittest.mock import patch


            @patch("src.a.worker.json_handler")
            def test_reads_the_row(mock_handler):
                assert mock_handler is not None
            """,
        )

        assert _drift_targets(tmp_path) == ["src.a.worker.json_handler"]

    def test_a_target_resolving_to_nothing_in_the_tree_is_left_alone(self, tmp_path):
        """NEGATIVE CONTROL: the rule reports what it resolves, it does not guess.

        MUTATION CAUGHT: dropping the `if not reason: continue` guard in
        `unit_flags`. Every patch in every project then becomes a finding,
        including the library patches that make up most of a real suite.
        """
        _write(tmp_path, "src/mypkg/json_handler.py", "def read_json(path):\n    return {}")
        _write(
            tmp_path,
            "tests/test_stranger.py",
            """
            from unittest.mock import patch


            @patch("requests.sessions.Session.get")
            def test_calls_out(mock_get):
                assert mock_get is not None
            """,
        )

        assert _drift_targets(tmp_path) == []


class TestMockDriftWhichCallsAreRead:
    """Where a patch can be written, and which spellings are watched."""

    def test_a_context_manager_patch_is_read_as_well_as_a_decorator(self, tmp_path):
        """`with patch(...)` is the other half of every real suite.

        MUTATION CAUGHT: narrowing `_patch_calls` to `unit.node.decorator_list`
        instead of `ast.walk(unit.node)`. Half of the corpus - every patch
        written as a context manager - would stop being read at all, and the
        loss would look like a clean project.
        """
        _write(tmp_path, "src/mypkg/json_handler.py", "def read_json(path):\n    return {}")
        _write(
            tmp_path,
            "tests/test_ctx.py",
            """
            from unittest.mock import patch


            def test_reads_the_row():
                with patch("src.mypkg.json_handler"):
                    assert True
            """,
        )

        assert _drift_targets(tmp_path) == ["src.mypkg.json_handler"]

    def test_the_mock_dot_patch_spelling_is_watched_too(self, tmp_path):
        """`from unittest import mock` then `@mock.patch(...)` is the same defect.

        MUTATION CAUGHT: shrinking PATCH_NAMES to `{"patch"}`. A project that
        imports the module rather than the function scores 100 while carrying
        every one of these findings.
        """
        _write(tmp_path, "src/mypkg/json_handler.py", "def read_json(path):\n    return {}")
        _write(
            tmp_path,
            "tests/test_spelling.py",
            """
            from unittest import mock


            @mock.patch("src.mypkg.json_handler")
            def test_reads_the_row(mock_handler):
                assert mock_handler is not None
            """,
        )

        assert _drift_targets(tmp_path) == ["src.mypkg.json_handler"]

    def test_each_acquitting_keyword_clears_a_module_patch(self, tmp_path):
        """NEGATIVE CONTROL: a specced mock refuses unknown attributes.

        That refusal is the exact property whose absence this rule is about, so
        every one of the four keywords has to clear the patch. MUTATION CAUGHT:
        removing any single member of ACQUITTING_KEYWORDS - `new_callable` was
        the one measured, and its removal turns a correct, deliberately specced
        patch into a finding, which is how a standard gets switched off.
        """
        _write(tmp_path, "src/mypkg/json_handler.py", "def read_json(path):\n    return {}")
        _write(
            tmp_path,
            "tests/test_specced.py",
            """
            from unittest.mock import patch


            @patch("src.mypkg.json_handler", spec=True)
            def test_spec(mock_handler):
                assert mock_handler is not None


            @patch("src.mypkg.json_handler", spec_set=True)
            def test_spec_set(mock_handler):
                assert mock_handler is not None


            @patch("src.mypkg.json_handler", autospec=True)
            def test_autospec(mock_handler):
                assert mock_handler is not None


            @patch("src.mypkg.json_handler", new_callable=dict)
            def test_new_callable(mock_handler):
                assert mock_handler is not None
            """,
        )

        assert _drift_targets(tmp_path) == []


class TestMockDriftBranchCheck:
    """The scored result: the number, its denominator, and what it admits to."""

    def test_the_score_is_flagged_units_over_total_units(self, tmp_path):
        """One flagged unit in four is 75, and the result carries the contract.

        MUTATION CAUGHT: inverting the score to `len(units) / total` - the
        project scores 25 instead of 75 and every board reads backwards.
        """
        result = mock_drift_check.check_branch(str(_mock_drift_project(tmp_path)))

        assert result["score"] == 75
        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "MOCK_DRIFT"
        assert result["checks"][0]["passed"] is False
        assert "tests/test_worker.py::test_patches_a_module" in result["checks"][0]["message"]

    def test_two_module_patches_in_one_unit_cost_that_unit_once(self, tmp_path):
        """A unit with two module patches is ONE place a reader has to look.

        MUTATION CAUGHT: scoring on `len(flagged)` instead of
        `len(flagged_nodeids(flagged))`. On this two-unit project the score drops
        from 50 to 0, and on any project where one test carries more findings
        than the project has units the score goes NEGATIVE - a number nobody
        believes twice.
        """
        _write(tmp_path, "src/mypkg/json_handler.py", "def read_json(path):\n    return {}")
        _write(tmp_path, "src/mypkg/yaml_handler.py", "def read_yaml(path):\n    return {}")
        _write(
            tmp_path,
            "tests/test_twice.py",
            """
            from unittest.mock import patch


            @patch("src.mypkg.json_handler")
            @patch("src.mypkg.yaml_handler")
            def test_patches_two_modules(mock_yaml, mock_json):
                assert mock_yaml is not None


            def test_patches_nothing():
                assert True
            """,
        )

        result = mock_drift_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 2
        assert result["score"] == 50

    def test_an_unreadable_production_file_is_named_beside_the_score(self, tmp_path):
        """THE HONESTY LINE. This rule reads production, so it can read too little.

        A production file that will not parse contributes no module path and no
        import binding, so a real module patch inside it resolves to nothing and
        is never flagged. A hole and an unread file look identical from outside.
        MUTATION CAUGHT: deleting the `production_limits()` block from
        `_limit_checks` - the branch then reports a healthy number with no hint
        that part of the tree was never read.
        """
        _mock_drift_project(tmp_path)
        _write(tmp_path, "src/mypkg/broken.py", "def run(:\n    return 1")

        result = mock_drift_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Production readable"]

        assert len(named) == 1
        assert "src/mypkg/broken.py" in named[0]["message"]
        assert "NOT read" in named[0]["message"]
        assert "FEWER findings" in named[0]["message"]

    def test_a_whole_production_tree_that_reads_fine_says_nothing(self, tmp_path):
        """NEGATIVE CONTROL: the limits line must not appear when nothing is missing.

        MUTATION CAUGHT: emitting the `Production readable` check
        unconditionally. A limits line that is always present is one every
        reader learns to ignore, which costs exactly the honesty it was added
        for on the day it matters.
        """
        result = mock_drift_check.check_branch(str(_mock_drift_project(tmp_path)))

        assert [check["name"] for check in result["checks"]] == ["Patch target"]

    def test_a_project_with_no_tests_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        MUTATION CAUGHT: deleting the `total == 0` early return - the project
        scores a bare 0, which blames it for a fact about its layout and enters
        a branch average as evidence nobody collected.
        """
        _write(tmp_path, "tests/helpers.py", "def build_row():\n    return {}")

        result = mock_drift_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin.

        MUTATION CAUGHT: moving the `unreadable` block below the `total == 0`
        early return. An unparseable file contributes no units, so it cannot
        lower a score, and silence about it reads as a clean result - this is
        the one path where nothing else can catch it.
        """
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = mock_drift_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])
