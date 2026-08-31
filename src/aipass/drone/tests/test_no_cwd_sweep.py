# =================== AIPass ====================
# Name: test_no_cwd_sweep.py
# Description: Every location-inference site survives a deleted working directory
# Version: 1.0.0
# Created: 2026-08-31
# =============================================

"""No location is not a failure — pinned at every site that infers one.

THE SPECIES. ``Path.cwd()`` raises ENOENT the moment the directory it names is
gone. Session 68 fixed that in the deletion RECORD and session 69 fixed it on
the ROUTING path, and both times the fix landed on the sites already in hand
rather than on every site in the tree. @trigger reproduced the leftover live —
``drone rm`` from a deleted directory, exit 1, ``FileNotFoundError`` at
``rm_handler.py:37`` — and named it as the pattern rather than the incident: a
fix that lands on some of N identical paths. This file is the N.

It is also the recovery case, which is what makes it more than tidiness. The
first ``drone rm`` succeeds and deletes the directory the caller stands in; the
SECOND command — the one a person runs to clean up after — is the one that
crashed. Fixing the crash in session 68 is what put a live process here to run
it.

THE RULE, identical at every site: a walk that infers something from where the
caller STANDS has nothing to read when the caller stands nowhere. That is the
absence of a signal, said out loud at INFO, not an error — so the walk is
SKIPPED and every other source still answers. Sites that can honestly return
"unknown" do. The one gate that cannot — owner-tier auth — fails CLOSED and
says why.

``caller_cwd()`` in ``router_handler`` is the single reader. A tenth private
copy of ``try: Path.cwd() except OSError: None`` would be this file's own
lesson repeated.
"""

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


@pytest.fixture()
def no_cwd(monkeypatch):
    """The process has no working directory — the state, not a mock of a guard.

    Patches ``Path.cwd`` rather than ``caller_cwd`` on purpose: before the
    sweep, nine sites never went through ``caller_cwd`` at all, so patching the
    guard would have made this file green against unfixed code.
    """

    def gone():
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(Path, "cwd", staticmethod(gone))
    yield


@pytest.fixture()
def home_root(tmp_path, monkeypatch):
    """An AIPass home that answers when the cwd cannot."""
    home = tmp_path / "home"
    home.mkdir()
    (home / "AIPASS_REGISTRY.json").write_text('{"branches": []}')
    monkeypatch.setenv("AIPASS_HOME", str(home))
    return home


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------


class TestDroneEntryPointSurvives:
    def test_registry_presence_check_falls_through_to_aipass_home(self, no_cwd, home_root):
        """The cwd walk is skipped; the source that never needed a location answers."""
        from aipass.drone.apps import drone

        assert drone._cwd_has_registry() is True

    def test_registry_presence_check_answers_false_rather_than_raising(self, no_cwd, monkeypatch):
        from aipass.drone.apps import drone

        monkeypatch.delenv("AIPASS_HOME", raising=False)
        assert drone._cwd_has_registry() is False

    def test_the_seat_inbox_is_unknown_not_a_crash(self, no_cwd):
        """A seat is inferred from where you stand. Standing nowhere means no seat."""
        from aipass.drone.apps import drone

        assert drone._find_seat_inbox() is None


# ---------------------------------------------------------------------------
# The delete lane — the one @trigger reproduced
# ---------------------------------------------------------------------------


class TestTheDeleteLaneSurvives:
    def test_project_root_falls_through_to_aipass_home(self, no_cwd, home_root):
        from aipass.drone.apps.handlers import rm_handler

        assert rm_handler._find_project_root() == home_root.resolve()

    def test_project_root_is_unknown_rather_than_a_crash(self, no_cwd, monkeypatch):
        from aipass.drone.apps.handlers import rm_handler

        monkeypatch.delenv("AIPASS_HOME", raising=False)
        assert rm_handler._find_project_root() is None

    def test_the_current_branch_is_unknown(self, no_cwd, tmp_path):
        from aipass.drone.apps.handlers import rm_handler

        assert rm_handler._detect_current_branch(tmp_path) is None

    def test_an_absolute_path_still_deletes(self, no_cwd, home_root):
        """The recovery command. It names its target absolutely and needs no cwd."""
        from aipass.drone.apps.handlers import rm_handler

        target = home_root / "scratch"
        target.mkdir()

        results = rm_handler.safe_delete([str(target)])

        assert results[0][1] is True, results
        assert not target.exists()

    def test_a_relative_path_is_refused_cleanly_not_crashed(self, no_cwd, home_root):
        """A relative path is meaningless without a cwd — a refusal, not a traceback."""
        from aipass.drone.apps.handlers import rm_handler

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
            cwd=str(tmp_path),
        )

        assert result.returncode == 0, result.stderr
        assert "RESULT True" in result.stdout, result.stdout
        assert not victim.exists()


