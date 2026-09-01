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
_EMULATE_310 = """
    import os, os.path, pathlib

    if hasattr(pathlib, "_NormalAccessor"):
        # Real <=3.10. The property is native here; do not build a stand-in
        # over it. Reported so a reader of the output knows which was measured.
        print("ACCESSOR_NATIVE")
    else:
        class _NormalAccessor310:
            # EAGER capture — the whole mechanism. Evaluated at class creation,
            # exactly as 3.10 evaluated it at pathlib's first import. Make this
            # a lazy lookup and the emulation stops emulating 3.10, which is
            # what test_the_bare_rebinding_is_inert_under_the_emulation pins.
            realpath = staticmethod(os.path.realpath)

        pathlib._NormalAccessor = _NormalAccessor310
        # 3.10 held an INSTANCE (Path._accessor = _normal_accessor), not the
        # class. Routing through the instance is what makes the binding
        # question below a real one rather than a hypothetical.
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

# The emulation now PROVES it took before anything downstream claims anything.
#
# This is the round-6 arming lesson applied one level up. On 3.13 and on
# windows the old emulation was silently inert: the pins failed for a reason
# that took a CI log and a traceback to name, when the child could simply have
# said so. A world that cannot report ROUTE_DARK is a world that reports every
# inert run as a measurement.
#
# It also settles @devpulse's trap (b) in the child rather than in my head: the
# probe literal is built with abspath and checked with isabs ON THE RUNNER,
# because os.sep + "tmp" is DRIVE-RELATIVE on nt (drone's sibling failure
# printed "RESOLVED: D:\\tmp") and ntpath.realpath reads os.getcwd
# unconditionally. An absolute path is whatever the host says is absolute.
_ARM_THE_ROUTE = """
    import os, pathlib

    _ARM_ABS = {probe_literal}
    if not os.path.isabs(_ARM_ABS):
        print("PROBE_NOT_ABS")
    if os.name == "nt" and not os.path.splitdrive(_ARM_ABS)[0]:
        # Measured BY THE RUNNER, because no Linux box can answer it: a
        # rooted-driveless path carries no drive on nt, and ntpath.realpath
        # resolves it against the current one — reading the cwd for a literal
        # that looks absolute. This machine cannot falsify the row (ntpath on
        # posix has no drive to add), so the child reports it instead of me
        # asserting it from here.
        print("PROBE_NO_DRIVE")

    _seen = []
    _captured = pathlib._NormalAccessor.realpath

    def _recording(*a, **k):
        _seen.append(a[0] if a else None)
        return _captured(*a, **k)

    # CLASS only, here too: an instance attribute left behind by the arming
    # probe would shadow the class patch the shipped world installs later, and
    # the world would go inert with nothing to show for it.
    pathlib._NormalAccessor.realpath = staticmethod(_recording)
    pathlib.Path(_ARM_ABS).resolve()
    pathlib._NormalAccessor.realpath = staticmethod(_captured)

    print("ROUTE_ARMED" if _seen else "ROUTE_DARK")
"""

# The version CI convicted, kept verbatim and PUBLISHED as a negative control.
#
# Deleting it would leave the host shapes below unfalsifiable: three preludes
# that nothing fails against are three preludes nobody can tell are working.
# This one fails against each of them, in the exact shape its CI leg reported.
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
    print("ACCESSOR_EMULATED")
"""

