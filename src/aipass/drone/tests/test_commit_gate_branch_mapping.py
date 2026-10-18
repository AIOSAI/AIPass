# =================== AIPass ====================
# Name: test_commit_gate_branch_mapping.py
# Description: Commit gate maps changed files to real citizens, never template trees
# Version: 1.0.2
# Created: 2026-08-13
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/git/commit_handler.py's commit test gate: which branch a changed file belongs to."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — pathlib's own parent walk and is_relative_to

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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
