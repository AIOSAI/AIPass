# =================== AIPass ====================
# Name: test_pytest_quality_pack.py
# Description: behavioural pins for the pytest_quality standards pack
# Version: 1.4.0
# Created: 2026-09-01
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/corpus.py and the pack's checkers beside it."""

# Pins for the pytest_quality pack: the static corpus reader and the no_oracle
# check. Every test here names the defect or contract it protects.
#
# The owner's standing rule governs this file - never add a test without a defect it
# pins - and it applies with extra force here, because the standard under test is
# the one that convicts tests which prove nothing. A vacuous pin on the
# vacuous-test detector would be the joke telling itself. Every test below was
# confirmed RED against a named one-line mutation of the source before it shipped.
#
# What is pinned is what a plausible future edit could break:
#
#   * the vendor skip (losing it scores a project on its DEPENDENCIES' tests -
#     the single worst failure mode a portable pack has, because the number it
#     prints would be about code the project does not own)
#   * `with pytest.raises(...)` as an oracle (it appears in no `ast.Assert` node
#     and it is not a bare call expression; missing it convicts a large, correct
#     family of exception tests as assertion-free)
#   * the delegation exemption (flagging `_assert_document_is_lawful(...)` would
#     teach projects to inline their helpers to please the checker - the exact
#     behaviour v4 produced and this pack exists to stop)
#   * `not_applicable` on an empty project (zero tests measured is not zero
#     quality found; a 0 blames a project for a fact about its layout)
#   * unparseable files named as NOT measured (a broken file must never read as
#     a clean one)
#
# NOTHING HERE ASSERTS A FACT ABOUT THIS MACHINE, and nothing here reads the live
# repo tree. No Python version, no platform, no path separator, no fleet count - a
# pin whose answer changes when the fleet changes is a change detector wearing a
# test's name. Every project under test is written into `tmp_path` by the test
# that reads it.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, e.g. pytest_quality_standards/no_oracle_content.py
# seedgo: no-test-needed(constant) — the manifest text in pytest_quality_standards/pack.json

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus, no_oracle_check
from aipass.seedgo.tests.support_pytest_quality_pack import _unit, _write

# =============================================================================
# WHAT THE CORPUS COLLECTS
# =============================================================================


