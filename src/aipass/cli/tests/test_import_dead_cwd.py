# ===================AIPASS====================
# META DATA HEADER
# Name: test_import_dead_cwd.py - cli imports without a readable cwd
# Date: 2026-08-31
# Version: 1.0.0
# Category: cli/tests
# =============================================

"""Every cli module must import without a readable working directory.

THE MECHANISM, measured on the Windows CI gate 2026-08-31 (@memory's finding,
reported to this branch by @trigger): ntpath.realpath calls os.getcwd()
UNCONDITIONALLY - not only for relative paths, the way posixpath does - and both
Path.resolve() and inspect.stack() route through it. So on Windows every one of
those reached AT IMPORT is a working-directory read, and a process whose cwd was
deleted cannot import the module at all.

WHY THIS BRANCH, LOUDLY. The handler guard at apps/handlers/__init__.py runs at
IMPORT time, and most of the fleet imports aipass.cli. @trigger could not get
their own dead-cwd pin past this branch: they preload aipass.cli.apps.modules in
the HEALTHY world so their pin can measure their own sites, and marked that
preload TEMPORARY - delete when @cli is cured. @commons and @devpulse carry the
same note. This file is what retires those three preloads.

THE WORLD injects ntpath's behaviour as a CONDITION rather than a platform, so
the defect is reachable from Linux. The injection happens in a child process
before any aipass import, so no module has cached the real functions. In-process
this property is unobservable - the imports already happened - which is why every
world here is a subprocess.

WHY THE NTPATH SHAPE IS REQUIRED, and it cost @trigger an hour before they
warned us: on POSIX every route inspect.stack() takes to os.path.realpath runs
through getabsfile(), whose os.path.abspath raises FileNotFoundError for the
relative "<frozen importlib._bootstrap>" filenames an import stack carries - and
getmodule() CATCHES FileNotFoundError, so the unguarded
`modulesbyfile[os.path.realpath(f)]` below it is never reached. A pin built on a
realpath denial alone therefore goes GREEN against a reintroduced
inspect.stack(): it measures the module-level resolve() next door, not the stack
walk. ntpath has no such early raise. Emulated by giving abspath ntpath's
non-raising behaviour while realpath keeps reading cwd - the injection then
denies the call the DEFECT actually makes (@memory's rule), not one the platform
happens to catch first.
"""

import ast
import subprocess
import sys
from pathlib import Path

# Peers held constant in the HEALTHY world, before the denial, so a failure here
# names a cli site and never a dependency's.
_PRELOAD = r"""
import rich.console  # noqa: F401
import inspect  # noqa: F401
import linecache  # noqa: F401
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

# Every cli site that resolved a path or walked the stack at IMPORT, named one
# per line so a failure says which module died rather than "the branch".
_SITES = r"""
import aipass.cli.apps.handlers  # noqa: F401
print("GUARD_OK")
import aipass.cli.apps.handlers.json.json_handler  # noqa: F401
print("JSON_OK")
import aipass.cli.apps.modules  # noqa: F401
print("MODULES_OK")
import aipass.cli  # noqa: F401
print("IMPORTED")
"""

GUARD_WORLD = (
    _NTPATH_PREAMBLE
    + r"""
import aipass.cli.apps.handlers  # noqa: F401

print("IMPORTED")
"""
)

SWEEP_WORLD = _NTPATH_PREAMBLE + _SITES

# The CALL-time site: log_operation() -> _get_caller_module_name() walked the
# stack too. It never blocked an import, but log_operation is called from across
# the fleet and would have raised in this world.
# The guard's undeterminable-caller path, reached DIRECTLY.
#
# This one needs its own world and it is worth saying why, because the obvious
# pin does not cover it. During a real import there is always a real-file frame
# on the stack - apps/__init__.py does `from . import handlers` - so
# _find_real_caller() finds it and the caller_file-is-None branch is never
# entered. A mutation restoring the deleted second inspect.stack() walk therefore
# SURVIVES every import-shaped pin above (measured, 2026-08-31). The branch is
# only reachable by calling the guard directly, which is what a REPL or a -c
# script does - exactly the callers that branch existed to allow.
GUARD_NONE_PATH_WORLD = (
    _PRELOAD
    + r"""
