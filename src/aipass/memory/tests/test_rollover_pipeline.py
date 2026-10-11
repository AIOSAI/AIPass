# =================== AIPass ====================
# Name: test_rollover_pipeline.py
# Description: Rollover pipeline — the rollover module's run, status and triggers, normalize, line counter
# Version: 1.5.0
# Created: 2026-04-25
# Modified: 2026-10-08
# Category: memory/tests
# =============================================

"""Tests for apps/modules/rollover.py and the rollover pipeline handlers it drives."""

# Tests for untested public functions in the rollover pipeline.
# Split on 2026-10-08 (oversize_test_file), one subject per file. This file
# keeps the run lane: run_rollover, show_status, check_triggers, normalize,
# the line counter, the valve's logging and the carried-debt lane. Siblings:
#   - test_rollover_pipeline_extraction.py -- the orchestrator's subprocess lanes, chroma path, extraction
#   - test_rollover_pipeline_valve.py      -- the safety valve, snapshot budget, newest-first guard
#   - test_rollover_pipeline_todo.py       -- the pad's roll to its backlog, the trim, the restore
# The extractor harness the three extractor files share is in support_rollover_pipeline.py.
#
# Covers:
#   from aipass.memory.apps.modules.rollover import run_rollover
#   from aipass.memory.apps.modules.rollover import show_status
#   from aipass.memory.apps.modules.rollover import check_triggers
#   from aipass.memory.apps.handlers.schema.normalize import normalize_all_memory_files
#   from aipass.memory.apps.handlers.tracking.line_counter import update_all_memory_files
#   from aipass.memory.apps.handlers.learnings.manager import process_all_branches
#
# All tests use mocks or tmp_path -- no live filesystem or infrastructure access.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — rollover.report_line_counts(); tests/test_marker7_memory_lane.py

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


# ---------------------------------------------------------------------------
# Import helpers -- each handler has module-level imports that need mocking
# ---------------------------------------------------------------------------


def _import_rollover_module(monkeypatch):
    """Import the rollover module with mocked infrastructure dependencies."""
    # FIRST LINE OF THE FIXTURE, before a single mock reaches sys.modules.
    # The `config` verbs live in modules/rollover_config.py and `_Json`,
    # `_emit` and `_refuse` in modules/rollover_json.py; rollover.py re-exports
    # both sets. BOTH modules must be first-imported against the REAL
    # aipass.cli, because whatever `console` and `error` each binds at import
    # time it keeps FOREVER — the module stays cached long after teardown
    # restores sys.modules. Standing one line below the cli stand-in was enough
    # to hand 191 of test_config_verbs.py's tests a MagicMock console that
    # printed nothing, in serial order only: --dist loadscope split the two
    # files across workers and no CI run ever saw it (2026-09-16).
    import importlib

    real_rollover_config = importlib.import_module("aipass.memory.apps.modules.rollover_config")
    real_rollover_json = importlib.import_module("aipass.memory.apps.modules.rollover_json")

    # aipass.cli and rich are the REAL packages (leg 12 of DPLAN-0354): the
    # console only prints, and the tests read what it printed with capsys.
    # error() and warning() are replaced at the use site, on each module that
    # bound them, because error() marks the process's command as failed; the
    # re-imported rollover below is patched the same way.
    mock_error = MagicMock()
    mock_warning = MagicMock()

    # aipass.memory handler sub-packages
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
    mock_orchestrator.sync_line_counts = MagicMock(return_value={"success": True, "updated": 0, "failed": 0})

    monitor_pkg = MagicMock()
    monitor_pkg.detector = mock_detector

    rollover_pkg = MagicMock()
    rollover_pkg.orchestrator = mock_orchestrator

    # The todo-pad reports resolve a branch and read a pad: stubbed to the
    # honest "nothing resolved" line so these tests never touch a real pad.
    mock_todo_report = MagicMock()
    no_branch = {"level": "line", "text": "Todos: no branch resolved (harness) - no todo pad checked"}
    mock_todo_report.check_pad = MagicMock(return_value=no_branch)
    mock_todo_report.roll_pad = MagicMock(return_value=no_branch)
    rollover_pkg.todo_report = mock_todo_report

    # A real ModuleType, not a MagicMock: the stand-in has to survive being
    # treated as a package by the import machinery, and a MagicMock raises
    # AttributeError for __spec__ the moment importlib asks.
    handlers_pkg = ModuleType("aipass.memory.apps.handlers")
    # A package stand-in must carry a __path__ that reaches the REAL package
    # (test_import_isolation.py) — a bare MagicMock has none, and any lazy
    # submodule import under it then dies with "is not a package". modules/
    # rollover.py imports handlers.cli.help_flags, which this harness does not
    # stand in for, so without this line the whole file only passes when some
    # earlier test file happens to have imported handlers for real.
    handlers_pkg.__path__ = [str(Path(__file__).resolve().parents[1] / "apps" / "handlers")]
    setattr(handlers_pkg, "monitor", monitor_pkg)
    setattr(handlers_pkg, "rollover", rollover_pkg)

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers", handlers_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor", monitor_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor.detector", mock_detector)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover", rollover_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover.orchestrator", mock_orchestrator)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover.todo_report", mock_todo_report)
    # Patched attribute by attribute rather than through the sys.modules
    # stand-in, because `_refuse` reads `error` from ITS OWN globals - without
    # these the mock error() never hears the refusal. monkeypatch restores each.
    monkeypatch.setattr(real_rollover_config, "error", mock_error)
    monkeypatch.setattr(real_rollover_config, "detector", mock_detector)
    # And error on rollover_json, which is where `_refuse` reads it now — a
    # patch on rollover_config no longer reaches it. No `detector` there: that
    # module never took one. `console` stays the real one on both.
    monkeypatch.setattr(real_rollover_json, "error", mock_error)

    # Recorded first, the way test_rollover.py's _import_rollover evicts. This re-import binds rollover
    # to the stand-in handlers, and its error() is the mock; a bare pop and a bare delattr left that
    # module cached AND named by the modules package after teardown, so test_contracts' in-process
    # `rollover <bogus>` on the same worker exited 0 instead of 2 (-n 3 --dist loadscope, 2026-09-15).
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
    """The rollover module _import_rollover_module binds to stand-ins and a mock error() must not outlive its test.

    It did: under -n 3 --dist loadscope a worker ran TestRunRollover, then test_contracts'
    in-process `rollover <bogus>` routed through the mock error() and exited 0 instead of 2.
    """

    def test_sys_modules_and_the_parent_attribute_are_restored(self) -> None:
        import importlib

        name = "aipass.memory.apps.modules.rollover"
        parent = importlib.import_module("aipass.memory.apps.modules")
        module_before = sys.modules.get(name)
        attr_before = getattr(parent, "rollover", None)

        with pytest.MonkeyPatch.context() as mp:
            rollover, mocks = _import_rollover_module(mp)
            # Guard the guard: the re-import really is bound to the mock.
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
    # Impersonating a package means answering __path__ — a bare MagicMock does not,
    # and every lazy submodule import under it then dies. See test_import_isolation.py.
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


