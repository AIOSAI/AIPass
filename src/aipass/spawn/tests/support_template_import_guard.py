# =================== AIPass ====================
# Name: support_template_import_guard.py
# Description: Shared child-script worlds for the template import guard tests (split from test_template_import_guard.py)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Shared worlds for the tests of templates/citizen/apps/handlers/__init__.py (no test_ prefix: never collected).

Read by test_template_import_guard.py (the newborn's guard, the getcwd route)
and test_template_import_guard_hosts.py (the realpath denial and the harness
across hosts): the child-script chunks, the host fingerprint measured once per
process, and the platform emulations.
"""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

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


# The control probe is the SAME text in both worlds, so neither world can be
# graded by a friendlier instrument than the other. It runs the exact call the
# defective guard made — Path("<string>").resolve() — and reports whether that
# call is currently broken.
_CONTROL_PROBE = """
    try:
        _ProbePath("<string>").resolve()
    except OSError:
        print("CONTROL_LIVE")
    else:
        print("CONTROL_DEAD")
"""

# Rebinding os.path.realpath is NOT enough on every interpreter, and the same
# four lines are needed by the direct-call probe further down. Shared text, so
# neither site can be armed by a friendlier instrument than the other.
#
# Python <=3.10: pathlib delegates Path.resolve through an accessor that did
# ``realpath = staticmethod(os.path.realpath)`` at pathlib's FIRST IMPORT
# (3.10 pathlib.py:358). The capture means a later rebinding of
# os.path.realpath is a name nothing reads again, so the world is silently
# INERT for anything reaching realpath through pathlib. 3.11+ looks realpath up
# on the flavour module at call time (3.12: ``self._flavour.realpath(...)``) and
# needs none of this. hasattr-guarded, so it is a no-op where the accessor does
# not exist rather than an interpreter check that rots.
#
# staticmethod on the CLASS, and NOTHING on the instance.
#
# The staticmethod matters: a plain function set on the class binds on instance
# access and eats the path into self, which would keep a raise-shaped pin green
# for a reason that has nothing to do with what it claims.
#
# The instance half is GONE, and the reversal is worth the paragraph because I
# recommended it to @memory one session ago. @drone measured that an instance
# attribute SHADOWS the class staticmethod, so carrying both makes the class
# half unfalsifiable — belt-and-braces that disarms the instrument. @memory
# checked the sufficiency claim in CPython rather than accepting either of us,
# and I read the same lines to confirm before changing my own tree: 3.10
# pathlib.py:361 builds ONE shared `_normal_accessor` carrying no instance
# attributes, and :954 hands that same object to Path — so the lookup falls
# through to the class every time. One half, measured, is enough.
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

    # os.path IS posixpath/ntpath, so on 3.11+ this reaches pathlib's own
    # resolve() too. On 3.10 it does not — see _ARM_PATHLIB_ACCESSOR.
    os.path.realpath = _no_realpath
"""
    + _ARM_PATHLIB_ACCESSOR
    + _CONTROL_PROBE
)


def _require_live_world(result, world: str = "getcwd-denied"):
    """Skip rather than pass when the faked world did not actually break.

    Takes the world name because the two worlds go inert for entirely different
    reasons and only one of them is a reason to skip. Until 2026-08-31 this
    skipped citing the getcwd/Windows explanation no matter which world ran, and
    that cost a real measurement: on Python 3.10 the realpath-denied world was
    inert for a CURABLE reason (the captured pathlib accessor), and every pin
    using it skipped quietly under a message about os.getcwd and
    _getfullpathname. One assert-shaped pin went red on CI; the skip-shaped ones
    said nothing at all. A skip has to name its own cause or it hides the cases
    worth fixing.
    """
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
            "Path.resolve() on this platform (Windows resolves through "
            "_getfullpathname, not os.getcwd), so nothing is claimed either way"
        )
    assert "CONTROL_LIVE" in lines, (
        f"the child never reported whether its world took:\n{result.stdout}\n{result.stderr}"
    )
    return lines