import os

_real_realpath = os.path.realpath
_real_abspath = os.path.abspath


def _ntpath_realpath(path, **kw):
    os.getcwd()
    return _real_realpath(path, **kw)


def _ntpath_abspath(path):
    try:
        return _real_abspath(path)
    except OSError:
        return path


# Import in the HEALTHY world: this pin is about the guard being CALLED without
# a cwd, not about importing it without one - that is the sweep's job.
import aipass.cli.apps.handlers as h

os.path.realpath = _ntpath_realpath
os.path.abspath = _ntpath_abspath


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd

import inspect

try:
    inspect.stack()
    print("STACK_SURVIVES")
except FileNotFoundError:
    print("STACK_DIES")

# From a -c script every frame is <string> or internals, so this is the
# undeterminable-caller case by construction.
caller = h._find_real_caller()
print(f"CALLER_IS_NONE={caller == (None, None)}")
h._guard_branch_access()
print("IMPORTED")
"""
)

CALL_TIME_WORLD = (
    _NTPATH_PREAMBLE
    + r"""
from aipass.cli.apps.handlers.json import json_handler

# Reached through the service, because that is where it lives now: cli's
# handler is a shim that BINDS the fleet json service (DPLAN-0325), and the
# service owns caller detection for all 18 branches. Imported off cli's own
# shim so the hop cli actually makes is the hop under test.
import sys as _sys

_service = _sys.modules[json_handler.log_operation.__self__.__class__.__module__]

name = _service._get_caller_module_name()
print(f"CALLER_NAME={name}")

# display.print_help() resolves __file__ to print the module reference. Also
# call-time, and `drone @cli --help` in a dead-cwd world should not traceback.
import io
import contextlib

from aipass.cli.apps.modules import display

with contextlib.redirect_stdout(io.StringIO()):
    display.print_help()