def _import_line_counter(monkeypatch):
    """Import line_counter with mocked infrastructure dependencies."""
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    mock_memory_files = MagicMock()
    mock_memory_files.update_metadata = MagicMock(return_value={"success": True})

    json_pkg = MagicMock()
    # Impersonating a package means answering __path__ — a bare MagicMock does not,
    # and every lazy submodule import under it then dies. See test_import_isolation.py.
    json_pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "apps" / "handlers" / "json")]
    json_pkg.json_handler = mock_json_handler

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.json_handler", mock_json_handler)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.memory_files", mock_memory_files)

    monkeypatch.delitem(sys.modules, "aipass.memory.apps.handlers.tracking.line_counter", raising=False)
    parent = sys.modules.get("aipass.memory.apps.handlers.tracking")
    if parent is not None:
        monkeypatch.delattr(parent, "line_counter", raising=False)

    from aipass.memory.apps.handlers.tracking import line_counter

    return line_counter, {
        "json_handler": mock_json_handler,
        "memory_files": mock_memory_files,
    }


# ===========================================================================
# Tests: modules.rollover.run_rollover
# ===========================================================================


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
        """Mutant (2026-09-27, killed): the failure line printing the trigger alone, no stage or error."""
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
        """0/1 is a result. Printing nothing lets a total failure read as a quiet run.

        The completion line was gated on `success_count > 0`, so a rollover in
        which every trigger failed ended on a blank line under "Found 1 files
        ready for rollover". The per-failure detail was there, but the run never
        said what it had achieved overall — and "no summary" is the same shape
        on screen as "nothing needed doing".
        """
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


# ===========================================================================
# Tests: modules.rollover.show_status
# ===========================================================================


class TestShowStatus:
    """Test show_status calls detector.get_rollover_stats and prints output."""

    def test_displays_error_on_failure(self, monkeypatch):
        """Mutant (2026-09-27, killed): the status error printed without the detector's reason."""
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
        # Should have printed without error
        mocks["error"].assert_not_called()


