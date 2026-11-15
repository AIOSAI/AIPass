# =================== AIPass ====================
# Name: support_template_import_guard.py
# Description: Shared child-script worlds for the template import guard tests (split from test_template_import_guard.py)
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-11-15
# =============================================

"""Shared worlds for the tests of templates/citizen/apps/handlers/__init__.py (no test_ prefix: never collected)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that the module parses and imports

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def _run(script: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script).strip()],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(cwd),
    )


# One control probe text for both worlds, so neither is graded by a friendlier instrument.
_CONTROL_PROBE = """
    try:
        _ProbePath("<string>").resolve()
    except OSError:
        print("CONTROL_LIVE")
    else:
        print("CONTROL_DEAD")
"""


def _require_live_world(result, world: str = "getcwd-denied"):
    """Skip rather than pass when the faked world did not actually break."""
    lines = result.stdout.split()
    if "CONTROL_DEAD" in lines:
        pytest.skip(
            "world not exercised: the injected os.getcwd failure does not reach "
            "Path.resolve() on this host, so nothing is claimed either way"
        )
    assert "CONTROL_LIVE" in lines, (
        f"the child never reported whether its world took:\n{result.stdout}\n{result.stderr}"
    )
    return lines


# Built once, before any world is installed: a probe built inside its world dies silently.
_BUILD_PROBE_PATH = """
    import os

    _ARM_ABS = {probe_literal}

    if not os.path.isabs(_ARM_ABS):
        print("PROBE_NOT_ABS", _ARM_ABS)
"""

# Decided by measuring whether Path.resolve travels through an accessor, not by hasattr:
# a host can have an accessor resolve no longer consults. ROUTE_* (found) and ACCESSOR_* (did) must agree.
_EMULATE_310 = """
    import os, os.path, pathlib

    _route_seen = []
    if hasattr(pathlib, "_NormalAccessor"):
        _orig_accessor_realpath = pathlib._NormalAccessor.realpath

        def _route_probe(*a, **k):
            _route_seen.append(True)
            return _orig_accessor_realpath(*a, **k)

        pathlib._NormalAccessor.realpath = staticmethod(_route_probe)
        try:
            pathlib.Path(_ARM_ABS).resolve()
        except OSError:
            pass
        finally:
            pathlib._NormalAccessor.realpath = staticmethod(_orig_accessor_realpath)

    print("ROUTE_WAS_NATIVE" if _route_seen else "ROUTE_WAS_DARK")

    if _route_seen:
        # Real <=3.10, or a shape that supplied the property. Emulating over it
        # would grade my stand-in on the only interpreter that carries the
        # defect for real.
        print("ACCESSOR_NATIVE")
    else:
        class _NormalAccessor310:
            # EAGER capture — the whole mechanism. Evaluated at class creation,
            # exactly as 3.10 evaluated it at pathlib's first import. Make this
            # a lazy lookup and the emulation stops emulating 3.10, which is
            # what test_the_bare_rebinding_is_inert_under_the_emulation pins.
            realpath = staticmethod(os.path.realpath)

        pathlib._NormalAccessor = _NormalAccessor310
        pathlib._normal_accessor = _NormalAccessor310()

        def _resolve_310(self, strict=False):
            # 3.10's Path.resolve, in one line: the accessor lookup is dynamic
            # (that is why patching it cures) while the value it holds was
            # captured eagerly (that is why the bare os.path rebinding is not).
            return type(self)(self._accessor.realpath(self, strict=strict))

        # Patched on Path, the base of PosixPath: the class the host instantiates is the only one that matters.
        pathlib.Path._accessor = pathlib._normal_accessor
        pathlib.Path.resolve = _resolve_310
        print("ACCESSOR_EMULATED")
"""

# The emulation proves it took (ROUTE_ARMED) before anything downstream claims anything.
_ARM_THE_ROUTE = """
    import pathlib

    _seen = []
    _captured = pathlib._NormalAccessor.realpath

    def _recording(*a, **k):
        _seen.append(a[0] if a else None)
        return _captured(*a, **k)

    # CLASS only: an instance attribute left behind by the arming probe would
    # shadow the class patch the shipped world installs later, and the world
    # would go inert with nothing to show for it.
    pathlib._NormalAccessor.realpath = staticmethod(_recording)
    pathlib.Path(_ARM_ABS).resolve()
    pathlib._NormalAccessor.realpath = staticmethod(_captured)

    print("ROUTE_ARMED" if _seen else "ROUTE_DARK")
"""

# The host fingerprint every child prints first.
_REPORT_HOST = """
    import pathlib

    _flavour_of_host = getattr(pathlib.PurePosixPath, "_flavour", None)
    if _flavour_of_host is None:
        _FLAVOUR_KIND = "absent"
    elif hasattr(_flavour_of_host, "parse_parts"):
        _FLAVOUR_KIND = "object"
    else:
        _FLAVOUR_KIND = "module"

    _HAS_ACCESSOR = hasattr(pathlib, "_NormalAccessor")

    print("HOST", _FLAVOUR_KIND, "accessor" if _HAS_ACCESSOR else "no-accessor")
"""

_PATHLIB_ROUTE_PROBE = """
    from pathlib import Path as _RoutePath

    try:
        _RoutePath(_ARM_ABS).resolve()
    except OSError:
        print("PATHLIB_ARMED")
    else:
        print("PATHLIB_INERT")
"""


# One spelling, from the host's anchor.
_PROBE_LITERAL = 'os.path.join(os.path.abspath(os.sep), "definitely", "not", "here")'


def _compose(*chunks: str) -> str:
    """Join child-script fragments at column zero, skipping empty ones."""
    return "\n".join(
        textwrap.dedent(chunk).strip().replace("{probe_literal}", _PROBE_LITERAL) for chunk in chunks if chunk.strip()
    )


def _child_script(*chunks: str) -> str:
    """Every child starts with the host fingerprint. One rule, no exceptions."""
    return _compose(_REPORT_HOST, *chunks)
