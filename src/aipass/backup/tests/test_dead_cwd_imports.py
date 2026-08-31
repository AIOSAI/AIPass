# =================== AIPass ====================
# Name: test_dead_cwd_imports.py
# Description: Dead-cwd import defect — guard shape, safe path helper, both worlds
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""The dead-cwd import defect (Windows round 4).

``ntpath.realpath`` reads ``os.getcwd()`` UNCONDITIONALLY -- posixpath only does
so for relative paths -- and ``Path.resolve()`` routes through it. So on Windows
every ``resolve()`` REACHED AT IMPORT is an import-time crash for a process whose
cwd was deleted: the module cannot be imported at all.

Two injections are needed because they convict different code:

* **World A** wraps ``os.path.realpath`` to read the cwd first, then denies
  ``os.getcwd``. This convicts a raw ``resolve()``. It CANNOT convict
  ``inspect.stack()`` -- denying getcwd also kills ``abspath``, so ``getmodule``
  dies at ``getabsfile`` inside its own ``except`` and ``stack()`` completes
  green for the wrong reason.
* **World B** denies ``os.path.realpath`` directly and leaves ``abspath``
  working. This convicts ``inspect.stack()`` via ``getmodule``'s unguarded
  ``realpath`` at inspect.py:1009.

Every probe rides a **string pseudo-frame** (``python -c``), never stdin:
linecache caches stdin and the probe would report green while lying.

Measured on this branch 2026-08-31: 57/57 modules red in both worlds before the
cure, 0/57 after.
"""

import ast
import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from aipass.backup.apps.handlers.path import module_paths

#: The real guard file. It is loaded from disk rather than imported by name
#: because conftest installs a stub for the handlers package (to keep the
#: cross-branch guard out of the suite's way), and a stub cannot be tested.
GUARD_FILE = Path(__file__).resolve().parents[1] / "apps" / "handlers" / "__init__.py"


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

#: One module per cured site, plus the entry point that pulls the whole tree.
PROBE_MODULES = [
    "aipass.backup.apps",
    "aipass.backup.apps.backup",
    "aipass.backup.apps.handlers",
    "aipass.backup.apps.handlers.state.backup_timestamps",
    "aipass.backup.apps.handlers.project.setup",
    "aipass.backup.apps.handlers.project.registry",
    "aipass.backup.apps.handlers.json.json_handler",
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
if world == "A":
    os.path.realpath = _realpath_reads_cwd
    os.getcwd = _dead_getcwd
elif world == "B":
    os.path.realpath = _dead_realpath
if world == "CONTROL":
    os.path.realpath = _realpath_reads_cwd
    os.getcwd = _dead_getcwd
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
        timeout=180,
    )
    assert proc.stdout.strip(), f"probe produced no stdout (stderr: {proc.stderr[-400:]})"
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestTheInjectionCanSayNo:
    """A positive control needs its own negative control.

    A CONTROL_LIVE probe that cannot fail turns every pin below vacuously green.
    """

    def test_the_denial_actually_bites(self) -> None:
        """Under the world-A injection, a plain resolve() must raise."""
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


class TestSafePathHelper:
    """module_file degrades to the raw absolute spelling, never to a crash."""

    def test_returns_resolved_path_normally(self) -> None:
        """In a healthy world it behaves like resolve()."""
        assert module_paths.module_file(__file__) == Path(__file__).resolve()

    def test_falls_back_when_resolve_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An OSError from resolve() yields an absolute path, not an exception."""
        original = Path.resolve

        def _boom(self, *args, **kwargs):
            raise OSError(2, "cwd denied")

        module_paths._REPORTED_DEGRADED.discard(__file__)
        monkeypatch.setattr(Path, "resolve", _boom)
        result = module_paths.module_file(__file__)
        monkeypatch.setattr(Path, "resolve", original)

        assert result.is_absolute()
        assert result.name == Path(__file__).name

    def test_branch_root_climbs_without_resolve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """branch_root still answers when resolve() is unavailable."""

        def _boom(self, *args, **kwargs):
            raise OSError(2, "cwd denied")

        monkeypatch.setattr(Path, "resolve", _boom)
        assert module_paths.branch_root(__file__, 1).is_absolute()


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

    @trigger measured that the caller-is-None branch is UNREACHABLE from any
    import-shaped pin -- apps/__init__ always supplies a real-file frame -- so
    restoring the second inspect.stack() walk leaves every behavioural test
    green. This pin is the only thing that convicts it.

    It must be an AST ban and never a string ban: the guard's own docstring
    names inspect.stack() while explaining the defect, and a spelling ban would
    convict the explanation.
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
        """Guards the negative control above: if the prose ever stops mentioning
        inspect.stack(), the docstring control is no longer testing anything."""
        assert "inspect.stack()" in GUARD_FILE.read_text(encoding="utf-8")


class TestFenceStillRefusesForeignCallers:
    """Curing the crash must not quietly open the fence.

    The guard reads ``f_code.co_filename`` off the calling frame, so a foreign
    caller is simulated by compiling the call under a foreign filename. That is
    the same mechanism a real cross-branch import presents.
    """

    @staticmethod
    def _call_guard_as(guard, caller_file: str) -> None:
        code = compile("check()", caller_file, "exec")
        exec(code, {"check": guard._guard_branch_access})

    def test_foreign_caller_is_refused(self, guard, tmp_path: Path) -> None:
        """A caller outside the branch root raises ImportError."""
        with pytest.raises(ImportError, match="ACCESS DENIED"):
            self._call_guard_as(guard, str(tmp_path / "outsider.py"))

    def test_sibling_branch_is_refused(self, guard) -> None:
        """Another citizen's file is refused, and named in the message."""
        sibling = str(Path(guard._BRANCH_ROOT).parent / "memory" / "apps" / "x.py")
        with pytest.raises(ImportError, match="memory"):
            self._call_guard_as(guard, sibling)

    def test_own_branch_file_is_allowed(self, guard) -> None:
        """A real backup file passes -- the fence is not simply always-refuse."""
        kin = str(Path(guard._BRANCH_ROOT) / "apps" / "modules" / "snapshot.py")
        self._call_guard_as(guard, kin)

    def test_pseudo_frame_caller_is_allowed(self, guard) -> None:
        """A <string> frame is skipped, not resolved -- that skip is the cure."""
        self._call_guard_as(guard, "<string>")
