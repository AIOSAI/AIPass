# =================== AIPass ====================
# Name: test_module_route_no_detour.py
# Description: A module target is routed as a module — never via a failed branch lookup
# Version: 1.0.1
# Created: 2026-08-21
# Modified: 2026-09-27
# =============================================

"""Tests for apps/drone.py: a module target never detours through branch routing."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — the subprocess a branch route would spawn; tests/test_router.py covers branch routing

from unittest.mock import patch

import pytest

from aipass.drone.apps.drone import main
from aipass.drone.apps.modules import BranchNotFoundError

# `git` is an internal module and never a branch, but "status" sits in
# INTERACTIVE_COMMANDS, so `drone @git status` used to skip the module fast path,
# take a guaranteed BranchNotFoundError and fall back to module routing: 1335 of
# 1337 lines in drone_drone.log, a fallback on the happy path (DPLAN-0315).
# Two things it concealed, both asserted here: interactive mode belongs to branch
# (subprocess) routing only, and a BranchNotFoundError from resolve_branch's
# path-escape security check must stay a refusal, never a detour to the module.

_DRONE = "aipass.drone.apps.drone"


class TestModuleTargetNeverDetours:
    """A module with no branch behind it goes straight to module routing."""

    def test_interactive_command_on_module_target_skips_branch_routing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`drone @git status` never tries a branch lookup (mutant: lane test `not needs_interactive`)."""
        with (
            patch(f"{_DRONE}.is_module", return_value=True),
            patch(f"{_DRONE}.branch_exists", return_value=False),
            patch(f"{_DRONE}.route_command") as mock_route,
            patch(f"{_DRONE}._handle_module", return_value=0) as mock_module,
        ):
            monkeypatch.setattr("sys.argv", ["drone", "@git", "status"])
            rc = main()

        assert rc == 0
        mock_route.assert_not_called(), "a module that is not a branch must never be branch-routed"
        mock_module.assert_called_once_with("git", ["status"])

    def test_bare_module_introspection_skips_branch_routing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`drone @git` is presentational, so it took the same detour (mutant: `not needs_interactive`)."""
        with (
            patch(f"{_DRONE}.is_module", return_value=True),
            patch(f"{_DRONE}.branch_exists", return_value=False),
            patch(f"{_DRONE}.route_command") as mock_route,
            patch(f"{_DRONE}._handle_module", return_value=0) as mock_module,
        ):
            monkeypatch.setattr("sys.argv", ["drone", "@git"])
            rc = main()

        assert rc == 0
        mock_route.assert_not_called()
        mock_module.assert_called_once_with("git", [])

    def test_module_help_skips_branch_routing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`drone @git --help` took the detour too (mutant: `not needs_interactive`)."""
        with (
            patch(f"{_DRONE}.is_module", return_value=True),
            patch(f"{_DRONE}.branch_exists", return_value=False),
            patch(f"{_DRONE}.route_command") as mock_route,
            patch(f"{_DRONE}._handle_module", return_value=0) as mock_module,
        ):
            monkeypatch.setattr("sys.argv", ["drone", "@git", "--help"])
            rc = main()

        assert rc == 0
        mock_route.assert_not_called()
        mock_module.assert_called_once_with("git", ["--help"])

    def test_non_interactive_module_command_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`drone @git diff` pays no registry read (mutant: branch_exists evaluated first)."""
        with (
            patch(f"{_DRONE}.is_module", return_value=True),
            patch(f"{_DRONE}.branch_exists") as mock_exists,
            patch(f"{_DRONE}.route_command") as mock_route,
            patch(f"{_DRONE}._handle_module", return_value=0) as mock_module,
        ):
            monkeypatch.setattr("sys.argv", ["drone", "@git", "diff"])
            rc = main()

        assert rc == 0
        mock_route.assert_not_called()
        mock_module.assert_called_once_with("git", ["diff"])
        mock_exists.assert_not_called(), "a non-interactive module command must not pay a registry read"


class TestBranchBackedModuleKeepsInteractive:
    """@seedgo is BOTH a module and a branch — its Rich lane must not regress."""

    def test_interactive_command_still_branch_routes_when_branch_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`drone @seedgo audit` keeps the live lane (mutants: `interactive = False`; lane `is_module` only)."""
        with (
            patch(f"{_DRONE}.is_module", return_value=True),
            patch(f"{_DRONE}.branch_exists", return_value=True),
            patch(f"{_DRONE}.route_command") as mock_route,
            patch(f"{_DRONE}._handle_module") as mock_module,
        ):
            mock_route.return_value.exit_code = 0
            mock_route.return_value.stdout = ""
            mock_route.return_value.stderr = ""
            monkeypatch.setattr("sys.argv", ["drone", "@seedgo", "audit", "aipass"])
            main()

        mock_module.assert_not_called()
        assert mock_route.call_args.kwargs["interactive"] is True


class TestNoFallbackHidesAFailure:
    """A branch that resolves and then fails is an ERROR, not a re-route."""

    def test_branch_resolution_failure_is_loud_not_rerouted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A resolve_branch security refusal fails loud, never runs the module (mutant: lane `is_module` only)."""
        # branch_exists() only checks the registry entry; resolve_branch additionally
        # validates the path. The old handler caught that refusal and ran the module
        # instead, so a blocked branch quietly got service by another door.
        with (
            patch(f"{_DRONE}.is_module", return_value=True),
            patch(f"{_DRONE}.branch_exists", return_value=True),
            patch(f"{_DRONE}.route_command", side_effect=BranchNotFoundError("path escapes project root")),
            patch(f"{_DRONE}._handle_module") as mock_module,
        ):
            monkeypatch.setattr("sys.argv", ["drone", "@seedgo", "audit"])
            rc = main()

        assert rc == 1, "a refused branch must fail loud"
        mock_module.assert_not_called(), "a security refusal must not be answered by module routing"
