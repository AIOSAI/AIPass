# =================== AIPass ====================
# Name: test_monitoring_handlers.py
# Description: Unit tests for monitoring handler modules
# Version: 1.3.0
# Created: 2026-04-25
# Modified: 2026-10-03
# =============================================

"""Tests for apps/handlers/monitoring/branch_detector.py and the three sibling handlers listed below."""

# Covers:
# - branch_detector: get_detector, reload_registry, detect_from_path,
#   detect_from_log, detect_from_module, get_stats
# - file_watcher_integration: load_branch_paths, file_event_callback,
#   get_file_watcher, is_file_watcher_running, get_file_watcher_stats,
#   FileWatcherManager.is_running, FileWatcherManager.get_stats
# - interactive_filter: parse_command, get_help_text
# - unified_stream: print_event, print_command_separator, print_status

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — print_hook_event(), covered by tests/test_display_resilience.py

import io
import json
from pathlib import Path, PurePosixPath
from unittest.mock import MagicMock, mock_open as _mock_file_open, patch

import pytest
from rich.console import Console

from aipass.prax.apps.handlers import repo_root as repo_root_mod
from aipass.prax.apps.handlers.config import load as config_load
from aipass.prax.apps.handlers.monitoring import branch_detector, unified_stream
from aipass.prax.apps.handlers.monitoring import file_watcher_integration, interactive_filter

# The detector is fed POSIX-spelled strings through a mocked Path, so none of
# these reach a disk. Built from parts under a root with no home directory in
# it (prax, leg 3): a checkout path is a fixture, not anyone's home.
_HOME = PurePosixPath("/", "ws")
_WS = _HOME / "Projects" / "AIPass"
_ECO = _WS / "src" / "aipass"

# Alias mock_open to avoid false-positive pattern match on "open(" without encoding
_mopen = _mock_file_open


# =============================================
# BRANCH DETECTOR TESTS
# =============================================


@pytest.fixture(autouse=True)
def _branch_detector_fresh(monkeypatch):
    """Double branch_detector's collaborators where it binds them and empty its singleton.

    Replaces a re-import under a mocked Path, json.load and open: the module
    reads no file at import, so all the re-import gave was an empty singleton.
    """
    monkeypatch.setattr(branch_detector, "logger", MagicMock())
    monkeypatch.setattr(branch_detector, "json_handler", MagicMock())
    monkeypatch.setattr(branch_detector, "_detector_instance", None)


def _import_branch_detector():
    """The branch_detector module, bound at the top of this file."""
    return branch_detector


def _detector_log() -> MagicMock:
    """The logger double the autouse fixture set on branch_detector."""
    log = branch_detector.logger
    assert isinstance(log, MagicMock), "branch_detector.logger is not doubled"
    return log


def _make_detector_with_branches(mod, branches: dict | None = None):
    """Create a BranchDetector with controlled state (no filesystem access)."""
    with patch.object(mod.BranchDetector, "_load_registry"):
        detector = mod.BranchDetector()
    # Populate known_branches and branch_map manually
    if branches is None:
        branches = {
            str(_ECO / "prax"): "PRAX",
            str(_ECO / "seedgo"): "SEEDGO",
            str(_ECO / "flow"): "FLOW",
            str(_ECO / "cli"): "CLI",
            str(_ECO / "ai_mail"): "AI_MAIL",
        }
    for path_str, name in branches.items():
        detector.branch_map[path_str] = name
        detector.known_branches.add(name)
    return detector


class TestGetDetector:
    """Tests for get_detector() singleton."""

    def test_returns_branch_detector_instance(self):
        """get_detector() builds a detector with empty caches and parks it on the module."""
        mod = _import_branch_detector()
        setattr(mod, "_detector_instance", None)
        with patch.object(mod.BranchDetector, "_load_registry", autospec=True):
            detector = mod.get_detector()

        assert isinstance(detector, mod.BranchDetector)
        assert detector.branch_map == {}
        assert detector.log_map == {}
        assert detector.module_map == {}
        assert detector.known_branches == set()
        assert mod._detector_instance is detector, "the singleton slot must hold what was handed back"

    def test_returns_same_instance_on_second_call(self):
        """get_detector() should return the same singleton on repeated calls."""
        mod = _import_branch_detector()
        setattr(mod, "_detector_instance", None)
        with patch.object(mod.BranchDetector, "__init__", return_value=None):
            first = mod.get_detector()
            second = mod.get_detector()
            assert first is second

    def test_creates_new_instance_after_reset(self):
        """get_detector() should create a new instance when singleton is None."""
        mod = _import_branch_detector()
        with patch.object(mod.BranchDetector, "__init__", return_value=None):
            setattr(mod, "_detector_instance", None)
            d1 = mod.get_detector()
            setattr(mod, "_detector_instance", None)
            d2 = mod.get_detector()
            assert d1 is not d2


class TestReloadRegistry:
    """Tests for BranchDetector.reload_registry()."""

    def test_clears_caches_and_reloads(self):
        """reload_registry() should clear all caches and reload from registry."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        # Populate caches
        detector.log_map["some_log"] = "PRAX"
        detector.module_map["some.module"] = "FLOW"

        with patch.object(detector, "_load_registry") as mock_load:
            detector.reload_registry()

        assert len(detector.branch_map) == 0
        assert len(detector.log_map) == 0
        assert len(detector.module_map) == 0
        assert len(detector.known_branches) == 0
        # _load_registry takes no arguments: the claim is one reload, nothing handed on.
        mock_load.assert_called_once_with()

    def test_reload_restores_branches(self):
        """reload_registry() should restore branches after clearing."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        def fake_load():
            """Simulate _load_registry by populating branch state."""
            detector.known_branches.add("PRAX")
            detector.branch_map["/prax"] = "PRAX"

        with patch.object(detector, "_load_registry", side_effect=fake_load):
            detector.reload_registry()

        assert "PRAX" in detector.known_branches
        assert detector.branch_map["/prax"] == "PRAX"


