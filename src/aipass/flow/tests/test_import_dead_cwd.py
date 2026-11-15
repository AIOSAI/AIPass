# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: No flow module reads the working directory to find itself, or walks inspect.stack()
# Version: 1.2.0
# Created: 2026-08-31
# Modified: 2026-11-15
# =============================================

"""Tests for aipass/flow/apps/__init__.py and every module beneath it: no stray cwd read, no inspect.stack()."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that the module parses and imports

import ast
from pathlib import Path

import pytest

import aipass.flow.apps as flow_apps

# Nothing looks into or runs out of a dropbox or an .archive; __pycache__ is skipped too. Names are compared
# below the walk's root.
_WALK_IGNORED_DIRS = frozenset({"dropbox", ".archive", "__pycache__"})


def _flow_modules(root: Path | None = None) -> list[str]:
    """Every importable module under ``aipass.flow.apps``, by walking the tree."""
    root = root or Path(flow_apps.__file__).parent
    names = set()
    for source in sorted(root.rglob("*.py")):
        if _WALK_IGNORED_DIRS.intersection(source.relative_to(root).parts):
            continue
        rel = source.relative_to(root).with_suffix("")
        parts = [p for p in rel.parts if p != "__init__"]
        names.add(".".join(["aipass.flow.apps", *parts]))
    return sorted(names)


def _flow_modules_by_import_machinery(root: Path | None = None) -> list[str]:
    """The same set, derived through importlib's finder instead of the filesystem."""
    import pkgutil

    def walk(path: Path, prefix: str) -> set[str]:
        found = set()
        for info in pkgutil.iter_modules([str(path)]):
            if info.name in _WALK_IGNORED_DIRS:
                continue
            name = f"{prefix}.{info.name}"
            found.add(name)
            if info.ispkg:
                found |= walk(path / info.name, name)
        return found

    root = root or Path(flow_apps.__file__).parent
    names = walk(root, "aipass.flow.apps") | {"aipass.flow.apps"}
    return sorted(name for name in names if ".archive" not in name)


@pytest.fixture(scope="module")
def flow_modules() -> list[str]:
    """Every flow module, with the count DERIVED rather than lower-bounded."""
    modules = _flow_modules()
    expected = _flow_modules_by_import_machinery()

    assert set(modules) == set(expected), (
        "the filesystem walk and importlib's finder disagree about which modules exist. "
        f"Only in the walk: {sorted(set(modules) - set(expected))}; "
        f"only in the finder: {sorted(set(expected) - set(modules))}. One of them is "
        "dropping entries, and a sweep built on the short list would pass while covering less."
    )
    assert len(modules) > 40, (
        f"both mechanisms agree on only {len(modules)} modules — they are agreeing about a "
        "tree that is not there, which set equality alone cannot catch"
    )
    return modules


def _tree_with_a_dropbox_and_an_archive(tmp_path: Path) -> Path:
    """An apps/ stand-in: real.py (the live control), beside a dropbox, an .archive
    and a __pycache__ each holding a package.

    The root itself sits inside a directory named dropbox: a skip reading the whole path would drop real.py.
    """
    root = tmp_path / "dropbox" / "apps"
    for package in (root, root / "dropbox", root / ".archive", root / "__pycache__"):
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
    (root / "real.py").write_text("", encoding="utf-8")
    (root / "dropbox" / "stray.py").write_text("", encoding="utf-8")
    (root / ".archive" / "old.py").write_text("", encoding="utf-8")
    (root / "__pycache__" / "cached.py").write_text("", encoding="utf-8")
    return root


