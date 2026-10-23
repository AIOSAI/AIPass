# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Pins seedgo imports against a working directory the OS cannot read
# Version: 1.2.1
# Created: 2026-08-31
# Modified: 2026-10-21
# =============================================

"""Tests that every module under apps/, apps/handlers/__init__.py first, imports with a dead cwd."""

# Every seedgo module must import without a readable working directory.
# World A emulates ntpath: ``os.path.realpath`` reads ``os.getcwd()`` first, then getcwd is denied, so a
# module-level ``Path(__file__).resolve()`` dies as it does on Windows. World B denies ``os.path.realpath``
# while ``abspath`` works, the asymmetry an ``inspect.stack()`` walk hits on Windows; world A cannot see it.
# The interpreter version is part of the platform: pre-3.11 pathlib routes resolve through a captured
# accessor, so the worlds patch it too. Each world has a positive control (the old shape must die) and a
# control for that control (the same module imports cleanly in the healthy world).

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — what os.getcwd() does on a live directory; only its denial is the subject

import subprocess
import sys
from pathlib import Path

import pytest

SEEDGO_ROOT = Path(__file__).resolve().parents[1]

# The children's cwd is a room this module owns, so a world writing to a RELATIVE path lands there and
# the litter detector below fails the module. Not the repo root: parallel workers write there (a ruff
# call mints .ruff_cache), and a detector over a shared directory convicts a sibling's write.
CHILD_CWD = None


def _working_tree_entries(root: Path) -> set:
    """Names directly under `root`, or an empty set if it is not readable."""
    try:
        return {entry.name for entry in root.iterdir()}
    except OSError:
        return set()


def _litter(before: set, after: set) -> set:
    """What this file's children added to the working tree, as a plain function over two sets."""
    return after - before


@pytest.fixture(scope="module", autouse=True)
def _no_working_tree_litter(tmp_path_factory):
    """Hand the children their own room as cwd, and fail the module if they left anything in it."""
    room = tmp_path_factory.mktemp("child_cwd")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(sys.modules[__name__], "CHILD_CWD", room)
        before = _working_tree_entries(room)
        yield
        new = _litter(before, _working_tree_entries(room))
    assert not new, (
        "a world in this file wrote into its cwd - the children run in this module's "
        f"room, so a relative path lands there: {sorted(new)}"
    )


#: Warmed while the cwd is still readable, so the sweep convicts SEEDGO's modules, not the shared
#: infrastructure they pull in. A name belongs here only if something under _seedgo_modules() reaches it.
PRELOAD = """
from aipass.prax import logger  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.cli  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401
import aipass.cli.apps.modules.display  # noqa: F401
import aipass.drone.apps.modules  # noqa: F401
import aipass.spawn.apps.modules  # noqa: F401
import aipass.aipass.shared  # noqa: F401
"""

# The two shapes the cure deleted, rebuilt verbatim and imported live: only the old code can say
# whether the world still kills it.
DEFECT_A_SOURCE = "from pathlib import Path\nX = Path(__file__).resolve()\n"
DEFECT_B_SOURCE = "import inspect\nX = inspect.stack()\n"
#: The second captured route: before 3.11 Path.cwd() reaches _accessor.getcwd, never os.getcwd, so
#: this and DEFECT_A_SOURCE are convicted by different halves of the same world.
DEFECT_C_SOURCE = "from pathlib import Path\nX = Path.cwd()\n"

ARM_WORLD_A = """
import os

_real_realpath = os.path.realpath


def _ntpath_condition(path, **kw):
    os.getcwd()  # ntpath.realpath reads cwd before checking absoluteness
    return _real_realpath(path, **kw)


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.path.realpath = _ntpath_condition

# THE CAPTURED ACCESSOR. Before 3.11, pathlib's _NormalAccessor took its OWN
# reference at class-creation time — `realpath = staticmethod(os.path.realpath)`,
# CPython 3.10 pathlib.py:358 — and Path.resolve called it as
# `self._accessor.realpath(self, strict=strict)` (line 1077). So 3.10 DOES
# delegate to os.path.realpath; it just holds a copy taken when pathlib was
# first imported, and rebinding the module attribute afterwards rebinds a name
# nothing will read again. That, not a missing delegation, is why this world was
# inert on the 3.10 CI leg (@memory read the source and refuted the first
# diagnosis; relayed by @devpulse). staticmethod, not a plain function: bound as
# a method it would swallow the path argument into self.
try:
    import pathlib as _pathlib_for_accessor

    _pathlib_for_accessor._NormalAccessor.realpath = staticmethod(_ntpath_condition)
    # The OTHER captured route: Path.cwd() is cls(cls._accessor.getcwd()) before
    # 3.11, a separate attribute holding a separate copy. Curing realpath alone
    # leaves a module-level Path.cwd() unconvicted on 3.10 — the world would
    # deny a getcwd nothing reads (@skills, round 7).
    _pathlib_for_accessor._NormalAccessor.getcwd = staticmethod(_dead_getcwd)
except AttributeError:
    pass  # 3.11+ removed the accessor and calls os.path.realpath at use.

os.getcwd = _dead_getcwd
"""

# WORLD A-PRIME patches ``Path.resolve`` itself, the public call the defect makes, so it arms on every
# version. World A stays as the faithful ntpath emulation; the two are pinned to AGREE wherever both arm.
ARM_WORLD_A_PRIME = """
import os
import pathlib

_real_resolve = pathlib.Path.resolve


def _windows_shaped_resolve(self, strict=False):
    # The PROPERTY ntpath gives Windows: resolve() reads the working directory
    # whether or not the path is relative. Injected at the public call so no
    # pathlib internal is assumed.
    os.getcwd()
    return _real_resolve(self, strict=strict)


pathlib.Path.resolve = _windows_shaped_resolve


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd
"""

ARM_WORLD_B = """
import os


def _dead_realpath(path, **kw):
    # ntpath.realpath's first act is a cwd read; abspath still SUCCEEDS on
    # Windows, which is exactly why inspect reaches this call unprotected.
    raise FileNotFoundError(2, "realpath needs a cwd", "")


os.path.realpath = _dead_realpath
"""

# Does this interpreter's Path.resolve() reach the denied call for an absolute path? A probe reporting
# both outcomes, never a skipif, so a vacuous world is named in the output.
PROBE = """
import pathlib

try:
    pathlib.Path(pathlib.__file__).resolve()
    print("PROBE_VACUOUS")
except OSError:
    print("PROBE_ARMED")
"""

# World B denies ``os.path.realpath``, so its probe measures os.path.realpath, the call ``inspect``
# makes on every version, not Path.resolve().
PROBE_REALPATH = """
import os

try:
    os.path.realpath(os.__file__)
    print("PROBE_VACUOUS")
except OSError:
    print("PROBE_ARMED")
"""


# THE OPPOSITE-PLATFORM LITMUS, as a world so it can ride into any child. Emulated BY PROPERTY, never
# by aliasing: on posix ntpath.realpath IS abspath, while a real nt realpath reads os.getcwd() for
# absolute paths too (ntpath.py:678).
EMULATE_NT_REALPATH = """
import os

_posix_realpath_before_nt = os.path.realpath


def _nt_shaped_realpath(path, *a, **kw):
    # ntpath.py:678 - unconditional, even when the path is already absolute.
    os.getcwd()
    return _posix_realpath_before_nt(path, *a, **kw)


os.path.realpath = _nt_shaped_realpath
"""


# World A WITHOUT the accessor cure — the shape that went red on the 3.10 CI
# leg, kept as the negative control for the four lines that fixed it.
BARE_MODULE_PATCH_ONLY = """
import os

_real_realpath_bare = os.path.realpath


def _ntpath_condition_bare(path, **kw):
    os.getcwd()
    return _real_realpath_bare(path, **kw)


os.path.realpath = _ntpath_condition_bare


def _dead_getcwd_bare():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd_bare
"""

# Equivalent mutant: binding os.getcwd harmlessly inside EMULATE_NT_REALPATH survives every pin,
# because both worlds rebind os.getcwd to a denier last, after the emulation.


# A host that is ALREADY 3.10-shaped: the emulation must stand down over a real accessor, not replace it
# with a stand-in pathlib's own API cannot route through. Emulated by property: pre-3.11 pathlib ROUTES
# through the accessor (mkdir at pathlib.py:1175), not merely carries the attribute.
EMULATE_NATIVE_ACCESSOR_HOST = """
import os
import pathlib

# THE HOST MAY ALREADY BE ONE. Round 8 cured EMULATE_PY310_PATHLIB of replacing
# a real accessor and I built its reproduction partner with the identical flaw:
# a three-method stand-in installed over CPython 3.10's real _NormalAccessor,
# which routes stat, listdir, open and the rest through it. On 3.12 nothing
# reads the attribute so both arms looked right; on the real 3.10 leg of
# 9bd2618b every pin riding this world died on
# `AttributeError: '_NativeAccessor' object has no attribute 'stat'`.
#
# THE SAME DEFECT, ONE FILE OVER, IN THE WORLD BUILT TO REPRODUCE IT. The cure
# is the same too, and it is now applied in both directions: on a host that
# already has the shape, do nothing and say so.
if hasattr(pathlib, "_NormalAccessor"):
    print("NATIVE_HOST_ALREADY")
else:

    class _NativeAccessor:
        # Stands in for CPython 3.10's real _NormalAccessor: MANY methods, not
        # three. Anything not named here DELEGATES to the os function of the
        # same name, so this stand-in cannot decapitate a host by omission -
        # which is exactly how its first version failed.
        realpath = staticmethod(os.path.realpath)
        getcwd = staticmethod(os.getcwd)
        mkdir = staticmethod(os.mkdir)

        def __getattr__(self, name):
            for source in (os, os.path):
                found = getattr(source, name, None)
                if found is not None:
                    return found
            raise AttributeError(name)

    def _pre_311_mkdir(self, mode=0o777, parents=False, exist_ok=False):
        # CPython 3.10 pathlib.py:1175, INCLUDING the parents/exist_ok handling
        # around it. The first version called the accessor and stopped there, so
        # mkdir(parents=True, exist_ok=True) raised the moment the directory
        # existed - green alone, red in a full suite where a temp log dir is
        # already there. Order-dependence hid an incomplete stand-in.
        try:
            self._accessor.mkdir(str(self), mode)
        except FileNotFoundError:
            if not parents or self.parent == self:
                raise
            self.parent.mkdir(parents=True, exist_ok=True)
            self.mkdir(mode, parents=False, exist_ok=exist_ok)
        except OSError:
            if not exist_ok or not self.is_dir():
                raise

    pathlib._NormalAccessor = _NativeAccessor
    pathlib._normal_accessor = _NativeAccessor()
    pathlib.Path._accessor = pathlib._normal_accessor
    pathlib.Path.mkdir = _pre_311_mkdir
    print("NATIVE_HOST_SYNTHESISED")
"""


