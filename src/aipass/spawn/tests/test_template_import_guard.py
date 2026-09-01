"""What the newborn's handler guard must survive on its very first import.

Every citizen is born carrying `apps/handlers/__init__.py` from the template,
and that file runs `_guard_branch_access()` at import time — so a defect in it
is not a defect in one branch, it is a defect in every branch the factory has
ever shipped and every one it will ship.

MEASURED 2026-08-30 (@drone's dead-cwd pin, reported by @devpulse): the guard
resolved frame filenames BEFORE skipping pseudo-files like `<string>`, and
`Path(...).resolve()` on a relative or pseudo filename calls `os.getcwd()`. Any
process whose working directory had been deleted therefore died with
FileNotFoundError while importing ANY branch. All 18 live copies were fixed in
32db831c; these pins guard the TEMPLATE, so the next spawned branch is born
with the guarded form instead of re-inheriting the defect.

The tests render the template into a throwaway package and import it in a
subprocess, because that is the only way to exercise a file whose whole
behaviour happens at import time. The defect pins reproduce it in two worlds —
an injected cwd failure that runs on every OS, and a genuinely deleted directory
that runs wherever the OS allows the recipe — and the fence pins exist so the
fix cannot be mistaken for a weakened guard: it must still refuse an outside
caller and still admit an inside one.

ON THE CPYTHON LINE NUMBERS IN THIS FILE (@skills' round-9 correction): every
`pathlib.py:NNN` and `ntpath.py:NNN` below is a DATED COURTESY to the reader,
not the claim. They were read on 3.12.3 here, and on the 3.10/3.11/3.13 sources
fetched for the round that needed them, and they move between patch releases —
@skills and I cited two different numbers for one getcwd read within a day. What
is falsifiable, and what every comment states in words beside the number, is the
MECHANISM and the ORDERING: which call happens above which check, and what is
captured when. A pin whose reasoning rests on a line number fails open on the
next bugfix release, silently, which is the line-scoped-waiver species one
context over.
"""

import ast
import importlib
import ntpath
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from _pytest.outcomes import Failed, Skipped

from aipass.spawn.apps.handlers.class_registry import get_available_classes, get_template_dir


TEMPLATE_CLASSES = sorted(get_available_classes())

GUARD_RELATIVE_PATH = Path("apps") / "handlers" / "__init__.py"


def _template_guard(class_name: str) -> Path:
    return get_template_dir(class_name) / GUARD_RELATIVE_PATH


def _render(source: str) -> str:
    """Fill the two branch placeholders the way a real mint does."""
    return source.replace("{{BRANCHNAME}}", "NEWBORN").replace("{{BRANCH}}", "newborn")


