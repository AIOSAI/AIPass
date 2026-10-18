# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Every drone module imports without a readable working directory
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests for apps/ and apps/handlers/json/json_handler.py: every drone module imports and logs with no cwd."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — run-time location-inference sites, pinned in tests/test_no_cwd_sweep.py
# seedgo: no-test-needed(external) — other branches' import-time code (prax.logger, cli, api), preloaded and held here

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import aipass.drone.apps as drone_apps

# Sandbox names (dropbox, .archive, __pycache__) come from conftest, never from seedgo's handlers.
from .conftest import SANDBOX_DIRS

# ntpath.realpath reads os.getcwd() unconditionally (posixpath only for a relative path) and
# Path.resolve() routes through it, so a module-level resolve() kills the import with no cwd.
# inspect.stack() reaches getmodule()'s unguarded os.path.realpath for a pseudo-file frame.
# World A (ntpath emulation) convicts resolve(); only world B (realpath denied) convicts
# inspect.stack(), and only from a <string> frame: <stdin> sits in linecache and goes green.

# Other branches' import-time code is preloaded in the healthy world: their cure is their own.
# Delete a line once that branch's own dead-cwd pin is green.
_PRELOAD = """
from aipass.prax import logger  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401
import aipass.api  # noqa: F401
"""

# 3.10's pathlib._NormalAccessor copies os.path.realpath at import, so the accessor class is
# patched too; that arms every interpreter in either import order.
# staticmethod AND *a are redundant on purpose: staticmethod stops the accessor binding, *a
# survives its removal. A bound wrapper still raises, so only a return-value pin catches it.
# Class only: an instance attribute shadows it and left staticmethod unfalsifiable (mutant M24b).
_NTPATH_WRAPPER = """
import os

_real_realpath = os.path.realpath


def _ntpath_condition(path, *a, **kw):
    os.getcwd()  # ntpath.realpath reads cwd before checking absoluteness
    return _real_realpath(path, *a, **kw)


os.path.realpath = _ntpath_condition

import pathlib as _pathlib_rp

if hasattr(_pathlib_rp, "_NormalAccessor"):
    _pathlib_rp._NormalAccessor.realpath = staticmethod(_ntpath_condition)
"""

_DENY_GETCWD = """
def _dead_getcwd(*a, **k):
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd
"""

_WORLD_A = _NTPATH_WRAPPER + _DENY_GETCWD

_WORLD_B = """
import os


def _dead_realpath(path, *a, **kw):
    raise FileNotFoundError(2, "realpath denied", "")


os.path.realpath = _dead_realpath

import pathlib as _pathlib_dr

if hasattr(_pathlib_dr, "_NormalAccessor"):
    _pathlib_dr._NormalAccessor.realpath = staticmethod(_dead_realpath)
"""

# 3.10's accessor shape, so the accessor rows are falsifiable on 3.11+; it captures the real
# os.path.realpath before any world is installed, the ordering 3.10 produces.
_FAKE_ACCESSOR = """
import os
import pathlib as _p


class _NormalAccessor:
    realpath = staticmethod(os.path.realpath)


_p._NormalAccessor = _NormalAccessor
_p._normal_accessor = _NormalAccessor()
"""

# A probe asking "did my patch reach X" lets X capture a sentinel, not the real function, or
# the platform answers: ntpath.realpath('/tmp') is D:\\tmp (a POSIX literal is drive-relative).
# This returns its argument and touches no filesystem, cwd or path module.
_SENTINEL_REALPATH = """
import os


def _sentinel_realpath(path, *a, **kw):
    return path


os.path.realpath = _sentinel_realpath
"""

# The opposite platform, for the litmus: the verdict must not move under an nt emulation.
# Trap: never alias ntpath.realpath here; on POSIX it falls back to abspath, which reads the cwd
# only for a relative path, so the alias emulates this host. The win32 branch is built by name.
_NT_EMULATION = """
import os


def _win32_realpath(path, *a, **kw):
    os.getcwd()  # unconditional on nt, unlike posixpath
    p = os.fspath(path)
    if p[:1] in ("/", "\\\\"):
        return "D:" + p.replace("/", "\\\\")
    return "D:\\\\emulated_cwd\\\\" + p.replace("/", "\\\\")


os.path.realpath = _win32_realpath
"""

