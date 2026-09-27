# =================== AIPass ====================
# Name: test_commit_gate_branch_mapping.py
# Description: Commit gate maps changed files to real citizens, never template trees
# Version: 1.0.1
# Created: 2026-08-13
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/git/commit_handler.py's commit test gate: which branch a changed file belongs to."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — pathlib's own parent walk and is_relative_to

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from aipass.drone.apps.handlers.git.commit_handler import commit_changes

# DPLAN-0291 round close finding. Spawn's templates ship full branch skeletons
# including .trinity/, so a bottom-up walk that stops at the FIRST .trinity/
# ancestor declares the template a branch. The gate then ran pytest on the
# template's tests, and pytest (finding the template's pytest.ini) wrote
# .pytest_cache INTO the template tree, which spawn's own hygiene tests correctly
# reject, wedging every subsequent commit. Citizens never nest, so the outermost
# .trinity/ ancestor is the real owner.

_RUN = "aipass.drone.apps.handlers.git.commit_handler.subprocess.run"


def _mk_branch(root: Path, rel: str) -> Path:
    branch = root / rel
    (branch / ".trinity").mkdir(parents=True)
    (branch / "tests").mkdir()
    return branch


def _gate_runs(repo_root: Path, changed: str) -> tuple[dict, list[list[str]]]:
    """Commit --all with *changed* as the one dirty path; every git, ruff and pytest call is recorded, none runs.

    The recorded pytest fails, so the gate refuses and the commit stops before git add.
    """
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
    """Mutant: _find_branch_for_path returns the first .trinity/ hit — the gate tests the template."""
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
