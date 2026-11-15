# =================== AIPass ====================
# Name: test_dead_cwd_imports.py
# Description: Dead-cwd import defect — safe path helper, the denied-cwd world, the fence with its cwd removed
# Version: 2.0.4
# Created: 2026-08-31
# Modified: 2026-11-14
# =============================================

"""Tests for apps/handlers/path/module_paths.py and the fence in apps/handlers/__init__.py under a dead cwd."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that handlers/__init__.py and handlers/path/module_paths.py lint clean
# sentry: no-test-needed(documentation) — the docstrings of module_file() and branch_root()
# sentry: no-test-needed(stdlib) — linecache.getline(), which fills the fence message's Blocked: line

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from aipass.backup.apps.handlers.path import module_paths
from aipass.backup.tests import support_fence

# World A (getcwd denied) convicts an import-time cwd read. Probes run as -c, never stdin:
# linecache caches stdin and lies green.


KIN_PROBE = Path(support_fence.__file__)


#: Imported healthy BEFORE any denial; drive/client's optional @api import is not preloaded, so it stays tested.
PRELOAD = ["aipass.prax", "aipass.cli.apps.modules"]

PROBE_MODULES = [
    "aipass.backup.apps",
    "aipass.backup.apps.backup",
    "aipass.backup.apps.handlers",
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
def _dead_getcwd(*a, **k):
    raise FileNotFoundError(2, "probe: cwd denied")
if world in ("A", "CONTROL"):
    os.getcwd = _dead_getcwd
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

    def test_no_module_dies_at_import(self) -> None:
        """Every probed module imports with the cwd denied."""
        assert _run_probe("A")["red"] == {}


class _ResolveDeniedPath(type(Path())):
    """A ``Path`` whose ``resolve()`` refuses, standing in for the dead cwd.

    Subclasses the concrete class: on Python 3.10/3.11 a direct ``Path`` subclass cannot be built.
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
        link.symlink_to(real.parent, target_is_directory=True)

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
    """A dead cwd fails EVERY resolve, so the report is once per file, not per call."""

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


#: The kin probe in a child whose cwd was removed: ALLOWED.
_DEAD_CWD_PROBE = """
import json, os, runpy, sys, tempfile
seat, shape = sys.argv[1], sys.argv[2]
dead = tempfile.mkdtemp()
os.chdir(dead)
os.rmdir(dead)
try:
    os.getcwd()
    cwd_dead = False
except OSError:
    cwd_dead = True
probe = runpy.run_path(seat)
print(json.dumps({"cwd_dead": cwd_dead, "verdict": probe["_run"](shape)}))
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

        assert report["cwd_dead"] is True, report
        assert report["verdict"] == "ALLOWED", report
