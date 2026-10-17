# =================== AIPass ====================
# Name: test_audit_tests_lane_gate.py
# Description: audit-tests write gate: payload classifier and its gate log (split from test_audit_tests_lane.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/tests_pytest_standards/payload/audit_hygiene_plugin.py and gatelog.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in handlers/audit_tests/ and handlers/tests_pytest_standards/ parses
# seedgo: no-test-needed(documentation) — that the public lane functions carry docstrings

import importlib.util
import os
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.tests_pytest_standards import adapter, gatelog
from aipass.seedgo.tests.support_audit_tests_lane import _records

# Loaded by path: the payload must never be an importable aipass module (`execution_isolation` proves it).
_PAYLOAD = Path(adapter.PLUGIN_FILE)
_spec = importlib.util.spec_from_file_location("audit_hygiene_plugin_under_test", _PAYLOAD)
assert _spec is not None and _spec.loader is not None
plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plugin)


def _outside_path(*parts: str) -> str:
    """An absolute, native path that no allowance acquits, on either platform."""
    # A POSIX literal is drive-relative on Windows: abspath rewrites it, so a hardcoded literal never matches.
    return os.path.abspath(os.path.join(os.sep, "audit_tests_not_an_allowance", *parts))


@pytest.fixture
def state(tmp_path):
    """A gate state with a declared sandbox, so classification is meaningful."""
    fresh = plugin.GateState()
    fresh.log_path = str(tmp_path / "gate.jsonl")
    fresh.env_root = str(tmp_path / "env")
    fresh.target_root = str(tmp_path / "env" / "target")
    fresh.tmp_root = str(tmp_path / "tmp")
    fresh.pytest_basetemp = str(tmp_path / "tmp" / "pytest-of-me" / "pytest-0")
    fresh.pytest_tmp_prefix = str(tmp_path / "tmp" / "pytest-of-")
    return fresh


class TestClassifierPrecedence:
    """The copy is checked before every tmp allowance, and that ordering is the gate."""

    def test_a_write_inside_the_copy_is_a_violation_even_though_the_copy_is_under_tmpdir(self, state):
        inside = os.path.join(state.env_root, "target", "daemon_json", "rotation_log.json")
        assert plugin.classify(inside, state) == ("violation", "inside_copy")

    def test_the_copy_beats_the_pytest_basetemp_allowance_too(self, state):
        # The copy can live under pytest-of-* (a lane run inside pytest): checked first, that acquits every write.
        state.env_root = os.path.join(state.pytest_basetemp, "env")
        inside = os.path.join(state.env_root, "wrote.json")
        assert plugin.classify(inside, state) == ("violation", "inside_copy")

    def test_a_plain_tmpdir_write_is_allowed(self, state):
        assert plugin.classify(os.path.join(state.tmp_root, "scratch.txt"), state) == ("allowed", "tmpdir")

    def test_tmpdir_is_a_violation_once_the_allowance_is_withdrawn(self, state):
        state.tmpdir_allowed = False
        assert plugin.classify(os.path.join(state.tmp_root, "scratch.txt"), state)[0] == "violation"

    def test_a_write_to_the_home_directory_is_a_violation(self, state):
        assert plugin.classify("/home/somebody/.aipass", state) == ("violation", "outside_copy")


