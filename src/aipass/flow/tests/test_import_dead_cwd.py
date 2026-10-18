# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Every flow module imports, and keeps logging, without a readable working directory
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests for aipass/flow/apps/__init__.py and every module beneath it importing with no readable working directory."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import aipass.flow.apps as flow_apps
from aipass.flow.tests import support_fence

# ntpath.realpath reads os.getcwd() unconditionally and Path.resolve() routes through it, so on Windows a
# module-level Path(__file__).resolve() cannot import once the cwd is gone. inspect.stack() carries the same
# defect through getmodule()'s unguarded realpath on a pseudo-file frame; POSIX raises earlier, inside a catch.
# World A emulates ntpath (realpath reads the cwd, getcwd is denied) and convicts a raw resolve().
# World B denies realpath outright: the only world that reaches getmodule and convicts inspect.stack().
# World B's frame must be <string> (-c or compile()), never <stdin>, whose linecache entry hides the call.
# Every assertion is preceded by a control proving its world is armed.

# Other branches' import-time code is preloaded in the healthy world so this file measures only flow's sites.
# Delete a line once that branch's own dead-cwd pin is green. trigger is deliberately not preloaded:
# close_plan imports it behind `except ImportError`, and an OSError there must red the fan with
# close_plan.py named, not be hidden by a wider except.
_PRELOAD = """
from aipass.prax import logger  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401
import aipass.api  # noqa: F401
"""

# Python 3.10's Path.resolve calls _NormalAccessor.realpath, a copy of os.path.realpath captured at pathlib's
# first import, so rebinding os.path.realpath later never reaches it (3.11 removed the accessor). Patching
# the accessor when it exists makes every world order-independent. Each detail un-arms the world if lost:
# staticmethod (else the accessor binds itself as the path); *a, **k (resolve passes strict); exercised
# through an INSTANCE (a class-level read never binds); probed with an ABSOLUTE path (posixpath reads the cwd
# for a relative one, convicting on the path's shape).
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

# Does this interpreter's resolve() reach the denied call for an ABSOLUTE path? With the accessor patched it
# answers YES on every supported interpreter; NO is a broken instrument, not a fact about the host.
_RESOLVE_CONTROL = """
import pathlib

try:
    pathlib.Path(pathlib.__file__).resolve()
    print("RESOLVE_DIES: NO")
except OSError:
    print("RESOLVE_DIES: YES")
"""

# Must ride a <string> frame: compile(..., "<string>") leaves nothing in linecache, the shape getmodule's
# unguarded realpath is reached for.
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


# Nothing looks into or runs out of a dropbox or an .archive; __pycache__ is skipped too. Names are compared
# below the walk's root.
_WALK_IGNORED_DIRS = frozenset({"dropbox", ".archive", "__pycache__"})


def _flow_modules(root: Path | None = None) -> list[str]:
    """Every importable module under ``aipass.flow.apps``, by walking the tree."""
    root = root or Path(flow_apps.__file__).parent
    names = set()
    for source in sorted(root.rglob("*.py")):
        if _WALK_IGNORED_DIRS.intersection(source.relative_to(root).parts):
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
        encoding="utf-8",
        timeout=300,
    )


def _flow_modules_by_import_machinery(root: Path | None = None) -> list[str]:
    """The same set, derived through importlib's finder instead of the filesystem."""
    import pkgutil

    def walk(path: Path, prefix: str) -> set[str]:
        found = set()
        for info in pkgutil.iter_modules([str(path)]):
            if info.name in _WALK_IGNORED_DIRS:
                continue
            name = f"{prefix}.{info.name}"
            found.add(name)
            if info.ispkg:
                found |= walk(path / info.name, name)
        return found

    root = root or Path(flow_apps.__file__).parent
    names = walk(root, "aipass.flow.apps") | {"aipass.flow.apps"}
    return sorted(name for name in names if ".archive" not in name)


@pytest.fixture(scope="module")
def flow_modules() -> list[str]:
    """Every flow module, with the count DERIVED rather than lower-bounded."""
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


