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
from pathlib import Path, PureWindowsPath

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


class TestKinshipSurvivesTheWindowsSpelling:
    """The fence must recognise its OWN files when paths are spelled Windows.

    Round 5, from the windows-setup runner on 28ee90d5: every test in this file
    errored at import with backup's own ACCESS DENIED message -- the fence was
    refusing backup's own ``apps/__init__.py``.

    The mechanism is one-sided normalisation. The guard normalised the CALLER
    (``caller_file.replace("\\\\", "/")``) and compared it against a
    ``_BRANCH_ROOT`` that came straight from ``Path``, i.e. spelled with
    BACKSLASHES on Windows. A forward-slashed caller can never contain a
    backslashed root, so kinship failed for every file in the branch and the
    door import that arms the fence raised instead.

    Reproduced on Linux by fabricating the Windows spelling with
    ``PureWindowsPath`` -- the bug needs a backslash, not a Windows box.
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

    def test_case_does_not_fold_on_posix(self, guard) -> None:
        """The negative control for the fold: POSIX case-sensitivity is not weakened.

        Folding unconditionally would ADMIT a foreign /tmp/BACKUP on Linux, so
        the fold is gated on the platform rather than applied to be safe.
        """
        root = "/home/x/src/aipass/backup"
        assert not guard._is_kin(f"{root.upper()}/apps/evil.py", root, windows=False)
        assert guard._is_kin(f"{root}/apps/ok.py", root, windows=False)

    def test_foreign_windows_caller_is_still_refused(self, guard) -> None:
        """Separator-safety must not turn into admit-everything."""
        foreign = PureWindowsPath(r"C:\Actions\AIPass\src\aipass\memory\apps\x.py")
        assert not guard._is_kin(str(foreign), str(self.WIN_ROOT))

    def test_guard_allows_windows_spelled_own_file_end_to_end(self, guard, monkeypatch) -> None:
        """The whole decision, not just the helper -- this is what CI ran.

        Red before the cure: ImportError, ACCESS DENIED, on backup's own file,
        with "Caller branch: backup" in the message -- the fence naming ITSELF
        as the foreigner, which is exactly what the runner printed.

        Noted for the next reader: on Linux a drive-lettered path is RELATIVE,
        so ``_find_real_caller`` resolves it under cwd and the branch root is
        prefixed onto it. The kinship substring is still the thing under test
        (this pin was red before the cure), but the pure-function pins above
        are the ones that carry the argument without that artifact.
        """
        monkeypatch.setattr(guard, "_BRANCH_ROOT", str(self.WIN_ROOT))
        code = compile("check()", str(self.WIN_KIN), "exec")
        exec(code, {"check": guard._guard_branch_access})

    def test_guard_still_refuses_windows_spelled_foreigner(self, guard, monkeypatch) -> None:
        """Same end-to-end path, refuse side -- the fence still closes."""
        monkeypatch.setattr(guard, "_BRANCH_ROOT", str(self.WIN_ROOT))
        foreign = PureWindowsPath(r"C:\Actions\AIPass\src\aipass\memory\apps\x.py")
        code = compile("check()", str(foreign), "exec")
        with pytest.raises(ImportError, match="ACCESS DENIED"):
            exec(code, {"check": guard._guard_branch_access})

    def test_self_skip_uses_the_same_spelling_rule(self, guard) -> None:
        """The guard's own-frame skip is the same comparison, and it matters more.

        If the self-skip misses, ``__init__.py`` itself is returned as the
        caller -- trivially kin -- and the foreign frame beneath it is never
        looked at. A case-fragile self-skip OPENS the fence.
        """
        source = GUARD_FILE.read_text(encoding="utf-8")
        assert "if this_file in resolved:" not in source
        assert source.count("_spell_for_kinship(") >= 4


#: Behavioural sibling to the AST ban, spawn's shape (relayed by devpulse).
#: The round-4 guidance said the caller-is-None branch is unreachable and only a
#: parse-tree pin can watch it. The true sentence is narrower: it is unreachable
#: from IMPORT-shaped pins. Called DIRECTLY from a ``-c`` child every frame is
#: string-pseudo or importlib, both skipped, ``_find_real_caller`` returns None,
#: and the branch RUNS -- so a regrown ``inspect.stack()`` walk dies there under
#: a realpath denial while the cured plain return survives.
_NONE_BRANCH_PROBE = textwrap.dedent(
    """
    import json, os, os.path, sys
    # Imported BEFORE the denial: the guard's own import needs realpath.
    import aipass.backup.apps.handlers as g

    result = {}
    def _denied(*a, **k):
        raise OSError(9999, "realpath denied")
    os.path.realpath = _denied

    # ARMING PROBE 1 -- the denial must bite the construct under test. Without
    # this the pin passes in a world where nothing was ever denied.
    import inspect
    try:
        inspect.stack()
        result["denial_bites"] = False
    except OSError as exc:
        result["denial_bites"] = exc.errno == 9999

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


class TestTheCallerIsNoneBranchIsWatchedBehaviourally:
    """The deleted second stack walk, pinned by RUNNING it -- not only by shape.

    ``-c`` and never a script: run this as a file and every frame is a real
    on-disk path, ``getsourcefile`` early-returns, and the denial is silently
    inert (commons, round 4).
    """

    @staticmethod
    def _run() -> dict:
        proc = subprocess.run(
            [sys.executable, "-c", _NONE_BRANCH_PROBE],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_the_denial_bites(self) -> None:
        """Arming probe: an unguarded inspect.stack() really dies in this world."""
        assert self._run()["denial_bites"] is True

    def test_the_none_branch_is_actually_entered(self) -> None:
        """Arming probe: _find_real_caller returned None, so the branch ran."""
        assert self._run()["caller_is_none"] is True

    def test_the_guard_returns_instead_of_walking(self) -> None:
        """The pin. A regrown inspect.stack() walk raises OSError here."""
        assert self._run()["guard_returns"] is True
