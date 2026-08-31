# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Every flow module imports, and keeps logging, without a readable working directory
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""Flow must import, and must keep its audit line alive, with no cwd.

THE MECHANISM, measured on the Windows CI gate 2026-08-31 (@memory's finding,
relayed by @devpulse). ``ntpath.realpath`` calls ``os.getcwd()``
UNCONDITIONALLY — on its first lines, before it even asks whether the path is
absolute — where ``posixpath`` only reads the cwd for a relative one. And
``Path.resolve()`` routes through ``os.path.realpath``. So on Windows every
module-level ``Path(__file__).resolve()`` is an import-time working-directory
dependency, and a process whose cwd is gone cannot import the module at all.
Guarding INSIDE that module's functions changes nothing: the import died before
any of them existed.

``inspect.stack()`` carries the same defect one layer down and needs a
DIFFERENT world to convict it. It builds a ``FrameInfo`` per frame, and for a
frame whose filename is a PSEUDO-file it reaches ``getmodule()``, whose
``os.path.realpath(f)`` sits outside every ``try`` in that function. On POSIX
the equivalent raise happens EARLIER, inside ``getabsfile()``, where ``inspect``
catches it — which is exactly why two calls on flow's every-import and
every-write paths survived years of Linux CI carrying this.

TWO WORLDS, and @seedgo's asymmetry is why both are here rather than one:

* **World A** emulates ntpath — ``os.path.realpath`` is wrapped to read
  ``os.getcwd()`` first, then ``os.getcwd`` is denied. This convicts a raw
  ``resolve()``. It does NOT convict ``inspect.stack()`` on Linux, because
  ``getabsfile`` raises inside inspect's own catch before ``getmodule`` is
  reached.
* **World B** denies ``os.path.realpath`` outright while ``abspath`` keeps
  working. This is what reaches ``getmodule``'s unguarded call and convicts
  ``inspect.stack()``.

THIRD INGREDIENT for world B (@hooks): the frame must be ``<string>`` — an
interpreter ``-c`` or ``compile()`` frame — and NEVER ``<stdin>``. A
heredoc-fed child puts ``<stdin>`` in ``linecache.cache``, ``getsourcefile``
early-returns, and the probe reports green while the same world kills imports
for real. Every assertion below is preceded by a control that states whether its
world is armed, so a probe that quietly stopped biting cannot pass itself off as
a cure.

WHAT FLOW CARRIED, measured not estimated. Before this build, **61 of 61** flow
modules died on import in BOTH worlds — every one of them inside
``handlers/__init__.py``, at the ``inspect.stack()`` on line 20 and the
``Path(__file__).resolve()`` on line 21. Those two lines MASKED everything under
them, which is why the count only became true as cures landed: curing the guard
took it to 43/61 and revealed ``json/json_handler.py:38`` (masking 31 modules on
its own) plus twelve more; routing all **29** module-level
``Path(__file__).resolve()`` sites and all **7** private ``_find_repo_root``
copies through ``handlers/repo_root.py`` took it to **0/62**.

AND ONE LIVE SITE NO IMPORT PROBE REACHES. ``log_operation`` is the audit line
flow writes on essentially every registry operation, and its
``_get_caller_module_name`` called ``inspect.stack()``. The stack it walks is
the CALLER'S, so the shape that convicts it is a ``<string>`` frame — which is
precisely what @drone's router produces when it invokes flow.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

# Other branches' import-time code is held CONSTANT: preloaded in the healthy
# world, before any denial. Their cure is their own build; this file measures
# flow's sites and must not go red in someone else's name. These are flow's only
# cross-branch module-level imports, and they are TEMPORARY — delete a line once
# that branch's own dead-cwd pin is green.
#
# @trigger is DELIBERATELY not preloaded. close_plan.py imports their core at
# module level behind `except ImportError`, and the dispatch asked whether that
# should widen to (ImportError, OSError). MEASURED here rather than assumed:
# `from aipass.trigger.apps.modules.core import trigger` succeeds in BOTH worlds
# — their own cure has landed — so widening would add a catch for a condition
# that does not occur. Leaving trigger out of the preload is what keeps that
# measurement live: if their import ever starts raising OSError, close_plan dies
# for real and the fan below reds with close_plan.py named, which is the honest
# report. Widening the except would have hidden exactly that.
_PRELOAD = """
import aipass.prax  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401
import aipass.api  # noqa: F401
"""

