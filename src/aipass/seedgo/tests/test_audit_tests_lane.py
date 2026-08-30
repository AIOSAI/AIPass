# =================== AIPass ====================
# Name: test_audit_tests_lane.py
# Description: tests for the pytest pack, the payload gate and the verb
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
Phase 4-5 of the audit-tests lane: the pack, the payload and the runner.

THE CREATION-SIDE BAR THIS LANE PROPOSES, APPLIED TO ITSELF. Law L0 says a test
proves something when there EXISTS a change to production code that makes it
fail, so every test here is written to name one behaviour that a mutation could
remove. Assertions on a law's PREFIX rather than on its own message have
already let a deleted rule survive once in this suite; the fix was to assert
the branch's own words, and that discipline is kept here.
"""

import importlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.audit_tests import m10, refusal, runner, spine, target as target_module
from aipass.seedgo.apps.handlers.tests_pytest_standards import adapter, envcopy, gatelog

# The payload is deliberately NOT an importable aipass module - that is the
# property `execution_isolation` proves. Loading it by path here is how a test
# reaches something that must never be on the package path.
_PAYLOAD = Path(adapter.PLUGIN_FILE)
_spec = importlib.util.spec_from_file_location("audit_hygiene_plugin_under_test", _PAYLOAD)
assert _spec is not None and _spec.loader is not None
plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plugin)


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


# =============================================================================
# THE CLASSIFIER - where the gate decides what a write means
# =============================================================================


class TestClassifierPrecedence:
    """The copy is checked before every tmp allowance, and that ordering is the gate."""

    def test_a_write_inside_the_copy_is_a_violation_even_though_the_copy_is_under_tmpdir(self, state):
        inside = os.path.join(state.env_root, "target", "daemon_json", "rotation_log.json")
        assert plugin.classify(inside, state) == ("violation", "inside_copy")

    def test_the_copy_beats_the_pytest_basetemp_allowance_too(self, state):
        # The scratch copy really can live under a pytest-of-* tree: it does
        # whenever the lane is run from inside another pytest session. If that
        # allowance were checked first it would acquit every write the gate
        # exists to catch.
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

    def test_pycache_is_allowed_anywhere(self, state):
        assert plugin.classify("/anywhere/__pycache__/mod.cpython-312.pyc", state)[1] == "pycache_dir"

    def test_a_bytecode_file_outside_pycache_is_still_allowed(self, state):
        assert plugin.classify("/anywhere/mod.pyc", state) == ("allowed", "bytecode")

    def test_coverage_data_is_allowed(self, state):
        assert plugin.classify("/anywhere/.coverage.host.1", state) == ("allowed", "coverage_data")

    def test_devnull_is_allowed_because_pytests_own_logging_opens_it(self, state):
        assert plugin.classify(os.devnull, state) == ("allowed", "devnull")

    def test_every_allowance_name_the_classifier_can_return_is_declared(self, state):
        # A gate that acquits under a name it never published has widened its
        # own sandbox silently, which is the one thing a gate may never do.
        declared = {name for name, _ in plugin.ALLOWANCES}
        returned = {
            plugin.classify(state.log_path, state)[1],
            plugin.classify("/x/__pycache__/a.pyc", state)[1],
            plugin.classify("/x/.pytest_cache/v/f", state)[1],
            plugin.classify("/x/mod.pyc", state)[1],
            plugin.classify("/x/.coverage", state)[1],
            plugin.classify(os.devnull, state)[1],
            plugin.classify(os.path.join(state.tmp_root, "f"), state)[1],
            plugin.classify(os.path.join(state.pytest_basetemp, "f"), state)[1],
        }
        assert returned <= declared


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

    def test_a_file_path_is_file_backed(self):
        assert plugin.classify_sqlite("/tmp/probe.db") == "file_backed"

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
    """The two payload facts a mutation pass found untested on their first run.

    Both were exercised only end-to-end, so deleting either left 114 tests
    green while the artifact quietly lost a field. An integration run that
    passes is not a pin on the line that made it pass.
    """

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
        plugin._record_write("open", "/home/somebody/.aipass/state.json")
        assert ("tests/test_x.py::test_forges", "call", "open", "/home/somebody/.aipass/state.json") in state.violations

    def test_a_relative_path_is_counted_not_guessed_at(self, state, monkeypatch):
        monkeypatch.setattr(plugin, "STATE", state)
        plugin._record_write("os.remove", "inner/file")
        assert state.relative_unattributable == 1
        assert state.violations == {}

    def test_repeat_writes_to_one_path_increment_rather_than_duplicate(self, state, monkeypatch):
        monkeypatch.setattr(plugin, "STATE", state)
        for _ in range(3):
            plugin._record_write("open", "/home/somebody/.aipass/state.json")
        assert list(state.violations.values()) == [3]


# =============================================================================
# THE GATE LOG - the normalized measurement the core consumes
# =============================================================================


def _records(*, hook=True, canary_caught=True, violations=0, order=None):
    """A synthetic run's records, shaped exactly as the payload writes them."""
    records = [{"rec": "header", "hook_installed": hook, "allowances": [], "observed_events": ["open"]}]
    records.append({"rec": "copy_check", "verified_live": True, "resolved_to": "/env/pkg/__init__.py"})
    for index in range(violations):
        records.append(
            {
                "rec": "violation",
                "nodeid": f"tests/test_x.py::test_{index}",
                "phase": "call",
                "event": "open",
                "path": f"/real/state_{index}.json",
                "count": 1,
                "where": "outside_copy",
            }
        )
    records.append(
        {
            "rec": "summary",
            "canary": {"attempted": True, "caught": canary_caught, "path": "/env/c", "error": ""},
            "executed_order": list(order or []),
            "child_processes_spawned": 0,
            "sqlite3_connections": {"file_backed": 0, "memory": 0, "read_only": 0},
        }
    )
    return records


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
        # Written expecting "the write gate was not installed" and the run
        # refuted it: an empty log has no header, so that branch fired and
        # invented a specific cause from missing evidence. The reason now names
        # the fact instead of inferring one.
        measured = gatelog.measure([], timed_out=False)
        assert measured["proven"] is False
        assert "never reported" in measured["unproven_reason"]

    def test_a_run_that_reported_but_fired_no_canary_says_so(self):
        records = [{"rec": "header", "hook_installed": True}, {"rec": "summary", "canary": {"attempted": False}}]
        assert "no canary was fired" in gatelog.measure(records, timed_out=False)["unproven_reason"]

    def test_a_budget_expiry_says_the_budget_expired_rather_than_blaming_the_canary(self):
        # The hang-to-refusal conversion falls out of canary-or-refuse, but the
        # REASON a reader is handed must still name the budget, or a timeout
        # looks like a broken gate.
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
        # Built the other way first, and a live run refuted it: deriving the
        # order from violation records lists only the units that WROTE, so a
        # clean test vanished from "the order the tests executed in".
        records = _records(violations=1, order=["tests/a.py::clean", "tests/test_x.py::test_0"])
        assert gatelog.executed_order(records) == ["tests/a.py::clean", "tests/test_x.py::test_0"]

    def test_a_run_with_no_summary_reports_no_order_rather_than_a_partial_one(self):
        assert gatelog.executed_order([{"rec": "header"}]) == []