class TestCorpusCollection:
    """Which files and which functions become units - every number rests here."""

    def test_both_pytest_filename_shapes_are_collected(self, tmp_path):
        """pytest collects `test_*.py` AND `*_test.py`, so a generic pack must.

        The pack claims to lift onto any Python project. Half the ecosystem
        spells it `_test.py`; dropping that glob would report those projects as
        having no tests at all, and `not_applicable` would then hide a project
        that is fully tested behind a message saying nothing was measured.
        """
        _write(tmp_path, "tests/test_leading.py", "def test_leading():\n    assert True")
        _write(tmp_path, "tests/trailing_test.py", "def test_trailing():\n    assert True")

        relpaths = {parsed.relpath for parsed in corpus.build(tmp_path).files}

        assert relpaths == {"tests/test_leading.py", "tests/trailing_test.py"}

    def test_a_vendored_test_file_is_never_collected(self, tmp_path):
        """THE WORST FAILURE MODE: scoring a project on its dependencies.

        A dependency's own suite sits under `.venv/` and `node_modules/` in
        every real checkout. Losing the SKIP_DIRS prune does not just slow the
        walk - it prints a quality number about code the project does not own,
        cannot change, and was never asked about.
        """
        _write(tmp_path, ".venv/lib/site/test_vendored.py", "def test_vendored():\n    assert True")
        _write(tmp_path, "node_modules/pkg/test_dependency.py", "def test_dependency():\n    assert True")
        _write(tmp_path, "tests/test_mine.py", "def test_mine():\n    assert True")

        scanned = corpus.build(tmp_path)

        assert [parsed.relpath for parsed in scanned.files] == ["tests/test_mine.py"]
        assert scanned.unit_count() == 1

    def test_module_level_functions_and_class_methods_are_both_units(self, tmp_path):
        """pytest collects both spellings, so the reader has to see both.

        Reading only module-level defs silently drops every class-grouped
        suite - and this branch groups nearly all of its tests in classes, so
        the miss would look like a well-scoring project rather than a blind one.
        """
        _write(
            tmp_path,
            "tests/test_both.py",
            """
            def test_at_module_level():
                assert True

            class TestGrouped:
                def test_in_a_class(self):
                    assert True
            """,
        )

        units = list(corpus.build(tmp_path).units())

        assert [(unit.name, unit.class_name) for unit in units] == [
            ("test_at_module_level", ""),
            ("test_in_a_class", "TestGrouped"),
        ]

    def test_an_async_test_is_a_unit(self, tmp_path):
        """`async def test_*` is a test, and it is a separate AST node type.

        An `isinstance` that names only `ast.FunctionDef` reads an entire
        async suite as absent. The project scores on the tests it happens to
        have written synchronously, which is a fact about its I/O style.
        """
        _write(
            tmp_path,
            "tests/test_async.py",
            """
            def test_sync():
                assert True

            async def test_awaits_the_thing():
                result = await fetch()
                assert result
            """,
        )

        names = {unit.name for unit in corpus.build(tmp_path).units()}

        assert names == {"test_sync", "test_awaits_the_thing"}

    def test_a_syntax_error_lands_in_unparseable_and_is_not_counted_as_clean(self, tmp_path):
        """A broken file must not crash the build NOR read as a clean one.

        Two defects in one contract. A static reader that raises on a stranger's
        broken file cannot be pointed at an unknown project at all; a reader
        that swallows the error into silence reports a file with zero flagged
        units, which is indistinguishable from a perfect one.
        """
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")
        _write(tmp_path, "tests/test_fine.py", "def test_fine():\n    assert True")

        scanned = corpus.build(tmp_path)

        assert scanned.unparseable == ["tests/test_broken.py"]
        assert [parsed.relpath for parsed in scanned.files] == ["tests/test_fine.py"]
        assert scanned.unit_count() == 1

    def test_a_nodeid_carries_the_class_only_when_there_is_one(self, tmp_path):
        """The nodeid is the coordinate a human uses to open the flagged test.

        A flag naming `tests/test_ids.py::test_in_a_class` for a method sends
        the reader to a name that does not exist at module level, and
        `pytest tests/test_ids.py::test_in_a_class` collects nothing. The
        class segment is what makes the report actionable.
        """
        _write(
            tmp_path,
            "tests/test_ids.py",
            """
            def test_at_module_level():
                assert True

            class TestGrouped:
                def test_in_a_class(self):
                    assert True
            """,
        )

        ids = [unit.nodeid for unit in corpus.build(tmp_path).units()]

        assert ids == [
            "tests/test_ids.py::test_at_module_level",
            "tests/test_ids.py::TestGrouped::test_in_a_class",
        ]

    def test_a_fixture_named_like_a_test_is_not_a_unit(self, tmp_path):
        """pytest does not collect a fixture, whatever its name (aipass' policy fixture, fleet green leg 20).

        Read on pytest 9.1.1: an autouse fixture named ``test_...`` beside a
        real test collects the real test alone. Both spellings of the
        decorator, called and bare, are read. Red first on the name-only rule.
        """
        _write(
            tmp_path,
            "tests/test_fix.py",
            """
            import pytest
            from pytest import fixture


            @pytest.fixture(autouse=True)
            def test_policy_stays_in_tmp():
                yield 1


            @fixture
            def test_bare_fixture():
                return 2


            def test_real():
                assert True
            """,
        )

        ids = [unit.nodeid for unit in corpus.build(tmp_path).units()]

        assert ids == ["tests/test_fix.py::test_real"]


# =============================================================================
# WHAT COUNTS AS AN ORACLE
# =============================================================================


