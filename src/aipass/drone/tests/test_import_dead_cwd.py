# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Every drone module imports without a readable working directory
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""Drone must import, and must keep logging, with no working directory.

THE MECHANISM, measured on the Windows CI gate 2026-08-31 (@memory's finding,
relayed by @devpulse). ``ntpath.realpath`` calls ``os.getcwd()``
UNCONDITIONALLY — on its first lines, before it even asks whether the path is
absolute — where ``posixpath`` only reads the cwd for a relative one. And
``Path.resolve()`` routes through ``os.path.realpath``. So on Windows every
module-level ``Path(__file__).resolve()`` is an import-time working-directory
dependency, and a process whose cwd is gone cannot import the module at all.
Guarding INSIDE that module's functions changes nothing: the import died before
any of them existed.

``inspect.stack()`` carries the same defect one layer down and needs a
different world to convict it. It builds a ``FrameInfo`` per frame, and for a
frame whose filename is a PSEUDO-file it reaches ``getmodule()``, whose
``os.path.realpath(f)`` sits outside every ``try`` in that function. On POSIX
the equivalent raise happens EARLIER, inside ``getabsfile()``, where
``inspect`` catches it — which is exactly why a call on drone's every-import
path survived years of Linux CI carrying this.

TWO WORLDS, and @seedgo's asymmetry is why both are here rather than one:

* **World A** emulates ntpath — ``os.path.realpath`` is wrapped to read
  ``os.getcwd()`` first, then ``os.getcwd`` is denied. This convicts a raw
  ``resolve()``. It does NOT convict ``inspect.stack()`` on Linux, because
  ``getabsfile`` raises inside inspect's own catch before ``getmodule`` is
  reached.
* **World B** denies ``os.path.realpath`` outright while ``abspath`` keeps
  working. This is what reaches ``getmodule``'s unguarded call and convicts
  ``inspect.stack()``.

THIRD INGREDIENT for world B (@hooks): the frame must be ``<string>`` —
an interpreter ``-c`` or ``compile()`` frame — and NEVER ``<stdin>``. A heredoc-fed
child puts ``<stdin>`` in ``linecache.cache``, ``getsourcefile`` early-returns,
and the probe reports green while the same world kills imports for real. Every
assertion below is preceded by a control that states whether its world is armed,
so a probe that quietly stopped biting cannot pass itself off as a cure.

WHAT DRONE CARRIED, measured not estimated. Before this build, 63 of 63 drone
modules died on import in BOTH worlds — every one of them at
``handlers/__init__.py:57``, the module-level ``_BRANCH_ROOT`` resolve. That
line MASKED everything under it, which is why the count only became true as
cures landed: curing the guard took it to 56/63 and revealed
``json_handler.py:41``, and curing the three module-level sites took it to 0.
Session 74's inner ``try/except OSError`` around the frame-filename resolve was
below both crash lines the whole time — decorative, exactly as @trigger and
@prax found in their own trees.

And one live site that no import probe reaches: ``log_operation`` is the audit
line drone writes on essentially every operation, and its
``_get_caller_module_name`` called ``inspect.stack()``. Under world B, called
across a ``<string>`` frame, it raised ``FileNotFoundError`` — drone's logging
taking down the caller it was logging for, on the very recovery lane (``drone
rm`` from a directory that was just deleted) sessions 68 and 77 exist to keep
alive.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

# Other branches' import-time code is held CONSTANT: preloaded in the healthy
# world, before any denial. Their cure is their own build; this file measures
# drone's sites and must not go red in someone else's name. These are drone's
# only cross-branch module-level imports, and they are TEMPORARY — delete a
# line once that branch's own dead-cwd pin is green.
_PRELOAD = """
from aipass.prax import logger  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401
import aipass.api  # noqa: F401
"""