print("HELP_OK")
print("IMPORTED")
"""
)


def _run(world: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", world],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _assert_world_is_hostile(out: str) -> None:
    """The instrument must be able to fire, or every assertion below is vacuous."""
    assert "STACK_DIES" in out, (
        "inspect.stack() survived the ntpath-shaped denial - the instrument no "
        f"longer reaches the defect and this pin proves nothing:\n{out}"
    )


class TestTheInstrumentItself:
    """A positive control needs its own negative control (@spawn's rule)."""

    def test_the_denied_world_actually_kills_inspect_stack(self):
        """If this goes green-by-survival, every other test in the file lies."""
        result = _run(_NTPATH_PREAMBLE + "\nprint('IMPORTED')\n")
        _assert_world_is_hostile(result.stdout)

    def test_the_denied_world_is_not_so_hostile_that_everything_dies(self):
        """The negative control: a plain stdlib import must still work.

        Without this, a world that broke ALL imports would satisfy every
        'did not crash' assertion by never getting far enough to crash.
        """
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


class TestImportTimeSites:
    def test_handlers_guard_survives_the_ntpath_shaped_denial(self):
        """The guard must not walk inspect.stack().

        RED against the pre-2026-08-31 spelling: the guard ran at import and
        died at inspect.py:1009 in getmodule, before any of its own code ran.
        """
        result = _run(GUARD_WORLD)
        _assert_world_is_hostile(result.stdout)
        assert "IMPORTED" in result.stdout, (
            f"the handlers guard still depends on a readable cwd:\nstdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_every_import_time_site_survives_a_denied_cwd(self):
        """The whole branch, which is what the fleet actually imports."""
        result = _run(SWEEP_WORLD)
        _assert_world_is_hostile(result.stdout)
        assert "IMPORTED" in result.stdout, (
            f"a cli import died under the dead-cwd world:\nstdout={result.stdout}\nstderr={result.stderr}"
        )


class TestUndeterminableCallerPath:
    """The branch that used to hold a SECOND inspect.stack() walk.

    Both its arms returned None with no side effect - match and fall-through
    alike - so the call could not change the answer. @prax's ruling, and
    @trigger measured the same dead arm in their own copy: a call that needs a
    working directory to compute a value nobody reads is pure exposure. Deleted
    rather than wrapped, and pinned here because no import-shaped test reaches it.
    """

    def test_guard_called_without_a_cwd_allows_an_undeterminable_caller(self):
        result = _run(GUARD_NONE_PATH_WORLD)
        _assert_world_is_hostile(result.stdout)
        assert "CALLER_IS_NONE=True" in result.stdout, (
            "this world no longer produces an undeterminable caller, so it no "
            f"longer exercises the deleted walk:\n{result.stdout}"
        )
        assert "IMPORTED" in result.stdout, (
            "the guard's undeterminable-caller path still reads the cwd:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )


class TestCallTimeSites:
    def test_log_operation_caller_detection_survives_a_denied_cwd(self):
        """_get_caller_module_name walked inspect.stack() too.

        Call-time, so it never blocked an import - but every branch calls
        json_handler.log_operation(), and this would have raised there.
        """
        result = _run(CALL_TIME_WORLD)
        _assert_world_is_hostile(result.stdout)
        assert "IMPORTED" in result.stdout, (
            f"caller detection still depends on a readable cwd:\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "CALLER_NAME=" in result.stdout, f"caller detection did not return a name:\n{result.stdout}"
        assert "HELP_OK" in result.stdout, (
            f"print_help() still depends on a readable cwd:\nstdout={result.stdout}\nstderr={result.stderr}"
        )


class TestStructuralSweep:
    """AST ban on inspect.stack() in the files that run at import.

    REQUIRED BY THE ROLLOUT (@memory's rule, relayed by @devpulse): an
    import-probe cannot see the caller-is-None branch, so a behavioural pin
    alone can miss a reintroduced walk. Measured here and it is not theoretical
    — a mutant restoring the deleted second walk survived every import-shaped
    test in this file before TestUndeterminableCallerPath was added.

    Parsed, not grepped: a string ban convicts docstrings, and this file's own
    docstrings discuss inspect.stack() at length. The two pins are
    complementary, not redundant — this one convicts the CODE, the direct-call
    world convicts the BEHAVIOUR.
    """

    # Files whose module level runs on import of this branch.
    _IMPORT_TIME_FILES = (
        "apps/handlers/__init__.py",
        "apps/handlers/json/json_handler.py",
        "apps/modules/display.py",
    )

    def _branch_root(self) -> Path:
        # tests/ -> cli/
        return Path(__file__).resolve().parents[1]

    def test_no_inspect_stack_call_in_import_time_files(self):
        offenders = []
        for rel in self._IMPORT_TIME_FILES:
            path = self._branch_root() / rel
            assert path.exists(), f"pin names a file that does not exist: {rel}"
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "stack":
                    if isinstance(func.value, ast.Name) and func.value.id == "inspect":
                        offenders.append(f"{rel}:{node.lineno}")

        assert not offenders, (
            "inspect.stack() is back in a file that runs at import time. It "
            "needs a readable cwd before any of the calling function's own code "
            "runs, so this crashes the import on Windows when the cwd is gone — "
            "and most of the fleet imports this branch. Use sys._getframe over "
            f"f_code.co_filename instead. Offenders: {offenders}"
        )

    def test_the_ast_pin_can_actually_fail(self):
        """Positive control: the matcher must convict the shape it bans.

        Without this the test above is satisfied by a matcher that never
        matches anything — which is how the old test_quality check scored
        everyone 100.
        """
        tree = ast.parse("import inspect\nstack = inspect.stack()\n")
        found = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "stack"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "inspect"
        ]
        assert found, "the AST matcher cannot see inspect.stack() — the ban above is vacuous"

    def test_the_ast_pin_does_not_convict_a_docstring(self):
        """A string ban would convict this very file's docstrings. Parsing does not."""
        tree = ast.parse('"""We used to call inspect.stack() here."""\nx = 1\n')
        found = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        assert not found, "prose mentioning inspect.stack() must not count as a call"
