# =================== AIPass ====================
# Name: test_pytest_quality_pack_assertion_shape.py
# Description: pytest_quality pack, assertion_shape checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/assertion_shape_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/assertion_shape_content.py

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.pytest_quality_standards import assertion_shape_check
from aipass.seedgo.tests.support_pytest_quality_pack import _unit, _write

# =============================================================================
# ASSERTION SHAPE - CAN THE ORACLE EVER SAY NO
# =============================================================================
#
# Every test below was confirmed RED against a named one-line mutation of
# assertion_shape_check.py before it shipped, per the owner's standing rule. The
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

    def test_an_isinstance_on_the_cause_beside_a_raises_block_is_not_type_only(self):
        """The raised error and its cause ARE the value (flow's register shape, fleet green leg 20).

        A ``pytest.raises`` block is oracle company: the isinstance on
        ``__cause__`` is the second half of a claim the block already makes.
        Green-first reading of the old rule convicted it; its proof is the
        mutant that drops the raises recognition.
        """
        unit = _unit(
            """
            def test_undecodable_register_refuses():
                with pytest.raises(UnreadableRegisterError) as excinfo:
                    find_project_root(SUB)
                assert isinstance(excinfo.value.__cause__, UnicodeDecodeError)
            """
        )

        assert assertion_shape_check.unit_flags(unit) == []

    def test_an_isinstance_beside_a_mock_assert_call_is_not_type_only(self):
        """A mock's ``assert_*`` call is an oracle (commons' identity shape, fleet green leg 20).

        No raises block here, so only the ``assert_`` recognition can acquit
        the unit. Its proof is the mutant that drops that recognition.
        """
        unit = _unit(
            """
            def test_lookup_returns_an_error_and_registers_nothing():
                result = lookup(JUNK)
                assert isinstance(result, LookupFailed)
                mock_register.assert_not_called()
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
