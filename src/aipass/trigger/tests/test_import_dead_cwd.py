# ===================AIPASS====================
# META DATA HEADER
# Name: test_import_dead_cwd.py - trigger imports without a readable cwd
# Date: 2026-08-31
# Version: 1.3.0
# Category: trigger/tests
# =============================================

"""Every trigger module must import without a readable working directory.

THE MECHANISM, measured on the Windows CI gate 2026-08-31 (@memory's finding,
relayed round 4): ntpath.realpath calls os.getcwd() UNCONDITIONALLY - not only
for relative paths, the way posixpath does - and Path.resolve() routes through
it. So on Windows every Path(__file__).resolve() REACHED AT IMPORT is a
working-directory read, and a process whose cwd was deleted cannot import the
module at all.

WHY THIS BRANCH, LOUDLY. @prax reproduced it on Linux against trigger and their
traceback is the reason this file exists: prax's logger imports
discovery/watcher.py, which imports aipass.trigger.apps.modules.core, which ran
trigger's handler guard, which died on line 12. One guard in one branch took
down every consumer of prax's logger. Trigger carried eight import-time sites
plus the guard.

THE WORLD injects ntpath's behaviour as a CONDITION rather than a platform:
os.path.realpath is wrapped to read os.getcwd() first, then os.getcwd is denied.
The injection happens in a child process before any aipass import, so no module
has cached the real functions. In-process this property is unobservable - the
imports already happened - which is why every world here is a subprocess.

AND THE INJECTION HAS TO REACH THE CALL. Patching os.path.realpath only reaches
sites that look the name up each time. CPython 3.10's pathlib captures a copy at
its own first import (_NormalAccessor.realpath), so on 3.10 the order of imports
decides whether this whole file measures anything - and 3.10 is in the CI matrix.
_ACCESSOR_PATCH rebinds the captured copy too, so the world arms on every
interpreter rather than on luck. Credit: @flow found it, @memory read the 3.10
source, @devpulse relayed it.

WHY THE PRELOAD LIST IS SHORT HERE. The fleet pattern preloads peer branches in
the healthy world so a pin measures its own branch only. Trigger cannot preload
@prax: prax's logger imports trigger, so preloading prax would import the very
sites under test in the healthy world and the pin would go green measuring
nothing. It is preloaded UNDER the denial instead, which is sound because prax's
own cure landed 2026-08-31 (verified: prax imports clean in this world). @cli was preloaded
healthy while its guard still walked inspect.stack(); that preload was retired
2026-08-31 once their cure was verified from here.
"""

import subprocess
import sys
from pathlib import Path

import pytest

# Peers held constant in the healthy world, before the denial.
#
# @cli's preload was here and is RETIRED. Two facts, and the second corrects
# what this file used to claim: their guard was cured 2026-08-31 and verified
# importing clean under the ntpath world below from this branch — AND @cli is
# never reached from these worlds at all. Measured: after importing every site
# below under the denial, no aipass.cli module is in sys.modules. prax is (it is
# on trigger's import path); prax does not pull cli. So the preload was
# belt-and-braces, not load-bearing, and this file previously said otherwise.
#
# @prax is deliberately NOT preloaded and never can be — prax's logger imports
# trigger, so preloading it would import the sites under test in the HEALTHY
# world and every assert here would go green measuring nothing. Prax rides under
# the denial instead, which is sound because their own cure landed the same day.
_PRELOAD = r"""
import rich.console  # noqa: F401
import inspect  # noqa: F401
import linecache  # noqa: F401
"""

# THE CAPTURED COPY (@flow's find, relayed by @devpulse 2026-08-31).
#
# Patching os.path.realpath only reaches call sites that LOOK IT UP each time.
# CPython 3.10's pathlib does not: Lib/pathlib.py binds
# `realpath = staticmethod(os.path.realpath)` onto _NormalAccessor at class
# creation, i.e. at pathlib's FIRST import, and resolve() reads it back through
# `self._accessor.realpath`. Rebind os.path afterwards and you rebind a name
# nothing reads again - the world goes inert and every pin under it passes
# measuring nothing.
#
# So the world rebinds the captured copy too. staticmethod is not decoration:
# a plain function assigned to a class becomes a bound method and eats the path
# into `self`, which fails for the wrong reason and can leave a raise-shaped pin
# green. Guarded by hasattr because 3.11+ deleted _NormalAccessor - there the
# rebind is a no-op and the call-time lookup is what arms the world (measured on
# 3.12: this world arms whether pathlib is imported before or after the patch).
_ACCESSOR_PATCH = r"""
import pathlib

_captured = getattr(pathlib, "_NormalAccessor", None)
if _captured is not None:
    _captured.realpath = staticmethod(os.path.realpath)
"""