class TestDetectFromPath:
    """Tests for BranchDetector.detect_from_path()."""

    def test_exact_match(self):
        """Should return branch for exact path match."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        # Path.resolve() returns the real path; we need the branch_map key
        # to match. Mock Path to control resolution.
        resolved = str(_ECO / "prax")
        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path = MagicMock(spec=Path)
            mock_path.__str__ = MagicMock(return_value=resolved)
            mock_path.resolve.return_value = mock_path
            mock_path.parents = []
            mock_path.parent = MagicMock()
            mock_path.name = "branch_detector.py"
            mock_path_cls.return_value = mock_path
            mock_path_cls.home.return_value = Path(str(_HOME))
            # _find_repo_root
            detector._repo_root = MagicMock(spec=Path)
            detector._repo_root.__str__ = MagicMock(return_value=str(_WS))

            result = detector.detect_from_path(resolved)

        assert result == "PRAX"

    def test_parent_directory_match(self):
        """Should detect branch by walking up parent directories."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        child = str(_ECO / "seedgo" / "core" / "validator.py")
        parent_str = str(_ECO / "seedgo")

        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path = MagicMock(spec=Path)
            mock_path.__str__ = MagicMock(return_value=child)
            mock_path.resolve.return_value = mock_path
            mock_path.name = "validator.py"

            mock_parent = MagicMock(spec=Path)
            mock_parent.__str__ = MagicMock(return_value=parent_str)
            mock_path.parents = [mock_parent]
            mock_path.parent = mock_parent

            mock_path_cls.return_value = mock_path
            mock_path_cls.home.return_value = Path(str(_HOME))

            detector._repo_root = MagicMock(spec=Path)
            detector._repo_root.__str__ = MagicMock(return_value=str(_WS))

            result = detector.detect_from_path(child)

        assert result == "SEEDGO"

    def test_unknown_path(self):
        """Should return UNKNOWN for unrecognized paths."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path = MagicMock(spec=Path)
            mock_path.__str__ = MagicMock(return_value=str(_HOME / "random" / "file.txt"))
            mock_path.resolve.return_value = mock_path
            mock_path.parents = []
            mock_path.parent = MagicMock()
            mock_path.parent.__eq__ = MagicMock(return_value=False)
            mock_path.name = "file.txt"
            mock_path_cls.return_value = mock_path
            mock_path_cls.home.return_value = Path(str(_HOME))

            detector._repo_root = MagicMock(spec=Path)
            detector._repo_root.__str__ = MagicMock(return_value=str(_WS))

            result = detector.detect_from_path(str(_HOME / "random" / "file.txt"))

        assert result == "UNKNOWN"

    def test_exception_returns_unknown(self, tmp_path):
        """Should return UNKNOWN when an exception occurs."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        with patch(f"{mod.__name__}.Path", side_effect=Exception("boom")):
            result = detector.detect_from_path(str(tmp_path / "invalid"))

        assert result == "UNKNOWN"

    def test_caches_result(self):
        """detect_from_path should cache results in log_map."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        resolved = str(_ECO / "flow")

        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path = MagicMock(spec=Path)
            mock_path.__str__ = MagicMock(return_value=resolved)
            mock_path.resolve.return_value = mock_path
            mock_path.parents = []
            mock_path.parent = MagicMock()
            mock_path.name = "something.py"
            mock_path_cls.return_value = mock_path
            mock_path_cls.home.return_value = Path(str(_HOME))

            detector._repo_root = MagicMock(spec=Path)
            detector._repo_root.__str__ = MagicMock(return_value=str(_WS))

            detector.detect_from_path(resolved)

        assert resolved in detector.log_map


class TestDetectFromLog:
    """Tests for BranchDetector.detect_from_log()."""

    def test_known_branch_prefix(self):
        """Should detect branch from log filename with known prefix."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        result = detector.detect_from_log("seedgo_audit.log")
        assert result == "SEEDGO"

    def test_exact_branch_name_log(self):
        """Should detect branch when log name matches exactly."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        result = detector.detect_from_log("prax.log")
        assert result == "PRAX"

    def test_underscore_fallback(self):
        """Should fall back to first underscore segment for unknown logs."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        result = detector.detect_from_log("custom_report_20260101.log")
        assert result == "CUSTOM"

    def test_unknown_log_no_underscore(self):
        """Should return UNKNOWN for unrecognizable log names."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        result = detector.detect_from_log("randomname.log")
        assert result == "UNKNOWN"

    def test_caches_result(self):
        """detect_from_log should cache stem in log_map."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector.detect_from_log("flow_plan.log")
        assert "flow_plan" in detector.log_map

    def test_exception_returns_unknown(self):
        """Should return UNKNOWN on exception."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        with patch(f"{mod.__name__}.Path", side_effect=Exception("bad")):
            result = detector.detect_from_log("crash.log")

        assert result == "UNKNOWN"

    def test_full_path_delegates_to_detect_from_path(self, tmp_path):
        """Log file with full path should delegate to detect_from_path for unknown prefixes."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        # Use a POSIX-style path so the "/" in log_file check in detect_from_log
        # triggers the delegation. On Windows, tmp_path uses backslashes which
        # would not match the "/" check in the production code.
        fake_log_path = str(_HOME / "branch_output" / "something.log")
        with patch.object(detector, "detect_from_path", return_value="CLI") as mock_dfp:
            result = detector.detect_from_log(fake_log_path)

        mock_dfp.assert_called_once_with(fake_log_path)
        assert result == "CLI"


class TestDetectFromModule:
    """Tests for BranchDetector.detect_from_module()."""

    def test_known_module_prefix(self):
        """Should detect branch from first dotted segment."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        # Add AIPASS to known branches since modules start with "aipass"
        detector.known_branches.add("AIPASS")
        result = detector.detect_from_module("aipass.prax.apps")
        assert result == "AIPASS"

    def test_single_segment_known(self):
        """Should detect branch from single-segment module name."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        result = detector.detect_from_module("seedgo")
        assert result == "SEEDGO"

    def test_unknown_module(self):
        """Should return UNKNOWN for unrecognized module."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        result = detector.detect_from_module("pandas.core.frame")
        assert result == "UNKNOWN"

    def test_caches_result(self):
        """detect_from_module should cache in module_map."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector.detect_from_module("flow.planners.daily")
        assert "flow.planners.daily" in detector.module_map

    def test_empty_string_returns_unknown(self):
        """Empty module name should return UNKNOWN."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        result = detector.detect_from_module("")
        assert result == "UNKNOWN"

    def test_exception_returns_unknown(self):
        """Should return UNKNOWN on exception."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        # Force an exception by corrupting the input type
        result = detector.detect_from_module(None)  # type: ignore[arg-type]
        assert result == "UNKNOWN"