# Does THIS interpreter's resolve() reach the denied call for an ABSOLUTE path?
_RESOLVE_CONTROL = """
import pathlib

try:
    pathlib.Path(pathlib.__file__).resolve()
    print("RESOLVE_DIES: NO")
except OSError:
    print("RESOLVE_DIES: YES")
"""

# World B's control; it must ride a <string> frame (nothing in linecache) to reach getmodule.
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


def _run_world(world: str, control: str, body: str) -> subprocess.CompletedProcess:
    script = _PRELOAD + world + control + body
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )


@pytest.fixture(scope="module")
def drone_modules() -> list[str]:
    modules = _drone_modules()
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
            if "aipass" in fr.filename and "drone" in fr.filename:
                site = fr.filename + ":" + str(fr.lineno)
        dead.append(name + " -> " + site)
    except Exception:
        pass  # not this file's question

print("DEAD: " + str(len(dead)))
for entry in dead:
    print("  " + entry)
print("SWEPT: " + str(len({names!r})))
"""

    def test_world_a_ntpath_emulation_kills_no_drone_import(self, drone_modules):
        """A raw ``Path(__file__).resolve()`` anywhere on the import fan reds this."""
        result = _run_world(_WORLD_A, _RESOLVE_CONTROL, self.IMPORT_BODY.format(names=drone_modules))

        assert result.returncode == 0, result.stdout + result.stderr
        assert "RESOLVE_DIES: YES" in result.stdout, (
            "the ntpath world did not arm — every assertion below it would be vacuous.\n" + result.stdout
        )
        assert "DEAD: 0" in result.stdout, result.stdout
        assert f"SWEPT: {len(drone_modules)}" in result.stdout, result.stdout

    def test_world_b_denied_realpath_kills_no_drone_import(self, drone_modules):
        """Harsher, and the only world that convicts ``inspect.stack()``."""
        result = _run_world(_WORLD_B, _STACK_CONTROL, self.IMPORT_BODY.format(names=drone_modules))

        assert result.returncode == 0, result.stdout + result.stderr
        assert "STACK_DIES: YES" in result.stdout, (
            "world B did not arm — inspect.stack() survived it, so nothing here convicts that call.\n" + result.stdout
        )
        assert "DEAD: 0" in result.stdout, result.stdout


class TestTheAuditLineSurvivesTheWorldItLogsIn:
    """``log_operation`` is reached at runtime, so no import probe covers it.

    It walks the caller's stack, so a ``<string>`` frame (what drone's router produces) convicts it.
    """

    BODY = """
import os
import tempfile
import pathlib

seam = tempfile.mkdtemp()
os.environ["AIPASS_TEST_LOG_DIR"] = seam
from aipass.drone.apps.handlers.json import json_handler

# Measured THROUGH log_operation, never by calling caller detection directly.
# drone's handler is a shim that binds the one fleet json service
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

# Arm 2: the <string> frame drone's own router actually produces.
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
        # It must still ANSWER, not merely not-crash: attributing every caller
        # to one name would satisfy the lines above and destroy the audit trail.
        assert "router_probe_log.json" in result.stdout, (
            "the caller name stopped being read from the frame: " + result.stdout
        )
        # A pseudo-frame is answered "unknown" by design: a log naming <string> asserts a false author.
        assert "unknown_log.json" in result.stdout, "a pseudo-frame is no longer answered 'unknown': " + result.stdout