#: A host shaped like a real pre-3.11 interpreter: an accessor pathlib ROUTES stat through, so the
#: 3.10 red is falsifiable here.
EMULATE_REAL_310_ACCESSOR_HOST = """
import os
import pathlib


class _RealAccessor:
    realpath = staticmethod(os.path.realpath)
    getcwd = staticmethod(os.getcwd)
    mkdir = staticmethod(os.mkdir)
    stat = staticmethod(os.stat)


def _pre_311_stat(self, follow_symlinks=True):
    # CPython 3.10 pathlib.py:1097 - self._accessor.stat(self, ...)
    return self._accessor.stat(str(self))


pathlib._NormalAccessor = _RealAccessor
pathlib._normal_accessor = _RealAccessor()
pathlib.Path._accessor = pathlib._normal_accessor
pathlib.Path.stat = _pre_311_stat
"""

#: An nt-shaped host: on Windows ``os.path`` IS ``ntpath``, so aliasing ntpath over os.path changes nothing.
#: Both halves are needed: module IDENTITY, and the unconditional cwd read a real nt realpath performs.
#: The replacement is a SENTINEL returning its argument, never borrowed posixpath behaviour. It patches
#: ``ntpath.realpath``, which survives the alias world's ``os.path.realpath = ntpath.realpath``.
_NT_HOST_UNCONDITIONAL_CWD = """
import ntpath
import os


def _nt_shaped_realpath_sentinel(path, *a, **kw):
    os.getcwd()  # ntpath.py:678 - unconditional, absolute paths included
    return path


ntpath.realpath = _nt_shaped_realpath_sentinel
"""

_NT_HOST_MODULE_IDENTITY = """
import ntpath
import os
import sys

os.path = ntpath
sys.modules["os.path"] = ntpath
"""

EMULATE_NT_HOST_IDENTITY = _NT_HOST_UNCONDITIONAL_CWD + _NT_HOST_MODULE_IDENTITY

#: The MIRROR of the world above: forcing each starting dialect keeps the pair two arms on every host,
#: since on a windows runner an untouched child already starts as ntpath. Identity ONLY, not a posix platform.
_POSIX_HOST_MODULE_IDENTITY = """
import os
import posixpath
import sys

os.path = posixpath
sys.modules["os.path"] = posixpath
"""

#: A flavour that is an OBJECT, as 3.10 and 3.11 carry. Stack it on EMULATE_PY310_PATHLIB, which
#: redirects resolve through the accessor first. It REFUSES realpath, as CPython 3.10's _PosixFlavour does.
EMULATE_OBJECT_FLAVOUR_HOST = """
import pathlib
import posixpath


class _ObjectFlavour:
    sep = posixpath.sep
    altsep = ""
    has_drv = False
    pathmod = posixpath

    def __getattr__(self, name):
        if name == "realpath":
            raise AttributeError("a 3.10 flavour has no realpath; resolve goes through the accessor")
        return getattr(posixpath, name)


# THE HOST MAY ALREADY BE THIS SHAPE - 3.10 and 3.11 are - and installing over
# a real _PosixFlavour REMOVES behaviour this world is not testing: the real one
# answers parse_parts, casefold and make_uri, none of which posixpath has, so
# the delegation below decapitates the very interpreter it is imitating.
#
# ROUND 11 SHIPPED THIS CHECK AGAINST THE WRONG CLASS. It read PurePath, where
# 3.10 and 3.11 do not define _flavour at all - the concrete PurePosixPath does
# - so getattr answered None, the else branch ran, and CI's 3.11 leg died in
# pathlib._parse_args on `module 'posixpath' has no attribute 'parse_parts'`.
# The stand-down existed and was looking at the wrong object; a guard that reads
# the wrong attribute is indistinguishable from no guard at all.
#
# Read from the CONCRETE class the world would replace, and answer three ways,
# because a pathlib with no _flavour at all (3.13 spells it parser) is not a
# host to stand down from - it is a question this world cannot ask.
_existing = getattr(pathlib.Path, "_flavour", None)
if _existing is None:
    print("OBJECT_FLAVOUR_UNAVAILABLE: this pathlib has no _flavour to stand in for")
elif not isinstance(_existing, type(posixpath)):
    print("OBJECT_FLAVOUR_NATIVE")
else:
    pathlib.Path._flavour = _ObjectFlavour()
    pathlib.PurePath._flavour = pathlib.Path._flavour
    print("OBJECT_FLAVOUR_INSTALLED")
"""

#: A 3.13-shaped resolve: one that reads ``os.path`` AT CALL TIME, so pointing os.path at ntpath MOVES
#: the route rather than breaking it, and the world's patch rides along.
EMULATE_313_RESOLVE_READS_OS_PATH = """
import os
import pathlib


def _resolve_313(self, strict=False):
    # The distinguishing property: os.path is looked up NOW, so whatever it
    # points at is the route.
    return pathlib.Path(os.path.realpath(str(self), strict=strict))


pathlib.Path.resolve = _resolve_313
print("RESOLVE_READS_OS_PATH_AT_CALL_TIME")
"""


#: Break the routing identity TOWARD the dialect this host is not: always pointing os.path at ntpath is a
#: no-op on nt. The child says which way it went, so a break that cannot happen does not look like one.
BREAK_THE_ROUTING_IDENTITY = """
import ntpath
import os
import posixpath
import sys

# WHERE THE CHILD STARTED, printed before anything moves. A row that spelled
# the starting dialect would be spelling the host it was written on: this box
# starts as posixpath, a windows runner starts as ntpath, and the nt-identity
# emulation starts as ntpath too. The direction is a JUDGEMENT over this
# reading, made by the reader, not a literal in the assertion.
print("IDENTITY_STARTED_AS:", os.path.__name__)
_toward = posixpath if os.path is ntpath else ntpath
os.path = _toward
sys.modules["os.path"] = _toward
print("IDENTITY_BROKEN_TOWARD:", _toward.__name__)
"""


def _break_direction(started_as: str) -> str:
    """Which dialect the break must land on, given where the child started."""
    return "posixpath" if started_as == "ntpath" else "ntpath"


def _break_can_move_the_identity(flavour_is_a_dialect_module: bool) -> bool:
    """Whether `flavour is os.path` can move at all on this host."""
    return flavour_is_a_dialect_module


#: Make this child a host with NO accessor on any interpreter, so both arms are reachable everywhere.
REMOVE_ANY_NATIVE_ACCESSOR = """
import pathlib

if hasattr(pathlib, "_NormalAccessor"):
    del pathlib._NormalAccessor
"""

#: THE 3.11 HYBRID: no captured accessor (like 3.12+), an OBJECT flavour (like 3.10), and the call-time
#: module route. Composed from the halves above; the accessor removal is required, or a host that has
#: one cannot produce the hybrid.
EMULATE_311_HYBRID_HOST = REMOVE_ANY_NATIVE_ACCESSOR + EMULATE_OBJECT_FLAVOUR_HOST + EMULATE_313_RESOLVE_READS_OS_PATH


# A 3.10-shaped pathlib, so the accessor claim is falsifiable here: resolve() is rebuilt to read the cwd
# itself without touching os.path.realpath. Under it world A goes inert and world A-prime still convicts.
EMULATE_PY310_PATHLIB = """
import os
import pathlib


def _captured_sentinel(path, *a, **kw):
    # A SENTINEL, not the real os.path.realpath. What this emulation is FOR is
    # the capture — that a reference taken at class-creation time cannot see a
    # later rebinding — and the identity of the captured function is beside the
    # point. Capturing the real one imported behaviour this file does not test:
    # on Windows ntpath.realpath reads os.getcwd() UNCONDITIONALLY (ntpath.py
    # :678, even for an absolute path, which is the posixpath fact that does not
    # travel), so under the getcwd denial the bare-patch control raised and the
    # pin read DEFECT_DIED. It died for the PLATFORM, not for the mechanism.
    # Measured on the round-6 windows-setup leg of c82c3d34 and reproduced here
    # by emulating that property (@memory's sentinel pattern, relayed round 7).
    #
    # Touching nothing means anything that raises afterwards is the patch's
    # doing, on any host. My own round-6 rule said absolute targets are
    # load-bearing; the half I missed is that "absolute never reads the cwd" is
    # a posixpath fact, not a portable one.
    return path


def _captured_getcwd():
    # The second sentinel. Returns a fixed absolute string rather than calling
    # the real os.getcwd, for the same reason as its sibling: this emulation is
    # about the CAPTURE, and anything it borrows from the host is a property the
    # pin did not mean to depend on.
    return os.sep + "captured"


class _NormalAccessor:
    # CPython 3.10 pathlib.py:358. The capture is the whole point: this holds
    # the function object NAMED when the class body ran, and a later rebinding
    # of that module attribute cannot be seen from here.
    #
    # TWO captured routes, not one. Path.cwd() is cls(cls._accessor.getcwd())
    # before 3.11 and Path.resolve() goes through _accessor.realpath — separate
    # attributes, each with its own capture. Arming one says nothing about the
    # other, and a world that cures only realpath still lets a module-level
    # Path.cwd() sail through on 3.10 (@skills, who found it as a live mutant
    # survivor: deleting their realpath patch changed nothing because every pin
    # underneath was riding the getcwd half).
    realpath = staticmethod(_captured_sentinel)
    getcwd = staticmethod(_captured_getcwd)


_normal_accessor = _NormalAccessor()

# THE HOST MAY ALREADY BE THIS SHAPE, and if it is, emulating DESTROYS it.
#
# Measured on the round-8 3.10 leg of 68ab5132: a real 3.10 pathlib routes its
# whole API through the accessor (mkdir at pathlib.py:1175 is
# `self._accessor.mkdir(self, mode)`), so replacing a fully-featured accessor
# with this two-method stand-in decapitated the interpreter and every module
# import died on `AttributeError: '_NormalAccessor' object has no attribute
# 'mkdir'`. The pin was red for the emulation, not for the defect.
#
# The general rule this file had already learned once and did not apply here: an
# instrument must not import behaviour it is not testing - and the mirror image
# is that it must not REMOVE behaviour it is not testing either. On a host that
# already has the pre-3.11 shape there is nothing to emulate; the host IS the
# subject, and the emulation's whole job is to give a 3.11+ host that shape.
#
# Which arm ran is PRINTED rather than assumed, because a silent no-op and a
# silent replacement look identical from downstream (@spawn's ROUTE_ARMED /
# ROUTE_DARK vocabulary, arrived at independently on the same CI board).
if getattr(pathlib, "_NormalAccessor", None) is not _NormalAccessor and hasattr(pathlib, "_NormalAccessor"):
    print("ACCESSOR_NATIVE")
else:
    pathlib._NormalAccessor = _NormalAccessor
    pathlib._normal_accessor = _normal_accessor

    def _pre_311_resolve(self, strict=False):
        # CPython 3.10 pathlib.py:1077 - called through the INSTANCE, which is
        # why a world must patch the class attribute the instance falls
        # through to.
        return pathlib.Path(_normal_accessor.realpath(str(self), strict=strict))

    def _pre_311_cwd(cls):
        # CPython 3.10 pathlib.py:1088 - cls(cls._accessor.getcwd()).
        return cls(cls._accessor.getcwd())

    pathlib.Path.resolve = _pre_311_resolve
    pathlib.Path._accessor = _normal_accessor
    pathlib.Path.cwd = classmethod(_pre_311_cwd)
    print("ACCESSOR_EMULATED")
"""


