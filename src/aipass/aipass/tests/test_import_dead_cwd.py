# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Pins every aipass module against an unreadable working directory
# Version: 1.2.3
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests that apps/aipass.py and every module beneath it import without reading a dead working directory."""

# Windows ntpath.realpath (behind Path.resolve) always reads os.getcwd(); posixpath does not, so
# a child process injects that condition and denies cwd before importing every module: what
# counts is any resolve() reached at import, a default argument included.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — each module's own logic; see tests/test_read.py
# seedgo: no-test-needed(stdlib) — os.path.realpath's real Windows codepath; emulated, not run on Windows

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

BRANCH_ROOT = Path(__file__).resolve().parents[1]

#: Cross-branch modules this tree imports, preloaded healthy so a red here is always an aipass site.
_FOREIGN = [
    "aipass.prax",
    "aipass.prax.apps.modules.logger",
    "aipass.cli.apps.modules",
    # Its hooks json_handler resolves Path(__file__) at module scope; drop this when hooks is cured.
    "aipass.hooks.apps.modules.door_trust_registry",
    "aipass.trigger.apps.modules.core",
]

#: Sandboxes nothing looks into, and docs.local (untracked scratch, never shipped).
_SKIP_PARTS = {"dropbox", ".archive", ".backup", "__pycache__", "docs.local", "tests", "logs"}


def _branch_modules(root: Path = BRANCH_ROOT) -> list[str]:
    """Every importable ``aipass.aipass.*`` module name, found on disk.

    Walks files, not ``pkgutil``: pkgutil imports as it walks, the very thing under test.
    """
    names: list[str] = []
    for py in sorted(root.rglob("*.py")):
        parts = py.relative_to(root).parts
        if any(part in _SKIP_PARTS for part in parts):
            continue
        stem = parts[:-1] if parts[-1] == "__init__.py" else (*parts[:-1], parts[-1][:-3])
        names.append(".".join(("aipass", "aipass", *stem)))
    return names


_DEAD_CWD_WORLD = """
import os, sys, importlib

# Other branches' import-time code, held constant in the healthy world.
for _foreign in {foreign!r}:
    try:
        importlib.import_module(_foreign)
    except Exception:
        pass

_real_realpath = os.path.realpath


def _ntpath_condition(path, **kw):
    os.getcwd()  # ntpath.realpath reads cwd before checking absoluteness
    return _real_realpath(path, **kw)


os.path.realpath = _ntpath_condition


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd

# Probe the instrument: does THIS interpreter route an absolute resolve()
# through os.path.realpath? 3.11+ does; 3.10 resolves absolute paths without
# touching cwd, so the denial could not fire there.
import pathlib

try:
    pathlib.Path(pathlib.__file__).resolve()
    print("PROBE_VACUOUS")
except FileNotFoundError:
    print("PROBE_ARMED")

for _name in {modules!r}:
    try:
        importlib.import_module(_name)
    except Exception as exc:
        print("FAIL %s | %s: %s" % (_name, type(exc).__name__, exc))

print("SWEPT")
"""


def _run(source: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    return result.stdout + result.stderr


class TestEveryModuleImportsWithoutTheWorkingDirectory:
    def test_no_module_reads_cwd_to_import(self) -> None:
        out = _run(_DEAD_CWD_WORLD.format(foreign=_FOREIGN, modules=_branch_modules()))
        assert "SWEPT" in out, f"the sweep itself died:\n{out}"
        failures = [line for line in out.splitlines() if line.startswith("FAIL ")]
        assert failures == [], "module(s) need a readable cwd to import:\n" + "\n".join(failures)

    def test_the_instrument_is_armed(self) -> None:
        """A vacuous probe would make the sweep above green for free."""
        out = _run(_DEAD_CWD_WORLD.format(foreign=_FOREIGN, modules=[]))
        if "PROBE_VACUOUS" in out:
            assert sys.version_info < (3, 11), (
                "resolve() survived the denial on an interpreter that routes through "
                "os.path.realpath — the instrument is broken, not the world"
            )
        else:
            assert "PROBE_ARMED" in out, f"probe reported neither outcome:\n{out}"

    def test_the_sweep_actually_found_modules(self) -> None:
        """A walk that names nothing reports clean. Refuse to call that a pass."""
        modules = _branch_modules()
        assert len(modules) > 40, f"module walk named only {len(modules)} — it is blind, not clean"
        assert "aipass.aipass.apps.handlers" in modules
        assert not any(".tests" in name or ".archive" in name for name in modules)

    def test_the_walk_never_enters_a_sandbox_or_scratch(self, tmp_path: Path) -> None:
        """A planted module in each skipped directory is never named; the live one beside them is."""
        for skipped in ("dropbox", ".archive", "__pycache__", "docs.local"):
            (tmp_path / skipped).mkdir()
            (tmp_path / skipped / "planted.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "live.py").write_text("x = 1\n", encoding="utf-8")
        assert _branch_modules(tmp_path) == ["aipass.aipass.live"]


_REALPATH_DENIED_WORLD = """
import os, sys, importlib

for _foreign in {foreign!r}:
    try:
        importlib.import_module(_foreign)
    except Exception:
        pass

import inspect


def _denied(path, *a, **kw):
    raise FileNotFoundError(2, "realpath denied", str(path))


os.path.realpath = _denied

