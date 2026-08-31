# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Pins seedgo imports against a working directory the OS cannot read
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""Every seedgo module must import without a readable working directory.

TWO DEFECTS, TWO WORLDS — and one instrument would have proved only half.

WORLD A, the ntpath condition. ``ntpath.realpath`` calls ``os.getcwd()``
UNCONDITIONALLY, before it checks whether the path is even relative, and
``Path.resolve()`` routes through it. So on Windows every module-level
``Path(__file__).resolve()`` is an import-time working-directory read. Twelve
seedgo modules had one. Injected as the CONDITION rather than the platform:
``os.path.realpath`` is wrapped to read ``os.getcwd()`` first, then ``getcwd``
is denied.

WORLD B, the inspect.stack() shape. ``handlers/__init__.py`` called
``inspect.stack()`` before anything else. That builds a FrameInfo per frame ->
``getsourcefile`` -> (only for the frozen importlib frames an import puts on the
stack) ``getmodule``, whose module-scan loop calls ``os.path.realpath`` OUTSIDE
any try. World A CANNOT catch this one: on POSIX the walk raises earlier inside
``getabsfile``, where ``inspect`` catches ``FileNotFoundError`` and returns
None — so a getcwd denial leaves the defective guard green while Windows dies,
because ``ntpath.abspath`` succeeds there and control reaches the unprotected
realpath. World B injects that asymmetry directly: ``abspath`` keeps working,
``os.path.realpath`` raises.

Both were REPRODUCED RED ON LINUX against the pre-fix source before the cure was
written; neither needed a Windows box. Measured on the Windows CI gate
2026-08-31 (@memory's finding for A, @spawn's for B, relayed by @devpulse).

Each world carries a POSITIVE CONTROL — a module rebuilt in the defective shape
and imported live, which must die — and a NEGATIVE CONTROL FOR THE POSITIVE
CONTROL: the same module must import cleanly in the healthy world. @spawn's
lesson from the same round: a control that dies for any reason turns every pin
above it vacuously green, so the control needs a control.
"""

import subprocess
import sys
from pathlib import Path

import pytest

SEEDGO_ROOT = Path(__file__).resolve().parents[1]

# Other branches' import-time code is held CONSTANT: imported in the healthy
# world, before any denial. Their dead-cwd cure is their own build (fleet
# rollout in flight, 2026-08-31); this pin measures SEEDGO's sites only.
# TEMPORARY — delete each line as its branch is cured, and the pin gets stricter
# for free. These ten are exactly the foreign entry points seedgo's own source
# names; the rest of each chain rides in behind them.
PRELOAD = """
import aipass.prax  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.prax.apps.handlers.logging.setup  # noqa: F401
import aipass.cli  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401
import aipass.cli.apps.modules.display  # noqa: F401
import aipass.drone.apps.modules  # noqa: F401
import aipass.spawn.apps.modules  # noqa: F401
import aipass.aipass.shared  # noqa: F401
import aipass.aipass.shared.json_handler  # noqa: F401
"""

# The two shapes the cure deleted, rebuilt verbatim. Written to disk and
# imported live rather than reasoned about: the question is whether the world
# still kills the OLD code, and only the old code can answer it.
DEFECT_A_SOURCE = "from pathlib import Path\nX = Path(__file__).resolve()\n"
DEFECT_B_SOURCE = "import inspect\nX = inspect.stack()\n"

ARM_WORLD_A = """
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

ARM_WORLD_B = """
import os


def _dead_realpath(path, **kw):
    # ntpath.realpath's first act is a cwd read; abspath still SUCCEEDS on
    # Windows, which is exactly why inspect reaches this call unprotected.
    raise FileNotFoundError(2, "realpath needs a cwd", "")


os.path.realpath = _dead_realpath
"""

# Does THIS interpreter's Path.resolve() reach the denied call for an absolute
# path? 3.11+ routes through os.path.realpath; older ones short-circuit. Pinned
# as a probe with BOTH outcomes reported, never a skipif — the vacuous world is
# named in the output rather than hidden by a skip.
PROBE = """
import pathlib

try:
    pathlib.Path(pathlib.__file__).resolve()
    print("PROBE_VACUOUS")
except OSError:
    print("PROBE_ARMED")
"""


def _seedgo_modules():
    """Every importable module under seedgo/apps, enumerated live.

    Enumerated in the PARENT and injected, so a module added tomorrow is covered
    without anyone remembering to list it — and so the child never needs a
    directory walk in a world where the filesystem is being denied.
    """
    modules = []
    for path in sorted(SEEDGO_ROOT.glob("apps/**/*.py")):
        parts = list(path.relative_to(SEEDGO_ROOT).parts)
        parts = parts[:-1] if parts[-1] == "__init__.py" else parts[:-1] + [parts[-1][:-3]]
        modules.append("aipass.seedgo." + ".".join(parts) if parts else "aipass.seedgo")
    return modules


