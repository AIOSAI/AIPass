# =================== AIPass ====================
# Name: test_pytest_quality_pack_assertion_shape.py
# Description: pytest_quality pack, assertion_shape checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/assertion_shape_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/assertion_shape_content.py

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.pytest_quality_standards import assertion_shape_check
from aipass.seedgo.tests.support_pytest_quality_pack import _unit, _write


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
        """`assert True` is a comment with a keyword in front of it."""
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
        """`len(x) >= 0` holds for every sequence; `len(x) < 0` holds for none."""
        unit = _unit(f"def test_rows_are_returned():\n    rows = fetch()\n    assert {compare}")

        rows = assertion_shape_check.unit_flags(unit)

        assert [row["species"] for row in rows] == ["TAUTOLOGY"]
        assert "true of every sequence" in rows[0]["reason"]

    @pytest.mark.parametrize("compare", ["len(rows) > 0", "len(rows) >= 3"])
    def test_a_real_len_comparison_is_never_flagged(self, compare):
        """NEGATIVE CONTROL: `len(x) > 0` and `len(x) >= 3` are ordinary bounds; only a bound of ZERO is vacuous."""
        unit = _unit(f"def test_rows_are_returned():\n    rows = fetch()\n    assert {compare}")

        assert assertion_shape_check.unit_flags(unit) == []

    def test_membership_in_the_whole_bool_domain_is_flagged(self):
        """`x in (True, False)` is true of every bool, so it asserts nothing."""
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
        """NEGATIVE CONTROL: membership is a normal assertion about a value."""
        unit = _unit(
            """
            def test_the_status_is_known():
                status = compute()
                assert status in ("ok", "fail")
            """
        )

        assert assertion_shape_check.unit_flags(unit) == []

    def test_a_self_comparison_is_flagged(self):
        """`a == a` compares an expression with itself and cannot fail."""
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
        """NEGATIVE CONTROL: the ordinary assertion, which must stay silent."""
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
        """`assert x == [] or isinstance(x, list)` passes whenever either holds."""
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
        """NEGATIVE CONTROL AND THE RULE'S HONESTY: platform-divergent code is not an escape."""
        unit = _unit(f"def test_handles_the_platform_gap():\n    assert {clause} or compute() == 3")

        assert assertion_shape_check.unit_flags(unit) == []


class TestTypeOnlyIsAPropertyOfTheUnit:
    """The pairing rule - the one this port could most easily get backwards."""

    def test_a_unit_whose_whole_oracle_is_isinstance_is_flagged(self):
        """A test that pins only the return TYPE passes on the right shape of garbage."""
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
        """THE PAIRING RULE: TYPE-ONLY is a property of the UNIT, never of a line."""
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
        """An absent oracle is `no_oracle`'s business, not this rule's."""
        unit = _unit(
            """
            def test_renders_a_widget():
                widget = build_widget("blue")
                widget.render()
            """
        )

        assert assertion_shape_check.unit_flags(unit) == []

    def test_a_healthy_unit_produces_no_findings_of_any_species(self):
        """THE OVERALL NEGATIVE CONTROL - without it, a detector that says yes to everything passes."""
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
        """The raised error and its cause ARE the value: a ``pytest.raises`` block is oracle company."""
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
        """A mock's ``assert_*`` call is an oracle, so it acquits the unit without a raises block."""
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
        """The number is units-WITHOUT-a-flag over total, not the inverse."""
        result = assertion_shape_check.check_branch(str(_shape_project(tmp_path)))

        assert result["score"] == 75
        assert [row["nodeid"] for row in result["violations"]] == ["tests/test_shapes.py::test_asserts_a_literal"]

    def test_a_unit_holding_several_flagged_assertions_still_costs_one_unit(self, tmp_path):
        """THE SCORE IS PER UNIT, NOT PER FINDING - or it can go below zero."""
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
        """SHADOW MODE GATES NOTHING - the pack scores before it is calibrated."""
        result = assertion_shape_check.check_branch(str(_shape_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "ASSERTION_SHAPE"
        assert result["checks"][0]["passed"] is False
        assert "cannot fail" in result["checks"][0]["message"]

    def test_a_finding_names_its_species_and_the_line_the_assertion_lives_on(self, tmp_path):
        """A flag with the wrong coordinates sends a reader to an innocent line."""
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
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND."""
        _write(tmp_path, "tests/helpers.py", "def build_row():\n    return {}")

        result = assertion_shape_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert result["advisory"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """THE ORDERING CONTRACT: a broken file must never read as an absent one."""
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = assertion_shape_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("tests/test_broken.py" in check["message"] for check in result["checks"])
        assert any("NOT measured" in check["message"] for check in result["checks"])

    def test_an_unparseable_file_beside_readable_ones_is_named_as_not_measured(self, tmp_path):
        """A file that could not be read must never pass for a clean one."""
        _shape_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = assertion_shape_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]
