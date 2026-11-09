# =================== AIPass ====================
# Name: test_monitoring_handlers_external_project.py
# Description: Unit tests for the branch detector's external project and path strategies
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-11-08
# =============================================

"""Tests for apps/handlers/monitoring/branch_detector.py, its external project detection and path strategies."""

# Covers:
# - BranchDetector: _detect_from_claude_project, _detect_from_compound_parts, _extract_branch_from_central,
#   detect_from_path strategies, detect_from_log caches
# - branch_detector: detect_branch_from_path, detect_branch_from_log

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(through_the_command) — _load_registry, covered by tests/test_monitoring_handlers.py

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
# hardcoded /home/ paths that trip the SENTRY log-structure checker.
_FAKE_HOME = Path(str(_HOME / "user"))
_FAKE_PROJECTS = _FAKE_HOME / "Projects"


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

    def test_a_folder_encoding_a_cwd_inside_a_declared_row_names_that_row(self):
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod, branches={str(_FAKE_HOME / "seed" / "grow"): "GROW"})

        path = str(_FAKE_HOME) + "/.claude/projects/" + "-ws-user-seed-grow-apps/file.jsonl"
        assert detector._detect_from_claude_project(path) == "GROW"

    def test_the_deepest_row_wins_and_a_subagent_gets_sub(self):
        mod = _import_branch_detector()
        branches = {str(_FAKE_HOME / "seed"): "SEED", str(_FAKE_HOME / "seed" / "grow"): "GROW"}
        detector = _make_detector_with_branches(mod, branches=branches)

        path = str(_FAKE_HOME) + "/.claude/projects/" + "-ws-user-seed-grow/subagents/abc/file.jsonl"
        assert detector._detect_from_claude_project(path) == "GROW SUB"

    def test_a_folder_under_no_declared_row_gets_no_project_label(self):
        """The ~/Projects walk is gone: a project-shaped folder no row declares is not labelled."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        path = str(_FAKE_HOME) + "/.claude/projects/" + "-ws-user-Projects-Vera-Studio/file.jsonl"
        assert detector._detect_from_claude_project(path) is None

    def test_old_fallback_segment_scan(self):
        """Should fall back to segment scanning for unknown external paths."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector.known_branches.add("SENTRY")

        path = str(_FAKE_HOME) + "/.claude/projects/some-random-sentry/file.jsonl"
        result = detector._detect_from_claude_project(path)

        assert result == "SENTRY"

    def test_old_fallback_returns_none_for_empty_segments(self):
        """Should return None when folder parses to no segments."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

        path = str(_FAKE_HOME) + "/.claude/projects//file.jsonl"
        result = detector._detect_from_claude_project(path)

        assert result is None

    def test_old_fallback_last_segment_known(self):
        """Should return last segment if it matches a known branch."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)
        detector.known_branches.add("CLI")

        path = str(_FAKE_HOME) + "/.claude/projects/unknown-cli/file.jsonl"
        result = detector._detect_from_claude_project(path)

        assert result == "CLI"

    def test_old_fallback_returns_none_when_no_branch_match(self):
        """Should return None when no segments match known branches."""
        mod = _import_branch_detector()
        detector = _make_detector_with_branches(mod)

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
