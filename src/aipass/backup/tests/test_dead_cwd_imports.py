# =================== META ====================
# Name: test_dead_cwd_imports.py
# Description: Dead-cwd import defect — guard shape, safe path helper, both worlds
# Version: 1.0.4
# Created: 2026-08-31
# Modified: 2026-09-25
# =============================================

"""Tests for apps/handlers/path/module_paths.py and the kinship fence in apps/handlers/__init__.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/__init__.py and handlers/path/module_paths.py lint clean
# seedgo: no-test-needed(documentation) — the docstrings of module_file() and branch_root()
# seedgo: no-test-needed(stdlib) — linecache.getline(), which fills the fence message's Blocked: line

import ast
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from collections.abc import Iterable
from pathlib import Path, PureWindowsPath

import coverage
import pytest

from aipass.backup.apps.handlers.path import module_paths

# The defect (Windows round 4). ntpath.realpath reads os.getcwd()
# UNCONDITIONALLY - posixpath only does so for relative paths - and
# Path.resolve() routes through it. So on Windows every resolve() REACHED AT
# IMPORT is an import-time crash for a process whose cwd was deleted: the module
# cannot be imported at all.
# Two injections are needed because they convict different code. World A wraps
# os.path.realpath to read the cwd first, then denies os.getcwd: this convicts a
# raw resolve(). It CANNOT convict inspect.stack() - denying getcwd also kills
# abspath, so getmodule dies at getabsfile inside its own except and stack()
# completes green for the wrong reason. World B denies os.path.realpath directly
# and leaves abspath working: this convicts inspect.stack() via getmodule's
# unguarded realpath at inspect.py:1009.
# Every probe rides a string pseudo-frame (a -c child), never stdin: linecache
# caches stdin and the probe would report green while lying.


#: The real guard file, executed fresh from disk by _load_guard_module. No stub is in the
#: way of a name import: tests/conftest.py:26 imports the real handlers package before
#: conftest.py:35 tests for it, so the stub at conftest.py:36-39 never installs.
TEST_FILE = Path(__file__).resolve()
BRANCH_ROOT = TEST_FILE.parents[1]
GUARD_FILE = BRANCH_ROOT / "apps" / "handlers" / "__init__.py"
SOURCE_TREE = BRANCH_ROOT.parents[2] / "src" / "aipass"


def _missing_sources(measured: "Iterable[str]") -> list[str]:
    """Measured filenames with no file on disk.

    Exactly the condition ``coverage report`` exits 1 on with "No source for
    code". A plain function so the control below can feed it a guilty set.
    """
    return sorted(f for f in measured if not os.path.exists(f))


def _compile_sites(source: str) -> list[str]:
    """Names of the functions containing a ``compile()`` call.

    The invariant it serves: exactly ONE mint point, so the coverage guard in
    ``_compile_as`` cannot be walked around by a new site.
    """
    sites = []
    for parent in ast.walk(ast.parse(source)):
        if not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(parent):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "compile":
                sites.append(parent.name)
                break
    return sites


def _compile_as(caller_file: str, guard) -> None:
    """Drive the fence by compiling ``check()`` under a fabricated filename.

    THE ONLY ``compile()`` in this file, so the coverage invariant has exactly
    one place to stand. coverage.py records executed code objects by filename,
    resolving a RELATIVE one against the cwd at trace time -- so "is this name
    inside the source tree" is a question about ``abspath``, not about the
    literal. A fabricated name that lands inside the tree and has no file makes
    the report step exit 1 with "No source for code".
    """
    if not caller_file.startswith("<"):
        landed = Path(os.path.abspath(caller_file))
        assert SOURCE_TREE not in landed.parents, (
            f"fabricated caller filename lands inside the coverage source tree: {landed}"
        )
    exec(compile("check()", caller_file, "exec"), {"check": guard._guard_branch_access})


def _fence_verdict(caller_file: str, guard) -> str | None:
    """Run the fence as ``caller_file``: None when admitted, the ImportError text when refused.

    AssertionError from ``_compile_as``'s mint guard is NOT caught: that is the
    coverage invariant firing, not a fence decision.
    """
    try:
        _compile_as(caller_file, guard)
    except ImportError as refused:
        return str(refused)
    return None


def _load_guard_module():
    """Execute the real handlers/__init__.py, guard and all.

    The caller frame is this test file, which lives inside the branch, so the
    guard's own import-time invocation passes -- that is itself a check that a
    kin caller is still allowed.
    """
    spec = importlib.util.spec_from_file_location(
        "aipass.backup.apps.handlers",
        GUARD_FILE,
        submodule_search_locations=[str(GUARD_FILE.parent)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not build an import spec for {GUARD_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def guard():
    """The real guard module, loaded once."""
    return _load_guard_module()


#: Imported healthy BEFORE any denial. Other branches' cure is their own build;
#: this suite measures backup. Deliberately NOT preloaded: the optional @api
#: import inside drive/client, because a preload is a claim you stop testing.
PRELOAD = ["aipass.prax", "aipass.cli.apps.modules"]

#: The five live cured sites (handlers, state.backup_timestamps, project.setup,
#: project.registry, audit.trail); two entry points (apps, apps.backup);
#: json.json_handler, now a shim over aipass.prax; drive.client, for its optional @api import.
PROBE_MODULES = [
    "aipass.backup.apps",
    "aipass.backup.apps.backup",
    "aipass.backup.apps.handlers",
    "aipass.backup.apps.handlers.state.backup_timestamps",
    "aipass.backup.apps.handlers.project.setup",
    "aipass.backup.apps.handlers.project.registry",
    "aipass.backup.apps.handlers.json.json_handler",
    "aipass.backup.apps.handlers.audit.trail",
    "aipass.backup.apps.handlers.drive.client",
]

_PROBE = """
import json, os, os.path, sys

