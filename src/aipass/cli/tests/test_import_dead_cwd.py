# =================== AIPass ====================
# META DATA HEADER
# Name: test_import_dead_cwd.py - cli imports without a readable cwd
# Description: Every cli module imports, the fence decides, and call-time sites run, with the cwd deleted
# Version: 1.2.0
# Created: 2026-08-31
# Modified: 2026-10-17
# Category: cli/tests
# =============================================

"""Tests for apps/handlers/__init__.py and every cli import-time site — imports with no readable cwd."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — the OS cwd read behind Path.resolve(); emulated, the instrument tests pin it
# seedgo: no-test-needed(standard) — the fence with a healthy cwd; tests/test_handlers_fence.py covers it

import ast
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from aipass.cli.tests import support_fence

# ntpath.realpath reads os.getcwd() unconditionally, so on Windows Path.resolve() and
# inspect.stack() at import die with a deleted cwd. Each world is a child process that
# emulates ntpath before any aipass import; abspath must not raise as posixpath's does,
# or getmodule() swallows the error and a reintroduced inspect.stack() stays green.

KIN_PROBE = Path(support_fence.__file__)

# Peers load before the denial, so a failure names a cli site, never a dependency's.
_PRELOAD = r"""
import rich.console  # noqa: F401
import inspect  # noqa: F401
import linecache  # noqa: F401
import runpy  # noqa: F401
"""

_NTPATH_PREAMBLE = (
    _PRELOAD
    + r"""
import os

_real_realpath = os.path.realpath
_real_abspath = os.path.abspath


def _ntpath_realpath(path, **kw):
    os.getcwd()  # ntpath.realpath reads cwd before checking absoluteness
    return _real_realpath(path, **kw)


def _ntpath_abspath(path):
    # ntpath.abspath falls back rather than raising the way posixpath does.
    try:
        return _real_abspath(path)
    except OSError:
        return path


os.path.realpath = _ntpath_realpath
os.path.abspath = _ntpath_abspath


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd

# Probe against the defect ITSELF, not a proxy: does inspect.stack() die in this
# world? If it does not, this pin proves nothing and says so.
import inspect

try:
    inspect.stack()
    print("STACK_SURVIVES")
except FileNotFoundError:
    print("STACK_DIES")
"""
)

# Import-time sites reached the way the fleet reaches them, one print per step.
_SITES = r"""
import aipass.cli.apps.modules  # noqa: F401
print("MODULES_OK")
from aipass.cli import console  # noqa: F401
print("IMPORTED")
"""

SWEEP_WORLD = _NTPATH_PREAMBLE + _SITES

# The call-time site: display.print_help() resolves __file__.
CALL_TIME_WORLD = (
    _NTPATH_PREAMBLE
    + r"""
import io
import contextlib

from aipass.cli.apps.modules import display

with contextlib.redirect_stdout(io.StringIO()):
    display.print_help()
