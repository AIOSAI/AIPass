# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Pins seedgo imports against a working directory the OS cannot read
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""Every seedgo module must import without a readable working directory.

TWO DEFECTS, TWO WORLDS — and one instrument would have proved only half.

WORLD A, the ntpath condition. ``ntpath.realpath`` calls ``os.getcwd()``
UNCONDITIONALLY, before it checks whether the path is even relative, and
``Path.resolve()`` routes through it. So on Windows every module-level
``Path(__file__).resolve()`` is an import-time working-directory read. Twelve
seedgo modules had one. Injected as the CONDITION rather than the platform:
``os.path.realpath`` is wrapped to read ``os.getcwd()`` first, then ``getcwd``
is denied.

WORLD B, the inspect.stack() shape. ``handlers/__init__.py`` called
``inspect.stack()`` before anything else. That builds a FrameInfo per frame ->
``getsourcefile`` -> (only for the frozen importlib frames an import puts on the
stack) ``getmodule``, whose module-scan loop calls ``os.path.realpath`` OUTSIDE
any try. World A CANNOT catch this one: on POSIX the walk raises earlier inside
``getabsfile``, where ``inspect`` catches ``FileNotFoundError`` and returns
None — so a getcwd denial leaves the defective guard green while Windows dies,
because ``ntpath.abspath`` succeeds there and control reaches the unprotected
realpath. World B injects that asymmetry directly: ``abspath`` keeps working,
``os.path.realpath`` raises.

Both were REPRODUCED RED ON LINUX against the pre-fix source before the cure was
written; neither needed a Windows box. Measured on the Windows CI gate
2026-08-31 (@memory's finding for A, @spawn's for B, relayed by @devpulse).

THE INTERPRETER VERSION IS PART OF THE PLATFORM. Round 6, from CI: both worlds
went red on the Python 3.10 leg and neither was a defect in seedgo. 3.10's pathlib
delegates ``Path.resolve()`` to ``os.path.realpath`` through a ``_NormalAccessor``
that CAPTURED its own reference when pathlib was first imported (CPython 3.10
pathlib.py:358, called at :1077). Rebinding ``os.path.realpath`` afterwards
rebinds a name nothing reads again, so world A was inert there — not because the
delegation is missing, which was the first diagnosis and was wrong (@memory read
the source and refuted it). The arming probes refused rather than passing
quietly, which is the instrument discipline working; what they could not do was
still measure the claim. So:

  * world A stays as the faithful ntpath emulation, keyed to a per-version
    cured in four lines: it patches the CAPTURED ACCESSOR too, so it arms on
    every interpreter and needs no version table at all;
  * ``ARM_WORLD_A_PRIME`` patches ``Path.resolve`` itself — the public call the
    defect makes, not the private delegate it routes through this year — so it
    arms on every version, and the module sweep rides it;
  * ``EMULATE_PY310_PATHLIB`` rebuilds the capture so the whole claim is
    falsifiable on THIS machine. A row no local platform can contradict enters
    silently (@ai_mail, round 5), and a CI red is a negative measurement: it
    proves not-armed, never why — which is precisely how the first, wrong
    mechanism survived a careful write-up.