class TestOracleReading:
    """The four oracle spellings, and the one shape that is not an oracle."""

    def test_a_with_pytest_raises_is_read_as_an_oracle(self):
        """THE HIGHEST-VALUE PIN. The commonest oracle is not an `assert`.

        `with pytest.raises(...)` produces no `ast.Assert` node and is not a
        bare call expression - it lives inside a `With` item. A reader that
        misses it convicts every correctly written exception test in a project
        as verifying nothing, which is the false-flag flood that would get the
        whole standard switched off.
        """
        unit = _unit(
            """
            def test_refuses_a_bad_path():
                with pytest.raises(ValueError):
                    resolve("nope")
            """
        )

        assert corpus.oracle_calls_in(unit) == ["pytest.raises"]
        assert corpus.asserts_in(unit) == []
        assert no_oracle_check.has_oracle(unit) is True

    def test_an_assert_anywhere_in_the_body_is_found(self):
        """The oracle can be nested; only the unit's top level is not enough.

        Asserting inside a loop or a `with` block is ordinary. A reader that
        looks only at the function's direct body statements flags a test whose
        every iteration checks something, and the fix a project would reach for
        is to hoist the assert out of the loop - a worse test, to please a
        checker.
        """
        unit = _unit(
            """
            def test_every_row_is_shaped():
                for row in rows():
                    assert row.width == 3
            """
        )

        assert len(corpus.asserts_in(unit)) == 1
        assert no_oracle_check.has_oracle(unit) is True

    def test_a_mock_assert_method_is_an_oracle_via_the_prefix_rule(self):
        """`assert_*` methods are the unittest and mock spellings of an oracle.

        A change detector is a weak test, but it IS a test with a visible
        oracle. Losing the `assert_` prefix rule would file every mock-based
        suite under "verifies nothing", mixing the weak-oracle problem into the
        no-oracle report and making both unreadable.
        """
        unit = _unit(
            """
            def test_writes_the_row(store):
                write_row(store, {"a": 1})
                store.save.assert_called_once_with({"a": 1})
            """
        )

        assert corpus.oracle_calls_in(unit) == ["store.save.assert_called_once_with"]
        assert no_oracle_check.has_oracle(unit) is True

    def test_a_unit_that_verifies_nothing_reads_empty_on_both_readers(self):
        """The negative case - without it, a reader that says yes to everything passes.

        Every positive pin above is satisfied by an oracle detector that never
        returns False. This is the test that makes the others mean something:
        a unit that only drives production code has no assert and no oracle
        call, and the standard's entire output rests on that being detectable.
        """
        unit = _unit(
            """
            def test_renders_a_widget():
                widget = build_widget("blue")
                widget.render()
            """
        )

        assert corpus.oracle_calls_in(unit) == []
        assert corpus.asserts_in(unit) == []
        assert no_oracle_check.has_oracle(unit) is False


# =============================================================================
# NOMINATION
# =============================================================================