print("HELP_OK")
print("IMPORTED")
"""
)


def _fence_world(seat: Path, shape: str) -> str:
    """The dead-cwd world, then the fence probe at `seat` run as a script."""
    return _NTPATH_PREAMBLE + (
        f"\nimport sys\nsys.argv[1:] = [{shape!r}]\nrunpy.run_path({str(seat)!r}, run_name='__main__')\n"
    )


def _run(world: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", world],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def _assert_world_is_hostile(out: str) -> None:
    """The instrument must be able to fire, or every assertion below is vacuous."""
    assert "STACK_DIES" in out, (
        "inspect.stack() survived the ntpath-shaped denial - the instrument no "
        f"longer reaches the defect and this pin proves nothing:\n{out}"
    )


def _inspect_stack_call_lines(tree: ast.Module) -> list:
    """Line numbers of every inspect.stack() CALL in a parsed module."""
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "stack":
            if isinstance(func.value, ast.Name) and func.value.id == "inspect":
                lines.append(node.lineno)
    return lines


@pytest.fixture
def elsewhere_seat(tmp_path: Path) -> Path:
    """A copy of the fence probe under a path with no branch segment at all."""
    seat = tmp_path / "elsewhere" / "probe.py"
    seat.parent.mkdir(parents=True)
    shutil.copy(KIN_PROBE, seat)
    return seat


class TestTheInstrumentItself:
    """A positive control needs its own negative control (@spawn's rule)."""

    def test_the_denied_world_actually_kills_inspect_stack(self):
        """If this goes green-by-survival, every other test in the file lies."""
        result = _run(_NTPATH_PREAMBLE + "\nprint('IMPORTED')\n")
        _assert_world_is_hostile(result.stdout)

    def test_the_denied_world_is_not_so_hostile_that_everything_dies(self):
        """The negative control: a plain stdlib import must still work."""
        result = _run(
            _NTPATH_PREAMBLE
            + r"""
import json  # noqa: F401
import collections  # noqa: F401
print("STDLIB_OK")
print("IMPORTED")
"""
        )
        assert "STDLIB_OK" in result.stdout, (
            "even plain stdlib imports die in this world - it is too hostile to "
            f"prove anything about cli:\nstdout={result.stdout}\nstderr={result.stderr}"
        )


class TestTheFenceWithoutACwd:
    """The fence resolves every frame's path; with no cwd it must still decide."""

    def test_kin_is_allowed_with_the_cwd_deleted(self):
        """This branch's own probe imports its handlers: allowed, not crashed."""
        result = _run(_fence_world(KIN_PROBE, "pkg"))
        _assert_world_is_hostile(result.stdout)
        assert result.stdout.strip().splitlines()[-1] == "ALLOWED", (
            f"the fence did not allow kin without a cwd:\nstdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_an_elsewhere_caller_is_still_refused_with_the_cwd_deleted(self, elsewhere_seat):
        """A dead cwd must not open the fence: a script outside any aipass tree is refused."""
        result = _run(_fence_world(elsewhere_seat, "pkg"))
        _assert_world_is_hostile(result.stdout)
        assert result.stdout.strip().splitlines()[-1] == "DENIED Caller branch: unknown", (
            f"the fence did not refuse a foreign caller without a cwd:\nstdout={result.stdout}\nstderr={result.stderr}"
        )


class TestImportTimeSites:
    def test_every_import_time_site_survives_a_denied_cwd(self):
        """The whole branch, which is what the fleet actually imports."""
        result = _run(SWEEP_WORLD)
        _assert_world_is_hostile(result.stdout)
        assert "IMPORTED" in result.stdout, (
            f"a cli import died under the dead-cwd world:\nstdout={result.stdout}\nstderr={result.stderr}"
        )


class TestCallTimeSites:
    def test_print_help_survives_a_denied_cwd(self):
        """print_help() resolves __file__ at call time; `drone @cli --help` must not traceback."""
        result = _run(CALL_TIME_WORLD)
        _assert_world_is_hostile(result.stdout)
        assert "HELP_OK" in result.stdout, (
            f"print_help() still depends on a readable cwd:\nstdout={result.stdout}\nstderr={result.stderr}"
        )


class TestStructuralSweep:
    """AST ban on inspect.stack() in the files that run at import; parsed, not grepped."""

    _IMPORT_TIME_FILES = (
        "apps/handlers/__init__.py",
        "apps/handlers/json/json_handler.py",
        "apps/modules/display.py",
    )

    def _branch_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_no_inspect_stack_call_in_import_time_files(self):
        offenders = []
        for rel in self._IMPORT_TIME_FILES:
            path = self._branch_root() / rel
            assert path.exists(), f"pin names a file that does not exist: {rel}"
            tree = ast.parse(path.read_text(encoding="utf-8"))
            offenders += [f"{rel}:{line}" for line in _inspect_stack_call_lines(tree)]

        assert not offenders, (
            "inspect.stack() is back in a file that runs at import time. It "
            "needs a readable cwd before any of the calling function's own code "
            "runs, so this crashes the import on Windows when the cwd is gone — "
            "and most of the fleet imports this branch. Use sys._getframe over "
            f"f_code.co_filename instead. Offenders: {offenders}"
        )

    def test_the_ast_pin_can_actually_fail(self):
        """Positive control: the matcher must convict the shape it bans."""
        tree = ast.parse("import inspect\nstack = inspect.stack()\n")
        assert _inspect_stack_call_lines(tree) == [2], (
            "the AST matcher cannot see inspect.stack() — the ban above is vacuous"
        )

    def test_the_ast_pin_does_not_convict_a_docstring(self):
        """A string ban would convict this very file's docstrings. Parsing does not."""
        tree = ast.parse('"""We used to call inspect.stack() here."""\nx = 1\n')
        assert _inspect_stack_call_lines(tree) == [], "prose mentioning inspect.stack() must not count as a call"
