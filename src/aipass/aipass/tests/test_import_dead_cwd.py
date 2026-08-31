# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Pins every aipass module against an unreadable working directory
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""No module in this branch may read the working directory to import.

THE MECHANISM (measured on the Windows CI gate 2026-08-31, @memory's finding)
----------------------------------------------------------------------------
``ntpath.realpath`` computes ``os.getcwd()`` UNCONDITIONALLY — on its first
lines, before it checks whether the path is even absolute — and
``Path.resolve()`` routes through it.  So on Windows every
``Path(__file__).resolve()`` reached while a module is being imported is an
import-time working-directory read, and a process whose cwd was deleted (or
sits on a disconnected share) cannot import the module at all.

``posixpath.realpath`` skips ``getcwd`` for an absolute path, which is why this
was invisible on Linux for as long as it existed.  These pins inject the
Windows behaviour as a CONDITION rather than a platform, so they run red on
this host: ``os.path.realpath`` is wrapped to read ``os.getcwd()`` first, then
``os.getcwd`` is denied.

THE DISCRIMINATOR IS *REACHED AT IMPORT*, NOT *WRITTEN AT MODULE SCOPE*
-----------------------------------------------------------------------
A ``resolve()`` inside a function still counts when import-time code calls that
function — including a default argument evaluated during import.  A grep for
module-level assignments would miss those, so the pin imports every module in
the tree and lets the interpreter decide what is reached.

WHY A CHILD PROCESS
-------------------
The injection has to land before any ``aipass`` module is imported, or a module
that already cached ``os.path.realpath`` would be measured against the real
one.  Other branches' import-time code is held CONSTANT by preloading it in the
healthy world first: their dead-cwd cure is their own build, and this file
measures aipass's sites only.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

BRANCH_ROOT = Path(__file__).resolve().parents[1]

#: Cross-branch modules this tree imports. Preloaded in the healthy world so a
#: red here is always an aipass site. (Found by grepping ``from aipass.<other>``
#: across apps/ and shared/ — see the module docstring.)
_FOREIGN = [
    "aipass.prax",
    "aipass.prax.apps.modules.logger",
    "aipass.cli.apps.modules",
    "aipass.hooks.apps.handlers.json",
    "aipass.hooks.apps.handlers.config",
    # trust_registry pulls hooks' own json_handler, whose module-level
    # Path(__file__).resolve() is the same species at hooks/.../json_handler.py:30.
    # Reported to @hooks 2026-08-31; their site, their build. Preloading it keeps
    # this pin measuring aipass — drop the line when hooks is cured.
    "aipass.hooks.apps.handlers.config.trust_registry",
    "aipass.trigger.apps.modules.core",
]

_SKIP_PARTS = {".archive", ".backup", "__pycache__", "tests", "logs"}


def _branch_modules() -> list[str]:
    """Every importable ``aipass.aipass.*`` module name, found on disk.

    Named by walking files rather than by ``pkgutil``, because ``pkgutil``
    imports as it walks — the very thing under test.
    """
    names: list[str] = []
    for py in sorted(BRANCH_ROOT.rglob("*.py")):
        parts = py.relative_to(BRANCH_ROOT).parts
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


# ---------------------------------------------------------------------------
# the guard specifically — inspect.stack() needs the filesystem
# ---------------------------------------------------------------------------

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

    For a frozen-importlib frame the filename does not exist on disk, so
    ``getsourcefile`` falls through to ``getmodule()`` — whose module-scanning
    loop calls ``os.path.realpath`` OUTSIDE the ``try`` that wraps
    ``getabsfile``.  On POSIX the equivalent raise happens earlier, inside
    ``getabsfile``'s ``abspath`` → ``getcwd``, where ``inspect`` catches it.  On
    Windows ``ntpath.abspath`` succeeds and the unguarded ``realpath`` runs.

    So the Windows-faithful denial on this host is of ``os.path.realpath``, not
    of ``os.getcwd``: a getcwd denial alone is green against the defective
    guard, because posixpath skips getcwd for absolute paths (@ai_mail's
    instrument note, 2026-08-31).
    """

    def test_inspect_stack_raises_in_this_world(self) -> None:
        """Positive control. Without this the pin below could pass blind."""
        out = _run(_REALPATH_DENIED_WORLD.format(foreign=_FOREIGN, body=_INSTRUMENT_BITES))
        assert "STACK_RAISED" in out, f"the denial did not reach inspect.stack — instrument is blind:\n{out}"

    def test_the_handlers_guard_imports_anyway(self) -> None:
        out = _run(_REALPATH_DENIED_WORLD.format(foreign=_FOREIGN, body=_GUARD_IMPORTS))
        assert "GUARD_OK" in out, f"the import guard needs the filesystem to run:\n{out}"


# ---------------------------------------------------------------------------
# the structural ban -- inspect.stack() must be unwritable in this tree
# ---------------------------------------------------------------------------

GUARD = BRANCH_ROOT / "apps" / "handlers" / "__init__.py"

#: Directories the ban does not police: retired code and the pin's own fixtures.
_BAN_SKIP = {".archive", ".backup", "__pycache__", "tests", "logs"}


def _inspect_stack_calls(source: str) -> list[int]:
    """Line numbers of every ``inspect.stack(...)`` CALL in *source*.

    Structural, never a string search.  The cured guard's own docstring names
    ``inspect.stack()`` while explaining why it is gone, and a spelling ban
    would convict the explanation — the file would have to stop saying what it
    learned in order to pass.  An ``ast.Call`` whose func is an ``Attribute``
    named ``stack`` on a ``Name`` ``inspect`` is the defect and nothing else is.
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


def _banned_sites() -> tuple[list[str], int]:
    """Every ``inspect.stack()`` call under the branch, and the files parsed."""
    offenders: list[str] = []
    scanned = 0
    for py in sorted(BRANCH_ROOT.rglob("*.py")):
        parts = py.relative_to(BRANCH_ROOT).parts
        if any(part in _BAN_SKIP for part in parts):
            continue
        try:
            source = py.read_text(encoding="utf-8")
            lines = _inspect_stack_calls(source)
        except (SyntaxError, UnicodeDecodeError):
            continue
        scanned += 1
        offenders.extend(f"{py.relative_to(BRANCH_ROOT).as_posix()}:{line}" for line in lines)
    return offenders, scanned


class TestNoInspectStackSurvives:
    """A behavioural pin cannot reach every branch of the guard.

    @trigger measured this fleet-wide and @canary reproduced it: the DELETED
    second ``inspect.stack()`` walk lived in the guard's ``caller_file is None``
    branch, which no import-shaped world can enter — ``apps/__init__`` always
    supplies a real-file frame.  Restoring that walk leaves every behavioural
    test green (canary: 30 of 31 passed, only their AST ban died).  So the
    unreachable branch needs a structural pin or it is not pinned at all.
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


# ---------------------------------------------------------------------------
# world B -- logging must never take down the caller it logs for
# ---------------------------------------------------------------------------

#: A caller filename that is NOT on disk. That is the whole point: getsourcefile
#: early-returns for files that exist, so a real path would never reach the
#: unguarded realpath and the pin would prove nothing. Never ``<stdin>`` --
#: linecache caches stdin and the probe lies green (@devpulse, 2026-08-31).
_PSEUDO_CALLER = "/nonexistent/aipass_probe_caller.py"

#: Compiled under _PSEUDO_CALLER so these functions ARE the caller frame the
#: name lookup reads. An earlier draft passed a lambda into a compiled helper
#: and the lookup read the lambda's own ``<string>`` frame instead -- the pin
#: caught it, which is the only reason this comment exists.
_CALLER_SOURCE = (
    "def call_shared(handler):\n"
    "    return handler.log_operation('probe', {'x': 1})\n"
    "def call_shim(module):\n"
    "    return module.log_operation('probe', {'x': 1})\n"
    "def call_control(fn):\n"
    "    return fn()\n"
)

_WORLD_B = """
import os, tempfile, pathlib

from aipass.aipass.shared.json_handler import JsonHandler
from aipass.aipass.apps.handlers.json import json_handler as shim

assert not os.path.exists({caller!r}), "the pseudo-caller must not exist on disk"


def _denied(path, *a, **kw):
    raise FileNotFoundError(2, "realpath denied", str(path))


# WORLD B: realpath denied, abspath left WORKING. That is the Windows shape --
# ntpath.abspath succeeds, so control passes inspect's guarded getabsfile and
# reaches the unguarded os.path.realpath inside getmodule's scanning loop.
os.path.realpath = _denied

ns = {{}}
exec(compile({source!r}, {caller!r}, "exec"), ns)

# CONTROL: the pre-cure form, rebuilt and run in this same world. If it does
# not raise, the world is not the defect's world and every pin below is vacuous.
import inspect


def _pre_cure():
    stack = inspect.stack()
    if len(stack) > 2:
        name = pathlib.Path(stack[2].filename).stem
        if name and not name.startswith("_"):
            return name
    return "unknown"


try:
    ns["call_control"](_pre_cure)
    print("CONTROL_SURVIVED")
except FileNotFoundError:
    print("CONTROL_RAISED")

shared_dir = tempfile.mkdtemp()
try:
    print("SHARED", ns["call_shared"](JsonHandler(shared_dir)))
except Exception as exc:
    print("SHARED_DIED %s: %s" % (type(exc).__name__, exc))
print("SHARED_NAMES", sorted(os.listdir(shared_dir)))

shim_dir = tempfile.mkdtemp()
shim.AIPASS_JSON_DIR = pathlib.Path(shim_dir)
try:
    print("SHIM", ns["call_shim"](shim))
except Exception as exc:
    print("SHIM_DIED %s: %s" % (type(exc).__name__, exc))
print("SHIM_NAMES", sorted(os.listdir(shim_dir)))
"""


class TestLoggingSurvivesWorldB:
    """``log_operation`` resolved the caller name BEFORE its own ``try``.

    So ``inspect.stack()`` raising there escaped every handler beneath it and
    logging took down the caller it was logging for -- measured by @canary
    through this branch's shim, the same species @drone cured in their tree.

    The caller frame here is a ``compile()``d source whose filename is not on
    disk, which is what forces ``getsourcefile`` down into ``getmodule``.  It
    also keeps a USABLE name in ``co_filename``, so the pins can demand the
    audit trail survived: returning ``"unknown"`` for every caller satisfies a
    not-crash assertion and destroys the record.
    """

    @staticmethod
    def _world() -> str:
        return _run(_WORLD_B.format(caller=_PSEUDO_CALLER, source=_CALLER_SOURCE))

    def test_the_pre_cure_form_dies_in_this_world(self) -> None:
        """Positive control. Without it, the pins below could pass blind."""
        out = TestLoggingSurvivesWorldB._world()
        assert "CONTROL_RAISED" in out, f"world B did not reach the defect -- instrument is blind:\n{out}"

    def test_the_shared_handler_logs_instead_of_raising(self) -> None:
        out = TestLoggingSurvivesWorldB._world()
        assert "SHARED True" in out, f"shared json_handler.log_operation failed under world B:\n{out}"

    def test_the_shim_logs_instead_of_raising(self) -> None:
        out = TestLoggingSurvivesWorldB._world()
        assert "SHIM True" in out, f"the branch shim's log_operation failed under world B:\n{out}"

    def test_the_audit_trail_still_names_the_caller(self) -> None:
        """Not-crashing is half the contract. The log must still say WHO."""
        out = TestLoggingSurvivesWorldB._world()
        stem = Path(_PSEUDO_CALLER).stem
        for label in ("SHARED_NAMES", "SHIM_NAMES"):
            line = next((ln for ln in out.splitlines() if ln.startswith(label)), "")
            assert f"{stem}_log.json" in line, (
                f"{label} did not record the caller as '{stem}' -- a log that answers "
                f"'unknown' for every caller passes a not-crash test and destroys the trail:\n{line}"
            )
