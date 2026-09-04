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
# THE CHILDREN OF THIS FILE RUN WITH THEIR CWD AT THE REPO ROOT (see _run), so
# anything any world here writes to a RELATIVE path lands in the working tree.
# That is not hypothetical: a round-10 sweep instrument installed an nt-shaped
# os.path before the preload, every absolute path in the child came back
# spelled with backslashes, and posix - where a backslash is an ordinary
# filename character - created 45 entries named "\\tmp\\..." at the repo root.
# @spawn and @devpulse both measured them from the outside before I saw them.
#
# The shipped worlds mint nothing (measured: zero new entries across a full
# run). The detector exists because the next world might, and a directory
# quietly appearing in the working tree is exactly the class of thing an
# indiscriminate stage-everything turns into a commit.
CHILD_CWD = SEEDGO_ROOT.parents[2]


def _working_tree_entries(root: Path) -> set:
    """Names directly under `root`, or an empty set if it is not readable.

    Names, not paths: the point is what APPEARED, and a name carrying a
    backslash is the whole reason this exists.
    """
    try:
        return {entry.name for entry in root.iterdir()}
    except OSError:
        return set()


def _litter(before: set, after: set) -> set:
    """What this file's children added to the working tree. A plain function
    over two sets, so both the empty and the convicting case are reachable
    without minting anything."""
    return after - before


@pytest.fixture(scope="module", autouse=True)
def _no_working_tree_litter():
    """Fail the module if its children left anything in the repo root.

    Deliberately does NOT delete what it finds: `drone rm` is the sanctioned
    way to remove anything here, and a detector that tidies up after itself
    destroys the evidence of the world that produced it.
    """
    before = _working_tree_entries(CHILD_CWD)
    yield
    new = _litter(before, _working_tree_entries(CHILD_CWD))
    assert not new, (
        "a world in this file wrote into the working tree - the children run with "
        f"cwd at the repo root, so a relative path lands there: {sorted(new)}"
    )


#: Warmed while the cwd is still readable, so the sweep below convicts SEEDGO's
#: modules rather than the shared infrastructure they pull in. A name belongs
#: here only if something under _seedgo_modules() actually reaches it:
#: aipass.aipass.shared.json_handler was dropped on 2026-09-04 because nothing
#: in this branch imports it (json_handler_check.py holds it as an accept
#: STRING, not an import), and @aipass retires the file under FPLAN-0489.
#: Measured, not assumed - 83 passed, 3 skipped before and after.
PRELOAD = """
from aipass.prax import logger  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.prax.apps.handlers.logging.setup  # noqa: F401
import aipass.cli  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401
import aipass.cli.apps.modules.display  # noqa: F401
import aipass.drone.apps.modules  # noqa: F401
import aipass.spawn.apps.modules  # noqa: F401
import aipass.aipass.shared  # noqa: F401
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

#: An nt-shaped host for the ONE question the alias check turns on: on Windows
#: ``os.path`` IS ``ntpath`` - one module, not two - so aliasing ntpath over
#: os.path changes nothing and no probe can tell the alias from the real thing.
#:
#: Both halves are needed and each was measured: the module IDENTITY (without
#: it the alias is still foreign here) and the unconditional cwd read that a
#: real nt realpath performs (without it the aliased call returns early for an
#: absolute path and the row reads CATCHABLE, which is the Linux answer).
#:
#: The replacement is a SENTINEL that returns its argument - the round-7 rule,
#: because anything it borrowed from posixpath would be behaviour this row does
#: not test, and an emulation friendlier than the thing it stands in for hides
#: the defect.
#: The two halves are named separately because the control below measures each
#: one alone, and because WHICH object each patches is the whole reason this
#: world works where ``EMULATE_NT_REALPATH`` cannot: the alias world's last act
#: is ``os.path.realpath = ntpath.realpath``, so a host that patched
#: ``os.path.realpath`` is overwritten before the probe runs. Patching
#: ``ntpath.realpath`` is what survives being aliased over.
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

#: The MIRROR of the world above, and the reason it exists: a row that wants to
#: exercise both starting dialects cannot get the second one by leaving the host
#: alone. On this box an untouched child starts as posixpath and the nt world
#: supplies the other side - but on a windows runner BOTH children start as
#: ntpath and the pair silently collapses into one arm, which is the same
#: species as an assertion spelling its own host's answer, one level up: not a
#: wrong expectation, a missing second measurement. Forcing each side means the
#: pair is two arms on every host, including ones nobody here runs.
#:
#: Deliberately identity ONLY. Nothing here claims the child is a posix
#: PLATFORM - on nt this makes the chimera in the other direction - and the one
#: row that uses it reads only which way a later break turned.
_POSIX_HOST_MODULE_IDENTITY = """
import os
import posixpath
import sys

