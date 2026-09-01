# =================== AIPass ====================
# Name: test_dead_cwd_imports.py
# Description: Windows dead-cwd import defect - every api module imports without a readable cwd
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""No api module may read the working directory to be IMPORTED.

THE DEFECT (measured on the Windows CI gate 2026-08-31, @memory's finding):
ntpath.realpath calls os.getcwd() UNCONDITIONALLY - not only for relative
paths, the way posixpath does - and Path.resolve() routes through it. So on
Windows every Path(__file__).resolve() REACHED AT IMPORT is an import-time
working-directory dependency: a process whose cwd has been deleted cannot
import the module at all. On POSIX the equivalent raise happens earlier and
inside a try inspect already owns, which is why this was invisible on Linux
for as long as it existed.

The discriminator is REACHED AT IMPORT, not written at module scope, so these
pins RUN the imports rather than grepping for spellings. A grep finds
spellings; only the run finds reachability.

TWO WORLDS, because one cannot convict both species:

  World A - wrap os.path.realpath so it reads os.getcwd() first (emulating
  ntpath), then deny os.getcwd. Convicts a raw resolve(). It CANNOT convict
  inspect.stack: denying getcwd kills abspath, so getmodule dies at
  getabsfile INSIDE inspect's own except and stack() completes green for the
  wrong reason (@daemon measured this).

  World B - deny os.path.realpath directly and leave abspath working.
  Convicts inspect.stack via getmodule's unguarded realpath at
  inspect.py:1009.

MEASURED IN THIS BRANCH: 61/61 modules red in both worlds before the cure.
The handlers guard masked everything (apps/__init__ does `from . import
handlers`, so every module died there first); curing it left 49/61, and the
traceback named ONE remaining line - json_handler.py:43's API_ROOT constant,
which nearly every module in this tree imports. 0/61 after both cures.
"""

import ast
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# api/tests/ -> api/
BRANCH_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BRANCH_ROOT.parent.parent.parent
GUARD_FILE = BRANCH_ROOT / "apps" / "handlers" / "__init__.py"

# Cross-branch deps api imports at module scope. Preloaded in the HEALTHY world
# because their cure is their own build - this file measures api only.
# aipass.trigger is deliberately NOT preloaded: usage_tracker imports it lazily
# inside a function, so it is never reached at import, and a preload is a claim
# you stop testing (@flow's rule).
PRELOAD = [
    "aipass.prax",
    "aipass.cli",
    "aipass.drone",
    "aipass.ai_mail",
    "aipass.skills.lib.screen_lock",
    "aipass.hooks.apps.sound",
]


def _api_modules() -> list[str]:
    """Every importable api module, as dotted names."""
    names = []
    for path in sorted((BRANCH_ROOT / "apps").rglob("*.py")):
        if ".archive" in path.parts or "parked" in path.parts:
            continue
        rel = path.relative_to(BRANCH_ROOT).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts.pop()
        names.append(".".join(["aipass", "api", *parts]))
    return names


_PROBE = """
import importlib, json, os, sys

WORLD = os.environ["PROBE_WORLD"]
MODULES = json.loads(os.environ["PROBE_MODULES"])
PRELOAD = json.loads(os.environ["PROBE_PRELOAD"])

preload_failed = {}
for name in PRELOAD:
    try:
        importlib.import_module(name)
    except Exception as e:
        preload_failed[name] = f"{type(e).__name__}: {e}"

_real_realpath = os.path.realpath

if WORLD == "A":
    def realpath_reads_cwd(p, *a, **k):
        os.getcwd()
        return _real_realpath(p, *a, **k)
    os.path.realpath = realpath_reads_cwd
    def dead_getcwd(*a, **k):
        raise FileNotFoundError(2, "No such file or directory")
    os.getcwd = dead_getcwd
elif WORLD == "B":
    def dead_realpath(*a, **k):
        raise OSError(2, "No such file or directory")
    os.path.realpath = dead_realpath

# Positive control, and the negative control FOR it: the injection must deny
# the call the defect actually makes, and must NOT be firing on everything.
from pathlib import Path as _P
if WORLD == "A":
    try:
        _P(".").resolve()
        control_live, control_no = False, None
    except OSError:
        control_live = True
        try:
            os.path.basename("/tmp/x")
            control_no = True
        except OSError:
            control_no = False
else:
    try:
        os.path.realpath("/tmp/x")
        control_live, control_no = False, None
    except OSError:
        control_live = True
        try:
            os.path.abspath("/tmp/x")
            control_no = True
        except OSError:
            control_no = False

def _purge():
    for n in [m for m in sys.modules if m == "aipass.api" or m.startswith("aipass.api.")]:
        del sys.modules[n]

results = {}
for mod in MODULES:
    _purge()
    try:
        importlib.import_module(mod)
        results[mod] = "OK"
    except Exception as e:
        results[mod] = f"{type(e).__name__}: {str(e)[:160]}"

print("@@PROBE@@" + json.dumps({
    "world": WORLD, "control_live": control_live, "control_can_say_no": control_no,
    "preload_failed": preload_failed, "results": results,
}))
"""


def _run_probe(world: str, modules: list[str]) -> dict:
    """Run the probe in a child interpreter under a STRING pseudo-frame.

    compile() with an angle-bracket filename, never stdin: linecache caches
    stdin and a stdin-fed probe reports green for the wrong reason (@hooks'
    finding).
    """
    env = dict(os.environ)
    env["PROBE_WORLD"] = world
    env["PROBE_MODULES"] = json.dumps(modules)
    env["PROBE_PRELOAD"] = json.dumps(PRELOAD)
    runner = f"import sys\nsrc = {_PROBE!r}\nexec(compile(src, '<aipass-deadcwd-probe>', 'exec'))\n"
    proc = subprocess.run(
        [sys.executable, "-c", runner],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("@@PROBE@@"):
            return json.loads(line[len("@@PROBE@@") :])
    raise AssertionError(f"probe produced no verdict\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")


class TestEveryModuleImportsWithoutAReadableCwd:
    """The import fence: no api module may need a cwd to be imported."""

    @pytest.mark.parametrize("world", ["A", "B"])
    def test_the_injection_is_live_and_can_still_say_no(self, world: str) -> None:
        """The positive control fires, and it is not firing indiscriminately.

        A CONTROL_LIVE probe that cannot report its own defeat turns every pin
        below it vacuously green (@spawn's finding, relayed by @memory).
        """
        report = _run_probe(world, [])
        assert report["control_live"] is True, f"world {world}: the denial never fired"
        assert report["control_can_say_no"] is True, (
            f"world {world}: the denial is indiscriminate - it fires on calls the defect never makes"
        )

    @pytest.mark.parametrize("world", ["A", "B"])
    def test_no_api_module_dies_on_import(self, world: str) -> None:
        """Every api module imports in a process whose cwd cannot be read."""
        modules = _api_modules()
        assert modules, "no api modules discovered - the probe would pass vacuously"
        report = _run_probe(world, modules)
        assert report["control_live"] is True, "injection not live - result says nothing"
        assert not report["preload_failed"], f"preload broke in the healthy world: {report['preload_failed']}"
        dead = {k: v for k, v in report["results"].items() if v != "OK"}
        assert not dead, (
            f"world {world}: {len(dead)} of {len(modules)} api modules need a cwd to import:\n"
            + "\n".join(f"  {k} -> {v}" for k, v in sorted(dead.items()))
        )


# --------------------------------------------------------------------------
# The pin-shape hole: the deleted inspect.stack() walk is UNREACHABLE from any
# import-shaped test (apps/__init__ always supplies a real-file frame), so
# restoring the defect leaves every behavioural pin green (@trigger measured
# this). Only a structural ban convicts it.
#
# An AST ban, never a string ban: the guard's docstring NAMES inspect.stack
# while explaining the defect, and a spelling ban convicts the explanation.
# --------------------------------------------------------------------------


def _inspect_stack_calls(source: str) -> list[int]:
    """Line numbers of every `inspect.stack(...)` CALL in *source*."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "stack"
            and isinstance(func.value, ast.Name)
            and func.value.id == "inspect"
        ):
            found.append(node.lineno)
    return found


class TestTheGuardNeverWalksInspectStack:
    """inspect.stack() may not return to the handlers guard."""

    def test_the_guard_file_calls_inspect_stack_nowhere(self) -> None:
        hits = _inspect_stack_calls(GUARD_FILE.read_text(encoding="utf-8"))
        assert hits == [], (
            f"{GUARD_FILE.name} calls inspect.stack() at line(s) {hits} - "
            "it needs a readable cwd before any of the guard's own code runs"
        )

    def test_the_ban_convicts_a_real_call(self) -> None:
        """Positive control: the checker is not simply returning []."""
        assert _inspect_stack_calls("import inspect\nx = inspect.stack()\n") == [2]

    def test_the_ban_ignores_a_docstring_that_names_it(self) -> None:
        """Negative control: the guard's own explanation must not convict it."""
        source = '"""Walks frames rather than inspect.stack(), which reads the cwd."""\n'
        assert _inspect_stack_calls(source) == []

    def test_the_ban_ignores_an_unrelated_stack_attribute(self) -> None:
        """Negative control: numpy.stack is a different function entirely."""
        assert _inspect_stack_calls("import numpy\ny = numpy.stack([1, 2])\n") == []


# --------------------------------------------------------------------------
# The runtime species: json_handler's caller auto-detection runs on the
# log_operation hot path. It must not crash without a cwd - and it must still
# ANSWER. Returning "unknown" for every caller satisfies a not-crash assertion
# and destroys the audit trail (@flow's pin shape).
# --------------------------------------------------------------------------

_CALLER_PROBE = """
import importlib, json, os, sys

for name in json.loads(os.environ["PROBE_PRELOAD"]):
    importlib.import_module(name)

sys.path.insert(0, os.environ["PROBE_TMP"])
jh = importlib.import_module("aipass.api.apps.handlers.json.json_handler")
named = importlib.import_module("deadcwd_named_caller")

def dead_realpath(*a, **k):
    raise OSError(2, "No such file or directory")
os.path.realpath = dead_realpath

try:
    os.path.realpath("/tmp/x")
    control_live = False
except OSError:
    control_live = True

try:
    answer = named.ask(jh)
    err = None
except Exception as e:
    answer, err = None, f"{type(e).__name__}: {e}"

print("@@CALLER@@" + json.dumps({"control_live": control_live, "answer": answer, "error": err}))
"""


class TestCallerDetectionStillAnswersWithoutARealpath:
    """log_operation's auto-detect must survive world B AND still name the caller."""

    def test_it_names_the_calling_module_not_unknown(self, tmp_path: Path) -> None:
        # A REAL file supplies the caller frame, while the probe's own top-level
        # frame is a string pseudo-frame - the shape the defect actually meets.
        (tmp_path / "deadcwd_named_caller.py").write_text(
            textwrap.dedent(
                """
                def ask(jh):
                    # Mimics log_operation's depth: _get_caller_module_name
                    # skips [0]=itself, [1]=its caller, [2]=the real caller.
                    def stand_in_for_log_operation():
                        return jh._get_caller_module_name()
                    return stand_in_for_log_operation()
                """
            ),
            encoding="utf-8",
        )
        env = dict(os.environ)
        env["PROBE_PRELOAD"] = json.dumps(PRELOAD)
        env["PROBE_TMP"] = str(tmp_path)
        runner = f"import sys\nsrc = {_CALLER_PROBE!r}\nexec(compile(src, '<aipass-caller-probe>', 'exec'))\n"
        proc = subprocess.run(
            [sys.executable, "-c", runner],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        verdict = None
        for line in proc.stdout.splitlines():
            if line.startswith("@@CALLER@@"):
                verdict = json.loads(line[len("@@CALLER@@") :])
        assert verdict is not None, f"probe produced no verdict\n{proc.stdout}\n{proc.stderr}"
        assert verdict["control_live"] is True, "realpath denial never fired - result says nothing"
        assert verdict["error"] is None, f"caller detection crashed without a realpath: {verdict['error']}"
        assert verdict["answer"] == "deadcwd_named_caller", (
            f"caller detection answered {verdict['answer']!r} - a not-crash that names nobody "
            "destroys the audit trail it exists to write"
        )
