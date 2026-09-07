# =================== AIPass ====================
# Name: test_pytest_quality_pack.py
# Description: behavioural pins for the pytest_quality standards pack
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""
Pins for the pytest_quality pack: the static corpus reader and the no_oracle
check. Every test here names the defect or contract it protects.

Patrick's standing rule governs this file - never add a test without a defect it
pins - and it applies with extra force here, because the standard under test is
the one that convicts tests which prove nothing. A vacuous pin on the
vacuous-test detector would be the joke telling itself. Every test below was
confirmed RED against a named one-line mutation of the source before it shipped.

What is pinned is what a plausible future edit could break:

  * the vendor skip (losing it scores a project on its DEPENDENCIES' tests -
    the single worst failure mode a portable pack has, because the number it
    prints would be about code the project does not own)
  * `with pytest.raises(...)` as an oracle (it appears in no `ast.Assert` node
    and it is not a bare call expression; missing it convicts a large, correct
    family of exception tests as assertion-free)
  * the delegation exemption (flagging `_assert_document_is_lawful(...)` would
    teach projects to inline their helpers to please the checker - the exact
    behaviour v4 produced and this pack exists to stop)
  * `not_applicable` on an empty project (zero tests measured is not zero
    quality found; a 0 blames a project for a fact about its layout)
  * unparseable files named as NOT measured (a broken file must never read as
    a clean one)

NOTHING HERE ASSERTS A FACT ABOUT THIS MACHINE, and nothing here reads the live
repo tree. No Python version, no platform, no path separator, no fleet count - a
pin whose answer changes when the fleet changes is a change detector wearing a
test's name. Every project under test is written into `tmp_path` by the test
that reads it.
"""

import ast
import textwrap
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.pytest_quality_standards import assertion_shape_check, corpus, no_oracle_check


def _write(root: Path, relpath: str, source: str) -> Path:
    """One file, dedented, with its parents made."""
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).strip() + "\n", encoding="utf-8")
    return path


def _unit(source: str, relpath: str = "tests/test_x.py", class_name: str = "") -> corpus.TestUnit:
    """One written-out test function as the TestUnit the readers are handed."""
    node = ast.parse(textwrap.dedent(source).strip()).body[0]
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)), "the snippet must be one test function"
    return corpus.TestUnit(
        name=node.name,
        node=node,
        relpath=relpath,
        class_name=class_name,
        line=node.lineno,
    )


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


# =============================================================================
# ASSERTION SHAPE - CAN THE ORACLE EVER SAY NO
# =============================================================================
#
# Every test below was confirmed RED against a named one-line mutation of
# assertion_shape_check.py before it shipped, per Patrick's standing rule. The
# mutation each one catches is named in its docstring, so a future reader can
# re-run the experiment instead of trusting this comment.


def _shape_project(root: Path) -> Path:
    """A four-unit project where exactly one unit carries an unfailable assert."""
    _write(
        root,
        "tests/test_shapes.py",
        """
        def test_asserts_a_value():
            assert compute() == 3

        def test_asserts_a_literal():
            assert True

        def test_checks_the_pair():
            result = compute()
            assert isinstance(result, int)
            assert result == 3

        def test_tolerates_a_platform_gap():
            assert not hasattr(signal, "SIGKILL") or compute() == 3
        """,
    )
    return root


class TestTautologyDetection:
    """Assertions that are decided before the program runs - and the ones that are not."""

    def test_a_bare_literal_assert_is_flagged(self):
        """`assert True` is a comment with a keyword in front of it.

        Pins the `_literal_assert` detector. MUTATION CAUGHT: making
        `_literal_assert` return "" unconditionally (dropping its
        `isinstance(test, ast.Constant)` arm) - the single most common shape in
        the audited corpus then reads as a real assertion.
        """
        unit = _unit(
            """
            def test_the_thing_works():
                run_the_thing()
                assert True
            """
        )

        rows = assertion_shape_check.unit_flags(unit)

        assert [row["species"] for row in rows] == ["TAUTOLOGY"]
        assert "literal True" in rows[0]["reason"]

    @pytest.mark.parametrize("compare", ["len(rows) >= 0", "len(rows) < 0"])
    def test_a_len_compared_against_zero_in_a_decided_direction_is_flagged(self, compare):
        """`len(x) >= 0` holds for every sequence; `len(x) < 0` holds for none.

        Both directions are decided before the program runs, and both read as
        real bounds checks at a glance. MUTATION CAUGHT: narrowing
        `VACUOUS_LEN_OPS` to `(ast.Lt,)` - the `>=` spelling, which is the one
        that actually appears in corpora, stops being seen.
        """
        unit = _unit(f"def test_rows_are_returned():\n    rows = fetch()\n    assert {compare}")

        rows = assertion_shape_check.unit_flags(unit)

        assert [row["species"] for row in rows] == ["TAUTOLOGY"]
        assert "true of every sequence" in rows[0]["reason"]

    @pytest.mark.parametrize("compare", ["len(rows) > 0", "len(rows) >= 3"])
    def test_a_real_len_comparison_is_never_flagged(self, compare):
        """NEGATIVE CONTROL, constructed rather than borrowed.

        `len(x) > 0` and `len(x) >= 3` are ordinary, correct assertions and are
        the overwhelming majority of `len` comparisons in any suite. Flagging
        them would bury the two real shapes in noise and get the standard
        switched off. The second arm is deliberately `>=`: only the comparison
        against ZERO is vacuous, and it is the BOUND that decides that, not the
        operator. MUTATIONS CAUGHT: widening `VACUOUS_LEN_OPS` with `ast.Gt`
        (kills the first arm); dropping the `comparator.value == 0` requirement
        to `if not isinstance(comparator, ast.Constant):` (kills the second, and
        would convict every `len(x) >= N` bound in a suite).
        """
        unit = _unit(f"def test_rows_are_returned():\n    rows = fetch()\n    assert {compare}")

        assert assertion_shape_check.unit_flags(unit) == []

    def test_membership_in_the_whole_bool_domain_is_flagged(self):
        """`x in (True, False)` is true of every bool, so it asserts nothing.

        MUTATION CAUGHT: replacing the domain test `set(values) == {True, False}`
        with `False` - the shape survives as a plausible-looking membership
        check that no implementation can fail.
        """
        unit = _unit(
            """
            def test_the_flag_is_boolean():
                flag = compute()
                assert flag in (True, False)
            """
        )

        rows = assertion_shape_check.unit_flags(unit)

        assert [row["species"] for row in rows] == ["TAUTOLOGY"]
        assert "every bool" in rows[0]["reason"]

    def test_a_membership_in_real_values_is_never_flagged(self):
        """NEGATIVE CONTROL: membership is a normal assertion about a value.

        `status in ("ok", "fail")` genuinely excludes every other string. The
        rule must key on the DOMAIN, not on the `in` operator. MUTATION CAUGHT:
        dropping the `set(values) == {True, False}` domain test so any
        constant-only container flags.
        """
        unit = _unit(
            """
            def test_the_status_is_known():
                status = compute()
                assert status in ("ok", "fail")
            """
        )

        assert assertion_shape_check.unit_flags(unit) == []

    def test_a_self_comparison_is_flagged(self):
        """`a == a` compares an expression with itself and cannot fail.

        The two sides are distinct AST objects with identical structure, which
        is why the comparison has to be on the DUMP. MUTATION CAUGHT: replacing
        `ast.dump(test.left) == ast.dump(test.comparators[0])` with the identity
        test `test.left is test.comparators[0]`, which is never true for two
        parsed sides and so silently detects nothing.
        """
        unit = _unit(
            """
            def test_the_name_survives():
                config = load()
                assert config.name == config.name
            """
        )

        rows = assertion_shape_check.unit_flags(unit)

        assert [row["species"] for row in rows] == ["TAUTOLOGY"]
        assert "same expression" in rows[0]["reason"]

    def test_a_comparison_of_two_different_expressions_is_never_flagged(self):
        """NEGATIVE CONTROL: the ordinary assertion, which must stay silent.

        `config.name == expected.name` is structurally identical to a self
        comparison apart from the operand names. MUTATION CAUGHT: relaxing the
        dump comparison to a type comparison,
        `type(test.left) is type(test.comparators[0])` - which flags every
        attribute-against-attribute assertion in a suite.
        """
        unit = _unit(
            """
            def test_the_name_round_trips():
                config = load()
                assert config.name == expected.name
            """
        )

        assert assertion_shape_check.unit_flags(unit) == []


class TestTheOrEscapeJudgement:
    """The narrow species: an assertion with an exit, and the one that is not."""

    def test_an_or_whose_clauses_are_all_about_the_result_is_flagged(self):
        """`assert x == [] or isinstance(x, list)` passes whenever either holds.

        The second clause is true whenever the first is, so the assertion has an
        exit and a wrong implementation walks out through it. MUTATION CAUGHT:
        reading `ast.And` instead of `ast.Or` in `_or_escape` - the detector
        then fires on conjunctions, which are strictly stronger assertions, and
        never on the escape it was written for.
        """
        unit = _unit(
            """
            def test_the_diff_is_empty_ish():
                result = diff(a, b)
                assert result == [] or isinstance(result, list)
            """
        )

        rows = assertion_shape_check.unit_flags(unit)

        assert [row["species"] for row in rows] == ["OR-ESCAPE"]
        assert "probes the machine" in rows[0]["reason"]

    @pytest.mark.parametrize(
        "clause",
        [
            'not hasattr(signal, "SIGKILL")',
            'sys.platform == "win32"',
            'os.name == "nt"',
            'shutil.which("git") is None',
        ],
    )
    def test_a_capability_probe_acquits_the_or(self, clause):
        """NEGATIVE CONTROL AND THE RULE'S HONESTY: platform-divergent code is not an escape.

        A first clause that asks about the MACHINE rather than the result is how
        a correct cross-platform test is written. Flagging these would convict
        exactly the tests that were most carefully written, which is the wrong
        that gets a standard disabled. MUTATION CAUGHT: deleting the
        `any(_is_capability_clause(value) for value in test.values)` acquittal
        from `_or_escape`.
        """
        unit = _unit(f"def test_handles_the_platform_gap():\n    assert {clause} or compute() == 3")

        assert assertion_shape_check.unit_flags(unit) == []


class TestTypeOnlyIsAPropertyOfTheUnit:
    """The pairing rule - the one this port could most easily get backwards."""

    def test_a_unit_whose_whole_oracle_is_isinstance_is_flagged(self):
        """A test that pins only the return TYPE passes on the right shape of garbage.

        MUTATION CAUGHT: making `_is_isinstance_only` return False (for example
        by mis-spelling the `isinstance` name it matches on) - the species
        disappears entirely and every type-only unit scores clean.
        """
        unit = _unit(
            """
            def test_parse_returns_a_dict():
                result = parse(SAMPLE)
                assert isinstance(result, dict)
            """
        )

        rows = assertion_shape_check.unit_flags(unit)

        assert [row["species"] for row in rows] == ["TYPE-ONLY"]
        assert "says nothing about the value" in rows[0]["reason"]

    def test_an_isinstance_standing_beside_a_value_assertion_is_never_flagged(self):
        """THE PAIRING RULE: TYPE-ONLY is a property of the UNIT, never of a line.

        A type assertion with a value assertion beside it is correct and common.
        Flagging it would teach projects to DELETE their type assertions to
        please the checker - a worse suite, produced by the standard itself.
        MUTATION CAUGHT: `all(_is_isinstance_only(...))` weakened to `any(...)`,
        which convicts every unit that contains an isinstance anywhere.
        """
        unit = _unit(
            """
            def test_parse_returns_the_offset():
                result = parse(SAMPLE)
                assert isinstance(result, dict)
                assert result["offset"] == 3
            """
        )

        assert assertion_shape_check.unit_flags(unit) == []

    def test_a_unit_with_no_assertions_at_all_produces_no_shape_finding(self):
        """An absent oracle is `no_oracle`'s business, not this rule's.

        `all(...)` over an empty list is True, so a unit with zero asserts would
        be reported TYPE-ONLY by a reader that forgot the empty guard - and the
        message would claim "every one of this unit's 0 assertion(s) is an
        isinstance check", which is both false and unactionable. MUTATION
        CAUGHT: deleting the `if not asserts: return []` guard from
        `unit_flags`.
        """
        unit = _unit(
            """
            def test_renders_a_widget():
                widget = build_widget("blue")
                widget.render()
            """
        )

        assert assertion_shape_check.unit_flags(unit) == []

    def test_a_healthy_unit_produces_no_findings_of_any_species(self):
        """THE OVERALL NEGATIVE CONTROL - without it, a detector that says yes to everything passes.

        Every positive pin above is satisfied by an analyser that flags all
        assertions. This unit asserts a value, pairs a type check beside it, and
        must come back clean on all three species at once. MUTATION CAUGHT:
        inverting `_literal_assert`'s guard to
        `if not isinstance(test, ast.Constant)`, which flags every non-literal
        assertion in existence.
        """
        unit = _unit(
            """
            def test_the_parser_keeps_the_offset():
                result = parse("a=1")
                assert result.offset == 3
                assert isinstance(result.offset, int)
            """
        )

        assert assertion_shape_check.unit_flags(unit) == []


class TestAssertionShapeBranchCheck:
    """The scoring API: what it reports, and what it refuses to report."""

    def test_the_score_is_the_share_of_units_with_no_flagged_assertion(self, tmp_path):
        """The number is units-WITHOUT-a-flag over total, not the inverse.

        An inverted score still moves plausibly with a tree, so nothing about a
        live run would look wrong - a project would simply be told it is bad at
        exactly the rate it is good. Pinned on a project whose answer is exact:
        one of four units carries an unfailable assertion. MUTATION CAUGHT:
        `score = int((len(units) / total) * 100)`.
        """
        result = assertion_shape_check.check_branch(str(_shape_project(tmp_path)))

        assert result["score"] == 75
        assert [row["nodeid"] for row in result["violations"]] == ["tests/test_shapes.py::test_asserts_a_literal"]

    def test_a_unit_holding_several_flagged_assertions_still_costs_one_unit(self, tmp_path):
        """THE SCORE IS PER UNIT, NOT PER FINDING - or it can go below zero.

        A single sloppy test with three tautologies would otherwise drive a
        two-unit project to -50, and a score that can go negative is one nobody
        believes twice. MUTATION CAUGHT: scoring off the finding list,
        `score = int(((total - len(flagged)) / total) * 100)`, which reports -50
        here while still reporting a plausible number on every project that
        happens to hold one flag per unit.
        """
        _write(
            tmp_path,
            "tests/test_many.py",
            """
            def test_piles_them_up():
                value = compute()
                assert True
                assert len(value) >= 0
                assert value == value

            def test_asserts_a_value():
                assert compute() == 3
            """,
        )

        result = assertion_shape_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 3
        assert result["score"] == 50

    def test_the_result_passes_and_stays_advisory_while_units_are_flagged(self, tmp_path):
        """SHADOW MODE GATES NOTHING - the pack scores before it is calibrated.

        A standard that starts by failing boards it has never been measured
        against repeats the mistake this pack exists to correct. Top-level
        `passed` stays True while flags exist; the per-check line is where the
        failure shows. MUTATION CAUGHT: `"passed": not units` in the returned
        dict, which turns an advisory report into a board-failing verdict.
        """
        result = assertion_shape_check.check_branch(str(_shape_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "ASSERTION_SHAPE"
        assert result["checks"][0]["passed"] is False
        assert "cannot fail" in result["checks"][0]["message"]

    def test_a_finding_names_its_species_and_the_line_the_assertion_lives_on(self, tmp_path):
        """A flag with the wrong coordinates sends a reader to an innocent line.

        The line must be the ASSERT's, not the unit's: a reader opening the flag
        needs the statement, and the def line is silently plausible - it points
        at the right test, so the mistake survives review. MUTATION CAUGHT:
        `_finding("TAUTOLOGY", unit, unit.line, reason)` in `unit_flags`.
        """
        path = _write(
            tmp_path,
            "tests/test_coords.py",
            """
            def test_has_a_tautology():
                value = compute()
                assert True
            """,
        )
        expected_line = next(
            number
            for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
            if text.strip() == "assert True"
        )

        rows = assertion_shape_check.check_branch(str(tmp_path))["violations"]

        assert [row["nodeid"] for row in rows] == ["tests/test_coords.py::test_has_a_tautology"]
        assert rows[0]["species"] == "TAUTOLOGY"
        assert rows[0]["line"] == expected_line

    def test_a_project_with_no_tests_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        A 0 blames a project for a fact about its layout and a 100 claims a
        measurement that never happened; either number enters a branch average
        on evidence nobody collected. MUTATION CAUGHT: `if total < 0:` on the
        early return, which drops through to the score line and divides by zero
        on every project that keeps no tests.
        """
        _write(tmp_path, "tests/helpers.py", "def build_row():\n    return {}")

        result = assertion_shape_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert result["advisory"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """THE ORDERING CONTRACT: a broken file must never read as an absent one.

        The unparseable check line is built BEFORE the `total == 0` return
        precisely so this path keeps it - an unreadable file contributes no
        units, so the empty path is the one place nothing else could catch the
        omission. MUTATION CAUGHT: guarding the unparseable block with
        `if scanned.unparseable and total:`, which reproduces the original
        defect exactly - the file is never named, and the project reads as one
        that simply has no tests.
        """
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = assertion_shape_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("tests/test_broken.py" in check["message"] for check in result["checks"])
        assert any("NOT measured" in check["message"] for check in result["checks"])

    def test_an_unparseable_file_beside_readable_ones_is_named_as_not_measured(self, tmp_path):
        """A file that could not be read must never pass for a clean one.

        An unparseable file contributes no units, so it cannot lower the score -
        which means silence about it reads as a perfect result. MUTATION CAUGHT:
        dropping `checks.extend(unreadable)` from the scored return path, where
        the score itself still looks entirely reasonable.
        """
        _shape_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = assertion_shape_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]


