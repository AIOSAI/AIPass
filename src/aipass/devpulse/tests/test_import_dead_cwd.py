# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Pins devpulse imports against a dead working directory
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-10-08
# =============================================

"""Tests for apps/handlers/__init__.py and apps/handlers/module_root.py with no readable working directory."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — ntpath's own realpath; the world injects its cwd read as a condition

import subprocess
import sys
from pathlib import Path

from aipass.devpulse.apps.handlers import module_root

# ntpath.realpath reads os.getcwd() for every path and Path.resolve() routes through
# it (Windows CI, 2026-08-31). The world injects that as a condition, in a child
# process before any aipass import; where resolve() never reaches the denial the
# probe says PROBE_VACUOUS, and the test allows that only on pre-3.11 interpreters.
WORLD = r"""
# Other branches' import-time code is held CONSTANT: preloaded in the healthy
# world, before the denial. Their dead-cwd cure is their own build (fleet
# rollout in flight, 2026-08-31); this pin measures devpulse's sites only.
# When the fleet is cured these preloads can drop.
from aipass.prax import logger  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401

import os

_real_realpath = os.path.realpath


def _ntpath_condition(path, **kw):
    os.getcwd()  # ntpath.realpath reads cwd before checking absoluteness
    return _real_realpath(path, **kw)


os.path.realpath = _ntpath_condition


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd

# Probe the instrument: does THIS interpreter's resolve() reach the denied
# call for an absolute path? 3.11+ routes through os.path.realpath; 3.10
# resolves absolute paths without cwd, so the denial cannot fire there.
import pathlib

try:
    pathlib.Path(pathlib.__file__).resolve()
    print("PROBE_VACUOUS")
except FileNotFoundError:
    print("PROBE_ARMED")

import aipass.devpulse.apps.handlers.owner.admin_grant  # noqa: F401
import aipass.devpulse.apps.handlers.feedback.storage  # noqa: F401
import aipass.devpulse.apps.handlers.feedback.compose  # noqa: F401
import aipass.devpulse.apps.handlers.json.json_handler  # noqa: F401
import aipass.devpulse.apps.handlers.compass.store  # noqa: F401

print("IMPORTED")
"""


def _inspect_stack_calls(source: str) -> list[int]:
    """Line numbers of every inspect.stack() call in *source*, by parse.

    An AST matcher, never a string scan: the guard's own docstring names
    inspect.stack() while explaining the defect, and a spelling ban would
    convict the explanation while acquitting the code.
    """
    import ast

    tree = ast.parse(source)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "stack"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "inspect"
    ]


def test_the_guard_never_calls_inspect_stack():
    """Structural pin on the guard cure - import probes cannot carry this.

    The deleted second inspect.stack() walk sat in the caller-is-None branch,
    which no import-shaped world ever reached while apps/__init__.py supplied
    a real-file frame. @trigger measured the hole - restoring the defect left
    their whole suite green. Only a parse of the file convicts it. The fence
    v2 (DPLAN-0404) walks sys._getframe and resolves each frame's file under
    its own except OSError; inspect has no place in it.
    """
    guard = (Path(__file__).resolve().parents[1] / "apps" / "handlers" / "__init__.py").read_text(encoding="utf-8")

    assert _inspect_stack_calls(guard) == [], (
        "inspect.stack() is back in the guard - it needs a readable cwd on "
        "Windows before any of the guard's own code runs (getmodule's "
        "os.path.realpath sits outside any try)"
    )
    assert "import inspect" not in [line.strip() for line in guard.splitlines()], (
        "the guard imports inspect again - nothing in the cured shape needs it"
    )

    # Positive control: the matcher must convict a real call...
    assert _inspect_stack_calls("import inspect\nframes = inspect.stack()\n") == [2]
    # ...and clear prose that names the defect (docstring negative control).
    assert _inspect_stack_calls('"""inspect.stack() is banned here."""\n') == []
    # ...and clear an unrelated .stack attribute (numpy.stack shape).
    assert _inspect_stack_calls("import numpy\nnumpy.stack([])\n") == []


class _UnresolvablePath(type(Path())):
    """A path whose resolve() fails the way a dead working directory makes it fail.

    Bound as module_root's own Path (@daemon's shape, 2026-09-27), so only
    module_file() meets it: pathlib.Path is left alone for the rest of the process.
    """

    def resolve(self, strict=False):
        raise OSError("resolve denied")


def test_fallback_diagnostics_never_take_the_lane_down(monkeypatch, capsys):
    """@daemon's flag on this branch (2026-08-31): module_file's fallback
    logged OUTSIDE its own protection. The world that reaches the fallback
    is exactly the world where the logger may be down too - prax's logger
    construction reads the cwd - so an unguarded diagnostic becomes the
    import crash the helper exists to prevent. Mutant-verified: restoring
    the unprotected logger.debug in module_file's except turns this red.
    """

    def _logger_is_down(*args, **kwargs):
        raise OSError("logger lane is down with the cwd")

    monkeypatch.setattr(module_root.logger, "debug", _logger_is_down)
    monkeypatch.setattr(module_root, "Path", _UnresolvablePath)

    result = module_root.module_file(__file__)

    # The right file still comes back, in its unresolved spelling...
    assert result == Path(__file__)
    # ...and the double failure reached the last-resort channel rather than
    # vanishing - the wrapper reports, it never swallows.
    assert "cannot record it" in capsys.readouterr().err


DENIED_RESOLVE_WORLD = r"""
# The fence v2 (DPLAN-0404) resolves every frame's file in _frame_path, under
# its own except OSError: a process whose cwd was deleted must not die in the
# walk. This world denies realpath for every path, so each resolve raises and
# the fence falls back to the raw spelling; a -c seat's frames are <string> and
# importlib, transport, so the walk finds no foreign frame and returns. The
# public shape is all this world touches: the import, and its survival.
from aipass.prax import logger  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401