# The posix-shaped denial: enough to reach every module-level resolve().
_PREAMBLE = (
    _PRELOAD
    + r"""
import os

_real_realpath = os.path.realpath


def _ntpath_condition(path, **kw):
    os.getcwd()  # ntpath.realpath reads cwd before checking absoluteness
    return _real_realpath(path, **kw)


os.path.realpath = _ntpath_condition


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd
"""
    + _ACCESSOR_PATCH
    + r"""
# Probe the instrument: does THIS interpreter's resolve() reach the denied call?
# The path is ABSOLUTE on purpose - a relative one dies in abspath for its own
# shape and would report ARMED whatever the patch did or failed to do.
try:
    pathlib.Path(pathlib.__file__).resolve()
    print("PROBE_VACUOUS")
except FileNotFoundError:
    print("PROBE_ARMED")
"""
)

# The ntpath-SHAPED denial, needed to reach the guard's old defect.
#
# On POSIX every route inspect.stack() takes to os.path.realpath runs through
# getabsfile(), whose os.path.abspath raises FileNotFoundError for the relative
# "<frozen importlib._bootstrap>" filenames an import stack carries - and
# getmodule() CATCHES FileNotFoundError, so the unguarded
# `modulesbyfile[os.path.realpath(f)]` below it is never reached. A pin built on
# the preamble above therefore goes GREEN against a reintroduced inspect.stack():
# it measures the module-level resolve() next door, not the stack walk.
#
# ntpath has no such early raise, so on Windows getmodule() proceeds and dies.
# Emulated by giving abspath ntpath's non-raising behaviour while realpath keeps
# reading cwd - the injection then denies the call the DEFECT actually makes
# (@memory's rule), not one the platform happens to catch first.
_NTPATH_PREAMBLE = (
    _PRELOAD
    + r"""
import os

_real_realpath = os.path.realpath
_real_abspath = os.path.abspath


def _ntpath_realpath(path, **kw):
    os.getcwd()  # ntpath.realpath reads cwd before checking absoluteness
    return _real_realpath(path, **kw)


def _ntpath_abspath(path):
    # ntpath.abspath falls back rather than raising the way posixpath does.
    try:
        return _real_abspath(path)
    except OSError:
        return path


os.path.realpath = _ntpath_realpath
os.path.abspath = _ntpath_abspath


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd
"""
    + _ACCESSOR_PATCH
    + r"""
# Probe against the defect ITSELF, not a proxy: does inspect.stack() die in this
# world? If it does not, this pin proves nothing.
import inspect

try:
    inspect.stack()
    print("STACK_SURVIVES")
except FileNotFoundError:
    print("STACK_DIES")
"""
)

# Every trigger site that resolves a path at IMPORT, named one per line so a
# failure says which module died rather than "the branch".
#
# events/plan_file.py was a fourth _find_repo_root caller and is gone: retired
# 2026-08-31 as measured inert (see apps/handlers/events/.archive/plan_file.py).
# This pin went red when it was archived, which is the list doing its job.
_SITES = r"""
import aipass.trigger.apps.handlers  # noqa: F401
print("GUARD_OK")
import aipass.trigger.apps.config  # noqa: F401
print("CONFIG_OK")
import aipass.trigger.apps.handlers.json.json_handler  # noqa: F401
print("JSON_OK")
import aipass.trigger.apps.handlers.escalation  # noqa: F401
print("ESCALATION_OK")
import aipass.trigger.apps.handlers.events.error_detected  # noqa: F401
print("ERROR_DETECTED_OK")
import aipass.trigger.apps.handlers.events.runaway_handler  # noqa: F401
print("RUNAWAY_OK")
import aipass.trigger.apps.modules.medic  # noqa: F401
print("MEDIC_OK")
import aipass.trigger.apps.modules.core  # noqa: F401
print("IMPORTED")
"""

SWEEP_WORLD = _PREAMBLE + _SITES

# The guard alone, under the world its old implementation actually died in.
NTPATH_GUARD_WORLD = (
    _NTPATH_PREAMBLE
    + r"""
import aipass.trigger.apps.handlers  # noqa: F401

print("IMPORTED")
"""
)

# The whole branch under the ntpath world - the shape @prax's traceback took.
NTPATH_SWEEP_WORLD = _NTPATH_PREAMBLE + _SITES


