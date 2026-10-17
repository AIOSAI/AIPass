# =================== AIPass ====================
# Name: test_windows_import.py
# Description: Every api module must IMPORT on a platform it cannot run on
# Version: 1.0.0
# Created: 2026-08-18
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/host/attach.py and every apps/ module, importing without POSIX."""

# Default arguments, decorator arguments and module constants run at import: a
# POSIX-only name there (os.setsid, os.geteuid) is a win32 collection error that
# hides every test in the file. The PTY lane not WORKING on Windows is fine.
# A subprocess, because hiding fcntl and deleting os attributes would maim the
# runner's own interpreter. A meta_path finder, not a patched __import__: that
# would put this file in the import stack the cross-branch import gate reads.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(windows_compat) — that the PTY lane works on Windows; it cannot, PTY_AVAILABLE guards it
# seedgo: no-test-needed(duplicate_test) — the PTY lane's behaviour on POSIX, covered by tests/test_host_attach.py

import json
import subprocess
import sys
from pathlib import Path

import pytest

from aipass.api.apps.handlers.host import attach as host_attach

BRANCH_ROOT = Path(host_attach.__file__).parents[3]

# `tty` is here because it imports `termios`.
ABSENT_MODULES = ("fcntl", "pty", "termios", "grp", "pwd", "resource", "tty")

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
import importlib, importlib.util, json, os, pathlib, sys

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

# The tests themselves, executed the way pytest collection executes them: the
# whole file runs top to bottom, so a POSIX-only attribute in a decorator or a
# module constant fails HERE the way it failed on the real lane.
collected, collection_failures = 0, []

for index, source in enumerate(sorted(root.glob("tests/**/*.py"))):
    if "__pycache__" in source.parts or ".archive" in source.parts:
        continue
    spec = importlib.util.spec_from_file_location("winprobe_%d_%s" % (index, source.stem), source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    collected += 1
    try:
        spec.loader.exec_module(module)
    except BaseException as e:  # noqa: BLE001 - Skipped and SystemExit both matter here
        if type(e).__name__ == "Skipped":
            continue
        why = type(e).__name__ + ": " + str(e).splitlines()[0][:200]
        collection_failures.append({"module": source.name, "why": why})

print("RESULT" + json.dumps({
    "hidden": hidden,
    "imported": len(imported),
    "failures": failures,
    "collected": collected,
    "collection_failures": collection_failures,
}))
'''


@pytest.fixture(scope="module")
def without_posix() -> dict:
    """Import every module under apps/ in a child that has no POSIX."""
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
        encoding="utf-8",
        cwd=str(BRANCH_ROOT),
        timeout=300,
    )

    line = next((ln for ln in run.stdout.splitlines() if ln.startswith("RESULT")), None)
    assert line, f"the child said nothing usable:\n{run.stdout[-2000:]}\n{run.stderr[-2000:]}"
    return json.loads(line[len("RESULT") :])


class TestEveryModuleImportsWithoutPosix:
    """The whole package, not just the module that broke."""

    def test_the_harness_actually_hides_posix(self, without_posix: dict) -> None:
        """First, that this file is measuring anything at all."""
        assert without_posix["hidden"], "the child still has POSIX — nothing was measured"

    def test_nothing_under_apps_fails_to_import(self, without_posix: dict) -> None:
        """The pin itself, and the sentence a future failure gets to say."""
        assert without_posix["failures"] == []

    def test_the_sweep_covers_the_package_rather_than_a_file(self, without_posix: dict) -> None:
        """A guard on the guard: a glob that stops matching reports zero failures."""
        assert without_posix["imported"] > 40

    def test_every_test_file_still_collects_without_posix(self, without_posix: dict) -> None:
        """
        The 2026-08-18 second-round species: a POSIX-only attribute evaluated
        at COLLECTION time in a test file.
        """
        assert without_posix["collection_failures"] == []

    def test_the_collection_sweep_actually_finds_the_test_tree(self, without_posix: dict) -> None:
        """Same guard-on-the-guard as apps/: an empty glob passes vacuously."""
        assert without_posix["collected"] > 20