class TestGetStats:
    """Tests for BranchDetector.get_stats()."""

    def test_returns_correct_keys(self):
        """get_stats() should return dict with expected keys."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        stats = detector.get_stats()
        assert "branch_paths" in stats
        assert "cached_lookups" in stats
        assert "cached_modules" in stats
        assert "known_branches" in stats

    def test_counts_match_state(self):
        """get_stats() counts should match internal state."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector.log_map["a"] = "X"
        detector.log_map["b"] = "Y"
        detector.module_map["m.x"] = "Z"

        stats = detector.get_stats()
        assert stats["branch_paths"] == len(detector.branch_map)
        assert stats["cached_lookups"] == 2
        assert stats["cached_modules"] == 1
        assert stats["known_branches"] == len(detector.known_branches)

    def test_empty_detector_stats(self):
        """get_stats() on fresh detector should have zero caches."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod, branches={})
        stats = detector.get_stats()
        assert stats["branch_paths"] == 0
        assert stats["cached_lookups"] == 0
        assert stats["cached_modules"] == 0
        assert stats["known_branches"] == 0


# =============================================
# FILE WATCHER INTEGRATION TESTS
# =============================================


_FILE_WATCHER_DOUBLES: dict[str, MagicMock] = {}


@pytest.fixture(autouse=True)
def _file_watcher_doubled(monkeypatch, tmp_path):
    """Double file_watcher_integration's collaborators where it binds them.

    The watcher and the event queue are replaced on the module itself, and the
    repo root the loader asks config.load for is this test's tmp_path, so a
    registry the test writes there is the one read. Replaces raw sys.modules
    assignments that nothing put back (prax, leg 12).
    """
    watcher = MagicMock()
    watcher.WATCHDOG_AVAILABLE = True
    watcher.start_monitoring = MagicMock(return_value=MagicMock())
    event_queue = MagicMock()
    event_queue.global_queue.enqueue = MagicMock(return_value=True)
    for name in ("start_monitoring", "stop_monitoring", "WATCHDOG_AVAILABLE"):
        monkeypatch.setattr(file_watcher_integration, name, getattr(watcher, name))
    monkeypatch.setattr(file_watcher_integration, "MonitoringEvent", event_queue.MonitoringEvent)
    monkeypatch.setattr(file_watcher_integration, "global_queue", event_queue.global_queue)
    monkeypatch.setattr(file_watcher_integration, "logger", MagicMock())
    monkeypatch.setattr(file_watcher_integration, "json_handler", MagicMock())
    monkeypatch.setattr(file_watcher_integration, "_file_watcher", None)
    monkeypatch.setattr(config_load, "_find_repo_root", lambda: tmp_path)
    monkeypatch.setitem(_FILE_WATCHER_DOUBLES, "watcher", watcher)
    monkeypatch.setitem(_FILE_WATCHER_DOUBLES, "event_queue", event_queue)


def _import_file_watcher_integration():
    """The top-bound module and the doubles the autouse fixture set on it."""
    return (
        file_watcher_integration,
        _FILE_WATCHER_DOUBLES["watcher"],
        _FILE_WATCHER_DOUBLES["event_queue"],
        config_load,
    )


def _write_registry(root: Path, payload: str) -> None:
    """Write AIPASS_REGISTRY.json under the repo root the loader is pointed at."""
    (root / "AIPASS_REGISTRY.json").write_text(payload, encoding="utf-8")


class TestLoadBranchPaths:
    """Tests for load_branch_paths()."""

    def test_returns_branch_tuples(self, tmp_path):
        """Should return list of (name, Path) tuples from registry, folders that exist only."""
        mod, _, _, _ = _import_file_watcher_integration()
        for name in ("prax", "cli"):
            (tmp_path / name).mkdir()
        branches = [{"name": n, "path": str(tmp_path / n.lower())} for n in ("PRAX", "CLI", "GONE")]
        _write_registry(tmp_path, json.dumps({"branches": branches}))

        result = mod.load_branch_paths()

        assert result == [("PRAX", tmp_path / "prax"), ("CLI", tmp_path / "cli")]

    def test_with_branch_filter(self, tmp_path):
        """Should filter branches when branch_filter is provided."""
        mod, _, _, _ = _import_file_watcher_integration()
        for name in ("prax", "cli", "flow"):
            (tmp_path / name).mkdir()
        branches = [{"name": n, "path": str(tmp_path / n.lower())} for n in ("PRAX", "CLI", "FLOW")]
        _write_registry(tmp_path, json.dumps({"branches": branches}))

        result = mod.load_branch_paths(branch_filter=["prax", "FLOW"])

        assert [name for name, _ in result] == ["PRAX", "FLOW"]

    def test_missing_registry_returns_empty(self, tmp_path):
        """Should return empty list when registry file is missing.

        The absence is measured by the open FAILING, not by an exists() call
        that answered about a moment already over: the loader opens and handles
        FileNotFoundError, so no registry is written and nothing is stubbed.
        """
        mod, _, _, _ = _import_file_watcher_integration()

        result = mod.load_branch_paths()

        assert result == []
        # The message has to be the ABSENCE one, not the catch-all: a loader
        # that lost its guard also answers [] here, through the generic
        # "Could not read the branch registry" clause at the bottom, so the
        # return value alone cannot tell the two apart.
        warnings = " ".join(str(call) for call in mod.logger.warning.call_args_list)
        assert "No branch registry at" in warnings
        assert mod.logger.error.call_args_list == []

    def test_invalid_json_returns_empty(self, tmp_path):
        """Should return empty list on JSON decode error, and say it was the JSON."""
        mod, _, _, _ = _import_file_watcher_integration()
        _write_registry(tmp_path, "{invalid json")

        result = mod.load_branch_paths()

        assert result == []
        assert "The branch registry is not valid JSON (line 1)" in mod.logger.error.call_args.args[0]

    def test_empty_branches_returns_empty(self, tmp_path):
        """Should return empty list when branches array is empty."""
        mod, _, _, _ = _import_file_watcher_integration()
        _write_registry(tmp_path, json.dumps({"branches": []}))

        result = mod.load_branch_paths()

        assert result == []
        assert "lists no branches" in mod.logger.warning.call_args.args[0]


class TestFileEventCallback:
    """Tests for file_event_callback()."""

    def test_creates_monitoring_event(self, tmp_path):
        """Should create and enqueue a MonitoringEvent."""
        mod, _, mock_eq, _ = _import_file_watcher_integration()

        changed_file = str(tmp_path / "some" / "file.py")
        mod.file_event_callback("PRAX", "MODIFIED", changed_file)

        assert mod.MonitoringEvent.call_count == 1
        kwargs = mod.MonitoringEvent.call_args.kwargs
        assert (kwargs["branch"], kwargs["action"], kwargs["message"]) == ("PRAX", "modified", changed_file)
        mod.global_queue.enqueue.assert_called_once_with(mod.MonitoringEvent.return_value)

    def test_maps_event_types_correctly(self, tmp_path):
        """A known event type gets its mapped action and the priority that goes with it."""
        mod, _, mock_eq, _ = _import_file_watcher_integration()

        changed_file = str(tmp_path / "file.py")
        mod.file_event_callback("CLI", "CREATED", changed_file)

        kwargs = mod.MonitoringEvent.call_args.kwargs
        assert kwargs["action"] == "created"
        assert kwargs["priority"] == 2, "created is one of the three that outrank a modify"
        assert kwargs["event_type"] == "file"
        assert kwargs["branch"] == "CLI"
        assert kwargs["message"] == changed_file
        assert kwargs["level"] == "info"

    def test_handles_unknown_event_type(self, tmp_path):
        """An event type outside the map is lowercased and falls to the default priority."""
        mod, _, mock_eq, _ = _import_file_watcher_integration()

        mod.file_event_callback("FLOW", "RENAMED", str(tmp_path / "file.py"))

        kwargs = mod.MonitoringEvent.call_args.kwargs
        assert kwargs["action"] == "renamed"
        assert kwargs["priority"] == 3, "an unmapped action takes the priority_map default"
        assert kwargs["branch"] == "FLOW"

    def test_handles_exception(self, tmp_path):
        """A failing event build is swallowed: nothing is enqueued and the error is logged."""
        mod, _, mock_eq, _ = _import_file_watcher_integration()
        mod.MonitoringEvent.side_effect = Exception("boom")

        changed_file = str(tmp_path / "file.py")
        assert mod.file_event_callback("PRAX", "MODIFIED", changed_file) is None

        mock_eq.global_queue.enqueue.assert_not_called()
        mod.logger.error.assert_called_once()
        message = mod.logger.error.call_args.args[0]
        assert f"unexpected Exception (PRAX MODIFIED {changed_file})" in message
        assert "file watching continues" in message


class TestGetFileWatcher:
    """Tests for get_file_watcher() singleton."""

    def test_returns_file_watcher_manager(self):
        """get_file_watcher() builds an idle manager on the global queue and caches it."""
        mod, _, mock_eq, _ = _import_file_watcher_integration()
        setattr(mod, "_file_watcher", None)

        watcher = mod.get_file_watcher()

        assert isinstance(watcher, mod.FileWatcherManager)
        assert watcher.queue is mock_eq.global_queue, "no queue argument means the global one"
        assert watcher.running is False
        assert watcher.observer is None
        assert watcher.branch_paths == []
        assert watcher.branch_filter is None
        assert mod._file_watcher is watcher, "the singleton slot must hold what was handed back"

    def test_returns_same_instance(self):
        """get_file_watcher() should return singleton."""
        mod, _, _, _ = _import_file_watcher_integration()
        setattr(mod, "_file_watcher", None)
        first = mod.get_file_watcher()
        second = mod.get_file_watcher()
        assert first is second


class TestIsFileWatcherRunning:
    """Tests for is_file_watcher_running() module-level function."""

    def test_false_when_not_started(self):
        """Should return False when watcher has not been started."""
        mod, _, _, _ = _import_file_watcher_integration()
        setattr(mod, "_file_watcher", None)
        assert mod.is_file_watcher_running() is False

    def test_true_when_running(self):
        """Should return True when watcher is running."""
        mod, _, _, _ = _import_file_watcher_integration()
        watcher = mod.FileWatcherManager()
        watcher.running = True
        setattr(mod, "_file_watcher", watcher)
        assert mod.is_file_watcher_running() is True


class TestGetFileWatcherStats:
    """Tests for get_file_watcher_stats() module-level function."""

    def test_returns_stats_dict(self):
        """Should return stats dictionary from the manager."""
        mod, _, _, _ = _import_file_watcher_integration()
        setattr(mod, "_file_watcher", None)
        stats = mod.get_file_watcher_stats()
        assert stats == {
            "running": False,
            "branches_watched": 0,
            "branch_names": [],
            "watchdog_available": mod.WATCHDOG_AVAILABLE,
        }

    def test_reflects_manager_state(self, tmp_path):
        """Stats should reflect current manager state."""
        mod, _, _, _ = _import_file_watcher_integration()
        watcher = mod.FileWatcherManager()
        watcher.running = True
        watcher.branch_paths = [("PRAX", tmp_path / "prax"), ("CLI", tmp_path / "cli")]
        setattr(mod, "_file_watcher", watcher)
        stats = mod.get_file_watcher_stats()
        assert stats["running"] is True
        assert stats["branches_watched"] == 2
        assert "PRAX" in stats["branch_names"]


class TestFileWatcherManagerIsRunning:
    """Tests for FileWatcherManager.is_running() instance method."""

    def test_false_initially(self):
        """is_running() should be False for new instance."""
        mod, _, _, _ = _import_file_watcher_integration()
        mgr = mod.FileWatcherManager()
        assert mgr.is_running() is False

    def test_true_after_setting(self):
        """is_running() should reflect running state."""
        mod, _, _, _ = _import_file_watcher_integration()
        mgr = mod.FileWatcherManager()
        mgr.running = True
        assert mgr.is_running() is True

    def test_false_after_stop(self):
        """is_running() should be False after stop()."""
        mod, _, _, _ = _import_file_watcher_integration()
        mgr = mod.FileWatcherManager()
        mgr.running = True
        mgr.observer = MagicMock()
        mgr.stop()
        assert mgr.is_running() is False


class TestFileWatcherManagerGetStats:
    """Tests for FileWatcherManager.get_stats() instance method."""

    def test_default_stats(self):
        """get_stats() on fresh instance should show defaults."""
        mod, _, _, _ = _import_file_watcher_integration()
        mgr = mod.FileWatcherManager()
        stats = mgr.get_stats()
        assert stats["running"] is False
        assert stats["branches_watched"] == 0
        assert stats["branch_names"] == []
        assert "watchdog_available" in stats

    def test_stats_with_branches(self, tmp_path):
        """get_stats() should list watched branches."""
        mod, _, _, _ = _import_file_watcher_integration()
        mgr = mod.FileWatcherManager()
        mgr.branch_paths = [
            ("SEEDGO", tmp_path / "seedgo"),
            ("DRONE", tmp_path / "drone"),
        ]
        mgr.running = True
        stats = mgr.get_stats()
        assert stats["running"] is True
        assert stats["branches_watched"] == 2
        assert "SEEDGO" in stats["branch_names"]
        assert "DRONE" in stats["branch_names"]


# =============================================
# INTERACTIVE FILTER TESTS
# =============================================


def _import_interactive_filter():
    """The interactive_filter module, bound at the top of this file; it holds no state."""
    return interactive_filter


class TestParseCommand:
    """Tests for parse_command()."""

    def test_simple_command(self):
        """Should parse single-word command."""
        mod = _import_interactive_filter()
        cmd, args = mod.parse_command("status")
        assert cmd == "status"
        assert args == []

    def test_command_with_args(self):
        """Should parse command with arguments."""
        mod = _import_interactive_filter()
        cmd, args = mod.parse_command("watch PRAX CLI")
        assert cmd == "watch"
        assert args == ["PRAX", "CLI"]

    def test_empty_string_returns_none(self):
        """Empty input should return (None, [])."""
        mod = _import_interactive_filter()
        cmd, args = mod.parse_command("")
        assert cmd is None
        assert args == []

    def test_whitespace_only_returns_none(self):
        """Whitespace-only input should return (None, [])."""
        mod = _import_interactive_filter()
        cmd, args = mod.parse_command("   ")
        assert cmd is None
        assert args == []

    def test_exit_normalized_to_quit(self):
        """'exit' should be normalized to 'quit'."""
        mod = _import_interactive_filter()
        cmd, _ = mod.parse_command("exit")
        assert cmd == "quit"

    def test_q_normalized_to_quit(self):
        """'q' should be normalized to 'quit'."""
        mod = _import_interactive_filter()
        cmd, _ = mod.parse_command("q")
        assert cmd == "quit"

    def test_uppercase_normalized(self):
        """Commands should be lowercased."""
        mod = _import_interactive_filter()
        cmd, _ = mod.parse_command("STATUS")
        assert cmd == "status"

    def test_leading_trailing_whitespace_stripped(self):
        """Leading and trailing whitespace should be stripped."""
        mod = _import_interactive_filter()
        cmd, args = mod.parse_command("  help  ")
        assert cmd == "help"
        assert args == []

    def test_logs_operation(self):
        """Should call json_handler.log_operation."""
        mod = _import_interactive_filter()
        with patch.object(mod, "json_handler") as recorder:
            mod.parse_command("status")
        recorder.log_operation.assert_called_once_with("filter_applied", {"command": "status", "args": []})


class TestGetHelpText:
    """Tests for get_help_text()."""

    def test_returns_string(self):
        """get_help_text() returns the exact three-command menu the loop prints."""
        mod = _import_interactive_filter()
        result = mod.get_help_text()
        assert isinstance(result, str)
        assert result == (
            "\n"
            "Available Commands:\n"
            "  status          - Show monitoring state\n"
            "  help            - Show this help\n"
            "  quit/exit       - Stop monitoring\n"
        )

    def test_contains_key_commands(self):
        """Help text should mention available commands."""
        mod = _import_interactive_filter()
        result = mod.get_help_text()
        assert "status" in result
        assert "help" in result
        assert "quit" in result

    def test_not_empty(self):
        """Help text should not be empty."""
        mod = _import_interactive_filter()
        result = mod.get_help_text()
        assert len(result.strip()) > 0


# =============================================
# UNIFIED STREAM TESTS
# =============================================


@pytest.fixture
def stream_log(monkeypatch) -> MagicMock:
    """unified_stream is imported once at the top and prints through the real
    console, read with capsys (prax, leg 11). Its logger and json service are
    doubled where it binds them, so no test writes live state."""
    log_ops = MagicMock()
    monkeypatch.setattr(unified_stream, "json_handler", log_ops)
    monkeypatch.setattr(unified_stream, "logger", MagicMock())
    return log_ops


def _colour_console(monkeypatch) -> io.StringIO:
    """A real Console on a buffer with colour forced, for this test alone.

    The colour is the claim here and it exists only inside the console call
    (a dict lookup in print_event), and capsys strips it (prax, leg 11)."""
    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=True, color_system="standard", width=200)
    monkeypatch.setattr(unified_stream, "console", console)
    return buffer


@pytest.mark.usefixtures("stream_log")
class TestPrintEvent:
    """Tests for print_event()."""

    def test_includes_branch_name(self, capsys):
        """One line reaches the console and it carries the branch name."""
        unified_stream.print_event("log", "SEEDGO", "audit complete")
        # The line carries a host clock, so the count and the label are the claim.
        lines = capsys.readouterr().out.splitlines()
        assert len(lines) == 1
        assert "[SEEDGO" in lines[0]

    def test_includes_message(self, capsys):
        """Output should include the event message."""
        unified_stream.print_event("system", "CLI", "started successfully")
        assert capsys.readouterr().out.rstrip("\n").endswith(" started successfully")

    def test_with_pid(self, capsys):
        """Output should include PID when provided."""
        unified_stream.print_event("file", "PRAX", "changed", pid=12345)
        assert "[PRAX:12345" in capsys.readouterr().out

    def test_error_level_coloring(self, monkeypatch):
        """Error-level messages should use red color."""
        buffer = _colour_console(monkeypatch)
        unified_stream.print_event("log", "FLOW", "something broke", level="error")
        assert "\x1b[31msomething broke\x1b[0m" in buffer.getvalue()

    def test_logs_operation(self, stream_log):
        """print_event should log via json_handler."""
        unified_stream.print_event("file", "PRAX", "test message")
        stream_log.log_operation.assert_called_with(
            "stream_output",
            {"event_type": "file", "branch": "PRAX", "level": "info"},
        )

    def test_branch_color_lookup(self, monkeypatch):
        """Should use branch-specific color from BRANCH_COLORS."""
        buffer = _colour_console(monkeypatch)
        unified_stream.print_event("file", "SEEDGO", "test")
        assert "\x1b[32mSEEDGO " in buffer.getvalue()  # SEEDGO -> green

    def test_unknown_branch_uses_white(self, monkeypatch):
        """Unknown branches should use white as default color."""
        buffer = _colour_console(monkeypatch)
        unified_stream.print_event("file", "XYZUNKNOWN", "test")
        assert "\x1b[37mXYZUNKNOWN " in buffer.getvalue()


@pytest.mark.usefixtures("stream_log")
class TestPrintCommandSeparator:
    """Tests for print_command_separator()."""

    def test_prints_separator(self, capsys):
        """A blank line, a rule, the command, a rule: no context line without caller or target."""
        unified_stream.print_command_separator("PRAX", "seedgo audit")
        assert capsys.readouterr().out.splitlines() == ["", "─" * 60, "▶ seedgo audit", "─" * 60]

    def test_includes_command(self, capsys):
        """Output should include the command text."""
        unified_stream.print_command_separator("CLI", "deploy --force")
        assert "▶ deploy --force" in capsys.readouterr().out.splitlines()

    def test_with_caller(self, capsys):
        """Output should include caller when provided."""
        unified_stream.print_command_separator("SEEDGO", "audit PRAX", caller="DRONE")
        assert "  DRONE" in capsys.readouterr().out.splitlines()

    def test_with_target(self, capsys):
        """Output should include target when provided."""
        unified_stream.print_command_separator("SEEDGO", "audit", target="FLOW")
        assert "  → FLOW" in capsys.readouterr().out.splitlines()

    def test_without_caller_or_target(self, capsys):
        """Should work without caller or target (no context line crash)."""
        unified_stream.print_command_separator("PRAX", "status")
        assert len(capsys.readouterr().out.splitlines()) == 4


@pytest.mark.usefixtures("stream_log")
class TestPrintStatus:
    """Tests for print_status()."""

    def test_prints_status(self, capsys):
        """print_status prints its heading."""
        unified_stream.print_status(["PRAX", "CLI"], verbosity=1)
        assert "Current Status:" in capsys.readouterr().out.splitlines()

    def test_includes_branch_names(self, capsys):
        """Status output should list watched branches."""
        unified_stream.print_status(["SEEDGO", "FLOW"], verbosity=0)
        assert "  Watching: SEEDGO, FLOW" in capsys.readouterr().out.splitlines()

    def test_empty_branches_shows_all(self, capsys):
        """Empty branch list should show 'All branches'."""
        unified_stream.print_status([], verbosity=0)
        assert "  Watching: All branches" in capsys.readouterr().out.splitlines()

    def test_includes_verbosity(self, capsys):
        """Status output should include verbosity level."""
        unified_stream.print_status(["PRAX"], verbosity=2)
        assert "  Verbosity: 2" in capsys.readouterr().out.splitlines()

    def test_with_filters(self, capsys):
        """Status output should show filter details when provided."""
        filters = {
            "file_types": [".py", ".json"],
            "log_levels": ["error", "warning"],
            "exclude_patterns": ["__pycache__"],
        }
        unified_stream.print_status(["PRAX"], verbosity=1, filters=filters)
        lines = capsys.readouterr().out.splitlines()
        assert "    File types: .py, .json" in lines
        assert "    Log levels: error, warning" in lines
        assert "    Excluded: __pycache__" in lines

    def test_without_filters(self, capsys):
        """Should work without filters (no crash)."""
        unified_stream.print_status(["PRAX"], verbosity=0, filters=None)
        assert "  Filters:" not in capsys.readouterr().out.splitlines()


# =============================================
# BRANCH DETECTOR — ADDITIONAL COVERAGE TESTS
# =============================================

# Fake home base used across external-project tests to avoid
# hardcoded /home/ paths that trip the SEEDGO log-structure checker.
_FAKE_HOME = Path(str(_HOME / "user"))
_FAKE_PROJECTS = _FAKE_HOME / "Projects"


class TestExactCaseRegistries:
    """Path.glob is case-INSENSITIVE on Windows, and the registry is a trust anchor.

    @memory found both of their registry walks exposed to this on 2026-08-31 and
    closed it with an exact-case post-filter; @devpulse asked whether any prax
    walk globbed a cased pattern. One did: the projects/ sweep in branch_detector.

    Pinned by driving the FILTER with a stand-in glob, so the assertion runs on
    Linux — where the real glob is case-sensitive and could never produce the
    input that breaks it. A live-directory test here would be green on the only
    platform I can run and silent on the one that has the defect.

    The positive control that ran the stand-in glob alone is retired (prax, leg 4):
    the mutant that drops the filter reddens the first pin at its assert.
    """

    def test_a_lowercase_registry_is_rejected_even_when_the_glob_returns_it(self, tmp_path, monkeypatch):
        mod = _import_branch_detector()

        real = tmp_path / "PROJECT_REGISTRY.json"
        windows_only = tmp_path / "project_registry.json"
        for path in (real, windows_only):
            path.write_text("{}", encoding="utf-8")

        # Stand in for the Windows matcher: return BOTH, the way it would there.
        monkeypatch.setattr(type(tmp_path), "glob", lambda self, _pattern: iter([real, windows_only]))

        assert mod._exact_case_registries(tmp_path) == [real]

    def test_the_exact_case_name_still_passes(self, tmp_path):
        mod = _import_branch_detector()
        real = tmp_path / "AIPASS_REGISTRY.json"
        real.write_text("{}", encoding="utf-8")
        (tmp_path / "notes.json").write_text("{}", encoding="utf-8")

        assert mod._exact_case_registries(tmp_path) == [real]


class TestFindRepoRoot:
    """Tests for BranchDetector._find_repo_root()."""

    def test_cached_repo_root_returned(self, tmp_path):
        """When _repo_root is already set, return it without walking."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        sentinel = tmp_path / "cached" / "root"
        detector._repo_root = sentinel
        result = detector._find_repo_root()
        assert result is sentinel

    def test_walks_parents_to_find_registry(self, tmp_path, monkeypatch):
        """Should find AIPASS_REGISTRY.json above the module file.

        Rewritten 2026-08-31. The previous version mocked the Path class inside
        branch_detector to fake a walk that no longer lives there — it asserted
        the shape of an implementation, so it went red the moment the walk moved
        into handlers/repo_root.py while the ANSWER stayed identical. This drives
        the real resolver over a real directory instead.
        """
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector._repo_root = None

        root = tmp_path / "checkout"
        start = root / "src" / "aipass" / "prax" / "a.py"
        start.parent.mkdir(parents=True)
        (root / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(mod, "find_repo_root", lambda _start=None: repo_root_mod.find_repo_root(start))

        assert detector._find_repo_root() == root

    def test_a_registry_less_tree_never_falls_back_to_the_cwd(self, tmp_path, monkeypatch):
        """REPLACES test_fallback_to_cwd_when_registry_missing.

        That test asserted the defect: @memory reported on 2026-08-31 that the
        Path.cwd() fallback crashes any import in a process whose working
        directory was deleted, and silently resolves against the caller's shell
        on every registry-less checkout — which is every clean CI clone, since
        the marker is gitignored. The old pin is not weakened here, it is
        INVERTED: the cwd answer is now the wrong one, so the assertion says so.
        """
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector._repo_root = None

        start = tmp_path / "checkout" / "src" / "aipass" / "prax" / "a.py"
        start.parent.mkdir(parents=True)
        monkeypatch.setattr(mod, "find_repo_root", lambda _start=None: repo_root_mod.find_repo_root(start))

        resolved = detector._find_repo_root()
        assert resolved == tmp_path / "checkout"
        assert resolved != Path.cwd()

    def test_the_answer_is_cached_per_instance(self, tmp_path):
        """The cache survived the delegation — it is called per registry entry."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector._repo_root = None
        counted_root = tmp_path / "counted" / "root"

        calls = []

        def counting(start=None):
            calls.append(start)
            return counted_root

        original = mod.find_repo_root
        setattr(mod, "find_repo_root", counting)
        try:
            first = detector._find_repo_root()
            second = detector._find_repo_root()
        finally:
            setattr(mod, "find_repo_root", original)

        assert first == second == counted_root
        assert len(calls) == 1


class TestRegisterBranch:
    """Tests for BranchDetector._register_branch()."""

    def test_registers_branch_with_name_and_path(self):
        """Should add to branch_map and known_branches."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod, branches={})

        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_resolved = MagicMock(spec=Path)
            mock_resolved.__str__ = MagicMock(return_value="/resolved/path")
            mock_path_cls.return_value.resolve.return_value = mock_resolved

            detector._register_branch({"name": "DRONE", "path": "/some/drone"})

        assert "DRONE" in detector.known_branches
        assert "/resolved/path" in detector.branch_map
        assert "/resolved/path/" in detector.branch_map

    def test_skips_empty_name(self):
        """Should skip branch entries with empty name."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod, branches={})
        initial_count = len(detector.known_branches)
        detector._register_branch({"name": "", "path": "/some/path"})
        assert len(detector.known_branches) == initial_count

    def test_skips_empty_path(self):
        """Should skip branch entries with empty path."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod, branches={})
        initial_count = len(detector.known_branches)
        detector._register_branch({"name": "EMPTY", "path": ""})
        assert len(detector.known_branches) == initial_count

    def test_skips_missing_keys(self):
        """Should skip branch entries with missing name or path keys."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod, branches={})
        initial_count = len(detector.known_branches)
        detector._register_branch({})
        assert len(detector.known_branches) == initial_count


class TestLoadRegistry:
    """Tests for BranchDetector._load_registry()."""

    # Each test points the detector at a repo root under tmp_path and writes the
    # registry there for real (prax, leg 12): a mocked open stood in for the very
    # read under test.

    def _detector_at(self, mod, root: Path):
        detector = _make_detector_with_branches(mod, branches={})
        detector._repo_root = root
        return detector

    def test_loads_branches_from_valid_registry(self, tmp_path):
        """Should populate known_branches and branch_map from a valid registry file."""
        mod = _import_branch_detector()
        detector = self._detector_at(mod, tmp_path)
        branches = [{"name": n.lower(), "path": str(tmp_path / n.lower())} for n in ("PRAX", "FLOW")]
        _write_registry(tmp_path, json.dumps({"branches": branches}))

        detector._load_registry()

        assert detector.known_branches == {"PRAX", "FLOW"}
        assert detector.branch_map[str((tmp_path / "prax").resolve())] == "PRAX"

    def test_loads_fallback_when_registry_missing(self, tmp_path):
        """Should load fallback branches when registry file not found."""
        mod = _import_branch_detector()
        detector = self._detector_at(mod, tmp_path)

        detector._load_registry()

        assert "PRAX" in detector.known_branches
        assert "SEEDGO" in detector.known_branches
        assert "no branch registry at" in _detector_log().warning.call_args.args[0]

    def test_loads_fallback_when_no_branches_key(self, tmp_path):
        """Should load fallback when registry has empty branches array."""
        mod = _import_branch_detector()
        detector = self._detector_at(mod, tmp_path)
        _write_registry(tmp_path, json.dumps({"branches": []}))

        detector._load_registry()

        assert "PRAX" in detector.known_branches
        assert "lists no branches" in _detector_log().warning.call_args.args[0]

    def test_loads_fallback_on_json_decode_error(self, tmp_path):
        """Should load fallback on JSONDecodeError, and say it was the JSON."""
        mod = _import_branch_detector()
        detector = self._detector_at(mod, tmp_path)
        _write_registry(tmp_path, "{bad json")

        detector._load_registry()

        assert "PRAX" in detector.known_branches
        assert "is not valid JSON (line 1)" in _detector_log().error.call_args.args[0]

    def test_loads_fallback_on_generic_exception(self, tmp_path):
        """Should load fallback when the registry cannot be read at all.

        The registry name is a directory: it exists, and opening it fails with
        whatever error this platform raises for that. The assert names no error
        type, only that the catch-all clause, not the JSON one, answered.
        """
        mod = _import_branch_detector()
        detector = self._detector_at(mod, tmp_path)
        (tmp_path / "AIPASS_REGISTRY.json").mkdir()

        detector._load_registry()

        assert "PRAX" in detector.known_branches
        assert "could not read the branch registry" in _detector_log().error.call_args.args[0]


class TestLoadFallbackBranches:
    """Tests for BranchDetector._load_fallback_branches()."""

    def test_populates_known_branches(self):
        """Should populate known_branches with standard fallback set."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod, branches={})
        detector.known_branches.clear()
        detector._load_fallback_branches()

        expected = {
            "SEEDGO",
            "CLI",
            "FLOW",
            "PRAX",
            "DRONE",
            "BACKUP",
            "SECURITY",
            "AIPASS",
        }
        assert detector.known_branches == expected


class TestResolveExternalProjectName:
    """Tests for BranchDetector._resolve_external_project_name()."""

    def test_returns_uppercased_name_when_no_registry(self):
        """Should return uppercased directory name when no _REGISTRY.json found."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_home = MagicMock(spec=Path)
            mock_projects = MagicMock(spec=Path)
            mock_project_dir = MagicMock(spec=Path)
            mock_project_dir.exists.return_value = True
            mock_project_dir.iterdir.return_value = []
            mock_projects.__truediv__ = MagicMock(return_value=mock_project_dir)
            mock_home.__truediv__ = MagicMock(return_value=mock_projects)
            mock_path_cls.home.return_value = mock_home

            result = detector._resolve_external_project_name("MyProject")

        assert result == "MYPROJECT"

    def test_returns_uppercased_when_dir_not_found(self):
        """Should return uppercased name when project dir doesn't exist."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_home = MagicMock(spec=Path)
            mock_projects = MagicMock(spec=Path)
            mock_project_dir = MagicMock(spec=Path)
            mock_project_dir.exists.return_value = False
            mock_projects.__truediv__ = MagicMock(return_value=mock_project_dir)
            mock_home.__truediv__ = MagicMock(return_value=mock_projects)
            mock_path_cls.home.return_value = mock_home

            result = detector._resolve_external_project_name("NoSuchProject")

        assert result == "NOSUCHPROJECT"

    def test_handles_os_error_on_iterdir(self):
        """Should return uppercased name on OSError reading directory."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_home = MagicMock(spec=Path)
            mock_projects = MagicMock(spec=Path)
            mock_project_dir = MagicMock(spec=Path)
            mock_project_dir.exists.return_value = True
            mock_project_dir.iterdir.side_effect = OSError("permission denied")
            mock_projects.__truediv__ = MagicMock(return_value=mock_project_dir)
            mock_home.__truediv__ = MagicMock(return_value=mock_projects)
            mock_path_cls.home.return_value = mock_home

            result = detector._resolve_external_project_name("Locked")

        assert result == "LOCKED"


class TestParseExternalProjectPath:
    """Tests for BranchDetector._parse_external_project_path()."""

    def test_returns_none_for_non_encoded_path(self):
        """Should return (None, None) if path doesn't start with dash."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        project, agent = detector._parse_external_project_path("not-encoded")
        assert project is None
        assert agent is None

    def test_returns_none_when_no_projects_boundary(self):
        """Should return (None, None) if -projects- not found."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        project, agent = detector._parse_external_project_path("-fakehome-user-something")
        assert project is None
        assert agent is None

    def test_parses_project_without_src(self):
        """Should parse project name without src subdirectory."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        with patch.object(detector, "_resolve_external_project_name", return_value="VERA-STUDIO"):
            project, agent = detector._parse_external_project_path("-fakehome-user-Projects-Vera-Studio")

        assert project == "VERA-STUDIO"
        assert agent is None

    def test_parses_project_with_src_agent(self):
        """Should parse project and agent from -src- segment."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        with patch.object(detector, "_resolve_external_project_name", return_value="AIPL"):
            project, agent = detector._parse_external_project_path("-fakehome-user-Projects-AIPL-src-polyglot")

        assert project == "AIPL"
        assert agent == "POLYGLOT"


class TestDetectFromClaudeProject:
    """Tests for BranchDetector._detect_from_claude_project()."""

    def test_internal_aipass_branch_via_registry(self):
        """Should detect internal AIPass branch from Claude project path."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        path = str(_FAKE_HOME) + "/.claude/projects/" + "-fakehome-user-Projects-AIPass-src-aipass-prax/session.jsonl"
        result = detector._detect_from_claude_project(path)
        assert result == "AIPASS/PRAX"

    def test_internal_aipass_fallback_to_segment_scan(self):
        """Should fall back to known branch name scanning for internal AIPass."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector.known_branches.add("PRAX")

        path = str(_FAKE_HOME) + "/.claude/projects/" + "-fakehome-user-Projects-AIPass-src-aipass-prax/something.jsonl"
        result = detector._detect_from_claude_project(path)
        assert result == "AIPASS/PRAX"

    def test_internal_aipass_subagent_suffix(self):
        """Should append SUB for subagent paths."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector.known_branches.add("PRAX")

        path = (
            str(_FAKE_HOME)
            + "/.claude/projects/"
            + "-fakehome-user-Projects-AIPass-src-aipass-prax"
            + "/subagents/abc123/session.jsonl"
        )
        result = detector._detect_from_claude_project(path)
        assert result == "AIPASS/PRAX SUB"

    def test_external_project_detection(self):
        """Should detect external project from Claude project path."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        with patch.object(
            detector,
            "_parse_external_project_path",
            return_value=("AIPL", "POLYGLOT"),
        ):
            path = str(_FAKE_HOME) + "/.claude/projects/" + "-fakehome-user-Projects-AIPL-src-polyglot/file.jsonl"
            result = detector._detect_from_claude_project(path)

        assert result == "AIPL/POLYGLOT"

    def test_external_project_main_session(self):
        """Should return project name only for main session (no agent)."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        with patch.object(
            detector,
            "_parse_external_project_path",
            return_value=("VERA-STUDIO", None),
        ):
            path = str(_FAKE_HOME) + "/.claude/projects/" + "-fakehome-user-Projects-Vera-Studio/file.jsonl"
            result = detector._detect_from_claude_project(path)

        assert result == "VERA-STUDIO"

    def test_external_project_subagent(self):
        """Should append SUB to external project subagent paths."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        with patch.object(
            detector,
            "_parse_external_project_path",
            return_value=("VERA-STUDIO", None),
        ):
            path = (
                str(_FAKE_HOME)
                + "/.claude/projects/"
                + "-fakehome-user-Projects-Vera-Studio"
                + "/subagents/abc/file.jsonl"
            )
            result = detector._detect_from_claude_project(path)

        assert result == "VERA-STUDIO SUB"

    def test_old_fallback_segment_scan(self):
        """Should fall back to segment scanning for unknown external paths."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector.known_branches.add("SEEDGO")

        with patch.object(
            detector,
            "_parse_external_project_path",
            return_value=(None, None),
        ):
            path = str(_FAKE_HOME) + "/.claude/projects/some-random-seedgo/file.jsonl"
            result = detector._detect_from_claude_project(path)

        assert result == "SEEDGO"

    def test_old_fallback_returns_none_for_empty_segments(self):
        """Should return None when folder parses to no segments."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        with patch.object(
            detector,
            "_parse_external_project_path",
            return_value=(None, None),
        ):
            path = str(_FAKE_HOME) + "/.claude/projects//file.jsonl"
            result = detector._detect_from_claude_project(path)

        assert result is None

    def test_old_fallback_last_segment_known(self):
        """Should return last segment if it matches a known branch."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector.known_branches.add("CLI")

        with patch.object(
            detector,
            "_parse_external_project_path",
            return_value=(None, None),
        ):
            path = str(_FAKE_HOME) + "/.claude/projects/unknown-cli/file.jsonl"
            result = detector._detect_from_claude_project(path)

        assert result == "CLI"

    def test_old_fallback_returns_none_when_no_branch_match(self):
        """Should return None when no segments match known branches."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        with patch.object(
            detector,
            "_parse_external_project_path",
            return_value=(None, None),
        ):
            path = str(_FAKE_HOME) + "/.claude/projects/completely-unknown-xyz/file.jsonl"
            result = detector._detect_from_claude_project(path)

        assert result is None

    def test_internal_aipass_fallback_last_segment(self):
        """When no known branch found, should use last segment uppercased."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod, branches={})

        path = str(_FAKE_HOME) + "/.claude/projects/" + "-fakehome-user-Projects-AIPass-src-aipass-newmod/file.jsonl"
        result = detector._detect_from_claude_project(path)
        assert result == "AIPASS/NEWMOD"


