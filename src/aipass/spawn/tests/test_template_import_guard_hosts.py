# =================== AIPass ====================
# Name: test_template_import_guard_hosts.py
# Description: The realpath denial and the guard's test harness, measured on hosts this box is not
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
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

# Every host stand-in states what it needs from the host, reports whether it took, and stands down
# where the host already IS the thing it stands in for: keyed on facts the child measures, never a version.
# Where the interpreter has the accessor natively (<=3.10) it is measured, not emulated over.

# The emulation CI convicted, kept as the negative control every host shape below must fail.
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

# Host shapes, built from halves; each half prints HALF:<name>:NATIVE | INSTALLED | UNAVAILABLE:<reason>.
# UNAVAILABLE is a SKIP carrying the child's reason: "cannot be built here" is not "broken".

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

# The real _PosixFlavour carries parsing and no realpath; the tolerant stand-in above cannot show that.
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
    "3.12-as-it-is": (),
    "3.10-native-accessor-and-flavour-object": (_HALF_FLAVOUR_OBJECT, _HALF_ACCESSOR_ROUTE),
    "3.11-flavour-object-and-direct-resolve": (_HALF_FLAVOUR_OBJECT, _HALF_DIRECT_RESOLVE),
    "3.13-no-accessor-direct-resolve": (_HALF_DIRECT_RESOLVE,),
    "nt-concrete-class-is-not-posix": (_HALF_FOREIGN_CONCRETE_CLASS,),
}

# The old emulation's symptom depends on the COMPOSED world (host flavour x shape), not the shape name;
# the foreign-class shape carries its own flavour copy, so the emulation's write never reaches it.
_FOREIGN_CLASS_SHAPE = "nt-concrete-class-is-not-posix"


def _expected_old_emulation_symptom(flavour_in_force: str, shape: str) -> str:
    """Two rows, each read off a CI traceback rather than reasoned about.

    parse_parts where parsing travels through an OBJECT flavour on a posix class; ROUTE_DARK elsewhere.
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

    Every test runs under each HOST SHAPE, so "arms on every interpreter" is measured, not promised.
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
        """Refuse to read a verdict out of a child whose route never armed."""
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
        """Native or stand-in — the child names it, so no run is ambiguous."""
        lines = self._armed(self._child(shape, _BARE_REBINDING_ONLY), shape)

        # Keyed on what the child FOUND, not the shape name or version: on 3.10 every row is ACCESSOR_NATIVE.
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

        If _NormalAccessor310 captured lazily, the rebinding would reach it and report PATHLIB_ARMED.
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

        If this goes green, the shape stopped reproducing the interpreter that convicted it.
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

        # The symptom is derived from what the child MEASURED, not from the shape's name.
        in_force = _flavour_in_force(result)
        if in_force == "unknown":
            pytest.fail(
                f"the child never printed its HOST fingerprint under shape {shape!r}, so "
                f"which symptom to expect cannot be derived:\n{result.stdout}\n{result.stderr}"
            )

        symptom = _expected_old_emulation_symptom(in_force, shape)
        # Token-matched in stdout: the emulation prints its own ROUTE_WAS_DARK, which a substring could accept.
        convicted_as_predicted = symptom in result.stdout.split() or symptom in result.stderr
        assert convicted_as_predicted, (
            f"host shape {shape!r} with a {in_force!r} flavour in force convicted the old "
            f"emulation, but not with the symptom that composition predicts ({symptom!r}) — "
            f"it is reproducing some other half of that interpreter:\n{result.stdout}\n{result.stderr}"
        )

    # The recorder replaces the world's `_no_realpath`, so the SHIPPED _ARM_PATHLIB_ACCESSOR text is measured.
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

        A plain function on the accessor CLASS binds and eats the path into self; a raising denial never notices.
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

        An instance attribute shadows the class descriptor, so the class half could no longer be falsified.
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

        Both worlds report CONTROL_DEAD; only which world asked separates skip from fail.
        """

        class _FakeResult:
            stdout = "CONTROL_DEAD\n"
            stderr = ""

        # Not pytest.raises(Failed): a Skipped sails through it and retires the test as SKIPPED.
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

        ROUTE_ARMED is load-bearing in _armed(), so the child must be able to print ROUTE_DARK.
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
        """hasattr-guarded, so 3.11+ is untouched rather than version-checked."""
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