# THE ACCESSOR PATCH, and it is the difference between a world and a costume.
#
# CI found this on the Python 3.10 leg of 8550ed10: the arming probe below
# printed RESOLVE_DIES: NO and the pin REFUSED rather than passing vacuously.
# @devpulse relayed the mechanism and @memory corrected the first diagnosis by
# reading CPython's source, so this is the corrected version:
#
#     CPython 3.10 Lib/pathlib.py
#       358:  realpath = staticmethod(os.path.realpath)       # _NormalAccessor
#       1077: s = self._accessor.realpath(self, strict=strict)  # Path.resolve
#
# 3.10 DOES delegate resolve() to os.path.realpath — it simply took its COPY
# when pathlib was first imported. So a world that rebinds ``os.path.realpath``
# afterwards rebinds a name nothing will read again, and every pin under it is
# green while asserting nothing. 3.11 deleted the accessor and calls
# os.path.realpath at use, which is why exactly one interpreter reddened.
#
# The cure patches the captured accessor as well, which also makes the world
# ORDER-INDEPENDENT: a child may import pathlib before or after installing it.
# No version table and no skipif — the same text arms on every interpreter.
#
# TWO EDGES, both @memory's, both honoured:
#   * ``staticmethod`` AND ``*a`` are redundant with each other on purpose. A
#     plain function stored on a class arrives BOUND through an instance, so it
#     would eat the accessor as its first positional argument. staticmethod
#     prevents the binding; ``*a`` survives it if a future edit drops the
#     staticmethod. Keeping one and deleting the other is how the remaining half
#     silently becomes load-bearing.
#   * a bound wrapper that ate the path would still call os.getcwd() first and
#     still raise, so a raise-shaped probe stays green FOR THE WRONG REASON.
#     test_the_ntpath_wrapper_resolves_the_path_not_the_accessor pins the value
#     it returns, through a sentinel so the answer is the wrapper's and not the
#     host path module's.
#
# THE PATCH IS CLASS-LEVEL ONLY, AND THAT IS A MEASUREMENT RATHER THAN A COPY.
# The first cut here also assigned ``_pathlib._normal_accessor.realpath`` on the
# INSTANCE. It looked like harmless belt-and-braces and it was not: an instance
# attribute is never bound, so it SHADOWED the class attribute and made the
# class-level ``staticmethod`` unfalsifiable — mutant M24b dropped it and all 16
# pins stayed green. Removing the instance line turns that same mutant red. 3.10
# stores no per-instance ``realpath``, so the class patch is what its
# ``self._accessor.realpath(...)`` actually reaches; the extra line bought
# nothing and cost the only pin that watches the binding. @memory has adopted the
# same refusal, crediting drone's M24b, against @spawn's belt-and-braces form.
_NTPATH_WRAPPER = """
import os

_real_realpath = os.path.realpath


def _ntpath_condition(path, *a, **kw):
    os.getcwd()  # ntpath.realpath reads cwd before checking absoluteness
    return _real_realpath(path, *a, **kw)


os.path.realpath = _ntpath_condition

import pathlib as _pathlib_rp

if hasattr(_pathlib_rp, "_NormalAccessor"):
    _pathlib_rp._NormalAccessor.realpath = staticmethod(_ntpath_condition)
"""

_DENY_GETCWD = """
def _dead_getcwd(*a, **k):
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd
"""

_WORLD_A = _NTPATH_WRAPPER + _DENY_GETCWD

_WORLD_B = """
import os


def _dead_realpath(path, *a, **kw):
    raise FileNotFoundError(2, "realpath denied", "")


os.path.realpath = _dead_realpath

import pathlib as _pathlib_dr

if hasattr(_pathlib_dr, "_NormalAccessor"):
    _pathlib_dr._NormalAccessor.realpath = staticmethod(_dead_realpath)
"""

# 3.10's pathlib reduced to the two lines that matter, installed ON PURPOSE so
# the accessor row is falsifiable on an interpreter that no longer has one. It
# captures the REAL os.path.realpath BEFORE the world is installed, which is
# exactly the ordering 3.10 produces by importing pathlib early.
_FAKE_ACCESSOR = """
import os
import pathlib as _p


class _NormalAccessor:
    realpath = staticmethod(os.path.realpath)


_p._NormalAccessor = _NormalAccessor
_p._normal_accessor = _NormalAccessor()
"""