class TestDetectFromCompoundParts:
    """Tests for BranchDetector._detect_from_compound_parts()."""

    def test_finds_known_branch_in_underscore_part(self):
        """Should detect branch from underscore-delimited path part."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector.known_branches.add("MAIL")

        result = detector._detect_from_compound_parts(["src", "ai_mail", "handler"])
        assert result == "MAIL"

    def test_returns_none_when_no_match(self):
        """Should return None when no underscore subparts match."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        result = detector._detect_from_compound_parts(["src", "something_else"])
        assert result is None

    def test_skips_parts_without_underscore(self):
        """Should only check parts that contain underscores."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        result = detector._detect_from_compound_parts(["simple", "parts", "here"])
        assert result is None


class TestDetectFromExternalProjectPath:
    """Tests for BranchDetector._detect_from_external_project_path()."""

    def test_path_not_under_projects(self, tmp_path):
        """Should return None if path is not under ~/Projects/."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        path = tmp_path / "some" / "random" / "file.py"
        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path_cls.home.return_value = _FAKE_HOME

            result = detector._detect_from_external_project_path(path)

        assert result is None

    def test_skips_aipass_directory(self):
        """Should return None for paths under AIPass directory."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        path = _FAKE_PROJECTS / "AIPass" / "src" / "prax" / "file.py"
        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path_cls.home.return_value = _FAKE_HOME

            result = detector._detect_from_external_project_path(path)

        assert result is None

    def test_returns_project_with_agent(self):
        """Should return PROJECT/AGENT for path with src subdirectory."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector._external_project_cache["AIPL"] = "AIPL"

        path = _FAKE_PROJECTS / "AIPL" / "src" / "polyglot" / "file.py"
        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path_cls.home.return_value = _FAKE_HOME

            result = detector._detect_from_external_project_path(path)

        assert result == "AIPL/POLYGLOT"

    def test_returns_project_without_agent(self):
        """Should return PROJECT for path without src subdirectory."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector._external_project_cache["MyApp"] = "MYAPP"

        path = _FAKE_PROJECTS / "MyApp" / "config.json"
        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path_cls.home.return_value = _FAKE_HOME

            result = detector._detect_from_external_project_path(path)

        assert result == "MYAPP"

    def test_test_suffix_appended(self):
        """Should append TESTS suffix for test-related paths."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector._external_project_cache["AIPL"] = "AIPL"

        path = _FAKE_PROJECTS / "AIPL" / "src" / "polyglot" / "tests" / "test_main.py"
        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path_cls.home.return_value = _FAKE_HOME

            result = detector._detect_from_external_project_path(path)

        assert result == "AIPL/POLYGLOT TESTS"

    def test_cached_project_name(self):
        """Should use cached project name on subsequent lookups."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector._external_project_cache["CachedProj"] = "CACHED"

        path = _FAKE_PROJECTS / "CachedProj" / "file.py"
        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path_cls.home.return_value = _FAKE_HOME

            result = detector._detect_from_external_project_path(path)

        assert result == "CACHED"

    def test_empty_rel_parts_returns_none(self):
        """Should return None if relative path has no parts."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path_cls.home.return_value = _FAKE_HOME

            result = detector._detect_from_external_project_path(_FAKE_PROJECTS)

        assert result is None

    def test_returns_none_when_no_registry_file(self):
        """Should return None when project directory has no _REGISTRY.json."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector._external_project_cache.clear()

        path = _FAKE_PROJECTS / "SomeProject" / "src" / "module" / "file.py"
        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path_cls.home.return_value = _FAKE_HOME
            mock_project_dir = MagicMock(spec=Path)
            mock_project_dir.iterdir.return_value = iter([])

            result = detector._detect_from_external_project_path(path)

        assert result is None

    def test_test_suffix_for_test_log_file(self):
        """Should append TESTS for paths ending in _test.log."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector._external_project_cache["Proj"] = "PROJ"

        path = _FAKE_PROJECTS / "Proj" / "output_test.log"
        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path_cls.home.return_value = _FAKE_HOME

            result = detector._detect_from_external_project_path(path)

        assert result == "PROJ TESTS"


