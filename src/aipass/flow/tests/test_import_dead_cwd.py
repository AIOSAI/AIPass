# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Every flow module imports, and keeps logging, without a readable working directory
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-11-02
# =============================================

"""Tests for aipass/flow/apps/__init__.py and every module beneath it importing with no readable working directory."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that the module parses and imports

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import aipass.flow.apps as flow_apps
from aipass.flow.tests import support_fence

# inspect.stack() reaches getmodule()'s unguarded realpath on a pseudo-file frame.
# World B denies realpath outright: the world that reaches getmodule and convicts inspect.stack().
# World B's frame must be <string> (-c or compile()), never <stdin>, whose linecache entry hides the call.
# Every assertion is preceded by a control proving its world is armed.

# Other branches' import-time code is preloaded in the healthy world so this file measures only flow's sites.
# Delete a line once that branch's own dead-cwd pin is green. trigger is deliberately not preloaded:
# close_plan imports it behind `except ImportError`, and an OSError there must red the fan with
# close_plan.py named, not be hidden by a wider except.
_PRELOAD = """
from aipass.prax import logger  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401
import aipass.api  # noqa: F401
"""

# Python 3.10's Path.resolve calls _NormalAccessor.realpath, a copy of os.path.realpath captured at pathlib's
# first import, so rebinding os.path.realpath later never reaches it (3.11 removed the accessor). Patching
# the accessor when it exists makes every world order-independent. Each detail un-arms the world if lost:
# staticmethod (else the accessor binds itself as the path); *a, **k (resolve passes strict); exercised
# through an INSTANCE (a class-level read never binds); probed with an ABSOLUTE path (posixpath reads the cwd
# for a relative one, convicting on the path's shape).
_ACCESSOR_CURE = """
import pathlib as _pathlib_accessor

if hasattr(_pathlib_accessor, "_NormalAccessor"):
    _pathlib_accessor._NormalAccessor.realpath = staticmethod(_denied_realpath)
"""

_WORLD_B = (
    """
import os


def _denied_realpath(path, *a, **k):
    raise FileNotFoundError(2, "realpath denied", "")


os.path.realpath = _denied_realpath
"""
    + _ACCESSOR_CURE
)

# Must ride a <string> frame: compile(..., "<string>") leaves nothing in linecache, the shape getmodule's
# unguarded realpath is reached for.
_STACK_CONTROL = """
import inspect


def _probe():
    try:
        inspect.stack()
        return "NO"
    except OSError:
        return "YES"


_ns = {"_probe": _probe, "out": None}
exec(compile("out = _probe()", "<string>", "exec"), _ns)
print("STACK_DIES: " + _ns["out"])
"""


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


def _run_world(world: str, control: str, body: str) -> subprocess.CompletedProcess:
    script = _PRELOAD + world + control + body
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )


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


class TestEveryModuleImportsWithoutACwd:
    """The import fan, with the world's own liveness asserted."""

    IMPORT_BODY = """
import importlib
import sys
import traceback

dead = []
for name in {names!r}:
    try:
        importlib.import_module(name)
    except OSError:
        tb = traceback.extract_tb(sys.exc_info()[2])
        site = "unknown"
        for fr in tb:
            if "aipass" in fr.filename and "flow" in fr.filename:
                site = fr.filename + ":" + str(fr.lineno)
        dead.append(name + " -> " + site)
    except Exception:
        pass  # not this file's question

print("DEAD: " + str(len(dead)))
for entry in dead:
    print("  " + entry)
print("SWEPT: " + str(len({names!r})))
"""

    def test_world_b_denied_realpath_kills_no_flow_import(self, flow_modules):
        """The world that convicts ``inspect.stack()``."""
        result = _run_world(_WORLD_B, _STACK_CONTROL, self.IMPORT_BODY.format(names=flow_modules))

        assert result.returncode == 0, result.stdout + result.stderr
        assert "STACK_DIES: YES" in result.stdout, (
            "world B did not arm — inspect.stack() survived it, so nothing here convicts that call.\n" + result.stdout
        )
        assert "DEAD: 0" in result.stdout, result.stdout