# @memory's SENTINEL, and it is the cure for drone's one windows-setup red on
# c82c3d34. The return-value pin below asked "did the wrapper receive the PATH or
# the accessor?" and answered it by reading what came back from the real
# ``os.path.realpath``. On Linux that discriminates. On nt it does not, because
# ``ntpath.realpath('/tmp')`` returns ``D:\\tmp`` — a POSIX-absolute literal is
# DRIVE-RELATIVE there — so the pin reported "it is arriving bound and resolving
# the accessor" about a wrapper that had worked perfectly. The mechanism it
# guards was right; the string it compared was a POSIX fact asserted as
# universal, which is the species this whole file exists to catch, committed
# inside the instrument built to catch it.
#
# @memory's rule, paid for by four of their own reds the same night: when a probe
# asks "did my patch reach X", let X have captured a SENTINEL rather than the
# real function — otherwise the original's own platform behaviour answers the
# question for you. This one returns its argument and touches no filesystem, no
# cwd and no path module, so whatever comes back afterwards is the wrapper's
# doing on any platform. It also subsumes the drive-relative symptom entirely:
# with nothing resolving the literal, there is no spelling to disagree about.
_SENTINEL_REALPATH = """
import os


def _sentinel_realpath(path, *a, **kw):
    return path


os.path.realpath = _sentinel_realpath
"""

# The OPPOSITE platform, for the litmus @devpulse requires: run the probe under
# an nt emulation and require the verdict not to move.
#
# @flow's M3 TRAP, honoured rather than repeated: do NOT alias ``ntpath.realpath``
# on this host. CPython's ntpath.py cannot import ``nt`` on POSIX and falls back
# to ``realpath = abspath``, and ``ntpath.abspath`` reads the cwd only for a
# RELATIVE path — so the alias emulates THIS host wearing an nt label and proves
# nothing. The win32 branch is built by name instead: read the cwd
# UNCONDITIONALLY (ntpath.py:678), and spell the answer the way nt does, where a
# POSIX-absolute literal is drive-relative. ``D:`` is CI's own drive, from the
# failure log.
_NT_EMULATION = """
import os


def _win32_realpath(path, *a, **kw):
    os.getcwd()  # unconditional on nt, unlike posixpath
    p = os.fspath(path)
    if p[:1] in ("/", "\\\\"):
        return "D:" + p.replace("/", "\\\\")
    return "D:\\\\emulated_cwd\\\\" + p.replace("/", "\\\\")


os.path.realpath = _win32_realpath
"""

# Does THIS interpreter's resolve() reach the denied call for an ABSOLUTE path?
_RESOLVE_CONTROL = """
import pathlib

try:
    pathlib.Path(pathlib.__file__).resolve()
    print("RESOLVE_DIES: NO")
except OSError:
    print("RESOLVE_DIES: YES")
"""

# The control for world B, and it MUST ride a <string> frame — see the module
# docstring. compile(..., "<string>") gives the frame a pseudo-filename with
# nothing in linecache, which is the shape getmodule's unguarded realpath is
# reached for.
_STACK_CONTROL = """
import inspect


def _probe():
    try:
        inspect.stack()
        return "NO"
    except OSError:
        return "YES"


_ns = {"_probe": _probe, "out": None}
exec(compile("out = _probe()", "<string>", "exec"), _ns)
print("STACK_DIES: " + _ns["out"])
"""


def _drone_modules() -> list[str]:
    """Every importable module under ``aipass.drone.apps``, by walking the tree.

    Named from the filesystem rather than from a hand-written list: the whole
    species this file is about is a fix landing on some of N identical paths,
    and a list in a test is one more place for N to be undercounted.
    """
    import aipass.drone.apps as drone_apps

    root = Path(drone_apps.__file__).parent
    names = set()
    for source in sorted(root.rglob("*.py")):
        if "__pycache__" in source.parts:
            continue
        rel = source.relative_to(root).with_suffix("")
        parts = [p for p in rel.parts if p != "__init__"]
        names.add(".".join(["aipass.drone.apps", *parts]))
    return sorted(names)


def _run_world(world: str, control: str, body: str) -> subprocess.CompletedProcess:
    script = _PRELOAD + world + control + body
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.fixture(scope="module")
def drone_modules() -> list[str]:
    modules = _drone_modules()
    assert len(modules) > 40, f"the module walk found only {len(modules)} — it is not measuring the tree"
    return modules


