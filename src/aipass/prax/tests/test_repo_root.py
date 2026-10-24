# =================== AIPass ====================
# Name: test_repo_root.py
# Description: Repo-Root Resolution Pins
# Version: 1.2.2
# Created: 2026-08-31
# Modified: 2026-10-23
# Category: prax/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.2.0 (2026-10-02): The caller-path guard asked through detect_external_project;
#     the refresh/status lanes read through AIPASS_REGISTRY (prax, leg 5)
#   - v1.0.0 (2026-08-31): Initial creation — @memory's dead-cwd report, plus the
#     second crash site the sweep found in introspection
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - Dead-cwd behaviour is proved in a SUBPROCESS — a test that deletes its own
#     working directory in-process cannot get back
# =============================================

"""Tests for apps/handlers/repo_root.py and the introspection/dashboard modules it guards."""

# Repo-root resolution must never read the process cwd: loggers resolve it at import, so a dead or
# registry-less cwd crashed or misrouted almost every import. A ninth private copy is caught by an AST sweep.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(error_handling) — resolved_file answering the unresolved path on OSError, covered by that row
# seedgo: no-test-needed(error_handling) — find_repo_root walking past an unreadable directory, covered by that row

import ast
import os
import subprocess
import sys
import textwrap
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from unittest.mock import MagicMock

import pytest

from aipass.prax.apps.handlers import repo_root as repo_root_mod
from aipass.prax.apps.handlers.config import load as load_mod
from aipass.prax.apps.handlers.dashboard import refresh as refresh_mod
from aipass.prax.apps.handlers.dashboard import status as status_mod
from aipass.prax.apps.handlers.logging import introspection


def _answer(result) -> str:
    """The last line a probe printed — its answer, not its noise."""
    return result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""


APPS_DIR = Path(repo_root_mod.__file__).resolve().parents[1]
REPO_SRC = str(Path(repo_root_mod.__file__).resolve().parents[5])


# The pinned condition is "os.getcwd() raises", injected rather than built by deleting the directory:
# Windows locks a process's cwd (WinError 32). TestBothConstructionsAgree licenses the substitution.
_INJECT_DEAD_CWD = """
import os as _os


def _no_working_directory(*_args, **_kwargs):
    raise FileNotFoundError(2, "No such file or directory")


_os.getcwd = _no_working_directory
try:
    _os.getcwd()
    print("INVALID-PROBE: the working directory still answers")
    raise SystemExit(3)
except FileNotFoundError:
    pass
"""

# ntpath.realpath calls os.getcwd() first and inspect's getmodule() calls realpath outside a try, so denying
# realpath is the denial Windows meets. It convicts a module-level resolve(), not inspect.stack().
_DENY_REALPATH = (
    _INJECT_DEAD_CWD
    + """
import os.path as _ospath


def _no_realpath(*_args, **_kwargs):
    raise FileNotFoundError(2, "No such file or directory")


_ospath.realpath = _no_realpath
"""
)

# realpath raises, getcwd answers: Windows' shape (ntpath.abspath asks the OS, not os.getcwd). Only this world
# lets inspect.stack() reach its unguarded realpath; a getcwd denial makes inspect bail early and hides it.
_NTPATH_SHAPED = """
import os.path as _ospath


def _no_realpath(*_args, **_kwargs):
    raise FileNotFoundError(2, "No such file or directory")


_ospath.realpath = _no_realpath
"""

# Windows on Linux: ntpath.abspath never calls os.getcwd and realpath does; posixpath routes both through it.
# It reproduces the Windows runner's table, the only way prax can check it (no Windows box here).
_WINDOWS_EMULATED = """
import os as _os
import os.path as _ospath

_OS_LEVEL_CWD = _os.getcwd()
_real_realpath = _ospath.realpath
_real_join = _ospath.join
_real_normpath = _ospath.normpath


def _no_working_directory(*_args, **_kwargs):
    raise FileNotFoundError(2, "No such file or directory")


def _win_abspath(path):
    path = _os.fspath(path)
    if not _ospath.isabs(path):
        path = _real_join(_OS_LEVEL_CWD, path)
    return _real_normpath(path)


def _win_realpath(path, *_args, **_kwargs):
    _os.getcwd()
    return _real_realpath(path, *_args, **_kwargs)


_ospath.abspath = _win_abspath
_ospath.realpath = _win_realpath
_os.getcwd = _no_working_directory
"""

# Measured per platform: one OS's reading is not a property of the interpreter.
EXPECTED_WORLD_VERDICTS = (
    {"getcwd-denied": "DIED", "realpath-denied": "DIED", "ntpath-shaped": "DIED"}
    if os.name == "nt"
    else {"getcwd-denied": "SURVIVED", "realpath-denied": "SURVIVED", "ntpath-shaped": "DIED"}
)

