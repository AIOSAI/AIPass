# =================== AIPass ====================
# Name: test_no_cwd_sweep.py
# Description: Every location-inference site survives a deleted working directory
# Version: 1.0.5
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/router_handler.py caller_cwd and every site that infers a location from the cwd."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — the import-time half of a dead cwd, in tests/test_import_dead_cwd.py

import ast
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

import aipass.drone.apps as drone_apps
from aipass.drone.apps import drone
from aipass.drone.apps.handlers import rm_handler, router_handler
from aipass.drone.apps.handlers.broker import daemon
from aipass.drone.apps.handlers.git import lock_handler
from aipass.drone.apps.modules import git_module
from aipass.drone.apps.plugins.devpulse_ops import auth
from aipass.drone.tests import conftest as drone_conftest

# No cwd is the absence of a signal, not an error: the cwd walk is skipped and every other source
# still answers; owner-tier auth alone fails closed. ``caller_cwd()`` is the single reader.


@pytest.fixture()
def no_cwd(monkeypatch):
    """The process has no working directory — the state, not a mock of a guard.

    Patches the read beneath ``caller_cwd``: patching the guard itself stays green for a site that bypasses it.
    """

    def gone():
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(router_handler, "_working_directory", gone)
    yield


@pytest.fixture()
def home_root(tmp_path, monkeypatch):
    """An AIPass home that answers when the cwd cannot."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "AIPASS_REGISTRY.json").write_text('{"branches": []}', encoding="utf-8")
    monkeypatch.setenv("AIPASS_HOME", str(home))
    return home


class TestDroneEntryPointSurvives:
    def test_registry_presence_check_falls_through_to_aipass_home(self, no_cwd, home_root, monkeypatch, capsys):
        """The cwd walk is skipped; the source that never needed a location answers.

        Mutant killed: _cwd_has_registry dropping its AIPASS_HOME fallback (systems saw no registry).
        """
        monkeypatch.setattr("sys.argv", ["drone", "systems"])
        assert drone.main() == 0
        assert "No registry found" not in capsys.readouterr().out

    def test_registry_presence_check_answers_false_rather_than_raising(self, no_cwd, monkeypatch, capsys):
        """Mutant killed: _cwd_has_registry walking a cwd it does not have (a crash, not an answer)."""
        monkeypatch.delenv("AIPASS_HOME", raising=False)
        monkeypatch.setattr("sys.argv", ["drone", "systems"])
        assert drone.main() == 0
        assert "No registry found in current directory tree." in capsys.readouterr().out

    def test_the_seat_inbox_is_unknown_not_a_crash(self, no_cwd, tmp_path, monkeypatch):
        """A seat is inferred from where you stand. Standing nowhere means no seat.

        With no seat the index is handed on as typed; a cwd read past the guard would turn 1 into "oldest".
        Mutant killed (runner): _find_seat_inbox's no-cwd return removed (a traceback, not a token).
        """
        (tmp_path / ".trinity").mkdir()
        (tmp_path / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".ai_mail.local").mkdir()
        (tmp_path / ".ai_mail.local" / "inbox.json").write_text(
            '{"messages": [{"id": "newest"}, {"id": "oldest"}]}', encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        routed = []
        monkeypatch.setattr(drone, "is_module", lambda name: name != "ai_mail")
        monkeypatch.setattr(drone, "branch_exists", lambda target: target == "@ai_mail")
        monkeypatch.setattr(
            drone,
            "route_command",
            lambda *a, **kw: routed.append(kw["args"]) or SimpleNamespace(stdout="", stderr="", exit_code=0),
        )
        monkeypatch.setattr("sys.argv", ["drone", "@ai_mail", "view", "1"])

        assert drone.main() == 0
        assert routed == [["1"]]


class TestTheDeleteLaneSurvives:
    def test_project_root_falls_through_to_aipass_home(self, no_cwd, home_root):
        """Mutant killed: _find_project_root dropping its AIPASS_HOME fallback (no project root allowed)."""
        assert rm_handler.get_allowed_roots()[0] == home_root.resolve()

    def test_project_root_is_unknown_rather_than_a_crash(self, no_cwd, monkeypatch):
        """Mutant killed: _find_project_root walking a cwd it does not have (a crash, not an answer)."""
        monkeypatch.delenv("AIPASS_HOME", raising=False)
        temp_roots = {Path(tempfile.gettempdir()).resolve()}
        if sys.platform != "win32":
            temp_roots.add(Path(os.sep, "tmp").resolve())
        assert set(rm_handler.get_allowed_roots()) == temp_roots

    def test_the_current_branch_is_unknown(self, no_cwd, tmp_path):
        """Mutant killed: _current_branch_root walking a cwd it does not have; no branch is the caller's own."""
        (tmp_path / "somebranch" / ".trinity").mkdir(parents=True)
        blocked, reason = rm_handler.check_carveouts((tmp_path / "somebranch" / "build").resolve(), tmp_path.resolve())
        assert blocked is True
        assert "sibling branch somebranch/" in reason

    def test_an_absolute_path_still_deletes(self, no_cwd, home_root):
        """The recovery command. It names its target absolutely and needs no cwd."""
        target = home_root / "scratch"
        target.mkdir()

        results = rm_handler.safe_delete([str(target)])

        assert results[0][1] is True, results
        assert not target.exists()

    def test_a_relative_path_is_refused_cleanly_not_crashed(self, no_cwd, home_root):
        """A relative path is meaningless without a cwd — a refusal, not a traceback."""
        results = rm_handler.safe_delete(["scratch"])

        assert results[0][1] is False
        assert "current directory" in results[0][2].lower(), results


