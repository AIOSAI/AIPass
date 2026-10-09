# =================== AIPass ====================
# Name: test_pytest_quality_pack_capture_never_read.py
# Description: pytest_quality pack, capture_never_read checker pins (split from test_pytest_quality_pack.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/pytest_quality_standards/capture_never_read_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — the content page prose, pytest_quality_standards/capture_never_read_content.py

from pathlib import Path

from aipass.seedgo.apps.handlers.pytest_quality_standards import capture_never_read_check, corpus
from aipass.seedgo.tests.support_pytest_quality_pack import _line_of, _write

# =============================================================================
# CAPTURE NEVER READ - THE OUTPUT THE TEST ASKED FOR AND NEVER LOOKED AT
# =============================================================================


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