def _plant_newborn(root: Path, class_name: str) -> Path:
    """Write the rendered guard at the path a real newborn would carry it.

    Returns the directory to put on sys.path.
    """
    package = root / "aipass" / "newborn" / "apps" / "handlers"
    package.mkdir(parents=True)

    for parent in (root / "aipass", root / "aipass" / "newborn", root / "aipass" / "newborn" / "apps"):
        (parent / "__init__.py").write_text("", encoding="utf-8")

    (package / "__init__.py").write_text(
        _render(_template_guard(class_name).read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    return root


def _run(script: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script).strip()],
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


# =============================================================================
# The two worlds, and why both exist
# =============================================================================

# The condition these pins reproduce is "the cwd read RAISES", not "a directory
# was deleted" — deletion is one way to arrive there, and on Windows it is not
# an available one: Windows locks a process's current directory, so the recipe
# dies at rmdir with WinError 32 before the test reaches its claim (round-2
# Windows gate, relayed by @devpulse 2026-08-31).
#
# MY PICK, stated so it can be quoted: BOTH, scoped by what each can honestly
# measure — @memory's injection as the portable pin that runs on every OS, and
# @drone's real-world recipe kept and skipped on win32, because Windows makes
# the RECIPE unavailable, not the STATE (a disconnected share or an ejected
# volume hands a live Windows process a dead cwd).
#
# @devpulse asked whether mine are the quiet species — a relative path resolving
# to the WRONG place rather than crashing — because the injection would then
# need to fake a different world. I MEASURED IT RATHER THAN ANSWERING: I rebuilt
# the pre-32db831c form (resolve first, skip second) and ran it with a live cwd
# from outside the newborn tree. Both forms imported cleanly. The old form
# still skipped `<string>` — it just paid for the resolve first — so the ONLY
# behavioural difference between defective and fixed is whether that resolve
# raises. There is no quiet species here, and that is precisely what licenses
# the injection: it reproduces the whole of the discriminator, not part of it.
#
# The injection carries a POSITIVE CONTROL for the same reason @memory's own
# skip-reads-green mutant taught the fleet: a faked world that fails to fake
# anything makes every pin pass. The child proves the call site is broken before
# it imports, and a test whose world did not take SKIPS with that reason instead
# of reporting a green it did not earn.

WINDOWS_RECIPE_SKIP = (
    "Windows locks a process's current working directory, so this recipe dies at "
    "rmtree with WinError 32 before reaching its claim. Windows makes the RECIPE "
    "unavailable, not the STATE — the portable injection pin above covers the "
    "state on every OS, and a disconnected share is how a live Windows process "
    "reaches it for real."
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

_INJECT_DEAD_CWD = (
    """
    import errno, os
    from pathlib import Path as _ProbePath

    def _no_cwd(*args, **kwargs):
        raise FileNotFoundError(errno.ENOENT, "No such file or directory")

    os.getcwd = _no_cwd
"""
    + _CONTROL_PROBE
)

_DELETE_CWD = (
    """
    import os, shutil, tempfile
    from pathlib import Path as _ProbePath

    doomed = tempfile.mkdtemp()
    os.chdir(doomed)
    shutil.rmtree(doomed)
"""
    + _CONTROL_PROBE
)

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

PORTABLE_WORLDS = {
    # Denying os.getcwd is @memory's construction. On POSIX it reaches
    # Path.resolve(); on Windows it reaches ntpath.realpath, which calls
    # os.getcwd() unconditionally on its first lines, before it even checks
    # whether the path is absolute.
    "getcwd-denied": _INJECT_DEAD_CWD,
    # Denying os.path.realpath is the call the Windows CI traceback actually
    # died in: inspect.stack() -> getsourcefile() -> getmodule() -> an
    # UNPROTECTED os.path.realpath(f). ADDED 2026-08-31 after the Windows gate
    # found a defect one line ABOVE the code the first fix guarded. On POSIX the
    # os.getcwd denial can never reach that call site — posixpath.abspath raises
    # first, inside getabsfile(), where inspect catches it
    # (`except (TypeError, FileNotFoundError): return None`) — which is exactly
    # why this was invisible on Linux for as long as it existed. Denying the
    # call the defect makes is the honest way to run CI's world from here.
    "realpath-denied": _DENY_REALPATH,
}

_NO_WORLD_AT_ALL = (
    """
    from pathlib import Path as _ProbePath
"""
    + _CONTROL_PROBE
)


def _in_dead_cwd(root: Path, world: str, tail: str, cwd: Path):
    """Run `tail` in a child whose cwd read is broken by `world`."""
    return _run(
        f"""
        import sys
        sys.path.insert(0, {str(root)!r})
        {textwrap.indent(textwrap.dedent(world).strip(), " " * 8).lstrip()}
        {textwrap.indent(textwrap.dedent(tail).strip(), " " * 8).lstrip()}
        """,
        cwd=cwd,
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


# =============================================================================
# The realpath denial has to arm on every interpreter, not just this one
# =============================================================================

# 3.10 pathlib.py:358 did `realpath = staticmethod(os.path.realpath)` on its
# accessor, at pathlib's first import. Nothing on this machine runs 3.10, so
# the CI leg that found this is not reproducible here by asking the
# interpreter — it is reproducible by REBUILDING the property on 3.12, which is
# @memory's falsifiability rule: an interpreter difference you cannot run is
# still a difference you can construct.
#
# ROUND 7, and this is the correction that matters: the first version of that
# rebuild WORKED ONLY ON THE INTERPRETER IT WAS WRITTEN ON. It rerouted
# Path.resolve by replacing `PurePosixPath._flavour` with a wrapper around the
# posixpath MODULE, which is a 3.12 shape and only a 3.12 shape. CI on
# c82c3d34 convicted it on 3.10, 3.11, 3.13 and windows at once.
#
# THE TABLE BELOW WAS READ, NOT INFERRED — CPython Lib/pathlib.py per branch,
# fetched and grepped this session, because round 6's lesson was bought with a
# wrong mechanism that sounded right (mine), and my first write-up of this one
# was wrong too: I had 3.13 routing resolve through `parser`. It does not.
#
#   3.10  resolve -> `self._accessor.realpath(self, strict=strict)` (:1071)
#         accessor captured EAGERLY at import: `realpath =
#         staticmethod(os.path.realpath)` (:358), `_normal_accessor` (:361),
#         `Path._accessor = _normal_accessor` (:954). _flavour is a
#         _PosixFlavour OBJECT (:928 -> :274) carrying parse_parts (:56).
#   3.11  resolve -> `os.path.realpath(self, strict=strict)` (:992) — MODULE
#         level, dynamic, no accessor at all. _flavour is still an OBJECT
#         (:840). So 3.11's red was never about the route: the emulation died
#         while PARSING, because a wrapper around the posixpath module has no
#         parse_parts. Same cause as 3.10's red, different half of the file.
#   3.12  resolve -> `self._flavour.realpath(...)`, and _flavour IS the
#         posixpath module. The only version the old emulation matched.
#   3.13  pathlib became a package; _local.py:670 is
#         `self.with_segments(os.path.realpath(self, strict=strict))` and the
#         string `_flavour` appears ZERO times in it (`parser = os.path` at
#         :104 is for parsing only). Writing _flavour was a write nothing read,
#         so the real realpath answered and the bare rebinding ARMED.
#   nt    the host instantiates WindowsPath, which is not in the PosixPath
#         hierarchy the emulation patched, and its flavour IS the live os.path
#         module. Same inertness, same armed bare rebinding.
#
# So the emulation now assumes NOTHING about how the host spells its routing.
# It touches exactly two things — a module-level accessor of its own making,
# and `Path.resolve` on the class the host actually instantiates — and it
# replaces no host object, which is what took 3.10/3.11 down. Where the
# interpreter HAS the accessor natively (real <=3.10), it emulates nothing and
# the native one is measured instead: emulating over the real thing would grade
# my stand-in on the only interpreters that carry the defect for real.
# ROUND 8 — THE SAME SPECIES, ONE LEVEL UP: the HARNESS was 3.12-shaped.
#
# The emulation above stopped assuming an interpreter; the machinery that
# INSTALLS it did not. CI on 68ab5132 convicted it on five legs at once, and
# every failure was a stand-in that could only run where it was written:
#
#   * 3.10 and 3.11 hosts — the shape preludes reached
#     `pathlib.PurePath._parse_path`, which is 3.12+ (those versions spell it
#     `_parse_args`). The child died at line 16 before printing anything, so 37
#     tests failed saying "the child never reported whether its route armed" —
#     a harness crash wearing the arming probe's message.
#   * a 3.10 host also failed the 3.12-as-it-is row of the accessor pin,
#     because the EXPECTATION was keyed on the SHAPE'S NAME rather than on what
#     the host actually is. On 3.10 every row is ACCESSOR_NATIVE and that is
#     correct.
#   * 3.13 (and the coverage leg, which also runs 3.13 — ci.yml:101) — the
#     nt-absolute getcwd row. The probe built its own input with
#     os.path.abspath AFTER the world denied os.getcwd; 3.13's ntpath.isabs
#     stopped accepting a rooted-driveless path, so abspath reached the cwd
#     where 3.12 short-circuited. The probe died constructing its argument.
#   * windows — the posix rows of the getcwd table ran BARE, so on an nt host
#     they measured nt under a posix label (@memory's rule, exactly), and the
#     drive row asserted a posix answer for a "here" hard-coded to Linux.
#
# THE RULE THIS FILE NOW FOLLOWS, and it is one rule: every stand-in states
# what it needs from the host, reports whether it took, and stands down where
# the host already IS the thing it stands in for. Nothing is keyed on a version
# number or on a shape's name; everything is keyed on a fact the child measures
# and prints. A test whose stand-in cannot be built here SKIPS with the child's
# own reason instead of failing on someone else's interpreter.

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

# The version CI convicted, kept verbatim and PUBLISHED as a negative control.
#
# Deleting it would leave the host shapes below unfalsifiable: preludes that
# nothing fails against are preludes nobody can tell are working. This one
# fails against each of them, in the exact shape its CI leg reported.
_EMULATION_THAT_ASSUMED_ONE_INTERPRETER = """
    import os.path, pathlib, posixpath

    class _NormalAccessor310:
        realpath = staticmethod(os.path.realpath)

    pathlib._NormalAccessor = _NormalAccessor310
    pathlib._normal_accessor = _NormalAccessor310()

    class _EagerFlavour:
        def __init__(self, mod):
            self._mod = mod

        def __getattr__(self, name):
            return getattr(self._mod, name)

        def realpath(self, path, strict=False):
            return pathlib._normal_accessor.realpath(str(path))

    _flav = _EagerFlavour(posixpath)
    pathlib.PurePosixPath._flavour = _flav
    pathlib.PosixPath._flavour = _flav
    print("ROUTE_WAS_DARK")
    print("ACCESSOR_EMULATED")
"""

# =============================================================================
# Host shapes, built from HALVES that each answer for themselves
# =============================================================================
#
# Each half installs one property of a real interpreter, and each reports one
# of three verdicts:
#
#   HALF:<name>:NATIVE       the host already has it — install nothing
#   HALF:<name>:INSTALLED    the stand-in is in place
#   HALF:<name>:UNAVAILABLE:<reason>   this host cannot carry the stand-in
#
# UNAVAILABLE is a SKIP, not a failure, and it carries the child's own reason —
# because "3.13 has no _flavour to stand in for" and "the stand-in is broken"
# look identical from a red test and are not the same thing at all.

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

_HALF_FLAVOUR_OBJECT = """
    import pathlib, posixpath

    _host_flavour = getattr(pathlib.PurePosixPath, "_flavour", None)
    if _CONCRETE_KIND == "nt":
        # The stand-in and its parse hook are POSIX: they replace
        # PurePosixPath._flavour and route PurePath._parse_path through it. On a
        # host that constructs WindowsPath neither is on the path the child
        # travels, and installing them anyway hands the hook an ntpath module
        # with no parse_parts. Round 9's windows reds, in one clause.
        print("HALF:flavour-object:UNAVAILABLE:this host constructs WindowsPath; the stand-in is posix-only")
    elif _host_flavour is None:
        print("HALF:flavour-object:UNAVAILABLE:this host has no _flavour at all (3.13+)")
    elif hasattr(_host_flavour, "parse_parts"):
        print("HALF:flavour-object:NATIVE")
    elif not hasattr(pathlib.PurePath, "_parse_path"):
        print("HALF:flavour-object:UNAVAILABLE:no _parse_path to route parsing through")
    else:
        class _FlavourObject:
            sep = posixpath.sep
            altsep = ""

            def __getattr__(self, name):
                return getattr(posixpath, name)

            def parse_parts(self, parts):
                return ("", posixpath.sep, list(parts))

        pathlib.PurePosixPath._flavour = _FlavourObject()
        pathlib.PosixPath._flavour = pathlib.PurePosixPath._flavour

        _real_parse = pathlib.PurePath._parse_path.__func__

        def _parse_path_via_flavour(cls, path):
            cls._flavour.parse_parts([path])
            return _real_parse(cls, path)

        pathlib.PurePath._parse_path = classmethod(_parse_path_via_flavour)
        print("HALF:flavour-object:INSTALLED")
"""

_HALF_ACCESSOR_ROUTE = """
    import os, os.path, pathlib

    if hasattr(pathlib, "_NormalAccessor"):
        print("HALF:accessor-route:NATIVE")
    else:
        class _NormalAccessorShape:
            realpath = staticmethod(os.path.realpath)

        pathlib._NormalAccessor = _NormalAccessorShape
        pathlib._normal_accessor = _NormalAccessorShape()

        def _resolve_via_accessor(self, strict=False):
            return type(self)(self._accessor.realpath(self, strict=strict))

        pathlib.Path._accessor = pathlib._normal_accessor
        pathlib.Path.resolve = _resolve_via_accessor
        print("HALF:accessor-route:INSTALLED")
"""

_HALF_DIRECT_RESOLVE = """
    import os, pathlib

    def _resolve_direct(self, strict=False):
        return type(self)(os.path.realpath(self, strict=strict))

    pathlib.Path.resolve = _resolve_direct
    print("HALF:direct-resolve:INSTALLED")
"""

_HALF_FOREIGN_CONCRETE_CLASS = """
    import os.path, pathlib

    # MEASURED, so the copy below is not tidied away: deleting it kills the
    # shape (the class becomes unconstructible), while changing the BASE class
    # or routing resolve through os.path directly changes nothing on 3.12 —
    # both are equivalents here, because the copy is what makes this class
    # foreign and on 3.12 the copied flavour IS os.path.
    _base_flavour = getattr(pathlib.PurePosixPath, "_flavour", None)

    class _ForeignPath(pathlib.PurePath):
        # Deliberately OUTSIDE the PosixPath hierarchy, the way WindowsPath is,
        # and carrying the host's own flavour so it is constructible on every
        # version. The flavour is copied at class creation, so a later patch of
        # PurePosixPath._flavour cannot reach it — which is the whole point.
        if _base_flavour is not None:
            _flavour = _base_flavour

        def resolve(self, strict=False):
            # Through the flavour when the flavour IS a path module, the way
            # WindowsPath does on 3.12 — that is what makes the copied flavour
            # load-bearing: inherit the posix one instead of copying it and the
            # emulation's patch reaches this class, which is the foreignness the
            # shape exists to reproduce.
            #
            # ROUND 9: on 3.10 and 3.11 the flavour is a _PosixFlavour OBJECT
            # with no realpath at all, and this line died with
            # "'_PosixFlavour' object has no attribute 'realpath'". A stand-in
            # that assumes what a host attribute IS, rather than asking, is the
            # same defect as assuming the host version.
            _mod = getattr(type(self), "_flavour", None)
            if not hasattr(_mod, "realpath"):
                _mod = os.path
            return type(self)(_mod.realpath(self, strict=strict))

    pathlib.Path = _ForeignPath
    print("HALF:foreign-concrete-class:INSTALLED")
"""

# CI's 3.11 red, in a chunk: a flavour that is an OBJECT and has no realpath.
# The real _PosixFlavour is exactly this — it carries parsing and nothing else —
# and the foreign-class shape read it as a path module and died with
# "'_PosixFlavour' object has no attribute 'realpath'". My own stand-in cannot
# reproduce that: it forwards every unknown attribute to posixpath, so it HAS a
# realpath and the assumption stays invisible. An emulation that is friendlier
# than the thing it emulates hides the defect it was built to find.
_A_FLAVOUR_OBJECT_THAT_IS_NOT_A_PATH_MODULE = """
    import pathlib, posixpath

    class _FlavourWithoutRealpath:
        sep = posixpath.sep
        altsep = ""

        def __getattr__(self, name):
            if name in ("realpath", "abspath"):
                raise AttributeError(f"'_PosixFlavour' object has no attribute '{name}'")
            return getattr(posixpath, name)

        def parse_parts(self, parts):
            return ("", posixpath.sep, list(parts))

    pathlib.PurePosixPath._flavour = _FlavourWithoutRealpath()
    pathlib.PosixPath._flavour = pathlib.PurePosixPath._flavour
    print("FLAVOUR_WITHOUT_REALPATH_INSTALLED")
"""


_HOST_SHAPES = {
    # 3.12 as it really is here: no halves at all, so a shape can be compared
    # against whatever interpreter the file is actually running on.
    "3.12-as-it-is": (),
    # 3.10: resolve travels through an eagerly-captured accessor, and _flavour
    # is an OBJECT reached during PARSING.
    "3.10-native-accessor-and-flavour-object": (_HALF_FLAVOUR_OBJECT, _HALF_ACCESSOR_ROUTE),
    # 3.11: flavour is still an OBJECT, but resolve calls os.path.realpath at
    # MODULE level and there is no accessor. Its CI red was the parsing half,
    # not the route — which is why both halves are named separately.
    "3.11-flavour-object-and-direct-resolve": (_HALF_FLAVOUR_OBJECT, _HALF_DIRECT_RESOLVE),
    # 3.13: no accessor, no _flavour on the resolve path.
    "3.13-no-accessor-direct-resolve": (_HALF_DIRECT_RESOLVE,),
    # windows: the class the host instantiates is not in the PosixPath
    # hierarchy, and its realpath is the live os.path one.
    "nt-concrete-class-is-not-posix": (_HALF_FOREIGN_CONCRETE_CLASS,),
}

# The shapes the OLD emulation must die against. "3.12-as-it-is" is not among
# them, and that absence is the finding: the old emulation passed here for two
# rounds because the only interpreter it was ever run against was the one it
# assumed.
#
# Requiring a NAMED symptom rather than "it failed somehow" is what keeps the
# shapes honest: without it, a shape that reproduced only HALF an interpreter
# would still convict — and both flavour-object shapes did exactly that in the
# first cut, with their parsing halves decorative and unmeasured.
#
# What the OLD emulation dies of is a function of the COMPOSED world, not of the
# shape alone — round 9's clearest cross term. It replaces PurePosixPath._flavour
# with a module wrapper, so:
#
#   * parse_parts fires only where parsing actually travels through that object:
#     a posix-constructed class whose flavour is an OBJECT, native (3.10/3.11)
#     or stood in for (3.12 + the flavour half).
#   * everywhere else the write is inert or harmless and the bare rebinding
#     reaches the real realpath instead — PATHLIB_ARMED.
#   * the foreign-class shape is always the second case, because the class it
#     constructs carries its OWN flavour copy and the emulation's write cannot
#     reach it. That is the whole point of that shape.
#
# The old table hard-coded parse_parts for two shape NAMES, which was right on a
# 3.12 box and wrong on every other host: on a real 3.13 there is no flavour to
# replace, and on a real 3.11 the 3.13 shape inherits an object flavour and dies
# of parse_parts after all.
_FOREIGN_CLASS_SHAPE = "nt-concrete-class-is-not-posix"


def _expected_old_emulation_symptom(flavour_in_force: str, shape: str) -> str:
    """Two rows, each read off a CI traceback rather than reasoned about.

    The old emulation installs an eager accessor of its own AND replaces
    PurePosixPath._flavour with an eager wrapper. So it loses in exactly two
    ways, and which one depends on the COMPOSED world:

      parse_parts — parsing travels through the flavour, i.e. the flavour in
        force is an OBJECT (native on 3.10/3.11, stood in for on 3.12) and the
        child is constructing a posix class. The wrapper is a module wrapper
        with no parse_parts, so the child dies at Path(...) before resolve is
        ever reached. CI 3.11, verbatim: "module 'posixpath' has no attribute
        'parse_parts'" out of pathlib.py:502 _parse_args.

      ROUTE_DARK — everywhere else. Each shape puts the resolve route somewhere
        the emulation's accessor is not: the accessor half binds Path._accessor
        to ITS instance, the direct-resolve half bypasses accessors entirely,
        and the foreign class is not in the hierarchy at all. The arming probe
        patches pathlib._NormalAccessor.realpath — the emulation's own class —
        and nothing calls it.

    What the old table pinned instead was PATHLIB_ARMED / PATHLIB_INERT, which
    is the INCIDENTAL half: whether a bare os.path.realpath rebinding reaches
    the route afterwards. That answer moves with the host for reasons that have
    nothing to do with the emulation — 3.13 + the accessor shape gives INERT,
    the same shape one version down gives ARMED, and on Windows the foreign
    class resolves through posixpath while os.path IS ntpath, so the rebinding
    cannot reach it and INERT comes back there too. Three CI reds, one wrong
    question.
    """
    if flavour_in_force == "object" and shape != _FOREIGN_CLASS_SHAPE:
        return "parse_parts"
    return "ROUTE_DARK"


def _host_line(result) -> list:
    """The child's own HOST fingerprint: flavour kind, concrete kind, accessor.

    The LAST one, deliberately. A child that simulates a foreign host re-reports
    afterwards, and what every half downstream decided against is the host in
    force at that point — not the box the process happened to start on.
    """
    fingerprints = [line for line in result.stdout.splitlines() if line.startswith("HOST ")]
    return fingerprints[-1].split()[1:] if fingerprints else []


def _flavour_in_force(result) -> str:
    """object / module / absent — after every half has had its say."""
    if "HALF:flavour-object:INSTALLED" in result.stdout:
        return "object"
    if "HALF:flavour-object:NATIVE" in result.stdout:
        return "object"
    host = _host_line(result)
    return host[0] if host else "unknown"


_SHAPES_THAT_CONVICT_THE_OLD_EMULATION = sorted(set(_HOST_SHAPES) - {"3.12-as-it-is"})

_BARE_REBINDING_ONLY = """
    import errno, os, os.path
    from pathlib import Path as _ProbePath

    def _no_realpath(*args, **kwargs):
        raise FileNotFoundError(errno.ENOENT, "No such file or directory")

    os.path.realpath = _no_realpath
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

# Same probe, relative input. @skills' round-7 finding, answered by measurement
# rather than by agreement: cwd and resolve ride DIFFERENT captured attributes
# on <=3.10, so arming one says nothing about the other.
_PATHLIB_ROUTE_PROBE_RELATIVE = """
    from pathlib import Path as _RoutePath

    try:
        _RoutePath("relative_thing").resolve()
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


def _shape_prelude(shape: str) -> str:
    """The halves of a host shape, composed in order."""
    return _compose(*_HOST_SHAPES[shape])


def _unavailable_half(result) -> str:
    """The child's own reason, when a stand-in cannot be built on this host."""
    for line in result.stdout.splitlines():
        if line.startswith("HALF:") and ":UNAVAILABLE:" in line:
            return line
    return ""


class TestTheRealpathDenialArmsOnEveryInterpreter:
    """The 3.10 CI red, reproduced and cured without a 3.10 on the machine.

    FOUND BY CI, not here: the 3.10 leg of 8550ed10 failed this file's
    direct-call pin with "os.path.realpath denial was inert in the child, so
    this run claims nothing" — the arming probe refusing to make a claim, which
    is the instrument working rather than breaking. 3.11-3.13 were green.

    Worth stating because it is the uncomfortable half: that probe reached the
    pathlib route because I changed it to, one session earlier, on the argument
    that a probe should ask through the route the code under test travels. The
    argument was right and the comment I wrote next to it named this exact
    hazard — "if pathlib ever bound realpath eagerly instead of looking it up on
    the module". On <=3.10 it does. The reasoning predicted the failure and the
    implementation shipped into it anyway.

    ROUND 7 (@devpulse, c82c3d34): the CURE then failed on four legs of its own
    — 3.10, 3.11, 3.13 and windows — because the emulation built to survive one
    interpreter difference was written against a second one. Every test here now
    runs under each HOST SHAPE, so "arms on every interpreter" is measured
    against five of them rather than promised by a class name.
    """

    def _child(self, shape: str, world: str, probe: str = _PATHLIB_ROUTE_PROBE):
        return _run(
            _child_script(
                _shape_prelude(shape),
                _BUILD_PROBE_PATH,
                _EMULATE_310,
                _ARM_THE_ROUTE,
                world,
                probe,
            ),
            cwd=Path(__file__).parent,
        )

    def _armed(self, result, shape: str) -> list:
        """Refuse to read a verdict out of a child whose route never armed.

        A stand-in the host cannot carry is a SKIP carrying the child's own
        reason. Round 8's 3.10 and 3.11 legs failed 37 tests under the arming
        probe's message when what had actually happened was a shape prelude
        crashing on plumbing those versions do not have — the message named the
        instrument that never ran instead of the one that broke.
        """
        missing = _unavailable_half(result)
        if missing:
            pytest.skip(f"host shape {shape!r} cannot be built here: {missing}")

        lines = result.stdout.split()
        assert "PROBE_NOT_ABS" not in lines, (
            f"the probe literal is not absolute on this runner ({shape}) — an "
            "absolute path is whatever os.path.isabs says it is, and a "
            f"drive-relative one reads the cwd instead:\n{result.stdout}"
        )
        assert "ROUTE_DARK" not in lines, (
            f"the emulation did not take under host shape {shape!r}: Path.resolve "
            "never reached the accessor, so nothing below this line measures "
            f"anything.\n{result.stdout}\n{result.stderr}"
        )
        assert "ROUTE_ARMED" in lines, (
            f"the child never reported whether its route armed ({shape}):\n{result.stdout}\n{result.stderr}"
        )
        return lines

    @pytest.mark.parametrize("shape", sorted(_HOST_SHAPES))
    def test_the_emulation_says_which_accessor_it_measured(self, shape):
        """Native or stand-in — the child names it, so no run is ambiguous.

        The real-3.10 shape is the one with a claim in it: emulating on top of a
        native accessor would grade my stand-in on the only interpreters that
        carry the defect for real.
        """
        lines = self._armed(self._child(shape, _BARE_REBINDING_ONLY), shape)

        # NOT keyed on the shape's name, and not on a version: keyed on what
        # the child FOUND. On a 3.10 host every row is ACCESSOR_NATIVE and that
        # is correct — the round-8 red here was an expectation that only knew
        # how to be right on 3.12.
        found_native = "ROUTE_WAS_NATIVE" in lines
        decided_native = "ACCESSOR_NATIVE" in lines
        decided_emulated = "ACCESSOR_EMULATED" in lines

        assert decided_native != decided_emulated, f"the child reported neither decision, or both:\n{lines}"
        assert decided_native == found_native, (
            f"the child found the accessor route {'live' if found_native else 'dark'} "
            f"and then did the opposite ({shape!r}): emulating over a live accessor "
            f"grades the stand-in instead of the interpreter.\n{lines}"
        )

    @pytest.mark.parametrize("shape", sorted(_HOST_SHAPES))
    def test_the_bare_rebinding_is_inert_under_the_emulation(self, shape):
        """CI's 3.10 failure, reproduced on this interpreter.

        Doubles as the eager-capture pin: a published emulated shape needs
        something that fails when the emulation stops emulating. If
        _NormalAccessor310 captured lazily, the rebinding would reach it and
        this would report PATHLIB_ARMED.
        """
        result = self._child(shape, _BARE_REBINDING_ONLY)
        lines = self._armed(result, shape)

        assert "PATHLIB_INERT" in lines, (
            "rebinding os.path.realpath was expected to be INERT against an "
            f"eagerly-captured accessor under host shape {shape!r} — if this "
            f"armed, the emulation is no longer emulating 3.10:\n{result.stdout}\n{result.stderr}"
        )

    @pytest.mark.parametrize("shape", sorted(_HOST_SHAPES))
    def test_the_shipped_world_arms_the_pathlib_route_under_the_emulation(self, shape):
        """The cure, measured against the same emulation."""
        result = self._child(shape, _DENY_REALPATH)
        lines = self._armed(result, shape)

        assert "PATHLIB_ARMED" in lines, (
            "the shipped realpath-denied world did not reach Path.resolve() "
            f"through an eagerly-captured accessor under host shape {shape!r} — "
            "the _ARM_PATHLIB_ACCESSOR half is what makes this work on <=3.10:"
            f"\n{result.stdout}\n{result.stderr}"
        )

    @pytest.mark.parametrize("shape", _SHAPES_THAT_CONVICT_THE_OLD_EMULATION)
    def test_the_previous_emulation_dies_against_the_shape_it_assumed_away(self, shape):
        """The negative control for the host shapes themselves.

        A prelude nothing fails against is a prelude nobody can tell is
        working. The emulation CI convicted is kept above and run here: it must
        fail to deliver a usable verdict under every shape but the one it was
        written on. If this ever goes green, the shape stopped reproducing the
        interpreter and the pins above are measuring 3.12 five times.
        """
        result = _run(
            _child_script(
                _shape_prelude(shape),
                _BUILD_PROBE_PATH,
                _EMULATION_THAT_ASSUMED_ONE_INTERPRETER,
                _ARM_THE_ROUTE,
                _BARE_REBINDING_ONLY,
                _PATHLIB_ROUTE_PROBE,
            ),
            cwd=Path(__file__).parent,
        )

        lines = result.stdout.split()
        armed_and_inert = "ROUTE_ARMED" in lines and "PATHLIB_INERT" in lines
        assert not armed_and_inert, (
            f"the old emulation survived host shape {shape!r} — the shape is no "
            f"longer reproducing the interpreter that convicted it:\n{result.stdout}"
        )

        # Round 9: the symptom is derived from what the child MEASURED, not
        # from the shape's name. On a 3.11 box the 3.13 shape inherits an object
        # flavour and dies of parse_parts; on a 3.13 box the 3.10 shape has no
        # flavour to stand in for and the old emulation goes inert instead. Both
        # are the old emulation losing — they just lose differently, and a table
        # written on 3.12 called one of them a wrong symptom.
        in_force = _flavour_in_force(result)
        if in_force == "unknown":
            pytest.fail(
                f"the child never printed its HOST fingerprint under shape {shape!r}, so "
                f"which symptom to expect cannot be derived:\n{result.stdout}\n{result.stderr}"
            )

        symptom = _expected_old_emulation_symptom(in_force, shape)
        # Token-matched in stdout, substring in stderr: the emulation prints its
        # own fixed ROUTE_WAS_DARK line, and a substring test against stdout
        # would be one careless edit away from accepting the emulation's own
        # boast as the arming probe's verdict.
        #
        # PUBLISHED AS EQUIVALENT rather than counted as a kill: restoring the
        # substring form passes every row today, because "ROUTE_WAS_DARK" does
        # not contain "ROUTE_DARK". Nothing here can tell the two apart, and the
        # token form is bought for the next marker that shares a prefix — said
        # out loud, because a mutant nobody can kill and a pin nobody wrote look
        # identical in a survivor table.
        convicted_as_predicted = symptom in result.stdout.split() or symptom in result.stderr
        assert convicted_as_predicted, (
            f"host shape {shape!r} with a {in_force!r} flavour in force convicted the old "
            f"emulation, but not with the symptom that composition predicts ({symptom!r}) — "
            f"it is reproducing some other half of that interpreter:\n{result.stdout}\n{result.stderr}"
        )

    # The recorder replaces the world's `_no_realpath`, so what gets measured is
    # the SHIPPED _ARM_PATHLIB_ACCESSOR text and not a second spelling of it in
    # this test.
    _RECORDING_DENIAL = """
        import os

        _seen_here = []

        def _no_realpath(*args, **kwargs):
            _seen_here.append(args[0] if args else None)
            return os.path.join(os.path.abspath(os.sep), "recorded")
    """

    _READ_THE_FIRST_ARG = """
        import pathlib as _pathlib

        _pathlib.Path(_ARM_ABS).resolve()
        print("FIRST_ARG", _seen_here[0])
    """

    @pytest.mark.parametrize("shape", sorted(_HOST_SHAPES))
    def test_the_accessor_patch_receives_the_path_and_not_the_accessor(self, shape):
        """@devpulse's trap (a), measured on the shipped text itself.

        A plain function assigned to the accessor CLASS binds on instance
        access and eats the path into self. Every denial in this file raises
        unconditionally, so it would raise just the same with the wrong
        argument — the pin would stay green for a reason that has nothing to do
        with what it claims. The only way to see it is to look at what the
        patched callable was actually handed, so the recorder here REPLACES the
        world's own `_no_realpath` and _ARM_PATHLIB_ACCESSOR is then applied
        verbatim: what gets measured is the shipped text, not a second spelling
        of it in this test.
        """
        result = _run(
            _child_script(
                _shape_prelude(shape),
                _BUILD_PROBE_PATH,
                _EMULATE_310,
                _ARM_THE_ROUTE,
                self._RECORDING_DENIAL,
                _ARM_PATHLIB_ACCESSOR,
                self._READ_THE_FIRST_ARG,
            ),
            cwd=Path(__file__).parent,
        )

        lines = self._armed(result, shape)
        assert "FIRST_ARG" in lines, f"the recorder never ran ({shape}):\n{result.stdout}\n{result.stderr}"
        first_arg = lines[lines.index("FIRST_ARG") + 1]
        assert first_arg.endswith("here"), (
            "the accessor patch was handed something other than the path — a "
            "plain function on the class binds and eats the path into self, and "
            f"a raise-shaped denial can never notice ({shape}): {first_arg!r}"
        )

    def test_an_instance_attribute_would_shadow_the_class_patch(self):
        """WHY the world sets no instance half — @drone's finding, rebuilt here.

        I recommended the belt-and-braces pair to @memory one session ago and
        was wrong: an instance attribute shadows the class descriptor, so with
        both applied the class half can no longer be falsified. Their reply
        checked sufficiency in CPython (3.10 pathlib.py:361 builds ONE shared
        accessor with no instance attributes, :954 hands it to Path), and this
        is the behavioural half of that argument — the mechanism itself, so the
        pair cannot quietly come back as an obvious improvement.
        """
        result = _run(
            _child_script(
                _BUILD_PROBE_PATH,
                _EMULATE_310,
                _ARM_THE_ROUTE,
                """
                import errno, os, pathlib as _pathlib

                def _no_realpath(*args, **kwargs):
                    raise FileNotFoundError(errno.ENOENT, "denied")

                def _untouched(path, *a, **k):
                    return str(path)
                """,
                _ARM_PATHLIB_ACCESSOR,
                """
                # The shadowing half, added on purpose: a bare instance
                # attribute that does NOT deny.
                _pathlib._normal_accessor.realpath = _untouched

                try:
                    _pathlib.Path(_ARM_ABS).resolve()
                except OSError:
                    print("CLASS_PATCH_ANSWERED")
                else:
                    print("INSTANCE_SHADOWED_THE_CLASS")
                """,
            ),
            cwd=Path(__file__).parent,
        )

        assert "INSTANCE_SHADOWED_THE_CLASS" in result.stdout.split(), (
            "an instance attribute no longer shadows the class patch — then the "
            "belt-and-braces pair is safe again and the ruling above is stale:"
            f"\n{result.stdout}\n{result.stderr}"
        )

    def test_an_inert_realpath_world_fails_rather_than_skipping(self):
        """The gate change itself, which nothing else reaches.

        Both worlds report inertness identically (CONTROL_DEAD), so the only
        thing separating "platform difference, claim nothing" from "the world is
        broken, say so" is which world asked. A skip that can fire for a cause
        it does not name is how the 3.10 leg stayed quiet.
        """

        class _FakeResult:
            stdout = "CONTROL_DEAD\n"
            stderr = ""

        # NOT pytest.raises(Failed): pytest.skip raises Skipped, which sails
        # straight through a raises(Failed) block and retires the whole test as
        # SKIPPED — green suite, defeat reported as a pass. Caught by mutating
        # the gate back to its pre-fix behaviour, which this pin exists to
        # convict and initially did not.
        try:
            _require_live_world(_FakeResult(), "realpath-denied")
        except Failed as exc:
            assert "no known platform reason" in str(exc), exc
        except Skipped:
            pytest.fail("the gate SKIPPED an inert realpath-denied world instead of failing it")
        else:
            pytest.fail("the gate accepted an inert realpath-denied world without complaint")

        with pytest.raises(Skipped):
            _require_live_world(_FakeResult(), "getcwd-denied")

    def test_the_arming_probe_can_report_a_route_that_never_armed(self):
        """The negative control FOR the arming probe.

        My own round-4 lesson, and it applies to this file's newest instrument:
        a CONTROL_LIVE probe that cannot say NO turns every pin downstream
        vacuously green. ROUTE_ARMED is now load-bearing in _armed(), so
        something has to prove the child can print ROUTE_DARK. This restores the
        real resolve after the emulation installed its own — the route is
        genuinely bypassed, and the probe must notice.
        """
        result = _run(
            _child_script(
                _BUILD_PROBE_PATH,
                _EMULATE_310,
                """
                import os, pathlib

                def _resolve_around_the_accessor(self, strict=False):
                    return type(self)(os.path.realpath(self))

                pathlib.Path.resolve = _resolve_around_the_accessor
                """,
                _ARM_THE_ROUTE,
            ),
            cwd=Path(__file__).parent,
        )

        assert "ROUTE_DARK" in result.stdout.split(), (
            "the arming probe reported ARMED for a route that goes nowhere near "
            f"the accessor — it cannot say NO:\n{result.stdout}\n{result.stderr}"
        )

    def test_the_accessor_patch_is_a_no_op_where_there_is_no_accessor(self):
        """hasattr-guarded, so 3.11+ is untouched rather than version-checked.

        Without the emulation there is no _NormalAccessor on 3.11+, so the
        guarded block must do nothing and the world must still arm through the
        call-time lookup that those versions use.
        """
        result = _run(
            _child_script(
                _BUILD_PROBE_PATH,
                _DENY_REALPATH,
                """
                import pathlib
                print("ACCESSOR_ABSENT" if not hasattr(pathlib, "_NormalAccessor") else "ACCESSOR_PRESENT")
                """,
                _PATHLIB_ROUTE_PROBE,
            ),
            cwd=Path(__file__).parent,
        )

        lines = result.stdout.split()
        if "ACCESSOR_PRESENT" in lines:
            pytest.skip("this interpreter has the accessor; the no-op claim is not testable here")
        assert "PATHLIB_ARMED" in lines, (
            f"the world stopped arming on an interpreter with no accessor:\n{result.stdout}\n{result.stderr}"
        )


# =============================================================================
# The harness itself, run on a host that is not the one it was written on
# =============================================================================
#
# Round 8's reds were not in the emulation — they were in the machinery that
# installs it. These simulations make this 3.12 interpreter present the plumbing
# of the hosts that convicted it, so "the harness survives a host that is not
# 3.12" is a measurement here rather than a promise checked by CI.
#
# The scope is part of the simulation, not an afterthought: shadowing a pathlib
# class is a blunt instrument, and pointing it at a shape whose halves do not
# read that class produces a failure about the simulation rather than about the
# harness. Saying which shapes a simulation speaks for is cheaper than a
# cleverer simulation, and it is honest about what is being claimed.
#
# ROUND 9 asked the same question one level up — which REAL hosts can a
# simulation speak FROM — and CI answered it: on 3.13 the flavour simulation
# presents nothing, because the half it is built out of has nothing to stand in
# for there. Both scopes are declared per simulation now, and both are gates.


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


# 3.10's parsing consumer, reduced to the one call that matters, so the dialect
# probe above has something to say NO against on a 3.12 box. Round 6's rule
# applied to round 10's new instrument: a probe that cannot report the bad news
# turns every gate keyed on it vacuously open.
_A_HOST_WHOSE_PATHLIB_SPEAKS_THE_OBJECT_DIALECT = """
    import pathlib

    class _OldDialectPurePosixPath:
        _flavour = getattr(pathlib.PurePosixPath, "_flavour", None)

        def __init__(self, *parts):
            # 3.10 pathlib.py:587, in one line: _parse_args asks the FLAVOUR.
            type(self)._flavour.parse_parts(list(parts))

    pathlib.PurePosixPath = _OldDialectPurePosixPath
    print("OLD_DIALECT_CONSUMER_INSTALLED")
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


def _rows_missing_a_dialect_declaration(source: str, allowed: dict) -> list:
    """Which test rows compose the old emulation without declaring their hosts.

    A judgement over source text, so it can be fed a file this one is not —
    @commons' rule applied to a structural check. The check that only ever runs
    against its own file cannot be shown to fire at all, and a scan that never
    reports is indistinguishable from a scan that cannot.
    """
    offenders = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test"):
            continue
        names = {inner.id for inner in ast.walk(node) if isinstance(inner, ast.Name)}
        if "_EMULATION_THAT_ASSUMED_ONE_INTERPRETER" not in names:
            continue
        if node.name in allowed:
            continue
        if "_A_MODULE_SHAPED_FLAVOUR_NEEDS_A_TOLERANT_HOST" not in names:
            offenders.append(f"{node.name} (line {node.lineno})")
    return offenders


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

# The requirement a WORLD carries, not a simulation: any row that installs a
# module-shaped flavour needs a host whose pathlib is content with one. Written
# as a fact-keyed dict so it goes through the same judgement as every other
# speakable-hosts declaration in this file.
_A_MODULE_SHAPED_FLAVOUR_NEEDS_A_TOLERANT_HOST = {"parsing": ("module-tolerant",)}


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


# name -> (prelude, the shapes it is meaningful for, the real hosts it can speak from)
_HOST_SIMULATIONS = {
    # 3.10 and 3.11 present a flavour that is already an OBJECT. The shape's
    # half must recognise that and install nothing — and it must reach that
    # decision BEFORE touching _parse_path, which those versions spell
    # _parse_args and which is what the child actually died on.
    "flavour-is-already-an-object": (
        _HALF_FLAVOUR_OBJECT,
        sorted(_HOST_SHAPES),
        # It IS the half: on a host with no flavour at all, or one that builds
        # WindowsPath, the half honestly reports UNAVAILABLE and the simulation
        # presents nothing. CI's 3.13 red was exactly that, read as a defect.
        {"flavour": ("object", "module"), "concrete": ("posix",)},
    ),
    # 3.10 also presents the accessor natively.
    # The accessor half installs onto pathlib.Path itself, which every concrete
    # class inherits from on every version — no host precondition to declare.
    "accessor-route-is-already-native": (_HALF_ACCESSOR_ROUTE, sorted(_HOST_SHAPES), {}),
    # 3.13 has no _flavour at all. Shadowing the class is crude, but the
    # condition the half reads is exactly the real one, and the child's own
    # parsing is left alone so the run gets far enough to report.
    "purposixpath-has-no-flavour": (
        """
        import pathlib

        class _FlavourlessPurePosixPath:
            pass

        pathlib.PurePosixPath = _FlavourlessPurePosixPath
        """,
        [name for name in sorted(_HOST_SHAPES) if _HALF_FLAVOUR_OBJECT in _HOST_SHAPES[name]],
        # On an nt host the half refuses for the WindowsPath reason first, so
        # the UNAVAILABLE that comes back is not the one being simulated.
        {"concrete": ("posix",)},
    ),
    # The backstop lane: a host whose flavour is a module AND which does not
    # spell parsing the 3.12 way. No released interpreter is both, which is
    # why it is simulated rather than waited for.
    "purepath-has-no-parse-path": (
        """
        import pathlib

        class _PurePathWithoutParsePath:
            pass

        pathlib.PurePath = _PurePathWithoutParsePath
        """,
        [name for name in sorted(_HOST_SHAPES) if _HALF_FLAVOUR_OBJECT in _HOST_SHAPES[name]],
        # The guard this simulation aims at is the LAST branch of the half. A
        # host whose flavour is natively an object answers NATIVE two branches
        # earlier and never reaches it — so on 3.10 and 3.11 this row was
        # measuring nothing while looking green.
        {"flavour": ("module",), "concrete": ("posix",)},
    ),
}

_SIMULATION_PAIRS = sorted(
    (simulation, shape) for simulation, (_, shapes, _requires) in _HOST_SIMULATIONS.items() for shape in shapes
)

# The simulation may itself be built out of halves, and their verdicts are not
# the ones under test — the marker separates the two.
_SIMULATION_DONE = 'print("SIMULATION_INSTALLED")'

_LEGAL_HALF_VERDICTS = ("NATIVE", "INSTALLED", "UNAVAILABLE")


class TestTheHarnessSurvivesAHostThatIsNotTheOneItWasWrittenOn:
    """Round 8's actual subject: the stand-ins, not the thing they stand in for.

    68ab5132 failed 37 tests on the 3.10 and 3.11 legs, every one of them
    saying "the child never reported whether its route armed". Not one was
    about arming: the shape prelude reached pathlib.PurePath._parse_path, which
    is 3.12+, and the child died before printing anything. A harness crash
    arrived wearing the arming probe's message, which is the worst way to fail
    — the instrument that never ran got the blame.
    """

    def _speak_or_skip(self, simulation: str) -> None:
        """One gate, in front of every test in this class.

        A simulation that cannot speak from this host SKIPS with its own reason
        — the same rule the halves already follow, and the one round 9's 3.13
        leg proved was not yet wired at this level.
        """
        why = _simulation_unavailable(_HOST_SIMULATIONS[simulation][2], _HOST_FACTS)
        if why:
            pytest.skip(f"{simulation}: {why}")

    def _simulated(self, simulation: str, *chunks: str) -> str:
        """The ONE place a simulated host is installed, gated and re-measured.

        Every test in this class composes through here. Written as a helper
        rather than repeated because the re-fingerprint below is the kind of
        line a second call site quietly does without — and then the test that
        would have caught its absence is the one carrying its own copy.
        """
        self._speak_or_skip(simulation)
        return _child_script(
            _HOST_SIMULATIONS[simulation][0],
            _SIMULATION_DONE,
            # Re-measured: from here on the halves decide against the host the
            # simulation is presenting, not the one the process started on.
            _REPORT_HOST,
            *chunks,
        )

    def _child(self, simulation: str, shape: str):
        return _run(
            self._simulated(
                simulation,
                _shape_prelude(shape),
                _BUILD_PROBE_PATH,
                _EMULATE_310,
                _ARM_THE_ROUTE,
                _DENY_REALPATH,
                _PATHLIB_ROUTE_PROBE,
            ),
            cwd=Path(__file__).parent,
        )

    @staticmethod
    def _shape_halves(result) -> list:
        """Only the halves the SHAPE reported — not the simulation's own."""
        lines = result.stdout.splitlines()
        if "SIMULATION_INSTALLED" in lines:
            lines = lines[lines.index("SIMULATION_INSTALLED") + 1 :]
        return [line for line in lines if line.startswith("HALF:")]

    @pytest.mark.parametrize(("simulation", "shape"), _SIMULATION_PAIRS)
    def test_every_half_reports_a_verdict_instead_of_crashing(self, simulation, shape):
        """The whole round-8 species, in one assertion per pair.

        Whatever the host looks like, each half either takes, stands down, or
        says it cannot be built — and the child says which. What it must never
        do is die on plumbing it assumed.
        """
        result = self._child(simulation, shape)

        halves = self._shape_halves(result)
        assert len(halves) == len(_HOST_SHAPES[shape]), (
            f"{len(_HOST_SHAPES[shape])} halves were composed for {shape!r} under "
            f"{simulation!r} but {len(halves)} reported — one of them died:"
            f"\n{result.stdout}\n{result.stderr}"
        )
        for line in halves:
            assert line.split(":")[2] in _LEGAL_HALF_VERDICTS, f"illegal half verdict: {line!r}"

        if _unavailable_half(result):
            return

        assert "ROUTE_ARMED" in result.stdout.split(), (
            f"every half took under {simulation!r}/{shape!r} and the route still "
            f"never armed:\n{result.stdout}\n{result.stderr}"
        )

    def test_a_shape_stands_down_where_the_host_already_has_its_property(self):
        """The 3.10-host row: nothing to install, and the child says so."""
        result = self._child("accessor-route-is-already-native", "3.10-native-accessor-and-flavour-object")

        assert "HALF:accessor-route:NATIVE" in result.stdout, result.stdout
        assert "ACCESSOR_NATIVE" in result.stdout.split(), (
            "the emulation built a stand-in over a live accessor route — on a "
            f"real 3.10 that grades my copy instead of the interpreter:\n{result.stdout}"
        )

    def test_the_flavour_half_decides_before_it_reaches_3_12_only_plumbing(self):
        """CI's exact crash, inverted into a pin.

        On 3.10 and 3.11 the flavour is already an object, so the half must
        answer NATIVE without ever asking for _parse_path. Reorder those two
        checks and this goes red on the simulation below, which is the only
        place a 3.12 box can see it.
        """
        result = self._child("flavour-is-already-an-object", "3.11-flavour-object-and-direct-resolve")

        # ROUND 10 SWEEP: read the SHAPE's half, not the whole of stdout. The
        # simulation is built out of this same half, and on a host that already
        # has an object flavour the simulation ALSO prints NATIVE — so the raw
        # substring form was satisfiable by the simulation's own line while the
        # row under test said anything at all. Round 8's separation existed one
        # test over and had not travelled here.
        #
        # PUBLISHED AS EQUIVALENT: restoring the raw form passes on every host
        # reachable from here, because nothing between the two lines can move
        # the flavour — they agree by construction today. Kept anyway, because
        # an assertion satisfiable by a line other than the one under test reads
        # as a measurement of the shape when it is not necessarily one.
        assert "HALF:flavour-object:NATIVE" in self._shape_halves(result), (
            f"the SHAPE's flavour half did not stand down:\n{result.stdout}\n{result.stderr}"
        )
        assert "Traceback" not in result.stderr, result.stderr

    def test_an_unavailable_half_skips_rather_than_failing(self):
        """The gate itself, which no shape on this host can reach.

        Every half takes on 3.12, so the UNAVAILABLE lane is only reachable
        through a simulation — and the DECISION it feeds (skip, not fail) is
        reachable only by calling the gate. A skip that can silently become a
        failure is how round 8's 3.10 leg reported a harness crash as an arming
        defect.
        """

        class _Unavailable:
            stdout = "HALF:flavour-object:UNAVAILABLE:this host has no _flavour at all\n"
            stderr = ""

        class _Fine:
            stdout = "HALF:flavour-object:NATIVE\nROUTE_WAS_DARK\nACCESSOR_EMULATED\nROUTE_ARMED\n"
            stderr = ""

        instrument = TestTheRealpathDenialArmsOnEveryInterpreter()

        with pytest.raises(Skipped) as skipped:
            instrument._armed(_Unavailable(), "some-shape")
        assert "UNAVAILABLE" in str(skipped.value), skipped.value

        assert "ROUTE_ARMED" in instrument._armed(_Fine(), "some-shape"), (
            "the gate skipped a child that reported perfectly well"
        )

    @pytest.mark.parametrize(
        "shape",
        ["3.10-native-accessor-and-flavour-object", "3.11-flavour-object-and-direct-resolve"],
    )
    def test_the_old_emulations_symptom_follows_the_host_and_not_the_shape_name(self, shape):
        """CI's 3.13 red, reproduced here — the round-9 species end to end.

        The negative control asked the flavour shapes to die of parse_parts.
        That is what they do on a box WITH a flavour. Take the flavour away and
        the same two shapes convict the same emulation by a different mechanism
        entirely: its accessor is no longer on the resolve route, so the arming
        probe reports ROUTE_DARK and nothing ever reaches a parse. A table keyed
        on the shape's NAME called that "reproducing some other half of that
        interpreter" and went red on a leg where everything was working.

        ROUND 10 — WHICH HOSTS THIS ROW CAN SPEAK FROM. The world below contains
        the old emulation, and the old emulation installs a MODULE-SHAPED
        flavour. On 3.10 and 3.11 pathlib's own _parse_args asks that flavour
        for parse_parts, an API no path module ever had, and the child dies at
        the first Path(...) before any of this can be measured — which is
        exactly the parse_parts symptom this row exists to distinguish itself
        from, arriving before the row can run. The premise cannot hold there, so
        the row says so and skips, with the answer the host itself gave.
        """
        why = _simulation_unavailable(_A_MODULE_SHAPED_FLAVOUR_NEEDS_A_TOLERANT_HOST, _HOST_FACTS)
        if why:
            pytest.skip(f"the old emulation installs a module-shaped flavour and {why}")

        result = _run(
            self._simulated(
                "purposixpath-has-no-flavour",
                _shape_prelude(shape),
                _BUILD_PROBE_PATH,
                _EMULATION_THAT_ASSUMED_ONE_INTERPRETER,
                _ARM_THE_ROUTE,
                _BARE_REBINDING_ONLY,
                _PATHLIB_ROUTE_PROBE,
            ),
            cwd=Path(__file__).parent,
        )

        assert _flavour_in_force(result) == "absent", (
            f"the simulated host did not present as flavourless:\n{result.stdout}\n{result.stderr}"
        )
        assert _expected_old_emulation_symptom("absent", shape) == "ROUTE_DARK"
        assert "ROUTE_DARK" in result.stdout.split(), (
            f"on a flavourless host the old emulation's accessor is off the resolve "
            f"route and the probe must say so:\n{result.stdout}\n{result.stderr}"
        )
        assert "parse_parts" not in result.stderr, (
            "parse_parts is the symptom of a host that HAS a flavour — this one "
            f"does not, so the old table was pinning a mechanism that cannot fire:\n{result.stderr}"
        )

    def test_the_foreign_class_survives_a_flavour_that_is_not_a_path_module(self):
        """CI's 3.11 red on the nt shape, reproduced on 3.12.

        The foreign class resolves THROUGH the flavour it copied, because that
        is what WindowsPath does on 3.12 and copying is what makes it foreign.
        On 3.10 and 3.11 the flavour is a _PosixFlavour object that knows about
        parsing and nothing else, and the line died reaching for realpath on it.
        The cure asks instead of assuming — and this is the world where asking
        is the difference, since a host flavour with no realpath is a thing this
        interpreter never produces on its own.
        """
        # No _EMULATE_310 in this chain, and that is the whole test: it replaces
        # pathlib.Path.resolve, which on this shape IS the foreign class's own
        # resolve. Composed with it, the line under test never runs and the
        # mutation that restores the assumption survives — measured, after the
        # first cut of this test scored exactly that.
        result = _run(
            _child_script(
                _A_FLAVOUR_OBJECT_THAT_IS_NOT_A_PATH_MODULE,
                _BUILD_PROBE_PATH,
                _shape_prelude("nt-concrete-class-is-not-posix"),
                _DENY_REALPATH,
                _PATHLIB_ROUTE_PROBE,
            ),
            cwd=Path(__file__).parent,
        )

        assert "FLAVOUR_WITHOUT_REALPATH_INSTALLED" in result.stdout.split(), (
            f"the world never took, so this measured nothing:\n{result.stdout}\n{result.stderr}"
        )
        assert "has no attribute 'realpath'" not in result.stderr, (
            "the foreign class is reading its copied flavour as a path module "
            f"again — this is CI's 3.11 traceback, verbatim:\n{result.stderr}"
        )
        assert "HALF:foreign-concrete-class:INSTALLED" in result.stdout, result.stdout
        assert "PATHLIB_ARMED" in result.stdout.split(), (
            f"the shape stopped arming under a realpath-less flavour:\n{result.stdout}\n{result.stderr}"
        )

    def test_the_fingerprint_reads_the_host_instead_of_asserting_one(self):
        """The fingerprint is load-bearing for four gates now, so pin its source.

        The behavioural row — the child agrees with this process about os.name —
        is only falsifiable on a host where the two could differ, which from
        Linux means never. So the claim that matters is structural and is made
        here: the concrete kind is DERIVED from os.name, not written down. That
        is the difference between a stand-in and a decoration, and it is exactly
        the mutation (a hard-coded "posix") that no behavioural pin on this box
        can catch.
        """
        result = _run(_child_script(), cwd=Path(__file__).parent)

        assert _host_line(result)[1] == ("nt" if os.name == "nt" else "posix"), result.stdout
        assert "os.name" in _REPORT_HOST, (
            "the fingerprint stopped reading the host — every gate keyed on concrete kind is now measuring a literal"
        )
        assert "_CONCRETE_KIND = " in _REPORT_HOST and '"nt" if' in _REPORT_HOST, _REPORT_HOST

    @staticmethod
    def _flavour_half_verdict(*chunks: str) -> str:
        """The half's own last word, from a child composed exactly as given."""
        result = _run(_child_script(*chunks, _HALF_FLAVOUR_OBJECT), cwd=Path(__file__).parent)
        lines = [line for line in result.stdout.splitlines() if line.startswith("HALF:")]
        assert lines, f"the half reported nothing at all:\n{result.stdout}\n{result.stderr}"
        return lines[-1]

    def test_the_flavour_half_refuses_a_host_that_builds_windows_paths(self):
        """CI's windows red, reproduced by faking the FINGERPRINT — not a world.

        @trigger's rule from round 8, applied: what convicted the runner was the
        platform the process runs on, and a probe reads that through one name.
        This substitutes that name and nothing else, deliberately — building a
        whole WindowsPath world here would measure my scaffolding, while the
        thing under test is which branch the half takes when the host says nt.

        Speakable from every host, and that is not luck: the nt branch is the
        half's FIRST question, so it is reached before anything version-shaped.
        """
        refusal = self._flavour_half_verdict('_CONCRETE_KIND = "nt"')

        assert refusal.startswith("HALF:flavour-object:UNAVAILABLE:"), refusal
        assert "WindowsPath" in refusal, f"the refusal does not name what it is refusing for: {refusal!r}"

    # The second row is round 10's red, reproduced on a 3.12 box: a host whose
    # flavour is ALREADY an object answers NATIVE, which is what 3.10 and 3.11
    # said on CI while this test demanded the literal INSTALLED.
    _CONTROL_HOSTS = {
        "as-this-host-is": (),
        "with-an-object-flavour-already-installed": (_HALF_FLAVOUR_OBJECT,),
    }

    @pytest.mark.parametrize("control_host", sorted(_CONTROL_HOSTS))
    def test_forcing_the_posix_branch_leaves_the_row_where_the_host_put_it(self, control_host):
        """The control for the refusal above, and round 10's first red.

        This asserted the literal HALF:flavour-object:INSTALLED — the 3.12
        answer, spelled. Three legs disagreed HONESTLY: 3.10 and 3.11 have an
        object flavour natively and say NATIVE, 3.13 has none and says
        UNAVAILABLE. The verdict machinery was right on every one of them and
        the assertion was still 3.12-shaped, which is the round-9 species moved
        up one level, into the assertion OVER the verdict.

        The control's real question needs no literal at all: does forcing the
        posix branch leave the row where the untouched host put it, while
        forcing nt moves it? Both sides measured, nothing spelled — and run
        twice, once against a host presenting the answer CI's 3.10 and 3.11
        legs gave, so the cure is falsifiable here instead of on the board.
        """
        if _HOST_FACTS["concrete"] != "posix":
            pytest.skip(
                "this row forces the POSIX branch, which installs the very "
                "stand-in the nt branch exists to refuse; from an nt host that "
                f"is not a control, it is the defect (host: {_HOST_FACTS['concrete']})"
            )

        prelude = self._CONTROL_HOSTS[control_host]
        control = self._flavour_half_verdict(*prelude)
        forced_posix = self._flavour_half_verdict(*prelude, '_CONCRETE_KIND = "posix"')
        forced_nt = self._flavour_half_verdict(*prelude, '_CONCRETE_KIND = "nt"')

        assert forced_posix == control, (
            "forcing the branch the host is already on MOVED the verdict — then "
            f"the fingerprint substitution is doing more than it claims: {forced_posix!r} vs {control!r}"
        )
        assert forced_nt != control, (
            "the nt refusal is what this host says anyway, so the row above is "
            f"not measuring the platform branch at all: {forced_nt!r} vs {control!r}"
        )

    def test_the_parsing_dialect_probe_can_report_the_answer_that_shuts_a_row(self):
        """The negative control for round 10's new instrument.

        Every skip added this round is keyed on one measured word. If the probe
        could only ever say "module-tolerant", those rows would run everywhere
        and the 3.10/3.11 crash would come back wearing a different message. So
        this box grows 3.10's parsing consumer for one child and the probe has
        to notice — and to NAME what was asked, because "this host is different"
        and "this host wants parse_parts" are not the same report.
        """
        result = _run(
            _child_script(_A_HOST_WHOSE_PATHLIB_SPEAKS_THE_OBJECT_DIALECT, _REPORT_PARSING_DIALECT),
            cwd=Path(__file__).parent,
        )

        assert "OLD_DIALECT_CONSUMER_INSTALLED" in result.stdout.split(), (
            f"the old-dialect consumer never took:\n{result.stdout}\n{result.stderr}"
        )
        answers = [line for line in result.stdout.splitlines() if line.startswith("PARSING ")]
        assert answers == ["PARSING demands:parse_parts"], (
            "the dialect probe cannot tell a host that speaks the object dialect "
            f"from one that does not — every round-10 skip is vacuous:\n{result.stdout}\n{result.stderr}"
        )

        assert _simulation_unavailable(
            _A_MODULE_SHAPED_FLAVOUR_NEEDS_A_TOLERANT_HOST, {"parsing": "demands:parse_parts"}
        ), "and the judgement over that answer must close the row"

    def test_a_simulation_this_host_cannot_carry_skips_rather_than_failing(self, monkeypatch):
        """The gate's DECISION, reachable from a host that is none of those.

        CI's 3.13 leg failed here rather than skipping, and a failure that
        should have been a skip is how round 8 spent a round blaming an arming
        probe for a crash in the prelude ahead of it.
        """
        # Patched on the module OBJECT, not by dotted name: this file is
        # collected under two different rootdirs and its import name differs
        # between them. A string target would work in one and fail in the other.
        monkeypatch.setattr(
            sys.modules[__name__],
            "_HOST_FACTS",
            {"flavour": "absent", "concrete": "posix", "accessor": "no-accessor"},
            raising=True,
        )

        with pytest.raises(Skipped) as skipped:
            self._speak_or_skip("flavour-is-already-an-object")
        assert "flavour" in str(skipped.value), skipped.value

        self._speak_or_skip("accessor-route-is-already-native")

    @pytest.mark.parametrize("simulation", ["purposixpath-has-no-flavour", "purepath-has-no-parse-path"])
    def test_a_host_that_cannot_carry_the_stand_in_says_so_by_name(self, simulation):
        """UNAVAILABLE is a skip with a reason, not a red on someone else's box."""
        result = self._child(simulation, "3.10-native-accessor-and-flavour-object")

        missing = _unavailable_half(result)
        assert missing.startswith("HALF:flavour-object:UNAVAILABLE:"), (
            f"the half neither installed nor explained itself under {simulation!r}:\n{result.stdout}\n{result.stderr}"
        )
        assert missing.split(":", 3)[3].strip(), f"UNAVAILABLE with no reason: {missing!r}"


class TestTheRoundNineJudgementsAnswerForHostsThisBoxIsNot:
    """The judgements, separated from the worlds that feed them — @commons' rule.

    Every row below is a host this machine cannot be: a 3.13 with no _flavour, a
    3.10 whose flavour is natively an object, a Windows box, and a fourth thing
    no interpreter has ever been. Round 9's reds all lived in the CROSS of host
    and shape, and a cross is only measurable here if the deciding is a plain
    function of measured values rather than something that happens inside a
    child on one leg of the matrix.
    """

    @pytest.mark.parametrize(
        ("flavour_in_force", "shape", "expected"),
        [
            # Hosts WITH an object flavour: parsing travels through the wrapper
            # and the child dies constructing a Path. 3.10 and 3.11 natively,
            # 3.12 once the flavour half has stood one in.
            ("object", "3.10-native-accessor-and-flavour-object", "parse_parts"),
            ("object", "3.11-flavour-object-and-direct-resolve", "parse_parts"),
            # THE CROSS TERM, measured on CI's 3.11 leg: the shape named after
            # 3.13 still dies of parse_parts, because the HOST supplies the
            # flavour the shape never mentions.
            ("object", "3.13-no-accessor-direct-resolve", "parse_parts"),
            # ...except against the foreign class, which carries its own copy
            # and is the one shape the emulation's write cannot reach.
            ("object", "nt-concrete-class-is-not-posix", "ROUTE_DARK"),
            # THE OTHER CROSS TERM, measured on CI's 3.13 leg: no flavour to
            # replace, so the emulation loses by being off the resolve route.
            ("absent", "3.10-native-accessor-and-flavour-object", "ROUTE_DARK"),
            ("absent", "3.11-flavour-object-and-direct-resolve", "ROUTE_DARK"),
            ("absent", "nt-concrete-class-is-not-posix", "ROUTE_DARK"),
            # A module flavour is 3.12 and the Windows runner both — the write
            # lands somewhere real and changes nothing that resolve reads.
            ("module", "3.10-native-accessor-and-flavour-object", "ROUTE_DARK"),
            ("module", "3.13-no-accessor-direct-resolve", "ROUTE_DARK"),
            # No interpreter reports this. It is here so that an unrecognised
            # fingerprint fails to the mechanism that is always true rather than
            # to the one that happens to be listed first.
            ("chimera", "3.10-native-accessor-and-flavour-object", "ROUTE_DARK"),
        ],
    )
    def test_the_symptom_is_a_function_of_the_host_and_the_shape(self, flavour_in_force, shape, expected):
        assert _expected_old_emulation_symptom(flavour_in_force, shape) == expected

    _A_313 = {"flavour": "absent", "concrete": "posix", "accessor": "no-accessor"}
    _A_312 = {"flavour": "module", "concrete": "posix", "accessor": "no-accessor"}
    _A_310 = {"flavour": "object", "concrete": "posix", "accessor": "accessor"}
    _WINDOWS = {"flavour": "module", "concrete": "nt", "accessor": "no-accessor"}
    _UNREADABLE = {"flavour": "unknown", "concrete": "unknown", "accessor": "unknown"}

    @pytest.mark.parametrize(
        ("simulation", "host", "speaks"),
        [
            # The flavour simulation IS the flavour half: it needs a host with a
            # flavour to stand in for, and a posix concrete class to install it
            # on. CI's 3.13 red, and its windows red, in two rows.
            ("flavour-is-already-an-object", _A_312, True),
            ("flavour-is-already-an-object", _A_310, True),
            ("flavour-is-already-an-object", _A_313, False),
            ("flavour-is-already-an-object", _WINDOWS, False),
            # The parse_path backstop aims at the LAST branch of that half. A
            # host whose flavour is already an object answers two branches
            # earlier, so on 3.10 and 3.11 this row measured nothing while
            # looking green — the species one level below a false green.
            ("purepath-has-no-parse-path", _A_312, True),
            ("purepath-has-no-parse-path", _A_310, False),
            ("purepath-has-no-parse-path", _A_313, False),
            # The accessor simulation declares no preconditions: pathlib.Path
            # exists and is inherited from on every version and both platforms.
            ("accessor-route-is-already-native", _A_313, True),
            ("accessor-route-is-already-native", _WINDOWS, True),
            ("accessor-route-is-already-native", _UNREADABLE, True),
            # A host that could not be measured is not a host any simulation
            # with a precondition may claim to speak from.
            ("flavour-is-already-an-object", _UNREADABLE, False),
            ("purposixpath-has-no-flavour", _UNREADABLE, False),
        ],
    )
    def test_a_simulation_declares_which_real_hosts_it_can_speak_from(self, simulation, host, speaks):
        why = _simulation_unavailable(_HOST_SIMULATIONS[simulation][2], host)

        assert (why == "") is speaks, f"{simulation} on {host}: {why!r}"
        if not speaks:
            assert "this host reports" in why, f"a refusal with no measurement in it: {why!r}"

    @pytest.mark.parametrize(
        ("parsing", "speaks"),
        [
            ("module-tolerant", True),
            # 3.10 and 3.11: pathlib's own _parse_args asks the flavour for
            # parse_parts, which no path module has ever had.
            ("demands:parse_parts", False),
            # A host that asks for something nobody has named yet is still a
            # host a module-shaped flavour cannot serve.
            ("demands:something", False),
            # And an unmeasurable one fails CLOSED: an instrument that cannot
            # tell what the host speaks must not assume the convenient answer.
            ("unknown:TypeError", False),
            ("unknown", False),
        ],
    )
    def test_a_module_shaped_flavour_declares_which_hosts_it_can_serve(self, parsing, speaks):
        """Round 10's judgement, with every host this box is not.

        The rule is not about versions: it is about whether the host's pathlib
        speaks to a flavour in a dialect a path MODULE knows. Delegation cannot
        cure a consumer that calls methods the delegate never had — which is why
        the cure is a declaration and a skip, not a shim.
        """
        why = _simulation_unavailable(_A_MODULE_SHAPED_FLAVOUR_NEEDS_A_TOLERANT_HOST, {"parsing": parsing})

        assert (why == "") is speaks, f"{parsing}: {why!r}"
        if not speaks:
            assert parsing in why, f"the refusal does not carry the host's own answer: {why!r}"

    # The one row that may meet a host whose pathlib speaks the object dialect,
    # and why — published rather than silently exempted. Any other test that
    # composes the old emulation must DECLARE its speakable hosts.
    _ROWS_THAT_MAY_MEET_AN_OBJECT_DIALECT_HOST = {
        "test_the_previous_emulation_dies_against_the_shape_it_assumed_away": (
            "its expectation IS the crash: the symptom judgement predicts "
            "parse_parts on exactly the hosts whose pathlib asks for it, and the "
            "expectation is derived from the flavour the CHILD measured"
        ),
    }

    def test_every_world_with_a_module_shaped_flavour_declares_or_derives(self):
        """The sweep, kept from rotting — @skills' lower-bound rule as a pin.

        Two tests were flagged by CI. A flagged list is a diff and therefore a
        LOWER BOUND, so the rule is stated structurally instead: any test that
        composes the old emulation DECLARES which hosts it can speak from, and
        the single exception is named below with its reason. A third such test
        written next month gets caught here rather than on a board.

        The first cut of this check accepted "mentions the symptom judgement"
        as equivalent to declaring — and a mutant that deleted the cross-term
        row's declaration SURVIVED it, because that row calls the judgement with
        a literal argument. Mentioning a measurement is not making one.
        """
        offenders = _rows_missing_a_dialect_declaration(
            Path(__file__).read_text(encoding="utf-8"), self._ROWS_THAT_MAY_MEET_AN_OBJECT_DIALECT_HOST
        )

        assert not offenders, (
            "these tests install a module-shaped flavour without saying which "
            "hosts can carry one and without deriving the symptom: " + ", ".join(offenders)
        )

    def test_the_dialect_sweep_reports_a_row_that_does_not_declare(self):
        """The negative control for the sweep — it has to be able to say YES.

        A structural check run only against a file that already passes is the
        vacuous-green species in a new costume. This feeds it a source it has
        never seen, containing one row that declares and one that does not.
        """
        source = textwrap.dedent(
            """
            def test_it_declares():
                _run(_child_script(_EMULATION_THAT_ASSUMED_ONE_INTERPRETER))
                _simulation_unavailable(_A_MODULE_SHAPED_FLAVOUR_NEEDS_A_TOLERANT_HOST, _HOST_FACTS)

            def test_it_does_not():
                _run(_child_script(_EMULATION_THAT_ASSUMED_ONE_INTERPRETER))

            def test_it_never_touches_the_old_emulation():
                _run(_child_script(_DENY_REALPATH))
            """
        )

        offenders = _rows_missing_a_dialect_declaration(source, {})

        assert [name.split(" (")[0] for name in offenders] == ["test_it_does_not"], offenders
        assert _rows_missing_a_dialect_declaration(source, {"test_it_does_not": "published reason"}) == [], (
            "the allow-list is not being consulted"
        )

    def test_the_published_exception_carries_its_reason(self):
        """An exemption with no reason is an exemption nobody will re-examine."""
        for name, reason in self._ROWS_THAT_MAY_MEET_AN_OBJECT_DIALECT_HOST.items():
            assert reason.strip(), f"{name} is exempt with no reason given"
            assert name in Path(__file__).read_text(encoding="utf-8"), (
                f"{name} is exempt and no longer exists — a stale exemption is a hole"
            )

    def test_the_platform_emulations_declare_an_asymmetry_and_not_an_oversight(self):
        """Why one platform stand-in has a precondition and the other does not.

        The posix row turns on whether the path READS as absolute, which the
        concrete class gets a vote on — so a host that builds WindowsPath cannot
        run it, and CI's windows leg proved that by answering ARMED where the
        row says INERT. The nt row turns on ntpath.realpath reading os.getcwd
        UNCONDITIONALLY, above any question of spelling, so no dialect mismatch
        can move it and it can be measured from anywhere.

        Pinned because "the nt emulation has no requirements" looks exactly like
        "nobody got round to writing them".
        """
        posix_requires = _PLATFORM_EMULATIONS["posix"][1]
        nt_requires = _PLATFORM_EMULATIONS["nt"][1]

        assert _simulation_unavailable(posix_requires, self._WINDOWS) != ""
        assert _simulation_unavailable(posix_requires, self._A_312) == ""
        assert _simulation_unavailable(posix_requires, self._A_313) == ""
        assert _simulation_unavailable(nt_requires, self._WINDOWS) == ""
        assert _simulation_unavailable(nt_requires, self._A_312) == ""

    class _Result:
        def __init__(self, stdout):
            self.stdout = stdout
            self.stderr = ""

    def test_the_flavour_in_force_is_read_from_the_child_not_assumed(self):
        """INSTALLED and NATIVE both mean object; otherwise the host answers."""
        installed = self._Result("HOST module posix no-accessor\nHALF:flavour-object:INSTALLED\n")
        native = self._Result("HOST object posix accessor\nHALF:flavour-object:NATIVE\n")
        refused = self._Result("HOST absent posix no-accessor\nHALF:flavour-object:UNAVAILABLE:no _flavour\n")
        windows = self._Result("HOST module nt no-accessor\nHALF:flavour-object:UNAVAILABLE:WindowsPath\n")

        assert _flavour_in_force(installed) == "object"
        assert _flavour_in_force(native) == "object"
        assert _flavour_in_force(refused) == "absent"
        assert _flavour_in_force(windows) == "module"

    def test_a_child_that_never_reported_its_dialect_is_unknown_not_tolerant(self):
        """Round 10's fact reads the same way its neighbours do: closed on silence."""
        assert _parsing_answer(self._Result("PARSING module-tolerant\n")) == "module-tolerant"
        assert _parsing_answer(self._Result("PARSING demands:parse_parts\n")) == "demands:parse_parts"
        assert _parsing_answer(self._Result("HOST module posix no-accessor\n")) == "unknown"
        assert _simulation_unavailable(
            _A_MODULE_SHAPED_FLAVOUR_NEEDS_A_TOLERANT_HOST, {"parsing": _parsing_answer(self._Result(""))}
        ), "silence must close the rows this fact gates, not open them"

    def test_a_child_that_never_reported_its_host_is_unknown_not_guessed(self):
        """The fingerprint is load-bearing now, so its absence must be loud."""
        assert _flavour_in_force(self._Result("HALF:direct-resolve:INSTALLED\n")) == "unknown"
        assert _host_line(self._Result("")) == []

    def test_the_last_fingerprint_wins_because_a_simulation_moves_the_host(self):
        """A simulated host re-reports; the halves ran against the SECOND line."""
        both = self._Result("HOST module posix no-accessor\nSIMULATION_INSTALLED\nHOST absent posix no-accessor\n")

        assert _host_line(both) == ["absent", "posix", "no-accessor"]
        assert _flavour_in_force(both) == "absent"

    def test_this_host_measured_itself_before_any_world_touched_it(self):
        """The parent's own fingerprint, and the gate that reads it."""
        assert set(_HOST_FACTS) == {"flavour", "concrete", "accessor", "parsing"}
        assert _HOST_FACTS["concrete"] in ("posix", "nt"), _HOST_FACTS
        assert _HOST_FACTS["flavour"] in ("object", "module", "absent"), _HOST_FACTS
        # Round 10's fact. Either the host is content with a module-shaped
        # flavour, or it NAMES what it asked for — "unknown" would mean the
        # probe could not even install one, which is a fifth state nobody has
        # seen and would take every world built on it dark without saying why.
        parsing = _HOST_FACTS["parsing"]
        assert parsing == "module-tolerant" or parsing.startswith("demands:"), parsing


def _drive_row_is_satisfied(os_name: str, anchor_drive: str) -> bool:
    """Does this host's ntpath.abspath answer the way its own row says it must?

    A plain function of two values, so every row is reachable from any machine
    — including the ones this box will never be. The world that supplies those
    values is one test below; the decision is here.
    """
    if os_name == "nt":
        return bool(anchor_drive)
    if os_name == "posix":
        return anchor_drive == ""
    return False


class TestTheProbeLiteralNamesAnAbsolutePathOnTheRunner:
    """@devpulse's trap (b), split into the half I can measure and the half I cannot.

    The trap: a POSIX-absolute literal like os.sep + "tmp" is DRIVE-RELATIVE on
    nt, and ntpath.realpath resolves it against the current drive — so a path
    that looks absolute reads the cwd, and round 4's headline (ntpath.realpath
    calls os.getcwd unconditionally) applies to it after all.

    MEASURED HERE: what makes a path drive-relative, which is pure ntpath and
    runs on any OS. NOT MEASURABLE HERE, and said rather than guessed:
    ntpath.abspath on posix has no drive to add, so this machine cannot produce
    the cured literal's Windows value. That row is answered by the runner — the
    child prints PROBE_NO_DRIVE — instead of being asserted from Linux.
    """

    def test_a_rooted_driveless_literal_carries_no_drive_on_nt(self):
        rooted = ntpath.join(ntpath.sep, "definitely", "not", "here")

        assert ntpath.splitdrive(rooted)[0] == "", (
            f"the mechanism this file guards against stopped being true: {rooted!r}"
        )
        assert ntpath.splitdrive(ntpath.join("D:" + ntpath.sep, "definitely"))[0] == "D:"

    def test_the_child_builds_its_literal_from_the_anchor_not_from_the_separator(self):
        """The cure, pinned where it is spelled — there is exactly one spelling."""
        assert "abspath(os.sep)" in _PROBE_LITERAL, _PROBE_LITERAL

    @pytest.mark.parametrize(
        ("os_name", "anchor_drive", "expected"),
        [
            ("posix", "", True),
            ("posix", "D:", False),
            ("nt", "D:", True),
            ("nt", "", False),
            # No machine produces this, which is exactly why it is here:
            # @commons' rule, that the judgement must be reachable for inputs
            # the host cannot manufacture.
            ("plan9", "", False),
        ],
    )
    def test_the_drive_judgement_answers_for_hosts_this_one_is_not(self, os_name, anchor_drive, expected):
        """The judgement, separated from the world that feeds it.

        Round 8 red: the live version of this pin asserted "ntpath.abspath
        produces no drive" with `here` hard-coded to a posix runner. On the
        Windows host it produced D:, the assertion fired, and its message said
        the row had "just become falsifiable" — true, and the pin's own
        conclusion arriving as a failure. Split this way, the nt row is
        reachable from Linux and the plan9 row is reachable from anywhere.
        """
        assert _drive_row_is_satisfied(os_name, anchor_drive) is expected

    def test_the_live_host_satisfies_its_own_drive_row(self):
        """And the world, fed to the judgement above."""
        anchor_drive = ntpath.splitdrive(ntpath.abspath(ntpath.sep))[0]

        assert _drive_row_is_satisfied(os.name, anchor_drive), (
            f"host {os.name!r} produced anchor drive {anchor_drive!r}, which its "
            "own row does not allow — on posix that means ntpath grew a drive "
            "and the PROBE_NO_DRIVE gate is exercisable locally after all; on nt "
            "it means the cured probe literal cannot carry one"
        )


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

# Windows' contribution to the posix-absolute row, reduced to the one property
# that decides it: the concrete class spells the path back in ITS dialect, so a
# posix-absolute literal reaches posixpath.realpath as a relative path.
#
# MEASURED THE HARD WAY, and the reason this patches a dunder instead of
# introducing a class: a stand-in built as `class X(pathlib.Path)` and installed
# as `pathlib.Path = X` is DOWNGRADED BY THE INTERPRETER. Path.__new__
# (3.12 pathlib.py:1166) asks `if cls is Path` — and `Path` there is a GLOBAL
# LOOKUP in the pathlib module, which the installation just rebound to X. So
# `cls is Path` is true for X, __new__ returns a plain PosixPath, __init__ never
# runs because the result is not an instance of X, and the first str() dies in
# _load_parts with no _raw_paths. The round-9 species one level further down:
# replacing a module attribute changes what the interpreter's OWN identity test
# means. Pinned below so it cannot come back as a tidier-looking rewrite.
_A_CONCRETE_CLASS_THAT_SPELLS_ANOTHER_DIALECT = """
    import pathlib

    _real_fspath = pathlib.PurePath.__fspath__

    def _fspath_in_another_dialect(self):
        return _real_fspath(self).replace("/", chr(92))

    pathlib.PurePath.__fspath__ = _fspath_in_another_dialect
    print("DIALECT_INSTALLED")
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

# route -> {absolute probe verdict, relative probe verdict} under a getcwd
# denial. EVERY row is measured through an explicit platform emulation, on
# whatever host runs the file.
_GETCWD_TABLE = {
    ("posix", "absolute"): "PATHLIB_INERT",
    ("posix", "relative"): "PATHLIB_ARMED",
    ("nt", "absolute"): "PATHLIB_ARMED",
    ("nt", "relative"): "PATHLIB_ARMED",
}


class TestTheGetcwdRouteNeedsNoAccessorPatch:
    """@skills' round-7 return finding, answered by measurement.

    Their words: cwd and resolve ride DIFFERENT captured attributes on <=3.10
    (Path.cwd() is `cls(cls._accessor.getcwd())` there — confirmed, 3.10
    pathlib.py:993, and 3.11 :907 already reads os.getcwd directly), so an
    emulation that exercises one call leaves the other patch dark.

    What I measured in my own tree rather than agreeing: the getcwd-denied
    world needs no accessor patch AT ALL for the route this file cares about,
    because Path.resolve reaches os.getcwd from INSIDE realpath, which looks the
    name up on the `os` module at CALL time on every interpreter. Nothing
    captures it. What the world genuinely cannot reach on <=3.10 is Path.cwd(),
    and the template guard never calls it — a limit, stated rather than left to
    be discovered.

    AND THE ROW @memory'S LITMUS CAUGHT BEFORE CI DID: run the probe under the
    OPPOSITE platform's emulation and require the verdict not to move. It
    moved. The absolute-path row is a POSIXPATH fact; on nt, realpath reads the
    cwd before it looks at the path at all, so the same denial arms there.

    ROUND 8 finished the same thought in the other direction: the posix rows
    were running BARE, so on an nt host they measured nt under a posix label.
    Both rows go through an explicit emulation now — emulate both platforms or
    neither, which is the rule that produced this class in the first place.
    """

    @staticmethod
    def _emulation_or_skip(route: str) -> str:
        """One gate for every row that installs a platform, and the only one."""
        emulation, requires = _PLATFORM_EMULATIONS[route]
        why = _simulation_unavailable(requires, _HOST_FACTS)
        if why:
            pytest.skip(f"the {route} emulation cannot speak from this host: {why}")
        return emulation

    def _verdict(self, route: str, probe: str) -> str:
        emulation = self._emulation_or_skip(route)

        result = _run(
            _child_script(
                emulation,
                _BUILD_PROBE_PATH,
                _EMULATE_310,
                _ARM_THE_ROUTE,
                _INJECT_DEAD_CWD,
                _PATHLIB_ROUTE_PROBE if probe == "absolute" else _PATHLIB_ROUTE_PROBE_RELATIVE,
            ),
            cwd=Path(__file__).parent,
        )
        lines = result.stdout.split()
        assert "PROBE_NOT_ABS" not in lines, (
            f"the probe literal is not absolute under the {route} emulation — an "
            f"absolute path is whatever that platform says it is:\n{result.stdout}"
        )
        assert "ROUTE_ARMED" in lines, f"the route never armed ({route}/{probe}):\n{result.stdout}\n{result.stderr}"

        built = result.stdout.split("PROBE_PATH ", 1)[1].splitlines()[0]
        if route == "nt":
            assert ntpath.splitdrive(built)[0], (
                "the windows emulation built a drive-less literal. On 3.12 that "
                "changes nothing (ntpath.isabs still accepted rooted paths); on "
                "3.13 abspath falls through to os.getcwd and the probe dies "
                f"building its own argument: {built!r}"
            )
        else:
            assert not ntpath.splitdrive(built)[0], f"a posix row produced a drive: {built!r}"

        armed = [line for line in lines if line.startswith("PATHLIB_")]
        assert armed, f"the probe reported nothing ({route}/{probe}):\n{result.stdout}\n{result.stderr}"
        return armed[0]

    @pytest.mark.parametrize(("route", "probe"), sorted(_GETCWD_TABLE))
    def test_the_getcwd_denial_answers_the_same_way_the_table_says(self, route, probe):
        expected = _GETCWD_TABLE[(route, probe)]

        assert self._verdict(route, probe) == expected, (
            f"the {route} route answered differently for a {probe} path than the "
            "table says. If this is the nt row, read ntpath.realpath again "
            "before editing the table — the getcwd read ABOVE the isabs check "
            "is what the row is derived from (ordering, not line number)."
        )

    def test_the_live_platform_agrees_with_its_own_row(self):
        """The emulations are stand-ins; this is the host answering for itself."""
        route = "nt" if os.name == "nt" else "posix"

        result = _run(
            _child_script(_BUILD_PROBE_PATH, _EMULATE_310, _ARM_THE_ROUTE, _INJECT_DEAD_CWD, _PATHLIB_ROUTE_PROBE),
            cwd=Path(__file__).parent,
        )
        lines = result.stdout.split()
        assert "ROUTE_ARMED" in lines, result.stdout
        live = [line for line in lines if line.startswith("PATHLIB_")][0]

        assert live == _GETCWD_TABLE[(route, "absolute")], (
            f"this host is {os.name!r} and answered {live} where its own table "
            f"row says {_GETCWD_TABLE[(route, 'absolute')]}"
        )

    def test_the_relative_probe_is_inert_with_no_world_at_all(self):
        """The control for the control: no denial, no arming."""
        result = _run(
            _child_script(_BUILD_PROBE_PATH, _EMULATE_310, _ARM_THE_ROUTE, _PATHLIB_ROUTE_PROBE_RELATIVE),
            cwd=Path(__file__).parent,
        )

        assert "PATHLIB_INERT" in result.stdout.split(), (
            "the relative probe raised with NO world installed — it is "
            f"convicting for its own shape, not for the denial:\n{result.stdout}\n{result.stderr}"
        )

    def test_a_posix_route_with_a_foreign_dialect_class_is_the_windows_red(self):
        """CI's windows red, reproduced from Linux — and the reason for the gate.

        Same posix emulation, same denial, same probe literal. The only change
        is a concrete class that spells the path back in another dialect, which
        is precisely what Windows contributes to this row and the one thing the
        emulation never replaced. INERT becomes ARMED, and the row's expectation
        was a posix fact all along.

        Kept as a test rather than a comment because it is also the negative
        control for the skip above: if the gate ever lets an nt host run this
        row again, this is the verdict it will get.
        """
        emulation = self._emulation_or_skip("posix")

        result = _run(
            _child_script(
                emulation,
                _BUILD_PROBE_PATH,
                _A_CONCRETE_CLASS_THAT_SPELLS_ANOTHER_DIALECT,
                _EMULATE_310,
                _ARM_THE_ROUTE,
                _INJECT_DEAD_CWD,
                _PATHLIB_ROUTE_PROBE,
            ),
            cwd=Path(__file__).parent,
        )

        assert "DIALECT_INSTALLED" in result.stdout.split(), (
            f"the chimera never got built, so this measured nothing:\n{result.stdout}\n{result.stderr}"
        )
        assert "PATHLIB_ARMED" in result.stdout.split(), (
            "a posix os.path with a foreign-dialect concrete class no longer "
            "reads the cwd for an absolute literal — if this is genuinely fixed "
            f"upstream, the windows skip above can go:\n{result.stdout}\n{result.stderr}"
        )
        assert self._verdict("posix", "absolute") == "PATHLIB_INERT", (
            "the control moved too — then the difference above is not the dialect"
        )

    def test_a_stand_in_that_subclasses_the_class_it_replaces_is_downgraded(self):
        """Why the dialect stand-in patches a dunder instead of adding a class.

        The obvious way to make Path spell paths differently is to subclass it
        and install the subclass. On 3.12 that quietly does not work: Path.__new__
        asks `if cls is Path`, `Path` is a global lookup in pathlib, and the
        installation just rebound it — so the check matches the subclass, __new__
        returns a plain PosixPath, and __init__ never runs on it. What comes back
        is a half-built object of the WRONG class that dies on first str().

        Reported as measured rather than asserted as universal: a version where
        the identity check is gone would keep the subclass, and that is a legal
        answer here. What must never happen is the third state — a subclass that
        survives as a half-built object nobody notices.
        """
        result = _run(
            _child_script(
                _BUILD_PROBE_PATH,
                """
                import pathlib

                class _Subclassed(pathlib.Path):
                    pass

                pathlib.Path = _Subclassed
                _made = pathlib.Path(_ARM_ABS)
                _kept = type(_made) is _Subclassed
                print("SUBCLASS_KEPT" if _kept else "SUBCLASS_DOWNGRADED", type(_made).__name__)
                print("INITIALISED" if hasattr(_made, "_raw_paths") else "UNINITIALISED")
                """,
            ),
            cwd=Path(__file__).parent,
        )

        lines = result.stdout.split()
        assert ("SUBCLASS_KEPT" in lines) != ("SUBCLASS_DOWNGRADED" in lines), (
            f"the probe reported neither verdict:\n{result.stdout}\n{result.stderr}"
        )
        if "SUBCLASS_DOWNGRADED" in lines:
            assert "UNINITIALISED" in lines, (
                "the interpreter swapped the class but ran __init__ anyway — then "
                "the trap this comment describes is not the one that happens here"
            )
        else:
            assert "INITIALISED" in lines, (
                "a subclass survived installation as a HALF-BUILT object: it will "
                f"die at the first str(), a long way from here:\n{result.stdout}"
            )

    def test_no_row_of_the_table_runs_bare(self):
        """@memory's rule, pinned where it can rot: emulate BOTH or neither.

        Round 8's windows red was a posix row with no prelude — which reads as
        "posix" only while the host is posix. This host cannot tell a bare row
        from an emulated one behaviourally (they are the same here), so the
        claim is pinned on the table itself, which is where the mistake was.
        """
        for route, (prelude, _requires) in _PLATFORM_EMULATIONS.items():
            assert prelude.strip(), (
                f"the {route!r} row installs nothing, so it measures whatever "
                "host runs it under a label that says otherwise"
            )
        assert set(_PLATFORM_EMULATIONS) == {row for row, _ in _GETCWD_TABLE}, (
            "a table row has no platform emulation, or an emulation has no rows"
        )

    @pytest.mark.parametrize("route", sorted(_PLATFORM_EMULATIONS))
    def test_an_emulation_stacked_on_its_own_platform_is_one_layer(self, route):
        """@seedgo's round-8 find, relayed by @devpulse, checked here.

        They stacked an nt emulation on an nt-shaped world and recursed to the
        stack limit: host == emulated is one layer, and an emulation whose
        replacement calls the name it replaced eats itself. On the Windows
        runner my nt emulation IS applied to a host where ntpath is already
        os.path, so that is not a hypothetical for this file — it is just
        invisible from Linux unless the emulation is applied twice.
        """
        emulation = self._emulation_or_skip(route)
        result = _run(
            _child_script(
                emulation,
                emulation,
                _BUILD_PROBE_PATH,
                _EMULATE_310,
                _ARM_THE_ROUTE,
                _PATHLIB_ROUTE_PROBE,
            ),
            cwd=Path(__file__).parent,
        )

        assert "RecursionError" not in result.stderr, (
            f"the {route} emulation calls the name it replaced — stacking it on "
            f"its own platform recurses:\n{result.stderr[-400:]}"
        )
        assert "ROUTE_ARMED" in result.stdout.split(), (
            f"the {route} emulation stopped working when applied twice:\n{result.stdout}\n{result.stderr}"
        )

    @pytest.mark.parametrize("route", sorted(_PLATFORM_EMULATIONS))
    def test_each_platform_emulation_is_inert_without_the_denial(self, route):
        """And the same for the platform stand-ins themselves.

        An emulation that raises on its own would make every row above
        vacuously ARMED — @canary's round-4 species, applied to a platform
        instead of a world.
        """
        result = _run(
            _child_script(
                self._emulation_or_skip(route),
                _BUILD_PROBE_PATH,
                _EMULATE_310,
                _ARM_THE_ROUTE,
                _PATHLIB_ROUTE_PROBE,
            ),
            cwd=Path(__file__).parent,
        )

        assert "PATHLIB_INERT" in result.stdout.split(), (
            f"the {route} emulation arms the probe with no denial installed — "
            f"every {route} row above is measuring the stand-in:\n{result.stdout}\n{result.stderr}"
        )


# =============================================================================
# The defect itself — portable form (runs on every OS)
# =============================================================================


@pytest.mark.parametrize("world", sorted(PORTABLE_WORLDS))
@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_newborn_import_survives_a_cwd_that_cannot_be_read(class_name, world, tmp_path):
    """Import the newborn's handlers where reading the cwd raises.

    `-c` gives the top frame the pseudo-filename `<string>`, and the defective
    guard resolved it before skipping it — so the import died on a call the
    fixed guard never makes. MEASURED red against the pre-fix form on Linux.
    """
    root = _plant_newborn(tmp_path / "tree", class_name)
    (tmp_path / "stand_here").mkdir()

    result = _in_dead_cwd(
        root,
        PORTABLE_WORLDS[world],
        """
        import aipass.newborn.apps.handlers
        print("IMPORTED")
        """,
        cwd=tmp_path / "stand_here",
    )

    lines = _require_live_world(result, world)
    assert result.returncode == 0, (
        f"a newborn of class '{class_name}' cannot be imported in the '{world}' world:\n{result.stderr}"
    )
    assert lines[-1] == "IMPORTED"


@pytest.mark.parametrize("world", sorted(PORTABLE_WORLDS))
@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_resolve_is_never_reached_for_a_pseudo_filename(class_name, world, tmp_path):
    """Ordering pin: pseudo-files are skipped before anything touches the disk.

    Behaviourally identical to the pin above for today's code, but it fails on
    the ORDERING rather than on the whole import — so a future rewrite that
    reintroduces an early resolve() is named precisely.
    """
    root = _plant_newborn(tmp_path / "tree", class_name)
    (tmp_path / "stand_here").mkdir()

    result = _in_dead_cwd(
        root,
        PORTABLE_WORLDS[world],
        """
        from aipass.newborn.apps.handlers import _find_real_caller

        caller, line = _find_real_caller()
        print("NO_CRASH")
        """,
        cwd=tmp_path / "stand_here",
    )

    lines = _require_live_world(result, world)
    assert result.returncode == 0, f"_find_real_caller still needs a cwd:\n{result.stderr}"
    assert lines[-1] == "NO_CRASH"


# =============================================================================
# The defect itself — real-world form (POSIX only, by ruling)
# =============================================================================


@pytest.mark.skipif(sys.platform == "win32", reason=WINDOWS_RECIPE_SKIP)
@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_newborn_import_survives_a_deleted_working_directory(class_name, tmp_path):
    """The same claim against a genuinely deleted cwd — no faking at all.

    This is the pin the injection stands in for. Keeping it means the stand-in
    is never the only evidence on the platforms where the real world is
    reachable.
    """
    root = _plant_newborn(tmp_path / "tree", class_name)
    (tmp_path / "stand_here").mkdir()

    result = _in_dead_cwd(
        root,
        _DELETE_CWD,
        """
        import aipass.newborn.apps.handlers
        print("IMPORTED")
        """,
        cwd=tmp_path / "stand_here",
    )

    lines = _require_live_world(result, "getcwd-denied")  # _DELETE_CWD is a cwd world
    assert result.returncode == 0, (
        f"a newborn of class '{class_name}' cannot be imported from a deleted cwd:\n{result.stderr}"
    )
    assert lines[-1] == "IMPORTED"


class TestBothConstructionsAgree:
    """@memory's licensing condition, made a test rather than a promise.

    The injection is a legitimate stand-in only for as long as it produces the
    IDENTICAL answer from the IDENTICAL call site as the real deleted-directory
    world. Both run on POSIX, so that is checkable here every time the suite
    runs — and the day it stops being true, this goes red instead of the
    stand-in quietly drifting away from the world it claims to model.
    """

    CALL_SITE = """
        from pathlib import Path

        try:
            Path("<string>").resolve()
        except OSError:
            print("RAISED")
        else:
            print("RESOLVED")
        """

    @pytest.mark.skipif(sys.platform == "win32", reason=WINDOWS_RECIPE_SKIP)
    def test_the_two_worlds_answer_the_call_site_identically(self, tmp_path):
        (tmp_path / "stand_here").mkdir()

        injected = _in_dead_cwd(tmp_path, _INJECT_DEAD_CWD, self.CALL_SITE, tmp_path / "stand_here")
        deleted = _in_dead_cwd(tmp_path, _DELETE_CWD, self.CALL_SITE, tmp_path / "stand_here")

        assert injected.returncode == deleted.returncode == 0
        assert injected.stdout.split() == deleted.stdout.split() == ["CONTROL_LIVE", "RAISED"], (
            "the injection no longer models the deleted-directory world:\n"
            f"  injected: {injected.stdout.split()}\n  deleted:  {deleted.stdout.split()}"
        )

    def test_the_control_probe_can_report_a_world_that_did_not_take(self):
        """The control's own negative control — it must be able to say NO.

        A control that always reports CONTROL_LIVE is worse than no control: it
        turns every portable pin into a vacuous green on exactly the platform
        where the injection may not reach the call site. Run the probe with no
        world applied at all; a healthy cwd must make it say so.
        """
        result = _run(_NO_WORLD_AT_ALL, cwd=Path(__file__).parent)

        assert result.returncode == 0, result.stderr
        assert result.stdout.split() == ["CONTROL_DEAD"], (
            "the control probe reports a broken world on a healthy machine — it "
            f"cannot distinguish anything: {result.stdout!r}"
        )

    def test_the_windows_skip_states_the_ruling_not_just_the_symptom(self):
        """The skip reason is the evidence a future reader gets — pin it.

        Readable from Linux, so both answers are observable without a Windows
        box: what is pinned is what the skipped tests SAY, not that they ran.
        """
        marks = [m for m in test_newborn_import_survives_a_deleted_working_directory.pytestmark if m.name == "skipif"]
        assert len(marks) == 1, "the deleted-cwd recipe lost its platform skip"

        reason = marks[0].kwargs["reason"]
        assert "WinError 32" in reason
        assert "RECIPE" in reason and "STATE" in reason, "the skip must say WHY Windows is excused, not just that it is"
        assert marks[0].args[0] is (sys.platform == "win32")


# =============================================================================
# The fence the fix must not have weakened
# =============================================================================


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_newborn_still_refuses_an_outside_caller(class_name, tmp_path):
    """A file outside the newborn's tree importing its handlers is still blocked."""
    root = _plant_newborn(tmp_path / "tree", class_name)

    outsider = tmp_path / "outsider"
    outsider.mkdir()
    caller = outsider / "trespass.py"
    caller.write_text(
        textwrap.dedent(
            f"""
            import sys

            sys.path.insert(0, {str(root)!r})

            try:
                import aipass.newborn.apps.handlers
            except ImportError as exc:
                print("BLOCKED" if "ACCESS DENIED" in str(exc) else "OTHER")
            else:
                print("ALLOWED")
            """
        ).strip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(caller)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "BLOCKED"


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_newborn_admits_its_own_code(class_name, tmp_path):
    """A file inside the newborn's own tree imports its handlers freely."""
    root = _plant_newborn(tmp_path / "tree", class_name)

    insider = root / "aipass" / "newborn" / "apps" / "inside.py"
    insider.write_text(
        textwrap.dedent(
            f"""
            import sys

            sys.path.insert(0, {str(root)!r})

            import aipass.newborn.apps.handlers
            print("ADMITTED")
            """
        ).strip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(insider)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )

    assert result.returncode == 0, f"the guard locked a newborn out of its own handlers:\n{result.stderr}"
    assert result.stdout.strip() == "ADMITTED"


# =============================================================================
# The wider species: import-time resolve() anywhere in the template
# =============================================================================


def _unguarded_module_level_resolves(source: str) -> list:
    """Line numbers of resolve() calls that run at import and are not guarded.

    Module level only, and outside any try — see the class docstring for why
    function-level resolves are deliberately not flagged.
    """
    tree = ast.parse(source)

    guarded = {
        node.lineno
        for block in ast.walk(tree)
        if isinstance(block, ast.Try)
        for node in ast.walk(block)
        if hasattr(node, "lineno")
    }

    # Walk what RUNS at import, which is not the same as what is WRITTEN at
    # module level — @memory's correction, 2026-08-31, after the last crash
    # standing in their tree was a resolve() in a find_repo_root DEFAULT
    # ARGUMENT: written inside a def, evaluated at import anyway. So a
    # function's body is pruned (that resolve is a deliberate raise, see the
    # class docstring) but its defaults and decorators are NOT.
    #
    # STATED LIMIT: a module-level call into a locally defined function also
    # runs at import and is not followed here. That needs a call graph, and
    # naming the gap beats a pin that reads like it covers more than it does.
    found = []
    pending = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            pending.extend(getattr(node, "decorator_list", []))
            args = getattr(node, "args", None)
            if args is not None:
                pending.extend(args.defaults)
                pending.extend(d for d in args.kw_defaults if d is not None)
            continue
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "resolve"
            and node.lineno not in guarded
        ):
            found.append(node.lineno)
        pending.extend(ast.iter_child_nodes(node))

    return sorted(found)


class TestImportTimeRootDerivationSurvivesADeadCwd:
    """A newborn must not inherit a cwd read that runs at import.

    @memory raised this as the wider species after the guard fix (2026-08-31)
    and left the template ruling to me: `Path(__file__).resolve()` is a cwd read
    on Windows anywhere it appears, because ntpath.realpath computes os.getcwd()
    unconditionally rather than only for relative paths.

    MY RULING, and the sweep that backs it: severity splits on WHEN it runs.

    * At MODULE level it is unrecoverable and it spreads — the template's
      json_handler derives its branch root that way, and nearly every module in
      a newborn imports json_handler, so one dead-cwd process loses the whole
      branch with a traceback from inside the stdlib. These are guarded, falling
      back to the unresolved absolute path (`__file__` has been absolute since
      3.9, so only symlink normalisation is lost, and only in the world where
      the alternative is a dead import).
    * Inside a FUNCTION it stays exactly as written. It fails where a caller can
      see it, and a root that is wrong-but-plausible is worse than a raise —
      "fail to errors, never fall back silently" is the branch's own rule. The
      pin below is scoped to module level for that reason, not by oversight.
    """

    def test_the_json_handler_root_derivation_survives_realpath_denial(self, tmp_path):
        """Run the template's own module-level derivation in the denied world."""
        source = (get_template_dir("specialist") / "apps" / "handlers" / "json" / "json_handler.py").read_text(
            encoding="utf-8"
        )
        derivation = source[source.index("_BRANCH_ROOT = ") : source.index("_JSON_DIR")]

        probe = tmp_path / "derive.py"
        probe.write_text(
            textwrap.dedent(
                """
                import errno, os, os.path
                from pathlib import Path

                def _no_realpath(*args, **kwargs):
                    raise FileNotFoundError(errno.ENOENT, "No such file or directory")

                os.path.realpath = _no_realpath

                """
            ).lstrip()
            + derivation
            + '\nprint("DERIVED", "ABSOLUTE" if _BRANCH_ROOT.is_absolute() else "RELATIVE")\n',
            encoding="utf-8",
        )

        result = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True, cwd=str(tmp_path))

        assert result.returncode == 0, f"the template's import-time root derivation needs a cwd:\n{result.stderr}"
        assert result.stdout.split()[0] == "DERIVED"
        assert result.stdout.split()[1] == "ABSOLUTE", (
            "the derivation produced a relative root — __file__ has been absolute "
            "since 3.9 and dropping resolve() relies on exactly that"
        )

    def test_no_unguarded_module_level_resolve_anywhere_in_the_template(self):
        """The species, not the site — so a newborn cannot re-inherit the idiom.

        Scoped to module level: a resolve() inside a function is a deliberate
        raise, and flagging it here would push future authors toward silently
        wrong roots.
        """
        offenders = []
        for path in sorted(get_template_dir("specialist").rglob("*.py")):
            # Render first: the template carries {{BRANCH}} placeholders that
            # are not valid Python. Skipping unparseable files instead would
            # exempt exactly the files most likely to carry the idiom.
            offenders += [
                f"{path.name}:{line}"
                for line in _unguarded_module_level_resolves(_render(path.read_text(encoding="utf-8")))
            ]

        assert offenders == [], (
            "unguarded module-level resolve() in the template — this runs at "
            "import on every newborn, and ntpath.realpath reads the cwd even for "
            f"an absolute path: {offenders}"
        )

    @pytest.mark.parametrize(
        "label,source,expected",
        [
            (
                "module-level unguarded — the defect",
                "from pathlib import Path\nROOT = Path(__file__).resolve().parents[3]\n",
                [2],
            ),
            (
                "module-level guarded — the cure",
                "from pathlib import Path\ntry:\n    ROOT = Path(__file__).resolve().parents[3]\n"
                "except OSError:\n    ROOT = Path(__file__).parents[3]\n",
                [],
            ),
            (
                "inside a function — deliberately out of scope",
                "from pathlib import Path\ndef root():\n    return Path(__file__).resolve().parents[3]\n",
                [],
            ),
            (
                "default argument — written in a def, RUN at import",
                "from pathlib import Path\ndef root(base=Path(__file__).resolve()):\n    return base\n",
                [2],
            ),
            (
                "keyword-only default — same, one syntax over",
                "from pathlib import Path\ndef root(*, base=Path(__file__).resolve()):\n    return base\n",
                [2],
            ),
            (
                "decorator — also evaluated at import",
                "from pathlib import Path\n@register(Path(__file__).resolve())\ndef root():\n    pass\n",
                [2],
            ),
        ],
    )
    def test_the_detector_can_tell_the_three_cases_apart(self, label, source, expected):
        """The detector's own control — it must be able to say yes AND no.

        A structural pin that quietly stopped detecting would go green forever
        and read as coverage. Same lesson as the control probe above: a check
        that can only produce one answer has not been tested, it was assumed.
        """
        assert _unguarded_module_level_resolves(source) == expected, label


# =============================================================================
# Optional peer imports must survive a peer that is BROKEN, not just absent
# =============================================================================


class TestOptionalPeerImportsAreWideEnough:
    """A peer branch being broken is allowed; dying of it is not.

    Raised by @prax 2026-08-31 from their own watcher: they declared the
    @trigger import optional and caught only ImportError, while trigger's
    handler guard raises FileNotFoundError. An optional dependency's fallback
    has to be at least as wide as the failures its import can produce — and a
    peer's handlers package does real filesystem work at import time, so a dead
    or unreadable cwd surfaces as OSError, not ImportError.

    The width is deliberately OSError and not Exception: a peer that is
    unavailable or broken at the filesystem level is weather, but a peer with a
    genuine programming error should still take spawn down loudly rather than
    be swallowed into an empty dict.
    """

    @staticmethod
    def _deny(module_prefix, exc):
        """A finder that raises `exc` for the named module and its children."""

        class _Denier:
            @staticmethod
            def find_spec(name, path=None, target=None):
                if name == module_prefix or name.startswith(module_prefix + "."):
                    raise exc
                return None

        return _Denier

    @pytest.mark.parametrize(
        "exc",
        [
            FileNotFoundError(2, "No such file or directory"),
            PermissionError(13, "Permission denied"),
            ImportError("@memory is not installed"),
        ],
        ids=["dead-cwd", "unreadable", "absent"],
    )
    def test_meta_tabs_fall_back_when_memory_is_broken_or_absent(self, exc, monkeypatch):
        from aipass.spawn.apps.modules import core

        denier = self._deny("aipass.memory", exc)
        monkeypatch.setattr(sys, "meta_path", [denier] + sys.meta_path)
        for name in [m for m in sys.modules if m.startswith("aipass.memory")]:
            monkeypatch.delitem(sys.modules, name, raising=False)

        assert core._load_meta_tabs() == {}, (
            f"a peer raising {type(exc).__name__} took spawn's meta-tab lookup down instead of falling back"
        )

    def test_the_denier_actually_denies(self, monkeypatch):
        """Negative control: an inert finder would make the pins above vacuous."""
        denier = self._deny("aipass.memory", FileNotFoundError(2, "denied"))
        monkeypatch.setattr(sys, "meta_path", [denier] + sys.meta_path)
        for name in [m for m in sys.modules if m.startswith("aipass.memory")]:
            monkeypatch.delitem(sys.modules, name, raising=False)

        with pytest.raises(FileNotFoundError):
            importlib.import_module("aipass.memory.apps.handlers.tracking.tab_renderer")

    def test_a_real_programming_error_is_still_fatal(self, monkeypatch):
        """The width is OSError, not Exception — a broken peer must stay loud."""
        denier = self._deny("aipass.memory", ValueError("peer has a bug"))
        monkeypatch.setattr(sys, "meta_path", [denier] + sys.meta_path)
        for name in [m for m in sys.modules if m.startswith("aipass.memory")]:
            monkeypatch.delitem(sys.modules, name, raising=False)

        from aipass.spawn.apps.modules import core

        with pytest.raises(ValueError):
            core._load_meta_tabs()


# =============================================================================
# The deleted stack walk, pinned structurally
# =============================================================================


def _inspect_stack_calls(source: str) -> list:
    """Line numbers of every ``inspect.stack()`` CALL in ``source``.

    An AST matcher, never a string search. The guard's own docstring names
    ``inspect.stack()`` while explaining the defect, so a spelling ban would
    convict the explanation and force the cure to be undocumented — the pin
    would be arguing against its own comment.

    Handles the three ways the call can be spelled, because a ban that only
    knows one is an invitation to the other two:

    * ``inspect.stack()`` — attribute on the module name
    * ``import inspect as i`` then ``i.stack()`` — module bound to an alias
    * ``from inspect import stack`` then ``stack()`` — the function bound direct

    Deliberately NOT convicted: ``inspect.currentframe()`` (that is
    ``sys._getframe`` under another name and touches no filesystem), any
    ``.stack`` attribute on something that is not the inspect module, and a bare
    reference that is never called.
    """
    tree = ast.parse(source)

    module_aliases = {"inspect"}
    direct_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "inspect":
                    module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "inspect":
            for alias in node.names:
                if alias.name == "stack":
                    direct_names.add(alias.asname or alias.name)

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "stack"
            and isinstance(func.value, ast.Name)
            and func.value.id in module_aliases
        ):
            found.append(node.lineno)
        elif isinstance(func, ast.Name) and func.id in direct_names:
            found.append(node.lineno)

    return sorted(found)


# Every .py under these roots, excluding the retired template archive.
_BANNED_ROOTS = (Path(__file__).resolve().parents[1] / "apps", get_template_dir("specialist"))

# Measured 2026-08-31: 48 files across apps/ and templates/citizen/. The floor
# exists so a walk that silently stops finding files cannot read as "clean" —
# a blinded sweep and a cured tree produce the same empty list otherwise.
_MIN_FILES_SWEPT = 40


class TestTheStackWalkCannotComeBack:
    """The deleted second walk has no behavioural instrument — so pin the source.

    MEASURED FLEET-WIDE and relayed by @devpulse 2026-08-31: the
    ``caller_file is None`` branch in ``_guard_branch_access`` is unreachable
    from any import-shaped test, because ``apps/__init__.py`` always supplies a
    real-file frame. Nine branches reproduced it identically — restoring the
    walk leaves the whole suite green. This branch is the copy every newborn
    inherits, so an unpinned regression here would ship.

    A structural pin is the honest instrument for a defect whose only symptom
    is a call that must not exist.
    """

    def test_the_guard_has_no_stack_walk(self):
        source = (Path(__file__).resolve().parents[1] / "apps" / "handlers" / "__init__.py").read_text(encoding="utf-8")

        assert _inspect_stack_calls(source) == [], (
            "inspect.stack() is back in the handler guard. It reads the cwd on "
            "Windows before any of the guard's own code runs — walk frames with "
            "sys._getframe instead"
        )

    def test_no_stack_walk_anywhere_in_apps_or_the_template(self):
        """Tree-wide, because zero legitimate callers remain — CHECKED, not assumed.

        @devpulse's warning was earned elsewhere: @commons applied this ban
        without looking first and found a LIVE stack walk the dispatch had not
        named. So this was measured before widening — spawn's json_handler is a
        pure shim over aipass.aipass.shared.json_handler with no local walk, and
        that shared implementation is itself already on sys._getframe(2).
        """
        offenders = []
        swept = 0

        for root in _BANNED_ROOTS:
            for path in sorted(root.rglob("*.py")):
                if ".archive" in path.parts:
                    continue
                swept += 1
                offenders += [
                    f"{path.name}:{line}" for line in _inspect_stack_calls(_render(path.read_text(encoding="utf-8")))
                ]

        assert swept >= _MIN_FILES_SWEPT, (
            f"the sweep only reached {swept} files (expected at least "
            f"{_MIN_FILES_SWEPT}) — an empty result from a blinded walk is not "
            "evidence of a clean tree"
        )
        assert offenders == [], f"inspect.stack() at import-capable sites: {offenders}"


class TestTheStackMatcherIsTheRealOne:
    """Controls run through the SHIPPED matcher, never a copy of it.

    A control that exercises a second implementation proves that copy correct
    and says nothing about the pin above.
    """

    def test_a_planted_call_convicts_at_the_right_line(self):
        source = "import inspect\n\n\ndef f():\n    return inspect.stack()\n"

        assert _inspect_stack_calls(source) == [5]

    def test_the_guards_own_docstring_is_not_a_violation(self):
        """The cure explains itself by naming the defect — that must stay legal.

        Takes the guard's REAL docstring and puts it in a stub, rather than
        asserting the whole live file is clean. The first version did the
        latter, and the mutant run exposed it: restoring the walk made this
        "control" red too, which means it was a second copy of the ban wearing a
        control's name. A control has to fail for the reason it exists — here,
        only if prose starts convicting.
        """
        guard = Path(__file__).resolve().parents[1] / "apps" / "handlers" / "__init__.py"
        tree = ast.parse(guard.read_text(encoding="utf-8"))

        docstrings = [
            ast.get_docstring(node)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        prose = "\n".join(d for d in docstrings if d)

        assert "inspect.stack()" in prose, (
            "the guard no longer explains what it replaced — this control is measuring nothing"
        )
        assert _inspect_stack_calls(f'def stub():\n    """{prose}"""\n') == []

    @pytest.mark.parametrize(
        "label,source,expected",
        [
            ("numpy.stack", "import numpy\nx = numpy.stack([1])\n", []),
            ("traceback.stack", "import traceback\nx = traceback.stack()\n", []),
            ("self.stack", "class C:\n    def f(self):\n        return self.stack()\n", []),
            ("bare reference, never called", "import inspect\nf = inspect.stack\n", []),
            ("inspect.currentframe is legal", "import inspect\nx = inspect.currentframe()\n", []),
            ("module alias", "import inspect as i\nx = i.stack()\n", [2]),
            ("direct import", "from inspect import stack\nx = stack()\n", [2]),
            ("direct import aliased", "from inspect import stack as s\nx = s()\n", [2]),
            ("a different from-import", "from inspect import currentframe\nx = currentframe()\n", []),
        ],
    )
    def test_the_matcher_tells_the_cases_apart(self, label, source, expected):
        assert _inspect_stack_calls(source) == expected, label


class TestNewbornsAreBornPinned:
    """The template ships the AST pin, and it works in the position it lands in.

    TEMPLATE OWNER'S DECISION, stated rather than left implicit: YES, the pin
    ships in ``templates/citizen/tests/test_scaffold.py``. A newborn inherits
    the cured guard, but without a pin a future author regrows the walk and
    every suite stays green — which is exactly the fleet-wide condition
    @devpulse measured in nine branches. test_scaffold.py is the right home
    because it is self-contained: unlike the fixture smoke test beside it, the
    pin needs no conftest, so it survives a branch replacing the template
    scaffolding with its own suite.

    STATED LIMIT: ``spawn update`` never overwrites .py files, so this reaches
    FUTURE citizens only. The 18 existing branches need their own owners to add
    it — which is what @devpulse's relay is doing. Shipping it here is not a
    claim that the fleet is covered.

    These tests render the template into a throwaway newborn and run its own
    scaffold pin against it, green AND red, because a shipped test nobody has
    executed in its landing position is a guess.
    """

    @staticmethod
    def _mint(root: Path, guard_source: str) -> Path:
        branch = root / "newborn"
        (branch / "apps" / "handlers").mkdir(parents=True)
        (branch / "tests").mkdir()
        (branch / "apps" / "handlers" / "__init__.py").write_text(guard_source, encoding="utf-8")

        scaffold = get_template_dir("specialist") / "tests" / "test_scaffold.py"
        (branch / "tests" / "test_scaffold.py").write_text(
            _render(scaffold.read_text(encoding="utf-8")), encoding="utf-8"
        )
        return branch

    @staticmethod
    def _run_scaffold(branch: Path):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(branch / "tests" / "test_scaffold.py"),
                "-p",
                "no:randomly",
                "-q",
                "--no-header",
                "-k",
                "stack",
            ],
            capture_output=True,
            text=True,
            cwd=str(branch),
        )

    def test_a_newborn_with_the_cured_guard_passes_its_own_pin(self, tmp_path):
        cured = _render(_template_guard("specialist").read_text(encoding="utf-8"))
        branch = self._mint(tmp_path, cured)

        result = self._run_scaffold(branch)

        assert result.returncode == 0, f"a newborn fails the pin it is born with:\n{result.stdout}\n{result.stderr}"

    def test_a_newborn_that_regrows_the_walk_fails_its_own_pin(self, tmp_path):
        """The pin the newborn ships has to be able to convict, not just pass."""
        regressed = _render(_template_guard("specialist").read_text(encoding="utf-8")).replace(
            "    frame = sys._getframe(1)",
            "    import inspect\n\n    stack = inspect.stack()\n    frame = sys._getframe(1)",
        )
        assert "inspect.stack()" in regressed
        branch = self._mint(tmp_path, regressed)

        result = self._run_scaffold(branch)

        assert result.returncode != 0, (
            "a newborn that regrew the stack walk still passed its own pin — the "
            f"shipped pin cannot convict:\n{result.stdout}"
        )
        assert "handler guard" in result.stdout