_WORLD_A = """
import os

_real_realpath = os.path.realpath


def _ntpath_condition(path, **kw):
    os.getcwd()  # ntpath.realpath reads cwd before checking absoluteness
    return _real_realpath(path, **kw)


os.path.realpath = _ntpath_condition


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd
"""

_WORLD_B = """
import os


def _dead_realpath(path, **kw):
    raise FileNotFoundError(2, "realpath denied", "")


os.path.realpath = _dead_realpath
"""

# Does THIS interpreter's resolve() reach the denied call for an ABSOLUTE path?
# 3.11+ routes through os.path.realpath; 3.10 resolves absolute paths without
# touching the cwd, so the denial cannot fire there and the pin proves less.
_RESOLVE_CONTROL = """
import pathlib

try:
    pathlib.Path(pathlib.__file__).resolve()
    print("RESOLVE_DIES: NO")
except OSError:
    print("RESOLVE_DIES: YES")
"""

# The control for world B, and it MUST ride a <string> frame — see the module
# docstring. compile(..., "<string>") gives the frame a pseudo-filename with
# nothing in linecache, which is the shape getmodule's unguarded realpath is
# reached for.
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


def _flow_modules() -> list[str]:
    """Every importable module under ``aipass.flow.apps``, by walking the tree.

    Named from the filesystem rather than from a hand-written list: the whole
    species this file is about is a fix landing on some of N identical paths,
    and a list in a test is one more place for N to be undercounted.
    """
    import aipass.flow.apps as flow_apps

    root = Path(flow_apps.__file__).parent
    names = set()
    for source in sorted(root.rglob("*.py")):
        if "__pycache__" in source.parts or ".archive" in source.parts:
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
        timeout=300,
    )


@pytest.fixture(scope="module")
def flow_modules() -> list[str]:
    modules = _flow_modules()
    assert len(modules) > 40, f"the module walk found only {len(modules)} — it is not measuring the tree"
    return modules


class TestEveryModuleImportsWithoutACwd:
    """The import fan, in both worlds, with the world's own liveness asserted."""

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

    def test_world_a_ntpath_emulation_kills_no_flow_import(self, flow_modules):
        """A raw ``Path(__file__).resolve()`` anywhere on the import fan reds this."""
        result = _run_world(_WORLD_A, _RESOLVE_CONTROL, self.IMPORT_BODY.format(names=flow_modules))

        assert result.returncode == 0, result.stdout + result.stderr
        assert "RESOLVE_DIES: YES" in result.stdout, (
            "the ntpath world did not arm — every assertion below it would be vacuous.\n" + result.stdout
        )
        assert "DEAD: 0" in result.stdout, result.stdout
        assert f"SWEPT: {len(flow_modules)}" in result.stdout, result.stdout

    def test_world_b_denied_realpath_kills_no_flow_import(self, flow_modules):
        """Harsher, and the only world that convicts ``inspect.stack()``."""
        result = _run_world(_WORLD_B, _STACK_CONTROL, self.IMPORT_BODY.format(names=flow_modules))

        assert result.returncode == 0, result.stdout + result.stderr
        assert "STACK_DIES: YES" in result.stdout, (
            "world B did not arm — inspect.stack() survived it, so nothing here convicts that call.\n" + result.stdout
        )
        assert "DEAD: 0" in result.stdout, result.stdout