# =============================================================================
# THE ADAPTER CONTRACT
# =============================================================================


class TestAdapterShape:
    """The shape gate: this pack must stay invisible to the audit engine."""

    def test_the_adapter_defines_no_check_module(self):
        assert not hasattr(adapter, "check_module")

    def test_the_adapter_defines_no_check_branch(self):
        # If this ever goes green the pack becomes visible to a file-walk that
        # would invoke it once per .py file, with no timeout anywhere.
        assert not hasattr(adapter, "check_branch")

    def test_the_adapter_declares_the_api_this_core_speaks(self):
        from aipass.seedgo.apps.handlers.audit_tests import adapters

        assert adapter.ADAPTER_API == adapters.SUPPORTED_ADAPTER_API

    def test_the_pack_manifest_declares_execution_kind(self):
        manifest = json.loads((Path(adapter.__file__).parent / "pack.json").read_text(encoding="utf-8"))
        assert manifest["kind"] == "execution"

    def test_the_manifest_records_the_grant_as_conditional_on_the_machine_check(self):
        manifest = json.loads((Path(adapter.__file__).parent / "pack.json").read_text(encoding="utf-8"))
        assert "execution_isolation" in manifest["granted"]["condition"]


class TestPayloadIsolation:
    """The condition @devpulse's bypass grant is conditional on."""

    def test_the_real_payload_imports_no_aipass(self):
        from aipass.seedgo.apps.handlers.audit_tests import adapters

        assert adapters.execution_isolation(Path(adapter.__file__).parent)["isolated"] is True

    def test_a_planted_aipass_import_fails_registration(self, tmp_path):
        from aipass.seedgo.apps.handlers.audit_tests import adapters

        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "leaky.py").write_text("from aipass.prax import logger\n", encoding="utf-8")
        result = adapters.execution_isolation(tmp_path)
        assert result["isolated"] is False
        assert any("leaky.py" in offender for offender in result["offenders"])