# Simulations make this interpreter present other hosts' plumbing; each declares which shapes it speaks
# for and which real hosts it can speak from, and both are gates.


# 3.10's parsing consumer reduced to one call, so the dialect probe has something to say NO against.
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
    """Which test rows compose the old emulation without declaring their hosts."""
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


# Any row that installs a module-shaped flavour needs a host whose pathlib is content with one.
_A_MODULE_SHAPED_FLAVOUR_NEEDS_A_TOLERANT_HOST = {"parsing": ("module-tolerant",)}


# name -> (prelude, the shapes it is meaningful for, the real hosts it can speak from)
_HOST_SIMULATIONS = {
    # 3.10/3.11 flavour is already an OBJECT: the half must say NATIVE before touching _parse_path.
    "flavour-is-already-an-object": (
        _HALF_FLAVOUR_OBJECT,
        sorted(_HOST_SHAPES),
        # On a flavourless or WindowsPath host the half reports UNAVAILABLE and presents nothing.
        {"flavour": ("object", "module"), "concrete": ("posix",)},
    ),
    # pathlib.Path is inherited from on every version, so the accessor half has no precondition.
    "accessor-route-is-already-native": (_HALF_ACCESSOR_ROUTE, sorted(_HOST_SHAPES), {}),
    "purposixpath-has-no-flavour": (
        """
        import pathlib

        class _FlavourlessPurePosixPath:
            pass

        pathlib.PurePosixPath = _FlavourlessPurePosixPath
        """,
        [name for name in sorted(_HOST_SHAPES) if _HALF_FLAVOUR_OBJECT in _HOST_SHAPES[name]],
        # On nt the half refuses for the WindowsPath reason first, not the simulated one.
        {"concrete": ("posix",)},
    ),
    # A module flavour without 3.12's parsing: no released interpreter is both, so it is simulated.
    "purepath-has-no-parse-path": (
        """
        import pathlib

        class _PurePathWithoutParsePath:
            pass

        pathlib.PurePath = _PurePathWithoutParsePath
        """,
        [name for name in sorted(_HOST_SHAPES) if _HALF_FLAVOUR_OBJECT in _HOST_SHAPES[name]],
        # Aims at the half's LAST branch; an object-flavour host answers NATIVE first and never reaches it.
        {"flavour": ("module",), "concrete": ("posix",)},
    ),
}

_SIMULATION_PAIRS = sorted(
    (simulation, shape) for simulation, (_, shapes, _requires) in _HOST_SIMULATIONS.items() for shape in shapes
)

# Marks where the simulation's own half verdicts end and the shape's begin.
_SIMULATION_DONE = 'print("SIMULATION_INSTALLED")'

_LEGAL_HALF_VERDICTS = ("NATIVE", "INSTALLED", "UNAVAILABLE")


