# =================== AIPass ====================
# Name: test_rollover_pipeline.py
# Description: Rollover pipeline — the rollover module's run, status and triggers, normalize
# Version: 1.5.0
# Created: 2026-04-25
# Modified: 2026-10-23
# Category: memory/tests
# =============================================

"""Tests for apps/modules/rollover.py and the rollover pipeline handlers it drives."""

# The run lane: run_rollover, show_status, check_triggers, normalize, the valve's logging and the
# carried-debt lane. Siblings: test_rollover_pipeline_{extraction,valve,todo}.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — orchestrator.execute_rollover(); tests/test_orchestrator_exec.py

import json
import tempfile
import types
import sys
from datetime import datetime
from pathlib import Path
import pytest
from types import ModuleType
from unittest.mock import MagicMock, patch

from aipass.memory.tests.support_rollover_pipeline import _import_extractor


def _import_rollover_module(monkeypatch):
    """Import the rollover module with mocked infrastructure dependencies."""
    # FIRST, before any mock reaches sys.modules: rollover_config and rollover_json keep the
    # `console`/`error` they bind at first import forever, so they must bind the REAL aipass.cli.
    import importlib

    real_rollover_config = importlib.import_module("aipass.memory.apps.modules.rollover_config")
    real_rollover_json = importlib.import_module("aipass.memory.apps.modules.rollover_json")

    # error() is replaced at each use site because it marks the process's command as failed.
    mock_error = MagicMock()
    mock_warning = MagicMock()

    mock_detector = MagicMock()
    mock_detector.check_all_branches = MagicMock(return_value={"success": True, "triggers": []})
    mock_detector.get_rollover_stats = MagicMock(
        return_value={
            "success": True,
            "total_branches": 0,
            "files_checked": 0,
            "files_ready": 0,
            "branches": {},
        }
    )

    mock_orchestrator = MagicMock()
    mock_orchestrator.execute_rollover = MagicMock(return_value={"success": True, "triggers_count": 0})

    monitor_pkg = MagicMock()
    monitor_pkg.detector = mock_detector

    rollover_pkg = MagicMock()
    rollover_pkg.orchestrator = mock_orchestrator

    # Stubbed to "nothing resolved" so these tests never touch a real pad.
    mock_todo_report = MagicMock()
    no_branch = {"level": "line", "text": "Todos: no branch resolved (harness) - no todo pad checked"}
    mock_todo_report.check_pad = MagicMock(return_value=no_branch)
    mock_todo_report.roll_pad = MagicMock(return_value=no_branch)
    rollover_pkg.todo_report = mock_todo_report

    # A real ModuleType with the REAL __path__: importlib asks a stand-in package for __spec__, and
    # rollover's lazy handlers.cli.help_flags import must resolve (test_import_isolation.py).
    handlers_pkg = ModuleType("aipass.memory.apps.handlers")
    handlers_pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "apps" / "handlers")]
    setattr(handlers_pkg, "monitor", monitor_pkg)
    setattr(handlers_pkg, "rollover", rollover_pkg)

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers", handlers_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor", monitor_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor.detector", mock_detector)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover", rollover_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover.orchestrator", mock_orchestrator)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover.todo_report", mock_todo_report)
    # Patched per module: `_refuse` (rollover_json) reads `error` from its own globals.
    monkeypatch.setattr(real_rollover_config, "error", mock_error)
    monkeypatch.setattr(real_rollover_config, "detector", mock_detector)
    monkeypatch.setattr(real_rollover_json, "error", mock_error)

    # Recorded before eviction so teardown restores it: a bare pop left the mock-bound rollover
    # cached after the test, and a later in-process `rollover <bogus>` exited 0 instead of 2.
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.modules.rollover", None)
    del sys.modules["aipass.memory.apps.modules.rollover"]
    parent = sys.modules.get("aipass.memory.apps.modules")
    if parent is not None:
        monkeypatch.setattr(parent, "rollover", None, raising=False)
        delattr(parent, "rollover")

    from aipass.memory.apps.modules import rollover

    monkeypatch.setattr(rollover, "error", mock_error)
    monkeypatch.setattr(rollover, "warning", mock_warning)

    return rollover, {
        "error": mock_error,
        "warning": mock_warning,
        "detector": mock_detector,
        "orchestrator": mock_orchestrator,
        "todo_report": mock_todo_report,
    }


