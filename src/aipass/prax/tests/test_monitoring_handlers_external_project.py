# =================== AIPass ====================
# Name: test_monitoring_handlers_external_project.py
# Description: Unit tests for the branch detector's external project and path strategies
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/monitoring/branch_detector.py, its external project detection and path strategies."""

# Covers:
# - BranchDetector: _resolve_external_project_name, _parse_external_project_path,
#   _detect_from_claude_project, _detect_from_compound_parts,
#   _detect_from_external_project_path, _extract_branch_from_central,
#   detect_from_path strategies, detect_from_log and detect_from_module caches
# - branch_detector: detect_branch_from_path, detect_branch_from_log, reload_registry

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — _load_registry, covered by tests/test_monitoring_handlers.py

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.prax.tests.support_test_monitoring_handlers import (
    _HOME,
    _import_branch_detector,
    _make_detector_with_branches,
)

pytestmark = pytest.mark.usefixtures("_branch_detector_fresh")

# Fake home base used across external-project tests to avoid
# hardcoded /home/ paths that trip the SEEDGO log-structure checker.
_FAKE_HOME = Path(str(_HOME / "user"))
_FAKE_PROJECTS = _FAKE_HOME / "Projects"


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
