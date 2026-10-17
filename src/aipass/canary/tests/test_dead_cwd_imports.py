# =================== AIPass ====================
# Name: test_dead_cwd_imports.py
# Description: Windows dead-cwd import defect - two-world child pins, live-injection controls, AST ban on inspect.stack
# Version: 1.3.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/__init__.py and every canary package, imported under a dead cwd."""

# The declared pass — nothing: every canary package and every command module is probed in both worlds.

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

# ntpath.realpath reads os.getcwd() unconditionally (posixpath only for relative paths) and Path.resolve()
# routes through it, so on Windows a resolve reached at import kills the import under an unreadable cwd.
# Reached-at-import, not written-at-module-scope, is the test: these pins run the import in a child.
# World A wraps realpath to read the cwd first, then denies getcwd: it convicts a raw Path.resolve(), not
# inspect.stack (on POSIX the denial kills abspath, so getmodule fails inside its own except).
# World B denies realpath and keeps abspath: it convicts inspect.stack() via inspect.py:1009.
# Probes go through -c, never stdin: linecache caches stdin and the probe lies green.

BRANCH_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BRANCH_ROOT.parents[2]
GUARD_FILE = BRANCH_ROOT / "apps" / "handlers" / "__init__.py"

# Command modules are read off apps/modules/ by discover_modules' rule, so a new module is probed unlisted.
COMMAND_MODULES = sorted(
    f"aipass.canary.apps.modules.{path.stem}"
    for path in (BRANCH_ROOT / "apps" / "modules").glob("*.py")
    if not path.name.startswith("_")
)
CANARY_MODULES = [
    "aipass.canary",
    "aipass.canary.apps",
    "aipass.canary.apps.canary",
    "aipass.canary.apps.handlers",
    "aipass.canary.apps.handlers.json",
    "aipass.canary.apps.handlers.json.json_handler",
    "aipass.canary.apps.modules",
    "aipass.canary.apps.plugins",
    *COMMAND_MODULES,
]

# Non-optional sibling imports, preloaded so the denial convicts canary's own code; a preload is a claim
# you stop testing, so nothing behind try/except ImportError belongs here.
PRELOAD = [
    "aipass.cli.apps.modules",
    "aipass.prax",
]

_WORLD_A = """
import os, os.path
_real = os.path.realpath
def realpath(p, *a, **k):
    os.getcwd()
    return _real(p, *a, **k)
os.path.realpath = realpath
def _dead_cwd(*a, **k):
    raise FileNotFoundError(2, "No such file or directory")
os.getcwd = _dead_cwd
"""

_WORLD_B = """
import os, os.path
def _dead_realpath(*a, **k):
    raise FileNotFoundError(2, "No such file or directory")
os.path.realpath = _dead_realpath
"""

WORLDS = {"A": _WORLD_A, "B": _WORLD_B}


def _run_child(body: str) -> subprocess.CompletedProcess:
    """Run body in a child interpreter on a '<string>' pseudo-frame."""
    return subprocess.run(
        [sys.executable, "-c", body],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=str(REPO_ROOT),
    )


def _import_probe(module: str, world: str, inject: bool = True) -> subprocess.CompletedProcess:
    """Import `module` under `world`. inject=False kills the injection."""
    body = (
        "".join(f"import {m}\n" for m in PRELOAD) + (WORLDS[world] if inject else "") + f"import {module}\n"
        "print('PROBE_OK')\n"
    )
    return _run_child(body)


@pytest.mark.parametrize("module", CANARY_MODULES)
@pytest.mark.parametrize("world", sorted(WORLDS))
def test_module_imports_with_no_readable_cwd(module, world):
    """Every canary module imports in a process whose cwd is unreadable."""
    result = _import_probe(module, world)
    assert "PROBE_OK" in result.stdout, f"{module} failed to import in world {world}:\n{result.stderr[-2000:]}"


@pytest.mark.parametrize("world", sorted(WORLDS))
def test_the_injection_is_live(world):
    """Positive control: the denial denies, or every pin above is a vacuous green."""
    body = WORLDS[world] + (
        "from pathlib import Path\n"
        "try:\n"
        "    Path(__file__ if '__file__' in dir() else '/etc/hostname').resolve()\n"
        "    print('CONTROL_DEAD')\n"
        "except OSError:\n"
        "    print('CONTROL_LIVE')\n"
    )
    result = _run_child(body)
    assert "CONTROL_LIVE" in result.stdout, (
        f"world {world} injection did not deny resolve — every pin in this "
        f"file is vacuous until it does:\n{result.stdout}\n{result.stderr[-1000:]}"
    )


@pytest.mark.parametrize("world", sorted(WORLDS))
def test_control_catches_a_dead_injection(world):
    """Negative control for the positive control: with no injection the probe reports CONTROL_DEAD."""
    body = (
        "from pathlib import Path\n"
        "try:\n"
        "    Path('/etc/hostname').resolve()\n"
        "    print('CONTROL_DEAD')\n"
        "except OSError:\n"
        "    print('CONTROL_LIVE')\n"
    )
    result = _run_child(body)
    assert "CONTROL_DEAD" in result.stdout, (
        "with no injection the probe still reported a denial — the probe is "
        f"not measuring the injection:\n{result.stdout}\n{result.stderr[-1000:]}"
    )