class TestPipelineRolloverImportIsUndoneAtTeardown:
    """The rollover module _import_rollover_module binds to stand-ins and a mock error() must not outlive its test."""

    def test_sys_modules_and_the_parent_attribute_are_restored(self) -> None:
        import importlib

        name = "aipass.memory.apps.modules.rollover"
        parent = importlib.import_module("aipass.memory.apps.modules")
        module_before = sys.modules.get(name)
        attr_before = getattr(parent, "rollover", None)

        with pytest.MonkeyPatch.context() as mp:
            rollover, mocks = _import_rollover_module(mp)
            assert rollover.error is mocks["error"]
            assert rollover is not module_before

        assert sys.modules.get(name) is module_before, "the mock-bound rollover outlived its test"
        assert getattr(parent, "rollover", None) is attr_before, (
            "the modules package still names the mock-bound rollover"
        )


def _import_normalize(monkeypatch):
    """Import normalize with mocked infrastructure dependencies."""
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    json_pkg = MagicMock()
    # A package stand-in must answer __path__ (test_import_isolation.py).
    json_pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "apps" / "handlers" / "json")]
    json_pkg.json_handler = mock_json_handler

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.json_handler", mock_json_handler)

    monkeypatch.delitem(sys.modules, "aipass.memory.apps.handlers.schema.normalize", raising=False)
    parent = sys.modules.get("aipass.memory.apps.handlers.schema")
    if parent is not None:
        monkeypatch.delattr(parent, "normalize", raising=False)

    from aipass.memory.apps.handlers.schema import normalize

    return normalize, {
        "json_handler": mock_json_handler,
    }