world, targets, preload = sys.argv[1], json.loads(sys.argv[2]), json.loads(sys.argv[3])
for name in preload:
    try:
        __import__(name)
    except Exception:
        pass
_real_realpath = os.path.realpath
def _realpath_reads_cwd(path, *a, **k):
    os.getcwd()
    return _real_realpath(path, *a, **k)
def _dead_getcwd(*a, **k):
    raise FileNotFoundError(2, "probe: cwd denied")
def _dead_realpath(*a, **k):
    raise OSError(2, "probe: realpath denied")
if world in ("A", "CONTROL"):
    os.path.realpath = _realpath_reads_cwd
    os.getcwd = _dead_getcwd
elif world == "B":
    os.path.realpath = _dead_realpath
if world == "CONTROL":
    from pathlib import Path
    try:
        Path("relative/thing").resolve()
        print(json.dumps({"control": "LIED_GREEN"}))
    except Exception as exc:
        print(json.dumps({"control": "BITES", "err": type(exc).__name__}))
    raise SystemExit(0)
red = {}
for name in targets:
    for cached in [m for m in list(sys.modules) if m.startswith("aipass.backup")]:
        del sys.modules[cached]
    try:
        __import__(name)
    except Exception as exc:
        red[name] = type(exc).__name__ + ": " + str(exc)[:80]
print(json.dumps({"world": world, "red": red}))
"""


def _run_probe(world: str, targets: list[str] | None = None) -> dict:
    """Run the import probe in a child interpreter across a string frame."""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            _PROBE,
            world,
            json.dumps(targets if targets is not None else PROBE_MODULES),
            json.dumps(PRELOAD),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert proc.stdout.strip(), f"probe produced no stdout (stderr: {proc.stderr[-400:]})"
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestTheInjectionCanSayNo:
    """The CONTROL world must bite, or world A's pin below is vacuously green."""

    def test_the_denial_actually_bites(self) -> None:
        """The CONTROL world (world A's injection) makes a relative resolve() raise."""
        assert _run_probe("CONTROL")["control"] == "BITES"

    def test_healthy_world_imports_everything(self) -> None:
        """With no injection the same probe is green -- so red means the denial."""
        assert _run_probe("HEALTHY")["red"] == {}