# ===========================================================================
# Tests: modules.rollover.check_triggers
# ===========================================================================


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
        """Mutant (2026-09-27, killed): the trigger-check error printed without the detector's reason."""
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


# ===========================================================================
# Tests: normalize.normalize_all_memory_files
# ===========================================================================


class TestNormalizeAllMemoryFiles:
    """Test normalize_all_memory_files iterates registry branches."""

    def test_returns_error_when_registry_not_found(self, monkeypatch, tmp_path):
        norm, _ = _import_normalize(monkeypatch)
        with patch.object(norm, "_find_repo_root", return_value=tmp_path / "nonexistent"):
            result = norm.normalize_all_memory_files()
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_normalizes_files_for_existing_branches(self, monkeypatch, tmp_path):
        norm, _ = _import_normalize(monkeypatch)

        # Create registry
        branch_dir = tmp_path / "src" / "aipass" / "test_branch"
        branch_dir.mkdir(parents=True)

        # Create memory file that needs normalization (root-level limits)
        memory_data = {
            "limits": {"max_lines": 600},
            "document_metadata": {"status": {}},
            "sessions": [],
        }
        file_path = branch_dir / "TEST_BRANCH.local.json"
        file_path.write_text(json.dumps(memory_data, indent=2), encoding="utf-8")

        registry = {
            "branches": [
                {"name": "TEST_BRANCH", "path": str(branch_dir)},
            ]
        }
        registry_path = tmp_path / "AIPASS_REGISTRY.json"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

        with patch.object(norm, "_find_repo_root", return_value=tmp_path):
            result = norm.normalize_all_memory_files()

        assert result["success"] is True
        assert result["files_checked"] >= 1

    def test_skips_branches_with_missing_paths(self, monkeypatch, tmp_path):
        norm, _ = _import_normalize(monkeypatch)

        registry = {
            "branches": [
                {"name": "MISSING", "path": str(tmp_path / "nonexistent")},
            ]
        }
        registry_path = tmp_path / "AIPASS_REGISTRY.json"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

        with patch.object(norm, "_find_repo_root", return_value=tmp_path):
            result = norm.normalize_all_memory_files()

        assert result["success"] is True
        assert result["files_checked"] == 0

    def test_dry_run_does_not_modify_files(self, monkeypatch, tmp_path):
        norm, _ = _import_normalize(monkeypatch)

        branch_dir = tmp_path / "branch"
        branch_dir.mkdir()

        memory_data = {
            "limits": {"max_lines": 600},
            "document_metadata": {"status": {}},
            "sessions": [],
        }
        file_path = branch_dir / "BRANCH.local.json"
        original_content = json.dumps(memory_data, indent=2)
        file_path.write_text(original_content, encoding="utf-8")

        registry = {"branches": [{"name": "BRANCH", "path": str(branch_dir)}]}
        registry_path = tmp_path / "AIPASS_REGISTRY.json"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

        with patch.object(norm, "_find_repo_root", return_value=tmp_path):
            result = norm.normalize_all_memory_files(dry_run=True)

        assert result["dry_run"] is True
        # File content should not be changed in dry_run
        assert file_path.read_text(encoding="utf-8") == original_content


# ===========================================================================
# Tests: line_counter.update_all_memory_files
# ===========================================================================


class TestUpdateAllMemoryFiles:
    """Test update_all_memory_files iterates registry branches."""

    def test_returns_empty_when_no_branches(self, monkeypatch):
        lc, _ = _import_line_counter(monkeypatch)

        mock_read_registry = MagicMock(return_value=[])
        mock_get_path = MagicMock(return_value=None)

        with (
            patch(
                "aipass.memory.apps.handlers.monitor.detector._read_registry",
                mock_read_registry,
            ),
            patch(
                "aipass.memory.apps.handlers.monitor.detector._get_memory_file_path",
                mock_get_path,
            ),
        ):
            result = lc.update_all_memory_files()

        assert result["success"] is True
        assert result["updated"] == 0

    def test_updates_existing_files(self, monkeypatch, tmp_path):
        lc, mocks = _import_line_counter(monkeypatch)

        file_path = tmp_path / "local.json"
        file_path.write_text('{\n  "test": true\n}\n', encoding="utf-8")

        branch = {"name": "TEST", "path": str(tmp_path)}

        def mock_get_path(b, mem_type):
            if mem_type == "local":
                return file_path
            return None

        import importlib

        detector = importlib.import_module("aipass.memory.apps.handlers.monitor.detector")
        monkeypatch.setattr(detector, "_read_registry", lambda: [branch])
        monkeypatch.setattr(detector, "_get_memory_file_path", mock_get_path)

        result = lc.update_all_memory_files()

        assert result["success"] is True
        assert result["updated"] >= 1

    def test_tracks_failures(self, monkeypatch, tmp_path):
        lc, _mocks = _import_line_counter(monkeypatch)

        # The old failure injection was a mocked update_metadata write error.
        # That write is gone (health stamping removed 2026-08-25), so the only
        # way update_line_count can fail now is a file that is not there —
        # which is the honest remaining failure mode to track.
        file_path = tmp_path / "local.json"

        branch = {"name": "TEST", "path": str(tmp_path)}

        def mock_get_path(b, mem_type):
            if mem_type == "local":
                return file_path
            return None

        import importlib

        detector = importlib.import_module("aipass.memory.apps.handlers.monitor.detector")
        monkeypatch.setattr(detector, "_read_registry", lambda: [branch])
        monkeypatch.setattr(detector, "_get_memory_file_path", mock_get_path)

        result = lc.update_all_memory_files()

        assert result["success"] is True
        assert result["failed"] >= 1