def _tree_with_a_dropbox_and_an_archive(tmp_path: Path) -> Path:
    """An apps/ stand-in: real.py (the live control), beside a dropbox, an .archive
    and a __pycache__ each holding a package.

    The root itself sits inside a directory named dropbox: a skip reading the whole path would drop real.py.
    """
    root = tmp_path / "dropbox" / "apps"
    for package in (root, root / "dropbox", root / ".archive", root / "__pycache__"):
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
    (root / "real.py").write_text("", encoding="utf-8")
    (root / "dropbox" / "stray.py").write_text("", encoding="utf-8")
    (root / ".archive" / "old.py").write_text("", encoding="utf-8")
    (root / "__pycache__" / "cached.py").write_text("", encoding="utf-8")
    return root


class TestTheWalksNeverEnterADropbox:
    """Every walk in this file skips dropbox/, .archive/ and __pycache__/."""

    def test_the_filesystem_walk_skips_a_dropbox(self, tmp_path):
        assert _flow_modules(_tree_with_a_dropbox_and_an_archive(tmp_path)) == [
            "aipass.flow.apps",
            "aipass.flow.apps.real",
        ]

    def test_the_finder_walk_skips_a_dropbox(self, tmp_path):
        """dropbox/ and __pycache__/ are proved here; .archive/ is not.

        pkgutil skips a dotted directory by itself, so the filesystem walk's pin proves the .archive half.
        """
        assert _flow_modules_by_import_machinery(_tree_with_a_dropbox_and_an_archive(tmp_path)) == [
            "aipass.flow.apps",
            "aipass.flow.apps.real",
        ]

    def test_the_source_sweep_skips_a_dropbox(self, tmp_path):
        root = _tree_with_a_dropbox_and_an_archive(tmp_path)

        swept = TestNoModuleLevelLocationCallSurvives._apps_sources(root)

        assert [p.relative_to(root).as_posix() for p in swept] == ["__init__.py", "real.py"]


class TestTheModuleCountIsDerivedFromTwoMechanisms:
    """The short-table cure's own control, added because a mutant walked past it."""

    def test_the_two_derivations_are_different_code_paths(self):
        """Asserted structurally, because behaviour cannot tell a copy from a check."""
        import ast
        import inspect

        # Docstring stripped first: it names rglob to warn against it.
        tree = ast.parse(inspect.getsource(_flow_modules_by_import_machinery).strip())
        function = tree.body[0]
        assert isinstance(function, ast.FunctionDef), (
            "the second derivation is no longer a plain function definition, so the source "
            f"read below is not its body: {type(function).__name__}"
        )
        body = function.body
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
        # Of every discovery mechanism the file knows, the second derivation calls exactly pkgutil's.
        mechanisms = {"pkgutil.iter_modules", "pkgutil.walk_packages", "_flow_modules", "rglob", "glob", "os.walk"}
        called = set()
        for statement in body:
            for node in ast.walk(statement):
                if isinstance(node, ast.Call):
                    name = ast.unparse(node.func)
                    # root.rglob / path.glob: the receiver varies, the mechanism does not.
                    called.add(name.rsplit(".", 1)[-1] if name.endswith("glob") else name)
        assert called & mechanisms == {"pkgutil.iter_modules"}, (
            f"the second derivation's discovery calls are {sorted(called & mechanisms)}, not pkgutil's finder alone"
        )

    def test_the_fixture_compares_one_against_the_other(self):
        """And that the fixture actually uses both, rather than one twice."""
        import inspect

        # getattr: pytest's fixture type does not declare __wrapped__. Asserted first to fail with a sentence.
        undecorated = getattr(flow_modules, "__wrapped__", None)
        assert undecorated is not None, (
            "the flow_modules fixture no longer carries __wrapped__, so the source read "
            "below would be the decorator's rather than the fixture's own"
        )
        fixture_source = inspect.getsource(undecorated)

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
    """``log_operation`` is reached at runtime, so no import probe covers it."""

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
        # It must still ANSWER: one name for every caller would pass the lines above and destroy the audit trail.
        assert "router_probe_log.json" in result.stdout, (
            "the caller name stopped being read from the frame: " + result.stdout
        )
        # "unknown" by design: attributing work to <string> asserts something false about who did it.
        assert "unknown_log.json" in result.stdout, "a pseudo-frame is no longer answered 'unknown': " + result.stdout


