# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Every flow module imports, and keeps logging, without a readable working directory
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""Flow must import, and must keep its audit line alive, with no cwd.

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
DIFFERENT world to convict it. It builds a ``FrameInfo`` per frame, and for a
frame whose filename is a PSEUDO-file it reaches ``getmodule()``, whose
``os.path.realpath(f)`` sits outside every ``try`` in that function. On POSIX
the equivalent raise happens EARLIER, inside ``getabsfile()``, where ``inspect``
catches it — which is exactly why two calls on flow's every-import and
every-write paths survived years of Linux CI carrying this.

TWO WORLDS, and @seedgo's asymmetry is why both are here rather than one:

* **World A** emulates ntpath — ``os.path.realpath`` is wrapped to read
  ``os.getcwd()`` first, then ``os.getcwd`` is denied. This convicts a raw
  ``resolve()``. It does NOT convict ``inspect.stack()`` on Linux, because
  ``getabsfile`` raises inside inspect's own catch before ``getmodule`` is
  reached.
* **World B** denies ``os.path.realpath`` outright while ``abspath`` keeps
  working. This is what reaches ``getmodule``'s unguarded call and convicts
  ``inspect.stack()``.

THIRD INGREDIENT for world B (@hooks): the frame must be ``<string>`` — an
interpreter ``-c`` or ``compile()`` frame — and NEVER ``<stdin>``. A
heredoc-fed child puts ``<stdin>`` in ``linecache.cache``, ``getsourcefile``
early-returns, and the probe reports green while the same world kills imports
for real. Every assertion below is preceded by a control that states whether its
world is armed, so a probe that quietly stopped biting cannot pass itself off as
a cure.

WHAT FLOW CARRIED, measured not estimated. Before this build, **61 of 61** flow
modules died on import in BOTH worlds — every one of them inside
``handlers/__init__.py``, at the ``inspect.stack()`` on line 20 and the
``Path(__file__).resolve()`` on line 21. Those two lines MASKED everything under
them, which is why the count only became true as cures landed: curing the guard
took it to 43/61 and revealed ``json/json_handler.py:38`` (masking 31 modules on
its own) plus twelve more; routing all **29** module-level
``Path(__file__).resolve()`` sites and all **7** private ``_find_repo_root``
copies through ``handlers/repo_root.py`` took it to **0/62**.

AND ONE LIVE SITE NO IMPORT PROBE REACHES. ``log_operation`` is the audit line
flow writes on essentially every registry operation, and its
``_get_caller_module_name`` called ``inspect.stack()``. The stack it walks is
the CALLER'S, so the shape that convicts it is a ``<string>`` frame — which is
precisely what @drone's router produces when it invokes flow.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

# Other branches' import-time code is held CONSTANT: preloaded in the healthy
# world, before any denial. Their cure is their own build; this file measures
# flow's sites and must not go red in someone else's name. These are flow's only
# cross-branch module-level imports, and they are TEMPORARY — delete a line once
# that branch's own dead-cwd pin is green.
#
# @trigger is DELIBERATELY not preloaded. close_plan.py imports their core at
# module level behind `except ImportError`, and the dispatch asked whether that
# should widen to (ImportError, OSError). MEASURED here rather than assumed:
# `from aipass.trigger.apps.modules.core import trigger` succeeds in BOTH worlds
# — their own cure has landed — so widening would add a catch for a condition
# that does not occur. Leaving trigger out of the preload is what keeps that
# measurement live: if their import ever starts raising OSError, close_plan dies
# for real and the fan below reds with close_plan.py named, which is the honest
# report. Widening the except would have hidden exactly that.
_PRELOAD = """
from aipass.prax import logger  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401
import aipass.api  # noqa: F401
"""

# THE CAPTURED ACCESSOR, and why every world below ends with it.
#
# Python 3.10's pathlib delegates Path.resolve through _NormalAccessor, and that
# class took its copy of os.path.realpath at CLASS-DEFINITION time — when
# pathlib was first imported (CPython 3.10 Lib/pathlib.py:358,
# `realpath = staticmethod(os.path.realpath)`, read by Path.resolve at :1077 as
# `self._accessor.realpath(self, strict=strict)`). So a world that imports
# pathlib and THEN rebinds os.path.realpath is rebinding a name nothing will
# read again: the denial lands on the module attribute and the accessor never
# sees it. 3.11 removed the accessor and calls os.path.realpath at use, which is
# why exactly one interpreter reddened.
#
# CI found it on commit 8550ed10, Python 3.10 only: world A's arming probe
# printed RESOLVE_DIES: NO and refused, which is the probe doing its job — every
# pin underneath it would otherwise have been vacuously green on that leg.
# (@memory read the CPython source, @seedgo reproduced by construction; relayed
# by @devpulse 2026-08-31.)
#
# Patching the accessor when one EXISTS makes the world order-independent and
# identical on every interpreter — no version table, no skipif, no row that only
# one leg can falsify. Four details, each of which silently un-arms the world:
#   - `staticmethod`, or the accessor passes itself as the first argument and
#     the patch resolves the accessor OBJECT rather than the path;
#   - `*a, **k`, because Path.resolve passes `strict` and a bound call adds one;
#   - exercised through an INSTANCE, since a class-level read never binds;
#   - probed with an ABSOLUTE path, because posixpath.realpath reads the cwd for
#     a relative one whatever else is patched — the world would then convict for
#     the path's SHAPE and look like success.
_ACCESSOR_CURE = """
import pathlib as _pathlib_accessor

if hasattr(_pathlib_accessor, "_NormalAccessor"):
    _pathlib_accessor._NormalAccessor.realpath = staticmethod(_denied_realpath)
"""

_WORLD_A = (
    """
import os

_real_realpath = os.path.realpath


def _denied_realpath(path, *a, **k):
    os.getcwd()  # ntpath.realpath reads cwd before checking absoluteness
    return _real_realpath(path, *a, **k)


os.path.realpath = _denied_realpath


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd
"""
    + _ACCESSOR_CURE
)

_WORLD_B = (
    """
import os


def _denied_realpath(path, *a, **k):
    raise FileNotFoundError(2, "realpath denied", "")


os.path.realpath = _denied_realpath
"""
    + _ACCESSOR_CURE
)

# Does THIS interpreter's resolve() reach the denied call for an ABSOLUTE path?
#
# CORRECTED 2026-08-31. This comment used to read "3.10 resolves absolute paths
# without touching the cwd, so the denial cannot fire there" — inherited from the
# round-4 reference and WRONG, the same first diagnosis @devpulse retracted.
# 3.10 DOES route resolve() through os.path.realpath; it just reads a copy
# captured at pathlib's import (see _ACCESSOR_CURE above). The distinction
# matters to whoever reads this next: the false version sends you to a version
# table or a skipif, and the true one is cured by four lines that work
# everywhere. With the accessor patched, this probe now answers YES on every
# supported interpreter, and a NO is a broken instrument rather than a fact
# about the host.
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


def _flow_modules() -> list[str]:
    """Every importable module under ``aipass.flow.apps``, by walking the tree.

    Named from the filesystem rather than from a hand-written list: the whole
    species this file is about is a fix landing on some of N identical paths,
    and a list in a test is one more place for N to be undercounted.
    """
    import aipass.flow.apps as flow_apps

    root = Path(flow_apps.__file__).parent
    names = set()
    for source in sorted(root.rglob("*.py")):
        if "__pycache__" in source.parts or ".archive" in source.parts:
            continue
        rel = source.relative_to(root).with_suffix("")
        parts = [p for p in rel.parts if p != "__init__"]
        names.add(".".join(["aipass.flow.apps", *parts]))
    return sorted(names)


def _run_world(world: str, control: str, body: str) -> subprocess.CompletedProcess:
    script = _PRELOAD + world + control + body
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=300,
    )


def _flow_modules_by_import_machinery() -> list[str]:
    """The same set, derived through importlib's finder instead of the filesystem.

    A SECOND MECHANISM, on purpose. ``_flow_modules`` globs and manipulates
    strings to undo ``__init__`` nesting; this asks ``pkgutil`` — the machinery
    that decides what a module IS — and imports nothing. Re-running the same
    rglob logic twice would be the table-written-twice failure: two copies of one
    belief agree with each other no matter how wrong they are.
    """
    import pkgutil

    import aipass.flow.apps as flow_apps

    def walk(path: Path, prefix: str) -> set[str]:
        found = set()
        for info in pkgutil.iter_modules([str(path)]):
            name = f"{prefix}.{info.name}"
            found.add(name)
            if info.ispkg:
                found |= walk(path / info.name, name)
        return found

    root = Path(flow_apps.__file__).parent
    names = walk(root, "aipass.flow.apps") | {"aipass.flow.apps"}
    return sorted(name for name in names if ".archive" not in name)


@pytest.fixture(scope="module")
def flow_modules() -> list[str]:
    """Every flow module, with the count DERIVED rather than lower-bounded.

    @seedgo nominated this file for the SHORT-TABLE species on 2026-08-31
    (@trigger's find, a ruling change rather than new code): the guard here was
    ``len(modules) > 40``, which catches a collector blinded entirely and misses
    one that drops a SINGLE entry. The table stays non-empty, every surviving
    module passes, and the sweep is quietly one module lighter — an empty run
    looks odd, a short one looks normal.

    Ruled on rather than inherited, which is what the nomination asks for. The
    table is NOT legitimately variable here: the same tree is walked on every
    host, so there is an exact answer and it is worth asserting. Both mechanisms
    are compared as SETS rather than counts, because two collectors that disagree
    should say WHICH module, not just how many.
    """
    modules = _flow_modules()
    expected = _flow_modules_by_import_machinery()

    assert set(modules) == set(expected), (
        "the filesystem walk and importlib's finder disagree about which modules exist. "
        f"Only in the walk: {sorted(set(modules) - set(expected))}; "
        f"only in the finder: {sorted(set(expected) - set(modules))}. One of them is "
        "dropping entries, and a sweep built on the short list would pass while covering less."
    )
    assert len(modules) > 40, (
        f"both mechanisms agree on only {len(modules)} modules — they are agreeing about a "
        "tree that is not there, which set equality alone cannot catch"
    )
    return modules