# The interpreters this machine cannot run, rebuilt as HOST SHAPES.
#
# Each one installs the single property of a real interpreter that the old
# emulation assumed away, BEFORE the emulation runs. They are stand-ins, not
# interpreters — what they buy is that every CI red above is now falsifiable
# from a 3.12 laptop, and stays falsifiable after the cure.
_HOST_SHAPES = {
    # 3.12 as it really is here: the baseline, so a shape can be compared
    # against the interpreter the file actually runs on.
    "3.12-as-it-is": "",
    # 3.10: the accessor exists NATIVELY (so the emulation must stand down and
    # measure the interpreter), and _flavour is an OBJECT reached during
    # PARSING. Replace it with something lacking parse_parts and Path(...)
    # itself dies — CI's traceback, verbatim, on this machine.
    "3.10-native-accessor-and-flavour-object": """
        import os, os.path, pathlib, posixpath

        class _Flavour310:
            sep = posixpath.sep
            altsep = ""

            def __getattr__(self, name):
                return getattr(posixpath, name)

            def parse_parts(self, parts):
                return ("", posixpath.sep, list(parts))

        pathlib.PurePosixPath._flavour = _Flavour310()
        pathlib.PosixPath._flavour = pathlib.PurePosixPath._flavour

        _real_parse = pathlib.PurePath._parse_path.__func__

        def _parse_path_310(cls, path):
            cls._flavour.parse_parts([path])
            return _real_parse(cls, path)

        pathlib.PurePath._parse_path = classmethod(_parse_path_310)

        class _NormalAccessor:
            realpath = staticmethod(os.path.realpath)

        pathlib._NormalAccessor = _NormalAccessor
        pathlib._normal_accessor = _NormalAccessor()

        def _resolve_310(self, strict=False):
            return type(self)(self._accessor.realpath(self, strict=strict))

        pathlib.Path._accessor = pathlib._normal_accessor
        pathlib.Path.resolve = _resolve_310
    """,
    # 3.11: flavour is still an OBJECT, but resolve calls os.path.realpath at
    # MODULE level and there is no accessor. Its CI red was the parsing half,
    # not the route — which is why both halves are carried here separately.
    "3.11-flavour-object-and-direct-resolve": """
        import os, pathlib, posixpath

        class _Flavour311:
            sep = posixpath.sep
            altsep = ""

            def __getattr__(self, name):
                return getattr(posixpath, name)

            def parse_parts(self, parts):
                return ("", posixpath.sep, list(parts))

        pathlib.PurePosixPath._flavour = _Flavour311()
        pathlib.PosixPath._flavour = pathlib.PurePosixPath._flavour

        _real_parse = pathlib.PurePath._parse_path.__func__

        def _parse_path_311(cls, path):
            cls._flavour.parse_parts([path])
            return _real_parse(cls, path)

        pathlib.PurePath._parse_path = classmethod(_parse_path_311)

        def _resolve_311(self, strict=False):
            return type(self)(os.path.realpath(self, strict=strict))

        pathlib.Path.resolve = _resolve_311
    """,
    # 3.13: no accessor, no _flavour on the resolve path — resolve calls
    # os.path.realpath directly, so a write to _flavour is a write nothing
    # reads. (_flavour is left in place here because 3.12's own parser still
    # needs it; the reproduction is that RESOLVE no longer consults it.)
    "3.13-no-accessor-direct-resolve": """
        import os, pathlib

        def _resolve_313(self, strict=False):
            return type(self)(os.path.realpath(self, strict=strict))

        pathlib.Path.resolve = _resolve_313
    """,
    # windows: the class the host instantiates is not in the PosixPath
    # hierarchy, and its flavour IS the live os.path module — which is why the
    # bare rebinding armed there while the emulation sat inert on classes
    # nothing constructed.
    "nt-concrete-class-is-not-posix": """
        import os.path, pathlib

        class _OtherFlavourPath(pathlib.PurePath):
            _flavour = os.path

            def resolve(self, strict=False):
                return type(self)(self._flavour.realpath(self, strict=strict))

        pathlib.Path = _OtherFlavourPath
    """,
}

