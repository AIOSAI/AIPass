# =================== AIPass ====================
# Name: test_commit_gate_branch_mapping.py
# Description: Commit gate maps changed files to real citizens, never template trees
# Version: 1.0.0
# Created: 2026-08-13
# Modified: 2026-08-13
# =============================================

"""Branch mapping for the commit test gate (DPLAN-0291 round close finding).

Spawn's templates ship full branch skeletons including .trinity/, so a
bottom-up walk that stops at the FIRST .trinity/ ancestor declares the
template a branch. The gate then ran pytest on the template's tests, and
pytest (finding the template's pytest.ini) wrote .pytest_cache INTO the
template tree — which spawn's own hygiene tests correctly reject, wedging
every subsequent commit. Citizens never nest, so the outermost .trinity/
ancestor is the real owner.
"""

from __future__ import annotations

from pathlib import Path

from aipass.drone.apps.handlers.git.commit_handler import _find_branch_for_path


def _mk_branch(root: Path, rel: str) -> Path:
    branch = root / rel
    (branch / ".trinity").mkdir(parents=True)
    return branch


def test_template_file_maps_to_owning_branch(tmp_path: Path) -> None:
    """A change inside a template tree belongs to spawn, not the template."""
    spawn = _mk_branch(tmp_path, "src/aipass/spawn")
    template = _mk_branch(tmp_path, "src/aipass/spawn/templates/aipass_framework")
    (template / ".spawn").mkdir()
    changed = "src/aipass/spawn/templates/aipass_framework/.spawn/.template_registry.json"
    (tmp_path / changed).touch()

    result = _find_branch_for_path(changed, tmp_path)

    assert result is not None
    name, path = result
    assert name == "spawn"
    assert path == spawn


def test_plain_branch_file_maps_to_its_branch(tmp_path: Path) -> None:
    """Control: the ordinary case is untouched by the outermost-wins rule."""
    drone = _mk_branch(tmp_path, "src/aipass/drone")
    (drone / "apps").mkdir()
    changed = "src/aipass/drone/apps/drone.py"
    (tmp_path / changed).touch()

    result = _find_branch_for_path(changed, tmp_path)

    assert result == ("drone", drone)


def test_file_outside_any_branch_maps_to_none(tmp_path: Path) -> None:
    """Control: repo-root files (CHANGELOG etc.) still map to no branch."""
    _mk_branch(tmp_path, "src/aipass/drone")
    changed = "CHANGELOG.md"
    (tmp_path / changed).touch()

    assert _find_branch_for_path(changed, tmp_path) is None