from aipass.seedgo.apps.handlers.pytest_quality_standards import unentered_assert_check  # noqa: E402

# =============================================================================
# UNENTERED ASSERTIONS - THE ASSERT THAT MAY NEVER EXECUTE
# =============================================================================


def _line_of(path: Path, prefix: str) -> int:
    """The 1-based line number of the first line starting with `prefix`."""
    return next(
        number
        for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if text.startswith(prefix)
    )


def _unentered_assert_project(root: Path) -> Path:
    """A four-unit project where exactly one unit's assertions may never run.

    Three of the four are the known-good shapes this rule must never flag: a
    plain body assertion, a two-sided guard, and a loop over a literal. Built
    that way on purpose - a project where the safe units are safe for the SAME
    reason would score 75 with two of the three exemptions deleted.
    """
    _write(
        root,
        "tests/test_scored_reachability.py",
        """
        def test_asserts_plainly():
            assert compute() == 3

        def test_checks_both_arms():
            if payload.compressed:
                assert decode(payload) == EXPECTED
            else:
                assert payload.raw == EXPECTED

        def test_walks_a_literal_collection():
            for value in [1, 2]:
                assert shape(value) == 2

        def test_asserts_only_when_configured():
            config = load_config()
            if config.strict:
                assert config.limit == 10
        """,
    )
    return root