class TestTheWalksNeverEnterADropbox:
    """Every walk in this file skips dropbox/, .archive/ and __pycache__/."""

    def test_the_filesystem_walk_skips_a_dropbox(self, tmp_path):
        assert _flow_modules(_tree_with_a_dropbox_and_an_archive(tmp_path)) == [
            "aipass.flow.apps",
            "aipass.flow.apps.real",
        ]

    def test_the_finder_walk_skips_a_dropbox(self, tmp_path):
        """dropbox/ and __pycache__/ are proved here; .archive/ is not.

        pkgutil skips a dotted directory by itself, so the filesystem walk's pin proves the .archive half.
        """
        assert _flow_modules_by_import_machinery(_tree_with_a_dropbox_and_an_archive(tmp_path)) == [
            "aipass.flow.apps",
            "aipass.flow.apps.real",
        ]

    def test_the_source_sweep_skips_a_dropbox(self, tmp_path):
        root = _tree_with_a_dropbox_and_an_archive(tmp_path)

        swept = TestNoModuleLevelLocationCallSurvives._apps_sources(root)

        assert [p.relative_to(root).as_posix() for p in swept] == ["__init__.py", "real.py"]


class TestTheModuleCountIsDerivedFromTwoMechanisms:
    """The short-table cure's own control, added because a mutant walked past it."""

    def test_the_two_derivations_are_different_code_paths(self):
        """Asserted structurally, because behaviour cannot tell a copy from a check."""
        import ast
        import inspect

        # Docstring stripped first: it names rglob to warn against it.
        tree = ast.parse(inspect.getsource(_flow_modules_by_import_machinery).strip())
        function = tree.body[0]
        assert isinstance(function, ast.FunctionDef), (
            "the second derivation is no longer a plain function definition, so the source "
            f"read below is not its body: {type(function).__name__}"
        )
        body = function.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        finder_source = "\n".join(ast.unparse(node) for node in body)

        assert "pkgutil" in finder_source, (
            "the second derivation no longer goes through importlib's finder — if it "
            "globs the filesystem like the first one, the two agree by construction"
        )
        assert "_flow_modules(" not in finder_source, (
            "the second derivation calls the first — the set equality in the fixture is "
            "then comparing a value with itself"
        )
        assert "rglob" not in finder_source, "the second derivation is globbing, which is the first mechanism"
        # Of every discovery mechanism the file knows, the second derivation calls exactly pkgutil's.
        mechanisms = {"pkgutil.iter_modules", "pkgutil.walk_packages", "_flow_modules", "rglob", "glob", "os.walk"}
        called = set()
        for statement in body:
            for node in ast.walk(statement):
                if isinstance(node, ast.Call):
                    name = ast.unparse(node.func)
                    # root.rglob / path.glob: the receiver varies, the mechanism does not.
                    called.add(name.rsplit(".", 1)[-1] if name.endswith("glob") else name)
        assert called & mechanisms == {"pkgutil.iter_modules"}, (
            f"the second derivation's discovery calls are {sorted(called & mechanisms)}, not pkgutil's finder alone"
        )

    def test_the_fixture_compares_one_against_the_other(self):
        """And that the fixture actually uses both, rather than one twice."""
        import inspect

        # getattr: pytest's fixture type does not declare __wrapped__. Asserted first to fail with a sentence.
        undecorated = getattr(flow_modules, "__wrapped__", None)
        assert undecorated is not None, (
            "the flow_modules fixture no longer carries __wrapped__, so the source read "
            "below would be the decorator's rather than the fixture's own"
        )
        fixture_source = inspect.getsource(undecorated)

        assert "_flow_modules()" in fixture_source and "_flow_modules_by_import_machinery()" in fixture_source, (
            "the fixture no longer derives its expectation from the second mechanism: " + fixture_source
        )

    def test_both_mechanisms_agree_on_a_known_module(self):
        """Control for the pair: two empty collectors would also be set-equal."""
        by_walk = set(_flow_modules())
        by_finder = set(_flow_modules_by_import_machinery())

        for expected in ("aipass.flow.apps.handlers.repo_root", "aipass.flow.apps.handlers.json.json_handler"):
            assert expected in by_walk, f"the filesystem walk lost a module that is demonstrably there: {expected}"
            assert expected in by_finder, f"the finder lost a module that is demonstrably there: {expected}"