def _seedgo_modules():
    """Every importable module under seedgo/apps, enumerated live."""
    modules = []
    for path in sorted(SEEDGO_ROOT.glob("apps/**/*.py")):
        parts = list(path.relative_to(SEEDGO_ROOT).parts)
        # Dot-directories are not packages: .archive/ holds disposal copies whose dotted name is not valid syntax.
        if any(part.startswith(".") or part == "__pycache__" for part in parts):
            continue
        parts = parts[:-1] if parts[-1] == "__init__.py" else parts[:-1] + [parts[-1][:-3]]
        modules.append("aipass.seedgo." + ".".join(parts) if parts else "aipass.seedgo")
    return modules


def _run(world: str):
    """Run a world in a child process, fed on stdin.

    stdin, not a script file: ``<stdin>`` is a pseudo-file the handlers guard skips; a real path is refused.
    """
    return subprocess.run(
        [sys.executable, "-"],
        input=world,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(CHILD_CWD),
    )


def _import_every_module_body():
    lines = [f"import {name}  # noqa: F401" for name in _seedgo_modules()]
    return "\n".join(lines) + '\nprint("IMPORTED_ALL")\n'


def _defect_body(tmp_path: Path, source: str, name: str) -> str:
    """A module in the deleted shape, on disk, imported by absolute path."""
    target = tmp_path / f"{name}.py"
    target.write_text(source, encoding="utf-8")
    return f"""
import importlib.util

_spec = importlib.util.spec_from_file_location({name!r}, {str(target)!r})
_mod = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_mod)
    print("DEFECT_SURVIVED")
except OSError as exc:
    print("DEFECT_DIED:", type(exc).__name__)
"""


@pytest.fixture(scope="module")
def world_a_result():
    """The module sweep rides WORLD A-PRIME, not world A."""
    return _run(PRELOAD + ARM_WORLD_A_PRIME + PROBE + _import_every_module_body())


@pytest.fixture(scope="module")
def world_a_result_on_310_shaped_pathlib():
    """The same sweep on the interpreter shape this machine does not have."""
    return _run(PRELOAD + EMULATE_PY310_PATHLIB + ARM_WORLD_A_PRIME + PROBE + _import_every_module_body())


@pytest.fixture(scope="module")
def world_b_result():
    return _run(PRELOAD + ARM_WORLD_B + _import_every_module_body())


#: The three answers the nt arming probe can honestly give, a plain judgement over measured values so
#: every row is reachable on any host.
ALIAS_DISCRIMINATION_LIVE = "ARMED_AND_DISCRIMINATING"
ALIAS_DISCRIMINATION_UNFALSIFIABLE = "ARMED_BUT_INDISTINGUISHABLE_FROM_AN_ALIAS"
EMULATION_NOT_ARMED = "NOT_ARMED"


def _alias_discrimination_verdict(host_reads_cwd: bool, emulated_reads_cwd: bool) -> str:
    """What the nt arming probe can claim, given what it measured."""
    if not emulated_reads_cwd:
        return EMULATION_NOT_ARMED
    if host_reads_cwd:
        return ALIAS_DISCRIMINATION_UNFALSIFIABLE
    return ALIAS_DISCRIMINATION_LIVE


#: Why the alias trap can or cannot be caught on this interpreter, one answer per way of losing it,
#: so a verdict names the cause.
ALIAS_CATCHABLE = "ALIAS_IS_CATCHABLE_HERE"
ALIAS_LOST_TO_PLATFORM = "ALIAS_INDISTINGUISHABLE:the alias IS this host"
ALIAS_LOST_TO_VERSION = "ALIAS_INDISTINGUISHABLE:ntpath no longer calls a rooted literal absolute"
ALIAS_LOST_TO_BEHAVIOUR = "ALIAS_INDISTINGUISHABLE:a foreign ntpath read the cwd anyway"


CONTROL_EXPECTS_DEATH = "WORLD_A_STILL_CONVICTS"
CONTROL_EXPECTS_SURVIVAL = "WORLD_A_IS_DISARMED"


def _chimera_control_expectation(reaches_under_chimera: bool, has_captured_accessor: bool) -> str:
    """What breaking the ``os.path`` identity should do to world A here."""
    if reaches_under_chimera or has_captured_accessor:
        return CONTROL_EXPECTS_DEATH
    return CONTROL_EXPECTS_SURVIVAL


ROUTE_VIA_MODULE = "A_MODULE_PATCH_REACHES_RESOLVE"
ROUTE_VIA_ACCESSOR = "A_MODULE_PATCH_IS_NOT_READ_AGAIN:pathlib captured its own copy"
ROUTE_UNEXPLAINED = "NO_ROUTE_EXPLAINS_THIS_HOST"


def _module_patch_route(module_patch_reaches_resolve: bool, has_captured_accessor: bool) -> str:
    """Whether rebinding ``os.path.realpath`` can reach ``Path.resolve`` here."""
    if module_patch_reaches_resolve:
        return ROUTE_VIA_MODULE
    if has_captured_accessor:
        return ROUTE_VIA_ACCESSOR
    return ROUTE_UNEXPLAINED


def _alias_catchability(
    alias_reads_cwd: bool,
    ntpath_calls_probe_absolute: bool,
    alias_is_the_host: bool,
) -> str:
    """Whether the alias trap (``os.path.realpath = ntpath.realpath``) is detectable here, and if not, why."""
    if not alias_reads_cwd:
        return ALIAS_CATCHABLE
    if alias_is_the_host:
        return ALIAS_LOST_TO_PLATFORM
    if not ntpath_calls_probe_absolute:
        return ALIAS_LOST_TO_VERSION
    return ALIAS_LOST_TO_BEHAVIOUR