class TestAllowances:
    """Each allowance acquits by its own name, so deleting one is visible."""

    def test_the_plugin_log_is_allowed_by_exact_path(self, state):
        assert plugin.classify(state.log_path, state) == ("allowed", "plugin_log")

    def test_the_canary_is_its_own_verdict_and_never_a_violation(self, state):
        state.canary_path = os.path.join(state.target_root, ".audit_tests_canary_1")
        assert plugin.classify(state.canary_path, state) == ("canary", "canary")

    def test_pycache_is_allowed_anywhere(self, state, tmp_path):
        assert plugin.classify(str(tmp_path / "__pycache__" / "mod.cpython-312.pyc"), state)[1] == "pycache_dir"

    def test_a_bytecode_file_outside_pycache_is_still_allowed(self, state, tmp_path):
        assert plugin.classify(str(tmp_path / "mod.pyc"), state) == ("allowed", "bytecode")

    def test_coverage_data_is_allowed(self, state, tmp_path):
        assert plugin.classify(str(tmp_path / ".coverage.host.1"), state) == ("allowed", "coverage_data")

    def test_devnull_is_allowed_because_pytests_own_logging_opens_it(self, state):
        assert plugin.classify(os.devnull, state) == ("allowed", "devnull")

    def test_every_allowance_name_the_classifier_can_return_is_declared(self, state, tmp_path):
        # Acquitting under a name it never published widens the gate's own sandbox silently.
        declared = {name for name, _ in plugin.ALLOWANCES}
        returned = {
            plugin.classify(state.log_path, state)[1],
            plugin.classify(str(tmp_path / "__pycache__" / "a.pyc"), state)[1],
            plugin.classify(str(tmp_path / ".pytest_cache" / "v" / "f"), state)[1],
            plugin.classify(str(tmp_path / "mod.pyc"), state)[1],
            plugin.classify(str(tmp_path / ".coverage"), state)[1],
            plugin.classify(os.devnull, state)[1],
            plugin.classify(os.path.join(state.tmp_root, "f"), state)[1],
            plugin.classify(os.path.join(state.pytest_basetemp, "f"), state)[1],
        }
        assert returned <= declared


class TestSeparatorPortability:
    """The Windows branch of the classifier, driven from any platform."""

    WINDOWS = ("\\", "/")

    @pytest.fixture
    def windows(self, monkeypatch):
        monkeypatch.setattr(plugin, "SEPARATORS", self.WINDOWS)

    def test_a_forward_slash_pycache_is_a_pycache_dir_on_windows_too(self, state, windows, tmp_path):
        assert plugin.classify(str(tmp_path / "__pycache__" / "m.pyc"), state) == ("allowed", "pycache_dir")

    def test_a_forward_slash_coverage_file_is_never_a_violation_on_windows(self, state, windows, tmp_path):
        """Mutant: the classifier splits on the first separator alone in payload/audit_hygiene_plugin.py — killed."""
        # as_posix(), not str(): on Windows str() uses backslashes and the forward-slash case is never exercised.
        assert plugin.classify((tmp_path / ".coverage.host.1").as_posix(), state) == ("allowed", "coverage_data")

    def test_a_native_backslash_path_still_classifies_on_windows(self, state, windows):
        assert plugin.classify("D:\\x\\__pycache__\\m.pyc", state) == ("allowed", "pycache_dir")

    def test_a_backslash_is_a_filename_character_on_posix_and_never_a_separator(self):
        # Derived from os.altsep: splitting on "\\" on POSIX would tear a legal filename into invented parts.
        assert plugin._split_path("/weird/back\\slash.txt", ("/",)) == ["", "weird", "back\\slash.txt"]

    def test_the_windows_pair_is_derived_from_windows_values(self):
        # Spelled out, not re-derived: on POSIX altsep is None, so a derived expectation cannot fail.
        assert plugin.accepted_separators("\\", "/") == ("\\", "/")

    def test_the_posix_single_separator_is_derived_from_posix_values(self):
        assert plugin.accepted_separators("/", None) == ("/",)

    def test_the_platform_set_always_contains_the_platform_separator(self):
        assert os.sep in plugin.SEPARATORS
        assert plugin.SEPARATORS == plugin.accepted_separators()

    def test_a_copy_boundary_survives_mixed_spelling(self, state, windows):
        # env_root is native, the path is as typed: compared unnormalised, a write inside the copy reads outside.
        assert plugin._under("C:/env/pkg/f.py", "C:\\env", self.WINDOWS) is True

    def test_an_unrelated_tree_is_still_not_under_the_copy(self, state, windows):
        assert plugin._under("C:/other/f.py", "C:\\env", self.WINDOWS) is False


