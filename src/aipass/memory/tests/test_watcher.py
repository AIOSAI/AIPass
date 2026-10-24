# =================== AIPass ====================
# Name: test_watcher.py
# Description: memory watcher handler — lifecycle, status, on_modified callback, branch-path walk
# Version: 1.1.1
# Created: 2026-04-25
# Modified: 2026-10-23
# Category: memory/tests
# =============================================

"""Tests for apps/handlers/monitor/memory_watcher.py."""

# All tests use mocks -- no live filesystem watchers or infrastructure access.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — watchdog.observers.Observer; a mock stands in for it, no live filesystem watch
# seedgo: no-test-needed(external) — execute_rollover itself; the orchestrator is mocked, only the call is pinned

import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aipass.memory.apps.handlers import write_fence
from aipass.memory.apps.handlers.monitor import detector, memory_watcher
from aipass.memory.apps.handlers.rollover import orchestrator
from aipass.memory.apps.handlers.schema import normalize


def _pin_lazy_import(monkeypatch, module):
    """Make a lazy ``from <module> import name`` inside the watcher read THIS real module.

    Other files evict and re-import these modules; an unpatched copy of the orchestrator is a real fleet rollover.
    """
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module


def _prepare_watcher_mocks(monkeypatch):
    """Patch, at the edge, every collaborator memory_watcher.py reaches.

    The two lazy imports (normalize, rollover orchestrator) are patched on their real modules, where they read.
    """
    mock_check_single_file = MagicMock(return_value={"success": True, "should_rollover": False})
    monkeypatch.setattr(memory_watcher, "check_single_file", mock_check_single_file)

    # watchdog: no live filesystem observer is ever started by a test.
    mock_observer_instance = MagicMock()
    mock_observer_instance.is_alive.return_value = True
    mock_observer_cls = MagicMock(return_value=mock_observer_instance)
    monkeypatch.setattr(memory_watcher, "Observer", mock_observer_cls)
    monkeypatch.setattr(memory_watcher, "WATCHDOG_AVAILABLE", True)

    monkeypatch.setattr(memory_watcher, "json_handler", MagicMock())
    monkeypatch.setattr(memory_watcher, "logger", MagicMock())

    # normalize (lazy import inside on_modified and check_and_rollover)
    mock_normalize_memory_file = MagicMock(return_value={"success": True, "changes": []})
    monkeypatch.setattr(_pin_lazy_import(monkeypatch, normalize), "normalize_memory_file", mock_normalize_memory_file)

    # rollover orchestrator (lazy import inside on_modified) — never a real rollover.
    mock_execute_rollover = MagicMock(return_value={"success": True})
    monkeypatch.setattr(_pin_lazy_import(monkeypatch, orchestrator), "execute_rollover", mock_execute_rollover)

    return {
        "check_single_file": mock_check_single_file,
        "observer_instance": mock_observer_instance,
        "observer_cls": mock_observer_cls,
        "execute_rollover": mock_execute_rollover,
        "normalize_memory_file": mock_normalize_memory_file,
    }


def _import_watcher(monkeypatch):
    """Patch the real memory_watcher's edges and return (module, mocks_dict)."""
    mocks = _prepare_watcher_mocks(monkeypatch)

    monkeypatch.setattr(memory_watcher, "_observer", None)

    return memory_watcher, mocks


