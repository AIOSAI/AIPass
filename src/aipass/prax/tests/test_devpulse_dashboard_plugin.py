# =================== AIPass ====================
# Name: test_devpulse_dashboard_plugin.py
# Description: Tests for devpulse dashboard plugin
# Version: 1.4.0
# Created: 2026-05-16
# Modified: 2026-10-24
# =============================================

"""Tests for apps/plugins/devpulse_dashboard/git_section.py, dispatch_section.py and refresh.py."""

# Tests for devpulse dashboard plugin (git, session, dispatch sections + refresh).

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — the builders' write_section, covered by tests/test_operations.py
# seedgo: no-test-needed(ruff) — that __init__.py's __all__ re-export of refresh names a real import (F822)
# seedgo: no-test-needed(log_level) — the lines each builder logs on a failure, covered by that row

import json
import os
from unittest.mock import patch, MagicMock

import pytest

from aipass.prax.apps.handlers.dashboard import operations
from aipass.prax.apps.plugins.devpulse_dashboard import dispatch_section
from aipass.prax.apps.plugins.devpulse_dashboard import git_section as dashboard_git_section
from aipass.prax.apps.plugins.devpulse_dashboard.dispatch_section import build_dispatch_section
from aipass.prax.apps.plugins.devpulse_dashboard.git_section import build_git_section
from aipass.prax.apps.plugins.devpulse_dashboard.refresh import DEVPULSE_PATH, refresh


def _glance(mock_run, branch, subject_stdout):
    """The last_commit_msg build_git_section writes when git's subject reads ``subject_stdout``.

    Through the section builder, not its private _subject_line (prax, leg 7).
    """

    def _responses(cmd, **kwargs):
        result = _git_subprocess_responses(cmd, **kwargs)
        if tuple(cmd[1:]) == ("log", "-1", "--format=%s"):
            result.stdout = subject_stdout
        return result

    mock_run.side_effect = _responses
    assert dashboard_git_section.build_git_section(branch) is True
    dash = json.loads((branch / "DASHBOARD.local.json").read_text(encoding="utf-8"))
    return dash["sections"]["git"]["last_commit_msg"]


def _git_subprocess_responses(cmd, **kwargs):
    """Mock subprocess.run responses for git commands."""
    result = MagicMock()
    result.returncode = 0
    args = cmd[1:]  # strip 'git'
    responses = {
        ("rev-parse", "--abbrev-ref", "HEAD"): "dev\n",
        ("status", "--porcelain"): " M file1.py\n M file2.py\n",
        ("rev-list", "--count", "origin/main..HEAD"): "5\n",
        ("log", "-1", "--format=%s"): "feat: add dashboard plugin\n",
        ("log", "-1", "--format=%cs"): "2026-05-16\n",
    }
    result.stdout = responses.get(tuple(args), "")
    return result