class TestNomination:
    """Who gets flagged, who is excused, and what evidence rides along."""

    @pytest.mark.parametrize(
        "helper",
        ["_assert_document_is_lawful", "check_shape", "_verify_row", "expect_empty"],
    )
    def test_a_call_to_a_checking_helper_is_not_flagged(self, helper):
        """THE EXEMPTION THAT KEEPS THE STANDARD HONEST: the oracle may be one hop away.

        A unit calling `_assert_document_is_lawful(...)` verifies something; the
        assert simply lives in the helper. Flagging it teaches a project to
        INLINE its helpers to please the checker - measurably worse tests,
        produced by the checker itself. That is exactly what v4 did, and it is
        the reason this pack was written.

        The four spellings are chosen so that each one rests on the DELEGATION
        rule alone: a plain `assert_row_shape` would be excused by the `assert_`
        oracle-call rule instead, and would keep passing with the delegation
        exemption deleted entirely.
        """
        unit = _unit(f"def test_the_row_is_shaped_right():\n    {helper}(build_row())")

        assert no_oracle_check.has_oracle(unit) is True

    def test_a_test_that_only_drives_production_code_is_flagged_with_its_calls(self, tmp_path):
        """A nomination must show its work, or a human cannot triage it.

        The check nominates, it does not convict: a bare call CAN be a working
        oracle. That claim is only true if the flag carries what the test
        called, so a reader can judge in seconds. A flag reduced to a nodeid
        turns a nomination into an accusation with no evidence attached.
        """
        _write(
            tmp_path,
            "tests/test_bare.py",
            """
            def test_renders_a_widget():
                widget = build_widget("blue")
                widget.render()
            """,
        )

        rows = no_oracle_check.find_unoracled(corpus.build(tmp_path))

        assert len(rows) == 1
        assert rows[0]["calls"] == ["build_widget", "widget.render"]
        assert rows[0]["call_count"] == 2

    def test_the_flag_names_the_unit_and_the_line_it_lives_on(self, tmp_path):
        """A flag with the wrong coordinates sends a reader to an innocent test.

        The line is carried from the corpus, not re-derived, and a default of 0
        is silently plausible everywhere - it points at the top of the file,
        which looks like a formatting quirk rather than a lost measurement.
        Pinned against the line the flagged `def` actually occupies.
        """
        path = _write(
            tmp_path,
            "tests/test_lines.py",
            """
            def test_has_an_oracle():
                assert True


            def test_drives_and_checks_nothing():
                produce_a_value()
            """,
        )
        expected_line = next(
            number
            for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
            if text.startswith("def test_drives_and_checks_nothing")
        )

        rows = no_oracle_check.find_unoracled(corpus.build(tmp_path))

        assert [row["nodeid"] for row in rows] == ["tests/test_lines.py::test_drives_and_checks_nothing"]
        assert rows[0]["line"] == expected_line

    def test_a_helper_of_the_same_module_holding_the_asserts_is_the_oracle(self, tmp_path):
        """One call away is still visible (hooks' _reason and ai_mail's _claims shapes, fleet green leg 20).

        A method of the unit's own class reached through ``self`` and a
        module-level function of the same file each count when their body
        holds an oracle. One level only: the helper's own body is read, not
        what it calls in turn. The control helper holds no oracle and its
        caller stays flagged. Red first on the reader without helpers; its
        proof is also the mutants, one per arm.
        """
        _write(
            tmp_path,
            "tests/test_helpers.py",
            """
            def _claims(value):
                assert value == 1


            def _produce(value):
                return value


            def test_module_helper_checks():
                _claims(run())


            def test_control_helper_checks_nothing():
                _produce(run())


            class TestGate:
                def _reason(self, result):
                    assert result == "block"

                def test_method_helper_checks(self):
                    self._reason(run())
            """,
        )

        rows = no_oracle_check.find_unoracled(corpus.build(tmp_path))

        assert [row["nodeid"] for row in rows] == ["tests/test_helpers.py::test_control_helper_checks_nothing"]


# =============================================================================
# THE BRANCH-LEVEL CHECK
# =============================================================================


def _scored_project(root: Path) -> Path:
    """A four-unit project where exactly one unit has no visible oracle."""
    _write(
        root,
        "tests/test_scored.py",
        """
        def test_asserts():
            assert compute() == 3

        def test_raises():
            with pytest.raises(ValueError):
                compute("bad")

        def test_mock(store):
            save(store)
            store.write.assert_called_once_with(3)

        def test_drives_only():
            compute()
        """,
    )
    return root