class TestTheInstrumentsCanFire:
    """Positive controls: each world must still kill the code the cure deleted."""

    def test_world_a_kills_a_module_level_resolve(self, tmp_path):
        """World A kills a module-level resolve on every interpreter: it patches the captured accessor too."""
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        result = _run(PRELOAD + ARM_WORLD_A + body)
        assert "DEFECT_DIED" in result.stdout, f"world A is not armed: {result.stdout}\n{result.stderr}"

    def test_world_a_prime_kills_a_module_level_resolve_on_every_version(self, tmp_path):
        """World A-prime patches ``Path.resolve`` itself, so nothing pathlib does internally can fool it."""
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        result = _run(PRELOAD + ARM_WORLD_A_PRIME + body)
        assert "DEFECT_DIED" in result.stdout, f"world A-prime is not armed: {result.stdout}\n{result.stderr}"

    def test_the_two_world_a_constructions_agree(self, tmp_path):
        """The two world-A constructions must agree, so a divergence surfaces as a red."""
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        faithful = _run(PRELOAD + ARM_WORLD_A + body)
        cross_check = _run(PRELOAD + ARM_WORLD_A_PRIME + body)
        assert "DEFECT_DIED" in faithful.stdout, faithful.stdout
        assert "DEFECT_DIED" in cross_check.stdout, cross_check.stdout

    def test_a_getcwd_denial_does_not_reach_a_pre_captured_getcwd_accessor(self, tmp_path):
        """The realpath control's sibling, on the route nothing here was driving."""
        body = _defect_body(tmp_path, DEFECT_C_SOURCE, "defect_c")
        result = _run(PRELOAD + EMULATE_PY310_PATHLIB + BARE_MODULE_PATCH_ONLY + body)
        assert "DEFECT_SURVIVED" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_world_a_convicts_the_getcwd_route_too(self, tmp_path):
        """The cured world reaches the getcwd route: without the second staticmethod line this is red."""
        body = _defect_body(tmp_path, DEFECT_C_SOURCE, "defect_c")
        result = _run(PRELOAD + EMULATE_PY310_PATHLIB + ARM_WORLD_A + body)
        assert "DEFECT_DIED" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_the_emulation_is_inert_on_a_host_that_already_has_an_accessor(self, tmp_path):
        """The emulation stands down on a host that already has an accessor, rather than replacing it."""
        probe = (
            "import pathlib, tempfile\n"
            "target = pathlib.Path(tempfile.mkdtemp()) / 'sub'\n"
            "target.mkdir()\n"
            "print('MKDIR_WORKED')\n"
        )
        world = EMULATE_REAL_310_ACCESSOR_HOST + EMULATE_NATIVE_ACCESSOR_HOST
        result = _run(PRELOAD + world + EMULATE_PY310_PATHLIB + probe)
        assert "NATIVE_HOST_ALREADY" in result.stdout, f"{result.stdout}\n{result.stderr}"
        assert "ACCESSOR_NATIVE" in result.stdout, f"{result.stdout}\n{result.stderr}"
        assert "MKDIR_WORKED" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_the_emulation_still_takes_on_a_host_without_one(self, tmp_path):
        """The emulation still takes on a host without an accessor, which is emulated rather than assumed."""
        probe = "print('BODY_RAN')\n"
        result = _run(PRELOAD + REMOVE_ANY_NATIVE_ACCESSOR + EMULATE_PY310_PATHLIB + probe)
        assert "ACCESSOR_EMULATED" in result.stdout, f"{result.stdout}\n{result.stderr}"
        assert "BODY_RAN" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_the_native_host_emulation_routes_and_does_not_merely_declare(self, tmp_path):
        """The native-host emulation routes through the accessor, not merely declares it."""
        probe = (
            "import pathlib, tempfile\n"
            "seen = []\n"
            "_real = pathlib.Path._accessor.mkdir\n"
            "pathlib.Path._accessor.mkdir = lambda *a, **k: (seen.append(1), _real(*a, **k))[1]\n"
            "(pathlib.Path(tempfile.mkdtemp()) / 'sub').mkdir()\n"
            "print('MKDIR_WENT_THROUGH_ACCESSOR:', bool(seen))\n"
        )
        result = _run(PRELOAD + EMULATE_NATIVE_ACCESSOR_HOST + probe)
        assert "MKDIR_WENT_THROUGH_ACCESSOR: True" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_the_native_world_does_not_decapitate_a_real_pre_311_host(self, tmp_path):
        """The native world installs over no real pre-3.11 accessor: 3.10's routes stat through it."""
        probe = "import pathlib, tempfile\nd = pathlib.Path(tempfile.mkdtemp())\nprint('IS_DIR:', d.is_dir())\n"
        world = EMULATE_REAL_310_ACCESSOR_HOST + EMULATE_NATIVE_ACCESSOR_HOST
        result = _run(PRELOAD + world + probe)
        assert "NATIVE_HOST_ALREADY" in result.stdout, f"{result.stdout}\n{result.stderr}"
        assert "IS_DIR: True" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_the_synthesised_accessor_delegates_what_it_does_not_name(self, tmp_path):
        """The synthesised accessor delegates every unnamed attribute to the os function of that name."""
        probe = (
            "import pathlib\n"
            "acc = pathlib._normal_accessor\n"
            "print('DELEGATES_STAT:', callable(getattr(acc, 'stat', None)))\n"
            "print('DELEGATES_LISTDIR:', callable(getattr(acc, 'listdir', None)))\n"
        )
        result = _run(PRELOAD + REMOVE_ANY_NATIVE_ACCESSOR + EMULATE_NATIVE_ACCESSOR_HOST + probe)
        assert "NATIVE_HOST_SYNTHESISED" in result.stdout, f"{result.stdout}\n{result.stderr}"
        assert "DELEGATES_STAT: True" in result.stdout, f"{result.stdout}\n{result.stderr}"
        assert "DELEGATES_LISTDIR: True" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_the_real_310_host_routes_stat_and_does_not_merely_declare_it(self, tmp_path):
        """Arming probe: the real-3.10 host emulation routes stat through the accessor, not merely carries it."""
        probe = (
            "import pathlib, tempfile\n"
            "seen = []\n"
            "_real = pathlib.Path._accessor.stat\n"
            "pathlib.Path._accessor.stat = lambda *a, **k: (seen.append(1), _real(*a, **k))[1]\n"
            "pathlib.Path(tempfile.mkdtemp()).is_dir()\n"
            "print('STAT_WENT_THROUGH_ACCESSOR:', bool(seen))\n"
        )
        result = _run(PRELOAD + EMULATE_REAL_310_ACCESSOR_HOST + probe)
        assert "STAT_WENT_THROUGH_ACCESSOR: True" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_the_accessor_absence_emulation_actually_removes_it(self, tmp_path):
        """Arming probe: REMOVE_ANY_NATIVE_ACCESSOR really removes it, though it is a no-op on 3.11+."""
        probe = "import pathlib\nprint('HAS_ACCESSOR:', hasattr(pathlib, '_NormalAccessor'))\n"
        before = _run(PRELOAD + EMULATE_REAL_310_ACCESSOR_HOST + probe)
        after = _run(PRELOAD + EMULATE_REAL_310_ACCESSOR_HOST + REMOVE_ANY_NATIVE_ACCESSOR + probe)
        assert "HAS_ACCESSOR: True" in before.stdout, f"{before.stdout}\n{before.stderr}"
        assert "HAS_ACCESSOR: False" in after.stdout, f"{after.stdout}\n{after.stderr}"

    def test_the_native_host_mkdir_honours_parents_and_exist_ok(self, tmp_path):
        """The fidelity of the stand-in, pinned rather than left to run order."""
        probe = (
            "import pathlib, tempfile\n"
            "root = pathlib.Path(tempfile.mkdtemp()) / 'a' / 'b'\n"
            "root.mkdir(parents=True, exist_ok=True)\n"
            "root.mkdir(parents=True, exist_ok=True)\n"
            "print('PARENTS_AND_EXIST_OK_HONOURED')\n"
        )
        result = _run(PRELOAD + EMULATE_NATIVE_ACCESSOR_HOST + probe)
        assert "PARENTS_AND_EXIST_OK_HONOURED" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_every_module_imports_on_a_native_accessor_host_too(self, tmp_path):
        """Every module imports on a native-accessor host too, so a stand-in replacing it reds here."""
        modules = _seedgo_modules()
        assert modules != [], "no seedgo modules enumerated - this pin would be vacuous"
        body = (
            "import importlib\n"
            f"for name in {modules[:40]!r}:\n"
            "    importlib.import_module(name)\n"
            "print('ALL_IMPORTED')\n"
        )
        world = EMULATE_NATIVE_ACCESSOR_HOST + EMULATE_PY310_PATHLIB + ARM_WORLD_A
        result = _run(PRELOAD + world + body)
        assert "ACCESSOR_NATIVE" in result.stdout, f"{result.stdout}\n{result.stderr}"
        assert "ALL_IMPORTED" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_the_bare_patch_control_holds_on_an_nt_shaped_host_too(self, tmp_path):
        """THE LITMUS: the bare-patch control holds under the nt property too, not only on posix."""
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        world = EMULATE_NT_REALPATH + EMULATE_PY310_PATHLIB + BARE_MODULE_PATCH_ONLY
        result = _run(PRELOAD + world + body)
        assert "DEFECT_SURVIVED" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_world_a_still_convicts_on_an_nt_shaped_host(self, tmp_path):
        """World A still ARMS under the nt emulation, or the litmus pair proves only that both are inert."""
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        world = EMULATE_NT_REALPATH + EMULATE_PY310_PATHLIB + ARM_WORLD_A
        result = _run(PRELOAD + world + body)
        assert "DEFECT_DIED" in result.stdout, f"{result.stdout}\n{result.stderr}"

    ABSOLUTE_CWD_PROBE = (
        "import os\n"
        # '//x' is absolute under every rule here (posixpath, 3.12 and 3.13 ntpath) and is written down, never
        # built from the host. It is deliberately not the alias probe's '/x', whose absoluteness 3.13 changed.
        "_abs = '//x'\n"
        "print('PROBE_IS_ABS:', os.path.isabs(_abs))\n"
        "_seen = []\n"
        "_real_getcwd = os.getcwd\n"
        "os.getcwd = lambda: (_seen.append(1), _real_getcwd())[1]\n"
        "os.path.realpath(_abs)\n"
        "print('ABSOLUTE_PATH_READ_CWD:', bool(_seen))\n"
    )

    def _reads_cwd_for_an_absolute_path(self, host: str = "") -> bool:
        """Measure it, on whatever host `host` makes this child into."""
        result = _run(PRELOAD + host + self.ABSOLUTE_CWD_PROBE)
        assert "PROBE_IS_ABS: True" in result.stdout, f"{result.stdout}\n{result.stderr}"
        assert "ABSOLUTE_PATH_READ_CWD:" in result.stdout, f"{result.stdout}\n{result.stderr}"
        return "ABSOLUTE_PATH_READ_CWD: True" in result.stdout

    def test_the_nt_emulation_is_armed_and_says_what_it_can_discriminate(self, tmp_path):
        """Arming probe for the litmus, keyed on what it MEASURED."""
        host_reads = self._reads_cwd_for_an_absolute_path()
        emulated_reads = self._reads_cwd_for_an_absolute_path(EMULATE_NT_REALPATH)

        verdict = _alias_discrimination_verdict(host_reads, emulated_reads)
        assert verdict != EMULATION_NOT_ARMED, (
            "the nt emulation did not change an absolute path's cwd-reading behaviour, "
            "so every pin riding it measures nothing"
        )
        if verdict == ALIAS_DISCRIMINATION_LIVE:
            assert host_reads is False
        else:
            # Recorded, not skipped: the emulated half is asserted above; only whether an ALIAS would answer the
            # same is unmeasurable here, and on this host it would.
            assert host_reads is True

    @pytest.mark.parametrize(
        "host_reads,emulated_reads,expected",
        [
            (False, True, ALIAS_DISCRIMINATION_LIVE),
            (True, True, ALIAS_DISCRIMINATION_UNFALSIFIABLE),
            (False, False, EMULATION_NOT_ARMED),
            (True, False, EMULATION_NOT_ARMED),
        ],
    )
    def test_the_verdict_table_is_reachable_on_any_host(self, host_reads, emulated_reads, expected):
        """Every verdict row runs here, the nt one included: a literal table, so it cannot vanish."""
        assert _alias_discrimination_verdict(host_reads, emulated_reads) == expected

    def test_the_probe_answers_true_on_an_nt_shaped_host_and_the_pin_survives_it(self, tmp_path):
        """On an nt-shaped host the probe measures True, routes to the unfalsifiable verdict, and the pin holds."""
        # ONE application, read twice: stacking the emulation on itself recurses, so an nt host is modelled as
        # host == emulated.
        host_reads = self._reads_cwd_for_an_absolute_path(EMULATE_NT_REALPATH)
        emulated_reads = host_reads
        assert host_reads is True
        assert _alias_discrimination_verdict(host_reads, emulated_reads) == (ALIAS_DISCRIMINATION_UNFALSIFIABLE)

    NTPATH_313_ISABS = (
        "import ntpath, os\n"
        "\n"
        "def _isabs_313(s):\n"
        "    # CPython 3.13 ntpath.isabs - the LEGACY BUG clause is gone, so a\n"
        "    # rooted driveless path needs a drive or a UNC prefix to count.\n"
        "    s = os.fspath(s)\n"
        "    sep, altsep, colon_sep = chr(92), '/', ':' + chr(92)\n"
        "    s = s[:3].replace(altsep, sep)\n"
        "    return s.startswith(colon_sep, 1) or s.startswith(sep * 2)\n"
        "\n"
        "ntpath.isabs = _isabs_313\n"
    )

    ALIAS_WORLD = "import ntpath, os\nos.path.realpath = ntpath.realpath\n"

    ALIAS_PROBE = (
        "import ntpath, os\n"
        # A dialect-neutral literal, never derived from the host: `os.path.abspath(os.sep)` is '/' on posix and
        # 'D:\\' on nt, a different shape per platform.
        "_abs = '/x'\n"
        "print('ALIAS_IS_THE_HOST:', os.path is ntpath)\n"
        "print('NTPATH_CALLS_IT_ABSOLUTE:', ntpath.isabs(_abs))\n"
        "_seen = []\n"
        "_real_getcwd = os.getcwd\n"
        "os.getcwd = lambda: (_seen.append(1), _real_getcwd())[1]\n"
        "os.path.realpath(_abs)\n"
        "print('ALIAS_READ_CWD:', bool(_seen))\n"
    )

    def _measure_alias(self, host: str = "") -> tuple:
        """`(alias_reads_cwd, ntpath_calls_probe_absolute, alias_is_the_host)`."""
        result = _run(PRELOAD + host + self.ALIAS_WORLD + self.ALIAS_PROBE)
        assert "ALIAS_READ_CWD:" in result.stdout, f"{result.stdout}\n{result.stderr}"
        assert "ALIAS_IS_THE_HOST:" in result.stdout, f"{result.stdout}\n{result.stderr}"
        return (
            "ALIAS_READ_CWD: True" in result.stdout,
            "NTPATH_CALLS_IT_ABSOLUTE: True" in result.stdout,
            "ALIAS_IS_THE_HOST: True" in result.stdout,
        )

    def test_the_alias_trap_is_caught_or_the_reason_is_named(self, tmp_path):
        """The alias trap is caught here, or the verdict names which dimension took it away."""
        alias_reads, ntpath_absolute, alias_is_the_host = self._measure_alias()
        verdict = _alias_catchability(alias_reads, ntpath_absolute, alias_is_the_host)
        if verdict == ALIAS_CATCHABLE:
            assert alias_reads is False
        else:
            # Not skipped: the loss is recorded with its mechanism attached, so
            # a future reader sees a measured boundary rather than a gap.
            assert alias_reads is True

    def test_the_catchability_matches_what_the_host_is(self, tmp_path):
        """Both arms are asserted: the expectation derives from whether os.path already IS ntpath."""
        alias_reads, ntpath_absolute, alias_is_the_host = self._measure_alias()
        verdict = _alias_catchability(alias_reads, ntpath_absolute, alias_is_the_host)
        if alias_is_the_host:
            assert verdict == ALIAS_LOST_TO_PLATFORM, (
                "os.path IS ntpath here, so aliasing changes nothing and the trap "
                f"cannot be caught - expected the platform verdict, measured {verdict}"
            )
        elif ntpath_absolute:
            assert verdict == ALIAS_CATCHABLE, (
                "os.path is not ntpath here and ntpath calls the probe absolute, so "
                "the alias is a foreign shape whose failure to read the cwd is exactly "
                f"what catches it - measured {verdict}"
            )
        else:
            # THE THIRD HOST: a 3.13 interpreter on posix, where the alias is foreign AND reads the cwd, because
            # ntpath stopped calling a rooted driveless literal absolute.
            assert verdict == ALIAS_LOST_TO_VERSION, (
                "ntpath does not call the probe absolute here, so a foreign alias "
                f"reads the cwd for the version reason - measured {verdict}"
            )

    def test_the_alias_is_lost_to_version_on_a_313_shaped_ntpath(self, tmp_path):
        """The 3.13 row, emulated by property with a dialect-neutral literal, stated with its dimension."""
        _, bare_ntpath_absolute, _ = self._measure_alias()
        alias_reads, ntpath_absolute, alias_is_the_host = self._measure_alias(self.NTPATH_313_ISABS)
        if bare_ntpath_absolute:
            print("ISABS_313: INSTALLED")
        else:
            # NATIVE: the interpreter is already 3.13-shaped, so the row measures the host, not the emulation.
            print("ISABS_313: NATIVE")
        assert ntpath_absolute is False, (
            "the 3.13 isabs emulation did not take: a rooted driveless literal is still "
            "reported absolute, so this row would pass for the wrong reason"
        )
        assert alias_reads is True, "the alias did not read the cwd under the 3.13 shape"
        verdict = _alias_catchability(alias_reads, ntpath_absolute, alias_is_the_host)
        if alias_is_the_host:
            # UNVERIFIABLE HERE, by name: where os.path IS ntpath no version emulation can produce a version-only
            # loss, and the judgement reports the deeper reason.
            assert verdict == ALIAS_LOST_TO_PLATFORM, (
                "os.path IS ntpath here, so the version dimension cannot be isolated "
                f"and the platform reason outranks it - measured {verdict}"
            )
        else:
            assert verdict == ALIAS_LOST_TO_VERSION, (
                "on a host where the alias is foreign, a 3.13-shaped isabs is the only "
                f"thing that can make it read the cwd - measured {verdict}"
            )

    ROUTE_PROBE = (
        "import os, pathlib\n"
        "_p = pathlib.Path('x')\n"
        # 3.13 renamed _flavour to parser (pathlib._local): both are asked for and the answering one printed,
        # so a probe finding neither says so.
        "_name = 'NONE'\n"
        "_mod = None\n"
        "for _attr in ('_flavour', 'parser'):\n"
        "    _found = getattr(type(_p), _attr, None)\n"
        "    if _found is not None:\n"
        "        _name, _mod = _attr, _found\n"
        "        break\n"
        "print('FLAVOUR_ATTR:', _name)\n"
        "print('FLAVOUR_IS_OS_PATH:', _mod is os.path)\n"
        # Whether the routing attribute is a DIALECT MODULE at all, which decides if the line above can move.
        "import ntpath, posixpath\n"
        "print('FLAVOUR_IS_A_DIALECT_MODULE:', _mod is posixpath or _mod is ntpath)\n"
        "print('HAS_ACCESSOR:', hasattr(pathlib, '_NormalAccessor'))\n"
        # THE ROUTE ITSELF, measured: a spy on the module attribute, then one resolve of an absolute literal.
        "_seen = []\n"
        "_real_for_route = os.path.realpath\n"
        "def _route_spy(path, *a, **kw):\n"
        "    _seen.append(1)\n"
        "    return _real_for_route(path, *a, **kw)\n"
        "os.path.realpath = _route_spy\n"
        "try:\n"
        "    pathlib.Path('//x').resolve()\n"
        "except OSError as _exc:\n"
        # The measurement is whether the spy FIRED, not whether the call succeeded.
        "    print('ROUTE_RESOLVE_RAISED:', type(_exc).__name__)\n"
        "os.path.realpath = _real_for_route\n"
        "print('MODULE_PATCH_REACHES_RESOLVE:', bool(_seen))\n"
    )

    def _measure_route_and_report(self, host: str = "") -> tuple:
        """`((has_accessor, flavour_is_os_path, reaches), stdout)`."""
        result = _run(PRELOAD + host + self.ROUTE_PROBE)
        for line in ("HAS_ACCESSOR:", "FLAVOUR_IS_OS_PATH:", "MODULE_PATCH_REACHES_RESOLVE:"):
            assert line in result.stdout, f"{result.stdout}\n{result.stderr}"
        return (
            (
                "HAS_ACCESSOR: True" in result.stdout,
                "FLAVOUR_IS_OS_PATH: True" in result.stdout,
                "MODULE_PATCH_REACHES_RESOLVE: True" in result.stdout,
            ),
            result.stdout,
        )

    @staticmethod
    def _read_line(result, prefix: str) -> str:
        """The child's own answer for `prefix`, or a failure naming the child."""
        for line in result.stdout.splitlines():
            if line.startswith(prefix):
                return line[len(prefix) :].strip()
        raise AssertionError(f"the child never printed {prefix!r}: {result.stdout}\n{result.stderr}")

    def _measure_route(self, host: str = "") -> tuple:
        """`(has_accessor, flavour_is_os_path, module_patch_reaches_resolve)`."""
        readings, _ = self._measure_route_and_report(host)
        return readings

    def test_the_arming_worlds_patch_the_module_pathlib_routes_through(self, tmp_path):
        """A module patch on ``os.path.realpath`` reaches resolve, measured by a spy rather than read off _flavour."""
        has_accessor, flavour_is_os_path, reaches = self._measure_route()
        expected = _module_patch_route(reaches, has_accessor)
        assert expected != ROUTE_UNEXPLAINED, (
            "nothing reached resolve through os.path and no captured accessor "
            "explains why, so every world here that patches os.path.realpath is "
            f"inert (flavour is os.path: {flavour_is_os_path})"
        )
        # No second assertion for the missed-route case: it restates the UNEXPLAINED arm and no mutant kills it.
        # THE CONTROL FOR THE CONTROL: without it every value above could be hardcoded to its expected answer.
        # It breaks the identity TOWARD the dialect this host is not; the always-ntpath break is a no-op on nt.
        (broken_accessor, broken_is_os_path, _), break_report = self._measure_route_and_report(
            BREAK_THE_ROUTING_IDENTITY
        )
        assert "IDENTITY_BROKEN_TOWARD:" in break_report, (
            f"the break did not run, so this control measured nothing: {break_report}"
        )
        assert broken_is_os_path is False, (
            "the probe reports the routing identity intact on a host where it was "
            f"deliberately broken, so it is not reading anything: {break_report}"
        )
        # The reach half is not asserted here: it reads False on this interpreter and True on 3.13, whose resolve
        # follows os.path at call time. It is pinned host-independently one row down.
        assert broken_accessor is has_accessor, (
            "the chimera changed whether this host has a captured accessor, which it has no business touching"
        )

    def test_the_pre_311_shape_answers_the_other_arm_from_here(self, tmp_path):
        """The arm CI runs and this interpreter cannot reach on its own."""
        has_accessor, flavour_is_os_path, reaches = self._measure_route(EMULATE_PY310_PATHLIB)
        assert has_accessor is True, "the pre-3.11 emulation did not install an accessor"
        assert _module_patch_route(reaches, has_accessor) == ROUTE_VIA_ACCESSOR
        assert reaches is False, (
            "a module patch still reaches resolve under the pre-3.11 shape, so the "
            "captured-accessor half of every world here is measuring nothing"
        )

    def test_the_identity_break_goes_toward_the_dialect_the_host_is_not(self, tmp_path):
        """The identity break goes TOWARD the dialect the host is not, from either starting dialect."""
        for label, host in (
            ("a child forced to posix identity", _POSIX_HOST_MODULE_IDENTITY),
            ("a child forced to nt identity", _NT_HOST_MODULE_IDENTITY),
        ):
            child = _run(PRELOAD + host + BREAK_THE_ROUTING_IDENTITY + "print('DONE')\n")
            started = self._read_line(child, "IDENTITY_STARTED_AS:")
            went = self._read_line(child, "IDENTITY_BROKEN_TOWARD:")
            assert went == _break_direction(started), (
                f"{label}: started as {started}, so the break had to go toward "
                f"{_break_direction(started)} and went toward {went} - a fixed "
                f"direction is the no-op windows convicted: {child.stdout}\n{child.stderr}"
            )
        # AND THE TWO ARMS MUST BE DIFFERENT ARMS: the second host starts somewhere else, or a world that
        # never turns around passes both rows.
        as_posix = _run(PRELOAD + _POSIX_HOST_MODULE_IDENTITY + BREAK_THE_ROUTING_IDENTITY + "print('DONE')\n")
        as_nt = _run(PRELOAD + _NT_HOST_MODULE_IDENTITY + BREAK_THE_ROUTING_IDENTITY + "print('DONE')\n")
        assert self._read_line(as_posix, "IDENTITY_STARTED_AS:") != self._read_line(as_nt, "IDENTITY_STARTED_AS:"), (
            "both children started as the same dialect, so the turn-around was "
            f"never exercised: {as_posix.stdout}\n{as_nt.stdout}"
        )

    def test_the_break_actually_moves_the_identity_from_either_side(self, tmp_path):
        """The break moves the identity reading from either side, or reports a reading that cannot move."""
        for label, host in (
            ("this host, untouched", ""),
            ("the nt-identity emulation", _NT_HOST_MODULE_IDENTITY),
            # THE THIRD ARM IS THE STAND-DOWN, kept in this row because it is otherwise unreachable while this
            # box's flavour is a module. The HYBRID, not the bare object-flavour world: on 3.12 a bare one leaves
            # resolve asking the stand-in for realpath, which it refuses.
            ("a child with an OBJECT flavour", EMULATE_311_HYBRID_HOST),
        ):
            (_, intact, _), report = self._measure_route_and_report(host)
            (_, broken, _), _ = self._measure_route_and_report(host + BREAK_THE_ROUTING_IDENTITY)
            movable = "FLAVOUR_IS_A_DIALECT_MODULE: True" in report
            # Both arms assert, written as two arms rather than guard-and-`continue`, so each iteration pins a reading.
            if _break_can_move_the_identity(movable):
                assert broken is not intact, (
                    f"{label}: the break must MOVE the routing identity; it read "
                    f"{intact} before and {broken} after, i.e. nothing moved: {report}"
                )
            else:
                # 3.10, 3.11 and 3.13 land here: reported, not asserted; the reading is pinned dead in both directions.
                assert intact is False and broken is False, (
                    f"{label}: the routing attribute is not a dialect module, so "
                    f"`flavour is os.path` cannot be True either side of the "
                    f"break, and it read {intact} then {broken}: {report}"
                )

    def test_unexplained_means_measured_and_not_merely_absent_from_the_table(self, tmp_path):
        """UNEXPLAINED stays reachable as a value, so the route verdict keeps its third arm."""
        assert _module_patch_route(False, False) == ROUTE_UNEXPLAINED
        assert _module_patch_route(True, False) == ROUTE_VIA_MODULE
        assert _module_patch_route(False, True) == ROUTE_VIA_ACCESSOR

    def test_the_object_flavour_world_stands_down_on_a_host_that_has_one(self, tmp_path):
        """The object-flavour world stands down on a host that already has an object flavour."""
        marker = (
            "import pathlib, posixpath\n"
            "class _AlreadyAnObject:\n"
            "    sep = posixpath.sep\n"
            "    marked = True\n"
            "    def __getattr__(self, name):\n"
            "        return getattr(posixpath, name)\n"
            "pathlib.PurePath._flavour = _AlreadyAnObject()\n"
            "pathlib.Path._flavour = pathlib.PurePath._flavour\n"
        )
        probe = "import pathlib\nprint('MARKER_SURVIVED:', getattr(pathlib.Path._flavour, 'marked', False))\n"
        result = _run(PRELOAD + marker + EMULATE_OBJECT_FLAVOUR_HOST + probe)
        assert "OBJECT_FLAVOUR_NATIVE" in result.stdout, (
            "the world installed over a flavour that was already an object, which is "
            f"what decapitates a real 3.10: {result.stdout}\n{result.stderr}"
        )
        assert "MARKER_SURVIVED: True" in result.stdout, (
            f"the host's own flavour was replaced anyway: {result.stdout}\n{result.stderr}"
        )

    def test_the_object_flavour_world_reports_unavailable_with_no_flavour_at_all(self, tmp_path):
        """With no _flavour at all, the object-flavour world reports unavailable rather than standing down."""
        flavourless = (
            "import pathlib\n"
            "for _cls in (pathlib.Path, pathlib.PurePath, pathlib.PurePosixPath, pathlib.PosixPath):\n"
            "    try:\n"
            "        del _cls._flavour\n"
            "    except AttributeError:\n"
            "        pass\n"
        )
        result = _run(PRELOAD + flavourless + EMULATE_OBJECT_FLAVOUR_HOST + "print('CHILD_LIVED')\n")
        assert "OBJECT_FLAVOUR_UNAVAILABLE" in result.stdout, (
            "the world did not report the missing flavour, so it either installed "
            f"one or stood down for the wrong reason: {result.stdout}\n{result.stderr}"
        )
        assert "CHILD_LIVED" in result.stdout, (
            f"the world took the child down instead of reporting: {result.stdout}\n{result.stderr}"
        )

    def test_the_stand_down_reads_the_concrete_class_not_the_pure_path(self, tmp_path):
        """The stand-down reads the concrete PurePosixPath, where 3.10 and 3.11 define _flavour, not PurePath."""
        concrete_only = (
            "import pathlib, posixpath\n"
            "class _ConcreteFlavour:\n"
            "    sep = posixpath.sep\n"
            "    marked = True\n"
            "    def __getattr__(self, name):\n"
            "        return getattr(posixpath, name)\n"
            # ONLY the concrete class, exactly as 3.10 and 3.11 arrange it.
            "pathlib.Path._flavour = _ConcreteFlavour()\n"
            "try:\n"
            "    del pathlib.PurePath._flavour\n"
            "except AttributeError:\n"
            "    pass\n"
        )
        probe = "import pathlib\nprint('MARKER_SURVIVED:', getattr(pathlib.Path._flavour, 'marked', False))\n"
        result = _run(PRELOAD + concrete_only + EMULATE_OBJECT_FLAVOUR_HOST + probe)
        assert "OBJECT_FLAVOUR_NATIVE" in result.stdout, (
            "the world installed over a flavour it could only see on the concrete "
            f"class - the round-12 red, exactly: {result.stdout}\n{result.stderr}"
        )
        assert "MARKER_SURVIVED: True" in result.stdout, (
            f"the host's own flavour was replaced anyway: {result.stdout}\n{result.stderr}"
        )

    def test_the_object_flavour_refuses_realpath_like_the_real_one(self, tmp_path):
        """The stand-in must not be friendlier than the thing it stands in for."""
        probe = (
            "import pathlib\n"
            # A pathlib with no _flavour is a host this row cannot ask: reported by name, not crashing the child.
            "_f = getattr(pathlib.Path, '_flavour', None)\n"
            "if _f is None:\n"
            "    print('NO_FLAVOUR_TO_ASK')\n"
            "else:\n"
            "    try:\n"
            "        _f.realpath\n"
            "        print('FLAVOUR_ANSWERS_REALPATH: True')\n"
            "    except AttributeError:\n"
            "        print('FLAVOUR_ANSWERS_REALPATH: False')\n"
            "    print('FLAVOUR_STILL_PARSES:', _f.sep)\n"
        )
        result = _run(PRELOAD + EMULATE_PY310_PATHLIB + EMULATE_OBJECT_FLAVOUR_HOST + probe)
        if "NO_FLAVOUR_TO_ASK" in result.stdout:
            assert "OBJECT_FLAVOUR_UNAVAILABLE" in result.stdout, (
                f"the child found no flavour but the world claims it installed one: {result.stdout}\n{result.stderr}"
            )
            return
        assert "FLAVOUR_ANSWERS_REALPATH: False" in result.stdout, (
            f"the stand-in answers a question the original refuses: {result.stdout}\n{result.stderr}"
        )
        assert "FLAVOUR_STILL_PARSES: /" in result.stdout, (
            "the stand-in stopped parsing, so it is not a flavour at all - a stand-in "
            f"for a namespace must still answer what it is not being tested on: {result.stdout}"
        )

    @pytest.mark.parametrize(
        "reaches,has_accessor,expected",
        [
            (True, False, ROUTE_VIA_MODULE),
            (True, True, ROUTE_VIA_MODULE),
            (False, True, ROUTE_VIA_ACCESSOR),
            (False, False, ROUTE_UNEXPLAINED),
        ],
    )
    def test_the_route_table_is_reachable_on_any_host(self, reaches, has_accessor, expected):
        """All four combinations over a plain function."""
        assert _module_patch_route(reaches, has_accessor) == expected

    def test_no_probe_derives_its_path_from_the_host_it_measures(self, tmp_path):
        """No probe builds its path from the host it measures: checked in source, since behaviour hides it here."""
        for name, probe in (
            ("ABSOLUTE_CWD_PROBE", self.ABSOLUTE_CWD_PROBE),
            ("ALIAS_PROBE", self.ALIAS_PROBE),
        ):
            # The constant IS the child's source text, so this reads the line the
            # child will actually run rather than this file's spelling of it.
            assignment = [line for line in probe.splitlines() if line.strip().startswith("_abs =")]
            assert len(assignment) == 1, f"{name} no longer assigns its probe path once"
            assert "os.sep" not in assignment[0], (
                f"{name} builds its path out of the host's separator, so the row asks a different question per platform"
            )
            assert "abspath" not in assignment[0], f"{name} builds its path with the path module it is measuring"

    def test_the_sys_modules_half_survives_a_from_import(self, tmp_path):
        """The sys.modules half of the identity emulation is what a `from os.path import` child sees."""
        probe = "import ntpath\nfrom os.path import isabs\nprint('FROM_IMPORT_IS_NTPATH:', isabs is ntpath.isabs)\n"
        result = _run(PRELOAD + _NT_HOST_MODULE_IDENTITY + probe)
        assert "FROM_IMPORT_IS_NTPATH: True" in result.stdout, (
            f"the sys.modules half is not taking: {result.stdout}\n{result.stderr}"
        )

    def test_the_litter_detector_convicts_and_acquits(self, tmp_path):
        """Both verdicts of the working-tree detector, reachable without minting anything."""
        before = {"README.md", "src"}
        littered = chr(92) + "tmp" + chr(92) + "tmpx"
        assert _litter(before, set(before)) == set()
        assert _litter(before, before | {littered}) == {littered}
        assert _litter(before, before - {"src"}) == set(), (
            "the detector must not convict on a REMOVED entry - a concurrent "
            "citizen tidying its own file is not this file's litter"
        )

    def test_the_detector_reads_the_directory_the_children_actually_use(self, tmp_path):
        """The detector watches the directory `_run` hands the children as their cwd."""
        probe = "import os\nprint('CHILD_CWD:', os.getcwd())\n"
        result = _run(PRELOAD + probe)
        assert f"CHILD_CWD: {CHILD_CWD}" in result.stdout, (
            f"the detector watches {CHILD_CWD} but the children run elsewhere: {result.stdout}\n{result.stderr}"
        )

    def test_the_detector_reads_a_real_directory_and_survives_a_missing_one(self, tmp_path):
        """An unreadable root answers empty rather than raising; a real directory never answers empty."""
        # Its own room, not tmp_path itself: conftest's autouse mock_infrastructure creates the json seam under
        # tmp_path, and this assertion reads an EXACT set.
        room = tmp_path / "room"
        room.mkdir()
        (room / "here").mkdir()
        assert _working_tree_entries(room) == {"here"}
        assert _working_tree_entries(room / "absent") == set()

    def test_the_two_probe_literals_answer_different_questions(self, tmp_path):
        """'//x' and '/x' answer different questions and must not be unified: only '/x' changed in 3.13."""
        neutral = self._probe_literal(self.ABSOLUTE_CWD_PROBE)
        versioned = self._probe_literal(self.ALIAS_PROBE)
        probe = (
            "import ntpath, os, posixpath\n"
            "def _isabs_313(s):\n"
            "    s = os.fspath(s)\n"
            "    sep, altsep, colon_sep = chr(92), '/', ':' + chr(92)\n"
            "    s = s[:3].replace(altsep, sep)\n"
            "    return s.startswith(colon_sep, 1) or s.startswith(sep * 2)\n"
            f"for _name, _lit in (('NEUTRAL', {neutral!r}), ('VERSIONED', {versioned!r})):\n"
            "    print(_name, posixpath.isabs(_lit), _isabs_313(_lit))\n"
        )
        result = _run(PRELOAD + probe)
        assert "NEUTRAL True True" in result.stdout, f"{result.stdout}\n{result.stderr}"
        assert "VERSIONED True False" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_breaking_the_route_disarms_world_a_where_the_route_is_the_only_one(self, tmp_path):
        """The negative control, keyed on the route the host actually has: three arms, each asserted."""
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        chimera = "import ntpath, os, sys\nos.path = ntpath\nsys.modules['os.path'] = ntpath\n"
        has_accessor, _, _ = self._measure_route()
        # The fact that decides it, measured in the same world the control runs: with the chimera installed, does
        # a patch on os.path.realpath STILL reach resolve? Where it does, the route moved and world A convicts.
        _, _, reaches_under_chimera = self._measure_route(chimera)

        armed = _run(PRELOAD + ARM_WORLD_A + body)
        disarmed = _run(PRELOAD + chimera + ARM_WORLD_A + body)
        assert "DEFECT_DIED" in armed.stdout, f"{armed.stdout}\n{armed.stderr}"

        expectation = _chimera_control_expectation(reaches_under_chimera, has_accessor)
        if expectation == CONTROL_EXPECTS_DEATH:
            # THE ROUTE MOVED OR THERE ARE TWO OF THEM. Either resolve reads
            # os.path at call time (3.13, and nt seen from nt), or a captured
            # accessor carries a second route the break cannot touch (pre-3.11).
            assert "DEFECT_DIED" in disarmed.stdout, (
                "a route to realpath survived the chimera, so world A should still "
                f"convict and it did not: {disarmed.stdout}"
            )
        else:
            assert "DEFECT_SURVIVED" in disarmed.stdout, (
                "breaking the os.path route no longer disarms world A on a host where "
                f"it is the only route, so the invariant has stopped being why it works: {disarmed.stdout}"
            )

    @pytest.mark.parametrize(
        "reaches,has_accessor,expected",
        [
            (False, False, CONTROL_EXPECTS_SURVIVAL),
            (True, False, CONTROL_EXPECTS_DEATH),
            (False, True, CONTROL_EXPECTS_DEATH),
            (True, True, CONTROL_EXPECTS_DEATH),
        ],
    )
    def test_the_chimera_control_table_is_reachable_on_any_host(self, reaches, has_accessor, expected):
        """All four combinations over a plain function."""
        assert _chimera_control_expectation(reaches, has_accessor) == expected

    def test_the_313_shape_reproduces_the_unexplained_leg_from_here(self, tmp_path):
        """A call-time ``os.path`` resolve (3.13's shape) reproduces DEFECT_DIED with no accessor."""
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        chimera = "import ntpath, os, sys\nos.path = ntpath\nsys.modules['os.path'] = ntpath\n"
        world = EMULATE_313_RESOLVE_READS_OS_PATH + chimera
        disarmed = _run(PRELOAD + world + ARM_WORLD_A + body)
        _, _, reaches_under_chimera = self._measure_route(world)

        assert "RESOLVE_READS_OS_PATH_AT_CALL_TIME" in disarmed.stdout, (
            f"the 3.13 shape did not install, so this row measured nothing: {disarmed.stdout}"
        )
        assert reaches_under_chimera is True, (
            "the 3.13 shape did not move the route, so it is not the shape that explains the reported answer"
        )
        assert "DEFECT_DIED: FileNotFoundError" in disarmed.stdout, (
            f"the 3.13 shape no longer reproduces the leg it was built from: {disarmed.stdout}\n{disarmed.stderr}"
        )

    def test_the_313_shape_is_what_moves_the_route_and_not_the_chimera(self, tmp_path):
        """The control that separates the two halves of the row above."""
        chimera = "import ntpath, os, sys\nos.path = ntpath\nsys.modules['os.path'] = ntpath\n"
        _, _, without = self._measure_route(chimera)
        _, _, with_313 = self._measure_route(EMULATE_313_RESOLVE_READS_OS_PATH + chimera)
        assert with_313 is True
        if without:
            # NATIVE: this interpreter's own resolve already follows os.path, so the world cannot be shown to move
            # the route here. Reported, not asserted away.
            assert with_313 is without
        else:
            assert without is False, "the 3.13 shape adds nothing on this host, so the row above proves nothing"

    def test_the_pre_311_shape_reproduces_the_ci_answer_from_here(self, tmp_path):
        """Under EMULATE_PY310_PATHLIB the child answers DEFECT_DIED, and the bare host the other way."""
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        chimera = "import ntpath, os, sys\nos.path = ntpath\nsys.modules['os.path'] = ntpath\n"
        pre_311 = _run(PRELOAD + EMULATE_PY310_PATHLIB + chimera + ARM_WORLD_A + body)
        # The other arm is constructed too: removing the accessor leaves the module route as the only route on
        # every interpreter, so neither arm is read off the bare host.
        no_accessor = _run(PRELOAD + REMOVE_ANY_NATIVE_ACCESSOR + chimera + ARM_WORLD_A + body)
        # Which arm ran is reported, not demanded: on a real 3.10 the emulation stands down (ACCESSOR_NATIVE).
        assert any(word in pre_311.stdout for word in ("ACCESSOR_EMULATED", "ACCESSOR_NATIVE")), (
            f"the pre-3.11 world said nothing about which arm it took: {pre_311.stdout}"
        )
        assert "DEFECT_DIED: FileNotFoundError" in pre_311.stdout, (
            f"the pre-3.11 shape no longer reproduces the CI answer: {pre_311.stdout}"
        )
        _, _, no_accessor_reaches = self._measure_route(REMOVE_ANY_NATIVE_ACCESSOR + chimera)
        if no_accessor_reaches:
            # 3.13-shaped: removing the accessor leaves a resolve that still follows os.path, so the chimera moves
            # the route and world A keeps convicting.
            assert "DEFECT_DIED" in no_accessor.stdout, (
                "a module patch still reaches resolve with no accessor anywhere, so "
                f"world A should still convict and it did not: {no_accessor.stdout}"
            )
        else:
            assert "DEFECT_SURVIVED" in no_accessor.stdout, (
                "with no captured accessor and no route left, the chimera still fails "
                "to disarm world A, so the two arms no longer distinguish the routes: "
                f"{no_accessor.stdout}"
            )

    def test_the_platform_arm_is_reachable_here_on_an_nt_identity_host(self, tmp_path):
        """The platform arm of the catchability verdict is reachable here on an nt-identity host."""
        alias_reads, ntpath_absolute, alias_is_the_host = self._measure_alias(EMULATE_NT_HOST_IDENTITY)
        assert alias_is_the_host is True, "the nt identity emulation did not take"
        assert alias_reads is True, (
            "the emulated nt realpath did not read the cwd for an absolute path, so "
            "this host is nt in name only and the arm below proves nothing"
        )
        assert _alias_catchability(alias_reads, ntpath_absolute, alias_is_the_host) == ALIAS_LOST_TO_PLATFORM

    def test_the_nt_identity_emulation_needs_both_halves(self, tmp_path):
        """The nt-identity emulation needs both halves; each alone is measured on every host."""
        _, bare_ntpath_absolute, bare_is_the_host = self._measure_alias()
        reads_cwd_only, _, host_cwd_only = self._measure_alias(_NT_HOST_UNCONDITIONAL_CWD)
        reads_id_only, _, host_id_only = self._measure_alias(_NT_HOST_MODULE_IDENTITY)
        assert reads_cwd_only is True, "the cwd half did not take"
        assert host_id_only is True, "the identity half did not take"
        if bare_is_the_host:
            # ALREADY NT, so neither half can discriminate; both rows are still asserted at their nt values.
            assert host_cwd_only is True
            assert reads_id_only is True
        elif bare_ntpath_absolute:
            assert host_cwd_only is False, "the cwd half must not change module identity"
            assert reads_id_only is False, (
                "the identity half alone made the alias read the cwd, so this host "
                "no longer shows why the other half is needed"
            )
        else:
            # A 3.13-shaped ntpath reaches getcwd by itself, so this host cannot show the cwd half adds anything;
            # reported with the dimension attached.
            assert host_cwd_only is False, "the cwd half must not change module identity"
            assert reads_id_only is True

    @staticmethod
    def _probe_literal(probe: str) -> str:
        """The path a probe will actually use, read out of the probe itself."""
        assigned = [line for line in probe.splitlines() if line.strip().startswith("_abs =")]
        assert len(assigned) == 1, "the probe no longer assigns its path exactly once"
        value = assigned[0].split("=", 1)[1].strip()
        assert value[:1] == "'" and value[-1:] == "'", f"the probe path is not a plain literal: {value}"
        return value[1:-1]

    def test_the_probe_literal_is_the_same_shape_on_every_dialect(self, tmp_path):
        """The probe literal is rooted, driveless, and read the same way by both path modules."""
        literal = self._probe_literal(self.ALIAS_PROBE)
        probe = (
            "import ntpath, posixpath\n"
            f"_abs = {literal!r}\n"
            "print('NT_DRIVE:', repr(ntpath.splitdrive(_abs)[0]))\n"
            "print('POSIX_ABSOLUTE:', posixpath.isabs(_abs))\n"
        )
        result = _run(PRELOAD + probe)
        assert "NT_DRIVE: ''" in result.stdout, f"{result.stdout}\n{result.stderr}"
        assert "POSIX_ABSOLUTE: True" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_the_round_9_probe_spelling_would_still_be_host_shaped(self, tmp_path):
        """`os.path.abspath(os.sep)` under nt yields a DRIVE-rooted path, absolute under every isabs rule."""
        probe = (
            "import ntpath\n"
            "_old_spelling = ntpath.abspath(ntpath.sep)\n"
            "print('OLD_SPELLING_HAS_DRIVE:', bool(ntpath.splitdrive(_old_spelling)[0]))\n"
            "print('NEW_SPELLING_HAS_DRIVE:', bool(ntpath.splitdrive('/x')[0]))\n"
        )
        result = _run(PRELOAD + probe)
        assert "NEW_SPELLING_HAS_DRIVE: False" in result.stdout, f"{result.stdout}\n{result.stderr}"

    @pytest.mark.parametrize(
        "alias_reads,ntpath_absolute,is_host,expected",
        [
            (False, True, False, ALIAS_CATCHABLE),
            (False, False, False, ALIAS_CATCHABLE),
            (False, True, True, ALIAS_CATCHABLE),
            (False, False, True, ALIAS_CATCHABLE),
            (True, True, True, ALIAS_LOST_TO_PLATFORM),
            (True, False, True, ALIAS_LOST_TO_PLATFORM),
            (True, False, False, ALIAS_LOST_TO_VERSION),
            (True, True, False, ALIAS_LOST_TO_BEHAVIOUR),
        ],
    )
    def test_the_catchability_table_is_reachable_on_any_host(self, alias_reads, ntpath_absolute, is_host, expected):
        """All eight catchability combinations, a literal table over a plain function."""
        assert _alias_catchability(alias_reads, ntpath_absolute, is_host) == expected

    def test_the_313_emulation_changes_only_isabs(self, tmp_path):
        """Arming probe: the 3.13 emulation changes only isabs, or the version row passes for the wrong reason."""
        probe = (
            "import ntpath, os\n"
            "print('ROOTED_IS_ABSOLUTE:', ntpath.isabs(os.sep))\n"
            "print('DRIVED_IS_ABSOLUTE:', ntpath.isabs('C:' + chr(92) + 'x'))\n"
        )
        plain = _run(PRELOAD + probe)
        emulated = _run(PRELOAD + self.NTPATH_313_ISABS + probe)
        assert "DRIVED_IS_ABSOLUTE: True" in plain.stdout, plain.stdout
        assert "DRIVED_IS_ABSOLUTE: True" in emulated.stdout, emulated.stdout
        assert "ROOTED_IS_ABSOLUTE: False" in emulated.stdout, emulated.stdout

    def test_world_a_arms_against_a_310_shaped_pathlib(self, tmp_path):
        """With the captured accessor patched, world A convicts against a pre-3.11 pathlib."""
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        result = _run(PRELOAD + EMULATE_PY310_PATHLIB + ARM_WORLD_A + body)
        assert "DEFECT_DIED" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_world_a_prime_still_convicts_against_a_310_shaped_pathlib(self, tmp_path):
        """World A-prime still convicts against the same 3.10-shaped pathlib: the pair discriminates."""
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        result = _run(PRELOAD + EMULATE_PY310_PATHLIB + ARM_WORLD_A_PRIME + body)
        assert "DEFECT_DIED" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_the_310_emulation_is_armed_and_not_merely_quiet(self, tmp_path):
        """Arming probe: the 3.10 emulation's rebuilt resolve still RESOLVES, so the pins above mean something."""
        probe = (
            "import os, pathlib\n"
            "print('EMULATION_RESOLVES:', pathlib.Path(pathlib.__file__).resolve() == "
            "pathlib.Path(os.path.normpath(pathlib.__file__)))\n"
            "print('REALPATH_UNTOUCHED:', os.path.realpath is os.path.realpath)\n"
        )
        result = _run(PRELOAD + EMULATE_PY310_PATHLIB + probe)
        assert "EMULATION_RESOLVES: True" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_a_bare_module_patch_does_not_reach_a_pre_captured_accessor(self, tmp_path):
        """The mechanism, measured rather than asserted.

        The probe path is absolute: posixpath.realpath reads the cwd for a relative one whatever is patched.
        """
        world = EMULATE_PY310_PATHLIB + BARE_MODULE_PATCH_ONLY
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        result = _run(PRELOAD + world + body)
        assert "DEFECT_SURVIVED" in result.stdout, f"{result.stdout}\n{result.stderr}"