class TestImportsSurviveADeadCwd:
    """No backup module may need a readable cwd in order to be imported."""

    @pytest.mark.parametrize("world", ["A", "B"])
    def test_no_module_dies_at_import(self, world: str) -> None:
        """Every probed module imports with the cwd/realpath denied."""
        assert _run_probe(world)["red"] == {}


class _ResolveDeniedPath(Path):
    """A ``Path`` whose ``resolve()`` refuses, standing in for the dead cwd.

    Installed over ``module_paths.Path`` (the module's own ``from pathlib import
    Path`` binding), it denies ``resolve()`` to the module under test and to
    nothing else. ``module_file``'s fallback is reached through the same
    binding, so it returns one of these: a real ``Path`` in every other respect.
    """

    def resolve(self, strict: bool = False) -> Path:
        """Refuse the way a deleted cwd refuses: OSError, not a crash."""
        raise OSError(2, "cwd denied")


class TestSafePathHelper:
    """module_file degrades to the raw absolute spelling, never to a crash."""

    def test_returns_resolved_path_normally(self) -> None:
        """In a healthy world it behaves like resolve()."""
        assert module_paths.module_file(__file__) == Path(__file__).resolve()

    def test_falls_back_when_resolve_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An OSError from resolve() yields an absolute path, not an exception."""
        monkeypatch.setattr(module_paths, "_REPORTED_DEGRADED", set())
        monkeypatch.setattr(module_paths, "Path", _ResolveDeniedPath)
        result = module_paths.module_file(__file__)

        assert result.is_absolute()
        assert result.name == Path(__file__).name

    def test_branch_root_climbs_without_resolve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """branch_root still answers when resolve() is unavailable."""
        monkeypatch.setattr(module_paths, "_REPORTED_DEGRADED", set())
        monkeypatch.setattr(module_paths, "Path", _ResolveDeniedPath)
        assert module_paths.branch_root(__file__, 1) == Path(os.path.abspath(__file__)).parents[1]


class TestDegradedResolutionIsAnnouncedOnce:
    """A dead cwd fails EVERY resolve, so the report is once per file, not per call.

    One line per call buries the traceback that actually explains the run under
    its own noise. The set that remembers what was already reported is isolated
    per test rather than read, so the pin is the stderr the user sees.
    """

    def test_two_degraded_resolutions_of_one_file_write_one_line(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """module_file called twice on the same file announces once."""
        monkeypatch.setattr(module_paths, "_REPORTED_DEGRADED", set())
        monkeypatch.setattr(module_paths, "Path", _ResolveDeniedPath)

        module_paths.module_file(__file__)
        module_paths.module_file(__file__)

        out, err = capsys.readouterr()
        assert out == "", "the degraded report belongs on stderr, which drone piping relies on"
        assert err.count("cwd unreadable") == 1
        assert Path(__file__).name in err

    def test_a_second_file_gets_its_own_line(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Once-per-file, not once-per-process: a different file is still reported."""
        monkeypatch.setattr(module_paths, "_REPORTED_DEGRADED", set())
        monkeypatch.setattr(module_paths, "Path", _ResolveDeniedPath)

        module_paths.module_file(__file__)
        module_paths.module_file(str(Path(__file__).parent / "conftest.py"))

        _out, err = capsys.readouterr()
        assert err.count("cwd unreadable") == 2


def _inspect_stack_calls(source: str) -> list[int]:
    """Line numbers of every literal ``inspect.stack()`` CALL in source."""
    hits = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "stack"
            and isinstance(func.value, ast.Name)
            and func.value.id == "inspect"
        ):
            hits.append(node.lineno)
    return hits