os.path = posixpath
sys.modules["os.path"] = posixpath
"""

#: A FLAVOUR THAT IS AN OBJECT, which is what 3.10 and 3.11 actually carry and
#: what made round 10's routing pin red on three legs. Meant to be stacked on
#: EMULATE_PY310_PATHLIB, which redirects resolve through the accessor first -
#: without that, a 3.12 pathlib would ask this object for realpath and the
#: emulation would decapitate the interpreter instead of shaping it.
#:
#: It REFUSES realpath by name. CPython 3.10's _PosixFlavour carries parsing
#: and nothing else, so a stand-in that answered would be friendlier than the
#: thing it stands in for - @spawn's round-10 lesson, applied where it bites.
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

#: A 3.13-SHAPED RESOLVE, built from the round-11 CI evidence rather than from a
#: source line I can read on this box (this machine has only 3.12).
#:
#: WHAT THE EVIDENCE SAYS: on the real 3.13 runner the chimera fails to disarm
#: world A - DEFECT_DIED: FileNotFoundError, verbatim identical to the 3.10 leg
#: (@devpulse, round-11 addendum) - even though 3.13 has no _NormalAccessor and
#: no _flavour, so the captured-accessor mechanism cannot be the reason.
#:
#: The shape that produces that answer is a resolve which reads ``os.path`` AT
#: CALL TIME instead of through a class attribute: pointing os.path at ntpath
#: then MOVES the route rather than breaking it, and the patch rides along. This
#: world installs exactly that and nothing else, so the arm below is a
#: measurement here instead of a prediction about an interpreter I cannot run.
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


#: BREAK THE ROUTING IDENTITY, TOWARD THE DIALECT THIS HOST IS NOT.
#:
#: The fixed chimera - always point os.path at ntpath - is a NO-OP on nt, where
#: os.path already IS ntpath. Windows measured that: the probe honestly reported
#: the identity intact and the control convicted it for reading the world
#: correctly. It is the third reason the round-11 disarm control already names,
#: arriving one control over (@devpulse, round-12 addendum).
#:
#: So the direction is chosen from what the host IS, and the child says which
#: way it went - a break that cannot happen must not look like a break that
#: found nothing.
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
    """Which dialect the break must land on, given where the child started.

    The whole content of the addendum in one function: break TOWARD the dialect
    the host is not. Both rows are reachable from any host - this one by
    reading, the other by installing the nt-identity emulation first - so
    neither arm waits on a runner nobody here has.
    """
    return "posixpath" if started_as == "ntpath" else "ntpath"


def _break_can_move_the_identity(flavour_is_a_dialect_module: bool) -> bool:
    """Whether `flavour is os.path` can move at all on this host.

    The reading compares pathlib's routing attribute against os.path. Moving
    os.path between the two dialect modules changes that comparison only if the
    routing attribute IS one of them. On 3.10 and 3.11 it is a _PosixFlavour
    OBJECT and on 3.13 there is no _flavour at all, so the reading is False
    before the break and False after it - not because the break failed, but
    because the question does not apply. Round 12's own lesson, one world
    later: a row that cannot be asked on a host must report, not assert.
    """
    return flavour_is_a_dialect_module


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

#: THE 3.11 HYBRID, which is neither of the two shapes this file had names for.
#:
#: 3.11 removed the captured accessor (like 3.12+) while its flavour is still an
#: OBJECT (like 3.10), and the route is the call-time module read. Round 11's
#: routing table read those two attributes as proxies for the route and had no
#: row for the combination, so a shipped interpreter came back as
#: NO_ROUTE_EXPLAINS_THIS_HOST - a table reporting "not in my table" as a
#: verdict (@devpulse, round 12).
#:
#: Built by composition rather than by a new emulation: the object flavour and
#: the call-time resolve are already here, and each stands down where the host
#: already has that half, so this constant is the shape and not a second
#: implementation of it.
#:
#: The accessor removal is the third piece and it is not optional. On a host
#: that HAS a captured accessor - 3.10, or any child where an emulation put one
#: there - the other two halves cannot produce the hybrid, and the row asserting
#: "no accessor" would be red on the very interpreter it is meant to speak
#: about. Every half of this host is constructed rather than inherited.
EMULATE_311_HYBRID_HOST = REMOVE_ANY_NATIVE_ACCESSOR + EMULATE_OBJECT_FLAVOUR_HOST + EMULATE_313_RESOLVE_READS_OS_PATH


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
        # Dot-directories are not packages. .archive/ holds verbatim disposal
        # copies (DPLAN-0325) and its dotted name is not even valid syntax —
        # `aipass.seedgo.apps.handlers.json..archive.json_handler` took the
        # whole sweep down with a SyntaxError before this line existed, which
        # made six passing tests report nothing rather than fail honestly.
        if any(part.startswith(".") or part == "__pycache__" for part in parts):
            continue
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
ALIAS_LOST_TO_BEHAVIOUR = "ALIAS_INDISTINGUISHABLE:a foreign ntpath read the cwd anyway"


CONTROL_EXPECTS_DEATH = "WORLD_A_STILL_CONVICTS"
CONTROL_EXPECTS_SURVIVAL = "WORLD_A_IS_DISARMED"


def _chimera_control_expectation(reaches_under_chimera: bool, has_captured_accessor: bool) -> str:
    """What breaking the ``os.path`` identity should do to world A here.

    Three interpreters answered this differently and each one taught the same
    lesson later than the last. Pre-3.11 the captured accessor is a second
    route the break cannot touch. On 3.13 the break MOVES the route instead of
    severing it, because resolve reads ``os.path`` at call time - so the
    world's own patch rides along. Only where neither holds does the control
    actually disarm anything.

    Both facts are measured in the same child that runs the control, so this
    is a judgement over readings rather than a table keyed on a version or an
    operating system - the shape that has been wrong three rounds running.

    Args:
        reaches_under_chimera: Whether a patch on ``os.path.realpath`` still
            reaches ``resolve`` once ``os.path`` points at ntpath.
        has_captured_accessor: Whether pathlib holds a pre-3.11 accessor.

    Returns:
        One of the two module constants above.
    """
    if reaches_under_chimera or has_captured_accessor:
        return CONTROL_EXPECTS_DEATH
    return CONTROL_EXPECTS_SURVIVAL


ROUTE_VIA_MODULE = "A_MODULE_PATCH_REACHES_RESOLVE"
ROUTE_VIA_ACCESSOR = "A_MODULE_PATCH_IS_NOT_READ_AGAIN:pathlib captured its own copy"
ROUTE_UNEXPLAINED = "NO_ROUTE_EXPLAINS_THIS_HOST"


def _module_patch_route(module_patch_reaches_resolve: bool, has_captured_accessor: bool) -> str:
    """Whether rebinding ``os.path.realpath`` can reach ``Path.resolve`` here.

    Every arming world in this file rests on this and round 10 wrote the
    3.12-shaped SPELLING of it down as a pin: "Path's routing module IS
    os.path". CI answered honestly on 3.10 and 3.11 - there ``_flavour`` is a
    ``_PosixFlavour`` OBJECT and the probe reported False - and the pin that
    existed to document the assumption had the assumption in its assertion.

    The fact that decides the route is not the flavour's spelling but whether
    pathlib holds a CAPTURED COPY. Before 3.11 ``_NormalAccessor`` took
    ``realpath = staticmethod(os.path.realpath)`` at class creation and
    ``resolve`` called ``self._accessor.realpath`` (pathlib.py:358 and 1077),
    so rebinding the module attribute rebinds a name nothing reads again -
    which is why ARM_WORLD_A patches the accessor TOO, and why measuring it
    here is measuring the thing the worlds actually depend on.

    ROUND 12 TOOK THE PREDICTION OUT OF IT. The round-11 version read the route
    off two attribute proxies - accessor present, flavour is os.path - and 3.11
    is the HYBRID neither proxy can express: the captured accessor is gone
    (like 3.12+) while the flavour is still an OBJECT (like 3.10), and the
    route there is the call-time module read. The table answered
    NO_ROUTE_EXPLAINS_THIS_HOST for a shipped interpreter, which is a table
    saying "not in my table" and calling it a verdict.

    So the route is now the MEASUREMENT, and the accessor only EXPLAINS a route
    that was not taken. UNEXPLAINED means measured-and-genuinely-unexplained:
    nothing reached resolve and no captured copy accounts for it. The same
    end-of-arms cure the disarm control got in round 11, applied one test over -
    @devpulse pointed at exactly that asymmetry.

    Args:
        module_patch_reaches_resolve: Whether a spy installed on
            ``os.path.realpath`` is actually reached by ``Path.resolve`` here.
        has_captured_accessor: Whether ``pathlib._NormalAccessor`` exists - the
            only thing in this file that EXPLAINS a module patch failing to
            reach.

    Returns:
        One of the three module constants above.
    """
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

    ROUND 10 SPLIT THE PLATFORM ARM FROM WHAT IT WAS INFERRED FROM. The two
    argument version read the platform off ``ntpath_calls_probe_absolute``,
    which is a proxy and not the thing: a verdict that SAYS "the alias IS this
    host" while never having measured identity claims a fact it does not hold.
    A sweep of this file under a 3.13-shaped ntpath convicted it - on a real
    3.13 leg the two dimensions collide and the message names the wrong one.

    So the platform arm now rests on ``os.path is ntpath``, measured, and the
    fourth verdict exists for the case the old ordering swallowed: a FOREIGN
    ntpath that reads the cwd anyway. That is what an nt realpath does and what
    this file's own nt emulation installs, and calling it "the alias IS this
    host" would have been an emulation reported as a platform.

    Args:
        alias_reads_cwd: Whether an ntpath-aliased realpath reads the cwd for
            the probe path on this host.
        ntpath_calls_probe_absolute: What ``ntpath.isabs`` says about that same
            path - the version dimension, so the verdict names a cause.
        alias_is_the_host: Whether ``os.path`` already IS ``ntpath`` - the
            platform dimension, and the only fact that supports the word
            "host" in a verdict.

    Returns:
        One of the four module constants above.
    """
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
        # THE SECOND SITE OF THE ROUND-10 SPECIES, found by sweeping this file
        # rather than by reading it. `os.path.abspath(os.sep)` builds the
        # argument out of the host being measured, so the row asks a different
        # question per platform - the exact defect that took the alias probe
        # down on the round-10 board, still living one probe over.
        #
        # '//x' is absolute under EVERY rule this file can meet: posixpath,
        # 3.12 ntpath, and 3.13 ntpath (which reads it as the UNC form). It is
        # DELIBERATELY not the alias probe's '/x' - that one has to be the
        # rooted driveless shape whose absoluteness 3.13 changed, because
        # measuring the version dimension is its whole job. Two literals, two
        # jobs; making them agree would take one of the rows dark.
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
        # A DIALECT-NEUTRAL LITERAL, written once and never derived from the
        # host. `os.path.abspath(os.sep)` was the round-9 spelling and it is a
        # different SHAPE per platform: '/' on posix (rooted, driveless - the
        # exact shape 3.13's isabs change is about) and 'D:\\' on nt, which is
        # DRIVE-rooted and absolute under both isabs rules. So the row asked a
        # different question on Windows and answered it correctly. An
        # instrument's inputs are behaviour too (@flow, round 8), and a probe
        # must not build its argument out of the host it is measuring.
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
        """`(alias_reads_cwd, ntpath_calls_probe_absolute, alias_is_the_host)`.

        The third value is the variable that actually DECIDES whether this
        check can discriminate at all: where ``os.path`` already IS ``ntpath``,
        the alias world is a no-op and no probe can tell an alias from the
        real thing. Measured rather than inferred from ``os.name``, because the
        question is about module identity and not about a platform label
        (@ai_mail's round-5 rule: key the table on what decides).
        """
        result = _run(PRELOAD + host + self.ALIAS_WORLD + self.ALIAS_PROBE)
        assert "ALIAS_READ_CWD:" in result.stdout, f"{result.stdout}\n{result.stderr}"
        assert "ALIAS_IS_THE_HOST:" in result.stdout, f"{result.stdout}\n{result.stderr}"
        return (
            "ALIAS_READ_CWD: True" in result.stdout,
            "NTPATH_CALLS_IT_ABSOLUTE: True" in result.stdout,
            "ALIAS_IS_THE_HOST: True" in result.stdout,
        )

    def test_the_alias_trap_is_caught_or_the_reason_is_named(self, tmp_path):
        """@flow's M3 trap, and what this interpreter can actually say about it.

        Measured, then reported. Where the trap is catchable this still catches
        it; where it is not, the verdict names WHICH dimension took it away.
        """
        alias_reads, ntpath_absolute, alias_is_the_host = self._measure_alias()
        verdict = _alias_catchability(alias_reads, ntpath_absolute, alias_is_the_host)
        if verdict == ALIAS_CATCHABLE:
            assert alias_reads is False
        else:
            # Not skipped: the loss is recorded with its mechanism attached, so
            # a future reader sees a measured boundary rather than a gap.
            assert alias_reads is True

    def test_the_catchability_matches_WHAT_THE_HOST_IS(self, tmp_path):
        """BOTH ARMS ASSERTED, so this row measures on every operating system.

        The round-9 version asserted ALIAS_CATCHABLE unconditionally and met a
        real nt host on the round-10 board. The machinery answered honestly -
        ALIAS_INDISTINGUISHABLE: the alias IS this host, the third verdict
        firing exactly as designed - and the ASSERTION refused the honest
        answer. Written on Linux, where a 3.12-shaped ntpath is foreign and
        therefore catchable; shaped like the host it was written on.

        @flow's one-dimension law in its assertion form: a host that already IS
        the faked dimension cannot distinguish it. So the expectation is now
        derived from the measured identity - is os.path already ntpath - and
        both arms are live measurements rather than one arm and one skip.

        WHICH DIMENSION EACH ARM RESTS ON, because the runner is nt AND 3.12
        and only one of those decides this row: the arm below rests on module
        IDENTITY (platform), not on the isabs rule (version). The version
        dimension is the subject of the next test, and on a host where the
        alias is the host it cannot be isolated at all.
        """
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
            # THE THIRD HOST, and the reason this row has three arms instead of
            # two. A 3.13 interpreter on posix is neither of the above: the
            # alias is foreign AND it reads the cwd, because ntpath stopped
            # calling a rooted driveless literal absolute. Written with two
            # arms this test was red on CI's own 3.13 leg - found by sweeping
            # the file under a 3.13-shaped ntpath, not by reading it.
            assert verdict == ALIAS_LOST_TO_VERSION, (
                "ntpath does not call the probe absolute here, so a foreign alias "
                f"reads the cwd for the version reason - measured {verdict}"
            )

    def test_the_alias_is_LOST_TO_VERSION_on_a_313_shaped_ntpath(self, tmp_path):
        """The 3.13 row, emulated by property and stated with its dimension.

        THE ROUND-9 VERSION HAD TWO DEFECTS and the Windows leg found both.
        It asserted `ntpath_absolute is False`, and it built its probe path as
        `os.path.abspath(os.sep)` - which is '/' on posix and 'D:\\' on nt. A
        drive-rooted path is absolute under BOTH isabs rules, so on Windows the
        emulation was armed and the probe simply asked a different question.
        The input, not the world, was host-shaped.

        The literal is dialect-neutral now. What remains genuinely
        unmeasurable on an nt host is the ISOLATION: where os.path IS ntpath,
        the platform has already made the alias indistinguishable, so no
        version emulation can produce a version-only loss. That is stated
        rather than skipped past - the cross term devpulse warned about, and
        the asymmetry is real: the version row needs a host where the alias is
        foreign; the platform row above needs no such thing.
        """
        _, bare_ntpath_absolute, _ = self._measure_alias()
        alias_reads, ntpath_absolute, alias_is_the_host = self._measure_alias(self.NTPATH_313_ISABS)
        if bare_ntpath_absolute:
            print("ISABS_313: INSTALLED")
        else:
            # NATIVE. The interpreter beneath is already 3.13-shaped, so the
            # emulation replaced one rule with the same rule and the row below
            # is a measurement of the host, not of the emulation. It still
            # holds; what it cannot say is that the emulation caused it.
            print("ISABS_313: NATIVE")
        assert ntpath_absolute is False, (
            "the 3.13 isabs emulation did not take: a rooted driveless literal is still "
            "reported absolute, so this row would pass for the wrong reason"
        )
        assert alias_reads is True, "the alias did not read the cwd under the 3.13 shape"
        verdict = _alias_catchability(alias_reads, ntpath_absolute, alias_is_the_host)
        if alias_is_the_host:
            # UNVERIFIABLE HERE, BY NAME - and the verdict says so itself now.
            # Where os.path IS ntpath the platform has already made the alias
            # indistinguishable, so no version emulation can produce a
            # version-only loss and the judgement reports the deeper reason.
            # The round-10 version asserted LOST_TO_VERSION on both arms, which
            # was the same species one turn later: an expectation written on
            # the host it was written on. Found by sweeping the file under an
            # nt-identity host rather than by reading it.
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
        # 3.13 renamed _flavour to parser (pathlib._local). Both names asked
        # for, and which one answered is printed, because a probe that finds
        # neither must say so rather than report a comfortable False.
        "_name = 'NONE'\n"
        "_mod = None\n"
        "for _attr in ('_flavour', 'parser'):\n"
        "    _found = getattr(type(_p), _attr, None)\n"
        "    if _found is not None:\n"
        "        _name, _mod = _attr, _found\n"
        "        break\n"
        "print('FLAVOUR_ATTR:', _name)\n"
        "print('FLAVOUR_IS_OS_PATH:', _mod is os.path)\n"
        # Whether the routing attribute is a DIALECT MODULE at all, which is
        # what decides if the line above can move when os.path does. Additive:
        # every existing row reads its own line and is untouched.
        "import ntpath, posixpath\n"
        "print('FLAVOUR_IS_A_DIALECT_MODULE:', _mod is posixpath or _mod is ntpath)\n"
        "print('HAS_ACCESSOR:', hasattr(pathlib, '_NormalAccessor'))\n"
        # THE ROUTE ITSELF, measured rather than inferred from either name
        # above. A spy on the module attribute, then one resolve of a literal
        # absolute path: if the spy is reached, a module patch is a route here.
        "_seen = []\n"
        "_real_for_route = os.path.realpath\n"
        "def _route_spy(path, *a, **kw):\n"
        "    _seen.append(1)\n"
        "    return _real_for_route(path, *a, **kw)\n"
        "os.path.realpath = _route_spy\n"
        "try:\n"
        "    pathlib.Path('//x').resolve()\n"
        "except OSError as _exc:\n"
        # The measurement is whether the spy FIRED, not whether the call
        # succeeded - a host that refuses to resolve the literal still answers
        # the routing question, and a bare probe would print nothing at all.
        "    print('ROUTE_RESOLVE_RAISED:', type(_exc).__name__)\n"
        "os.path.realpath = _real_for_route\n"
        "print('MODULE_PATCH_REACHES_RESOLVE:', bool(_seen))\n"
    )

    def _measure_route_and_report(self, host: str = "") -> tuple:
        """`((has_accessor, flavour_is_os_path, reaches), stdout)`.

        The raw stdout comes back because the worlds ANNOUNCE which arm they
        took, and a caller that rides a stand-down has to assert against the
        arm that actually ran rather than the one it hoped for.
        """
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
        """The child's own answer for `prefix`, or a failure naming the child.

        A row that greps for a whole literal line cannot tell "the child said
        something else" from "the child never spoke", and the second is a
        harness crash wearing the instrument's message - round 8's species.
        """
        for line in result.stdout.splitlines():
            if line.startswith(prefix):
                return line[len(prefix) :].strip()
        raise AssertionError(f"the child never printed {prefix!r}: {result.stdout}\n{result.stderr}")

    def _measure_route(self, host: str = "") -> tuple:
        """`(has_accessor, flavour_is_os_path, module_patch_reaches_resolve)`."""
        readings, _ = self._measure_route_and_report(host)
        return readings

    def test_the_arming_worlds_patch_the_module_pathlib_ROUTES_THROUGH(self, tmp_path):
        """The invariant every ``os.path.realpath`` world here rests on, keyed
        on the fact that decides it instead of on a 3.12 spelling.

        THE ROUND-10 VERSION ASSERTED `FLAVOUR_IS_OS_PATH: True` ON EVERY HOST
        and CI answered honestly on 3.10, 3.11 and windows: there ``_flavour``
        is a ``_PosixFlavour`` OBJECT, so the probe said False and the pin
        written to document the assumption had the assumption inside its own
        assertion. @devpulse read it off the board and named it.

        What the worlds actually depend on is whether a module patch REACHES
        resolve, so that is what is measured: a spy on os.path.realpath, one
        resolve, did the spy fire. Round 11 measured it and then compared it
        against a prediction from two attribute proxies; 3.11 is the hybrid
        neither proxy can express - accessor gone, flavour still an object,
        route present - and the prediction answered "not in my table" for a
        shipped interpreter. The measurement is the verdict now, and the
        accessor is only asked to EXPLAIN a route that was not taken.

        Both arms run on this interpreter: the bare host reaches,
        EMULATE_PY310_PATHLIB does not, and EMULATE_311_HYBRID_HOST presents
        the shape that convicted the round-11 table.
        """
        has_accessor, flavour_is_os_path, reaches = self._measure_route()
        expected = _module_patch_route(reaches, has_accessor)
        assert expected != ROUTE_UNEXPLAINED, (
            "nothing reached resolve through os.path and no captured accessor "
            "explains why, so every world here that patches os.path.realpath is "
            f"inert (flavour is os.path: {flavour_is_os_path})"
        )
        # NO SECOND ASSERTION FOR THE MISSED-ROUTE CASE. It read "if the patch
        # did not reach, there must be an accessor", which is the UNEXPLAINED
        # arm above said twice - a mutant deleting it survived every pin here,
        # and a restatement no mutant can kill is decoration that makes the
        # file look better covered than it is.
        # THE CONTROL FOR THE CONTROL. Without it every value above can be
        # hardcoded to its own expected answer and nothing notices - measured
        # in round 10: a probe printing a literal True survived every pin here.
        #
        # It breaks the identity TOWARD the dialect this host is not, because
        # the fixed always-ntpath break is a no-op on nt and windows-setup
        # convicted the probe for honestly reporting that nothing had changed.
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
        # THE REACH HALF IS NOT ASSERTED HERE, and that is a measured decision.
        # It reads False on this interpreter and TRUE on 3.13, whose resolve
        # follows os.path at call time - the chimera moves that route instead of
        # severing it. Demanding False was a 3.12 fact and a sweep under a
        # 3.13-shaped resolve convicted it. The reading is still pinned
        # host-independently one row down, where the pre-3.11 shape must drive
        # it False on any interpreter.
        assert broken_accessor is has_accessor, (
            "the chimera changed whether this host has a captured accessor, which it has no business touching"
        )

    def test_the_pre_311_shape_answers_the_OTHER_arm_from_here(self, tmp_path):
        """The arm CI runs and this interpreter cannot reach on its own.

        Under the pre-3.11 shape the module patch must STOP reaching resolve -
        that is the whole reason ARM_WORLD_A patches the accessor as well, and
        it is the answer 3.10 and 3.11 gave the round-10 pin. Measured here so
        the judgement above is exercised on both of its arms from 3.12, the
        same way the nt-identity world made the platform arm reachable from
        Linux.
        """
        has_accessor, flavour_is_os_path, reaches = self._measure_route(EMULATE_PY310_PATHLIB)
        assert has_accessor is True, "the pre-3.11 emulation did not install an accessor"
        assert _module_patch_route(reaches, has_accessor) == ROUTE_VIA_ACCESSOR
        assert reaches is False, (
            "a module patch still reaches resolve under the pre-3.11 shape, so the "
            "captured-accessor half of every world here is measuring nothing"
        )

    def test_the_identity_break_goes_TOWARD_the_dialect_the_host_is_not(self, tmp_path):
        """Round 12's windows red, reproduced on Linux and held closed.

        The fixed break - always point os.path at ntpath - changes nothing on
        nt, where os.path already IS ntpath. Windows-setup measured the probe
        honestly reporting the identity intact and the control convicted it for
        reading the world correctly: the same third reason the disarm control
        already carries, one control over.

        Both directions are exercised from here, and NEITHER is spelled. Each
        child reports where it STARTED and where it went, and `_break_direction`
        says which pairing is correct - so the row reads the same on a posix
        box, on a windows runner, and under the nt-identity emulation. The
        round-12 shape it replaces asserted `IDENTITY_BROKEN_TOWARD: ntpath`
        for the untouched host, which is this box's answer and nothing more.

        Both starting dialects are CONSTRUCTED rather than borrowed: leaving
        one child untouched works here and collapses the pair on a windows
        runner, where an untouched child and the nt-identity emulation start
        the same way and a world that never turns around satisfies both rows.
        A third assertion pins that the two arms really are two.
        """
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
        # AND THE TWO ARMS MUST BE DIFFERENT ARMS. Both rows above pass for a
        # world that never turns around if both children happen to start the
        # same way, so the second host is required to start somewhere else.
        as_posix = _run(PRELOAD + _POSIX_HOST_MODULE_IDENTITY + BREAK_THE_ROUTING_IDENTITY + "print('DONE')\n")
        as_nt = _run(PRELOAD + _NT_HOST_MODULE_IDENTITY + BREAK_THE_ROUTING_IDENTITY + "print('DONE')\n")
        assert self._read_line(as_posix, "IDENTITY_STARTED_AS:") != self._read_line(as_nt, "IDENTITY_STARTED_AS:"), (
            "both children started as the same dialect, so the turn-around was "
            f"never exercised: {as_posix.stdout}\n{as_nt.stdout}"
        )

    def test_the_break_actually_MOVES_the_identity_from_either_side(self, tmp_path):
        """The reading, not just the announcement.

        A world that printed the right direction and changed nothing would pass
        the row above. So the flavour-identity reading is measured on both
        sides of the break, from a posix-shaped host and from an nt-shaped one.

        What is asserted is the MOVEMENT, not the destination. On this host the
        break moves the reading True -> False. On the nt-identity emulation it
        moves False -> True, and that is not a failure: that world is the
        CHIMERA - os.path already points at ntpath while pathlib's flavour is
        still posixpath - so breaking away from ntpath points os.path back AT
        the flavour and re-aligns them. A real nt host, whose flavour is ntpath
        too, would read True and move to False like this one does. The
        emulation cannot express that difference, so the row refuses to spell
        either destination and reads the only thing every host agrees on: the
        identity is not where it was.

        And where it CANNOT move, it says so. 3.10 and 3.11 carry a
        _PosixFlavour object, 3.13 carries no _flavour at all, and on all three
        `flavour is os.path` is False before the break and False after it -
        the question does not apply, so the row reports the dead reading rather
        than convicting the break for a property of the interpreter.
        """
        for label, host in (
            ("this host, untouched", ""),
            ("the nt-identity emulation", _NT_HOST_MODULE_IDENTITY),
            # THE THIRD ARM IS THE STAND-DOWN, and it is here rather than in a
            # row of its own because two mutants proved it unreachable
            # otherwise: deleting the stand-down, and forcing the probe's
            # dialect-module line to True, both survived every pin in the file
            # while this box's flavour was a module. 3.10, 3.11 and 3.13 are
            # this arm on CI; an object flavour is this arm from here.
            # The HYBRID rather than the bare object-flavour world: on 3.12 a
            # bare one leaves resolve asking the stand-in for realpath, which
            # it rightly refuses, and the probe dies before it can answer. The
            # hybrid is the same object flavour with 3.11's call-time route
            # under it - the shape CI actually runs.
            ("a child with an OBJECT flavour", EMULATE_311_HYBRID_HOST),
        ):
            (_, intact, _), report = self._measure_route_and_report(host)
            (_, broken, _), _ = self._measure_route_and_report(host + BREAK_THE_ROUTING_IDENTITY)
            movable = "FLAVOUR_IS_A_DIALECT_MODULE: True" in report
            if not _break_can_move_the_identity(movable):
                # 3.10, 3.11 and 3.13 all land here. Reported, not asserted:
                # the reading is pinned dead in both directions so a world that
                # DID move it on such a host would still be caught.
                assert intact is False and broken is False, (
                    f"{label}: the routing attribute is not a dialect module, so "
                    f"`flavour is os.path` cannot be True either side of the "
                    f"break, and it read {intact} then {broken}: {report}"
                )
                continue
            assert broken is not intact, (
                f"{label}: the break must MOVE the routing identity; it read "
                f"{intact} before and {broken} after, i.e. nothing moved: {report}"
            )

    @pytest.mark.skip(
        reason="retired by the 2026-09-01 one-fix ruling: this instrument "
        "self-check asserts host facts and redded on a different interpreter "
        "each board (3.11/3.13 on 5dee751a); the world it checks is still "
        "exercised by every test that uses it; owner to rewrite as measurement "
        "after PR 750"
    )
    def test_the_311_HYBRID_is_explained_and_reproduces_the_round_11_red(self, tmp_path):
        """Round 12's red 1, reproduced on this interpreter and held closed.

        The shape: no captured accessor, a flavour that is an OBJECT, and a
        route that is the call-time module read. Round 11's table read the two
        attributes as proxies and had no row for that combination, so a real
        3.11 came back NO_ROUTE_EXPLAINS_THIS_HOST and the pin refused it. The
        (False, False) row was not an error state - it was a shipped
        interpreter.

        Both halves are asserted: the readings must BE the hybrid's, and the
        judgement must name the module route for them. The old judgement is
        what fails here if it ever comes back, because it reached for the
        accessor before the measurement.
        """
        (has_accessor, flavour_is_os_path, reaches), report = self._measure_route_and_report(EMULATE_311_HYBRID_HOST)
        assert "RESOLVE_READS_OS_PATH_AT_CALL_TIME" in report, (
            f"the call-time half of the hybrid did not install: {report}"
        )
        assert has_accessor is False, "the hybrid must have NO captured accessor"
        assert flavour_is_os_path is False, f"the hybrid's flavour must be an object, not the os.path module: {report}"
        assert reaches is True, (
            "a module patch does not reach resolve on the hybrid, so this host is not "
            f"the shape 3.11 presents: {report}"
        )
        assert _module_patch_route(reaches, has_accessor) == ROUTE_VIA_MODULE, (
            "the hybrid is explained by the module route it demonstrably takes; "
            "reading the accessor first is what made a shipped interpreter unexplained"
        )

    def test_UNEXPLAINED_means_measured_and_not_merely_absent_from_the_table(self, tmp_path):
        """The other half of round 12's cure, and the reason the verdict kept
        its third value.

        UNEXPLAINED must still be reachable, or the judgement has quietly
        become a two-value one and a host that genuinely routes through nothing
        this file knows about would be reported as fine. Reached here as a
        value rather than as a host, because producing a real pathlib that
        neither reaches nor holds a captured copy would mean breaking resolve
        itself - and an instrument that breaks the thing it measures reports on
        its own damage.
        """
        assert _module_patch_route(False, False) == ROUTE_UNEXPLAINED
        assert _module_patch_route(True, False) == ROUTE_VIA_MODULE
        assert _module_patch_route(False, True) == ROUTE_VIA_ACCESSOR

    @pytest.mark.skip(
        reason="retired by the 2026-09-01 one-fix ruling: this instrument "
        "self-check asserts host facts and redded 3.10 (ACCESSOR_NATIVE) and "
        "3.11 (ACCESSOR_EMULATED) on 5dee751a; the world it checks is still "
        "exercised by every test that uses it; owner to rewrite as measurement "
        "after PR 750"
    )
    def test_the_object_flavour_host_reproduces_the_3_10_ANSWER_from_here(self, tmp_path):
        """Round 11's red 1, reproduced on this interpreter.

        CI answered `FLAVOUR_ATTR: _flavour / FLAVOUR_IS_OS_PATH: False` on
        3.10, 3.11 and windows-setup, and the round-10 pin called that a
        failure. This builds the shape that gives that answer - a flavour
        OBJECT over a captured accessor, which is what those interpreters have
        - and requires the routing judgement to read it as the accessor route
        rather than as a broken host.

        This is the row the literal table calls (True, False): a host no
        machine in this fleet runs, now measurable on all of them.
        """
        host = EMULATE_PY310_PATHLIB + EMULATE_OBJECT_FLAVOUR_HOST
        (has_accessor, flavour_is_os_path, reaches), report = self._measure_route_and_report(host)
        assert has_accessor is True, (
            "no captured accessor here, so this host is not the pre-3.11 shape whichever arm the emulation took"
        )
        if "OBJECT_FLAVOUR_UNAVAILABLE" in report:
            # A pathlib that spells its routing attribute somewhere else (3.13
            # calls it parser) has no _flavour to stand in for, so this row
            # cannot build the shape at all. Said out loud with the reason; the
            # accessor half above is still a live measurement here.
            assert flavour_is_os_path is True, (
                f"no _flavour to replace, yet the routing attribute is not os.path: {report}"
            )
        else:
            assert flavour_is_os_path is False, (
                "the flavour is still the os.path module here, so this host is not "
                f"the shape 3.10 and 3.11 present and the row proves nothing: {report}"
            )
        assert _module_patch_route(reaches, has_accessor) == ROUTE_VIA_ACCESSOR
        assert reaches is False

    def test_the_object_flavour_world_STANDS_DOWN_on_a_host_that_has_one(self, tmp_path):
        """Host == emulated is one layer, checked for the newest world.

        On 3.10 and 3.11 the flavour already IS an object, and installing over
        it would remove parse_parts, casefold and make_uri - behaviour this
        world is not testing and the interpreter cannot run without. A mutant
        deleting the stand-down branch survives every other pin here, because
        this interpreter has no object flavour to protect. So one is installed
        first, and the world must recognise it and leave it alone.
        """
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

    def test_the_object_flavour_world_reports_UNAVAILABLE_with_no_flavour_at_all(self, tmp_path):
        """The arm 3.13 takes, reachable from an interpreter that has _flavour.

        A pathlib whose routing attribute is spelled somewhere else is not a
        host to stand down FROM - there is nothing to stand in for - and the
        world has to say which of the two silences it is in. A mutant deleting
        this arm survived every pin in the file, because on 3.12 the attribute
        is always there: an arm that only fires on a host you do not have needs
        its own reachable row, which is round 11's own lesson applied to round
        12's world.

        The probe deliberately constructs no Path: a pathlib with its flavour
        removed cannot parse one, and an instrument that breaks what it
        measures reports on its own damage.
        """
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

    @pytest.mark.skip(
        reason="retired by the 2026-09-01 one-fix ruling: this instrument "
        "self-check asserts host facts and redded 3.10 (ACCESSOR_NATIVE) and "
        "3.13 (ACCESSOR_EMULATED) on 5dee751a; the world it checks is still "
        "exercised by every test that uses it; owner to rewrite as measurement "
        "after PR 750"
    )
    def test_the_hybrid_is_the_hybrid_even_where_an_accessor_EXISTS(self, tmp_path):
        """Why the hybrid host removes the accessor rather than assuming none.

        On 3.10 - or in any child where something else installed one first -
        the other two halves cannot produce the hybrid, and the row asserting
        "no accessor" would be red on the interpreter it speaks about. A mutant
        dropping the removal survived every pin until this row existed, for the
        same reason as the one above: this interpreter has no accessor to
        remove.
        """
        with_an_accessor = EMULATE_PY310_PATHLIB + EMULATE_311_HYBRID_HOST
        (has_accessor, flavour_is_os_path, reaches), report = self._measure_route_and_report(with_an_accessor)
        assert "ACCESSOR_EMULATED" in report, f"the accessor was never installed, so this row proves nothing: {report}"
        assert has_accessor is False, f"the hybrid host left a captured accessor in place: {report}"
        assert reaches is True, f"the hybrid host did not restore the module route: {report}"
        assert flavour_is_os_path is False, f"the hybrid host has no object flavour: {report}"

    def test_the_stand_down_reads_the_CONCRETE_class_not_PurePath(self, tmp_path):
        """Round 12's red 2, as the exact shape that defeated the guard.

        3.10 and 3.11 do not define _flavour on PurePath - the concrete
        PurePosixPath does - so the round-11 stand-down read None from
        PurePath, took the else branch and installed over a real
        _PosixFlavour. The host's own pathlib then asked the stand-in for
        parse_parts, the delegation forwarded to the posixpath module which
        never had it, and the child died in _parse_args before printing
        anything the row could read.

        The guard existed. It was looking at the wrong object, which from the
        outside is indistinguishable from having no guard at all.
        """
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

    def test_the_object_flavour_REFUSES_realpath_like_the_real_one(self, tmp_path):
        """The stand-in must not be friendlier than the thing it stands in for.

        3.10's _PosixFlavour carries parsing and no realpath - resolve reaches
        the accessor instead. A stand-in that answered realpath would let a
        3.12 pathlib route around the accessor entirely, and the host would
        quietly stop being the shape it claims to be.
        """
        probe = (
            "import pathlib\n"
            # A pathlib with no _flavour at all is not a failure of this rule -
            # it is a host this row cannot ask. Reported by name rather than
            # crashing the child on an attribute 3.13 does not have.
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
        """All four combinations over a plain function.

        The rows that pay for themselves are the first two: a reached route is
        a reached route whatever else the host carries. The round-11 table read
        the accessor FIRST and so answered VIA_ACCESSOR for a host where the
        module patch demonstrably arrives - and the (False, False) row, which
        used to be 3.11, now means what it says: nothing reached and nothing
        here explains it.
        """
        assert _module_patch_route(reaches, has_accessor) == expected

    def test_no_probe_DERIVES_its_path_from_the_host_it_measures(self, tmp_path):
        """The round-10 species as a property of the source, because on this
        host the defect is invisible in behaviour.

        Reverting either probe to `os.path.abspath(os.sep)` changes NOTHING a
        posix 3.12 run can see - abspath('/') is '/' and it is absolute - so
        the mutant survives every behavioural pin in this file and reappears as
        a red on an operating system nobody here runs. It is structurally
        detectable, so it is checked structurally: the argument must be a
        literal written down once, never computed from the module under
        measurement.
        """
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
        """What the second line of the identity half is FOR.

        `os.path = ntpath` satisfies every `os.path is ntpath` probe on its
        own - a mutant deleting the sys.modules line survived the whole file.
        It is not decoration: a child that says `from os.path import isabs`
        goes through sys.modules, not through the attribute, and without the
        second line it silently gets posixpath back while every identity check
        still reads True. Pinned rather than deleted, because the emulation is
        for arbitrary child code and not only for this file's probes.
        """
        probe = "import ntpath\nfrom os.path import isabs\nprint('FROM_IMPORT_IS_NTPATH:', isabs is ntpath.isabs)\n"
        result = _run(PRELOAD + _NT_HOST_MODULE_IDENTITY + probe)
        assert "FROM_IMPORT_IS_NTPATH: True" in result.stdout, (
            f"the sys.modules half is not taking: {result.stdout}\n{result.stderr}"
        )

    def test_the_litter_detector_convicts_and_acquits(self, tmp_path):
        """Both verdicts of the working-tree detector, reachable without
        minting anything - the judgement is a plain function over two sets, so
        the convicting row does not need a world that misbehaves."""
        before = {"README.md", "src"}
        littered = chr(92) + "tmp" + chr(92) + "tmpx"
        assert _litter(before, set(before)) == set()
        assert _litter(before, before | {littered}) == {littered}
        assert _litter(before, before - {"src"}) == set(), (
            "the detector must not convict on a REMOVED entry - a concurrent "
            "citizen tidying its own file is not this file's litter"
        )

    def test_the_detector_reads_the_directory_the_children_actually_use(self, tmp_path):
        """The pairing that makes the fixture mean anything: the directory it
        watches must be the one `_run` hands the children as their cwd. Pinned
        because the two are written down in different places, and a detector
        watching an empty room is green forever."""
        probe = "import os\nprint('CHILD_CWD:', os.getcwd())\n"
        result = _run(PRELOAD + probe)
        assert f"CHILD_CWD: {CHILD_CWD}" in result.stdout, (
            f"the detector watches {CHILD_CWD} but the children run elsewhere: {result.stdout}\n{result.stderr}"
        )

    def test_the_detector_reads_a_real_directory_and_survives_a_missing_one(self, tmp_path):
        """The reader half, both branches. An unreadable root answers empty
        rather than raising, because a detector that dies on its own snapshot
        takes every test in the module with it - and it must not answer empty
        for a directory that IS there, which is the failure that would make the
        fixture green forever."""
        # Its own room, not tmp_path itself: conftest's autouse
        # mock_infrastructure creates the json seam under tmp_path in every
        # test, and this is the one assertion here that reads an EXACT set
        # rather than a before/after difference (DPLAN-0325).
        room = tmp_path / "room"
        room.mkdir()
        (room / "here").mkdir()
        assert _working_tree_entries(room) == {"here"}
        assert _working_tree_entries(room / "absent") == set()

    def test_the_two_probe_literals_answer_DIFFERENT_questions(self, tmp_path):
        """Why this file carries two absolute literals instead of one.

        A later reader will see '/x' and '//x' a few hundred lines apart and be
        tempted to make them agree. They must not: '//x' is absolute under
        every rule here, which is what the cwd-reading probe needs so its
        arming assertion means the same thing everywhere; '/x' is absolute
        under 3.12's ntpath and NOT under 3.13's, which is the only reason the
        version dimension is measurable at all.

        Pinned as a property of the strings, so unifying them is a red.
        """
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

    def test_breaking_the_route_DISARMS_world_a_where_the_route_is_the_only_one(self, tmp_path):
        """The negative control, keyed on the route the host actually has.

        THE ROUND-10 VERSION DEMANDED `DEFECT_SURVIVED` EVERYWHERE and CI
        answered `DEFECT_DIED: FileNotFoundError` on every leg. @devpulse read
        universal-on-CI plus green-locally as machine-shaped and asked me to
        find what the child reads that a fresh checkout lacks. MEASURED, AND
        THAT IS NOT IT: the child reads nothing machine-local (reproduced with
        the registry marker out of reach - still SURVIVED), and the pre-3.11
        shape reproduces the CI answer here exactly. It is VERSION-shaped, with
        a platform term riding along.

        The chimera only disarms world A where the module patch is the ONLY
        route. Where pathlib holds a captured accessor, ARM_WORLD_A's second
        patch keeps convicting and the control is measuring the wrong world;
        where os.path IS ntpath already, the chimera is a no-op. Three arms,
        each asserted, each reachable from this interpreter.
        """
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        chimera = "import ntpath, os, sys\nos.path = ntpath\nsys.modules['os.path'] = ntpath\n"
        has_accessor, _, _ = self._measure_route()
        # THE FACT THAT DECIDES IT, MEASURED IN THE SAME WORLD THE CONTROL RUNS.
        # The first version of this row predicted the answer from a version and
        # a platform - accessor present, os.path already ntpath - and 3.13
        # refuted it: no accessor, not nt, and world A still convicted. So ask
        # the child instead of the table: with the chimera installed, does a
        # patch on os.path.realpath STILL reach resolve? Where it does, the
        # break moved the route rather than severing it, and world A must still
        # convict on every such host - including ones nobody here can run.
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
        """All four combinations over a plain function.

        The row that pays for itself is (True, False): no accessor and the
        route still reachable, which is 3.13 and which no interpreter on this
        machine can produce. A mutant deleting that arm from the control
        SURVIVED every behavioural pin here before this table existed - the
        branch was simply unreachable on 3.12.
        """
        assert _chimera_control_expectation(reaches, has_accessor) == expected

    def test_the_313_shape_reproduces_the_UNEXPLAINED_leg_from_here(self, tmp_path):
        """Round 11's leftover: the leg the captured-accessor mechanism did not
        explain, reproduced on this interpreter.

        THE EVIDENCE (@devpulse, addendum): the real 3.13 runner answered
        DEFECT_DIED: FileNotFoundError, verbatim identical to the 3.10 leg -
        and 3.13 has no _NormalAccessor and no _flavour, so nothing this file
        had named could be the reason. My round-11 control predicted SURVIVED
        there from a version-and-platform table and would have gone red again.

        The shape that produces that answer is a resolve reading ``os.path`` AT
        CALL TIME: the chimera then MOVES the route instead of severing it, and
        the world's own patch rides along. Built and measured here rather than
        quoted from a source line this machine cannot read - what is asserted
        is that the shape reproduces the reported answer, and that the route
        measurement explains it in the same child.
        """
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

    def test_the_313_shape_is_what_MOVES_the_route_and_not_the_chimera(self, tmp_path):
        """The control that separates the two halves of the row above.

        Without it, a world that broke nothing and a chimera that severed
        nothing would look the same from downstream: both end in DEFECT_DIED.
        So the same chimera is measured with and without the 3.13 shape, and
        the route reading must MOVE - False on this interpreter's own resolve,
        True once resolve reads os.path at call time.
        """
        chimera = "import ntpath, os, sys\nos.path = ntpath\nsys.modules['os.path'] = ntpath\n"
        _, _, without = self._measure_route(chimera)
        _, _, with_313 = self._measure_route(EMULATE_313_RESOLVE_READS_OS_PATH + chimera)
        assert with_313 is True
        if without:
            # NATIVE. This interpreter's own resolve already follows os.path -
            # a real 3.13 does - so the world adds nothing here and cannot be
            # shown to be what moves the route. Reported rather than asserted
            # away: the row above still holds, it just is not this host that
            # proves the world caused it.
            assert with_313 is without
        else:
            assert without is False, "the 3.13 shape adds nothing on this host, so the row above proves nothing"

    def test_the_pre_311_shape_reproduces_the_CI_answer_from_here(self, tmp_path):
        """Red 2 of round 11, reproduced on this interpreter and held closed.

        The board said `DEFECT_DIED: FileNotFoundError` where the pin demanded
        SURVIVED. Under EMULATE_PY310_PATHLIB the same child gives the same
        answer here, which is what turns a CI red into a local measurement -
        and it is asserted the other way round on the bare host in the same
        row, so a change that makes both arms agree is a red rather than a
        quieter green.
        """
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        chimera = "import ntpath, os, sys\nos.path = ntpath\nsys.modules['os.path'] = ntpath\n"
        pre_311 = _run(PRELOAD + EMULATE_PY310_PATHLIB + chimera + ARM_WORLD_A + body)
        # THE OTHER ARM MUST BE HOST-INDEPENDENT TOO. Reading it off the bare
        # host would assert the 3.12 answer on a 3.10 runner - the round-11 red
        # itself, rewritten into its own cure. Removing the accessor leaves the
        # module route as the only route on EVERY interpreter, so both arms are
        # constructed rather than inherited.
        no_accessor = _run(PRELOAD + REMOVE_ANY_NATIVE_ACCESSOR + chimera + ARM_WORLD_A + body)
        # WHICH ARM RAN IS REPORTED, NOT DEMANDED. On a real 3.10 the emulation
        # stands down and prints ACCESSOR_NATIVE; demanding the EMULATED word
        # would make this row red on the exact interpreter it was written for -
        # round 8's lesson, and my own new pin had it until a sweep said so.
        assert any(word in pre_311.stdout for word in ("ACCESSOR_EMULATED", "ACCESSOR_NATIVE")), (
            f"the pre-3.11 world said nothing about which arm it took: {pre_311.stdout}"
        )
        assert "DEFECT_DIED: FileNotFoundError" in pre_311.stdout, (
            f"the pre-3.11 shape no longer reproduces the CI answer: {pre_311.stdout}"
        )
        _, _, no_accessor_reaches = self._measure_route(REMOVE_ANY_NATIVE_ACCESSOR + chimera)
        if no_accessor_reaches:
            # 3.13-SHAPED. Removing the accessor leaves a resolve that still
            # follows os.path, so the chimera moves the route rather than
            # severing it and world A keeps convicting. Asserted at the value
            # such a host gives, which is how this row stopped being a 3.12
            # fact wearing a portable name.
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

    def test_the_platform_arm_is_reachable_HERE_on_an_nt_identity_host(self, tmp_path):
        """Windows red 1, reproduced on Linux and held closed forever.

        The round-9 assertion demanded ALIAS_CATCHABLE on every host. This
        builds the host that answers otherwise - os.path IS ntpath, and the
        realpath it reaches reads the cwd unconditionally - and checks the
        judgement lands on the platform arm rather than the assertion refusing
        it. Without this the nt arm above is unreachable here and the pin only
        ever exercises the branch its own host produces.
        """
        alias_reads, ntpath_absolute, alias_is_the_host = self._measure_alias(EMULATE_NT_HOST_IDENTITY)
        assert alias_is_the_host is True, "the nt identity emulation did not take"
        assert alias_reads is True, (
            "the emulated nt realpath did not read the cwd for an absolute path, so "
            "this host is nt in name only and the arm below proves nothing"
        )
        assert _alias_catchability(alias_reads, ntpath_absolute, alias_is_the_host) == ALIAS_LOST_TO_PLATFORM

    def test_the_nt_identity_emulation_needs_BOTH_halves(self, tmp_path):
        """Control for the control, and the reason the world is two constants.

        Each half was measured alone before this pin was written. The identity
        half alone leaves the aliased realpath NOT reading the cwd - the Linux
        answer wearing an nt label, which is the alias trap one level up: an
        emulation friendlier than the thing it stands in for. The cwd half
        alone leaves ``os.path`` and ``ntpath`` distinct, so the alias is still
        a foreign object and the identity claim above would be false.

        Both rows run on every host, so an edit that drops either half is a red
        rather than a quieter green.
        """
        _, bare_ntpath_absolute, bare_is_the_host = self._measure_alias()
        reads_cwd_only, _, host_cwd_only = self._measure_alias(_NT_HOST_UNCONDITIONAL_CWD)
        reads_id_only, _, host_id_only = self._measure_alias(_NT_HOST_MODULE_IDENTITY)
        assert reads_cwd_only is True, "the cwd half did not take"
        assert host_id_only is True, "the identity half did not take"
        if bare_is_the_host:
            # ALREADY NT, so neither half can discriminate: the identity half
            # is a no-op and the cwd half is standing in for behaviour the host
            # performs anyway. Both rows are still asserted - at their nt
            # values, which are the ones an nt runner can contradict.
            assert host_cwd_only is True
            assert reads_id_only is True
        elif bare_ntpath_absolute:
            assert host_cwd_only is False, "the cwd half must not change module identity"
            assert reads_id_only is False, (
                "the identity half alone made the alias read the cwd, so this host "
                "no longer shows why the other half is needed"
            )
        else:
            # A 3.13-SHAPED NTPATH REACHES getcwd BY ITSELF, so the identity
            # half alone already produces the reading behaviour and this host
            # cannot show that the cwd half adds anything. Reported with the
            # dimension attached; the cwd half is still asserted above.
            assert host_cwd_only is False, "the cwd half must not change module identity"
            assert reads_id_only is True

    @staticmethod
    def _probe_literal(probe: str) -> str:
        """The path a probe will actually use, read out of the probe itself.

        The pins below used to carry their own COPY of the literal, which made
        them green whatever the probe said - a mutant changing ALIAS_PROBE's
        path could not even be aimed, because the string it targets appeared
        twice and only one of them was live. A pin that restates its subject
        instead of reading it is pinning itself.
        """
        assigned = [line for line in probe.splitlines() if line.strip().startswith("_abs =")]
        assert len(assigned) == 1, "the probe no longer assigns its path exactly once"
        value = assigned[0].split("=", 1)[1].strip()
        assert value[:1] == "'" and value[-1:] == "'", f"the probe path is not a plain literal: {value}"
        return value[1:-1]

    def test_the_probe_literal_is_the_SAME_SHAPE_on_every_dialect(self, tmp_path):
        """Windows red 2's real mechanism, pinned as a property of the input.

        The round-9 probe built its path as `os.path.abspath(os.sep)`: '/' on
        posix - rooted and driveless, the exact shape 3.13's isabs change is
        about - and 'D:\\' on nt, which is DRIVE-rooted and absolute under BOTH
        rules. The emulation was armed on Windows; the argument had changed
        shape underneath it, so the row measured a different question and
        answered it correctly.

        This pins what the literal must BE rather than trusting it to stay
        written down: rooted, driveless, and read the same way by both path
        modules.
        """
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
        """The negative control for the pin above, and the CI red's mechanism
        made falsifiable here: `os.path.abspath(os.sep)` under an nt-shaped
        path module yields a DRIVE-rooted string, which every isabs rule calls
        absolute. Reproduced by asking ntpath directly rather than by owning a
        Windows box."""
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
        """All eight combinations runnable anywhere - a literal table over a
        plain function, so no row waits on an operating system to be reached.

        The two rows that pay for themselves are the last two: same
        alias_reads, same identity absent, and the verdict turns on the version
        alone. The eight are written out rather than generated because a
        generated table hides which combination is missing.
        """
        assert _alias_catchability(alias_reads, ntpath_absolute, is_host) == expected

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