_DELETE_CWD = """
import os as _os, shutil as _shutil, tempfile as _tempfile
_d = _tempfile.mkdtemp()
_os.chdir(_d)
_shutil.rmtree(_d)
try:
    _os.getcwd()
    print("INVALID-PROBE: the working directory still answers")
    raise SystemExit(3)
except OSError:
    pass
"""


# A dev seat has the registry, so the marker walk would succeed; hiding the marker puts every machine
# in CI's registry-less world, where the cwd fallback used to be reached.
_MARKER_ABSENT = """
from aipass.prax.apps.handlers import repo_root as _rr
_rr.REGISTRY_MARKER = "AIPASS_REGISTRY_THAT_CANNOT_EXIST.json"
"""


def _run_without_a_working_directory(body: str, world: str = _INJECT_DEAD_CWD, marker_absent: bool = True):
    """Run a snippet in a process whose working directory cannot be read."""
    script = (
        world
        + textwrap.dedent(
            f"""
        import sys
        sys.path.insert(0, {REPO_SRC!r})
        """
        )
        + (_MARKER_ABSENT if marker_absent else "")
        + textwrap.dedent(body)
    )
    # Fed on stdin, not -c: a `<stdin>` caller is the relative pseudo-filename introspection resolves.
    return subprocess.run(
        [sys.executable, "-"], input=script, capture_output=True, text=True, encoding="utf-8", timeout=120
    )


class TestSourceRoot:
    """The fallback is derived from the FILE, and nothing else.

    Starts are built from tmp_path: a POSIX literal is rooted-but-driveless, so not absolute on Windows.
    """

    def test_the_directory_containing_src_is_the_checkout(self, tmp_path):
        start = tmp_path / "checkout" / "src" / "aipass" / "prax" / "a.py"
        assert repo_root_mod.source_root(start) == tmp_path / "checkout"

    def test_no_src_component_falls_to_the_root(self, tmp_path):
        """Defined, incapable of raising, and absurd enough to fail loudly."""
        start = tmp_path / "nowhere" / "at" / "all" / "a.py"
        assert repo_root_mod.source_root(start) == Path(start.anchor)

    def test_a_drive_qualified_windows_path_walks_to_its_own_checkout(self):
        """The spelling a real Windows caller actually produces."""
        start = PureWindowsPath(r"D:\a\AIPass\AIPass\src\aipass\prax\a.py")
        assert repo_root_mod._walk_to_source_root(start) == PureWindowsPath(r"D:\a\AIPass\AIPass")

    def test_the_src_match_is_exact_case_not_folded(self, tmp_path):
        """A deliberate semantic, pinned because a mutation folding it survived.

        On Linux SRC/ and src/ are different directories; an unrecognised layout takes the loud last resort.
        """
        start = tmp_path / "x" / "SRC" / "aipass" / "prax" / "a.py"
        assert repo_root_mod.source_root(start) == Path(start.anchor)

    def test_a_relative_start_is_refused_not_resolved(self):
        """Resolving it would read the working directory this module exists to avoid."""
        assert repo_root_mod.source_root(Path("relative/a.py")) == repo_root_mod.source_root()

    def test_a_rooted_driveless_start_is_refused_on_windows_spelling(self):
        """The exact shape that made the CI leg red, now stated as the rule.

        A rooted driveless path is not absolute on Windows; pinned so nobody 'fixes' the guard to accept it.
        """
        assert not PureWindowsPath("/x/checkout/src/aipass/prax/a.py").is_absolute()
        assert PurePosixPath("/x/checkout/src/aipass/prax/a.py").is_absolute()