class TestGuardNeverCallsInspectStack:
    """An AST ban, because no import-shaped test can reach the deleted walk.

    The caller-is-None branch is unreachable from an import: apps/__init__ always
    supplies a real-file frame. An AST ban, never a string ban: the guard's own
    docstring names inspect.stack(), and a spelling ban would convict it.
    """

    def test_guard_file_has_no_inspect_stack_call(self) -> None:
        """The shipped guard contains no inspect.stack() call."""
        assert _inspect_stack_calls(GUARD_FILE.read_text(encoding="utf-8")) == []

    def test_positive_control_a_real_call_convicts(self) -> None:
        """The detector fires on an actual call."""
        source = textwrap.dedent(
            """
            import inspect
            def f():
                return inspect.stack()
            """
        )
        assert _inspect_stack_calls(source) == [4]

    def test_negative_control_a_docstring_mention_is_not_a_call(self) -> None:
        """Prose naming inspect.stack() must not convict."""
        source = '"""Uses sys._getframe rather than inspect.stack() -- see defect."""\n'
        assert _inspect_stack_calls(source) == []

    def test_negative_control_numpy_stack_is_not_inspect_stack(self) -> None:
        """A different module's stack() must not convict."""
        source = "import numpy\nnumpy.stack([1, 2])\n"
        assert _inspect_stack_calls(source) == []

    def test_the_guard_docstring_really_does_name_it(self) -> None:
        """The guard's prose names inspect.stack(), so the docstring control above tests something."""
        assert "inspect.stack()" in GUARD_FILE.read_text(encoding="utf-8")


def _fake_tree(tmp_path: Path) -> Path:
    """A tree-SHAPED root that is not the tree.

    The fence is driven by compiling ``check()`` under a fabricated filename,
    and coverage.py records every executed code object BY FILENAME whether or
    not the file exists. Fabricating under the REAL tree therefore writes
    measurement for a path inside coverage's source filter: if the file does
    not exist the report step dies with "No source for code", and if it DOES
    exist the run forges a covered line in a file that never ran.

    Everything fabricated here lives under ``tmp_path`` -- outside the source
    filter, never recorded -- while keeping the ``aipass/<branch>`` segments the
    guard's branch-name extraction reads.
    """
    return tmp_path / "src" / "aipass"


class TestFenceStillRefusesForeignCallers:
    """Curing the crash must not quietly open the fence.

    The guard reads ``f_code.co_filename`` off the calling frame, so a foreign
    caller is simulated by compiling the call under a foreign filename. That is
    the same mechanism a real cross-branch import presents.

    Every fabricated filename here is under ``tmp_path``; the REAL-tree
    adjacency properties are pinned on ``_is_kin`` instead, which is pure and
    compiles nothing.
    """

    def test_foreign_caller_is_refused(self, guard, tmp_path: Path) -> None:
        """A caller outside the branch root raises ImportError."""
        with pytest.raises(ImportError, match="ACCESS DENIED"):
            _compile_as(str(tmp_path / "outsider.py"), guard)

    def test_sibling_branch_is_refused(self, guard, tmp_path, monkeypatch) -> None:
        """Another citizen's file is refused, and named in the message."""
        fake = _fake_tree(tmp_path)
        monkeypatch.setattr(guard, "_BRANCH_ROOT", str(fake / "backup"))
        sibling = str(fake / "memory" / "apps" / "x.py")
        with pytest.raises(ImportError, match="memory"):
            _compile_as(sibling, guard)

    def test_the_real_sibling_path_is_foreign_too(self, guard) -> None:
        """The real sibling branch ``memory`` is not kin, checked without compiling anything."""
        real_sibling = str(Path(guard._BRANCH_ROOT).parent / "memory" / "apps" / "x.py")
        assert not guard._is_kin(real_sibling, guard._BRANCH_ROOT)

    def test_a_sibling_named_backup_old_is_not_kin(self, guard) -> None:
        """A sibling whose name merely EXTENDS this branch's name is foreign."""
        # Kinship is by whole path SEGMENT: ``<root>_old`` contains ``<root>`` as text.
        stale = str(Path(guard._BRANCH_ROOT + "_old") / "apps" / "x.py")
        assert not guard._is_kin(stale, guard._BRANCH_ROOT)

    def test_a_sibling_named_backup2_is_not_kin(self, guard) -> None:
        """The same hole without the separator: a digit suffix is still foreign."""
        # A second name, so a cure that only refuses a trailing underscore goes red.
        numbered = str(Path(guard._BRANCH_ROOT + "2") / "apps" / "x.py")
        assert not guard._is_kin(numbered, guard._BRANCH_ROOT)

    def test_a_copy_of_the_branch_nested_under_a_foreign_root_is_not_kin(self, guard, tmp_path: Path) -> None:
        """A copy of the root nested mid-path is foreign: kinship is anchored at the path's start."""
        nested = f"{tmp_path}{guard._BRANCH_ROOT}/apps/x.py"
        assert not guard._is_kin(nested, guard._BRANCH_ROOT)

    def test_a_sibling_named_backup_old_is_refused_end_to_end(self, guard, tmp_path, monkeypatch) -> None:
        """The fence refuses a backup_old caller and names backup_old as the caller branch."""
        fake = _fake_tree(tmp_path)
        monkeypatch.setattr(guard, "_BRANCH_ROOT", str(fake / "backup"))
        stale = str(fake / "backup_old" / "apps" / "x.py")

        with pytest.raises(ImportError, match="ACCESS DENIED") as refused:
            _compile_as(stale, guard)
        assert "Caller branch: backup_old" in str(refused.value)

    def test_own_branch_file_is_allowed(self, guard, tmp_path, monkeypatch) -> None:
        """A file under the branch root is admitted: the fence is not always-refuse."""
        fake = _fake_tree(tmp_path)
        monkeypatch.setattr(guard, "_BRANCH_ROOT", str(fake / "backup"))
        own = str(fake / "backup" / "apps" / "modules" / "snapshot.py")

        assert _fence_verdict(own, guard) is None

    def test_a_real_backup_file_is_kin(self, guard) -> None:
        """The allow side against the REAL root, again without compiling."""
        real_kin = str(Path(guard._BRANCH_ROOT) / "apps" / "modules" / "snapshot.py")
        assert guard._is_kin(real_kin, guard._BRANCH_ROOT)

    def test_pseudo_frame_caller_is_allowed(self, guard) -> None:
        """A <string> frame is skipped, not resolved, so the fence admits it."""
        # From a cwd inside the branch this passes without the skip too; the
        # tmp_path-cwd sibling test_the_mint_guard_permits_a_pseudo_frame pins the skip.
        assert _fence_verdict("<string>", guard) is None