class TestStartMemoryWatcher:
    """Verify start_memory_watcher lifecycle."""

    def test_start_returns_success_with_paths(self, monkeypatch, tmp_path):
        """Starting watcher with valid branch paths returns success."""
        mod, mocks = _import_watcher(monkeypatch)

        branch_path = tmp_path / "src" / "aipass" / "test_branch"
        branch_path.mkdir(parents=True)
        monkeypatch.setattr(mod, "_get_branch_paths", lambda: [branch_path])

        result = mod.start_memory_watcher()

        assert result["success"] is True
        assert result["count"] == 1
        assert str(branch_path) in result["watched_paths"]
        mocks["observer_cls"].assert_called_once()
        mocks["observer_instance"].start.assert_called_once()

    def test_start_fails_when_already_running(self, monkeypatch, tmp_path):
        """Starting when observer is already alive returns error."""
        mod, mocks = _import_watcher(monkeypatch)

        mock_existing = MagicMock()
        mock_existing.is_alive.return_value = True
        setattr(mod, "_observer", mock_existing)

        result = mod.start_memory_watcher()

        assert result["success"] is False
        assert "already running" in result["error"].lower()

    def test_start_fails_when_no_branches(self, monkeypatch):
        """Starting with no branch paths returns error."""
        mod, mocks = _import_watcher(monkeypatch)
        monkeypatch.setattr(mod, "_get_branch_paths", lambda: [])

        result = mod.start_memory_watcher()

        assert result["success"] is False
        assert "no branch" in result["error"].lower()

    def test_start_handles_schedule_error_gracefully(self, monkeypatch, tmp_path):
        """If scheduling a path raises an exception, other paths still work."""
        mod, mocks = _import_watcher(monkeypatch)

        good_path = tmp_path / "good_branch"
        good_path.mkdir(parents=True)
        bad_path = tmp_path / "bad_branch"
        bad_path.mkdir(parents=True)

        call_count = 0

        def _mock_schedule(handler, path, recursive=False):
            """Mock observer.schedule that fails on the first call."""
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("Permission denied")

        mocks["observer_instance"].schedule = _mock_schedule
        monkeypatch.setattr(mod, "_get_branch_paths", lambda: [bad_path, good_path])

        result = mod.start_memory_watcher()

        assert result["success"] is True
        # Only the second path should succeed
        assert result["count"] == 1


class TestStopMemoryWatcher:
    """Verify stop_memory_watcher lifecycle."""

    def test_stop_returns_success(self, monkeypatch):
        """Stopping a running watcher returns success."""
        mod, mocks = _import_watcher(monkeypatch)

        mock_obs = MagicMock()
        mock_obs.is_alive.return_value = True
        setattr(mod, "_observer", mock_obs)

        result = mod.stop_memory_watcher()

        assert result["success"] is True
        mock_obs.stop.assert_called_once()
        mock_obs.join.assert_called_once()
        assert mod._observer is None  # type: ignore[union-attr]

    def test_stop_fails_when_not_running(self, monkeypatch):
        """Stopping when no watcher is running returns error."""
        mod, mocks = _import_watcher(monkeypatch)

        result = mod.stop_memory_watcher()

        assert result["success"] is False
        assert "not running" in result["error"].lower()

    def test_stop_fails_when_observer_not_alive(self, monkeypatch):
        """Stopping when observer exists but is not alive returns error."""
        mod, mocks = _import_watcher(monkeypatch)

        mock_obs = MagicMock()
        mock_obs.is_alive.return_value = False
        setattr(mod, "_observer", mock_obs)

        result = mod.stop_memory_watcher()

        assert result["success"] is False


class TestIsMemoryWatcherActive:
    """Verify is_memory_watcher_active boolean checks."""

    def test_active_when_observer_alive(self, monkeypatch):
        """Returns True when observer is alive."""
        mod, mocks = _import_watcher(monkeypatch)

        mock_obs = MagicMock()
        mock_obs.is_alive.return_value = True
        setattr(mod, "_observer", mock_obs)

        assert mod.is_memory_watcher_active() is True

    def test_inactive_when_no_observer(self, monkeypatch):
        """Returns False when _observer is None."""
        mod, mocks = _import_watcher(monkeypatch)

        assert mod.is_memory_watcher_active() is False

    def test_inactive_when_observer_not_alive(self, monkeypatch):
        """Returns False when observer exists but is_alive returns False."""
        mod, mocks = _import_watcher(monkeypatch)

        mock_obs = MagicMock()
        mock_obs.is_alive.return_value = False
        setattr(mod, "_observer", mock_obs)

        assert mod.is_memory_watcher_active() is False


