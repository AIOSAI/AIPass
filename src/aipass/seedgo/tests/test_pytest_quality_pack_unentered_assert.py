# =================== AIPass ====================
# Name: test_pytest_quality_pack_unentered_assert.py
# Description: pytest_quality pack, unentered_assert checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/unentered_assert_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/unentered_assert_content.py

from pathlib import Path

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus, unentered_assert_check
from aipass.seedgo.tests.support_pytest_quality_pack import _line_of, _write


def _unentered_assert_project(root: Path) -> Path:
    """A four-unit project where exactly one unit's assertions may never run."""
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
        """VACUOUS-GUARD, with the coordinates a reader needs to triage it."""
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
        """THE KNOWN-GOOD, AND THE HARD HALF OF THE RULE: a two-sided guard is correct code."""
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
        """An assertion that always runs excuses the unit, however much it also guards."""
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
        """Entering a `with` is not a branch, so an assert in its body always runs."""
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
        """VACUOUS-LOOP: an empty iterable makes the whole unit a silent pass."""
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
        """THE LOOP'S KNOWN-GOOD: a literal iterable is a floor by construction."""
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
        """One unit, one finding - or the score can be driven below zero."""
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
        """The number is units-that-are-FINE over total, not the inverse."""
        result = unentered_assert_check.check_branch(str(_unentered_assert_project(tmp_path)))

        assert result["score"] == 75
        assert [row["nodeid"] for row in result["violations"]] == [
            "tests/test_scored_reachability.py::test_asserts_only_when_configured"
        ]

    def test_the_result_passes_and_stays_advisory_even_when_units_are_flagged(self, tmp_path):
        """SHADOW MODE GATES NOTHING - this rule scores before it is calibrated."""
        result = unentered_assert_check.check_branch(str(_unentered_assert_project(tmp_path)))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "UNENTERED_ASSERT"
        assert result["checks"][0]["passed"] is False
        assert "may never be entered" in result["checks"][0]["message"]

    def test_a_project_with_no_tests_is_not_applicable_not_zero_quality(self, tmp_path):
        """ZERO TESTS MEASURED IS NOT ZERO QUALITY FOUND."""
        _write(tmp_path, "tests/helpers.py", "def build_row():\n    return {}")

        result = unentered_assert_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin."""
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = unentered_assert_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_file_is_named_beside_a_scored_result(self, tmp_path):
        """The unreadable line must also survive onto the path that DOES score."""
        _unentered_assert_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = unentered_assert_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 75
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]

    def test_a_loop_over_a_named_literal_table_is_entered(self, tmp_path):
        """A for over a name bound once to a non-empty literal runs (hooks' self.BLOCKED, fleet green leg 20)."""
        _write(
            tmp_path,
            "tests/test_tables.py",
            """
            CASES = ["a"]
            TABLE = build()
            EMPTY = ()
            TWICE = ["a"]
            TWICE = ["b"]


            def test_module_table():
                for case in CASES:
                    assert run(case)


            def test_local_table():
                targets = ("a",)
                for target in targets:
                    assert run(target)


            def test_computed_table():
                for case in TABLE:
                    assert run(case)


            def test_empty_table():
                for case in EMPTY:
                    assert run(case)


            def test_twice_bound_table():
                for case in TWICE:
                    assert run(case)


            class TestSpellings:
                BLOCKED = ("rm -rf x", "rm -r x")

                def test_class_table(self):
                    for spelling in self.BLOCKED:
                        assert run(spelling)
            """,
        )

        rows = unentered_assert_check.find_unentered(corpus.build(tmp_path))

        assert [row["nodeid"].split("::")[-1] for row in rows] == [
            "test_computed_table",
            "test_empty_table",
            "test_twice_bound_table",
        ]
