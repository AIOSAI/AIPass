# =================== AIPass ====================
# Name: test_caller_identity_provenance.py
# Description: Caller identity ships with the evidence it came from
# Version: 1.0.0
# Created: 2026-08-21
# =============================================

"""A caller's identity and WHERE it came from must travel together.

Two different questions were being answered with one string:

    (a) agent assigned @commons, standing in /tmp  -> CALLER_BRANCH=commons
    (b) nobody assigned, standing at the repo root -> CALLER_BRANCH=aipass

(a) is a credential — a dispatched agent that cd'd out of its branch is still
itself (S102). (b) is a DIRECTORY NAME that happens to collide with the citizen
@aipass, so ai_mail's contact lookup found a real row and stamped it "verified":
a dispatch sent from the repo root on 2026-08-21 went out as @aipass and the
wake-back woke the wrong citizen (11 turns, $1.41, DPLAN-0315 item 3).

Downstream could not tell them apart, so ai_mail's identity fence had to refuse
BOTH — which re-broke the S102 case it was protecting. Stamping the provenance
next to the name is what lets a consumer accept "assigned" from anywhere and
refuse "project" everywhere.
"""

import json
import shutil
from pathlib import Path

import pytest

from aipass.drone.apps.handlers.router_handler import (
    resolve_caller_identity,
    resolve_caller_identity_signal,
)


def _plant_passport(directory: Path, branch_name: str) -> Path:
    """Create directory/.trinity/passport.json naming branch_name."""
    trinity = directory / ".trinity"
    trinity.mkdir(parents=True, exist_ok=True)
    (trinity / "passport.json").write_text(json.dumps({"branch_info": {"branch_name": branch_name}}))
    return directory


def _plant_registry(directory: Path, project_name: str) -> Path:
    """Create a project registry naming project_name, with no passport anywhere."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{project_name.upper()}_REGISTRY.json").write_text(
        json.dumps({"metadata": {"project_name": project_name}, "branches": []})
    )
    return directory


class TestProvenanceTravelsWithTheName:
    """resolve_caller_identity_signal answers WHO and HOW IT KNOWS."""

    def test_assigned_identity_is_sourced_assigned(self, temp_test_dir: Path, monkeypatch):
        """An assigned name is a credential, wherever the process is standing."""
        nowhere = temp_test_dir / "nowhere"
        nowhere.mkdir()
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "commons")

        assert resolve_caller_identity_signal(nowhere) == ("commons", "assigned")

    def test_assigned_wins_and_is_still_sourced_assigned_over_a_passport(self, temp_test_dir: Path, monkeypatch):
        """S102: cd'ing into another branch does not relabel you as that branch."""
        home = _plant_passport(temp_test_dir / "aipass", "AIPASS")
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "commons")

        assert resolve_caller_identity_signal(home) == ("commons", "assigned")

    def test_passport_identity_is_sourced_passport(self, temp_test_dir: Path, monkeypatch):
        """A human in a branch is identified by the passport under their feet."""
        home = _plant_passport(temp_test_dir / "drone", "drone")
        monkeypatch.delenv("AIPASS_BRANCH_NAME", raising=False)

        assert resolve_caller_identity_signal(home) == ("drone", "passport")

    def test_project_name_is_sourced_project(self, temp_test_dir: Path, monkeypatch):
        """THE $1.41 CASE: a repo root yields a project name, not a citizen."""
        root = _plant_registry(temp_test_dir / "AIPass", "aipass")
        monkeypatch.delenv("AIPASS_BRANCH_NAME", raising=False)

        name, source = resolve_caller_identity_signal(root)
        assert name == "aipass"
        assert source == "project", "a directory name must never be indistinguishable from a credential"

    def test_anonymous_caller_has_no_source(self, temp_test_dir: Path, monkeypatch):
        """No passport, no registry, nothing assigned — an honest gap."""
        nowhere = temp_test_dir / "nowhere"
        nowhere.mkdir()
        monkeypatch.delenv("AIPASS_BRANCH_NAME", raising=False)

        assert resolve_caller_identity_signal(nowhere) == (None, None)

    def test_the_two_collapsed_cases_are_now_distinguishable(self, temp_test_dir: Path, monkeypatch):
        """The exact pair ai_mail could not tell apart, side by side."""
        elsewhere = temp_test_dir / "tmp"
        elsewhere.mkdir()
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "commons")
        legit = resolve_caller_identity_signal(elsewhere)

        root = _plant_registry(temp_test_dir / "AIPass", "aipass")
        monkeypatch.delenv("AIPASS_BRANCH_NAME", raising=False)
        collision = resolve_caller_identity_signal(root)

        assert legit.source != collision.source, "these two are the whole incident — they must not read alike"
        assert legit.source == "assigned" and collision.source == "project"


class TestBareNameApiUnchanged:
    """resolve_caller_identity keeps its contract — deletion_log and router.py call it."""

    @pytest.mark.parametrize(
        "assigned,expected",
        [("commons", "commons"), (None, "drone")],
    )
    def test_bare_resolver_still_returns_just_the_name(self, temp_test_dir: Path, monkeypatch, assigned, expected):
        home = _plant_passport(temp_test_dir / "drone", "drone")
        if assigned:
            monkeypatch.setenv("AIPASS_BRANCH_NAME", assigned)
        else:
            monkeypatch.delenv("AIPASS_BRANCH_NAME", raising=False)

        result = resolve_caller_identity(home)
        assert result == expected
        assert isinstance(result, str)


