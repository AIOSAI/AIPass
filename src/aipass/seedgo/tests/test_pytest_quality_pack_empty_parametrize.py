# =================== AIPass ====================
# Name: test_pytest_quality_pack_empty_parametrize.py
# Description: pytest_quality pack, empty_parametrize checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/empty_parametrize_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/empty_parametrize_content.py

from pathlib import Path

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus, empty_parametrize_check
from aipass.seedgo.tests.support_pytest_quality_pack import _line_of, _write


def _empty_parametrize_project(root: Path) -> Path:
    """A four-unit project where exactly one table is computed at collection time.

    The three safe tables are safe for three DIFFERENT reasons, and no assertion measures a length,
    which keeps the one flag at its full VANISHING-TABLE species.
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
        """The subject is the DECORATOR, so that is the line a reader gets."""
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
        """THE ACQUITTAL THAT MATTERS MOST: most of every corpus is literals."""
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
        """An EMPTY literal is the species written out in full, and it happens."""
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
        """A name bound to a literal at module level cannot vanish either."""
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
        """An IMPORTED name is a query with a shorter spelling."""
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
        """`range(24)` is a table written in shorthand, not a query."""
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
        """ONE LAYER IS UNWRAPPED, AND ONLY ONE - the builtin is not a laundry."""
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
        """The decorator does not have to carry two positional arguments."""
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
        """SHORT-TABLE: `did it find anything` is not `did it find them all`."""
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
        """THE FULL ACQUITTAL: this file already did the thing the rule asks for."""
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
        """`len(x) == 0` is an emptiness claim, and it acquits nothing."""
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
        """The number is units-that-are-FINE over total, not the inverse."""
        result = empty_parametrize_check.check_branch(str(_empty_parametrize_project(tmp_path)))

        assert result["score"] == 75
        assert [row["nodeid"] for row in result["violations"]] == [
            "tests/test_scored_tables.py::test_over_a_computed_table"
        ]

    def test_a_unit_stacking_two_tables_is_one_flagged_unit_not_two(self, tmp_path):
        """One unit, one unit of score - or the score can be driven below zero."""
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
        """SHADOW MODE GATES NOTHING - this rule scores before it is calibrated."""
        result = empty_parametrize_check.check_branch(str(_empty_parametrize_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "EMPTY_PARAMETRIZE"
        assert result["checks"][0]["passed"] is False
        assert "computed at collection time" in result["checks"][0]["message"]

    def test_a_project_with_no_tests_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND."""
        _write(tmp_path, "tests/helpers.py", "def build_row():\n    return {}")

        result = empty_parametrize_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin."""
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = empty_parametrize_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_file_is_named_beside_a_scored_result(self, tmp_path):
        """The unreadable line must also survive onto the path that DOES score."""
        _empty_parametrize_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = empty_parametrize_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 75
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]