# ===========================================================================
# The safety valve must not become a runaway log (incident 2026-08-16)
# ===========================================================================


class TestValveLoggingIsBounded:
    """@trigger raised memory_extractor.log CRITICAL at 634 lines/min.

    The valve was correct — it was refusing entries an external branch had
    written at the wrong end of the array — but it logged one WARNING per
    refused entry, each carrying the entire entry (~800 bytes). One rollover
    pass over one file produced 97 warning lines in a single second.

    A refusal is normal and can be routine at scale, so it gets ONE summary
    line per array per run. The per-entry detail drops to DEBUG, where it is
    recoverable while debugging without flooding a routine run.
    """

    @staticmethod
    def _run(monkeypatch, tmp_path, entries, limit):
        """Drive the valve through public extract_items on a tmp key_learnings file.

        The extractor's logger is substituted and the calls read off it.
        Neither caplog nor a real logging.Handler works here: the suite runs
        with prax mocked, so `extractor.logger` is not a live Logger and
        addHandler silently does nothing — a capture-based assertion would
        pass vacuously, reading zero emitted lines as zero warnings. Replacing
        the logger measures the calls the code actually made.

        `entries` must already be newest-first: extract_items re-sorts by
        number first and warns when it has to, so an unsorted array would add
        a line that is not the valve's.
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
        """n entries that all trip the valve: dated today under a head that is not.

        Numbered below `below` so the array stays newest-first — the "numbered
        above head" half cannot survive extract_items' re-sort, so the date half
        is the one a real run reaches.
        """
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
        """The alarm worth having: over limit + nothing archivable = the
        detector re-fires on this file forever. It used to be invisible,
        buried in the very wall of lines it produced."""
        entries = [self._HEAD] + self._misplaced(96, 1000)
        _kept, warnings, _debugs = self._run(monkeypatch, tmp_path, entries, 15)
        assert "NOTHING DRAINED" in warnings[0]

    def test_a_partial_refusal_is_not_called_a_skip_loop(self, monkeypatch, tmp_path):
        """Some drained means the lane still moves — warn, but do not alarm.

        Mutant (2026-09-27, killed): `excess` computed one short of `len(entries) - limit`.
        """
        old = [{"number": 999 - i, "date": "2026-01-01", "value": "old"} for i in range(40)]
        # Misplaced entries at the very END so they land inside the candidate
        # tail alongside genuinely-old ones — the mixed case.
        entries = [self._HEAD] + old + self._misplaced(5, 960)
        kept, warnings, _debugs = self._run(monkeypatch, tmp_path, entries, 15)
        assert len(kept) == 26
        assert len(warnings) == 1
        assert "NOTHING DRAINED" not in warnings[0]

    def test_no_refusals_logs_nothing(self, monkeypatch, tmp_path):
        """Mutant (2026-09-27, killed): `excess` computed one short of `len(entries) - limit`."""
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
    """A trigger counted as neither success nor failure is a hole in the tally.

    Same species as the 0/N silence fixed earlier: the detector says a file is
    ready, the extractor finds nothing to archive, and the loop ``continue``s
    without touching ``success_count`` OR ``failed``. The run then reports
    ``0/1 successful`` with an empty failure list — a number that says something
    went wrong and a list that says nothing did. Whoever reads that output has
    to guess, and the file is left in whatever state the detector objected to.

    The extractor's own skip path can even have WRITTEN the file (a newest-first
    order repair with nothing to archive persists), so "skipped" is not reliably
    "nothing happened" either.
    """

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
                "create_rollover_backup",
                return_value={"success": True, "message": "backed up"},
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
        """Mutant (2026-09-27, killed): the reason fixed to "no excess" instead of the extractor's message."""
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