class TestTheModuleCountIsDerivedFromTwoMechanisms:
    """The short-table cure's own control, added because a mutant walked past it.

    @seedgo's nomination replaced ``len(modules) > 40`` with set equality against
    a second derivation. A mutant then pointed the fixture at ``_flow_modules``
    for BOTH operands and every pin stayed green: two copies of one belief agree
    with each other however wrong they are, and the equality assertion becomes a
    tautology that reads like a cross-check. The docstring warned about exactly
    this while nothing enforced it — a comment is not a control.
    """

    def test_the_two_derivations_are_different_code_paths(self):
        """Asserted structurally, because behaviour cannot tell a copy from a check."""
        import ast
        import inspect

        # The DOCSTRING AND COMMENTS ARE STRIPPED FIRST, and this is the third
        # time in three rounds that a structural check has reddened on its own
        # explanation: the function's docstring names ``rglob`` precisely to warn
        # against it. A check that cannot tell the warning from the violation
        # will always convict the most careful author. Parsing gets the executable
        # body; comments are dropped by the tokenizer on the way.
        tree = ast.parse(inspect.getsource(_flow_modules_by_import_machinery).strip())
        body = tree.body[0].body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        finder_source = "\n".join(ast.unparse(node) for node in body)

        assert "pkgutil" in finder_source, (
            "the second derivation no longer goes through importlib's finder — if it "
            "globs the filesystem like the first one, the two agree by construction"
        )
        assert "_flow_modules(" not in finder_source, (
            "the second derivation calls the first — the set equality in the fixture is "
            "then comparing a value with itself"
        )
        assert "rglob" not in finder_source, "the second derivation is globbing, which is the first mechanism"

    def test_the_fixture_compares_one_against_the_other(self):
        """And that the fixture actually uses both, rather than one twice."""
        import inspect

        fixture_source = inspect.getsource(flow_modules.__wrapped__)

        assert "_flow_modules()" in fixture_source and "_flow_modules_by_import_machinery()" in fixture_source, (
            "the fixture no longer derives its expectation from the second mechanism: " + fixture_source
        )

    def test_both_mechanisms_agree_on_a_known_module(self):
        """Control for the pair: two empty collectors would also be set-equal."""
        by_walk = set(_flow_modules())
        by_finder = set(_flow_modules_by_import_machinery())

        for expected in ("aipass.flow.apps.handlers.repo_root", "aipass.flow.apps.handlers.json.json_handler"):
            assert expected in by_walk, f"the filesystem walk lost a module that is demonstrably there: {expected}"
            assert expected in by_finder, f"the finder lost a module that is demonstrably there: {expected}"


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
            if "aipass" in fr.filename and "flow" in fr.filename:
                site = fr.filename + ":" + str(fr.lineno)
        dead.append(name + " -> " + site)
    except Exception:
        pass  # not this file's question

print("DEAD: " + str(len(dead)))
for entry in dead:
    print("  " + entry)
print("SWEPT: " + str(len({names!r})))
"""

    def test_world_a_ntpath_emulation_kills_no_flow_import(self, flow_modules):
        """A raw ``Path(__file__).resolve()`` anywhere on the import fan reds this."""
        result = _run_world(_WORLD_A, _RESOLVE_CONTROL, self.IMPORT_BODY.format(names=flow_modules))

        assert result.returncode == 0, result.stdout + result.stderr
        assert "RESOLVE_DIES: YES" in result.stdout, (
            "the ntpath world did not arm — every assertion below it would be vacuous.\n" + result.stdout
        )
        assert "DEAD: 0" in result.stdout, result.stdout
        assert f"SWEPT: {len(flow_modules)}" in result.stdout, result.stdout

    def test_world_b_denied_realpath_kills_no_flow_import(self, flow_modules):
        """Harsher, and the only world that convicts ``inspect.stack()``."""
        result = _run_world(_WORLD_B, _STACK_CONTROL, self.IMPORT_BODY.format(names=flow_modules))

        assert result.returncode == 0, result.stdout + result.stderr
        assert "STACK_DIES: YES" in result.stdout, (
            "world B did not arm — inspect.stack() survived it, so nothing here convicts that call.\n" + result.stdout
        )
        assert "DEAD: 0" in result.stdout, result.stdout


class TestTheAuditLineSurvivesTheWorldItLogsIn:
    """``log_operation`` is reached at runtime, so no import probe covers it.

    The stack it walks is the CALLER'S, so the shape that convicts it is a
    ``<string>`` frame — a routed subprocess, a hook, anything exec'd — which is
    precisely what @drone's router produces when it invokes flow.
    """

    BODY = """
import os
import tempfile
import pathlib

seam = tempfile.mkdtemp()
os.environ["AIPASS_TEST_LOG_DIR"] = seam
from aipass.flow.apps.handlers.json import json_handler

# Measured THROUGH log_operation, never by calling caller detection directly.
# flow's handler is a shim that binds the one fleet json service
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

# Arm 2: the <string> frame @drone's router actually produces.
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
        # flow's old handler wrote the literal "<string>" here; the service
        # refuses to, because a log that attributes work to <string> asserts
        # something false about who did it — and that name became a DIRECTORY
        # once (2026-08-31). Pinned so the cure cannot be undone quietly.
        assert "unknown_log.json" in result.stdout, "a pseudo-frame is no longer answered 'unknown': " + result.stdout


def expected_route_without_cure(has_accessor: bool) -> str:
    """What removing ``_ACCESSOR_CURE`` must do to the real ``Path.resolve`` route.

    A PLAIN FUNCTION, fed synthetic values, because the alternative is a branch
    only one interpreter can execute. @commons' round-5 separation: keep the
    JUDGEMENT apart from the WORLD, and every row becomes reachable on any host —
    including the row this machine cannot produce, which is the only row whose
    inversion would otherwise sail through a green suite.

    Args:
        has_accessor: Whether this interpreter's ``pathlib`` still carries
            ``_NormalAccessor`` — true on <=3.10, false from 3.11.

    Returns:
        ``"ROUTE_INERT"`` where the cure is load-bearing, ``"ROUTE_ARMED"`` where
        it patches nothing and removing it can change nothing.
    """
    return "ROUTE_INERT" if has_accessor else "ROUTE_ARMED"


class TestTheRouteExpectationIsReachableOnAnyHost:
    """Both rows of the judgement above, on whichever interpreter runs this.

    Round 7's M9: inverting the ``has_accessor`` branch of the live test left the
    suite green, because no interpreter here can enter it. That is @ai_mail's
    unfalsifiable-row species inside the pin written to answer a red about the
    same species. Naming the choice is what makes it convictable — @memory's
    ``_world_for()``, applied one file over.
    """

    def test_an_interpreter_with_an_accessor_needs_the_cure(self):
        """The 3.10 row. Unreachable as a live branch here; reachable as a value."""
        assert expected_route_without_cure(True) == "ROUTE_INERT", (
            "with a real _NormalAccessor the cure is the only thing rebinding the "
            "captured copy, so removing it must leave the route unarmed"
        )

    def test_an_interpreter_without_one_cannot_notice_the_cure(self):
        """The 3.11+ row, which is also the row this machine measures live."""
        assert expected_route_without_cure(False) == "ROUTE_ARMED"

    def test_the_two_rows_disagree(self):
        """Control: a judgement returning one constant would pass both rows above."""
        assert expected_route_without_cure(True) != expected_route_without_cure(False), (
            "the judgement is not keyed on its input — then the live test below is "
            "asserting the same thing on every interpreter and the 3.10 row is decoration"
        )


