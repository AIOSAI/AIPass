#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_project_citizens.py
# Description: projects/* citizens resolve by registry and passport, not path shape
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""Regression cover for Mission Control's third path shape (DPLAN night item 9).

prax learned two shapes: ``src/aipass/*`` branches from AIPASS_REGISTRY.json,
and external Vera-class projects under ``~/Projects/``. In-repo citizens at
``projects/<proj>/src/<mod>/<name>`` were never learned, so Patrick's live
``monitor run baud`` answered "BAUD is not a known branch — nothing will be
shown."

Two defects, one cause. Scoping could not resolve the name, and path detection
fell through to Strategy 6, which splits a path into segments and matches each
against known branch names — the segment ``AIPass`` matches the ``aipass``
branch, so every BAUD file was labelled **AIPASS**. Misattribution is worse than
UNKNOWN: the events show up on the wrong screen and are filtered off the right
one.

Same family as the watchdog fix (c247fce8, sweep ``projects/*/*_REGISTRY.json``
after the main registry) and the statusline fix (walk up to the nearest
``.trinity/passport.json`` instead of matching path patterns).

Each test builds a real temporary repo, so nothing here depends on the live
tree's current citizen list.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest


DETECTOR_PATH = "aipass.prax.apps.handlers.monitoring.branch_detector"


def _load():
    """Import (or reimport) the detector under the active mocks."""
    sys.modules.pop(DETECTOR_PATH, None)
    module = importlib.import_module(DETECTOR_PATH)
    return importlib.reload(module)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _build_repo(tmp_path: Path, main_branches=None, projects=None, passports=()) -> Path:
    """Build a repo root with a main registry, project registries and passports.

    Args:
        tmp_path: pytest temp dir
        main_branches: entries for AIPASS_REGISTRY.json
        projects: {project_dir_name: [branch entries]} -> projects/<dir>/<NAME>_REGISTRY.json
        passports: paths (relative to repo root) that get a .trinity/passport.json

    Returns:
        The repo root path.
    """
    repo = tmp_path / "AIPass"
    if main_branches is None:
        main_branches = [{"name": "PRAX", "path": "src/aipass/prax", "status": "active"}]
    _write_json(repo / "AIPASS_REGISTRY.json", {"branches": main_branches})

    for dir_name, entries in (projects or {}).items():
        _write_json(repo / "projects" / dir_name / f"{dir_name.upper()}_REGISTRY.json", {"branches": entries})

    for rel in passports:
        _write_json(
            repo / rel / ".trinity" / "passport.json",
            {"branch_info": {"branch_name": Path(rel).name.upper(), "path": str(repo / rel)}},
        )
    return repo


def _detector_for(repo: Path, monkeypatch, cwd: Path | None = None):
    """Build a detector rooted at `repo`, optionally from a foreign CWD."""
    mod = _load()
    monkeypatch.setattr(mod.BranchDetector, "_find_repo_root", lambda self: repo)
    if cwd is not None:
        monkeypatch.chdir(cwd)
    return mod.BranchDetector()


BAUD_ENTRY = {"name": "BAUD", "path": "src/baud/baud", "status": "active"}


# ---------------------------------------------------------------------------
# The reported bug — scoping cannot resolve a projects/* citizen
# ---------------------------------------------------------------------------