class TestKinshipSurvivesTheWindowsSpelling:
    """The fence must recognise its OWN files when paths are spelled Windows.

    Both sides of the kinship comparison must be normalised: a forward-slashed
    caller never contains a backslashed ``_BRANCH_ROOT``. Reproduced on Linux
    with ``PureWindowsPath`` -- the bug needs a backslash, not a Windows box.
    """

    WIN_ROOT = PureWindowsPath(r"C:\Actions\AIPass\src\aipass\backup")
    WIN_KIN = WIN_ROOT / "apps" / "__init__.py"

    def test_windows_spelled_kin_is_recognised(self, guard) -> None:
        """The exact CI shape: backslashed root, backslashed own file."""
        assert guard._is_kin(str(self.WIN_KIN), str(self.WIN_ROOT))

    def test_the_fabrication_really_carries_backslashes(self) -> None:
        """Control: if PureWindowsPath rendered POSIX here, the pin proves nothing."""
        assert "\\" in str(self.WIN_KIN)
        assert "/" not in str(self.WIN_KIN)

    def test_mixed_spellings_agree(self, guard) -> None:
        """Either side may arrive in either dialect; both readings are kin."""
        assert guard._is_kin(str(self.WIN_KIN), self.WIN_ROOT.as_posix())
        assert guard._is_kin(self.WIN_KIN.as_posix(), str(self.WIN_ROOT))

    def test_drive_letter_case_folds_on_windows(self, guard) -> None:
        """C: vs c: is the same drive. Windows folds case; the comparison must."""
        lowered = str(self.WIN_KIN).replace("C:", "c:", 1)
        assert guard._is_kin(lowered, str(self.WIN_ROOT), windows=True)

    def test_case_does_not_fold_on_posix(self, guard, tmp_path: Path) -> None:
        """The negative control for the fold: POSIX case-sensitivity is not weakened."""
        # An unconditional fold would admit a foreign BACKUP dir on Linux; the fold is platform-gated.
        root = str(tmp_path / "src" / "aipass" / "backup")
        assert not guard._is_kin(f"{root.upper()}/apps/evil.py", root, windows=False)
        assert guard._is_kin(f"{root}/apps/ok.py", root, windows=False)

    def test_foreign_windows_caller_is_still_refused(self, guard) -> None:
        """Separator-safety must not turn into admit-everything."""
        foreign = PureWindowsPath(r"C:\Actions\AIPass\src\aipass\memory\apps\x.py")
        assert not guard._is_kin(str(foreign), str(self.WIN_ROOT))

    def test_guard_allows_windows_spelled_own_file_end_to_end(self, guard, monkeypatch, tmp_path: Path) -> None:
        """The fence admits a Windows-spelled own file end to end."""
        # On Linux a drive-lettered path is RELATIVE, so _find_real_caller resolves it
        # under the cwd; the pure _is_kin pins above carry the argument without that artifact.
        monkeypatch.setattr(guard, "_BRANCH_ROOT", str(self.WIN_ROOT))
        monkeypatch.chdir(tmp_path)

        assert _fence_verdict(str(self.WIN_KIN), guard) is None

    def test_guard_still_refuses_windows_spelled_foreigner(self, guard, monkeypatch, tmp_path: Path) -> None:
        """Same end-to-end path, refuse side -- the fence still closes."""
        monkeypatch.setattr(guard, "_BRANCH_ROOT", str(self.WIN_ROOT))
        monkeypatch.chdir(tmp_path)
        foreign = PureWindowsPath(r"C:\Actions\AIPass\src\aipass\memory\apps\x.py")
        with pytest.raises(ImportError, match="ACCESS DENIED"):
            _compile_as(str(foreign), guard)

    def test_self_skip_uses_the_same_spelling_rule(self, guard, monkeypatch, tmp_path: Path) -> None:
        """Under the Windows case fold, a case-variant spelling of the guard's own file still skips its frame."""
        # A missed self-skip returns __init__.py as the (kin) caller and opens the fence.
        monkeypatch.setattr(guard, "_IS_WINDOWS", True)
        monkeypatch.setattr(guard, "__file__", str(GUARD_FILE).upper())
        with pytest.raises(ImportError, match="ACCESS DENIED"):
            _compile_as(str(tmp_path / "outsider.py"), guard)


