"""Tests for command routing — router module and router_handler."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.drone.apps.handlers.exceptions import (
    BranchNotFoundError,
    CommandExecutionError,
)
from aipass.drone.apps.handlers.executor import CommandResult
from aipass.drone.apps.handlers.router_handler import (
    detect_caller_branch_name,
    execute_branch_command,
    find_entry_point,
)
from aipass.drone.apps.modules.router import handle_command, route_command, route_all


# ---------------------------------------------------------------------------
# find_entry_point
# ---------------------------------------------------------------------------


class TestFindEntryPoint:
    """Tests for find_entry_point() in router_handler."""

    def test_locates_existing_entry_point(self, temp_test_dir: Path):
        """find_entry_point returns the correct Path when apps/{name}.py exists."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir()
        entry_file = apps_dir / "mybranch.py"
        entry_file.write_text("# entry point stub")

        result = find_entry_point(str(temp_test_dir), "mybranch")

        assert result == entry_file
        assert result.exists()

    def test_raises_when_entry_point_missing(self, temp_test_dir: Path):
        """find_entry_point raises CommandExecutionError if file doesn't exist."""
        with pytest.raises(CommandExecutionError, match="Entry point not found"):
            find_entry_point(str(temp_test_dir), "nonexistent")

    def test_returns_path_under_apps_subdirectory(self, temp_test_dir: Path):
        """Returned path is always branch_path / apps / {name}.py."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir()
        entry_file = apps_dir / "test_branch.py"
        entry_file.write_text("")

        result = find_entry_point(str(temp_test_dir), "test_branch")

        assert result.parent.name == "apps"
        assert result.name == "test_branch.py"


# ---------------------------------------------------------------------------
# execute_branch_command
# ---------------------------------------------------------------------------


class TestExecuteBranchCommand:
    """Tests for execute_branch_command() in router_handler."""

    @pytest.fixture
    def branch_dir(self, temp_test_dir: Path) -> Path:
        """Create a fake branch directory with a valid entry point."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir()
        entry = apps_dir / "fakebranch.py"
        entry.write_text("# stub")
        return temp_test_dir

    @patch("aipass.drone.apps.handlers.router_handler.execute_command")
    def test_valid_command_returns_command_result(self, mock_exec, branch_dir: Path):
        """A valid command returns a CommandResult with correct fields."""
        mock_exec.return_value = CommandResult(stdout="ok\n", stderr="", exit_code=0, branch="", command="")

        result = execute_branch_command(
            branch_path=str(branch_dir),
            branch_name="fakebranch",
            command="status",
        )

        assert isinstance(result, CommandResult)
        assert result.exit_code == 0
        assert result.stdout == "ok\n"
        assert result.branch == "fakebranch"
        assert result.command == "status"

    @patch("aipass.drone.apps.handlers.router_handler.execute_command")
    def test_introspection_with_command_none(self, mock_exec, branch_dir: Path):
        """When command=None the entry point is invoked with no command args."""
        mock_exec.return_value = CommandResult(
            stdout="introspect output", stderr="", exit_code=0, branch="", command=""
        )

        result = execute_branch_command(
            branch_path=str(branch_dir),
            branch_name="fakebranch",
            command=None,
        )

        # Args passed to execute_command should only be the relative entry point
        args_list = mock_exec.call_args.kwargs["args"]
        assert args_list == [str(Path("apps") / "fakebranch.py")]
        assert result.command == ""

    @patch("aipass.drone.apps.handlers.router_handler.execute_command")
    def test_interactive_flag_passed_through(self, mock_exec, branch_dir: Path):
        """interactive=True is forwarded to execute_command."""
        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="", command="")

        execute_branch_command(
            branch_path=str(branch_dir),
            branch_name="fakebranch",
            command="monitor",
            interactive=True,
        )

        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs.get("interactive") is True

    @patch("aipass.drone.apps.handlers.router_handler.execute_command")
    def test_sets_aipass_caller_cwd_env(self, mock_exec, branch_dir: Path):
        """AIPASS_CALLER_CWD is set in the env dict passed to execute_command."""
        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="", command="")

        execute_branch_command(
            branch_path=str(branch_dir),
            branch_name="fakebranch",
            command="test",
        )

        call_kwargs = mock_exec.call_args.kwargs
        env = call_kwargs.get("env", {})
        assert "AIPASS_CALLER_CWD" in env
        assert env["AIPASS_CALLER_CWD"] == str(Path.cwd())

    @patch("aipass.drone.apps.handlers.router_handler.execute_command")
    def test_timeout_propagated_to_executor(self, mock_exec, branch_dir: Path):
        """Timeout value is forwarded to execute_command."""
        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="", command="")

        execute_branch_command(
            branch_path=str(branch_dir),
            branch_name="fakebranch",
            command="slow",
            timeout=120,
        )

        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs.get("timeout") == 120

    @patch("aipass.drone.apps.handlers.router_handler.execute_command")
    def test_args_appended_to_command(self, mock_exec, branch_dir: Path):
        """Extra args are appended after the command in the args list."""
        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="", command="")

        execute_branch_command(
            branch_path=str(branch_dir),
            branch_name="fakebranch",
            command="deploy",
            args=["--force", "--env=prod"],
        )

        args_list = mock_exec.call_args.kwargs["args"]
        # Verify the args list ends with the command and its arguments in exact order
        assert args_list[-3:] == ["deploy", "--force", "--env=prod"]

    @patch("aipass.drone.apps.handlers.router_handler.execute_command")
    def test_uses_sys_executable(self, mock_exec, branch_dir: Path):
        """execute_command is called with sys.executable as the executable."""
        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="", command="")

        execute_branch_command(
            branch_path=str(branch_dir),
            branch_name="fakebranch",
            command="test",
        )

        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs.get("executable") == sys.executable

    def test_raises_when_entry_point_missing(self, temp_test_dir: Path):
        """execute_branch_command raises CommandExecutionError if entry point missing."""
        with pytest.raises(CommandExecutionError, match="Entry point not found"):
            execute_branch_command(
                branch_path=str(temp_test_dir),
                branch_name="does_not_exist",
                command="test",
            )