# The shapes the OLD emulation must die against, each keyed to the SYMPTOM its
# CI leg actually printed. "3.12-as-it-is" is not among them, and that absence
# is the finding: the old emulation passed here for two rounds because the only
# interpreter it was ever run against was the one it assumed.
#
# Keying on the symptom rather than on "it failed somehow" is what keeps the
# shapes honest: without it, a shape that reproduced only HALF an interpreter
# would still convict — and both flavour-object shapes did exactly that in the
# first cut, with their parsing halves decorative and unmeasured.
_OLD_EMULATION_SYMPTOM = {
    # CI's 3.10 and 3.11 tracebacks, verbatim: "module 'posixpath' has no
    # attribute 'parse_parts'", raised while CONSTRUCTING a Path.
    "3.10-native-accessor-and-flavour-object": "parse_parts",
    "3.11-flavour-object-and-direct-resolve": "parse_parts",
    # CI's 3.13 and windows verdicts: the emulation sat inert and a bare
    # os.path.realbinding reached the real thing.
    "3.13-no-accessor-direct-resolve": "PATHLIB_ARMED",
    "nt-concrete-class-is-not-posix": "PATHLIB_ARMED",
}

_SHAPES_THAT_CONVICT_THE_OLD_EMULATION = sorted(_OLD_EMULATION_SYMPTOM)

assert set(_SHAPES_THAT_CONVICT_THE_OLD_EMULATION) == set(_HOST_SHAPES) - {"3.12-as-it-is"}, (
    "a host shape was added or renamed without saying which CI symptom it reproduces"
)

_BARE_REBINDING_ONLY = """
    import errno, os, os.path
    from pathlib import Path as _ProbePath

    def _no_realpath(*args, **kwargs):
        raise FileNotFoundError(errno.ENOENT, "No such file or directory")

    os.path.realpath = _no_realpath
"""

_PATHLIB_ROUTE_PROBE = """
    import os
    from pathlib import Path as _RoutePath

    _abs = {probe_literal}
    try:
        _RoutePath(_abs).resolve()
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


# ONE spelling of the probe path, substituted into every child fragment that
# needs it, so no two fragments can disagree about what "absolute" means.
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
            _compose(_HOST_SHAPES[shape], _EMULATE_310, _ARM_THE_ROUTE, world, probe),
            cwd=Path(__file__).parent,
        )

    def _armed(self, result, shape: str) -> list:
        """Refuse to read a verdict out of a child whose route never armed."""
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

        expected = "ACCESSOR_NATIVE" if shape.startswith("3.10-") else "ACCESSOR_EMULATED"
        assert expected in lines, f"expected {expected} under {shape!r}:\n{lines}"

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
            _compose(
                _HOST_SHAPES[shape],
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

        symptom = _OLD_EMULATION_SYMPTOM[shape]
        assert symptom in (result.stdout + result.stderr), (
            f"host shape {shape!r} convicted the old emulation, but not with the "
            f"symptom its CI leg printed ({symptom!r}) — it is reproducing some "
            f"other half of that interpreter:\n{result.stdout}\n{result.stderr}"
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

        _abs = {probe_literal}
        _pathlib.Path(_abs).resolve()
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
            _compose(
                _HOST_SHAPES[shape],
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
            _compose(
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

                _abs = {probe_literal}
                try:
                    _pathlib.Path(_abs).resolve()
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
            _compose(
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
            _compose(
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

    def test_the_drive_row_is_unfalsifiable_here_and_that_is_measured(self):
        """Why the runner has to answer, rather than a hand-written expectation.

        If this ever fails, posix ntpath grew a drive and the PROBE_NO_DRIVE
        gate could be exercised locally after all — which would be better news
        than the pin it replaces.
        """
        assert ntpath.splitdrive(ntpath.abspath(ntpath.sep))[0] == "", (
            "ntpath.abspath produced a drive on this platform — the row this "
            "file declares unfalsifiable here just became falsifiable"
        )


# ntpath.realpath's win32 branch, the only half of it this table needs, read
# from CPython 3.12 Lib/ntpath.py:664-692 rather than remembered: `cwd =
# os.getcwd()` at :678 runs UNCONDITIONALLY, several lines ABOVE the
# `if not had_prefix and not isabs(path)` that would use it. On posix that
# module's realpath is just abspath, which reads the cwd only for a relative
# path — so the two platforms genuinely disagree, and a pin that asserts the
# posix answer everywhere is red on the runner.
_WINDOWS_EMULATED = """
    import ntpath, os, sys

    def _win32_realpath(path, *, strict=False):
        path = ntpath.normpath(path)
        cwd = os.getcwd()
        if not ntpath.isabs(path):
            path = ntpath.join(cwd, path)
        return path

    ntpath.realpath = _win32_realpath
    os.path = ntpath
    sys.modules["os.path"] = ntpath