class TestTheWorldArmsOnAPreCapturedAccessor:
    """The 3.10 row, made falsifiable on an interpreter that has no accessor.

    ``_ACCESSOR_CURE`` is a no-op on 3.11+, which removed ``_NormalAccessor``. A
    cure whose only evidence is a CI leg this machine cannot run is a row nobody
    here can contradict — @ai_mail's round-5 species, where a table entry no
    local platform can falsify enters silently. So the 3.10 CONSTRUCTION is
    rebuilt here and both directions are asserted against it.

    ROUND 7, AND THIS IS THE PART WORTH READING. Two of these pins went red on
    the Windows runner, both reporting ``ACCESSOR_DIES: YES`` where they demanded
    NO. Nothing about the cure was wrong; the PROBES were. They let the emulated
    accessor capture the live ``os.path.realpath``, then asked "did a later patch
    reach it?" by denying ``os.getcwd`` and reading raise/no-raise. That
    discriminates on posix, where the captured function ignores the cwd for an
    absolute path, so a raise can only mean the patch landed. On nt
    ``os.path`` IS ``ntpath`` and ``ntpath.realpath`` reads ``os.getcwd``
    UNCONDITIONALLY — this branch's own round-4 headline, turned back on the
    instrument that quoted it — so the ORIGINAL raises too and RAISED stops
    discriminating.

    @memory measured the identical species on four of their own reds and
    published the rule the fleet adopted: AN INSTRUMENT MUST NOT IMPORT BEHAVIOUR
    IT IS NOT TESTING. Their three consequences, each verified here rather than
    imported on their word:

    1. emulate BOTH platforms or neither — a table with one emulated row and one
       bare row is host-dependent in the half nobody thought about, and "no
       emulation" reads as posix only while the host is posix;
    2. build an emulation from the dialect module BY NAME (``posixpath``,
       ``ntpath``), never from ``os.path``, which IS the host;
    3. when a probe asks "did my patch reach X", let X have captured a SENTINEL —
       otherwise the original's own platform behaviour answers the question.

    Their litmus, and every accessor probe below now runs it: exercise the probe
    under the OPPOSITE platform's emulation and require the verdict not to move.

    Built to the four traps @memory and @seedgo paid for in round 6, each of
    which makes this vacuously green:

    * ``staticmethod`` — a plain function on a class arrives bound and eats the
      path into ``self``, so the patch resolves the accessor OBJECT and a
      raise-shaped pin stays green for the wrong reason;
    * exercised through an INSTANCE (3.10's ``Path.resolve`` calls
      ``self._accessor.realpath(self, strict=strict)``); a class-level read never
      binds and never shows the trap;
    * probed with an ABSOLUTE path — ``posixpath.realpath`` reads the cwd for a
      RELATIVE one whatever else is patched, so a relative probe convicts on the
      path's shape and looks like a working world;
    * captured EAGERLY at class creation (@seedgo's M9) — a lazy capture reads
      the already-patched module attribute and the whole shape becomes a no-op
      that proves nothing.
    """

    # ------------------------------------------------------------------
    # The two hosts, built from the dialect modules BY NAME (@memory rule 2)
    # ------------------------------------------------------------------
    # ``os.path`` is the HOST: posixpath here, ntpath on the Windows runner. An
    # emulation assembled out of it emulates whatever it is already running on,
    # which is how a row labelled posix measured nt and reported it as fact.
    POSIX_HOST = """
import os
import posixpath

# Bound BEFORE the rebinding below, and this is not a style choice. On a posix
# host ``os.path IS posixpath``, so assigning ``os.path.realpath`` assigns
# ``posixpath.realpath`` — a body that then looked the name up again would call
# itself forever. Measured the hard way: the first version of this constant
# recursed 997 frames deep. The same identity that makes an os.path-built
# emulation measure the host makes it eat itself.
_posixpath_realpath = posixpath.realpath


def _posix_realpath(path, *a, **k):
    # posixpath.realpath reads the cwd ONLY for a relative path.
    return _posixpath_realpath(path, *a, **k)


os.path.realpath = _posix_realpath

# The probe path, IN THIS EMULATION'S DIALECT. Round 8: it used to be built from
# ``os.sep`` and ``pathlib.__file__`` — the HOST's dialect — and on the Windows
# runner that is ``\\definitely\\not\\here``, which posixpath reads as RELATIVE.
# posixpath.realpath reads the cwd for a relative path on every platform, so the
# posix row convicted for the path's SHAPE and reported it as "the emulation is
# not posix-shaped". The emulation was fine. Its INPUT was the host's.
ABSOLUTE = "/definitely/not/here"
"""

    NT_HOST = r"""
import os
import ntpath


def _nt_realpath(path, *a, **k):
    # CPython's ntpath.realpath takes ``cwd = os.getcwd()`` while picking its
    # str/bytes prefixes — on the first lines, before it asks whether the path
    # is even absolute. Spelled out rather than aliased to ``ntpath.realpath``,
    # because off Windows that name is a WRAPPER that returns ``abspath(path)``,
    # which reads the cwd only for a relative path: aliasing it would emulate
    # this host wearing an nt label, the exact defect this constant prevents.
    #
    # WRAPPER, not alias, and @skills paid for the distinction by source read:
    # ntpath.py defines ``realpath`` twice and picks at import on whether
    # ``nt._getfinalpathname`` exists, so off Windows you get a fallback ``def``
    # rather than a rebinding. Measured here on 3.12.3 —
    # ``ntpath.realpath is ntpath.abspath`` is FALSE. The consequence is what
    # matters: anyone checking this edge with an ``is`` test gets a green that
    # means nothing. Behaviour-equality is the claim; identity is not.
    os.getcwd()
    return ntpath.normpath(path)


os.path.realpath = _nt_realpath

# Drive-qualified, because that is what "absolute" means in this dialect. A
# posix-shaped literal passes ``ntpath.isabs`` but is DRIVE-RELATIVE — @memory
# measured ``ntpath.realpath('/tmp')`` returning ``D:\tmp`` on the runner — so
# ``isabs`` alone is not enough to call a literal absolute here.
#
# THE ENCLOSING CONSTANT IS RAW, and it has to be: a non-raw triple-quote eats
# the escapes before the child ever sees them, so ``\not\here`` arrived as a
# NEWLINE and the emitted source was an unterminated string. The instrument's
# INPUT was corrupted by the language the instrument is written in — the same
# shape as the round-8 defect itself, one layer down.
ABSOLUTE = r"C:\definitely\not\here"
"""

    # Both hosts, for the litmus. Named so a failing parametrisation says which
    # platform moved.
    HOSTS = {"posix": POSIX_HOST, "nt": NT_HOST}

    # The RUNNER, as opposed to the emulated host: the platform the test process
    # itself is executing on. Round 7's litmus varied the emulated host and held;
    # round 8 reddened anyway, because three probes read the RUNNER — ``os.sep``
    # and ``pathlib.__file__`` — to build their input. Varying the emulated world
    # cannot see that. This constant makes the runner a variable too.
    #
    # It fakes only what a probe can read to build a path. It is NOT a world and
    # must never be used as one.
    WINDOWS_RUNNER = r"""
import ntpath
import os
import pathlib

os.path = ntpath
os.sep = "\\"
pathlib.__file__ = r"D:\a\AIPass\AIPass\.venv\Lib\pathlib.py"
"""

    # The counterpart, and round 9 is why it exists. A single Windows-shaped
    # runner fake CANNOT ARM on a Windows runner: the host already is what the
    # fake supplies, so the faked and unfaked runs are byte-identical and every
    # comparison built on the difference passes for free. @seedgo's one-layer
    # rule — host == emulated is not two layers — landing in the file whose
    # round-8 reply flagged it for everybody else.
    #
    # So the runner varies toward BOTH platforms. On any host at least one of
    # these differs from it, which is @memory's "emulate both platforms or
    # neither" applied one dimension over — to the RUNNER, where round 8 applied
    # it only to the emulated world.
    POSIX_RUNNER = """
import os
import pathlib
import posixpath

os.path = posixpath
os.sep = "/"
pathlib.__file__ = "/usr/lib/python3/pathlib.py"
"""

    # Both runner shapes. Keyed by name so a failure says which one moved.
    RUNNERS = {"posix": POSIX_RUNNER, "windows": WINDOWS_RUNNER}

    # For compositions that install no host at all. The literal is deliberately
    # built in the HOST's dialect here: with no emulation in play, "absolute"
    # means whatever this interpreter means by it, and saying so beats a
    # posix literal that would be drive-relative on Windows.
    NO_HOST = """
import os

ABSOLUTE = os.path.join(os.sep, "definitely", "not", "here")
"""

    # ------------------------------------------------------------------
    # The 3.10 construction, with a SENTINEL where the live function was
    # ------------------------------------------------------------------
    # Shape byte-for-byte as CPython 3.10 Lib/pathlib.py:358
    # ``realpath = staticmethod(os.path.realpath)``, captured when the class body
    # executes — pathlib's first import, BEFORE any world is installed.
    #
    # What it captures is NOT ``os.path.realpath``. The question these probes ask
    # is "did a later patch REPLACE this attribute", and the only honest way to
    # ask it is to make the pre-patch value do nothing observable: the sentinel
    # returns its argument and touches no filesystem, no cwd, no path module. Any
    # raise afterwards is then the patch's doing, on any platform. Capturing the
    # real function instead is what reddened this file on Windows.
    SHAPE = """
import os
import pathlib


def _sentinel_captured(path, *a, **k):
    return "CAPTURED"


def _sentinel_moved(path, *a, **k):
    return "MOVED"


_source_realpath = _sentinel_captured


class _Accessor:
    realpath = staticmethod(_source_realpath)   # captured EAGERLY, as 3.10 does


# The source name MOVES after the class body has run. An eager capture kept the
# value and still answers CAPTURED; a lazy one follows the name and answers
# MOVED. @trigger's escape, and it closes a hole their correction found in my
# round-7 shape: a sentinel is stale-proof, so a LAZY wrapper AROUND a sentinel
# returns exactly what an eager capture of it returns, and the eagerness pin goes
# quietly dark while looking healthy. The durable form of an identity check is a
# difference you CONSTRUCT. No platform behaviour appears anywhere in this.
_source_realpath = _sentinel_moved


_accessor = _Accessor()
"""

    # Called through the instance, with an absolute path, exactly as 3.10's
    # Path.resolve reaches it.
    PROBE = """
try:
    _accessor.realpath(ABSOLUTE)
    print("ACCESSOR_DIES: NO")
except OSError:
    print("ACCESSOR_DIES: YES")
"""

    # The same construction, but PUBLISHED ON pathlib under the name 3.10 uses —
    # so ``_WORLD_A`` runs VERBATIM against it, hasattr and all, and the thing
    # under test is the constant that ships rather than a restatement of it.
    PUBLISHED_SHAPE = """
import os
import pathlib


def _sentinel_captured(path, *a, **k):
    return "CAPTURED"


def _sentinel_moved(path, *a, **k):
    return "MOVED"


_source_realpath = _sentinel_captured


class _NormalAccessor:
    realpath = staticmethod(_source_realpath)   # captured EAGERLY, as 3.10 does


# The source name MOVES after the class body has run. An eager capture kept the
# value and still answers CAPTURED; a lazy one follows the name and answers
# MOVED. @trigger's escape, and it closes a hole their correction found in my
# round-7 shape: a sentinel is stale-proof, so a LAZY wrapper AROUND a sentinel
# returns exactly what an eager capture of it returns, and the eagerness pin goes
# quietly dark while looking healthy. The durable form of an identity check is a
# difference you CONSTRUCT. No platform behaviour appears anywhere in this.
_source_realpath = _sentinel_moved


pathlib._NormalAccessor = _NormalAccessor
_accessor = _NormalAccessor()
"""

    BARE_MODULE_PATCH_ONLY = """
_real = os.path.realpath


def _denied_realpath(path, *a, **k):
    os.getcwd()
    return _real(path, *a, **k)


os.path.realpath = _denied_realpath


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd
"""

    # The shipped cure, written against the emulated accessor rather than
    # pathlib's, because 3.11+ has none to patch.
    EMULATED_CURE = """
_Accessor.realpath = staticmethod(_denied_realpath)
"""

    # Eagerness, measured as a value rather than as a consequence. Takes a bare
    # string, not a path: there is no filesystem, no cwd and no dialect in this
    # question, so none should be able to answer it.
    EAGERNESS_PROBE = """
print("EAGERNESS:", _accessor.realpath("probe"))
"""

    # The real route: no emulated accessor anywhere, just this interpreter's own
    # pathlib. ``import pathlib`` comes FIRST so a 3.10 accessor takes its copy
    # BEFORE the world is installed — which is the only ordering under which the
    # cure is load-bearing, and the ordering every real import fan has.
    REAL_ROUTE_PROBE = """
import os
from pathlib import Path as _RoutePath

_abs = os.path.join(os.sep, "definitely", "not", "here")
try:
    _RoutePath(_abs).resolve()
    print("ROUTE_INERT")
except OSError:
    print("ROUTE_ARMED")
"""
    PATHLIB_FIRST = "import pathlib\n"

    @staticmethod
    def _run(script: str) -> str:
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    @staticmethod
    def _run_or_reason(script: str) -> tuple[str, str | None]:
        """Run a child, returning ``(stdout, None)`` or ``(stdout, reason)``.

        ``_run`` asserts the child exited cleanly, which is right for a probe
        whose world this branch controls. It is wrong for a RUNNER fake: a host
        this file was not written on may refuse one, and failing there reports
        somebody else's platform as a flow defect. @spawn's round-8 shape —
        say UNAVAILABLE with the child's own reason and skip that row, never
        fail on an interpreter you do not have.
        """
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return result.stdout, (result.stderr.strip().splitlines() or ["no diagnostic"])[-1]
        return result.stdout, None

    def _runner_verdicts(self, body: str, runners: dict[str, str]) -> dict[str, str]:
        """Every verdict for *body*, once bare and once under each runner fake.

        RAISES on a row that could not be measured, rather than returning a dict
        that quietly has fewer keys than it should. That is deliberate: round 9's
        lesson is that a row which cannot speak must not be mistaken for a row
        that agreed, and an assertion sitting beside the collector was
        unconvictable — no runner fake fails on this host, so deleting it changed
        nothing. Making the refusal part of the collector's contract lets a
        synthetic broken runner convict it here.

        Args:
            body: The composed child script whose verdict is being compared.
            runners: Runner fakes to prepend, keyed by name.

        Returns:
            Verdicts keyed by runner name, plus ``"<no runner fake>"``.

        Raises:
            AssertionError: If any runner fake could not be installed.
        """
        bare, reason = self._run_or_reason(body)
        assert reason is None, f"the unfaked run failed, so nothing here is measurable: {reason}"

        verdicts = {"<no runner fake>": bare.strip()}
        for runner in sorted(runners):
            out, why = self._run_or_reason(runners[runner] + body)
            assert why is None, (
                f"the {runner!r} runner fake could not be installed, so that row was not "
                "measured at all. A row that cannot speak is not a row that agreed — this "
                f"is a fact about this host, not a verdict about the probes: {why}"
            )
            verdicts[runner] = out.strip()
        return verdicts

    @staticmethod
    def _literal_from(host: str) -> str:
        """The probe path a host publishes, read out of the constant itself.

        Parsed rather than restated: a pin that hard-codes the literal it is
        checking stops noticing when the constant changes, which is the failure
        mode of every table written twice.
        """
        line = next(entry for entry in host.splitlines() if entry.startswith("ABSOLUTE = "))
        return ast.literal_eval(line.split("=", 1)[1].strip())

    @staticmethod
    def _world_without_cure() -> str:
        """``_WORLD_A`` with the shipped cure sliced out, read off the constants.

        Both operands come from the module rather than being restated, so a
        control built on this cannot quietly start proving a different four lines
        than the ones that ship.
        """
        world = _WORLD_A.replace(_ACCESSOR_CURE, "")
        assert world != _WORLD_A, "the cure is not a substring of the world — this slice is not slicing anything"
        return world

    # ------------------------------------------------------------------
    # The defect direction: a bare module patch must not reach the capture
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("host", sorted(HOSTS))
    def test_a_bare_module_attribute_patch_does_not_reach_a_captured_accessor(self, host):
        """CI's Python 3.10 failure, reproduced on this machine — under BOTH hosts.

        This is the defect: the denial lands on ``os.path.realpath`` and the
        accessor keeps calling the copy it took at import. Every pin that
        depended on the world would have been vacuously green.

        Round 7 added the host parametrisation and the sentinel. Before them this
        pin read ``ACCESSOR_DIES: YES`` on the Windows runner and reported it as
        "a bare module-attribute patch reached the captured accessor" — which was
        false. Nothing had reached anything; the captured ``ntpath.realpath`` was
        raising on its own unconditional ``os.getcwd()``.
        """
        out = self._run(self.HOSTS[host] + self.SHAPE + self.BARE_MODULE_PATCH_ONLY + self.PROBE)

        assert "ACCESSOR_DIES: NO" in out, (
            f"under the {host} host a bare module-attribute patch appeared to reach the "
            "captured accessor. Either the patch really did land — and then the 3.10 CI "
            "failure has no mechanism and this whole cure is unexplained — or the capture "
            "is not a sentinel and the platform's own realpath is answering instead: " + out
        )

    @pytest.mark.parametrize("host", sorted(HOSTS))
    def test_the_published_shape_captures_eagerly(self, host):
        """Trap (d) as a control on the PUBLISHED half, where it was missing.

        Found by mutation in round 6, not by reading: making ``PUBLISHED_SHAPE``
        capture lazily left the whole class green. A lazy capture follows the
        patched module attribute, so the arming pin below passes WITHOUT
        ``_ACCESSOR_CURE`` doing anything — it stops distinguishing an accessor
        patch from a module patch, which is @seedgo's M9 one level along.

        So: the shipped world with its cure REMOVED must leave this shape alive,
        under either host.
        """
        out = self._run(self.HOSTS[host] + self.PUBLISHED_SHAPE + self._world_without_cure() + self.PROBE)

        assert "ACCESSOR_DIES: NO" in out, (
            f"under the {host} host a module-only patch appeared to reach the published "
            "accessor, so either it is not capturing eagerly or the capture is not a "
            "sentinel — and the arming pin below is green for the wrong reason: " + out
        )

    @pytest.mark.parametrize("host", sorted(HOSTS))
    def test_the_published_shape_is_inert_without_the_world(self, host):
        """Control: the shape alone must not convict, or the arming pin is free."""
        out = self._run(self.HOSTS[host] + self.PUBLISHED_SHAPE + self.PROBE)

        assert "ACCESSOR_DIES: NO" in out, (
            f"under the {host} host the accessor died with no world installed at all — "
            "the arming pin is measuring something other than the world: " + out
        )

    # ------------------------------------------------------------------
    # The cure direction: the shipped world must arm the capture
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("host", sorted(HOSTS))
    def test_the_shipped_world_arms_through_a_pre_captured_accessor(self, host):
        """The cure, exercised as ``_WORLD_A`` VERBATIM against a 3.10-shaped accessor.

        Everything above establishes that the construction reproduces CI; this
        runs the SHIPPED world text against it and asserts it arms — so deleting
        ``_ACCESSOR_CURE`` reds here with CI's own sentence, on an interpreter
        that has no accessor of its own.
        """
        out = self._run(self.HOSTS[host] + self.PUBLISHED_SHAPE + _WORLD_A + self.PROBE)

        assert "ACCESSOR_DIES: YES" in out, (
            f"under the {host} host the ntpath world did not arm — the shipped world's "
            "denial did not reach a pre-captured accessor, which is exactly the Python "
            "3.10 failure on 8550ed10: " + out
        )

    @pytest.mark.parametrize("host", sorted(HOSTS))
    def test_patching_the_accessor_arms_the_same_world(self, host):
        """The same direction through the local emulation, without pathlib in it.

        Kept alongside the pin above because it isolates the CURE from the
        ``hasattr`` lookup: if ``pathlib._NormalAccessor`` ever stops being the
        name the world reaches for, this one still says whether patching an
        accessor arms the world at all.
        """
        out = self._run(self.HOSTS[host] + self.SHAPE + self.BARE_MODULE_PATCH_ONLY + self.EMULATED_CURE + self.PROBE)

        assert "ACCESSOR_DIES: YES" in out, (
            f"under the {host} host the accessor patch did not arm the world it exists to arm: " + out
        )

    # ------------------------------------------------------------------
    # The litmus, stated as its own pin rather than left implicit
    # ------------------------------------------------------------------

    def test_no_accessor_verdict_moves_between_the_two_hosts(self):
        """@memory's litmus, run over every direction at once.

        The parametrisation above already runs each probe on both hosts, but it
        asserts a CONSTANT per probe. This asserts the weaker, more general thing
        the constants are an instance of: the platform must not be able to change
        any verdict. If someone later relaxes one expectation to a per-host value,
        this pin is what refuses.
        """
        directions = {
            "bare-patch": self.SHAPE + self.BARE_MODULE_PATCH_ONLY + self.PROBE,
            "published-no-cure": self.PUBLISHED_SHAPE + self._world_without_cure() + self.PROBE,
            "published-bare": self.PUBLISHED_SHAPE + self.PROBE,
            "published-cured": self.PUBLISHED_SHAPE + _WORLD_A + self.PROBE,
            "emulated-cure": self.SHAPE + self.BARE_MODULE_PATCH_ONLY + self.EMULATED_CURE + self.PROBE,
        }
        moved = {
            name: (self._run(self.POSIX_HOST + body).strip(), self._run(self.NT_HOST + body).strip())
            for name, body in directions.items()
        }
        disagreed = {name: pair for name, pair in moved.items() if pair[0] != pair[1]}

        assert disagreed == {}, (
            "an accessor verdict changed with the emulated platform, so the probe is "
            f"measuring the host rather than the patch: {disagreed}"
        )

    def test_no_verdict_moves_when_the_runner_changes_shape(self):
        """ROUND 8's instrument, cured of ROUND 9's blindness.

        Round 7's litmus varied the emulated HOST and held; round 8 reddened
        anyway because two probes read the RUNNER — ``os.sep``,
        ``pathlib.__file__`` — to build their input. So round 8 added a
        Windows-shaped runner fake and required no verdict to move.

        THAT FAKE CANNOT ARM ON A WINDOWS RUNNER. The host already is what it
        supplies, so faked and unfaked runs are byte-identical and the comparison
        passes for free — measured on the windows-setup leg of 9bd2618b, where
        the control below reported the two outputs equal character for character.
        The litmus was DARK on exactly the platform it was written to catch, and
        that is worse than the red that reported it: the red was one assertion,
        the darkness was the whole instrument.

        HOST == FAKED IS ONE LAYER — @seedgo's rule, arriving in the file whose
        round-8 reply passed it on to everyone else. The cure is @memory's
        "emulate both platforms or neither" applied one dimension over: the
        runner varies toward BOTH shapes, so on any host at least one fake
        genuinely differs from it, and the bare run is compared against both.
        """
        live_shape = self.SHAPE.replace("staticmethod(_source_realpath)", "staticmethod(os.path.realpath)")
        directions = {
            f"{host}:{name}": self.HOSTS[host] + body
            for host in sorted(self.HOSTS)
            for name, body in {
                "bare-patch": self.SHAPE + self.BARE_MODULE_PATCH_ONLY + self.PROBE,
                "published-cured": self.PUBLISHED_SHAPE + _WORLD_A + self.PROBE,
                "published-no-cure": self.PUBLISHED_SHAPE + self._world_without_cure() + self.PROBE,
                "live-capture": live_shape + self.BARE_MODULE_PATCH_ONLY + self.PROBE,
            }.items()
        }

        disagreed = {}
        for name, body in directions.items():
            verdicts = self._runner_verdicts(body, self.RUNNERS)
            if len(set(verdicts.values())) > 1:
                disagreed[name] = verdicts

        assert disagreed == {}, (
            "a verdict changed when only the RUNNER changed. The world under test was "
            "identical in every run, so something in the probe is reading the host to "
            "build its input — most likely a path spelled with os.sep or derived from a "
            f"module's __file__, which posixpath reads as relative on Windows: {disagreed}"
        )

    def test_a_runner_fake_that_cannot_install_is_refused_not_skipped(self):
        """The UNAVAILABLE row, made reachable on a host where nothing is unavailable.

        No runner fake fails here, so the refusal branch is unreachable from any
        real composition — the species that keeps recurring in this file, and a
        mutant confirmed it: deleting the check left all 47 pins green. Cured by
        feeding the collector a synthetic runner that cannot install, which is a
        difference constructed rather than waited for.

        The distinction being defended: SKIPPING an unmeasurable row makes it
        indistinguishable from a row that agreed, and every verdict-comparison
        above would then be over a smaller set than it claims.
        """
        broken = {"deliberately-broken": "raise RuntimeError('this runner fake cannot install here')\n"}

        with pytest.raises(AssertionError, match="was not measured at all"):
            self._runner_verdicts(self.NO_HOST + self.PUBLISHED_SHAPE + self.PROBE, broken)

    def test_the_collector_reports_every_row_when_they_all_install(self):
        """Control: a collector that always raised would pass the pin above for free."""
        verdicts = self._runner_verdicts(self.NO_HOST + self.PUBLISHED_SHAPE + self.PROBE, self.RUNNERS)

        assert set(verdicts) == {"<no runner fake>", *self.RUNNERS}, (
            f"the collector dropped a row on a host where every fake installs: {verdicts}"
        )

    def test_at_least_one_runner_fake_changes_what_a_probe_reads(self):
        """ROUND 9's red, cured with three states instead of a bare difference.

        This is the control for the litmus above, and it used to assert that the
        Windows fake changed something. On Linux it does; on the Windows runner
        it changes NOTHING, because the host already supplies exactly what the
        fake supplies — and the assertion fired, reporting "the litmus is
        vacuous" as though the instrument were broken. The instrument was fine on
        that host and the CONTROL was the thing that could not survive being run
        where its subject was already true.

        Three states now, and each is an OUTPUT rather than a silence:

        * CHANGED — the fake altered what a probe reads;
        * ALREADY — the host is already this shape, with the host's own
          ``os.name``/``os.sep`` printed as the reason, so a no-op and a broken
          fake are different results;
        * UNAVAILABLE — the fake could not be installed here, carrying the
          child's own diagnostic (@spawn's shape: never fail on someone else's
          host, and never stay quiet about it either).

        The assertion that cannot go dark: at least one fake must report CHANGED
        on every host. Both fakes reporting ALREADY would mean the runner
        dimension is unvaried, which is round 9 again in either direction.
        """
        probe = """
import os
import pathlib

print("SEP:", repr(os.sep))
print("HOST_BUILT:", repr(os.path.join(os.sep, "x")))
print("PATHLIB_FILE_ABS_TO_POSIX:", __import__("posixpath").isabs(str(pathlib.__file__)))
"""
        bare, bare_reason = self._run_or_reason(probe)
        assert bare_reason is None, f"the unfaked probe itself failed, so nothing below is measurable: {bare_reason}"

        verdicts = {}
        for runner in sorted(self.RUNNERS):
            out, reason = self._run_or_reason(self.RUNNERS[runner] + probe)
            if reason is not None:
                verdicts[runner] = f"UNAVAILABLE: {reason}"
            elif out != bare:
                verdicts[runner] = "CHANGED"
            else:
                verdicts[runner] = f"ALREADY (this host is already {runner}-shaped: {bare.strip()!r})"

        changed = [runner for runner, state in verdicts.items() if state == "CHANGED"]

        assert changed, (
            "NO runner fake changed anything a probe reads, so the runner dimension is "
            "unvaried on this host and the litmus above is passing for free. With one fake "
            "per platform that should be impossible — unless both were refused, or both "
            f"now supply what the host already had: {verdicts}"
        )

    @pytest.mark.parametrize("simulated_host", ["posix", "windows"])
    def test_the_runner_set_arms_on_either_kind_of_host(self, simulated_host):
        """Round 9's species, made falsifiable on the one machine available.

        The pin above asserts that some runner fake changes something on THIS
        host. That is necessary and it is not enough: it was true on Linux for
        the whole of round 8, while being false on the runner that mattered. A
        row only this host can satisfy is exactly the thing round 9 was.

        So both KINDS of host are simulated here and the requirement is checked
        against each: whatever shape the runner turns out to be, some fake in
        ``RUNNERS`` must still differ from it. Deleting either fake reds this on
        Linux — which is the whole point, because deleting the posix one is the
        round-8 state and no probe on this machine could previously tell.

        The simulated host is applied FIRST and the fake stacked on top, so the
        stacked case (host == faked) is exercised deliberately rather than met by
        accident on somebody's CI leg.
        """
        host_prefix = "" if simulated_host == "posix" else self.WINDOWS_RUNNER
        probe = """
import os
import pathlib

print("SEP:", repr(os.sep))
print("HOST_BUILT:", repr(os.path.join(os.sep, "x")))
print("PATHLIB_FILE_ABS_TO_POSIX:", __import__("posixpath").isabs(str(pathlib.__file__)))
"""
        bare, reason = self._run_or_reason(host_prefix + probe)
        assert reason is None, f"the {simulated_host}-shaped host could not run the probe at all: {reason}"

        states = {}
        for runner in sorted(self.RUNNERS):
            out, why = self._run_or_reason(host_prefix + self.RUNNERS[runner] + probe)
            states[runner] = f"UNAVAILABLE: {why}" if why else ("CHANGED" if out != bare else "ALREADY")

        assert "CHANGED" in states.values(), (
            f"on a {simulated_host}-shaped runner NO fake in RUNNERS changes what a probe "
            "reads, so the runner dimension collapses there and the litmus passes for "
            "free. This is the round-9 failure reproduced: host == faked is one layer. "
            f"{states}"
        )

    @pytest.mark.parametrize(
        ("runner", "expected"),
        [
            ("posix", {"SEP_IS_BACKSLASH": "False", "PATH_MODULE": "posixpath", "FILE_ABS_TO_POSIX": "True"}),
            ("windows", {"SEP_IS_BACKSLASH": "True", "PATH_MODULE": "ntpath", "FILE_ABS_TO_POSIX": "False"}),
        ],
    )
    def test_each_runner_fake_overrides_every_host_read_a_probe_makes(self, runner, expected):
        """A fake that covers SOME of the host reads is not a fake, it is a leak.

        Found by mutation and it survived the coarser pins: deleting the
        ``pathlib.__file__`` line from ``POSIX_RUNNER`` left every other pin
        green, because that fake still changes ``os.sep`` and ``os.path``, so
        "at least one fake CHANGED something" was satisfied while one of the
        three host reads still came from the host. On Linux the omission is
        invisible — ``pathlib.__file__`` is already posix — and load-bearing on
        the Windows runner, where it is the ``D:\\...`` path that reddened round 8.

        So each fake is checked ATTRIBUTE BY ATTRIBUTE, under the OPPOSITE
        simulated host, against the three reads the probes in this file actually
        make. Any read that still answers with the host's value is a hole the
        coarse pins cannot see.
        """
        opposite = self.WINDOWS_RUNNER if runner == "posix" else ""
        probe = """
import os
import pathlib
import posixpath

# A derived boolean, not repr(os.sep): a backslash crossing a string boundary
# gets eaten by whichever quoting layer is least expected, which cost three
# separate repairs across rounds 8 and 9. Nothing here needs the character
# itself — only whether the fake supplied it.
print("SEP_IS_BACKSLASH", os.sep == chr(92))
print("PATH_MODULE", os.path.__name__)
print("FILE_ABS_TO_POSIX", posixpath.isabs(str(pathlib.__file__)))
"""
        out, reason = self._run_or_reason(opposite + self.RUNNERS[runner] + probe)
        assert reason is None, f"the {runner} fake could not be installed over the opposite host: {reason}"

        reported = dict(line.split(" ", 1) for line in out.strip().splitlines())
        leaked = {
            key: reported.get(key) for key, want in expected.items() if reported.get(key, "").strip("'\"") != want
        }

        assert leaked == {}, (
            f"the {runner!r} runner fake did not override every host read a probe makes, so "
            "those reads still answer with the host's value. On this machine that is "
            "invisible for whichever reads the host already matches — which is exactly how "
            f"it ships and reds on the other platform: {leaked} (full: {reported})"
        )

    def test_the_host_table_covers_every_dialect_it_is_built_from(self):
        """@seedgo's SHORT-TABLE nomination, ruled on rather than inherited.

        Their checker flags five parametrisations here for reading
        ``sorted(HOSTS)`` — a table computed at collection time whose only guard
        is non-emptiness, which a collector dropping ONE entry still satisfies.
        The ruling: the nomination is right about the shape and the table was
        already guarded, just not anywhere their checker could see. Measured
        before answering — deleting the ``nt`` row reds
        ``test_the_two_hosts_are_genuinely_different_worlds``, which names both
        constants directly. A guard that only a mutation run can find is not much
        of a guard for the next reader, so it is spelled out here.

        DERIVED, not restated: the expected keys come from the dialect modules the
        constants actually import, so adding a host without a dialect or dropping
        a dialect without its host both red. Writing ``{"posix", "nt"}`` as a
        literal would be the table written twice.
        """
        named_after = {"posixpath": "posix", "ntpath": "nt"}
        dialects = {
            module: name
            for name, host in self.HOSTS.items()
            for module in ("posixpath", "ntpath")
            if f"import {module}" in host
        }

        assert dialects == {module: named_after[module] for module in dialects}, (
            "a host is registered under a name that does not match the dialect it is built "
            f"from, so a parametrisation labelled posix may be emulating nt: {dialects}"
        )
        assert set(dialects.values()) == set(self.HOSTS), (
            "a host in HOSTS is not built from a dialect module at all: "
            f"{sorted(dialects.values())} vs {sorted(self.HOSTS)}"
        )
        assert set(dialects) == {"posixpath", "ntpath"}, (
            "HOSTS no longer covers both path dialects. Every parametrisation over "
            "sorted(HOSTS) silently loses a row when this shrinks, and the remaining rows "
            f"still pass — @seedgo's SHORT-TABLE species: {sorted(dialects)}"
        )

    def test_the_two_hosts_are_genuinely_different_worlds(self):
        """Control for the litmus: two identical hosts would pass it for free.

        Measures the one behaviour the whole round turns on — ``ntpath.realpath``
        reads the cwd for an ABSOLUTE path and ``posixpath.realpath`` does not —
        through the emulations themselves, so a future edit that quietly makes
        ``NT_HOST`` posix-shaped reds here instead of silently disarming the
        litmus above.
        """
        # ABSOLUTE comes from the host prefix, so each row is probed with a path
        # its own dialect calls absolute. Building it here from ``os.sep`` is the
        # round-8 defect: on the Windows runner that produced a backslash literal,
        # posixpath read it as relative, and this pin reported "the posix
        # emulation is not posix-shaped" about a perfectly good emulation.
        probe = """
import os


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd
try:
    os.path.realpath(ABSOLUTE)
    print("ABSOLUTE_READS_CWD: NO")
except OSError:
    print("ABSOLUTE_READS_CWD: YES")
"""
        assert "ABSOLUTE_READS_CWD: NO" in self._run(self.POSIX_HOST + probe), (
            "the posix emulation read the cwd for an absolute path — it is not posix-shaped"
        )
        assert "ABSOLUTE_READS_CWD: YES" in self._run(self.NT_HOST + probe), (
            "the nt emulation did NOT read the cwd for an absolute path — it is this host "
            "wearing an nt label, and every 'verdict did not move' result above is free"
        )

    # ------------------------------------------------------------------
    # The real accessor, on whichever interpreter actually has one
    # ------------------------------------------------------------------

    def test_the_cure_matches_the_accessor_this_interpreter_has(self):
        """Both interpreters, one probe, no assertion about the host taken on faith.

        ROUND 7 RED, and the assertion text named its own fix: this used to be
        ``assert not hasattr(pathlib, "_NormalAccessor")`` — "on 3.11+ the shipped
        four lines patch nothing" — which is true on three CI legs and FALSE on
        3.10, where the cure is live by design. A pin that reds on the one
        interpreter the cure exists for was measuring the emulation's redundancy,
        not the cure.

        So it is a two-row table now, and the row that runs is measured LIVE on
        whichever interpreter runs it:

        * every interpreter — the shipped world must ARM the real
          ``Path.resolve`` route. This is the invariant the cure exists to hold,
          and on 3.10 it is the REAL ``_NormalAccessor`` being exercised, not an
          emulation of one.
        * with a real accessor (<=3.10) — removing the cure must go INERT, which
          is what makes it load-bearing rather than decorative.
        * without one (3.11+) — removing the cure must change NOTHING, which is
          what "inert here" actually means and is the honest version of the
          deleted assertion.

        ``pathlib`` is imported FIRST so a 3.10 accessor takes its copy before the
        world exists. Without that ordering the accessor captures the already
        denied function, the cure looks unnecessary, and the row lies in the
        direction of a passing test.
        """
        import pathlib

        has_accessor = hasattr(pathlib, "_NormalAccessor")
        armed = self._run(self.PATHLIB_FIRST + _WORLD_A + self.REAL_ROUTE_PROBE)

        assert "ROUTE_ARMED" in armed, (
            "the shipped world did not arm this interpreter's own Path.resolve — "
            f"whatever the accessor situation is (has_accessor={has_accessor}), the world "
            "is not hostile and every import fan above is vacuous: " + armed
        )

        without = self._run(self.PATHLIB_FIRST + self._world_without_cure() + self.REAL_ROUTE_PROBE)
        expected = expected_route_without_cure(has_accessor)

        assert expected in without, (
            f"this interpreter reports has_accessor={has_accessor}, so removing "
            f"_ACCESSOR_CURE was expected to leave the real resolve route {expected}. "
            "With an accessor that means the cure is the only thing rebinding the captured "
            "copy; without one it means the cure patches nothing and cannot be noticed. "
            "Neither held: " + without
        )

    def test_the_shipped_cure_is_the_thing_being_emulated(self):
        """The emulation must not drift from the constant that actually ships.

        Reads ``_ACCESSOR_CURE`` rather than restating it: an emulation that
        proves a DIFFERENT four lines than the ones shipped proves nothing about
        CI.
        """
        assert "staticmethod(_denied_realpath)" in _ACCESSOR_CURE, (
            "the shipped cure no longer assigns a staticmethod — a plain function "
            "arrives bound and resolves the accessor object instead of the path"
        )
        assert "_NormalAccessor" in _ACCESSOR_CURE
        assert "hasattr" in _ACCESSOR_CURE, (
            "the shipped cure is no longer guarded — it must be a no-op on 3.11+, which removed the accessor"
        )
        # The emulation patches the same attribute name, the same way.
        assert "staticmethod(_denied_realpath)" in self.EMULATED_CURE

    def test_the_capture_is_a_sentinel_and_not_the_live_function(self):
        """The round-7 cure, pinned in the source rather than only in behaviour.

        The behavioural pins above would all pass again on Linux if someone
        restored ``staticmethod(os.path.realpath)`` — that is exactly the state
        this file shipped in, green here and red on Windows. So the sentinel is
        asserted structurally too, in both shapes.
        """
        for name, shape in (("SHAPE", self.SHAPE), ("PUBLISHED_SHAPE", self.PUBLISHED_SHAPE)):
            assert "_sentinel_captured" in shape and "staticmethod(_source_realpath)" in shape, (
                f"{name} no longer captures a sentinel. If it captures the live "
                "os.path.realpath, then on nt it captures ntpath.realpath, which reads "
                "os.getcwd unconditionally — the ORIGINAL raises and 'it raised' stops "
                "meaning 'the patch reached it'"
            )
            assert "os.path.realpath" not in shape.split("class ")[0], (
                f"{name} reads os.path in the captured value — an instrument must not "
                "import behaviour it is not testing (@memory, round 7)"
            )

    @pytest.mark.parametrize("shape_name", ["SHAPE", "PUBLISHED_SHAPE"])
    def test_the_capture_is_eager_measured_by_its_return_value(self, shape_name):
        """@trigger's escape, adopted after their correction found the hole.

        I told them an identity check beats a behavioural one because
        "consequences can be satisfied by accident; identities cannot". They
        showed the missing clause: identities cannot be satisfied by accident,
        but they CAN GO DARK when the thing whose identity you are checking stops
        being able to differ. A sentinel is stale-proof by construction, so a lazy
        wrapper AROUND the sentinel returns exactly what an eager capture of it
        returns — and every behavioural eagerness pin in this class answered the
        same either way. Measured, not conceded: mutating ``PUBLISHED_SHAPE`` to a
        lambda around the sentinel left ``test_the_published_shape_captures_eagerly``
        GREEN. The pins that did catch it caught it on a string guard, which is
        an accident of how the mutation was spelled.

        So eagerness is a constructed difference now. The source name is rebound
        AFTER the class body runs: an eager capture kept the value and answers
        CAPTURED, a lazy one follows the name and answers MOVED. Return-value, and
        no filesystem, cwd or path dialect anywhere in the question.
        """
        shape = getattr(self, shape_name)
        out = self._run(shape + self.EAGERNESS_PROBE)

        assert "EAGERNESS: CAPTURED" in out, (
            f"{shape_name} did not keep the value bound at class creation — it is following "
            "the source name, so it captures LAZILY and stops emulating 3.10, where the "
            "accessor holds a copy taken at pathlib's first import: " + out
        )

    def test_the_eagerness_probe_can_report_the_other_answer(self):
        """Control: a probe that can only print CAPTURED proves nothing.

        Builds the lazy shape explicitly and requires MOVED, so the pin above is
        known to be reading a two-valued question rather than a constant.
        """
        lazy = self.PUBLISHED_SHAPE.replace(
            "realpath = staticmethod(_source_realpath)",
            "realpath = staticmethod(lambda p, *a, **k: _source_realpath(p, *a, **k))",
        )
        assert lazy != self.PUBLISHED_SHAPE, "the lazy variant is not replacing anything"

        out = self._run(lazy + self.EAGERNESS_PROBE)

        assert "EAGERNESS: MOVED" in out, (
            "a deliberately LAZY capture still answered CAPTURED — the source-name move is "
            "not happening after the class body, so the pin above cannot distinguish "
            "eager from lazy and is green by construction: " + out
        )

    def test_a_lazy_capture_would_prove_nothing(self):
        """@seedgo's M9, pinned as a control on the emulation itself.

        If the shape captured LAZILY it would read the already-patched module
        attribute, the bare-patch test would report DIES: YES, and the whole
        construction would silently stop reproducing 3.10.
        """
        lazy_shape = self.SHAPE.replace(
            "realpath = staticmethod(_source_realpath)   # captured EAGERLY, as 3.10 does",
            "realpath = staticmethod(lambda p, *a, **k: os.path.realpath(p, *a, **k))",
        )
        assert lazy_shape != self.SHAPE, "the lazy variant is not replacing anything"

        out = self._run(self.NO_HOST + lazy_shape + self.BARE_MODULE_PATCH_ONLY + self.PROBE)

        assert "ACCESSOR_DIES: YES" in out, (
            "a lazy capture did NOT follow the patched module attribute, so it is "
            "not the no-op M9 describes and this control is not controlling: " + out
        )

    def test_each_host_probes_with_a_path_its_own_dialect_calls_absolute(self):
        """ROUND 8's red, and the rule it generalises to.

        An instrument must not import behaviour it is not testing — and its
        INPUTS are behaviour. Round 7 fixed the captured FUNCTION and left the
        probe PATH built from ``os.sep`` and ``pathlib.__file__``, which are the
        host's. On the Windows runner that yields ``\\definitely\\not\\here``;
        posixpath reads it as RELATIVE, reads the cwd, and raises — so the posix
        row convicted for the path's shape and announced "the posix emulation is
        not posix-shaped" about an emulation that was doing its job.

        Measured on every platform, because both dialect modules import
        everywhere. Asserted with ``isabs`` from the dialect module BY NAME, for
        the same reason the emulations are built that way.

        THE TABLE IS NOT SYMMETRIC and pretending otherwise would hide the more
        dangerous half:

        * posixpath REFUSES an nt literal — ``isabs`` is False, and that refusal
          is the whole round-8 defect;
        * ntpath ACCEPTS a posix literal — ``isabs`` is True — but treats it as
          DRIVE-RELATIVE, which is @memory's ``ntpath.realpath('/tmp') ->
          D:\\tmp`` on the runner. So an nt probe path must carry a DRIVE, and
          ``isabs`` alone is not enough to call it absolute.
        """
        import ntpath
        import posixpath

        posix_literal = self._literal_from(self.POSIX_HOST)
        nt_literal = self._literal_from(self.NT_HOST)

        assert posixpath.isabs(posix_literal), (
            f"the posix host probes with {posix_literal!r}, which posixpath does not call "
            "absolute — posixpath.realpath reads the cwd for a relative path on EVERY "
            "platform, so this row would convict for the path's shape"
        )
        assert ntpath.isabs(nt_literal) and ntpath.splitdrive(nt_literal)[0], (
            f"the nt host probes with {nt_literal!r}, which carries no drive — ntpath "
            "resolves a driveless path against the current drive, so the row measures the "
            "runner's volume rather than the emulation"
        )

        # The negative half: this is what went wrong, stated as a fact rather
        # than as history, so it reds if anyone reintroduces a host-built path.
        assert not posixpath.isabs(nt_literal), (
            "an nt-shaped literal is absolute to posixpath — then the round-8 defect had "
            "no mechanism and this pin is not guarding what it claims"
        )
        assert not ntpath.splitdrive(posix_literal)[0], (
            "a posix literal carries a drive — the drive-relative asymmetry above is not real"
        )

    @pytest.mark.parametrize("host", sorted(HOSTS))
    def test_each_host_publishes_a_literal_and_never_computes_one(self, host):
        """@trigger's round-9 offer, taken: a literal is immune, host-derived is not.

        Round 8 cured the two probe paths that were built from ``os.sep`` and
        ``pathlib.__file__``, but nothing stopped the NEXT edit from computing one
        from the host again — and a computed path is the round-8 defect returning
        under a different spelling. ``_literal_from`` already refuses one, but it
        refuses by raising out of ``ast.literal_eval`` with "malformed node",
        which names no species and teaches the next reader nothing.

        So the refusal is stated here instead: the right-hand side must be a
        string constant. ``os.path.join(os.sep, ...)``, ``sys.executable``,
        ``__file__`` — every host-derived spelling is a ``Call``, a ``Name`` or an
        ``Attribute``, and every one of them reds on Linux without a Windows
        runner to find it.
        """
        line = next(entry for entry in self.HOSTS[host].splitlines() if entry.startswith("ABSOLUTE = "))
        node = ast.parse(line).body[0].value

        assert isinstance(node, ast.Constant) and isinstance(node.value, str), (
            f"the {host} host COMPUTES its probe path rather than publishing one: "
            f"{ast.unparse(node)}. Anything read off the running host — os.sep, "
            "sys.executable, __file__, os.getcwd() — carries the RUNNER's dialect into "
            "an emulation that is not the runner, which is exactly the round-8 defect; "
            "a plain literal cannot"
        )

    def test_the_real_route_probe_deliberately_uses_the_host_dialect(self):
        """The one exception, pinned so it is not "fixed" into a bug.

        ``REAL_ROUTE_PROBE`` exercises THIS interpreter's own ``pathlib`` with no
        emulation anywhere, so the host's dialect is the correct one and
        ``os.sep`` is the right way to build its path. Replacing it with a posix
        literal would make the probe drive-relative on Windows and quietly change
        what the 3.10 row measures.
        """
        assert "os.sep" in self.REAL_ROUTE_PROBE, (
            "the real-route probe stopped building its path from os.sep. It has no "
            "emulation installed, so a fixed literal would be the WRONG dialect on one "
            "platform — this is the one probe that should read the host"
        )
        assert "ABSOLUTE" not in self.REAL_ROUTE_PROBE, (
            "the real-route probe now reads a host constant's ABSOLUTE — it installs no "
            "host, so that name is either undefined or leaking in from a composition"
        )

    def test_each_host_is_built_from_its_own_dialect_module(self):
        """@memory's rule 2, pinned in the source because behaviour cannot pin it here.

        Building ``POSIX_HOST`` out of ``os.path`` is EQUIVALENT on this machine —
        ``os.path IS posixpath``, so every verdict is identical and no probe can
        tell. It is load-bearing on the Windows runner, where the same line would
        capture ``ntpath.realpath`` and the "posix" host would emulate nt. That is
        the round-7 defect exactly, one constant over.

        A mutant proved it: swapping the dialect module for ``os.path`` left all
        33 pins green. So the rule is asserted where it is checkable rather than
        published as a survivor nobody can convict.
        """
        assert "_posixpath_realpath = posixpath.realpath" in self.POSIX_HOST, (
            "the posix emulation no longer captures posixpath BY NAME. On nt os.path IS "
            "ntpath, so this row would emulate the runner and report it as posix"
        )
        assert "ntpath." in self.NT_HOST, "the nt emulation no longer references ntpath by name"
        for name, host in (("POSIX_HOST", self.POSIX_HOST), ("NT_HOST", self.NT_HOST)):
            # Comments are stripped first: both constants EXPLAIN the os.path trap
            # in prose, and a check that cannot tell the explanation from the
            # defect reds on its own documentation. (It did, on the first run.)
            capture = "\n".join(
                line for line in host.split("def ")[0].splitlines() if not line.lstrip().startswith("#")
            )
            assert "os.path.realpath" not in capture, (
                f"{name} reads os.path before installing its own function — os.path IS the "
                "host, so the emulation would inherit exactly what it exists to replace"
            )

    def test_the_capture_ordering_is_what_makes_the_cure_load_bearing(self):
        """Why ``PATHLIB_FIRST`` exists, measured rather than asserted.

        Removing ``PATHLIB_FIRST`` is EQUIVALENT on 3.11+ and load-bearing on
        3.10 — a mutant confirmed the whole suite stays green without it here. The
        claim it encodes is about ORDER, and order IS measurable on this host
        through the published accessor: capture before the world and a bare module
        patch cannot reach it; capture after, and the accessor takes the already
        denied function and arms with no cure at all.

        That second row is also the scope @trigger corrected me on: import order
        decides on 3.10, where a captured copy exists to go stale. On 3.12 the
        flavour is read at call time and order is irrelevant — which is why this
        pin measures the ORDERING against an emulated capture rather than claiming
        anything about this interpreter's own pathlib.
        """
        world = self._world_without_cure()
        # The LIVE capture, deliberately: staleness is a property of holding a real
        # copy, and a sentinel is stale-proof by construction — it returns its
        # argument whenever it was captured. Measuring ordering through the
        # sentinel shape reports NO in both directions and proves nothing, which
        # is how the first version of this pin failed. Run under POSIX_HOST so the
        # absolute probe convicts only when the patch landed.
        live_capture = self.PUBLISHED_SHAPE.replace("staticmethod(_source_realpath)", "staticmethod(os.path.realpath)")
        assert live_capture != self.PUBLISHED_SHAPE

        before = self._run(self.POSIX_HOST + live_capture + world + self.PROBE)
        after = self._run(self.POSIX_HOST + world + live_capture + self.PROBE)

        assert "ACCESSOR_DIES: NO" in before, (
            "a capture taken BEFORE the world followed a later module patch — then there "
            "is no stale copy, and the cure has nothing to cure: " + before
        )
        assert "ACCESSOR_DIES: YES" in after, (
            "a capture taken AFTER the world did not pick up the denial, so ordering is "
            "not the mechanism this class says it is: " + after
        )
        assert "import pathlib" in self.PATHLIB_FIRST, (
            "PATHLIB_FIRST no longer imports pathlib ahead of the world, so on <=3.10 the "
            "accessor would capture the already-denied function, the cure would look "
            "unnecessary, and the row would lie in the direction of a passing test"
        )

    @pytest.mark.parametrize(
        ("host", "absolute_verdict"),
        [("posix", "ACCESSOR_DIES: NO"), ("nt", "ACCESSOR_DIES: YES")],
    )
    def test_the_absolute_probe_only_discriminates_on_one_platform(self, host, absolute_verdict):
        """Trap (c) and the round-7 red, as one two-row table over the REAL function.

        This is the only test here that deliberately captures the live
        ``os.path.realpath``, because it is the only one making a claim ABOUT it.
        Both rows are emulated; neither inherits the host.

        posix: a RELATIVE path convicts with the accessor untouched, an ABSOLUTE
        one does not — which is why every other probe uses an absolute path.

        nt: BOTH convict. ``ntpath.realpath`` reads the cwd unconditionally, so
        the absolute probe stops discriminating and a raise-shaped answer no
        longer means the patch landed. That row is the round-7 CI red, kept as a
        positive measurement instead of a fixed-and-forgotten symptom — it is the
        whole reason the other probes capture a sentinel, and if it ever goes
        green the sentinel has stopped being necessary and somebody should find
        out why before deleting it.
        """
        live_capture = self.SHAPE.replace("staticmethod(_source_realpath)", "staticmethod(os.path.realpath)")
        assert live_capture != self.SHAPE

        relative = self.PROBE.replace("_accessor.realpath(ABSOLUTE)", '_accessor.realpath("./somewhere")')

        relative_out = self._run(self.HOSTS[host] + live_capture + self.BARE_MODULE_PATCH_ONLY + relative)
        absolute_out = self._run(self.HOSTS[host] + live_capture + self.BARE_MODULE_PATCH_ONLY + self.PROBE)

        assert "ACCESSOR_DIES: YES" in relative_out, (
            f"under the {host} host a relative path did not convict a live capture — then "
            "the absolute probe is not distinguishing what this class claims it does: " + relative_out
        )
        assert absolute_verdict in absolute_out, (
            f"the {host} row moved: an absolute path against a LIVE captured realpath was "
            f"expected to report {absolute_verdict!r}. On posix a change here means "
            "posixpath started reading the cwd for absolute paths; on nt it means "
            "ntpath.realpath stopped, and the sentinel below may no longer be needed: " + absolute_out
        )