class TestGetWatcherStatus:
    """Verify get_watcher_status returns correct status info."""

    def test_status_when_inactive(self, monkeypatch):
        """Returns inactive status when watcher is not running."""
        mod, mocks = _import_watcher(monkeypatch)

        result = mod.get_watcher_status()

        assert result["active"] is False
        assert "not running" in result["message"].lower()

    def test_status_when_active(self, monkeypatch, tmp_path):
        """Returns active status with directory count when watcher is running."""
        mod, mocks = _import_watcher(monkeypatch)

        mock_obs = MagicMock()
        mock_obs.is_alive.return_value = True
        setattr(mod, "_observer", mock_obs)

        branch_path = tmp_path / "branch1"
        branch_path.mkdir()
        monkeypatch.setattr(mod, "_get_branch_paths", lambda: [branch_path])

        result = mod.get_watcher_status()

        assert result["active"] is True
        assert result["watched_directories"] == 1
        assert str(branch_path) in result["paths"]

    def test_status_returns_multiple_paths(self, monkeypatch, tmp_path):
        """Returns all watched directory paths."""
        mod, mocks = _import_watcher(monkeypatch)

        mock_obs = MagicMock()
        mock_obs.is_alive.return_value = True
        setattr(mod, "_observer", mock_obs)

        paths = []
        for name in ["branch_a", "branch_b", "branch_c"]:
            p = tmp_path / name
            p.mkdir()
            paths.append(p)

        monkeypatch.setattr(mod, "_get_branch_paths", lambda: paths)

        result = mod.get_watcher_status()

        assert result["watched_directories"] == 3
        assert len(result["paths"]) == 3