class TestWriteDetection:
    """Reads are not intercepted; the gate says so and behaves that way."""

    def test_a_read_only_open_is_not_a_write(self):
        assert plugin.is_write_open(("/some/path", "r", os.O_RDONLY)) is False

    def test_a_text_write_mode_is_a_write(self):
        assert plugin.is_write_open(("/some/path", "w", 0)) is True

    def test_an_append_mode_is_a_write(self):
        assert plugin.is_write_open(("/some/path", "a", 0)) is True

    def test_os_open_reports_no_mode_so_the_flags_decide(self):
        assert plugin.is_write_open(("/some/path", None, os.O_WRONLY | os.O_CREAT)) is True


class TestSqliteClassification:
    """Three buckets, because a bare count over-reports the blind spot."""

    def test_a_file_path_is_file_backed(self, tmp_path):
        assert plugin.classify_sqlite(str(tmp_path / "probe.db")) == "file_backed"

    def test_memory_is_not_a_file(self):
        assert plugin.classify_sqlite(":memory:") == "memory"

    def test_a_read_only_uri_is_its_own_bucket(self):
        assert plugin.classify_sqlite("file:/tmp/probe.db?mode=ro") == "read_only"

    def test_a_shared_memory_uri_is_memory_not_file_backed(self):
        assert plugin.classify_sqlite("file::memory:?cache=shared") == "memory"


class TestObservationCounting:
    """A spawn and a connect are counted, never convicted."""

    def test_a_subprocess_spawn_is_counted_and_attributed(self, state, monkeypatch):
        monkeypatch.setattr(plugin, "STATE", state)
        state.nodeid = "tests/test_x.py::test_spawns"
        assert plugin._record_observation("subprocess.Popen", ("/bin/true",)) is True
        assert state.spawns == 1
        assert state.spawn_nodeids == ["tests/test_x.py::test_spawns"]

    def test_a_spawn_never_becomes_a_violation(self, state, monkeypatch):
        monkeypatch.setattr(plugin, "STATE", state)
        plugin.audit_hook("subprocess.Popen", ("/bin/true",))
        assert state.violations == {}

    def test_an_sqlite_connect_lands_in_its_bucket(self, state, monkeypatch):
        monkeypatch.setattr(plugin, "STATE", state)
        plugin._record_observation("sqlite3.connect", ("/tmp/real.db",))
        plugin._record_observation("sqlite3.connect", (":memory:",))
        assert state.sqlite_buckets == {"file_backed": 1, "memory": 1, "read_only": 0}

    def test_an_ordinary_write_event_is_not_an_observation(self):
        assert plugin._record_observation("open", ("/tmp/f", "w", 0)) is False


class TestSessionRecording:
    """The two payload facts a mutation pass found untested on their first run."""

    def test_logstart_records_the_unit_in_execution_order(self, state, monkeypatch):
        monkeypatch.setattr(plugin, "STATE", state)
        plugin.pytest_runtest_logstart("tests/test_a.py::test_one", None)
        plugin.pytest_runtest_logstart("tests/test_a.py::test_two", None)
        assert state.executed_order == ["tests/test_a.py::test_one", "tests/test_a.py::test_two"]

    def test_a_unit_appears_once_however_many_phases_it_reports(self, state, monkeypatch):
        monkeypatch.setattr(plugin, "STATE", state)
        plugin.pytest_runtest_logstart("tests/test_a.py::test_one", None)
        plugin.pytest_runtest_logstart("tests/test_a.py::test_one", None)
        assert state.executed_order == ["tests/test_a.py::test_one"]

    def test_logstart_also_takes_over_attribution(self, state, monkeypatch):
        monkeypatch.setattr(plugin, "STATE", state)
        plugin.pytest_runtest_logstart("tests/test_a.py::test_one", None)
        assert state.nodeid == "tests/test_a.py::test_one"

    def test_a_write_to_the_canary_path_marks_the_gate_as_having_fired(self, state, monkeypatch):
        monkeypatch.setattr(plugin, "STATE", state)
        state.canary_path = os.path.join(state.target_root, ".audit_tests_canary_1")
        plugin._record_write("open", state.canary_path)
        assert state.canary_seen is True

    def test_the_canary_is_never_itself_recorded_as_a_violation(self, state, monkeypatch):
        # It is a deliberate out-of-sandbox write. Convicting the instrument's
        # own probe would score every proven run at 0.
        monkeypatch.setattr(plugin, "STATE", state)
        state.canary_path = os.path.join(state.target_root, ".audit_tests_canary_1")
        plugin._record_write("open", state.canary_path)
        assert state.violations == {}