class TestTheAuditLineSurvivesTheWorldItLogsIn:
    """``log_operation`` is reached at runtime, so no import probe covers it."""

    BODY = """
import os
import tempfile
import pathlib

seam = tempfile.mkdtemp()
os.environ["AIPASS_TEST_LOG_DIR"] = seam
from aipass.flow.apps.handlers.json import json_handler

# Measured THROUGH log_operation, never by calling caller detection directly.
# flow's handler is a shim that binds the one fleet json service
# (DPLAN-0325), and the service reads sys._getframe(2) - [0] itself,
# [1] log_operation, [2] the caller. A direct call is one frame short and
# reads whatever happens to sit above it, so it would answer a question
# nobody asked. The document the service WRITES carries the attribution in
# its own filename, which is the audit trail this test exists to protect.

# Arm 1: a frame with a real module filename. compile() sets co_filename, so
# this is a genuine named frame without a file on disk.
try:
    exec(compile("jh.log_operation('dead_cwd_probe', {'k': 1})", "router_probe.py", "exec"), {"jh": json_handler})
    print("LOG_OPERATION: SURVIVED")
except OSError as exc:
    print("LOG_OPERATION DIED: " + type(exc).__name__)

# Arm 2: the <string> frame @drone's router actually produces.
try:
    exec(compile("jh.log_operation('dead_cwd_probe', {'k': 2})", "<string>", "exec"), {"jh": json_handler})
    print("PSEUDO_FRAME: SURVIVED")
except OSError as exc:
    print("PSEUDO_FRAME DIED: " + type(exc).__name__)

written = sorted(p.name for p in pathlib.Path(seam).rglob("*_log.json"))
print("DOCUMENTS: " + ",".join(written))
"""

    def test_log_operation_survives_a_string_frame_with_realpath_denied(self):
        result = _run_world(_WORLD_B, _STACK_CONTROL, self.BODY)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "STACK_DIES: YES" in result.stdout, (
            "world B did not arm — this test would pass against the uncured call.\n" + result.stdout
        )
        assert "LOG_OPERATION: SURVIVED" in result.stdout, result.stdout
        assert "PSEUDO_FRAME: SURVIVED" in result.stdout, result.stdout
        # It must still ANSWER: one name for every caller would pass the lines above and destroy the audit trail.
        assert "router_probe_log.json" in result.stdout, (
            "the caller name stopped being read from the frame: " + result.stdout
        )
        # "unknown" by design: attributing work to <string> asserts something false about who did it.
        assert "unknown_log.json" in result.stdout, "a pseudo-frame is no longer answered 'unknown': " + result.stdout


class TestTheFenceLetsKinThroughWithNoCwd:
    """The fence's kin walk under a dead cwd, through its public shape.

    Runs tests/support_fence.py from its kin seat in world B, as a -c child via runpy.
    """

    BODY = f"""
import runpy

sys.argv = [{str(Path(support_fence.__file__))!r}, "pkg"]
runpy.run_path(sys.argv[0], run_name="__main__")
"""

    def test_the_fence_lets_kin_through_with_no_cwd(self):
        """The kin seat imports its handlers under world B's denied realpath: ALLOWED.

        Red against a frame walk that resolves a path without an OSError arm.
        """
        result = _run_world(_WORLD_B, _STACK_CONTROL, "\nimport sys\n" + self.BODY)
        out = result.stdout

        assert "STACK_DIES: YES" in out, f"world B did not arm - this pin proves nothing:\n{out}"
        assert out.strip().splitlines()[-1] == "ALLOWED", (
            f"the fence refused or died on its own kin under a dead cwd:\nstdout={out}\nstderr={result.stderr}"
        )