class TestMemoryFileWatcherOnModified:
    """Verify MemoryFileWatcher.on_modified callback behavior."""

    def test_ignores_directory_events(self, monkeypatch, tmp_path):
        """Directory modification events are ignored."""
        mod, mocks = _import_watcher(monkeypatch)

        watcher = mod.MemoryFileWatcher([tmp_path / "some"])
        event = MagicMock()
        event.is_directory = True
        event.src_path = str(tmp_path / "some" / ".trinity" / "local.json")

        watcher.on_modified(event)

        mocks["check_single_file"].assert_not_called()

    def test_ignores_non_memory_files(self, monkeypatch, tmp_path):
        """Non-memory files (not in .trinity/) are ignored."""
        mod, mocks = _import_watcher(monkeypatch)

        watcher = mod.MemoryFileWatcher([tmp_path / "some" / "dir"])
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(tmp_path / "some" / "dir" / "config.json")

        watcher.on_modified(event)

        mocks["check_single_file"].assert_not_called()

    def test_processes_memory_file_modification(self, monkeypatch, tmp_path):
        """Valid memory file modification triggers the rollover check."""
        mod, mocks = _import_watcher(monkeypatch)

        watcher = mod.MemoryFileWatcher([tmp_path / "some" / "branch"])
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(tmp_path / "some" / "branch" / ".trinity" / "local.json")

        watcher.on_modified(event)

        mocks["check_single_file"].assert_called_once_with(Path(event.src_path))

    def test_rollover_triggered_when_threshold_exceeded(self, monkeypatch, tmp_path):
        """When check_single_file says should_rollover, execute_rollover is called."""
        mod, mocks = _import_watcher(monkeypatch)

        mocks["check_single_file"].return_value = {
            "success": True,
            "should_rollover": True,
            "trigger": "5/3 sessions",
        }

        watcher = mod.MemoryFileWatcher([tmp_path / "some" / "branch"])
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(tmp_path / "some" / "branch" / ".trinity" / "local.json")

        watcher.on_modified(event)

        mocks["execute_rollover"].assert_called_once_with()
        assert watcher._recent_modifications == {str(Path(event.src_path))}

    def test_skips_recently_modified_file(self, monkeypatch, tmp_path):
        """Files already in the recent modifications set are skipped."""
        mod, mocks = _import_watcher(monkeypatch)

        watcher = mod.MemoryFileWatcher([tmp_path / "some" / "branch"])
        # str(Path(...)) matches how on_modified normalizes the key on Windows.

        file_path = str(tmp_path / "some" / "branch" / ".trinity" / "local.json")
        file_key = str(Path(file_path))
        watcher._recent_modifications.add(file_key)

        event = MagicMock()
        event.is_directory = False
        event.src_path = file_path

        watcher.on_modified(event)

        mocks["check_single_file"].assert_not_called()
        # The file key should be removed from recent modifications after skip
        assert file_key not in watcher._recent_modifications

    def test_handles_check_failure(self, monkeypatch, tmp_path):
        """When check_single_file fails, rollover is not triggered."""
        mod, mocks = _import_watcher(monkeypatch)

        mocks["check_single_file"].return_value = {
            "success": False,
            "error": "Read error",
        }

        watcher = mod.MemoryFileWatcher([tmp_path / "some" / "branch"])
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(tmp_path / "some" / "branch" / ".trinity" / "local.json")

        watcher.on_modified(event)

        mocks["check_single_file"].assert_called_once()
        mocks["execute_rollover"].assert_not_called()

    def test_processes_observations_json(self, monkeypatch, tmp_path):
        """observations.json files in .trinity/ are also processed."""
        mod, mocks = _import_watcher(monkeypatch)

        watcher = mod.MemoryFileWatcher([tmp_path / "some" / "branch"])
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(tmp_path / "some" / "branch" / ".trinity" / "observations.json")

        watcher.on_modified(event)

        mocks["check_single_file"].assert_called_once_with(Path(event.src_path))

    def test_rollover_exception_does_not_propagate(self, monkeypatch, tmp_path):
        """If execute_rollover raises, the exception is caught."""
        mod, mocks = _import_watcher(monkeypatch)
        log = MagicMock()
        monkeypatch.setattr(memory_watcher, "logger", log)

        mocks["check_single_file"].return_value = {
            "success": True,
            "should_rollover": True,
            "trigger": "10/5 sessions",
        }
        mocks["execute_rollover"].side_effect = RuntimeError("Rollover crashed")

        watcher = mod.MemoryFileWatcher([tmp_path / "some" / "branch"])
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(tmp_path / "some" / "branch" / ".trinity" / "local.json")

        watcher.on_modified(event)

        mocks["execute_rollover"].assert_called_once_with()
        assert any("Rollover crashed" in str(call) for call in log.error.call_args_list)

    def test_normalize_called_on_modification(self, monkeypatch, tmp_path):
        """on_modified calls normalize_memory_file before the rollover check."""
        mod, mocks = _import_watcher(monkeypatch)

        watcher = mod.MemoryFileWatcher([tmp_path / "some" / "branch"])
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(tmp_path / "some" / "branch" / ".trinity" / "local.json")

        watcher.on_modified(event)

        mocks["normalize_memory_file"].assert_called_once_with(Path(event.src_path))

    def test_normalize_changes_guard_write_loop(self, monkeypatch, tmp_path):
        """When normalize makes changes, file_key is added to _recent_modifications to prevent write-loop."""
        mod, mocks = _import_watcher(monkeypatch)

        mocks["normalize_memory_file"].return_value = {
            "success": True,
            "changes": ["Stripped orphan 'stale_key' from root"],
        }

        watcher = mod.MemoryFileWatcher([tmp_path / "some" / "branch"])
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(tmp_path / "some" / "branch" / ".trinity" / "local.json")

        watcher.on_modified(event)

        file_key = str(tmp_path / "some" / "branch" / ".trinity" / "local.json")
        assert file_key in watcher._recent_modifications

    def test_normalize_no_changes_no_guard(self, monkeypatch, tmp_path):
        """When normalize makes no changes, _recent_modifications is not populated by normalize step."""
        mod, mocks = _import_watcher(monkeypatch)

        mocks["normalize_memory_file"].return_value = {
            "success": True,
            "changes": [],
        }

        watcher = mod.MemoryFileWatcher([tmp_path / "some" / "branch"])
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(tmp_path / "some" / "branch" / ".trinity" / "local.json")

        watcher.on_modified(event)

        file_key = str(tmp_path / "some" / "branch" / ".trinity" / "local.json")
        # file_key should NOT be in _recent_modifications from normalize (may be from rollover)
        mocks["check_single_file"].return_value = {"success": True, "should_rollover": False}
        assert file_key not in watcher._recent_modifications


