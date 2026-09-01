# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Pins devpulse imports against a dead working directory
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""Every devpulse module must import without a readable working directory.

The mechanism, measured on the Windows CI gate 2026-08-31 (@memory's finding):
ntpath.realpath calls os.getcwd() UNCONDITIONALLY - not only for relative
paths, the way posixpath does - and Path.resolve() routes through it. So on
Windows every module-level Path(__file__).resolve() is an import-time
working-directory read, and a process whose cwd was deleted cannot import the
module at all. devpulse carried six such sites.

The world injects ntpath's behaviour as a CONDITION rather than a platform:
os.path.realpath is wrapped to read os.getcwd() first, then os.getcwd is
denied. The injection happens in a child process before any aipass import, so
no module has cached the real functions.

Where the interpreter's own pathlib never routes resolve() through
os.path.realpath (3.10 resolves absolute paths without touching cwd), the
denial cannot fire and the probe says so - the pin still asserts the imports
succeed there, it just proves less. Pinned as a probe with both outcomes,
never a skipif: the vacuous world is named in the output, and the test
asserts vacuity only occurs on interpreters where it is the truth.
"""

import subprocess
import sys

WORLD = r"""
# Other branches' import-time code is held CONSTANT: preloaded in the healthy
# world, before the denial. Their dead-cwd cure is their own build (fleet
# rollout in flight, 2026-08-31); this pin measures devpulse's sites only.
# When the fleet is cured these preloads can drop.
import aipass.prax  # noqa: F401
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
    which no import-shaped world ever reaches: apps/__init__.py always
    supplies a real-file frame, so _find_real_caller never returns None
    during an import. @trigger measured the hole - restoring the defect left
    their whole suite green. Only a parse of the file convicts it.
    """
    from pathlib import Path

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


def test_fallback_diagnostics_never_take_the_lane_down(monkeypatch, capsys):
    """@daemon's flag on this branch (2026-08-31): module_file's fallback
    logged OUTSIDE its own protection. The world that reaches the fallback
    is exactly the world where the logger may be down too - prax's logger
    construction reads the cwd - so an unguarded diagnostic becomes the
    import crash the helper exists to prevent. Mutant-verified: restoring
    the unprotected logger.debug in module_file's except turns this red.
    """
    from pathlib import Path

    from aipass.devpulse.apps.handlers import module_root

    def _logger_is_down(*args, **kwargs):
        raise OSError("logger lane is down with the cwd")

    monkeypatch.setattr(module_root.logger, "debug", _logger_is_down)

    def _resolve_denied(self, strict=False):
        raise OSError("resolve denied")

    monkeypatch.setattr(module_root.Path, "resolve", _resolve_denied)

    result = module_root.module_file(__file__)

    # The right file still comes back, in its unresolved spelling...
    assert result == Path(__file__)
    # ...and the double failure reached the last-resort channel rather than
    # vanishing - the wrapper reports, it never swallows.
    assert "cannot record it" in capsys.readouterr().err


DIRECT_CALL_WORLD = r"""
# @spawn's finding (2026-08-31): the caller-is-None branch is unreachable from
# IMPORT-shaped pins (apps/__init__ always supplies a real-file frame) but IS
# reachable by calling the guard directly from a -c child - every frame is
# <string> or importlib, both skipped, so _find_real_caller returns (None,
# None) and the branch runs. A regrown inspect.stack() walk there dies under
# the realpath denial; the cured plain return survives it.
import aipass.prax  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401
import aipass.devpulse.apps.handlers as handlers

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

# Arming probe 2: this world must actually reach the None branch.
caller = handlers._find_real_caller()
print(f"CALLER_IS_NONE:{caller == (None, None)}")

handlers._guard_branch_access()
print("GUARD_RETURNED")
"""


def test_the_none_branch_is_reachable_by_direct_call():
    """Behavioural sibling of the AST ban - @spawn measured the shape.

    The AST pin names the defect precisely but is a parse, not a run; this
    world RUNS the caller-is-None branch under a realpath denial. Both
    instruments watch the same branch from different sides: restoring the
    deleted inspect.stack() walk turns this red (the walk executes under the
    denial) and the AST pin red (the call is back in the source).
    """
    result = subprocess.run(
        [sys.executable, "-c", DIRECT_CALL_WORLD],
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = result.stdout
    assert "DENIAL_ARMED" in out, f"the realpath denial never bit - vacuous world:\n{out}\n{result.stderr}"
    assert "CALLER_IS_NONE:True" in out, f"the world never reached the None branch - wrong path exercised:\n{out}"
    assert "GUARD_RETURNED" in out, (
        f"the guard died in the caller-is-None branch under a realpath denial:\n{out}\n{result.stderr}"
    )


def test_handlers_import_with_dead_cwd():
    result = subprocess.run(
        [sys.executable, "-c", WORLD],
        capture_output=True,
        text=True,
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