class TestEveryModuleImportsWithoutACwd:
    """The import fan, in both worlds, with the world's own liveness asserted."""

    IMPORT_BODY = """
import importlib
import sys
import traceback

dead = []
for name in {names!r}:
    try:
        importlib.import_module(name)
    except OSError:
        tb = traceback.extract_tb(sys.exc_info()[2])
        site = "unknown"
        for fr in tb:
            if "aipass" in fr.filename and "drone" in fr.filename:
                site = fr.filename + ":" + str(fr.lineno)
        dead.append(name + " -> " + site)
    except Exception:
        pass  # not this file's question

print("DEAD: " + str(len(dead)))
for entry in dead:
    print("  " + entry)
print("SWEPT: " + str(len({names!r})))
"""

    def test_world_a_ntpath_emulation_kills_no_drone_import(self, drone_modules):
        """A raw ``Path(__file__).resolve()`` anywhere on the import fan reds this."""
        result = _run_world(_WORLD_A, _RESOLVE_CONTROL, self.IMPORT_BODY.format(names=drone_modules))

        assert result.returncode == 0, result.stdout + result.stderr
        assert "RESOLVE_DIES: YES" in result.stdout, (
            "the ntpath world did not arm — every assertion below it would be vacuous.\n" + result.stdout
        )
        assert "DEAD: 0" in result.stdout, result.stdout
        assert f"SWEPT: {len(drone_modules)}" in result.stdout, result.stdout

    def test_world_b_denied_realpath_kills_no_drone_import(self, drone_modules):
        """Harsher, and the only world that convicts ``inspect.stack()``."""
        result = _run_world(_WORLD_B, _STACK_CONTROL, self.IMPORT_BODY.format(names=drone_modules))

        assert result.returncode == 0, result.stdout + result.stderr
        assert "STACK_DIES: YES" in result.stdout, (
            "world B did not arm — inspect.stack() survived it, so nothing here convicts that call.\n" + result.stdout
        )
        assert "DEAD: 0" in result.stdout, result.stdout


class TestTheAuditLineSurvivesTheWorldItLogsIn:
    """``log_operation`` is reached at runtime, so no import probe covers it.

    The stack it walks is the CALLER'S, so the shape that convicts it is a
    ``<string>`` frame — a routed subprocess, a hook, anything exec'd — which is
    precisely what drone's own router produces.
    """

    BODY = """
import os
import tempfile
import pathlib

seam = tempfile.mkdtemp()
os.environ["AIPASS_TEST_LOG_DIR"] = seam
from aipass.drone.apps.handlers.json import json_handler

# Measured THROUGH log_operation, never by calling caller detection directly.
# drone's handler is a shim that binds the one fleet json service
# (DPLAN-0325), and the service reads sys._getframe(2) - [0] itself,
# [1] log_operation, [2] the caller. A direct call is one frame short and
# reads whatever happens to sit above it, so it would answer a question
# nobody asked. The document the service WRITES carries the attribution in
# its own filename, which is the audit trail this test exists to protect.

# Arm 1: a frame with a real module filename. compile() sets co_filename, so
# this is a genuine named frame without a file on disk.
try:
    exec(compile("jh.log_operation('dead_cwd_probe', {'k': 1})", "router_probe.py", "exec"), {"jh": json_handler})
    print("LOG_OPERATION: SURVIVED")
except OSError as exc:
    print("LOG_OPERATION DIED: " + type(exc).__name__)

# Arm 2: the <string> frame drone's own router actually produces.
try:
    exec(compile("jh.log_operation('dead_cwd_probe', {'k': 2})", "<string>", "exec"), {"jh": json_handler})
    print("PSEUDO_FRAME: SURVIVED")
except OSError as exc:
    print("PSEUDO_FRAME DIED: " + type(exc).__name__)

written = sorted(p.name for p in pathlib.Path(seam).rglob("*_log.json"))
print("DOCUMENTS: " + ",".join(written))
"""

    def test_log_operation_survives_a_string_frame_with_realpath_denied(self):
        result = _run_world(_WORLD_B, _STACK_CONTROL, self.BODY)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "STACK_DIES: YES" in result.stdout, (
            "world B did not arm — this test would pass against the uncured call.\n" + result.stdout
        )
        assert "LOG_OPERATION: SURVIVED" in result.stdout, result.stdout
        assert "PSEUDO_FRAME: SURVIVED" in result.stdout, result.stdout
        # It must still ANSWER, not merely not-crash: attributing every caller
        # to one name would satisfy the lines above and destroy the audit trail.
        assert "router_probe_log.json" in result.stdout, (
            "the caller name stopped being read from the frame: " + result.stdout
        )
        # And the pseudo-frame is answered "unknown" BY DESIGN, not by accident.
        # drone's old handler wrote the literal "<string>" here; the service
        # refuses to, because a log that attributes work to <string> asserts
        # something false about who did it — and that name became a DIRECTORY
        # once (2026-08-31). drone is the branch that produces those frames, so
        # this is its own router's audit line being pinned, not a hypothetical.
        assert "unknown_log.json" in result.stdout, "a pseudo-frame is no longer answered 'unknown': " + result.stdout