class TestTheWatcherOwnsOnlyTheMemoryFilesOfItsRoots:
    """A dropbox and an .archive are sandboxes: nothing the watcher does reaches them.

    The observer hears memory files anywhere below a recursive schedule. The handler is taken from
    the observer's own schedule call, so these pins judge the watcher ``start_memory_watcher`` builds.
    """

    def _scheduled_watcher(self, monkeypatch, branch):
        mod, mocks = _import_watcher(monkeypatch)
        monkeypatch.setattr(mod, "_get_branch_paths", lambda: [branch])
        assert mod.start_memory_watcher()["success"] is True
        handler = mocks["observer_instance"].schedule.call_args.args[0]
        return handler, mocks

    def _modify(self, handler, file_path):
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("{}", encoding="utf-8")
        event = MagicMock()
        event.is_directory = False
        event.src_path = str(file_path)
        handler.on_modified(event)

    @pytest.mark.parametrize(
        "sandbox",
        [("dropbox", "any", ".trinity"), (".archive", ".trinity")],
        ids=["dropbox", "archive"],
    )
    def test_a_memory_file_copy_inside_a_sandbox_is_left_alone(self, monkeypatch, tmp_path, sandbox):
        """A modified local.json in a sandbox is not rewritten, not measured, not checked."""
        branch = tmp_path / "src" / "aipass" / "some_branch"
        handler, mocks = self._scheduled_watcher(monkeypatch, branch)

        self._modify(handler, branch.joinpath(*sandbox, "local.json"))

        mocks["normalize_memory_file"].assert_not_called()
        mocks["check_single_file"].assert_not_called()

    def test_the_branch_own_memory_file_is_handled_as_before(self, monkeypatch, tmp_path):
        """The control beside the sandboxes: the branch's own .trinity/local.json."""
        branch = tmp_path / "src" / "aipass" / "some_branch"
        handler, mocks = self._scheduled_watcher(monkeypatch, branch)
        own = branch / ".trinity" / "local.json"

        self._modify(handler, own)

        mocks["normalize_memory_file"].assert_called_once_with(own)
        mocks["check_single_file"].assert_called_once_with(own)

    def test_a_root_reached_through_a_symlink_is_heard_at_its_real_path(self, monkeypatch, tmp_path):
        """An observer may report the real path behind a symlinked root .

        A platform that cannot make a symlink uses the real directory as the root.
        """
        real = tmp_path / "real_branch"
        real.mkdir()
        branch = tmp_path / "linked_branch"
        try:
            branch.symlink_to(real, target_is_directory=True)
        except OSError as exc:
            logging.getLogger(__name__).info("No symlink on this platform (%s): the root is the real directory", exc)
            branch = real
        handler, mocks = self._scheduled_watcher(monkeypatch, branch)
        reported = real / ".trinity" / "local.json"

        self._modify(handler, reported)

        mocks["normalize_memory_file"].assert_called_once_with(reported)
        mocks["check_single_file"].assert_called_once_with(reported)


