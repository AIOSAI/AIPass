# =================== AIPass ====================
# Name: test_no_cwd_sweep.py
# Description: Every location-inference site survives a deleted working directory
# Version: 1.0.5
# Created: 2026-08-31
# Modified: 2026-09-29
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

# No location is not a failure — pinned at every site that infers one.
#
# THE SPECIES. ``Path.cwd()`` raises ENOENT the moment the directory it names is
# gone. Session 68 fixed that in the deletion RECORD and session 69 fixed it on
# the ROUTING path, and both times the fix landed on the sites already in hand
# rather than on every site in the tree. @trigger reproduced the leftover live —
# ``drone rm`` from a deleted directory, exit 1, ``FileNotFoundError`` at
# ``rm_handler.py:37`` — and named it as the pattern rather than the incident: a
# fix that lands on some of N identical paths. This file is the N.
#
# It is also the recovery case, which is what makes it more than tidiness. The
# first ``drone rm`` succeeds and deletes the directory the caller stands in; the
# SECOND command — the one a person runs to clean up after — is the one that
# crashed. Fixing the crash in session 68 is what put a live process here to run
# it.
#
# THE RULE, identical at every site: a walk that infers something from where the
# caller STANDS has nothing to read when the caller stands nowhere. That is the
# absence of a signal, said out loud at INFO, not an error — so the walk is
# SKIPPED and every other source still answers. Sites that can honestly return
# "unknown" do. The one gate that cannot — owner-tier auth — fails CLOSED and
# says why.
#
# ``caller_cwd()`` in ``router_handler`` is the single reader. A tenth private
# copy of ``try: Path.cwd() except OSError: None`` would be this file's own
# lesson repeated.


@pytest.fixture()
def no_cwd(monkeypatch):
    """The process has no working directory — the state, not a mock of a guard.

    Patches the raw read BENEATH ``caller_cwd`` rather than ``caller_cwd`` on
    purpose: before the sweep, nine sites never went through ``caller_cwd`` at
    all, so patching the guard would have made this file green against unfixed
    code. A site that bypasses the guard with its own ``Path.cwd()`` is caught
    by TestTheSweepIsComplete below, which bans the bare read.
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


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------


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

        Through `drone @ai_mail view 1`: with no seat the index is handed on as
        typed. The seat built under the chdir would turn 1 into "oldest" for a
        site that read the cwd past the guard. Mutant killed (runner):
        _find_seat_inbox's no-cwd return removed (a traceback, not a token).
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


# ---------------------------------------------------------------------------
# The delete lane — the one @trigger reproduced
# ---------------------------------------------------------------------------


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
    """The end-to-end case, in a subprocess with a genuinely deleted directory.

    @trigger ran exactly this and got exit 1 with a traceback. Patched fixtures
    prove the guards; only a real deleted directory proves the lane.
    """

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


# ---------------------------------------------------------------------------
# The git lane
# ---------------------------------------------------------------------------


class TestTheGitLaneSurvives:
    def test_the_caller_branch_is_unknown_rather_than_a_crash(self, no_cwd, monkeypatch):
        """``drone @git diff`` with no cwd names the missing branch and exits 1, reaching no git.

        Through the command, not the private detector. Auth is stubbed where the
        product resolves it at call time (the module in sys.modules), and the
        diff handler fails loudly if the lane ever got past detection.
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
        """``find_repo_root`` promises a Path, not an Optional — so it must find one.

        With no cwd both the walk and the toplevel-query fallback lose their
        starting point, so the answer comes from the sources that never needed
        one. AIPASS_HOME is the first of them, and it is checkable against a
        stand-in rather than against this machine.
        """
        assert lock_handler.find_repo_root() == home_root

    def test_with_no_registry_findable_anywhere_it_still_returns_a_real_directory(self, no_cwd, monkeypatch):
        """The bare-runner world, reproduced — and the assertion this file got wrong.

        The first cut asserted ``list(root.glob("*_REGISTRY.json"))`` — "the
        answer is a project root". That reads the MACHINE. ``*_REGISTRY.json``
        is gitignored and machine-local, so a clean checkout has none, and it
        red on CI with "/home/runner/work/AIPass/AIPass is not a project root"
        — which was the honest answer to a question nobody should have asked.
        The half-present world this file's own sweep was written about, committed
        in the one test the sweep added. @devpulse caught it on PR#750.

        The registry walk is switched off here rather than assumed absent, so
        the marker leg — the only leg a bare runner reaches — actually executes.

        WHAT IS DURABLE, and true in both worlds: with no cwd the answer is a
        real absolute directory that CONTAINS this package. Never a relative
        sentinel, never the deleted directory, never a raise. Whether that
        directory happens to hold a registry is a fact about the checkout, not
        about the function.
        """
        # Switched off at registries_in's one listing, the read every registry walk shares.
        monkeypatch.setattr(router_handler, "_registry_candidates", lambda directory: [])
        monkeypatch.delenv("AIPASS_HOME", raising=False)

        root = lock_handler.find_repo_root()

        assert isinstance(root, Path)
        assert root.is_absolute(), f"a relative answer names nowhere in particular: {root}"
        assert root.is_dir(), f"a lock cannot be written into {root}"
        assert Path(lock_handler.__file__).resolve().is_relative_to(root), (
            f"{root} does not contain the package that answered from it"
        )
        # "Contains the package" alone is too weak — apps/handlers/git/ satisfies
        # it, and that is the last-resort return. A project root is a directory
        # that DECLARES itself one, and a bare checkout still has .git.
        # Mutant killed: find_repo_root skipping its marker walk (the last resort answered).
        assert (root / ".git").exists(), f"{root} carries no .git — a lock would land in a subdirectory"