class TestTheWorldArmsOnEveryInterpreter:
    """The 3.10 row, made falsifiable on an interpreter that is not 3.10.

    STATED PLAINLY BECAUSE IT LIMITS WHAT THIS FILE PROVES: no Python 3.10
    exists on this machine (3.12 only, checked). So the 3.10 row is DERIVED from
    CI's red and REPRODUCED under the emulated accessor below — it is not a live
    measurement on a real 3.10, and this file should not be read as one. What is
    measured live here is the accessor SHAPE and the cure's behaviour against it,
    which is the part a future edit can break.

    CI's failure was not a bug in drone's code — it was the world failing to
    arm, and the arming probe REFUSING instead of passing vacuously is the only
    reason anyone found out. That is the discipline working, and it is also the
    limit of it: a probe can only tell you the world is dead on the interpreter
    that runs it. Nothing here could have said so from a 3.12 laptop.

    So the accessor shape is BUILT rather than waited for. Each test below states
    which half of the cure it measures, and the middle one reproduces CI's
    failure exactly — a bare module-attribute patch, a pre-captured accessor, and
    a denial that never lands.
    """

    PROBE = """
import pathlib as _p

try:
    _p._normal_accessor.realpath("/tmp")
    print("ACCESSOR_DENIED: NO")
except OSError:
    print("ACCESSOR_DENIED: YES")
"""

    BARE_PATCH_ONLY = """
import os


def _bare(path, *a, **kw):
    raise FileNotFoundError(2, "realpath denied", "")


os.path.realpath = _bare
"""

    @staticmethod
    def _run(script: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)

    def test_a_bare_module_patch_does_not_reach_a_pre_captured_accessor(self):
        """CI's Python 3.10 failure, reproduced here. This is the red-first half.

        The accessor captured the real function before the patch, so rebinding
        ``os.path.realpath`` rebinds a name nothing reads again. If this test
        ever goes green, the interpreter stopped being able to express the bug
        and the two below prove less than they claim.
        """
        result = self._run(_FAKE_ACCESSOR + self.BARE_PATCH_ONLY + self.PROBE)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "ACCESSOR_DENIED: NO" in result.stdout, (
            "a bare os.path.realpath patch reached a pre-captured accessor — "
            "then CI's 3.10 red is not reproducible here and this file cannot "
            "defend the cure: " + result.stdout
        )

    def test_the_shipped_world_reaches_a_pre_captured_accessor(self):
        """The cure, measured against the shape that defeated the bare patch."""
        result = self._run(_FAKE_ACCESSOR + _WORLD_B + self.PROBE)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "ACCESSOR_DENIED: YES" in result.stdout, (
            "the shipped world left a pre-captured accessor holding the real "
            "function — this is exactly the 3.10 red: " + result.stdout
        )

    def test_world_a_also_reaches_a_pre_captured_accessor(self):
        """Both worlds carry the cure, so both are measured against the shape.

        World A is the one CI actually reddened, and patching only world B would
        leave the exact failure in place while the test named after it passed.
        """
        result = self._run(_FAKE_ACCESSOR + _WORLD_A + self.PROBE)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "ACCESSOR_DENIED: YES" in result.stdout, (
            "world A left a pre-captured accessor holding the real function — "
            "this is CI's 3.10 red exactly: " + result.stdout
        )

    def test_the_shipped_world_still_arms_where_no_accessor_exists(self):
        """3.11+ — the ``hasattr`` guard must not turn the world into a no-op."""
        result = self._run(_WORLD_A + _RESOLVE_CONTROL)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "RESOLVE_DIES: YES" in result.stdout, result.stdout

    RESOLVE_PROBE = """
import pathlib as _p

print("RESOLVED: " + str(_p._normal_accessor.realpath("/tmp")))
"""

    def test_the_ntpath_wrapper_resolves_the_path_not_the_accessor(self):
        """@memory's return-value pin, cured of the platform it was importing.

        THE CLAIM is unchanged and it is still not decoration: every other
        assertion about world A is RAISE-shaped, and a wrapper that arrived bound
        would eat the real path into ``*a``, resolve the accessor object instead,
        and STILL call ``os.getcwd()`` first — so it would still raise and every
        raise-shaped probe would stay green for entirely the wrong reason. Only
        the return value separates the two, so it is checked with the denial OFF.

        WHAT CHANGED is what the accessor captured. This pin used to read the
        answer back through the host's real ``os.path.realpath``, which made the
        verdict a fact about the host's path module — and on nt it returned
        ``D:\\tmp`` and the pin accused a wrapper that was working. It reads
        through a sentinel now, so the only thing that can change the answer is
        the wrapper's own argument handling, which is the thing under test.
        """
        result = self._run(_SENTINEL_REALPATH + _FAKE_ACCESSOR + _NTPATH_WRAPPER + self.RESOLVE_PROBE)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "RESOLVED: /tmp" in result.stdout, (
            "the wrapper did not receive the path it was handed — it is arriving "
            "bound and passing the accessor through: " + result.stdout
        )

    def test_the_nt_emulation_reproduces_the_ci_red_without_the_sentinel(self):
        """Red-first, locally: the failure @devpulse relayed, rebuilt on this host.

        Without the sentinel the probe resolves a POSIX literal through whatever
        path module the host has. Under the nt emulation that is ``D:\\tmp`` —
        CI's exact string, from a wrapper doing exactly the right thing.

        If this ever stops producing ``D:\\tmp``, the emulation has stopped being
        able to express the bug and the litmus below proves nothing.
        """
        result = self._run(_NT_EMULATION + _FAKE_ACCESSOR + _NTPATH_WRAPPER + self.RESOLVE_PROBE)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "RESOLVED: D:\\tmp" in result.stdout, (
            "the nt emulation no longer reproduces the drive-relative spelling, "
            "so it cannot defend the sentinel: " + result.stdout
        )

    def test_the_sentinel_gives_the_same_verdict_under_either_platform(self):
        """@devpulse's litmus: run the probe under the OPPOSITE platform's
        emulation and require the verdict not to move.

        This is the test that would have caught the original red on Linux. The
        two runs differ only in which path module the host appears to have, and a
        pin about argument handling must not be able to notice that.

        THE COMPARISON IS THE PIN, not the ``RESOLVED: /tmp`` line under it, and
        that was measured rather than assumed. Neutering the comparison alone is
        an INVALID mutant by @daemon's round-5 rule — an assertion that currently
        holds cannot be killed by deleting it, so of course it stays green. The
        valid form is the compound: revert the sentinel AND neuter the
        comparison, and the whole file passes. So the cross-platform equality is
        the only thing here that catches CI's actual defect. Do not delete it as
        redundant with the literal check below; the literal check is what CI was
        already doing when it went red.
        """
        here = self._run(_SENTINEL_REALPATH + _FAKE_ACCESSOR + _NTPATH_WRAPPER + self.RESOLVE_PROBE)
        as_nt = self._run(_NT_EMULATION + _SENTINEL_REALPATH + _FAKE_ACCESSOR + _NTPATH_WRAPPER + self.RESOLVE_PROBE)

        assert here.returncode == 0, here.stdout + here.stderr
        assert as_nt.returncode == 0, as_nt.stdout + as_nt.stderr
        assert here.stdout == as_nt.stdout, (
            "the verdict moved when the platform did — this pin is measuring the "
            f"host rather than the wrapper.\n  here: {here.stdout!r}\n  as nt: {as_nt.stdout!r}"
        )
        assert "RESOLVED: /tmp" in here.stdout, here.stdout