class TestFindRepoRoot:
    """Marker first, source root second, working directory never."""

    def test_the_marker_wins_when_present(self, tmp_path):
        root = tmp_path / "checkout"
        (root / "src" / "aipass" / "prax").mkdir(parents=True)
        (root / repo_root_mod.REGISTRY_MARKER).write_text("{}", encoding="utf-8")
        assert repo_root_mod.find_repo_root(root / "src" / "aipass" / "prax" / "a.py") == root

    def test_a_registry_less_checkout_resolves_to_the_checkout(self, tmp_path):
        """Every clean CI clone: the marker is gitignored, so it is never there."""
        start = tmp_path / "checkout" / "src" / "aipass" / "prax" / "a.py"
        start.parent.mkdir(parents=True)
        assert repo_root_mod.find_repo_root(start) == tmp_path / "checkout"

    def test_a_relative_start_is_refused_not_walked_from_the_cwd(self, tmp_path, monkeypatch):
        """The mutation this kills: accepting a relative start.

        With a live cwd inside another checkout, the walk would return somebody else's repo.
        """
        foreign = tmp_path / "someone_elses_checkout"
        (foreign / "src" / "aipass" / "prax").mkdir(parents=True)
        (foreign / repo_root_mod.REGISTRY_MARKER).write_text("{}", encoding="utf-8")
        monkeypatch.chdir(foreign)

        resolved = repo_root_mod.find_repo_root(Path("src/aipass/prax/a.py"))
        assert resolved not in (Path("."), foreign), (
            f"a relative start was walked from the working directory: {resolved}"
        )
        assert resolved == repo_root_mod.find_repo_root()

    def test_the_fallback_is_announced(self, tmp_path, caplog, monkeypatch):
        """A fallback nobody can see is how the next one survives."""
        monkeypatch.setattr(repo_root_mod, "_ANNOUNCED", set())
        start = tmp_path / "checkout" / "src" / "aipass" / "prax" / "a.py"
        start.parent.mkdir(parents=True)
        with caplog.at_level("WARNING", logger=repo_root_mod.__name__):
            repo_root_mod.find_repo_root(start)
        assert repo_root_mod.REGISTRY_MARKER in caplog.text

    def test_the_announcement_is_once_per_process_not_once_per_call(self, tmp_path, caplog, monkeypatch):
        """A per-call warning would bury CI output: every module reaches this during import."""
        monkeypatch.setattr(repo_root_mod, "_ANNOUNCED", set())
        start = tmp_path / "checkout" / "src" / "aipass" / "prax" / "a.py"
        start.parent.mkdir(parents=True)
        with caplog.at_level("WARNING", logger=repo_root_mod.__name__):
            for _ in range(5):
                repo_root_mod.find_repo_root(start)
        assert caplog.text.count("[repo_root]") == 1

    def test_an_installed_package_falls_back_to_the_anchor_root_without_a_warning(self, tmp_path, caplog, monkeypatch):
        """site-packages has no registry and no src/: the anchor root is the designed answer, logged as a note."""
        monkeypatch.setattr(repo_root_mod, "_ANNOUNCED", set())
        start = tmp_path / "site-packages" / "aipass" / "prax" / "a.py"
        start.parent.mkdir(parents=True)
        with caplog.at_level("INFO", logger=repo_root_mod.__name__):
            resolved = repo_root_mod.find_repo_root(start)
        assert resolved == Path(start.anchor)
        levels = [record.levelname for record in caplog.records if "[repo_root]" in record.getMessage()]
        assert levels == ["INFO"], levels
        assert "installed package" in caplog.text

    def test_this_module_imports_nothing_from_prax(self):
        """Imports nothing from aipass: it runs inside the construction of prax's own logger."""
        tree = ast.parse(Path(repo_root_mod.__file__).read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert not [name for name in imported if name.startswith("aipass")], imported


WORLDS = [
    pytest.param(_INJECT_DEAD_CWD, id="getcwd-denied"),
    pytest.param(_DENY_REALPATH, id="realpath-denied"),
]

# Kept apart from WORLDS: the import pins must never widen onto a world where getcwd works.
ATTRIBUTION_WORLDS = WORLDS + [pytest.param(_NTPATH_SHAPED, id="ntpath-shaped")]


@pytest.mark.parametrize("world", WORLDS)
class TestDeadCwd:
    """The working directory cannot be read and something imports.

    realpath-denied is the same denial reaching the call Windows makes; it is red on Linux pre-cure.
    """

    def test_the_resolver_answers_without_a_working_directory(self, world):
        result = _run_without_a_working_directory(
            world=world,
            body="""
            from aipass.prax.apps.handlers import repo_root
            from pathlib import Path
            print("ANSWER", repo_root.find_repo_root(Path("/no/such/src/aipass/x/a.py")))
            """,
        )
        assert result.returncode == 0, result.stderr
        assert "ANSWER" in result.stdout, result.stderr

    def test_the_logger_can_be_built_without_a_working_directory(self, world):
        """The end-to-end case: a `<stdin>` caller makes introspection resolve a relative path first."""
        result = _run_without_a_working_directory(
            world=world,
            body="""
            from aipass.prax.apps.modules.logger import get_system_logger
            print("LOGGER", get_system_logger().name)
            """,
        )
        assert result.returncode == 0, result.stderr
        assert "LOGGER" in result.stdout, result.stderr

    def test_the_fallback_path_is_the_one_being_exercised(self, world):
        """Positive control on the WORLD, not the claim: the answer is the source-root fallback.

        It cannot fail against the pre-fix code on a machine with a registry (the old walk hardcoded its marker).
        """
        result = _run_without_a_working_directory(
            world=world,
            body="""
            from aipass.prax.apps.handlers import repo_root
            from pathlib import Path
            print("ANSWER", repo_root.find_repo_root(Path(repo_root.__file__)))
            """,
        )
        assert result.returncode == 0, result.stderr
        assert _answer(result).split(" ", 1)[1] == str(repo_root_mod.source_root())

    def test_the_system_logs_dir_resolves_without_a_working_directory(self, world):
        result = _run_without_a_working_directory(
            world=world,
            body="""
            from aipass.prax.apps.handlers.config.load import get_system_logs_dir
            print("LOGS", get_system_logs_dir())
            """,
        )
        assert result.returncode == 0, result.stderr
        assert "LOGS" in result.stdout, result.stderr


def _a_project_around(root: Path, monkeypatch) -> None:
    """Make ``root`` an external project an unguarded resolve would find."""
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    monkeypatch.setenv("AIPASS_CALLER_CWD", str(root))
    monkeypatch.setattr(introspection, "logger", MagicMock())


class TestCallerPathResolution:
    """The caller-path guard in introspection, the second crash site.

    Asked through detect_external_project: a refused caller is None, a caller let through is the project.
    """

    def test_a_pseudo_filename_is_not_a_path(self, tmp_path, monkeypatch):
        _a_project_around(tmp_path, monkeypatch)
        monkeypatch.chdir(tmp_path)

        assert introspection.detect_external_project("<stdin>") is None
        assert introspection.detect_external_project("<string>") is None

    def test_a_relative_caller_is_refused_even_when_the_cwd_is_alive(self, tmp_path, monkeypatch):
        """With a live cwd a relative caller resolves to the wrong branch, silently.

        Dropping the is_absolute guard survives the dead-cwd pin and is killed only here.
        """
        _a_project_around(tmp_path, monkeypatch)
        branch_dir = tmp_path / "src" / "aipass" / "someoneelse" / "apps"
        branch_dir.mkdir(parents=True)
        (branch_dir / "mod.py").write_text("", encoding="utf-8")
        monkeypatch.chdir(branch_dir)

        assert introspection.detect_external_project("mod.py") is None

    def test_an_absolute_caller_still_resolves(self, tmp_path, monkeypatch):
        _a_project_around(tmp_path, monkeypatch)
        real = tmp_path / "mod.py"
        real.write_text("", encoding="utf-8")

        found = introspection.detect_external_project(str(real))
        assert found is not None
        assert found[1] == real.resolve().parent

    def test_an_unresolvable_absolute_path_is_an_answer_not_a_crash(self, monkeypatch, tmp_path):
        """Branch detection is a routing hint: not knowing the caller must never break its import."""
        _a_project_around(tmp_path, monkeypatch)

        def boom(self, *_args, **_kwargs):
            raise OSError("no cwd")

        monkeypatch.setattr(Path, "resolve", boom)
        unresolvable = str(tmp_path / "unresolvable.py")
        assert introspection.detect_external_project(unresolvable) is None


class TestBothConstructionsAgree:
    """The licence for substituting the injected world for the deleted one.

    On POSIX both worlds are buildable and must give the identical answer; Windows locks the cwd, so the
    deletion world cannot be built there.
    """

    PROBE = """
        from aipass.prax.apps.handlers import repo_root
        from pathlib import Path
        print("ANSWER", repo_root.find_repo_root(Path("/no/such/src/aipass/x/a.py")))
        """

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="the deleted-cwd world is unbuildable on Windows — WinError 32, the OS locks it",
    )
    def test_the_injected_world_and_the_deleted_world_give_the_same_answer(self):
        injected = _run_without_a_working_directory(self.PROBE, world=_INJECT_DEAD_CWD)
        deleted = _run_without_a_working_directory(self.PROBE, world=_DELETE_CWD)

        assert injected.returncode == 0, injected.stderr
        assert deleted.returncode == 0, deleted.stderr
        assert _answer(injected) == _answer(deleted), (
            f"injected={_answer(injected)!r} deleted={_answer(deleted)!r} — the stand-in no longer stands in"
        )

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="the deleted-cwd world is unbuildable on Windows — WinError 32, the OS locks it",
    )
    def test_both_worlds_really_do_break_the_working_directory(self):
        """Positive control on the WORLDS: a world that broke nothing cannot pass as dead-cwd."""
        probe = """
            import os
            try:
                os.getcwd()
                print("ALIVE")
            except OSError:
                print("BROKEN")
            """
        for name, world in (("injected", _INJECT_DEAD_CWD), ("deleted", _DELETE_CWD)):
            result = _run_without_a_working_directory(probe, world=world)
            assert "BROKEN" in result.stdout, f"{name}: {result.stdout!r} {result.stderr!r}"


