# =================== AIPass ====================
# Name: test_audit_tests_static.py
# Description: tests for the static nominator tier, harness selfcheck and cache stamp
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
Phase 6-7 of the audit-tests lane: the nine nominators, selfcheck, cache, render.

THE TWO-SIDED BAR (design section 10.2, from TAXONOMY section 6):

    A checker that flags nothing in table A is not measuring.
    A checker that flags anything in table B is not shippable.

So every rule here is tested in BOTH directions, and the known-good direction
is the one that gets the sharper test — a false nomination teaches a branch to
delete a pin that was holding something up, and Law M11 exists because that has
already nearly happened once in this campaign's own corpus.

The fixtures reproduce TAXONOMY's exemplar SHAPES rather than importing another
branch's source. A test that read @daemon's tests would fail the day @daemon
fixed them, which would make this suite's green mean "the corpus has not moved"
instead of "the rule still works".
"""

import ast
import json
import os
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

from aipass.seedgo.apps.handlers.audit import discovery
from aipass.seedgo.apps.handlers.audit_tests import cache, render, selfcheck
from aipass.seedgo.apps.handlers.tests_pytest_standards import (
    adapter,
    assertion_shape_check,
    capture_never_read_check,
    corpus,
    coverage_slot_check,
    entry_point_diff_check,
    mock_drift_check,
    no_oracle_check,
    nominators,
    render_spec,
    ruff_pt_check,
    self_skip_check,
    unentered_assert_check,
)


def _corpus(tmp_path: Path, source: str, filename: str = "test_sample.py", production: str = "") -> corpus.Corpus:
    """A one-file corpus from a source string, optionally with production code."""
    tests = tmp_path / "tests"
    tests.mkdir(exist_ok=True)
    (tests / filename).write_text(textwrap.dedent(source), encoding="utf-8")
    if production:
        (tmp_path / "module_under_test.py").write_text(textwrap.dedent(production), encoding="utf-8")
    return corpus.build(tmp_path, ["tests"])


def _fake_module(**attributes) -> ModuleType:
    """A stand-in module for the shape gate, which inspects real modules."""
    module = ModuleType("fake_nominator")
    for name, value in attributes.items():
        setattr(module, name, value)
    return module


def _species(rows) -> set:
    """The species names a nominator returned."""
    return {row["species"] for row in rows}


# =============================================================================
# THE CORPUS - parsed once, and honest about what it could not read
# =============================================================================


class TestCorpus:
    """Parsing is where a silent hole would be cheapest to introduce."""

    def test_a_test_function_becomes_a_unit_with_its_nodeid(self, tmp_path):
        scanned = _corpus(tmp_path, "def test_one():\n    assert 1 == 1\n")
        assert [unit.nodeid for unit in scanned.units()] == ["tests/test_sample.py::test_one"]

    def test_a_method_on_a_test_class_carries_the_class_in_its_nodeid(self, tmp_path):
        scanned = _corpus(tmp_path, "class TestThing:\n    def test_two(self):\n        assert True\n")
        assert [unit.nodeid for unit in scanned.units()] == ["tests/test_sample.py::TestThing::test_two"]

    def test_self_is_not_reported_as_a_fixture_parameter(self, tmp_path):
        scanned = _corpus(tmp_path, "class TestThing:\n    def test_two(self, tmp_path):\n        assert True\n")
        assert list(scanned.units())[0].params == ["tmp_path"]

    def test_an_unparseable_file_is_counted_never_skipped(self, tmp_path):
        # "could not check" must never read as "checked and clean" - the same
        # rule the payload isolation proof already follows.
        scanned = _corpus(tmp_path, "def test_broken(:\n")
        assert scanned.unparseable == ["tests/test_sample.py"]
        assert scanned.files == []

    def test_a_non_test_file_is_production_not_corpus(self, tmp_path):
        scanned = _corpus(tmp_path, "def test_one():\n    assert True\n", production="def real(): pass\n")
        assert any(path.name == "module_under_test.py" for path in scanned.production)

    def test_every_nomination_row_carries_an_unprobed_deletion_safety_field(self, tmp_path):
        # Law M11: deletion safety is a row-level probe, and its ABSENCE must
        # be stated. A row with no such field reads as safe to act on.
        scanned = _corpus(tmp_path, "def test_one():\n    assert True\n")
        row = corpus.nomination("X", list(scanned.units())[0], "because")
        assert row["deletion_safety"]["probed"] is False
        assert row["deletion_safety"]["reason"]


# =============================================================================
# RULE 3 - SKIP PROVENANCE
# =============================================================================


class TestSelfSkip:
    """Machine probes pass; subject probes are nominated; nothing runs is worst."""

    def test_a_platform_skip_is_never_nominated(self, tmp_path):
        source = """
            import sys
            import pytest

            @pytest.mark.skipif(sys.platform == "win32", reason="posix only")
            def test_posix_only():
                assert True
        """
        assert self_skip_check.nominate(_corpus(tmp_path, source)) == []

    def test_a_which_probe_is_never_nominated(self, tmp_path):
        source = """
            import shutil
            import pytest

            @pytest.mark.skipif(not shutil.which("rsync"), reason="needs rsync")
            def test_needs_rsync():
                assert True
        """
        assert self_skip_check.nominate(_corpus(tmp_path, source)) == []

    def test_a_hasattr_probe_on_the_subject_is_skip_on_drift(self, tmp_path):
        source = """
            import pytest
            from module_under_test import thing

            @pytest.mark.skipif(not hasattr(thing, "JSON_DIR"), reason="drifted")
            def test_reads_json_dir():
                assert True
        """
        assert _species(self_skip_check.nominate(_corpus(tmp_path, source))) == {"SKIP-ON-DRIFT"}

    def test_an_unconditional_mark_skip_is_perma_skip(self, tmp_path):
        source = """
            import pytest

            @pytest.mark.skip(reason="later")
            def test_never_runs():
                assert False
        """
        assert _species(self_skip_check.nominate(_corpus(tmp_path, source))) == {"PERMA-SKIP"}

    def test_a_module_level_skip_is_found(self, tmp_path):
        # The most expensive skip in the catalog and the one the first version
        # of this rule missed: it removes the WHOLE FILE. Renaming JSON_DIR made
        # 75 daemon tests vanish through exactly this shape.
        source = """
            import pytest
            from module_under_test import thing

            if not hasattr(thing, "JSON_DIR"):
                pytest.skip("no JSON_DIR", allow_module_level=True)

            def test_one():
                assert True
        """
        rows = self_skip_check.nominate(_corpus(tmp_path, source))
        assert _species(rows) == {"SKIP-ON-DRIFT"}
        assert rows[0]["test"] == "<module>"

    def test_a_module_level_skip_reading_a_computed_name_is_followed(self, tmp_path):
        # The provenance lives in the FOR LOOP that computed the name, not in
        # the assignment. Binding to the assignment node alone finds nothing.
        source = """
            import pytest
            from module_under_test import thing

            _ATTR = None
            for _candidate in ("JSON_DIR", "JSON_PATH"):
                if hasattr(thing, _candidate):
                    _ATTR = _candidate
                    break

            if _ATTR is None:
                pytest.skip("cannot find it", allow_module_level=True)

            def test_one():
                assert True
        """
        assert _species(self_skip_check.nominate(_corpus(tmp_path, source))) == {"SKIP-ON-DRIFT"}

    def test_a_condition_calling_a_local_helper_is_followed_one_hop(self, tmp_path):
        source = """
            import pytest
            from module_under_test import thing

            def _factory_raises():
                return hasattr(thing, "raises_on_unknown")

            def test_unknown_type_raises():
                if not _factory_raises():
                    pytest.skip("branch does not raise")
                assert True
        """
        rows = self_skip_check.nominate(_corpus(tmp_path, source))
        assert _species(rows) == {"SKIP-ON-DRIFT"}
        assert rows[0]["evidence"]["via_helper"] == "_factory_raises"

    def test_a_machine_probe_inside_the_helper_still_acquits(self, tmp_path):
        source = """
            import sys
            import pytest

            def _on_windows():
                return sys.platform == "win32"

            def test_posix_only():
                if _on_windows():
                    pytest.skip("posix only")
                assert True
        """
        assert self_skip_check.nominate(_corpus(tmp_path, source)) == []


# =============================================================================
# RULE 4 - PATCH TARGET RESOLUTION
# =============================================================================


class TestMockDrift:
    """A patch that replaces a MODULE answers every attribute, forever."""

    def _tree(self, tmp_path: Path, test_source: str) -> corpus.Corpus:
        """A target where `helper` is a module and `Console` is not."""
        package = tmp_path / "pkg"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "helper.py").write_text("def work():\n    return 1\n", encoding="utf-8")
        (package / "service.py").write_text(
            "from pkg import helper\n\nConsole = object()\n\n\ndef run():\n    return helper.work()\n",
            encoding="utf-8",
        )
        return _corpus(tmp_path, test_source)

    def test_patching_a_module_by_attribute_is_nominated(self, tmp_path):
        source = """
            from unittest.mock import patch

            @patch("pkg.service.helper")
            def test_run(_helper):
                assert True
        """
        assert _species(mock_drift_check.nominate(self._tree(tmp_path, source))) == {"MOCK-DRIFT"}

    def test_patching_a_non_module_attribute_is_not_nominated(self, tmp_path):
        # `Console` is an object bound in the same module. A last-segment name
        # match would flag it; resolving the binding does not.
        source = """
            from unittest.mock import patch

            @patch("pkg.service.Console")
            def test_run(_console):
                assert True
        """
        assert mock_drift_check.nominate(self._tree(tmp_path, source)) == []

    def test_autospec_acquits_the_patch(self, tmp_path):
        source = """
            from unittest.mock import patch

            @patch("pkg.service.helper", autospec=True)
            def test_run(_helper):
                assert True
        """
        assert mock_drift_check.nominate(self._tree(tmp_path, source)) == []

    def test_spec_acquits_the_patch(self, tmp_path):
        source = """
            from unittest.mock import patch

            @patch("pkg.service.helper", spec=True)
            def test_run(_helper):
                assert True
        """
        assert mock_drift_check.nominate(self._tree(tmp_path, source)) == []

    def test_an_f_string_target_resolves_through_a_module_constant(self, tmp_path):
        # The dominant real spelling. Requiring ast.Constant scored a branch
        # with 25 known MOCK-DRIFTs as completely clean.
        source = """
            from unittest.mock import patch

            _MOD = "pkg.service"

            @patch(f"{_MOD}.helper")
            def test_run(_helper):
                assert True
        """
        assert _species(mock_drift_check.nominate(self._tree(tmp_path, source))) == {"MOCK-DRIFT"}

    def test_a_computed_target_is_never_nominated(self, tmp_path):
        source = """
            from unittest.mock import patch

            def _target(name):
                return "pkg.service." + name

            def test_run():
                with patch(_target("helper")):
                    assert True
        """
        assert mock_drift_check.nominate(self._tree(tmp_path, source)) == []


# =============================================================================
# RULE 5 - ASSERTION SHAPE
# =============================================================================


class TestAssertionShape:
    """Tautologies are per-assertion; type-only is per-unit. That split is the rule."""

    def test_assert_true_is_a_tautology(self, tmp_path):
        assert _species(assertion_shape_check.nominate(_corpus(tmp_path, "def test_a():\n    assert True\n"))) == {
            "TAUTOLOGY"
        }

    def test_len_greater_or_equal_zero_is_a_tautology(self, tmp_path):
        source = "def test_a():\n    result = []\n    assert len(result) >= 0\n"
        assert _species(assertion_shape_check.nominate(_corpus(tmp_path, source))) == {"TAUTOLOGY"}

    def test_len_equal_to_zero_is_a_real_assertion(self, tmp_path):
        source = "def test_a():\n    result = []\n    assert len(result) == 0\n"
        assert assertion_shape_check.nominate(_corpus(tmp_path, source)) == []

    def test_membership_in_true_false_is_a_tautology(self, tmp_path):
        source = "def test_a():\n    result = probe()\n    assert result in (True, False)\n"
        assert _species(assertion_shape_check.nominate(_corpus(tmp_path, source))) == {"TAUTOLOGY"}

    def test_a_self_comparison_is_a_tautology(self, tmp_path):
        source = "def test_a():\n    result = probe()\n    assert result == result\n"
        assert _species(assertion_shape_check.nominate(_corpus(tmp_path, source))) == {"TAUTOLOGY"}

    def test_an_isinstance_only_unit_is_type_only(self, tmp_path):
        source = "def test_a():\n    result = probe()\n    assert isinstance(result, list)\n"
        assert _species(assertion_shape_check.nominate(_corpus(tmp_path, source))) == {"TYPE-ONLY"}

    def test_isinstance_paired_with_a_value_assertion_is_never_flagged(self, tmp_path):
        # TAXONOMY's known-good rule, and the direction that costs the most to
        # get wrong: pairing is correct, common code.
        source = """
            def test_a():
                result = probe()
                assert isinstance(result, list)
                assert result == [1, 2]
        """
        assert assertion_shape_check.nominate(_corpus(tmp_path, source)) == []

    def test_a_two_clause_or_about_the_result_is_an_or_escape(self, tmp_path):
        source = "def test_a():\n    result = probe()\n    assert result == [] or isinstance(result, list)\n"
        assert "OR-ESCAPE" in _species(assertion_shape_check.nominate(_corpus(tmp_path, source)))

    def test_an_or_whose_first_clause_probes_the_machine_is_never_flagged(self, tmp_path):
        # TAXONOMY known-good row 1. In a real OR-ESCAPE both clauses are about
        # the result; here the first is about the platform.
        source = """
            import signal

            def test_a():
                assert not hasattr(signal, "SIGKILL") or signal.SIGKILL not in (1, 2)
        """
        assert assertion_shape_check.nominate(_corpus(tmp_path, source)) == []


# =============================================================================
# RULE 6 - THE CONFESSION GREP
# =============================================================================


class TestCoverageSlot:
    """Purposive phrases only. The bare word 'coverage' is a topic, not a confession."""

    def test_a_docstring_saying_for_coverage_is_a_confession(self, tmp_path):
        source = 'def test_a():\n    """Exists for coverage."""\n    assert True\n'
        assert _species(coverage_slot_check.nominate(_corpus(tmp_path, source))) == {"COVERAGE-SLOT"}

    def test_a_docstring_saying_to_satisfy_is_a_confession(self, tmp_path):
        source = 'def test_a():\n    """Added to satisfy the standards audit."""\n    assert True\n'
        assert _species(coverage_slot_check.nominate(_corpus(tmp_path, source))) == {"COVERAGE-SLOT"}

    def test_a_docstring_merely_mentioning_coverage_is_not_a_confession(self, tmp_path):
        # The false positive the naive grep produces, and it would fire dozens
        # of times on this very branch, whose whole subject is checkers.
        source = 'def test_a():\n    """The coverage report renders every branch."""\n    assert render() == "ok"\n'
        assert coverage_slot_check.nominate(_corpus(tmp_path, source)) == []

    def test_a_confessing_comment_inside_the_test_is_found(self, tmp_path):
        source = "def test_a():\n    # here for coverage\n    assert True\n"
        rows = coverage_slot_check.nominate(_corpus(tmp_path, source))
        assert _species(rows) == {"COVERAGE-SLOT"}
        assert rows[0]["evidence"]["where"] == "comment"

    def test_a_unit_confessing_twice_is_nominated_once(self, tmp_path):
        source = 'def test_a():\n    """For coverage, and to satisfy the checker."""\n    assert True\n'
        assert len(coverage_slot_check.nominate(_corpus(tmp_path, source))) == 1

    def test_a_string_in_test_data_is_not_scanned(self, tmp_path):
        source = 'def test_a():\n    payload = "for coverage"\n    assert transform(payload) == "FOR COVERAGE"\n'
        assert coverage_slot_check.nominate(_corpus(tmp_path, source)) == []


# =============================================================================
# RULE 7 - NO ORACLE
# =============================================================================


class TestNoOracle:
    """Generous about what counts as an oracle, on purpose."""

    def test_a_unit_with_no_oracle_at_all_is_nominated(self, tmp_path):
        assert _species(no_oracle_check.nominate(_corpus(tmp_path, "def test_a():\n    do_work()\n"))) == {"NO-ORACLE"}

    def test_pytest_raises_counts_as_an_oracle(self, tmp_path):
        source = "import pytest\n\ndef test_a():\n    with pytest.raises(ValueError):\n        do_work()\n"
        assert no_oracle_check.nominate(_corpus(tmp_path, source)) == []

    def test_a_mock_assert_call_counts_as_an_oracle(self, tmp_path):
        source = "def test_a(mocked):\n    do_work()\n    mocked.assert_called_once_with(1)\n"
        assert no_oracle_check.nominate(_corpus(tmp_path, source)) == []

    def test_a_call_to_a_local_assertion_helper_counts_as_an_oracle(self, tmp_path):
        # Flagging this would teach branches to inline their helpers, which is
        # a worse suite for a better number.
        source = "def test_a():\n    result = do_work()\n    _assert_document_is_lawful(result)\n"
        assert no_oracle_check.nominate(_corpus(tmp_path, source)) == []

    def test_the_nomination_shows_the_calls_it_saw(self, tmp_path):
        rows = no_oracle_check.nominate(_corpus(tmp_path, "def test_a():\n    do_work()\n    tidy()\n"))
        assert set(rows[0]["evidence"]["calls"]) == {"do_work", "tidy"}


# =============================================================================
# RULE 8 - CAPTURE NEVER READ
# =============================================================================


class TestCaptureNeverRead:
    """Sole is the species. A paired assertion is always KEEP."""

    def test_capsys_requested_and_never_read_is_nominated(self, tmp_path):
        source = "def test_a(capsys):\n    print_help()\n    assert True\n"
        assert _species(capture_never_read_check.nominate(_corpus(tmp_path, source))) == {"RETURN-ONLY"}

    def test_capsys_read_with_readouterr_is_never_nominated(self, tmp_path):
        source = 'def test_a(capsys):\n    print_help()\n    assert "usage" in capsys.readouterr().out\n'
        assert capture_never_read_check.nominate(_corpus(tmp_path, source)) == []

    def test_a_sole_receipt_on_a_print_callee_is_nominated(self, tmp_path):
        assert _species(
            capture_never_read_check.nominate(_corpus(tmp_path, "def test_a():\n    assert print_help() is True\n"))
        ) == {"RETURN-ONLY"}

    def test_a_receipt_paired_with_another_assertion_is_never_nominated(self, tmp_path):
        # TAXONOMY known-good row 9: nine such lines in @api are each paired
        # and are correct.
        source = """
            def test_a(mocked):
                assert print_help() is True
                assert mocked.called
        """
        assert capture_never_read_check.nominate(_corpus(tmp_path, source)) == []

    def test_a_receipt_paired_with_a_mock_assertion_is_never_nominated(self, tmp_path):
        source = """
            def test_a(mocked):
                assert print_help() is True
                mocked.assert_called_once_with("drive")
        """
        assert capture_never_read_check.nominate(_corpus(tmp_path, source)) == []

    def test_a_predicate_under_test_is_never_nominated(self, tmp_path):
        # TAXONOMY known-good row 10: the boolean IS the behaviour.
        source = "def test_a():\n    assert is_ssl_error(x) is True\n"
        assert capture_never_read_check.nominate(_corpus(tmp_path, source)) == []


# =============================================================================
# RULE 9 - UNENTERED ASSERTIONS
# =============================================================================


class TestUnenteredAssert:
    """A one-sided guard is vacuous; a two-sided one is correct code."""

    def test_a_lone_assert_under_an_if_is_a_vacuous_guard(self, tmp_path):
        source = """
            def test_a(path):
                if path.exists():
                    assert path.read_text() == "x"
        """
        assert _species(unentered_assert_check.nominate(_corpus(tmp_path, source))) == {"VACUOUS-GUARD"}

    def test_an_if_asserting_on_both_branches_is_never_nominated(self, tmp_path):
        # TAXONOMY known-good rows 2 and 3: correct platform-divergent code.
        source = """
            import sys

            def test_a():
                if sys.platform == "win32":
                    assert path_for() == "C:\\\\tmp"
                else:
                    assert path_for() == "/tmp"
        """
        assert unentered_assert_check.nominate(_corpus(tmp_path, source)) == []

    def test_a_lone_assert_inside_a_floorless_loop_is_a_vacuous_loop(self, tmp_path):
        source = """
            def test_a():
                for entry in discover():
                    assert entry.declared
        """
        assert _species(unentered_assert_check.nominate(_corpus(tmp_path, source))) == {"VACUOUS-LOOP"}

    def test_a_loop_with_an_emptiness_floor_is_never_nominated(self, tmp_path):
        source = """
            def test_a():
                entries = discover()
                assert entries
                for entry in entries:
                    assert entry.declared
        """
        assert unentered_assert_check.nominate(_corpus(tmp_path, source)) == []

    def test_a_loop_over_a_literal_collection_is_never_nominated(self, tmp_path):
        source = """
            def test_a():
                for name in ("a", "b"):
                    assert resolve(name)
        """
        assert unentered_assert_check.nominate(_corpus(tmp_path, source)) == []

    def test_a_top_level_assertion_acquits_the_whole_unit(self, tmp_path):
        source = """
            def test_a(path):
                assert path is not None
                if path.exists():
                    assert path.read_text() == "x"
        """
        assert unentered_assert_check.nominate(_corpus(tmp_path, source)) == []


# =============================================================================
# RULE 10 - ENTRY POINT DIFF
# =============================================================================


class TestEntryPointDiff:
    """A declared verb no literal names is an absence, not a suspect test."""

    def _target(self, tmp_path: Path, production: str, test_source: str) -> corpus.Corpus:
        (tmp_path / "verbs.py").write_text(textwrap.dedent(production), encoding="utf-8")
        return _corpus(tmp_path, test_source)

    def test_a_declared_verb_no_test_names_is_nominated(self, tmp_path):
        scanned = self._target(
            tmp_path,
            'COMMANDS = ("install-timer", "uninstall-timer")\n',
            'def test_a():\n    assert route("install-timer") is True\n',
        )
        rows = entry_point_diff_check.nominate(scanned)
        assert [row["evidence"]["entry_point"] for row in rows] == ["uninstall-timer"]

    def test_a_verb_every_test_names_is_never_nominated(self, tmp_path):
        scanned = self._target(
            tmp_path,
            'COMMANDS = ("install-timer",)\n',
            'def test_a():\n    assert route("install-timer") is True\n',
        )
        assert entry_point_diff_check.nominate(scanned) == []

    def test_a_route_decorator_declares_an_entry_point(self, tmp_path):
        scanned = self._target(
            tmp_path,
            '@app.get("/health")\ndef health():\n    return {}\n',
            'def test_a():\n    assert client.get("/other")\n',
        )
        assert [row["evidence"]["entry_point"] for row in entry_point_diff_check.nominate(scanned)] == ["/health"]

    def test_a_very_short_verb_is_skipped(self, tmp_path):
        scanned = self._target(tmp_path, 'COMMANDS = ("ls",)\n', "def test_a():\n    assert True\n")
        assert entry_point_diff_check.nominate(scanned) == []

    def test_the_row_says_it_is_an_absence_with_no_test_to_point_at(self, tmp_path):
        scanned = self._target(tmp_path, 'COMMANDS = ("uninstall-timer",)\n', "def test_a():\n    assert True\n")
        row = entry_point_diff_check.nominate(scanned)[0]
        assert row["nodeid"] == "" and "absence" in row["file"]


# =============================================================================
# RUFF PT - THE ADOPT HALF
# =============================================================================


class TestRuffPt:
    """Ruff's absence is a not_applicable, never a silent clean sheet."""

    def test_a_missing_ruff_raises_rather_than_returning_nothing(self, tmp_path, monkeypatch):
        # Returning [] would publish a CLEAN group for a tool that never ran,
        # which is the exact lie Law S1 exists to stop.
        monkeypatch.setattr(ruff_pt_check, "_ruff_binary", lambda: "")
        with pytest.raises(RuntimeError, match="not installed"):
            ruff_pt_check.nominate(_corpus(tmp_path, "def test_a():\n    assert True\n"))

    def test_unreadable_ruff_output_raises_rather_than_reporting_clean(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ruff_pt_check, "_ruff_binary", lambda: "/bin/true")
        monkeypatch.setattr(ruff_pt_check, "_run_ruff", lambda *a: ([], "ruff output was not readable JSON"))
        with pytest.raises(RuntimeError, match="not readable JSON"):
            ruff_pt_check.nominate(_corpus(tmp_path, "def test_a():\n    assert True\n"))

    def test_a_diagnostic_becomes_a_nomination_carrying_its_code(self, tmp_path):
        diagnostic = {
            "filename": str(tmp_path / "tests/test_sample.py"),
            "location": {"row": 7},
            "code": "PT009",
            "message": "m",
        }
        row = ruff_pt_check._row(diagnostic, tmp_path)
        assert row["species"] == "PT-FAMILY" and row["line"] == 7 and row["evidence"]["code"] == "PT009"

    def test_a_ruff_diagnostic_never_carries_a_delete_family_verdict(self, tmp_path):
        row = ruff_pt_check._row({"filename": "x.py", "location": {"row": 1}, "code": "PT001"}, tmp_path)
        assert row["verdict"] in (corpus.VERDICT_SUSPECT, corpus.VERDICT_IMPROVE)


