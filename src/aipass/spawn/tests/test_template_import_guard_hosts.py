# =================== AIPass ====================
# Name: test_template_import_guard_hosts.py
# Description: The realpath denial and the guard's test harness, measured on hosts this box is not
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for the worlds that pin templates/citizen/apps/handlers/__init__.py, measured across hosts."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — Path.resolve and ntpath.realpath on other interpreters, emulated here, never run

import ast
import ntpath
import os
import sys
import textwrap
from pathlib import Path

import pytest
from _pytest.outcomes import Failed, Skipped

from aipass.spawn.tests.support_template_import_guard import (
    _ARM_PATHLIB_ACCESSOR,
    _ARM_THE_ROUTE,
    _BUILD_PROBE_PATH,
    _DENY_REALPATH,
    _EMULATE_310,
    _HOST_FACTS,
    _PATHLIB_ROUTE_PROBE,
    _PLATFORM_EMULATIONS,
    _REPORT_HOST,
    _REPORT_PARSING_DIALECT,
    _child_script,
    _compose,
    _host_line,
    _parsing_answer,
    _require_live_world,
    _run,
    _simulation_unavailable,
)

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
        verdict = ("ROUTE_ARMED" in lines, "PATHLIB_INERT" in lines)
        assert verdict != (True, True), (
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
        except Skipped as exc:
            raise Failed("the gate SKIPPED an inert realpath-denied world instead of failing it") from exc
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


# The requirement a WORLD carries, not a simulation: any row that installs a
# module-shaped flavour needs a host whose pathlib is content with one. Written
# as a fact-keyed dict so it goes through the same judgement as every other
# speakable-hosts declaration in this file.
_A_MODULE_SHAPED_FLAVOUR_NEEDS_A_TOLERANT_HOST = {"parsing": ("module-tolerant",)}


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

        assert offenders == [], (
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
        exemptions = self._ROWS_THAT_MAY_MEET_AN_OBJECT_DIALECT_HOST
        assert len(exemptions) == 1, (
            f"the exemption list holds {sorted(exemptions)} - an emptied list would make this sweep silent"
        )
        for name, reason in exemptions.items():
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
        # Round 10's fact, said as a closed set rather than an either/or. The host
        # is content with a module-shaped flavour, or it NAMES what it asked for —
        # "unknown" would mean the probe could not even install one, a fifth state
        # nobody has seen that would take every world built on it dark without
        # saying why. Stated this way the bare "demands:" with nothing after the
        # colon fails too, which the old startswith() clause let through.
        # Measured on this box 2026-09-08: module-tolerant.
        dialect, colon, demanded = _HOST_FACTS["parsing"].partition(":")
        assert dialect in ("module-tolerant", "demands"), _HOST_FACTS["parsing"]
        assert (dialect == "demands") is bool(colon and demanded.strip()), (
            f"a demanding host must name the attribute it demanded: {_HOST_FACTS['parsing']!r}"
        )


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