{body}
"""

_INSTRUMENT_BITES = """
try:
    inspect.stack()
    print("STACK_SURVIVED")
except FileNotFoundError:
    print("STACK_RAISED")
"""

_GUARD_IMPORTS = """
try:
    importlib.import_module("aipass.aipass.apps.handlers")
    print("GUARD_OK")
except Exception as exc:
    print("GUARD_DIED %s: %s" % (type(exc).__name__, exc))
"""


class TestTheImportGuardWalksFramesWithoutTheFilesystem:
    """``inspect.stack()`` builds a FrameInfo per frame.

    For a frozen frame getmodule() calls realpath outside inspect's try, so deny realpath, not getcwd.
    """

    def test_inspect_stack_raises_in_this_world(self) -> None:
        """Positive control. Without this the pin below could pass blind."""
        out = _run(_REALPATH_DENIED_WORLD.format(foreign=_FOREIGN, body=_INSTRUMENT_BITES))
        assert "STACK_RAISED" in out, f"the denial did not reach inspect.stack — instrument is blind:\n{out}"

    def test_the_handlers_guard_imports_anyway(self) -> None:
        out = _run(_REALPATH_DENIED_WORLD.format(foreign=_FOREIGN, body=_GUARD_IMPORTS))
        assert "GUARD_OK" in out, f"the import guard needs the filesystem to run:\n{out}"


GUARD = BRANCH_ROOT / "apps" / "handlers" / "__init__.py"

#: Directories the ban does not police: sandboxes, untracked scratch and the pin's own fixtures.
_BAN_SKIP = {"dropbox", ".archive", ".backup", "__pycache__", "docs.local", "tests", "logs"}


def _inspect_stack_calls(source: str) -> list[int]:
    """Line numbers of every ``inspect.stack(...)`` CALL in *source*.

    Structural, never a string search: the cured guard's docstring names it, and a
    spelling ban would convict the explanation.
    """
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "stack"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "inspect"
        ):
            lines.append(node.lineno)
    return sorted(lines)


def _banned_sites(root: Path = BRANCH_ROOT) -> tuple[list[str], int]:
    """Every ``inspect.stack()`` call under *root* (the live branch by default), and the files parsed."""
    offenders: list[str] = []
    scanned = 0
    for py in sorted(root.rglob("*.py")):
        parts = py.relative_to(root).parts
        if any(part in _BAN_SKIP for part in parts):
            continue
        # A live file that will not parse raises here: skipping it could hide a call.
        lines = _inspect_stack_calls(py.read_text(encoding="utf-8"))
        scanned += 1
        offenders.extend(f"{py.relative_to(root).as_posix()}:{line}" for line in lines)
    return offenders, scanned


class TestNoInspectStackSurvives:
    """A behavioural pin cannot reach every branch of the guard.

    The ``caller_file is None`` branch is unreachable from an import, so a restored
    inspect.stack() there would leave every behavioural test green.
    """

    def test_the_guard_contains_no_inspect_stack_call(self) -> None:
        assert _inspect_stack_calls(GUARD.read_text(encoding="utf-8")) == [], (
            "apps/handlers/__init__.py calls inspect.stack() — it needs a readable cwd "
            "on Windows before any of the guard's own code runs"
        )

    def test_no_module_in_the_tree_calls_inspect_stack(self) -> None:
        offenders, _ = _banned_sites()
        assert offenders == [], "inspect.stack() call(s) — walk frames with sys._getframe instead: " + ", ".join(
            offenders
        )

    def test_the_ban_actually_parsed_the_tree(self) -> None:
        """A walk that visits nothing reports clean. Refuse to call that a pass."""
        _, scanned = _banned_sites()
        assert scanned > 40, f"ban only parsed {scanned} modules -- it is blind, not clean"

    def test_the_ban_never_enters_a_sandbox_or_scratch(self, tmp_path: Path) -> None:
        """A call planted in each skipped directory goes unread; the live one beside them is convicted."""
        planted = "import inspect\nx = inspect.stack()\n"
        for skipped in ("dropbox", ".archive", "__pycache__", "docs.local"):
            (tmp_path / skipped).mkdir()
            (tmp_path / skipped / "planted.py").write_text(planted, encoding="utf-8")
        (tmp_path / "live.py").write_text(planted, encoding="utf-8")
        assert _banned_sites(tmp_path) == (["live.py:2"], 1)

    def test_a_planted_call_is_convicted_at_its_line(self) -> None:
        """Positive control through the REAL matcher, not a re-implementation."""
        assert _inspect_stack_calls("import inspect\nx = 1\ny = inspect.stack()\n") == [3]

    def test_a_docstring_naming_inspect_stack_is_not_a_call(self) -> None:
        """The cured guard's own docstring must survive its own ban."""
        assert _inspect_stack_calls('"""Walks frames rather than inspect.stack()."""\n') == []
        assert _inspect_stack_calls("# inspect.stack() is the defect\nx = 1\n") == []
        assert _inspect_stack_calls('s = "inspect.stack()"\n') == []

    def test_another_libs_stack_is_not_convicted(self) -> None:
        """``stack`` is a common verb. Only ``inspect``'s is the defect."""
        assert _inspect_stack_calls("import numpy\nx = numpy.stack([1, 2])\n") == []
        assert _inspect_stack_calls("import traceback\nx = traceback.stack()\n") == []
        assert _inspect_stack_calls("x = self.stack()\n") == []