def _fake_interpreter(tmp_path: Path, monkeypatch) -> Path:
    """Point `sys.executable` at a scratch venv and return its binary directory.

    The lookup under test reads `sys.executable`, so a test that did not move
    it would be measuring the machine it happens to run on - green here and
    silent about every other machine.
    """
    binaries = tmp_path / "venv" / "bin"
    binaries.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sys, "executable", str(binaries / "python"))
    return binaries


def _executable(path: Path) -> Path:
    """Write a runnable stand-in binary at `path`."""
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


class TestRuffBinaryLookup:
    """PATH is not where ruff lives; a venv is, and the venv was invisible.

    The reported defect: `shutil.which` searches PATH only, the drone process's
    PATH does not carry `.venv/bin`, and the PT family therefore published
    not_applicable on a machine that had had ruff installed for months. Every
    test here is about that one sentence - a tool that IS present must never be
    reported absent, and a tool that is absent must say where it was looked for.
    """

    def test_the_ruff_beside_the_interpreter_wins_over_the_one_on_PATH(self, tmp_path, monkeypatch):
        # PREFERRED, not merely found. The venv's ruff is the one the target's
        # own configuration was pinned against; a system ruff of another
        # version would nominate different codes for the same corpus.
        binaries = _fake_interpreter(tmp_path, monkeypatch)
        sibling = _executable(binaries / "ruff")
        monkeypatch.setattr(ruff_pt_check.shutil, "which", lambda _name: str(tmp_path / "elsewhere" / "ruff"))
        assert ruff_pt_check._ruff_binary() == str(sibling)

    def test_the_windows_spelling_of_the_sibling_is_found_too(self, tmp_path, monkeypatch):
        # A POSIX-only name list would report "not installed" on every Windows
        # machine that has ruff - the same false not_applicable, moved.
        binaries = _fake_interpreter(tmp_path, monkeypatch)
        sibling = _executable(binaries / "ruff.exe")
        monkeypatch.setattr(ruff_pt_check.shutil, "which", lambda _name: "")
        assert ruff_pt_check._ruff_binary() == str(sibling)

    def test_PATH_is_still_searched_when_the_interpreter_has_no_sibling(self, tmp_path, monkeypatch):
        # The fix adds a place to look; it must not remove one. A system-wide
        # ruff with no venv beside it is the ordinary case on a CI runner.
        _fake_interpreter(tmp_path, monkeypatch)
        on_path = str(tmp_path / "usr" / "bin" / "ruff")
        monkeypatch.setattr(ruff_pt_check.shutil, "which", lambda _name: on_path)
        assert ruff_pt_check._ruff_binary() == on_path

    def test_a_sibling_that_is_a_directory_is_not_taken_for_a_binary(self, tmp_path, monkeypatch):
        # Handing a directory to subprocess turns a missing linter into a
        # crash, which the group would report as "ruff failed" - a third wrong
        # answer to a question that has only two right ones.
        binaries = _fake_interpreter(tmp_path, monkeypatch)
        (binaries / "ruff").mkdir()
        on_path = str(tmp_path / "usr" / "bin" / "ruff")
        monkeypatch.setattr(ruff_pt_check.shutil, "which", lambda _name: on_path)
        assert ruff_pt_check._ruff_binary() == on_path

    @pytest.mark.skipif(os.name == "nt", reason="Windows ignores the executable bit")
    def test_a_sibling_without_the_executable_bit_is_not_returned(self, tmp_path, monkeypatch):
        binaries = _fake_interpreter(tmp_path, monkeypatch)
        (binaries / "ruff").write_text("not a binary\n", encoding="utf-8")
        (binaries / "ruff").chmod(0o644)
        on_path = str(tmp_path / "usr" / "bin" / "ruff")
        monkeypatch.setattr(ruff_pt_check.shutil, "which", lambda _name: on_path)
        assert ruff_pt_check._ruff_binary() == on_path

    def test_only_both_places_missing_is_an_absence(self, tmp_path, monkeypatch):
        _fake_interpreter(tmp_path, monkeypatch)
        monkeypatch.setattr(ruff_pt_check.shutil, "which", lambda _name: None)
        assert ruff_pt_check._ruff_binary() == ""

    def test_the_refusal_names_BOTH_places_it_looked(self, tmp_path, monkeypatch):
        # "ruff is not installed" was true of PATH and false of the machine,
        # and no reader of the artifact could tell which claim they held. The
        # reason has to carry the candidate locations or the next reader
        # repeats the same investigation.
        binaries = _fake_interpreter(tmp_path, monkeypatch)
        monkeypatch.setattr(ruff_pt_check.shutil, "which", lambda _name: None)
        with pytest.raises(RuntimeError) as raised:
            ruff_pt_check.nominate(_corpus(tmp_path, "def test_a():\n    assert True\n"))
        reason = str(raised.value)
        assert str(binaries / "ruff") in reason
        assert "PATH" in reason

    def test_the_absence_reason_still_says_not_installed(self, tmp_path, monkeypatch):
        # The orchestrator's not_applicable text is read by people, and the
        # phrase they search for is the old one; naming the places must not
        # cost the sentence that says what happened.
        _fake_interpreter(tmp_path, monkeypatch)
        assert "not installed" in ruff_pt_check._absent_reason()