class TestAttribution:
    """A gate that sees a write but cannot say who is only half a gate."""

    def test_a_violation_carries_the_running_nodeid(self, state, monkeypatch):
        monkeypatch.setattr(plugin, "STATE", state)
        state.nodeid, state.phase = "tests/test_x.py::test_forges", "call"
        written = _outside_path("somebody", ".aipass", "state.json")
        plugin._record_write("open", written)
        assert ("tests/test_x.py::test_forges", "call", "open", written) in state.violations

    def test_the_attribution_key_is_the_native_normalized_absolute_path(self, state, monkeypatch):
        # The key is normpath of an absolute path, so NATIVE separators: the published path must resolve in
        # the reader's own shell.
        monkeypatch.setattr(plugin, "STATE", state)
        state.nodeid, state.phase = "tests/test_x.py::test_forges", "call"
        spelled = _outside_path("somebody", "state.json").replace(os.sep, "/")
        plugin._record_write("open", spelled)
        recorded = [key[3] for key in state.violations]
        assert recorded == [os.path.normpath(spelled)]
        assert os.path.isabs(recorded[0])

    def test_a_relative_path_is_counted_not_guessed_at(self, state, monkeypatch):
        monkeypatch.setattr(plugin, "STATE", state)
        plugin._record_write("os.remove", "inner/file")
        assert state.relative_unattributable == 1
        assert state.violations == {}

    def test_the_key_is_normalized_so_two_spellings_of_one_file_are_one_record(self, state, monkeypatch):
        # A ".." segment needs normalising on every platform, so this kills the deleted-normpath mutant anywhere.
        monkeypatch.setattr(plugin, "STATE", state)
        state.nodeid, state.phase = "tests/test_x.py::test_forges", "call"
        direct = _outside_path("pkg", "state.json")
        # Not built through _outside_path: its abspath normalises the detour away before the code sees it.
        detoured = os.path.join(os.path.dirname(direct), "sub", "..", "state.json")
        plugin._record_write("open", direct)
        plugin._record_write("open", detoured)
        assert [key[3] for key in state.violations] == [direct]
        assert list(state.violations.values()) == [2]

    def test_repeat_writes_to_one_path_increment_rather_than_duplicate(self, state, monkeypatch):
        monkeypatch.setattr(plugin, "STATE", state)
        for _ in range(3):
            plugin._record_write("open", "/home/somebody/.aipass/state.json")
        assert list(state.violations.values()) == [3]


class TestGateLogReading:
    """A log that cannot be read is a fact, not a clean result."""

    def test_a_missing_log_raises_rather_than_reading_as_empty(self, tmp_path):
        with pytest.raises(gatelog.GateLogError) as caught:
            gatelog.read_records(tmp_path / "absent.jsonl")
        assert "the plugin did not run" in str(caught.value)

    def test_a_malformed_line_is_counted_rather_than_dropped_in_silence(self, tmp_path):
        log = tmp_path / "gate.jsonl"
        log.write_text('{"rec": "header"}\nnot json at all\n', encoding="utf-8")
        records = gatelog.read_records(log)
        assert {"rec": "malformed_lines", "count": 1} in records

    def test_blank_lines_are_not_malformed(self, tmp_path):
        log = tmp_path / "gate.jsonl"
        log.write_text('{"rec": "header"}\n\n\n', encoding="utf-8")
        assert all(record.get("rec") != "malformed_lines" for record in gatelog.read_records(log))