class TestTheBranchPathWalkReadsNamesNotSpellings:
    """The fourth of this tree's ``*_REGISTRY.json`` walks — detector's twin.

    A folded match's "branches" become paths this watcher rewrites. Trap: ``_get_branch_paths``
    shadows ``repo_root`` with a Path local, so ``exactly_named`` is imported by name.
    """

    @pytest.fixture
    def caller_tree(self, tmp_path, monkeypatch):

        home = tmp_path / "aipass_home"
        home.mkdir()
        (home / "AIPASS_REGISTRY.json").write_text('{"branches":[]}', encoding="utf-8")
        # The watcher walks the rollover scope, so the root it stands on is the detector's.
        monkeypatch.setattr(detector, "_REPO_ROOT", home)

        foreign = tmp_path / "foreign_project"
        (foreign / "src" / "real").mkdir(parents=True)
        (foreign / "src" / "bait").mkdir(parents=True)
        (foreign / "FOREIGN_REGISTRY.json").write_text(
            json.dumps({"branches": [{"name": "real", "path": "src/real", "status": "active"}]}), encoding="utf-8"
        )
        (foreign / "flow_json_registry.json").write_text(
            json.dumps({"branches": [{"name": "bait", "path": "src/bait", "status": "active"}]}), encoding="utf-8"
        )
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(foreign))
        return foreign

    def test_the_injected_world_really_widens(self, caller_tree, case_insensitive_filesystem):
        """Positive control, before anything below is believed."""
        matched = sorted(path.name for path in caller_tree.glob("*_REGISTRY.json"))

        assert matched == ["FOREIGN_REGISTRY.json", "flow_json_registry.json"]

    @staticmethod
    def _watched(monkeypatch) -> dict:
        """start_memory_watcher() with watchdog's Observer mocked: the paths it would watch, or its refusal."""
        mod, _mocks = _import_watcher(monkeypatch)
        return mod.start_memory_watcher()

    def test_a_folded_registry_never_contributes_a_path_to_roll_over(
        self, caller_tree, case_insensitive_filesystem, monkeypatch
    ):

        names = {Path(path).name for path in self._watched(monkeypatch)["watched_paths"]}

        assert "real" in names, "the genuine branch was lost while excluding the impostor"
        assert "bait" not in names

    def test_a_caller_outside_the_aipass_root_contributes_nothing_to_roll_over(self, caller_tree, monkeypatch):
        """A foreign project beside the fenced home is another repository: nothing it lists is rolled over."""

        monkeypatch.setattr(write_fence, "ROOT", caller_tree.parent / "aipass_home")

        assert self._watched(monkeypatch) == {
            "success": False,
            "error": "No branch paths found in AIPASS_REGISTRY.json",
        }

    def test_a_declared_resident_reaches_the_watcher_with_nothing_remembered(self, tmp_path, monkeypatch):
        """A declared resident reaches the watcher through the rollover scope: one fleet for both write lanes."""

        home = tmp_path / "aipass_home"
        branch = home / "projects" / "guest" / "src" / "guest"
        (branch / ".trinity").mkdir(parents=True)
        (home / "AIPASS_REGISTRY.json").write_text('{"branches":[]}', encoding="utf-8")
        (home / "projects" / "guest" / "GUEST_REGISTRY.json").write_text(
            json.dumps({"branches": [{"name": "guest", "path": "src/guest", "status": "active"}]}), encoding="utf-8"
        )
        (branch / ".trinity" / "passport.json").write_text(
            json.dumps({"citizenship": {"residency": "resident"}}), encoding="utf-8"
        )
        neutral = tmp_path / "neutral"
        neutral.mkdir()
        monkeypatch.setattr(detector, "_REPO_ROOT", home)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(neutral))

        assert [Path(path).name for path in self._watched(monkeypatch)["watched_paths"]] == ["guest"]