# =============================================================================
# THE ORCHESTRATOR AND ITS SHAPE GATE
# =============================================================================


class TestNominatorShapeGate:
    """A nominator that could be mistaken for a standards checker is refused."""

    def test_every_shipped_nominator_is_discovered(self):
        found, rejections = nominators.discover()
        assert rejections == []
        assert sorted(found) == sorted(adapter.STATIC_GROUPS)

    def test_the_declared_group_list_matches_what_discovery_finds(self):
        # Adding a species is three files AND one line in STATIC_GROUPS. A file
        # added without the line would silently change the published group list,
        # which is exactly what Law S3 exists to stop.
        assert nominators.declared_groups() == sorted(adapter.STATIC_GROUPS)

    def test_discovery_returns_the_package_module_not_a_copy(self):
        # A second module object for one rule means the SPECIFICATION a reader
        # inspects is not the one that ran, and discovery re-executes all nine
        # files on every call.
        found, _ = nominators.discover()
        assert found[ruff_pt_check.GROUP] is ruff_pt_check

    def test_a_foreign_pack_directory_is_still_loaded_by_path(self, tmp_path):
        (tmp_path / "sample_check.py").write_text(
            'GROUP = "static_sample"\nSPECIFICATION = {"rule": "r"}\n\n\ndef nominate(corpus):\n    return []\n',
            encoding="utf-8",
        )
        found, rejections = nominators.discover(tmp_path)
        assert rejections == [] and list(found) == ["static_sample"]

    def test_no_nominator_defines_check_module(self):
        found, _ = nominators.discover()
        assert [name for name, module in found.items() if hasattr(module, "check_module")] == []

    def test_no_nominator_defines_check_branch(self):
        found, _ = nominators.discover()
        assert [name for name, module in found.items() if hasattr(module, "check_branch")] == []

    def test_a_module_defining_check_module_is_rejected_by_name(self):
        module = _fake_module(GROUP="x", SPECIFICATION={}, nominate=lambda c: [], check_module=lambda p: {})
        assert any("check_module" in problem for problem in nominators.shape_problems(module))

    def test_a_module_defining_check_branch_is_rejected_by_name(self):
        module = _fake_module(GROUP="x", SPECIFICATION={}, nominate=lambda c: [], check_branch=lambda p: {})
        assert any("check_branch" in problem for problem in nominators.shape_problems(module))

    def test_a_module_missing_nominate_is_rejected(self):
        module = _fake_module(GROUP="x", SPECIFICATION={})
        assert "missing nominate" in nominators.shape_problems(module)

    def test_a_well_shaped_module_has_no_problems(self):
        module = _fake_module(GROUP="x", SPECIFICATION={}, nominate=lambda c: [])
        assert nominators.shape_problems(module) == []

    def test_every_problem_is_reported_at_once(self):
        # All-problems-at-once, the same contract the adapter gate follows: a
        # first-error-wins gate turns one fix into four rounds.
        module = _fake_module(check_branch=lambda p: {})
        assert len(nominators.shape_problems(module)) >= 4


