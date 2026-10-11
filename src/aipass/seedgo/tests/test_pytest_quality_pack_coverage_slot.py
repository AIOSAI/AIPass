# =================== AIPass ====================
# Name: test_pytest_quality_pack_coverage_slot.py
# Description: pytest_quality pack, coverage_slot checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/coverage_slot_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/coverage_slot_content.py

import ast
from pathlib import Path

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus, coverage_slot_check
from aipass.seedgo.tests.support_pytest_quality_pack import _write

# =============================================================================
# COVERAGE SLOT - THE TEST THAT SAYS OUT LOUD WHY IT EXISTS
# =============================================================================


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

    def test_a_file_that_cannot_be_read_a_second_time_is_named_not_silent(self, tmp_path):
        """The corpus keeps the tree, not the source, so comments cost a re-read.

        A file that moved, was rewritten or turned unreadable between the parse
        and the read must produce fewer findings, never an exception: a static
        reader that raises does not report a finding, it takes the whole
        branch's score down with it. Red first: the failed read answered {},
        the answer a file with no comments gives, and nothing said so (seedgo
        fleet green leg 15). Now the file is named as judged without comments.
        """
        parsed = corpus.TestFile(relpath="tests/test_gone.py", tree=ast.parse("x = 1"))
        unread = []

        assert coverage_slot_check.comments_in(tmp_path, parsed) is None
        assert coverage_slot_check.find_confessions(corpus.Corpus(root=tmp_path, files=[parsed]), unread) == []
        assert unread == ["tests/test_gone.py"]


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