class TestTheCallerIsNoneBranchHasABehaviouralInstrumentAfterAll:
    """A behavioural pin for the branch @devpulse's sweep called unreachable.

    Their fleet measurement (nine branches, 2026-08-31) is correct as stated:
    the ``caller_file is None`` branch is unreachable from any IMPORT-shaped
    test, because ``apps/__init__.py`` eagerly imports handlers and so always
    supplies a real-file frame. That is why restoring the walk leaves whole
    suites green.

    It is reachable from a DIRECT-CALL-shaped test. Called from a ``python -c``
    child, the only frames are ``<string>`` and importlib — both skipped — so
    ``_find_real_caller`` returns ``(None, None)`` and the branch runs. Deny
    ``os.path.realpath`` in that child and the restored walk dies where the
    cured guard returns cleanly.

    MEASURED both ways before writing this, against spawn's live guard:
        cured    -> GUARD_OK
        walk back -> GUARD_RAISED FileNotFoundError

    So the AST pin above is not the only thing standing between the fleet and a
    silent regrowth — it is just the only one that needs no subprocess. Relayed
    to @devpulse, because eight other branches were told no instrument exists.
    """

    PROBE = """
        import errno, os, os.path
        from pathlib import Path

        from aipass.spawn.apps.handlers import _find_real_caller, _guard_branch_access

        # Arming probe: the branch under test only runs when there is no caller
        # frame outside the guard. If a real-file frame ever appears here, this
        # test is exercising a different path and must say so rather than pass.
        caller, _line = _find_real_caller()
        print("CALLER_IS_NONE" if caller is None else f"CALLER_IS_{caller}")

        def _no_realpath(*args, **kwargs):
            raise FileNotFoundError(errno.ENOENT, "No such file or directory")

        os.path.realpath = _no_realpath

        import pathlib as _pathlib

        if hasattr(_pathlib, "_NormalAccessor"):
            _pathlib._NormalAccessor.realpath = staticmethod(_no_realpath)
        if hasattr(_pathlib, "_normal_accessor"):
            _pathlib._normal_accessor.realpath = _no_realpath

        # Second arming probe, split by ROUTE. The guard can reach realpath two
        # ways and they are denied by different patches, so one combined
        # DENIAL_LIVE would hide a half-armed world:
        #
        #   direct  — inspect.stack() -> getsourcefile -> getmodule ->
        #             os.path.realpath(f). This is the route a REGROWN walk
        #             takes, and it is what this pin exists to catch.
        #   pathlib — _find_real_caller's own Path(...).resolve() calls, which
        #             on <=3.10 go through the captured accessor and are NOT
        #             denied by the rebinding above.
        #
        # Both paths are ABSOLUTE. @devpulse's trap (c): a relative probe path
        # can raise because the path is relative and the cwd is unreadable,
        # which convicts for the path's shape rather than for the denial.
        _abs = os.path.join(os.sep, "definitely", "not", "here")

        try:
            os.path.realpath(_abs)
        except OSError:
            print("DENIAL_LIVE_DIRECT")
        else:
            print("DENIAL_DEAD_DIRECT")

        try:
            Path(_abs).resolve()
        except OSError:
            print("DENIAL_LIVE_PATHLIB")
        else:
            print("DENIAL_DEAD_PATHLIB")

        _guard_branch_access()
        print("GUARD_RETURNED")
        """

    def test_the_guard_returns_from_that_branch_without_touching_the_filesystem(self):
        result = _run(self.PROBE, cwd=Path(__file__).resolve().parents[4])

        lines = result.stdout.split()
        assert lines and lines[0] == "CALLER_IS_NONE", (
            "the probe did not reach the caller-is-None branch — it is measuring "
            f"a different path: {result.stdout!r} {result.stderr[-400:]}"
        )
        for route in ("DIRECT", "PATHLIB"):
            assert f"DENIAL_DEAD_{route}" not in lines, (
                f"the {route.lower()} realpath route was inert in the child, so this run "
                f"claims nothing. On <=3.10 the pathlib route needs the captured "
                f"accessor patched as well as os.path.realpath: {result.stdout!r}"
            )
            assert f"DENIAL_LIVE_{route}" in lines, (
                f"the child never armed the {route.lower()} route: {result.stdout!r}"
            )

        assert result.returncode == 0, (
            "the caller-is-None branch needs the filesystem — a restored "
            f"inspect.stack() walk is the usual cause:\n{result.stderr}"
        )
        assert lines[-1] == "GUARD_RETURNED"