class TestTheWorldArmsOnEveryInterpreter:
    """The 3.10 row, made falsifiable on an interpreter that is not 3.10.

    The row is reproduced under an emulated accessor, not measured on a real 3.10.
    """

    PROBE = """
import pathlib as _p

try:
    _p._normal_accessor.realpath("/tmp")
    print("ACCESSOR_DENIED: NO")
except OSError:
    print("ACCESSOR_DENIED: YES")
"""

    BARE_PATCH_ONLY = """
import os


def _bare(path, *a, **kw):
    raise FileNotFoundError(2, "realpath denied", "")


os.path.realpath = _bare
"""

    @staticmethod
    def _run(script: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, encoding="utf-8", timeout=120
        )

    def test_a_bare_module_patch_does_not_reach_a_pre_captured_accessor(self):
        """CI's Python 3.10 failure, reproduced here. This is the red-first half.

        If this ever fails, the bug is no longer expressible and the two below prove less.
        """
        result = self._run(_FAKE_ACCESSOR + self.BARE_PATCH_ONLY + self.PROBE)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "ACCESSOR_DENIED: NO" in result.stdout, (
            "a bare os.path.realpath patch reached a pre-captured accessor — "
            "then CI's 3.10 red is not reproducible here and this file cannot "
            "defend the cure: " + result.stdout
        )

    def test_the_shipped_world_reaches_a_pre_captured_accessor(self):
        """The cure, measured against the shape that defeated the bare patch."""
        result = self._run(_FAKE_ACCESSOR + _WORLD_B + self.PROBE)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "ACCESSOR_DENIED: YES" in result.stdout, (
            "the shipped world left a pre-captured accessor holding the real "
            "function — this is exactly the 3.10 red: " + result.stdout
        )

    def test_world_a_also_reaches_a_pre_captured_accessor(self):
        """Both worlds carry the cure, so both are measured against the shape (A is the one CI reddened)."""
        result = self._run(_FAKE_ACCESSOR + _WORLD_A + self.PROBE)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "ACCESSOR_DENIED: YES" in result.stdout, (
            "world A left a pre-captured accessor holding the real function — "
            "this is CI's 3.10 red exactly: " + result.stdout
        )

    def test_the_shipped_world_still_arms_where_no_accessor_exists(self):
        """3.11+ — the ``hasattr`` guard must not turn the world into a no-op."""
        result = self._run(_WORLD_A + _RESOLVE_CONTROL)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "RESOLVE_DIES: YES" in result.stdout, result.stdout

    RESOLVE_PROBE = """
import pathlib as _p

print("RESOLVED: " + str(_p._normal_accessor.realpath("/tmp")))
"""

    def test_the_ntpath_wrapper_resolves_the_path_not_the_accessor(self):
        """@memory's return-value pin, cured of the platform it was importing.

        A bound wrapper eats the path into ``*a`` and still raises, so only the return value
        (denial off) tells them apart; a sentinel keeps the host's path module from answering.
        """
        result = self._run(_SENTINEL_REALPATH + _FAKE_ACCESSOR + _NTPATH_WRAPPER + self.RESOLVE_PROBE)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "RESOLVED: /tmp" in result.stdout, (
            "the wrapper did not receive the path it was handed — it is arriving "
            "bound and passing the accessor through: " + result.stdout
        )

    def test_the_nt_emulation_reproduces_the_ci_red_without_the_sentinel(self):
        """Red-first, locally: the failure @devpulse relayed, rebuilt on this host.

        If this stops producing ``D:\\tmp``, the emulation cannot express the bug and the litmus proves nothing.
        """
        result = self._run(_NT_EMULATION + _FAKE_ACCESSOR + _NTPATH_WRAPPER + self.RESOLVE_PROBE)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "RESOLVED: D:\\tmp" in result.stdout, (
            "the nt emulation no longer reproduces the drive-relative spelling, "
            "so it cannot defend the sentinel: " + result.stdout
        )

    def test_the_sentinel_gives_the_same_verdict_under_either_platform(self):
        """@devpulse's litmus: run the probe under the OPPOSITE platform's
        emulation and require the verdict not to move.

        The comparison is the pin: revert the sentinel AND neuter it and the whole file passes
        (compound mutant). Do not delete it as redundant with the literal check below.
        """
        here = self._run(_SENTINEL_REALPATH + _FAKE_ACCESSOR + _NTPATH_WRAPPER + self.RESOLVE_PROBE)
        as_nt = self._run(_NT_EMULATION + _SENTINEL_REALPATH + _FAKE_ACCESSOR + _NTPATH_WRAPPER + self.RESOLVE_PROBE)

        assert here.returncode == 0, here.stdout + here.stderr
        assert as_nt.returncode == 0, as_nt.stdout + as_nt.stderr
        assert here.stdout == as_nt.stdout, (
            "the verdict moved when the platform did — this pin is measuring the "
            f"host rather than the wrapper.\n  here: {here.stdout!r}\n  as nt: {as_nt.stdout!r}"
        )
        assert "RESOLVED: /tmp" in here.stdout, here.stdout