class TestProjectCitizensAreKnown:
    """`monitor run baud` must resolve BAUD as a real citizen."""

    def test_project_citizen_is_a_known_branch(self, tmp_path, monkeypatch):
        repo = _build_repo(tmp_path, projects={"baud": [BAUD_ENTRY]})
        detector = _detector_for(repo, monkeypatch)
        assert "BAUD" in detector.known_branches

    def test_main_registry_branches_still_known(self, tmp_path, monkeypatch):
        """The sweep must add, never replace."""
        repo = _build_repo(tmp_path, projects={"baud": [BAUD_ENTRY]})
        detector = _detector_for(repo, monkeypatch)
        assert "PRAX" in detector.known_branches

    def test_every_project_registry_is_swept(self, tmp_path, monkeypatch):
        repo = _build_repo(
            tmp_path,
            projects={
                "baud": [BAUD_ENTRY],
                "earmark": [{"name": "EARMARK", "path": "src/earmark/earmark", "status": "active"}],
            },
        )
        detector = _detector_for(repo, monkeypatch)
        assert {"BAUD", "EARMARK"} <= detector.known_branches

    def test_scope_no_longer_calls_a_project_citizen_unknown(self, tmp_path, monkeypatch):
        """The exact live symptom: the launch-time typo warning fired on a real citizen."""
        from aipass.prax.apps.handlers.monitoring.branch_scope import BranchScope

        repo = _build_repo(tmp_path, projects={"baud": [BAUD_ENTRY]})
        detector = _detector_for(repo, monkeypatch)
        assert BranchScope(["BAUD"]).unknown_names(set(detector.known_branches)) == []

    def test_a_genuine_typo_is_still_reported(self, tmp_path, monkeypatch):
        """Widening the known set must not silence the typo warning."""
        from aipass.prax.apps.handlers.monitoring.branch_scope import BranchScope

        repo = _build_repo(tmp_path, projects={"baud": [BAUD_ENTRY]})
        detector = _detector_for(repo, monkeypatch)
        assert BranchScope(["BAUUD"]).unknown_names(set(detector.known_branches)) == ["BAUUD"]


# ---------------------------------------------------------------------------
# The worse half — misattribution to AIPASS
# ---------------------------------------------------------------------------


class TestProjectCitizenFilesAreNotMisattributed:
    """A BAUD file is BAUD, not the repo directory's name."""

    def test_project_citizen_file_resolves_to_its_own_branch(self, tmp_path, monkeypatch):
        repo = _build_repo(
            tmp_path,
            main_branches=[
                {"name": "PRAX", "path": "src/aipass/prax", "status": "active"},
                {"name": "AIPASS", "path": "src/aipass/aipass", "status": "active"},
            ],
            projects={"baud": [BAUD_ENTRY]},
        )
        detector = _detector_for(repo, monkeypatch)
        target = repo / "projects" / "baud" / "src" / "baud" / "baud" / "apps" / "baud.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
        assert detector.detect_from_path(str(target)) == "BAUD"

    def test_canary_path_segment_matching_would_say_aipass(self, tmp_path):
        """Proof of the old mechanism: the repo directory name IS a branch name."""
        known = {"AIPASS", "PRAX"}
        parts = "/home/u/Projects/AIPass/projects/baud/src/baud/baud/apps/baud.py".split("/")
        assert next((p.upper() for p in parts if p.upper() in known), None) == "AIPASS"


# ---------------------------------------------------------------------------
# Resolution comes from declarations, not from where the process happens to be
# ---------------------------------------------------------------------------


class TestPathsResolveAgainstTheirRegistry:
    """A registry's relative path is relative to that registry, never to CWD."""

    def test_relative_main_registry_path_ignores_cwd(self, tmp_path, monkeypatch):
        repo = _build_repo(tmp_path, main_branches=[{"name": "BACKUP", "path": "src/aipass/backup"}])
        foreign = tmp_path / "elsewhere"
        foreign.mkdir()
        detector = _detector_for(repo, monkeypatch, cwd=foreign)
        assert str(repo / "src" / "aipass" / "backup") in detector.branch_map
        assert not [p for p in detector.branch_map if str(foreign) in p]

    def test_relative_project_path_resolves_against_project_dir(self, tmp_path, monkeypatch):
        repo = _build_repo(tmp_path, projects={"baud": [BAUD_ENTRY]})
        detector = _detector_for(repo, monkeypatch)
        assert detector.branch_map.get(str(repo / "projects" / "baud" / "src" / "baud" / "baud")) == "BAUD"

    def test_absolute_paths_are_left_alone(self, tmp_path, monkeypatch):
        absolute = tmp_path / "somewhere" / "prax"
        repo = _build_repo(tmp_path, main_branches=[{"name": "PRAX", "path": str(absolute)}])
        detector = _detector_for(repo, monkeypatch)
        assert detector.branch_map.get(str(absolute)) == "PRAX"


