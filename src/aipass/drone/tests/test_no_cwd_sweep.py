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

    def test_the_repo_root_still_answers_from_the_package(self, no_cwd):
        """``find_repo_root`` promises a Path, not an Optional — so it must find one.

        With no cwd both the walk and the toplevel-query fallback lose their
        starting point, so the answer comes from the sources that never needed
        one. This mirrors ``find_registry``'s existing precedence exactly rather
        than inventing a second order for the same question.
        """
        from aipass.drone.apps.handlers.git import lock_handler

        root = lock_handler.find_repo_root()

        assert isinstance(root, Path)
        assert list(root.glob("*_REGISTRY.json")), f"{root} is not a project root"


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
    """

    def test_no_bare_cwd_read_survives_outside_caller_cwd(self):
        import aipass.drone.apps as drone_apps

        root = Path(drone_apps.__file__).parent
        offenders = []
        for source in sorted(root.rglob("*.py")):
            if source.name == "router_handler.py":
                continue  # caller_cwd() itself — the one sanctioned read
            for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]
                if "Path.cwd()" in code or "os.getcwd()" in code:
                    offenders.append(f"{source.relative_to(root)}:{number}")

        assert offenders == [], "bare working-directory reads outside caller_cwd(): " + ", ".join(offenders)
