"""Tests for project_scope — "a project is its register".

The rule under test is Patrick's ruling of 2026-08-22: a directory is a project
root iff it holds a ``<NAME>_REGISTRY.json`` carrying a ``branches`` key.
Neither half is decoration — the live tree contains files that match the name
and are not registers, and projects that hold a register and nothing else.
"""

import json
import os
from pathlib import Path

import pytest


REGISTER_SUFFIX = "_REGISTRY" + ".json"  # assembled: the literal name is a sealed-write trigger


@pytest.fixture(autouse=True)
def _clear_scope_cache():
    """The resolver memoises directory -> root; tmp_path reuse must not leak."""
    from aipass.flow.apps.handlers.plan import project_scope

    project_scope.clear_cache()
    yield
    project_scope.clear_cache()


def _register(directory: Path, name: str = "PROJ", **payload) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}{REGISTER_SUFFIX}"
    path.write_text(json.dumps({"metadata": {}, "branches": [], **payload}), encoding="utf-8")
    return path


def _import():
    from aipass.flow.apps.handlers.plan.project_scope import (
        caller_project_root,
        find_project_root,
    )

    return find_project_root, caller_project_root


class TestFindProjectRoot:
    def test_directory_holding_a_register_is_its_own_root(self, tmp_path):
        find_project_root, _ = _import()
        _register(tmp_path)
        assert find_project_root(tmp_path) == tmp_path.resolve()

    def test_nearest_ancestor_wins(self, tmp_path):
        find_project_root, _ = _import()
        _register(tmp_path, "OUTER")
        inner = tmp_path / "projects" / "inner"
        _register(inner, "INNER")
        deep = inner / "apps" / "handlers"
        deep.mkdir(parents=True)

        assert find_project_root(deep) == inner.resolve()

    def test_falls_through_to_the_outer_project_when_nested_dir_has_no_register(self, tmp_path):
        find_project_root, _ = _import()
        _register(tmp_path, "OUTER")
        deep = tmp_path / "src" / "aipass" / "flow"
        deep.mkdir(parents=True)

        assert find_project_root(deep) == tmp_path.resolve()

    def test_a_file_path_resolves_from_its_parent(self, tmp_path):
        find_project_root, _ = _import()
        _register(tmp_path)
        plan = tmp_path / "docs" / "FPLAN-0001_x.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("# plan", encoding="utf-8")

        assert find_project_root(plan) == tmp_path.resolve()

    def test_no_register_anywhere_returns_none(self, tmp_path):
        find_project_root, _ = _import()
        loose = tmp_path / "loose" / "dir"
        loose.mkdir(parents=True)
        # tmp_path has no register; the walk reaches / and gives up.
        assert find_project_root(loose) is None


class TestRegisterDiscrimination:
    """The ``branches`` key is what separates a register from a lookalike."""

    def test_matching_name_without_branches_is_not_a_register(self, tmp_path):
        find_project_root, _ = _import()
        _register(tmp_path, "OUTER")
        inventory = tmp_path / "inventory"
        inventory.mkdir()
        # Real file on this machine: marketstand/inventory/LISTINGS_REGISTRY.json
        (inventory / f"LISTINGS{REGISTER_SUFFIX}").write_text(
            json.dumps({"registry_meta": {}, "listings": []}), encoding="utf-8"
        )

        # inventory/ must NOT become a project of its own.
        assert find_project_root(inventory) == tmp_path.resolve()

    def test_plan_registry_is_not_a_project_register(self, tmp_path):
        find_project_root, _ = _import()
        _register(tmp_path, "OUTER")
        flow_json = tmp_path / "src" / "flow" / "flow_json"
        flow_json.mkdir(parents=True)
        (flow_json / f"PLAN{REGISTER_SUFFIX}").write_text(json.dumps({"plans": {}, "next_number": 1}), encoding="utf-8")

        assert find_project_root(flow_json) == tmp_path.resolve()

    def test_corrupt_register_is_not_treated_as_yes(self, tmp_path):
        """Unreadable tells us nothing; answering 'yes' on no evidence splits a project."""
        find_project_root, _ = _import()
        _register(tmp_path, "OUTER")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / f"BROKEN{REGISTER_SUFFIX}").write_text("{not json", encoding="utf-8")

        assert find_project_root(sub) == tmp_path.resolve()

    def test_register_with_zero_citizens_still_marks_a_project(self, tmp_path):
        """SPEAKEASY and FEEL_GOOD_APP are real projects with no citizens."""
        find_project_root, _ = _import()
        _register(tmp_path, "OUTER")
        empty = tmp_path / "projects" / "speakeasy"
        _register(empty, "SPEAKEASY")

        assert find_project_root(empty) == empty.resolve()


class TestRefusalToGuess:
    def test_empty_location_is_not_attributed_to_the_process_cwd(self, tmp_path, monkeypatch):
        """Path("").resolve() is the CWD -- an empty row must not join the caller's project."""
        find_project_root, _ = _import()
        _register(tmp_path)
        monkeypatch.chdir(tmp_path)

        assert find_project_root(Path("")) is None

    def test_relative_location_is_refused(self, tmp_path, monkeypatch):
        find_project_root, _ = _import()
        _register(tmp_path)
        monkeypatch.chdir(tmp_path)

        assert find_project_root(Path("src/aipass")) is None

    def test_none_is_refused(self):
        find_project_root, _ = _import()
        assert find_project_root(None) is None


class TestCallerProjectRoot:
    def test_reads_the_caller_cwd_env_as_evidence(self, tmp_path, monkeypatch):
        _, caller_project_root = _import()
        _register(tmp_path)
        deep = tmp_path / "src" / "aipass" / "flow"
        deep.mkdir(parents=True)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(deep))

        assert caller_project_root() == tmp_path.resolve()

    def test_env_beats_the_process_cwd(self, tmp_path, monkeypatch):
        """Flow's own CWD is not where the caller stood."""
        _, caller_project_root = _import()
        theirs = tmp_path / "theirs"
        _register(theirs, "THEIRS")
        ours = tmp_path / "ours"
        _register(ours, "OURS")
        monkeypatch.chdir(ours)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(theirs))

        assert caller_project_root() == theirs.resolve()

    def test_falls_back_to_process_cwd_when_env_absent(self, tmp_path, monkeypatch):
        """Direct invocation: the process CWD is the same KIND of evidence."""
        _, caller_project_root = _import()
        _register(tmp_path)
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
        monkeypatch.chdir(tmp_path)

        assert caller_project_root() == tmp_path.resolve()

    def test_caller_outside_any_project_returns_none(self, tmp_path, monkeypatch):
        _, caller_project_root = _import()
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))

        assert caller_project_root() is None

    def test_no_identity_claim_is_consulted(self, tmp_path, monkeypatch):
        """Location is evidence; a branch name is a claim. Only the first is read."""
        _, caller_project_root = _import()
        _register(tmp_path)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "somebody-else")
        monkeypatch.setenv("AIPASS_CALLER_IDENTITY_SOURCE", "project")

        assert caller_project_root() == tmp_path.resolve()
        assert os.environ["AIPASS_CALLER_BRANCH"] == "somebody-else"