# The probe path, built ONCE and before any world is installed.
#
# Round 8's 3.13 red was the probe dying while constructing its own input. A
# probe whose argument is computed inside the world it measures cannot report
# on that world — and it fails in the most misleading way available, by
# printing nothing at all.
_BUILD_PROBE_PATH = """
    import ntpath, os

    _ARM_ABS = {probe_literal}

    if not os.path.isabs(_ARM_ABS):
        print("PROBE_NOT_ABS", _ARM_ABS)
    if os.path.sep == ntpath.sep and not os.path.splitdrive(_ARM_ABS)[0]:
        # Keyed on the ACTIVE path module, not on os.name, so it fires under
        # the windows emulation as well as on the real runner.
        print("PROBE_NO_DRIVE", _ARM_ABS)

    # Published, not just checked: on 3.12 ntpath.isabs still accepted a
    # rooted-driveless path ("LEGACY BUG", ntpath.py:101), so a missing drive
    # changed nothing here and only showed up on 3.13. A value the test can
    # read is falsifiable on every version.
    print("PROBE_PATH", _ARM_ABS)
"""

# The emulation decides by MEASUREMENT, not by hasattr.
#
# hasattr(pathlib, "_NormalAccessor") answers "does an accessor exist", which
# is not the question. The question is "does Path.resolve actually travel
# through one", and a host shape can make those two disagree — a 3.10 host with
# the 3.13 shape installed HAS an accessor that resolve no longer consults.
# Measuring it also gives the pin its second, independent line: the child
# reports what it FOUND (ROUTE_WAS_NATIVE / ROUTE_WAS_DARK) separately from
# what it DID (ACCESSOR_NATIVE / ACCESSOR_EMULATED), and the two must agree.
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

        # Patched on Path — the base of PosixPath AND WindowsPath — because the
        # class the host instantiates is the only one that matters, and naming
        # the posix half is exactly how this went dark on the Windows runner.
        pathlib.Path._accessor = pathlib._normal_accessor
        pathlib.Path.resolve = _resolve_310
        print("ACCESSOR_EMULATED")
"""

# The emulation PROVES it took before anything downstream claims anything.
#
# This is the round-6 arming lesson applied one level up. On 3.13 and on
# windows the old emulation was silently inert: the pins failed for a reason
# that took a CI log and a traceback to name, when the child could simply have
# said so. A world that cannot report ROUTE_DARK is a world that reports every
# inert run as a measurement.
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

# ROUND 9 — THE CROSS TERMS. Every stand-in below was written as
# "3.12 plus a delta" and validated on a 3.12 box. On a real 3.10, 3.11, 3.13 or
# nt host it composes with a base it was never written against and produces a
# CHIMERA: a posix flavour stand-in on a host that constructs WindowsPath, a
# symptom table keyed to a flavour that is not there, a simulation of a property
# the host already has. The board's remaining reds were all cross terms.
#
# The rule, which is the three-verdict vocabulary pointed at the stand-ins
# themselves: a stand-in declares which REAL hosts it can speak from, measured
# in the child, and says UNAVAILABLE with its own reason everywhere else. The
# host is a fact to be measured, never a delta from the one I happen to run.
_REPORT_HOST = """
    import os, pathlib

    _flavour_of_host = getattr(pathlib.PurePosixPath, "_flavour", None)
    if _flavour_of_host is None:
        _FLAVOUR_KIND = "absent"
    elif hasattr(_flavour_of_host, "parse_parts"):
        _FLAVOUR_KIND = "object"
    else:
        _FLAVOUR_KIND = "module"

    _CONCRETE_KIND = "nt" if os.name == "nt" else "posix"
    _HAS_ACCESSOR = hasattr(pathlib, "_NormalAccessor")

    print("HOST", _FLAVOUR_KIND, _CONCRETE_KIND, "accessor" if _HAS_ACCESSOR else "no-accessor")
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


# ONE spelling of the probe path, substituted into the fragment that builds it,
# so no two fragments can disagree about what "absolute" means — everything
# downstream reuses the value, never the expression.
#
# Built from the host's own anchor rather than from os.sep alone: os.sep +
# "definitely" is DRIVE-RELATIVE on nt (@drone's sibling failure printed
# "RESOLVED: D:\\tmp"), and ntpath.realpath resolves such a path against the
# current drive — reading the cwd for a literal that looks absolute. abspath of
# the anchor is "/" on posix and "D:\\" on the runner.
_PROBE_LITERAL = 'os.path.join(os.path.abspath(os.sep), "definitely", "not", "here")'


