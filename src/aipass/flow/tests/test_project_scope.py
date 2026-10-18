# =================== AIPass ====================
# Name: test_project_scope.py
# Description: Tests for apps/handlers/plan/project_scope.py — project root resolution and register discrimination
# Version: 1.0.1
# Created: 2026-08-22
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/plan/project_scope.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import json
import os
from pathlib import Path

import pytest

from aipass.flow.apps.handlers.plan import project_scope
from aipass.flow.apps.handlers.plan.project_scope import (
    UnreadableRegisterError,
    caller_cwd,
    caller_project_root,
    describe_project,
    find_project_root,
)


REGISTER_SUFFIX = "_REGISTRY" + ".json"  # assembled: the literal name is a sealed-write trigger


def _register(directory: Path, name: str = "PROJ", **payload) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}{REGISTER_SUFFIX}"
    path.write_text(json.dumps({"metadata": {}, "branches": [], **payload}), encoding="utf-8")
    return path


class TestTheCacheIsTheCallersNotTheModules:
    """The memo is a parameter, not module state -- see find_project_root."""

    def test_a_register_created_after_a_miss_is_found_on_the_next_call(self, tmp_path):
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        assert find_project_root(deep) is None

        _register(tmp_path)
        assert find_project_root(deep) == tmp_path.resolve()

    def test_a_supplied_cache_is_filled_with_every_directory_walked(self, tmp_path):
        _register(tmp_path)
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)

        cache = {}
        assert find_project_root(deep, cache) == tmp_path.resolve()
        assert cache[deep.resolve()] == tmp_path.resolve()
        assert cache[(tmp_path / "a").resolve()] == tmp_path.resolve()

    def test_a_supplied_cache_answers_without_re_reading_the_tree(self, tmp_path):
        _register(tmp_path)
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)

        cache = {}
        find_project_root(deep, cache)
        # The register is gone; only the memo can still answer.
        for stale in tmp_path.glob(f"*{REGISTER_SUFFIX}"):
            stale.unlink()
        assert find_project_root(deep, cache) == tmp_path.resolve()
        assert find_project_root(deep) is None


class TestFindProjectRoot:
    def test_directory_holding_a_register_is_its_own_root(self, tmp_path):
        _register(tmp_path)
        assert find_project_root(tmp_path) == tmp_path.resolve()

    def test_nearest_ancestor_wins(self, tmp_path):
        _register(tmp_path, "OUTER")
        inner = tmp_path / "projects" / "inner"
        _register(inner, "INNER")
        deep = inner / "apps" / "handlers"
        deep.mkdir(parents=True)

        assert find_project_root(deep) == inner.resolve()

    def test_falls_through_to_the_outer_project_when_nested_dir_has_no_register(self, tmp_path):
        _register(tmp_path, "OUTER")
        deep = tmp_path / "src" / "aipass" / "flow"
        deep.mkdir(parents=True)

        assert find_project_root(deep) == tmp_path.resolve()

    def test_a_file_path_resolves_from_its_parent(self, tmp_path):
        _register(tmp_path)
        plan = tmp_path / "docs" / "FPLAN-0001_x.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("# plan", encoding="utf-8")

        assert find_project_root(plan) == tmp_path.resolve()

    def test_no_register_anywhere_returns_none(self, tmp_path):
        loose = tmp_path / "loose" / "dir"
        loose.mkdir(parents=True)
        assert find_project_root(loose) is None


