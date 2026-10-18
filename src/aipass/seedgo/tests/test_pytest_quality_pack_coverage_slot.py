# =================== AIPass ====================
# Name: test_pytest_quality_pack_coverage_slot.py
# Description: pytest_quality pack, coverage_slot checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/coverage_slot_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/coverage_slot_content.py

import ast
from pathlib import Path

from aipass.seedgo.apps.handlers.pytest_quality_standards import corpus, coverage_slot_check
from aipass.seedgo.tests.support_pytest_quality_pack import _write


def _coverage_slot_project(root: Path) -> Path:
    """A five-unit project where exactly two units confess.

    The three clean units are clean for three DIFFERENT reasons, so no single acquittal carries the 60.
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
        """The subject of the rule: the test says what it is, in writing."""
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
        """Quoting a confession is not making one — the data exclusion, one layer up."""
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
        """Negative control for the quote narrowing, and the reason it is narrow."""
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
        """The scan reads EVERY match, not the first."""
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
        """A bare verb phrase is not a purposive claim."""
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
        """THE NARROWING THAT DECIDED THE SHAPE - phrases, never bare words."""
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
        """ "coverage slots" as a subject is prose; "coverage slot" as a name is not."""
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
        """A sentence that opens with the phrase is still the phrase."""
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
        """Comments are not in the AST, so the line has to be carried by hand."""
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
        """THE DEFECT THE PORT FIXED: sample content read as the test's own prose."""
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
        """A module-level note is not a test's confession."""
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
        """A test whose DATA holds the phrase is testing a string."""
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
        """THE ARM THAT WAS DELETED, held here as a decision rather than as code."""
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
        """Three confessions in one docstring is one confessing test."""
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
        """The corpus keeps the tree, not the source, so comments cost a re-read."""
        parsed = corpus.TestFile(relpath="tests/test_gone.py", tree=ast.parse("x = 1"))
        unread = []

        assert coverage_slot_check.comments_in(tmp_path, parsed) is None
        assert coverage_slot_check.find_confessions(corpus.Corpus(root=tmp_path, files=[parsed]), unread) == []
        assert unread == ["tests/test_gone.py"]


class TestCoverageSlotScoring:
    """The number, and the arithmetic that would make it a lie."""

    def test_two_findings_naming_one_unit_cost_one_unit(self):
        """The dedupe that keeps a score from going negative."""
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
        """The constructed negative control: three acquittals, three reasons."""
        _coverage_slot_project(tmp_path)

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert result["score"] == 60
        assert len(result["violations"]) == 2
        assert "2/5 test units say in writing that they exist for the checker" in result["checks"][0]["message"]


class TestCoverageSlotBranchCheck:
    """The scoring-API contract, and the two paths where silence reads as clean."""

    def test_the_result_carries_the_scoring_api_shape(self, tmp_path):
        """The pack is advisory in shadow mode and every result has to say so."""
        _coverage_slot_project(tmp_path)

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert result["passed"] is True
        assert result["advisory"] is True
        assert result["standard"] == "COVERAGE_SLOT"
        assert result["checks"][0]["passed"] is False

    def test_a_project_with_no_test_files_is_not_applicable(self, tmp_path):
        """Zero tests measured is not zero quality found."""
        _write(tmp_path, "src/thing.py", "def thing():\n    return 1")

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert result["passed"] is True
        assert "no test files found" in result["checks"][0]["message"]

    def test_a_project_whose_only_test_file_is_broken_is_not_reported_as_having_no_tests(self, tmp_path):
        """A broken file must never read as an absent one - the ordering pin."""
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = coverage_slot_check.check_branch(str(tmp_path))

        assert result["not_applicable"] is True
        assert "no test files found" not in result["checks"][0]["message"]
        assert "unparseable" in result["checks"][0]["message"]
        assert any("test_broken.py" in check["message"] for check in result["checks"])

    def test_an_unparseable_file_is_named_beside_a_scored_result(self, tmp_path):
        """The unreadable line must also survive onto the path that DOES score."""
        _coverage_slot_project(tmp_path)
        _write(tmp_path, "tests/test_broken.py", "def test_broken(:\n    assert True")

        result = coverage_slot_check.check_branch(str(tmp_path))
        named = [check for check in result["checks"] if check["name"] == "Corpus readable"]

        assert result["score"] == 60
        assert len(named) == 1
        assert "tests/test_broken.py" in named[0]["message"]
        assert "NOT measured" in named[0]["message"]