# The one sanctioned cwd read: `dashboard refresh` with no argument means "the branch I stand in", and
# `_caller_dir` also tells `refresh @branch` the caller's project registry. One read, one file.
CWD_ALLOWLIST = {"apps/modules/dashboard.py"}


def _module_key(relative: PurePath) -> str:
    """The one spelling a module is named by, on every platform.

    Normalised at the boundary: relative_to gives OS separators, which missed the forward-slash allowlist.
    """
    return relative.as_posix()


# Not live code (dropbox hand-offs, .archive) or no source. Matched relative to the walk root, so a root
# inside a directory of one of these names is still walked.
_NOT_LIVE = {"dropbox", ".archive", "__pycache__"}


def _not_live(path: Path, root: Path) -> bool:
    """True when a directory between root and path is one the sweeps skip by name."""
    return bool(_NOT_LIVE.intersection(path.relative_to(root).parts))


def _modules_reading_the_cwd(root: Path) -> dict:
    """AST scan: which files call Path.cwd() or os.getcwd()?"""
    found = {}
    for path in sorted(root.rglob("*.py")):
        if _not_live(path, root):
            continue
        # Never skipped: an unparseable module is a hole, and a sweep that skips holes reports green.
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            raise AssertionError(f"{path} could not be parsed, so this sweep cannot see it: {exc}") from exc
        lines = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            owner = node.func.value
            name = getattr(owner, "id", None)
            if (name == "Path" and node.func.attr == "cwd") or (name == "os" and node.func.attr == "getcwd"):
                lines.append(node.lineno)
        if lines:
            found[_module_key(path.relative_to(root.parent))] = lines
    return found