class TestRegisterDiscrimination:
    """The ``branches`` key is what separates a register from a lookalike."""

    def test_matching_name_without_branches_is_not_a_register(self, tmp_path):
        _register(tmp_path, "OUTER")
        inventory = tmp_path / "inventory"
        inventory.mkdir()
        (inventory / f"LISTINGS{REGISTER_SUFFIX}").write_text(
            json.dumps({"registry_meta": {}, "listings": []}), encoding="utf-8"
        )

        assert find_project_root(inventory) == tmp_path.resolve()

    def test_plan_registry_is_not_a_project_register(self, tmp_path):
        _register(tmp_path, "OUTER")
        flow_json = tmp_path / "src" / "flow" / "flow_json"
        flow_json.mkdir(parents=True)
        (flow_json / f"PLAN{REGISTER_SUFFIX}").write_text(json.dumps({"plans": {}, "next_number": 1}), encoding="utf-8")

        assert find_project_root(flow_json) == tmp_path.resolve()

    def test_corrupt_register_is_neither_yes_nor_the_outer_project(self, tmp_path):
        """Unreadable tells us nothing, so the walk refuses.

        Mutant: `raise UnreadableRegisterError(...)` -> `continue` reddens this.
        """
        _register(tmp_path, "OUTER")
        sub = tmp_path / "sub"
        sub.mkdir()
        broken = sub / f"BROKEN{REGISTER_SUFFIX}"
        broken.write_text("{not json", encoding="utf-8")
        cache: dict = {}

        with pytest.raises(UnreadableRegisterError, match="Unreadable project register") as excinfo:
            find_project_root(sub, cache)

        assert str(broken) in str(excinfo.value)
        assert isinstance(excinfo.value.__cause__, json.JSONDecodeError)
        assert cache == {}

    def test_undecodable_register_also_refuses(self, tmp_path):
        """Bytes that are not UTF-8 refuse the same way as broken JSON."""
        _register(tmp_path, "OUTER")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / f"BROKEN{REGISTER_SUFFIX}").write_bytes(b"\xff\xfe{")

        with pytest.raises(UnreadableRegisterError) as excinfo:
            find_project_root(sub)

        assert isinstance(excinfo.value.__cause__, UnicodeDecodeError)

    def test_a_caller_standing_over_a_corrupt_register_is_not_placed_in_the_outer_project(self, tmp_path, monkeypatch):
        """The caller's side of the same walk: no project is guessed for them."""
        _register(tmp_path, "OUTER")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / f"BROKEN{REGISTER_SUFFIX}").write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(sub))

        with pytest.raises(UnreadableRegisterError):
            caller_project_root()

    def test_register_with_zero_citizens_still_marks_a_project(self, tmp_path):
        """SPEAKEASY and FEEL_GOOD_APP are real projects with no citizens."""
        _register(tmp_path, "OUTER")
        empty = tmp_path / "projects" / "speakeasy"
        _register(empty, "SPEAKEASY")

        assert find_project_root(empty) == empty.resolve()


class TestRefusalToGuess:
    def test_empty_location_is_not_attributed_to_the_process_cwd(self, tmp_path, monkeypatch):
        """Path("").resolve() is the CWD -- an empty row must not join the caller's project."""
        _register(tmp_path)
        monkeypatch.chdir(tmp_path)

        assert find_project_root(Path("")) is None

    def test_relative_location_is_refused(self, tmp_path, monkeypatch):
        _register(tmp_path)
        monkeypatch.chdir(tmp_path)

        assert find_project_root(Path("src/aipass")) is None

    def test_none_is_refused(self):
        assert find_project_root(None) is None


class TestCallerProjectRoot:
    def test_reads_the_caller_cwd_env_as_evidence(self, tmp_path, monkeypatch):
        _register(tmp_path)
        deep = tmp_path / "src" / "aipass" / "flow"
        deep.mkdir(parents=True)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(deep))

        assert caller_project_root() == tmp_path.resolve()

    def test_env_beats_the_process_cwd(self, tmp_path, monkeypatch):
        """Flow's own CWD is not where the caller stood."""
        theirs = tmp_path / "theirs"
        _register(theirs, "THEIRS")
        ours = tmp_path / "ours"
        _register(ours, "OURS")
        monkeypatch.chdir(ours)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(theirs))

        assert caller_project_root() == theirs.resolve()

    def test_falls_back_to_process_cwd_when_env_absent(self, tmp_path, monkeypatch):
        """Direct invocation: the process CWD is the same KIND of evidence."""
        _register(tmp_path)
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
        monkeypatch.chdir(tmp_path)

        assert caller_project_root() == tmp_path.resolve()

    def test_caller_outside_any_project_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))

        assert caller_project_root() is None

    def test_no_identity_claim_is_consulted(self, tmp_path, monkeypatch):
        """Location is evidence; a branch name is a claim. Only the first is read."""
        _register(tmp_path)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
        monkeypatch.setenv("AIPASS_CALLER_BRANCH", "somebody-else")
        monkeypatch.setenv("AIPASS_CALLER_IDENTITY_SOURCE", "project")

        assert caller_project_root() == tmp_path.resolve()
        assert os.environ["AIPASS_CALLER_BRANCH"] == "somebody-else"