class TestTheAuditLineSurvivesTheWorldItLogsIn:
    """``log_operation`` is reached at runtime, so no import probe covers it.

    The stack it walks is the CALLER'S, so the shape that convicts it is a
    ``<string>`` frame — a routed subprocess, a hook, anything exec'd — which is
    precisely what @drone's router produces when it invokes flow.
    """

    BODY = """
import os
import tempfile

os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp()
from aipass.flow.apps.handlers.json import json_handler

json_handler.FLOW_JSON_DIR = __import__("pathlib").Path(tempfile.mkdtemp())

g = {"jh": json_handler, "name": None}
try:
    exec(compile("name = jh._get_caller_module_name()", "<string>", "exec"), g)
    print("CALLER_NAME: " + str(g["name"]))
except OSError as exc:
    print("CALLER_NAME DIED: " + type(exc).__name__)

try:
    exec(compile("jh.log_operation('dead_cwd_probe', {'k': 1})", "<string>", "exec"), g)
    print("LOG_OPERATION: SURVIVED")
except OSError as exc:
    print("LOG_OPERATION DIED: " + type(exc).__name__)
"""

    def test_log_operation_survives_a_string_frame_with_realpath_denied(self):
        result = _run_world(_WORLD_B, _STACK_CONTROL, self.BODY)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "STACK_DIES: YES" in result.stdout, (
            "world B did not arm — this test would pass against the uncured call.\n" + result.stdout
        )
        assert "LOG_OPERATION: SURVIVED" in result.stdout, result.stdout
        assert "CALLER_NAME DIED" not in result.stdout, result.stdout
        # It must still ANSWER, not merely not-crash: returning "unknown" for
        # every caller would satisfy the line above and destroy the audit trail.
        assert "CALLER_NAME: <string>" in result.stdout, (
            "the caller name stopped being read from the frame: " + result.stdout
        )


class TestNoModuleLevelLocationCallSurvives:
    """The structural half, because behaviour cannot reach every reintroduction.

    Proven by @hooks (M7) and re-proved by @trigger, who restored the deleted
    ``inspect.stack()`` walk and watched 1058 tests stay green: the walk sat in
    ``_guard_branch_access``'s caller-is-None branch, and no import-shaped world
    ever enters it — ``apps/__init__.py`` always supplies a real-file frame, so
    ``_find_real_caller`` never returns None during an import. A parse of the
    tree is the only instrument that sees it.

    The ban is on the CALL — ``ast.Call`` whose func is ``inspect.stack`` — never
    on the string, because this file and the cured modules SPELL the defect in
    their docstrings to explain it, and a string ban would convict the
    explanation along with the thing.
    """

    BANNED_ATTRS = frozenset({"resolve", "cwd", "getcwd", "realpath", "abspath"})

    # The two functions in this tree that read the process cwd ON PURPOSE, and
    # are RIGHT to. Both answer "where did the caller stand" — a location,
    # observed — and both are reached at call time, never at import. Named here
    # so the ban above can never delete a correct answer, which is the failure
    # mode a blanket rule has and a measured one does not.
    DELIBERATE_CALLER_CWD_READS = frozenset(
        {
            ("project_scope.py", "caller_cwd"),
            ("resolve_location.py", "_get_caller_cwd"),
        }
    )

    @staticmethod
    def _apps_sources() -> list[Path]:
        import aipass.flow.apps as flow_apps

        root = Path(flow_apps.__file__).parent
        return [p for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts and ".archive" not in p.parts]

    @staticmethod
    def _module_level_location_calls(tree: ast.Module) -> list[tuple[int, str]]:
        """Calls that infer a location and are evaluated when the module loads."""
        found = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for sub in ast.walk(node):
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
            "module-level location calls crash the import on a Windows box with no cwd; "
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

        This is the QUIET half of the defect, and the half a ``try``/``except``
        would have left in place: cwd is a guess, four of those callers are
        writers, and a writer with a guessed root writes into a tree nobody
        chose.
        """
        offenders = []
        for source in self._apps_sources():
            tree = ast.parse(source.read_text(encoding="utf-8"))
            offenders.extend(self._cwd_reads_outside_the_named_two(source, tree))

        assert offenders == [], (
            "a cwd read outside the two deliberate caller-cwd functions — "
            "use handlers/repo_root.find_repo_root(): " + ", ".join(offenders)
        )

    # -- negative controls, both directions -------------------------------
    #
    # A checker that convicts nothing and a checker that convicts everything
    # look identical in a green summary. Every detector is run against source it
    # MUST flag and source it must NOT.

    def test_the_module_level_detector_convicts_a_module_level_resolve(self):
        tree = ast.parse("from pathlib import Path\nROOT = Path(__file__).resolve().parents[3]\n")
        assert self._module_level_location_calls(tree), "the detector is blind to the exact line it exists to ban"

    def test_the_module_level_detector_clears_the_same_call_inside_a_function(self):
        tree = ast.parse("from pathlib import Path\ndef f():\n    return Path(__file__).resolve()\n")
        assert self._module_level_location_calls(tree) == [], (
            "a resolve() inside a function is reached at CALL time, not import time — "
            "convicting it would ban the guarded helper this cure is built on"
        )

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