class TestEverySeedgoModuleImportsWithoutAReadableCwd:
    def test_the_sweeps_world_is_armed_not_merely_reporting(self, world_a_result):
        """The sweep's world is ARMED on every interpreter, not merely reporting PROBE_VACUOUS."""
        assert "PROBE_ARMED" in world_a_result.stdout, world_a_result.stdout

    def test_world_a_imports_every_module(self, world_a_result):
        assert "IMPORTED_ALL" in world_a_result.stdout, world_a_result.stderr

    def test_the_sweeps_world_arms_on_a_310_shaped_pathlib_too(self, world_a_result_on_310_shaped_pathlib):
        """The sweep must measure something on 3.10, not merely pass there."""
        assert "PROBE_ARMED" in world_a_result_on_310_shaped_pathlib.stdout, world_a_result_on_310_shaped_pathlib.stdout

    def test_every_module_imports_on_a_310_shaped_pathlib_too(self, world_a_result_on_310_shaped_pathlib):
        assert "IMPORTED_ALL" in world_a_result_on_310_shaped_pathlib.stdout, (
            world_a_result_on_310_shaped_pathlib.stderr
        )

    def test_world_b_imports_every_module(self, world_b_result):
        assert "IMPORTED_ALL" in world_b_result.stdout, world_b_result.stderr