class TestUnenteredAssertReachability:
    """VACUOUS-GUARD and VACUOUS-LOOP: assertions nothing proves ever execute."""

    def test_an_assert_reachable_only_through_a_one_sided_if_is_flagged(self, tmp_path):
        """VACUOUS-GUARD, with the coordinates a reader needs to triage it.

        The species this rule exists for: when the guard is false the unit
        passes having checked nothing, and the report says nothing about which
        happened. Pinned with the guard's own line, not just the unit's - a flag
        that names the def sends a reader hunting for the branch, and a default
        0 there is silently plausible because it points at the top of the file.
        """
        path = _write(
            tmp_path,
            "tests/test_guard.py",
            """
            def test_asserts_only_when_configured():
                config = load_config()
                if config.strict:
                    assert config.limit == 10
            """,
        )

        rows = unentered_assert_check.find_unentered(corpus.build(tmp_path))

        assert [row["nodeid"] for row in rows] == ["tests/test_guard.py::test_asserts_only_when_configured"]
        assert rows[0]["species"] == "VACUOUS-GUARD"
        assert rows[0]["line"] == _line_of(path, "def test_asserts_only_when_configured")
        assert rows[0]["branch_line"] == _line_of(path, "    if config.strict")

    def test_an_if_that_asserts_on_both_arms_is_never_flagged(self, tmp_path):
        """THE KNOWN-GOOD, AND THE HARD HALF OF THE RULE: a two-sided guard is correct code.

        Whichever way the condition falls, something is checked - this is how
        divergent behaviour is legitimately tested. Flag it and the checker
        teaches projects to delete the arm they cannot run on the box they are
        sitting at, which is worse code than it started with. The unit carries
        NO body-level assertion, so it rests on the two-sided exemption alone
        and cannot be saved by the always-runs rule instead.
        """
        _write(
            tmp_path,
            "tests/test_two_sided.py",
            """
            def test_the_payload_round_trips():
                if payload.compressed:
                    assert decode(payload) == EXPECTED
                else:
                    assert payload.raw == EXPECTED
            """,
        )

        rows = unentered_assert_check.find_unentered(corpus.build(tmp_path))

        assert rows == []

    def test_a_unit_that_also_asserts_in_its_body_is_never_flagged(self, tmp_path):
        """An assertion that always runs excuses the unit, however much it also guards.

        This rule is about assertions that may never execute, not assertions
        that are merely conditional. Drop the exemption and every test that
        checks a base case first and then a conditional extra - a large and
        entirely correct family - is convicted for the second assertion.
        """
        _write(
            tmp_path,
            "tests/test_body_assert.py",
            """
            def test_the_row_is_shaped_and_maybe_labelled():
                row = load_row()
                assert row.width == 3
                if row.label:
                    assert row.label.startswith("v")
            """,
        )

        rows = unentered_assert_check.find_unentered(corpus.build(tmp_path))

        assert rows == []

    def test_an_assert_inside_a_with_block_counts_as_one_that_always_runs(self, tmp_path):
        """Entering a `with` is not a branch, so an assert in its body always runs.

        Read only the function body's own statements and `with` looks like a
        conditional: the assertion inside it stops counting, the unit loses its
        exemption, and every test that asserts inside a context manager and then
        guards an extra case is flagged. `with` and `try` decide nothing - the
        recursion into their bodies is what keeps them from reading as branches.
        """
        _write(
            tmp_path,
            "tests/test_with_block.py",
            """
            def test_the_header_is_read_and_maybe_labelled():
                with open_fixture() as data:
                    assert data.header == "v1"
                if data.label:
                    assert data.label.startswith("v")
            """,
        )

        rows = unentered_assert_check.find_unentered(corpus.build(tmp_path))

        assert rows == []

    def test_an_assert_reachable_only_inside_a_floorless_for_is_flagged(self, tmp_path):
        """VACUOUS-LOOP: an empty iterable makes the whole unit a silent pass.

        Observed live - a citizen-declaration test walking an empty directory
        inside a suite reporting 478 passed. The loop's line rides along for the
        same reason the guard's does: the def alone does not tell a reader which
        of several loops was the one that may never be entered.
        """
        path = _write(
            tmp_path,
            "tests/test_loop.py",
            """
            def test_every_project_declares_itself():
                for project in projects_dir.iterdir():
                    assert (project / "passport.json").exists()
            """,
        )

        rows = unentered_assert_check.find_unentered(corpus.build(tmp_path))

        assert [row["nodeid"] for row in rows] == ["tests/test_loop.py::test_every_project_declares_itself"]
        assert rows[0]["species"] == "VACUOUS-LOOP"
        assert rows[0]["branch_line"] == _line_of(path, "    for project in projects_dir.iterdir")

    def test_a_loop_over_a_literal_collection_is_never_flagged(self, tmp_path):
        """THE LOOP'S KNOWN-GOOD: a literal iterable is a floor by construction.

        `for value in [1, 2, 3]` runs three times on every machine that ever
        executes it - there is no empty case to worry about. Losing the literal
        arm convicts the commonest correct table-driven test in any corpus, and
        it is the arm that actually fires from `check_branch`: the assert-shaped
        floor is subsumed by the always-runs exemption one step earlier.
        """
        _write(
            tmp_path,
            "tests/test_literal_loop.py",
            """
            def test_each_named_case_is_shaped():
                for value in [1, 2, 3]:
                    assert shape(value) == 3
            """,
        )

        rows = unentered_assert_check.find_unentered(corpus.build(tmp_path))

        assert rows == []

    def test_a_unit_carrying_both_shapes_is_one_flag_not_two(self, tmp_path):
        """One unit, one finding - or the score can be driven below zero.

        A unit with a one-sided guard AND a floorless loop is one problem with
        two symptoms. Counting it twice pushes the flagged total past the unit
        total, and `(total - flagged) / total` then reports a NEGATIVE score
        that no caller checks for, on a branch that merely has a lot of them.
        """
        _write(
            tmp_path,
            "tests/test_both_shapes.py",
            """
            def test_guards_and_walks():
                if config.strict:
                    assert config.limit == 10
                for project in projects_dir.iterdir():
                    assert project.exists()
            """,
        )

        rows = unentered_assert_check.find_unentered(corpus.build(tmp_path))

        assert len(rows) == 1
        assert rows[0]["species"] == "VACUOUS-GUARD"

    def test_the_score_is_the_share_of_units_with_no_unentered_assert(self, tmp_path):
        """The number is units-that-are-FINE over total, not the inverse.

        An inverted or unscaled score still moves plausibly with the tree, so
        nothing about a live run would look wrong - a project would simply be
        told it is bad at exactly the rate it is good. Pinned on a project whose
        answer is exact: three of four units assert on a path that always runs.
        """
        result = unentered_assert_check.check_branch(str(_unentered_assert_project(tmp_path)))

        assert result["score"] == 75
        assert [row["nodeid"] for row in result["violations"]] == [
            "tests/test_scored_reachability.py::test_asserts_only_when_configured"
        ]

    def test_the_result_passes_and_stays_advisory_even_when_units_are_flagged(self, tmp_path):
        """SHADOW MODE GATES NOTHING - this rule scores before it is calibrated.

        Top-level `passed` must stay True while flags exist and `advisory` must
        stay True, so a caller can tell a report from a verdict. A rule that
        starts by failing boards it has never been measured against is how the
        v4 pattern count came to be gamed rather than fixed. The per-check line
        is where the failure shows.
        """
        result = unentered_assert_check.check_branch(str(_unentered_assert_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "UNENTERED_ASSERT"
        assert result["checks"][0]["passed"] is False
        assert "may never be entered" in result["checks"][0]["message"]

    def test_a_project_with_no_tests_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        A 0 blames a project for a fact about its layout; a 100 claims a
        measurement that never happened. Either number enters a branch average
        and moves a board on evidence nobody collected. The only honest answer
        is `not_applicable`, and it must survive as a key the caller can read.
        """
        _write(tmp_path, "tests/helpers.py", "def build_row():\n    return {}")

        result = unentered_assert_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin.

        Build the unreadable-file line AFTER the `total == 0` early return and a
        project whose ONLY test file has a syntax error reports exactly what a
        project with no tests at all reports. That is the one path where nothing
        else can catch it: an unparseable file contributes no units, so it
        cannot lower a score, and silence about it reads as a clean result.
        """
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = unentered_assert_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_file_is_named_beside_a_scored_result(self, tmp_path):
        """The unreadable line must also survive onto the path that DOES score.

        The early-return path carries it by construction; the scored path has to
        append it deliberately, and dropping that one line leaves a branch with
        a healthy number and no hint that a file was never read at all.
        """
        _unentered_assert_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = unentered_assert_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 75
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]


# =============================================================================
# MOCK DRIFT - DOES A PATCH REPLACE A FUNCTION OR A WHOLE MODULE
# =============================================================================
#
# Every test below was confirmed RED against a named one-line mutation of
# mock_drift_check.py before it shipped, per Patrick's standing rule. The
# mutation each one catches is named in its docstring, so a future reader can
# re-run the experiment instead of trusting this comment.
#
# The import sits here rather than at the top of the file because this section
# was appended while another author was appending to the same file; E402 is
# ignored repo-wide, and a local import cannot collide with a concurrent edit.

from aipass.seedgo.apps.handlers.pytest_quality_standards import mock_drift_check, self_skip_check  # noqa: E402


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


# =============================================================================
# SELF SKIP - WHERE A SKIP CONDITION GETS ITS ANSWER FROM
# =============================================================================
#
# Every test below was confirmed RED against a named one-line mutation of
# self_skip_check.py before it shipped, per Patrick's standing rule.


def _skip_rows(root: Path) -> list:
    """Every skip-provenance finding in a written-out project."""
    return self_skip_check.find_self_skips(corpus.build(root, test_dirs=self_skip_check.TEST_DIRS))


def _skip_species(root: Path) -> list:
    """The findings as `(species, nodeid)` pairs, for a compact assertion."""
    return [(row["species"], row["nodeid"]) for row in _skip_rows(root)]


def _self_skip_project(root: Path) -> Path:
    """A four-unit file where exactly one unit skips on the subject.

    The three clean units are clean for THREE DIFFERENT reasons - a platform
    gate, an environment gate, and no skip at all - so no single deleted
    exemption leaves the score where it was.
    """
    _write(
        root,
        "tests/test_skips.py",
        """
        import os
        import sys

        import pytest

        from mypkg import registry


        @pytest.mark.skipif(sys.platform == "win32", reason="posix only")
        def test_gates_on_the_platform():
            assert registry.build() is not None


        @pytest.mark.skipif(os.environ.get("CI") is None, reason="ci only")
        def test_gates_on_the_environment():
            assert registry.build() is not None


        @pytest.mark.skipif(not hasattr(registry, "build"), reason="not available")
        def test_gates_on_the_subject():
            assert registry.build() is not None


        def test_does_not_gate_at_all():
            assert registry.build() is not None
        """,
    )
    return root


class TestSelfSkipProvenance:
    """Machine, subject, or nothing - the three answers and only one defect."""

    def test_a_skipif_asking_hasattr_is_flagged_as_skip_on_drift(self, tmp_path):
        """The defining shape: rename the symbol and the test vanishes, not fails.

        MUTATION CAUGHT: removing `hasattr` from EXISTENCE_PROBES (or deleting
        the `_existence_probe` loop in `classify_site`). The shape that made 75
        tests silently disappear then reads as clean.
        """
        rows = _skip_rows(_self_skip_project(tmp_path))

        assert [(row["species"], row["nodeid"]) for row in rows] == [
            ("SKIP-ON-DRIFT", "tests/test_skips.py::test_gates_on_the_subject")
        ]
        assert "renaming that symbol makes this test vanish instead of fail" in rows[0]["reason"]

    def test_a_machine_probe_acquits_the_whole_site(self, tmp_path):
        """NEGATIVE CONTROL: a platform gate is correct code and must never flag.

        MUTATION CAUGHT: deleting the `if any(_is_machine_probe(...))` early
        return from `classify_site`. Both correct gates in this project flag,
        the score drops from 75 to 25, and the fix a branch would reach for is
        deleting its own portability.
        """
        assert [row["nodeid"] for row in _skip_rows(_self_skip_project(tmp_path))] == [
            "tests/test_skips.py::test_gates_on_the_subject"
        ]

    def test_a_machine_probe_acquits_even_when_a_hasattr_sits_beside_it(self, tmp_path):
        """THE ORDERING PIN: the acquittal has to be decided before the probe.

        `sys.platform == "win32" or not hasattr(mod, "X")` is a portability gate
        with an existence probe in it, and the probe loop would convict it on
        sight. MUTATION CAUGHT: moving the machine-probe early return below the
        `_existence_probe` loop in `classify_site` - the ordering is the whole
        acquittal, and a reader reviewing the diff sees two correct-looking
        blocks in either order.
        """
        _write(
            tmp_path,
            "tests/test_mixed.py",
            """
            import sys

            import pytest

            from mypkg import registry


            @pytest.mark.skipif(
                sys.platform == "win32" or not hasattr(registry, "build"), reason="posix and built"
            )
            def test_gates_on_both():
                assert registry.build() is not None
            """,
        )

        assert _skip_rows(tmp_path) == []

    def test_an_unconditional_skip_decorator_is_perma_skip(self, tmp_path):
        """A test that never runs proves nothing, whatever it asserts.

        MUTATION CAUGHT: deleting the `else: sites.append((None, ...))` branch of
        `_decorator_skip_sites`. `@pytest.mark.skip` is the cheapest thing in the
        catalog to leave behind and the easiest to stop measuring.
        """
        _write(
            tmp_path,
            "tests/test_perma.py",
            """
            import pytest


            @pytest.mark.skip(reason="flaky, will fix")
            def test_the_important_thing():
                assert everything_works()
            """,
        )

        assert _skip_species(tmp_path) == [("PERMA-SKIP", "tests/test_perma.py::test_the_important_thing")]

    def test_a_condition_reading_a_name_imported_from_the_subject_is_self_skip(self, tmp_path):
        """The same defect one step less obvious than `hasattr`.

        MUTATION CAUGHT: deleting the `_reads_subject` loop from
        `classify_site`. The condition asks nothing about the machine and
        everything about the code under test, and without this arm it reads as
        an ordinary conditional skip.
        """
        _write(
            tmp_path,
            "tests/test_reads.py",
            """
            import pytest

            from mypkg.storage import JSON_DIR


            def test_writes_the_row():
                if JSON_DIR is None:
                    pytest.skip("no dir")
                assert True
            """,
        )

        rows = _skip_rows(tmp_path)

        assert [row["species"] for row in rows] == ["SELF-SKIP"]
        assert "reads 'JSON_DIR' from the subject under test" in rows[0]["reason"]

    def test_a_body_skip_is_classified_by_the_if_that_guards_it(self, tmp_path):
        """A guarded `pytest.skip()` is conditional, not unconditional.

        MUTATION CAUGHT: making `_guarded_skip_calls` hand back
        `None` instead of `guards.get(id(node))`. Every guarded body skip in
        every project then reports PERMA-SKIP - a wrong species on a correct
        machine gate, which is worse than silence because a reader acts on it.
        """
        _write(
            tmp_path,
            "tests/test_guarded.py",
            """
            import shutil

            import pytest


            def test_reads_the_log():
                if shutil.which("git") is None:
                    pytest.skip("git not installed")
                assert True
            """,
        )

        assert _skip_rows(tmp_path) == []

    def test_a_bare_body_skip_with_no_guard_is_perma_skip(self, tmp_path):
        """The other side of the same contract: no guard really is unconditional.

        Paired with the guarded test above so the two together pin the guard
        lookup in both directions - one of them stays green under any mutation
        that only ever answers one way. MUTATION CAUGHT: making
        `_guarded_skip_calls` return the enclosing `if` test for every call
        regardless of `id`, which is what a careless "fix" to the pairing looks
        like.
        """
        _write(
            tmp_path,
            "tests/test_bare.py",
            """
            import pytest


            def test_not_written_yet():
                pytest.skip("todo")
                assert True
            """,
        )

        assert _skip_species(tmp_path) == [("PERMA-SKIP", "tests/test_bare.py::test_not_written_yet")]


class TestSelfSkipOneHop:
    """The provenance is often one function or one module-level name away."""

    def test_a_condition_calling_a_local_helper_is_followed_one_hop(self, tmp_path):
        """`if not _factory_still_there():` hides the probe one call away.

        MUTATION CAUGHT: deleting the `_called_helpers` loop from `_sources_for`.
        Calibration against a real corpus found the unhopped rule scoring exactly
        this shape as clean, which is why the hop exists at all.
        """
        _write(
            tmp_path,
            "tests/test_hop.py",
            """
            import pytest

            from mypkg import factory


            def _factory_still_raises():
                return hasattr(factory, "raise_on_unknown")


            @pytest.mark.skipif(not _factory_still_raises(), reason="behaviour changed")
            def test_rejects_unknown():
                assert True
            """,
        )

        rows = _skip_rows(tmp_path)

        assert [row["species"] for row in rows] == ["SKIP-ON-DRIFT"]
        assert "through the local helper _factory_still_raises()" in rows[0]["reason"]

    def test_a_module_level_flag_is_followed_to_the_statement_that_computes_it(self, tmp_path):
        """THE STATEMENT, NOT THE ASSIGNMENT - the reasoning is in the loop.

        MUTATION CAUGHT: binding to `node` instead of `statement` in
        `_module_bindings`. The provenance here lives in the `for`/`if` around
        the assignment, so a rule that recorded the bare `_HAS_IT = True` sees a
        constant and reports clean - which is what the real @daemon shape did.
        """
        _write(
            tmp_path,
            "tests/test_flag.py",
            """
            import pytest

            import mypkg

            _HAS_IT = False
            for _candidate in ("build", "make"):
                if hasattr(mypkg, _candidate):
                    _HAS_IT = True


            @pytest.mark.skipif(not _HAS_IT, reason="entry point renamed")
            def test_builds():
                assert True
            """,
        )

        rows = _skip_rows(tmp_path)

        assert [row["species"] for row in rows] == ["SKIP-ON-DRIFT"]
        assert "through the module-level name _HAS_IT" in rows[0]["reason"]

    def test_the_reported_provenance_names_the_source_that_carried_the_answer(self, tmp_path):
        """A finding proved by a binding must not be blamed on an unrelated helper.

        The condition here calls a helper AND reads a module-level flag; only the
        flag carries the `hasattr`. MUTATION CAUGHT: reverting `_sources_for` to
        the original rule's single remembered `hopped` name - the message then
        says "through the local helper _threshold()", sending a reader to a
        function that has nothing to do with the finding.
        """
        _write(
            tmp_path,
            "tests/test_blame.py",
            """
            import pytest

            import mypkg

            _HAS_IT = False
            for _candidate in ("build",):
                if hasattr(mypkg, _candidate):
                    _HAS_IT = True


            def _threshold():
                return 3


            @pytest.mark.skipif(_threshold() > 2 and not _HAS_IT, reason="entry point renamed")
            def test_builds():
                assert True
            """,
        )

        rows = _skip_rows(tmp_path)

        assert len(rows) == 1
        assert "through the module-level name _HAS_IT" in rows[0]["reason"]
        assert "_threshold" not in rows[0]["reason"]


class TestSelfSkipModuleScope:
    """The file-wide skip: the most expensive one, and it belongs to no function."""

    def test_a_module_level_skip_is_reported_against_the_file(self, tmp_path):
        """This is the shape that took 75 tests and it belongs to no test function.

        MUTATION CAUGHT: deleting the `_module_skip_sites` loop from
        `find_self_skips`. A rule that walked test functions only reported this
        exact file as clean, which is how the defect survived long enough to be
        measured.
        """
        _write(
            tmp_path,
            "tests/test_module_gate.py",
            """
            import pytest

            import mypkg.storage as storage

            if not hasattr(storage, "JSON_DIR"):
                pytest.skip("storage layout changed", allow_module_level=True)


            def test_writes_the_row():
                assert True
            """,
        )

        assert _skip_species(tmp_path) == [("SKIP-ON-DRIFT", "tests/test_module_gate.py::<module>")]

    def test_a_skip_inside_a_function_is_not_also_charged_to_the_module(self, tmp_path):
        """NEGATIVE CONTROL: one skip is one finding, in one scope.

        MUTATION CAUGHT: passing `set()` instead of `inside_functions` to
        `_guarded_skip_calls` from `_module_skip_sites`. Every body skip in the
        project is then reported twice - once against its own unit and once
        against the file - and the file scope is flagged for something that
        never removed it.
        """
        _write(
            tmp_path,
            "tests/test_body_only.py",
            """
            import pytest

            from mypkg.storage import JSON_DIR


            def test_writes_the_row():
                if JSON_DIR is None:
                    pytest.skip("no dir")
                assert True
            """,
        )

        assert _skip_species(tmp_path) == [("SELF-SKIP", "tests/test_body_only.py::test_writes_the_row")]


class TestSelfSkipScoring:
    """The denominator, the dedupe, and the number that comes out."""

    def test_the_denominator_counts_file_scopes_so_the_score_cannot_go_negative(self, tmp_path):
        """A module-level finding names a scope that is not one of the units.

        One file, one unit, and two findings - one on the unit and one on the
        file. MUTATION CAUGHT: `scope_count` returning `scanned.unit_count()`
        alone. The flagged count then exceeds the total and the score comes out
        at -100, and a score that can go negative is one nobody believes twice.
        """
        _write(
            tmp_path,
            "tests/test_both.py",
            """
            import pytest

            import mypkg.storage as storage

            if not hasattr(storage, "JSON_DIR"):
                pytest.skip("storage layout changed", allow_module_level=True)


            @pytest.mark.skip(reason="flaky")
            def test_writes_the_row():
                assert True
            """,
        )

        result = self_skip_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 2
        assert result["score"] == 0
        assert "2/2 test scopes" in result["checks"][0]["message"]

    def test_three_skips_in_one_unit_cost_that_unit_once(self, tmp_path):
        """One unit is one place a reader has to go and look at.

        MUTATION CAUGHT: scoring on `len(flagged)` instead of
        `len(flagged_nodeids(flagged))`. This project has three findings in one
        of its two units across one file - three scopes in total - so the score
        falls from 66 to 0 and would go negative on any project with more
        findings than scopes.
        """
        _write(
            tmp_path,
            "tests/test_many.py",
            """
            import pytest

            from mypkg import registry


            @pytest.mark.skipif(not hasattr(registry, "build"), reason="a")
            def test_three_ways():
                if not hasattr(registry, "make"):
                    pytest.skip("b")
                if not hasattr(registry, "form"):
                    pytest.skip("c")
                assert True


            def test_runs_always():
                assert True
            """,
        )

        result = self_skip_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 3
        assert result["score"] == 66

    def test_one_skip_decorator_produces_exactly_one_finding(self, tmp_path):
        """A `@skip()` decorator is seen twice and must be reported once.

        `@skip()` is a `Call` whose dotted name is exactly `skip`, so the
        decorator pass and the body walk - which descends into decorators - both
        find it. MUTATION CAUGHT: deleting the `_deduped` call from
        `unit_flags`, which doubles the violation list for this spelling and
        makes the report list the same line twice.
        """
        _write(
            tmp_path,
            "tests/test_alias.py",
            """
            from pytest import skip


            @skip()
            def test_not_written_yet():
                assert True
            """,
        )

        rows = _skip_rows(tmp_path)

        assert len(rows) == 1
        assert rows[0]["species"] == "PERMA-SKIP"

    def test_the_score_is_clean_scopes_over_total_scopes(self, tmp_path):
        """One flagged unit, four units and one file scope: four of five clean.

        MUTATION CAUGHT: inverting the score to `len(scopes) / total` - the
        project reads 20 instead of 80 and every board reads backwards.
        """
        result = self_skip_check.check_branch(str(_self_skip_project(tmp_path)))

        assert result["score"] == 80
        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "SELF_SKIP"
        assert result["checks"][0]["passed"] is False
        assert "tests/test_skips.py::test_gates_on_the_subject" in result["checks"][0]["message"]

    def test_a_project_with_no_tests_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        MUTATION CAUGHT: deleting the `total == 0` early return - the project
        scores a bare 0, which blames it for a fact about its layout and enters
        a branch average as evidence nobody collected.
        """
        _write(tmp_path, "tests/helpers.py", "def build_row():\n    return {}")

        result = self_skip_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin.

        MUTATION CAUGHT: moving the `unreadable` block below the `total == 0`
        early return. An unparseable file contributes no scope, so it cannot
        lower a score, and silence about it reads as a clean result - this is
        the one path where nothing else can catch it.
        """
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = self_skip_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])


# =============================================================================
# CAPTURE NEVER READ - THE OUTPUT THE TEST ASKED FOR AND NEVER LOOKED AT
# =============================================================================

from aipass.seedgo.apps.handlers.pytest_quality_standards import (  # noqa: E402
    capture_never_read_check,
    empty_parametrize_check,
)


