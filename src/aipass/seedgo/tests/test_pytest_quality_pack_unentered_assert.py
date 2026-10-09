# =================== AIPass ====================
# Name: test_pytest_quality_pack_unentered_assert.py
# Description: pytest_quality pack, unentered_assert checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/unentered_assert_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/unentered_assert_content.py

from pathlib import Path

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus, unentered_assert_check
from aipass.seedgo.tests.support_pytest_quality_pack import _line_of, _write

# =============================================================================
# UNENTERED ASSERTIONS - THE ASSERT THAT MAY NEVER EXECUTE
# =============================================================================


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

    def test_a_loop_over_a_named_literal_table_is_entered(self, tmp_path):
        """A for over a name bound once to a non-empty literal runs (hooks' self.BLOCKED, fleet green leg 20).

        Read in the class through ``self``, at module level by name, and in the
        unit's own body before the loop. A table computed by a call, an empty
        literal and a name bound twice keep the flag, because that is the shape
        the standard means. Red first on the reader that took only a literal
        at the loop itself; its proof is also the mutants, one per arm.
        """
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