class TestRunRollover:
    """Test run_rollover delegates to handler and renders Rich output."""

    def test_returns_true_when_no_triggers(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["orchestrator"].execute_rollover.return_value = {
            "success": True,
            "triggers_count": 0,
            "success_count": 0,
            "failed": [],
            "results": [],
        }
        result = rollover.run_rollover()
        assert result is True

    def test_the_run_says_its_file_list_is_fleet_wide(self, monkeypatch, capsys):
        """`run --branch @x` reads as scoped; only the pad follows it, and the run says so where it happens."""
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["orchestrator"].execute_rollover.return_value = {
            "success": True,
            "triggers_count": 1,
            "success_count": 1,
            "failed": [],
            "skipped": [],
            "results": [],
        }

        rollover.run_rollover("@memory")

        printed = capsys.readouterr().out
        assert "files ready for rollover (fleet-wide)" in printed, printed
        assert rollover.FLEET_WIDE_RUN_NOTE in printed, printed

    def test_returns_false_on_handler_exception(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["orchestrator"].execute_rollover.side_effect = RuntimeError("boom")
        result = rollover.run_rollover()
        assert result is False
        mocks["error"].assert_called()

    def test_returns_false_on_error_result(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["orchestrator"].execute_rollover.return_value = {
            "success": False,
            "error": "Registry missing",
            "triggers_count": 0,
        }
        result = rollover.run_rollover()
        assert result is False

    def test_returns_true_with_successful_rollover(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["orchestrator"].execute_rollover.return_value = {
            "success": True,
            "triggers_count": 1,
            "success_count": 1,
            "failed": [],
            "results": [
                {
                    "trigger": "TEST.local.json",
                    "memories_count": 5,
                    "old_lines": 600,
                    "new_lines": 400,
                    "global_collection": "test_col",
                    "global_total": 50,
                    "local_stored": True,
                }
            ],
        }
        result = rollover.run_rollover()
        assert result is True

    def test_displays_failure_details(self, monkeypatch):
        """Mutant killed: the failure line printing the trigger alone, no stage or error."""
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["orchestrator"].execute_rollover.return_value = {
            "success": False,
            "triggers_count": 1,
            "success_count": 0,
            "failed": [{"trigger": "BAD.local.json", "stage": "embedding", "error": "model not found"}],
            "results": [],
        }
        rollover.run_rollover()
        mocks["error"].assert_called_once_with("BAD.local.json - embedding: model not found")

    def test_a_run_where_everything_failed_still_states_its_score(self, monkeypatch, capsys):
        """0/N is a result: a run where every trigger failed still prints its score."""
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["orchestrator"].execute_rollover.return_value = {
            "success": False,
            "triggers_count": 3,
            "success_count": 0,
            "failed": [{"trigger": "BAD.local.json", "stage": "extraction", "error": "write refused"}],
            "results": [],
        }

        rollover.run_rollover()

        printed = capsys.readouterr().out
        assert "0/3" in printed, printed


class TestShowStatus:
    """Test show_status calls detector.get_rollover_stats and prints output."""

    def test_displays_error_on_failure(self, monkeypatch):
        """Mutant killed: the status error printed without the detector's reason."""
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["detector"].get_rollover_stats.return_value = {
            "success": False,
            "error": "Registry not found",
        }
        rollover.show_status()
        mocks["error"].assert_called_once_with("Failed to get status: Registry not found")

    def test_displays_v2_branch_details(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["detector"].get_rollover_stats.return_value = {
            "success": True,
            "total_branches": 1,
            "files_checked": 1,
            "files_ready": 1,
            "branches": {
                "V2BRANCH": {
                    "local": {
                        "current": 25,
                        "ready": True,
                        "schema_version": "3.0.0",
                        "v2_reason": "sessions: 25/20",
                    }
                }
            },
        }
        rollover.show_status()
        mocks["error"].assert_not_called()


class TestCheckTriggers:
    """Test check_triggers calls detector.check_all_branches and prints output."""

    def test_no_triggers_prints_clean(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["detector"].check_all_branches.return_value = {"success": True, "triggers": []}
        rollover.check_triggers()
        mocks["error"].assert_not_called()

    def test_displays_triggers_when_found(self, monkeypatch):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mock_trigger = MagicMock()
        mock_trigger.__str__ = MagicMock(return_value="TEST.local.json (650/600 lines)")
        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [mock_trigger],
        }
        rollover.check_triggers()
        mocks["error"].assert_not_called()

    def test_displays_error_on_failure(self, monkeypatch):
        """Mutant killed: the trigger-check error printed without the detector's reason."""
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["detector"].check_all_branches.return_value = {
            "success": False,
            "error": "Cannot read registry",
        }
        rollover.check_triggers()
        mocks["error"].assert_called_once_with("Failed to check triggers: Cannot read registry")

    def test_undrainable_files_are_listed_without_the_ready_phrase(self, monkeypatch, capsys):
        """@hooks' PreCompact fires a fleet run on 'ready for rollover', and no run can move these files."""
        rollover, mocks = _import_rollover_module(monkeypatch)
        stuck = "VERA.local (250/15 key_learnings held as a dict, not a list (schema 2.0.0))"
        mocks["detector"].check_all_branches.return_value = {"success": True, "triggers": [], "undrainable": [stuck]}

        rollover.check_triggers()

        printed = capsys.readouterr().out
        warned = " ".join(str(c) for c in mocks["warning"].call_args_list)
        assert stuck in warned and "cannot drain" in warned, warned
        assert "ready for rollover" not in (printed + warned).lower()


class TestValveLoggingIsBounded:
    """The safety valve logs ONE summary warning per array per run; per-entry detail goes to DEBUG."""

    @staticmethod
    def _run(monkeypatch, tmp_path, entries, limit):
        """Drive the valve through public extract_items on a tmp key_learnings file.

        The logger is replaced, not captured: prax is mocked, so caplog would read zero lines vacuously.
        `entries` must be newest-first, or the re-sort adds a warning that is not the valve's.
        """
        ext, mocks = _import_extractor(monkeypatch)
        data = {"document_metadata": {"schema_version": "3.0.0", "status": {}}, "key_learnings": entries}
        file_path = tmp_path / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(data), encoding="utf-8")
        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {tmp_path.name.lower(): {"local": {"key_learnings": {"count": limit}}}},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data
        fake = MagicMock()
        monkeypatch.setattr(ext, "logger", fake)

        result = ext.extract_items(file_path)

        assert result["success"] is True, result
        warnings = [c.args[0] for c in fake.warning.call_args_list]
        debugs = [c.args[0] for c in fake.debug.call_args_list]
        return result.get("extracted", []), warnings, debugs

    @staticmethod
    def _misplaced(n, below):
        """n entries that all trip the valve by date; numbered below `below` so the re-sort keeps them."""
        today = datetime.now().strftime("%Y-%m-%d")
        return [{"number": below - 1 - i, "date": today, "value": "x" * 800} for i in range(n)]

    _HEAD = {"number": 1000, "date": "2026-01-01", "value": "head"}

    def test_one_warning_per_array_not_one_per_entry(self, monkeypatch, tmp_path):
        entries = [self._HEAD] + self._misplaced(96, 1000)
        _kept, warnings, _debugs = self._run(monkeypatch, tmp_path, entries, 15)
        assert len(warnings) == 1

    def test_the_refused_count_is_in_the_summary(self, monkeypatch, tmp_path):
        entries = [self._HEAD] + self._misplaced(96, 1000)
        _kept, warnings, _debugs = self._run(monkeypatch, tmp_path, entries, 15)
        assert "82 of 82" in warnings[0]

    def test_per_entry_detail_survives_at_debug(self, monkeypatch, tmp_path):
        entries = [self._HEAD] + self._misplaced(96, 1000)
        _kept, _warnings, debugs = self._run(monkeypatch, tmp_path, entries, 15)
        assert len(debugs) == 82

    def test_nothing_drained_names_the_skip_loop(self, monkeypatch, tmp_path):
        """Over limit with nothing archivable says NOTHING DRAINED: the detector would re-fire forever."""
        entries = [self._HEAD] + self._misplaced(96, 1000)
        _kept, warnings, _debugs = self._run(monkeypatch, tmp_path, entries, 15)
        assert "NOTHING DRAINED" in warnings[0]

    def test_a_partial_refusal_is_not_called_a_skip_loop(self, monkeypatch, tmp_path):
        """Some drained means the lane still moves — warn, but do not alarm."""
        old = [{"number": 999 - i, "date": "2026-01-01", "value": "old"} for i in range(40)]
        # Misplaced at the END so they share the candidate tail with genuinely-old ones.
        entries = [self._HEAD] + old + self._misplaced(5, 960)
        kept, warnings, _debugs = self._run(monkeypatch, tmp_path, entries, 15)
        assert len(kept) == 26
        assert len(warnings) == 1
        assert "NOTHING DRAINED" not in warnings[0]

    def test_no_refusals_logs_nothing(self, monkeypatch, tmp_path):
        """Mutant killed: `excess` computed one short of `len(entries) - limit`."""
        entries = [{"number": 100 - i, "date": "2026-01-01", "value": "v"} for i in range(40)]
        kept, warnings, debugs = self._run(monkeypatch, tmp_path, entries, 15)
        assert len(kept) == 25
        assert warnings == []
        assert debugs == []

    def test_the_valve_still_holds_every_misplaced_entry_back(self, monkeypatch, tmp_path):
        """Log volume changed; the protection must not have."""
        entries = [self._HEAD] + self._misplaced(96, 1000)
        kept, _warnings, _debugs = self._run(monkeypatch, tmp_path, entries, 15)
        assert kept == []


class TestASkippedTriggerIsNotSilentlyDropped:
    """A trigger counted as neither success nor failure is a hole in the tally."""

    @staticmethod
    def _trigger(name="guinea.local"):
        trigger = MagicMock()
        setattr(trigger, "__str__", lambda self: name)
        trigger.file_path = Path(tempfile.gettempdir()) / "does-not-matter" / "local.json"
        trigger.branch = "guinea"
        trigger.memory_type = "local"
        return trigger

    def _run_with_skip(self):
        from aipass.memory.apps.handlers.rollover import orchestrator

        with (
            patch.object(
                orchestrator.detector,
                "check_all_branches",
                return_value={"success": True, "triggers": [self._trigger()]},
            ),
            patch.object(
                orchestrator.extractor,
                "extract_with_metadata",
                return_value={"success": True, "skipped": True, "message": "No entries exceed v2 limits"},
            ),
        ):
            return orchestrator.execute_rollover()

    def test_a_skipped_trigger_is_reported_somewhere(self):
        result = self._run_with_skip()
        accounted = result["success_count"] + len(result["failed"]) + len(result.get("skipped", []))
        assert accounted == result["triggers_count"], (
            f"1 trigger in, {accounted} accounted for: {result['success_count']} succeeded, "
            f"{len(result['failed'])} failed, {len(result.get('skipped', []))} skipped"
        )

    def test_the_skip_carries_the_reason_the_extractor_gave(self):
        """Mutant killed: the reason fixed to "no excess" instead of the extractor's message."""
        skipped = self._run_with_skip().get("skipped", [])
        assert len(skipped) == 1, "the skip must be reported, not dropped"
        assert skipped[0]["reason"] == "No entries exceed v2 limits", skipped[0]

    def test_a_skipped_trigger_is_not_counted_as_a_success(self):
        """The file was not archived. Calling it a success would be the lie."""
        assert self._run_with_skip()["success_count"] == 0

    def test_a_run_that_only_skipped_did_not_fail(self):
        """Nothing broke — 'nothing to do' is a legitimate outcome, just a named one."""
        assert self._run_with_skip()["success"] is True

    def test_an_empty_run_still_carries_the_undrainable_files(self):
        """A dict-only file is never a trigger, so the no-trigger return is where it must survive."""
        from aipass.memory.apps.handlers.rollover import orchestrator

        stuck = "VERA.local (250/15 key_learnings held as a dict, not a list (schema 2.0.0))"
        walk = {"success": True, "triggers": [], "undrainable": [stuck]}
        with patch.object(orchestrator.detector, "check_all_branches", return_value=walk):
            result = orchestrator.execute_rollover()

        assert (result["triggers_count"], result["undrainable"]) == (0, [stuck])

    def test_the_extractor_names_a_dict_instead_of_claiming_no_excess(self, tmp_path, monkeypatch):
        """'No entries exceed v2 limits' is what VERA's 250/15 printed on every run."""
        ext, mocks = _import_extractor(monkeypatch)
        data = {
            "document_metadata": {"schema_version": "2.0.0"},
            "key_learnings": {f"KL-{n:03d}": "x" for n in range(1, 5)},
        }
        file_path = tmp_path / "writer" / ".trinity" / "local.json"
        file_path.parent.mkdir(parents=True)
        file_path.write_text(json.dumps(data), encoding="utf-8")
        mocks["config_loader"].section.return_value = {
            "defaults": {"local": {"key_learnings": {"count": 3}}},
            "per_branch": {},
        }
        mocks["memory_files"].read_memory_file_data.return_value = data

        result = ext.extract_items(file_path)

        assert result["skipped"] is True
        assert "exceed" not in result["message"], result["message"]
        assert "4/3 key_learnings held as a dict" in result["message"], result["message"]
        mocks["memory_files"].write_memory_file_simple.assert_not_called()


class TestASkippedTriggerIsVisibleOnScreen:
    """The handler counting it is only half — the operator has to be able to read it."""

    def test_the_skip_and_its_reason_are_printed(self, monkeypatch, capsys):
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["orchestrator"].execute_rollover.return_value = {
            "success": True,
            "triggers_count": 1,
            "success_count": 0,
            "failed": [],
            "skipped": [{"trigger": "guinea.local (16/15 sessions)", "reason": "No entries exceed v2 limits"}],
            "results": [],
        }

        rollover.run_rollover()

        printed = capsys.readouterr().out
        assert "0/1" in printed, printed
        assert "guinea.local" in printed and "skipped" in printed, printed

    def test_a_run_with_no_skips_prints_no_skip_line(self, monkeypatch, capsys):
        """The absence of a category must not print an empty heading."""
        rollover, mocks = _import_rollover_module(monkeypatch)
        mocks["orchestrator"].execute_rollover.return_value = {
            "success": True,
            "triggers_count": 1,
            "success_count": 1,
            "failed": [],
            "skipped": [],
            "results": [],
        }

        rollover.run_rollover()

        printed = capsys.readouterr().out
        assert "0/1" not in printed and "1/1" in printed, printed
        assert "skipped" not in printed, printed

    def test_an_empty_run_prints_the_undrainable_files(self, monkeypatch):
        """No triggers used to end on 'No files need rollover' with VERA at 250/15 unsaid."""
        rollover, mocks = _import_rollover_module(monkeypatch)
        stuck = "VERA.local (250/15 key_learnings held as a dict, not a list (schema 2.0.0))"
        mocks["orchestrator"].execute_rollover.return_value = {
            "success": True,
            "triggers_count": 0,
            "success_count": 0,
            "failed": [],
            "skipped": [],
            "results": [],
            "undrainable": [stuck],
        }

        rollover.run_rollover()

        warned = " ".join(str(c) for c in mocks["warning"].call_args_list)
        assert stuck in warned and "cannot drain" in warned, warned


# The lane against the REAL write gate: nothing below the extractor is mocked, and every
# assertion reads the file on disk, because "success" was reported while the file never changed.


class TestRolloverSurvivesCarriedDebt:
    """The live deadlock, driven through the extractor against the real writer."""

    @pytest.fixture
    def ext(self, monkeypatch):
        """The extractor with its REAL dependencies — the point of this class.

        Evicted via monkeypatch.delitem: a cached extractor stays bound to an earlier test's mock memory_files.
        """
        for name in (
            "aipass.memory.apps.handlers.json",
            "aipass.memory.apps.handlers.json.json_handler",
            "aipass.memory.apps.handlers.json.config_loader",
            "aipass.memory.apps.handlers.json.entry_limits",
            "aipass.memory.apps.handlers.json.memory_files",
            "aipass.memory.apps.handlers.rollover.extractor",
        ):
            monkeypatch.delitem(sys.modules, name, raising=False)
        parent = sys.modules.get("aipass.memory.apps.handlers.rollover")
        if parent is not None and hasattr(parent, "extractor"):
            monkeypatch.delattr(parent, "extractor", raising=False)

        from aipass.memory.apps.handlers.rollover import extractor

        assert isinstance(extractor.write_memory_file_simple, types.FunctionType), (
            "extractor is bound to a mocked writer — this class would prove nothing"
        )
        return extractor

    @staticmethod
    def _seedgo_shaped_file(tmp_path):
        """A file over its session count with one over-cap summary in the HEAD, where rollover never archives."""
        trinity = tmp_path / "standin" / ".trinity"
        trinity.mkdir(parents=True)
        file_path = trinity / "local.json"
        data = {
            "document_metadata": {
                "document_type": "session_history",
                "document_name": "standin.LOCAL",
                "version": "2.0.0",
                "schema_version": "3.0.0",
            },
            "sessions": [{"number": 20, "date": "2026-08-30", "summary": "X" * 343}]
            + [{"number": n, "date": "2026-08-29", "summary": f"session {n}"} for n in range(19, 0, -1)],
        }
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return file_path

    def test_entries_actually_leave_the_file(self, ext, tmp_path):
        """Not "reported success" — MEASURED on disk, which is where the lie was."""
        file_path = self._seedgo_shaped_file(tmp_path)
        before_count = len(json.loads(file_path.read_text(encoding="utf-8"))["sessions"])

        result = ext.extract_items(file_path)

        assert result["success"] is True, result.get("error")
        assert ext.commit_trimmed(file_path, result["trimmed"])["success"] is True
        after = json.loads(file_path.read_text(encoding="utf-8"))["sessions"]
        assert len(after) < before_count, "the lane reported success and the file never shrank"
        assert result["extracted_count"] == before_count - len(after), (
            "extracted count disagrees with what left the file — the 3-hour lie exactly"
        )

    def test_the_carried_entry_is_still_there_and_still_over_cap(self, ext, tmp_path):
        """Rollover must not 'fix' the fat entry — editing text to satisfy a cap would be authoring memories."""
        file_path = self._seedgo_shaped_file(tmp_path)
        result = ext.extract_items(file_path)

        # The run must have archived something, or "still there" passes on a dead lane.
        assert result["success"] is True, result.get("error")
        assert result["extracted_count"] > 0, "nothing was archived — this pin would pass vacuously"
        ext.commit_trimmed(file_path, result["trimmed"])

        head = json.loads(file_path.read_text(encoding="utf-8"))["sessions"][0]
        assert head["summary"] == "X" * 343, "rollover edited an entry it only moves past"

    def test_a_second_run_is_not_re_archiving_the_same_entries(self, ext, tmp_path):
        """A file that shrank leaves the second run strictly less to do (no duplicate-work loop)."""
        file_path = self._seedgo_shaped_file(tmp_path)
        first = ext.extract_items(file_path)
        ext.commit_trimmed(file_path, first["trimmed"])
        second = ext.extract_items(file_path)

        assert first["extracted_count"] > 0
        assert second.get("extracted_count", 0) < first["extracted_count"], (
            "the second run extracted as much as the first — the file did not shrink"
        )