def expected_route_without_cure(has_accessor: bool) -> str:
    """What removing ``_ACCESSOR_CURE`` must do to the real ``Path.resolve`` route.

    Returns "ROUTE_INERT" where the cure is load-bearing (an accessor exists), else "ROUTE_ARMED".
    """
    return "ROUTE_INERT" if has_accessor else "ROUTE_ARMED"


class TestTheRouteExpectationIsReachableOnAnyHost:
    """Both rows of the judgement above, on whichever interpreter runs this."""

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

    An instrument must not import behaviour it is not testing: ntpath.realpath reads the cwd even for an
    absolute path, so a captured live function raises on its own. Emulate both platforms or neither, build each
    from its dialect module BY NAME (os.path IS the host), capture a SENTINEL, and require no verdict to move.
    Vacuously green without: staticmethod, an instance read, an absolute probe path, an eager capture.
    """

    # The two hosts, built from the dialect modules BY NAME: os.path is the host itself.
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

    HOSTS = {"posix": POSIX_HOST, "nt": NT_HOST}

    # The RUNNER (the platform this process executes on), faked only in what a probe reads to build a path.
    # It is NOT a world and must never be used as one.
    WINDOWS_RUNNER = r"""
import ntpath
import os
import pathlib

os.path = ntpath
os.sep = "\\"
pathlib.__file__ = r"D:\a\AIPass\AIPass\.venv\Lib\pathlib.py"
"""

    # A Windows-shaped fake cannot arm on a Windows runner (host == fake), so the runner varies toward BOTH
    # shapes: on any host at least one differs from it.
    POSIX_RUNNER = """
import os
import pathlib
import posixpath

os.path = posixpath
os.sep = "/"
pathlib.__file__ = "/usr/lib/python3/pathlib.py"
"""

    RUNNERS = {"posix": POSIX_RUNNER, "windows": WINDOWS_RUNNER}

    # Installs no host, so ABSOLUTE is built in this interpreter's own dialect.
    NO_HOST = """
import os

ABSOLUTE = os.path.join(os.sep, "definitely", "not", "here")
"""

    # The 3.10 construction (Lib/pathlib.py:358), captured EAGERLY at class creation, holding a SENTINEL, not
    # os.path.realpath: the sentinel touches nothing, so any later raise is the patch's doing on any platform.
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

    # Called through the instance with an absolute path, as 3.10's Path.resolve reaches it.
    PROBE = """
try:
    _accessor.realpath(ABSOLUTE)
    print("ACCESSOR_DIES: NO")
except OSError:
    print("ACCESSOR_DIES: YES")
"""

    # Published on pathlib under 3.10's name so _WORLD_A runs VERBATIM against it.
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

    # The shipped cure against the emulated accessor, because 3.11+ has none to patch.
    EMULATED_CURE = """
_Accessor.realpath = staticmethod(_denied_realpath)
"""

    # A bare string: no filesystem, cwd or dialect should be able to answer eagerness.
    EAGERNESS_PROBE = """