def _run(world: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", world],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _assert_probe_armed(out: str) -> None:
    """The instrument must be able to fire, or the pin proves nothing.

    This used to accept PROBE_VACUOUS on sys.version_info < (3, 11), citing
    "pre-3.11 pathlib never routes an absolute resolve through os.path.realpath".
    That sentence was a RETRACTED diagnosis and it is false: 3.10 routes through
    a copy of os.path.realpath captured onto _NormalAccessor at pathlib's first
    import. The clause therefore blessed exactly the vacuity it exists to catch,
    on the one interpreter where the world could genuinely go inert - and 3.10 is
    in the CI matrix. _ACCESSOR_PATCH arms that interpreter, so no version is
    excused any more. A vacuous world is a failure everywhere.
    """
    assert "PROBE_ARMED" in out, (
        "the denial did not reach resolve() - the instrument is broken, not the "
        f"world, and every pin under it proves nothing:\n{out}"
    )


# The JUDGEMENT, separated from the WORLD (@commons' round-5 rule). No
# interpreter here can produce a vacuous probe, so the branch that decides what
# to DO about one is unreachable from any real world on this host - which is how
# the version escape hatch survived in the first place, and how it would come
# back. Fed synthetic strings, every interpreter case is reachable from any
# machine, including the one no local run can create.


def test_a_vacuous_probe_is_refused_on_the_interpreter_that_could_produce_one(monkeypatch):
    """3.10 is the ONE interpreter that can go inert, and it gets no exemption.

    The deleted clause read `assert sys.version_info < (3, 11)`, so on 3.10 it
    returned quietly. This is the pin that convicts its return: faking the
    version is the only way this host can stand where 3.10 stands.
    """
    monkeypatch.setattr(sys, "version_info", (3, 10, 4, "final", 0))

    with pytest.raises(AssertionError):
        _assert_probe_armed("PROBE_VACUOUS\nIMPORTED\n")


def test_a_vacuous_probe_is_refused_on_this_interpreter_too():
    """The unfaked half, so the pin above cannot pass on the monkeypatch alone."""
    with pytest.raises(AssertionError):
        _assert_probe_armed("PROBE_VACUOUS\nIMPORTED\n")


def test_an_armed_probe_is_accepted():
    """The judgement is not simply 'always raise' - it has to let a real world through."""
    _assert_probe_armed("PROBE_ARMED\nIMPORTED\n")


def test_a_probe_that_printed_nothing_is_refused():
    """Silence is not consent: a world that crashed before probing proves nothing."""
    with pytest.raises(AssertionError):
        _assert_probe_armed("IMPORTED\n")


def test_import_time_sites_survive_a_denied_cwd():
    """The eight import-time resolve sites, under a denied working directory."""
    result = _run(SWEEP_WORLD)
    out = result.stdout

    assert "IMPORTED" in out, f"a trigger import died under the dead-cwd world:\nstdout={out}\nstderr={result.stderr}"
    _assert_probe_armed(out)


def test_handlers_guard_survives_the_ntpath_shaped_denial():
    """The guard must not walk inspect.stack().

    Separate from the sweep because the posix-shaped world is satisfied by the
    guarded resolve alone. This one is RED against an inspect.stack() walk and
    green against the sys._getframe cure.
    """
    result = _run(NTPATH_GUARD_WORLD)
    out = result.stdout

    assert "STACK_DIES" in out, (
        "inspect.stack() survived the ntpath-shaped denial - the instrument no "
        f"longer reaches the defect and this pin is vacuous:\n{out}"
    )
    assert "IMPORTED" in out, (
        f"the handlers guard still depends on a readable cwd:\nstdout={out}\nstderr={result.stderr}"
    )


def test_whole_branch_imports_under_the_ntpath_shaped_denial():
    """@prax's traceback, as a pin: importing trigger must not need a cwd."""
    result = _run(NTPATH_SWEEP_WORLD)
    out = result.stdout

    assert "STACK_DIES" in out, f"the ntpath world went vacuous - this pin proves nothing:\n{out}"
    assert "IMPORTED" in out, f"a trigger import died under the ntpath world:\nstdout={out}\nstderr={result.stderr}"


# ---------------------------------------------------------------------------
# Is _ACCESSOR_PATCH load-bearing, or decoration? Falsifiable HERE, on 3.12.
#
# The interpreter that needs it (3.10) is in the CI matrix and is not installed
# on this machine, so "it works on 3.10" is not something this suite can claim.
# What it CAN do is rebuild 3.10's capture shape - an eager staticmethod bound at
# class creation, read back through an instance - and pin the two directions
# separately: the bare os.path patch is INERT against it, the shipped patch ARMS
# it.
#
# ROUND 7, PAID FOR ON THE WINDOWS RUNNER. The first cut let the shape capture
# the LIVE os.path.realpath and then asked "did a later patch reach it?" by
# reading raise/no-raise under a denied getcwd. That discriminates on POSIX only:
# posixpath.realpath ignores the cwd for an absolute path, so RAISED could only
# mean the patch landed. On nt, ntpath.realpath (ntpath.py:673) computes
# `cwd = os.getcwd()` UNCONDITIONALLY - above the `isabs` test that is the only
# thing reading it - so the ORIGINAL raises too and RAISED stops discriminating.
# CI printed EMULATION_EAGER / CAPTURE_ARMED and the pin failed for the reason it
# was built to detect, one platform over.
#
# @memory's verdict, and the rule this file now obeys: AN INSTRUMENT MUST NOT
# IMPORT BEHAVIOUR IT IS NOT TESTING. The captured function is a SENTINEL that
# touches no filesystem, no cwd and no path module, and answers with a constant
# rather than a path - so whatever raises or returns afterwards is the patch's
# doing, on any platform, and no return-value pin can quietly start measuring the
# host (@drone's addendum).
# ---------------------------------------------------------------------------

# Two distinguishable sentinels, because a sentinel alone cannot show EAGERNESS.
# @skills' asymmetry note: sentinel the dialect-divergent half only, or a pin
# that measures when the capture happened goes dark. An identity check would not
# have survived the cure either - a lazy wrapper around one sentinel returns the
# same answer as an eager capture of it. Moving the SOURCE after class creation
# is what separates them, and it needs no platform behaviour at all.
_SENTINELS = r"""
def _sentinel_captured(path, *, strict=False):
    # Touches no filesystem, no cwd, no path module. Answers with a CONSTANT,
    # not a path, so no return-value check can start measuring the host.
    return "CAPTURED"


def _sentinel_moved(path, *, strict=False):
    return "MOVED"


_source_realpath = _sentinel_captured

# The control FOR the eagerness control (@flow's shape, 2026-08-31). The
# discriminator below is "did the answer follow the moved source name" - and it
# can only discriminate while the two sentinels give DIFFERENT answers. Collapse
# them to one string and the eagerness pin reports EAGER forever with nothing
# saying so; measured as a surviving mutant here before this line existed.
print("SENTINELS_DIFFER", _sentinel_captured(_ABS) != _sentinel_moved(_ABS))
"""

# The win32 branch of ntpath.realpath, built BY NAME from ntpath's own helpers.
#
# NOT by aliasing: off Windows `ntpath.realpath` is a WRAPPER that returns
# abspath(path) (ntpath.py:564), not an alias - `ntpath.realpath is
# ntpath.abspath` is False here, so an is-test proves nothing either way
# (@flow's alias trap as corrected by @skills). Aliasing it would produce a
# green-looking answer that silently stops reproducing the bug.
_NT_SHAPED = r"""
import ntpath

_getcwd_reads = []


def _nt_shaped_realpath(path, *, strict=False):
    # ntpath.py:659-673, str branch: cwd is computed BEFORE the isabs test that
    # is the only thing that consumes it.
    path = ntpath.normpath(path)
    _getcwd_reads.append(1)
    cwd = os.getcwd()
    if not ntpath.isabs(path):
        path = ntpath.join(cwd, path)
    return path
"""

_CAPTURE_HEAD = r"""
import ntpath
import os
import posixpath
import sys

# ABSOLUTE on purpose - a relative path dies in abspath for its own shape and
# would report ARMED whatever the patch did or failed to do - and absolute IN
# BOTH DIALECTS, which is the round-8 correction.
#
# This was sys.executable, which is absolute in the HOST's dialect and nobody
# else's. On the Windows runner that is D:\a\...\python.exe, and
# posixpath.isabs() of it is FALSE - so the posix capture treated it as relative,
# joined the denied cwd, and reported ARMED where the row demanded INERT. The
# arming row had silently keyed on here-equals-a-posix-host.
#
# A rooted literal is absolute to posixpath AND to ntpath (drive-relative there,
# which costs nothing since nothing resolves it), and exists on no machine, so
# no filesystem can answer for the probe either. @spawn's sentence: the
# platform-shaped assumption moves up a level each time it is cured - round 6
# the world, round 7 the emulation, round 8 the thing that INSTALLS the probe.
_ABS = "/AIPASS_NO_SUCH_PROBE_PATH"
"""

# Said out loud rather than assumed, and printed before any verdict: a row whose
# probe is not absolute in the captured dialect is measuring the host's notion of
# absoluteness, not the patch.
#
# posixpath ONLY, and that is a measurement rather than an oversight. The two
# dialects are asymmetric (@flow's note, confirmed here): posixpath REFUSES an nt
# literal, ntpath ACCEPTS a posix one and treats it as drive-relative. So there
# is no path that is posix-absolute and not nt-absolute -
#   '/x'    posix True  nt True
#   'D:\x'  posix False nt True
#   r'\\srv\s' posix False nt True
# - and an `and ntpath.isabs(_ABS)` clause can never fire. It was here and a
# mutant proved it: dropping it changed nothing. Named rather than kept looking
# load-bearing. posixpath is the strict dialect, so it is the one that has to
# agree, and every row shares one literal.
_PROBE_CONTROL = r"""
print("PROBE_IS_ABS", posixpath.isabs(_ABS))
"""

# @spawn's ROUTE_ARMED/ROUTE_DARK: the emulation proves it TOOK the route before
# anything downstream claims anything. For the nt shape that means showing the
# unconditional cwd read really fires for an ABSOLUTE path - which is the entire
# reason the nt dialect breaks a raise-shaped probe.
_ROUTE_CONTROL = r"""
if _CAPTURED is _nt_shaped_realpath or _HOST_REALPATH is _nt_shaped_realpath:
    _before = len(_getcwd_reads)
    _nt_shaped_realpath(_ABS)
    print("ROUTE_ARMED" if len(_getcwd_reads) > _before else "ROUTE_DARK")
"""

_BUILD_ACCESSOR = r"""
class _NormalAccessorShape:
    # EAGER, at class creation - exactly when pathlib 3.10 binds its own copy.
    realpath = staticmethod(_CAPTURED)


_accessor = _NormalAccessorShape()
"""

# The eagerness control, by VALUE and with no platform behaviour in it: move the
# source name after the class was built. An eager capture still answers with the
# function it captured; a lazy wrapper follows the name and answers "MOVED".
_EAGER_CONTROL = r"""
if _CAPTURED is _sentinel_captured:
    _source_realpath = _sentinel_moved
    print("EMULATION_EAGER" if _accessor.realpath(_ABS) == "CAPTURED" else "EMULATION_NOT_EAGER")
else:
    print("EMULATION_EAGER" if _NormalAccessorShape.realpath is _CAPTURED else "EMULATION_NOT_EAGER")
"""

_DENIAL_HEAD = r"""
_real_realpath = _HOST_REALPATH


def _denied(path, **kw):
    os.getcwd()
    return _real_realpath(path, **kw)


os.path.realpath = _denied


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd
"""

# The shipped fragment, aimed at the emulated holder rather than pathlib's.
_APPLY_SHIPPED_PATCH = r"""
_captured = _NormalAccessorShape
if _captured is not None:
    _captured.realpath = staticmethod(os.path.realpath)
"""

# Read back through the INSTANCE, the way pathlib 3.10's resolve() does
# (`self._accessor.realpath`), never off the class.
_EXERCISE_CAPTURE = r"""
try:
    result = _accessor.realpath(_ABS)
except FileNotFoundError:
    print("CAPTURE_ARMED")
except TypeError as exc:
    print("PLAIN_EATS_SELF", type(exc).__name__)
else:
    # A return-value check, not a survived/raised one: a plain-function rebind
    # eats the path into `self` and can otherwise look like a pass.
    print("CAPTURE_INERT", result)
"""

_CAPTURE_EXPR = {
    "sentinel": "_sentinel_captured",
    "posix": "posixpath.realpath",
    "nt": "_nt_shaped_realpath",
}

_HOST_EXPR = {"posix": "posixpath.realpath", "nt": "_nt_shaped_realpath"}


def _capture_world(
    capture: str,
    *,
    host: str = "posix",
    apply_patch: bool = False,
    bare_rebind: bool = False,
    probe: str | None = None,
    spoof_executable: str | None = None,
) -> str:
    """Assemble one capture world.

    capture= what the accessor captured EAGERLY. "sentinel" is the shipped
    shape; "posix"/"nt" rebuild the PRE-CURE shape so the round-7 failure stays
    reproducible on this host rather than living only in a CI log.
    host=    which dialect the SURROUNDING os.path.realpath speaks. Varying this
    while holding the capture fixed is the litmus.
    """
    world = ""
    if spoof_executable is not None:
        # Stand where the other platform stands, before the world computes
        # anything from it.
        world += f"import sys\n\nsys.executable = {spoof_executable!r}\n"
    world += _CAPTURE_HEAD
    if probe is not None:
        world += f"_ABS = {probe!r}\n"
    world += _PROBE_CONTROL + _SENTINELS + _NT_SHAPED
    world += f"\n_CAPTURED = {_CAPTURE_EXPR[capture]}\n"
    world += f"_HOST_REALPATH = {_HOST_EXPR[host]}\n"
    world += _ROUTE_CONTROL + _BUILD_ACCESSOR + _EAGER_CONTROL + _DENIAL_HEAD
    if apply_patch:
        world += _APPLY_SHIPPED_PATCH
    if bare_rebind:
        world += "\n_NormalAccessorShape.realpath = os.path.realpath  # NO staticmethod\n"
    return world + _EXERCISE_CAPTURE


def _assert_emulation_sound(out: str, capture: str, host: str = "posix") -> None:
    """Nothing downstream may be believed until the emulation says it is real."""
    assert "SENTINELS_DIFFER True" in out, (
        "the two sentinels answer alike, so the eagerness discriminator below "
        f"cannot report anything but EAGER - it is dark, not passing:\n{out}"
    )
    assert "PROBE_IS_ABS True" in out, (
        "the probe path is not absolute to posixpath, the strict dialect, so this row is "
        f"measuring the host's notion of absoluteness rather than the patch:\n{out}"
    )
    assert "EMULATION_EAGER" in out, f"the emulation is not an eager capture - it describes another shape:\n{out}"
    if "nt" in (capture, host):
        assert "ROUTE_ARMED" in out, (
            "the nt-shaped realpath did not read the cwd for an ABSOLUTE path, so "
            f"this world is not the one that broke on the Windows runner:\n{out}"
        )


def test_the_captured_accessor_is_inert_under_a_bare_os_path_patch():
    """3.10's defect, rebuilt: patching os.path.realpath does not reach it."""
    result = _run(_capture_world("sentinel"))
    out = result.stdout

    _assert_emulation_sound(out, "sentinel")
    assert "CAPTURE_INERT CAPTURED" in out, (
        "the bare os.path patch reached the captured copy, so there is nothing "
        f"for _ACCESSOR_PATCH to fix and this file is carrying dead weight:\n{out}"
    )


def test_the_shipped_accessor_patch_arms_the_captured_copy():
    """_ACCESSOR_PATCH is load-bearing: remove it and this pin goes red."""
    result = _run(_capture_world("sentinel", apply_patch=True))
    out = result.stdout

    _assert_emulation_sound(out, "sentinel")
    assert "CAPTURE_ARMED" in out, (
        "the shipped accessor patch did not arm the captured copy - on 3.10 the "
        f"dead-cwd worlds are inert and every pin under them is vacuous:\n{out}"
    )


def test_the_accessor_patch_needs_staticmethod_not_a_bare_function():
    """Why _ACCESSOR_PATCH wraps: bare, the instance is eaten into the path slot.

    Without this, someone simplifies the fragment to a plain assignment, the
    call fails with TypeError instead of FileNotFoundError, and a pin that only
    asks "did it raise" reports a cured world.
    """
    result = _run(_capture_world("sentinel", bare_rebind=True))
    out = result.stdout

    _assert_emulation_sound(out, "sentinel")
    assert "PLAIN_EATS_SELF" in out, (
        "a bare function rebind did NOT bind as a method here - the staticmethod "
        f"wrapper in _ACCESSOR_PATCH may no longer be doing anything:\n{out}"
    )
    assert "CAPTURE_ARMED" not in out, f"the bare rebind looked like a working denial, which is the trap:\n{out}"


@pytest.mark.parametrize("host", ["posix", "nt"])
def test_the_inert_verdict_does_not_move_between_host_dialects(host: str):
    """@memory's litmus: run the probe under the opposite platform's dialect and
    require the verdict NOT to move.

    The capture is held fixed at the sentinel and the SURROUNDING realpath is
    swapped, which is the variable that actually moved between the Linux and
    Windows runners. This is the round-7 regression pin: revert the sentinel to
    a live capture and the nt row goes red HERE, on Linux, instead of on the
    Windows runner three hours later.
    """
    result = _run(_capture_world("sentinel", host=host))
    out = result.stdout

    _assert_emulation_sound(out, "sentinel", host)
    assert "CAPTURE_INERT CAPTURED" in out, f"the sentinel verdict moved under the {host} host dialect:\n{out}"


@pytest.mark.parametrize(
    ("dialect", "expected"),
    [("posix", "CAPTURE_INERT"), ("nt", "CAPTURE_ARMED")],
)
def test_the_litmus_is_armed_by_a_shape_whose_verdict_does_move(dialect: str, expected: str):
    """The arming for the litmus above (@skills' trap (d)).

    A run-under-both-dialects check is vacuously green if the dialect slot
    reaches nothing - and with a sentinel it reaches nothing BY DESIGN. So one
    shape whose verdict is SUPPOSED to move has to be measured beside it: the
    PRE-CURE live capture, which reads INERT on posix and ARMED on nt for two
    different reasons. That divergence IS the round-7 failure, reproduced on
    this host rather than quoted from a CI log.
    """
    result = _run(_capture_world(dialect, host=dialect))
    out = result.stdout

    _assert_emulation_sound(out, dialect, dialect)
    assert expected in out, (
        f"the pre-cure {dialect} capture no longer reads {expected} - the failure "
        f"this file was rebuilt around has stopped reproducing:\n{out}"
    )


# A stand-in for each host's sys.executable, which is what the probe path used to
# be. Absolute to its own dialect and to nothing else - which is the entire bug.
_HOST_SHAPED_EXECUTABLE = {
    "posix": "/usr/bin/python3",
    "nt": "D:\\a\\AIPass\\AIPass\\.venv\\Scripts\\python.exe",
}


@pytest.mark.parametrize("host_shape", ["posix", "nt"])
def test_a_host_shaped_probe_path_is_refused_rather_than_silently_answered(host_shape: str):
    """The round-8 regression pin, and it convicts the INSTALLER not the world.

    Round 7's probe path was sys.executable: absolute in the running host's
    dialect and nobody else's. On the Windows runner posixpath.isabs() of it is
    False, so the posix capture treated it as relative, joined the denied cwd,
    and reported ARMED - and the row announced "the failure this file was rebuilt
    around has stopped reproducing", which was a statement about the probe
    wearing the words of a statement about the subject.

    So the world now REFUSES a probe that is not absolute in both dialects and
    says which thing is wrong, rather than answering a question it can no longer
    read (@spawn's UNAVAILABLE-with-a-reason). This pin runs both host shapes on
    this machine, so neither leg of the matrix has to discover it.
    """
    result = _run(_capture_world("posix", probe=_HOST_SHAPED_EXECUTABLE[host_shape]))
    out = result.stdout

    if host_shape == "posix":
        # Absolute to posixpath here, so the row can still answer - and must.
        assert "PROBE_IS_ABS True" in out, out
        assert "CAPTURE_INERT" in out, f"a posix-absolute probe stopped being inert against the posix capture:\n{out}"
        return

    assert "PROBE_IS_ABS False" in out, (
        "an nt-shaped executable path was accepted as absolute - "
        f"posixpath.isabs() must reject it, or round 8 can happen again:\n{out}"
    )
    with pytest.raises(AssertionError, match="not absolute to posixpath"):
        _assert_emulation_sound(out, "posix")


@pytest.mark.parametrize("host_shape", ["posix", "nt"])
def test_the_probe_path_does_not_follow_the_hosts_executable(host_shape: str):
    """Convicts the round-8 defect ITSELF on this machine, not just its symptom.

    The pin above proves the world refuses a bad probe when one is handed to it.
    This one proves the world does not GO AND FETCH a bad one: sys.executable is
    spoofed to each platform's shape before the world computes _ABS, and the
    verdict must not move. A literal is immune; anything derived from the host -
    sys.executable, os.getcwd(), __file__ - is convicted here rather than on the
    runner that happens to have the other shape.
    """
    result = _run(_capture_world("posix", spoof_executable=_HOST_SHAPED_EXECUTABLE[host_shape]))
    out = result.stdout

    _assert_emulation_sound(out, "posix")
    assert "CAPTURE_INERT" in out, (
        f"the posix arming row moved when sys.executable took its {host_shape} shape - "
        f"the probe path is following the host again:\n{out}"
    )


def test_the_shipped_probe_path_is_absolute_to_the_strict_dialect():
    """The positive half: the literal actually shipped satisfies the rule.

    Without this the pin above passes on a world that refuses EVERYTHING, which
    would be a refusal wearing a control's name.
    """
    result = _run(_capture_world("posix"))

    assert "PROBE_IS_ABS True" in result.stdout, result.stdout
    _assert_emulation_sound(result.stdout, "posix")


def test_repo_root_fallback_is_the_source_tree_never_the_process_directory():
    """The QUIET defect: four walks used to end in `return Path.cwd()`.

    A registry-less tree (every clean clone; AIPASS_REGISTRY.json is gitignored)
    took that fallback on every import, so each caller resolved against whatever
    directory the shell happened to be in. Pinned from a child process standing
    somewhere unrelated, because in-process the cwd is the repo root and the
    wrong answer and the right one look identical.
    """
    world = r"""
import os
import tempfile
from pathlib import Path

os.chdir(tempfile.gettempdir())

from aipass.trigger.apps.handlers.repo_root import SOURCE_ROOT, find_repo_root

# A marker that exists nowhere above this file forces the fallback.
answer = find_repo_root(marker="AIPASS_NO_SUCH_MARKER.json", caller="pin")
print("ANSWER", answer)
print("SOURCE_ROOT", SOURCE_ROOT)
print("CWD", Path.cwd())
"""
    result = _run(world)
    lines = dict(line.split(" ", 1) for line in result.stdout.strip().splitlines() if " " in line)

    assert lines.get("ANSWER") == lines.get("SOURCE_ROOT"), (
        f"the fallback is no longer the source tree:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert lines.get("ANSWER") != lines.get("CWD"), (
        "the child stood in the repo root, so this run could not tell the source "
        f"tree from the process directory - the pin measured nothing:\n{result.stdout}"
    )


def test_repo_root_refuses_a_case_folded_marker(tmp_path, monkeypatch):
    """A cased literal folds too: exists() answers about `aipass_registry.json`.

    find_repo_root decides which installation this branch belongs to and several
    callers build write paths from the answer, so a folded bait file accepted as
    THE repo root is the quiet defect arriving through a different door.

    THE FOLDING IS INJECTED, not waited for. On ext4 the bait cannot fire, so a
    test that merely places a lowercase file and asserts refusal passes for the
    wrong reason - measured: a mutant degrading exists_exactly() to a bare
    exists() SURVIVED that shape on Linux. Path.exists is given the answer a
    folding filesystem would give, which is the call the defect actually makes.
    """
    from aipass.trigger.apps.handlers import repo_root

    bait_dir = tmp_path / "bait"
    bait_dir.mkdir()
    (bait_dir / "aipass_registry.json").write_text("{}", encoding="utf-8")
    start = bait_dir / "deep"
    start.mkdir()

    real_exists = Path.exists

    def folding_exists(self, *args, **kwargs):
        if real_exists(self, *args, **kwargs):
            return True
        try:
            names = {entry.name.lower() for entry in self.parent.iterdir()}
        except OSError:
            return False
        return self.name.lower() in names

    monkeypatch.setattr(Path, "exists", folding_exists)

    # The instrument must be live, or this pin proves nothing.
    assert (bait_dir / "AIPASS_REGISTRY.json").exists(), "the folding injection never fired"

    assert not repo_root.exists_exactly(bait_dir / "AIPASS_REGISTRY.json"), (
        "a case-folded bait file was accepted as the blessed filename"
    )
    assert repo_root.find_repo_root(start, caller="pin") != bait_dir, (
        "the walk stopped at a directory holding aipass_registry.json"
    )

    # And the exact spelling is still accepted, under the same injected world.
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    assert repo_root.exists_exactly(real_dir / "AIPASS_REGISTRY.json")
    assert repo_root.find_repo_root(real_dir, caller="pin") == real_dir


def test_the_folding_injection_is_a_real_negative_control(tmp_path, monkeypatch):
    """The control FOR the control: without the injection, the bait is inert.

    Proves the previous test's refusal comes from exists_exactly and not from
    ext4 answering no - a green that would survive deleting the cure.
    """
    from aipass.trigger.apps.handlers import repo_root

    bait_dir = tmp_path / "bait"
    bait_dir.mkdir()
    (bait_dir / "aipass_registry.json").write_text("{}", encoding="utf-8")

    if (bait_dir / "AIPASS_REGISTRY.json").exists():
        # A genuinely folding host: the injection is redundant there, and the
        # pin above measures the live condition rather than an emulation.
        assert not repo_root.exists_exactly(bait_dir / "AIPASS_REGISTRY.json")
    else:
        # Case-sensitive host: the bait is invisible WITHOUT the injection,
        # which is exactly why the injection exists.
        assert not repo_root.exists_exactly(bait_dir / "AIPASS_REGISTRY.json")


# ===========================================================================
# The deleted second stack walk — reachable only OUTSIDE an import
# ===========================================================================
#
# @cli's finding, 2026-08-31, and it landed on this branch too: the guard's
# `caller_file is None` branch is UNREACHABLE from any import-shaped pin. During
# a real import apps/__init__.py does `from . import handlers`, so there is
# always a real-file frame above the guard and _find_real_caller never returns
# None. MEASURED HERE: restoring the deleted inspect.stack() walk as a mutant
# passed all 1058 trigger tests, including every world above. Five green pins and
# the defect back in the tree.
#
# The branch is reachable exactly where it was meant to be — a REPL or a -c
# script, the callers it exists to allow — so the world calls the guard directly
# instead of importing something.

NO_CALLER_WORLD = (
    _NTPATH_PREAMBLE
    + r"""
from aipass.trigger.apps.handlers import _find_real_caller, _guard_branch_access

# Positive control: this world must actually REACH the branch under test.
# A -c frame is spelled "<string>", which the walk skips, so there is no
# caller outside this file and the guard takes its None arm.
caller, line = _find_real_caller()
if caller is None:
    print("NO_CALLER_REACHED")
else:
    print("NO_CALLER_NOT_REACHED", caller)

_guard_branch_access()
print("IMPORTED")
"""
)


def test_the_no_caller_branch_needs_no_cwd():
    """The guard's `caller_file is None` arm, under the ntpath-shaped denial.

    Red against a restored second inspect.stack() walk, which no import world
    can reach. Credited to @cli, who found it by mutating their own identical
    deletion and watching it stroll past five green pins.
    """
    result = _run(NO_CALLER_WORLD)
    out = result.stdout

    assert "STACK_DIES" in out, f"the ntpath world went vacuous - this pin proves nothing:\n{out}"
    assert "NO_CALLER_REACHED" in out, (
        f"the guard found a caller, so its None arm never ran and this pin measured nothing:\n{out}"
    )
    assert "IMPORTED" in out, (
        f"the guard's no-caller arm still depends on a readable cwd:\nstdout={out}\nstderr={result.stderr}"
    )
