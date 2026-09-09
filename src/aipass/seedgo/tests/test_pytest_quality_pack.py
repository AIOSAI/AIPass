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


class TestCaptureNeverReadDelegation:
    """The one level this rule follows: a helper in the same file.

    PACK DEFECT, reported by @devpulse 2026-09-07 and confirmed by measurement:
    a unit that hands `capsys` to a same-module helper which reads it HAD read
    its capture, and the rule said the opposite. Measured over 22 branches
    before the change: 132 rows fleet-wide, 90 acquitted, three branches move.
    """

    def test_a_same_file_helper_that_reads_the_fixture_acquits_its_caller(self, tmp_path):
        """The reported shape, exactly as @devpulse wrote it down.

        `_output(capsys)` reads `readouterr()` and hands back what was printed;
        the unit asserts on the return. Nothing about that unit is unfinished,
        which is the only thing CAPTURE-NEVER-READ claims.
        """
        _write(
            tmp_path,
            "tests/test_compass.py",
            """
            def _output(capsys):
                captured = capsys.readouterr()
                return captured.out + captured.err

            def test_help_flag_shows_usage(capsys):
                main(["--help"])
                assert "USAGE" in _output(capsys)
            """,
        )

        rows = capture_never_read_check.find_unread_captures(corpus.build(tmp_path))

        assert rows == []

    def test_a_same_file_helper_that_does_not_read_the_fixture_still_flags(self, tmp_path):
        """Negative control, and the reason the acquittal is not a blanket pass.

        `_noop` takes the fixture and never reads it. If the rule acquitted on
        the CALL rather than on what the helper does, every unit that passes
        capsys anywhere would be excused and the rule would find nothing at all.
        """
        _write(
            tmp_path,
            "tests/test_quiet.py",
            """
            def _noop(capsys):
                return None

            def test_help_flag_shows_usage(capsys):
                main(["--help"])
                _noop(capsys)
            """,
        )

        rows = capture_never_read_check.find_unread_captures(corpus.build(tmp_path))

        assert [row["nodeid"] for row in rows] == ["tests/test_quiet.py::test_help_flag_shows_usage"]

    def test_the_fixture_has_to_reach_the_parameter_the_helper_actually_reads(self, tmp_path):
        """Position is the claim. `_pick(marker, capsys)` reads its FIRST argument.

        A mapping keyed by helper name alone would acquit any call to a helper
        that reads something, whatever was handed to it. Here the helper reads
        parameter 0 and the unit passes the fixture at position 1, so the
        capture is still never read and the row must stand.
        """
        _write(
            tmp_path,
            "tests/test_positions.py",
            """
            def _pick(first, second):
                return first.readouterr().out

            def test_help_flag_shows_usage(capsys):
                main(["--help"])
                _pick(marker, capsys)
            """,
        )

        rows = capture_never_read_check.find_unread_captures(corpus.build(tmp_path))

        assert [row["nodeid"] for row in rows] == ["tests/test_positions.py::test_help_flag_shows_usage"]

    def test_a_helper_that_forwards_to_a_second_helper_is_followed_too(self, tmp_path):
        """@memory's spelling: `_payload` never reads, `_raw_stdout` does.

        Found by measuring after the one-hop version landed - it left 34 of
        @memory's units flagged, and every one of them looks at its output two
        calls down. A rule that stops at one hop is not answering "did somebody
        look", it is answering "did somebody look immediately", which is a
        different and less useful question.

        The fixture also sits at position 1 here, behind `verbs`, so the closure
        has to carry the POSITION through the forward and not just the name.
        """
        _write(
            tmp_path,
            "tests/test_chained.py",
            """
            def _raw_stdout(verbs, capsys, *args):
                capsys.readouterr()
                _run(verbs, *args)
                return capsys.readouterr().out

            def _payload(verbs, capsys, *args):
                return json.loads(_raw_stdout(verbs, capsys, *args))

            def test_whole_stdout_parses(verbs, capsys):
                assert isinstance(_payload(verbs, capsys, "get"), dict)
            """,
        )

        rows = capture_never_read_check.find_unread_captures(corpus.build(tmp_path))

        assert rows == []

    def test_two_helpers_that_call_each_other_and_read_nothing_still_flag(self, tmp_path):
        """The closure terminates, and terminating is not the same as acquitting.

        Mutual recursion is the input that turns a naive "follow the call" into
        a hang. Neither helper here ever reads the fixture, so the fixed point
        is reached with an empty reader set and the caller keeps its finding -
        the loop stopping is not by itself evidence that anyone looked.
        """
        _write(
            tmp_path,
            "tests/test_mutual.py",
            """
            def _ping(capsys):
                return _pong(capsys)

            def _pong(capsys):
                return _ping(capsys)

            def test_help_flag_shows_usage(capsys):
                main(["--help"])
                _ping(capsys)
            """,
        )

        rows = capture_never_read_check.find_unread_captures(corpus.build(tmp_path))

        assert [row["nodeid"] for row in rows] == ["tests/test_mutual.py::test_help_flag_shows_usage"]

    def test_a_reader_defined_in_another_file_does_not_acquit(self, tmp_path):
        """The published limit, pinned so it stays a limit and not a regression.

        Following an import means executing the import graph. The helper here is
        spelled identically to the one two tests up and lives one file over; the
        rule must not see it, and the honest consequence is a finding a human
        overrules rather than a resolution this reader cannot make.
        """
        _write(
            tmp_path,
            "tests/helpers_screen.py",
            """
            def _output(capsys):
                return capsys.readouterr().out
            """,
        )
        _write(
            tmp_path,
            "tests/test_imported.py",
            """
            from tests.helpers_screen import _output

            def test_help_flag_shows_usage(capsys):
                main(["--help"])
                assert "USAGE" in _output(capsys)
            """,
        )

        rows = capture_never_read_check.find_unread_captures(corpus.build(tmp_path))

        assert [row["nodeid"] for row in rows] == ["tests/test_imported.py::test_help_flag_shows_usage"]

    def test_unit_flags_without_a_reader_map_can_only_flag_more_never_fewer(self, tmp_path):
        """The default is the safe direction, and a caller cannot acquit by accident.

        `unit_flags` is public and takes a unit; a caller holding no tree passes
        no reader map. That caller must get the pre-2026-09-07 answer - a
        finding - rather than a silent acquittal it never asked for.
        """
        _write(
            tmp_path,
            "tests/test_default.py",
            """
            def _output(capsys):
                return capsys.readouterr().out

            def test_help_flag_shows_usage(capsys):
                assert "USAGE" in _output(capsys)
            """,
        )
        scanned = corpus.build(tmp_path)
        unit = next(scanned.units())

        assert [row["species"] for row in capture_never_read_check.unit_flags(unit)] == ["CAPTURE-NEVER-READ"]
        readers = capture_never_read_check.capture_readers(scanned.files[0].tree)
        assert capture_never_read_check.unit_flags(unit, readers) == []


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

    def test_a_module_that_names_its_dialect_out_loud_is_not_flagged(self, tmp_path):
        """`ntpath.abspath("/x")` is the CURE this rule sends people to.

        PACK DEFECT, found by the rule convicting its own hazard demonstration
        (seedgo, 2026-09-07). The premise in this checker's own docstring is that
        `os.path` MEANS a different module per host, so the line means two
        things. `ntpath` and `posixpath` are the opposite: the module names the
        dialect, the answer is fixed on every leg of the matrix, and a nominated
        site gets rewritten INTO this shape. Convicting it convicted the fix.

        Measured across 22 branches before the change: 5 rows fleet-wide, this
        acquits 2, and no other branch moves.
        """
        _write(
            tmp_path,
            "tests/test_dialects.py",
            """
            def test_the_two_dialects_disagree():
                assert ntpath.abspath("D:/x/../tmp") == "D:\\tmp"
                assert posixpath.realpath("/x/../tmp") == "/tmp"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_the_dialect_acquittal_does_not_reach_os_path(self, tmp_path):
        """Negative control, and the reason the acquittal above is not a hole.

        A gate spelled "any module ending in path" would take `os.path` with it
        and delete the whole second arm of the rule. Both spellings sit in one
        file so the two readings come from the same corpus in one pass: exactly
        the os.path line is convicted, and it is named.
        """
        _write(
            tmp_path,
            "tests/test_both.py",
            """
            def test_the_alias_is_still_read():
                assert os.path.abspath("/etc") == "/etc"

            def test_the_dialect_is_not():
                assert posixpath.abspath("/etc") == "/etc"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert [row["nodeid"] for row in result["violations"]] == ["tests/test_both.py::test_the_alias_is_still_read"]

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


class TestPosixLiteralRenderedAndReturnedPaths:
    """Arms 3 and 4 - the REVERSE shape, and the split that keeps arm 3 honest.

    Arms 1 and 2 are about a rooted literal put through a resolver. These two are
    the mirror image: a Path rendered to TEXT and compared with a literal that
    spells the separator forward. Four rows went red on the first Linux/Windows
    matrix run and not one of them held a rooted literal or a resolver.

    THE SPLIT IS THE HEART OF ARM 3, and it is measured rather than argued. The
    first fleet run of the undivided arm returned 64 rows, 27 of them on this
    branch, and most of this branch's are correct portable code: `corpus._relpath`
    (corpus.py:202) returns `path.relative_to(root).as_posix()`, so every test
    asserting on a relpath it produced is reading a string that is posix on every
    host, forever, on purpose. That fact is off-screen from any AST reader of the
    TEST - which is why a value the code under test RETURNED only nominates, while
    a rendering the test wrote down on the line the reader is looking at scores.

    Each test names the one-line mutation of `posix_literal_check` it was confirmed
    RED against.
    """

    def test_a_path_the_test_rendered_itself_is_scored(self, tmp_path):
        """RENDERED-PATH: the TEST chose the dialect, on the line under the reader's eye.

        `str()` of a Path spells the separator the HOST's way - `pkg/gamma.py`
        here, `pkg\\gamma.py` there - so nothing off-screen can make this literal
        right and the row moves the number. This half found ZERO rows fleet-wide,
        which the dossier says out loud rather than hiding: nobody here writes
        `str(p) == "a/b.py"` in a test yet. It is kept because it is the shape the
        cure turns INTO if the cure is done wrong. Mutation caught:
        `RENDER_BUILTINS: frozenset = frozenset({"str", "repr", "format",
        "ascii"})` becoming the same set without `"str"`.
        """
        _write(
            tmp_path,
            "tests/test_scanner.py",
            """
            def test_the_relative_path_is_reported(tmp_path):
                entry = collect(tmp_path)
                assert str(entry.path) == "pkg/gamma.py"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))
        row = result["violations"][0]

        assert [r["species"] for r in result["violations"]] == ["RENDERED-PATH"]
        assert result["nominations"] == []
        assert result["score"] == 0
        assert row["literal"] == "pkg/gamma.py"
        assert row["rendering"] == "str()"
        assert "only right on the leg of the matrix it was written on" in row["reason"]

    def test_an_f_string_is_the_same_rendering_spelled_shorter(self, tmp_path):
        """An f-string calls `__format__`, which for a Path is the host's dialect.

        `f"{p}"` and `str(p)` produce the same string and the same defect, and a
        rule that read only the builtin would teach the fleet to spell the bug in
        the shorter form. The species has to stay RENDERED-PATH - the test still
        wrote the rendering down. Mutation caught: `return "f-string" if
        pathish_expression(node) else ""` in `_written_rendering` becoming
        `return ""`, which drops the f-string half of the scoring arm and leaves
        `str()` looking healthy.
        """
        _write(
            tmp_path,
            "tests/test_scanner.py",
            """
            def test_the_relative_path_is_reported(tmp_path):
                entry = collect(tmp_path)
                assert f"{entry.path}" == "pkg/gamma.py"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["violations"]] == ["RENDERED-PATH"]
        assert result["violations"][0]["rendering"] == "f-string"
        assert result["score"] == 0

    def test_a_path_searched_for_inside_a_rendered_call_record_is_scored(self, tmp_path):
        """REPR-HAYSTACK: the haystack is not the argument, it is a rendering of it.

        `str(mock.call_args)` runs every argument through `repr()`, and `repr()`
        of a Windows path DOUBLES the separator - so even a needle built
        correctly, `str(logs_dir / "app.log")`, cannot be found in there. Both
        scored rows the first fleet run produced were this species. Mutation
        caught: `MOCK_CALL_RECORDS: frozenset = frozenset({"call_args",
        "call_args_list", "mock_calls", "await_args", "await_args_list",
        "method_calls"})` becoming the same set without `"call_args"`.
        """
        _write(
            tmp_path,
            "tests/test_log_watcher.py",
            """
            def test_the_log_path_is_warned_about(logs_dir):
                with patch("apps.watcher.logger.warning") as warned:
                    run_it()
                assert str(logs_dir / "app.log") in str(warned.call_args)
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))
        row = result["violations"][0]

        assert [r["species"] for r in result["violations"]] == ["REPR-HAYSTACK"]
        assert result["score"] == 0
        assert row["record"] == "warned.call_args"
        assert "DOUBLES a backslash separator" in row["reason"]
        assert "warned.call_args.args[n]" in row["reason"]

    def test_a_rendered_record_is_followed_one_hop_through_a_local_name(self, tmp_path):
        """ONE HOP, FIRST BINDING ONLY - and it is the shape every fleet site uses.

        `reported = str(warned.call_args)` on one line and the assertion on the
        next is how all four of the CI rows are written; a reader that only saw
        the rendering inside the comparison would call every one of them clean.
        Following further would mean tracking flow, and a name rebound later
        keeps its first reading, which is the direction that under-reports.
        Mutation caught: `if isinstance(node, ast.Name) and node.id in bindings:
        return _renders_a_call_record(bindings[node.id])` in `_rendered_record`
        becoming `return ""`.
        """
        _write(
            tmp_path,
            "tests/test_log_watcher.py",
            """
            def test_the_log_path_is_warned_about(logs_dir):
                with patch("apps.watcher.logger.warning") as warned:
                    run_it()
                reported = str(warned.call_args)
                assert str(logs_dir / "app.log") in reported
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["violations"]] == ["REPR-HAYSTACK"]
        assert result["violations"][0]["record"] == "warned.call_args"

    def test_a_value_the_code_under_test_returned_nominates_and_moves_no_number(self, tmp_path):
        """RETURNED-PATH: reported in its own line, `passed: True`, never scored.

        The comparison came BACK from the code under test - a dict subscript -
        and whether the producer normalised the separator is off-screen. This is
        the SAME AST SHAPE as the rows that broke CI; what separates them lives
        in production, which this pack does not read for this rule. Sixty-eight
        of the 70 fleet rows are this species, so letting it score would have
        dropped eight branches' numbers over code that is mostly right. Mutation
        caught: `SCORING_SPECIES: tuple = (SPECIES_POSIX_LITERAL,
        SPECIES_RENDERED_PATH, SPECIES_REPR_HAYSTACK)` becoming the same tuple
        with `SPECIES_RETURNED_PATH` appended.
        """
        _write(
            tmp_path,
            "tests/test_scanner.py",
            """
            def test_the_relative_path_is_reported(tmp_path):
                result = collect(tmp_path)
                assert result["relative_path"] == "pkg/gamma.py"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))
        line = result["checks"][1]
        row = result["nominations"][0]

        assert result["violations"] == []
        assert result["score"] == 100
        assert result["checks"][0]["passed"] is True
        assert line["name"] == "Path provenance nominations"
        assert line["passed"] is True
        assert "reported only - not scored, not counted as failing" in line["message"]
        assert row["species"] == "RETURNED-PATH"
        assert row["rendering"] == "subscript"
        assert "NOMINATION ONLY, not scored" in row["reason"]

    def test_a_nomination_does_not_move_a_number_a_scored_row_already_set(self, tmp_path):
        """THE SPLIT, PINNED AS ARITHMETIC: same denominator, same answer.

        Two two-unit projects with the SAME single RENDERED-PATH row. The
        second's other unit is a RETURNED-PATH nomination instead of a clean
        unit, and the score has to be identical - 50 both times - or the
        nomination is a penalty wearing a report's name. Mutation caught: `scored
        = [row for row in rows if row["species"] in SCORING_SPECIES]` in
        `split_rows` becoming `scored = list(rows)`, which reports 0 for the
        second project.
        """
        rendered_unit = (
            "def test_the_relative_path_is_rendered(tmp_path):\n"
            "    entry = collect(tmp_path)\n"
            '    assert str(entry.path) == "pkg/gamma.py"\n'
        )
        clean_unit = 'def test_a_clean_unit(tmp_path):\n    assert (tmp_path / "a").parent == tmp_path\n'
        returned_unit = (
            "def test_the_relative_path_is_returned(tmp_path):\n"
            "    result = collect(tmp_path)\n"
            '    assert result["relative_path"] == "pkg/gamma.py"\n'
        )
        _write(tmp_path / "clean", "tests/test_scanner.py", rendered_unit + "\n\n" + clean_unit)
        _write(tmp_path / "nominating", "tests/test_scanner.py", rendered_unit + "\n\n" + returned_unit)

        clean = posix_literal_check.check_branch(str(tmp_path / "clean"))
        nominating = posix_literal_check.check_branch(str(tmp_path / "nominating"))

        assert clean["score"] == 50
        assert nominating["score"] == 50
        assert len(nominating["nominations"]) == 1
        assert len(nominating["violations"]) == len(clean["violations"]) == 1

    def test_a_pack_assertion_on_a_corpus_rendered_relpath_is_never_scored(self, tmp_path):
        """THE 27-ROW FALSE-POSITIVE FAMILY, AND IT IS THIS FILE'S OWN TESTS.

        `corpus._relpath` (corpus.py:202) returns
        `path.relative_to(root).as_posix()`. Every nodeid and every relpath this
        pack reports is therefore POSIX on every host, forever, on purpose - so
        `"tests/test_x.py" in named[0]["message"]` is correct, portable code that
        cannot go red on any runner. The first fleet run of the undivided arm
        returned 64 rows and 27 were on this branch, sixteen of them in this very
        file. They are the SAME AST SHAPE as the rows that broke CI; the
        difference is that prax's `scanner.py:57` renders with `str()` and
        seedgo's `corpus.py:202` renders with `.as_posix()`, and no AST reader of
        the TEST can see either. So the row nominates and the number does not
        move - which is the only reason this pack can score its own test file at
        100. Mutation caught: `SCORING_SPECIES` gaining `SPECIES_RETURNED_PATH`,
        which drops this branch's own pins to 0 for being right.
        """
        _write(
            tmp_path,
            "tests/test_pack_shapes.py",
            """
            def test_the_unreadable_file_is_named(tmp_path):
                result = check_branch(str(tmp_path))
                named = [c for c in result["checks"] if c["name"] == "Corpus readable"]
                assert "tests/test_broken.py" in named[0]["message"]
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["score"] == 100
        assert result["violations"] == []
        assert [r["species"] for r in result["nominations"]] == ["RETURNED-PATH"]
        assert result["nominations"][0]["literal"] == "tests/test_broken.py"

    def test_as_posix_inside_the_comparison_acquits_the_whole_site(self, tmp_path):
        """`.as_posix()` says "posix on purpose", and it is the cure this arm teaches.

        A site rewritten into `.as_posix()` on both sides is exactly what the
        finding asks for, so convicting it would convict the fix - the same
        reasoning that acquits `ntpath` and `posixpath` in arm 2. `os.sep`,
        `os.path.join` and `os.fspath` are acquitted with it: each of them NAMES
        the separator instead of assuming one. Mutation caught:
        `POSIX_SPELLING_METHOD: str = "as_posix"` becoming `"as_posix_"`, which
        matches nothing and puts every cured site back in the report.
        """
        _write(
            tmp_path,
            "tests/test_scanner.py",
            """
            def test_the_relative_path_is_reported(tmp_path):
                entry = collect(tmp_path)
                assert entry.path.as_posix() == "pkg/gamma.py"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["nominations"] == []
        assert result["score"] == 100

    def test_a_returned_value_in_a_unit_that_never_touches_a_path_is_not_read(self, tmp_path):
        """THE WEAKEST EVIDENCE THIS RULE USES, AND IT IS USED ON PURPOSE.

        A subscript into a result dict cannot prove its value ever was a Path, so
        when the key is not path-ish the arm falls back to asking whether the
        unit works with paths AT ALL. It is circumstantial, it is written down as
        circumstantial, and it is the second reason this half does not score.
        Without it `payload["body"] == "a/b.txt"` in a unit that never touches
        the filesystem is a nomination, and the arm reports the fleet's message
        bodies. Mutation caught: `return "subscript" if builds_path or
        _pathish_subscript(node) else ""` in `_returned_value` becoming `return
        "subscript"`.
        """
        _write(
            tmp_path,
            "tests/test_payloads.py",
            """
            def test_the_payload_body_is_echoed():
                assert payload["body"] == "a/b.txt"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["nominations"] == []
        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_rooted_literal_belongs_to_arms_one_and_two_and_not_to_arm_three(self, tmp_path):
        """497 of the 501 rooted literals measured fleet-wide are DATA.

        A rooted literal is arms 1-2's subject - a root put through a resolver -
        and reading it here as well would put five hundred sites into arm 3's
        report to catch four that arms 1-2 already hold. Arm 4 is the one place
        the root is allowed, because inside a rendered repr the root is not the
        hazard and the separator is. Mutation caught: `return path_run(text,
        allow_rooted=False)` in `relative_path_run` becoming `allow_rooted=True`.
        """
        _write(
            tmp_path,
            "tests/test_scanner.py",
            """
            def test_the_absolute_path_is_reported(tmp_path):
                entry = collect(tmp_path)
                assert str(entry.path) == "/srv/pkg/gamma.py"
            """,
        )

        result = posix_literal_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["nominations"] == []
        assert result["score"] == 100

    def test_the_check_line_widens_when_a_rendering_row_is_in_the_list(self, tmp_path):
        """THE SENTENCE FOLLOWS THE SPECIES, or it describes a finding that is not there.

        A project flagged only by arms 1-2 keeps the resolver sentence it has
        always had. The moment a rendering row joins the list, "put a rooted path
        literal through a resolver" would be describing a finding that is neither
        rooted nor resolved, and a reader sent looking for a resolver finds
        nothing. Mutation caught: `if species == {SPECIES_POSIX_LITERAL}:` in
        `_flagged_message` becoming `if True:`, which prints the resolver
        sentence over a REPR-HAYSTACK row.
        """
        _write(
            tmp_path / "mixed",
            "tests/test_mixed.py",
            """
            def test_a_constructed_root_is_resolved():
                assert Path("/srv/data").resolve() in roster


            def test_the_relative_path_is_reported(tmp_path):
                entry = collect(tmp_path)
                assert str(entry.path) == "pkg/gamma.py"
            """,
        )
        _write(
            tmp_path / "resolver_only",
            "tests/test_roots.py",
            """
            def test_a_constructed_root_is_resolved():
                assert Path("/srv/data").resolve() in roster
            """,
        )

        mixed = posix_literal_check.check_branch(str(tmp_path / "mixed"))
        alone = posix_literal_check.check_branch(str(tmp_path / "resolver_only"))

        assert "2/2 test units spell a path in one platform's dialect" in mixed["checks"][0]["message"]
        assert "1/1 test units put a rooted path literal through a resolver" in alone["checks"][0]["message"]


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

    def test_a_phrase_inside_quotation_marks_is_named_not_confessed(self, tmp_path):
        """Quoting a confession is not making one — the data exclusion, one layer up.

        The rule has never flagged a test whose DATA contains the phrase: that
        test is testing a string. A docstring that writes the phrase between
        quotation marks is doing the same thing in prose. Measured fleet-wide
        on 2026-09-07 before the narrowing existed: 11 units matched, and the 5
        with the match inside quotes were ALL in this very class — the tests of
        this detector, whose docstrings have to name the phrases it hunts. No
        other branch moved by one unit.
        """
        _write(
            tmp_path,
            "tests/test_about_the_rule.py",
            '''
            def test_the_detector_reads_a_reason():
                """A docstring saying "added for coverage" is what this detector hunts."""
                assert detect(SAMPLE) == "docstring"
            ''',
        )

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert result["violations"] == []

    def test_the_same_phrase_without_quotation_marks_is_still_a_confession(self, tmp_path):
        """Negative control for the quote narrowing, and the reason it is narrow.

        The acquittal above must turn on the quotation marks and nothing else.
        Same phrase, same position, no quotes: flagged.
        """
        _write(
            tmp_path,
            "tests/test_plain.py",
            '''
            def test_the_writer_flushes():
                """A docstring saying added for coverage is what this detector hunts."""
                assert writer.flush() is None
            ''',
        )

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 1
        assert result["violations"][0]["where"] == "docstring"

    def test_a_quoted_phrase_does_not_acquit_a_plain_one_later_in_the_same_docstring(self, tmp_path):
        """The scan reads EVERY match, not the first.

        A docstring that quotes the phrase in its opening line and then confesses
        in its closing one must still be flagged. Taking the first match and
        stopping would let a quotation earlier in the paragraph silence a real
        confession after it — an acquittal bought by word order.
        """
        _write(
            tmp_path,
            "tests/test_both.py",
            '''
            def test_the_writer_flushes():
                """A docstring saying "for coverage" is the subject here.

                This one was added for coverage.
                """
                assert writer.flush() is None
            ''',
        )

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 1

    def test_to_satisfy_convicts_only_when_the_test_is_the_subject(self, tmp_path):
        """A bare verb phrase is not a purposive claim.

        The pattern was `to satisfy` with no subject until 2026-09-07, and on
        that date it convicted five units across three branches of which NONE
        was a confession: a hypothetical about another test, a rejected design,
        a guard that was never written, one "cheap to satisfy", and one about
        editing text to satisfy a cap. Every one of them is prose about
        something other than why this test exists. Both spellings are asserted
        here in one place, because the narrowing is only correct if it still
        reads the confession.
        """
        _write(
            tmp_path,
            "tests/test_subject.py",
            '''
            def test_a_hypothetical_about_other_code():
                """A guard that edited the measurement to satisfy itself would be lying."""
                assert guard(sample) is None

            def test_the_real_confession():
                """This one exists to satisfy the audit."""
                assert writer.flush() is None
            ''',
        )

        result = coverage_slot_check.check_branch(str(tmp_path))

        flagged = [row["nodeid"] for row in result["violations"]]
        assert len(flagged) == 1, flagged
        assert flagged[0].endswith("test_the_real_confession")

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


# =============================================================================
# HOST STATE - DID THE TEST PUT THE MACHINE BACK
# =============================================================================

from aipass.seedgo.apps.handlers.pytest_quality_standards import host_state_check  # noqa: E402

# NOTHING IN THIS SECTION TOUCHES HOST STATE, and the rule under test is why that
# has to be written down rather than assumed. A pin for a checker about services,
# signals, os.environ and the working directory is the one place in this file
# where a real `os.environ[...] = ...`, a real `os.chdir` or a real subprocess
# would read as ordinary setup. There is none: every project below is source TEXT
# written into tmp_path, and every assertion is about what the CHECKER reported
# over that text. No environment variable is set, no directory is entered, no
# process is signalled and nothing is written outside the fixture directory -
# a pin for this rule that broke this rule would be the joke telling itself.


def _effectful_module(root: Path, verbs: str) -> Path:
    """The production half of the incident: systemctl AND a published verb set.

    BOTH HALVES ARE THE DERIVATION, and that is why they are written together: a
    module that drives a service manager gives a reader no verb to look for
    unless it also publishes one, and a module full of verbs that touches
    nothing is an ordinary CLI. `verbs` is interpolated into the constant so a
    test can rename them and watch the finding follow the rename.
    """
    return _write(
        root,
        "apps/timer_install.py",
        f"""
        HANDLED_COMMANDS = ({verbs},)


        def _run_systemctl(*args):
            command = ["systemctl", "--user", *args]
            return subprocess.run(command, check=False)


        def main():
            _run_systemctl("stop", "daemon-tick.timer")
        """,
    )


def _host_state_project(root: Path) -> Path:
    """A six-unit project where exactly two units leave the machine changed.

    The four clean units are clean for four DIFFERENT reasons - a seam patched
    by a literal, a seam patched through a module-level constant, monkeypatch,
    and a path under tmp_path - so no single acquittal carries the whole 66 and
    collapsing any one of them moves the number.
    """
    _effectful_module(root, '"install-timer", "uninstall-timer", "timer-status"')
    _write(
        root,
        "tests/test_cli_routing.py",
        """
        GATED_VERBS = ["uninstall-timer", "help"]
        TIMER_SEAM = "apps.timer_install.subprocess.run"


        @pytest.mark.parametrize("verb", GATED_VERBS)
        def test_a_stray_positional_is_refused(verb):
            with patch.object(sys, "argv", ["daemon", verb, "not_a_real_subarg"]):
                with pytest.raises(SystemExit):
                    _daemon_mod.main()


        def test_the_timer_is_stopped_before_the_state_is_read():
            subprocess.run(["systemctl", "--user", "stop", "daemon-tick.timer"])
            assert read_state() == "stopped"


        def test_the_router_refuses_an_unknown_subcommand():
            with patch("apps.timer_install.subprocess.run") as runner:
                with patch.object(sys, "argv", ["daemon", "install-timer", "junk"]):
                    with pytest.raises(SystemExit):
                        _daemon_mod.main()
            assert not runner.called


        def test_the_seam_named_by_a_constant_is_patched():
            with patch(TIMER_SEAM) as runner:
                with patch.object(sys, "argv", ["daemon", "uninstall-timer"]):
                    _daemon_mod.main()
            assert runner.called


        def test_the_branch_is_read_from_the_environment(monkeypatch):
            monkeypatch.setenv("AIPASS_BRANCH", "daemon")
            assert read_branch() == "daemon"


        def test_the_real_config_is_snapshotted_into_the_fixture(tmp_path):
            config = Path.home() / ".config" / "daemon.json"
            snapshot = tmp_path / config.name
            snapshot.write_text("{}")
            assert snapshot.is_file()
        """,
    )
    return root


class TestHostStateDetection:
    """The six species, and the incident that is the whole reason for the sixth.

    Each test names the one-line mutation of `host_state_check` it was confirmed
    RED against, so a later reader can check the pin still bites rather than
    trusting that it once did.
    """

    def test_a_verb_production_made_effectful_driven_through_an_entry_point_is_flagged(self, tmp_path):
        """THE INCIDENT SHAPE, both halves written out, and the reason this rule exists.

        No AST reader can follow `main()` into `systemctl` - that is an
        interpreter, not a reader - so the dangerous verbs are DERIVED from the
        branch's own production: a module that reaches host control and also
        publishes a HANDLED_COMMANDS-style constant makes those verbs
        host-effectful. A unit that feeds one to a real entry point with nothing
        patched on the seam is the site that stopped daemon-tick.timer for
        twenty-three hours, and the finding has to name the module that made the
        verb dangerous or a reader cannot triage it. Mutation caught: `"main"`
        deleted from ENTRY_POINT_CALLS, which acquits the exact shape the rule
        was written for and leaves the other five species looking healthy.
        """
        _write(
            tmp_path,
            "apps/timer_install.py",
            """
            HANDLED_COMMANDS = ("install-timer", "uninstall-timer", "timer-status")


            def _run_systemctl(*args):
                command = ["systemctl", "--user", *args]
                return subprocess.run(command, check=False)


            def main():
                _run_systemctl("stop", "daemon-tick.timer")
            """,
        )
        _write(
            tmp_path,
            "tests/test_cli_routing.py",
            """
            def test_a_stray_positional_is_refused():
                with patch.object(sys, "argv", ["daemon", "uninstall-timer", "not_a_real_subarg"]):
                    with pytest.raises(SystemExit):
                        _daemon_mod.main()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))
        row = result["violations"][0]

        assert [r["species"] for r in result["violations"]] == ["EFFECTFUL_VERB"]
        assert row["nodeid"] == "tests/test_cli_routing.py::test_a_stray_positional_is_refused"
        assert "'uninstall-timer'" in row["detail"]
        assert "apps/timer_install.py" in row["detail"]
        assert "systemctl" in row["detail"]

    def test_a_verb_reached_only_through_a_parametrized_module_list_is_flagged(self, tmp_path):
        """ONE HOP, FIRST HALF: the verb in the incident is not in the unit at all.

        `TestUnknownArgumentIsRefused` parametrises over a module-level
        GATED_VERBS list, so a rule reading only the unit's own literals would
        have missed the very site it was written for. The list here also holds a
        verb production never declared, so the resolution has to pick the
        dangerous one rather than flag on the presence of a list. Mutation
        caught: `if isinstance(child, ast.Name) and child.id in
        module_collections:` becoming `... child.id in {}:`, which resolves no
        name and reports nothing.
        """
        _effectful_module(tmp_path, '"uninstall-timer"')
        _write(
            tmp_path,
            "tests/test_cli_routing.py",
            """
            GATED_VERBS = ["uninstall-timer", "help"]


            @pytest.mark.parametrize("verb", GATED_VERBS)
            def test_a_stray_positional_is_refused(verb):
                with patch.object(sys, "argv", ["daemon", verb, "not_a_real_subarg"]):
                    with pytest.raises(SystemExit):
                        _daemon_mod.main()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["nodeid"] for row in result["violations"]] == [
            "tests/test_cli_routing.py::test_a_stray_positional_is_refused"
        ]
        assert "'uninstall-timer'" in result["violations"][0]["detail"]

    def test_a_verb_reached_by_a_loop_over_the_same_list_inside_the_unit_is_flagged(self, tmp_path):
        """ONE HOP, SECOND HALF: a reader that walked only decorators calls this clean.

        The same file that parametrises over GATED_VERBS also loops over it
        inside a unit body, driving the same verbs through the same `main()`,
        and both halves were needed for the real site. The `--help` in the argv
        is not an acquittal either: it only saves the machine if production's
        help gate fires before the work does, and relying on a guard inside
        production is precisely the reliance that failed here. Mutation caught:
        `for scope in [*unit.node.decorator_list, unit.node]:` becoming `for
        scope in [*unit.node.decorator_list]:` - which leaves the parametrized
        pin above green and this one red.
        """
        _effectful_module(tmp_path, '"uninstall-timer"')
        _write(
            tmp_path,
            "tests/test_cli_routing.py",
            """
            GATED_VERBS = ["uninstall-timer", "help"]


            def test_help_outranks_the_gate():
                for verb in GATED_VERBS:
                    with patch.object(sys, "argv", ["daemon", verb, "--help"]):
                        with pytest.raises(SystemExit):
                            _daemon_mod.main()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["nodeid"] for row in result["violations"]] == [
            "tests/test_cli_routing.py::test_help_outranks_the_gate"
        ]
        assert "'uninstall-timer'" in result["violations"][0]["detail"]

    def test_the_dangerous_verbs_follow_a_rename_in_production(self, tmp_path):
        """DERIVED, NEVER LISTED - and this is the pin that stops a roster being added.

        One test file drives two verb spellings; two projects declare one each.
        A hardcoded list of verb names would keep flagging the old spelling
        after a branch renamed it and would never flag the new one - stale, and
        stale in the silent direction. Mutation caught: `for verb in
        _declared_verbs(tree):` becoming `for verb in ("uninstall-timer",):`,
        which keeps flagging the old spelling in the after project and never
        flags the new one - stale, and silent about it.
        """
        driver = """
            def test_the_old_name_is_refused():
                with patch.object(sys, "argv", ["daemon", "uninstall-timer", "junk"]):
                    with pytest.raises(SystemExit):
                        _daemon_mod.main()


            def test_the_new_name_is_refused():
                with patch.object(sys, "argv", ["daemon", "retire-timer", "junk"]):
                    with pytest.raises(SystemExit):
                        _daemon_mod.main()
            """
        before, after = tmp_path / "before", tmp_path / "after"
        for root, verbs in ((before, '"uninstall-timer"'), (after, '"retire-timer"')):
            _effectful_module(root, verbs)
            _write(root, "tests/test_cli_routing.py", driver)

        flagged_before = host_state_check.check_branch(str(before))["violations"]
        flagged_after = host_state_check.check_branch(str(after))["violations"]

        assert [row["nodeid"] for row in flagged_before] == ["tests/test_cli_routing.py::test_the_old_name_is_refused"]
        assert [row["nodeid"] for row in flagged_after] == ["tests/test_cli_routing.py::test_the_new_name_is_refused"]

    def test_a_subprocess_driving_a_service_manager_is_flagged(self, tmp_path):
        """SERVICE_CONTROL: the species the incident is made of, seen directly.

        A test that stops a timer and walks away has changed what the machine is
        DOING, not what it contains, and no later test in the session puts it
        back. Mutation caught: `return program if program in
        HOST_CONTROL_BINARIES else ""` in `_argv_binary` becoming `return ""`,
        which reads every argv and recognises no program in any of them.
        """
        _write(
            tmp_path,
            "tests/test_timer.py",
            """
            def test_the_timer_is_stopped():
                subprocess.run(["systemctl", "--user", "stop", "daemon-tick.timer"])
                assert read_state() == "stopped"
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["SERVICE_CONTROL"]
        assert "runs systemctl through subprocess.run" in result["violations"][0]["detail"]

    def test_a_signal_sent_to_a_process_the_unit_did_not_start_is_flagged(self, tmp_path):
        """PROCESS_SIGNAL: a signalled process is not put back by a finally clause.

        Narrow on purpose - `os.kill`, `os.killpg`, `signal.raise_signal` and
        nothing else, because `handle.terminate()` on a Popen the unit itself
        opened is correct teardown and telling the two apart needs the receiver.
        Mutation caught: `"os.kill"` deleted from the SIGNAL_CALLS frozenset,
        which leaves the commonest spelling of the species unread.
        """
        _write(
            tmp_path,
            "tests/test_lock.py",
            """
            def test_the_stale_holder_is_signalled():
                os.kill(pid_from_the_lockfile, signal.SIGTERM)
                assert lock.is_free()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["PROCESS_SIGNAL"]
        assert result["violations"][0]["nodeid"] == "tests/test_lock.py::test_the_stale_holder_is_signalled"

    def test_a_write_under_the_real_home_directory_is_flagged(self, tmp_path):
        """HOME_WRITE: a config file overwritten in the user's own home stays overwritten.

        The destination roots at `Path.home()`, so this is the user's real
        `.config`, not a fixture directory, and nothing in the unit puts the
        previous contents back. Mutation caught: `"write_text",` in
        MUTATING_PATH_METHODS becoming `"write_text_never",` - the roster losing
        the single commonest way a test writes a file at all.
        """
        _write(
            tmp_path,
            "tests/test_config.py",
            """
            def test_the_config_is_written():
                (Path.home() / ".config" / "daemon.json").write_text("{}")
                assert load_config() == {}
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["HOME_WRITE"]
        assert result["violations"][0]["nodeid"] == "tests/test_config.py::test_the_config_is_written"

    def test_an_assignment_into_os_environ_is_flagged(self, tmp_path):
        """ENV_MUTATION: the interpreter's environment is process-wide.

        A variable set here outlives the unit and every later test in the
        session sees it, which is how a suite acquires an order dependency
        nobody can find. Assignment is found STRUCTURALLY because
        `os.environ["X"] = "y"` has no call in it to read by name. Mutation
        caught: `_env_touch`'s Assign arm - `return "assignment into os.environ"
        if _subscripts_environ(node.targets) else ""` - becoming `return ""`.
        """
        _write(
            tmp_path,
            "tests/test_env.py",
            """
            def test_the_branch_is_read_from_the_environment():
                os.environ["AIPASS_BRANCH"] = "daemon"
                assert read_branch() == "daemon"
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["ENV_MUTATION"]
        assert "monkeypatch.setenv is restored for you" in result["violations"][0]["detail"]

    def test_a_raw_chdir_with_no_restore_is_flagged(self, tmp_path):
        """CWD_CHANGE: os.chdir moves the whole process, not this test.

        A later test resolving a relative path lands somewhere else, and the
        failure surfaces in a unit that has nothing to do with this one.
        Mutation caught: `corpus.dotted_name(node.func) != "os.chdir"` in
        `_cwd_change` becoming `!= "os.chdir_never"`, which reads every call and
        matches none.
        """
        _write(
            tmp_path,
            "tests/test_root.py",
            """
            def test_the_registry_is_found_from_the_repo_root():
                os.chdir(repo_root)
                assert Path("registry.json").is_file()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["CWD_CHANGE"]
        assert "monkeypatch.chdir is restored for you" in result["violations"][0]["detail"]

    def test_a_fixture_that_reaches_host_state_and_yields_nothing_after_it_is_flagged(self, tmp_path):
        """FIXTURE_NO_TEARDOWN: the setup landed and the teardown never did.

        A fixture is the RIGHT place to touch the host - it is the one place a
        restore runs for a failing test too - so the half-built version is worth
        its own species, and it is reported under the fixture's own nodeid
        because that is where a reader has to go. Mutation caught: `if not
        reached or _teardown_after_yield(node): continue` becoming `if not
        reached or not _teardown_after_yield(node): continue`, which reports
        every correctly restoring fixture and nothing else.
        """
        _write(
            tmp_path,
            "tests/test_timer.py",
            """
            @pytest.fixture
            def stopped_timer():
                subprocess.run(["systemctl", "--user", "stop", "daemon-tick.timer"])
                yield


            def test_the_state_reads_stopped(stopped_timer):
                assert read_state() == "stopped"
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["nodeid"] for row in result["violations"]] == ["tests/test_timer.py::stopped_timer"]
        assert result["violations"][0]["species"] == "FIXTURE_NO_TEARDOWN"
        assert "SERVICE_CONTROL" in result["violations"][0]["detail"]

    def test_a_unit_carrying_three_species_is_reported_as_one_row(self, tmp_path):
        """ONE ROW PER UNIT: three species is one unit a reader has to go and read.

        Counting findings instead of units would let a single test drive a
        project's score below zero, and a score that can go negative is one
        nobody believes twice. Mutation caught: `if row["nodeid"] not in seen:`
        in `find_unrestored` becoming `if True:`, which reports the same unit
        three times and takes this two-unit project to -50.
        """
        _write(
            tmp_path,
            "tests/test_many.py",
            """
            def test_three_species_in_one_unit():
                os.chdir(repo_root)
                os.environ["AIPASS_BRANCH"] = "daemon"
                subprocess.run(["systemctl", "--user", "stop", "daemon-tick.timer"])
                assert read_state() == "stopped"


            def test_one_clean_unit(monkeypatch):
                monkeypatch.setenv("AIPASS_BRANCH", "daemon")
                assert read_branch() == "daemon"
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))
        flagged = [row["nodeid"] for row in result["violations"]]

        assert flagged == ["tests/test_many.py::test_three_species_in_one_unit"]
        assert result["score"] == 50

    def test_a_runtime_assembled_argv_is_not_read_at_all(self, tmp_path):
        """A LIMIT PINNED AS A LIMIT, so nobody fixes the blind spot into a guess.

        Only a literal first element - or the first word of a literal command
        string - is evidence of which binary runs. The list here is assembled
        into a name first, so the checker says nothing, and that silence is the
        published contract rather than an oversight. Reading the whole unit for
        stray literals the way `_control_binary_anywhere` reads production would
        flag any test that merely MENTIONS systemctl in an assertion. Mutation
        caught: `program = _argv_binary(node)` in `_service_control` becoming
        `program = _argv_binary(node) or _control_binary_anywhere(unit.node)`.
        """
        _write(
            tmp_path,
            "tests/test_timer.py",
            """
            def test_the_timer_is_stopped():
                command = ["systemctl", "--user", "stop", "daemon-tick.timer"]
                subprocess.run(command)
                assert read_state() == "stopped"
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_module_that_publishes_verbs_and_reaches_nothing_makes_none_of_them_dangerous(self, tmp_path):
        """The other half of the derivation: an ordinary CLI is not a service manager.

        Every branch in the fleet publishes a COMMANDS-style constant and nearly
        every branch has a routing test that drives one of those verbs through
        `main()`. If publication alone made a verb dangerous, this rule would
        convict all of them and be switched off inside a week. Mutation caught:
        `program = _module_reaches_host_control(tree)` in `host_effectful_verbs`
        becoming `program = _module_reaches_host_control(tree) or "systemctl"`,
        which derives verbs from a module that touches nothing.
        """
        _write(
            tmp_path,
            "apps/cli.py",
            """
            HANDLED_COMMANDS = ("uninstall-timer", "status")


            def main():
                return route(sys.argv[1:])
            """,
        )
        _write(
            tmp_path,
            "tests/test_cli_routing.py",
            """
            def test_a_stray_positional_is_refused():
                with patch.object(sys, "argv", ["daemon", "uninstall-timer", "junk"]):
                    with pytest.raises(SystemExit):
                        _daemon_mod.main()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100


class TestHostStateAcquittals:
    """The difference between a rule and a nuisance - each one a measured false positive.

    Every acquittal below was added because the rule convicted correct code on a
    real fleet run, and every one of them is a line a later edit could delete
    without any test noticing. These are those tests.
    """

    def test_a_seam_patched_by_a_string_literal_acquits_the_verb(self, tmp_path):
        """TOUCHING THE REAL THING IS ALLOWED - reaching a patched seam is not touching it.

        This is the cure the rule teaches first: patch the module that does the
        work, and the refusal under test is actually proven rather than merely
        survived. If the cure does not acquit, the rule has nothing to recommend
        and every routing test in the fleet stays flagged forever. Mutation
        caught: `if needle and needle in target:` in `_seam_is_patched` becoming
        `if needle and needle == target:`, which only ever matches a patch
        target spelled as the bare module stem.
        """
        _effectful_module(tmp_path, '"uninstall-timer"')
        _write(
            tmp_path,
            "tests/test_cli_routing.py",
            """
            def test_the_router_refuses_an_unknown_subcommand():
                with patch("apps.timer_install.subprocess.run") as runner:
                    with patch.object(sys, "argv", ["daemon", "uninstall-timer", "junk"]):
                        with pytest.raises(SystemExit):
                            _daemon_mod.main()
                assert not runner.called
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_patch_target_held_in_a_module_level_constant_acquits_the_verb(self, tmp_path):
        """THE ONE HOP ON THE ACQUITTAL SIDE, and a rule that lacked it gave bad advice.

        @daemon wrote its cure with the seam in a module-level constant, and the
        literal-only reading kept flagging all three of its cured sites - which
        told an owner to inline a constant they had every reason to keep. A rule
        that pushes a branch into worse code to please the checker is the v4
        behaviour this pack exists to correct. Mutation caught: `if text in
        known:` in `patched_targets` becoming `if text in ():`, which leaves the
        bare name TIMER_SEAM as the only patched target and matches no needle.
        """
        _effectful_module(tmp_path, '"uninstall-timer"')
        _write(
            tmp_path,
            "tests/test_cli_routing.py",
            """
            TIMER_SEAM = "apps.timer_install.subprocess.run"


            def test_the_router_refuses_an_unknown_subcommand():
                with patch(TIMER_SEAM) as runner:
                    with patch.object(sys, "argv", ["daemon", "uninstall-timer", "junk"]):
                        with pytest.raises(SystemExit):
                            _daemon_mod.main()
                assert not runner.called
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_monkeypatch_setenv_and_delenv_are_never_a_finding(self, tmp_path):
        """USING THEM IS THE CURE, so flagging them would convict the fix itself.

        pytest restores a monkeypatched environment at teardown by contract, on
        every path including the failing one - which is exactly what the finding
        for a raw assignment tells the author to go and do. Mutation caught:
        `if dotted == "os.putenv":` in `_env_touch` becoming `if dotted in
        ("os.putenv", "monkeypatch.setenv", "monkeypatch.delenv"):`, the
        plausible edit of someone widening the roster by spelling rather than by
        meaning.
        """
        _write(
            tmp_path,
            "tests/test_env.py",
            """
            def test_the_branch_is_read_from_the_environment(monkeypatch):
                monkeypatch.setenv("AIPASS_BRANCH", "daemon")
                monkeypatch.delenv("AIPASS_ROOT", raising=False)
                assert read_branch() == "daemon"
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_monkeypatch_chdir_acquits_a_raw_chdir_deeper_in_the_same_unit(self, tmp_path):
        """A STATEMENT ABOUT HOW MONKEYPATCH WORKS, not a convenience.

        `monkeypatch.chdir` records the working directory at the moment it is
        called and restores THAT at teardown, so a raw `os.chdir` deeper into
        the same tree is undone with it. Reading the second call on its own
        convicts correct code, and the author's only way to please the checker
        would be to delete a line that changes nothing. Mutation caught:
        `_cwd_change`'s early return comparing against `"monkeypatch.chdir"`
        becoming `"monkeypatch.chdir_never"`.
        """
        _write(
            tmp_path,
            "tests/test_registry.py",
            """
            def test_the_registry_file_is_found(tmp_path, monkeypatch):
                monkeypatch.chdir(tmp_path)
                os.chdir(tmp_path / "nested")
                assert Path("registry.json").is_file()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_path_under_tmp_path_is_not_host_state(self, tmp_path):
        """A write to a directory pytest created and removes is not the host.

        The subject here is BOTH: rooted at the fixture and named from a
        `Path.home()` expression one hop back, which is the shape a snapshot
        test really has - read the user's config, land a copy where pytest will
        clean it up. The sandbox reading has to win, and it has to survive the
        hop, or every snapshot test in the fleet is a HOME_WRITE. Mutation
        caught: `sandbox_names = _bound_to(unit.node, SANDBOX_FIXTURES)` in
        `_home_write` becoming `sandbox_names = set()`.
        """
        _write(
            tmp_path,
            "tests/test_config.py",
            """
            def test_the_real_config_is_snapshotted_into_the_fixture(tmp_path):
                config = Path.home() / ".config" / "daemon.json"
                snapshot = tmp_path / config.name
                snapshot.write_text("{}")
                assert snapshot.is_file()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_same_file_fixture_restoring_os_environ_acquits_the_units_that_request_it(self, tmp_path):
        """THE PYTEST IDIOM: a bare yield then a restore, and it must not be flagged twice.

        @ai_mail's `clean_env` strips four identity variables, yields, and puts
        all four back; twenty-nine units then set one of those same four inside
        the test. Reading the units alone called all twenty-nine unrestored when
        the file restores every one - and demanding a `try`/`finally` instead of
        a plain yield convicted thirty correct fixtures on the first fleet run.
        Both halves are pinned here: the requesting unit is clean AND the
        fixture itself is clean. Mutation caught: `if {argument.arg for argument
        in unit.node.args.args} & restoring_fixtures:` in `_env_mutation`
        becoming `... & set():`.
        """
        _write(
            tmp_path,
            "tests/test_identity.py",
            """
            @pytest.fixture
            def clean_env():
                saved = os.environ.pop("AIPASS_BRANCH", None)
                yield
                os.environ["AIPASS_BRANCH"] = saved or ""


            def test_the_branch_is_read_from_the_environment(clean_env):
                os.environ["AIPASS_BRANCH"] = "daemon"
                assert read_branch() == "daemon"
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_same_file_fixture_calling_monkeypatch_chdir_acquits_the_units_that_request_it(self, tmp_path):
        """@drone's lock_dir, which is correct code and was one row on the first run.

        The fixture records the original directory through monkeypatch and the
        unit then walks deeper with a raw `os.chdir`; teardown puts the process
        back where it started regardless. The acquittal travels from the fixture
        to every unit in the same file that requests it, one hop, no imports.
        Mutation caught: `if "monkeypatch.chdir" in calls:` in
        `restoring_fixtures` becoming `if "monkeypatch.chdir" in set():`.
        """
        _write(
            tmp_path,
            "tests/test_registry.py",
            """
            @pytest.fixture
            def lock_dir(tmp_path, monkeypatch):
                monkeypatch.chdir(tmp_path)
                return tmp_path


            def test_the_registry_file_is_found(lock_dir):
                os.chdir(lock_dir / "nested")
                assert Path("registry.json").is_file()
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_an_env_change_guarded_by_its_own_finally_is_not_the_row(self, tmp_path):
        """The cure written inline: the guarded mutation is not what gets reported.

        A variable set inside a `try` whose `finally` deletes it has been
        restored on every path including the failing one, and convicting the
        line the rule's own fix advice produces would teach projects to delete
        their restores. Only the guarded statement is asserted about here - what
        the checker says about the restoring statement in the `finally` is its
        owner's call and is deliberately not pinned. Mutation caught: `if not
        touched or _undone_in_a_finally(unit.node, node, ("os.environ",
        "os.putenv")):` losing its second clause, which reports the assignment
        inside the try.
        """
        path = _write(
            tmp_path,
            "tests/test_env.py",
            """
            def test_the_branch_is_read_from_the_environment():
                try:
                    os.environ["AIPASS_BRANCH"] = "daemon"
                    assert read_branch() == "daemon"
                finally:
                    del os.environ["AIPASS_BRANCH"]
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))
        reported = [row["line"] for row in result["violations"]]

        assert _line_of(path, '        os.environ["AIPASS_BRANCH"] = "daemon"') not in reported

    def test_a_cwd_change_guarded_by_its_own_finally_is_not_the_row(self, tmp_path):
        """The same acquittal for the working directory, and it needs its own pin.

        `_cwd_change` consults the finally reading through a separate call with
        its own needles, so the env pin above cannot cover it: an edit that
        drops the cwd needles leaves that one green. Only the guarded statement
        is asserted about, same as above. Mutation caught:
        `_undone_in_a_finally(unit.node, node, ("os.chdir",))` becoming
        `_undone_in_a_finally(unit.node, node, ("os.chdir_never",))`.
        """
        path = _write(
            tmp_path,
            "tests/test_root.py",
            """
            def test_the_registry_is_found_from_the_repo_root():
                origin = os.getcwd()
                try:
                    os.chdir(repo_root)
                    assert Path("registry.json").is_file()
                finally:
                    os.chdir(origin)
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))
        reported = [row["line"] for row in result["violations"]]

        assert _line_of(path, "        os.chdir(repo_root)") not in reported

    def test_the_restoring_statement_in_the_finally_is_not_itself_a_row(self, tmp_path):
        """THE RULE MUST NOT CONVICT THE CURE ITS OWN RULE TEXT TEACHES.

        Measured defect, 2026-09-08: the first version read the whole `Try` for
        its evidence and the try body alone for its location, so the guarded
        change was acquitted and the RESTORE was reported - the worked example
        in host_state.md scored 0, with the row on the `del`. A rule that flags
        the restore teaches projects to delete restores, which is the incident
        again with more steps. The whole unit is asserted clean here, both
        halves, which is what the two pins above deliberately left open.
        Mutation caught: `if not in_body and line not in
        _lines_of(candidate.finalbody):` becoming `if not in_body:`, which is
        the original locating logic and reports the `del` again.
        """
        _write(
            tmp_path,
            "tests/test_env.py",
            """
            def test_the_branch_is_read_from_the_environment():
                try:
                    os.environ["AIPASS_BRANCH"] = "daemon"
                    assert read_branch() == "daemon"
                finally:
                    del os.environ["AIPASS_BRANCH"]


            def test_the_registry_is_found_from_the_repo_root():
                origin = os.getcwd()
                try:
                    os.chdir(repo_root)
                    assert Path("registry.json").is_file()
                finally:
                    os.chdir(origin)
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_finally_that_puts_nothing_back_does_not_acquit_the_change(self, tmp_path):
        """THE ACQUITTAL IS THE RESTORE, NEVER THE KEYWORD.

        Measured defect, 2026-09-08, the same one line as the pin above read
        from the other side: evidence collected by walking the whole `Try` meant
        a change inside the body satisfied its own acquittal, so `finally:
        logger.info(...)` acquitted an environment variable nobody put back.
        Correct code scored 0 and incorrect code scored 100 for one shape.
        Mutation caught: `counterpart = candidate.finalbody if in_body else
        candidate.body` becoming `counterpart = list(candidate.body) +
        list(candidate.finalbody)`, which is the original whole-try evidence
        walk and acquits this unit on its own mention.
        """
        path = _write(
            tmp_path,
            "tests/test_env.py",
            """
            def test_the_branch_is_read_from_the_environment():
                try:
                    os.environ["AIPASS_BRANCH"] = "daemon"
                    assert read_branch() == "daemon"
                finally:
                    logger.info("done")
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["ENV_MUTATION"]
        assert [row["line"] for row in result["violations"]] == [
            _line_of(path, '        os.environ["AIPASS_BRANCH"] = "daemon"')
        ]

    def test_the_finally_acquittal_does_not_reach_a_service_control(self, tmp_path):
        """DELIBERATELY NOT GENERAL: environment and working directory, and nothing else.

        `systemctl --user start` in a `finally` is not proof the machine is back
        - the unit file may already be deleted, the start may be a silent no-op,
        and the limit that matters most is that a `finally` does not run when
        the process is killed. A restore the checker cannot verify must not
        acquit the species the incident was made of. Pinned by the LINE the
        finding lands on, not by the row count: the guarded `stop` inside the
        try is the statement that must still be reported. Mutation caught:
        `_service_control`'s guard gaining `or _undone_in_a_finally(unit.node,
        node, ("subprocess",))`, which generalises the acquittal by one clause -
        and which a count alone cannot see, because that mutation moves the row
        onto the restart instead of removing it.
        """
        path = _write(
            tmp_path,
            "tests/test_timer.py",
            """
            def test_the_state_reads_stopped():
                try:
                    subprocess.run(["systemctl", "--user", "stop", "daemon-tick.timer"])
                    assert read_state() == "stopped"
                finally:
                    subprocess.run(["systemctl", "--user", "start", "daemon-tick.timer"])
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))
        reported = [row["line"] for row in result["violations"]]

        assert [row["species"] for row in result["violations"]] == ["SERVICE_CONTROL"]
        assert reported == [_line_of(path, '        subprocess.run(["systemctl", "--user", "stop"')]
        assert result["score"] == 0


class TestHostStateBranchCheck:
    """The scoring-API contract, and the two paths where silence reads as clean."""

    def test_the_score_is_the_share_of_units_that_leave_the_machine_as_they_found_it(self, tmp_path):
        """The number is clean-over-total, counted per unit, and four acquittals hold it up.

        Two of the six units are the real thing; the other four are clean for
        four different reasons, so a mutation that collapses any single
        acquittal moves this number and cannot hide behind the other three. An
        inverted numerator still moves plausibly with a tree, which is why it is
        pinned by the number and by the sentence a reader gets. Mutation caught:
        `score = int(((total - len(flagged)) / total) * 100)` becoming `score =
        int((len(flagged) / total) * 100)`, which reports 33 where the honest
        answer is 66.
        """
        result = host_state_check.check_branch(str(_host_state_project(tmp_path)))

        assert result["score"] == 66
        assert len(result["violations"]) == 2
        assert (
            "2/6 test units and fixtures change live host state with no visible restore"
            in result["checks"][0]["message"]
        )

    def test_fixtures_are_counted_in_the_denominator_that_scores_them(self, tmp_path):
        """A SCORE THAT CAN GO NEGATIVE IS ONE NOBODY BELIEVES TWICE.

        Measured defect, 2026-09-08: `find_unrestored` reports fixture rows as
        well as unit rows, and the first version divided both by a count of
        UNITS alone. One clean unit beside two unrestoring fixtures scored -100
        and printed the sentence "2/1 test units". Every subject the rule judges
        has to be in the denominator that scores it. Mutation caught:
        `population = total + fixture_count(scanned)` becoming `population =
        total`, which returns -100 here.
        """
        _write(
            tmp_path,
            "tests/test_fixtures.py",
            """
            @pytest.fixture
            def stopped_timer():
                subprocess.run(["systemctl", "--user", "stop", "daemon-tick.timer"])
                yield


            @pytest.fixture
            def moved_home():
                os.chdir("/tmp")
                yield


            def test_the_state_reads_stopped(stopped_timer):
                assert read_state() == "stopped"
            """,
        )

        result = host_state_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 2
        assert result["score"] == 33
        assert "2/3 test units and fixtures" in result["checks"][0]["message"]

    def test_the_result_passes_and_stays_advisory_even_when_units_are_flagged(self, tmp_path):
        """SHADOW MODE GATES NOTHING - this rule scores before it is calibrated.

        Top-level `passed` must stay True while flags exist and `advisory` must
        stay True, so a caller can tell a report from a verdict. Mutation
        caught: `"passed": True` becoming `"passed": not flagged` in the scored
        return, which turns an uncalibrated advisory into a board failure on
        every branch that has one of these sites.
        """
        result = host_state_check.check_branch(str(_host_state_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "HOST_STATE"
        assert result["checks"][0]["passed"] is False

    def test_a_project_with_no_test_files_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        A 0 blames a project for a fact about its layout and a 100 claims a
        measurement that never happened. Each check in this pack carries its own
        copy of the early return, so each one has to be pinned - and losing it
        here does not return a wrong number, it divides by zero and takes the
        caller with it. Mutation caught: `"not_applicable": True,` becoming
        `"not_applicable": False,` in the `total == 0` return.
        """
        _effectful_module(tmp_path, '"uninstall-timer"')

        result = host_state_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin.

        An unparseable file contributes no units, so it cannot lower a score,
        and silence about it reads as a clean result. This is the one path where
        nothing else can catch it: the message a caller sees must say the file
        was present and unreadable, not that the project has never written a
        test. Mutation caught: the `measured` ternary's `if not
        scanned.unparseable` becoming `if True`, which makes the two cases
        indistinguishable.
        """
        _effectful_module(tmp_path, '"uninstall-timer"')
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = host_state_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_test_file_is_named_beside_a_scored_result(self, tmp_path):
        """The unreadable line must also survive onto the path that DOES score.

        The early-return path carries it by construction; the scored path has to
        append it deliberately, and dropping that one line leaves a branch with
        a healthy number and no hint that a file was never read at all - which
        for this rule biases toward CLEAN, since an unread file flags nothing.
        Mutation caught: `checks.extend(unreadable)` becoming
        `checks.extend([])`.
        """
        _host_state_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = host_state_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 66
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]


# =============================================================================
# FRESH CLONE - WOULD THIS TEST PASS ON A MACHINE THAT HAS ONLY WHAT THE REPO SHIPS
# =============================================================================

from aipass.seedgo.apps.handlers.pytest_quality_standards import fresh_clone_check  # noqa: E402

# NOTHING IN THIS SECTION READS THE LIVE CHECKOUT, and the rule under test is the
# reason that has to be written down rather than assumed. A pin for a checker
# about `.trinity`, `projects/`, `find_repo_root()` and `Path(__file__).parents[1]`
# is the one place in this file where a real read of the branch tree would look
# like ordinary setup. There is none: every project below is source TEXT written
# into tmp_path, and every assertion is about what the CHECKER reported over that
# text. No fleet count, no branch name, no live registry, nothing outside the
# fixture directory - a pin for THIS rule that broke this rule would be the joke
# telling itself, and it would also be red on the fresh clone CI now runs.

#: Six units that are clone-safe for six DIFFERENT reasons - sandbox root,
#: sandbox handed out by a fixture chain, a spelling the unit builds, a negated
#: template region, a skip guard, and a machine root carrying a literal. Written
#: this way on purpose: a project whose clean units were clean for the SAME
#: reason would still score 100 with five of the six acquittals deleted.
_CLONE_SAFE_UNITS = """
BRANCH_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def hosted_baud(repo_root):
    return repo_root


@pytest.fixture
def repo_root(tmp_path):
    (tmp_path / "projects").mkdir()
    return tmp_path


def test_a_tree_with_no_projects_resolves_nothing(tmp_path):
    assert not (tmp_path / "projects" / "baud" / "registry.json").exists()


def test_the_registry_lists_what_the_fixture_built(hosted_baud):
    assert not (hosted_baud / "projects" / "baud" / "registry.json").exists()


def test_a_planted_passport_is_read_back(tmp_path):
    (tmp_path / ".trinity").mkdir()
    assert not (tmp_path / ".trinity" / "passport.json").exists()


def test_the_template_ships_its_passport():
    tpl = get_template_dir()
    assert (tpl / ".trinity" / "passport.json").is_file()


def test_the_local_file_is_a_document():
    local_file = BRANCH_ROOT / ".trinity" / "local.json"
    if not local_file.exists():
        pytest.skip("no live .trinity/local.json in this checkout")
    assert json.loads(local_file.read_text())["branch"] == "daemon"


def test_the_sample_document_parses():
    sample = Path(__file__).parent / "fixtures" / "sample.json"
    assert json.loads(sample.read_text()) == {"branch": "daemon"}
"""

#: The two rows CI went red on, transcribed from fresh_clone.md. One per species
#: that the fleet actually produced - the ai_mail `if`/`else` and the daemon
#: class-constant handed bare to production.
_HOST_DEPENDENT_UNITS = """
def test_the_live_fleet_still_resolves_its_four_residents():
    projects_tree = reg.find_repo_root() / reg.RESIDENT_PROJECTS_DIR
    live = reg.get_resident_branches()
    if projects_tree.is_dir():
        assert set(live) == {"@baud", "@earmark"}
    else:
        assert live == {}, "no projects/ tree on this machine"


def test_the_branch_reports_the_two_documents_it_holds():
    result = mh.get_memory_health_status(str(BRANCH_ROOT), "DAEMON")
    assert sorted(result["structure_checks"]) == [".trinity/local.json"]
"""


def _clone_safe_project(root: Path) -> Path:
    """Six units, every one of them green on a stranger's machine."""
    _write(root, "tests/test_fresh_clone_shapes.py", _CLONE_SAFE_UNITS)
    return root


def _fresh_clone_project(root: Path) -> Path:
    """The same six clean units with the two fleet rows appended - eight, two flagged.

    One file rather than two, because the acquittals and the findings have to
    survive in each other's company: `sandbox_fixtures` and
    `fixture_built_spellings` are read once per FILE, and a per-file reader that
    only ever saw clean files would never be caught confusing them.
    """
    _write(root, "tests/test_fresh_clone_shapes.py", _CLONE_SAFE_UNITS + "\n\n" + _HOST_DEPENDENT_UNITS)
    return root


class TestFreshCloneDetection:
    """The three species, and the structural readings each one needs to see them.

    Each test names the one-line mutation of `fresh_clone_check` it was confirmed
    RED against, so a later reader can check the pin still bites rather than
    trusting that it once did.
    """

    def test_a_path_the_repo_refuses_to_ship_and_the_unit_never_builds_is_flagged(self, tmp_path):
        """IGNORED_PATH, and this shape is a proof that EVAPORATES rather than one that breaks.

        `**/*_json/` is ignored, so a clone has nothing under `daemon_json/` -
        and the assertion cannot go red there. It stays green forever, having
        stopped checking anything, which is worse than a loud failure because
        nobody finds out. The finding has to name the segment or a reader cannot
        tell which part of the path is the problem. Mutation caught:
        `IGNORED_SEGMENT_SUFFIXES: tuple = ("_json",)` becoming
        `IGNORED_SEGMENT_SUFFIXES: tuple = ()`, which leaves every runtime-JSON
        directory in the fleet invisible while the other two species look healthy.
        """
        _write(
            tmp_path,
            "tests/test_migration.py",
            """
            def test_the_original_data_files_are_gone():
                daemon_root = Path(__file__).resolve().parents[1]
                assert not (daemon_root / "daemon_json" / "schedule.json").exists()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))
        row = result["violations"][0]

        assert [r["species"] for r in result["violations"]] == ["IGNORED_PATH"]
        assert row["nodeid"] == "tests/test_migration.py::test_the_original_data_files_are_gone"
        assert "daemon_json" in row["detail"]
        assert ".gitignore" in row["detail"]

    def test_an_ignored_needle_is_read_segment_wise_and_never_as_a_substring(self, tmp_path):
        """`logs` is a directory, `catalogs.py` is a module, and one letter apart is not a rule.

        Both units below reach a path on the filesystem and only one of them
        names an ignored directory. A substring reading would convict the second
        for the four letters at the end of its filename, which is the kind of
        false positive that gets a whole standard switched off. Mutation caught:
        `if segment in IGNORED_SEGMENTS or segment in IGNORED_FILE_NAMES:` in
        `is_ignored_segment` becoming `if any(s in segment for s in
        IGNORED_SEGMENTS) or segment in IGNORED_FILE_NAMES:`, which flags both.
        """
        _write(
            tmp_path,
            "tests/test_audit.py",
            """
            def test_the_audit_log_is_written():
                root = Path(__file__).resolve().parents[1]
                assert (root / "logs" / "audit.json").exists()


            def test_the_catalog_module_is_shipped():
                root = Path(__file__).resolve().parents[1]
                assert (root / "apps" / "catalogs.py").exists()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert [row["nodeid"] for row in result["violations"]] == ["tests/test_audit.py::test_the_audit_log_is_written"]
        assert "'logs'" in result["violations"][0]["detail"]

    def test_an_oracle_that_is_a_runtime_if_on_the_machine_is_flagged(self, tmp_path):
        """BOTH_WORLDS: two assertions, two claims, and only one of them ever runs.

        Whichever arm this host selects is the only arm anybody reads; the other
        is prose wearing an assert. Nothing here names an ignored spelling, so
        the row can only come from the `if`/`else` reading and not from arm one
        riding along. Mutation caught: `if not isinstance(node, ast.If) or not
        node.orelse:` in `_both_worlds` becoming `if not isinstance(node,
        ast.If) or node.orelse:`, which walks past every branch that has the
        second arm this species is made of.
        """
        _write(
            tmp_path,
            "tests/test_handlers.py",
            """
            def test_the_handler_registry_matches_this_checkout():
                apps_tree = find_branch_root() / "apps"
                if apps_tree.is_dir():
                    assert sorted(handler_names()) == ["json_handler", "ruff_handler"]
                else:
                    assert handler_names() == []
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["BOTH_WORLDS"]
        assert (
            result["violations"][0]["nodeid"]
            == "tests/test_handlers.py::test_the_handler_registry_matches_this_checkout"
        )
        assert "asserts in both arms" in result["violations"][0]["detail"]

    def test_a_bare_machine_root_handed_to_production_under_a_written_expectation_is_flagged(self, tmp_path):
        """DERIVED_EXPECTED at its plainest: the host chose the value, the author typed it down.

        `find_repo_root()` answers a question about this checkout, and the list
        on the right of the compare was read off one terminal. Nothing about the
        READER is wrong; what is wrong is writing down what it happened to
        return here. Mutation caught: `"find_repo_root",` deleted from
        MACHINE_ROOT_CALLS, which is the single commonest spelling of the
        species and leaves the arm reporting nothing on this shape.
        """
        _write(
            tmp_path,
            "tests/test_registry.py",
            """
            def test_the_registry_lists_the_three_branches():
                root = find_repo_root()
                assert collect_branches(root) == ["@daemon", "@devpulse", "@seedgo"]
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["DERIVED_EXPECTED"]
        assert "find_repo_root" in result["violations"][0]["detail"]
        assert "collect_branches" in result["violations"][0]["detail"]

    def test_a_machine_root_reached_through_a_module_level_constant_is_resolved_one_hop(self, tmp_path):
        """ONE HOP, MODULE HALF - a reader that only knew local names calls this clean.

        The root is never spelled inside the unit at all: the unit says `ROOT`
        and the module says what `ROOT` is. This is the same single hop
        `host_state` spends to read a `parametrize` list, and without it the
        commonest way a test file names its own checkout is invisible. Mutation
        caught: `module_scope = _bound_names_in_body(parsed.tree.body)` in
        `find_host_dependent` becoming `module_scope = {}`.
        """
        _write(
            tmp_path,
            "tests/test_registry.py",
            """
            ROOT = Path(__file__).resolve().parents[1]


            def test_the_registry_lists_the_three_branches():
                assert collect_branches(ROOT) == ["@daemon", "@devpulse", "@seedgo"]
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["DERIVED_EXPECTED"]
        assert "Path(__file__).parents[...]" in result["violations"][0]["detail"]

    def test_a_directory_listed_for_its_contents_is_read_through_its_receiver(self, tmp_path):
        """A LISTING METHOD'S WORLD IS THE THING ON ITS LEFT, not something in its parentheses.

        `Path.cwd().iterdir()` hands production nothing and describes the whole
        machine anyway, so a reader that only inspected call ARGUMENTS would
        call the loudest shape of this species clean. Mutation caught: `if tail
        in LISTING_METHODS and isinstance(call.func, ast.Attribute): return
        [call.func.value]` in `_world_arguments` becoming `... return []`.
        """
        _write(
            tmp_path,
            "tests/test_tree.py",
            """
            def test_the_working_tree_holds_the_three_documents():
                assert sorted(p.name for p in Path.cwd().iterdir()) == ["a.json", "b.json", "c.json"]
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["DERIVED_EXPECTED"]
        assert "iterdir" in result["violations"][0]["detail"]


class TestFreshCloneTheTwoRowsCIWentRedOn:
    """The rule's own evidence, transcribed - and each red row beside its green sibling.

    A standard derived from two measured failures has to be able to reproduce
    them, or the derivation is a story. Both files below are the shape CI ran on
    2026-09-08, and in both of them the SAME file also contains code that gets it
    right - which is what makes each row a defect rather than a style opinion.
    """

    def test_row_one_the_live_fleet_resolver_is_flagged_and_its_tmp_path_sibling_is_not(self, tmp_path):
        """@ai_mail row 1, and the green sibling twelve lines above it in the real file.

        Same resolver, called two ways. The red one calls it with ZERO arguments
        and lets the host answer, then guards itself with `is_dir()` - which is
        TRUE on a clone, because `!projects/README.md` puts the directory there
        empty, so CI walked into the arm expecting four residents. The green one
        passes `tmp_path` and builds the tree it reads. One argument is the whole
        difference and both halves have to be pinned, or a narrowing that
        acquitted the red row would look like a win. Mutation caught:
        `_asserts_in(node.orelse)` in `_both_worlds` becoming `_asserts_in([])`,
        which stops the else arm counting as a second oracle and clears the row
        the rule was written for.
        """
        _write(
            tmp_path,
            "tests/test_cross_project_bridge.py",
            """
            class TestTheResidentTree:
                def test_the_live_fleet_still_resolves_its_four_residents(self):
                    projects_tree = reg.find_repo_root() / reg.RESIDENT_PROJECTS_DIR
                    live = reg.get_resident_branches()
                    if projects_tree.is_dir():
                        assert set(live) == {"@baud", "@earmark", "@finch", "@aipass_site"}, sorted(live)
                    else:
                        assert live == {}, "no projects/ tree on this machine - nothing may resolve"

                def test_a_passport_cannot_add_a_branch_no_registry_lists(self, tmp_path):
                    stray = tmp_path / "projects" / "ghost" / "src" / "ghost" / ".trinity"
                    stray.mkdir(parents=True)
                    assert reg.get_resident_branches(tmp_path) == {}
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["BOTH_WORLDS"]
        assert result["violations"][0]["nodeid"] == (
            "tests/test_cross_project_bridge.py::TestTheResidentTree::"
            "test_the_live_fleet_still_resolves_its_four_residents"
        )
        assert result["score"] == 50

    def test_row_two_the_class_constant_root_is_flagged_and_its_skip_guarded_siblings_are_not(self, tmp_path):
        """@daemon row 2: BRANCH_ROOT is a CLASS attribute, and two green siblings prove the shape.

        The root is assigned in the class body and referenced as
        `self.BRANCH_ROOT` in every method under it, so a reader that only knew
        module-level names would have called the red unit clean while it handed
        the live branch root to production. The two siblings carry an existence
        guard and a `pytest.skip`; they read the same machine and step aside
        when it is not theirs, which is `self_skip`'s business and not this
        rule's. Mutation caught: `scope.update(classes.get(unit.class_name,
        {}))` in `unit_scope` becoming `scope.update({})`.
        """
        _write(
            tmp_path,
            "tests/test_memory_health.py",
            """
            class TestRealTrinityFiles:
                BRANCH_ROOT = Path(__file__).resolve().parents[1]

                def test_real_branch_reports_no_structure_issues(self):
                    result = mh.get_memory_health_status(str(self.BRANCH_ROOT), "DAEMON")
                    assert sorted(result["structure_checks"]) == [
                        ".trinity/local.json",
                        ".trinity/observations.json",
                    ]

                def test_the_local_file_is_a_document(self):
                    local_file = self.BRANCH_ROOT / ".trinity" / "local.json"
                    if not local_file.exists():
                        pytest.skip("no live .trinity/local.json in this checkout")
                    assert json.loads(local_file.read_text())["branch"] == "daemon"

                def test_the_observations_file_is_a_document(self):
                    observations = self.BRANCH_ROOT / ".trinity" / "observations.json"
                    if not observations.exists():
                        pytest.skip("no live .trinity/observations.json in this checkout")
                    assert json.loads(observations.read_text())["entries"] == []
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["DERIVED_EXPECTED"]
        assert result["violations"][0]["nodeid"] == (
            "tests/test_memory_health.py::TestRealTrinityFiles::test_real_branch_reports_no_structure_issues"
        )
        assert "get_memory_health_status" in result["violations"][0]["detail"]


class TestFreshCloneAcquittals:
    """The difference between a rule and a nuisance - each one a measured false positive.

    The first run of this checker over the fleet produced 41 rows and the
    calibrated run produces 6. Every narrowing below took correct code off that
    list, and every one of them is a line a later edit could delete without any
    other test noticing. These are those tests.
    """

    def test_a_path_rooted_at_tmp_path_is_the_test_s_own_world(self, tmp_path):
        """NAMING AN IGNORED SPELLING ON PURPOSE IS THE CURE, so it must not be the finding.

        A test that builds `tmp_path / "projects" / "ghost"` is modelling the
        directory a clone has and ships nothing; pytest made that directory and
        pytest removes it. If the sandbox reading fails, the rule convicts the
        exact shape its own fix advice produces and there is nothing left to
        recommend. Mutation caught: `if _names_under(spine) & sandbox or
        _rooted_in_a_negated_region(spine, scope):` in `_ignored_path` becoming
        `if _rooted_in_a_negated_region(spine, scope):`.
        """
        _write(
            tmp_path,
            "tests/test_registry.py",
            """
            def test_a_stray_passport_resolves_nothing(tmp_path):
                assert not (tmp_path / "projects" / "ghost" / ".trinity" / "passport.json").exists()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_tuple_unpack_of_a_sandbox_helper_binds_every_name_it_makes(self, tmp_path):
        """NINE ROWS, @spawn AND @memory, and every one of them this single line.

        `project, reg = _make_project(tmp_path, ...)` binds two names off one
        sandbox-rooted call. A reader that only understood a bare `Name` target
        saw `project` appear from nowhere and called a temp directory live host
        state. Unpacking is generous - if any element is the sandbox, all of
        them carry the acquittal - and generous is the safe direction for a rule
        that accuses. Mutation caught: `for child in ast.walk(target):` in
        `_target_names` becoming `for child in [target]:`, which is the
        bare-Name reading that produced those nine rows.
        """
        _write(
            tmp_path,
            "tests/test_spawn.py",
            """
            def test_the_minted_citizen_carries_no_archive(tmp_path):
                project, reg = _make_project(tmp_path, "ghost")
                assert not (project / ".trinity" / "passport.json").exists()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_temp_test_dir_is_carried_by_name_because_the_fleet_template_roots_it_at_tmp_path(self, tmp_path):
        """A NAMED EXCEPTION WITH A REASON, and the reason is what has to survive an edit.

        `temp_test_dir` is not a pytest builtin. It is the fleet's own sandbox -
        `test_dir = tmp_path / "test_workspace"` in this pack's own conftest
        template, copied into branch conftests fleet-wide - and a conftest
        fixture is invisible to this reader by published limit. So the one name
        the whole fleet shares is listed beside the builtins. Measured: 1 @drone
        row. Mutation caught: `"temp_test_dir",` in SANDBOX_SEEDS becoming
        `"temp_test_dir_never",`.
        """
        _write(
            tmp_path,
            "tests/test_drone.py",
            """
            def test_project_root_message_does_not_claim_a_passport(temp_test_dir):
                assert not (temp_test_dir / "projects" / "ghost" / ".trinity").is_dir()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_nested_def_s_parameters_carry_the_sandbox_the_unit_already_built(self, tmp_path):
        """@memory's test_missing_file_skipped: the world is tmp_path all the way down.

        The unit builds a directory under `tmp_path`, puts its string into a
        dict, and hands that dict to a stand-in it defined three lines earlier.
        The only thing a static reader can see inside the stand-in is a
        parameter name - and a stand-in the test wrote is the test's own scope.
        Mutation caught: `bound |= _nested_parameter_names(unit_node)` in
        `_sandbox_names` becoming `bound |= set()`.
        """
        _write(
            tmp_path,
            "tests/test_memory.py",
            """
            def test_missing_file_skipped(tmp_path):
                branch_dir = tmp_path / "src" / "aipass" / "empty_branch"
                branch_dir.mkdir(parents=True)
                mock_branches = [{"name": "empty_branch", "path": str(branch_dir)}]

                def mock_get_path(branch, mem_type):
                    p = Path(branch["path"]) / ".trinity" / "local.json"
                    return p if p.exists() else None

                assert collect(mock_branches, mock_get_path) == []
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_nested_def_in_a_unit_that_names_no_sandbox_is_still_a_row(self, tmp_path):
        """THE GATE IS THE POINT - the pin above is worthless without this one.

        Spelled as a gate rather than a blanket precisely so that a stand-in
        reading real host state keeps its finding. Same file, same nested `def`,
        same `.trinity` read; the only difference is that the unit never names a
        sandbox, and the path in the dict is a machine path the author typed.
        Without this pin, widening the acquittal into a blanket - which is the
        obvious simplification of the two-line gate - passes every other test in
        this class. Mutation caught: `if _names_under(unit_node) & bound:` in
        `_sandbox_names` becoming `if True:`.
        """
        _write(
            tmp_path,
            "tests/test_memory.py",
            """
            def test_missing_file_skipped():
                mock_branches = [{"name": "daemon", "path": "/srv/aipass/src/aipass/daemon"}]

                def mock_get_path(branch, mem_type):
                    p = Path(branch["path"]) / ".trinity" / "local.json"
                    return p if p.exists() else None

                assert collect(mock_branches, mock_get_path) == []
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert [row["species"] for row in result["violations"]] == ["IGNORED_PATH"]
        assert result["violations"][0]["nodeid"] == "tests/test_memory.py::test_missing_file_skipped"

    def test_a_spelling_the_unit_builds_itself_is_a_world_it_made(self, tmp_path):
        """THE CURE THE RULE TEACHES SECOND: build the tree, then read it.

        A `mkdir` on a path carrying the same ignored segment means the world
        under the assertion is the world the test made, on any machine, whatever
        it is rooted at. Convicting this shape would leave a branch no way to
        please the checker except by deleting the assertion. Mutation caught:
        `if on_receiver and tail in BUILDING_METHODS:` in `_call_role` becoming
        `if on_receiver and tail in set():`, which stops `mkdir`, `write_text`
        and `touch` counting as construction at all.
        """
        _write(
            tmp_path,
            "tests/test_health.py",
            """
            def test_a_planted_observation_file_is_read_back():
                home = Path(__file__).resolve().parents[1] / "fixtures" / "branch"
                (home / ".trinity").mkdir(parents=True, exist_ok=True)
                assert not (home / ".trinity" / "observations.json").exists()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_spelling_a_same_file_fixture_builds_acquits_the_units_that_request_it(self, tmp_path):
        """THE BUILD IS ROUTINELY ONE FRAME UP, which is where pytest users put it.

        The fixture makes the directory and the unit reads it; neither half is
        wrong and neither half is complete on its own. Read once per FILE rather
        than once per unit, because a rule the audit engine runs on eighteen
        branches cannot afford to re-parse six fixtures for each of a file's
        four hundred units. Mutation caught: `built |= (fixture_built or
        {}).get(name, set())` in `unit_flags` becoming `built |= set()`.
        """
        _write(
            tmp_path,
            "tests/test_planted.py",
            """
            @pytest.fixture
            def planted():
                home = Path(__file__).resolve().parents[1] / "fixtures"
                (home / ".trinity").mkdir(parents=True, exist_ok=True)
                return home


            def test_the_planted_tree_is_read_back(planted):
                assert not (planted / ".trinity" / "observations.json").exists()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_sandbox_handed_out_through_a_chain_of_fixtures_is_followed_to_a_fixed_point(self, tmp_path):
        """SIX @ai_mail ROWS, and a single hop would still miss every one of them.

        `hosted_baud` requests `repo_root`, and `repo_root` is the one that
        requests `tmp_path`; the unit then reads `projects/` under a directory
        that is two frames from the sandbox. Declared out of order here on
        purpose - the fixed point must not depend on a fixture being defined
        after the one it uses, which a single ordered pass would. Mutation
        caught: `& (SANDBOX_SEEDS | found)):` in `sandbox_fixtures` becoming `&
        SANDBOX_SEEDS):`, which finds `repo_root` and never reaches
        `hosted_baud`.
        """
        _write(
            tmp_path,
            "tests/test_cross_project_bridge.py",
            """
            @pytest.fixture
            def hosted_baud(repo_root):
                return repo_root


            @pytest.fixture
            def repo_root(tmp_path):
                return tmp_path


            def test_the_registry_lists_what_the_tree_holds(hosted_baud):
                assert not (hosted_baud / "projects" / "baud" / "registry.json").exists()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_path_reached_through_a_negated_region_is_shipped_on_purpose(self, tmp_path):
        """FLAGGING A TEMPLATE PASSPORT IS EXACTLY BACKWARDS - the ignore file re-admits it.

        The root `.gitignore`'s only `!` lines put
        `src/aipass/spawn/templates/*/.trinity/**` back, with a comment saying a
        template must ship WHOLE. A frozen needle list cannot express a
        negation, so the negated REGION is spelled by the root's name instead
        and read one hop through the unit's own assignment. Measured: 7 @spawn
        rows, every one a template passport read. Mutation caught:
        `NEGATED_ROOT_SPELLINGS: tuple = ("template",)` becoming
        `NEGATED_ROOT_SPELLINGS: tuple = ()`.
        """
        _write(
            tmp_path,
            "tests/test_spawn.py",
            """
            def test_the_template_ships_its_passport():
                tpl = get_template_dir()
                assert (tpl / ".trinity" / "passport.json").is_file()
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_skip_guarded_unit_belongs_to_self_skip_and_is_left_alone_here(self, tmp_path):
        """ONE DEFECT MUST NOT PRODUCE TWO FINDINGS UNDER TWO STANDARDS.

        A test carrying `pytest.skip` behind an existence check has already
        declared that it reads the host; whether that skip is honest is
        `self_skip`'s question. A fleet that gets two findings for one line
        starts discounting both, and the unit below is otherwise a textbook
        IGNORED_PATH - it reads `.trinity/local.json` off a class-constant
        branch root. Mutation caught: `return bool(calls & SKIP_CALLS) and
        bool(_existence_probe(unit.node))` in `skip_guarded` becoming `return
        bool(calls & set()) and bool(_existence_probe(unit.node))`.
        """
        _write(
            tmp_path,
            "tests/test_memory_health.py",
            """
            class TestRealTrinityFiles:
                BRANCH_ROOT = Path(__file__).resolve().parents[1]

                def test_the_local_file_is_a_document(self):
                    local_file = self.BRANCH_ROOT / ".trinity" / "local.json"
                    if not local_file.exists():
                        pytest.skip("no live .trinity/local.json in this checkout")
                    assert json.loads(local_file.read_text())["branch"] == "daemon"
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_machine_root_carrying_a_literal_segment_is_not_a_candidate_at_all(self, tmp_path):
        """BARE IS THE WHOLE NARROWING, and this is the half that keeps fixtures legal.

        `Path(__file__).parent / "fixtures" / "sample.json"` is machine-rooted
        and perfectly fresh-clone safe: the repo SHIPS that file, so every
        machine reads the same bytes. What is not safe is handing a DIRECTORY to
        production and pinning what production found in it. Without this clause
        every fixture-file test in the fleet is a DERIVED_EXPECTED row. Mutation
        caught: `if not seed or any(_holds_a_literal(form) for form in forms):`
        in `bare_machine_root` becoming `if not seed:`.
        """
        _write(
            tmp_path,
            "tests/test_fixtures.py",
            """
            def test_the_sample_document_parses():
                sample = Path(__file__).parent / "fixtures" / "sample.json"
                assert json.loads(sample.read_text()) == {"branch": "daemon"}
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_an_unclimbed_dunder_file_is_the_running_test_which_the_repo_ships(self, tmp_path):
        """SEVEN ROWS ACROSS @backup, @commons AND @devpulse, all of them correct code.

        `__file__` alone names the running test file, and the repo ships it by
        definition - it IS the test. Only `.parent`, `.parents` or
        `os.path.dirname` reaches a directory whose contents are this checkout's
        business. `module_file(__file__)` is a resolver handed its own module
        path and runs identically on a clone. Mutation caught: `if
        _climbs_to_a_directory(expr) and any(` in `_machine_root_seed` becoming
        `if any(`.
        """
        _write(
            tmp_path,
            "tests/test_backup.py",
            """
            def test_the_module_reader_names_the_handlers_it_was_given():
                assert sorted(declared_handlers(__file__)) == ["json_handler", "ruff_handler"]
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_property_assertion_is_not_an_expected_value_and_a_written_list_is(self, tmp_path):
        """FOUR FAMILIES CAME OFF THE FLEET FOR THIS ONE WORD, and it is what makes the species name true.

        Both projects hand the same bare machine root to the same production
        call. The first asserts that two implementations agree - which answers
        the same on every machine, because nobody wrote a machine's answer down.
        The second pins a list read off one terminal. Only the second is a
        DERIVED_EXPECTED, and pinning only the clean half would let a mutation
        that reports nothing at all look like a narrowing. Mutation caught: `if
        any(_is_written_down(side) for side in [child.left,
        *child.comparators]):` in `pins_a_written_expectation` becoming `if
        True:`, which flags the property assertion too.
        """
        properties, written = tmp_path / "properties", tmp_path / "written"
        _write(
            properties,
            "tests/test_drone.py",
            """
            def test_the_two_readers_agree_on_this_checkout():
                root = find_repo_root()
                assert collect_branches(root) == collect_branches_v2(root)
            """,
        )
        _write(
            written,
            "tests/test_drone.py",
            """
            def test_the_two_readers_agree_on_this_checkout():
                root = find_repo_root()
                assert collect_branches(root) == ["@daemon", "@devpulse", "@seedgo"]
            """,
        )

        clean = fresh_clone_check.check_branch(str(properties))
        flagged = fresh_clone_check.check_branch(str(written))

        assert clean["violations"] == []
        assert [row["species"] for row in flagged["violations"]] == ["DERIVED_EXPECTED"]

    def test_a_spelling_handed_to_a_parser_is_a_string_and_not_a_directory_this_unit_opened(self, tmp_path):
        """ELEVEN CORRECT @ai_mail UNITS, convicted on the first run for a path they never reached.

        The path has to be REACHED on the filesystem - `exists`, `iterdir`,
        `read_text`, `open`, `os.listdir` - not merely spelled. A machine-rooted
        string handed to a PARSER is data being fed to the code under test, and
        the parser is what the test is about. Reading spellings rather than
        reaches is the single largest false-positive family this rule has.
        Mutation caught: `if _role_of(literal, parents, uses) != "read":` in
        `_ignored_path` becoming `if False:`.
        """
        _write(
            tmp_path,
            "tests/test_inbox.py",
            """
            def test_the_inbox_document_parses():
                document = parse_document(Path("/srv/aipass/branch/.ai_mail.local/inbox.json"))
                assert document["branch"] == "daemon"
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_an_existence_branch_that_asserts_in_only_one_arm_is_not_two_oracles(self, tmp_path):
        """BOTH arms have to assert, or the shape is an ordinary guard and not a second claim.

        A branch whose else arm calls `pytest.fail` states ONE thing: the
        directory must be there. That is a test with one oracle, which is what
        this rule is asking for everywhere else - reporting it would mean the
        rule flags the strict version of its own advice. Mutation caught: `if
        not (_asserts_in(node.body) and _asserts_in(node.orelse)):` in
        `_both_worlds` becoming `if not _asserts_in(node.body):`.
        """
        _write(
            tmp_path,
            "tests/test_bridge.py",
            """
            def test_the_apps_tree_resolves_what_it_holds():
                apps_tree = find_repo_root() / "apps"
                if apps_tree.is_dir():
                    assert set(handler_names()) == {"json_handler"}
                else:
                    pytest.fail("no apps tree on this machine")
            """,
        )

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100


class TestFreshCloneBranchCheck:
    """The scoring-API contract, and the two paths where silence reads as clean."""

    def test_the_score_is_the_share_of_units_that_read_only_what_the_repo_ships(self, tmp_path):
        """The number is clean-over-total, counted per unit, and six acquittals hold it up.

        Two of the eight units are the rows CI went red on; the other six are
        clean for six DIFFERENT reasons, so a mutation that collapses any single
        acquittal moves this number and cannot hide behind the other five. An
        inverted numerator still moves plausibly with a tree, which is why the
        pin carries the sentence a reader gets as well as the number. Mutation
        caught: `score = int(((total - len(flagged)) / total) * 100)` becoming
        `score = int((len(flagged) / total) * 100)`, which reports 25 where the
        honest answer is 75.
        """
        result = fresh_clone_check.check_branch(str(_fresh_clone_project(tmp_path)))

        assert result["score"] == 75
        assert len(result["violations"]) == 2
        assert (
            "2/8 test units take their answer from state a fresh clone does not have" in result["checks"][0]["message"]
        )

    def test_a_project_whose_every_unit_builds_its_own_world_scores_one_hundred(self, tmp_path):
        """A CLEAN PROJECT HAS TO SAY SO IN ITS OWN WORDS, not merely produce no rows.

        Zero rows and a 100 are the easy half; the sentence is the half a reader
        actually sees on a board, and a check that printed the flagged wording
        with an empty list after it would read as a broken rule rather than a
        clean project. All six clone-safe shapes are here at once, which is also
        the only place any of them is asserted in the company of the others.
        Mutation caught: the message ternary's `if not flagged` becoming `if
        flagged`, which prints "0/6 test units take their answer from state a
        fresh clone does not have: " over a project that has none.
        """
        result = fresh_clone_check.check_branch(str(_clone_safe_project(tmp_path)))

        assert result["violations"] == []
        assert result["score"] == 100
        assert result["checks"][0]["passed"] is True
        assert result["checks"][0]["message"] == "6/6 test units read only what the repo ships"

    def test_a_unit_carrying_two_species_is_one_row_and_two_units_carrying_one_each_are_two(self, tmp_path):
        """A SCORE THAT CAN GO NEGATIVE IS ONE NOBODY BELIEVES TWICE.

        The first project holds ONE unit that branches on the machine AND pins a
        written-down value off a bare root - both species, one place for a
        reader to go and look. The second project splits those same two shapes
        across two units. One row against two is the whole claim, and the second
        project is what stops a mutation that simply reports less from passing
        as the per-unit rule. Mutation caught: `if row["nodeid"] not in seen:`
        in `find_host_dependent` becoming `if True:`, which returns two rows for
        the single unit and would let one path-heavy test drive a project below
        zero.
        """
        together, apart = tmp_path / "together", tmp_path / "apart"
        _write(
            together,
            "tests/test_health.py",
            """
            def test_the_branch_reports_its_documents():
                root = find_repo_root()
                if (root / "apps").is_dir():
                    assert read_health(root) == ["ok"]
                else:
                    assert read_health(root) == []
            """,
        )
        _write(
            apart,
            "tests/test_health.py",
            """
            def test_the_branch_reports_what_this_checkout_holds():
                if find_repo_root().is_dir():
                    assert read_health() == ["ok"]
                else:
                    assert read_health() == []


            def test_the_health_reader_names_the_documents():
                assert read_health(find_repo_root()) == ["ok"]
            """,
        )

        one_unit = fresh_clone_check.check_branch(str(together))
        two_units = fresh_clone_check.check_branch(str(apart))

        assert [row["species"] for row in one_unit["violations"]] == ["BOTH_WORLDS"]
        assert one_unit["score"] == 0
        assert [row["species"] for row in two_units["violations"]] == ["BOTH_WORLDS", "DERIVED_EXPECTED"]

    def test_the_result_passes_and_stays_advisory_even_when_units_are_flagged(self, tmp_path):
        """A REPORT IS NOT A VERDICT - this rule nominates and a human decides.

        Top-level `passed` must stay True while flags exist and `advisory` must
        stay True, so a caller can tell the two apart; the standard name and the
        violations list are the rest of the contract every rule in this pack
        answers. A flagged site may be perfectly safe for a reason this checker
        cannot see - a project that ships the directory anyway, a CI stage that
        populates it first - which is exactly why it must not fail a board.
        Mutation caught: `"passed": True,` becoming `"passed": not flagged,` in
        the scored return, which turns an advisory into a board failure on every
        branch that has one of these sites.
        """
        result = fresh_clone_check.check_branch(str(_fresh_clone_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "FRESH_CLONE"
        assert result["checks"][0]["name"] == "Fresh clone survivable"
        assert result["checks"][0]["passed"] is False
        assert sorted(result) == ["advisory", "checks", "passed", "score", "standard", "violations"]

    def test_a_project_with_no_test_files_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        A 0 blames a project for a fact about its layout and a 100 claims a
        measurement that never happened. Each check in this pack carries its own
        copy of the early return, so each one has to be pinned - and losing it
        here does not return a wrong number, it divides by zero and takes the
        caller with it. Mutation caught: `"not_applicable": True,` becoming
        `"not_applicable": False,` in the `total == 0` return.
        """
        _write(tmp_path, "apps/registry.py", "def find_repo_root():\n    return Path.cwd()")

        result = fresh_clone_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert result["score"] == 0
        assert "no test files found" in result["checks"][0]["message"]

    def test_an_unparseable_test_file_is_named_beside_a_scored_result(self, tmp_path):
        """AN UNREAD FILE FLAGS NOTHING, so for THIS rule silence biases toward clean.

        The early-return path carries the unreadable line by construction; the
        scored path has to append it deliberately, and dropping that one line
        leaves a branch with a healthy number and no hint that a file was never
        read at all. The message has to say NOT measured, not merely name the
        file. Mutation caught: `checks.extend(unreadable)` becoming
        `checks.extend([])`.
        """
        _fresh_clone_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = fresh_clone_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 75
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]

    def test_only_twelve_flagged_units_are_named_and_the_rest_are_counted(self, tmp_path):
        """A CHECK MESSAGE PRINTING HUNDREDS OF LINES IS ONE NOBODY READS.

        Fourteen flagged units, twelve named, and the remainder stated as a
        number rather than dropped - a truncation that did not say it had
        truncated would understate a branch's problem to every reader of the
        board while the score stayed honest. The violations list itself is never
        truncated, because the report artifact is where the full list lives.
        Mutation caught: `MAX_REPORTED: int = 12` becoming `MAX_REPORTED: int =
        24`, which names all fourteen and prints no remainder.
        """
        units = "\n\n\n".join(
            f"def test_row_{index:02d}():\n"
            f"    root = find_repo_root()\n"
            f'    assert collect_branches(root) == ["row-{index:02d}"]'
            for index in range(14)
        )
        _write(tmp_path, "tests/test_many.py", units)

        result = fresh_clone_check.check_branch(str(tmp_path))
        message = result["checks"][0]["message"]

        assert len(result["violations"]) == 14
        assert message.count("::test_row_") == 12
        assert message.endswith("(+2 more)")


# =============================================================================
# PLATFORM ORACLE - IS THE VERDICT ABOUT THE CODE, OR ABOUT THE HOST
# =============================================================================

from aipass.seedgo.apps.handlers.pytest_quality_standards import platform_oracle_check  # noqa: E402

# NOTHING IN THIS SECTION ASKS THIS MACHINE ANYTHING, and the rule under test is
# the reason that has to be written down rather than assumed. A pin for a checker
# about listing order, mode bits, TEMP short names and `Path.cwd` is the one place
# in this file where a real `rglob` over the repo, a real `chmod`, a real
# `/dev/null` write or a real `os.getcwd()` would read as ordinary setup. There is
# none: every project below is source TEXT written into tmp_path, and every
# assertion is about what the CHECKER reported over that text. No `os.name`, no
# `sys.platform`, no separator and no directory order read from the running host,
# on any line - a pin for THIS rule that broke this rule would be the joke telling
# itself, and it would also be the first thing to go red on the Windows leg.

#: The two rows the rule was written for, transcribed from platform_oracle.md.
#: @skills sorting Paths off an rglob, and @hooks asking the kernel for an
#: ENOTDIR by using /dev/null as a DIRECTORY. Both score.
_ORACLE_SCORED_UNITS = """
def test_the_two_files_are_laid_down(tmp_path):
    files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    assert [f.name for f in files] == ["SKILL.md", "handler.py"]


def test_the_unwritable_log_is_reported():
    impossible = Path("/dev/null/impossible/log.jsonl")
    with patch(LOGGER_PATCH) as mock_logger:
        _write_delivery_log(impossible)
    assert mock_logger.warning.call_count == 1
"""

#: One row per nominate-only species, each transcribed from the branch the
#: dossier measured it on - @drone's subprocess launch, @spawn's
#: TemporaryDirectory equality, @prax's sealed cwd behind a `_patch` alias.
#: NONE of these may move a number.
_ORACLE_NOMINATED_UNITS = """
def test_the_missing_executable_is_named():
    with pytest.raises(RuntimeError) as exc_info:
        run_executor("this_executable_does_not_exist_xyz")
    cause = exc_info.value.__cause__
    assert cause.filename == "this_executable_does_not_exist_xyz"


def test_the_agent_reports_where_it_landed():
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "init_test"
        landed = _spawn_agent(str(target))
        assert Path(landed["path"]) == target


def test_the_dashboard_names_the_branch(tmp_path, capsys):
    with _patch("pathlib.Path.cwd", return_value=tmp_path):
        mod._handle_refresh([])
    assert tmp_path.name.upper() in capsys.readouterr().out
"""

#: Three units that are clean for three DIFFERENT reasons - a sort with an
#: explicit key, a failure injected at a patched seam, a sandbox rebound through
#: a resolver. Written this way on purpose: a project whose clean units were
#: clean for the SAME reason would still score 100 with two of the three
#: acquittals deleted.
_ORACLE_CLEAN_UNITS = """
def test_the_listing_is_sorted_by_a_key(tmp_path):
    files = sorted((p for p in tmp_path.rglob("*") if p.is_file()), key=str)
    assert [f.name for f in files] == ["SKILL.md", "handler.py"]


def test_the_write_failure_is_injected_at_the_seam(tmp_path):
    target = tmp_path / "delivery.jsonl"
    with patch("apps.writer.Path.write_text", side_effect=OSError("no")):
        with patch(LOGGER_PATCH) as mock_logger:
            _write_delivery_log(target)
    assert mock_logger.warning.call_count == 1


def test_the_sandbox_is_resolved_before_it_is_compared(tmp_path):
    tmp_path = tmp_path.resolve()
    landed = _spawn_agent(str(tmp_path))
    assert Path(landed["path"]) == tmp_path / "init_test"
"""


def _platform_oracle_project(root: Path) -> Path:
    """Eight units: two that score, three that only nominate, three that are clean.

    ONE FILE RATHER THAN THREE, because the acquittals, the scored rows and the
    nominations have to survive in each other's company. The split this rule
    lives or dies by is a claim about a project holding all three kinds at once,
    and a per-species reader that only ever saw one kind of file would never be
    caught letting a nomination leak into the number.
    """
    _write(
        root,
        "tests/test_platform_shapes.py",
        _ORACLE_SCORED_UNITS + "\n\n" + _ORACLE_NOMINATED_UNITS + "\n\n" + _ORACLE_CLEAN_UNITS,
    )
    return root


def _oracle_nominations_only_project(root: Path) -> Path:
    """Three units, one per nominate-only species, and nothing that scores."""
    _write(root, "tests/test_platform_shapes.py", _ORACLE_NOMINATED_UNITS)
    return root


def _oracle_clean_project(root: Path) -> Path:
    """Three units, no finding of any species at all."""
    _write(root, "tests/test_platform_shapes.py", _ORACLE_CLEAN_UNITS)
    return root


class TestPlatformOracleDetection:
    """The five species, and the structural readings each one needs to see them.

    Each test names the one-line mutation of `platform_oracle_check` it was
    confirmed RED against, so a later reader can check the pin still bites rather
    than trusting that it once did.
    """

    def test_a_sorted_listing_compared_with_a_list_literal_is_flagged(self, tmp_path):
        """THE ROW THIS RULE WAS WRITTEN FOR - sorted() did not save it.

        `sorted()` over PATH objects uses `PurePath.__lt__`, which is
        case-SENSITIVE on POSIX and case-FOLDED under ntpath: POSIX puts
        `SKILL.md` first because `'S' < 'h'`, Windows folds the case and hands
        back the other order. Production laid down the same two files on both
        legs; the pin is what disagreed. The finding has to name the listing call
        or a reader cannot tell which side came from the filesystem. Mutation
        caught: `LISTING_CALLS: frozenset = frozenset({"iterdir", "listdir",
        "glob", "rglob", "scandir", "walk"})` becoming the same set without
        `"rglob"`, which acquits the exact shape the rule exists for.
        """
        _write(
            tmp_path,
            "tests/test_template.py",
            """
            def test_the_two_files_are_laid_down(tmp_path):
                files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
                assert [f.name for f in files] == ["SKILL.md", "handler.py"]
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))
        row = result["violations"][0]

        assert [r["species"] for r in result["violations"]] == ["LISTING_ORDER"]
        assert row["nodeid"] == "tests/test_template.py::test_the_two_files_are_laid_down"
        assert "rglob" in row["detail"]
        assert "2-element list literal" in row["detail"]

    def test_a_listing_compared_without_a_binding_hop_is_read_directly(self, tmp_path):
        """THE HOP IS AN EXTENSION OF THE READING, NOT THE WHOLE OF IT.

        `_listing_names` exists because the fleet row binds `files` on one line
        and compares it on the next, and a reader built only for that shape would
        miss the same defect written in one line. Both readings have to be live
        or the arm is one refactor of the corpus away from silence. Mutation
        caught: `return _listing_call(node) or _inherited_listing(node, listing)`
        in `_listing_source` becoming `return _inherited_listing(node, listing)`,
        which keeps the hop and loses the direct read.
        """
        _write(
            tmp_path,
            "tests/test_template.py",
            """
            def test_the_two_files_are_laid_down(tmp_path):
                assert sorted(tmp_path.iterdir()) == [tmp_path / "SKILL.md", tmp_path / "handler.py"]
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["violations"]] == ["LISTING_ORDER"]
        assert "iterdir" in result["violations"][0]["detail"]

    def test_a_listing_reached_only_through_a_bound_name_is_still_read(self, tmp_path):
        """ONE HOP, AND THE LISTING'S OWN SPELLING TRAVELS WITH THE NAME.

        The row walks its rglob result twice - `files = sorted(...)` and then
        `for f in files` - so a set-valued reading had two names to choose from
        and named the loop variable. A reader told the other side "came from f"
        has been told nothing, which is why `_listing_names` is a dict. Mutation
        caught: `for name in sorted(_names_under(value) & set(named)): return
        named[name]` in `_inherited_listing` becoming `return ""`, which drops
        the hop and leaves the fleet's only LISTING_ORDER row invisible.
        """
        _write(
            tmp_path,
            "tests/test_template.py",
            """
            def test_the_two_files_are_laid_down(tmp_path):
                files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
                names = [f.name for f in files]
                assert names == ["SKILL.md", "handler.py"]
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["violations"]] == ["LISTING_ORDER"]
        assert "rglob" in result["violations"][0]["detail"]

    def test_a_posix_device_path_used_as_an_injector_is_flagged(self, tmp_path):
        """MODE_INJECTOR, and the fleet row is purer than a chmod.

        `/dev/null/impossible/log.jsonl` is null used as a DIRECTORY, which is an
        ENOTDIR only POSIX has to give. Windows has no such semantics, so the
        write SUCCEEDS, nothing is reported, and the must-warn assertion sees
        ZERO calls while the code under test behaves perfectly - a claim that
        silently inverts rather than one that goes red. Mutation caught:
        `DEVICE_PATH_PREFIXES: tuple = ("/dev/null/", "/dev/full", "/dev/zero/",
        "/proc/", "/sys/")` becoming `DEVICE_PATH_PREFIXES: tuple = ()`.
        """
        _write(
            tmp_path,
            "tests/test_telegram_response.py",
            """
            def test_the_unwritable_log_is_reported():
                impossible = Path("/dev/null/impossible/log.jsonl")
                with patch(LOGGER_PATCH) as mock_logger:
                    _write_delivery_log(impossible)
                assert mock_logger.warning.call_count == 1
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))
        row = result["violations"][0]

        assert [r["species"] for r in result["violations"]] == ["MODE_INJECTOR"]
        assert "/dev/null/impossible/log.jsonl" in row["detail"]
        assert "patched seam" in row["detail"]

    def test_a_chmod_to_a_mode_with_no_owner_write_bit_is_flagged(self, tmp_path):
        """The other half of MODE_INJECTOR: the kernel is asked for a favour.

        Windows ignores POSIX mode bits for the owner, so `0o444` refuses nothing
        there and the `pytest.raises` under it fails on a runner where production
        is fine. The mode is read as the LAST positional argument, which covers
        `os.chmod(p, m)` and `p.chmod(m)` in one reading. Mutation caught:
        `return "" if node.value & OWNER_WRITE_BIT else oct(node.value)` in
        `_readonly_mode` becoming `return ""`, which makes every integer mode in
        the fleet writable and silences the arm's whole int branch.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_a_read_only_target_is_reported(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(0o444)
                with pytest.raises(PermissionError):
                    _write_delivery_log(target)
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["violations"]] == ["MODE_INJECTOR"]
        assert "chmod to 0o444" in result["violations"][0]["detail"]

    def test_a_stat_constant_carrying_no_write_name_is_flagged(self, tmp_path):
        """The mode arm's second reading: a symbolic mode, read by its NAMES.

        `S_IREAD | S_IRGRP` is `0o440` and a reader that only understood integer
        literals would call it clean - which is the spelling a careful author
        reaches for precisely because it says what it means. The names are read
        rather than evaluated, because this rule never asks the running machine
        anything. The dotted spelling has its own pin below, because for one
        afternoon it was a hole. Mutation caught: `_mode_spellings`'s
        `if name.startswith("S_I")` becoming `if name.startswith("S_X")`.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_a_read_only_mode_is_reported(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(S_IREAD | S_IRGRP)
                with pytest.raises(PermissionError):
                    _write_delivery_log(target)
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["violations"]] == ["MODE_INJECTOR"]
        assert "S_IREAD" in result["violations"][0]["detail"]

    def test_the_same_mode_written_with_its_module_prefix_is_flagged_the_same(self, tmp_path):
        """TWO SPELLINGS OF ONE MODE, AND THE DEFECT THIS PIN WAS BORN FROM.

        Found while pinning this arm, 2026-09-08: `_names_under` collects bare
        names and dotted CALL targets - which is what its seven other readers
        want - and no plain attribute, so `stat.S_IREAD | stat.S_IRGRP` reached
        the mode reading as the single name `stat` and came back clean. The two
        units below differ in NOTHING but that prefix; before the cure the bare
        one scored 0 and the dotted one scored 100, while `platform_oracle.md`
        printed the dotted form as the shape it flags. Cured with a reader of its
        own, `_mode_spellings`, so the other seven call sites did not move.
        Mutation caught: `_mode_spellings`'s `elif isinstance(child,
        ast.Attribute): found.add(child.attr)` deleted - the dotted unit goes
        clean again and this pin goes red while the bare pin above stays green.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_a_read_only_mode_is_reported(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(stat.S_IREAD | stat.S_IRGRP)
                with pytest.raises(PermissionError):
                    _write_delivery_log(target)

            def test_a_mode_that_keeps_the_write_bit_is_not_reported(tmp_path):
                target = tmp_path / "other.jsonl"
                target.chmod(stat.S_IRUSR | stat.S_IWUSR)
                _write_delivery_log(target)
                assert target.read_text()
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["violations"]] == ["MODE_INJECTOR"]
        assert result["violations"][0]["nodeid"].endswith("test_a_read_only_mode_is_reported")
        assert "S_IREAD" in result["violations"][0]["detail"]

    def test_an_assertion_on_an_os_filled_exception_attribute_is_nominated(self, tmp_path):
        """OSERROR_ATTRIBUTE, and the hop that reaches @drone's row.

        `cause = exc_info.value.__cause__` puts the OS-filled exception in a
        SECOND name and the assertion is written against that one, so a reader
        that only knew the `pytest.raises` capture would call it clean. The
        finding has to spell out what `.filename` does on the other leg -
        "it differs" is not something a reader can act on - and this row is
        NOMINATED, never scored. Mutation caught: `OSERROR_ATTRIBUTES: frozenset
        = frozenset({"filename", "filename2", "strerror", "errno", "winerror"})`
        becoming the same set without `"filename"`.
        """
        _write(
            tmp_path,
            "tests/test_executor.py",
            """
            def test_the_missing_executable_is_named():
                with pytest.raises(RuntimeError) as exc_info:
                    run_executor("this_executable_does_not_exist_xyz")
                cause = exc_info.value.__cause__
                assert cause.filename == "this_executable_does_not_exist_xyz"
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))
        row = result["nominations"][0]

        assert result["violations"] == []
        assert [r["species"] for r in result["nominations"]] == ["OSERROR_ATTRIBUTE"]
        assert row["nodeid"] == "tests/test_executor.py::test_the_missing_executable_is_named"
        assert "filename=None" in row["detail"]

    def test_an_unresolved_temp_path_equality_is_nominated(self, tmp_path):
        """UNRESOLVED_TMP_PATH, minted outside the pytest fixture.

        @spawn's row uses `tempfile.TemporaryDirectory()`, not `tmp_path`, and
        the hazard is identical: the Windows runner's TEMP is an 8.3 short name
        (`RUNNER~1`) until something resolves it, the code under test resolves
        what it hands back, and `Path == Path` compares TEXT. A reader seeded
        only with the pytest fixture names would call the row clean. Mutation
        caught: `TEMPDIR_MAKERS: frozenset = frozenset({...})` becoming
        `TEMPDIR_MAKERS: frozenset = frozenset()`.
        """
        _write(
            tmp_path,
            "tests/test_contracts.py",
            """
            def test_the_agent_reports_where_it_landed():
                with tempfile.TemporaryDirectory() as td:
                    target = Path(td) / "init_test"
                    landed = _spawn_agent(str(target))
                    assert Path(landed["path"]) == target
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert [r["species"] for r in result["nominations"]] == ["UNRESOLVED_TMP_PATH"]
        assert "8.3 short name" in result["nominations"][0]["detail"]

    def test_a_sealed_cwd_beside_a_rendered_name_is_nominated(self, tmp_path):
        """SHALLOW_SANDBOX: the seam is one level too shallow.

        Sealing `cwd` onto a temp directory does not seal what is ABOVE it. On
        Windows TEMP lives under the user profile, so a production walk upward
        can reach the profile directory and the rendered name comes back
        `RUNNERADMIN`; `/tmp` has no such ancestor, which is why the same unit is
        green here forever. It NOMINATES, because whether production walks up is
        a fact about production and this checker reads test units. Mutation
        caught: `CWD_SEAM_NEEDLES: tuple = ("Path.cwd", "os.getcwd", "getcwdb",
        "pathlib.Path.cwd")` becoming `CWD_SEAM_NEEDLES: tuple = ()`.
        """
        _write(
            tmp_path,
            "tests/test_operations.py",
            """
            def test_the_dashboard_names_the_branch(tmp_path, capsys):
                with _patch("pathlib.Path.cwd", return_value=tmp_path):
                    mod._handle_refresh([])
                assert tmp_path.name.upper() in capsys.readouterr().out
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert [r["species"] for r in result["nominations"]] == ["SHALLOW_SANDBOX"]
        assert "pathlib.Path.cwd" in result["nominations"][0]["detail"]

    def test_a_locally_aliased_patch_still_counts_as_a_seal(self, tmp_path):
        """SHALLOW_SANDBOX MEASURED ZERO BEFORE THIS, and the alias is why.

        The two rows this species exists for are written `from unittest.mock
        import patch as _patch`, because the units already take a `monkeypatch`
        fixture and the author wanted the two spellings to read apart. A reader
        keyed on the exact name `patch` saw no seal at all and called both rows
        clean - the arm reported 0 and looked healthy. Mutation caught: `return
        tail in {"patch", "object", "dict"} or tail.endswith("_patch")` in
        `_is_patching_call` becoming `return tail in {"patch", "object", "dict"}`,
        which takes the arm back to the zero it started at.
        """
        _write(
            tmp_path,
            "tests/test_operations.py",
            """
            def test_the_dashboard_names_the_branch(tmp_path, capsys):
                with _patch("pathlib.Path.cwd", return_value=tmp_path):
                    mod._handle_refresh([])
                assert tmp_path.name.upper() in capsys.readouterr().out
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert [r["species"] for r in result["nominations"]] == ["SHALLOW_SANDBOX"]

    def test_a_dispatch_call_is_not_read_as_a_patch(self, tmp_path):
        """THE ALIAS TEST IS `_patch`, NOT `patch`, AND THE DIFFERENCE IS `dispatch`.

        `endswith("patch")` is the obvious way to catch the alias and it also
        catches every `dispatch(...)` in the fleet - a verb this house uses for
        sending work, not for sealing a seam. The underscore is what tells the
        two apart, and it is one character wide, which is exactly the kind of
        detail a later edit tidies away. Mutation caught:
        `tail.endswith("_patch")` becoming `tail.endswith("patch")`, which turns
        this unit into a SHALLOW_SANDBOX nomination it has no business being.
        """
        _write(
            tmp_path,
            "tests/test_operations.py",
            """
            def test_the_refresh_is_dispatched(tmp_path, capsys):
                with dispatch("pathlib.Path.cwd", return_value=tmp_path):
                    mod._handle_refresh([])
                assert tmp_path.name.upper() in capsys.readouterr().out
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["nominations"] == []
        assert result["violations"] == []
        assert result["score"] == 100


class TestPlatformOracleTheSplit:
    """TWO SPECIES SCORE, THREE NOMINATE - the design this rule lives or dies by.

    Each of the three nominate-only arms, written as a convicting arm, flags
    correct code: an assertion on `.errno` is often right, an unresolved
    `tmp_path` comparison is usually right on the host that wrote it, and a
    sealed `cwd` is only a defect when production walks up. So they are reported
    in their own check line, with `passed: True`, and they move NO number. The
    first time a fleet watches its score drop for a test that was right, the
    score stops being read - and then the arms that ARE sound stop being read
    with it. Every pin in this class is a different angle on that one claim.
    """

    def test_a_project_whose_only_findings_are_nominations_scores_one_hundred(self, tmp_path):
        """THE SPLIT, PINNED HEAD ON: three nominations, three units, 100.

        All three nominate-only species are present and every one of them is a
        place to look rather than a charge. If any of them reached the
        arithmetic, this project would report 0 and three branches that wrote
        correct tests would watch their number collapse. Mutation caught:
        `SCORING_SPECIES: tuple = ("LISTING_ORDER", "MODE_INJECTOR")` becoming
        `("LISTING_ORDER", "MODE_INJECTOR", "UNRESOLVED_TMP_PATH")`, which is the
        single most plausible future edit to this file and reports 66.
        """
        result = platform_oracle_check.check_branch(str(_oracle_nominations_only_project(tmp_path)))

        assert result["score"] == 100
        assert result["violations"] == []
        assert len(result["nominations"]) == 3
        assert sorted(r["species"] for r in result["nominations"]) == [
            "OSERROR_ATTRIBUTE",
            "SHALLOW_SANDBOX",
            "UNRESOLVED_TMP_PATH",
        ]

    def test_the_nominations_have_their_own_check_line_and_that_line_passes(self, tmp_path):
        """A NOMINATION IS A PLACE TO LOOK, AND THE CHECK LINE HAS TO SAY SO.

        Reported in a line of its own, `passed: True`, and the message states in
        words that these rows are not scored and not counted as failing - because
        a reader who sees three findings in a check line and no explanation will
        read them as three failures whatever the number says. Mutation caught:
        `"passed": True,` in the non-empty branch of `_nomination_check` becoming
        `"passed": not nominated,`, which turns every nomination into a failing
        check line while the score stays honest - the worst of both.
        """
        result = platform_oracle_check.check_branch(str(_oracle_nominations_only_project(tmp_path)))
        line = result["checks"][1]

        assert line["name"] == "Platform nominations"
        assert line["passed"] is True
        assert "3/3 test units are NOMINATED" in line["message"]
        assert "not scored, not counted as failing" in line["message"]

    def test_the_scored_line_stays_true_when_only_nominations_were_found(self, tmp_path):
        """The SCORED line is about the scored species and about nothing else.

        A project whose only findings are nominations has to read as what it is -
        three units that decide on the code - because the first check line is the
        one a board renders. Letting a nomination fail it would move the verdict
        without moving the number, which is worse than either alone: the number
        would say 100 and the board would say red. Mutation caught: `"passed":
        not scored,` becoming `"passed": not scored and not nominated,`.
        """
        result = platform_oracle_check.check_branch(str(_oracle_nominations_only_project(tmp_path)))
        line = result["checks"][0]

        assert line["passed"] is True
        assert "3/3 test units decide on the code rather than on the host" in line["message"]

    def test_a_nomination_does_not_move_a_number_a_scored_row_already_set(self, tmp_path):
        """SAME DENOMINATOR, SAME NUMERATOR, SAME ANSWER - the arithmetic angle.

        Two two-unit projects, each with the SAME single scored row. The second
        one's other unit carries a nomination instead of being clean, and the
        score has to be identical: 50 both times. Holding the unit count fixed is
        what makes this pin about the split rather than about the denominator -
        a project that merely grew would move the number honestly. Mutation
        caught: `score = int(((total - len(scored)) / total) * 100)` becoming
        `score = int(((total - len(scored) - len(nominated)) / total) * 100)`,
        which reports 0 for the second project and 50 for the first.
        """
        clean_partner = tmp_path / "clean"
        nominating_partner = tmp_path / "nominating"
        _write(
            clean_partner,
            "tests/test_shapes.py",
            _ORACLE_SCORED_UNITS.split("def test_the_unwritable_log_is_reported")[0]
            + '\n\ndef test_a_clean_unit(tmp_path):\n    assert (tmp_path / "a").parent == tmp_path\n',
        )
        _write(
            nominating_partner,
            "tests/test_shapes.py",
            _ORACLE_SCORED_UNITS.split("def test_the_unwritable_log_is_reported")[0]
            + "\n\n"
            + _ORACLE_NOMINATED_UNITS.split("def test_the_agent_reports_where_it_landed")[0],
        )

        clean = platform_oracle_check.check_branch(str(clean_partner))
        nominating = platform_oracle_check.check_branch(str(nominating_partner))

        assert clean["score"] == 50
        assert nominating["score"] == 50
        assert len(nominating["nominations"]) == 1
        assert len(nominating["violations"]) == len(clean["violations"]) == 1

    def test_the_failing_count_and_the_score_are_computed_from_the_scored_species_alone(self, tmp_path):
        """Eight units, two scored, three nominated - and the number is 75, not 37.

        The whole project in one reading: the two scoring rows charge, the three
        nominations are named in their own line, and the three clean units hold
        three different acquittals up. Both sentences are pinned, because a
        reader gets the sentence before the number. Mutation caught: `scored =
        [r for r in rows if r["species"] in SCORING_SPECIES]` in `split_rows`
        becoming `scored = list(rows)`, which reports 37 and prints "5/8 test
        units would decide differently" over three tests that are right.
        """
        result = platform_oracle_check.check_branch(str(_platform_oracle_project(tmp_path)))

        assert result["score"] == 75
        assert len(result["violations"]) == 2
        assert len(result["nominations"]) == 3
        assert "2/8 test units would decide differently on another platform" in result["checks"][0]["message"]
        assert "3/8 test units are NOMINATED" in result["checks"][1]["message"]

    def test_a_unit_that_scores_and_nominates_appears_in_both_lines(self, tmp_path):
        """DEDUPED SEPARATELY, AND THAT IS THE POINT OF THE SPLIT.

        One unit sorts an rglob against a list literal AND compares an
        unresolved sandbox path with something production handed back. It is one
        unit to charge and two things to look at. Collapsing the nomination
        behind the scored row would lose the second, and the nomination line is
        not a penalty - it is the reason a reader knows to check the second line
        of the same test. Mutation caught: `nominated = [r for r in rows if
        r["species"] not in SCORING_SPECIES]` becoming `nominated = [r for r in
        rows if r["species"] not in SCORING_SPECIES and r["nodeid"] not in
        {s["nodeid"] for s in scored}]`, which is exactly the "tidy up the
        duplicate" edit this docstring exists to refuse.
        """
        _write(
            tmp_path,
            "tests/test_template.py",
            """
            def test_the_listing_and_the_landing_are_both_checked(tmp_path):
                files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
                assert [f.name for f in files] == ["SKILL.md", "handler.py"]
                landed = _spawn_agent(str(tmp_path))
                assert Path(landed["path"]) == tmp_path / "init_test"
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))
        nodeid = "tests/test_template.py::test_the_listing_and_the_landing_are_both_checked"

        assert [r["nodeid"] for r in result["violations"]] == [nodeid]
        assert [r["nodeid"] for r in result["nominations"]] == [nodeid]
        assert result["score"] == 0

    def test_two_scoring_species_in_one_unit_are_one_row_and_not_two(self, tmp_path):
        """A SCORE THAT CAN GO NEGATIVE IS ONE NOBODY BELIEVES TWICE.

        One unit carrying both scoring species is one unit a reader has to go and
        look at, not two. Counting findings instead of units lets a single
        loop-heavy test drive a two-unit project below zero. Mutation caught: `if
        row["nodeid"] in seen: continue` in `_dedupe_by_unit` becoming `if False:
        continue`, which reports two rows for one unit and scores 0 where the
        honest answer is 50.
        """
        _write(
            tmp_path,
            "tests/test_template.py",
            """
            def test_the_listing_and_the_refusal_are_both_checked(tmp_path):
                files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
                assert [f.name for f in files] == ["SKILL.md", "handler.py"]
                target = tmp_path / "log.jsonl"
                target.chmod(0o444)
                with pytest.raises(PermissionError):
                    _write_delivery_log(target)


            def test_a_clean_unit(tmp_path):
                assert (tmp_path / "a").parent == tmp_path
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert len(result["violations"]) == 1
        assert result["violations"][0]["species"] == "LISTING_ORDER"
        assert result["score"] == 50


class TestPlatformOracleAcquittals:
    """Every narrowing that cost a measured false positive, pinned by name.

    An arm that convicts correct code is how a standard gets switched off. Each
    test below is one of the narrowings the dossier paid for in rows - the
    LISTING_ORDER 5-to-1, the OSERROR_ATTRIBUTE 4-to-2, the UNRESOLVED_TMP_PATH
    84-to-83 - and losing any of them puts correct code back in the report.
    """

    def test_a_sorted_with_an_explicit_key_is_not_a_listing_order_row(self, tmp_path):
        """ANY key at all, and that is a statement about what a key DOES.

        Supplying one displaces `PurePath.__lt__` entirely, which is the whole
        hazard - the spellings that appear in real cures are `key=str` and
        `key=lambda p: p.name`, and a key that sorts by size is just as
        deterministic. This is the acquittal a flagged site is rewritten INTO, so
        convicting it would be teaching a rewrite into something the rule also
        flags. Mutation caught: `if any(kw.arg == "key" for kw in
        call.keywords):` in `_sort_is_neutral` becoming `if any(kw.arg == "cmp"
        for kw in call.keywords):`.
        """
        _write(
            tmp_path,
            "tests/test_template.py",
            """
            def test_the_two_files_are_laid_down(tmp_path):
                files = sorted((p for p in tmp_path.rglob("*") if p.is_file()), key=str)
                assert [f.name for f in files] == ["SKILL.md", "handler.py"]
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_sort_over_names_rather_than_paths_is_not_a_listing_order_row(self, tmp_path):
        """THE NARROWING THAT TOOK THIS ARM FROM FIVE ROWS TO ONE.

        `sorted(p.name for p in d.glob(...))` never touches `PurePath.__lt__` at
        all - it sorts STRINGS, which is byte order on every host. Four of the
        five rows measured before this narrowing were @memory sorting `.name` off
        a glob, and two of those four are that branch's own case-folding pins,
        which handle both hosts explicitly and are the most portable code in the
        corpus. Mutation caught: `STRING_VALUED_ATTRIBUTES: frozenset =
        frozenset({"name", "stem", "suffix"})` becoming `frozenset()`, which puts
        all four back.
        """
        _write(
            tmp_path,
            "tests/test_entries.py",
            """
            def test_the_two_files_are_laid_down(tmp_path):
                names = sorted(p.name for p in tmp_path.glob("*"))
                assert names == ["SKILL.md", "handler.py"]
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_set_comparison_carries_no_order_to_disagree_about(self, tmp_path):
        """The cheapest cure there is: compare the set.

        A set does not have an order and a Counter does not read one, so the
        filesystem's arbitrary order cannot reach the claim. It is the first cure
        the rule's own message recommends, which makes flagging it the one
        mistake this arm must never make. Mutation caught: `UNORDERED_WRAPPERS:
        frozenset = frozenset({"set", "frozenset", "Counter"})` becoming
        `frozenset()`.
        """
        _write(
            tmp_path,
            "tests/test_template.py",
            """
            def test_the_two_files_are_laid_down(tmp_path):
                files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
                assert set(f.name for f in files) == ["SKILL.md", "handler.py"]
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_one_element_literal_cannot_disagree_about_order(self, tmp_path):
        """One element has no order, whatever the filesystem hands back.

        The floor is two, and it is not a heuristic: a single-element list is the
        same list in every dialect, so flagging it would be reporting a
        divergence that cannot happen. Mutation caught: `if literal is None or
        len(literal.elts) < 2:` becoming `... len(literal.elts) < 1:`, which
        flags every one-file listing assertion in the fleet.
        """
        _write(
            tmp_path,
            "tests/test_template.py",
            """
            def test_only_one_file_is_laid_down(tmp_path):
                files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
                assert [f.name for f in files] == ["SKILL.md"]
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_ast_walk_is_not_a_directory_listing(self, tmp_path):
        """`walk` is in LISTING_CALLS and `ast.walk` lists no directory.

        Every checker in this pack calls `ast.walk`, and so does every test that
        reads one - so a rule keyed on the verb alone would flag its own author's
        code first and the fleet's AST tooling second. The root is read and
        refused by name. Mutation caught: `NOT_LISTING_ROOTS: frozenset =
        frozenset({"ast", "os.path", "json", "re"})` becoming `frozenset()`.
        """
        _write(
            tmp_path,
            "tests/test_reader.py",
            """
            def test_every_node_is_visited(tree):
                nodes = [n for n in ast.walk(tree)]
                assert [type(n).__name__ for n in nodes] == ["Module", "FunctionDef"]
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_patched_write_seam_named_by_its_target_is_never_a_mode_injector_row(self, tmp_path):
        """THE ONE ACQUITTAL THAT IS NOT NEGOTIABLE, read from the patch TARGET.

        Injecting at the seam is the cure this arm teaches, so an arm that could
        flag the cure would be teaching a rewrite into something it also flags -
        and a fleet that discovers that stops taking the rewrite. The unit here
        still holds everything the arm looks for on the failure side, chmod
        included; only the injection has moved onto a patched `write_text`, and
        the `side_effect` is assigned on a later line so that this pin rests on
        the TARGET reading alone. Mutation caught: `WRITE_SEAMS: frozenset =
        frozenset({... "write_text", "write_bytes", ...})` becoming the same set
        without `"write_text"`.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_the_write_failure_is_reported(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(0o444)
                with patch("apps.writer.Path.write_text") as writer:
                    writer.side_effect = IOError("no")
                    with patch(LOGGER_PATCH) as mock_logger:
                        _write_delivery_log(target)
                assert mock_logger.warning.call_count == 1
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_an_os_error_side_effect_on_any_patch_is_never_a_mode_injector_row(self, tmp_path):
        """The second half of the same acquittal: the seam named by its side_effect.

        The cure is also written `patch(seam, side_effect=OSError(...))` on a
        seam this rule's WRITE_SEAMS list has never heard of - a module's own
        private store, a helper, a client. The failure is still portable, still
        raised on every host, and still nothing to do with the filesystem's mood.
        Read from the `side_effect=` keyword rather than from the target, which
        is why it needs its own pin: the target reading acquits this unit not at
        all. Mutation caught: `if keyword.arg == "side_effect" and
        _names_under(keyword.value) & OSERROR_TYPES:` in
        `_seam_injects_the_failure` becoming `if keyword.arg == "side_effects"
        and _names_under(keyword.value) & OSERROR_TYPES:`.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_the_write_failure_is_reported(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(0o444)
                with patch("apps.writer._store", side_effect=OSError("no")):
                    with patch(LOGGER_PATCH) as mock_logger:
                        _write_delivery_log(target)
                assert mock_logger.warning.call_count == 1
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_dev_null_exactly_is_a_sink_and_not_an_injector(self, tmp_path):
        """`/dev/null` is correct, common and portable through `os.devnull`.

        The trailing slash in the prefix is the whole distinction: it is
        `/dev/null/something` - null used as a DIRECTORY - that provokes the
        ENOTDIR this arm is about, and Windows has no such semantics to provoke.
        Writing TO the sink is ordinary code that works everywhere. Mutation
        caught: the first element of `DEVICE_PATH_PREFIXES` becoming
        `"/dev/null"` without its trailing slash, which flags every sink write in
        the fleet.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_the_sink_swallows_the_output():
                with patch(LOGGER_PATCH) as mock_logger:
                    _write_delivery_log(Path("/dev/null"))
                assert mock_logger.warning.call_count == 1
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_mode_that_keeps_the_owner_write_bit_is_not_an_injector(self, tmp_path):
        """An ordinary chmod is not a platform oracle - only a read-only one is.

        `0o644` refuses nothing on either host, so nothing about the unit's
        verdict changes with the platform. The arm is about a mode that asks the
        kernel to fail, not about the verb `chmod`. Mutation caught: `return ""
        if node.value & OWNER_WRITE_BIT else oct(node.value)` becoming `return
        oct(node.value)`, which flags every chmod in the fleet including the
        ones that grant permission.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_a_writable_target_is_still_reported(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(0o644)
                with pytest.raises(OSError):
                    _write_delivery_log(target)
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_stat_constant_carrying_a_write_name_is_not_an_injector(self, tmp_path):
        """Any name with a W in it is a write bit, and a writable mode refuses nothing.

        The symbolic half of the same acquittal the integer half gets: a mode
        that grants the owner a write bit provokes no OSError on any host, so
        nothing about the unit's verdict changes with the platform. Reading the
        W out of the NAME rather than evaluating the constant is what keeps this
        rule from importing `stat` and asking this interpreter for a number - a
        portability rule that consulted the host would report a different
        standard on every leg of the matrix. Mutation caught: `if any("W" in
        _tail(n) for n in spellings):` becoming `if any("Z" in _tail(n) for n in
        spellings):`.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_a_writable_mode_is_still_reported(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(S_IREAD | S_IWUSR)
                with pytest.raises(PermissionError):
                    _write_delivery_log(target)
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_boolean_mode_is_refused_by_name_rather_than_read_as_mode_one(self, tmp_path):
        """`isinstance(True, int)` is True in Python, and mode 1 has no write bit.

        A boolean handed to a chmod-shaped call is a test doing something else
        entirely, and reading it as an integer mode makes it a read-only mode by
        accident - a finding manufactured out of Python's own numeric tower.
        Refused by name, before the bit test. Mutation caught: `if
        isinstance(node.value, bool) or not isinstance(node.value, int):`
        becoming `if not isinstance(node.value, int):`.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_a_flag_is_not_a_mode(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(True)
                with pytest.raises(OSError):
                    _write_delivery_log(target)
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_an_injector_with_no_failure_oracle_is_not_a_row(self, tmp_path):
        """The species is a FAILURE injected by the filesystem's mood.

        A unit that makes a file read-only and then asserts on a VALUE is not
        claiming anything about an error, so there is nothing for the other
        platform to invert. Without this half the arm would flag every
        permissions fixture in the fleet on the strength of the verb alone.
        Mutation caught: `if not injectors or not _asserts_on_failure(unit):`
        becoming `if not injectors:`.
        """
        _write(
            tmp_path,
            "tests/test_writer.py",
            """
            def test_a_read_only_target_still_reads(tmp_path):
                target = tmp_path / "log.jsonl"
                target.chmod(0o444)
                assert target.read_text() == ""
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["violations"] == []
        assert result["score"] == 100

    def test_a_unit_that_manufactures_its_own_os_error_is_not_nominated(self, tmp_path):
        """THE NARROWING THAT TOOK OSERROR_ATTRIBUTE FROM FOUR ROWS TO TWO.

        The attribute is only OS-filled when the OS filled it. A stand-in the
        unit installs and raises from puts the test's OWN literal in `.errno`,
        and a literal is the same number on every platform because the test wrote
        it down. Two of the four rows measured were exactly this shape - @spawn's
        and this branch's own atomic-write retry pins - and both are portable
        code. Mutation caught: `if not captured or
        _unit_manufactures_the_error(unit.node):` becoming `if not captured:`.
        """
        _write(
            tmp_path,
            "tests/test_atomic_write.py",
            """
            def test_the_retry_reports_the_cross_device_link(monkeypatch, tmp_path):
                def refuse(src, dst):
                    raise OSError(errno.EXDEV, "invalid cross-device link")

                monkeypatch.setattr(os, "replace", refuse)
                with pytest.raises(OSError) as exc_info:
                    atomic_write(tmp_path / "a.json", "{}")
                assert exc_info.value.errno == errno.EXDEV
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["nominations"] == []
        assert result["violations"] == []

    def test_a_sandbox_rebound_through_a_resolver_cures_every_comparison_below_it(self, tmp_path):
        """`tmp_path = tmp_path.resolve()` as the first line is the template's cure.

        After it, every later comparison in the unit is already resolved without
        saying so on its own line - so a reader that only looked at the
        comparison would flag the unit that TOOK the cure, and the cure is the
        one thing the finding tells a reader to do. Mutation caught: `if
        _sandbox_is_resolved_once(unit.node, sandbox):` in
        `unresolved_tmp_path_rows` becoming `if False:`.
        """
        _write(
            tmp_path,
            "tests/test_contracts.py",
            """
            def test_the_agent_reports_where_it_landed(tmp_path):
                tmp_path = tmp_path.resolve()
                target = tmp_path / "init_test"
                landed = _spawn_agent(str(target))
                assert Path(landed["path"]) == target
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["nominations"] == []
        assert result["score"] == 100

    def test_a_path_the_test_built_itself_is_not_nominated(self, tmp_path):
        """POSITIVE EVIDENCE, NOT THE ABSENCE OF IT - the 84-to-83 narrowing.

        The first version asked only "is this name NOT sandbox-derived", which is
        a different question and answers yes for anything the reader failed to
        recognise. Both sides here were built by the TEST, walking its own
        `parents` list; neither ever went through production's resolver, so both
        are the same unresolved text and an 8.3 short name cannot separate them.
        Mutation caught: `return _traces_to_the_subject(node, values, spies,
        set())` in `_came_out_of_the_subject` becoming `return True`, which is
        the first version's reading exactly.
        """
        _write(
            tmp_path,
            "tests/test_walk.py",
            """
            def test_the_walk_finds_its_own_parent(tmp_path):
                parent_dir = tmp_path / "a"
                found = None
                for candidate in [parent_dir, *parent_dir.parents]:
                    if candidate.name == "a":
                        found = candidate
                assert found == parent_dir
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["nominations"] == []
        assert result["score"] == 100

    def test_a_furnished_sandbox_is_not_a_shallow_sandbox_row(self, tmp_path):
        """A unit that lays its own marker down is not relying on an ancestor.

        An upward walk stops INSIDE a sandbox that holds what the walk is looking
        for, so the rendered name is the sandbox's own and no profile directory
        can reach it. It is also the cheapest cure available to a flagged site,
        which is the second reason it must never be the thing the arm flags.
        Mutation caught: `SANDBOX_MARKER_CALLS: frozenset = frozenset({"mkdir",
        "touch", "write_text", "write_bytes", "symlink_to", "makedirs"})`
        becoming `frozenset()`.
        """
        _write(
            tmp_path,
            "tests/test_operations.py",
            """
            def test_the_dashboard_names_the_branch(tmp_path, capsys):
                (tmp_path / "DASHBOARD.local.json").write_text("{}")
                with _patch("pathlib.Path.cwd", return_value=tmp_path):
                    mod._handle_refresh([])
                assert tmp_path.name.upper() in capsys.readouterr().out
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["nominations"] == []
        assert result["score"] == 100

    def test_a_cwd_seam_that_never_names_the_sandbox_is_not_a_seal(self, tmp_path):
        """The sandbox has to be NAMED by the seal, or it is a different test.

        `patch("pathlib.Path.cwd")` handed a Mock never puts the process anywhere
        real, so no ancestor walk can escape into a user profile - there is no
        walk and no profile, only a stand-in. Flagging it would nominate every
        unit in the fleet that stubs `Path.cwd` for any reason at all. Mutation
        caught: `if any(_is_sandbox_path(kw.value, sandbox) for kw in
        node.keywords) or _names_under(node) & sandbox:` in `_cwd_seam_sealed`
        becoming `if True:`.
        """
        _write(
            tmp_path,
            "tests/test_operations.py",
            """
            def test_the_dashboard_names_the_branch(tmp_path, capsys):
                with _patch("pathlib.Path.cwd", return_value=Mock()):
                    mod._handle_refresh([])
                assert tmp_path.name.upper() in capsys.readouterr().out
            """,
        )

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["nominations"] == []
        assert result["score"] == 100


class TestPlatformOracleBranchCheck:
    """The scoring-API contract, and the two paths where silence reads as clean."""

    def test_a_project_with_nothing_to_find_scores_one_hundred_and_says_so(self, tmp_path):
        """Three clean units, three different acquittals, one honest number.

        The clean sentence is pinned beside the number because it is what a
        reader sees first, and the nominations line has to be present and empty
        rather than absent - a missing line reads as a rule that did not run.
        Mutation caught: `f"{total - len(scored)}/{total} test units decide on
        the code rather than on the host"` becoming `f"{len(scored)}/{total} ..."`,
        which prints 0/3 over a project where all three are right.
        """
        result = platform_oracle_check.check_branch(str(_oracle_clean_project(tmp_path)))

        assert result["score"] == 100
        assert result["violations"] == []
        assert result["nominations"] == []
        assert "3/3 test units decide on the code rather than on the host" in result["checks"][0]["message"]
        assert "0/3 test units carry a platform nomination" in result["checks"][1]["message"]

    def test_the_result_carries_the_scoring_api_shape_and_stays_advisory(self, tmp_path):
        """SHADOW MODE GATES NOTHING - this rule reports and a human decides.

        Top-level `passed` must stay True while flags exist and `advisory` must
        stay True, so a caller can tell a report from a verdict. The two extra
        keys this rule carries - `violations` AND `nominations` - are part of the
        contract too: a report lane that only read `violations` would print two
        rows and lose the three a reader was told to go and look at. Mutation
        caught: `"passed": True,` becoming `"passed": not scored,` in the scored
        return, which turns an uncalibrated advisory into a board failure.
        """
        result = platform_oracle_check.check_branch(str(_platform_oracle_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "PLATFORM_ORACLE"
        assert result["checks"][0]["passed"] is False
        assert sorted(result) == [
            "advisory",
            "checks",
            "nominations",
            "passed",
            "score",
            "standard",
            "violations",
        ]

    def test_a_project_with_no_test_files_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND.

        A 0 blames a project for a fact about its layout and a 100 claims a
        measurement that never happened. Each check in this pack carries its own
        copy of the early return, so each one has to be pinned - and losing it
        here does not return a wrong number, it divides by zero and takes the
        caller with it. Mutation caught: `"not_applicable": True,` becoming
        `"not_applicable": False,` in the `total == 0` return.
        """
        _write(tmp_path, "apps/writer.py", "def write_log(path):\n    return path")

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert result["score"] == 0
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin.

        An unparseable file contributes no units, so it cannot lower a score, and
        silence about it reads as a clean result. This is the one path where
        nothing else can catch it: the message a caller sees must say the file
        was present and unreadable, not that the project has never written a
        test. Mutation caught: the `measured` ternary's `if not
        scanned.unparseable` becoming `if True`, which makes the two cases
        indistinguishable.
        """
        _write(tmp_path, "tests/test_unreadable_shapes.py", "def test_broken(:\n    assert True")

        result = platform_oracle_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_unreadable_shapes.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_file_is_named_beside_a_scored_result(self, tmp_path):
        """AN UNREAD FILE FLAGS NOTHING, so for THIS rule silence biases toward clean.

        The early-return path carries the unreadable line by construction; the
        scored path has to append it deliberately, and dropping that one line
        leaves a branch with a healthy number and no hint that a file was never
        read at all. The message has to say NOT measured, not merely name the
        file. Mutation caught: `checks.extend(unreadable)` becoming
        `checks.extend([])`.
        """
        _platform_oracle_project(tmp_path)
        _write(tmp_path, "tests/test_unreadable_shapes.py", "def test_broken(:\n    assert True")

        result = platform_oracle_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 75
        assert len(named) == 1
        assert "test_unreadable_shapes.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]

    def test_only_twelve_flagged_units_are_named_and_the_rest_are_counted(self, tmp_path):
        """A CHECK MESSAGE PRINTING HUNDREDS OF LINES IS ONE NOBODY READS.

        Fourteen flagged units, twelve named, and the remainder stated as a
        number rather than dropped - a truncation that did not say it had
        truncated would understate a branch's problem to every reader of the
        board while the score stayed honest. The violations list itself is never
        truncated, because the report artifact is where the full list lives.
        Mutation caught: `MAX_REPORTED: int = 12` becoming `MAX_REPORTED: int =
        24`, which names all fourteen and prints no remainder.
        """
        units = "\n\n\n".join(
            f"def test_row_{index:02d}(tmp_path):\n"
            f"    files = sorted(p for p in tmp_path.rglob('*') if p.is_file())\n"
            f'    assert [f.name for f in files] == ["SKILL.md", "row-{index:02d}.py"]'
            for index in range(14)
        )
        _write(tmp_path, "tests/test_many_listings.py", units)

        result = platform_oracle_check.check_branch(str(tmp_path))
        message = result["checks"][0]["message"]

        assert len(result["violations"]) == 14
        assert message.count("::test_row_") == 12
        assert message.endswith("(+2 more)")
