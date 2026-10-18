# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Pins devpulse imports against a dead working directory
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/__init__.py and apps/handlers/module_root.py with no readable working directory."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — ntpath's own realpath; the world injects its cwd read as a condition

import subprocess
import sys
from pathlib import Path

from aipass.devpulse.apps.handlers import module_root

# ntpath.realpath reads os.getcwd() for every path, and Path.resolve() routes through it.
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
    """Line numbers of every inspect.stack() call in *source*, by parse: prose naming it is not a call."""
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
    """Structural pin on the guard cure - import probes cannot reach the branch, only a parse convicts it."""
    guard = (Path(__file__).resolve().parents[1] / "apps" / "handlers" / "__init__.py").read_text(encoding="utf-8")

    assert _inspect_stack_calls(guard) == [], (
        "inspect.stack() is back in the guard - it needs a readable cwd on "
        "Windows before any of the guard's own code runs (getmodule's "
        "os.path.realpath sits outside any try)"
    )
    assert "import inspect" not in [line.strip() for line in guard.splitlines()], (
        "the guard imports inspect again - nothing in the cured shape needs it"
    )

    assert _inspect_stack_calls("import inspect\nframes = inspect.stack()\n") == [2]
    assert _inspect_stack_calls('"""inspect.stack() is banned here."""\n') == []
    assert _inspect_stack_calls("import numpy\nnumpy.stack([])\n") == []


class _UnresolvablePath(type(Path())):
    """A path whose resolve() fails as a dead cwd makes it; bound as module_root's own Path only."""

    def resolve(self, strict=False):
        raise OSError("resolve denied")


def test_fallback_diagnostics_never_take_the_lane_down(monkeypatch, capsys):
    """module_file's fallback diagnostic is guarded: the logger may be down in the same dead-cwd world."""

    def _logger_is_down(*args, **kwargs):
        raise OSError("logger lane is down with the cwd")

    monkeypatch.setattr(module_root.logger, "debug", _logger_is_down)
    monkeypatch.setattr(module_root, "Path", _UnresolvablePath)

    result = module_root.module_file(__file__)

    assert result == Path(__file__)
    # The wrapper reports the double failure, it never swallows it.
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
    """Behavioural sibling of the AST ban: this world RUNS the fence's walk with every resolve denied.

    The resolve probe is asserted on 3.11+ only; 3.10's pathlib never reaches os.path.realpath.
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