class TestProvenanceIsStampedIntoTheEnvironment:
    """A consumer in another process can only act on what drone stamps."""

    def test_source_is_stamped_next_to_the_caller_branch(self, monkeypatch):
        """AIPASS_CALLER_IDENTITY_SOURCE rides with AIPASS_CALLER_BRANCH."""
        from unittest.mock import MagicMock, patch

        from aipass.drone.apps.handlers import router_handler

        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return MagicMock(stdout="", stderr="", exit_code=0)

        with (
            patch.object(router_handler, "find_entry_point", return_value=Path("/tmp/branch/apps/x.py")),
            patch.object(router_handler, "execute_command", side_effect=_capture),
            patch.object(
                router_handler,
                "resolve_caller_identity_signal",
                return_value=router_handler.CallerIdentity("commons", "assigned"),
            ),
        ):
            router_handler.execute_branch_command(branch_path="/tmp/branch", branch_name="x", command="ping")

        env = captured["env"]
        assert env["AIPASS_CALLER_BRANCH"] == "commons"
        assert env["AIPASS_CALLER_IDENTITY_SOURCE"] == "assigned"

    def test_no_identity_stamps_neither_variable(self, monkeypatch):
        """An anonymous caller must not ship an empty provenance claim."""
        from unittest.mock import MagicMock, patch

        from aipass.drone.apps.handlers import router_handler

        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return MagicMock(stdout="", stderr="", exit_code=0)

        with (
            patch.object(router_handler, "find_entry_point", return_value=Path("/tmp/branch/apps/x.py")),
            patch.object(router_handler, "execute_command", side_effect=_capture),
            patch.object(
                router_handler,
                "resolve_caller_identity_signal",
                return_value=router_handler.CallerIdentity(None, None),
            ),
        ):
            router_handler.execute_branch_command(branch_path="/tmp/branch", branch_name="x", command="ping")

        env = captured["env"]
        assert "AIPASS_CALLER_BRANCH" not in env
        assert "AIPASS_CALLER_IDENTITY_SOURCE" not in env


# ---------------------------------------------------------------------------
# Routing must survive a caller whose directory no longer exists
# ---------------------------------------------------------------------------


class TestRoutingFromADeletedDirectory:
    """``drone rm`` on your own cwd now succeeds — so the NEXT command runs here.

    Every routed invocation reads the caller's cwd twice: once to ship
    AIPASS_CALLER_CWD to the target, once to resolve who is calling. Both reads
    were bare, and a process whose directory was deleted raises ENOENT on each.

    The delete lane was fixed first, which is what made this reachable rather
    than theoretical: before that fix the delete itself crashed, so nobody ever
    got to type a second command from a directory that was gone. @trigger found
    the count was three reads, not the two this branch first reported.
    """

    def test_routing_does_not_crash_when_the_cwd_was_deleted(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock, patch

        from aipass.drone.apps.handlers import router_handler

        doomed = tmp_path / "scratch"
        doomed.mkdir()
        monkeypatch.chdir(doomed)
        shutil.rmtree(doomed)

        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return MagicMock(stdout="", stderr="", exit_code=0)

        with (
            patch.object(router_handler, "find_entry_point", return_value=Path("/tmp/branch/apps/x.py")),
            patch.object(router_handler, "execute_command", side_effect=_capture),
        ):
            router_handler.execute_branch_command(branch_path="/tmp/branch", branch_name="x", command="ping")

        assert captured, "routing died on a cwd that no longer exists"

    def test_the_absent_cwd_is_not_forwarded_as_a_real_path(self, tmp_path, monkeypatch):
        """The target reads AIPASS_CALLER_CWD as a location. It must not get a lie."""
        from unittest.mock import MagicMock, patch

        from aipass.drone.apps.handlers import router_handler

        doomed = tmp_path / "scratch"
        doomed.mkdir()
        monkeypatch.chdir(doomed)
        shutil.rmtree(doomed)

        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return MagicMock(stdout="", stderr="", exit_code=0)

        with (
            patch.object(router_handler, "find_entry_point", return_value=Path("/tmp/branch/apps/x.py")),
            patch.object(router_handler, "execute_command", side_effect=_capture),
        ):
            router_handler.execute_branch_command(branch_path="/tmp/branch", branch_name="x", command="ping")

        assert captured["env"].get("AIPASS_CALLER_CWD") != str(doomed)

    def test_assigned_identity_still_answers_without_a_cwd(self, tmp_path, monkeypatch):
        """Who this process IS never depended on where it was standing (S102)."""
        from aipass.drone.apps.handlers import router_handler

        doomed = tmp_path / "scratch"
        doomed.mkdir()
        monkeypatch.chdir(doomed)
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "commons")
        shutil.rmtree(doomed)

        identity = router_handler.resolve_caller_identity_signal(router_handler.caller_cwd())

        assert identity.name == "commons"
        assert identity.source == "assigned"