def _run(world: str):
    """Run a world in a child process, fed on stdin.

    stdin, not a script file: code read from stdin has co_filename ``<stdin>``,
    which the handlers guard skips as a pseudo-file. A real script path on disk
    would be a caller OUTSIDE the branch and the guard would refuse the import —
    a correct refusal that has nothing to do with what this file measures.
    """
    return subprocess.run(
        [sys.executable, "-"],
        input=world,
        capture_output=True,
        text=True,
        cwd=str(SEEDGO_ROOT.parents[2]),
    )


def _import_every_module_body():
    lines = [f"import {name}  # noqa: F401" for name in _seedgo_modules()]
    return "\n".join(lines) + '\nprint("IMPORTED_ALL")\n'


def _defect_body(tmp_path: Path, source: str, name: str) -> str:
    """A module in the deleted shape, on disk, imported by absolute path."""
    target = tmp_path / f"{name}.py"
    target.write_text(source, encoding="utf-8")
    return f"""
import importlib.util

_spec = importlib.util.spec_from_file_location({name!r}, {str(target)!r})
_mod = importlib.util.module_from_spec(_spec)
try:
    _spec.loader.exec_module(_mod)
    print("DEFECT_SURVIVED")
except OSError as exc:
    print("DEFECT_DIED:", type(exc).__name__)
"""


@pytest.fixture(scope="module")
def world_a_result():
    return _run(PRELOAD + ARM_WORLD_A + PROBE + _import_every_module_body())


@pytest.fixture(scope="module")
def world_b_result():
    return _run(PRELOAD + ARM_WORLD_B + _import_every_module_body())


class TestTheInstrumentsCanFire:
    """Positive controls: each world must still kill the code the cure deleted."""

    def test_world_a_kills_a_module_level_resolve(self, tmp_path):
        body = _defect_body(tmp_path, DEFECT_A_SOURCE, "defect_a")
        result = _run(PRELOAD + ARM_WORLD_A + body)
        assert "DEFECT_DIED" in result.stdout, f"world A is not armed: {result.stdout}\n{result.stderr}"

    def test_world_b_kills_an_import_time_inspect_stack(self, tmp_path):
        body = _defect_body(tmp_path, DEFECT_B_SOURCE, "defect_b")
        result = _run(PRELOAD + ARM_WORLD_B + body)
        assert "DEFECT_DIED" in result.stdout, f"world B is not armed: {result.stdout}\n{result.stderr}"

    def test_world_b_does_not_ride_a_linecache_cached_frame(self, tmp_path):
        """@hooks' instrument hazard, relayed by @devpulse, MEASURED here.

        ``inspect.getsourcefile`` early-returns for anything already in
        ``linecache.cache``, so a world-B signal riding a cached top frame would
        never reach ``getmodule`` and would report vacuous-or-armed wrongly.
        Code fed on stdin CAN populate ``<stdin>`` there.

        This child's control does not ride that frame — it dies inside frozen
        importlib frames from ``exec_module``, which are never cached — but
        "does not today" is not something a future reader can verify, so the
        child asserts its own assumption. If a later edit makes the control
        depend on a cached frame, this goes red rather than going quiet.
        """
        probe = "import linecache\nprint('STDIN_CACHED:', '<stdin>' in linecache.cache)\n"
        body = _defect_body(tmp_path, DEFECT_B_SOURCE, "defect_b")
        result = _run(PRELOAD + probe + ARM_WORLD_B + body)
        assert "STDIN_CACHED: False" in result.stdout, result.stdout
        assert "DEFECT_DIED" in result.stdout, result.stdout

    @pytest.mark.parametrize(
        "source,name",
        [(DEFECT_A_SOURCE, "defect_a"), (DEFECT_B_SOURCE, "defect_b")],
    )
    def test_both_defect_modules_import_cleanly_in_the_healthy_world(self, tmp_path, source, name):
        """The control FOR the controls.

        A probe module that dies for its own reasons — a typo, a missing import —
        reports DEFECT_DIED in every world and every pin above goes vacuously
        green. So the same file must survive with nothing denied.
        """
        result = _run(PRELOAD + _defect_body(tmp_path, source, name))
        assert "DEFECT_SURVIVED" in result.stdout, f"{name} dies unarmed: {result.stdout}\n{result.stderr}"


class TestEverySeedgoModuleImportsWithoutAReadableCwd:
    def test_world_a_probe_reports_which_world_it_measured(self, world_a_result):
        """Reported, never skipped: an interpreter that short-circuits resolve()
        for absolute paths cannot fire world A's denial, and the pin below then
        proves less. It says so out loud rather than passing quietly."""
        assert "PROBE_ARMED" in world_a_result.stdout or "PROBE_VACUOUS" in world_a_result.stdout

    def test_world_a_imports_every_module(self, world_a_result):
        assert "IMPORTED_ALL" in world_a_result.stdout, world_a_result.stderr

    def test_world_b_imports_every_module(self, world_b_result):
        assert "IMPORTED_ALL" in world_b_result.stdout, world_b_result.stderr