class TestNoPrivateCwdFallback:
    """Eight identical copies is how this survived. The ninth is a red test."""

    def test_no_module_outside_the_allowlist_reads_the_working_directory(self):
        offenders = {
            module: lines for module, lines in _modules_reading_the_cwd(APPS_DIR).items() if module not in CWD_ALLOWLIST
        }
        assert offenders == {}, (
            "these modules resolve against the process working directory — derive "
            f"from __file__ via handlers/repo_root.py instead: {offenders}"
        )

    def test_the_sweep_can_actually_see_a_violation(self, tmp_path):
        """Positive control: a sweep that looks nowhere reports the same green as a clean tree."""
        planted = tmp_path / "apps" / "planted.py"
        planted.parent.mkdir(parents=True)
        planted.write_text("from pathlib import Path\n\n\ndef f():\n    return Path.cwd()\n", encoding="utf-8")
        assert _modules_reading_the_cwd(tmp_path / "apps")

    def test_the_sweep_skips_not_live_trees_by_name_under_its_own_root(self, tmp_path):
        """dropbox and .archive under the walk root are not live code and are skipped.

        The root itself sits inside a directory named dropbox: an absolute-path match would skip the whole tree.
        """
        root = tmp_path / "dropbox" / "apps"
        body = "from pathlib import Path\n\n\ndef f():\n    return Path.cwd()\n"
        for planted in (root / "live.py", root / "dropbox" / "handed.py", root / ".archive" / "old.py"):
            planted.parent.mkdir(parents=True, exist_ok=True)
            planted.write_text(body, encoding="utf-8")
        assert set(_modules_reading_the_cwd(root)) == {_module_key(PurePath("apps", "live.py"))}

    def test_the_allowlist_matches_a_windows_spelled_key(self):
        """The allowlist matches a Windows-spelled key (relative_to gives backslash separators there)."""
        assert _module_key(PureWindowsPath(r"apps\modules\dashboard.py")) in CWD_ALLOWLIST
        assert _module_key(PurePosixPath("apps/modules/dashboard.py")) in CWD_ALLOWLIST

    def test_the_allowlist_names_only_files_that_exist(self):
        """An allowlist entry for a deleted file is a hole nobody can see."""
        assert len(CWD_ALLOWLIST) == 1, (
            f"the allowlist holds {len(CWD_ALLOWLIST)} entries, not the 1 this pin was written "
            "against — an emptied allowlist sends the loop below through zero iterations and "
            f"reports green having checked nothing: {sorted(CWD_ALLOWLIST)}"
        )
        for entry in CWD_ALLOWLIST:
            assert (APPS_DIR.parent / entry).exists(), entry


