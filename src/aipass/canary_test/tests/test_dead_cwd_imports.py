# =================== AIPass ====================
# Name: test_dead_cwd_imports.py
# Description: Dead-cwd fence pins (cwd really removed) and the AST ban on inspect.stack
# Version: 1.4.0
# Created: 2026-08-31
# Modified: 2026-11-25
# =============================================

"""Tests for apps/handlers/__init__.py: the fence under a removed cwd, and no inspect.stack call."""

# The declared pass — nothing: the fence is the only file these pins read or run.

import ast
import subprocess
import sys
from pathlib import Path

BRANCH_ROOT = Path(__file__).resolve().parents[1]
GUARD_FILE = BRANCH_ROOT / "apps" / "handlers" / "__init__.py"


# Only a source-shape pin catches an inspect.stack walk: apps/__init__.py always supplies a real-file
# frame, so every import-shaped pin stays green. An AST ban, never a string ban: docstrings name it.


def _inspect_stack_calls(source: str) -> list:
    """Return line numbers of every inspect.stack() CALL in source."""
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


def test_guard_contains_no_inspect_stack_call():
    """BAN: the import guard never calls inspect.stack(); its unguarded realpath needs a readable cwd."""
    offenders = _inspect_stack_calls(GUARD_FILE.read_text(encoding="utf-8"))
    assert offenders == [], (
        f"inspect.stack() called at {GUARD_FILE}:{offenders} — walk frames "
        "with sys._getframe instead; see this module's docstring."
    )


def test_ast_ban_convicts_a_real_call():
    """POSITIVE CONTROL: the ban detects the construct it bans."""
    assert _inspect_stack_calls("import inspect\nx = inspect.stack()\n") == [2]


def test_ast_ban_ignores_the_name_in_a_docstring():
    """NEGATIVE CONTROL: prose naming inspect.stack() is not a call."""
    source = '"""Do not call inspect.stack() here."""\nx = 1\n'
    assert _inspect_stack_calls(source) == []


def test_ast_ban_ignores_an_unrelated_stack_attribute():
    """NEGATIVE CONTROL: numpy.stack is a different function entirely."""
    source = "import numpy\ny = numpy.stack([1, 2])\n"
    assert _inspect_stack_calls(source) == []


# The quiet species (a path resolving fine to the wrong place) has no site here: canary_test computes no
# cwd-sensitive module-level path, and sentry's cross-branch contract pins the json write destination.


# The fence reads frame paths, and a path read must not kill an import whose cwd is gone. The child runs
# support_fence.py after removing its cwd; it reports ARM_CWD_DEAD before the probe runs, or the pin is vacuous.

FENCE_PROBE = BRANCH_ROOT / "tests" / "support_fence.py"

_DEAD_CWD_LAUNCHER = """
import os, runpy, sys
seat, shape, doomed = sys.argv[1], sys.argv[2], sys.argv[3]
os.chdir(doomed)
os.rmdir(doomed)
try:
    os.getcwd()
    print("ARM_CWD_ALIVE")
except OSError:
    print("ARM_CWD_DEAD")
sys.argv = [seat, shape]
runpy.run_path(seat, run_name="__main__")
"""


def _probe_with_cwd_removed(seat: Path, tmp_path: Path) -> list:
    """Run the fence probe's 'pkg' shape from `seat` in a child whose cwd is gone; its output lines."""
    doomed = tmp_path / "doomed"
    doomed.mkdir()
    done = subprocess.run(
        [sys.executable, "-c", _DEAD_CWD_LAUNCHER, str(seat), "pkg", str(doomed)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=str(tmp_path),
    )
    assert done.returncode == 0, done.stderr[-1200:]
    return done.stdout.strip().splitlines()


def test_the_fence_lets_kin_through_with_its_cwd_removed(tmp_path):
    """The kin seat imports its own handlers in a process with no cwd; proven by its mutants."""
    lines = _probe_with_cwd_removed(FENCE_PROBE, tmp_path)

    assert lines[0] == "ARM_CWD_DEAD", lines
    assert lines[-1] == "ALLOWED", lines


def test_an_elsewhere_caller_is_still_refused_with_its_cwd_removed(tmp_path):
    """A seat outside any aipass tree is refused and named, cwd or no cwd; proven by its mutants."""
    seat = tmp_path / "elsewhere" / "probe.py"
    seat.parent.mkdir(parents=True)
    seat.write_bytes(FENCE_PROBE.read_bytes())

    lines = _probe_with_cwd_removed(seat, tmp_path)

    assert lines[0] == "ARM_CWD_DEAD", lines
    assert lines[-1] == "DENIED Caller branch: unknown", lines
