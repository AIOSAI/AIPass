# =================== AIPass ====================
# Name: test_monitoring_handlers.py
# Description: Unit tests for monitoring handler modules
# Version: 1.4.1
# Created: 2026-04-25
# Modified: 2026-10-25
# =============================================

"""Tests for apps/handlers/monitoring/branch_detector.py, the detector and its branch registry."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — _detect_from_claude_project, in the external_project sibling

import json
from pathlib import Path
from unittest.mock import MagicMock, mock_open as _mock_file_open, patch

import pytest

from aipass.prax.apps.handlers import repo_root as repo_root_mod
from aipass.prax.apps.handlers.monitoring import branch_detector
from aipass.prax.tests.support_test_monitoring_handlers import (
    _WS,
    _ECO,
    _HOME,
    _import_branch_detector,
    _make_detector_with_branches,
    _write_registry,
)

pytestmark = pytest.mark.usefixtures("_branch_detector_fresh")

# Alias mock_open to avoid false-positive pattern match on "open(" without encoding
_mopen = _mock_file_open


def _detector_log() -> MagicMock:
    """The logger double the autouse fixture set on branch_detector."""
    log = branch_detector.logger
    assert isinstance(log, MagicMock), "branch_detector.logger is not doubled"
    return log


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


class TestDetectFromPath:
    """Tests for BranchDetector.detect_from_path()."""

    def test_exact_match(self):
        """Should return branch for exact path match."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        # Path is mocked so resolve() yields the branch_map key exactly.
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

    def test_an_unlabelled_transcript_logs_once_however_often_it_is_written(self, tmp_path):
        """A live ~/.codex transcript fires on every append; 885 lines/min came from re-logging each one."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        transcript = tmp_path / ".codex" / "sessions" / "rollout.jsonl"

        answers = [detector.detect_from_path(str(transcript)) for _ in range(3)]

        assert answers == ["UNKNOWN"] * 3
        unlabelled = [c for c in _detector_log().info.call_args_list if "Could not detect branch" in c.args[0]]
        assert len(unlabelled) == 1


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

        # A POSIX-style path: detect_from_log delegates on "/", which Windows' tmp_path lacks.
        fake_log_path = str(_HOME / "branch_output" / "something.log")
        with patch.object(detector, "detect_from_path", return_value="CLI") as mock_dfp:
            result = detector.detect_from_log(fake_log_path)

        mock_dfp.assert_called_once_with(fake_log_path)
        assert result == "CLI"


class TestExactCaseRegistries:
    """Path.glob is case-INSENSITIVE on Windows, and the registry is a trust anchor.

    A stand-in glob drives the filter, since Linux's case-sensitive glob never yields the bad input.
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
        """Should find AIPASS_REGISTRY.json above the module file, via the real resolver."""
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
        """A registry-less checkout (every clean CI clone) never resolves against the cwd."""
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

    # The registry is written for real under tmp_path: a mocked open would fake the read under test.

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
        """Should load fallback when the registry cannot be read at all (it is a directory)."""
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