class TestTheCallerIsNoneBranchRunsAndReturns:
    """The branch the AST ban was built for, watched BEHAVIOURALLY as well.

    THE CORRECTION, @spawn's, relayed by @devpulse 2026-08-31 after this file
    shipped. The round-4 guidance said this branch is unreachable and only a
    parse can watch it. The true sentence is narrower: it is unreachable from
    IMPORT-shaped pins, because ``apps/__init__.py`` always supplies a real-file
    frame — the nine-branch reproduction stands, and drone's own M3 reproduced it
    (restoring the walk killed exactly one test, the AST ban).

    But CALLING ``_guard_branch_access()`` directly from an interpreter ``-c``
    child reaches it: every frame is then either string-pseudo or importlib, both
    skipped, so ``_find_real_caller`` returns None and the branch RUNS. Under a
    realpath denial a regrown ``inspect.stack()`` walk dies there; the cured plain
    return survives.

    TWO ARMING PROBES, not one, and the second is the one that matters. Probe 1
    proves the denial bites at all. Probe 2 proves ``_find_real_caller`` actually
    returned None — without it the world could silently exercise a DIFFERENT path
    (a real-file frame sneaking onto the stack sends the guard down the
    containment check instead, where it also returns, and the pin would report
    green having never entered the branch it names).

    The AST ban below is kept rather than replaced. It needs no subprocess, it
    names the defect precisely, and it catches reintroductions in files this probe
    never calls into. Two instruments, one defect, different blind spots.
    """

    BODY = """
from aipass.drone.apps.handlers import _find_real_caller, _guard_branch_access

# ARMING PROBE 2: the branch under test is the one actually entered.
caller, _line = _find_real_caller()
print("CALLER_IS_NONE: " + ("YES" if caller is None else "NO (" + str(caller) + ")"))

try:
    _guard_branch_access()
    print("GUARD: RETURNED")
except OSError as exc:
    print("GUARD DIED: " + type(exc).__name__)
except ImportError:
    print("GUARD: BLOCKED")
"""

    def test_the_guard_returns_from_a_string_frame_with_realpath_denied(self):
        result = _run_world(_WORLD_B, _STACK_CONTROL, self.BODY)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "STACK_DIES: YES" in result.stdout, (
            "world B did not arm — a regrown walk would survive this pin.\n" + result.stdout
        )
        assert "CALLER_IS_NONE: YES" in result.stdout, (
            "the probe never entered the caller-is-None branch, so it proves nothing about it.\n" + result.stdout
        )
        assert "GUARD: RETURNED" in result.stdout, result.stdout