class TestTheHarnessSurvivesAHostThatIsNotTheOneItWasWrittenOn:
    """Round 8's actual subject: the stand-ins, not the thing they stand in for."""

    def _speak_or_skip(self, simulation: str) -> None:
        """One gate, in front of every test in this class."""
        why = _simulation_unavailable(_HOST_SIMULATIONS[simulation][2], _HOST_FACTS)
        if why:
            pytest.skip(f"{simulation}: {why}")

    def _simulated(self, simulation: str, *chunks: str) -> str:
        """The ONE place a simulated host is installed, gated and re-measured."""
        self._speak_or_skip(simulation)
        return _child_script(
            _HOST_SIMULATIONS[simulation][0],
            _SIMULATION_DONE,
            # Re-measured: the halves decide against the simulated host, not the starting one.
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
        """The whole round-8 species, in one assertion per pair."""
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

        On 3.10/3.11 the half must answer NATIVE without asking for _parse_path; reorder the checks and this is red.
        """
        result = self._child("flavour-is-already-an-object", "3.11-flavour-object-and-direct-resolve")

        # Read the SHAPE's half: the simulation is built from the same half and may print NATIVE itself.
        assert "HALF:flavour-object:NATIVE" in self._shape_halves(result), (
            f"the SHAPE's flavour half did not stand down:\n{result.stdout}\n{result.stderr}"
        )
        assert "Traceback" not in result.stderr, result.stderr

    def test_an_unavailable_half_skips_rather_than_failing(self):
        """The gate itself, which no shape on this host can reach."""

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

        Needs a module-tolerant host: on 3.10/3.11 the child dies of parse_parts first, so the row skips.
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

        On 3.10/3.11 the copied flavour is an object with no realpath; the cure asks instead of assuming.
        """
        # No _EMULATE_310: it replaces Path.resolve, which on this shape IS the foreign class's resolve under test.
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

        The concrete kind must be DERIVED from os.name; a hard-coded "posix" passes every behavioural pin on Linux.
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

        The nt branch is the half's FIRST question, so this is speakable from every host.
        """
        refusal = self._flavour_half_verdict('_CONCRETE_KIND = "nt"')

        assert refusal.startswith("HALF:flavour-object:UNAVAILABLE:"), refusal
        assert "WindowsPath" in refusal, f"the refusal does not name what it is refusing for: {refusal!r}"

    # A host whose flavour is already an object answers NATIVE, as 3.10 and 3.11 do.
    _CONTROL_HOSTS = {
        "as-this-host-is": (),
        "with-an-object-flavour-already-installed": (_HALF_FLAVOUR_OBJECT,),
    }

    @pytest.mark.parametrize("control_host", sorted(_CONTROL_HOSTS))
    def test_forcing_the_posix_branch_leaves_the_row_where_the_host_put_it(self, control_host):
        """The control for the refusal above, and round 10's first red.

        Forcing posix must leave the verdict where the host put it and forcing nt must move it: nothing spelled.
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

        If the probe could only say "module-tolerant", every skip keyed on it would be vacuous.
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
        """The gate's DECISION, reachable from a host that is none of those."""
        # Patched on the module OBJECT: this file is collected under two rootdirs with different import names.
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
    """The judgements, separated from the worlds that feed them — @commons' rule."""

    @pytest.mark.parametrize(
        ("flavour_in_force", "shape", "expected"),
        [
            ("object", "3.10-native-accessor-and-flavour-object", "parse_parts"),
            ("object", "3.11-flavour-object-and-direct-resolve", "parse_parts"),
            # Cross term: the HOST supplies the flavour the 3.13-named shape never mentions.
            ("object", "3.13-no-accessor-direct-resolve", "parse_parts"),
            # The foreign class carries its own flavour copy, which the emulation's write cannot reach.
            ("object", "nt-concrete-class-is-not-posix", "ROUTE_DARK"),
            ("absent", "3.10-native-accessor-and-flavour-object", "ROUTE_DARK"),
            ("absent", "3.11-flavour-object-and-direct-resolve", "ROUTE_DARK"),
            ("absent", "nt-concrete-class-is-not-posix", "ROUTE_DARK"),
            ("module", "3.10-native-accessor-and-flavour-object", "ROUTE_DARK"),
            ("module", "3.13-no-accessor-direct-resolve", "ROUTE_DARK"),
            # No interpreter reports this: an unrecognised fingerprint falls to the always-true mechanism.
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
            ("flavour-is-already-an-object", _A_312, True),
            ("flavour-is-already-an-object", _A_310, True),
            ("flavour-is-already-an-object", _A_313, False),
            ("flavour-is-already-an-object", _WINDOWS, False),
            # The backstop aims at the half's LAST branch, which an object-flavour host never reaches.
            ("purepath-has-no-parse-path", _A_312, True),
            ("purepath-has-no-parse-path", _A_310, False),
            ("purepath-has-no-parse-path", _A_313, False),
            ("accessor-route-is-already-native", _A_313, True),
            ("accessor-route-is-already-native", _WINDOWS, True),
            ("accessor-route-is-already-native", _UNREADABLE, True),
            # An unmeasured host may not be claimed by any simulation with a precondition.
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
            ("demands:parse_parts", False),
            ("demands:something", False),
            # An unmeasurable host fails CLOSED.
            ("unknown:TypeError", False),
            ("unknown", False),
        ],
    )
    def test_a_module_shaped_flavour_declares_which_hosts_it_can_serve(self, parsing, speaks):
        """Round 10's judgement, with every host this box is not.

        Delegation cannot cure a consumer that calls methods the delegate never had: declare and skip.
        """
        why = _simulation_unavailable(_A_MODULE_SHAPED_FLAVOUR_NEEDS_A_TOLERANT_HOST, {"parsing": parsing})

        assert (why == "") is speaks, f"{parsing}: {why!r}"
        if not speaks:
            assert parsing in why, f"the refusal does not carry the host's own answer: {why!r}"

    # The one exempt row, with its reason; any other test composing the old emulation must declare.
    _ROWS_THAT_MAY_MEET_AN_OBJECT_DIALECT_HOST = {
        "test_the_previous_emulation_dies_against_the_shape_it_assumed_away": (
            "its expectation IS the crash: the symptom judgement predicts "
            "parse_parts on exactly the hosts whose pathlib asks for it, and the "
            "expectation is derived from the flavour the CHILD measured"
        ),
    }

    def test_every_world_with_a_module_shaped_flavour_declares_or_derives(self):
        """The sweep, kept from rotting — @skills' lower-bound rule as a pin.

        A flagged list is a lower bound, so the rule is structural; mentioning the judgement is not declaring.
        """
        offenders = _rows_missing_a_dialect_declaration(
            Path(__file__).read_text(encoding="utf-8"), self._ROWS_THAT_MAY_MEET_AN_OBJECT_DIALECT_HOST
        )

        assert offenders == [], (
            "these tests install a module-shaped flavour without saying which "
            "hosts can carry one and without deriving the symptom: " + ", ".join(offenders)
        )

    def test_the_dialect_sweep_reports_a_row_that_does_not_declare(self):
        """The negative control for the sweep — it has to be able to say YES."""
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

        posix turns on whether the path READS absolute; nt's ntpath.realpath reads getcwd unconditionally.
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
        # Closed set: module-tolerant, or demands:<named attribute>; a bare "demands:" fails too.
        dialect, colon, demanded = _HOST_FACTS["parsing"].partition(":")
        assert dialect in ("module-tolerant", "demands"), _HOST_FACTS["parsing"]
        assert (dialect == "demands") is bool(colon and demanded.strip()), (
            f"a demanding host must name the attribute it demanded: {_HOST_FACTS['parsing']!r}"
        )


def _drive_row_is_satisfied(os_name: str, anchor_drive: str) -> bool:
    """Does this host's ntpath.abspath answer the way its own row says it must?"""
    if os_name == "nt":
        return bool(anchor_drive)
    if os_name == "posix":
        return anchor_drive == ""
    return False


class TestTheProbeLiteralNamesAnAbsolutePathOnTheRunner:
    """@devpulse's trap (b), split into the half I can measure and the half I cannot.

    Drive-relative is measured here (pure ntpath); the Windows value is answered by the runner (PROBE_NO_DRIVE).
    """

    @pytest.mark.parametrize(
        ("os_name", "anchor_drive", "expected"),
        [
            ("posix", "", True),
            ("posix", "D:", False),
            ("nt", "D:", True),
            ("nt", "", False),
            # No machine produces this: the judgement must answer inputs the host cannot manufacture.
            ("plan9", "", False),
        ],
    )
    def test_the_drive_judgement_answers_for_hosts_this_one_is_not(self, os_name, anchor_drive, expected):
        """The judgement, separated from the world that feeds it."""
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