"""

# route -> {absolute probe verdict, relative probe verdict} under a getcwd
# denial. EVERY row is measured on this machine: the nt rows through the
# emulation above, the posix rows live.
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
    cwd before it looks at the path at all, so the same denial arms there. The
    first cut of this class asserted the posix answer unconditionally and would
    have gone red on the windows runner — the exact species it was written to
    close, one platform over.
    """

    def _verdict(self, route: str, probe: str) -> str:
        result = _run(
            _compose(
                _WINDOWS_EMULATED if route == "nt" else "",
                _EMULATE_310,
                _ARM_THE_ROUTE,
                _INJECT_DEAD_CWD,
                _PATHLIB_ROUTE_PROBE if probe == "absolute" else _PATHLIB_ROUTE_PROBE_RELATIVE,
            ),
            cwd=Path(__file__).parent,
        )
        lines = result.stdout.split()
        assert "ROUTE_ARMED" in lines, f"the route never armed ({route}/{probe}):\n{result.stdout}\n{result.stderr}"
        armed = [line for line in lines if line.startswith("PATHLIB_")]
        assert armed, f"the probe reported nothing ({route}/{probe}):\n{result.stdout}\n{result.stderr}"
        return armed[0]

    @pytest.mark.parametrize(("route", "probe"), sorted(_GETCWD_TABLE))
    def test_the_getcwd_denial_answers_the_same_way_the_table_says(self, route, probe):
        expected = _GETCWD_TABLE[(route, probe)]

        assert self._verdict(route, probe) == expected, (
            f"the {route} route answered differently for a {probe} path than the "
            "table says. If this is the nt row, read ntpath.realpath again "
            "before editing the table — the unconditional os.getcwd at :678 is "
            "what the row is derived from."
        )

    def test_the_live_platform_agrees_with_its_own_row(self):
        """The emulation is a stand-in; this is the host answering for itself."""
        route = "nt" if os.name == "nt" else "posix"
        probe = "absolute"

        result = _run(
            _compose(_EMULATE_310, _ARM_THE_ROUTE, _INJECT_DEAD_CWD, _PATHLIB_ROUTE_PROBE),
            cwd=Path(__file__).parent,
        )
        lines = result.stdout.split()
        assert "ROUTE_ARMED" in lines, result.stdout
        live = [line for line in lines if line.startswith("PATHLIB_")][0]

        assert live == _GETCWD_TABLE[(route, probe)], (
            f"this host is {os.name!r} and answered {live} where its own table row says {_GETCWD_TABLE[(route, probe)]}"
        )

    def test_the_relative_probe_is_inert_with_no_world_at_all(self):
        """The control for the control: no denial, no arming."""
        result = _run(
            _compose(_EMULATE_310, _ARM_THE_ROUTE, _PATHLIB_ROUTE_PROBE_RELATIVE),
            cwd=Path(__file__).parent,
        )

        assert "PATHLIB_INERT" in result.stdout.split(), (
            "the relative probe raised with NO world installed — it is "
            f"convicting for its own shape, not for the denial:\n{result.stdout}\n{result.stderr}"
        )

    def test_the_windows_emulation_is_inert_without_the_denial(self):
        """And the same for the platform stand-in itself.

        An emulation that raises on its own would make every nt row above
        vacuously ARMED — @canary's round-4 species, applied to a platform
        instead of a world.
        """
        result = _run(
            _compose(_WINDOWS_EMULATED, _EMULATE_310, _ARM_THE_ROUTE, _PATHLIB_ROUTE_PROBE),
            cwd=Path(__file__).parent,
        )

        assert "PATHLIB_INERT" in result.stdout.split(), (
            "the windows emulation arms the probe with no denial installed — "
            f"every nt row above is measuring the stand-in:\n{result.stdout}\n{result.stderr}"
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