class TestMainRegistryWinsCollisions:
    """A project registry must not shadow a real AIPass branch."""

    def test_project_entry_cannot_steal_an_existing_name(self, tmp_path, monkeypatch):
        real = {"name": "PRAX", "path": "src/aipass/prax", "status": "active"}
        impostor = {"name": "PRAX", "path": "src/fake/prax", "status": "active"}
        repo = _build_repo(tmp_path, main_branches=[real], projects={"rogue": [impostor]})
        detector = _detector_for(repo, monkeypatch)
        assert detector.branch_map.get(str(repo / "src" / "aipass" / "prax")) == "PRAX"
        assert str(repo / "projects" / "rogue" / "src" / "fake" / "prax") not in detector.branch_map


# ---------------------------------------------------------------------------
# Passports — the fallback that needs no registry at all
# ---------------------------------------------------------------------------


class TestPassportResolution:
    """A citizen with a passport resolves even when no registry lists it."""

    def test_unregistered_citizen_resolves_by_passport(self, tmp_path, monkeypatch):
        repo = _build_repo(
            tmp_path,
            main_branches=[{"name": "AIPASS", "path": "src/aipass/aipass", "status": "active"}],
            passports=["projects/orphan/src/orphan/orphan"],
        )
        detector = _detector_for(repo, monkeypatch)
        target = repo / "projects" / "orphan" / "src" / "orphan" / "orphan" / "apps" / "thing.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
        assert detector.detect_from_path(str(target)) == "ORPHAN"

    def test_passport_does_not_override_a_registered_path(self, tmp_path, monkeypatch):
        """Registry entries are the declaration of record; passports fill gaps."""
        repo = _build_repo(tmp_path, projects={"baud": [BAUD_ENTRY]}, passports=["projects/baud/src/baud/baud"])
        detector = _detector_for(repo, monkeypatch)
        target = repo / "projects" / "baud" / "src" / "baud" / "baud" / "apps" / "x.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
        assert detector.detect_from_path(str(target)) == "BAUD"


# ---------------------------------------------------------------------------
# A broken neighbour must not take the sweep down
# ---------------------------------------------------------------------------


class TestSweepIsFaultTolerant:
    """One unreadable project registry cannot cost us the others."""

    def test_empty_branches_list_is_survivable(self, tmp_path, monkeypatch):
        """speakeasy ships branches: [] — a real shape in the live tree."""
        repo = _build_repo(tmp_path, projects={"speakeasy": [], "baud": [BAUD_ENTRY]})
        detector = _detector_for(repo, monkeypatch)
        assert "BAUD" in detector.known_branches

    def test_malformed_registry_does_not_stop_the_sweep(self, tmp_path, monkeypatch):
        repo = _build_repo(tmp_path, projects={"baud": [BAUD_ENTRY]})
        bad = repo / "projects" / "broken" / "BROKEN_REGISTRY.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("{not json", encoding="utf-8")
        detector = _detector_for(repo, monkeypatch)
        assert "BAUD" in detector.known_branches

    def test_missing_projects_dir_is_not_an_error(self, tmp_path, monkeypatch):
        repo = _build_repo(tmp_path)
        detector = _detector_for(repo, monkeypatch)
        assert "PRAX" in detector.known_branches

    @pytest.mark.parametrize("entry", [{"path": "src/x/x"}, {"name": "X"}, {}, {"name": "", "path": ""}])
    def test_incomplete_entries_are_skipped(self, tmp_path, monkeypatch, entry):
        repo = _build_repo(tmp_path, projects={"baud": [entry, BAUD_ENTRY]})
        detector = _detector_for(repo, monkeypatch)
        assert "BAUD" in detector.known_branches