class TestMeasurement:
    """`proven` is a fact about the canary; nothing here decides a status."""

    def test_a_caught_canary_with_the_hook_installed_is_proven(self):
        assert gatelog.measure(_records(), timed_out=False)["proven"] is True

    def test_a_proven_run_carries_no_unproven_reason(self):
        assert gatelog.measure(_records(), timed_out=False)["unproven_reason"] == ""

    def test_a_missing_hook_is_unproven_and_says_the_gate_was_not_installed(self):
        measured = gatelog.measure(_records(hook=False), timed_out=False)
        assert measured["proven"] is False
        assert "was not installed" in measured["unproven_reason"]

    def test_a_canary_the_gate_missed_is_unproven_and_says_the_gate_is_blind(self):
        measured = gatelog.measure(_records(canary_caught=False), timed_out=False)
        assert measured["proven"] is False
        assert "did NOT catch it" in measured["unproven_reason"]

    def test_an_empty_log_says_the_plugin_never_reported_rather_than_blaming_the_hook(self):
        # An empty log has no header: the reason names that fact rather than infer an uninstalled gate.
        measured = gatelog.measure([], timed_out=False)
        assert measured["proven"] is False
        assert "never reported" in measured["unproven_reason"]

    def test_a_run_that_reported_but_fired_no_canary_says_so(self):
        records = [{"rec": "header", "hook_installed": True}, {"rec": "summary", "canary": {"attempted": False}}]
        assert "no canary was fired" in gatelog.measure(records, timed_out=False)["unproven_reason"]

    def test_a_budget_expiry_says_the_budget_expired_rather_than_blaming_the_canary(self):
        # The reason must name the budget, or a timeout looks like a broken gate.
        measured = gatelog.measure([], timed_out=True)
        assert "budget expired" in measured["unproven_reason"]

    def test_violations_are_published_untruncated(self):
        measured = gatelog.measure(_records(violations=7), timed_out=False)
        assert measured["violation_count"] == 7
        assert len(measured["violations"]) == 7

    def test_the_measurement_carries_no_status_and_no_score(self):
        # The seam: an adapter returns measurements, the core applies the laws.
        measured = gatelog.measure(_records(), timed_out=False)
        assert "status" not in measured
        assert "score" not in measured


class TestGateCoverage:
    """Law S8: a score without a declared blind spot is a refusal."""

    def test_the_blind_list_is_never_empty(self):
        assert gatelog.measure(_records(), timed_out=False)["gate_coverage"]["blind"]

    def test_the_mechanism_names_that_the_hook_is_per_interpreter(self):
        assert "per-interpreter" in gatelog.GATE_MECHANISM

    def test_child_processes_are_blind_and_said_to_be(self):
        blind = " ".join(gatelog.GATE_BLIND)
        assert "child processes" in blind

    def test_reads_are_declared_unmeasurable(self):
        assert any("reads of any kind" in entry for entry in gatelog.GATE_BLIND)

    def test_the_note_carries_the_counted_numbers_not_a_static_claim(self):
        summary = {
            "child_processes_spawned": 14,
            "sqlite3_connections": {"file_backed": 9, "memory": 3, "read_only": 0},
        }
        note = gatelog.gate_coverage(summary)["note"]
        assert "14 child process(es)" in note
        assert "9 file-backed" in note

    def test_the_note_refuses_to_let_a_hundred_read_as_clean(self):
        note = gatelog.gate_coverage({})["note"]
        assert "not 'no violation'" in note


class TestExecutedOrder:
    """Rev-4 section 9.2: order-specific and unreconstructable after the fact."""

    def test_the_order_comes_from_the_session_not_from_the_violations(self):
        # Order comes from every record: violation records list only units that wrote, dropping clean tests.
        records = _records(violations=1, order=["tests/a.py::clean", "tests/test_x.py::test_0"])
        assert gatelog.executed_order(records) == ["tests/a.py::clean", "tests/test_x.py::test_0"]

    def test_a_run_with_no_summary_reports_no_order_rather_than_a_partial_one(self):
        assert gatelog.executed_order([{"rec": "header"}]) == []