def _capture_project(root: Path) -> Path:
    """A four-unit project where exactly one unit never looks at its capture.

    The three safe units are safe for three DIFFERENT reasons - the capture is
    read, the callee is not an output function, the receipt has company - so
    the project still scores 75 with any two of the three exemptions deleted
    only if all three survive together.
    """
    _write(
        root,
        "tests/test_scored_capture.py",
        """
        def test_reads_what_it_captured(capsys):
            main(["--help"])
            assert "usage" in capsys.readouterr().out

        def test_asserts_on_a_predicate_under_test():
            assert is_ssl_error(handshake_error) is True

        def test_receipt_with_company(store):
            assert show_status(store) is True
            store.write.assert_called_once_with(3)

        def test_captures_and_never_looks(capsys):
            main(["--help"])
        """,
    )
    return root


class TestCaptureNeverReadDetection:
    """CAPTURE-NEVER-READ: the fixture does nothing at all unless it is read."""

    def test_a_unit_requesting_capsys_that_never_reads_it_is_flagged(self, tmp_path):
        """THE EXACT STATIC TELL, with the coordinates a reader needs.

        `capsys` is not a setting, it is a buffer with a read method: a
        signature that names it and a body that never calls `readouterr()` is a
        leftover from a deleted assertion or a test never finished. Losing the
        signature read - the pack's corpus keeps the function node rather than a
        parameter list, so this rule extracts the parameters itself - turns the
        whole species invisible while every other test here stays green.
        """
        path = _write(
            tmp_path,
            "tests/test_help.py",
            """
            def test_help_flag_prints_usage(capsys):
                main(["--help"])
            """,
        )

        rows = capture_never_read_check.find_unread_captures(corpus.build(tmp_path))

        assert [row["nodeid"] for row in rows] == ["tests/test_help.py::test_help_flag_prints_usage"]
        assert rows[0]["species"] == "CAPTURE-NEVER-READ"
        assert rows[0]["line"] == _line_of(path, "def test_help_flag_prints_usage")
        assert "capsys" in rows[0]["reason"]

    def test_a_unit_that_reads_its_capture_is_never_flagged(self, tmp_path):
        """THE NEGATIVE CONTROL: requesting the fixture is not the offence.

        The offence is requesting it and not reading it. A rule that flagged
        every unit taking `capsys` would convict the correct shape - the one it
        is asking projects to write - and would be switched off inside a day.
        """
        _write(
            tmp_path,
            "tests/test_reads.py",
            """
            def test_help_flag_prints_usage(capsys):
                main(["--help"])
                assert "usage:" in capsys.readouterr().out
            """,
        )

        rows = capture_never_read_check.find_unread_captures(corpus.build(tmp_path))

        assert rows == []

    def test_all_four_capture_fixture_spellings_are_read(self, tmp_path):
        """pytest ships four capture fixtures, so a generic pack must know four.

        `capfd` and the two binary spellings capture exactly as `capsys` does
        and are read exactly the same way. Knowing only `capsys` reports a
        project that uses the file-descriptor spelling as having nothing to
        answer for, which is a silent hole rather than a visible miss.
        """
        _write(
            tmp_path,
            "tests/test_spellings.py",
            """
            def test_with_capfd(capfd):
                main([])

            def test_with_capsysbinary(capsysbinary):
                main([])

            def test_with_capfdbinary(capfdbinary):
                main([])
            """,
        )

        rows = capture_never_read_check.find_unread_captures(corpus.build(tmp_path))

        assert len(rows) == 3
        assert all(row["species"] == "CAPTURE-NEVER-READ" for row in rows)

    def test_a_capture_read_through_a_bound_method_is_not_flagged(self, tmp_path):
        """The read is not always a call site - the attribute arm earns its line.

        `read = capsys.readouterr` handed to a helper reads the capture through
        a name this reader cannot resolve, so the only visible evidence is the
        attribute reference itself. Reading only call nodes reports a unit that
        does read its capture as one that never does.
        """
        _write(
            tmp_path,
            "tests/test_bound.py",
            """
            def test_output_is_drained(capsys):
                read = capsys.readouterr
                drain(read)
            """,
        )

        rows = capture_never_read_check.find_unread_captures(corpus.build(tmp_path))

        assert rows == []

    def test_a_flag_on_a_class_method_carries_the_class_in_its_nodeid(self, tmp_path):
        """The coordinate has to survive class grouping, or a triager cannot open it.

        This branch groups nearly all of its tests in classes, and a nodeid
        assembled by hand as file::name looks right in every module-level test
        while pointing at a function that does not exist in a class-grouped
        suite. Only a method can tell the two spellings apart.
        """
        _write(
            tmp_path,
            "tests/test_methods.py",
            """
            class TestOutput:
                def test_prints_usage(self, capsys):
                    main(["--help"])
            """,
        )

        rows = capture_never_read_check.find_unread_captures(corpus.build(tmp_path))

        assert [row["nodeid"] for row in rows] == ["tests/test_methods.py::TestOutput::test_prints_usage"]
        assert "requests capsys" in rows[0]["reason"]


class TestCaptureNeverReadReceipts:
    """RECEIPT-ONLY: the return value said the call happened, and nothing else."""

    def test_a_sole_receipt_from_an_output_function_is_flagged_at_the_assert(self, tmp_path):
        """The reader must be sent to the ASSERTION, not to the def.

        `print_summary` could print an empty string forever and `is True` would
        stay green. The finding's line is the only coordinate that matters here:
        a unit can be forty lines long, and the def line makes a triager read
        all of them to find which assertion was meant.
        """
        path = _write(
            tmp_path,
            "tests/test_receipt.py",
            """
            def test_summary_is_printed(rows):
                prepare(rows)
                assert print_summary(rows) is True
            """,
        )

        rows = capture_never_read_check.find_unread_captures(corpus.build(tmp_path))

        assert [row["nodeid"] for row in rows] == ["tests/test_receipt.py::test_summary_is_printed"]
        assert rows[0]["species"] == "RECEIPT-ONLY"
        assert rows[0]["line"] == _line_of(path, "    assert print_summary(rows) is True")
        assert "print_summary" in rows[0]["reason"]

    def test_an_exit_code_receipt_is_the_same_species(self, tmp_path):
        """`== 0` is the other half of the shape and it is written just as often.

        A command that reports by printing returns 0 to say it ran. Matching
        only `is True` would leave every CLI-shaped receipt in the corpus
        unflagged while the rule claimed to cover the species.
        """
        _write(
            tmp_path,
            "tests/test_exit.py",
            """
            def test_report_runs():
                assert report_totals() == 0
            """,
        )

        rows = capture_never_read_check.find_unread_captures(corpus.build(tmp_path))

        assert [row["species"] for row in rows] == ["RECEIPT-ONLY"]

    def test_a_receipt_standing_beside_another_assertion_is_never_flagged(self, tmp_path):
        """SOLE IS THE SPECIES - the pairing rule is the rule's correctness.

        A unit that checks behaviour and also records that the call returned is
        correct and common. Flagging it convicts the right answer and teaches
        projects to delete the assertion that made it right, which is exactly
        the gaming the v4 pattern count produced.
        """
        _write(
            tmp_path,
            "tests/test_paired.py",
            """
            def test_summary_says_three_rows(capsys):
                assert print_summary(ROWS) is True
                assert "3 rows" in capsys.readouterr().out
            """,
        )

        rows = capture_never_read_check.find_unread_captures(corpus.build(tmp_path))

        assert rows == []

    def test_a_receipt_beside_a_mock_assertion_is_never_flagged(self, tmp_path):
        """The company does not have to be an `assert` statement.

        Nine live `assert result is True` lines were each paired with a
        `assert_called_once_with(...)`, and every one of them is correct: the
        mock call IS the behavioural oracle. Counting only assert statements
        would convict all nine.
        """
        _write(
            tmp_path,
            "tests/test_mocked.py",
            """
            def test_status_is_shown_once(store):
                assert show_status(store) is True
                store.write.assert_called_once_with(3)
            """,
        )

        rows = capture_never_read_check.find_unread_captures(corpus.build(tmp_path))

        assert rows == []

    def test_a_predicate_under_test_is_never_flagged(self, tmp_path):
        """When the boolean IS the behaviour, `is True` is the right assertion.

        `is_ssl_error(x) is True` is a predicate under test, not a router's
        receipt, and five live examples of it are correct. The callee's own name
        is the only thing separating the two families; dropping that condition
        flags every boolean assertion in any corpus.
        """
        _write(
            tmp_path,
            "tests/test_predicate.py",
            """
            def test_ssl_errors_are_recognised():
                assert is_ssl_error(SSLError("bad handshake")) is True
            """,
        )

        rows = capture_never_read_check.find_unread_captures(corpus.build(tmp_path))

        assert rows == []

    def test_an_assertion_that_is_not_a_comparison_is_read_without_crashing(self, tmp_path):
        """`assert print_summary(rows)` is a bare truthiness test, not a receipt.

        It is also the shape that reaches the receipt reader with no `.ops` and
        no `.comparators` to unpack. The guard that turns it away is invisible
        until it is gone, and then the rule does not merely misjudge the file -
        it raises AttributeError and takes the whole branch score with it.
        """
        _write(
            tmp_path,
            "tests/test_bare.py",
            """
            def test_summary_runs(rows):
                assert print_summary(rows)
            """,
        )

        rows = capture_never_read_check.find_unread_captures(corpus.build(tmp_path))

        assert rows == []