class TestNoSeedgoModuleResolvesAtImportOutsideTheHelper:
    """The sweep that keeps the thirteenth site from being written quietly."""

    RECORDER = """
import importlib
import pathlib
import sys

_records = []
_real_resolve = pathlib.Path.resolve


def _recording_resolve(self, *a, **kw):
    frame = sys._getframe(1)
    _records.append((frame.f_code.co_filename, frame.f_lineno))
    return _real_resolve(self, *a, **kw)


pathlib.Path.resolve = _recording_resolve

for _name in %(modules)r:
    importlib.import_module(_name)

pathlib.Path.resolve = _real_resolve

for _filename, _lineno in sorted(set(_records)):
    if "%(marker)s" in _filename.replace("\\\\", "/"):
        print("SITE", _filename, _lineno)
print("SWEPT")
"""

    def _sweep(self):
        world = PRELOAD + self.RECORDER % {
            "modules": _seedgo_modules(),
            "marker": "/seedgo/",
        }
        return _run(world)

    def test_the_only_import_time_resolves_left_are_guarded(self):
        result = self._sweep()
        assert "SWEPT" in result.stdout, result.stderr
        sites = [line.split() for line in result.stdout.splitlines() if line.startswith("SITE ")]
        offenders = [
            f"{Path(parts[1]).relative_to(SEEDGO_ROOT)}:{parts[2]}"
            for parts in sites
            if Path(parts[1]).name not in ("module_root.py", "__init__.py")
        ]
        assert offenders == [], f"import-time resolve() outside module_file(): {offenders}"

    def test_the_sweep_actually_visited_the_tree(self):
        """Positive control: the helper's own guarded resolve proves the sweep really imported the tree."""
        result = self._sweep()
        seen = [line for line in result.stdout.splitlines() if line.startswith("SITE ")]
        assert any("module_root.py" in line for line in seen), (
            f"recorder saw no module_file() call — the sweep proves nothing: {result.stdout}"
        )