class TestNominatorRun:
    """A rule that crashed and a rule that found nothing are different documents."""

    def test_a_measured_group_carries_no_score(self, tmp_path):
        # Law S7a: an unscored group that carried a number would be refused by
        # the artifact validator, so this is the pin that keeps it publishable.
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_a():\n    assert 1 == 1\n", encoding="utf-8")
        groups = nominators.run(tmp_path)
        assert all(group["score"] is None for group in groups.values())

    def test_every_group_declares_the_static_tier(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_a():\n    assert 1 == 1\n", encoding="utf-8")
        groups = nominators.run(tmp_path)
        assert {group["tier"] for group in groups.values()} == {"static"}

    def test_every_group_is_nominate_only(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_a():\n    assert 1 == 1\n", encoding="utf-8")
        groups = nominators.run(tmp_path)
        assert {group["kind"] for group in groups.values()} == {"nominate_only"}

    def test_a_raising_nominator_becomes_not_applicable_with_its_reason(self, tmp_path, monkeypatch):
        def explode(_scanned):
            raise RuntimeError("the linter is not here")

        monkeypatch.setattr(ruff_pt_check, "nominate", explode)
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_a():\n    assert 1 == 1\n", encoding="utf-8")
        group = nominators.run(tmp_path)["static_ruff_pt"]
        assert group["status"] == "not_applicable"
        assert "the linter is not here" in group["reason"]

    def test_a_raising_nominator_never_publishes_an_empty_measured_group(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ruff_pt_check, "nominate", lambda _s: (_ for _ in ()).throw(RuntimeError("boom")))
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_a():\n    assert 1 == 1\n", encoding="utf-8")
        assert nominators.run(tmp_path)["static_ruff_pt"]["status"] != "measured"

    def test_a_measured_group_publishes_what_it_cannot_see(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_a():\n    assert 1 == 1\n", encoding="utf-8")
        assert nominators.run(tmp_path)["static_self_skip"]["limits"]


# =============================================================================
# THE CONTENT TRIPLET - derived, so it cannot drift
# =============================================================================


class TestContentRendering:
    """The content file and the checker are one source, not two."""

    def test_the_rendered_content_carries_the_rule_from_the_specification(self):
        rendered = render_spec.render("self_skip", self_skip_check.SPECIFICATION)
        assert self_skip_check.SPECIFICATION["rule"] in rendered

    def test_the_rendered_content_states_the_group_is_never_scored(self):
        rendered = render_spec.render("no_oracle", no_oracle_check.SPECIFICATION)
        assert "NEVER SCORED" in rendered

    def test_the_markdown_carries_every_exemption(self):
        rendered = render_spec.render_markdown("assertion_shape", assertion_shape_check.SPECIFICATION)
        for exemption in assertion_shape_check.SPECIFICATION["exempts"]:
            assert exemption in rendered

    def test_every_shipped_md_is_BYTE_IDENTICAL_to_what_the_spec_renders(self):
        # The strongest form of the no-drift claim, and the reason
        # render_markdown() exists at all: the .md on disk is not a second
        # statement of the rule that a reader has to trust, it is output. A
        # SPECIFICATION edited without regenerating fails here, loudly.
        found, _ = nominators.discover()
        drifted = []
        for group, module in sorted(found.items()):
            name = group.removeprefix("static_")
            doc = Path(nominators.PACK_DIR) / f"{name}.md"
            expected = render_spec.render_markdown(name, module.SPECIFICATION)
            if doc.read_text(encoding="utf-8") != expected:
                drifted.append(name)
        assert drifted == []

    def test_every_shipped_nominator_has_a_content_module_and_a_doc(self):
        pack = Path(nominators.PACK_DIR)
        for check in sorted(pack.glob("*_check.py")):
            name = check.stem.removesuffix("_check")
            assert (pack / f"{name}_content.py").is_file(), name
            assert (pack / f"{name}.md").is_file(), name

    def test_every_content_module_names_its_function_by_convention(self):
        pack = Path(nominators.PACK_DIR)
        for content in sorted(pack.glob("*_content.py")):
            name = content.stem.removesuffix("_content")
            source = content.read_text(encoding="utf-8")
            assert f"def get_{name}_standards()" in source, name


# =============================================================================
# THE PACK-KIND REFUSAL - an execution pack is not scored
# =============================================================================


class TestPackKindRefusal:
    """The nominators ship as *_check.py; the audit must not offer to score them."""

    def test_the_execution_pack_is_not_offered_as_a_scoring_pack(self):
        from aipass.seedgo.apps.modules import standards_audit

        assert "tests_pytest" not in standards_audit._discover_packs()

    def test_the_execution_pack_is_still_visible_as_a_non_scoring_pack(self):
        # Hidden and absent must not look the same: an operator who can see the
        # pack knows where to look for its numbers.
        from aipass.seedgo.apps.modules import standards_audit

        assert standards_audit.non_scoring_packs().get("tests_pytest") == "execution"

    def test_the_standards_pack_is_still_discovered(self):
        from aipass.seedgo.apps.modules import standards_audit

        assert "aipass" in standards_audit._discover_packs()

    def test_a_pack_with_no_manifest_is_treated_as_standards(self, tmp_path):
        # Changing the default would silently unregister the pack this branch
        # has audited eighteen citizens with.
        assert discovery.pack_kind(tmp_path) == discovery.SCORING_PACK_KIND

    def test_an_unreadable_manifest_is_treated_as_standards(self, tmp_path):
        (tmp_path / "pack.json").write_text("{not json", encoding="utf-8")
        assert discovery.pack_kind(tmp_path) == discovery.SCORING_PACK_KIND

    def test_the_non_scoring_packs_are_actually_PRINTED(self, capsys):
        # The function returning the right answer proves nothing if no surface
        # calls it: a pack that is hidden and a pack that is absent look the
        # same to an operator, which is the whole reason the list exists.
        from aipass.seedgo.apps.modules import standards_audit

        standards_audit._print_non_scoring_packs()
        printed = capsys.readouterr().out
        assert "tests_pytest" in printed and "execution" in printed

    def test_the_pytest_pack_declares_the_execution_kind(self):
        manifest = json.loads((Path(nominators.PACK_DIR) / "pack.json").read_text(encoding="utf-8"))
        assert manifest["kind"] == "execution"


# =============================================================================
# THE RETIREMENT - Law S3, and the ruling travels in the artifact
# =============================================================================


class TestRetirement:
    """A group may only vanish by a recorded ruling."""

    def test_the_placeholder_group_is_recorded_as_retired(self):
        assert [entry["group"] for entry in adapter.RETIRED_GROUPS] == ["pytest.static_nominators"]

    def test_the_retirement_names_a_ruling(self):
        # An entry with no ruling is refused by Law S3's own validator; this
        # pins that the shipped entry carries one.
        assert all(entry["ruling"] for entry in adapter.RETIRED_GROUPS)

    def test_the_ruling_names_EVERY_group_that_superseded_it(self):
        # Naming two endpoints and trusting the middle is how a ruling ends up
        # accounting for less than it retired. The claim is that every species
        # the placeholder stood in for is still published - so every live
        # static group has to appear by name.
        ruling = adapter.RETIRED_GROUPS[0]["ruling"]
        assert [group for group in adapter.STATIC_GROUPS if group not in ruling] == []

    def test_no_currently_declared_group_is_also_retired(self):
        retired = {entry["group"].split(".", 1)[-1] for entry in adapter.RETIRED_GROUPS}
        assert retired & set(adapter.ADAPTER_GROUPS) == set()


# =============================================================================
# THE HARNESS SELF-CHECK
# =============================================================================


def _harness(**overrides):
    """A harness block over plausible inputs, with targeted overrides."""
    facts = {
        "document": {"group_baseline": "abc123", "target": {"name": "T"}},
        "hygiene": {
            "score": 100,
            "budget_seconds": 900,
            "elapsed_seconds": 1.0,
            "canary": {"attempted": True, "caught": True, "path": "/tmp/c"},
            "gate_coverage": {"blind": ["a"], "child_processes_spawned": 0, "sqlite3_connections": {}},
        },
        "run": {"returncode": 0},
        "environment": {"target_copy": "/tmp/env/t", "m10_complete": True, "copied_siblings": ["a"]},
        "liveness": {"live": True, "resolved_to": "/tmp/env/t/__init__.py"},
        "m10_proof": {
            "probed": True,
            "real_tree_unchanged": True,
            "unattributed_changes": [],
            "attributed_to_concurrent_writers": [],
            "live_writers_probed": True,
            "files_fingerprinted": 12,
            "diff": {},
        },
        "config_note": "serial, one process",
    }
    facts.update(overrides)
    return selfcheck.harness_block(**facts)


class TestSelfCheck:
    """Published whether it passes or fails - never a silent pre-flight."""

    def test_all_seventeen_checks_are_published(self):
        assert [row["check"] for row in _harness()["checks"]] == list(range(1, 18))

    def test_a_sound_run_fails_nothing(self):
        assert _harness()["failed"] == 0

    def test_a_missed_canary_fails_check_eleven(self):
        block = _harness(
            hygiene={
                "score": 100,
                "budget_seconds": 900,
                "elapsed_seconds": 1.0,
                "canary": {"attempted": True, "caught": False},
                "gate_coverage": {"blind": ["a"], "child_processes_spawned": 0, "sqlite3_connections": {}},
            }
        )
        assert [row["check"] for row in block["checks"] if row["status"] == "fail"] == [11]

    def test_an_unattributed_change_fails_check_seventeen_not_twelve(self):
        """Repointed 2026-08-30 on @trigger's report - the assertion is unchanged,
        it just names the row that now owns it. Check 12 reds only on what the
        gate SAW the suite write; an unattributed change is check 17's finding."""
        proof = {
            "probed": True,
            "real_tree_unchanged": False,
            "unattributed_changes": ["/real/logs/operations.jsonl"],
            "attributed_to_concurrent_writers": [],
            "files_fingerprinted": 12,
            "diff": {"added": ["/real/logs/operations.jsonl"]},
        }
        failed = [row["check"] for row in _harness(m10_proof=proof)["checks"] if row["status"] == "fail"]
        assert 17 in failed
        assert 12 not in failed, "the suite wrote nothing, so the OBSERVER-FORGERY row must stay green"

    def test_a_change_the_live_writer_probe_saw_first_does_not_fail_check_seventeen(self):
        # A live citizen writes its own logs throughout the window. The path is
        # still published in the diff - it is just not charged to this run.
        proof = {
            "probed": True,
            "real_tree_unchanged": False,
            "unattributed_changes": [],
            "attributed_to_concurrent_writers": ["/real/api_json/feed_log.json"],
            "live_writers_probed": True,
            "files_fingerprinted": 12,
            "diff": {"modified": ["/real/api_json/feed_log.json"]},
        }
        row = [r for r in _harness(m10_proof=proof)["checks"] if r["check"] == 17][0]
        assert row["status"] == "pass" and "feed_log.json" in row["detail"]

    def test_a_concurrent_write_is_never_removed_from_the_published_diff(self):
        proof = {
            "probed": True,
            "real_tree_unchanged": False,
            "unattributed_changes": [],
            "attributed_to_concurrent_writers": ["/real/api_json/feed_log.json"],
            "live_writers_probed": True,
            "files_fingerprinted": 12,
            "diff": {"modified": ["/real/api_json/feed_log.json"]},
        }
        row = [r for r in _harness(m10_proof=proof)["checks"] if r["check"] == 17][0]
        assert "1 attributed" in row["detail"] and "probe ran: True" in row["detail"]

    def test_an_unprobed_fingerprint_fails_checks_one_and_twelve(self):
        block = _harness(m10_proof={"probed": False, "note": "could not fingerprint"})
        failed = [row["check"] for row in block["checks"] if row["status"] == "fail"]
        assert 1 in failed and 12 in failed

    def test_a_symlinked_sibling_fails_check_thirteen(self):
        block = _harness(environment={"target_copy": "/t", "m10_complete": False, "symlinked_siblings": ["prax"]})
        assert 13 in [row["check"] for row in block["checks"] if row["status"] == "fail"]

    def test_a_failing_suite_fails_the_control_check(self):
        assert 4 in [row["check"] for row in _harness(run={"returncode": 1})["checks"] if row["status"] == "fail"]

    def test_an_empty_blind_list_fails_check_fourteen(self):
        block = _harness(
            hygiene={
                "score": 100,
                "budget_seconds": 900,
                "elapsed_seconds": 1.0,
                "canary": {"attempted": True, "caught": True},
                "gate_coverage": {"blind": [], "child_processes_spawned": 0, "sqlite3_connections": {}},
            }
        )
        assert 14 in [row["check"] for row in block["checks"] if row["status"] == "fail"]

    def test_a_non_package_target_makes_check_three_not_applicable(self):
        block = _harness(liveness={"live": None, "resolved_to": ""})
        row = [row for row in block["checks"] if row["check"] == 3][0]
        assert row["status"] == "not_applicable"

    def test_the_group_bound_checks_name_the_group_they_wait_on(self):
        block = _harness()
        for number in (5, 6, 7, 8):
            row = [row for row in block["checks"] if row["check"] == number][0]
            assert row["status"] == "not_applicable" and "pytest." in row["detail"]

    def test_a_first_run_baseline_makes_check_sixteen_not_applicable(self):
        block = _harness(document={"group_baseline": "first run for this pair", "target": {"name": "T"}})
        row = [row for row in block["checks"] if row["check"] == 16][0]
        assert row["status"] == "not_applicable"

    def test_a_failing_harness_is_reported_never_raised(self):
        # A harness failure removed from the document because it was
        # inconvenient is the thing this campaign is against.
        block = _harness(m10_proof={"probed": False, "note": "x"})
        assert block["failed"] > 0 and block["checks"]


# =============================================================================
# THE CACHE STAMP - computed always, served by nothing
# =============================================================================


class TestCacheStamp:
    """The requirement lands before the capability, again."""

    def test_the_block_is_never_marked_cache_served(self):
        assert cache.cache_block().get("served_from_cache") is False

    def test_the_block_carries_a_stamp_even_though_nothing_serves_it(self):
        # A stamp first computed on the day serving is switched on is a stamp
        # nobody has tested.
        assert cache.cache_block()["stamp"].startswith(cache.AT_CACHE_VERSION)

    def test_the_block_names_what_the_fingerprint_cannot_see(self):
        assert len(cache.cache_block()["not_fingerprinted"]) >= 4

    def test_the_stamp_changes_when_the_sibling_set_changes(self):
        assert cache.compute_stamp(None, siblings=["a"]) != cache.compute_stamp(None, siblings=["a", "b"])

    def test_the_stamp_is_stable_for_the_same_inputs(self):
        assert cache.compute_stamp(None, siblings=["a"]) == cache.compute_stamp(None, siblings=["a"])

    def test_the_stamp_changes_when_a_hashed_file_changes(self, tmp_path):
        (tmp_path / "one.py").write_text("A", encoding="utf-8")
        before = cache.compute_stamp(tmp_path)
        (tmp_path / "one.py").write_text("B", encoding="utf-8")
        assert cache.compute_stamp(tmp_path) != before

    def test_a_rename_to_an_identical_twin_changes_the_stamp(self, tmp_path):
        # A hash over contents alone would call a rename a no-op, and a rename
        # is exactly how a checker stops being discovered.
        (tmp_path / "one.py").write_text("A", encoding="utf-8")
        before = cache.compute_stamp(tmp_path)
        (tmp_path / "one.py").rename(tmp_path / "two.py")
        assert cache.compute_stamp(tmp_path) != before

    def _pack(self, tmp_path: Path) -> Path:
        """A pack with an adapter beside its payload."""
        pack = tmp_path / "pack"
        (pack / "payload").mkdir(parents=True)
        (pack / "adapter.py").write_text("x = 1\n", encoding="utf-8")
        (pack / "payload" / "plugin.py").write_text("y = 1\n", encoding="utf-8")
        return pack

    def test_a_payload_change_moves_the_payload_segment_alone(self, tmp_path):
        # Asserting only that the STAMP moved is vacuous - the pack hash would
        # cover the payload anyway. The claim worth pinning is that the two
        # segments are DISJOINT, so a reader can see which half changed.
        pack = self._pack(tmp_path)
        before = cache.compute_stamp(pack).split(":")
        (pack / "payload" / "plugin.py").write_text("y = 2\n", encoding="utf-8")
        after = cache.compute_stamp(pack).split(":")
        assert after[3] != before[3] and after[1] == before[1]

    def test_an_adapter_change_moves_the_pack_segment_alone(self, tmp_path):
        pack = self._pack(tmp_path)
        before = cache.compute_stamp(pack).split(":")
        (pack / "adapter.py").write_text("x = 2\n", encoding="utf-8")
        after = cache.compute_stamp(pack).split(":")
        assert after[1] != before[1] and after[3] == before[3]


# =============================================================================
# RENDERING - the seam is easiest to lose here
# =============================================================================


def _screen(capsys) -> str:
    """Everything the run put on the terminal.

    The refusal line and a failed harness check go to STDERR, which is right
    for a CLI and is exactly why a test reading only `.out` would pass while
    the operator saw nothing.
    """
    captured = capsys.readouterr()
    return captured.out + captured.err


def _document(**overrides) -> dict:
    """A publishable document for the renderer to read."""
    document = {
        "status": "published",
        "group_list": ["hygiene", "pytest.static_self_skip", "oracle_execution"],
        "groups": {
            "hygiene": {
                "status": "measured",
                "score": 100,
                "violation_count": 0,
                "gate_coverage": {
                    "mechanism": "sys.addaudithook",
                    "child_processes_spawned": 2,
                    "sqlite3_connections": {"file_backed": 1},
                },
            },
            "pytest.static_self_skip": {
                "status": "measured",
                "kind": "nominate_only",
                "nomination_count": 7,
                "nominations": [
                    {
                        "species": "SELF-SKIP",
                        "verdict": "improve",
                        "nodeid": f"t.py::test_{n}",
                        "file": "t.py",
                        "line": n,
                    }
                    for n in range(7)
                ],
            },
            "oracle_execution": {"status": "not_applicable", "reason": "not built"},
        },
        "retired_groups": [{"group": "pytest.static_nominators", "ruling": "design revision 2"}],
        "harness": {"checks": [{"check": 1, "name": "n", "status": "pass", "detail": "d"}], "passed": 1, "failed": 0},
    }
    document.update(overrides)
    return document


class TestRender:
    """A number never prints alone, and a not_applicable always prints its reason."""

    def test_the_score_never_prints_without_the_blind_counts(self, capsys):
        render.render_target(_document(), "/tmp/a.json")
        output = capsys.readouterr().out
        assert "hygiene 100" in output and "cannot follow" in output

    def test_a_not_applicable_group_prints_its_reason(self, capsys):
        render.render_target(_document(), "/tmp/a.json")
        assert "not_applicable - not built" in capsys.readouterr().out

    def test_a_preview_says_how_many_rows_it_withheld(self, capsys):
        render.render_target(_document(), "/tmp/a.json")
        assert "and 2 more" in capsys.readouterr().out

    def test_the_retirement_ruling_is_rendered(self, capsys):
        render.render_target(_document(), "/tmp/a.json")
        assert "pytest.static_nominators" in capsys.readouterr().out

    def test_a_refusal_renders_its_law_and_not_a_score(self, capsys):
        document = _document(status="refused", refusal={"reason": "gate blind", "law": "T10", "code": 2, "detail": []})
        render.render_target(document, "/tmp/a.json")
        output = _screen(capsys)
        assert "REFUSED" in output and "T10" in output and "hygiene 100" not in output

    def test_a_failing_harness_check_is_printed(self, capsys):
        document = _document(
            harness={
                "checks": [{"check": 11, "name": "canary", "status": "fail", "detail": "not caught"}],
                "passed": 0,
                "failed": 1,
            }
        )
        render.render_target(document, "/tmp/a.json")
        assert "harness check 11 FAILED" in _screen(capsys)

    def test_the_renderer_names_no_ecosystem(self):
        # One `if ecosystem == "pytest"` here and the second ecosystem is a
        # rewrite rather than a directory.
        source = Path(render.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        literals = {
            node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert not any("pytest" in literal.lower() and "adapter" not in literal.lower() for literal in literals)
