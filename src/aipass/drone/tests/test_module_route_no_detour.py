# =================== AIPass ====================
# Name: test_module_route_no_detour.py
# Description: A module target is routed as a module — never via a failed branch lookup
# Version: 1.0.0
# Created: 2026-08-21
# =============================================

"""Routing a module target must not detour through branch routing.

`git` is an internal module and is never a branch, but "status" sits in
INTERACTIVE_COMMANDS, so `drone @git status` used to skip the module fast path,
call route_command(), take a guaranteed BranchNotFoundError, log "Falling back
to module routing" and then make the identical module call the fast path would
have made. On the live system that fallback was 1335 of 1337 lines in
drone_drone.log — a fallback firing on the HAPPY PATH (DPLAN-0315).

Two things it concealed, both asserted here:
  - interactive mode is a property of BRANCH (subprocess) routing; _handle_module
    takes no interactive parameter, so a module target never receives it
  - a BranchNotFoundError raised by resolve_branch's path-escape SECURITY check
    was swallowed and re-routed to the module, turning a refusal into a detour
"""

from unittest.mock import patch

from aipass.drone.apps.modules import BranchNotFoundError

_DRONE = "aipass.drone.apps.drone"


class TestModuleTargetNeverDetours:
    """A module with no branch behind it goes straight to module routing."""

    def test_interactive_command_on_module_target_skips_branch_routing(self) -> None:
        """`drone @git status` must not attempt a branch lookup it cannot win."""
        from aipass.drone.apps.drone import _handle_target

        with (
            patch(f"{_DRONE}.is_module", return_value=True),
            patch(f"{_DRONE}.branch_exists", return_value=False),
            patch(f"{_DRONE}.route_command") as mock_route,
            patch(f"{_DRONE}._handle_module", return_value=0) as mock_module,
        ):
            rc = _handle_target(["@git", "status"])

        assert rc == 0
        mock_route.assert_not_called(), "a module that is not a branch must never be branch-routed"
        mock_module.assert_called_once_with("git", ["status"])

    def test_bare_module_introspection_skips_branch_routing(self) -> None:
        """`drone @git` is presentational, so it took the same detour."""
        from aipass.drone.apps.drone import _handle_target

        with (
            patch(f"{_DRONE}.is_module", return_value=True),
            patch(f"{_DRONE}.branch_exists", return_value=False),
            patch(f"{_DRONE}.route_command") as mock_route,
            patch(f"{_DRONE}._handle_module", return_value=0) as mock_module,
        ):
            rc = _handle_target(["@git"])

        assert rc == 0
        mock_route.assert_not_called()
        mock_module.assert_called_once_with("git", [])

    def test_module_help_skips_branch_routing(self) -> None:
        """`drone @git --help` took the detour too — help is presentational."""
        from aipass.drone.apps.drone import _handle_target

        with (
            patch(f"{_DRONE}.is_module", return_value=True),
            patch(f"{_DRONE}.branch_exists", return_value=False),
            patch(f"{_DRONE}.route_command") as mock_route,
            patch(f"{_DRONE}._handle_module", return_value=0) as mock_module,
        ):
            rc = _handle_target(["@git", "--help"])

        assert rc == 0
        mock_route.assert_not_called()
        mock_module.assert_called_once_with("git", ["--help"])

    def test_non_interactive_module_command_unchanged(self) -> None:
        """`drone @git diff` was always silent — the fast path stays exactly as it was."""
        from aipass.drone.apps.drone import _handle_target

        with (
            patch(f"{_DRONE}.is_module", return_value=True),
            patch(f"{_DRONE}.branch_exists") as mock_exists,
            patch(f"{_DRONE}.route_command") as mock_route,
            patch(f"{_DRONE}._handle_module", return_value=0) as mock_module,
        ):
            rc = _handle_target(["@git", "diff"])

        assert rc == 0
        mock_route.assert_not_called()
        mock_module.assert_called_once_with("git", ["diff"])
        mock_exists.assert_not_called(), "a non-interactive module command must not pay a registry read"


class TestBranchBackedModuleKeepsInteractive:
    """@seedgo is BOTH a module and a branch — its Rich lane must not regress."""

    def test_interactive_command_still_branch_routes_when_branch_exists(self) -> None:
        """`drone @seedgo audit` keeps subprocess routing so progress bars render live."""
        from aipass.drone.apps.drone import _handle_target

        with (
            patch(f"{_DRONE}.is_module", return_value=True),
            patch(f"{_DRONE}.branch_exists", return_value=True),
            patch(f"{_DRONE}.route_command") as mock_route,
            patch(f"{_DRONE}._handle_module") as mock_module,
        ):
            mock_route.return_value.exit_code = 0
            mock_route.return_value.stdout = ""
            mock_route.return_value.stderr = ""
            _handle_target(["@seedgo", "audit", "aipass"])

        mock_module.assert_not_called()
        assert mock_route.call_args.kwargs["interactive"] is True


class TestNoFallbackHidesAFailure:
    """A branch that resolves and then fails is an ERROR, not a re-route."""

    def test_branch_resolution_failure_is_loud_not_rerouted(self) -> None:
        """resolve_branch refuses a path that escapes the project root — for SECURITY.

        branch_exists() only checks the registry entry; resolve_branch additionally
        validates the path. The old handler caught that refusal and ran the module
        instead, so a blocked branch quietly got service by another door.
        """
        from aipass.drone.apps.drone import _handle_target

        with (
            patch(f"{_DRONE}.is_module", return_value=True),
            patch(f"{_DRONE}.branch_exists", return_value=True),
            patch(f"{_DRONE}.route_command", side_effect=BranchNotFoundError("path escapes project root")),
            patch(f"{_DRONE}._handle_module") as mock_module,
        ):
            rc = _handle_target(["@seedgo", "audit"])

        assert rc == 1, "a refused branch must fail loud"
        mock_module.assert_not_called(), "a security refusal must not be answered by module routing"