def _compose(*chunks: str) -> str:
    """Join child-script fragments at column zero, skipping empty ones."""
    return "\n".join(
        textwrap.dedent(chunk).strip().replace("{probe_literal}", _PROBE_LITERAL) for chunk in chunks if chunk.strip()
    )


def _child_script(*chunks: str) -> str:
    """Every child starts with the host fingerprint. One rule, no exceptions.

    Round 9: each half now decides what it can honestly do from the host it
    finds itself on, so _FLAVOUR_KIND / _CONCRETE_KIND / _HAS_ACCESSOR have to
    exist before ANY chunk runs — including a half used as a simulation prelude,
    which is composed ahead of the shape it stands in for. Putting the
    fingerprint in _shape_prelude was one call site short of that, and the child
    died with NameError before a single half reported.
    """
    return _compose(_REPORT_HOST, *chunks)


def _host_line(result) -> list:
    """The child's own HOST fingerprint: flavour kind, concrete kind, accessor.

    The LAST one, deliberately. A child that simulates a foreign host re-reports
    afterwards, and what every half downstream decided against is the host in
    force at that point — not the box the process happened to start on.
    """
    fingerprints = [line for line in result.stdout.splitlines() if line.startswith("HOST ")]
    return fingerprints[-1].split()[1:] if fingerprints else []


# Round 10: the host's own PARSING DIALECT, measured rather than versioned.
#
# CI's 3.10 and 3.11 legs died inside the OLD emulation's flavour stand-in, and
# not because the stand-in was wrong: it forwards to the posixpath module, which
# is the thing a 3.12 flavour IS. What differs is the CONSUMER. On 3.10/3.11
# pathlib's own _parse_args calls `cls._flavour.parse_parts(parts)` — an API
# only the old _Flavour OBJECTS ever had, which no path module has ever
# carried. So a module-shaped flavour cannot serve those hosts no matter what it
# delegates to, and growing it a parse_parts of its own would be a simulation of
# a simulation (@devpulse's call, and I agree — that is a lap, not a cure).
#
# This probe asks the host directly instead of keying on a version: install a
# module-shaped flavour, build a path, and report what the host's pathlib
# reached for. Any row whose world contains a module-shaped flavour declares
# `parsing: module-tolerant` and SKIPS BY NAME with this answer elsewhere.
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

    The parent could import pathlib and ask these questions in-process. That
    would be a SECOND spelling of the host, free to drift from the one every
    child actually decides on — the same species as round 7's probe built out
    of the live os.path. One chunk, one measurement, both sides of the pipe.
    """
    result = _run(_child_script(), cwd=Path(__file__).parent)
    host = _host_line(result)
    if len(host) != 3:
        return {"flavour": "unknown", "concrete": "unknown", "accessor": "unknown"}
    return {"flavour": host[0], "concrete": host[1], "accessor": host[2]}


def _parsing_answer(result) -> str:
    """The child's dialect answer, or "unknown".

    Fails CLOSED, deliberately: a child that said nothing has not told me the
    host is tolerant, and defaulting to the convenient word would open every
    row this fact gates while looking exactly like a measurement.
    """
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

    Round 9's finding: a simulation is a stand-in too. "Make this box look like
    3.13" is a claim about the box making it, and on a box that is ALREADY 3.13
    — or that constructs WindowsPath, or whose flavour is natively an object —
    the simulation either never reaches the condition it exists to present or
    presents a different one silently. Then the test downstream measures the
    simulation instead of the harness, and its red names the wrong thing.

    A plain function of two dicts, so the rows for hosts this machine is not are
    reachable from this machine — @commons' rule, applied to the simulations.
    Empty string means it can speak; anything else is the reason it cannot.
    """
    for fact in sorted(requires):
        allowed = requires[fact]
        if host.get(fact) not in allowed:
            return (
                f"this simulation can only speak from a host whose {fact} is one of "
                f"{sorted(allowed)}; this host reports {host.get(fact)!r}"
            )
    return ""