# ---------------------------------------------------------------------------
# route_command (integration-level, mocking handler layer)
# ---------------------------------------------------------------------------


class TestRouteCommand:
    """Tests for route_command() in the router module."""

    @patch("aipass.drone.apps.modules.router.execute_branch_command")
    @patch("aipass.drone.apps.modules.router.resolve_branch")
    def test_valid_branch_and_command(self, mock_resolve, mock_exec):
        """route_command resolves target and delegates to execute_branch_command."""
        mock_resolve.return_value = "/fake/path/to/branch"
        mock_exec.return_value = CommandResult(
            stdout="done", stderr="", exit_code=0, branch="mybranch", command="status"
        )

        result = route_command("@mybranch", "status")

        mock_resolve.assert_called_once_with("@mybranch")
        mock_exec.assert_called_once()
        assert result.exit_code == 0
        assert result.stdout == "done"

    @patch("aipass.drone.apps.modules.router.resolve_branch")
    def test_invalid_branch_raises_branch_not_found(self, mock_resolve):
        """route_command propagates BranchNotFoundError from resolver."""
        mock_resolve.side_effect = BranchNotFoundError("Branch '@ghost' not found")

        with pytest.raises(BranchNotFoundError, match="not found"):
            route_command("@ghost", "status")

    @patch("aipass.drone.apps.modules.router.execute_branch_command")
    @patch("aipass.drone.apps.modules.router.resolve_branch")
    def test_timeout_forwarded(self, mock_resolve, mock_exec):
        """route_command passes timeout through to execute_branch_command."""
        mock_resolve.return_value = "/fake/path"
        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="b", command="c")

        route_command("@somebranch", "cmd", timeout=90)

        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs["timeout"] == 90

    @patch("aipass.drone.apps.modules.router.execute_branch_command")
    @patch("aipass.drone.apps.modules.router.resolve_branch")
    def test_interactive_forwarded(self, mock_resolve, mock_exec):
        """route_command passes interactive flag through."""
        mock_resolve.return_value = "/fake/path"
        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="b", command="c")

        route_command("@somebranch", "monitor", interactive=True)

        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs["interactive"] is True

    @patch("aipass.drone.apps.modules.router.execute_branch_command")
    @patch("aipass.drone.apps.modules.router.resolve_branch")
    def test_introspection_no_command(self, mock_resolve, mock_exec):
        """route_command with command=None triggers introspection."""
        mock_resolve.return_value = "/fake/path"
        mock_exec.return_value = CommandResult(stdout="info", stderr="", exit_code=0, branch="b", command="")

        result = route_command("@somebranch", None)

        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs["command"] is None
        assert result.stdout == "info"

    @patch("aipass.drone.apps.modules.router.execute_branch_command")
    @patch("aipass.drone.apps.modules.router.resolve_branch")
    def test_args_forwarded(self, mock_resolve, mock_exec):
        """route_command forwards args list to execute_branch_command."""
        mock_resolve.return_value = "/fake/path"
        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="b", command="c")

        route_command("@mybranch", "deploy", args=["--env=staging"])

        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs["args"] == ["--env=staging"]

    @patch("aipass.drone.apps.modules.router.execute_branch_command")
    @patch("aipass.drone.apps.modules.router.resolve_branch")
    def test_branch_name_stripped_and_lowered(self, mock_resolve, mock_exec):
        """route_command strips @ prefix and lowercases for branch_name."""
        mock_resolve.return_value = "/fake/path"
        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="mybranch", command="test")

        route_command("@MyBranch", "test")

        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs["branch_name"] == "mybranch"


