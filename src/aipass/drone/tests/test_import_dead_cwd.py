# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: No inspect.stack() call survives in drone's apps, and the source walks skip sandboxes
# Version: 1.2.0
# Created: 2026-08-31
# Modified: 2026-11-15
# =============================================

"""Tests for apps/handlers/__init__.py and every other source under apps/: no inspect.stack() call; the walks skip sandboxes."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(covered_elsewhere) — run-time location-inference sites, pinned in tests/test_no_cwd_sweep.py

import ast
from pathlib import Path

import pytest

import aipass.drone.apps as drone_apps

# Sandbox names (dropbox, .archive, __pycache__) come from conftest, never from sentry's handlers.
from .conftest import SANDBOX_DIRS


def _drone_modules(root: Path | None = None) -> list[str]:
    """Every importable module under ``aipass.drone.apps``, by walking the tree, never a hand list."""
    root = root or Path(drone_apps.__file__).parent
    names = set()
    for source in sorted(root.rglob("*.py")):
        if SANDBOX_DIRS.intersection(source.relative_to(root).parts):
            continue
        rel = source.relative_to(root).with_suffix("")
        parts = [p for p in rel.parts if p != "__init__"]
        names.add(".".join(["aipass.drone.apps", *parts]))
    return sorted(names)


class TestNoModuleLevelLocationCallSurvives:
    """The structural ban on inspect.stack() calls: on the call, never the string, so docstrings stay legal."""

    @staticmethod
    def _apps_sources(root: Path | None = None) -> list[Path]:
        root = root or Path(drone_apps.__file__).parent
        return [p for p in sorted(root.rglob("*.py")) if not SANDBOX_DIRS.intersection(p.relative_to(root).parts)]

    @staticmethod
    def _inspect_stack_calls(tree: ast.Module) -> list[int]:
        """``inspect.stack()`` calls at ANY depth — the unreachable-branch case."""
        found = []
        for sub in ast.walk(tree):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "stack"
                and isinstance(func.value, ast.Name)
                and func.value.id == "inspect"
            ):
                found.append(sub.lineno)
        return found

    def test_no_inspect_stack_call_survives_in_apps(self):
        offenders = []
        for source in self._apps_sources():
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for lineno in self._inspect_stack_calls(tree):
                offenders.append(f"{source.name}:{lineno}")

        assert offenders == [], (
            "inspect.stack() reaches getmodule's unguarded os.path.realpath; "
            "walk sys._getframe over f_code.co_filename instead: " + ", ".join(offenders)
        )

    # Negative controls: a detector that convicts nothing and one that convicts everything look
    # identical in a green summary, so both run against source they must and must not flag.

    def test_the_stack_detector_convicts_a_call_in_an_unreachable_branch(self):
        """@hooks' M7, reproduced: the branch no import probe can enter."""
        tree = ast.parse(
            "import inspect\n"
            "def guard(caller):\n"
            "    if caller is None:\n"
            "        for frame in inspect.stack():\n"
            "            pass\n"
            "        return\n"
            "    return\n"
        )
        assert self._inspect_stack_calls(tree), "the reintroduction @hooks measured would land unnoticed"

    def test_the_stack_detector_clears_a_docstring_that_names_the_defect(self):
        """The reason this is an AST ban and not a grep.

        The source stays a synthetic literal: a live file would make this a second copy of the ban.
        """
        tree = ast.parse('"""Walks sys._getframe rather than inspect.stack() — see the cure."""\n')
        assert self._inspect_stack_calls(tree) == [], (
            "a string ban convicts the explanation along with the defect, which is how a cure ends up undocumented"
        )

    def test_the_stack_detector_clears_an_unrelated_stack_attribute(self):
        tree = ast.parse("import numpy\nx = numpy.stack([1, 2])\ntraceback = []\ntraceback.stack()\n")
        assert self._inspect_stack_calls(tree) == [], "the ban is on inspect.stack, not on the word stack"


class TestTheSourceWalksSkipADropboxAndAnArchive:
    """Nothing looks into a dropbox or an .archive (owner ruling): both are
    sandboxes, so neither walk may import or parse what sits in one."""

    @pytest.fixture()
    def apps_tree(self, tmp_path: Path) -> Path:
        apps = tmp_path / "apps"
        for sandbox in ("dropbox", ".archive"):
            (apps / "handlers" / sandbox).mkdir(parents=True)
            (apps / "handlers" / sandbox / "probe.py").write_text("x = 1\n", encoding="utf-8")
        (apps / "handlers" / "real.py").write_text("x = 1\n", encoding="utf-8")
        return apps

    def test_the_import_walk_names_no_module_in_a_dropbox_or_an_archive(self, apps_tree: Path) -> None:
        assert _drone_modules(apps_tree) == ["aipass.drone.apps.handlers.real"]

    def test_the_parse_walk_reads_no_source_in_a_dropbox_or_an_archive(self, apps_tree: Path) -> None:
        sources = TestNoModuleLevelLocationCallSurvives._apps_sources(apps_tree)
        assert [p.relative_to(apps_tree).as_posix() for p in sources] == ["handlers/real.py"]

    def test_a_root_that_stands_inside_a_dropbox_is_still_walked(self, tmp_path: Path) -> None:
        """The skip judges the parts below the walked root, never the whole path: a project
        living under a directory named dropbox keeps every source. Green from its first run;
        its proof is that comparing the whole path empties both lists."""
        apps = tmp_path / "dropbox" / "apps"
        (apps / "handlers").mkdir(parents=True)
        (apps / "handlers" / "real.py").write_text("x = 1\n", encoding="utf-8")
        assert _drone_modules(apps) == ["aipass.drone.apps.handlers.real"]
        assert TestNoModuleLevelLocationCallSurvives._apps_sources(apps) == [apps / "handlers" / "real.py"]