World B needed no change — ``inspect`` calls ``os.path.realpath`` directly on
every version. Its ARMING PROBE was the defect: it asked ``Path.resolve()``, a
question about pathlib, while the world denies realpath. Identical answers on
3.11+ by delegation, divergent on 3.10. Deny and measure the call the DEFECT
makes (@memory's rule, applied to a probe rather than to a world).

Each world carries a POSITIVE CONTROL — a module rebuilt in the defective shape
and imported live, which must die — and a NEGATIVE CONTROL FOR THE POSITIVE
CONTROL: the same module must import cleanly in the healthy world. @spawn's
lesson from the same round: a control that dies for any reason turns every pin
above it vacuously green, so the control needs a control.
"""

import subprocess
import sys
from pathlib import Path

import pytest

SEEDGO_ROOT = Path(__file__).resolve().parents[1]

# Other branches' import-time code is held CONSTANT: imported in the healthy
# world, before any denial. Their dead-cwd cure is their own build (fleet
# rollout in flight, 2026-08-31); this pin measures SEEDGO's sites only.
# TEMPORARY — delete each line as its branch is cured, and the pin gets stricter
# for free. These ten are exactly the foreign entry points seedgo's own source
# names; the rest of each chain rides in behind them.
PRELOAD = """
import aipass.prax  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.prax.apps.handlers.logging.setup  # noqa: F401
import aipass.cli  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401
import aipass.cli.apps.modules.display  # noqa: F401
import aipass.drone.apps.modules  # noqa: F401
import aipass.spawn.apps.modules  # noqa: F401
import aipass.aipass.shared  # noqa: F401
import aipass.aipass.shared.json_handler  # noqa: F401
"""

# The two shapes the cure deleted, rebuilt verbatim. Written to disk and
# imported live rather than reasoned about: the question is whether the world
# still kills the OLD code, and only the old code can answer it.
DEFECT_A_SOURCE = "from pathlib import Path\nX = Path(__file__).resolve()\n"
DEFECT_B_SOURCE = "import inspect\nX = inspect.stack()\n"
#: The second captured route. Path.cwd() reaches _accessor.getcwd before
#: 3.11, never os.getcwd directly, so this defect and DEFECT_A_SOURCE are
#: convicted by DIFFERENT halves of the same world (@skills, round 7).
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

# WORLD A-PRIME, the same condition injected one level UP. World A wraps
# ``os.path.realpath`` because that is what ``ntpath`` does and what Windows
# actually runs, and until the accessor cure above it went inert on 3.10 —
# measured by CI on the 3.10 leg of 8550ed10, where the arming probe reported
# DEFECT_SURVIVED rather than the pin passing quietly (@devpulse, 2026-08-31).
#
# THE SENTENCE THAT USED TO BE HERE WAS WRONG, and it is corrected rather than
# deleted because the wrong mechanism is the lesson. It read: "pathlib only
# delegates to os.path.realpath from 3.11; on 3.10 it carried its own resolve,
# so the wrapper is never reached." 3.10 DOES delegate — through an accessor
# holding a reference captured at import (pathlib.py:358, called at 1077), which
# is why rebinding the module attribute alone changed nothing. @memory read the
# CPython source and refuted it. A CI red is a NEGATIVE measurement: it says
# not-armed and never why, and that gap is exactly where a plausible mechanism
# moves in and settles into a comment.
#
# The interpreter VERSION is part of the platform, exactly as os.name is.
# This world patches ``Path.resolve`` ITSELF — the public call the defect makes,
# not the private delegate it happens to route through this year — so it arms on
# every version by construction. It is the STAND-IN; world A stays because it is
# the faithful ntpath emulation, and the two are pinned to AGREE wherever both
# arm, so the stand-in expires the day they diverge (@memory's licence, ratified
# round 3).
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

# Does THIS interpreter's Path.resolve() reach the denied call for an absolute
# path? 3.11+ routes through os.path.realpath; older ones short-circuit. Pinned
# as a probe with BOTH outcomes reported, never a skipif — the vacuous world is
# named in the output rather than hidden by a skip.
PROBE = """
import pathlib

try:
    pathlib.Path(pathlib.__file__).resolve()
    print("PROBE_VACUOUS")
except OSError:
    print("PROBE_ARMED")
"""

# World B denies ``os.path.realpath``, so the probe for it must MEASURE
# os.path.realpath. The first version used the resolve probe above, which asks a
# question about pathlib instead — true on 3.11+ by delegation, false on 3.10,
# and the world-B pin went red on the 3.10 CI leg for a property world B never
# depended on. @memory's rule, applied to a probe rather than to a world: deny
# and measure the call the DEFECT actually makes. inspect calls
# os.path.realpath directly on every version.
PROBE_REALPATH = """
import os

try:
    os.path.realpath(os.__file__)
    print("PROBE_VACUOUS")
except OSError:
    print("PROBE_ARMED")
"""

# NO VERSION TABLE, and the first cut of this file had one. When the 3.10 CI leg
# went red the diagnosis on hand was "pathlib does not delegate before 3.11", and
# a two-row expectation table keyed on sys.version_info followed from it — every
# row falsifiable, no skipif, all the round-5 discipline correctly applied to a
# premise that was WRONG. @memory fetched CPython 3.10's pathlib and refuted it:
# it delegates, through a captured accessor. The cure is four lines in the world
# above and the table it would have justified does not need to exist.
#
# Keeping the note because the failure is instructive and cheap to repeat: a
# careful table built on an unverified mechanism is more durable than a guess,
# and therefore worse. The mechanism gets read from the source before the
# instrument is keyed to it.


# THE OPPOSITE-PLATFORM LITMUS, as a WORLD so it can ride into any child.
#
# Emulated BY PROPERTY, never by aliasing ntpath. On a posix host
# ntpath.realpath IS ntpath.abspath, so an alias emulates the host wearing an nt
# label and produces a green-looking answer that has silently stopped
# reproducing anything (@flow's M3 trap, failure mode measured by @drone;
# relayed round 7). The property that actually differs is one line:
# ntpath.realpath reads os.getcwd() unconditionally, for absolute paths too
# (ntpath.py:678), where posixpath reads it only for relative ones.
#
# @drone's addendum is why this is a TEST and not a one-time check: a pin that
# reads a value back can be measuring the host, so the litmus lives BESIDE the
# pin rather than in a commit message about a day someone once ran it.
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

# EQUIVALENT MUTANT, recorded so nobody spends the evening on it twice. Binding
# os.getcwd to something harmless inside EMULATE_NT_REALPATH survives every pin
# — because both worlds above rebind os.getcwd to a denier as their LAST line,
# and the emulation is concatenated FIRST. It is overwritten before anything
# runs, so the mutation has no behaviour to change. Run round 7, M5.


# A HOST THAT IS ALREADY 3.10-SHAPED, so the round-8 red is falsifiable HERE.
#
# The emulation below exists to give a 3.11+ host the pre-3.11 shape. On CI's
# real 3.10 leg the host ALREADY had it - and the emulation replaced a
# fully-featured accessor with a two-method stand-in, so pathlib's own API lost
# the methods it routes through and every module import died on
# `AttributeError: '_NormalAccessor' object has no attribute 'mkdir'`.
#
# Emulated BY PROPERTY, exactly as the nt world is: the discriminating fact is
# that a pre-3.11 pathlib ROUTES THROUGH the accessor (mkdir at pathlib.py:1175
# is `self._accessor.mkdir(self, mode)`), not merely that the attribute exists.
# A host that only carries the attribute is not the shape - the first version of
# this reproduction did exactly that and both arms came back green, which is the
# alias trap one dimension over: an emulation that quietly agrees with its host
# is indistinguishable from a cure.
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


#: A host shaped like a real pre-3.11 interpreter: an accessor that pathlib
#: ROUTES stat through, which is what made the round-9 3.10 red possible and
#: what no amount of 3.12 testing could produce. Kept so the red is falsifiable
#: here forever rather than on a leg nobody runs locally.
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

#: Make this child a host with NO accessor, whatever interpreter it is running
#: on. Round 9's second red: `test_the_emulation_still_TAKES_on_a_host_without
#: _one` asserted ACCESSOR_EMULATED unconditionally, which is only true where
#: the host has no accessor - a 3.12 fact, and on the real 3.10 leg the host
#: correctly reported ACCESSOR_NATIVE and the pin died for being right.
#:
#: Emulating the ABSENCE is what makes both arms reachable on every
#: interpreter, rather than each leg testing whichever arm it happens to have.
REMOVE_ANY_NATIVE_ACCESSOR = """
import pathlib

if hasattr(pathlib, "_NormalAccessor"):
    del pathlib._NormalAccessor
"""


# A 3.10-SHAPED pathlib, so the accessor claim is falsifiable HERE.
#
# @ai_mail's round-5 finding, one dimension over: a table row no local platform
# can contradict ENTERS SILENTLY. "3.10 cannot arm world A" arrived as a CI red
# and would otherwise sit in this file unchallenged by every local run, which is
# the original defect's shape wearing a version number.
#
# So the 3.10 CALL CHAIN is emulated rather than the version asserted: resolve()
# is rebuilt to read the cwd itself and normalise without ever touching
# os.path.realpath, which is what pathlib did before 3.11. Under it world A must
# go inert and world A-prime must still convict — the same discrimination the
# 3.10 CI leg reported, reproduced on 3.12.
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
    """Every importable module under seedgo/apps, enumerated live.

    Enumerated in the PARENT and injected, so a module added tomorrow is covered
    without anyone remembering to list it — and so the child never needs a
    directory walk in a world where the filesystem is being denied.
    """
    modules = []
    for path in sorted(SEEDGO_ROOT.glob("apps/**/*.py")):
        parts = list(path.relative_to(SEEDGO_ROOT).parts)
        parts = parts[:-1] if parts[-1] == "__init__.py" else parts[:-1] + [parts[-1][:-3]]
        modules.append("aipass.seedgo." + ".".join(parts) if parts else "aipass.seedgo")
    return modules


def _run(world: str):
    """Run a world in a child process, fed on stdin.

    stdin, not a script file: code read from stdin has co_filename ``<stdin>``,
    which the handlers guard skips as a pseudo-file. A real script path on disk
    would be a caller OUTSIDE the branch and the guard would refuse the import —
    a correct refusal that has nothing to do with what this file measures.
    """
    return subprocess.run(
        [sys.executable, "-"],
        input=world,
        capture_output=True,
        text=True,
        cwd=str(SEEDGO_ROOT.parents[2]),
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
    """The module sweep rides WORLD A-PRIME, not world A.

    The claim being measured is "every seedgo module imports with an unreadable
    cwd", and on 3.10 world A does not arm — so the sweep would have passed
    there against a world that denied nothing. Vacuously green on exactly one
    interpreter, and nothing in the output would have said so.
    """
    return _run(PRELOAD + ARM_WORLD_A_PRIME + PROBE + _import_every_module_body())


@pytest.fixture(scope="module")
def world_a_result_on_310_shaped_pathlib():
    """The same sweep on the interpreter shape this machine does not have.

    Closes a mutant that survived the first run: swapping the sweep back to the
    faithful world A changed nothing on 3.12, because there both worlds arm. It
    is only on 3.10 that the choice decides whether the sweep measures anything
    at all — so the 3.10 shape is emulated and the sweep run against it, and the
    mutant now dies here.
    """
    return _run(PRELOAD + EMULATE_PY310_PATHLIB + ARM_WORLD_A_PRIME + PROBE + _import_every_module_body())


@pytest.fixture(scope="module")
def world_b_result():
    return _run(PRELOAD + ARM_WORLD_B + _import_every_module_body())


#: The three answers the nt arming probe can honestly give, kept as a plain
#: judgement over measured values so every row is reachable on any host
#: (@commons' judgement/world separation, round 5).
ALIAS_DISCRIMINATION_LIVE = "ARMED_AND_DISCRIMINATING"
ALIAS_DISCRIMINATION_UNFALSIFIABLE = "ARMED_BUT_INDISTINGUISHABLE_FROM_AN_ALIAS"
EMULATION_NOT_ARMED = "NOT_ARMED"


def _alias_discrimination_verdict(host_reads_cwd: bool, emulated_reads_cwd: bool) -> str:
    """What the nt arming probe can claim, given what it measured.

    THE ROUND-8 RED IS THE SECOND ROW. The probe asserted the HOST does not read
    the cwd for an absolute path — a posixpath fact, written as a portable
    baseline, inside the pin built to catch exactly that species. Windows ran it
    for real and answered True: on nt, ``os.path.realpath`` IS ntpath's, which
    reads ``os.getcwd()`` unconditionally (ntpath.py:678).

    On such a host the emulation cannot be told apart from @flow's M3 alias trap,
    because an alias and the by-property emulation produce the same answer there.
    That row is genuinely unfalsifiable on nt, so it is REPORTED as unfalsifiable
    rather than asserted away — @ai_mail's round-5 rule, one platform over: a row
    no local host can contradict enters silently, so pin the decision instead of
    a guess.

    Args:
        host_reads_cwd: Whether the bare host reads the cwd for an ABSOLUTE path.
        emulated_reads_cwd: The same measurement under the nt emulation.

    Returns:
        One of the three module constants above.
    """
    if not emulated_reads_cwd:
        return EMULATION_NOT_ARMED
    if host_reads_cwd:
        return ALIAS_DISCRIMINATION_UNFALSIFIABLE
    return ALIAS_DISCRIMINATION_LIVE


#: Why the alias trap can or cannot be caught on the interpreter running this.
#: THREE answers, because there turned out to be two different ways of losing it
#: and a verdict that could not tell them apart would hide the more interesting
#: one (@trigger's round-8 line: a kill by string guard is indistinguishable
#: from a kill by measurement in a summary that only counts).
ALIAS_CATCHABLE = "ALIAS_IS_CATCHABLE_HERE"
ALIAS_LOST_TO_PLATFORM = "ALIAS_INDISTINGUISHABLE:the alias IS this host"
ALIAS_LOST_TO_VERSION = "ALIAS_INDISTINGUISHABLE:ntpath no longer calls a rooted literal absolute"


def _alias_catchability(alias_reads_cwd: bool, ntpath_calls_probe_absolute: bool) -> str:
    """Whether @flow's M3 alias trap is detectable here, and if not, why not.

    THE TRAP: emulating nt by ``os.path.realpath = ntpath.realpath`` reproduces
    nothing on a posix host, because off-Windows ``ntpath.realpath`` is just
    ``abspath`` (ntpath.py:564) and an absolute path never reaches ``getcwd``.
    The check that catches it is "the alias did NOT read the cwd".

    ROUND 9 FOUND THE SECOND WAY TO LOSE IT, and it is a VERSION fact, not a
    platform one. ``_abspath_fallback`` consults ``ntpath.isabs``, and through
    3.12 that carried an explicit LEGACY BUG clause making a rooted driveless
    path absolute (ntpath.py:99-102). 3.13 removed it: ``/tmp`` needs a drive or
    a UNC prefix to count. So on 3.13 the alias DOES read the cwd for the probe
    path, and answers exactly as the by-property emulation does.

    Which is my own checker-pack sentence landing in my own file: the platform
    dimension IS the version dimension. The probe was keyed on a fact only one
    leg of the matrix could contradict, and the leg that contradicted it was an
    interpreter, not an operating system.

    Args:
        alias_reads_cwd: Whether an ntpath-aliased realpath reads the cwd for
            the probe path on this host.
        ntpath_calls_probe_absolute: What ``ntpath.isabs`` says about that same
            path - the mechanism, so the verdict names a cause and not a mood.

    Returns:
        One of the three module constants above.
    """
    if not alias_reads_cwd:
        return ALIAS_CATCHABLE
    if ntpath_calls_probe_absolute:
        return ALIAS_LOST_TO_PLATFORM
    return ALIAS_LOST_TO_VERSION


class TestTheInstrumentsCanFire:
    """Positive controls: each world must still kill the code the cure deleted."""

    def test_world_a_kills_a_module_level_resolve(self, tmp_path):
        """Unconditional again, on every interpreter, now that the world patches
        the captured accessor as well as the module attribute."""
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        result = _run(PRELOAD + ARM_WORLD_A + body)
        assert "DEFECT_DIED" in result.stdout, f"world A is not armed: {result.stdout}\n{result.stderr}"

    def test_world_a_prime_kills_a_module_level_resolve_on_every_version(self, tmp_path):
        """The second construction, kept as a cross-check rather than as a
        stand-in: it patches ``Path.resolve`` itself, so it cannot be fooled by
        anything pathlib does internally on any version."""
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        result = _run(PRELOAD + ARM_WORLD_A_PRIME + body)
        assert "DEFECT_DIED" in result.stdout, f"world A-prime is not armed: {result.stdout}\n{result.stderr}"

    def test_the_two_world_a_constructions_agree(self, tmp_path):
        """@memory's licence, ratified round 3: two ways of building one world
        must agree, so a divergence surfaces as a red rather than as one
        instrument quietly becoming the only one."""
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        faithful = _run(PRELOAD + ARM_WORLD_A + body)
        cross_check = _run(PRELOAD + ARM_WORLD_A_PRIME + body)
        assert "DEFECT_DIED" in faithful.stdout, faithful.stdout
        assert "DEFECT_DIED" in cross_check.stdout, cross_check.stdout

    def test_a_getcwd_denial_does_NOT_reach_a_pre_captured_getcwd_accessor(self, tmp_path):
        """The realpath control's sibling, on the route nothing here was driving.

        Before 3.11 ``Path.cwd()`` is ``cls(cls._accessor.getcwd())`` — a
        SEPARATE captured attribute from ``_accessor.realpath``. Rebinding
        ``os.getcwd`` alone therefore cannot be seen from it, exactly as
        rebinding ``os.path.realpath`` could not be seen from the other half.

        Found by @skills, who hit it as a live mutant survivor: deleting their
        world's realpath patch changed nothing, because every pin underneath was
        riding the getcwd half. Arming one route says nothing about the other.
        """
        body = _defect_body(tmp_path, DEFECT_C_SOURCE, "defect_c")
        result = _run(PRELOAD + EMULATE_PY310_PATHLIB + BARE_MODULE_PATCH_ONLY + body)
        assert "DEFECT_SURVIVED" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_world_a_convicts_the_getcwd_route_TOO(self, tmp_path):
        """And the cured world reaches it. Without the second staticmethod line
        this pin is red — which is the whole reason it exists, because the tree
        has seven Path.cwd() sites today and none of them is reached at import.
        The day one is, the world must already have been able to convict it."""
        body = _defect_body(tmp_path, DEFECT_C_SOURCE, "defect_c")
        result = _run(PRELOAD + EMULATE_PY310_PATHLIB + ARM_WORLD_A + body)
        assert "DEFECT_DIED" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_the_emulation_is_INERT_on_a_host_that_already_has_an_accessor(self, tmp_path):
        """The round-8 3.10 red, held closed on this interpreter forever.

        On CI's real 3.10 the host already had the pre-3.11 shape, and the
        emulation replaced a fully-featured accessor with a two-method stub -
        so pathlib lost the methods it routes its own API through and every
        seedgo module import died on `AttributeError: '_NormalAccessor' object
        has no attribute 'mkdir'`. Red for the instrument, not the defect.
        """
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

    def test_the_emulation_still_TAKES_on_a_host_without_one(self, tmp_path):
        """The other half. An emulation that had learned to do nothing would
        satisfy the pin above and quietly take every 3.10 claim in this file
        dark - which is the arming-probe defect wearing a fix's clothes.

        THE ABSENCE IS EMULATED rather than assumed. Round 9's red: this pin
        asserted ACCESSOR_EMULATED unconditionally, which is only true on a host
        that has no accessor - a 3.12 fact. On the real 3.10 leg the emulation
        correctly reported ACCESSOR_NATIVE and the pin died for being right.
        A pin that expects one arm must BUILD the host that produces it, or it
        is testing whichever arm its own interpreter happens to have.
        """
        probe = "print('BODY_RAN')\n"
        result = _run(PRELOAD + REMOVE_ANY_NATIVE_ACCESSOR + EMULATE_PY310_PATHLIB + probe)
        assert "ACCESSOR_EMULATED" in result.stdout, f"{result.stdout}\n{result.stderr}"
        assert "BODY_RAN" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_the_native_host_emulation_ROUTES_and_does_not_merely_declare(self, tmp_path):
        """Arming probe for the reproduction itself.

        My first version of this world only SET pathlib._NormalAccessor. Both
        arms came back green, because on 3.12 nothing reads it - the world
        declared the shape without having it. A host that carries the attribute
        and does not route through it cannot reproduce the red, and an emulation
        that quietly agrees with its host is indistinguishable from a cure.
        """
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

    def test_the_native_world_does_not_DECAPITATE_a_real_pre_311_host(self, tmp_path):
        """The round-9 3.10 red, held closed here forever.

        Round 8 cured EMULATE_PY310_PATHLIB of replacing a real accessor, and I
        then built its reproduction partner with the identical flaw: a
        three-method stand-in installed over CPython 3.10's real _NormalAccessor,
        which routes stat through it. On 3.12 nothing reads the attribute so both
        arms looked right; on the real 3.10 leg every pin riding this world died
        on `AttributeError: '_NativeAccessor' object has no attribute 'stat'`.

        The same defect, one file over, in the world built to reproduce it.
        """
        probe = "import pathlib, tempfile\nd = pathlib.Path(tempfile.mkdtemp())\nprint('IS_DIR:', d.is_dir())\n"
        world = EMULATE_REAL_310_ACCESSOR_HOST + EMULATE_NATIVE_ACCESSOR_HOST
        result = _run(PRELOAD + world + probe)
        assert "NATIVE_HOST_ALREADY" in result.stdout, f"{result.stdout}\n{result.stderr}"
        assert "IS_DIR: True" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_the_SYNTHESISED_accessor_delegates_what_it_does_not_name(self, tmp_path):
        """Belt to the braces above, and the half a no-op guard cannot cover.

        The guard stops the world installing over a real accessor. It does not
        stop the synthetic one being incomplete on a host that genuinely has
        none - so the stand-in delegates every unnamed attribute to the os
        function of the same name. An accessor is a namespace, and a stand-in
        for a namespace that answers three questions is a trap for the fourth.
        """
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

    def test_the_real_310_host_ROUTES_stat_and_does_not_merely_declare_it(self, tmp_path):
        """Arming probe for the round-9 reproduction, for the same reason its
        round-8 sibling needed one: a host that carries the attribute without
        routing through it reproduces nothing, and the pin above would pass
        against a world that never had the shape."""
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

    def test_the_accessor_absence_emulation_actually_REMOVES_it(self, tmp_path):
        """Arming probe for REMOVE_ANY_NATIVE_ACCESSOR. On 3.11+ it is a no-op
        by construction, so without this pin the world could stop working and
        every arm expectation built on it would keep passing here while going
        dark on exactly the leg it exists for."""
        probe = "import pathlib\nprint('HAS_ACCESSOR:', hasattr(pathlib, '_NormalAccessor'))\n"
        before = _run(PRELOAD + EMULATE_REAL_310_ACCESSOR_HOST + probe)
        after = _run(PRELOAD + EMULATE_REAL_310_ACCESSOR_HOST + REMOVE_ANY_NATIVE_ACCESSOR + probe)
        assert "HAS_ACCESSOR: True" in before.stdout, f"{before.stdout}\n{before.stderr}"
        assert "HAS_ACCESSOR: False" in after.stdout, f"{after.stdout}\n{after.stderr}"

    def test_the_native_host_mkdir_honours_parents_and_exist_ok(self, tmp_path):
        """The fidelity of the stand-in, pinned rather than left to run order.

        Without this the gap is only visible when a directory already exists -
        which in a full suite it does and in a single-test run it does not. The
        pin above went red in the suite and green alone, and a mutant deleting
        the exist_ok arm still survived a two-file selection. An emulation is
        only as honest as the behaviour it keeps.
        """
        probe = (
            "import pathlib, tempfile\n"
            "root = pathlib.Path(tempfile.mkdtemp()) / 'a' / 'b'\n"
            "root.mkdir(parents=True, exist_ok=True)\n"
            "root.mkdir(parents=True, exist_ok=True)\n"
            "print('PARENTS_AND_EXIST_OK_HONOURED')\n"
        )
        result = _run(PRELOAD + EMULATE_NATIVE_ACCESSOR_HOST + probe)
        assert "PARENTS_AND_EXIST_OK_HONOURED" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_every_module_imports_on_a_NATIVE_accessor_host_too(self, tmp_path):
        """The failing CI pin's own shape, run under the host that failed it.

        This is the pin the round-8 red actually killed - restated so that the
        3.10 leg's world is reachable from here. If the emulation ever goes back
        to replacing a native accessor, this reds on 3.12 rather than waiting
        for a CI leg nobody runs locally.
        """
        modules = _seedgo_modules()
        assert modules, "no seedgo modules enumerated - this pin would be vacuous"
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

    def test_the_bare_patch_control_holds_on_an_NT_SHAPED_HOST_TOO(self, tmp_path):
        """THE LITMUS, and the pin that would have caught the round-6 red here.

        The control above claims a bare module patch cannot reach a captured
        accessor. That claim must not depend on which platform is running it —
        and until tonight it did: the emulation captured the real
        os.path.realpath, which on Windows reads the cwd unconditionally, so the
        control raised and reported DEFECT_DIED on the runner while passing
        here. Measured on windows-setup, c82c3d34.

        Runs the same world with the nt property emulated. Same verdict, or the
        pin above is a posix fact wearing a portable name.
        """
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        world = EMULATE_NT_REALPATH + EMULATE_PY310_PATHLIB + BARE_MODULE_PATCH_ONLY
        result = _run(PRELOAD + world + body)
        assert "DEFECT_SURVIVED" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_world_a_still_convicts_on_an_NT_SHAPED_HOST(self, tmp_path):
        """The other half. A litmus that only showed the control surviving
        everywhere would be satisfied by a world that denies nothing — so the
        cured world must still ARM under the same emulation, or the pair proves
        only that both are inert."""
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        world = EMULATE_NT_REALPATH + EMULATE_PY310_PATHLIB + ARM_WORLD_A
        result = _run(PRELOAD + world + body)
        assert "DEFECT_DIED" in result.stdout, f"{result.stdout}\n{result.stderr}"

    ABSOLUTE_CWD_PROBE = (
        "import os\n"
        "_abs = os.path.abspath(os.sep)\n"
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
        """Arming probe for the litmus, keyed on what it MEASURED.

        The version this replaces asserted `ABSOLUTE_PATH_READ_CWD: False` for
        the bare host - a posixpath fact written as a portable baseline, in the
        pin whose job is to catch that species. Windows ran it for real on the
        round-8 board and answered True, because on nt os.path.realpath IS
        ntpath's and reads the cwd unconditionally (ntpath.py:678).

        So the baseline is measured rather than assumed, and the probe reports
        WHICH claim it can support: on a posix-shaped host the emulation is
        distinguishable from @flow's M3 alias trap; on an nt-shaped host it is
        not, and saying so is the honest answer rather than a row filled in with
        a guess.
        """
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
            # Recorded, not skipped. The emulated half is still asserted above;
            # what cannot be measured here is only whether an ALIAS would have
            # produced the same answer - which on this host it would.
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
        """Every row runnable here, including the nt one no Linux box can
        produce live. A literal table, so it cannot vanish."""
        assert _alias_discrimination_verdict(host_reads, emulated_reads) == expected

    def test_the_probe_answers_TRUE_on_an_nt_SHAPED_HOST_and_the_pin_survives_it(self, tmp_path):
        """The round-8 red reproduced on Linux, and held closed.

        Running the bare-host measurement under the nt property is what CI did
        for real. The old pin asserted False here and died; this one measures
        True, routes to the unfalsifiable verdict, and still asserts the half it
        can support.
        """
        # ONE application, read twice. Stacking the emulation on itself is not
        # "an nt host with the emulation applied" - it is a wrapper capturing a
        # module name it then rebinds, which recurses until the stack ends. That
        # is @flow's round-7 self-eating emulation in miniature, and it is the
        # reason the nt host is modelled as host == emulated rather than as two
        # layers: on nt the emulation IS the host's own behaviour, which is
        # exactly why the alias row goes unfalsifiable there.
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
        "_abs = os.path.abspath(os.sep)\n"
        "print('NTPATH_CALLS_IT_ABSOLUTE:', ntpath.isabs(_abs))\n"
        "_seen = []\n"
        "_real_getcwd = os.getcwd\n"
        "os.getcwd = lambda: (_seen.append(1), _real_getcwd())[1]\n"
        "os.path.realpath(_abs)\n"
        "print('ALIAS_READ_CWD:', bool(_seen))\n"
    )

    def _measure_alias(self, host: str = "") -> tuple:
        """`(alias_reads_cwd, ntpath_calls_probe_absolute)` on this host."""
        result = _run(PRELOAD + host + self.ALIAS_WORLD + self.ALIAS_PROBE)
        assert "ALIAS_READ_CWD:" in result.stdout, f"{result.stdout}\n{result.stderr}"
        return (
            "ALIAS_READ_CWD: True" in result.stdout,
            "NTPATH_CALLS_IT_ABSOLUTE: True" in result.stdout,
        )

    def test_the_alias_trap_is_caught_or_the_reason_is_named(self, tmp_path):
        """@flow's M3 trap, and what this interpreter can actually say about it.

        The version this replaces asserted the alias does NOT read the cwd -
        true on 3.12 posix and false on two other legs for two different
        reasons. On nt the alias IS the host. On 3.13 ntpath stopped calling a
        rooted driveless path absolute (the LEGACY BUG clause at ntpath.py:99
        is gone), so `_abspath_fallback` consults the cwd for the probe path
        and the alias answers exactly as the real emulation does.

        Measured, then reported. Where the trap is catchable this still catches
        it; where it is not, the verdict names WHICH dimension took it away.
        """
        alias_reads, ntpath_absolute = self._measure_alias()
        verdict = _alias_catchability(alias_reads, ntpath_absolute)
        if verdict == ALIAS_CATCHABLE:
            assert alias_reads is False
        else:
            # Not skipped: the loss is recorded with its mechanism attached, so
            # a future reader sees a measured boundary rather than a gap.
            assert alias_reads is True

    def test_the_alias_IS_catchable_on_a_312_shaped_ntpath(self, tmp_path):
        """The row this file was built on, pinned as a row rather than assumed
        as the world. Green here today; the day the local interpreter drops the
        legacy clause this reds instead of the boundary moving in silence."""
        alias_reads, ntpath_absolute = self._measure_alias()
        if not ntpath_absolute:
            pytest.skip("this interpreter's ntpath already dropped the legacy clause (3.13+)")
        assert _alias_catchability(alias_reads, ntpath_absolute) == ALIAS_CATCHABLE

    def test_the_alias_is_LOST_TO_VERSION_on_a_313_shaped_ntpath(self, tmp_path):
        """The 3.13 red, reproduced here and held closed.

        Emulated BY PROPERTY - ntpath.isabs rewritten to 3.13's rule - not by
        asserting a version number, so the row is falsifiable on this
        interpreter rather than only on the leg that reported it.
        """
        alias_reads, ntpath_absolute = self._measure_alias(self.NTPATH_313_ISABS)
        assert alias_reads is True, "the 3.13 isabs emulation did not change the answer"
        assert ntpath_absolute is False
        assert _alias_catchability(alias_reads, ntpath_absolute) == ALIAS_LOST_TO_VERSION

    @pytest.mark.parametrize(
        "alias_reads,ntpath_absolute,expected",
        [
            (False, True, ALIAS_CATCHABLE),
            (False, False, ALIAS_CATCHABLE),
            (True, True, ALIAS_LOST_TO_PLATFORM),
            (True, False, ALIAS_LOST_TO_VERSION),
        ],
    )
    def test_the_catchability_table_is_reachable_on_any_host(self, alias_reads, ntpath_absolute, expected):
        """Every row runnable anywhere, including the nt one. A literal table,
        so it cannot vanish."""
        assert _alias_catchability(alias_reads, ntpath_absolute) == expected

    def test_the_313_emulation_changes_only_isabs(self, tmp_path):
        """Arming probe for the reproduction. If the emulation ever stops
        taking, the version row above passes for the wrong reason - which is
        the failure mode this whole file exists to refuse."""
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

    def test_world_a_ARMS_against_a_310_shaped_pathlib(self, tmp_path):
        """The cure, measured on the interpreter shape this machine does not
        have. With the captured accessor patched, the faithful world convicts
        against a pre-3.11 pathlib exactly as it does natively — which is what
        removed the need for a version table."""
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        result = _run(PRELOAD + EMULATE_PY310_PATHLIB + ARM_WORLD_A + body)
        assert "DEFECT_DIED" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_world_a_prime_still_convicts_against_a_310_shaped_pathlib(self, tmp_path):
        """The other half, and the whole reason the stand-in exists. Same
        emulated world, opposite verdict — which is what makes the pair a
        discrimination rather than two worlds that happen to agree."""
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        result = _run(PRELOAD + EMULATE_PY310_PATHLIB + ARM_WORLD_A_PRIME + body)
        assert "DEFECT_DIED" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_the_310_emulation_is_armed_and_not_merely_quiet(self, tmp_path):
        """Arming probe for the emulation itself, @commons' species: a world
        spelled so that nothing happens reports exactly what a cured tree
        reports. The rebuilt resolve must still RESOLVE — otherwise the two pins
        above pass because the emulation broke pathlib, not because it moved the
        call."""
        probe = (
            "import os, pathlib\n"
            "print('EMULATION_RESOLVES:', pathlib.Path(pathlib.__file__).resolve() == "
            "pathlib.Path(os.path.normpath(pathlib.__file__)))\n"
            "print('REALPATH_UNTOUCHED:', os.path.realpath is os.path.realpath)\n"
        )
        result = _run(PRELOAD + EMULATE_PY310_PATHLIB + probe)
        assert "EMULATION_RESOLVES: True" in result.stdout, f"{result.stdout}\n{result.stderr}"

    def test_a_bare_module_patch_does_NOT_reach_a_pre_captured_accessor(self, tmp_path):
        """The mechanism, measured rather than asserted.

        Reproduced independently here before rebuilding the world: patching only
        ``os.path.realpath`` cannot be seen through a reference captured at
        class-creation time, which is exactly the state 3.10's pathlib is in
        from the moment it is first imported.

        Note on my own reproduction: the first run of this appeared to REFUTE
        the claim, because the probe path was ``<stdin>`` — relative, and
        ``posixpath.realpath`` reads the cwd for a relative path whatever else
        is patched. An absolute target is load-bearing here.
        """
        world = EMULATE_PY310_PATHLIB + BARE_MODULE_PATCH_ONLY
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        result = _run(PRELOAD + world + body)
        assert "DEFECT_SURVIVED" in result.stdout, f"{result.stdout}\n{result.stderr}"


class TestEverySeedgoModuleImportsWithoutAReadableCwd:
    def test_the_sweeps_world_is_ARMED_not_merely_reporting(self, world_a_result):
        """Strengthened from either-outcome to ARMED, which the stand-in makes
        possible on every interpreter.

        The old form accepted PROBE_VACUOUS and said so out loud — honest, but it
        meant the module sweep below could pass on 3.10 against a world that
        denied nothing, with the report buried in stdout nobody reads. Now that
        the sweep rides world A-prime the world arms everywhere, so a vacuous
        probe is a defect rather than a disclosure.
        """
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
    """The sweep that keeps the thirteenth site from being written quietly.

    Not a grep: the discriminator is REACHED AT IMPORT, and 61 of seedgo's 75
    ``.resolve()`` call sites are call-time. ``Path.resolve`` is wrapped to
    record its caller while the whole tree is imported, so a default argument
    evaluated at import counts and a line inside a function body does not.
    """

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
        """Positive control on the SWEEP: a walk that imported nothing reports
        no offenders and passes forever. The helper's own guarded resolve is the
        witness that the recorder was installed and the tree was really read."""
        result = self._sweep()
        seen = [line for line in result.stdout.splitlines() if line.startswith("SITE ")]
        assert any("module_root.py" in line for line in seen), (
            f"recorder saw no module_file() call — the sweep proves nothing: {result.stdout}"
        )


# ---------------------------------------------------------------------------
# The caller-is-None branch, watched behaviourally as well as structurally
# ---------------------------------------------------------------------------

_DIRECT_CALL_BODY = """
from aipass.seedgo.apps.handlers import _find_real_caller, _guard_branch_access

# ARMING PROBE 2: the branch under test only RUNS when _find_real_caller
# returns None. Fed on stdin every frame is <stdin> or frozen importlib, both
# skipped, so it does. Without this the guard could return for some entirely
# different reason and the pin would report the same green.
print("CALLER_IS_NONE:", _find_real_caller() == (None, None))

_guard_branch_access()
print("GUARD_RETURNED")
"""


class TestTheCallerIsNoneBranchIsReachableByADirectCall:
    """@devpulse relaying @spawn's correction of MY sentence, 2026-08-31.

    I published "the deleted second inspect.stack() walk is unreachable, so only
    an AST ban can watch it". Too strong, and @spawn measured the correction:
    unreachable from IMPORT-shaped pins — apps/__init__ always supplies a real
    on-disk frame — but reachable by calling ``_guard_branch_access()`` DIRECTLY
    from a child fed on stdin, where every frame is a pseudo-file or frozen
    importlib and ``_find_real_caller`` therefore returns None.

    So the branch gets a behavioural pin as well as the structural one. The AST
    ban still earns its place: no subprocess, and it names the defect precisely.
    This one is the sibling that watches the BEHAVIOUR, and the two die to
    different mutations — regrowing the walk kills both, deleting only the AST
    rule leaves this standing.

    The true sentence, for the record: import-shaped pins cannot reach it. Not
    "nothing can".
    """

    @staticmethod
    @pytest.fixture(scope="class", params=["native", "310-shaped"])
    def result(request):
        """Run on BOTH interpreter shapes.

        Parametrised to close a mutant that survived the first run: putting the
        old resolve-shaped probe back changed nothing on 3.12, because
        delegation makes the two probes agree there. Under the 3.10 shape the
        old probe reports VACUOUS and the substitution finally has a
        consequence a local run can see.
        """
        shape = EMULATE_PY310_PATHLIB if request.param == "310-shaped" else ""
        return _run(PRELOAD + shape + ARM_WORLD_B + PROBE_REALPATH + _DIRECT_CALL_BODY)

    def test_the_denial_bites_in_this_child(self, result):
        """Arming probe 1. A world that silently failed to deny anything would
        let a regrown inspect.stack() walk pass this whole class.

        MEASURES os.path.realpath, which is what world B denies and what
        ``inspect`` calls directly on every interpreter. The first version asked
        ``Path.resolve()`` instead — a question about PATHLIB, true on 3.11+
        only by delegation — and went red on the 3.10 CI leg over a property
        world B never depended on. The world was fine; the probe was measuring
        something else (@devpulse relaying the 3.10 leg of 8550ed10).
        """
        assert "PROBE_ARMED" in result.stdout, result.stderr

    def test_the_branch_under_test_actually_runs(self, result):
        """Arming probe 2, and @spawn's rule: a structural claim that read the
        wrong thing reports exactly the same green as a clean tree. If
        _find_real_caller returned a real caller here, the guard would be
        exercising the ALLOW-pytest path instead and proving nothing."""
        assert "CALLER_IS_NONE: True" in result.stdout, result.stdout

    def test_the_OLD_probe_would_have_gone_vacuous_on_a_310_shaped_pathlib(self):
        """Why this class's arming probe had to change, reproduced locally.

        The original probe asked ``Path.resolve()`` — a question about pathlib —
        while world B denies ``os.path.realpath``. On 3.11+ delegation makes the
        two agree and the substitution is invisible; against a 3.10-shaped
        pathlib the old probe reports VACUOUS while the world is fully armed,
        which is the red the 3.10 CI leg produced.

        Pinned so the correction is falsifiable HERE rather than only on the one
        interpreter this machine does not have.
        """
        old_probe = _run(PRELOAD + EMULATE_PY310_PATHLIB + ARM_WORLD_B + PROBE)
        new_probe = _run(PRELOAD + EMULATE_PY310_PATHLIB + ARM_WORLD_B + PROBE_REALPATH)
        assert "PROBE_VACUOUS" in old_probe.stdout, old_probe.stdout
        assert "PROBE_ARMED" in new_probe.stdout, new_probe.stdout

    def test_the_guard_returns_rather_than_dying(self, result):
        """The claim itself. A regrown second walk dies here under the realpath
        denial; the cured plain return survives."""
        assert "GUARD_RETURNED" in result.stdout, result.stderr
        assert result.returncode == 0, result.stderr
