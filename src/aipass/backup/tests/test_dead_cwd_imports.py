# =================== AIPass ====================
# Name: test_dead_cwd_imports.py
# Description: Dead-cwd import defect — safe path helper, both worlds, the fence with its cwd removed
# Version: 2.0.3
# Created: 2026-08-31
# Modified: 2026-10-16
# =============================================

"""Tests for apps/handlers/path/module_paths.py and the fence in apps/handlers/__init__.py under a dead cwd."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/__init__.py and handlers/path/module_paths.py lint clean
# seedgo: no-test-needed(documentation) — the docstrings of module_file() and branch_root()
# seedgo: no-test-needed(stdlib) — linecache.getline(), which fills the fence message's Blocked: line

import ast
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from aipass.backup.apps.handlers.path import module_paths
from aipass.backup.tests import support_fence

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


TEST_FILE = Path(__file__).resolve()
BRANCH_ROOT = TEST_FILE.parents[1]
GUARD_FILE = BRANCH_ROOT / "apps" / "handlers" / "__init__.py"
KIN_PROBE = Path(support_fence.__file__)


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


class _ResolveDeniedPath(type(Path())):
    """A ``Path`` whose ``resolve()`` refuses, standing in for the dead cwd.

    Installed over ``module_paths.Path`` (the module's own ``from pathlib import
    Path`` binding), it denies ``resolve()`` to the module under test and to
    nothing else. ``module_file``'s fallback is reached through the same
    binding, so it returns one of these: a real ``Path`` in every other respect.
    It subclasses the concrete class (PosixPath or WindowsPath): on Python 3.10
    and 3.11 a direct ``Path`` subclass has no ``_flavour`` and cannot be built.
    """

    def resolve(self, strict: bool = False) -> Path:
        """Refuse the way a deleted cwd refuses: OSError, not a crash."""
        raise OSError(2, "cwd denied")


class TestSafePathHelper:
    """module_file degrades to the raw absolute spelling, never to a crash."""

    def test_returns_resolved_path_normally(self, tmp_path: Path) -> None:
        """In a healthy world a symlinked module file collapses to the real file it names."""
        base = Path(os.path.realpath(tmp_path))
        real = base / "real" / "mod.py"
        real.parent.mkdir()
        real.write_text("", encoding="utf-8")
        link = base / "link"
        try:
            link.symlink_to(real.parent, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlinks cannot be made here (Windows without the privilege): {exc}")

        assert module_paths.module_file(str(link / "mod.py")) == base / "real" / "mod.py"

    def test_falls_back_when_resolve_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """An OSError from resolve() yields the same file's absolute spelling, not an exception."""
        # Spelled from the fixture, not the product's abspath: a cwd answer must fail.
        module = tmp_path / "branch" / "apps" / "handlers" / "mod.py"
        monkeypatch.setattr(module_paths, "_REPORTED_DEGRADED", set())
        monkeypatch.setattr(module_paths, "Path", _ResolveDeniedPath)

        assert module_paths.module_file(str(module)) == tmp_path / "branch" / "apps" / "handlers" / "mod.py"

    def test_branch_root_climbs_without_resolve(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """branch_root lands on the exact ancestor the fixture built when resolve() is unavailable."""
        branch = tmp_path / "branch"
        module = branch / "apps" / "handlers" / "mod.py"
        monkeypatch.setattr(module_paths, "_REPORTED_DEGRADED", set())
        monkeypatch.setattr(module_paths, "Path", _ResolveDeniedPath)

        assert module_paths.branch_root(str(module), 2) == branch


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
    """An AST ban: inspect.stack() reaches os.path.realpath, which a dead cwd denies on Windows."""

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


#: The kin probe run from a child whose cwd was removed under it. The child asks
#: the platform whether a process may remove its own cwd and reports what it got;
#: the probe's own seat is kin, so the fence must answer ALLOWED either way.
_DEAD_CWD_PROBE = """
import json, os, runpy, sys, tempfile
seat, shape = sys.argv[1], sys.argv[2]
dead = tempfile.mkdtemp()
os.chdir(dead)
try:
    os.rmdir(dead)
    removed = True
except OSError:
    removed = False
try:
    os.getcwd()
    cwd_dead = False
except OSError:
    cwd_dead = True
probe = runpy.run_path(seat)
print(json.dumps({"removed": removed, "cwd_dead": cwd_dead, "verdict": probe["_run"](shape)}))
"""


class TestTheFenceSurvivesADeadCwd:
    """The fence reads frame paths with the cwd gone, and kin still passes."""

    @pytest.mark.parametrize("shape", ["pkg", "deep"])
    def test_the_kin_seat_is_allowed_with_its_cwd_removed(self, shape: str) -> None:
        """A removed cwd neither crashes the fence nor turns kin into a refusal."""
        proc = subprocess.run(
            [sys.executable, "-c", _DEAD_CWD_PROBE, str(KIN_PROBE), shape],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr[-600:]
        report = json.loads(proc.stdout.strip().splitlines()[-1])

        assert report["cwd_dead"] is report["removed"], report
        assert report["verdict"] == "ALLOWED", report
