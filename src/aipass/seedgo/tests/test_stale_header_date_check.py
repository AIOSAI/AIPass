# =================== META ====================
# Name: test_stale_header_date_check.py
# Description: stale_header_date_check — a Modified: date older than the file's own history
# Version: 1.0.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""Tests for apps/handlers/aipass_standards/stale_header_date_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — is_bypassed's own matching rules; tests/test_bypass.py
# seedgo: no-test-needed(shared) — a "not applicable" file leaving the average; tests/test_incremental_audit.py

import datetime
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers.aipass_standards import stale_header_date_check as checker

#: The model file for the whole per-item series.
MODEL = Path(__file__).resolve().parent / "test_readme_update.py"

#: Every test here builds a real repository; without git there is nothing to build.
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

TODAY = datetime.date.today().isoformat()


def _git(repo: Path, *argv: str, date: str = "2026-09-23") -> None:
    """One git call in ``repo`` with a fixed identity and author date."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_AUTHOR_DATE=f"{date}T12:00:00", GIT_COMMITTER_DATE=f"{date}T12:00:00")
    subprocess.run(
        ["git", "-c", "user.name=seedgo", "-c", "user.email=seedgo@example.invalid", *argv],
        cwd=str(repo),
        env=env,
        capture_output=True,
        encoding="utf-8",
        check=True,
    )


def _header(modified: str, body: str = "") -> str:
    """A test file whose META header claims ``modified``."""
    return f"# =================== META ====================\n# Modified: {modified}\n\n{body}"


def _repo(tmp_path: Path, modified: str, committed: str) -> Path:
    """A repository holding one test file, committed on ``committed``."""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    _git(repo, "init", "-q")
    path = repo / "tests" / "test_specimen.py"
    path.write_text(_header(modified), encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "specimen", date=committed)
    checker.history.cache_clear()
    return path


class TestTheModelFilePasses:
    """The template's own model is the floor: if it fails, the rule is wrong."""

    def test_the_model_files_date_is_current_with_its_last_commit(self):
        assert checker.check_module(str(MODEL))["score"] == 100


class TestThePlantedSpecimen:
    """@backup, 2026-09-24: every header read 2026-09-22 after b92e0361 rewrote it on 09-23."""

    def test_a_header_one_commit_behind_is_convicted(self, tmp_path):
        path = _repo(tmp_path, modified="2026-09-22", committed="2026-09-23")
        result = checker.check_module(str(path))
        assert result["score"] == 0
        assert "Modified: 2026-09-22 is older than its last commit (2026-09-23)" in result["checks"][0]["message"]

    def test_a_header_on_the_commits_own_date_passes(self, tmp_path):
        path = _repo(tmp_path, modified="2026-09-23", committed="2026-09-23")
        assert checker.check_module(str(path))["score"] == 100

    def test_a_header_ahead_of_its_commit_passes(self, tmp_path):
        path = _repo(tmp_path, modified="2026-09-24", committed="2026-09-23")
        assert checker.check_module(str(path))["score"] == 100


class TestTheWorkingTreeIsJudgedAsOfToday:
    def test_an_uncommitted_change_that_left_the_date_is_convicted_at_the_edit(self, tmp_path):
        path = _repo(tmp_path, modified="2026-09-23", committed="2026-09-23")
        path.write_text(_header("2026-09-23", "x = 1\n"), encoding="utf-8")
        checker.history.cache_clear()
        result = checker.check_module(str(path))
        assert result["score"] == 0
        assert f"its uncommitted change, today ({TODAY})" in result["checks"][0]["message"]

    def test_an_uncommitted_change_that_moved_the_date_passes_at_once(self, tmp_path):
        path = _repo(tmp_path, modified="2026-09-23", committed="2026-09-23")
        path.write_text(_header(TODAY, "x = 1\n"), encoding="utf-8")
        checker.history.cache_clear()
        assert checker.check_module(str(path))["score"] == 100

    def test_a_file_never_committed_is_judged_as_of_today(self, tmp_path):
        path = _repo(tmp_path, modified="2026-09-23", committed="2026-09-23")
        fresh = path.parent / "test_fresh.py"
        fresh.write_text(_header("2026-09-01"), encoding="utf-8")
        checker.history.cache_clear()
        assert checker.check_module(str(fresh))["score"] == 0


class TestWhereHistoryCannotAnswerTheRuleDeclines:
    """Declining is not passing: the file measured nothing and leaves the average."""

    def test_a_shallow_clone_declines_rather_than_convict_every_file(self, tmp_path):
        path = _repo(tmp_path, modified="2026-09-22", committed="2026-09-23")
        path.write_text(_header("2026-09-22", "x = 1\n"), encoding="utf-8")
        _git(path.parents[1], "commit", "-qam", "second", date="2026-09-24")
        _git(tmp_path, "clone", "-q", "--depth", "1", path.parents[1].as_uri(), "shallow")
        checker.history.cache_clear()
        result = checker.check_module(str(tmp_path / "shallow" / "tests" / "test_specimen.py"))
        assert result["not_applicable"] is True
        assert "not applicable: a shallow clone" in result["checks"][0]["message"]

    def test_a_file_outside_any_work_tree_declines(self, tmp_path):
        path = tmp_path / "test_loose.py"
        path.write_text(_header("2026-09-22"), encoding="utf-8")
        checker.history.cache_clear()
        result = checker.check_module(str(path))
        assert result["not_applicable"] is True
        assert "not applicable" in result["checks"][0]["message"]

    def test_a_file_with_no_modified_line_is_not_this_rules_business(self, tmp_path):
        path = _repo(tmp_path, modified="2026-09-23", committed="2026-09-23")
        path.write_text('"""Tests."""\n', encoding="utf-8")
        result = checker.check_module(str(path))
        assert result["not_applicable"] is True
        assert "file_top owns the header" in result["checks"][0]["message"]

    def test_a_git_dir_in_the_environment_does_not_redirect_the_read(self, tmp_path, monkeypatch):
        path = _repo(tmp_path, modified="2026-09-22", committed="2026-09-23")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        _git(elsewhere, "init", "-q")
        monkeypatch.setenv("GIT_DIR", str(elsewhere / ".git"))
        checker.history.cache_clear()
        assert checker.check_module(str(path))["score"] == 0