#: The fence's own probe (tests/test_handlers_fence.py), run as a script so its frames carry the
#: seat's filename.
FENCE_PROBE = SEEDGO_ROOT / "tests" / "support_fence.py"

_RUN_PROBE_AT = """
import runpy
import sys

sys.argv = ["probe", "pkg"]
runpy.run_path(%(seat)r, run_name="__main__")
"""


class TestTheFenceKeepsItsVerdictsWithADeadCwd:
    """Under both worlds the v2 fence still lets kin in and refuses a caller from no branch by name."""

    @staticmethod
    def _verdict(world: str, seat: Path) -> tuple:
        result = _run(PRELOAD + world + PROBE + PROBE_REALPATH + _RUN_PROBE_AT % {"seat": str(seat)})
        lines = result.stdout.strip().splitlines()
        return result, lines[-1] if lines else ""

    @pytest.mark.parametrize("world", [ARM_WORLD_A_PRIME, ARM_WORLD_B], ids=["world_a_prime", "world_b"])
    def test_kin_is_allowed(self, world):
        result, verdict = self._verdict(world, FENCE_PROBE)
        assert "PROBE_ARMED" in result.stdout, result.stdout
        assert verdict == "ALLOWED", result.stdout + result.stderr

    @pytest.mark.parametrize("world", [ARM_WORLD_A_PRIME, ARM_WORLD_B], ids=["world_a_prime", "world_b"])
    def test_an_elsewhere_caller_is_refused(self, world, tmp_path):
        seat = tmp_path / "elsewhere" / "probe.py"
        seat.parent.mkdir()
        seat.write_text(FENCE_PROBE.read_text(encoding="utf-8"), encoding="utf-8")

        result, verdict = self._verdict(world, seat)

        assert "PROBE_ARMED" in result.stdout, result.stdout
        assert verdict == "DENIED Caller branch: unknown", result.stdout + result.stderr