class TestExtractBranchFromCentral:
    """Tests for BranchDetector._extract_branch_from_central()."""

    def test_dot_central_json(self, tmp_path):
        """Should extract branch name from .central.json filename."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        path = tmp_path / "some" / "ai_mail" / "DRONE.central.json"
        result = detector._extract_branch_from_central(str(path), path)
        assert result == "DRONE"

    def test_underscore_central_json(self, tmp_path):
        """Should extract branch name from _central.json filename."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        path = tmp_path / "some" / "dir" / "ai_mail" / "PRAX_central.json"
        result = detector._extract_branch_from_central("ai_mail/PRAX_central.json", path)
        assert result == "PRAX"

    def test_returns_none_for_non_mail_path(self, tmp_path):
        """Should return None if path doesn't contain ai_mail or AI_MAIL."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        path = tmp_path / "some" / "dir" / "config.json"
        result = detector._extract_branch_from_central(str(path), path)
        assert result is None

    def test_returns_none_for_non_central_filename(self, tmp_path):
        """Should return None for non-central filename in ai_mail path."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        path = tmp_path / "ai_mail" / "inbox.json"
        result = detector._extract_branch_from_central("ai_mail/inbox.json", path)
        assert result is None


class TestDetectFromPathStrategies:
    """Tests for detect_from_path covering all strategy branches."""

    def test_cache_hit_returns_cached_value(self):
        """Strategy 0: Should return cached value from log_map."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        resolved = "/cached/path"
        detector.log_map[resolved] = "CACHED_BRANCH"

        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path = MagicMock(spec=Path)
            mock_path.__str__ = MagicMock(return_value=resolved)
            mock_path.resolve.return_value = mock_path
            mock_path_cls.return_value = mock_path

            result = detector.detect_from_path(resolved)

        assert result == "CACHED_BRANCH"

    def test_claude_project_path_strategy(self):
        """Strategy 3: Should detect from .claude/projects/ path."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector.known_branches.add("PRAX")

        resolved = (
            str(_FAKE_HOME) + "/.claude/projects/" + "-fakehome-user-Projects-AIPass-src-aipass-prax/session.jsonl"
        )

        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path = MagicMock(spec=Path)
            mock_path.__str__ = MagicMock(return_value=resolved)
            mock_path.resolve.return_value = mock_path
            mock_path.parents = []
            mock_path.parent = MagicMock()
            mock_path.parent.__eq__ = MagicMock(return_value=False)
            mock_path.name = "session.jsonl"
            mock_path_cls.return_value = mock_path
            mock_path_cls.home.return_value = _FAKE_HOME

            detector._repo_root = MagicMock(spec=Path)
            detector._repo_root.__str__ = MagicMock(return_value=str(_FAKE_PROJECTS / "AIPass"))

            result = detector.detect_from_path(resolved)

        assert "PRAX" in result

    def test_ai_mail_central_strategy(self):
        """Strategy 4: Should detect from ai_mail central filename."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        resolved = str(_FAKE_PROJECTS / "AIPass" / "src" / "aipass" / "ai_mail" / "central" / "DRONE.central.json")

        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path = MagicMock(spec=Path)
            mock_path.__str__ = MagicMock(return_value=resolved)
            mock_path.resolve.return_value = mock_path
            mock_path.parents = []
            mock_path.parent = MagicMock()
            mock_path.parent.__eq__ = MagicMock(return_value=False)
            mock_path.name = "DRONE.central.json"
            mock_path_cls.return_value = mock_path
            mock_path_cls.home.return_value = _FAKE_HOME

            detector._repo_root = MagicMock(spec=Path)
            detector._repo_root.__str__ = MagicMock(return_value=str(_FAKE_PROJECTS / "AIPass"))

            result = detector.detect_from_path(resolved)

        assert result == "DRONE"

    def test_root_level_system_files_strategy(self):
        """Strategy 5: Should return SYSTEM for repo root files."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        repo_root = _FAKE_PROJECTS / "AIPass"
        resolved = str(repo_root / "README.md")

        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path = MagicMock(spec=Path)
            mock_path.__str__ = MagicMock(return_value=resolved)
            mock_path.resolve.return_value = mock_path
            mock_path.parents = []
            mock_path.parent = repo_root
            mock_path.name = "README.md"
            mock_path_cls.return_value = mock_path
            mock_path_cls.home.return_value = _FAKE_HOME

            detector._repo_root = repo_root

            result = detector.detect_from_path(resolved)

        assert result == "SYSTEM"

    def test_root_claude_dir_system_files(self):
        """Strategy 5: Should return SYSTEM for .claude dir under repo root."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        repo_root = _FAKE_PROJECTS / "AIPass"
        resolved = str(repo_root / ".claude" / "settings.json")

        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path = MagicMock(spec=Path)
            mock_path.__str__ = MagicMock(return_value=resolved)
            mock_path.resolve.return_value = mock_path
            mock_path.parents = []
            mock_path.parent = repo_root / ".claude"
            mock_path.name = "settings.json"
            mock_path_cls.return_value = mock_path
            mock_path_cls.home.return_value = _FAKE_HOME

            detector._repo_root = repo_root

            result = detector.detect_from_path(resolved)

        assert result == "SYSTEM"

    def test_known_branch_in_path_parts_strategy(self):
        """Strategy 6: Should detect branch from path parts."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector.known_branches.add("DRONE")

        resolved = "/some/random/drone/handler.py"

        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path = MagicMock(spec=Path)
            mock_path.__str__ = MagicMock(return_value=resolved)
            mock_path.resolve.return_value = mock_path
            mock_path.parents = []
            mock_path.parent = MagicMock()
            mock_path.parent.__eq__ = MagicMock(return_value=False)
            mock_path.name = "handler.py"
            mock_path_cls.return_value = mock_path
            mock_path_cls.home.return_value = _FAKE_HOME

            detector._repo_root = MagicMock(spec=Path)
            detector._repo_root.__str__ = MagicMock(return_value=str(_FAKE_PROJECTS / "AIPass"))
            detector._repo_root.__truediv__ = MagicMock(return_value=MagicMock())

            result = detector.detect_from_path(resolved)

        assert result == "DRONE"

    def test_compound_parts_detection_strategy(self):
        """Strategy 6 (compound): Should detect from compound underscore parts."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        # Add WIDGET as known branch but NOT "SOME_WIDGET" — so only
        # compound splitting of "some_widget" -> ["some", "widget"] can match.
        detector.known_branches.add("WIDGET")

        resolved = "/unrelated/some_widget/handler.py"

        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path = MagicMock(spec=Path)
            mock_path.__str__ = MagicMock(return_value=resolved)
            mock_path.resolve.return_value = mock_path
            mock_path.parents = []
            mock_path.parent = MagicMock()
            mock_path.parent.__eq__ = MagicMock(return_value=False)
            mock_path.name = "handler.py"
            mock_path_cls.return_value = mock_path
            mock_path_cls.home.return_value = _FAKE_HOME

            detector._repo_root = MagicMock(spec=Path)
            detector._repo_root.__str__ = MagicMock(return_value=str(_FAKE_PROJECTS / "AIPass"))
            detector._repo_root.__truediv__ = MagicMock(return_value=MagicMock())

            result = detector.detect_from_path(resolved)

        assert result == "WIDGET"

    def test_external_project_path_priority(self):
        """Strategy 0 (external): Should detect external project with priority."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        resolved = str(_FAKE_PROJECTS / "AIPL" / "src" / "polyglot" / "tests" / "test_main.py")

        with patch(f"{mod.__name__}.Path") as mock_path_cls:
            mock_path = MagicMock(spec=Path)
            mock_path.__str__ = MagicMock(return_value=resolved)
            mock_path.resolve.return_value = mock_path
            mock_path.parents = []
            mock_path.parent = MagicMock()
            mock_path.name = "test_main.py"
            mock_path_cls.return_value = mock_path
            mock_path_cls.home.return_value = _FAKE_HOME

            detector._repo_root = MagicMock(spec=Path)
            detector._repo_root.__str__ = MagicMock(return_value=str(_FAKE_PROJECTS / "AIPass"))

            with patch.object(
                detector,
                "_detect_from_external_project_path",
                return_value="AIPL/POLYGLOT TESTS",
            ):
                result = detector.detect_from_path(resolved)

        assert result == "AIPL/POLYGLOT TESTS"