class TestEveryLaneUsesTheSharedResolver:
    """Structural: no lane keeps a private walk.

    Name-based, so a rename defeats it, but a renamed walk ending at the cwd is caught by the cwd sweep.
    Matching the marker string is wrong: many modules legitimately read AIPASS_REGISTRY.json.
    """

    def test_every_find_repo_root_delegates_to_the_shared_resolver(self):
        private = {}
        for path in sorted(APPS_DIR.rglob("*.py")):
            if _not_live(path, APPS_DIR):
                continue
            if path == Path(repo_root_mod.__file__).resolve():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name != "_find_repo_root":
                    continue
                delegates = any(
                    isinstance(inner, ast.Call)
                    and getattr(inner.func, "id", getattr(inner.func, "attr", None)) == "find_repo_root"
                    for inner in ast.walk(node)
                )
                if not delegates:
                    private.setdefault(_module_key(path.relative_to(APPS_DIR.parent)), []).append(node.lineno)
        assert private == {}, (
            f"these modules walk for the repo root themselves instead of calling handlers/repo_root.py: {private}"
        )

    def test_the_delegation_sweep_can_actually_see_a_violation(self, tmp_path):
        """Positive control: a sweep that looks nowhere reports the same green."""
        planted = tmp_path / "planted.py"
        planted.write_text(
            "from pathlib import Path\n\n\ndef _find_repo_root():\n    return Path.cwd()\n", encoding="utf-8"
        )
        tree = ast.parse(planted.read_text(encoding="utf-8"))
        offenders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_find_repo_root"
            and not any(
                isinstance(inner, ast.Call)
                and getattr(inner.func, "id", getattr(inner.func, "attr", None)) == "find_repo_root"
                for inner in ast.walk(node)
            )
        ]
        assert offenders == [4], "the sweep would not have seen the planted private walk on its line"

    def test_the_lanes_agree_with_the_shared_answer(self):
        """Behavioural, not just structural: same question, one answer."""
        expected = repo_root_mod.find_repo_root()
        # load is asked by name: its one public reader mkdirs in the live system_logs outside pytest.
        assert load_mod._find_repo_root() == expected
        assert refresh_mod.AIPASS_REGISTRY == expected / "AIPASS_REGISTRY.json"
        assert status_mod.AIPASS_REGISTRY == expected / "AIPASS_REGISTRY.json"


def _inspect_stack_calls(tree: ast.AST) -> list:
    """Every ``inspect.stack()`` CALL in a parsed module, by line number.

    A call, never a spelling: the guard's docstring names it while explaining the ban.
    """
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "stack"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "inspect"
    )


def _docstrings(tree: ast.AST) -> list:
    """Every docstring in a parsed module — module, class and function."""
    return [
        ast.get_docstring(node)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and ast.get_docstring(node)
    ]


def _tree_modules() -> list:
    """Every live module under apps/, excluding dropbox, archives and bytecode."""
    return [path for path in sorted(APPS_DIR.rglob("*.py")) if not _not_live(path, APPS_DIR)]


class TestNothingCallsInspectStack:
    """`inspect.stack()` is banned across apps/, and the ban is a CALL match.

    Structural because no import-shaped pin reaches the guard's `caller_file is None` branch. On Windows
    inspect.stack() reaches getmodule()'s unguarded os.path.realpath, which calls os.getcwd() first.
    inspect.currentframe() stays legal: it touches no filesystem.
    """

    def test_no_module_under_apps_calls_inspect_stack(self):
        offenders = {}
        for path in _tree_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            lines = _inspect_stack_calls(tree)
            if lines:
                offenders[_module_key(path.relative_to(APPS_DIR.parent))] = lines
        assert offenders == {}, (
            "inspect.stack() needs a readable working directory on Windows and dies at import "
            f"in a process that has none. Use sys._getframe(n).f_code.co_filename: {offenders}"
        )

    def test_the_walk_actually_parsed_something(self):
        """Negative control for the sweep: a blinded walk reads clean too.

        The expected count is derived fresh, not via _tree_modules(), so one silently dropped file fails.
        """
        modules = _tree_modules()
        expected = sum(
            1 for path in APPS_DIR.rglob("*.py") if ".archive" not in path.parts and "__pycache__" not in path.parts
        )
        assert expected > 50, (
            f"a fresh scan of apps/ found only {expected} modules — the tree itself is not "
            "there, so no walk over it could prove anything"
        )
        assert len(modules) == expected, (
            f"the apps/ walk found {len(modules)} modules but a fresh scan of the same tree "
            f"counts {expected} — the sweep above is silently dropping at least one file, and "
            "its assertion would pass clean on whatever it dropped"
        )

    def test_the_matcher_convicts_a_planted_call_at_the_right_line(self, tmp_path):
        """Positive control, through the REAL matcher rather than a copy of it."""
        planted = tmp_path / "planted.py"
        planted.write_text("import inspect\n\n\ndef f():\n    return inspect.stack()[1]\n", encoding="utf-8")
        assert _inspect_stack_calls(ast.parse(planted.read_text(encoding="utf-8"))) == [5]

    def test_the_matcher_does_not_convict_the_docstring_that_explains_the_ban(self):
        """The guard's docstring says `inspect.stack()` and must stay legal.

        The fixture is json_service's real docstrings re-emitted as literals: regrowing a stack walk cannot
        touch this control, and it expires if the explanation is deleted.
        """
        guard = APPS_DIR / "handlers" / "json" / "json_service.py"
        tree = ast.parse(guard.read_text(encoding="utf-8"))
        mentions = [text for text in _docstrings(tree) if "inspect.stack()" in text]
        assert mentions, (
            "json_service no longer explains why it does not use inspect.stack() — if the "
            "explanation was removed to satisfy a checker, the checker is the defect"
        )
        prose_only = "\n".join(repr(text) for text in mentions)
        assert _inspect_stack_calls(ast.parse(prose_only)) == []

    @pytest.mark.parametrize(
        "source",
        [
            pytest.param("import numpy\n\nx = numpy.stack([1, 2])\n", id="numpy.stack"),
            pytest.param("import traceback\n\nx = traceback.stack()\n", id="traceback.stack"),
            pytest.param("x = self.stack()\n", id="self.stack"),
            pytest.param("import inspect\n\nx = inspect.currentframe()\n", id="inspect.currentframe"),
        ],
    )
    def test_the_matcher_clears_things_that_only_look_like_it(self, source):
        """Somebody else's `.stack` is not this defect; convicting it teaches branches to route around it."""
        assert _inspect_stack_calls(ast.parse(source)) == []


