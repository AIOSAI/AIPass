# =================== AIPass ====================
# Name: support_template_import_guard.py
# Description: Shared child-script worlds for the template import guard tests (split from test_template_import_guard.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-11-02
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

# <=3.10 pathlib captured os.path.realpath at first import, so rebinding it alone is inert there.
# A staticmethod on the class only: a plain function eats the path into self, an instance attribute shadows it.
_ARM_PATHLIB_ACCESSOR = """
    import pathlib as _pathlib

    if hasattr(_pathlib, "_NormalAccessor"):
        _pathlib._NormalAccessor.realpath = staticmethod(_no_realpath)
"""

_DENY_REALPATH = (
    """
    import errno, os, os.path
    from pathlib import Path as _ProbePath

    def _no_realpath(*args, **kwargs):
        raise FileNotFoundError(errno.ENOENT, "No such file or directory")

    # os.path IS posixpath, so on 3.11+ this reaches pathlib's own
    # resolve() too. On 3.10 it does not — see _ARM_PATHLIB_ACCESSOR.
    os.path.realpath = _no_realpath
"""
    + _ARM_PATHLIB_ACCESSOR
    + _CONTROL_PROBE
)


def _require_live_world(result, world: str = "getcwd-denied"):
    """Skip rather than pass when the faked world did not actually break.

    Each world names its own cause: an inert realpath-denied world is a bug and fails, never skips."""
    lines = result.stdout.split()
    if "CONTROL_DEAD" in lines:
        if world == "realpath-denied":
            pytest.fail(
                "the realpath-denied world went inert, and there is no known "
                "platform reason for that one — os.path.realpath is denied "
                "directly and the captured-accessor route is patched for "
                "<=3.10. This is a bug in the world, not a platform difference: "
                f"{result.stdout!r} {result.stderr[-400:]}"
            )
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

# A stand-in declares which real hosts it can speak from, measured in the child, and is UNAVAILABLE elsewhere.
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


def _host_line(result) -> list:
    """The child's own HOST fingerprint: flavour kind, accessor.

    The last one: a child that simulates a foreign host re-reports, and that host is in force."""
    fingerprints = [line for line in result.stdout.splitlines() if line.startswith("HOST ")]
    return fingerprints[-1].split()[1:] if fingerprints else []


# The host's parsing dialect, measured not versioned: 3.10/3.11 call _flavour.parse_parts, which no
# module-shaped flavour has. Rows with a module-shaped flavour skip by name unless "module-tolerant".
_REPORT_PARSING_DIALECT = """
    import pathlib, posixpath

    class _ModuleShapedFlavour:
        sep = posixpath.sep
        altsep = ""

        def __getattr__(self, name):
            return getattr(posixpath, name)

    try:
        pathlib.PurePosixPath._flavour = _ModuleShapedFlavour()
    except (AttributeError, TypeError) as _exc:
        print("PARSING", "unknown:" + type(_exc).__name__)
    else:
        try:
            pathlib.PurePosixPath("/parsing/probe/only")
        except AttributeError as _exc:
            _text = str(_exc)
            _asked = _text.rsplit("'", 2)[-2] if _text.count("'") >= 2 else "something"
            print("PARSING", "demands:" + _asked)
        else:
            print("PARSING", "module-tolerant")
"""


def _measure_host() -> dict:
    """Run the child's OWN fingerprint chunk once, and read the answer back.

    Never an in-process pathlib read: that would be a second spelling of the host, free to drift."""
    result = _run(_child_script(), cwd=Path(__file__).parent)
    host = _host_line(result)
    if len(host) != 2:
        return {"flavour": "unknown", "accessor": "unknown"}
    return {"flavour": host[0], "accessor": host[1]}


def _parsing_answer(result) -> str:
    """The child's dialect answer, or "unknown" — fails closed, never defaults to tolerant."""
    for line in result.stdout.splitlines():
        if line.startswith("PARSING "):
            return line.split(None, 1)[1]
    return "unknown"


def _measure_parsing_dialect() -> str:
    """What this host's pathlib asks a flavour for while parsing. One child, once."""
    return _parsing_answer(_run(_child_script(_REPORT_PARSING_DIALECT), cwd=Path(__file__).parent))


_HOST_FACTS = _measure_host()
_HOST_FACTS["parsing"] = _measure_parsing_dialect()


def _simulation_unavailable(requires: dict, host: dict) -> str:
    """Which REAL hosts a simulation can speak from — the third verdict, one level up.

    Empty string means it can speak; anything else is the reason it cannot."""
    for fact in sorted(requires):
        allowed = requires[fact]
        if host.get(fact) not in allowed:
            return (
                f"this simulation can only speak from a host whose {fact} is one of "
                f"{sorted(allowed)}; this host reports {host.get(fact)!r}"
            )
    return ""