print("EAGERNESS:", _accessor.realpath("probe"))
"""

    # pathlib imported FIRST so a 3.10 accessor captures before the world, as in every real import fan.
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
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, encoding="utf-8", timeout=120
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    @staticmethod
    def _run_or_reason(script: str) -> tuple[str, str | None]:
        """Run a child, returning ``(stdout, None)`` or ``(stdout, reason)``.

        A host this was not written on may refuse a runner fake: that row is UNAVAILABLE, not a flow defect.
        """
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, encoding="utf-8", timeout=120
        )
        if result.returncode != 0:
            return result.stdout, (result.stderr.strip().splitlines() or ["no diagnostic"])[-1]
        return result.stdout, None

    def _runner_verdicts(self, body: str, runners: dict[str, str]) -> dict[str, str]:
        """Every verdict for *body*, once bare and once under each runner fake.

        Raises AssertionError on a row that could not be measured: a row that cannot speak did not agree.
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
        """The probe path a host publishes, read out of the constant itself."""
        line = next(entry for entry in host.splitlines() if entry.startswith("ABSOLUTE = "))
        return ast.literal_eval(line.split("=", 1)[1].strip())

    @staticmethod
    def _world_without_cure() -> str:
        """``_WORLD_A`` with the shipped cure sliced out, read off the constants."""
        world = _WORLD_A.replace(_ACCESSOR_CURE, "")
        assert world != _WORLD_A, "the cure is not a substring of the world — this slice is not slicing anything"
        return world

    @pytest.mark.parametrize("host", sorted(HOSTS))
    def test_a_bare_module_attribute_patch_does_not_reach_a_captured_accessor(self, host):
        """CI's Python 3.10 failure, reproduced on this machine — under BOTH hosts."""
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

        A lazy capture follows the patched attribute and the arming pin passes without _ACCESSOR_CURE, so
        the shipped world minus its cure must leave this shape alive.
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

    @pytest.mark.parametrize("host", sorted(HOSTS))
    def test_the_shipped_world_arms_through_a_pre_captured_accessor(self, host):
        """The cure, exercised as ``_WORLD_A`` VERBATIM against a 3.10-shaped accessor."""
        out = self._run(self.HOSTS[host] + self.PUBLISHED_SHAPE + _WORLD_A + self.PROBE)

        assert "ACCESSOR_DIES: YES" in out, (
            f"under the {host} host the ntpath world did not arm — the shipped world's "
            "denial did not reach a pre-captured accessor, which is exactly the Python "
            "3.10 failure on 8550ed10: " + out
        )

    @pytest.mark.parametrize("host", sorted(HOSTS))
    def test_patching_the_accessor_arms_the_same_world(self, host):
        """The same direction through the local emulation, without pathlib in it.

        Isolates the cure from the hasattr lookup on pathlib._NormalAccessor.
        """
        out = self._run(self.HOSTS[host] + self.SHAPE + self.BARE_MODULE_PATCH_ONLY + self.EMULATED_CURE + self.PROBE)

        assert "ACCESSOR_DIES: YES" in out, (
            f"under the {host} host the accessor patch did not arm the world it exists to arm: " + out
        )

    def test_no_accessor_verdict_moves_between_the_two_hosts(self):
        """@memory's litmus, run over every direction at once."""
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

        Probes must not read the RUNNER (os.sep, pathlib.__file__) to build input. The runner varies toward
        BOTH shapes, because a fake equal to the host compares equal for free.
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

        Unreachable from any real composition here, so a synthetic broken runner is fed in: a skipped row
        would be indistinguishable from one that agreed.
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

        Each fake reports CHANGED, ALREADY (the host already has this shape, reason printed) or UNAVAILABLE
        (could not install, with the child's diagnostic). At least one must be CHANGED on every host.
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
        # The OTHER platform's fake must change what a probe reads; the host's own may be ALREADY.
        foreign = "posix" if sys.platform == "win32" else "windows"
        assert verdicts[foreign] == "CHANGED", (
            f"the {foreign} fake is the foreign one on this host and changed nothing: {verdicts}"
        )

    @pytest.mark.parametrize("simulated_host", ["posix", "windows"])
    def test_the_runner_set_arms_on_either_kind_of_host(self, simulated_host):
        """Round 9's species, made falsifiable on the one machine available.

        Both KINDS of host are simulated (host first, fake stacked on top); some fake must differ from each.
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

        Checked read by read under the OPPOSITE host: a fake missing one read still passes the coarser pins.
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
        """@seedgo's SHORT-TABLE nomination, ruled on rather than inherited."""
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

        # Recounted from the class body, not HOSTS: a host defined and never registered leaves every
        # parametrisation a row short. A host is NAMED *_HOST and imports a dialect; NO_HOST imports none.
        defined = {
            name: value
            for name, value in vars(type(self)).items()
            if name.endswith("_HOST")
            and isinstance(value, str)
            and any(f"import {module}" in value for module in ("posixpath", "ntpath"))
        }
        assert len(self.HOSTS) == len(defined), (
            "a dialect host is defined in this class body and never registered in HOSTS, so "
            "every parametrisation over sorted(HOSTS) runs a row short and stays green: "
            f"defined {sorted(defined)} vs registered {sorted(self.HOSTS)}"
        )
        assert set(self.HOSTS.values()) == set(defined.values()), (
            "HOSTS registers a world that is not one of this class's dialect host constants, "
            f"so a parametrised row is emulating something unnamed: {sorted(self.HOSTS)} vs "
            f"{sorted(defined)}"
        )

    def test_the_two_hosts_are_genuinely_different_worlds(self):
        """Control for the litmus: two identical hosts would pass it for free.

        ntpath.realpath reads the cwd for an ABSOLUTE path and posixpath does not, measured through the emulations.
        """
        # ABSOLUTE comes from the host prefix in its own dialect; one built from os.sep is relative to posixpath.
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

    def test_the_cure_matches_the_accessor_this_interpreter_has(self):
        """Both interpreters, one probe, no assertion about the host taken on faith.

        The shipped world must ARM the real Path.resolve route; removing the cure must go INERT with an accessor
        (<=3.10) and change nothing without. pathlib is imported FIRST so a 3.10 accessor captures first.
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
        """The emulation must not drift from the constant that actually ships."""
        assert "staticmethod(_denied_realpath)" in _ACCESSOR_CURE, (
            "the shipped cure no longer assigns a staticmethod — a plain function "
            "arrives bound and resolves the accessor object instead of the path"
        )
        assert "_NormalAccessor" in _ACCESSOR_CURE
        assert "hasattr" in _ACCESSOR_CURE, (
            "the shipped cure is no longer guarded — it must be a no-op on 3.11+, which removed the accessor"
        )
        assert "staticmethod(_denied_realpath)" in self.EMULATED_CURE

    def test_the_capture_is_a_sentinel_and_not_the_live_function(self):
        """The round-7 cure, pinned in the source rather than only in behaviour.

        Restoring staticmethod(os.path.realpath) passes every behavioural pin on Linux and reds on Windows.
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

        A sentinel is stale-proof, so a lazy wrapper around it answers like an eager capture. The source name
        is rebound AFTER the class body: an eager capture answers CAPTURED, a lazy one MOVED.
        """
        shape = getattr(self, shape_name)
        out = self._run(shape + self.EAGERNESS_PROBE)

        assert "EAGERNESS: CAPTURED" in out, (
            f"{shape_name} did not keep the value bound at class creation — it is following "
            "the source name, so it captures LAZILY and stops emulating 3.10, where the "
            "accessor holds a copy taken at pathlib's first import: " + out
        )

    def test_the_eagerness_probe_can_report_the_other_answer(self):
        """Control: a probe that can only print CAPTURED proves nothing."""
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
        """@seedgo's M9, pinned as a control on the emulation itself."""
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

        An instrument's INPUTS are behaviour too: a path built from the host's os.sep is RELATIVE to posixpath
        on Windows. Asymmetric: posixpath refuses an nt literal, while ntpath takes a posix one as
        DRIVE-RELATIVE, so an nt probe path must carry a drive.
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

        # The negative half: reds if anyone reintroduces a host-built path.
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

        Stated here because _literal_from's "malformed node" names no species; every host-derived spelling
        is a Call, a Name or an Attribute.
        """
        line = next(entry for entry in self.HOSTS[host].splitlines() if entry.startswith("ABSOLUTE = "))
        statement = ast.parse(line).body[0]
        assert isinstance(statement, ast.Assign), (
            f"the {host} host's ABSOLUTE line is no longer a plain assignment: {line!r}"
        )
        node = statement.value

        assert isinstance(node, ast.Constant) and isinstance(node.value, str), (
            f"the {host} host COMPUTES its probe path rather than publishing one: "
            f"{ast.unparse(node)}. Anything read off the running host — os.sep, "
            "sys.executable, __file__, os.getcwd() — carries the RUNNER's dialect into "
            "an emulation that is not the runner, which is exactly the round-8 defect; "
            "a plain literal cannot"
        )

    def test_the_real_route_probe_deliberately_uses_the_host_dialect(self):
        """The one exception, pinned so it is not "fixed" into a bug."""
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
        """@memory's rule 2, pinned in the source because behaviour cannot pin it here."""
        assert "_posixpath_realpath = posixpath.realpath" in self.POSIX_HOST, (
            "the posix emulation no longer captures posixpath BY NAME. On nt os.path IS "
            "ntpath, so this row would emulate the runner and report it as posix"
        )
        assert "ntpath." in self.NT_HOST, "the nt emulation no longer references ntpath by name"
        for name, host in (("POSIX_HOST", self.POSIX_HOST), ("NT_HOST", self.NT_HOST)):
            # Comments stripped first: both constants explain the os.path trap in prose.
            capture = "\n".join(
                line for line in host.split("def ")[0].splitlines() if not line.lstrip().startswith("#")
            )
            assert "os.path.realpath" not in capture, (
                f"{name} reads os.path before installing its own function — os.path IS the "
                "host, so the emulation would inherit exactly what it exists to replace"
            )

    def test_the_capture_ordering_is_what_makes_the_cure_load_bearing(self):
        """Why ``PATHLIB_FIRST`` exists, measured rather than asserted.

        Capture before the world and a bare module patch cannot reach it; capture after and it arms with no
        cure. Measured against an emulated capture, because order only matters on 3.10.
        """
        world = self._world_without_cure()
        # The LIVE capture on purpose: a sentinel is stale-proof and reports NO either way. POSIX_HOST so the
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

        The only test capturing the live os.path.realpath, because it is the only one making a claim about it.
        posix: only a RELATIVE path convicts. nt: both do, since ntpath.realpath reads the cwd unconditionally;
        that row is why the other probes capture a sentinel.
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


class TestTheFenceLetsKinThroughWithNoCwd:
    """The fence's kin walk under a dead cwd, through its public shape.

    Runs tests/support_fence.py from its kin seat in world A, as a -c child via runpy. The dead cwd is
    emulated, not a removed directory: Windows refuses to remove a process's own working directory.
    """

    BODY = f"""
import runpy

sys.argv = [{str(Path(support_fence.__file__))!r}, "pkg"]
runpy.run_path(sys.argv[0], run_name="__main__")
"""

    def test_the_fence_lets_kin_through_with_no_cwd(self):
        """The kin seat imports its handlers under world A's dead cwd: ALLOWED.

        Red against a frame walk that resolves a path without an OSError arm.
        """
        result = _run_world(_WORLD_A, _RESOLVE_CONTROL, "\nimport sys\n" + self.BODY)
        out = result.stdout

        assert "RESOLVE_DIES: YES" in out, f"world A did not arm - this pin proves nothing:\n{out}"
        assert out.strip().splitlines()[-1] == "ALLOWED", (
            f"the fence refused or died on its own kin under a dead cwd:\nstdout={out}\nstderr={result.stderr}"
        )


class TestNoModuleLevelLocationCallSurvives:
    """The structural half, because behaviour cannot reach every reintroduction.

    An inspect.stack() walk in a branch no import enters stays green behaviourally. The ban is on the CALL
    (ast.Call of inspect.stack), never the string, because docstrings spell the defect to explain it.
    """

    BANNED_ATTRS = frozenset({"resolve", "cwd", "getcwd", "realpath", "abspath"})

    # The two functions that read the caller's cwd ON PURPOSE, at call time, never at import.
    DELIBERATE_CALLER_CWD_READS = frozenset(
        {
            ("project_scope.py", "caller_cwd"),
            ("resolve_location.py", "_get_caller_cwd"),
        }
    )

    @staticmethod
    def _apps_sources(root: Path | None = None) -> list[Path]:
        """Every .py under apps/ (or ``root``, which the dropbox pin passes), ignored dirs skipped."""
        root = root or Path(flow_apps.__file__).parent
        return [p for p in sorted(root.rglob("*.py")) if not _WALK_IGNORED_DIRS.intersection(p.relative_to(root).parts)]

    @staticmethod
    def _catches_oserror(node: ast.Try) -> bool:
        """Whether one of the try's handlers names OSError, alone or in a tuple."""
        for handler in node.handlers:
            kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
            if any(isinstance(kind, ast.Name) and kind.id == "OSError" for kind in kinds):
                return True
        return False

    @staticmethod
    def _module_level_location_calls(tree: ast.Module) -> list[tuple[int, str]]:
        """Calls that infer a location and are evaluated when the module loads.

        A call in a module-level try that catches OSError is exempt: the import survives (the fence v2 shape).
        """
        found = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            parts = [node]
            if isinstance(node, ast.Try) and TestNoModuleLevelLocationCallSurvives._catches_oserror(node):
                parts = [*node.handlers, *node.orelse, *node.finalbody]
            for part in parts:
                for sub in ast.walk(part):
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


        cwd is a guess, and a writer with a guessed root writes into a tree nobody chose.
        """
        offenders = []
        for source in self._apps_sources():
            tree = ast.parse(source.read_text(encoding="utf-8"))
            offenders.extend(self._cwd_reads_outside_the_named_two(source, tree))

        assert offenders == [], (
            "a cwd read outside the two deliberate caller-cwd functions — "
            "use handlers/repo_root.find_repo_root(): " + ", ".join(offenders)
        )

    # Negative controls: every detector runs against source it MUST flag and source it must NOT.

    def test_the_module_level_detector_convicts_a_module_level_resolve(self):
        tree = ast.parse("from pathlib import Path\nROOT = Path(__file__).resolve().parents[3]\n")
        assert self._module_level_location_calls(tree), "the detector is blind to the exact line it exists to ban"

    def test_the_module_level_detector_clears_the_same_call_inside_a_function(self):
        tree = ast.parse("from pathlib import Path\ndef f():\n    return Path(__file__).resolve()\n")
        assert self._module_level_location_calls(tree) == [], (
            "a resolve() inside a function is reached at CALL time, not import time — "
            "convicting it would ban the guarded helper this cure is built on"
        )

    def test_the_module_level_detector_clears_a_resolve_guarded_by_oserror(self):
        """The fence v2 shape: the dead cwd raises OSError inside the try and the import lives."""
        tree = ast.parse(
            "from pathlib import Path\n"
            "try:\n"
            "    F = str(Path(__file__).resolve())\n"
            "except OSError:\n"
            "    F = str(__file__)\n"
        )
        assert self._module_level_location_calls(tree) == [], "the detector convicts a resolve the import survives"

    def test_the_module_level_detector_convicts_a_resolve_guarded_by_another_error(self):
        """A try that does not catch OSError lets the dead cwd's raise kill the import."""
        tree = ast.parse(
            "from pathlib import Path\n"
            "try:\n"
            "    F = str(Path(__file__).resolve())\n"
            "except ValueError:\n"
            "    F = str(__file__)\n"
        )
        assert self._module_level_location_calls(tree), "the OSError exemption swallowed every try"

    def test_the_module_level_detector_convicts_a_resolve_in_the_oserror_arm(self):
        """The handler arm itself runs at import time and is not guarded by its own try."""
        tree = ast.parse(
            "from pathlib import Path\n"
            "try:\n"
            "    F = str(__file__)\n"
            "except OSError:\n"
            "    F = str(Path(__file__).resolve())\n"
        )
        assert self._module_level_location_calls(tree), "the exemption reached past the try body"

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
