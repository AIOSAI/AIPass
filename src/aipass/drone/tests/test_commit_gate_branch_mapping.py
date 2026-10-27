# =================== AIPass ====================
# Name: test_commit_gate_branch_mapping.py
# Description: Commit gate maps changed files to real citizens, never template trees; --all lints what exists
# Version: 1.1.0
# Created: 2026-08-13
# Modified: 2026-10-26
# =============================================

"""Tests for apps/handlers/git/commit_handler.py's commit --all gates: the branch a changed file maps to, and lint."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — pathlib's own parent walk and is_relative_to

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.drone.apps.handlers.git.commit_handler import commit_changes

# Spawn's templates ship .trinity/, and pytest run in one writes .pytest_cache into
# the template, wedging every commit. Citizens never nest: the outermost .trinity/ owns.

_RUN = "aipass.drone.apps.handlers.git.commit_handler.subprocess.run"


def _mk_branch(root: Path, rel: str) -> Path:
    branch = root / rel
    (branch / ".trinity").mkdir(parents=True)
    (branch / "tests").mkdir()
    return branch


def _gate_runs(repo_root: Path, changed: str) -> tuple[dict, list[list[str]]]:
    """Commit --all with *changed* dirty; calls are recorded, none runs, and pytest fails so the gate refuses."""
    calls: list[list[str]] = []

    def _run(cmd: list[str], **_kwargs: object) -> MagicMock:
        calls.append([str(part) for part in cmd])
        if cmd[1:3] == ["status", "--porcelain"]:
            return MagicMock(returncode=0, stdout=f" M {changed}\n", stderr="")
        if cmd[1:3] == ["-m", "pytest"]:
            return MagicMock(returncode=1, stdout="1 failed", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch(_RUN, side_effect=_run):
        result = commit_changes("chore(test): gate mapping", all_files=True, repo_root=repo_root)
    return result, calls


def _pytest_dirs(calls: list[list[str]]) -> list[str]:
    return [cmd[3] for cmd in calls if cmd[1:3] == ["-m", "pytest"]]


def test_template_file_maps_to_owning_branch(tmp_path: Path) -> None:
    """A change inside a template tree belongs to spawn, not the template.

    Mutant: _find_branch_for_path returns the first .trinity/ hit — the gate tests the template.
    """
    spawn = _mk_branch(tmp_path, "src/aipass/spawn")
    template = _mk_branch(tmp_path, "src/aipass/spawn/templates/aipass_framework")
    (template / ".spawn").mkdir()
    changed = "src/aipass/spawn/templates/aipass_framework/.spawn/.template_registry.json"
    (tmp_path / changed).touch()

    result, calls = _gate_runs(tmp_path, changed)

    assert _pytest_dirs(calls) == [str(spawn.resolve() / "tests")]
    assert "--- spawn ---" in result["stderr"]
    assert result["exit_code"] == 1


def test_plain_branch_file_maps_to_its_branch(tmp_path: Path) -> None:
    """Control: the ordinary case is untouched by the outermost-wins rule."""
    drone = _mk_branch(tmp_path, "src/aipass/drone")
    (drone / "apps").mkdir()
    changed = "src/aipass/drone/apps/drone.py"
    (tmp_path / changed).touch()

    result, calls = _gate_runs(tmp_path, changed)

    assert _pytest_dirs(calls) == [str(drone.resolve() / "tests")]
    assert "--- drone ---" in result["stderr"]


def test_file_outside_any_branch_maps_to_none(tmp_path: Path) -> None:
    """Control: repo-root files (CHANGELOG etc.) map to no branch. Mutant: no-branch answers the repo root."""
    _mk_branch(tmp_path, "src/aipass/drone")
    (tmp_path / "tests").mkdir()
    changed = "CHANGELOG.md"
    (tmp_path / changed).touch()

    result, calls = _gate_runs(tmp_path, changed)

    assert _pytest_dirs(calls) == []
    assert not any(cmd[1:2] == ["commit"] for cmd in calls)
    assert "Test failures" not in result["stderr"]


def _git(repo: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", *argv], cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout.strip()


@pytest.fixture()
def external_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo laid out like an external project: tests under src/<pkg>/, no root tests/, one commit."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    repo = tmp_path / "ext"
    (repo / "src" / "pkg" / "tests").mkdir(parents=True)
    (repo / "src" / "pkg" / "core.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


@pytest.mark.skipif(shutil.which("ruff") is None, reason="the --all lane lints with the ruff on PATH")
class TestCommitAllInAnExternalLayout:
    """commit --all lints only the dirs that exist, refuses before rewriting, and names what it rewrote."""

    def test_a_lint_clean_tree_with_no_root_tests_dir_commits_and_names_the_file_ruff_formatted(
        self, external_repo: Path
    ) -> None:
        """Mutant: the targets fixed to src/ tests/ — ruff dies on the missing tests/ with E902."""
        core = external_repo / "src" / "pkg" / "core.py"
        core.write_text("x  =  2\n", encoding="utf-8")

        result = commit_changes("chore(pkg): bump", all_files=True, repo_root=external_repo)

        assert result["exit_code"] == 0, result["stderr"]
        assert "ruff rewrote 1 file(s): src/pkg/core.py" in result["stdout"]
        assert _git(external_repo, "log", "-1", "--format=%s") == "chore(pkg): bump"
        assert core.read_text(encoding="utf-8") == "x = 2\n"

    def test_a_lint_dirty_tree_refuses_and_leaves_every_file_as_the_author_wrote_it(self, external_repo: Path) -> None:
        """Mutant: --fix and format run before the gate — the refusal arrives after the tree was rewritten."""
        dirty = external_repo / "src" / "pkg" / "core.py"
        dirty.write_text("import os\nx = 2\n", encoding="utf-8")
        unformatted = external_repo / "src" / "pkg" / "tool.py"
        unformatted.write_text("y  =  3\n", encoding="utf-8")

        result = commit_changes("chore(pkg): bump", all_files=True, repo_root=external_repo)

        assert result["exit_code"] == 1
        assert "Lint errors" in result["stderr"]
        assert dirty.read_text(encoding="utf-8") == "import os\nx = 2\n"
        assert unformatted.read_text(encoding="utf-8") == "y  =  3\n"
        assert _git(external_repo, "log", "-1", "--format=%s") == "init"