import os


def _denied_realpath(path, **kw):
    raise FileNotFoundError(2, "realpath denied", str(path))


os.path.realpath = _denied_realpath

# Arming probe 1: the denial must bite before its silence means anything.
try:
    os.path.realpath("x")
    print("DENIAL_INERT")
except FileNotFoundError:
    print("DENIAL_ARMED")

# Arming probe 2: this interpreter's resolve() must reach the denial, or the
# fence's except arm is never exercised (3.11+ routes through os.path.realpath).
import pathlib

try:
    pathlib.Path(pathlib.__file__).resolve()
    print("RESOLVE_INERT")
except FileNotFoundError:
    print("RESOLVE_DENIED")

import aipass.devpulse.apps.handlers  # noqa: F401

print("GUARD_RETURNED")
"""


def test_the_fence_survives_a_denied_resolve_from_a_file_less_seat():
    """Behavioural sibling of the AST ban, against v2's public shape.

    The AST pin is a parse, not a run; this world RUNS the fence's walk with
    every resolve denied. Mutant-proven: _frame_path without its except OSError
    arm dies here (M8, DPLAN-0404), and a regrown inspect.stack() walk dies the
    same way. The resolve-level probe is asserted on 3.11+, where pathlib routes
    resolve through os.path.realpath; 3.10 resolves through a copy pathlib
    captured at its first import, so the arm is out of this world's reach there
    and the import's survival is all it can pin.
    """
    result = subprocess.run(
        [sys.executable, "-c", DENIED_RESOLVE_WORLD],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    out = result.stdout
    assert "DENIAL_ARMED" in out, f"the realpath denial never bit - vacuous world:\n{out}\n{result.stderr}"
    if sys.version_info >= (3, 11):
        assert "RESOLVE_DENIED" in out, f"resolve() never reached the denial - the fence's arm is untouched:\n{out}"
    assert "GUARD_RETURNED" in out, f"the fence died walking the stack under a denied resolve:\n{out}\n{result.stderr}"


def test_handlers_import_with_dead_cwd():
    result = subprocess.run(
        [sys.executable, "-c", WORLD],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    out = result.stdout
    assert "IMPORTED" in out, f"import died under the dead-cwd world:\nstdout={out}\nstderr={result.stderr}"
    if "PROBE_VACUOUS" in out:
        # Allowed only where it is the interpreter's truth (pre-3.11 pathlib
        # never routes an absolute resolve through os.path.realpath).
        assert sys.version_info < (3, 11), (
            "resolve() survived the denial on an interpreter that routes "
            "through os.path.realpath - the instrument is broken, not the world"
        )
    else:
        assert "PROBE_ARMED" in out