# ---------------------------------------------------------------------------
# route_all
# ---------------------------------------------------------------------------


class TestRouteAll:
    """Tests for route_all() in the router module."""

    @patch("aipass.drone.apps.modules.router.route_command")
    @patch("aipass.drone.apps.modules.router.list_branches")
    def test_routes_to_all_active_branches(self, mock_list, mock_route):
        """route_all dispatches the command to every active branch."""
        mock_list.return_value = ["@alpha", "@beta"]
        mock_route.return_value = CommandResult(stdout="ok", stderr="", exit_code=0, branch="", command="status")

        results = route_all("status")

        assert len(results) == 2
        assert "alpha" in results
        assert "beta" in results
        assert mock_route.call_count == 2

    @patch("aipass.drone.apps.modules.router.route_command")
    @patch("aipass.drone.apps.modules.router.list_branches")
    def test_captures_failure_per_branch(self, mock_list, mock_route):
        """When a branch raises, route_all records exit_code=-1 for it."""
        mock_list.return_value = ["@ok_branch", "@bad_branch"]
        mock_route.side_effect = [
            CommandResult(stdout="ok", stderr="", exit_code=0, branch="ok_branch", command="cmd"),
            RuntimeError("boom"),
        ]

        results = route_all("cmd")

        assert results["ok_branch"].exit_code == 0
        assert results["bad_branch"].exit_code == -1
        assert "boom" in results["bad_branch"].stderr


# ---------------------------------------------------------------------------
# detect_caller_branch_name
# ---------------------------------------------------------------------------


class TestDetectCallerBranchName:
    """Tests for detect_caller_branch_name() in router_handler."""

    def test_v1_passport_branch_info(self, temp_test_dir: Path):
        """Detects branch name from v1 passport format (branch_info.branch_name)."""
        trinity = temp_test_dir / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"branch_info": {"branch_name": "alpha"}}))

        result = detect_caller_branch_name(temp_test_dir)
        assert result == "alpha"

    def test_v2_passport_identity_name(self, temp_test_dir: Path):
        """Detects branch name from v2 passport format (identity.name)."""
        trinity = temp_test_dir / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"identity": {"name": "beta"}}))

        result = detect_caller_branch_name(temp_test_dir)
        assert result == "beta"

    def test_v1_takes_precedence_over_v2(self, temp_test_dir: Path):
        """When both v1 and v2 keys exist, v1 branch_info.branch_name wins."""
        trinity = temp_test_dir / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(
            json.dumps(
                {
                    "branch_info": {"branch_name": "v1name"},
                    "identity": {"name": "v2name"},
                }
            )
        )

        result = detect_caller_branch_name(temp_test_dir)
        assert result == "v1name"

    def test_no_passport_returns_none(self, temp_test_dir: Path):
        """Returns None when no .trinity/passport.json exists."""
        result = detect_caller_branch_name(temp_test_dir)
        assert result is None

    def test_corrupt_passport_returns_none(self, temp_test_dir: Path):
        """Returns None and doesn't crash when passport.json is invalid JSON."""
        trinity = temp_test_dir / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text("{{{not valid json!!!")

        result = detect_caller_branch_name(temp_test_dir)
        assert result is None

    def test_walks_up_from_subdirectory(self, temp_test_dir: Path):
        """Finds passport.json in a parent directory when cwd is a subdirectory."""
        trinity = temp_test_dir / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"branch_info": {"branch_name": "found_it"}}))

        sub = temp_test_dir / "deep" / "nested" / "dir"
        sub.mkdir(parents=True)

        result = detect_caller_branch_name(sub)
        assert result == "found_it"


# ---------------------------------------------------------------------------
# AIPASS_CALLER_BRANCH env var
# ---------------------------------------------------------------------------