# ntpath.realpath's win32 branch, the only half of it this table needs, read
# from CPython's Lib/ntpath.py rather than remembered. THE FALSIFIABLE PART IS
# THE ORDERING: `cwd = os.getcwd()` runs UNCONDITIONALLY, several lines ABOVE
# the `if not had_prefix and not isabs(path)` that would use it. On posix that
# module's realpath is just abspath, which reads the cwd only for a relative
# path — so the two platforms genuinely disagree, and a pin that asserts the
# posix answer everywhere is red on the runner.
#
# LINE NUMBERS AS A DATED COURTESY, not as the claim — @skills' correction, and
# the same species as trigger's round-5 line-scoped waiver: on 3.12.3 the read
# is at :673 in the str branch (:541 in the bytes branch) with the isabs check
# at :687, while an earlier reading of mine said :678 from another 3.12.x. The
# ordering survives a patch release; the number fails open and silent on a CI
# leg one bugfix along, and the fleet briefly had two citizens citing two
# numbers for one mechanism with no way for a third reader to tell which was
# stale.
#
# The abspath half is emulated too, and round 8 is why. win32 resolves a
# rooted-driveless path against the CURRENT DRIVE via _getfullpathname; posix
# ntpath has no drive to find, so it falls back to reading os.getcwd — and on
# 3.13 it reaches that fallback for a rooted path where 3.12 short-circuited
# (ntpath.isabs dropped the "LEGACY BUG" rooted-is-absolute case, 3.12:102 vs
# 3.13:95). That is what killed the nt-absolute row on the 3.13 and coverage
# legs: the probe was building its own argument through this function, inside
# the world that had already denied the cwd. Supplying a drive makes the
# emulated platform answer the way the real one does, on every version.
_WINDOWS_EMULATED = """
    import ntpath, os, sys

    _FAKE_DRIVE = "C:"

    def _win32_abspath(path):
        path = ntpath.normpath(os.fspath(path))
        if not ntpath.splitdrive(path)[0]:
            if path.startswith(ntpath.sep):
                path = _FAKE_DRIVE + path
            else:
                path = ntpath.join(_FAKE_DRIVE + ntpath.sep, path)
        return path

    def _win32_realpath(path, *, strict=False):
        path = ntpath.normpath(os.fspath(path))
        cwd = os.getcwd()
        if not ntpath.isabs(path):
            path = ntpath.join(cwd, path)
        return path

    ntpath.abspath = _win32_abspath
    ntpath.realpath = _win32_realpath
    os.path = ntpath
    os.sep = ntpath.sep
    sys.modules["os.path"] = ntpath
"""

# The other half of @memory's rule, and round 8's windows red: emulate BOTH
# platforms or neither. A "posix" row that installs nothing is not a posix row
# — it is the HOST, wearing a posix label, and on the Windows runner it
# measured nt and disagreed with its own table.
_POSIX_EMULATED = """
    import os, posixpath, sys

    os.path = posixpath
    os.sep = posixpath.sep
    sys.modules["os.path"] = posixpath
"""

# ROUND 9, the windows red on the posix-absolute row: a platform emulation is a
# stand-in too, and this pair is NOT symmetric.
#
# The posix emulation repoints os.path, os.sep and sys.modules["os.path"] — but
# pathlib's concrete class is chosen at import from os.name, and on Windows it
# stays WindowsPath. So the child builds a genuinely posix-absolute literal
# ("/definitely/not/here"), hands it to Path(), and Path spells it back in ITS
# dialect — "\\definitely\\not\\here" — which posixpath then reads as RELATIVE and
# resolves against the cwd. The row said INERT, the runner said ARMED, and both
# were right about different worlds: the emulation was a chimera, posix os.path
# with an nt concrete class.
#
# The nt emulation is not symmetric with it, and the asymmetry is the mechanism
# rather than luck: its row rests on ntpath.realpath reading os.getcwd
# UNCONDITIONALLY, above any question of what the path looks like. A dialect
# mismatch cannot change that verdict, so the nt rows can be measured from a
# posix host — while the posix rows, which turn entirely on whether the path
# reads as absolute, cannot be measured from an nt one.
#
# So: same three-verdict vocabulary as the halves and the simulations, one level
# out. A platform emulation says which real hosts it can speak from, and a row
# it cannot speak for SKIPS with that reason instead of asserting a POSIX fact
# on a Windows box.
_PLATFORM_EMULATIONS = {
    "posix": (_POSIX_EMULATED, {"concrete": ("posix",)}),
    "nt": (_WINDOWS_EMULATED, {}),
}