class TestCallerAttributionWithoutAWorkingDirectory:
    """The two `inspect.stack()` sites cured, pinned by BEHAVIOUR: neither crashed on Linux."""

    def test_the_ntpath_shaped_world_actually_kills_a_stack_walk(self):
        """Negative control FOR the positive controls: is each world hostile?

        On POSIX only the ntpath-shaped world kills a bare inspect.stack(); without this control the pins
        below would pass in two of three worlds for a reason unrelated to their claim.
        """
        verdicts = {}
        for world, name in (
            (_INJECT_DEAD_CWD, "getcwd-denied"),
            (_DENY_REALPATH, "realpath-denied"),
            (_NTPATH_SHAPED, "ntpath-shaped"),
        ):
            probe = subprocess.run(
                [sys.executable, "-"],
                input=world
                + textwrap.dedent(
                    """
                    import inspect

                    try:
                        inspect.stack()
                        print("SURVIVED")
                    except BaseException:
                        print("DIED")
                    """
                ),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
            verdicts[name] = probe.stdout.strip()

        assert verdicts == EXPECTED_WORLD_VERDICTS, (
            f"the worlds no longer bite the way {os.name} was measured to bite. Expected "
            f"{EXPECTED_WORLD_VERDICTS}, got {verdicts}. If the new reading is real, re-derive the "
            "table from measurement rather than relaxing the assertion — this control exists to "
            "refuse a platform's expectation being carried onto a platform where it is false."
        )

    @pytest.mark.parametrize("world", ATTRIBUTION_WORLDS)
    def test_the_log_dir_resolver_names_its_caller_without_a_cwd(self, world):
        """config/load.py's `get_module_logs_dir()` with no module_name.

        Unguarded, it raises from the logging path exactly when logging is all that could explain why.
        """
        result = _run_without_a_working_directory(
            """
            import os
            import tempfile

            os.environ.setdefault("AIPASS_TEST_LOG_DIR", tempfile.mkdtemp(prefix="prax_probe_logs_"))
            from aipass.prax.apps.handlers.config.load import get_module_logs_dir

            print("LOGDIR", get_module_logs_dir().name)
            """,
            world=world,
        )
        assert result.returncode == 0, (
            "get_module_logs_dir() could not name its caller without a working directory.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        # The point is that a name was derived at all, from a frame rather than from the filesystem.
        assert "LOGDIR " in result.stdout, f"no directory came back: {result.stdout}"

    @pytest.mark.parametrize("world", ATTRIBUTION_WORLDS)
    def test_the_operations_log_still_attributes_its_caller(self, world):
        """json_handler's `_get_caller_module_name`.

        The caller is a real file, because "unknown" is correct for a `<stdin>` caller; the probe still runs
        from stdin so that frame keeps inspect reaching the unguarded realpath (on-disk-only stacks go inert).
        """
        result = _run_without_a_working_directory(
            """
            import sys
            import tempfile
            from pathlib import Path

            CALLER_SOURCE = [
                "from aipass.prax import json_handler",
                "",
                "",
                "def stands_in_for_log_operation():",
                "    return json_handler._get_caller_module_name()",
                "",
                "",
                "def ask():",
                "    # Two levels: _get_caller_module_name skips [0]=itself and",
                "    # [1]=log_operation to reach [2], the real caller.",
                "    return stands_in_for_log_operation()",
            ]

            caller_dir = Path(tempfile.mkdtemp(prefix="prax_caller_"))
            (caller_dir / "a_real_caller.py").write_text(chr(10).join(CALLER_SOURCE), encoding="utf-8")
            sys.path.insert(0, str(caller_dir))

            import a_real_caller

            print("CALLER", a_real_caller.ask())
            """,
            world=world,
        )
        assert result.returncode == 0, (
            f"importing json_handler died without a working directory.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "CALLER a_real_caller" in result.stdout, (
            "the caller was not attributed to the real file that asked — either the frame read "
            f"needed a working directory and threw the answer away, or it named the wrong "
            f"frame.\nstdout: {result.stdout}"
        )


class TestTheFenceSurvivesADeadWorkingDirectory:
    """The v2 fence, from its kin seat, in a process whose cwd was removed.

    The fence resolves frame paths through realpath, which reads os.getcwd first on Windows. The cwd is
    denied by injection: Windows holds a process's cwd open, so deleting it fails there.
    """

    def test_the_kin_probe_is_allowed_with_its_cwd_gone_and_realpath_denied(self):
        """Arming probe first: the denial bites in this child, so the claim is about it."""
        probe = Path(__file__).resolve().parent / "support_fence.py"
        script = _DENY_REALPATH + textwrap.dedent(
            f"""
                import os, runpy, sys
                sys.path.insert(0, {REPO_SRC!r})
                try:
                    os.path.realpath("x")
                    print("ARM INERT")
                except OSError:
                    print("ARM BITES")
                sys.argv = ["probe", "pkg"]
                runpy.run_path({str(probe)!r}, run_name="__main__")
                """
        )
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, encoding="utf-8", timeout=120
        )
        assert "ARM BITES" in result.stdout, f"stdout: {result.stdout}\nstderr: {result.stderr}"
        assert result.stdout.strip().splitlines()[-1] == "ALLOWED", f"stdout: {result.stdout}\nstderr: {result.stderr}"


# Windows-reserved in a path component, checked everywhere: Linux happily creates a `<stdin>` directory.
_WINDOWS_RESERVED_CHARS = set('<>:"|?*')


class TestACallerNameIsNotAlwaysAModuleName:
    """A frame's co_filename is not always a file, and never automatically a name.

    get_module_logs_dir() mkdirs its caller's module name; from a pseudo-frame (`<stdin>`) that name holds
    characters Windows reserves. A pseudo-frame gets the same answer as no caller at all.
    """

    def test_the_log_dir_from_a_pseudo_frame_is_creatable_on_every_platform(self):
        """The claim the Windows runner actually made, checkable here."""
        result = _run_without_a_working_directory(
            """
            import os
            import tempfile

            os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="prax_probe_logs_")
            from aipass.prax.apps.handlers.config.load import get_module_logs_dir

            print("LOGDIR", get_module_logs_dir().name)
            """,
            world=_NTPATH_SHAPED,
        )
        assert result.returncode == 0, f"probe died: {result.stdout}\n{result.stderr}"
        name = _answer(result).split("LOGDIR ", 1)[1]
        offending = sorted(_WINDOWS_RESERVED_CHARS & set(name))
        assert not offending, (
            f"get_module_logs_dir() derived the directory name {name!r} from a pseudo-frame and "
            f"created it. Windows refuses {offending} in a path component, so this raises there — "
            "from the logging path. A frame with no file behind it has no module name to give."
        )

    def test_the_operations_log_does_not_attribute_to_a_pseudo_frame(self):
        """json_handler reads the same co_filename; attributing work to `<stdin>` is false."""
        result = _run_without_a_working_directory(
            """
            from aipass.prax import json_handler


            def stands_in_for_log_operation():
                return json_handler._get_caller_module_name()


            def the_actual_caller():
                return stands_in_for_log_operation()


            print("CALLER", the_actual_caller())
            """,
            world=_NTPATH_SHAPED,
        )
        assert result.returncode == 0, f"probe died: {result.stdout}\n{result.stderr}"
        name = _answer(result).split("CALLER ", 1)[1]
        assert not (_WINDOWS_RESERVED_CHARS & set(name)), (
            f"the operations log attributed an entry to {name!r} — a pseudo-frame is not a module, "
            "and 'unknown' is the honest answer where there is nobody to name"
        )

    @pytest.mark.skipif(os.name == "nt", reason="on Windows this world IS the platform, not an emulation")
    def test_the_windows_emulation_reproduces_the_measured_windows_table(self):
        """The emulation is only worth having if it reads like the real Windows runner (all three die)."""
        verdicts = {}
        for world, name in (
            (_INJECT_DEAD_CWD, "getcwd-denied"),
            (_DENY_REALPATH, "realpath-denied"),
            (_NTPATH_SHAPED, "ntpath-shaped"),
        ):
            # The emulation goes first: it captures the real cwd before any world takes getcwd away.
            probe = subprocess.run(
                [sys.executable, "-"],
                input=_WINDOWS_EMULATED
                + world
                + textwrap.dedent(
                    """
                    import inspect

                    try:
                        inspect.stack()
                        print("SURVIVED")
                    except BaseException:
                        print("DIED")
                    """
                ),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
            verdicts[name] = _answer(probe)

        assert verdicts == {
            "getcwd-denied": "DIED",
            "realpath-denied": "DIED",
            "ntpath-shaped": "DIED",
        }, f"the Windows emulation does not read like the Windows runner did: {verdicts}"