class TestNoModuleLevelLocationCallSurvives:
    """The structural half, because behaviour cannot reach every reintroduction.

    An inspect.stack() walk in a branch no import enters stays green behaviourally. The ban is on the CALL
    (ast.Call of inspect.stack), never the string, because docstrings spell the defect to explain it.
    """

    BANNED_ATTRS = frozenset({"resolve", "cwd", "getcwd", "realpath", "abspath"})

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
    def _catches_oserror(node: ast.Try) -> bool:
        """Whether one of the try's handlers names OSError, alone or in a tuple."""
        for handler in node.handlers:
            kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
            if any(isinstance(kind, ast.Name) and kind.id == "OSError" for kind in kinds):
                return True
        return False

    @staticmethod
    def _module_level_location_calls(tree: ast.Module) -> list[tuple[int, str]]:
        """Calls that infer a location and are evaluated when the module loads.

        A call in a module-level try that catches OSError is exempt: the import survives (the fence v2 shape).
        """
        found = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            parts = [node]
            if isinstance(node, ast.Try) and TestNoModuleLevelLocationCallSurvives._catches_oserror(node):
                parts = [*node.handlers, *node.orelse, *node.finalbody]
            for part in parts:
                for sub in ast.walk(part):
                    if not isinstance(sub, ast.Call):
                        continue
                    func = sub.func
                    attr = func.attr if isinstance(func, ast.Attribute) else None
                    if attr in TestNoModuleLevelLocationCallSurvives.BANNED_ATTRS:
                        found.append((sub.lineno, ast.unparse(sub)))
        return found

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

    def test_no_module_level_resolve_or_cwd_read_anywhere_in_apps(self):
        offenders = []
        for source in self._apps_sources():
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for lineno, text in self._module_level_location_calls(tree):
                offenders.append(f"{source.name}:{lineno}  {text}")

        assert offenders == [], (
            "module-level location calls crash the import with no cwd; "
            "route them through handlers/repo_root.module_file(): " + ", ".join(offenders)
        )

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

    def test_the_module_level_detector_convicts_a_module_level_resolve(self):
        tree = ast.parse("from pathlib import Path\nROOT = Path(__file__).resolve().parents[3]\n")
        assert self._module_level_location_calls(tree), "the detector is blind to the exact line it exists to ban"

    def test_the_module_level_detector_clears_the_same_call_inside_a_function(self):
        tree = ast.parse("from pathlib import Path\ndef f():\n    return Path(__file__).resolve()\n")
        assert self._module_level_location_calls(tree) == [], (
            "a resolve() inside a function is reached at CALL time, not import time — "
            "convicting it would ban the guarded helper this cure is built on"
        )

    def test_the_module_level_detector_clears_a_resolve_guarded_by_oserror(self):
        """The fence v2 shape: the dead cwd raises OSError inside the try and the import lives."""
        tree = ast.parse(
            "from pathlib import Path\n"
            "try:\n"
            "    F = str(Path(__file__).resolve())\n"
            "except OSError:\n"
            "    F = str(__file__)\n"
        )
        assert self._module_level_location_calls(tree) == [], "the detector convicts a resolve the import survives"

    def test_the_module_level_detector_convicts_a_resolve_guarded_by_another_error(self):
        """A try that does not catch OSError lets the dead cwd's raise kill the import."""
        tree = ast.parse(
            "from pathlib import Path\n"
            "try:\n"
            "    F = str(Path(__file__).resolve())\n"
            "except ValueError:\n"
            "    F = str(__file__)\n"
        )
        assert self._module_level_location_calls(tree), "the OSError exemption swallowed every try"

    def test_the_module_level_detector_convicts_a_resolve_in_the_oserror_arm(self):
        """The handler arm itself runs at import time and is not guarded by its own try."""
        tree = ast.parse(
            "from pathlib import Path\n"
            "try:\n"
            "    F = str(__file__)\n"
            "except OSError:\n"
            "    F = str(Path(__file__).resolve())\n"
        )
        assert self._module_level_location_calls(tree), "the exemption reached past the try body"

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
