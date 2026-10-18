# =================== AIPass ====================
# Name: test_caller_identity_provenance.py
# Description: Caller identity ships with the evidence it came from
# Version: 1.0.2
# Created: 2026-08-21
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/router_handler.py: a caller's identity ships with the provenance it came from."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module under test parses and imports

import json
import shutil
from pathlib import Path

import pytest

from aipass.drone.apps.handlers.router_handler import (
    resolve_caller_identity,
    resolve_caller_identity_signal,
)
from aipass.drone.apps.handlers import router_handler


# An assigned name is a credential; a repo-root project name only collides with a
# citizen. The source travels with the name so a consumer can tell them apart.


def _plant_passport(directory: Path, branch_name: str) -> Path:
    """Create directory/.trinity/passport.json naming branch_name."""
    trinity = directory / ".trinity"
    trinity.mkdir(parents=True, exist_ok=True)
    (trinity / "passport.json").write_text(json.dumps({"branch_info": {"branch_name": branch_name}}), encoding="utf-8")
    return directory


def _plant_registry(directory: Path, project_name: str) -> Path:
    """Create a project registry naming project_name, with no passport anywhere."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{project_name.upper()}_REGISTRY.json").write_text(
        json.dumps({"metadata": {"project_name": project_name}, "branches": []}),
        encoding="utf-8",
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
        """cd'ing into another branch does not relabel you as that branch."""
        home = _plant_passport(temp_test_dir / "aipass", "AIPASS")
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "commons")

        assert resolve_caller_identity_signal(home) == ("commons", "assigned")

    def test_passport_identity_is_sourced_passport(self, temp_test_dir: Path, monkeypatch):
        """A human in a branch is identified by the passport under their feet."""
        home = _plant_passport(temp_test_dir / "drone", "drone")
        monkeypatch.delenv("AIPASS_BRANCH_NAME", raising=False)

        assert resolve_caller_identity_signal(home) == ("drone", "passport")

    def test_project_name_is_sourced_project(self, temp_test_dir: Path, monkeypatch):
        """A repo root yields a project name, not a citizen."""
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

    def test_source_is_stamped_next_to_the_caller_branch(self, tmp_path, monkeypatch):
        """AIPASS_CALLER_IDENTITY_SOURCE rides with AIPASS_CALLER_BRANCH."""
        from unittest.mock import MagicMock, patch

        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return MagicMock(stdout="", stderr="", exit_code=0)

        with (
            patch.object(router_handler, "find_entry_point", return_value=tmp_path / "branch" / "apps" / "x.py"),
            patch.object(router_handler, "execute_command", side_effect=_capture),
            patch.object(
                router_handler,
                "resolve_caller_identity_signal",
                return_value=router_handler.CallerIdentity("commons", "assigned"),
            ),
        ):
            router_handler.execute_branch_command(branch_path=str(tmp_path / "branch"), branch_name="x", command="ping")

        env = captured["env"]
        assert env["AIPASS_CALLER_BRANCH"] == "commons"
        assert env["AIPASS_CALLER_IDENTITY_SOURCE"] == "assigned"

    def test_no_identity_stamps_neither_variable(self, tmp_path, monkeypatch):
        """An anonymous caller must not ship an empty provenance claim."""
        from unittest.mock import MagicMock, patch

        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return MagicMock(stdout="", stderr="", exit_code=0)

        with (
            patch.object(router_handler, "find_entry_point", return_value=tmp_path / "branch" / "apps" / "x.py"),
            patch.object(router_handler, "execute_command", side_effect=_capture),
            patch.object(
                router_handler,
                "resolve_caller_identity_signal",
                return_value=router_handler.CallerIdentity(None, None),
            ),
        ):
            router_handler.execute_branch_command(branch_path=str(tmp_path / "branch"), branch_name="x", command="ping")

        env = captured["env"]
        assert "AIPASS_CALLER_BRANCH" not in env
        assert "AIPASS_CALLER_IDENTITY_SOURCE" not in env