class TestTheCallerIsNoneBranchSurvivesADeniedRealpath:
    """The behavioural sibling of the AST ban, and the correction that produced it.

    The round-4 guidance said the deleted second ``inspect.stack()`` walk is
    unreachable and only an AST ban can watch it. That was TOO STRONG, and
    @spawn measured the correction (relayed by @devpulse 2026-08-31): the branch
    is unreachable from IMPORT-shaped pins — ``apps/__init__.py`` always supplies
    a real-file frame, the nine-branch reproduction stands — but it IS reachable
    by calling ``_guard_branch_access()`` DIRECTLY from a ``python -c`` child.
    Every frame there is a string pseudo-file or importlib, both skipped, so
    ``_find_real_caller`` returns None and the branch RUNS. Under a realpath
    denial a regrown walk dies in it; the cured plain ``return`` survives.

    Kept ALONGSIDE the AST ban rather than replacing it. The ban needs no
    subprocess, names the offending line, and catches a reintroduction anywhere
    in the tree; this one proves the cure in the world it was built for. A mutant
    that regrows the walk kills both.

    TWO ARMING PROBES, because one is not enough here (@spawn's rules 2 and 4):
    probe 1 proves the denial actually bites this interpreter, and probe 2 proves
    ``_find_real_caller`` genuinely returned None — without it the child could be
    exercising the same-branch allow instead, and the test would pass while
    watching nothing.

    Runs as ``python -c``, never a script and never a heredoc (@commons,
    @hooks): a script frame is a real on-disk file, ``getsourcefile``
    early-returns, and the denial is silently inert.
    """

    BODY = """
import aipass.flow.apps.handlers as guard

# Probe 2 BEFORE the assertion: the branch under test must actually be entered.
_ns = {"g": guard, "OUT": None}
exec(compile("OUT = g._find_real_caller()", "<string>", "exec"), _ns)
print("CALLER_IS_NONE: " + ("YES" if _ns["OUT"] == (None, None) else "NO -> " + str(_ns["OUT"])))

try:
    exec(compile("g._guard_branch_access()", "<string>", "exec"), {"g": guard})
    print("GUARD: RETURNED")
except OSError as exc:
    print("GUARD DIED: " + type(exc).__name__ + ": " + exc.__class__.__name__)
except ImportError:
    print("GUARD: BLOCKED")
"""

    def test_calling_the_guard_directly_under_a_realpath_denial_returns(self):
        result = _run_world(_WORLD_B, _STACK_CONTROL, self.BODY)

        assert result.returncode == 0, result.stdout + result.stderr
        # Arming probe 1: the denial bites inspect.stack() on this interpreter.
        assert "STACK_DIES: YES" in result.stdout, (
            "world B did not arm — a regrown walk would survive it and this test would pass.\n" + result.stdout
        )
        # Arming probe 2: the branch under test is the one being exercised.
        assert "CALLER_IS_NONE: YES" in result.stdout, (
            "_find_real_caller did not return None, so the guard took a different "
            "path and this test is watching nothing.\n" + result.stdout
        )
        assert "GUARD: RETURNED" in result.stdout, result.stdout