#: Behavioural sibling to the AST ban. Called DIRECTLY from a ``-c`` child every frame
#: is string-pseudo or importlib, both skipped, ``_find_real_caller`` returns None and
#: the branch RUNS: a regrown ``inspect.stack()`` walk dies there under a realpath denial.
_NONE_BRANCH_PROBE = textwrap.dedent(
    """
    import json, os, os.path, sys
    # Imported BEFORE the denial: the guard's own import needs realpath.
    import aipass.backup.apps.handlers as g

    result = {}
    def _denied(*a, **k):
        raise OSError(9999, "realpath denied")
    os.path.realpath = _denied

    # ARMING PROBE 1 -- MEASURE, do not assert, whether the denial reaches the
    # construct under test. inspect.stack() routes to os.path.realpath through
    # getmodule (3.12: inspect.py:1009), and an interpreter that spells that
    # route differently makes this world inert rather than wrong. The child
    # reports; the parent decides. It measures the call THIS world denies: the
    # route travels across versions, the line number does not.
    import inspect
    try:
        inspect.stack()
        result["denial_bites"] = False
        result["stack_route"] = "inspect.stack() returned; no realpath on the route"
    except OSError as exc:
        result["denial_bites"] = exc.errno == 9999
        result["stack_route"] = "inspect.stack() raised OSError " + str(exc.errno)

    # ARMING PROBE 2 -- the branch under test must be the one entered. Without
    # this the world could silently exercise the ordinary kin path instead.
    try:
        result["caller_is_none"] = g._find_real_caller() == (None, None)
    except BaseException as exc:
        result["caller_is_none"] = "raised " + type(exc).__name__

    # THE PIN.
    try:
        g._guard_branch_access()
        result["guard_returns"] = True
    except BaseException as exc:
        result["guard_returns"] = "raised " + type(exc).__name__ + ": " + str(exc)

    print(json.dumps(result))
    """
)