class TestDetect:
    """Cheap, read-only, never raises — and it never imports the target."""

    def test_a_directory_with_tests_is_claimed(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_a.py").write_text("def test_a(): pass\n", encoding="utf-8")
        detected = adapter.detect(tmp_path)
        assert detected["applicable"] is True
        assert detected["unit_count"] == 1

    def test_a_directory_with_no_test_files_is_not_claimed(self, tmp_path):
        detected = adapter.detect(tmp_path)
        assert detected["applicable"] is False
        assert detected["unit_count"] == 0

    def test_a_refusal_to_claim_still_carries_a_reason(self, tmp_path):
        assert adapter.detect(tmp_path)["reason"]

    def test_loose_test_files_at_the_root_are_found(self, tmp_path):
        (tmp_path / "test_root.py").write_text("def test_a(): pass\n", encoding="utf-8")
        assert adapter.detect(tmp_path)["unit_count"] == 1

    def test_detect_never_raises_on_a_path_that_is_not_there(self, tmp_path):
        assert adapter.detect(tmp_path / "absent")["applicable"] is False


class TestNominate:
    """Static species nominate; they never score (Law M1)."""

    def test_every_nominated_group_carries_no_score(self, tmp_path):
        for document in adapter.nominate(_spec_for(tmp_path)).values():
            assert document["score"] is None

    def test_every_group_that_did_not_run_says_why(self, tmp_path):
        # Written when NOTHING was built, so it asserted every group was
        # not_applicable - which pinned the calendar, not the law. The law is
        # Law S1: a group that did not run carries a reason. A group that DID
        # run is a different document, and both now exist.
        for name, document in adapter.nominate(_spec_for(tmp_path)).items():
            if document["status"] == "not_applicable":
                assert document["reason"], name

    def test_the_unbuilt_execution_groups_are_still_not_applicable(self, tmp_path):
        for name in adapter.UNBUILT_EXECUTION_GROUPS:
            document = adapter.nominate(_spec_for(tmp_path))[name]
            assert document["status"] == "not_applicable" and document["reason"]

    def test_the_declared_groups_are_all_returned_by_nominate(self, tmp_path):
        # A declared group the adapter never fills would vanish from the
        # published list, which is precisely what S3 exists to catch.
        assert set(adapter.declared_groups()) == set(adapter.nominate(_spec_for(tmp_path)))


class TestTeardown:
    """A function that deletes a tree must refuse an implausible root."""

    def test_teardown_removes_the_scratch_env(self, tmp_path):
        env = tmp_path / "env"
        env.mkdir()
        adapter.teardown(_spec_for(env))
        assert not env.exists()

    def test_teardown_is_idempotent(self, tmp_path):
        env = tmp_path / "env"
        env.mkdir()
        spec = _spec_for(env)
        adapter.teardown(spec)
        adapter.teardown(spec)

    def test_teardown_refuses_the_home_directory(self, monkeypatch, tmp_path):
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        tmp_path.mkdir(exist_ok=True)
        adapter.teardown(_spec_for(tmp_path))
        assert tmp_path.exists()

    def test_teardown_accepts_no_spec_at_all(self):
        adapter.teardown(None)


def _spec_for(env_root: Path) -> envcopy.EnvSpec:
    """A minimal EnvSpec pointing at a scratch root."""
    return envcopy.EnvSpec(
        layout="plain",
        env_root=env_root,
        run_cwd=env_root,
        target_copy=env_root / "t",
        target_module="",
        test_arg="t",
        python=Path("/usr/bin/python3"),
        pythonpath=str(env_root),
        plugin_dir=env_root / "_audit_plugin",
        log_path=env_root / "_audit" / "hygiene.jsonl",
    )


# =============================================================================
# THE ENVIRONMENT - Law M10
# =============================================================================


class TestEnvLayout:
    """The aipass layout has to be mirrored or the copy is not what loads."""

    def test_a_branch_under_src_aipass_is_the_aipass_layout(self, tmp_path):
        branch = tmp_path / "src" / "aipass" / "somebranch"
        branch.mkdir(parents=True)
        layout, repo_root = envcopy.detect_layout(branch)
        assert layout == "aipass"
        assert repo_root == tmp_path

    def test_any_other_directory_is_plain(self, tmp_path):
        assert envcopy.detect_layout(tmp_path)[0] == "plain"

    def test_a_plain_target_has_no_repo_root(self, tmp_path):
        assert envcopy.detect_layout(tmp_path)[1] is None


class TestM10Completeness:
    """A symlinked sibling is writable, so it is named rather than assumed away."""

    def test_an_env_with_no_symlinks_is_m10_complete(self, tmp_path):
        assert _spec_for(tmp_path).m10_complete is True

    def test_one_symlinked_sibling_makes_the_env_incomplete(self, tmp_path):
        spec = _spec_for(tmp_path)
        spec.symlinked_siblings = ["prax"]
        assert spec.m10_complete is False

    def test_the_environment_document_publishes_the_completeness_flag(self, tmp_path):
        spec = _spec_for(tmp_path)
        spec.symlinked_siblings = ["prax"]
        assert spec.to_document()["m10_complete"] is False

    def test_the_excludes_are_published_as_part_of_the_contract(self, tmp_path):
        published = _spec_for(tmp_path).to_document()["excludes"]
        assert ".chroma" in published
        assert ".venv" in published


class TestPythonResolution:
    """No interpreter path is hardcoded; a one-machine checker is not a checker."""

    def test_an_explicit_override_wins(self, tmp_path):
        assert envcopy.find_python(tmp_path, "/opt/py/bin/python") == Path("/opt/py/bin/python")

    def test_a_nearby_venv_is_preferred_over_the_running_interpreter(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AUDIT_TESTS_PYTHON", raising=False)
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("", encoding="utf-8")
        assert envcopy.find_python(tmp_path) == venv / "python"

    def test_the_environment_variable_is_honoured(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUDIT_TESTS_PYTHON", "/opt/env/bin/python")
        assert envcopy.find_python(tmp_path) == Path("/opt/env/bin/python")


class TestSnapshotDiff:
    """Content is hashed, because a same-tick timestamp restore is invisible."""

    def test_a_rewritten_file_is_reported_as_modified(self, tmp_path):
        probe = tmp_path / "state.json"
        probe.write_text("{}", encoding="utf-8")
        before = m10.snapshot_tree(tmp_path)
        probe.write_text('{"forged": true}', encoding="utf-8")
        os.utime(probe, ns=(0, 0))
        after = m10.snapshot_tree(tmp_path)
        assert str(probe) in m10.diff_snapshots(before, after)["modified"]

    def test_two_files_of_identical_size_are_told_apart_by_content(self, tmp_path):
        # The rewrite test above changes the file's SIZE, so the diff fires on
        # stat alone and the hash is never exercised - a mutation deleting the
        # md5 survived it. This is the pin the hash actually needs: the
        # same-size forge is the case stat fields cannot see, and it is the
        # only reason content is hashed rather than inferred.
        first, second = tmp_path / "a.json", tmp_path / "b.json"
        first.write_text('{"a": 1}', encoding="utf-8")
        second.write_text('{"a": 2}', encoding="utf-8")
        left = m10._fingerprint(str(first), m10.HASH_SIZE_LIMIT)
        right = m10._fingerprint(str(second), m10.HASH_SIZE_LIMIT)
        assert left is not None and right is not None
        assert left[1] == right[1]
        assert left[4] != right[4]

    def test_a_same_size_rewrite_is_still_reported_as_modified(self, tmp_path):
        probe = tmp_path / "state.json"
        probe.write_text('{"a": 1}', encoding="utf-8")
        before = m10.snapshot_tree(tmp_path)
        original = probe.stat().st_mtime_ns
        probe.write_text('{"a": 2}', encoding="utf-8")
        os.utime(probe, ns=(original, original))
        after = m10.snapshot_tree(tmp_path)
        assert str(probe) in m10.diff_snapshots(before, after)["modified"]

    def test_a_file_too_large_to_hash_is_still_fingerprinted_by_stat(self, tmp_path):
        probe = tmp_path / "big.bin"
        probe.write_bytes(b"x" * 64)
        fingerprint = m10._fingerprint(str(probe), 8)
        assert fingerprint is not None
        assert fingerprint[4] == ""

    def test_a_file_that_vanished_is_absent_rather_than_an_error(self, tmp_path):
        assert m10._fingerprint(str(tmp_path / "gone.txt"), m10.HASH_SIZE_LIMIT) is None

    def test_an_untouched_tree_diffs_to_nothing(self, tmp_path):
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        before = m10.snapshot_tree(tmp_path)
        assert m10.diff_snapshots(before, m10.snapshot_tree(tmp_path)) == {
            "added": [],
            "removed": [],
            "modified": [],
        }

    def test_a_removed_file_is_reported_as_removed(self, tmp_path):
        probe = tmp_path / "a.txt"
        probe.write_text("x", encoding="utf-8")
        before = m10.snapshot_tree(tmp_path)
        probe.unlink()
        assert m10.diff_snapshots(before, m10.snapshot_tree(tmp_path))["removed"] == [str(probe)]


# =============================================================================
# THE RUNNER - where measurements become law-checked documents
# =============================================================================


def _target(tmp_path) -> target_module.Target:
    """A directory target the runner can carry through the pipeline."""
    return target_module.Target(name="probe", path=tmp_path, kind="directory", resolved_from="test")


class TestScoring:
    """The score is a gate, not an opinion: 100 or 0, never a percentage."""

    def test_a_clean_proven_run_scores_one_hundred(self):
        document = _hygiene(violations=[])
        assert document["score"] == 100
        assert document["passed"] is True

    def test_a_single_violation_scores_zero(self):
        assert _hygiene(violations=[{"path": "/real/state.json"}])["score"] == 0

    def test_many_violations_score_the_same_zero_as_one(self):
        # No partial credit: forging 31 log entries instead of 79 is not a
        # better suite, and a percentage would let a branch improve its number
        # without fixing anything.
        assert _hygiene(violations=[{"path": f"/real/{i}"} for i in range(31)])["score"] == 0

    def test_a_measured_group_declares_itself_measured(self):
        assert _hygiene(violations=[])["status"] == "measured"

    def test_the_proven_flag_survives_into_the_published_group(self):
        assert _hygiene(violations=[])["gate_proven"] is True

    def test_the_published_group_carries_no_internal_proven_key(self):
        # `proven`/`unproven_reason` are the adapter's vocabulary. Leaking them
        # into the artifact would publish two names for one fact.
        document = _hygiene(violations=[])
        assert "proven" not in document
        assert "unproven_reason" not in document

    def test_the_budget_and_elapsed_are_both_published(self):
        document = _hygiene(violations=[])
        assert document["budget_seconds"] == 900
        assert document["elapsed_seconds"] == 1.5


def _hygiene(*, violations):
    """A scored hygiene group built from a proven gate measurement."""
    gate = gatelog.measure(_records(), timed_out=False)
    gate["violations"] = violations
    gate["violation_count"] = len(violations)
    return runner._hygiene_group(
        gate,
        budget_seconds=900,
        elapsed_seconds=1.5,
        config_note="serial",
        environment={"m10_complete": True},
        liveness={"live": True},
    )


class TestGroupComposition:
    """Every declared group appears, in order, and none of them is ever 0."""

    def test_the_published_groups_match_the_group_list_exactly_and_in_order(self):
        group_list = spine.compose_group_list("pytest", ["static_nominators"])
        groups = runner._compose_groups(group_list, "pytest", _hygiene(violations=[]), {})
        assert list(groups) == group_list

    def test_an_unimplemented_spine_group_is_not_applicable_with_a_reason(self):
        group_list = spine.compose_group_list("pytest", [])
        groups = runner._compose_groups(group_list, "pytest", _hygiene(violations=[]), {})
        assert groups["order_dependence"]["status"] == "not_applicable"
        assert groups["order_dependence"]["reason"]

    def test_an_unimplemented_spine_group_is_never_scored_zero(self):
        group_list = spine.compose_group_list("pytest", [])
        groups = runner._compose_groups(group_list, "pytest", _hygiene(violations=[]), {})
        assert groups["oracle_execution"]["score"] is None

    def test_an_adapter_group_is_matched_by_its_bare_name(self):
        group_list = spine.compose_group_list("pytest", ["static_nominators"])
        nominations = {
            "static_nominators": {"tier": "static", "status": "not_applicable", "reason": "x", "score": None}
        }
        groups = runner._compose_groups(group_list, "pytest", _hygiene(violations=[]), nominations)
        assert groups["pytest.static_nominators"]["reason"] == "x"

    def test_a_declared_group_the_adapter_forgot_still_appears_and_names_the_adapter(self):
        group_list = spine.compose_group_list("pytest", ["static_nominators"])
        groups = runner._compose_groups(group_list, "pytest", _hygiene(violations=[]), {})
        document = groups["pytest.static_nominators"]
        assert document["status"] == "not_applicable"
        assert "pytest adapter declared" in document["reason"]


class TestM10Proof:
    """The lane's central promise, measured — and proven able to fail.

    A proof that has only ever come back green is indistinguishable from a
    proof that cannot come back red, which is precisely the instrument species
    this lane exists to catch. So the failing direction is pinned first.
    """

    def test_an_untouched_tree_proves_m10_held(self, tmp_path):
        (tmp_path / "state.json").write_text("{}", encoding="utf-8")
        before = m10.snapshot_tree(tmp_path)
        proof = runner._m10_proof(_target(tmp_path), before, {})
        assert proof["probed"] is True
        assert proof["real_tree_unchanged"] is True

    def test_a_forged_file_makes_the_proof_report_a_violation(self, tmp_path):
        probe = tmp_path / "state.json"
        probe.write_text("{}", encoding="utf-8")
        before = m10.snapshot_tree(tmp_path)
        probe.write_text('{"forged": true}', encoding="utf-8")
        proof = runner._m10_proof(_target(tmp_path), before, {})
        assert proof["real_tree_unchanged"] is False
        assert str(probe) in proof["diff"]["modified"]

    def test_a_new_file_in_the_real_tree_is_a_violation_too(self, tmp_path):
        before = m10.snapshot_tree(tmp_path)
        (tmp_path / "left_behind.json").write_text("{}", encoding="utf-8")
        assert runner._m10_proof(_target(tmp_path), before, {})["real_tree_unchanged"] is False

    def test_the_number_of_files_compared_is_published(self, tmp_path):
        (tmp_path / "a.json").write_text("{}", encoding="utf-8")
        (tmp_path / "b.json").write_text("{}", encoding="utf-8")
        before = m10.snapshot_tree(tmp_path)
        assert runner._m10_proof(_target(tmp_path), before, {})["files_fingerprinted"] == 2

    def test_a_disturbed_tree_is_recorded_as_an_operational_event(self, tmp_path, monkeypatch):
        # The most serious thing this lane can discover about ITSELF, so it is
        # recorded where the fact is established rather than at a call site
        # some future caller might not use.
        recorded = []
        monkeypatch.setattr(m10.json_handler, "log_operation", lambda name, payload: recorded.append(name))
        probe = tmp_path / "state.json"
        probe.write_text("{}", encoding="utf-8")
        before = m10.snapshot_tree(tmp_path)
        probe.write_text('{"forged": true}', encoding="utf-8")
        m10.diff_snapshots(before, m10.snapshot_tree(tmp_path))
        assert "m10_violated" in recorded

    def test_an_intact_tree_records_no_violation_event(self, tmp_path, monkeypatch):
        recorded = []
        monkeypatch.setattr(m10.json_handler, "log_operation", lambda name, payload: recorded.append(name))
        (tmp_path / "state.json").write_text("{}", encoding="utf-8")
        before = m10.snapshot_tree(tmp_path)
        m10.diff_snapshots(before, m10.snapshot_tree(tmp_path))
        assert recorded == []

    def test_a_skipped_proof_says_not_probed_rather_than_reporting_clean(self, tmp_path):
        # not_probed and passed must never look the same - Law S1 applied to
        # the lane's own harness.
        proof = runner._m10_proof(_target(tmp_path), None, {})
        assert proof["probed"] is False
        assert proof["real_tree_unchanged"] is None

    def test_a_skipped_proof_still_says_why(self, tmp_path):
        assert runner._m10_proof(_target(tmp_path), None, {})["note"]

    def test_the_proof_is_skipped_only_when_explicitly_asked(self, tmp_path):
        assert runner._fingerprint_target(_target(tmp_path), {"no_m10_proof": True}) is None
        assert runner._fingerprint_target(_target(tmp_path), {}) is not None


class TestUnprovenRefusalWording:
    """Each pre-built refusal is used only where its wording is true."""

    def test_a_timeout_gets_the_budget_refusal(self):
        built = runner._unproven_refusal({}, {"timed_out": True, "budget_seconds": 300}, 301.0)
        assert built.code == refusal.EXIT_BUDGET_EXHAUSTED
        assert built.law == "T-BUDGET"

    def test_a_missed_canary_gets_the_canary_refusal_only_when_the_hook_was_installed(self):
        gate = {"hook_installed": True, "canary": {"attempted": True, "caught": False}}
        built = runner._unproven_refusal(gate, {}, 1.0)
        assert "did not catch its own planted canary" in built.reason

    def test_a_disabled_gate_is_not_reported_as_a_blind_gate(self):
        # --prove-refusal switches the hook OFF, and the canary is still
        # written and still not caught - so the canary branch fires unless the
        # hook check comes first. It reported a blind gate for a run where no
        # gate existed, which is a wrong diagnosis, not a wording nit.
        gate = {
            "hook_installed": False,
            "canary": {"attempted": True, "caught": False},
            "unproven_reason": "the write gate was not installed, so a clean result would mean nothing (Law T10)",
        }
        assert "was not installed" in runner._unproven_refusal(gate, {}, 1.0).reason

    def test_an_uninstalled_hook_keeps_the_measurements_own_reason(self):
        # Reaching for the canary builder here would restate a cause the run
        # never established.
        gate = {"canary": {"attempted": False}, "unproven_reason": "the write gate was not installed"}
        built = runner._unproven_refusal(gate, {}, 1.0)
        assert built.reason == "the write gate was not installed"

    def test_every_unproven_refusal_carries_detail_a_reader_can_act_on(self):
        assert runner._unproven_refusal({}, {}, 1.0).detail


class TestRefusalPath:
    """A refusal publishes a complete artifact, never an empty one."""

    def test_a_refused_run_publishes_every_group_as_not_applicable(self, tmp_path, monkeypatch):
        written = _publish_refusal(tmp_path, monkeypatch, refusal.EXIT_NO_ADAPTER, "nothing claims this")
        assert all(group["status"] == "not_applicable" for group in written["groups"].values())

    def test_a_refused_run_names_the_law_it_refuses_under(self, tmp_path, monkeypatch):
        written = _publish_refusal(tmp_path, monkeypatch, refusal.EXIT_BUDGET_EXHAUSTED, "the budget expired")
        assert written["refusal"]["law"] == "T-BUDGET"

    def test_a_refused_run_carries_the_reason_into_every_group(self, tmp_path, monkeypatch):
        written = _publish_refusal(tmp_path, monkeypatch, refusal.EXIT_UNPROVEN, "the gate was blind")
        assert all("the gate was blind" in group["reason"] for group in written["groups"].values())

    def test_a_refused_artifact_reaches_disk(self, tmp_path, monkeypatch):
        _publish_refusal(tmp_path, monkeypatch, refusal.EXIT_UNPROVEN, "the gate was blind")
        assert list((tmp_path / "artifacts").glob("audit_tests_*.json"))

    def test_the_cache_block_states_that_no_cache_lane_exists(self, tmp_path, monkeypatch):
        written = _publish_refusal(tmp_path, monkeypatch, refusal.EXIT_UNPROVEN, "the gate was blind")
        assert written["cache"]["not_fingerprinted"]


def _publish_refusal(tmp_path, monkeypatch, code, reason) -> dict:
    """Run the refusal path against a redirected artifact directory."""
    from aipass.seedgo.apps.handlers.audit_tests import artifact

    monkeypatch.setattr(artifact, "ARTIFACT_DIR", tmp_path / "artifacts")
    result = runner.refuse(_target(tmp_path), refusal.Refusal(code=code, reason=reason))
    return result.document


class TestFleetForm:
    """The worst code wins, and a per-target line prints regardless."""

    def test_the_worst_code_is_returned_across_targets(self):
        assert refusal.worst_code([refusal.EXIT_PASSED, refusal.EXIT_UNPROVEN, refusal.EXIT_SCORED_FAILED]) == 2

    def test_a_refused_result_prints_its_law_and_reason(self, tmp_path):
        result = runner.RunResult(
            _target(tmp_path),
            {"status": "refused", "refusal": {"law": "T10", "reason": "the gate was blind"}},
            None,
            refusal.EXIT_UNPROVEN,
        )
        assert "REFUSED" in result.summary_line()
        assert "the gate was blind" in result.summary_line()

    def test_a_published_result_prints_its_score_and_violation_count(self, tmp_path):
        result = runner.RunResult(
            _target(tmp_path),
            {"status": "published", "groups": {"hygiene": {"score": 0, "violation_count": 31}}},
            Path("/tmp/a.json"),
            refusal.EXIT_SCORED_FAILED,
        )
        assert "hygiene 0" in result.summary_line()
        assert "31 violation(s)" in result.summary_line()


# =============================================================================
# TARGET RESOLUTION
# =============================================================================


class TestBranchNameResolution:
    """The registry spells some branches uppercase and everyone types lowercase."""

    def test_an_exact_name_resolves(self):
        resolved = target_module.resolve("@CANARY", {"CANARY": Path("/x/canary")})
        assert resolved.name == "CANARY"

    def test_a_lowercase_argument_resolves_to_the_canonical_spelling(self):
        # The CANONICAL name, not the typed one: two spellings of one branch
        # must never produce two artifacts.
        resolved = target_module.resolve("@canary", {"CANARY": Path("/x/canary")})
        assert resolved.name == "CANARY"
        assert resolved.artifact_name() == "audit_tests_CANARY"

    def test_an_exact_match_wins_over_a_case_insensitive_one(self):
        resolved = target_module.resolve("@canary", {"CANARY": Path("/a"), "canary": Path("/b")})
        assert resolved.path == Path("/b")

    def test_an_ambiguous_case_insensitive_match_raises_rather_than_guessing(self):
        with pytest.raises(ValueError) as caught:
            target_module.resolve("@Canary", {"CANARY": Path("/a"), "canary": Path("/b")})
        assert "more than one" in str(caught.value)

    def test_an_unknown_branch_still_refuses_loudly(self):
        with pytest.raises(ValueError) as caught:
            target_module.resolve("@nosuchbranch", {"CANARY": Path("/x")})
        assert "not a registered branch" in str(caught.value)


# =============================================================================
# THE VERB
# =============================================================================


class TestVerbIsDiscoverable:
    """The router hides a broken module, so loading it is its own pin.

    `discover_modules()` wraps each module's import in try/except and logs the
    failure to a line nobody reads, and `route_command()` then reports the verb
    as UNKNOWN. This is not hypothetical: an import of a `cli` helper that does
    not exist shipped during this build and the lane reported itself as an
    unknown command — the exact indistinguishability the verb's own docstring
    warns about, caught by nothing until a live run.
    """

    def test_the_verb_module_imports_cleanly(self):
        importlib.import_module("aipass.seedgo.apps.modules.audit_tests")

    def test_seedgos_own_discovery_finds_the_verb(self):
        from aipass.seedgo.apps import seedgo as entry

        names = {getattr(module, "__name__", "") for module in entry.discover_modules()}
        assert "audit_tests" in names

    def test_the_discovered_module_actually_claims_the_verb(self, monkeypatch):
        from aipass.seedgo.apps import seedgo as entry

        claimed = [module for module in entry.discover_modules() if getattr(module, "__name__", "") == "audit_tests"]
        assert claimed, "audit_tests did not survive discovery"
        monkeypatch.setattr(claimed[0], "print_introspection", lambda: None)
        assert claimed[0].handle_command("audit-tests", []) is True

    def test_no_arguments_shows_introspection_rather_than_running(self, monkeypatch):
        from aipass.seedgo.apps.modules import audit_tests as verb

        seen = []
        monkeypatch.setattr(verb, "print_introspection", lambda: seen.append(True))
        monkeypatch.setattr(verb, "_run", lambda args: seen.append("ran"))
        verb.handle_command("audit-tests", [])
        assert seen == [True]

    def test_help_is_intercepted_before_any_target_is_resolved(self, monkeypatch):
        from aipass.seedgo.apps.modules import audit_tests as verb

        # Written first as "raise inside _run", which could NEVER fail:
        # handle_command catches every exception by design, so the assertion
        # was swallowed and the mutant that deleted this whole gate survived.
        # A vacuous pin, inside the suite that enforces the rule against them.
        seen = []
        monkeypatch.setattr(verb, "_print_help", lambda: seen.append("help"))
        monkeypatch.setattr(verb, "_run", lambda args: seen.append("ran"))
        verb.handle_command("audit-tests", ["--help"])
        assert seen == ["help"]


class TestVerbClaiming:
    """Claim exactly, claim before working, and never claim a prefix."""

    def test_the_hyphenated_verb_is_claimed(self, monkeypatch):
        from aipass.seedgo.apps.modules import audit_tests as verb

        monkeypatch.setattr(verb, "_run", lambda args: None)
        assert verb.handle_command("audit-tests", []) is True

    def test_the_underscore_alias_is_claimed(self, monkeypatch):
        from aipass.seedgo.apps.modules import audit_tests as verb

        monkeypatch.setattr(verb, "_run", lambda args: None)
        assert verb.handle_command("audit_tests", []) is True

    def test_the_audit_verb_is_never_swallowed(self):
        from aipass.seedgo.apps.modules import audit_tests as verb

        # audit_tests.py sorts BEFORE standards_audit.py, so a prefix claim
        # here would silently take the audit verb away from its owner.
        assert verb.handle_command("audit", []) is False

    def test_a_crash_after_claiming_still_returns_true(self, monkeypatch):
        from aipass.seedgo.apps.modules import audit_tests as verb

        def explode(args):
            raise RuntimeError("the lane broke")

        monkeypatch.setattr(verb, "_run", explode)
        # route_command() swallows exceptions and moves on, so a lane that
        # raised would be reported to the user as an unknown command.
        assert verb.handle_command("audit-tests", []) is True


class TestVerbParsing:
    """Options are read positionally-safe; the target is the first bare token."""

    def test_a_bare_token_is_the_target(self):
        from aipass.seedgo.apps.modules import audit_tests as verb

        assert verb._parse(["@backup"])[0] == "@backup"

    def test_the_budget_is_read_as_an_integer(self):
        from aipass.seedgo.apps.modules import audit_tests as verb

        assert verb._parse(["@backup", "--budget", "300"])[1]["budget_seconds"] == 300

    def test_a_non_numeric_budget_falls_back_to_the_default(self):
        from aipass.seedgo.apps.modules import audit_tests as verb

        assert verb._parse(["--budget", "soon"])[1]["budget_seconds"] == runner.DEFAULT_BUDGET_SECONDS

    def test_prove_refusal_is_recognised(self):
        from aipass.seedgo.apps.modules import audit_tests as verb

        assert verb._parse(["@backup", "--prove-refusal"])[1]["prove_refusal"] is True

    def test_a_flag_is_never_mistaken_for_the_target(self):
        from aipass.seedgo.apps.modules import audit_tests as verb

        assert verb._parse(["--prove-refusal", "@backup"])[0] == "@backup"

    def test_symlink_siblings_is_off_unless_asked_for(self):
        from aipass.seedgo.apps.modules import audit_tests as verb

        # Copy-always is the default deliberately: a symlinked sibling is
        # writable and a write through one lands in the real tree.
        assert "symlink_siblings" not in verb._parse(["@backup"])[1]


# =============================================================================
# LAW ARGV - the CLI seam refuses what it cannot read
# =============================================================================


def _audit_vocabulary():
    """The `audit` verb's own flag list and sibling verbs, never a copy.

    Read off the module under test rather than restated here: a suggestion
    built from a private duplicate would keep offering flags the verb had
    stopped accepting, which is the same silent drift Law ARGV exists to end.
    """
    from aipass.seedgo.apps.modules import standards_audit

    return standards_audit.AUDIT_FLAGS, standards_audit.SIBLING_VERBS


def _lane_vocabulary():
    """The `audit-tests` verb's own flag list and sibling verbs."""
    from aipass.seedgo.apps.modules import audit_tests as verb

    return verb.LANE_FLAGS, verb.SIBLING_VERBS


def _built_refusal():
    """The ARGV refusal for the typo that started this, built as the verb builds it."""
    flags, siblings = _audit_vocabulary()
    argv = ["-tests", "@backup"]
    return refusal.refusal_for_unknown_argument(
        "-tests", refusal.suggested_command("-tests", "audit", argv, flags, siblings), "audit"
    )


def _capture_output(monkeypatch, module):
    """Collect everything a verb prints, in order, without a real console."""
    printed: list = []
    monkeypatch.setattr(module, "error", lambda message, **kwargs: printed.append(str(message)))
    monkeypatch.setattr(module, "console", _Recorder(printed))
    return printed


class _Recorder:
    """A console stand-in that keeps the text instead of wrapping it."""

    def __init__(self, printed: list) -> None:
        self.printed = printed

    def print(self, text: str = "", **kwargs) -> None:
        """Record one printed line."""
        self.printed.append(str(text))


class TestUnknownArgumentSuggestion:
    """The did-you-mean is a real command, rebuilt from what the caller typed."""

    def test_the_space_typo_is_glued_back_into_the_verb_it_was_reaching_for(self):
        # THE DEFECT, as typed: `drone @seedgo audit -tests @backup`. A hyphen
        # where nothing belonged, and the audit ran anyway. The suggestion is
        # the CANONICAL surface: `audit tests <target>`, two words, no hyphen.
        flags, siblings = _audit_vocabulary()

        assert (
            refusal.suggested_command("-tests", "audit", ["-tests", "@backup"], flags, siblings)
            == "drone @seedgo audit tests @backup"
        )

    def test_the_hyphenated_alias_is_still_a_suggestible_spelling(self):
        # `audit-tests` did not stop existing when `audit tests` became
        # canonical. A verb list that no longer carried it would be telling the
        # caller a working command does not work - so the list is read off the
        # module, and the glue is checked against a list holding only that form.
        _, siblings = _audit_vocabulary()

        assert "audit-tests" in siblings
        assert refusal.sibling_verb("-tests", "audit", ("audit-tests",)) == "audit-tests"

    def test_the_rest_of_the_line_is_carried_into_the_suggestion(self):
        flags, siblings = _audit_vocabulary()

        assert (
            refusal.suggested_command("-tests", "audit", ["-tests", "@flow", "--full"], flags, siblings)
            == "drone @seedgo audit tests @flow --full"
        )

    def test_a_near_miss_flag_is_offered_spelled_correctly(self):
        flags, siblings = _audit_vocabulary()

        assert (
            refusal.suggested_command("--nobypass", "audit", ["aipass", "--nobypass"], flags, siblings)
            == "drone @seedgo audit aipass --no-bypass"
        )

    def test_a_shared_verb_prefix_never_inflates_the_sibling_match(self):
        # Measured against the whole glued spelling, `audit-zzz` scored 0.6
        # against `audit-tests` on the shared `audit-` alone and offered the
        # execution lane for a token that was only ever a bad flag. Only the
        # DISTINGUISHING part is compared.
        flags, siblings = _audit_vocabulary()

        assert (
            refusal.suggested_command("--zzz", "audit", ["aipass", "--zzz"], flags, siblings)
            == "drone @seedgo audit --help"
        )

    def test_an_extra_bare_word_is_suggested_away(self):
        flags, siblings = _audit_vocabulary()

        assert (
            refusal.suggested_command("@prax", "audit", ["aipass", "@flow", "@prax"], flags, siblings)
            == "drone @seedgo audit aipass @flow"
        )

    def test_the_lane_offers_its_own_flag_back(self):
        flags, siblings = _lane_vocabulary()

        assert (
            refusal.suggested_command("-budget", "audit-tests", ["@backup", "-budget", "300"], flags, siblings)
            == "drone @seedgo audit-tests @backup --budget 300"
        )

    def test_the_verb_already_typed_is_never_suggested_back(self):
        # A suggestion identical to the command that just failed is not a
        # suggestion; it is the same twenty minutes again. Both guards are
        # pinned: the exact spelling, and the fuzzy near-miss behind it.
        assert refusal.sibling_verb("-audit", "audit", ("audit", "audit-tests")) == ""
        assert refusal.sibling_verb("-tests", "audit-tests", ("audit-tests",)) == ""


class TestUnknownArgumentRefusal:
    """A refused token names itself, cites ARGV, and carries the fix."""

    def test_the_refusal_names_the_offending_token(self):
        built = _built_refusal()

        assert "'-tests'" in built.reason

    def test_the_refusal_carries_the_command_that_would_have_worked(self):
        built = _built_refusal()

        assert "did you mean: drone @seedgo audit tests @backup" in built.reason

    def test_the_refusal_exits_non_zero(self):
        built = _built_refusal()

        assert built.code == refusal.EXIT_UNKNOWN_ARGUMENT
        assert built.code != refusal.EXIT_PASSED
        assert refusal.is_refusal(built.code), "a command nobody understood is a refusal, never a publication"

    def test_the_stdout_line_cites_the_law_it_refuses_under(self):
        line = _built_refusal().stdout_line()

        assert line.startswith("REFUSED:")
        assert "[ARGV]" in line

    def test_the_detail_carries_a_pasteable_command(self):
        assert "try: drone @seedgo audit tests @backup" in _built_refusal().detail

    def test_argv_outranks_every_measurement_outcome_except_unproven(self):
        """Nothing ran at all, so it must never rank quieter than a run that did."""
        assert (
            refusal.worst_code([refusal.EXIT_UNKNOWN_ARGUMENT, refusal.EXIT_BUDGET_EXHAUSTED])
            == refusal.EXIT_UNKNOWN_ARGUMENT
        )
        assert refusal.worst_code([refusal.EXIT_UNKNOWN_ARGUMENT, refusal.EXIT_UNPROVEN]) == refusal.EXIT_UNPROVEN

    def test_the_verb_prints_the_refused_line_the_code_and_the_detail(self, monkeypatch):
        """The refusal is only real once a reader sees it."""
        from aipass.seedgo.apps.modules import audit_tests as verb

        printed = _capture_output(monkeypatch, verb)

        verb._refuse_unknown_argument("--nonsense", ["@backup", "--nonsense"])

        assert any(line.startswith("REFUSED: [ARGV]") and "'--nonsense'" in line for line in printed)
        assert any("exit code: 7" in line for line in printed)
        assert any("try: drone @seedgo audit-tests" in line for line in printed)


class TestLaneParsingRefusesTheUnrecognized:
    """`audit-tests` collects what it could not read, and never drops it."""

    def test_an_unknown_flag_is_collected(self):
        from aipass.seedgo.apps.modules import audit_tests as verb

        assert verb._parse(["@backup", "--nonsense"])[2] == ["--nonsense"]

    def test_a_second_target_is_collected_because_a_run_measures_one(self):
        from aipass.seedgo.apps.modules import audit_tests as verb

        # `runner.run()` takes ONE argument, so a second bare word named
        # nothing and used to vanish. `aipass` is the fleet form.
        assert verb._parse(["@backup", "@flow"])[2] == ["@flow"]

    def test_argv_order_is_kept_so_the_first_mistake_is_the_one_reported(self):
        from aipass.seedgo.apps.modules import audit_tests as verb

        assert verb._parse(["--first", "@backup", "--second"])[2] == ["--first", "--second"]

    @pytest.mark.parametrize(
        "argv",
        [
            ["@backup"],
            ["."],
            ["/tmp/some_project"],
            ["aipass"],
            ["@backup", "--budget", "300"],
            ["@backup", "--prove-refusal"],
            ["@backup", "--symlink-siblings"],
            ["@backup", "--no-tmpdir-allowance"],
            ["--prove-refusal", "@backup"],
            ["@backup", "--budget", "300", "--prove-refusal", "--symlink-siblings", "--no-tmpdir-allowance"],
        ],
    )
    def test_every_documented_invocation_still_parses_clean(self, argv):
        """A refusal that rejects a valid command is worse than the bug it fixes."""
        from aipass.seedgo.apps.modules import audit_tests as verb

        target, options, unrecognized = verb._parse(argv)

        assert unrecognized == [], f"{argv} is documented usage and must not be refused"
        assert target, f"{argv} names a target"

    def test_a_budget_with_no_value_keeps_the_default_rather_than_being_refused(self):
        """The flag IS known; only its value is missing. Refusing it would lie."""
        from aipass.seedgo.apps.modules import audit_tests as verb

        target, options, unrecognized = verb._parse(["@backup", "--budget"])

        assert unrecognized == []
        assert options["budget_seconds"] == runner.DEFAULT_BUDGET_SECONDS


class TestLaneVerbRefusesTheUnrecognized:
    """The refusal happens before anything is measured."""

    def test_nothing_is_measured_once_a_token_is_unrecognized(self, monkeypatch):
        from aipass.seedgo.apps.modules import audit_tests as verb

        printed = _capture_output(monkeypatch, verb)
        monkeypatch.setattr(verb.runner, "run", lambda *a, **k: printed.append("MEASURED"))

        verb._run(["@backup", "--nonsense"])

        assert "MEASURED" not in printed, "the lane measured a target it had already failed to understand"
        assert any(line.startswith("REFUSED: [ARGV]") and "'--nonsense'" in line for line in printed)

    def test_a_help_flag_beside_an_unknown_token_still_explains(self, monkeypatch):
        from aipass.seedgo.apps.modules import audit_tests as verb

        # help_flag_safety: a help flag ANYWHERE means explain, never execute -
        # and never refuse either. The unknown token is collected during the
        # scan and acted on only after help has had its say.
        seen: list = []
        monkeypatch.setattr(verb, "_print_help", lambda: seen.append("help"))
        monkeypatch.setattr(verb, "_run", lambda args: seen.append("ran"))

        verb.handle_command("audit-tests", ["-tests", "--help"])

        assert seen == ["help"]