class TestTheAuthGateFailsClosed:
    """The one site that must NOT answer "unknown".

    Every other site here infers a convenience. This one decides whether a
    caller may write to the repository, and "I could not tell who you are" is a
    refusal — the same answer it already gives when the walk finds no passport.
    What changes is that it arrives as a stated refusal instead of an ENOENT
    traceback from inside a credential check.
    """

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
    """The count is the finding — three times a list of these sites came in low.

    Session 69 reported two unguarded reads where there were three. @trigger
    corrected "exactly one in the whole tree" to nine, and their nine was itself
    short of the ten actually there (``broker/daemon.py`` and
    ``git/lock_handler.py`` were not on their list). A prose count is what keeps
    being wrong, so the count is a test.

    THE INSTRUMENT CHANGED 2026-08-31, and the reason is worth keeping. This
    was a line scan that stripped ``#`` comments and matched the text
    ``Path.cwd()`` / ``os.getcwd()``. It went red on the Windows round-4 build
    against two DOCSTRINGS — prose in ``handlers/__init__.py`` and
    ``handlers/module_root.py`` explaining that ``ntpath.realpath`` reads
    ``os.getcwd()`` unconditionally, which is why those files were cured. A
    string ban convicts the explanation along with the defect, which is how a
    cure ends up undocumented. It parses now, so the ban is on the CALL.

    The parse also closed a hole the text match had: ``from os import getcwd``
    followed by a bare ``getcwd()`` was invisible to it, and is not now.
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
        """A dropbox and an .archive are sandboxes: nothing in them is swept (owner ruling).

        Both sweeps in this file and in test_registry_case_sweep.py walk through
        conftest's python_sources, which skips three names: dropbox, .archive and
        __pycache__. Red first on python_sources without the skip (the mutant
        runner cannot serve conftest, which pytest loads first).
        """
        (tmp_path / "handlers").mkdir()
        (tmp_path / "handlers" / "real.py").write_text("x = 1\n", encoding="utf-8")
        for sandbox in ("dropbox", ".archive"):
            (tmp_path / "handlers" / sandbox).mkdir()
            (tmp_path / "handlers" / sandbox / "stray.py").write_text("x = 1\n", encoding="utf-8")

        walked = drone_conftest.python_sources(tmp_path)

        assert walked == [tmp_path / "handlers" / "real.py"], walked

    def test_a_sweep_rooted_inside_a_dropbox_still_sees_its_sources(self, tmp_path):
        """The skip judges the parts below the walked root: a project under a directory named
        dropbox keeps every source. Green from its first run and held for mutants (the runner
        cannot serve conftest); its proof is that a whole-path comparison empties the list."""
        root = tmp_path / "dropbox" / "apps"
        (root / "handlers").mkdir(parents=True)
        (root / "handlers" / "real.py").write_text("x = 1\n", encoding="utf-8")

        assert drone_conftest.python_sources(root) == [root / "handlers" / "real.py"]

    def test_host_platform_answers_what_sys_platform_holds(self):
        """The seam's body is the read it replaced; the collection-hook tests replace the seam."""
        assert drone_conftest.host_platform() == sys.platform


class TestTheWindowsSkipIsNarrow:
    """A skip that fires everywhere reports its own defeat as a pass.

    Nine tests in this branch build their world by deleting the directory they
    stand in, and Windows will not let a process do that (conftest's
    WINDOWS_CWD_REASON states the ruling: the recipe is unavailable there, not
    the state). They carry ``@pytest.mark.deletable_cwd`` and conftest skips
    them on win32 only.

    "Only" is the whole load-bearing word. A condition that quietly became true
    everywhere would turn nine red tests into nine green ones and read the same
    in the summary line — @memory found exactly that mutant surviving in their
    own tree, which is why this is measured rather than asserted about the
    marker object.
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

        The subprocess pin above can only observe THIS platform, so a
        ``pytest_collection_modifyitems`` that stopped matching the marker
        entirely would leave it green here and hand Windows nine reds back.
        The hook is a function; called directly with the platform it branches
        on, both of its answers are observable anywhere.
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