class TestNoModuleLevelLocationCallSurvives:
    """The structural half, because behaviour cannot reach every reintroduction.

    An inspect.stack() walk in a branch no import enters stays green behaviourally. The ban is on the CALL
    (ast.Call of inspect.stack), never the string, because docstrings spell the defect to explain it.
    """

    # The two functions that read the caller's cwd ON PURPOSE, at call time, never at import.
    DELIBERATE_CALLER_CWD_READS = frozenset(
        {
            ("project_scope.py", "caller_cwd"),
            ("resolve_location.py", "_get_caller_cwd"),
        }
    )

    @staticmethod
    def _apps_sources(root: Path | None = None) -> list[Path]:
        """Every .py under apps/ (or ``root``, which the dropbox pin passes), ignored dirs skipped."""
        root = root or Path(flow_apps.__file__).parent
        return [p for p in sorted(root.rglob("*.py")) if not _WALK_IGNORED_DIRS.intersection(p.relative_to(root).parts)]

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

    @staticmethod
    def _cwd_reads_outside_the_named_two(source: Path, tree: ast.Module) -> list[str]:
        """``Path.cwd()``/``os.getcwd()`` calls in functions nobody blessed."""
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if (source.name, node.name) in TestNoModuleLevelLocationCallSurvives.DELIBERATE_CALLER_CWD_READS:
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call) or not isinstance(sub.func, ast.Attribute):
                    continue
                if sub.func.attr in ("cwd", "getcwd"):
                    offenders.append(f"{source.name}:{sub.lineno}  {node.name}() -> {ast.unparse(sub)}")
        return offenders

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

    def test_the_only_cwd_reads_left_are_the_two_that_mean_it(self):
        """Seven ``_find_repo_root`` copies ended ``return Path.cwd()``. None may return.


        cwd is a guess, and a writer with a guessed root writes into a tree nobody chose.
        """
        offenders = []
        for source in self._apps_sources():
            tree = ast.parse(source.read_text(encoding="utf-8"))
            offenders.extend(self._cwd_reads_outside_the_named_two(source, tree))

        assert offenders == [], (
            "a cwd read outside the two deliberate caller-cwd functions — "
            "use handlers/repo_root.find_repo_root(): " + ", ".join(offenders)
        )

    # Negative controls: every detector runs against source it MUST flag and source it must NOT.

    def test_the_stack_detector_convicts_a_call_in_an_unreachable_branch(self):
        """@hooks' M7 and @trigger's 1058-green mutant, reproduced."""
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
        """The reason this is an AST ban and not a grep."""
        tree = ast.parse('"""Walks sys._getframe rather than inspect.stack() — see the cure."""\n')
        assert self._inspect_stack_calls(tree) == [], (
            "a string ban convicts the explanation along with the defect, which is how a cure ends up undocumented"
        )

    def test_the_stack_detector_clears_an_unrelated_stack_attribute(self):
        tree = ast.parse("import numpy\nx = numpy.stack([1, 2])\n")
        assert self._inspect_stack_calls(tree) == [], "the ban is on inspect.stack, not on the word stack"

    def test_the_cwd_detector_convicts_a_fallback_in_an_unblessed_function(self):
        source = Path("close_helpers.py")
        tree = ast.parse("from pathlib import Path\ndef _find_repo_root():\n    return Path.cwd()\n")
        assert self._cwd_reads_outside_the_named_two(source, tree), (
            "the detector is blind to the exact seven-copy fallback it exists to ban"
        )

    def test_the_cwd_detector_clears_the_two_functions_that_mean_it(self):
        source = Path("project_scope.py")
        tree = ast.parse("from pathlib import Path\ndef caller_cwd():\n    return Path.cwd()\n")
        assert self._cwd_reads_outside_the_named_two(source, tree) == [], (
            "the ban deleted a correct answer — caller_cwd is ASKING where the caller stood"
        )

    def test_the_cwd_exemption_is_keyed_on_the_file_too(self):
        """The same function name in a different file is not the blessed one."""
        source = Path("close_helpers.py")
        tree = ast.parse("from pathlib import Path\ndef caller_cwd():\n    return Path.cwd()\n")
        assert self._cwd_reads_outside_the_named_two(source, tree), (
            "the exemption is name-only — any file could adopt the name and inherit the pass"
        )
