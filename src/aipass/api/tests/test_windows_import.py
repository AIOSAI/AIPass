#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_windows_import.py
# Description: Every api module must IMPORT on a platform it cannot run on
# Version: 1.0.0
# Created: 2026-08-18
# =============================================

"""
Tests that this package imports where POSIX is not

WHY THIS FILE EXISTS. On 2026-08-18 the Windows CI lane ran to completion for
the first time and reported 22 collection errors. All 22 came from one line:
`_setsid: Any = os.setsid` sat in a function signature in `host/attach.py`, a
default argument is evaluated when the module is IMPORTED, and `os.setsid` does
not exist on win32. `server` imports `attach` and `host_api` imports `server`,
so a single AttributeError took down eleven host test files across two workers.

The module was already careful. It guards `fcntl`, `pty` and `termios` behind a
try/except with a PTY_AVAILABLE flag, and three of the four defaults in that
same signature were fetched with `getattr`. The fourth was reached for
directly, and the guard forty lines above it never got the chance to run.

NOT WORKING AND NOT IMPORTING ARE DIFFERENT FAILURES. Nothing in the PTY lane
can work on Windows — a PTY is a Unix object and tmux does not run there. That
is a platform truth, guarded, tested and fine. Failing to import is not a
platform truth; it is a collection error that hides every unrelated test in the
same file.

WHY A SUBPROCESS. Hiding `fcntl` and deleting attributes off `os` is a change
to the interpreter, not to a fixture. Doing it in-process would leave the
runner's own `os` mutilated for every test that follows, in whatever order
xdist happened to pick. The child is a real, disposable interpreter.

WHY A META_PATH FINDER RATHER THAN A PATCHED __import__. Wrapping
`builtins.__import__` puts this file into the import stack, and the fleet's
cross-branch import gate reads that stack to decide who is calling. The
simulation would then be blocked by the gate instead of measuring anything. A
finder leaves the stack alone.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from aipass.api.apps.handlers.host import attach as host_attach

# The branch root, derived from a module that has to import anyway. A written
# down path would be the one thing this file is not allowed to contain.
BRANCH_ROOT = Path(host_attach.__file__).parents[3]

# What Windows does not ship. `tty` is here because it imports `termios`.
ABSENT_MODULES = ("fcntl", "pty", "termios", "grp", "pwd", "resource", "tty")

# What `os` does not carry on win32. Not exhaustive — it is the set a POSIX
# server is most likely to reach for, and each one is an AttributeError at
# import time if it appears in a default argument, a decorator or a constant.
ABSENT_OS_ATTRS = (
    "setsid",
    "fork",
    "forkpty",
    "openpty",
    "login_tty",
    "getuid",
    "geteuid",
    "getgid",
    "setpgrp",
    "getpgid",
    "killpg",
    "uname",
    "WIFEXITED",
)

CHILD = '''
import importlib, json, os, pathlib, sys

ABSENT_MODULES = set(json.loads(sys.argv[2]))
ABSENT_OS_ATTRS = json.loads(sys.argv[3])


class NotOnWindows:
    """Refuse the POSIX-only modules the way the real platform does."""

    @staticmethod
    def find_spec(name, path=None, target=None):
        if name.split(".")[0] in ABSENT_MODULES:
            raise ModuleNotFoundError("No module named " + repr(name), name=name)
        return None


for attr in ABSENT_OS_ATTRS:
    if hasattr(os, attr):
        delattr(os, attr)

for name in list(sys.modules):
    if name.split(".")[0] in ABSENT_MODULES:
        del sys.modules[name]

sys.meta_path.insert(0, NotOnWindows)

# Self-check: a harness that hides nothing would pass this file vacuously.
hidden = not any(hasattr(os, attr) for attr in ABSENT_OS_ATTRS)
try:
    importlib.import_module(sorted(ABSENT_MODULES)[0])
    hidden = False
except ImportError:
    pass

root = pathlib.Path(sys.argv[1])
failures, imported = [], []

for source in sorted(root.glob("apps/**/*.py")):
    if "__pycache__" in source.parts or ".archive" in source.parts:
        continue
    name = "aipass.api." + str(source.relative_to(root).with_suffix("")).replace(os.sep, ".")
    name = name[: -len(".__init__")] if name.endswith(".__init__") else name
    imported.append(name)
    try:
        importlib.import_module(name)
    except Exception as e:
        failures.append({"module": name, "why": type(e).__name__ + ": " + str(e).splitlines()[0][:200]})

print("RESULT" + json.dumps({"hidden": hidden, "imported": len(imported), "failures": failures}))
'''


@pytest.fixture(scope="module")
def without_posix() -> dict:
    """
    Import every module under apps/ in a child that has no POSIX.

    Returns:
        The child's verdict: whether the hiding took effect, how many modules
        were imported, and every failure with its reason.
    """
    run = subprocess.run(
        [
            sys.executable,
            "-c",
            CHILD,
            str(BRANCH_ROOT),
            json.dumps(list(ABSENT_MODULES)),
            json.dumps(list(ABSENT_OS_ATTRS)),
        ],
        capture_output=True,
        text=True,
        cwd=str(BRANCH_ROOT),
        timeout=300,
    )

    line = next((ln for ln in run.stdout.splitlines() if ln.startswith("RESULT")), None)
    assert line, f"the child said nothing usable:\n{run.stdout[-2000:]}\n{run.stderr[-2000:]}"
    return json.loads(line[len("RESULT") :])


class TestEveryModuleImportsWithoutPosix:
    """
    The whole package, not just the module that broke.

    Scoped to every file under apps/ deliberately. The defect was in attach.py
    this time; the SPECIES is a module-level reference to something a platform
    may not have, and it can land in any file. A pin that only watches attach
    would have to be rewritten the day it happens somewhere else.
    """

    def test_the_harness_actually_hides_posix(self, without_posix: dict) -> None:
        """
        First, that this file is measuring anything at all.

        A simulation that silently stops simulating passes forever and says
        nothing. If `os.setsid` still resolves in the child, or `fcntl` still
        imports there, every other assertion here is vacuous.
        """
        assert without_posix["hidden"], "the child still has POSIX — nothing was measured"

    def test_nothing_under_apps_fails_to_import(self, without_posix: dict) -> None:
        """
        The pin itself, and the sentence a future failure gets to say.

        Verified to bite: restoring `_setsid: Any = os.setsid` reproduces the
        Windows lane's exact cascade here — attach, then server, then host_api,
        three failures from one line, which is the same chain that became 22
        collection errors under xdist.
        """
        assert without_posix["failures"] == []

    def test_the_sweep_covers_the_package_rather_than_a_file(self, without_posix: dict) -> None:
        """
        A guard on the guard: a glob that stops matching reports zero failures.

        The count is not pinned to a number — modules come and go — only to
        being large enough that the sweep is obviously still finding the tree.
        """
        assert without_posix["imported"] > 40