class TestNoSeedgoModuleResolvesAtImportOutsideTheHelper:
    """The sweep that keeps the thirteenth site from being written quietly.

    Not a grep: the discriminator is REACHED AT IMPORT, and 61 of seedgo's 75
    ``.resolve()`` call sites are call-time. ``Path.resolve`` is wrapped to
    record its caller while the whole tree is imported, so a default argument
    evaluated at import counts and a line inside a function body does not.
    """

    RECORDER = """
import importlib
import pathlib
import sys

_records = []
_real_resolve = pathlib.Path.resolve


def _recording_resolve(self, *a, **kw):
    frame = sys._getframe(1)
    _records.append((frame.f_code.co_filename, frame.f_lineno))
    return _real_resolve(self, *a, **kw)


pathlib.Path.resolve = _recording_resolve

for _name in %(modules)r:
    importlib.import_module(_name)

pathlib.Path.resolve = _real_resolve

for _filename, _lineno in sorted(set(_records)):
    if "%(marker)s" in _filename.replace("\\\\", "/"):
        print("SITE", _filename, _lineno)
print("SWEPT")
"""

    def _sweep(self):
        world = PRELOAD + self.RECORDER % {
            "modules": _seedgo_modules(),
            "marker": "/seedgo/",
        }
        return _run(world)

    def test_the_only_import_time_resolves_left_are_guarded(self):
        result = self._sweep()
        assert "SWEPT" in result.stdout, result.stderr
        sites = [line.split() for line in result.stdout.splitlines() if line.startswith("SITE ")]
        offenders = [
            f"{Path(parts[1]).relative_to(SEEDGO_ROOT)}:{parts[2]}"
            for parts in sites
            if Path(parts[1]).name not in ("module_root.py", "__init__.py")
        ]
        assert offenders == [], f"import-time resolve() outside module_file(): {offenders}"

    def test_the_sweep_actually_visited_the_tree(self):
        """Positive control on the SWEEP: a walk that imported nothing reports
        no offenders and passes forever. The helper's own guarded resolve is the
        witness that the recorder was installed and the tree was really read."""
        result = self._sweep()
        seen = [line for line in result.stdout.splitlines() if line.startswith("SITE ")]
        assert any("module_root.py" in line for line in seen), (
            f"recorder saw no module_file() call — the sweep proves nothing: {result.stdout}"
        )


# ---------------------------------------------------------------------------
# The caller-is-None branch, watched behaviourally as well as structurally
# ---------------------------------------------------------------------------

_DIRECT_CALL_BODY = """
from aipass.seedgo.apps.handlers import _find_real_caller, _guard_branch_access

# ARMING PROBE 2: the branch under test only RUNS when _find_real_caller
# returns None. Fed on stdin every frame is <stdin> or frozen importlib, both
# skipped, so it does. Without this the guard could return for some entirely
# different reason and the pin would report the same green.
print("CALLER_IS_NONE:", _find_real_caller() == (None, None))

_guard_branch_access()
print("GUARD_RETURNED")
"""


class TestTheCallerIsNoneBranchIsReachableByADirectCall:
    """@devpulse relaying @spawn's correction of MY sentence, 2026-08-31.

    I published "the deleted second inspect.stack() walk is unreachable, so only
    an AST ban can watch it". Too strong, and @spawn measured the correction:
    unreachable from IMPORT-shaped pins — apps/__init__ always supplies a real
    on-disk frame — but reachable by calling ``_guard_branch_access()`` DIRECTLY
    from a child fed on stdin, where every frame is a pseudo-file or frozen
    importlib and ``_find_real_caller`` therefore returns None.

    So the branch gets a behavioural pin as well as the structural one. The AST
    ban still earns its place: no subprocess, and it names the defect precisely.
    This one is the sibling that watches the BEHAVIOUR, and the two die to
    different mutations — regrowing the walk kills both, deleting only the AST
    rule leaves this standing.

    The true sentence, for the record: import-shaped pins cannot reach it. Not
    "nothing can".
    """

    @staticmethod
    @pytest.fixture(scope="class")
    def result():
        return _run(PRELOAD + ARM_WORLD_B + PROBE + _DIRECT_CALL_BODY)

    def test_the_denial_bites_in_this_child(self, result):
        """Arming probe 1. A world that silently failed to deny anything would
        let a regrown inspect.stack() walk pass this whole class."""
        assert "PROBE_ARMED" in result.stdout, result.stderr

    def test_the_branch_under_test_actually_runs(self, result):
        """Arming probe 2, and @spawn's rule: a structural claim that read the
        wrong thing reports exactly the same green as a clean tree. If
        _find_real_caller returned a real caller here, the guard would be
        exercising the ALLOW-pytest path instead and proving nothing."""
        assert "CALLER_IS_NONE: True" in result.stdout, result.stdout

    def test_the_guard_returns_rather_than_dying(self, result):
        """The claim itself. A regrown second walk dies here under the realpath
        denial; the cured plain return survives."""
        assert "GUARD_RETURNED" in result.stdout, result.stderr
        assert result.returncode == 0, result.stderr