class TestNoModuleLevelLocationCallSurvives:
    """The structural half, because behaviour cannot reach every reintroduction.

    @hooks (M7), reproduced here as M3: restoring ``inspect.stack()`` in
    ``_guard_branch_access``'s caller-is-None branch left every IMPORT-shaped pin
    green, because ``apps/__init__.py`` always supplies a real-file frame so no
    import probe enters that branch. A parse sees it without a subprocess.

    The claim was narrowed 2026-08-31 (@spawn via @devpulse) and the narrowing is
    above: a direct call from a ``-c`` child does reach it. "Unreachable from
    import-shaped pins" is the true sentence, not "unreachable".

    The ban is on the CALL — ``ast.Call`` whose func is ``inspect.stack`` — never
    on the string, because this file and the cured modules SPELL the defect in
    their docstrings to explain it, and a string ban would convict the
    explanation along with the thing.
    """

    BANNED_ATTRS = frozenset({"resolve", "cwd", "getcwd", "realpath", "abspath"})

    @staticmethod
    def _apps_sources() -> list[Path]:
        import aipass.drone.apps as drone_apps

        root = Path(drone_apps.__file__).parent
        return [p for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts]

    @staticmethod
    def _module_level_location_calls(tree: ast.Module) -> list[tuple[int, str]]:
        """Calls that infer a location and are evaluated when the module loads."""
        found = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                func = sub.func
                attr = func.attr if isinstance(func, ast.Attribute) else None
                if attr in TestNoModuleLevelLocationCallSurvives.BANNED_ATTRS:
                    found.append((sub.lineno, ast.unparse(sub)))
        return found

    @staticmethod
    def _inspect_stack_calls(tree: ast.Module) -> list[int]:
        """``inspect.stack()`` calls at ANY depth — the unreachable-branch case."""
        found = []
        for sub in ast.walk(tree):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "stack"
                and isinstance(func.value, ast.Name)
                and func.value.id == "inspect"
            ):
                found.append(sub.lineno)
        return found

    def test_no_module_level_resolve_or_cwd_read_anywhere_in_apps(self):
        offenders = []
        for source in self._apps_sources():
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for lineno, text in self._module_level_location_calls(tree):
                offenders.append(f"{source.name}:{lineno}  {text}")

        assert offenders == [], (
            "module-level location calls crash the import on a Windows box with no cwd; "
            "route them through handlers/module_root.module_file(): " + ", ".join(offenders)
        )

    def test_no_inspect_stack_call_survives_in_apps(self):
        offenders = []
        for source in self._apps_sources():
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for lineno in self._inspect_stack_calls(tree):
                offenders.append(f"{source.name}:{lineno}")

        assert offenders == [], (
            "inspect.stack() reaches getmodule's unguarded os.path.realpath; "
            "walk sys._getframe over f_code.co_filename instead: " + ", ".join(offenders)
        )

    # -- negative controls, both directions -------------------------------
    #
    # A checker that convicts nothing and a checker that convicts everything
    # look identical in a green summary. Both detectors are run against source
    # they MUST flag and source they must NOT.

    def test_the_module_level_detector_convicts_a_module_level_resolve(self):
        tree = ast.parse("from pathlib import Path\nROOT = Path(__file__).resolve().parents[3]\n")
        assert self._module_level_location_calls(tree), "the detector is blind to the exact line it exists to ban"

    def test_the_module_level_detector_clears_the_same_call_inside_a_function(self):
        tree = ast.parse("from pathlib import Path\ndef f():\n    return Path(__file__).resolve()\n")
        assert self._module_level_location_calls(tree) == [], (
            "a resolve() inside a function is reached at CALL time, not import time — "
            "convicting it would ban the guarded helper this cure is built on"
        )

    def test_the_stack_detector_convicts_a_call_in_an_unreachable_branch(self):
        """@hooks' M7, reproduced: the branch no import probe can enter."""
        tree = ast.parse(
            "import inspect\n"
            "def guard(caller):\n"
            "    if caller is None:\n"
            "        for frame in inspect.stack():\n"
            "            pass\n"
            "        return\n"
            "    return\n"
        )
        assert self._inspect_stack_calls(tree), "the reintroduction @hooks measured would land unnoticed"

    def test_the_stack_detector_clears_a_docstring_that_names_the_defect(self):
        """The reason this is an AST ban and not a grep.

        The source is a SYNTHETIC literal on purpose, and it must stay one.
        @spawn's control here asserted the whole LIVE guard file clean, which
        made it a second copy of the ban wearing a control's name — restoring
        the walk redded the control too, so it could never have told them the
        detector had gone blind. This one cannot fail for the ban's reason:
        the string it parses has no call in it at all, so it fails only if the
        detector starts convicting prose, which is the single thing it exists
        to rule out.
        """
        tree = ast.parse('"""Walks sys._getframe rather than inspect.stack() — see the cure."""\n')
        assert self._inspect_stack_calls(tree) == [], (
            "a string ban convicts the explanation along with the defect, which is how a cure ends up undocumented"
        )

    def test_the_stack_detector_clears_an_unrelated_stack_attribute(self):
        tree = ast.parse("import numpy\nx = numpy.stack([1, 2])\ntraceback = []\ntraceback.stack()\n")
        assert self._inspect_stack_calls(tree) == [], "the ban is on inspect.stack, not on the word stack"