class TestCaptureNeverReadBranchCheck:
    """The scoring API for capture_never_read: what it reports and what it refuses."""

    def test_the_score_is_the_share_of_units_that_read_what_they_asked_for(self, tmp_path):
        """The number is units-that-are-FINE over total, not the inverse.

        An inverted or unscaled score still moves plausibly with the tree, so
        nothing about a live run would look wrong - a project would simply be
        told it is bad at exactly the rate it is good. Pinned on a project whose
        answer is exact: three of four units look at what they asked for.
        """
        result = capture_never_read_check.check_branch(str(_capture_project(tmp_path)))

        assert result["score"] == 75
        assert [row["nodeid"] for row in result["violations"]] == [
            "tests/test_scored_capture.py::test_captures_and_never_looks"
        ]

    def test_the_scorer_counts_a_unit_once_however_many_rows_name_it(self):
        """THE SCORE IS PER UNIT - a flagged total above the unit total goes negative.

        Two shapes can name the same unit, and the reader returns at most one
        row per unit today, so no project can exercise this from the outside.
        The helper is what keeps that a fact rather than a coincidence:
        `check_branch` divides by its answer, and counting rows instead lets one
        unit be subtracted twice and reports a score below zero that no caller
        checks for. Written against rows rather than a tree, because the state
        it protects against is not reachable through one.
        """
        rows = [
            {"nodeid": "tests/test_a.py::test_one", "species": "CAPTURE-NEVER-READ"},
            {"nodeid": "tests/test_a.py::test_one", "species": "RECEIPT-ONLY"},
            {"nodeid": "tests/test_a.py::test_two", "species": "RECEIPT-ONLY"},
        ]

        assert capture_never_read_check.flagged_nodeids(rows) == [
            "tests/test_a.py::test_one",
            "tests/test_a.py::test_two",
        ]

    def test_the_result_passes_and_stays_advisory_even_when_units_are_flagged(self, tmp_path):
        """SHADOW MODE GATES NOTHING - this rule scores before it is calibrated.

        Top-level `passed` must stay True while flags exist and `advisory` must
        stay True, so a caller can tell a report from a verdict. A rule that
        starts by failing boards it has never been measured against is how the
        v4 pattern count came to be gamed rather than fixed. The per-check line
        is where the failure shows.
        """
        result = capture_never_read_check.check_branch(str(_capture_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "CAPTURE_NEVER_READ"
        assert result["checks"][0]["passed"] is False
        assert "never look at the output they asked for" in result["checks"][0]["message"]

    def test_a_project_with_no_tests_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        A 0 blames a project for a fact about its layout; a 100 claims a
        measurement that never happened. Either number enters a branch average
        and moves a board on evidence nobody collected. Each check in this pack
        carries its own copy of the early return, so each one has to be pinned.
        """
        _write(tmp_path, "tests/helpers.py", "def build_row():\n    return {}")

        result = capture_never_read_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin.

        An unparseable file contributes no units, so it cannot lower a score,
        and silence about it reads as a clean result. This is the one path where
        nothing else can catch it: the message a caller sees must say the file
        was present and unreadable, not that the project has no tests.
        """
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = capture_never_read_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_file_is_named_beside_a_scored_result(self, tmp_path):
        """The unreadable line must also survive onto the path that DOES score.

        The early-return path carries it by construction; the scored path has to
        append it deliberately, and dropping that one line leaves a branch with
        a healthy number and no hint that a file was never read at all.
        """
        _capture_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = capture_never_read_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 75
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]


# =============================================================================
# EMPTY PARAMETRIZE - THE TABLE THAT VANISHES AT COLLECTION TIME
# =============================================================================


def _empty_parametrize_project(root: Path) -> Path:
    """A four-unit project where exactly one table is computed at collection time.

    The three safe tables are safe for three DIFFERENT reasons - a literal, a
    safe builtin over a literal count, and a module constant - so no single
    acquittal carries the whole 75. No assertion in the file measures a length,
    which is what keeps the file unguarded and the one real flag at its full
    VANISHING-TABLE species.
    """
    _write(
        root,
        "tests/test_scored_tables.py",
        """
        WORLDS = ["posix", "nt"]

        @pytest.mark.parametrize("value", [1, 2])
        def test_over_a_literal_table(value):
            assert shape(value) == 2

        @pytest.mark.parametrize("hour", range(24))
        def test_over_a_shorthand_table(hour):
            assert hour < 24

        @pytest.mark.parametrize("world", sorted(WORLDS))
        def test_over_a_module_constant(world):
            assert world

        @pytest.mark.parametrize("rule", load_rules())
        def test_over_a_computed_table(rule):
            assert rule.anchor
        """,
    )
    return root


class TestEmptyParametrizeDetection:
    """VANISHING-TABLE: an empty argvalues sequence is a SKIP that reads green."""

    def test_a_table_computed_by_a_call_is_flagged_at_the_decorator(self, tmp_path):
        """The subject is the DECORATOR, so that is the line a reader gets.

        `parametrize` takes argnames first and argvalues second; reading the
        wrong positional argument judges the string "item", which is a non-empty
        constant, and the rule then acquits every computed table in existence
        while still returning a plausible number.
        """
        path = _write(
            tmp_path,
            "tests/test_items.py",
            """
            @pytest.mark.parametrize("item", collect())
            def test_every_found_item_is_valid(item):
                assert item["ok"]
            """,
        )

        rows = empty_parametrize_check.find_vanishing_tables(corpus.build(tmp_path))

        assert [row["nodeid"] for row in rows] == ["tests/test_items.py::test_every_found_item_is_valid"]
        assert rows[0]["species"] == "VANISHING-TABLE"
        assert rows[0]["line"] == _line_of(path, '@pytest.mark.parametrize("item", collect())')
        assert rows[0]["argvalues"] == "collect()"

    def test_a_literal_table_with_elements_is_never_flagged(self, tmp_path):
        """THE ACQUITTAL THAT MATTERS MOST: most of every corpus is literals.

        312 parametrize sites were measured across one fleet and 217 were plain
        literals. A rule that flagged them would produce a wall of noise on the
        commonest correct shape in the ecosystem, and the real finding would be
        somewhere on page four.
        """
        _write(
            tmp_path,
            "tests/test_literals.py",
            """
            @pytest.mark.parametrize("value", [1, 2, 3])
            def test_over_a_list(value):
                assert shape(value)

            @pytest.mark.parametrize("name", ("a", "b"))
            def test_over_a_tuple(name):
                assert name

            @pytest.mark.parametrize("row", {"a": 1})
            def test_over_a_dict(row):
                assert row
            """,
        )

        rows = empty_parametrize_check.find_vanishing_tables(corpus.build(tmp_path))

        assert rows == []

    def test_a_literal_table_with_no_elements_is_flagged(self, tmp_path):
        """An EMPTY literal is the species written out in full, and it happens.

        A table whittled down to `[]` by deletions generates no cases at all:
        pytest skips the test and the summary still reads green. The literal arm
        must acquit on the elements being there, not on the node being a list -
        this test and the one above kill the two opposite mutations of that line.
        """
        _write(
            tmp_path,
            "tests/test_empty_literal.py",
            """
            @pytest.mark.parametrize("case", [])
            def test_every_case_is_handled(case):
                assert handle(case)
            """,
        )

        rows = empty_parametrize_check.find_vanishing_tables(corpus.build(tmp_path))

        assert [row["species"] for row in rows] == ["VANISHING-TABLE"]
        assert rows[0]["argvalues"] == "[]"

    def test_a_module_constant_bound_to_a_non_empty_literal_is_never_flagged(self, tmp_path):
        """A name bound to a literal at module level cannot vanish either.

        This is how a shared table is written once and used by three tests.
        Flagging it would push projects to inline the same literal three times
        to please a checker - the behaviour this pack exists to stop.
        """
        _write(
            tmp_path,
            "tests/test_constant.py",
            """
            WORLDS = ["posix", "nt"]

            @pytest.mark.parametrize("world", WORLDS)
            def test_over_a_constant(world):
                assert world
            """,
        )

        rows = empty_parametrize_check.find_vanishing_tables(corpus.build(tmp_path))

        assert rows == []

    def test_a_name_that_is_not_a_module_literal_is_still_flagged(self, tmp_path):
        """An IMPORTED name is a query with a shorter spelling.

        `from data import ROWS` says nothing about whether ROWS has anything in
        it - the binding is in another file this reader never opens. Treating
        every bare name as safe would acquit the whole species by spelling.
        """
        _write(
            tmp_path,
            "tests/test_imported.py",
            """
            from data import ROWS

            @pytest.mark.parametrize("row", ROWS)
            def test_over_an_imported_name(row):
                assert row
            """,
        )

        rows = empty_parametrize_check.find_vanishing_tables(corpus.build(tmp_path))

        assert [row["species"] for row in rows] == ["VANISHING-TABLE"]
        assert rows[0]["argvalues"] == "ROWS"

    def test_a_safe_builtin_over_a_literal_is_acquitted(self, tmp_path):
        """`range(24)` is a table written in shorthand, not a query.

        The safe builtins return something non-empty when handed something
        non-empty, so wrapping a literal in one changes nothing about whether
        the table can vanish. Losing that list flags the commonest shorthand in
        any parametrized suite.
        """
        _write(
            tmp_path,
            "tests/test_shorthand.py",
            """
            WORLDS = ["posix", "nt"]

            @pytest.mark.parametrize("hour", range(24))
            def test_over_a_range(hour):
                assert hour < 24

            @pytest.mark.parametrize("world", sorted(WORLDS))
            def test_over_a_sorted_constant(world):
                assert world
            """,
        )

        rows = empty_parametrize_check.find_vanishing_tables(corpus.build(tmp_path))

        assert rows == []

    def test_a_safe_builtin_wrapped_around_a_query_is_still_flagged(self, tmp_path):
        """ONE LAYER IS UNWRAPPED, AND ONLY ONE - the builtin is not a laundry.

        `sorted(collect())` is exactly as empty as `collect()` is. A safe
        builtin that acquitted whatever it wrapped would hand every project a
        one-word way to silence this rule without changing a thing about the
        table.
        """
        _write(
            tmp_path,
            "tests/test_wrapped.py",
            """
            @pytest.mark.parametrize("item", sorted(collect()))
            def test_over_a_sorted_query(item):
                assert item
            """,
        )

        rows = empty_parametrize_check.find_vanishing_tables(corpus.build(tmp_path))

        assert [row["species"] for row in rows] == ["VANISHING-TABLE"]
        assert rows[0]["argvalues"] == "sorted(collect())"

    def test_a_parametrize_written_with_keyword_arguments_is_passed_over(self, tmp_path):
        """The decorator does not have to carry two positional arguments.

        `parametrize(argnames=..., argvalues=...)` is legal and rare, and it is
        the shape that reaches the table reader with `args[1]` missing. Without
        the length guard the rule does not misjudge the file - it raises
        IndexError and takes the whole branch score down with it.
        """
        _write(
            tmp_path,
            "tests/test_keywords.py",
            """
            @pytest.mark.parametrize(argnames="case", argvalues=collect())
            def test_over_a_keyword_table(case):
                assert case
            """,
        )

        rows = empty_parametrize_check.find_vanishing_tables(corpus.build(tmp_path))

        assert rows == []


class TestEmptyParametrizeGuards:
    """The file-scoped acquittals, and the one that is a notch too weak."""

    def test_a_file_guarded_only_for_non_emptiness_gets_the_short_table_species(self, tmp_path):
        """SHORT-TABLE: `did it find anything` is not `did it find them all`.

        A collector that silently drops ONE entry leaves a non-empty table,
        every surviving case passes, and the run is one case lighter than it
        should be. An empty run at least looks odd; a short one looks normal.
        Reading the guard as a full acquittal loses that species entirely.
        """
        _write(
            tmp_path,
            "tests/test_guarded.py",
            """
            def test_rules_were_found():
                assert len(load_rules()) > 0

            @pytest.mark.parametrize("rule", load_rules())
            def test_each_rule_has_an_anchor(rule):
                assert rule.anchor
            """,
        )

        rows = empty_parametrize_check.find_vanishing_tables(corpus.build(tmp_path))

        assert [row["species"] for row in rows] == ["SHORT-TABLE"]
        assert "pin the expected COUNT" in rows[0]["reason"]

    def test_a_file_that_pins_an_expected_count_is_never_flagged(self, tmp_path):
        """THE FULL ACQUITTAL: this file already did the thing the rule asks for.

        A guard deriving the expected count and comparing it notices a table one
        entry short, which is everything this rule exists to want. Flagging it
        anyway is a false positive on the one file that got it right, and that
        is the failure that gets a standard switched off.
        """
        _write(
            tmp_path,
            "tests/test_counted.py",
            """
            def test_all_five_rules_load():
                assert len(load_rules()) == EXPECTED_RULE_COUNT

            @pytest.mark.parametrize("rule", load_rules())
            def test_each_rule_has_an_anchor(rule):
                assert rule.anchor
            """,
        )

        rows = empty_parametrize_check.find_vanishing_tables(corpus.build(tmp_path))

        assert rows == []

    def test_an_assertion_that_a_collection_is_empty_does_not_pin_a_count(self, tmp_path):
        """`len(x) == 0` is an emptiness claim, and it acquits nothing.

        It is written all over any corpus - `assert len(errors) == 0` - and it
        says the opposite of what a count guard says. Counting it as a pinned
        count hands a full acquittal to every file that asserts something is
        empty, which is most of them.
        """
        _write(
            tmp_path,
            "tests/test_zero.py",
            """
            def test_no_errors_are_reported():
                assert len(errors()) == 0

            @pytest.mark.parametrize("rule", load_rules())
            def test_each_rule_has_an_anchor(rule):
                assert rule.anchor
            """,
        )

        rows = empty_parametrize_check.find_vanishing_tables(corpus.build(tmp_path))

        assert [row["species"] for row in rows] == ["SHORT-TABLE"]


class TestEmptyParametrizeBranchCheck:
    """The scoring API for empty_parametrize: what it reports and what it refuses."""

    def test_the_score_is_the_share_of_units_with_no_vanishing_table(self, tmp_path):
        """The number is units-that-are-FINE over total, not the inverse.

        An inverted or unscaled score still moves plausibly with the tree, so
        nothing about a live run would look wrong - a project would simply be
        told it is bad at exactly the rate it is good. Pinned on a project whose
        answer is exact: three of four tables cannot vanish.
        """
        result = empty_parametrize_check.check_branch(str(_empty_parametrize_project(tmp_path)))

        assert result["score"] == 75
        assert [row["nodeid"] for row in result["violations"]] == [
            "tests/test_scored_tables.py::test_over_a_computed_table"
        ]

    def test_a_unit_stacking_two_tables_is_one_flagged_unit_not_two(self, tmp_path):
        """One unit, one unit of score - or the score can be driven below zero.

        Stacked `parametrize` decorators are the normal way to write a cross
        product, so a single unit really can carry two findings. Counting
        findings pushes the flagged total past the unit total and
        `(total - flagged) / total` reports a NEGATIVE score no caller checks.
        """
        _write(
            tmp_path,
            "tests/test_stacked.py",
            """
            @pytest.mark.parametrize("rule", load_rules())
            @pytest.mark.parametrize("mode", load_modes())
            def test_every_rule_in_every_mode(rule, mode):
                assert apply(rule, mode)
            """,
        )

        result = empty_parametrize_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 2
        assert result["score"] == 0

    def test_the_result_passes_and_stays_advisory_even_when_units_are_flagged(self, tmp_path):
        """SHADOW MODE GATES NOTHING - this rule scores before it is calibrated.

        Top-level `passed` must stay True while flags exist and `advisory` must
        stay True, so a caller can tell a report from a verdict. A rule that
        starts by failing boards it has never been measured against is how the
        v4 pattern count came to be gamed rather than fixed. The per-check line
        is where the failure shows.
        """
        result = empty_parametrize_check.check_branch(str(_empty_parametrize_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "EMPTY_PARAMETRIZE"
        assert result["checks"][0]["passed"] is False
        assert "computed at collection time" in result["checks"][0]["message"]

    def test_a_project_with_no_tests_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        A 0 blames a project for a fact about its layout; a 100 claims a
        measurement that never happened. Either number enters a branch average
        and moves a board on evidence nobody collected. Each check in this pack
        carries its own copy of the early return, so each one has to be pinned.
        """
        _write(tmp_path, "tests/helpers.py", "def build_row():\n    return {}")

        result = empty_parametrize_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin.

        An unparseable file contributes no units, so it cannot lower a score,
        and silence about it reads as a clean result. This is the one path where
        nothing else can catch it: the message a caller sees must say the file
        was present and unreadable, not that the project has no tests.
        """
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = empty_parametrize_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_file_is_named_beside_a_scored_result(self, tmp_path):
        """The unreadable line must also survive onto the path that DOES score.

        The early-return path carries it by construction; the scored path has to
        append it deliberately, and dropping that one line leaves a branch with
        a healthy number and no hint that a file was never read at all.
        """
        _empty_parametrize_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = empty_parametrize_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 75
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]


# =============================================================================
# POSIX LITERAL - A ROOTED PATH LITERAL PUT THROUGH A RESOLVER
# =============================================================================

from aipass.seedgo.apps.handlers.pytest_quality_standards import posix_literal_check  # noqa: E402

# NOTHING IN THIS SECTION ASKS THE MACHINE ANYTHING. The rule under test is about
# path separators, which makes it the one rule in the pack whose pins could most
# easily become a report on the host that ran them - an `os.sep` here, a
# `Path("/srv/data").resolve()` there, and the suite starts asserting what THIS
# interpreter does with a root instead of what the CHECKER says about a literal.
# Every project below is source TEXT written into tmp_path, and every assertion is
# about what the checker reported. No `os.name`, no `sys.platform`, no separator
# read from the running host, on any line.


def _posix_project(root: Path) -> Path:
    """A six-unit project where exactly two units resolve a rooted literal.

    The four clean units are clean for four DIFFERENT reasons - a resolver that
    is not pathlib's, a relative literal, a resolver name on something that is
    not a path module, and a derived path - so no single acquittal carries the
    whole 66.
    """
    _write(
        root,
        "tests/test_roots.py",
        """
        def test_a_constructed_root_is_resolved():
            assert Path("/srv/data").resolve() in roster

        def test_a_module_resolver_is_handed_a_root():
            assert os.path.realpath("/etc/hosts").startswith("/etc")

        def test_a_branch_name_resolver_shares_the_verb(registry):
            assert registry.resolve("/canary", {}) is None

        def test_a_relative_fragment_carries_no_claim():
            assert Path("logs").resolve().name == "logs"

        def test_a_helper_owns_its_own_abspath(helper):
            assert helper.abspath("/etc") is None

        def test_a_derived_path_was_never_written_down(tmp_path):
            assert tmp_path.resolve().is_dir()
        """,
    )
    return root


class TestPosixLiteralDetection:
    """POSIX-LITERAL: which literals reach a resolver, and which look like they do."""

    def test_a_path_constructor_over_a_rooted_literal_is_flagged(self, tmp_path):
        """The subject of the rule: a root written down and then resolved.

        `Path("/srv/data").resolve()` is `/srv/data` on POSIX and a drive-relative
        `D:\\tmp` under ntpath. Losing this arm leaves the rule with nothing but
        the os.path spelling, which the measurement found four times fewer.
        """
        _write(
            tmp_path,
            "tests/test_roster.py",
            """
            def test_the_root_is_in_the_roster():
                assert Path("/srv/data").resolve() in roster
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert [row["literal"] for row in result["violations"]] == ["/srv/data"]
        assert result["violations"][0]["species"] == "POSIX-LITERAL"
        assert result["violations"][0]["nodeid"] == "tests/test_roster.py::test_the_root_is_in_the_roster"

    def test_a_branch_name_resolver_sharing_the_verb_is_not_flagged(self, tmp_path):
        """THE ACQUITTAL THAT DECIDED THE SHAPE - keyed on receiver, not name.

        Six of the ten sites the name-keyed rule found fleet-wide were
        `target.resolve("@canary", {...})`: a branch-name lookup holding a rooted
        literal in an argument it never resolves. A rule that nominates those six
        forever is one a fleet learns to ignore inside a week.
        """
        _write(
            tmp_path,
            "tests/test_registry.py",
            """
            def test_the_branch_name_resolves(registry):
                assert registry.resolve("/canary", {"root": "/srv"}) is None
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_relative_literal_carries_no_platform_claim(self, tmp_path):
        """A relative fragment means the same thing in both dialects.

        `Path("logs")` is a name, not a root; resolving it is a claim about the
        working directory and about nothing else. Flagging it would put every
        `Path("x").resolve()` in the fleet into the report and bury the four
        sites that are actually about a root.
        """
        _write(
            tmp_path,
            "tests/test_relative.py",
            """
            def test_a_relative_fragment_resolves():
                assert Path("logs").resolve().name == "logs"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []

    def test_a_drive_rooted_literal_is_flagged_in_both_spellings(self, tmp_path):
        """The drive arm is the other half of the same defect, mirrored.

        A test that writes `C:\\tmp` has made the opposite platform assumption:
        posixpath reads it as a RELATIVE name, so the same line means something
        else on the other half of the matrix. Losing the drive arm leaves the
        rule catching only authors who guessed POSIX.
        """
        _write(
            tmp_path,
            "tests/test_drive.py",
            r"""
            def test_a_backslash_drive_resolves():
                assert PureWindowsPath(r"C:\tmp").resolve()

            def test_a_forward_slash_drive_resolves():
                assert PureWindowsPath("D:/tmp").resolve()
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert sorted(row["literal"] for row in result["violations"]) == ["C:\\tmp", "D:/tmp"]

    def test_a_resolver_function_over_a_rooted_literal_is_flagged(self, tmp_path):
        """The second arm: `os.path.realpath("/etc")` normalises against the host.

        Both spellings are named because they are one shape - `realpath` and
        `abspath` differ in symlink handling and not at all in the assumption
        they carry. Dropping either leaves half the arm live and the other half
        silently unmeasured.
        """
        _write(
            tmp_path,
            "tests/test_resolvers.py",
            """
            def test_realpath_normalises():
                assert os.path.realpath("/etc/hosts").startswith("/etc")

            def test_abspath_normalises():
                assert os.path.abspath("/etc") == "/etc"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert sorted(row["literal"] for row in result["violations"]) == ["/etc", "/etc/hosts"]

    def test_a_resolver_name_on_something_that_is_not_a_path_module_is_not_flagged(self, tmp_path):
        """`helper.abspath(...)` is somebody else's method that shares a name.

        The module gate is the same idea as the receiver gate one arm over: the
        rule is about pathlib and os.path, and a name is not evidence of either.
        Without the gate every object in the fleet with an `abspath` method
        becomes a finding.
        """
        _write(
            tmp_path,
            "tests/test_helper.py",
            """
            def test_the_helper_makes_it_absolute(helper):
                assert helper.abspath("/etc") is None
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []

    def test_a_constructor_called_with_no_arguments_is_read_without_crashing(self, tmp_path):
        """`Path().resolve()` is legal Python and the reader must survive it.

        A static reader that raises on a legal construct does not report a
        finding - it takes the whole branch's score down with it, and the caller
        sees a crash where a number should be. The argument guard is the only
        thing between this rule and an IndexError on a one-line test.
        """
        _write(
            tmp_path,
            "tests/test_cwd.py",
            """
            def test_the_working_directory_resolves():
                assert Path().resolve().is_dir()
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_the_line_reported_is_the_resolving_call_and_not_the_unit(self, tmp_path):
        """A reader gets sent to the line to look at, not to the def above it.

        A unit can be forty lines long and hold one rooted literal. Reporting the
        unit's own line makes every finding in a long test point at the same
        place, and the reader has to search for the thing the rule already found.
        """
        _write(
            tmp_path,
            "tests/test_deep.py",
            """
            def test_the_root_is_reached_late():
                roster = build_roster()
                extra = decorate(roster)
                assert Path("/srv/data").resolve() in extra
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert [row["line"] for row in result["violations"]] == [4]

    def test_a_rooted_literal_resolved_outside_a_test_unit_is_not_counted(self, tmp_path):
        """The rule walks TEST UNITS, and the denominator has to agree with it.

        A module-level constant and a fixture are not units, so a literal
        resolved in either has no unit to charge and no line a reader would be
        sent to. Widening the walk to the whole file finds them and then has to
        invent an owner - which is how a rule starts reporting findings that
        cannot be acted on.
        """
        _write(
            tmp_path,
            "tests/test_module_level.py",
            """
            ROOT = Path("/srv/data").resolve()

            @pytest.fixture
            def roster():
                return os.path.realpath("/etc")

            def test_the_roster_is_built(roster):
                assert roster
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100


class TestPosixLiteralScoring:
    """The number, and the one arithmetic mistake that would make it a lie."""

    def test_the_score_counts_units_and_not_findings(self, tmp_path):
        """A unit resolving three roots is ONE unit a reader has to go and read.

        Counting findings instead of units lets a single loop-heavy test drive a
        two-unit project to -50, and a score that can go negative is one nobody
        believes twice. The violations list still carries all three, because the
        reader wants every line.
        """
        _write(
            tmp_path,
            "tests/test_many.py",
            """
            def test_three_roots_in_one_unit():
                assert Path("/srv/data").resolve()
                assert Path("/var").resolve()
                assert os.path.abspath("/etc")

            def test_one_clean_unit():
                assert Path("logs").resolve()
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 3
        assert result["score"] == 50

    def test_a_project_with_four_kinds_of_clean_unit_scores_them_all_clean(self, tmp_path):
        """The constructed negative control: four acquittals, four reasons.

        Two units of the six are the real thing. The other four are clean for
        four different reasons, so a mutation that collapses any single
        acquittal - the receiver gate, the rooted test, the module gate - moves
        this number and cannot hide behind the other three.
        """
        _posix_project(tmp_path)

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["score"] == 66
        assert len(result["violations"]) == 2
        assert "2/6 test units put a rooted path literal through a resolver" in result["checks"][0]["message"]


class TestPosixLiteralBranchCheck:
    """The scoring-API contract, and the two paths where silence reads as clean."""

    def test_the_result_carries_the_scoring_api_shape(self, tmp_path):
        """The pack is advisory in shadow mode and every result has to say so.

        A caller reading `passed` gates on it. A standard that starts failing
        boards it has never been measured against is the mistake this pack was
        built to correct, so `passed` is True and `advisory` is True even on a
        project this rule has findings about.
        """
        _posix_project(tmp_path)

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "POSIX_LITERAL"
        assert result["checks"][0]["passed"] is False

    def test_a_project_with_no_test_files_is_not_applicable(self, tmp_path):
        """Zero tests measured is not zero quality found.

        A 0 blames a project for a fact about its layout and a 100 claims a
        measurement that never happened. Losing the early return does not return
        a wrong number either - it divides by zero and takes the caller with it.
        """
        _write(tmp_path, "src/thing.py", "def thing():\n    return 1")

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin.

        An unparseable file contributes no units, so it cannot lower a score, and
        silence about it reads as a clean result. This is the one path where
        nothing else can catch it: the message a caller sees must say the file
        was present and unreadable, not that the project has no tests.
        """
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_file_is_named_beside_a_scored_result(self, tmp_path):
        """The unreadable line must also survive onto the path that DOES score.

        The early-return path carries it by construction; the scored path has to
        append it deliberately, and dropping that one line leaves a branch with a
        healthy number and no hint that a file was never read at all.
        """
        _posix_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = posix_literal_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 66
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]


# =============================================================================
# COVERAGE SLOT - THE TEST THAT SAYS OUT LOUD WHY IT EXISTS
# =============================================================================

from aipass.seedgo.apps.handlers.pytest_quality_standards import coverage_slot_check  # noqa: E402


def _coverage_slot_project(root: Path) -> Path:
    """A five-unit project where exactly two units confess.

    The three clean units are clean for three DIFFERENT reasons - a docstring
    naming coverage as its SUBJECT, prose whose word boundaries defeat the
    phrase, and the phrase sitting in test DATA - so no single acquittal carries
    the whole 60.
    """
    _write(
        root,
        "tests/test_report.py",
        '''
        def test_the_writer_flushes():
            """Added for coverage."""
            assert writer.flush() is None

        def test_the_error_arm_runs():
            # for coverage of the error arm
            assert writer.fail() is None

        def test_every_file_appears_in_the_report():
            """The coverage report lists every file under src/."""
            assert set(report.files) == set(source_files())

        def test_the_recorded_value_predates_the_run():
            """Pins the value recorded before coverage runs, which the merge reuses."""
            assert recorded() == 3

        def test_the_note_is_rendered_verbatim():
            note = "for coverage"
            assert render(note) == "for coverage"
        ''',
    )
    return root


class TestCoverageSlotDetection:
    """COVERAGE-SLOT: a purposive phrase is a confession, a topic word is not."""

    def test_a_docstring_that_states_a_reason_is_flagged(self, tmp_path):
        """The subject of the rule: the test says what it is, in writing.

        Nobody writes "added for coverage" about a test they believe in. This is
        the phrase the whole rule is built around, and it is the one every other
        pattern is a variation of.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            '''
            def test_the_writer_flushes():
                """Added for coverage."""
                assert writer.flush() is None
            ''',
        )

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 1
        assert result["violations"][0]["where"] == "docstring"
        assert result["violations"][0]["species"] == "COVERAGE-SLOT"
        assert "exists for coverage" in result["violations"][0]["reason"]

    def test_a_docstring_that_names_coverage_as_its_subject_is_not_flagged(self, tmp_path):
        """THE NARROWING THAT DECIDED THE SHAPE - phrases, never bare words.

        The naive rule greps the word "coverage" anywhere. Run over a suite whose
        subject matter IS checkers and reports, it flags dozens of honest tests,
        and a rule that noisy is one people switch off inside a week. The
        patterns are purposive: they state a REASON, not a topic.
        """
        _write(
            tmp_path,
            "tests/test_report.py",
            '''
            def test_every_file_appears_in_the_report():
                """The coverage report lists every file under src/."""
                assert set(report.files) == set(source_files())
            ''',
        )

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_word_boundaries_keep_ordinary_prose_out(self, tmp_path):
        """ "coverage slots" as a subject is prose; "coverage slot" as a name is not.

        Every pattern is anchored on both ends, and the trailing anchor is the
        one that earns its keep here: a suite whose subject IS this rule writes
        "groups coverage slots by file" in a docstring, and unanchored the
        detector reads its own test suite as a room full of confessions.
        """
        _write(
            tmp_path,
            "tests/test_grouping.py",
            '''
            def test_the_report_groups_by_file():
                """The report groups coverage slots by file, which is what this pins."""
                assert group(report) == {"a.py": 2}
            ''',
        )

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert result["violations"] == []

    def test_a_confession_is_read_whatever_its_case(self, tmp_path):
        """A sentence that opens with the phrase is still the phrase.

        Docstrings are prose: the same confession appears as "For coverage.",
        "FOR COVERAGE" in a shouted comment, and mid-sentence. A case-sensitive
        rule catches the third spelling and misses the first two, which is the
        worst of both - it reports a number while missing the commonest form.
        """
        _write(
            tmp_path,
            "tests/test_shouted.py",
            '''
            def test_the_writer_flushes():
                """FOR COVERAGE."""
                assert writer.flush() is None
            ''',
        )

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 1

    def test_a_comment_inside_the_unit_is_reported_at_the_comments_own_line(self, tmp_path):
        """Comments are not in the AST, so the line has to be carried by hand.

        Reporting the unit's line instead sends a reader to the `def` of a
        forty-line test and lets them hunt for the sentence the rule already
        found. The comment arm exists because a confession is at least as likely
        to be written beside the code as above it.
        """
        _write(
            tmp_path,
            "tests/test_error_arm.py",
            """
            def test_the_error_arm_runs():
                writer.arm()
                # for coverage of the error arm
                assert writer.fail() is None
            """,
        )

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 1
        assert result["violations"][0]["where"] == "comment"
        assert result["violations"][0]["line"] == 3

    def test_a_hash_opening_a_line_inside_a_triple_quoted_block_is_not_a_comment(self, tmp_path):
        """THE DEFECT THE PORT FIXED: sample content read as the test's own prose.

        The original reader took every line whose content starts with `#` from
        the raw text. A fixture holding a sample config, an ini file, a snippet
        of another language - each carries `#` lines, and each could confess on
        behalf of a test that never said anything. The multi-line string spans
        come from the parsed tree so that content stays content.
        """
        _write(
            tmp_path,
            "tests/test_sample.py",
            '''
            def test_the_sample_config_parses():
                sample = """
            # for coverage
            key = 1
            """
                assert parse(sample) == {"key": 1}
            ''',
        )

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert result["violations"] == []

    def test_a_comment_between_two_tests_belongs_to_neither(self, tmp_path):
        """A module-level note is not a test's confession.

        Without the span filter every comment in a file is attributed to every
        unit in it, so one section header saying "the standard requires these"
        convicts the whole module - and the count it produces is the number of
        tests in the file rather than the number of confessions in it.
        """
        _write(
            tmp_path,
            "tests/test_sections.py",
            """
            def test_the_first_behaviour():
                assert first() == 1

            # the standard requires a section here

            def test_the_second_behaviour():
                assert second() == 2
            """,
        )

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert result["violations"] == []

    def test_the_phrase_sitting_in_test_data_is_not_a_confession(self, tmp_path):
        """A test whose DATA holds the phrase is testing a string.

        Scanning every string literal in a unit is the obvious widening and it is
        wrong: a renderer test that round-trips the sentence "for coverage" is
        doing its job. Only the prose a test writes ABOUT ITSELF - its docstring
        and its comments - is read.
        """
        _write(
            tmp_path,
            "tests/test_render.py",
            """
            def test_the_note_is_rendered_verbatim():
                note = "for coverage"
                assert render(note) == "for coverage"
            """,
        )

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert result["violations"] == []

    def test_a_class_name_that_looks_like_a_confession_does_not_flag_on_its_name(self, tmp_path):
        """THE ARM THAT WAS DELETED, held here as a decision rather than as code.

        The original ran the same phrases over the class name. Every pattern
        needs whitespace between its words and an identifier cannot contain any,
        so the arm never fired in any corpus. Reviving it by splitting CamelCase
        back into words was refused: a class ABOUT coverage slots would then read
        as a confession, and the precision that justifies phrase matching is the
        first thing that would die.
        """
        _write(
            tmp_path,
            "tests/test_named.py",
            """
            class TestCoverageSlotDetection:
                def test_the_detector_reads_a_docstring(self):
                    assert detect("Added for coverage.") == "docstring"
            """,
        )

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_unit_is_reported_once_however_many_phrases_it_matches(self, tmp_path):
        """Three confessions in one docstring is one confessing test.

        The docstring is read before the comments and the first match ends the
        unit. Collecting every match instead inflates the number the rule exists
        to report, and the loudest test in a suite - the one that apologises
        twice - would count for more than two silent ones.
        """
        _write(
            tmp_path,
            "tests/test_apologetic.py",
            '''
            def test_the_writer_flushes():
                """Added for coverage. A placeholder test, and the standard requires it."""
                # to satisfy the linter
                assert writer.flush() is None
            ''',
        )

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 1
        assert result["violations"][0]["where"] == "docstring"

    def test_a_file_that_cannot_be_read_a_second_time_yields_no_comments(self, tmp_path):
        """The corpus keeps the tree, not the source, so comments cost a re-read.

        A file that moved, was rewritten or turned unreadable between the parse
        and the read must produce fewer findings, never an exception: a static
        reader that raises does not report a finding, it takes the whole
        branch's score down with it.
        """
        parsed = corpus.TestFile(relpath="tests/test_gone.py", tree=ast.parse("x = 1"))

        assert coverage_slot_check.comments_in(tmp_path, parsed) == {}


class TestCoverageSlotScoring:
    """The number, and the arithmetic that would make it a lie."""

    def test_two_findings_naming_one_unit_cost_one_unit(self):
        """The dedupe that keeps a score from going negative.

        `unit_confession` returns at most one row per unit today, so this changes
        nothing today - it is here because the day someone reports every matching
        phrase instead of the first, the score is the thing that breaks, and a
        project can then be scored below zero on a suite it improved.
        """
        rows = [
            {"nodeid": "tests/test_a.py::test_one", "line": 2},
            {"nodeid": "tests/test_a.py::test_one", "line": 5},
            {"nodeid": "tests/test_a.py::test_two", "line": 9},
        ]

        assert coverage_slot_check.flagged_nodeids(rows) == [
            "tests/test_a.py::test_one",
            "tests/test_a.py::test_two",
        ]

    def test_a_project_with_three_kinds_of_clean_unit_scores_them_all_clean(self, tmp_path):
        """The constructed negative control: three acquittals, three reasons.

        Two units of the five confess. The other three are clean because the
        phrase is a subject, because a word boundary defeats it, and because it
        is data - so a mutation that collapses any single acquittal moves this
        number and cannot hide behind the other two.
        """
        _coverage_slot_project(tmp_path)

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert result["score"] == 60
        assert len(result["violations"]) == 2
        assert "2/5 test units say in writing that they exist for the checker" in result["checks"][0]["message"]


class TestCoverageSlotBranchCheck:
    """The scoring-API contract, and the two paths where silence reads as clean."""

    def test_the_result_carries_the_scoring_api_shape(self, tmp_path):
        """The pack is advisory in shadow mode and every result has to say so.

        A caller reading `passed` gates on it. A standard that starts failing
        boards it has never been measured against is the mistake this pack was
        built to correct, so `passed` is True and `advisory` is True even on a
        project this rule has findings about.
        """
        _coverage_slot_project(tmp_path)

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "COVERAGE_SLOT"
        assert result["checks"][0]["passed"] is False

    def test_a_project_with_no_test_files_is_not_applicable(self, tmp_path):
        """Zero tests measured is not zero quality found.

        A 0 blames a project for a fact about its layout and a 100 claims a
        measurement that never happened. Losing the early return does not return
        a wrong number either - it divides by zero and takes the caller with it.
        """
        _write(tmp_path, "src/thing.py", "def thing():\n    return 1")

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin.

        An unparseable file contributes no units, so it cannot lower a score, and
        silence about it reads as a clean result. This is the one path where
        nothing else can catch it: the message a caller sees must say the file
        was present and unreadable, not that the project has no tests.
        """
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_file_is_named_beside_a_scored_result(self, tmp_path):
        """The unreadable line must also survive onto the path that DOES score.

        The early-return path carries it by construction; the scored path has to
        append it deliberately, and dropping that one line leaves a branch with a
        healthy number and no hint that a file was never read at all.
        """
        _coverage_slot_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = coverage_slot_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 60
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]


# =============================================================================
# ENTRY POINT DIFF - THE VERB THE SUITE HAS NEVER ONCE SAID OUT LOUD
# =============================================================================

from aipass.seedgo.apps.handlers.pytest_quality_standards import (  # noqa: E402
    docstring_pin_check,
    entry_point_diff_check,
)


def _entry_point_project(root: Path) -> Path:
    """A project declaring five readable entry points, two of which are named.

    Both mentions live inside the SAME single test function on purpose, so that
    narrowing the corpus read to one node still finds them - which leaves the
    whole-file read to be pinned by its own test rather than by this fixture.
    """
    _write(
        root,
        "apps/cli.py",
        """
        COMMANDS = ("install-timer", "status", "purge-all")


        def handle(command):
            return command
        """,
    )
    _write(
        root,
        "apps/web.py",
        """
        @app.route("/admin/purge")
        def purge():
            return 204


        @app.get("/health")
        def health():
            return 200
        """,
    )
    _write(
        root,
        "tests/test_cli.py",
        """
        def test_the_cli_verb_and_the_admin_route_a_reader_expects():
            assert handle("status") == "status"
            assert client.post("/admin/purge").status == 403
        """,
    )
    return root


class TestEntryPointDiffReading:
    """What production declares and what the corpus names - every row rests here.

    Each test names the one-line mutation of `entry_point_diff_check` it was
    confirmed RED against, so a future reader can check the pin still bites
    rather than trusting that it once did.
    """

    def test_a_declared_verb_no_test_names_is_flagged_and_a_named_one_is_not(self, tmp_path):
        """The diff itself: the acquittal and the conviction in one project.

        Mutation caught: `if entry_point in mentioned: continue` inverted to
        `not in`. The negative controls are constructed, not borrowed - the two
        acquitted entry points are named by a literal in the corpus and by
        nothing else, so an inverted comparison cannot look plausible.
        """
        result = entry_point_diff_check.check_branch(str(_entry_point_project(tmp_path)))

        assert [row["entry_point"] for row in result["violations"]] == [
            "/health",
            "install-timer",
            "purge-all",
        ]

    def test_a_route_string_on_a_decorator_is_read_as_a_declaration(self, tmp_path):
        """A decorated route is a declaration, not just a constant tuple.

        Mutation caught: deleting the `elif isinstance(node, (ast.FunctionDef,
        ast.AsyncFunctionDef))` arm of `_declared_in`. Pinned on a project whose
        ONLY declaration is a route, so losing the arm turns a scored result
        into `not_applicable` instead of quietly shrinking a denominator.
        """
        _write(
            tmp_path,
            "apps/web.py",
            """
            @app.route("/admin/purge")
            def purge():
                return 204
            """,
        )
        _write(tmp_path, "tests/test_web.py", "def test_the_app_boots():\n    assert app is not None")

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert [row["entry_point"] for row in result["violations"]] == ["/admin/purge"]
        assert result["score"] == 0

    def test_a_decorator_that_is_not_a_call_is_stepped_over_rather_than_read(self, tmp_path):
        """A bare decorator has no `.args`, and reading one crashes the walk.

        Mutation caught: deleting `not isinstance(decorator, ast.Call) or` from
        the guard in `_from_route_decorators`, which raises AttributeError on
        the `@login_required` above the route. A static reader that dies on an
        ordinary decorator reports nothing about the whole project.
        """
        _write(
            tmp_path,
            "apps/web.py",
            """
            @login_required
            @app.route("/admin/purge")
            def purge():
                return 204
            """,
        )
        _write(tmp_path, "tests/test_web.py", "def test_the_app_boots():\n    assert app is not None")

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert [row["entry_point"] for row in result["violations"]] == ["/admin/purge"]

    def test_a_verb_named_only_outside_a_test_body_still_acquits(self, tmp_path):
        """The corpus is read WHOLE-FILE, because a suite names things at module level.

        A parametrize table, a fixture list or a shared constant is the suite
        naming a verb, and attributing the mention to one unit would manufacture
        findings out of file layout. Mutation caught: narrowing the read from
        the whole file to one node - `corpus.string_constants(parsed.tree)`
        becomes `corpus.string_constants(parsed.tree.body[-1])` - which loses
        every literal outside the last test function.
        """
        _write(tmp_path, "apps/cli.py", 'COMMANDS = ("purge-all",)')
        _write(
            tmp_path,
            "tests/test_cli.py",
            """
            VERBS_UNDER_TEST = ["purge-all"]


            def test_the_handler_echoes_an_unknown_command():
                assert handle("noop") == "noop"
            """,
        )

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_verb_buried_in_prose_does_not_acquit_it(self, tmp_path):
        """THE V4 DEFECT, REFUSED AT THE ONE LINE THAT COULD REINTRODUCE IT.

        The standard this pack replaces matched pattern substrings over raw
        source, so comments and docstrings counted and a file of strings with no
        code scored 94 percent. A substring comparison here would rebuild that
        exactly: any branch could clear this rule by writing its verbs into a
        comment. The verb below is named in a module docstring and in a comment
        and nowhere else, and it must still be flagged. Mutation caught:
        `if entry_point in mentioned:` becoming
        `if any(entry_point in text for text in mentioned):`.
        """
        _write(tmp_path, "apps/cli.py", 'COMMANDS = ("purge-all",)')
        _write(
            tmp_path,
            "tests/test_cli.py",
            """
            '''This suite covers purge-all end to end.'''


            def test_the_handler_echoes_an_unknown_command():
                # purge-all is exercised by the integration lane
                assert handle("noop") == "noop"
            """,
        )

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert [row["entry_point"] for row in result["violations"]] == ["purge-all"]

    def test_a_verb_shorter_than_the_minimum_is_not_measured_at_all(self, tmp_path):
        """A short verb is left OUT OF THE DENOMINATOR, not scored as clean.

        A literal match on a two-character string is not evidence of anything,
        so `go` is not measured rather than measured badly. Mutation caught:
        deleting the `if len(entry_point) >= MINIMUM_VERB_LENGTH` filter from
        `measurable_entry_points`, which both flags `go` and inflates the
        denominator to 2 - the message assertion catches the second half even
        if a future exemption ever acquits the first.
        """
        _write(tmp_path, "apps/cli.py", 'COMMANDS = ("go", "status")')
        _write(tmp_path, "tests/test_cli.py", 'def test_status_is_routed():\n    assert handle("status")')

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert "1/1 declared entry point(s)" in result["checks"][0]["message"]

    def test_one_verb_declared_in_two_modules_costs_the_project_once(self, tmp_path):
        """A re-export is one thing a test can name, not two - and the site is fixed.

        Mutation caught: `declared.setdefault(entry_point, site)` becomes
        `declared[entry_point] = site`, so the reader is sent to whichever
        module happened to be walked last. The row count catches a rewrite that
        stops deduping; the file name catches the last-wins flip, which is
        invisible to a count.
        """
        _write(tmp_path, "apps/a_first.py", 'COMMANDS = ("purge-all",)')
        _write(tmp_path, "apps/z_second.py", 'COMMANDS = ("purge-all",)')
        _write(tmp_path, "tests/test_x.py", "def test_the_app_boots():\n    assert app is not None")

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 1
        assert result["violations"][0]["file"] == "apps/a_first.py"

    def test_the_declaring_name_reported_is_the_constant_that_matched(self, tmp_path):
        """The reason shown must be the reason the rule actually used.

        Mutation caught: `_declaring_constant` returning the FIRST target
        instead of the matching one - the spelling the nominator this was
        ported from shipped, which told a reader `CLI = COMMANDS = (...)` was
        "declared in CLI", a name that is not in COMMAND_CONSTANTS and is not
        why the verb was found.
        """
        _write(tmp_path, "apps/cli.py", 'CLI = COMMANDS = ("purge-all",)')
        _write(tmp_path, "tests/test_x.py", "def test_the_app_boots():\n    assert app is not None")

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert result["violations"][0]["declared"] == "declared in COMMANDS"

    def test_a_declaration_with_no_literal_list_behind_it_declares_nothing(self, tmp_path):
        """A runtime-assembled verb list and a bare annotation are BLIND SPOTS.

        `COMMANDS = load_commands()` and `HANDLED_COMMANDS: tuple` are named as
        unreadable in the module docstring, and this pins that they are silent
        rather than fatal - the second is also the behaviour the nominator's
        dead `node.value is None` guard appeared to protect, kept after the
        guard was deleted for never firing. Mutation caught: deleting the
        `isinstance(node, (ast.Tuple, ast.List, ast.Set))` guard from
        `_constant_strings`, which raises AttributeError on both.
        """
        _write(
            tmp_path,
            "apps/cli.py",
            """
            COMMANDS = load_commands()
            HANDLED_COMMANDS: tuple
            VERBS = ("purge-all",)
            """,
        )
        _write(tmp_path, "tests/test_x.py", "def test_the_app_boots():\n    assert app is not None")

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert [row["entry_point"] for row in result["violations"]] == ["purge-all"]


class TestEntryPointDiffBranchCheck:
    """The scoring API for entry_point_diff: what it reports and what it refuses."""

    def test_the_score_is_the_share_of_declared_entry_points_the_suite_names(self, tmp_path):
        """The number is entry-points-that-are-NAMED over declared, not the inverse.

        An inverted score still moves plausibly with the tree, so nothing about
        a live run would look wrong - a project would simply be told it is bad
        at exactly the rate it is good. Mutation caught: the numerator becoming
        `len(flagged)`, which reports 60 where the honest answer is 40.
        """
        result = entry_point_diff_check.check_branch(str(_entry_point_project(tmp_path)))

        assert result["score"] == 40

    def test_a_project_declaring_nothing_readable_is_not_applicable_not_a_number(self, tmp_path):
        """NOTHING MEASURED IS NOT NOTHING FOUND - and the alternative is a crash.

        Most projects declare no entry point in a shape this rule can read, so
        this is the commonest path it takes on a live fleet. Mutation caught:
        deleting the `if not declared:` early return, which divides by zero on
        every such project.
        """
        _write(tmp_path, "apps/helper.py", "def helper():\n    return 1")
        _write(tmp_path, "tests/test_x.py", "def test_the_helper_returns_one():\n    assert helper() == 1")

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no entry point was declared" in result["checks"][0]["message"]
        assert "violations" not in result

    def test_the_production_files_it_could_not_read_are_named_beside_the_score(self, tmp_path):
        """THE MOST IMPORTANT LINE THIS CHECK EMITS, and the easiest to delete.

        The claim is "production declares X and no test names it", which is only
        honest beside a count of the production files that could not be read: an
        unreadable file declares nothing, so every entry point inside it is a
        finding that never happens, and the bias runs toward CLEAN. Mutation
        caught: deleting the `if production_limit:` block from `_limit_checks` -
        the score stays 40 and nothing else in the result changes, which is
        exactly why it needs its own pin.
        """
        _entry_point_project(tmp_path)
        _write(tmp_path, "apps/broken.py", "def handle(:\n    pass")

        result = entry_point_diff_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Production readable"]

        assert result["score"] == 40
        assert len(named) == 1
        assert "apps/broken.py" in named[0]["message"]
        assert "FEWER findings" in named[0]["message"]

    def test_the_production_limit_survives_onto_the_path_with_no_tests(self, tmp_path):
        """The unread count must not vanish on the path that scores nothing.

        A project with no tests still had production read, and the reader still
        needs to know the reading was incomplete. Mutation caught: dropping
        `+ unreadable` from the `total == 0` early return, which silently
        returns a bare not_applicable over a tree the rule could not finish.
        """
        _write(tmp_path, "apps/cli.py", 'COMMANDS = ("purge-all",)')
        _write(tmp_path, "apps/broken.py", "def handle(:\n    pass")

        result = entry_point_diff_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Production readable"]

        assert result["not_applicable"] is True
        assert len(named) == 1
        assert "apps/broken.py" in named[0]["message"]

    def test_the_result_passes_and_stays_advisory_even_when_entry_points_are_flagged(self, tmp_path):
        """SHADOW MODE GATES NOTHING - this rule scores before it is calibrated.

        Top-level `passed` must stay True while flags exist and `advisory` must
        stay True, so a caller can tell a report from a verdict. Mutation
        caught: `"passed": True` becoming `"passed": not flagged` in the scored
        return, which turns an uncalibrated advisory into a board failure.
        """
        result = entry_point_diff_check.check_branch(str(_entry_point_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "ENTRY_POINT_DIFF"
        assert result["checks"][0]["passed"] is False
        assert "named by no test" in result["checks"][0]["message"]

    def test_a_project_with_no_tests_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        A 0 blames a project for a fact about its layout; a 100 claims a
        measurement that never happened. Each check in this pack carries its own
        copy of the early return, so each one has to be pinned. Mutation caught:
        deleting `"not_applicable": True` from the `total == 0` return, which
        publishes a hard 0 into a branch average.
        """
        _write(tmp_path, "apps/cli.py", 'COMMANDS = ("purge-all",)')
        _write(tmp_path, "tests/helpers.py", "def build_row():\n    return {}")

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin.

        An unparseable file contributes no units, so it cannot lower a score,
        and silence about it reads as a clean result. Mutation caught: replacing
        the `measured` ternary with the bare "no test files found" string, which
        makes a project with one broken test file indistinguishable from a
        project that has never written a test.
        """
        _write(tmp_path, "apps/cli.py", 'COMMANDS = ("purge-all",)')
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = entry_point_diff_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_test_file_is_named_beside_a_scored_result(self, tmp_path):
        """The unreadable line must also survive onto the path that DOES score.

        The early-return path carries it by construction; the scored path has to
        append it deliberately. Mutation caught: deleting `checks.extend(
        unreadable)`, which leaves a branch with a healthy number and no hint
        that a file was never read at all.
        """
        _entry_point_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = entry_point_diff_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 40
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]


# =============================================================================
# DOCSTRING PIN - DOES THE DOCSTRING NAME ANYTHING THE TEST TOUCHES
# =============================================================================


def _docstring_pin_project(root: Path) -> Path:
    """Five units: three anchored, one with no docstring, one with prose only.

    THREE AND TWO, NOT TWO AND TWO. A project split evenly reports the same
    number whichever way round the score is computed, so an inverted numerator
    would sail through a fixture that looked perfectly reasonable. 3/5 and 2/5
    are different numbers and the pin can see the difference.

    The three anchored units anchor for DIFFERENT reasons - on a dotted call's
    tail, on a bare call, and on a call whose argument is a bare name - so the
    project still scores 60 with any one match direction intact, and the
    direction pins below have to do their own work.
    """
    _write(
        root,
        "tests/test_anchors.py",
        """
        def test_an_empty_document_is_rejected():
            '''parse refuses an empty document - a caller cannot tell empty from absent.'''
            with pytest.raises(ValueError):
                mod.parse("")


        def test_one_row_is_written_per_entry():
            '''build writes one row per entry.'''
            assert build(["a", "b"]) == 2


        def test_the_pending_rows_are_flushed_on_close():
            '''close flushes the rows still pending.'''
            assert close(handle) is True


        def test_the_thing_still_works():
            assert build([]) == 0


        def test_the_regression_that_keeps_coming_back():
            '''Pins the contract violated by the defect, a regression guarded here.'''
            assert build([]) == 0
        """,
    )
    return root


class TestDocstringPinAnchoring:
    """Whether a docstring names something the unit calls - and nothing else.

    Each test names the one-line mutation of `docstring_pin_check` it was
    confirmed RED against. The adversarial pin below is the reason this check
    exists at all: a prose matcher would pass the very docstring it flags.
    """

    def test_a_docstring_naming_a_called_symbol_anchors_and_prose_alone_does_not(self, tmp_path):
        """The whole rule in one project: two anchored, two flagged, two species.

        Mutation caught: `return token` in `anchoring_token` becoming
        `continue`, so nothing ever anchors and all four units are flagged. The
        acquitted units are constructed here rather than borrowed, so the pin
        fails in both directions.
        """
        rows = docstring_pin_check.find_unanchored_docstrings(corpus.build(_docstring_pin_project(tmp_path)))

        assert [(row["nodeid"].split("::")[-1], row["species"]) for row in rows] == [
            ("test_the_thing_still_works", "NO_DOCSTRING"),
            ("test_the_regression_that_keeps_coming_back", "UNANCHORED_DOCSTRING"),
        ]

    def test_a_docstring_stuffed_with_pin_vocabulary_naming_nothing_is_still_flagged(self, tmp_path):
        """THE ADVERSARIAL PIN - THIS IS WHY THE CHECK IS STRUCTURAL.

        The two units below carry the SAME prose. Every word a prose matcher
        could look for - pins, contract, defect, regression, invariant - is in
        both. The only difference is that the second names `mod.parse`, a symbol
        it really calls. The first must be flagged and the second must not, or
        the rule is a substring search and this pack has rebuilt the defect it
        exists to delete. Mutation caught: adding
        `or token.lower() in {"pins", "contract", "defect", "regression", "invariant"}`
        to the condition in `anchoring_token`, which acquits the first unit.
        """
        _write(
            tmp_path,
            "tests/test_prose.py",
            """
            def test_a_malformed_document_is_refused():
                '''Pins the contract that the defect violated. A regression that recurred
                twice, and the invariant this guards.'''
                assert mod.parse("<<<") is None


            def test_a_malformed_document_is_refused_with_the_symbol_named():
                '''mod.parse pins the contract that the defect violated. A regression that
                recurred twice, and the invariant this guards.'''
                assert mod.parse("<<<") is None
            """,
        )

        rows = docstring_pin_check.find_unanchored_docstrings(corpus.build(tmp_path))

        assert [row["nodeid"].split("::")[-1] for row in rows] == ["test_a_malformed_document_is_refused"]
        assert rows[0]["species"] == "UNANCHORED_DOCSTRING"

    def test_a_bare_name_in_the_docstring_anchors_a_dotted_call(self, tmp_path):
        """`parse` in prose is talking about `mod.parse` in the body.

        Requiring the author to reproduce the import path would score on typing
        rather than on knowledge. Mutation caught: deleting
        `names.add(name.rsplit(".", 1)[-1])` from `called_names`, which leaves
        only the fully dotted spelling in the set and flags a docstring that
        names the function correctly.
        """
        _write(
            tmp_path,
            "tests/test_offsets.py",
            """
            def test_the_offset_is_kept():
                '''parse keeps the offset of the assignment.'''
                assert mod.parse("a=1").offset == 3
            """,
        )

        assert docstring_pin_check.find_unanchored_docstrings(corpus.build(tmp_path)) == []

    def test_a_dotted_name_in_the_docstring_anchors_a_bare_call(self, tmp_path):
        """The match runs the other way too - `mod.parse` in prose, `parse` in the body.

        A docstring that spells out the import path is MORE precise, not less,
        and flagging it would push authors toward the shorter, vaguer spelling.
        Mutation caught: deleting `or token.rsplit(".", 1)[-1] in names` from
        `anchoring_token`.
        """
        _write(
            tmp_path,
            "tests/test_offsets.py",
            """
            def test_the_offset_is_kept():
                '''mod.parse keeps the offset of the assignment.'''
                assert parse("a=1").offset == 3
            """,
        )

        assert docstring_pin_check.find_unanchored_docstrings(corpus.build(tmp_path)) == []

    def test_a_missing_docstring_and_an_empty_one_are_different_species(self, tmp_path):
        """An author who wrote nothing and one who wrote something empty differ.

        `ast.get_docstring` returns None for the first and "" for the second,
        and both are falsy - so the distinction survives only because the test
        is `is None`. Mutation caught: `if text is None:` becoming
        `if not text:`, which collapses the empty docstring into NO_DOCSTRING
        and loses the species that exists for exactly that case.
        """
        _write(
            tmp_path,
            "tests/test_species.py",
            """
            def test_without_any_docstring():
                assert build([]) == 0


            def test_with_an_empty_docstring():
                ""
                assert build([]) == 0
            """,
        )

        rows = docstring_pin_check.find_unanchored_docstrings(corpus.build(tmp_path))

        assert [row["species"] for row in rows] == ["NO_DOCSTRING", "UNANCHORED_DOCSTRING"]

    def test_a_unit_that_calls_nothing_is_flagged_and_the_row_says_so(self, tmp_path):
        """THE KNOWN FALSE-FLAG FAMILY, pinned so it is a choice and not a surprise.

        A test whose subject is a constant makes no call, so it can never be
        anchored however well its docstring is written - and its docstring here
        names the very symbol it reads. Every such unit is flagged, and
        `call_count` is the field that lets a reader filter the family out in
        one pass. Mutation caught: `calls = sorted(...)` in `_finding` becoming
        `calls = []`, which reports every unit as call-less and makes the
        family indistinguishable from the real findings.
        """
        _write(
            tmp_path,
            "tests/test_limits.py",
            """
            def test_the_limit_is_ten():
                '''mod.LIMIT is ten.'''
                assert mod.LIMIT == 10


            def test_the_rows_are_written():
                '''Pins the defect the regression guarded.'''
                assert build(["a"]) == 1
            """,
        )

        rows = docstring_pin_check.find_unanchored_docstrings(corpus.build(tmp_path))

        assert [row["call_count"] for row in rows] == [0, 1]
        assert [row["calls"] for row in rows] == [[], ["build"]]


class TestDocstringPinBranchCheck:
    """The scoring API for docstring_pin: what it reports, and what it refuses to score."""

    def test_the_measured_score_is_the_share_of_units_whose_docstring_anchors(self, tmp_path):
        """The number is units-that-ARE-anchored over total, not the inverse.

        An inverted score still moves plausibly with the tree, so a project
        would simply be told it is bad at exactly the rate it is good. Mutation
        caught: the numerator becoming `len(flagged)`, which reports 40 where
        the honest answer is 60 - and the fixture is deliberately 3-and-2 rather
        than an even split, because an even split reports the same number both
        ways round and would let the mutation through.
        """
        result = docstring_pin_check.check_branch(str(_docstring_pin_project(tmp_path)))

        assert result["measured_score"] == 60
        assert [row["nodeid"] for row in result["violations"]] == [
            "tests/test_anchors.py::test_the_thing_still_works",
            "tests/test_anchors.py::test_the_regression_that_keeps_coming_back",
        ]

    def test_the_reported_score_is_100_while_the_rule_reports_rather_than_scores(self, tmp_path):
        """SCORED = False SHIPS THE RULING AS ACCEPTED: structural, unscored.

        The findings stay complete and the reported score is 100, so the fleet
        can be measured before anything is gated on the measurement. Mutation
        caught: `"score": measured_score if SCORED else 100` becoming
        `"score": measured_score`, which starts gating a rule whose named
        false-flag family has never been measured against a real branch.
        """
        result = docstring_pin_check.check_branch(str(_docstring_pin_project(tmp_path)))

        assert result["score"] == 100
        assert result["scored"] is False
        assert len(result["violations"]) == 2

    def test_the_measured_number_is_still_published_while_the_rule_is_unscored(self, tmp_path):
        """A fallback that discards its own measurement reports nothing at all.

        Reporting 100 and dropping the measured number makes an unscored rule
        indistinguishable from a rule that found nothing - and the whole point
        of the shadow cycle is seeing what the rule WOULD have said. Mutation
        caught: deleting the `if not SCORED:` check-line block, which leaves the
        100 unexplained beside a violation list nobody can weigh.
        """
        result = docstring_pin_check.check_branch(str(_docstring_pin_project(tmp_path)))
        named = [check for check in result["checks"] if check["name"] == "Docstring anchor scoring"]

        assert len(named) == 1
        assert "REPORTING, NOT SCORING" in named[0]["message"]
        assert "measured score is 60" in named[0]["message"]

    def test_turning_scoring_on_reports_the_measured_number_and_drops_the_report_line(self, tmp_path):
        """The constant is read at call time, so the fallback can actually be lifted.

        A `SCORED` baked in at import - or read once into a default argument -
        would leave the ruling's escape hatch welded shut, and the day the rule
        is calibrated nobody would find out why flipping it changed nothing.
        Mutation caught: `if not SCORED:` becoming `if True:`, which leaves the
        report line attached to a rule that is now scoring.
        """
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(docstring_pin_check, "SCORED", True)
        try:
            result = docstring_pin_check.check_branch(str(_docstring_pin_project(tmp_path)))
        finally:
            monkeypatch.undo()

        assert result["score"] == 60
        assert result["scored"] is True
        assert [check["name"] for check in result["checks"]] == ["Docstring anchor"]

    def test_the_result_passes_and_stays_advisory_even_when_units_are_flagged(self, tmp_path):
        """SHADOW MODE GATES NOTHING - this rule reports before it is calibrated.

        Top-level `passed` must stay True while flags exist and `advisory` must
        stay True, so a caller can tell a report from a verdict. Mutation
        caught: `"passed": True` becoming `"passed": not flagged` in the scored
        return, which turns an explicitly unscored rule into a board failure.
        """
        result = docstring_pin_check.check_branch(str(_docstring_pin_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "DOCSTRING_PIN"
        assert result["checks"][0]["passed"] is False
        assert "names nothing they call" in result["checks"][0]["message"]

    def test_a_project_with_no_tests_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        A 0 blames a project for a fact about its layout; a 100 claims a
        measurement that never happened. Each check in this pack carries its own
        copy of the early return, so each one has to be pinned. Mutation caught:
        deleting `"not_applicable": True` from the `total == 0` return, which
        publishes a hard 0 into a branch average.
        """
        _write(tmp_path, "tests/helpers.py", "def build_row():\n    return {}")

        result = docstring_pin_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin.

        An unparseable file contributes no units, so it cannot lower a score,
        and silence about it reads as a clean result. Mutation caught: replacing
        the `measured` ternary with the bare "no test files found" string, which
        makes a project with one broken test file indistinguishable from a
        project that has never written a test.
        """
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = docstring_pin_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_test_file_is_named_beside_a_scored_result(self, tmp_path):
        """The unreadable line must also survive onto the path that DOES score.

        The early-return path carries it by construction; the scored path has to
        append it deliberately. Mutation caught: deleting `checks.extend(
        unreadable)`, which leaves a branch with a healthy number and no hint
        that a file was never read at all.
        """
        _docstring_pin_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = docstring_pin_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["measured_score"] == 60
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]


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