@pytest.mark.deletable_cwd
class TestTheDeleteLaneSurvivesForReal:
    """The end-to-end case, in a subprocess with a genuinely deleted directory: only that proves the lane."""

    def test_drone_rm_from_a_deleted_directory_reports_instead_of_crashing(self, tmp_path):
        stand_in = tmp_path / "standhere"
        stand_in.mkdir()
        victim = tmp_path / "victim"
        victim.mkdir()

        probe = textwrap.dedent(
            """
            import os, shutil, sys
            here, target = sys.argv[1], sys.argv[2]
            os.chdir(here)
            shutil.rmtree(here)
            from aipass.drone.apps.handlers import rm_handler
            results = rm_handler.safe_delete([target])
            print("RESULT", results[0][1], results[0][2])
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", probe, str(stand_in), str(victim)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(tmp_path),
        )

        assert result.returncode == 0, result.stderr
        assert "RESULT True" in result.stdout, result.stdout
        assert not victim.exists()


class TestTheGitLaneSurvives:
    def test_the_caller_branch_is_unknown_rather_than_a_crash(self, no_cwd, monkeypatch):
        """``drone @git diff`` with no cwd names the missing branch and exits 1, reaching no git.

        Auth is stubbed on the module in sys.modules, where the product resolves it at call time.
        """

        def no_git(*_args, **_kwargs):
            raise AssertionError("the diff lane ran git with no branch detected")

        assert sys.modules[auth.__name__] is auth
        monkeypatch.setattr(auth, "verify_git_access", lambda _cmd: "drone")
        monkeypatch.setattr(git_module.diff_handler, "get_branch_diff", no_git)

        result = git_module.handle_command("diff", [])

        assert result == {
            "stdout": "",
            "stderr": "Cannot detect branch directory from CWD. Run from within src/aipass/<branch>/",
            "exit_code": 1,
        }

    def test_the_repo_root_comes_from_aipass_home_when_there_is_no_cwd(self, no_cwd, home_root):
        """``find_repo_root`` promises a Path, not an Optional — so it must find one."""
        assert lock_handler.find_repo_root() == home_root

    def test_with_no_registry_findable_anywhere_it_still_returns_a_real_directory(self, no_cwd, monkeypatch):
        """The bare-runner world: no registry anywhere, so the marker leg is the one that answers.

        Never assert a registry exists: ``*_REGISTRY.json`` is gitignored, so a clean checkout has none.
        """
        monkeypatch.setattr(router_handler, "_registry_candidates", lambda directory: [])
        monkeypatch.delenv("AIPASS_HOME", raising=False)

        root = lock_handler.find_repo_root()

        assert isinstance(root, Path)
        assert root.is_absolute(), f"a relative answer names nowhere in particular: {root}"
        assert root.is_dir(), f"a lock cannot be written into {root}"
        assert Path(lock_handler.__file__).resolve().is_relative_to(root), (
            f"{root} does not contain the package that answered from it"
        )
        # "Contains the package" alone passes on the last-resort return; a bare checkout still has .git.
        # Mutant killed: find_repo_root skipping its marker walk (the last resort answered).
        assert (root / ".git").exists(), f"{root} carries no .git — a lock would land in a subdirectory"


class TestTheAuthGateFailsClosed:
    """The one site that must NOT answer "unknown": no identity is a stated refusal, as with no passport."""

    def test_no_cwd_is_a_refusal_that_says_why(self, no_cwd):
        """Mutant killed: _resolve_caller walking a cwd it does not have (a traceback, not a refusal)."""
        with pytest.raises(PermissionError) as excinfo:
            auth.verify_git_access("status")

        assert "no current directory" in str(excinfo.value).lower(), str(excinfo.value)


class TestTheBrokerSurvives:
    def test_broker_project_root_falls_through_to_aipass_home(self, no_cwd, home_root):
        """Mutant killed: the daemon's _find_project_root dropping its AIPASS_HOME fallback."""
        assert daemon.BrokerDaemon().socket_path.is_relative_to(home_root.resolve())

    def test_broker_project_root_is_unknown_rather_than_a_crash(self, no_cwd, monkeypatch):
        """Mutant killed: the daemon's _find_project_root walking a cwd it does not have."""
        monkeypatch.delenv("AIPASS_HOME", raising=False)
        assert daemon.BrokerDaemon().socket_path.parent == Path(tempfile.gettempdir())


class TestTheSweepIsComplete:
    """A prose count of these sites kept coming in low, so the count is a test.

    The ban parses the AST, so it convicts the call and not a docstring that names it.
    """

    @staticmethod
    def _bare_cwd_reads(tree: ast.Module) -> list[int]:
        """Lines calling ``Path.cwd()``, ``os.getcwd()``, or a bare ``getcwd()``."""
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if (func.value.id, func.attr) in {("Path", "cwd"), ("os", "getcwd")}:
                    found.append(node.lineno)
            elif isinstance(func, ast.Name) and func.id == "getcwd":
                found.append(node.lineno)
        return found

    def test_no_bare_cwd_read_survives_outside_caller_cwd(self):
        root = Path(drone_apps.__file__).parent
        offenders = []
        for source in drone_conftest.python_sources(root):
            if source.name == "router_handler.py":
                continue  # caller_cwd() itself — the one sanctioned read
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for lineno in self._bare_cwd_reads(tree):
                offenders.append(f"{source.relative_to(root)}:{lineno}")

        assert offenders == [], "bare working-directory reads outside caller_cwd(): " + ", ".join(offenders)

    def test_the_detector_convicts_each_spelling_it_bans(self):
        """Both directions, because a checker that convicts nothing reads green."""
        assert self._bare_cwd_reads(ast.parse("from pathlib import Path\nhere = Path.cwd()\n"))
        assert self._bare_cwd_reads(ast.parse("import os\nhere = os.getcwd()\n"))
        assert self._bare_cwd_reads(ast.parse("from os import getcwd\nhere = getcwd()\n")), (
            "the bare-import spelling was invisible to the line scan this replaced"
        )

    def test_the_detector_clears_prose_that_names_the_defect(self):
        """The red that changed the instrument, kept as the pin for it."""
        tree = ast.parse('"""ntpath.realpath reads os.getcwd() unconditionally — hence the guard."""\n')
        assert self._bare_cwd_reads(tree) == [], (
            "a docstring explaining the cure is not the defect; convicting it is how cures go unexplained"
        )

    def test_the_sweeps_never_walk_into_a_dropbox_or_an_archive(self, tmp_path):
        """A dropbox and an .archive are sandboxes: nothing in them is swept.

        Mutant: python_sources without the skip goes red (the runner cannot serve conftest).
        """
        (tmp_path / "handlers").mkdir()
        (tmp_path / "handlers" / "real.py").write_text("x = 1\n", encoding="utf-8")
        for sandbox in ("dropbox", ".archive"):
            (tmp_path / "handlers" / sandbox).mkdir()
            (tmp_path / "handlers" / sandbox / "stray.py").write_text("x = 1\n", encoding="utf-8")

        walked = drone_conftest.python_sources(tmp_path)

        assert walked == [tmp_path / "handlers" / "real.py"], walked

    def test_a_sweep_rooted_inside_a_dropbox_still_sees_its_sources(self, tmp_path):
        """The skip judges the parts below the walked root: a project under a dropbox keeps every source.

        Mutant: a whole-path comparison empties the list (held; the runner cannot serve conftest).
        """
        root = tmp_path / "dropbox" / "apps"
        (root / "handlers").mkdir(parents=True)
        (root / "handlers" / "real.py").write_text("x = 1\n", encoding="utf-8")

        assert drone_conftest.python_sources(root) == [root / "handlers" / "real.py"]

    def test_host_platform_answers_what_sys_platform_holds(self):
        """The seam's body is the read it replaced; the collection-hook tests replace the seam."""
        assert drone_conftest.host_platform() == sys.platform


class TestTheWindowsSkipIsNarrow:
    """A skip that fires everywhere reports its own defeat as a pass.

    ``deletable_cwd`` tests delete their own cwd, which Windows forbids; conftest skips them on win32 only.
    """

    MARKED = (
        "tests/test_deletion_log.py::TestRecordFailureIsContained::test_record_deletion_does_not_raise_when_cwd_is_gone"
    )

    def test_a_marked_test_runs_on_every_platform_but_windows(self):
        branch_root = Path(drone_apps.__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, "-m", "pytest", self.MARKED, "-q", "-rs", "--timeout=120", "-p", "no:randomly"],
            cwd=str(branch_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        assert result.returncode == 0, result.stdout + result.stderr
        if sys.platform == "win32":
            assert "1 skipped" in result.stdout, result.stdout
            assert "current directory" in result.stdout, "the skip did not say why"
        else:
            assert "1 passed" in result.stdout, result.stdout
            assert "skipped" not in result.stdout, (
                "a deletable-cwd test was skipped on a platform that can delete its own cwd: " + result.stdout
            )

    def test_the_hook_skips_marked_items_on_windows_and_only_there(self, monkeypatch):
        """The Windows half of the ruling, checked from a machine that is not Windows.

        The subprocess pin sees only this platform; calling the hook directly observes both answers anywhere.
        """

        def one_item():
            recorded = []
            return SimpleNamespace(
                keywords={drone_conftest.DELETABLE_CWD_MARKER: True},
                recorded=recorded,
                add_marker=recorded.append,
            )

        monkeypatch.setattr(drone_conftest, "host_platform", lambda: "win32")
        on_windows = one_item()
        drone_conftest.pytest_collection_modifyitems(None, [on_windows])
        assert on_windows.recorded, "a deletable-cwd test was left to run on Windows"
        assert drone_conftest.WINDOWS_CWD_REASON in str(on_windows.recorded[0])

        monkeypatch.setattr(drone_conftest, "host_platform", lambda: "linux")
        elsewhere = one_item()
        unmarked = SimpleNamespace(keywords={}, recorded=[], add_marker=lambda m: None)
        drone_conftest.pytest_collection_modifyitems(None, [elsewhere, unmarked])
        assert not elsewhere.recorded, "the skip reached a platform that can delete its own cwd"