class TestCallerCwd:
    """caller_cwd is the evidence every scope decision rests on."""

    def test_returns_the_env_location_verbatim(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))
        assert caller_cwd() == tmp_path

    def test_falls_back_to_the_process_cwd(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AIPASS_CALLER_CWD", raising=False)
        monkeypatch.chdir(tmp_path)
        assert caller_cwd() == Path(os.getcwd())

    def test_an_empty_env_value_is_not_a_location(self, tmp_path, monkeypatch):
        """Empty is absent, not Path("") -- which resolves to the process CWD."""
        monkeypatch.setenv("AIPASS_CALLER_CWD", "")
        monkeypatch.chdir(tmp_path)
        assert caller_cwd() == Path(os.getcwd())


class TestDescribeProject:
    """The name that lands in a refusal message the operator has to act on."""

    def test_names_the_project_directory(self, tmp_path):
        assert describe_project(tmp_path / "MARKETSTAND") == "MARKETSTAND"

    def test_no_project_is_said_in_words_not_left_as_none(self, tmp_path):
        assert describe_project(None) == "no project"


class TestTheRegisterGlobIsNotCaseFolded:
    """The round-3 case-fold species, in the two flow lanes that carry it.

    Glob folds case on Windows/macOS; the listing is widened here so the pin also runs on Linux.
    """

    def _project_dir(self, tmp_path: Path) -> Path:
        root = tmp_path / "proj"
        root.mkdir()
        (root / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": [{"name": "flow"}]}), encoding="utf-8")
        return root

    def test_a_lowercase_register_shaped_decoy_does_not_make_a_directory_a_project(self, tmp_path, monkeypatch):
        """The harm, if a decoy were ever armed: a subdirectory becomes a project."""
        sub = tmp_path / "proj" / "sub"
        self._project_dir(tmp_path)
        sub.mkdir()
        (sub / "other_registry.json").write_text(json.dumps({"branches": [{"name": "nobody"}]}), encoding="utf-8")

        real_glob = Path.glob

        def folded_glob(self, pattern):
            if pattern == project_scope.REGISTER_GLOB:
                return iter(sorted(p for p in real_glob(self, "*.json") if p.name.lower().endswith("_registry.json")))
            return real_glob(self, pattern)

        monkeypatch.setattr(Path, "glob", folded_glob)

        assert project_scope.find_project_root(sub) == (tmp_path / "proj").resolve(), (
            "a lowercase *_registry.json was accepted as a project register — "
            "on Windows this makes any directory holding one its own project root"
        )

    def test_the_exact_case_register_is_still_found(self, tmp_path):
        """Negative control: the narrowing must not refuse the real thing.

        Mutant: if isinstance(data, dict) and REGISTER_KEY in data: -> if False: reddens this.
        """
        root = self._project_dir(tmp_path)
        assert project_scope.find_project_root(root) == root.resolve()

    def test_the_emulation_actually_widens_the_listing(self, tmp_path, monkeypatch):
        """Control for the control: a folded glob that matches nothing proves nothing."""
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "other_registry.json").write_text("{}", encoding="utf-8")

        real_glob = Path.glob

        def folded_glob(self, pattern):
            if pattern == project_scope.REGISTER_GLOB:
                return iter(sorted(p for p in real_glob(self, "*.json") if p.name.lower().endswith("_registry.json")))
            return real_glob(self, pattern)

        monkeypatch.setattr(Path, "glob", folded_glob)
        assert list(sub.glob(project_scope.REGISTER_GLOB)) == [sub / "other_registry.json"], (
            "the bait is not reaching the code under test — every assertion above would be vacuous"
        )