# ---------------------------------------------------------------------------
# The git lane
# ---------------------------------------------------------------------------


class TestTheGitLaneSurvives:
    def test_the_caller_branch_is_unknown_rather_than_a_crash(self, no_cwd):
        from aipass.drone.apps.modules import git_module

        assert git_module._detect_branch_dir() is None

    def test_the_repo_root_comes_from_aipass_home_when_there_is_no_cwd(self, no_cwd, home_root):
        """``find_repo_root`` promises a Path, not an Optional — so it must find one.

        With no cwd both the walk and the toplevel-query fallback lose their
        starting point, so the answer comes from the sources that never needed
        one. AIPASS_HOME is the first of them, and it is checkable against a
        stand-in rather than against this machine.
        """
        from aipass.drone.apps.handlers.git import lock_handler

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
        from aipass.drone.apps.handlers.git import lock_handler

        real_glob = Path.glob

        def no_registries(self, pattern, *args, **kwargs):
            if pattern == "*_REGISTRY.json":
                return iter(())
            return real_glob(self, pattern, *args, **kwargs)

        monkeypatch.setattr(Path, "glob", no_registries)
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
        assert any((root / marker).exists() for marker in lock_handler._PROJECT_MARKERS), (
            f"{root} carries no project marker — a lock would land in a subdirectory"
        )


class TestTheAuthGateFailsClosed:
    """The one site that must NOT answer "unknown".

    Every other site here infers a convenience. This one decides whether a
    caller may write to the repository, and "I could not tell who you are" is a
    refusal — the same answer it already gives when the walk finds no passport.
    What changes is that it arrives as a stated refusal instead of an ENOENT
    traceback from inside a credential check.
    """

    def test_no_cwd_is_a_refusal_that_says_why(self, no_cwd):
        from aipass.drone.apps.plugins.devpulse_ops import auth

        with pytest.raises(PermissionError) as excinfo:
            auth._resolve_caller()

        assert "no current directory" in str(excinfo.value).lower(), str(excinfo.value)


class TestTheBrokerSurvives:
    def test_broker_project_root_falls_through_to_aipass_home(self, no_cwd, home_root):
        from aipass.drone.apps.handlers.broker import daemon

        assert daemon._find_project_root() == home_root.resolve()

    def test_broker_project_root_is_unknown_rather_than_a_crash(self, no_cwd, monkeypatch):
        from aipass.drone.apps.handlers.broker import daemon

        monkeypatch.delenv("AIPASS_HOME", raising=False)
        assert daemon._find_project_root() is None


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
        import aipass.drone.apps as drone_apps

        root = Path(drone_apps.__file__).parent
        offenders = []
        for source in sorted(root.rglob("*.py")):
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
        import aipass.drone.apps as drone_apps

        branch_root = Path(drone_apps.__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, "-m", "pytest", self.MARKED, "-q", "-rs", "--timeout=120", "-p", "no:randomly"],
            cwd=str(branch_root),
            capture_output=True,
            text=True,
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
        from types import SimpleNamespace

        from aipass.drone.tests import conftest as drone_conftest

        def one_item():
            recorded = []
            return SimpleNamespace(
                keywords={drone_conftest.DELETABLE_CWD_MARKER: True},
                recorded=recorded,
                add_marker=recorded.append,
            )

        monkeypatch.setattr(drone_conftest.sys, "platform", "win32")
        on_windows = one_item()
        drone_conftest.pytest_collection_modifyitems(None, [on_windows])
        assert on_windows.recorded, "a deletable-cwd test was left to run on Windows"
        assert drone_conftest.WINDOWS_CWD_REASON in str(on_windows.recorded[0])

        monkeypatch.setattr(drone_conftest.sys, "platform", "linux")
        elsewhere = one_item()
        unmarked = SimpleNamespace(keywords={}, recorded=[], add_marker=lambda m: None)
        drone_conftest.pytest_collection_modifyitems(None, [elsewhere, unmarked])
        assert not elsewhere.recorded, "the skip reached a platform that can delete its own cwd"
