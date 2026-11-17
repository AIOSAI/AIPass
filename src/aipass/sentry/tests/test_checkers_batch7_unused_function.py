# =================== AIPass ====================
# Name: test_checkers_batch7_unused_function.py
# Description: unused_function_check ruling: the message says what was measured (split from test_checkers_batch7.py)
# Version: 1.2.0
# Created: 2026-10-08
# Modified: 2026-11-17
# =============================================

"""Tests for apps/handlers/aipass_standards/unused_function_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that each checker in handlers/aipass_standards/ parses and imports

import pytest

from aipass.sentry.apps.handlers.aipass_standards import unused_function_check

pytestmark = pytest.mark.usefixtures("_pin_bypass_log")


class TestUnusedFunctionSaysWhatItActuallyMeasured:
    """The check measures "no caller in THIS branch" and said "unused"."""

    def _report(self, tmp_path, monkeypatch):

        # A neutral root inside tmp_path: the collector's skip set matches every path part, and tmp_path names the test.
        root = tmp_path / "branchroot"
        pkg = root / "apps" / "handlers"
        pkg.mkdir(parents=True)
        (pkg / "mod.py").write_text("def never_called_here():\n    return 1\n", encoding="utf-8")
        return unused_function_check.check_branch(str(root))

    def test_the_message_does_not_claim_the_function_is_unused(self, tmp_path, monkeypatch):
        report = self._report(tmp_path, monkeypatch)
        blob = str(report).lower()
        assert "no caller in this branch" in blob, report

    def test_the_message_names_the_limit_of_the_scan(self, tmp_path, monkeypatch):
        """A reader must be able to tell that cross-branch callers were not checked."""
        blob = str(self._report(tmp_path, monkeypatch)).lower()
        # Not an `or` over synonyms: both halves of the disclosure are pinned.
        assert "cross-branch" in blob
        assert "importlib" in blob
        assert "confirm before deleting" in blob


def test_a_function_that_only_calls_itself_has_no_caller(tmp_path):
    pkg = tmp_path / "branchroot" / "apps" / "handlers"
    pkg.mkdir(parents=True)
    (pkg / "mod.py").write_text("def walk(n):\n    return walk(n - 1) if n else 0\n", encoding="utf-8")
    report = unused_function_check.check_branch(str(tmp_path / "branchroot"))
    assert [u["name"] for u in report["checks"][0]["unused"]] == ["walk"]


def _fleet(tmp_path, hooks=None):
    """A repo with branch ``mine`` beside branch ``other``; ``hooks`` is the root .aipass/hooks.json text."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/dev\n", encoding="utf-8")
    if hooks is not None:
        (repo / ".aipass").mkdir()
        (repo / ".aipass" / "hooks.json").write_text(hooks, encoding="utf-8")
    for name in ("mine", "other"):
        (repo / "src" / "aipass" / name / "apps").mkdir(parents=True)
    mine = repo / "src" / "aipass" / "mine"
    (mine / "apps" / "mod.py").write_text("def wired():\n    return 1\n", encoding="utf-8")
    return mine, repo / "src" / "aipass" / "other" / "apps"


def _no_caller(branch):
    report = unused_function_check.check_branch(str(branch))
    return [u["name"] for u in report["checks"][0].get("unused", [])]


class TestCallersOutsideTheBranchAreCallers:
    """@hooks: hooks.json handlers and sandbox.build_policy (called from ai_mail) were rows."""

    def test_a_handler_the_root_hooks_json_names_has_a_caller(self, tmp_path):
        mine, _ = _fleet(tmp_path, '{"Stop": {"x": {"handler": "aipass.mine.apps.mod.wired"}}}')
        assert _no_caller(mine) == []

    def test_a_handler_hooks_json_names_for_another_branch_is_no_caller(self, tmp_path):
        mine, _ = _fleet(tmp_path, '{"Stop": {"x": {"handler": "aipass.other.apps.mod.wired"}}}')
        assert _no_caller(mine) == ["wired"]

    def test_a_sibling_branch_that_imports_the_function_is_a_caller(self, tmp_path):
        mine, other = _fleet(tmp_path)
        (other / "use.py").write_text("from aipass.mine.apps.mod import wired\n\nwired()\n", encoding="utf-8")
        assert _no_caller(mine) == []

    def test_a_sibling_that_never_names_the_branch_is_no_caller(self, tmp_path):
        mine, other = _fleet(tmp_path)
        (other / "own.py").write_text("def wired():\n    return 2\n\n\nwired()\n", encoding="utf-8")
        assert _no_caller(mine) == ["wired"]

    def test_a_sibling_test_file_is_no_caller(self, tmp_path):
        mine, other = _fleet(tmp_path)
        (other.parent / "tests").mkdir()
        (other.parent / "tests" / "test_use.py").write_text(
            "from aipass.mine.apps.mod import wired\n\nwired()\n", encoding="utf-8"
        )
        assert _no_caller(mine) == ["wired"]


#: A package top file in the house shape: a name-to-home table, __all__ built from it.
DOOR = '_HOMES = {"wired": "aipass.mine.apps.mod"}\n__all__ = list(_HOMES)\n'


class TestTheBranchsOwnDoorTableIsUse:
    """A name the branch's own door hands out is in use: the door is how other branches reach it."""

    @pytest.mark.parametrize(
        "door",
        [DOOR, DOOR.replace("list(_HOMES)", "[*_HOMES]"), '__all__ = ["wired"]\n'],
        ids=["list_of_table", "starred_table", "literal_all"],
    )
    def test_a_name_in_the_own_door_has_a_caller(self, tmp_path, door):
        mine, _ = _fleet(tmp_path)
        (mine / "__init__.py").write_text(door, encoding="utf-8")
        assert _no_caller(mine) == []

    def test_a_door_that_does_not_list_the_name_leaves_it_without_a_caller(self, tmp_path):
        mine, _ = _fleet(tmp_path)
        (mine / "__init__.py").write_text(DOOR.replace('"wired"', '"other_name"'), encoding="utf-8")
        assert _no_caller(mine) == ["wired"]

    def test_another_branchs_door_listing_the_same_name_is_no_caller(self, tmp_path):
        mine, other = _fleet(tmp_path)
        (other.parent / "__init__.py").write_text(DOOR.replace("aipass.mine", "aipass.other"), encoding="utf-8")
        assert _no_caller(mine) == ["wired"]