class TestTheFenceLetsKinThroughWithNoCwd:
    """The fence (handlers/__init__.py, v2) survives a dead cwd and still lets kin in.

    Both resolve() sites fall back to the raw spelling on OSError; a kin seat must still read as kin.
    FENCE_FRESH proves no preload cached the handlers, which would let the pin pass unrun.
    """

    BODY = """
import sys

print("FENCE_FRESH: " + ("NO" if "aipass.drone.apps.handlers" in sys.modules else "YES"))
from aipass.drone.tests import support_fence

print("FENCE: " + support_fence._run("pkg"))
"""

    @pytest.mark.parametrize("world", [_WORLD_A, _WORLD_B], ids=["ntpath_getcwd_denied", "realpath_denied"])
    def test_the_kin_probe_is_allowed_when_every_resolve_dies(self, world: str) -> None:
        result = _run_world(world, _RESOLVE_CONTROL, self.BODY)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "RESOLVE_DIES: YES" in result.stdout, "the world did not arm.\n" + result.stdout
        assert "FENCE_FRESH: YES" in result.stdout, "the fence was imported before the probe.\n" + result.stdout
        assert "FENCE: ALLOWED" in result.stdout, result.stdout


class TestNoModuleLevelLocationCallSurvives:
    """The structural half, because behaviour cannot reach every reintroduction.

    Mutant M3: ``inspect.stack()`` restored in ``_guard_branch_access``'s caller-is-None branch
    left every import-shaped pin green. The ban is on the call, never the string, so docstrings
    that spell the defect stay legal.
    """

    BANNED_ATTRS = frozenset({"resolve", "cwd", "getcwd", "realpath", "abspath"})

    @staticmethod
    def _apps_sources(root: Path | None = None) -> list[Path]:
        root = root or Path(drone_apps.__file__).parent
        return [p for p in sorted(root.rglob("*.py")) if not SANDBOX_DIRS.intersection(p.relative_to(root).parts)]

    @staticmethod
    def _catches_oserror(node: ast.Try) -> bool:
        """A try whose handlers catch OSError by name, alone or in a tuple."""
        for handler in node.handlers:
            caught = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
            if any(isinstance(c, ast.Name) and c.id == "OSError" for c in caught):
                return True
        return False

    @staticmethod
    def _module_level_location_calls(tree: ast.Module) -> list[tuple[int, str]]:
        """Calls that infer a location and are evaluated when the module loads.

        The body of a module-level try catching OSError is guarded; its handlers, else and finally are not.
        """
        found = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(node, ast.Try) and TestNoModuleLevelLocationCallSurvives._catches_oserror(node):
                roots: list[ast.AST] = [*node.handlers, *node.orelse, *node.finalbody]
            else:
                roots = [node]
            for sub in (s for root in roots for s in ast.walk(root)):
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

    def test_no_module_level_resolve_or_cwd_read_anywhere_in_apps(self):
        offenders = []
        for source in self._apps_sources():
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for lineno, text in self._module_level_location_calls(tree):
                offenders.append(f"{source.name}:{lineno}  {text}")

        assert offenders == [], (
            "module-level location calls crash the import on a Windows box with no cwd; "
            "route them through handlers/module_root.module_file(): " + ", ".join(offenders)
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

    # Negative controls: a detector that convicts nothing and one that convicts everything look
    # identical in a green summary, so both run against source they must and must not flag.

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
        tree = ast.parse(
            "from pathlib import Path\n"
            "try:\n    ROOT = Path(__file__).resolve()\nexcept OSError:\n    ROOT = Path(__file__)\n"
        )
        assert self._module_level_location_calls(tree) == [], "a caught raise cannot kill the import"

    def test_the_module_level_detector_convicts_a_resolve_guarded_by_another_exception(self):
        tree = ast.parse(
            "from pathlib import Path\ntry:\n    ROOT = Path(__file__).resolve()\nexcept ValueError:\n    ROOT = None\n"
        )
        assert self._module_level_location_calls(tree), "a try that lets OSError through guards nothing"

    def test_the_module_level_detector_convicts_a_resolve_in_the_handler(self):
        tree = ast.parse("import os\ntry:\n    pass\nexcept OSError:\n    ROOT = os.path.realpath('.')\n")
        assert self._module_level_location_calls(tree), "the handler itself runs unguarded"

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