# World A's inspect.stack outcome is per-platform, decided by whether abspath survives a getcwd denial.
# POSIX: abspath reads the cwd for a relative path and dies, getmodule returns None, the stack survives.
# Windows: abspath (_getfullpathname) never reads it, getmodule reaches the wrapped realpath, the stack dies.
# Neither is a bug; each row is a live measurement on its platform, so re-derive the table, never delete a row.

STACK_SURVIVES_WORLD_A = os.name != "nt"


def test_world_a_abspath_outcome_is_the_mechanism():
    """The fact the table turns on, measured here, so an interpreter change reds naming the cause."""
    body = _WORLD_A + (
        "import os, os.path\n"
        "try:\n"
        "    os.path.abspath('rel.py')\n"
        "    print('ABSPATH_SURVIVED')\n"
        "except OSError:\n"
        "    print('ABSPATH_DIED')\n"
    )
    result = _run_child(body)
    expected = "ABSPATH_DIED" if os.name != "nt" else "ABSPATH_SURVIVED"
    assert expected in result.stdout, (
        f"on {os.name}, world A's getcwd denial was expected to produce "
        f"{expected} from os.path.abspath. If this changed, the two-world "
        f"split and the stack table below both need re-deriving, not "
        f"deleting:\n{result.stdout}\n{result.stderr[-800:]}"
    )


def test_world_a_stack_outcome_matches_the_platform_table():
    """world A convicts inspect.stack on Windows and not on POSIX."""
    body = _WORLD_A + (
        "import inspect\n"
        "try:\n"
        "    inspect.stack()\n"
        "    print('STACK_SURVIVED')\n"
        "except OSError:\n"
        "    print('STACK_DIED')\n"
    )
    result = _run_child(body)
    expected = "STACK_SURVIVED" if STACK_SURVIVES_WORLD_A else "STACK_DIED"
    assert expected in result.stdout, (
        f"world A on {os.name} was expected to produce {expected} from "
        f"inspect.stack(). See the platform table above: re-derive the table "
        f"rather than deleting the pin, and check "
        f"test_world_a_abspath_outcome_is_the_mechanism first — it names the "
        f"cause:\n{result.stdout}\n{result.stderr[-800:]}"
    )


def test_the_windows_half_of_the_table_reproduces_here():
    """Run the WINDOWS row's mechanism here: with a cwd-free abspath, inspect.stack() dies at realpath."""
    body = _WORLD_A + (
        "import os, os.path, inspect\n"
        "os.path.abspath = lambda p, *a, **k: p if p.startswith('/') else '/fake/' + p\n"
        "try:\n"
        "    os.path.abspath('rel.py')\n"
        "    print('ABSPATH_SURVIVED')\n"
        "except OSError:\n"
        "    print('ABSPATH_DIED')\n"
        "try:\n"
        "    inspect.stack()\n"
        "    print('STACK_SURVIVED')\n"
        "except OSError:\n"
        "    print('STACK_DIED')\n"
    )
    result = _run_child(body)
    assert "ABSPATH_SURVIVED" in result.stdout, (
        "the ntpath emulation did not take — this pin proves nothing until "
        f"abspath survives:\n{result.stdout}\n{result.stderr[-800:]}"
    )
    assert "STACK_DIED" in result.stdout, (
        "with abspath surviving the getcwd denial, inspect.stack() was "
        "expected to die at inspect.py:1009 — that causal link is the whole "
        f"reason the Windows row of the table reads STACK_DIES:\n{result.stdout}"
    )


def test_world_b_does_convict_inspect_stack():
    """The other half of the same claim: world B is the one that convicts."""
    body = _WORLD_B + (
        "import inspect\n"
        "try:\n"
        "    inspect.stack()\n"
        "    print('STACK_SURVIVED')\n"
        "except OSError:\n"
        "    print('STACK_DIED')\n"
    )
    result = _run_child(body)
    assert "STACK_DIED" in result.stdout, (
        "world B no longer convicts inspect.stack — it is the only world that "
        f"can, so this pin failing means the species is unmeasured:\n{result.stdout}"
    )


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


# The quiet species (a path resolving fine to the wrong place) has no site here: canary computes no
# cwd-sensitive module-level path, and seedgo's cross-branch contract pins the json write destination.


# The fence reads frame paths, and a path read must not kill an import whose cwd is gone. The child runs
# support_fence.py after removing its cwd (where the OS refuses, it denies getcwd) with realpath reading
# the cwd as ntpath's does; it reports ARM_CWD_DEAD before the probe runs, or the pin is vacuous.

FENCE_PROBE = BRANCH_ROOT / "tests" / "support_fence.py"

_DEAD_CWD_LAUNCHER = """
import os, runpy, sys
seat, shape, doomed = sys.argv[1], sys.argv[2], sys.argv[3]
os.chdir(doomed)
try:
    os.rmdir(doomed)
except OSError:
    def _dead_cwd(*a, **k):
        raise FileNotFoundError(2, "No such file or directory")
    os.getcwd = _dead_cwd
_real = os.path.realpath
def realpath(p, *a, **k):
    os.getcwd()
    return _real(p, *a, **k)
os.path.realpath = realpath
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