@pytest.fixture
def branch_path(tmp_path):
    """Create a minimal branch directory structure."""
    (tmp_path / "DASHBOARD.local.json").write_text(
        json.dumps(
            {
                "_warning": "AUTO-GENERATED",
                "branch": "DEVPULSE",
                "last_updated": "",
                "quick_status": {"action_required": False},
                "sections": {},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def branch_with_trinity(branch_path):
    """Branch path with .trinity/local.json."""
    trinity = branch_path / ".trinity"
    trinity.mkdir()
    local_data = {
        "sessions": [{"id": "S162", "d": "2026-05-16", "sum": "Test session summary", "st": "+"}],
        "active_tasks": {
            "today_focus": "Testing the plugin",
            "pending": ["Task 1", "Task 2"],
            "recently_completed": [],
        },
    }
    (trinity / "local.json").write_text(json.dumps(local_data), encoding="utf-8")
    return branch_path


@pytest.fixture
def branch_with_git(branch_path):
    """Branch path inside a fake git repo."""
    (branch_path / ".git").mkdir()
    return branch_path


class TestGitSection:
    """Tests for git_section.py."""

    @patch("aipass.prax.apps.plugins.devpulse_dashboard.git_section.subprocess.run")
    def test_build_git_section_success(self, mock_run, branch_with_git):
        """Test successful git section build with mocked subprocess."""

        mock_run.side_effect = _git_subprocess_responses
        result = build_git_section(branch_with_git)
        assert result is True

        # Verify dashboard was written
        dash = json.loads((branch_with_git / "DASHBOARD.local.json").read_text(encoding="utf-8"))
        git = dash["sections"]["git"]
        assert git["managed_by"] == "devpulse"
        assert git["branch"] == "dev"
        assert git["files_changed"] == 2
        assert git["ahead_of_main"] == 5
        assert git["last_commit_msg"] == "feat: add dashboard plugin"
        assert git["last_commit_date"] == "2026-05-16"

    @patch("aipass.prax.apps.plugins.devpulse_dashboard.git_section.subprocess.run")
    def test_essay_subject_is_capped_to_one_glance(self, mock_run, branch_with_git):
        """A 3 KB one-line subject (the essay era) lands as its first SUBJECT_CAP chars."""
        essay = "fix(memory): " + "why " * 800

        msg = _glance(mock_run, branch_with_git, essay + "\n")

        cap = dashboard_git_section.SUBJECT_CAP
        assert cap - 4 < len(msg) <= cap
        assert msg.startswith("fix(memory): why")
        assert msg.endswith("...")

    @patch("aipass.prax.apps.plugins.devpulse_dashboard.git_section.subprocess.run")
    def test_subject_line_keeps_short_subjects_and_drops_the_body(self, mock_run, branch_with_git):
        """Short subjects pass through untouched; a body under the subject never reaches the glance."""
        assert _glance(mock_run, branch_with_git, "feat(x): short\n") == "feat(x): short"
        assert _glance(mock_run, branch_with_git, "feat(x): short\n\nWHY: the essay lives here\n") == "feat(x): short"
        assert _glance(mock_run, branch_with_git, "   \n") == ""

    @patch("aipass.prax.apps.plugins.devpulse_dashboard.git_section.subprocess.run")
    def test_the_plugin_reads_the_shared_cap_instead_of_its_own(self, mock_run, branch_with_git):
        """A commit subject and a plan subject are the same glance — one number (DPLAN-0347)."""

        assert dashboard_git_section.SUBJECT_CAP is operations.SUBJECT_CAP
        assert _glance(mock_run, branch_with_git, "x" * 500) == operations.cap_subject("x" * 500)

    @patch("aipass.prax.apps.plugins.devpulse_dashboard.git_section.subprocess.run")
    def test_build_git_section_subprocess_failure(self, mock_run, branch_with_git):
        """Test git section handles subprocess failures gracefully."""

        mock_run.side_effect = OSError("git not found")
        # Should not raise — handles errors internally
        result = build_git_section(branch_with_git)
        # Still writes section with empty/default values
        assert result is True

    @staticmethod
    def _section_with(branch, failing):
        """The git section written when the git reads named in ``failing`` fail.

        The runner is handed in at build_git_section's seam, so no subprocess is
        patched (prax, leg 16). A failed read answers None and records its
        reason the way _run_git does.
        """
        answers = {
            ("rev-parse", "--abbrev-ref", "HEAD"): "dev",
            ("status", "--porcelain"): "M file1.py\n M file2.py",
            ("rev-list", "--count", "origin/main..HEAD"): "5",
            ("log", "-1", "--format=%s"): "feat: add dashboard plugin",
            ("log", "-1", "--format=%cs"): "2026-05-16",
        }

        def stand_in(repo_root, *args, errors=None):
            if args in failing:
                if errors is not None:
                    errors.append(f"git {' '.join(args)}: exit 128: stand-in failure")
                return None
            return answers[args]

        assert build_git_section(branch, run_git=stand_in) is True
        return json.loads((branch / "DASHBOARD.local.json").read_text(encoding="utf-8"))["sections"]["git"]

    def test_every_read_answered_writes_ints_and_no_error(self, branch_with_git):
        git = self._section_with(branch_with_git, failing=())
        assert "error" not in git
        assert git["branch"] == "dev"
        assert git["files_changed"] == 2
        assert git["ahead_of_main"] == 5
        assert git["last_commit_msg"] == "feat: add dashboard plugin"
        assert git["last_commit_date"] == "2026-05-16"

    def test_one_failed_read_is_null_and_named_and_the_rest_intact(self, branch_with_git):
        """A failed status read used to be written as files_changed 0 (prax, leg 16)."""
        git = self._section_with(branch_with_git, failing=(("status", "--porcelain"),))
        assert git["files_changed"] is None
        assert git.get("error") == "git status --porcelain: exit 128: stand-in failure"
        assert git["branch"] == "dev"
        assert git["ahead_of_main"] == 5
        assert git["last_commit_msg"] == "feat: add dashboard plugin"
        assert git["last_commit_date"] == "2026-05-16"

    def test_every_read_failed_is_all_null_and_names_the_first(self, branch_with_git):
        """Every read failing used to write unknown, 0, 0, '' and '' as the card (prax, leg 16)."""
        failing = (
            ("rev-parse", "--abbrev-ref", "HEAD"),
            ("status", "--porcelain"),
            ("rev-list", "--count", "origin/main..HEAD"),
            ("log", "-1", "--format=%s"),
            ("log", "-1", "--format=%cs"),
        )
        git = self._section_with(branch_with_git, failing=failing)
        assert git["branch"] is None
        assert git["files_changed"] is None
        assert git["ahead_of_main"] is None
        assert git["last_commit_msg"] is None
        assert git["last_commit_date"] is None
        assert git.get("error") == "git rev-parse --abbrev-ref HEAD: exit 128: stand-in failure"

    def test_the_real_runner_answers_null_where_git_cannot_read(self, branch_with_git):
        """The default runner against a .git directory with nothing in it.

        Git refuses it (or is absent, which fails the same way), so every read
        fails. The old runner answered '' there and the card read unknown, 0,
        0, '' and '' (prax, leg 16).
        """
        assert build_git_section(branch_with_git) is True
        git = json.loads((branch_with_git / "DASHBOARD.local.json").read_text(encoding="utf-8"))["sections"]["git"]
        assert git["branch"] is None
        assert git["files_changed"] is None
        assert git["ahead_of_main"] is None
        assert git["last_commit_msg"] is None
        assert git["last_commit_date"] is None
        assert git["error"].startswith("git rev-parse --abbrev-ref HEAD: ")

    @patch("aipass.prax.apps.plugins.devpulse_dashboard.git_section._find_git_root")
    def test_build_git_section_no_git_dir(self, mock_find_root, branch_path):
        """Test git section when no .git directory exists."""

        mock_find_root.side_effect = FileNotFoundError("No .git found above " + str(branch_path))
        with pytest.raises(FileNotFoundError):
            build_git_section(branch_path)


class TestDispatchSection:
    """Tests for dispatch_section.py: branches come from the registry, locks in ai_mail's shape."""

    @pytest.fixture(autouse=True)
    def _registry(self, branch_path, monkeypatch):
        """Registered branches are siblings of branch_path, named the way the registry lists them."""
        parent = branch_path.parent
        self.branches = {name: parent / name for name in ("ai_mail", "prax", "seedgo", "daemon")}
        for path in self.branches.values():
            (path / ".ai_mail.local").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(dispatch_section, "get_branch_paths", lambda: list(self.branches.values()))

    def _lock(self, name, data):
        text = data if isinstance(data, str) else json.dumps(data)
        (self.branches[name] / ".ai_mail.local" / ".dispatch.lock").write_text(text, encoding="utf-8")

    def _section(self, branch_path):
        assert build_dispatch_section(branch_path) is True
        dash = json.loads((branch_path / "DASHBOARD.local.json").read_text(encoding="utf-8"))
        return dash["sections"]["dispatch"]

    def test_build_dispatch_section_no_locks(self, branch_path):
        """No lock anywhere: nothing active."""
        dispatch = self._section(branch_path)
        assert dispatch["managed_by"] == "devpulse"
        assert dispatch["agents_active"] == []
        assert dispatch["agents_active_count"] == 0

    def test_a_live_lock_reports_pid_and_timestamp(self, branch_path):
        """ai_mail writes {pid, timestamp, branch}; a branch outside the old hard-coded list is seen."""
        self._lock("daemon", {"pid": os.getpid(), "timestamp": "2026-05-16T14:00:00", "branch": "/x/daemon"})

        dispatch = self._section(branch_path)

        assert dispatch["agents_active"] == ["daemon"]
        assert dispatch["details"]["daemon"] == {"pid": os.getpid(), "timestamp": "2026-05-16T14:00:00"}

    def test_a_dead_pid_lock_is_not_active(self, branch_path, monkeypatch):
        """A lock left by a process that is gone is not an active dispatch."""
        monkeypatch.setattr(dispatch_section.sys, "platform", "linux")

        def _gone(pid, sig):
            raise ProcessLookupError(pid)

        monkeypatch.setattr(dispatch_section.os, "kill", _gone)
        self._lock("prax", {"pid": 424242, "timestamp": "2026-05-16T14:00:00", "branch": "/x/prax"})

        assert self._section(branch_path)["agents_active"] == []

    def test_build_dispatch_section_corrupt_lock(self, branch_path):
        """An unparseable lock is held as mid-write, so it still counts as active."""
        self._lock("seedgo", "broken json{{{")

        dispatch = self._section(branch_path)

        assert "seedgo" in dispatch["agents_active"]
        assert dispatch["details"]["seedgo"] == {"pid": None, "timestamp": ""}


class TestRefresh:
    """Tests for refresh.py orchestrator."""

    @patch("aipass.prax.apps.plugins.devpulse_dashboard.git_section.build_git_section")
    @patch("aipass.prax.apps.plugins.devpulse_dashboard.dispatch_section.build_dispatch_section")
    def test_refresh_all_success(self, mock_dispatch, mock_git, branch_path):
        """Test refresh orchestrator calls all builders."""

        results = refresh(branch_path)
        assert results["git"]["success"] is True
        assert results["dispatch"]["success"] is True
        mock_git.assert_called_once_with(branch_path)
        mock_dispatch.assert_called_once_with(branch_path)

    @patch("aipass.prax.apps.plugins.devpulse_dashboard.git_section.build_git_section")
    @patch("aipass.prax.apps.plugins.devpulse_dashboard.dispatch_section.build_dispatch_section")
    def test_refresh_partial_failure(self, mock_dispatch, mock_git, branch_path):
        """Test refresh continues when one section fails."""

        mock_git.side_effect = FileNotFoundError("No .git")
        results = refresh(branch_path)
        assert results["git"]["success"] is False
        assert "No .git" in results["git"]["error"]
        assert results["dispatch"]["success"] is True
        # "Continues" is the dispatch builder still reached, for the same branch (prax, leg 7).
        mock_dispatch.assert_called_once_with(branch_path)

    def test_refresh_default_path(self):
        """Test refresh uses DEVPULSE_PATH by default."""

        assert DEVPULSE_PATH.name == "devpulse"
        assert "src" in DEVPULSE_PATH.parts and "aipass" in DEVPULSE_PATH.parts
