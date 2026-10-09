# =================== AIPass ====================
# Name: test_pytest_quality_pack_docstring_pin.py
# Description: pytest_quality pack, docstring_pin checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/docstring_pin_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/docstring_pin_content.py

from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus, docstring_pin_check
from aipass.seedgo.tests.support_pytest_quality_pack import _write

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
