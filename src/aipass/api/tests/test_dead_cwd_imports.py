# =================== AIPass ====================
# Name: test_dead_cwd_imports.py
# Description: Windows dead-cwd import defect - every api module imports without a readable cwd
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests that every module under apps/ imports without a readable cwd, and apps/handlers/__init__.py's guard."""

# ntpath.realpath calls os.getcwd() unconditionally and Path.resolve() goes
# through it, so on Windows a resolve() REACHED AT IMPORT fails once the cwd is
# gone. Reachability, not spelling: these pins run the imports, never grep.
# Two worlds, because one cannot convict both species:
#   A - realpath reads getcwd first (as ntpath does), getcwd denied. Convicts a
#   raw resolve(); inspect.stack dies inside inspect's own except and passes.
#   B - realpath denied, abspath alive. Convicts inspect.stack via getmodule.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every api module parses; this file measures only the import's cwd
# seedgo: no-test-needed(windows_compat) — a real Windows host's ntpath; world A emulates it here on POSIX
# seedgo: no-test-needed(covered_elsewhere) — POSIX-only imports on Windows, tests/test_windows_import.py

import ast
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

BRANCH_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BRANCH_ROOT.parent.parent.parent
GUARD_FILE = BRANCH_ROOT / "apps" / "handlers" / "__init__.py"

# Cross-branch deps preloaded in the healthy world: this file measures api only.
# aipass.trigger is not: usage_tracker imports it lazily, and a preload stops the test.
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
# An absolute path that is only ever handed to os.path, never opened.
ANY_ABS = os.path.join(os.sep, "deadcwd_probe", "x")

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
            os.path.basename(ANY_ABS)
            control_no = True
        except OSError:
            control_no = False
else:
    try:
        os.path.realpath(ANY_ABS)
        control_live, control_no = False, None
    except OSError:
        control_live = True
        try:
            os.path.abspath(ANY_ABS)
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
    stdin and a stdin-fed probe reports green for the wrong reason.
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
        encoding="utf-8",
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
        """The positive control fires, and it is not firing indiscriminately."""
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


# An inspect.stack() walk in the guard is unreachable from any import-shaped test
# (a real-file frame is always there), so only a structural ban convicts it. AST,
# not a string ban: the guard's docstring names inspect.stack.


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


# Caller auto-detection runs on the log_operation hot path: it must survive no
# cwd AND still answer; "unknown" for every caller destroys the audit trail.

_CALLER_PROBE = """
import importlib, json, os, sys

# Every write this world makes lands under the probe's own tmp_path, never in
# the real api_json/: since DPLAN-0325 the one service reads this seam on every
# call, and the probe below asks it to actually WRITE a log document.
os.environ["AIPASS_TEST_LOG_DIR"] = os.path.join(os.environ["PROBE_TMP"], "_aipass_json_seam")

for name in json.loads(os.environ["PROBE_PRELOAD"]):
    importlib.import_module(name)

sys.path.insert(0, os.environ["PROBE_TMP"])
jh = importlib.import_module("aipass.api.apps.handlers.json.json_handler")
named = importlib.import_module("deadcwd_named_caller")

ANY_ABS = os.path.join(os.sep, "deadcwd_probe", "x")

def dead_realpath(*a, **k):
    raise OSError(2, "No such file or directory")
os.path.realpath = dead_realpath

try:
    os.path.realpath(ANY_ABS)
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
        # A real file supplies the caller frame under a string pseudo-frame. Through
        # log_operation: the service reads _getframe(2), so a direct call is one short.
        (tmp_path / "deadcwd_named_caller.py").write_text(
            textwrap.dedent(
                """
                def ask(jh):
                    jh.log_operation("dead_cwd_probe", {"ok": True})
                    directory = jh.get_json_path("probe", "log").parent
                    written = sorted(p.name for p in directory.glob("*_log.json"))
                    return ",".join(n[: -len("_log.json")] for n in written)
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
            encoding="utf-8",
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