class TestCallerBranchEnvVar:
    """Tests that execute_branch_command sets AIPASS_CALLER_BRANCH."""

    @patch("aipass.drone.apps.handlers.router_handler.execute_command")
    def test_sets_caller_branch_from_passport(self, mock_exec, temp_test_dir: Path):
        """AIPASS_CALLER_BRANCH is set when passport.json exists in cwd."""
        # Set up branch entry point
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir()
        entry = apps_dir / "testbranch.py"
        entry.write_text("# stub")

        # Set up passport in cwd
        cwd_dir = temp_test_dir / "caller_cwd"
        cwd_dir.mkdir()
        trinity = cwd_dir / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"branch_info": {"branch_name": "caller_branch"}}))

        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="", command="")

        with patch("aipass.drone.apps.handlers.router_handler.Path") as mock_path_cls:
            # Make Path.cwd() return our fake cwd
            mock_path_cls.cwd.return_value = cwd_dir
            # But keep Path(branch_path) / ... working for find_entry_point
            mock_path_cls.side_effect = Path

            execute_branch_command(
                branch_path=str(temp_test_dir),
                branch_name="testbranch",
                command="status",
            )

        env = mock_exec.call_args.kwargs["env"]
        assert env["AIPASS_CALLER_BRANCH"] == "caller_branch"

    @patch("aipass.drone.apps.handlers.router_handler.execute_command")
    def test_no_caller_branch_without_passport(self, mock_exec, temp_test_dir: Path):
        """AIPASS_CALLER_BRANCH is absent when no passport.json and no env var."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir()
        entry = apps_dir / "testbranch.py"
        entry.write_text("# stub")

        # Use a cwd with no passport
        cwd_dir = temp_test_dir / "empty_cwd"
        cwd_dir.mkdir()

        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="", command="")

        with patch("aipass.drone.apps.handlers.router_handler.Path") as mock_path_cls:
            mock_path_cls.cwd.return_value = cwd_dir
            mock_path_cls.side_effect = Path

            with patch.dict(os.environ, {}, clear=False):
                # Remove AIPASS_BRANCH_NAME if present
                os.environ.pop("AIPASS_BRANCH_NAME", None)
                execute_branch_command(
                    branch_path=str(temp_test_dir),
                    branch_name="testbranch",
                    command="status",
                )

        env = mock_exec.call_args.kwargs["env"]
        assert "AIPASS_CALLER_BRANCH" not in env


# ---------------------------------------------------------------------------
# handle_command
# ---------------------------------------------------------------------------


class TestHandleCommand:
    """Tests for handle_command() in the router module."""

    def test_route_no_args_returns_false(self):
        """handle_command('route', []) returns False — not enough args."""
        result = handle_command("route", [])
        assert result is False

    @patch("aipass.drone.apps.modules.router.route_command")
    def test_route_with_target_and_command(self, mock_route):
        """handle_command('route', ['@branch', 'cmd']) delegates to route_command."""
        mock_route.return_value = CommandResult(stdout="output", stderr="", exit_code=0, branch="branch", command="cmd")

        result = handle_command("route", ["@branch", "cmd"])

        assert result is True
        mock_route.assert_called_once_with("@branch", "cmd", args=None)

    @patch("aipass.drone.apps.modules.router.route_command")
    def test_route_with_extra_args(self, mock_route):
        """handle_command('route', ['@b', 'cmd', '--flag']) passes extra args."""
        mock_route.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="b", command="cmd")

        result = handle_command("route", ["@b", "cmd", "--flag"])

        assert result is True
        mock_route.assert_called_once_with("@b", "cmd", args=["--flag"])

    @patch("aipass.drone.apps.modules.router.route_command")
    def test_route_nonzero_exit_returns_false(self, mock_route):
        """handle_command('route', ...) returns False when exit_code != 0."""
        mock_route.return_value = CommandResult(stdout="", stderr="err", exit_code=1, branch="b", command="cmd")

        result = handle_command("route", ["@b", "cmd"])

        assert result is False

    def test_route_all_no_args_returns_false(self):
        """handle_command('route_all', []) returns False — missing command."""
        result = handle_command("route_all", [])
        assert result is False

    @patch("aipass.drone.apps.modules.router.route_all")
    def test_route_all_delegates(self, mock_route_all):
        """handle_command('route_all', ['status']) delegates to route_all."""
        mock_route_all.return_value = {
            "a": CommandResult(stdout="", stderr="", exit_code=0, branch="a", command="status"),
        }

        result = handle_command("route_all", ["status"])

        assert result is True
        mock_route_all.assert_called_once_with("status", args=None)

    @patch("aipass.drone.apps.modules.router.route_all")
    def test_route_all_with_extra_args(self, mock_route_all):
        """handle_command('route_all', ['cmd', '--v']) passes extra args."""
        mock_route_all.return_value = {
            "x": CommandResult(stdout="", stderr="", exit_code=0, branch="x", command="cmd"),
        }

        result = handle_command("route_all", ["cmd", "--v"])

        assert result is True
        mock_route_all.assert_called_once_with("cmd", args=["--v"])

    @patch("aipass.drone.apps.modules.router.route_all")
    def test_route_all_partial_failure_returns_false(self, mock_route_all):
        """handle_command('route_all', ...) returns False if any branch fails."""
        mock_route_all.return_value = {
            "ok": CommandResult(stdout="", stderr="", exit_code=0, branch="ok", command="c"),
            "bad": CommandResult(stdout="", stderr="err", exit_code=1, branch="bad", command="c"),
        }

        result = handle_command("route_all", ["c"])

        assert result is False

    def test_unknown_command_returns_false(self):
        """handle_command('unknown_cmd', []) returns False."""
        result = handle_command("unknown_cmd", [])
        assert result is False