class TestNoModuleLevelLocationCallSurvives:
    """The structural half, because behaviour cannot reach every reintroduction.

    Proven by @hooks (M7) and re-proved by @trigger, who restored the deleted
    ``inspect.stack()`` walk and watched 1058 tests stay green: the walk sat in
    ``_guard_branch_access``'s caller-is-None branch, and no import-shaped world
    ever enters it — ``apps/__init__.py`` always supplies a real-file frame, so
    ``_find_real_caller`` never returns None during an import.

    CORRECTED 2026-08-31 (@spawn, relayed by @devpulse): this docstring used to
    end "a parse of the tree is the only instrument that sees it". That was TOO
    STRONG. The branch is unreachable from IMPORT-shaped pins, which is not the
    same as unreachable — calling the guard DIRECTLY from a ``python -c`` child
    reaches it, and ``TestTheCallerIsNoneBranchSurvivesADeniedRealpath`` above is
    that pin. Both are kept: regrowing the walk kills both, and this one needs no
    subprocess and names the offending line anywhere in the tree.

    The ban is on the CALL — ``ast.Call`` whose func is ``inspect.stack`` — never
    on the string, because this file and the cured modules SPELL the defect in
    their docstrings to explain it, and a string ban would convict the
    explanation along with the thing.
    """

    BANNED_ATTRS = frozenset({"resolve", "cwd", "getcwd", "realpath", "abspath"})

    # The two functions in this tree that read the process cwd ON PURPOSE, and
    # are RIGHT to. Both answer "where did the caller stand" — a location,
    # observed — and both are reached at call time, never at import. Named here
    # so the ban above can never delete a correct answer, which is the failure
    # mode a blanket rule has and a measured one does not.
    DELIBERATE_CALLER_CWD_READS = frozenset(
        {
            ("project_scope.py", "caller_cwd"),
            ("resolve_location.py", "_get_caller_cwd"),
        }
    )

    @staticmethod
    def _apps_sources() -> list[Path]:
        import aipass.flow.apps as flow_apps

        root = Path(flow_apps.__file__).parent
        return [p for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts and ".archive" not in p.parts]

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

    @staticmethod
    def _cwd_reads_outside_the_named_two(source: Path, tree: ast.Module) -> list[str]:
        """``Path.cwd()``/``os.getcwd()`` calls in functions nobody blessed."""
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if (source.name, node.name) in TestNoModuleLevelLocationCallSurvives.DELIBERATE_CALLER_CWD_READS:
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call) or not isinstance(sub.func, ast.Attribute):
                    continue
                if sub.func.attr in ("cwd", "getcwd"):
                    offenders.append(f"{source.name}:{sub.lineno}  {node.name}() -> {ast.unparse(sub)}")
        return offenders

    def test_no_module_level_resolve_or_cwd_read_anywhere_in_apps(self):
        offenders = []
        for source in self._apps_sources():
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for lineno, text in self._module_level_location_calls(tree):
                offenders.append(f"{source.name}:{lineno}  {text}")

        assert offenders == [], (
            "module-level location calls crash the import on a Windows box with no cwd; "
            "route them through handlers/repo_root.module_file(): " + ", ".join(offenders)
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

    def test_the_only_cwd_reads_left_are_the_two_that_mean_it(self):
        """Seven ``_find_repo_root`` copies ended ``return Path.cwd()``. None may return.

        This is the QUIET half of the defect, and the half a ``try``/``except``
        would have left in place: cwd is a guess, four of those callers are
        writers, and a writer with a guessed root writes into a tree nobody
        chose.
        """
        offenders = []
        for source in self._apps_sources():
            tree = ast.parse(source.read_text(encoding="utf-8"))
            offenders.extend(self._cwd_reads_outside_the_named_two(source, tree))

        assert offenders == [], (
            "a cwd read outside the two deliberate caller-cwd functions — "
            "use handlers/repo_root.find_repo_root(): " + ", ".join(offenders)
        )

    # -- negative controls, both directions -------------------------------
    #
    # A checker that convicts nothing and a checker that convicts everything
    # look identical in a green summary. Every detector is run against source it
    # MUST flag and source it must NOT.

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
        """@hooks' M7 and @trigger's 1058-green mutant, reproduced."""
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
        """The reason this is an AST ban and not a grep."""
        tree = ast.parse('"""Walks sys._getframe rather than inspect.stack() — see the cure."""\n')
        assert self._inspect_stack_calls(tree) == [], (
            "a string ban convicts the explanation along with the defect, which is how a cure ends up undocumented"
        )

    def test_the_stack_detector_clears_an_unrelated_stack_attribute(self):
        tree = ast.parse("import numpy\nx = numpy.stack([1, 2])\n")
        assert self._inspect_stack_calls(tree) == [], "the ban is on inspect.stack, not on the word stack"

    def test_the_cwd_detector_convicts_a_fallback_in_an_unblessed_function(self):
        source = Path("close_helpers.py")
        tree = ast.parse("from pathlib import Path\ndef _find_repo_root():\n    return Path.cwd()\n")
        assert self._cwd_reads_outside_the_named_two(source, tree), (
            "the detector is blind to the exact seven-copy fallback it exists to ban"
        )

    def test_the_cwd_detector_clears_the_two_functions_that_mean_it(self):
        source = Path("project_scope.py")
        tree = ast.parse("from pathlib import Path\ndef caller_cwd():\n    return Path.cwd()\n")
        assert self._cwd_reads_outside_the_named_two(source, tree) == [], (
            "the ban deleted a correct answer — caller_cwd is ASKING where the caller stood"
        )

    def test_the_cwd_exemption_is_keyed_on_the_file_too(self):
        """The same function name in a different file is not the blessed one."""
        source = Path("close_helpers.py")
        tree = ast.parse("from pathlib import Path\ndef caller_cwd():\n    return Path.cwd()\n")
        assert self._cwd_reads_outside_the_named_two(source, tree), (
            "the exemption is name-only — any file could adopt the name and inherit the pass"
        )