@pytest.mark.deletable_cwd
class TestRoutingFromADeletedDirectory:
    """``drone rm`` on your own cwd succeeds, so the NEXT command runs from a deleted directory."""

    def test_routing_does_not_crash_when_the_cwd_was_deleted(self, tmp_path, monkeypatch):
        """Mutant killed: the routed command dropped from the args handed to execute_command."""
        from unittest.mock import MagicMock, patch

        doomed = tmp_path / "scratch"
        doomed.mkdir()
        monkeypatch.chdir(doomed)
        shutil.rmtree(doomed)

        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return MagicMock(stdout="", stderr="", exit_code=0)

        with (
            patch.object(router_handler, "find_entry_point", return_value=tmp_path / "branch" / "apps" / "x.py"),
            patch.object(router_handler, "execute_command", side_effect=_capture),
        ):
            router_handler.execute_branch_command(branch_path=str(tmp_path / "branch"), branch_name="x", command="ping")

        assert "ping" in captured["args"], "routing died on a cwd that no longer exists"

    def test_the_absent_cwd_is_not_forwarded_as_a_real_path(self, tmp_path, monkeypatch):
        """The target reads AIPASS_CALLER_CWD as a location. It must not get a lie."""
        from unittest.mock import MagicMock, patch

        doomed = tmp_path / "scratch"
        doomed.mkdir()
        monkeypatch.chdir(doomed)
        shutil.rmtree(doomed)

        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return MagicMock(stdout="", stderr="", exit_code=0)

        with (
            patch.object(router_handler, "find_entry_point", return_value=tmp_path / "branch" / "apps" / "x.py"),
            patch.object(router_handler, "execute_command", side_effect=_capture),
        ):
            router_handler.execute_branch_command(branch_path=str(tmp_path / "branch"), branch_name="x", command="ping")

        assert captured["env"].get("AIPASS_CALLER_CWD") != str(doomed)

    def test_assigned_identity_still_answers_without_a_cwd(self, tmp_path, monkeypatch):
        """Who this process IS never depended on where it was standing."""

        doomed = tmp_path / "scratch"
        doomed.mkdir()
        monkeypatch.chdir(doomed)
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "commons")
        shutil.rmtree(doomed)

        identity = router_handler.resolve_caller_identity_signal(router_handler.caller_cwd())

        assert identity.name == "commons"
        assert identity.source == "assigned"

    def test_the_handlers_package_imports_at_all_without_a_cwd(self, tmp_path):
        """Every guard above is unreachable if the IMPORT raises first.

        A real subprocess, not a mock: the import-time ``Path.resolve()`` reaches ``os.getcwd`` in C.
        """
        import subprocess
        import sys
        import textwrap

        doomed = tmp_path / "scratch"
        doomed.mkdir()
        probe = textwrap.dedent(
            """
            import os, shutil, sys
            here = sys.argv[1]
            os.chdir(here)
            shutil.rmtree(here)
            from aipass.drone.apps.handlers import registry_handler
            print("imported", registry_handler.__name__.rsplit(".", 1)[-1])
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", probe, str(doomed)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(tmp_path),
        )

        assert result.returncode == 0, result.stderr
        assert "imported registry_handler" in result.stdout


class TestRoutingWithoutACwdOnEveryOS:
    """The same three claims as the class above, built portably (Windows refuses deleting the cwd).

    The import claim has no portable sibling: on Windows it is genuinely untested.
    """

    @pytest.fixture()
    def no_cwd(self, monkeypatch):
        """The raw read raises ENOENT beneath caller_cwd, so every guard above it runs."""

        def gone():
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(router_handler, "_working_directory", gone)
        yield

    @staticmethod
    def _route(tmp_path):
        """Route one command with execution stubbed; return the captured kwargs."""
        from unittest.mock import MagicMock, patch

        branch = tmp_path / "branch"
        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return MagicMock(stdout="", stderr="", exit_code=0)

        with (
            patch.object(router_handler, "find_entry_point", return_value=branch / "apps" / "x.py"),
            patch.object(router_handler, "execute_command", side_effect=_capture),
        ):
            router_handler.execute_branch_command(branch_path=str(branch), branch_name="x", command="ping")
        return captured

    def test_routing_does_not_crash(self, no_cwd, tmp_path):
        assert self._route(tmp_path), "routing died with no current directory"

    def test_the_absent_cwd_is_omitted_rather_than_faked(self, no_cwd, tmp_path):
        """The target reads AIPASS_CALLER_CWD as a location: omitted, not blanked or faked."""
        captured = self._route(tmp_path)

        assert "AIPASS_CALLER_CWD" not in captured["env"]

    def test_assigned_identity_still_answers(self, no_cwd, monkeypatch):
        """Who this process IS never depended on where it was standing."""

        monkeypatch.setenv("AIPASS_BRANCH_NAME", "commons")

        identity = router_handler.resolve_caller_identity_signal(router_handler.caller_cwd())

        assert identity.name == "commons"
        assert identity.source == "assigned"