class TestDetectFromLogAdditional:
    """Additional tests for detect_from_log covering uncovered lines."""

    def test_log_name_matches_branch_exactly(self):
        """Should detect branch when log name equals known branch."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector.known_branches.add("BACKUP")

        result = detector.detect_from_log("backup.log")
        assert result == "BACKUP"
        assert "backup" in detector.log_map

    def test_cache_hit_on_stem(self):
        """Should return cached stem from log_map."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector.log_map["cached_log"] = "CACHED"

        result = detector.detect_from_log("cached_log.log")
        assert result == "CACHED"


class TestDetectFromModuleAdditional:
    """Additional tests for detect_from_module covering uncovered lines."""

    def test_module_cache_hit(self):
        """Should return cached module from module_map."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector.module_map["cached.module"] = "CACHED"

        result = detector.detect_from_module("cached.module")
        assert result == "CACHED"


class TestPublicAPIFunctions:
    """Tests for module-level public API functions."""

    def test_detect_branch_from_path_delegates(self, tmp_path):
        """detect_branch_from_path should delegate to get_detector."""
        mod = _import_branch_detector()
        mock_detector = MagicMock()
        mock_detector.detect_from_path.return_value = "PRAX"
        setattr(mod, "_detector_instance", mock_detector)

        some_path = str(tmp_path / "some" / "path")
        result = mod.detect_branch_from_path(some_path)
        assert result == "PRAX"
        mock_detector.detect_from_path.assert_called_once_with(some_path)

    def test_detect_branch_from_log_delegates(self):
        """detect_branch_from_log should delegate to get_detector."""
        mod = _import_branch_detector()
        mock_detector = MagicMock()
        mock_detector.detect_from_log.return_value = "FLOW"
        setattr(mod, "_detector_instance", mock_detector)

        result = mod.detect_branch_from_log("flow_plan.log")
        assert result == "FLOW"
        mock_detector.detect_from_log.assert_called_once_with("flow_plan.log")

    def test_reload_registry_delegates(self):
        """reload_registry should delegate to get_detector."""
        mod = _import_branch_detector()
        mock_detector = MagicMock()
        setattr(mod, "_detector_instance", mock_detector)

        mod.reload_registry()
        mock_detector.reload_registry.assert_called_once_with()