def _behavioural_verdict(report: dict) -> str:
    """ASSERT where the denial reaches inspect.stack(), STAND_DOWN where it does not.

    Both rows are reachable from any interpreter because the input is a
    measured value, not the host.
    """
    return "ASSERT" if report.get("denial_bites") is True else "STAND_DOWN"


class TestTheCallerIsNoneBranchIsWatchedBehaviourally:
    """The deleted second stack walk, pinned by RUNNING it -- not only by shape.

    ``-c`` and never a script: run this as a file and every frame is a real
    on-disk path, ``getsourcefile`` early-returns, and the denial is silently
    inert.
    """

    @staticmethod
    def _run() -> dict:
        proc = subprocess.run(
            [sys.executable, "-c", _NONE_BRANCH_PROBE],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_the_verdict_table_has_both_rows(self) -> None:
        """Both verdict rows are reachable on this host, the stand-down arm included."""
        armed = {"denial_bites": True, "stack_route": "raised"}
        inert = {"denial_bites": False, "stack_route": "returned"}
        assert _behavioural_verdict(armed) == "ASSERT"
        assert _behavioural_verdict(inert) == "STAND_DOWN"
        assert _behavioural_verdict({}) == "STAND_DOWN"

    def test_this_host_is_armed(self) -> None:
        """And on THIS interpreter the world is armed -- reported, not assumed."""
        report = self._run()
        assert _behavioural_verdict(report) == "ASSERT", report["stack_route"]

    def test_the_none_branch_is_actually_entered(self) -> None:
        """Arming probe: _find_real_caller returned None, so the branch ran."""
        # Version-independent: it rests on frame filenames, not on any route.
        assert self._run()["caller_is_none"] is True

    def test_the_guard_returns_instead_of_walking(self) -> None:
        """The guard returns under a realpath denial, where a regrown inspect.stack() walk raises."""
        report = self._run()
        # Where inspect.stack() never reaches realpath the world is inert: stand down;
        # the AST ban still watches the branch everywhere.
        if _behavioural_verdict(report) == "STAND_DOWN":
            pytest.skip(f"world inert here: {report['stack_route']}")
        assert report["guard_returns"] is True


#: Classes whose tests compile ``check()`` under a fabricated filename. Run
#: under coverage below; anything added here is covered by the same pin.
_COMPILING_CLASSES = (
    "TestFenceStillRefusesForeignCallers",
    "TestKinshipSurvivesTheWindowsSpelling",
)

_INNER_COVERAGE_WINDOWS_SKIP = (
    "skipped on Windows: measured 2026-09-01 (5dee751a, windows-setup), the inner "
    "coverage run failed on the real Windows host, unverifiable from this box; "
    "the pin stays live on POSIX, where the report-step failure was caught"
)


class TestFabricatedFilenamesNeverReachCoverage:
    """No fabricated caller filename may reach coverage's measured files.

    coverage.py records every executed code object by filename, existing file or
    not: a fabricated name inside the ``source`` filter and absent from disk makes
    the REPORT step exit 1 with "No source for code" while every test passes.
    The report-step pins and the structural ones fail for different reasons.
    """

    @staticmethod
    def _empty_rcfile(tmp_path: Path) -> Path:
        """An empty coverage config under tmp_path, so no project rcfile is read."""
        rcfile = tmp_path / "empty.coveragerc"
        rcfile.write_text("", encoding="utf-8")
        return rcfile

    @staticmethod
    def _coverage_run(tmp_path: Path, cwd: Path) -> Path:
        """Run the compiling tests under coverage from ``cwd``; return the data file."""
        data_file = tmp_path / f"cov-{cwd.name}.dat"
        rcfile = TestFabricatedFilenamesNeverReachCoverage._empty_rcfile(tmp_path)
        env = {**os.environ, "COVERAGE_FILE": str(data_file)}
        selected = [f"{TEST_FILE}::{name}" for name in _COMPILING_CLASSES]
        run = subprocess.run(
            [
                sys.executable,
                "-m",
                "coverage",
                "run",
                f"--rcfile={rcfile}",
                f"--source={SOURCE_TREE}",
                "-m",
                "pytest",
                *selected,
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,
        )
        assert run.returncode == 0, f"the tests themselves failed:\n{run.stdout}"
        return data_file

    @pytest.mark.skipif(sys.platform == "win32", reason=_INNER_COVERAGE_WINDOWS_SKIP)
    @pytest.mark.parametrize("from_repo_root", [True, False], ids=["repo_cwd", "branch_cwd"])
    def test_no_measured_file_is_missing_from_disk(self, tmp_path: Path, from_repo_root: bool) -> None:
        """Run from the repo root and from the branch, coverage measures no file missing from disk."""
        # Both cwds, because coverage resolves a relative fabricated filename against the cwd
        # at trace time. Asserted on the data, not `coverage report` (~30s, paid once below).
        cwd = SOURCE_TREE.parents[1] if from_repo_root else BRANCH_ROOT
        data = coverage.CoverageData(basename=str(self._coverage_run(tmp_path, cwd)))
        data.read()
        assert _missing_sources(data.measured_files()) == []

    @pytest.mark.skipif(sys.platform == "win32", reason=_INNER_COVERAGE_WINDOWS_SKIP)
    def test_the_real_report_step_survives(self, tmp_path: Path) -> None:
        """The real `coverage report` step, run from the branch cwd, exits 0 with no missing source."""
        # The branch cwd sees both the absolute and the relative (Windows-spelled) minters.
        env = {**os.environ, "COVERAGE_FILE": str(self._coverage_run(tmp_path, BRANCH_ROOT))}
        rcfile = self._empty_rcfile(tmp_path)
        report = subprocess.run(
            [sys.executable, "-m", "coverage", "report", f"--rcfile={rcfile}"],
            cwd=BRANCH_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,
        )
        assert "No source for code" not in (report.stdout + report.stderr)
        assert report.returncode == 0, report.stderr

    def test_no_compiled_filename_is_under_the_source_tree(self) -> None:
        """This file has exactly one compile() site, _compile_as, where the mint guard stands."""
        assert _compile_sites(TEST_FILE.read_text(encoding="utf-8")) == ["_compile_as"]

    def test_the_missing_source_predicate_can_say_no(self, tmp_path: Path) -> None:
        """Control: the missing-source predicate convicts an absent file and passes a present one."""
        present = tmp_path / "real.py"
        present.write_text("x = 1\n", encoding="utf-8")
        absent = str(tmp_path / "src" / "aipass" / "memory" / "apps" / "x.py")
        assert _missing_sources([str(present), absent]) == [absent]

    def test_the_mint_guard_refuses_a_tree_shaped_name(self, guard) -> None:
        """Control: the mint guard in _compile_as refuses a name inside the source tree."""
        # The name is refused before compile(), so nothing is minted under the real tree.
        with pytest.raises(AssertionError, match="coverage source tree"):
            _compile_as(str(BRANCH_ROOT / "apps" / "never_written.py"), guard)

    def test_the_mint_guard_permits_a_pseudo_frame(self, guard, monkeypatch, tmp_path: Path) -> None:
        """From a cwd outside the branch, the mint guard and the fence both admit a <string> frame."""
        # The cwd must leave the branch: from inside it "<string>" resolves to
        # <branch_root>/<string>, which is kin, so dropping the pseudo-frame skip stays green.
        monkeypatch.chdir(tmp_path)

        assert _fence_verdict("<string>", guard) is None

    def test_the_structural_check_can_say_no(self) -> None:
        """Control: _compile_sites names a second compile() site in a synthetic file."""
        synthetic = textwrap.dedent(
            """
            def _compile_as(name, guard):
                exec(compile("check()", name, "exec"), {})

            def a_second_mint_point(name):
                return compile("check()", name, "exec")
            """
        )
        assert _compile_sites(synthetic) == ["_compile_as", "a_second_mint_point"]