class TestTheTrinityMatchIsAFilenameNotAPattern:
    """``local.json`` has no wildcard in it, so it was never a glob's job.

    On a folding filesystem a glob also matches ``Local.json``, and what this loop matches gets rewritten.
    """

    def test_a_differently_cased_memory_file_is_not_checked(self, tmp_path, monkeypatch, case_insensitive_filesystem):

        branch = tmp_path / "src" / "aipass" / "impostor"
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".trinity" / "Local.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(memory_watcher, "_get_branch_paths", lambda: [branch])
        # check_and_rollover is once-per-process; without this reset the second test asserts nothing.
        monkeypatch.setattr(memory_watcher, "_startup_check_done", False)

        assert memory_watcher.check_and_rollover()["files_checked"] == 0

    def test_the_correctly_spelled_file_is_still_checked(self, tmp_path, monkeypatch, case_insensitive_filesystem):
        """The guard must not blind the lane it protects."""

        branch = tmp_path / "src" / "aipass" / "genuine"
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".trinity" / "local.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(memory_watcher, "_get_branch_paths", lambda: [branch])
        # check_and_rollover is once-per-process; without this reset the second test asserts nothing.
        monkeypatch.setattr(memory_watcher, "_startup_check_done", False)

        assert memory_watcher.check_and_rollover()["files_checked"] == 1


class TestAnUnreadableRegistryIsAnsweredByEveryEntry:
    """Each watcher entry answers its own failure shape, naming the registry, never a raise.

    The registry read raises at its home in detector; the real _get_branch_paths runs. No observer starts.
    """

    @staticmethod
    def _unreadable(monkeypatch, tmp_path) -> Path:
        registry = tmp_path / "AIPASS_REGISTRY.json"

        def _raise():
            raise detector.RegistryUnreadable(f"Unreadable registry {registry}: x")

        monkeypatch.setattr(detector, "_read_registry", _raise)
        return registry

    def test_the_startup_check_fails_and_names_it(self, monkeypatch, tmp_path):
        mod, _ = _import_watcher(monkeypatch)
        registry = self._unreadable(monkeypatch, tmp_path)
        monkeypatch.setattr(mod, "_startup_check_done", False)
        deps = MagicMock(return_value=True)  # the probe is a real subprocess; never run here
        monkeypatch.setattr(mod, "_check_vector_deps", deps)

        result = mod.check_and_rollover()

        deps.assert_called_once_with()
        assert result["success"] is False
        assert str(registry) in result["error"]

    def test_degraded_vector_deps_skip_the_rollover(self, monkeypatch, tmp_path):
        """An over-limit file keeps its entries when the store cannot take them: no rollover, and said so."""
        mod, mocks = _import_watcher(monkeypatch)
        monkeypatch.setattr(mod, "_startup_check_done", False)
        monkeypatch.setattr(mod, "_check_vector_deps", MagicMock(return_value=False))
        monkeypatch.setattr(mod, "_check_memory_pool", lambda: None)
        monkeypatch.setattr(mod, "_check_plans", lambda: None)
        trinity = tmp_path / "b" / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "local.json").write_text('{"sessions": []}', encoding="utf-8")
        monkeypatch.setattr(mod, "_get_branch_paths", lambda: [tmp_path / "b"])
        monkeypatch.setattr(detector, "_should_rollover", lambda path: (True, 9, "3.0.0", "16/15 sessions"))

        result = mod.check_and_rollover()

        mocks["execute_rollover"].assert_not_called()
        assert result["rollover_triggered"] is False
        assert result["rollover_skipped"] == "vector storage degraded"
        assert len(result["files_over_limit"]) == 1

    def test_the_start_refuses_and_names_it(self, monkeypatch, tmp_path):
        mod, mocks = _import_watcher(monkeypatch)
        registry = self._unreadable(monkeypatch, tmp_path)

        result = mod.start_memory_watcher()

        assert result["success"] is False
        assert str(registry) in result["error"]
        mocks["observer_instance"].start.assert_not_called()

    def test_the_status_of_a_running_watcher_names_it(self, monkeypatch, tmp_path):
        mod, _ = _import_watcher(monkeypatch)
        registry = self._unreadable(monkeypatch, tmp_path)
        running = MagicMock()
        running.is_alive.return_value = True
        monkeypatch.setattr(mod, "_observer", running)

        result = mod.get_watcher_status()

        assert result["active"] is True
        assert str(registry) in result["error"]