# ===========================================================================
# THE LANE AGAINST THE REAL WRITE GATE (2026-08-30)
# ===========================================================================
#
# Every test above imports the extractor with `memory_files` MOCKED — correct
# for testing extraction logic, and blind to the one thing that actually took
# this lane down.
#
# On 2026-08-30 the cap gate refused rollover's write for an entry in the head
# it never touched, and the lane re-failed identically every 20 minutes for
# three hours against @seedgo's real file. When the rule was fixed, restoring
# the defect as a mutant killed exactly three tests — all of them in
# test_changed_entries.py, at the WRITER. Not one rollover test died. The suite
# for the lane that broke could not see what broke it, because it mocks the
# component that refused.
#
# @hooks found the mirror image of this in their own tree the same evening: a
# mutant that made their checker return NOTHING left all 115 of their
# end-to-end tests green, because the union ran @memory's real diff. When two
# halves overlap, a suite that cannot tell them apart proves neither.
#
# So this class mocks NOTHING below the extractor. Real memory_files, real
# entry_limits, real caps, a real file on disk — and it asserts on what is
# actually written, because "success" is what the lane reported for three
# hours while the file never changed.


class TestRolloverSurvivesCarriedDebt:
    """The live deadlock, driven through the extractor against the real writer."""

    @pytest.fixture
    def ext(self, monkeypatch):
        """The extractor with its REAL dependencies — the point of this class.

        `_import_extractor` above leaves a cached extractor module bound to a
        MagicMock `memory_files`, and that binding outlives the monkeypatch
        that created it: restoring sys.modules does not re-bind names already
        imported into a cached module. Without this eviction these tests pass
        alone and fail in the suite, reading `read_memory_file_data` as a mock
        returning None.

        Evicted with `monkeypatch.delitem`, never a bare `sys.modules.pop` — a
        bare pop is one-way and outlives the test, which is how two receipt
        tests went red on a single xdist worker in session 163.
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

        # Prove the real writer is wired, not a mock. A test class whose whole
        # purpose is "run against the real gate" must not silently run against
        # a double.
        assert isinstance(extractor.write_memory_file_simple, types.FunctionType), (
            "extractor is bound to a mocked writer — this class would prove nothing"
        )
        return extractor

    @staticmethod
    def _seedgo_shaped_file(tmp_path):
        """A file over its session count, carrying one over-cap summary in the HEAD.

        The 343-char summary is @seedgo's real shape. It sits at the top, where
        rollover archives from the BOTTOM — so the lane can never shrink it,
        and a gate that refuses the document for it can never be satisfied.
        """
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
        after = json.loads(file_path.read_text(encoding="utf-8"))["sessions"]
        assert len(after) < before_count, "the lane reported success and the file never shrank"
        assert result["extracted_count"] == before_count - len(after), (
            "extracted count disagrees with what left the file — the 3-hour lie exactly"
        )

    def test_the_carried_entry_is_still_there_and_still_over_cap(self, ext, tmp_path):
        """Rollover must not 'fix' the fat entry — it is not rollover's to touch.

        The cure for a carried entry is its own agent trimming it, or the entry
        ageing into the tail and being archived whole. A shrink lane that
        started editing text to satisfy a cap would be authoring memories.
        """
        file_path = self._seedgo_shaped_file(tmp_path)
        result = ext.extract_items(file_path)

        # Assert the run DID something first. A refused write leaves the file
        # untouched, so "the fat entry is still there" would pass on a run that
        # archived nothing — the test would be green about a dead lane.
        assert result["success"] is True, result.get("error")
        assert result["extracted_count"] > 0, "nothing was archived — this pin would pass vacuously"

        head = json.loads(file_path.read_text(encoding="utf-8"))["sessions"][0]
        assert head["summary"] == "X" * 343, "rollover edited an entry it only moves past"

    def test_a_second_run_is_not_re_archiving_the_same_entries(self, ext, tmp_path):
        """The duplicate-work loop the refusal caused, pinned from the outside.

        While the write was refused the file never changed, so every run
        extracted and vectorised the same entries again. If the file shrinks,
        the second run has strictly less to do.
        """
        file_path = self._seedgo_shaped_file(tmp_path)
        first = ext.extract_items(file_path)
        second = ext.extract_items(file_path)

        assert first["extracted_count"] > 0
        assert second.get("extracted_count", 0) < first["extracted_count"], (
            "the second run extracted as much as the first — the file did not shrink"
        )