class TestBranchCheck:
    """The scoring API: what it reports, and what it refuses to report."""

    def test_a_project_with_no_tests_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        A 0 blames a project for a fact about its layout; a 100 claims a
        measurement that never happened. Either number enters a branch average
        and moves a board on evidence nobody collected. The only honest answer
        is `not_applicable`, and it must survive as a key the caller can read.
        """
        _write(tmp_path, "tests/helpers.py", "def build_row():\n    return {}")

        result = no_oracle_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert result["advisory"] is True
        assert "nothing measured" in result["checks"][0]["message"]

    def test_the_score_is_the_share_of_units_with_a_visible_oracle(self, tmp_path):
        """The number is units-WITH-an-oracle over total, not the inverse.

        An inverted or unscaled score still moves plausibly with the tree, so
        nothing about a live run would look wrong - a project would simply be
        told it is bad at exactly the rate it is good. Pinned on a project whose
        answer is exact: three of four units carry an oracle.
        """
        result = no_oracle_check.check_branch(str(_scored_project(tmp_path)))

        assert result["score"] == 75
        assert [row["nodeid"] for row in result["violations"]] == ["tests/test_scored.py::test_drives_only"]

    def test_the_result_passes_and_stays_advisory_even_when_units_are_flagged(self, tmp_path):
        """SHADOW MODE GATES NOTHING - the pack scores before it is calibrated.

        A standard that starts by failing boards it has never been measured
        against repeats the mistake v4 made. Top-level `passed` must stay True
        while flags exist, and `advisory` must stay True so the caller can tell
        a report from a verdict. The per-check line is where the failure shows.
        """
        result = no_oracle_check.check_branch(str(_scored_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["checks"][0]["passed"] is False
        assert "no visible oracle" in result["checks"][0]["message"]

    def test_an_unparseable_file_is_named_as_not_measured(self, tmp_path):
        """A file that could not be read must never pass for a clean one.

        An unparseable file contributes no units, so it cannot lower the score -
        which means silence about it reads as a perfect result. The extra check
        line is the only thing standing between "we could not read this" and
        "we read this and it was fine".
        """
        _scored_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = no_oracle_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]


class TestTheFixesFromTheFirstRedFirstPass:
    """The two defects the pack's own first test pass found in the pack.

    Both were reproduced against the live code before the fix and both are
    inherited-shape bugs, not typos - they are pinned here so the fix cannot
    quietly regress.
    """

    def test_a_project_that_keeps_tests_outside_a_top_level_tests_dir_is_still_measured(self, tmp_path):
        """Pins the whole-tree fallback in corpus.build.

        `[root / n for n in test_dirs] or [root]` can NEVER reach the fallback:
        a non-empty test_dirs always yields a non-empty list whether or not any
        of those directories exist. The walk then found nothing and the project
        reported "no test files found". Most of the pytest ecosystem does not
        use a top-level tests/, so this silently declined to measure exactly the
        projects the pack claims portability onto.
        """
        (tmp_path / "src" / "tests").mkdir(parents=True)
        (tmp_path / "src" / "tests" / "test_a.py").write_text("def test_one():\n    assert 1 == 1\n", encoding="utf-8")
        (tmp_path / "test_root_level.py").write_text("def test_two():\n    assert 2 == 2\n", encoding="utf-8")

        result = no_oracle_check.check_branch(str(tmp_path))

        assert result.get("not_applicable") is not True
        assert result["score"] == 100
        assert "2/2" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """Pins: a broken file must never read as an absent one.

        The `total == 0` early return fired before the unparseable check was
        built, so a project whose ONLY test file had a syntax error returned the
        identical message to a project with no tests at all - "no test files
        found". That is the precise contract Corpus.unparseable exists to keep,
        defeated on the one path where nothing else could catch it.
        """
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_broken.py").write_text("def test_broken(:\n    pass\n", encoding="utf-8")

        result = no_oracle_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in c["message"] for c in result["checks"])

    def test_a_genuinely_empty_project_still_says_no_test_files_found(self, tmp_path):
        """The other arm of the same fix - the fallback must not swallow the real empty case.

        Constructing both arms rather than borrowing one: without this, the
        broken-file pin above passes just as well against code that never says
        "no test files found" at all.
        """
        result = no_oracle_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" in result["checks"][0]["message"]


class TestTheCorpusWalkSurvivesWhereItLives:
    """The portability species: three ways a corpus silently collected nothing.

    All three shipped in code written for this pack, all three were found by the
    pack's own red-first test passes rather than by review, and all three failed
    the same way - not with an error but with the plausible sentence "no test
    files found". That is the failure mode worth pinning: a walker that returns
    an empty list looks exactly like a project with no tests.
    """

    def test_a_project_living_under_a_vendor_named_directory_is_still_walked(self, tmp_path):
        """Pins relative-path pruning in corpus._walk.

        Testing `path.parts` against SKIP_DIRS reads the WHOLE ABSOLUTE path, so
        a checkout that merely lives under a directory called build, dist, venv
        or node_modules had every one of its test files skipped. A checkout's
        parent directories are the user's business; only what is inside the
        project can be vendored.
        """
        project = tmp_path / "build" / "myproject"
        (project / "tests").mkdir(parents=True)
        (project / "tests" / "test_a.py").write_text("def test_a():\n    assert 1\n", encoding="utf-8")

        scanned = corpus.build(project, test_dirs=("tests", "test"))

        assert scanned.unit_count() == 1

    def test_a_vendor_directory_inside_the_project_is_still_pruned(self, tmp_path):
        """The other arm - the fix must not simply stop pruning.

        Constructed rather than borrowed: without this, the pin above passes
        just as well against a walker that skips nothing at all and happily
        scores a project on its dependencies' test suites.
        """
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_mine.py").write_text("def test_m():\n    assert 1\n", encoding="utf-8")
        vendored = tmp_path / "node_modules" / "dep" / "tests"
        vendored.mkdir(parents=True)
        (vendored / "test_theirs.py").write_text("def test_t():\n    assert 1\n", encoding="utf-8")

        scanned = corpus.build(tmp_path)

        assert [f.relpath for f in scanned.files] == ["tests/test_mine.py"]

    def test_a_test_file_outside_the_named_test_dirs_is_never_read_as_production(self, tmp_path):
        """Pins that production excludes every test-SHAPED file, not just collected ones.

        Excluding only the paths the test walk reached let a test_*.py outside
        test_dirs fall through into production_trees, and then both halves were
        wrong at once: pytest really would collect that file so a genuine test
        went unmeasured, and its test-only constants were readable as production
        declarations by any rule that walks production.
        """
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    assert 1\n", encoding="utf-8")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "test_stray.py").write_text(
            'COMMANDS = ("ghost-verb",)\n\n\ndef test_stray():\n    assert 1\n', encoding="utf-8"
        )

        scanned = corpus.build(tmp_path, test_dirs=("tests", "test"), with_production=True)

        assert scanned.production_trees == {}

    def test_a_real_production_module_is_still_parsed_into_production_trees(self, tmp_path):
        """The other arm - excluding test-shaped files must not exclude everything.

        Without this the pin above passes against a _parse_production that
        parses nothing at all, which would silently disarm every rule that
        compares tests against the code they cover.
        """
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    assert 1\n", encoding="utf-8")
        (tmp_path / "app.py").write_text('COMMANDS = ("run",)\n', encoding="utf-8")

        scanned = corpus.build(tmp_path, test_dirs=("tests", "test"), with_production=True)

        assert list(scanned.production_trees) == ["app.py"]


class TestTheTeachingTemplatesStillRun:
    """The templates claim to be worked examples. Something has to prove it.

    They are deliberately invisible to both suites: seedgo's pytest.ini narrows
    `python_files` to `test_*.py` (these are `*_test.py`) and the repo root puts
    `templates` in `norecursedirs`. That is the right call - teaching files must
    not inflate a branch's green count. But it leaves them run by NOTHING, and a
    worked example nobody executes is prose claiming to be code, which is the
    exact species this pack exists to correct. So this pin runs them out-of-band.
    """

    def test_every_teaching_template_passes_when_it_is_actually_run(self):
        """Pins that the templates in pytest_quality_standards/templates are green.

        Calls subprocess.run over pytest with the default file patterns restored.
        If a template rots - a renamed symbol, a changed signature, a wrong
        example that stops being wrong - this goes red and nothing else would.
        """
        import subprocess
        import sys

        templates = (
            Path(__file__).resolve().parent.parent / "apps" / "handlers" / "pytest_quality_standards" / "templates"
        )
        assert templates.is_dir(), f"templates directory is missing: {templates}"

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(templates),
                "-q",
                "-o",
                "python_files=test_*.py *_test.py",
                "-o",
                "addopts=",
                "-p",
                "no:cacheprovider",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
        )

        assert completed.returncode == 0, f"templates are not green:\n{completed.stdout}\n{completed.stderr}"

    def test_the_templates_are_not_collected_by_the_branch_suite(self):
        """Pins the other arm - teaching files must stay OUT of the branch count.

        Constructed rather than borrowed: without this, the pin above passes
        just as well after someone renames the templates to test_*.py, which
        would quietly add worked examples to every fleet test tally and undo the
        reason they are kept separate.
        """
        templates = (
            Path(__file__).resolve().parent.parent / "apps" / "handlers" / "pytest_quality_standards" / "templates"
        )

        collected_by_branch_pattern = sorted(p.name for p in templates.glob("test_*.py"))

        assert collected_by_branch_pattern == []
