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
from aipass.drone.apps.handlers import router_handler
from aipass.drone.apps.handlers.executor import CommandResult
from aipass.drone.apps.handlers.router_handler import (
    detect_caller_signal,
    execute_branch_command,
    find_entry_point,
    resolve_caller_identity,
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
    def test_sets_aipass_branch_name_to_target(self, mock_exec, branch_dir: Path):
        """AIPASS_BRANCH_NAME is set to the target branch name on dispatch."""
        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="", command="")

        execute_branch_command(
            branch_path=str(branch_dir),
            branch_name="fakebranch",
            command="test",
        )

        env = mock_exec.call_args.kwargs.get("env", {})
        assert env["AIPASS_BRANCH_NAME"] == "fakebranch"

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

    @patch("aipass.drone.apps.modules.router.resolve_caller_identity", return_value=None)
    @patch("aipass.drone.apps.modules.router.execute_branch_command")
    @patch("aipass.drone.apps.modules.router.resolve_branch")
    def test_lost_caller_logs_unknown_not_blank(self, mock_resolve, mock_exec, _mock_identity):
        """An undetected caller routes as UNKNOWN, not as a silently omitted tag.

        A blank tag reads as 'not applicable' and hid the gap that surfaced one
        second later as a BRANCH DETECTION FAILED in the target branch.
        """
        mock_resolve.return_value = "/fake/path/to/branch"
        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="ai_mail", command="dispatch")

        with patch("aipass.drone.apps.modules.router.logger") as mock_logger:
            route_command("@ai_mail", "dispatch")

        logged = mock_logger.info.call_args[0]
        assert " [CALLER:UNKNOWN]" in logged

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


class TestExtensionIsOnlyForTheDefault:
    """An explicit --drone-timeout means EXACTLY that number.

    route_command already knows whether the operator supplied one: `timeout`
    arrives as None when nobody said. Extension is switched off when they did,
    because a deliberate tight cap that silently stretches is unpredictable —
    the operator's number is the operator's number.
    """

    @patch("aipass.drone.apps.modules.router.execute_branch_command")
    @patch("aipass.drone.apps.modules.router.resolve_branch")
    def test_explicit_timeout_disables_extension(self, mock_resolve, mock_exec):
        mock_resolve.return_value = "/fake/path"
        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="b", command="c")

        route_command("@somebranch", "cmd", timeout=30)

        assert mock_exec.call_args.kwargs["extend_on_output"] is False

    @patch("aipass.drone.apps.modules.router.execute_branch_command")
    @patch("aipass.drone.apps.modules.router.resolve_branch")
    def test_default_timeout_keeps_extension(self, mock_resolve, mock_exec):
        mock_resolve.return_value = "/fake/path"
        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="b", command="c")

        route_command("@somebranch", "cmd")

        assert mock_exec.call_args.kwargs["extend_on_output"] is True

    @patch("aipass.drone.apps.modules.router.execute_branch_command")
    @patch("aipass.drone.apps.modules.router.resolve_branch")
    def test_routing_line_states_the_extension_state(self, mock_resolve, mock_exec):
        """The routing log says whether this call can stretch.

        The timeout is already logged; a number without its policy is half the
        fact, and the missing half is what made a 60s kill look like a hang.
        """
        mock_resolve.return_value = "/fake/path"
        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="b", command="c")

        with patch("aipass.drone.apps.modules.router.logger") as mock_logger:
            route_command("@somebranch", "cmd")

        call_args = mock_logger.info.call_args[0]
        rendered = call_args[0] % tuple(call_args[1:])
        assert "extend_on_output=True" in rendered

    @pytest.fixture
    def branch_dir(self, temp_test_dir: Path) -> Path:
        """Create a fake branch directory with a valid entry point."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir()
        entry = apps_dir / "fakebranch.py"
        entry.write_text("# stub", encoding="utf-8")
        return temp_test_dir

    @patch("aipass.drone.apps.handlers.router_handler.execute_command")
    def test_handler_forwards_extend_on_output(self, mock_exec, branch_dir: Path):
        """router_handler passes the flag down instead of swallowing it."""
        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="", command="")

        execute_branch_command(
            branch_path=str(branch_dir),
            branch_name="fakebranch",
            command="slow",
            extend_on_output=False,
        )

        assert mock_exec.call_args.kwargs["extend_on_output"] is False

    def test_handler_extends_by_default(self):
        """The handler's own default must not silently disable extension."""
        import inspect

        sig = inspect.signature(execute_branch_command)
        assert sig.parameters["extend_on_output"].default is True


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
# detect_caller_signal
# ---------------------------------------------------------------------------


class TestDetectCallerBranchName:
    """Tests for detect_caller_signal().name in router_handler."""

    def test_v1_passport_branch_info(self, temp_test_dir: Path):
        """Detects branch name from v1 passport format (branch_info.branch_name)."""
        trinity = temp_test_dir / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"branch_info": {"branch_name": "alpha"}}))

        result = detect_caller_signal(temp_test_dir).name
        assert result == "alpha"

    def test_v2_passport_identity_name(self, temp_test_dir: Path):
        """Detects branch name from v2 passport format (identity.name)."""
        trinity = temp_test_dir / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"identity": {"name": "beta"}}))

        result = detect_caller_signal(temp_test_dir).name
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

        result = detect_caller_signal(temp_test_dir).name
        assert result == "v1name"

    def test_no_passport_returns_none(self, temp_test_dir: Path):
        """Returns None when no .trinity/passport.json exists."""
        result = detect_caller_signal(temp_test_dir).name
        assert result is None

    def test_corrupt_passport_returns_none(self, temp_test_dir: Path):
        """Returns None and doesn't crash when passport.json is invalid JSON."""
        trinity = temp_test_dir / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text("{{{not valid json!!!")

        result = detect_caller_signal(temp_test_dir).name
        assert result is None

    def test_walks_up_from_subdirectory(self, temp_test_dir: Path):
        """Finds passport.json in a parent directory when cwd is a subdirectory."""
        trinity = temp_test_dir / ".trinity"
        trinity.mkdir()
        passport = trinity / "passport.json"
        passport.write_text(json.dumps({"branch_info": {"branch_name": "found_it"}}))

        sub = temp_test_dir / "deep" / "nested" / "dir"
        sub.mkdir(parents=True)

        result = detect_caller_signal(sub).name
        assert result == "found_it"


class TestDetectCallerFallsBackToRegistry:
    """An unusable passport must not dead-end detection.

    The old code returned None the moment a passport was found but unreadable,
    silently skipping the registry fallback its own docstring promises — so an
    external project with a valid registry still lost its caller identity.
    """

    @staticmethod
    def _write_registry(root: Path, name: str) -> None:
        (root / "PROJ_REGISTRY.json").write_text(json.dumps({"metadata": {"name": name}, "branches": []}))

    def test_corrupt_passport_falls_back_to_registry(self, temp_test_dir: Path):
        """Invalid JSON in the passport still resolves the project from the registry."""
        trinity = temp_test_dir / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text("{{{not valid json!!!")
        self._write_registry(temp_test_dir, "Vera Studio")

        assert detect_caller_signal(temp_test_dir).name == "vera-studio"

    def test_nameless_passport_falls_back_to_registry(self, temp_test_dir: Path):
        """A passport that parses but names no branch is unusable, not authoritative."""
        trinity = temp_test_dir / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text(json.dumps({"branch_info": {}}))
        self._write_registry(temp_test_dir, "Vera Studio")

        assert detect_caller_signal(temp_test_dir).name == "vera-studio"

    def test_broken_passport_does_not_inherit_parent_identity(self, temp_test_dir: Path):
        """The walk-up STOPS at a broken passport — climbing would misattribute identity.

        A nested branch with a corrupt passport must never be reported as its parent.
        """
        parent_trinity = temp_test_dir / ".trinity"
        parent_trinity.mkdir()
        (parent_trinity / "passport.json").write_text(json.dumps({"branch_info": {"branch_name": "parent_branch"}}))

        child = temp_test_dir / "child"
        child_trinity = child / ".trinity"
        child_trinity.mkdir(parents=True)
        (child_trinity / "passport.json").write_text("{{{broken")

        assert detect_caller_signal(child).name != "parent_branch"

    def test_total_failure_logs_cwd(self, temp_test_dir: Path):
        """No passport and no registry logs the cwd — without it the failure is invisible.

        The downstream error names the TARGET branch's directory, which sends
        investigation to the wrong branch entirely (see @ai_mail send-fail 47f50fdb).

        INFO since DPLAN-0283 — an anonymous caller is a correct outcome, not a
        fault. The breadcrumb is what matters and it is unchanged; only the
        severity moved. See TestIdentityMessageSeverity for why.
        """
        with patch("aipass.drone.apps.handlers.router_handler.logger") as mock_logger:
            assert detect_caller_signal(temp_test_dir).name is None
        mock_logger.info.assert_called_once()
        assert mock_logger.warning.call_args_list == []
        # Compare as Paths, not reprs: on Windows the logged arg renders as
        # WindowsPath('C:/...') while str(tmp_path) has backslashes, so a
        # substring match fails on separator style alone.
        assert any(
            Path(str(arg)) == temp_test_dir for arg in mock_logger.info.call_args.args if isinstance(arg, (str, Path))
        )

    def test_successful_detection_is_silent(self, temp_test_dir: Path):
        """The happy path must not warn — noise in the logs @trigger watches."""
        trinity = temp_test_dir / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text(json.dumps({"branch_info": {"branch_name": "alpha"}}))

        with patch("aipass.drone.apps.handlers.router_handler.logger") as mock_logger:
            assert detect_caller_signal(temp_test_dir).name == "alpha"
        mock_logger.warning.assert_not_called()


class TestNamelessRegistryFallback:
    """A registry with no declared name must still identify its project.

    AIPass's OWN registry carries only version/last_updated/total_branches/id, so
    requiring metadata.name made the framework repo the single place this
    fallback could never fire — and it failed silently. Callers at the AIPass
    root were anonymous all day: six feedback messages arrived From unknown with
    no reply path, three replies undeliverable for five hours.
    """

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("AIPASS_REGISTRY.json", "aipass"),
            ("VERA-STUDIO_REGISTRY.json", "vera-studio"),
            ("EARMARK_REGISTRY.json", "earmark"),
        ],
    )
    def test_filename_identifies_project_when_metadata_is_nameless(
        self, temp_test_dir: Path, filename: str, expected: str
    ):
        """The filename is the one thing every registry provably has."""
        (temp_test_dir / filename).write_text(
            json.dumps({"metadata": {"version": "1.0.0", "total_branches": 17, "id": "abc"}, "branches": []})
        )
        assert detect_caller_signal(temp_test_dir).name == expected

    def test_declared_name_beats_the_filename(self, temp_test_dir: Path):
        """An explicit declaration outranks inference — filename is the fallback, not the rule."""
        (temp_test_dir / "PROJ_REGISTRY.json").write_text(
            json.dumps({"metadata": {"name": "Vera Studio"}, "branches": []})
        )
        assert detect_caller_signal(temp_test_dir).name == "vera-studio"

    def test_passport_still_outranks_the_registry(self, temp_test_dir: Path):
        """Project-level attribution must never shadow a citizen standing in their branch.

        This is the whole safety boundary of the fallback: it fires only when
        nobody identifiable is home.
        """
        trinity = temp_test_dir / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text(json.dumps({"branch_info": {"branch_name": "drone"}}))
        (temp_test_dir / "AIPASS_REGISTRY.json").write_text(json.dumps({"metadata": {}, "branches": []}))

        assert detect_caller_signal(temp_test_dir).name == "drone"

    def test_unreadable_registry_says_so(self, temp_test_dir: Path):
        """Found-but-rejected must never be silent — that silence cost the diagnosis.

        The old code logged nothing when a registry was found and turned down, so
        the log showed 'no passport or registry found' while the registry was
        sitting in the very directory named by the message.
        """
        (temp_test_dir / "PROJ_REGISTRY.json").write_text("{{{not json")
        with patch("aipass.drone.apps.handlers.router_handler.logger") as mock_logger:
            detect_caller_signal(temp_test_dir).name
        assert mock_logger.warning.called
        assert any("unreadable" in str(c) for c in mock_logger.warning.call_args_list)

    def test_bare_suffix_registry_is_refused_and_named(self, temp_test_dir: Path):
        """'_REGISTRY.json' leaves nothing to derive — refuse, and SAY which file.

        Asserting the warning, not just the None: the caller's truthiness check
        already discards an empty name, so returning None proves nothing about
        the guard. The log line is the part that only this guard can produce, and
        it is the whole point — a registry turned down in silence is exactly the
        failure being fixed here.
        """
        (temp_test_dir / "_REGISTRY.json").write_text(json.dumps({"metadata": {}, "branches": []}))
        with patch("aipass.drone.apps.handlers.router_handler.logger") as mock_logger:
            assert detect_caller_signal(temp_test_dir).name is None
        assert any("no usable project name" in str(c) for c in mock_logger.warning.call_args_list)

    def test_derived_name_cannot_earn_git_authority(self, temp_test_dir: Path, monkeypatch):
        """A project name is identity for routing, never a credential.

        Filename derivation means any directory with a *_REGISTRY.json now yields
        a caller name. Owner-tier reads passports directly and must stay unmoved
        by that — otherwise this convenience would be an escalation path.
        """
        from aipass.drone.apps.plugins.devpulse_ops.auth import verify_git_access

        (temp_test_dir / "AIPASS_REGISTRY.json").write_text(json.dumps({"metadata": {"id": "x"}, "branches": []}))
        assert detect_caller_signal(temp_test_dir).name == "aipass"

        monkeypatch.chdir(temp_test_dir)
        with pytest.raises(PermissionError):
            verify_git_access("commit")


# ---------------------------------------------------------------------------
# Caller identity precedence
# ---------------------------------------------------------------------------


def _plant_passport(directory: Path, branch_name: str) -> Path:
    """Create directory/.trinity/passport.json naming branch_name."""
    trinity = directory / ".trinity"
    trinity.mkdir(parents=True, exist_ok=True)
    (trinity / "passport.json").write_text(json.dumps({"branch_info": {"branch_name": branch_name}}))
    return directory


class TestCallerIdentityPrecedence:
    """Assigned identity (AIPASS_BRANCH_NAME) outranks the cwd passport.

    Every test here sets or deletes AIPASS_BRANCH_NAME explicitly. The var is
    live in any dispatched agent's shell, so a test that reads it from the
    ambient environment passes or fails on who ran pytest.
    """

    def test_assigned_identity_beats_cwd_passport(self, temp_test_dir: Path, monkeypatch):
        """An agent standing in another branch is still itself (S102)."""
        home = _plant_passport(temp_test_dir / "aipass", "AIPASS")
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "commons")

        assert resolve_caller_identity(home) == "commons"

    def test_cwd_answers_when_nothing_is_assigned(self, temp_test_dir: Path, monkeypatch):
        """A human in a terminal has no assigned identity — cwd still speaks."""
        home = _plant_passport(temp_test_dir / "aipass", "AIPASS")
        monkeypatch.delenv("AIPASS_BRANCH_NAME", raising=False)

        assert resolve_caller_identity(home) == "AIPASS"

    def test_assigned_identity_survives_a_cwd_with_no_passport(self, temp_test_dir: Path, monkeypatch):
        """cd'ing somewhere unmarked must not erase who you are."""
        nowhere = temp_test_dir / "nowhere"
        nowhere.mkdir()
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "commons")

        assert resolve_caller_identity(nowhere) == "commons"

    def test_conflict_is_logged_naming_both_signals(self, temp_test_dir: Path, monkeypatch):
        """This process is the only place both signals coexist.

        ai_mail cannot see the conflict downstream — it receives the winner
        only — so an unlogged disagreement is unrecoverable.
        """
        home = _plant_passport(temp_test_dir / "aipass", "AIPASS")
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "commons")

        with patch("aipass.drone.apps.handlers.router_handler.logger") as mock_logger:
            resolve_caller_identity(home)

        warnings = " ".join(str(c) for c in mock_logger.warning.call_args_list)
        assert "commons" in warnings and "AIPASS" in warnings

    def test_agreement_is_not_logged(self, temp_test_dir: Path, monkeypatch):
        """Passports carry display casing; the env var carries the directory name.

        'AIPASS' and 'aipass' are the same citizen — comparing them exactly
        would warn on every well-behaved call.
        """
        home = _plant_passport(temp_test_dir / "aipass", "AIPASS")
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "aipass")

        with patch("aipass.drone.apps.handlers.router_handler.logger") as mock_logger:
            result = resolve_caller_identity(home)

        assert result == "aipass"
        conflicts = [c for c in mock_logger.warning.call_args_list if "conflict" in str(c)]
        assert conflicts == []

    def test_no_signal_at_all_returns_none(self, temp_test_dir: Path, monkeypatch):
        """Fail to None, never to a guess — the CALLER:UNKNOWN tag says so."""
        nowhere = temp_test_dir / "nowhere"
        nowhere.mkdir()
        monkeypatch.delenv("AIPASS_BRANCH_NAME", raising=False)
        monkeypatch.setenv("AIPASS_REGISTRY", str(temp_test_dir / "absent_REGISTRY.json"))

        assert resolve_caller_identity(nowhere) is None


class TestIdentityMessageSeverity:
    """A resolution that SUCCEEDS must not page anyone (DPLAN-0283).

    Two escalation digests fired off these sites in eight minutes. Every fact
    below was true of the live logs before the fix.
    """

    def _plant_registry(self, directory: Path, filename: str = "AIPASS_REGISTRY.json") -> Path:
        """Write a registry with no declared name — AIPass's own shape."""
        directory.mkdir(parents=True, exist_ok=True)
        (directory / filename).write_text(json.dumps({"metadata": {"version": "1.0"}, "branches": []}))
        return directory

    def test_project_root_caller_does_not_warn(self, temp_test_dir: Path, monkeypatch):
        """THE BUG: a service launched at a repo root warned on every call.

        AIPASS_BRANCH_NAME=prax + cwd=<repo root> is the ordinary shape of every
        long-lived process in the system. 103 of the 105 logged 'conflicts' were
        this, and none of them was one.
        """
        root = self._plant_registry(temp_test_dir / "AIPass")
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "prax")

        with patch("aipass.drone.apps.handlers.router_handler.logger") as mock_logger:
            result = resolve_caller_identity(root)

        assert result == "prax"
        assert mock_logger.warning.call_args_list == []

    def test_project_root_message_does_not_claim_a_passport(self, temp_test_dir: Path, monkeypatch):
        """The old line named evidence that was never there.

        It said 'the passport at cwd /home/patrick/Projects/AIPass says aipass'.
        That directory holds no .trinity/passport.json — the name came from the
        registry. Patrick's ruling: say plainly what happened.
        """
        root = self._plant_registry(temp_test_dir / "AIPass")
        assert not (root / ".trinity" / "passport.json").exists()
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "prax")

        with patch("aipass.drone.apps.handlers.router_handler.logger") as mock_logger:
            resolve_caller_identity(root)

        said = " ".join(str(c) for c in mock_logger.info.call_args_list)
        assert "passport" not in said.lower().split("no passport")[0]
        assert "prax" in said and "aipass" in said

    def test_real_passport_conflict_still_warns(self, temp_test_dir: Path, monkeypatch):
        """S102's shape stays loud — two citizens claiming one process."""
        home = _plant_passport(temp_test_dir / "aipass", "AIPASS")
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "commons")

        with patch("aipass.drone.apps.handlers.router_handler.logger") as mock_logger:
            resolve_caller_identity(home)

        warnings = " ".join(str(c) for c in mock_logger.warning.call_args_list)
        assert "commons" in warnings and "AIPASS" in warnings

    def test_detection_failure_does_not_warn(self, temp_test_dir: Path, monkeypatch):
        """Patrick running a monitor from ~ is a normal operator action."""
        nowhere = temp_test_dir / "nowhere"
        nowhere.mkdir()
        monkeypatch.delenv("AIPASS_BRANCH_NAME", raising=False)

        with patch("aipass.drone.apps.handlers.router_handler.logger") as mock_logger:
            result = resolve_caller_identity(nowhere)

        assert result is None
        assert mock_logger.warning.call_args_list == []
        assert "anonymous" in " ".join(str(c) for c in mock_logger.info.call_args_list)

    def test_repeat_calls_in_one_process_log_once(self, temp_test_dir: Path, monkeypatch):
        """resolve_caller_identity runs TWICE per route — router.py, then here.

        That alone doubled every line in the digest. Neither signal can change
        under a running process, so the second is the first restated.
        """
        home = _plant_passport(temp_test_dir / "aipass", "AIPASS")
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "commons")

        with patch("aipass.drone.apps.handlers.router_handler.logger") as mock_logger:
            for _ in range(10):
                resolve_caller_identity(home)

        assert len(mock_logger.warning.call_args_list) == 1

    def test_a_different_conflict_still_speaks(self, temp_test_dir: Path, monkeypatch):
        """Dedupe must silence repeats, never a NEW disagreement."""
        home = _plant_passport(temp_test_dir / "aipass", "AIPASS")

        with patch("aipass.drone.apps.handlers.router_handler.logger") as mock_logger:
            monkeypatch.setenv("AIPASS_BRANCH_NAME", "commons")
            resolve_caller_identity(home)
            monkeypatch.setenv("AIPASS_BRANCH_NAME", "trigger")
            resolve_caller_identity(home)

        warnings = " ".join(str(c) for c in mock_logger.warning.call_args_list)
        assert len(mock_logger.warning.call_args_list) == 2
        assert "commons" in warnings and "trigger" in warnings

    def test_dedupe_does_not_leak_across_processes(self, temp_test_dir: Path, monkeypatch):
        """Suppression is per-process, so a real conflict still escalates.

        A recurring conflict across separate drone invocations SHOULD reach the
        digest threshold. Muting it globally would trade a noisy bug for a
        silent one.
        """
        home = _plant_passport(temp_test_dir / "aipass", "AIPASS")
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "commons")

        with patch("aipass.drone.apps.handlers.router_handler.logger") as mock_logger:
            resolve_caller_identity(home)
            router_handler._LOGGED_IDENTITY_SIGNATURES.clear()  # a fresh process starts empty
            resolve_caller_identity(home)

        assert len(mock_logger.warning.call_args_list) == 2

    def test_signal_reports_passport_provenance(self, temp_test_dir: Path):
        """Provenance is the whole fix — a name alone cannot tell these apart."""
        home = _plant_passport(temp_test_dir / "aipass", "AIPASS")

        assert detect_caller_signal(home) == ("AIPASS", "passport")

    def test_signal_reports_project_provenance(self, temp_test_dir: Path):
        """A registry answers 'where am I', never 'who am I'."""
        root = self._plant_registry(temp_test_dir / "AIPass")

        assert detect_caller_signal(root) == ("aipass", "project")

    def test_name_field_carries_the_answer(self, temp_test_dir: Path):
        """Provenance is additive — the name is still the answer."""
        home = _plant_passport(temp_test_dir / "aipass", "AIPASS")

        assert detect_caller_signal(home).name == "AIPASS"

    @patch("aipass.drone.apps.handlers.router_handler.execute_command")
    def test_stamped_caller_is_the_assigned_identity(self, mock_exec, temp_test_dir: Path, monkeypatch):
        """End to end: the env var the child receives is what ai_mail stamps."""
        apps_dir = temp_test_dir / "apps"
        apps_dir.mkdir()
        (apps_dir / "testbranch.py").write_text("# stub")
        home = _plant_passport(temp_test_dir / "aipass", "AIPASS")
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "commons")
        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="", command="")

        with patch("aipass.drone.apps.handlers.router_handler.Path") as mock_path_cls:
            mock_path_cls.cwd.return_value = home
            mock_path_cls.side_effect = Path
            execute_branch_command(branch_path=str(temp_test_dir), branch_name="testbranch", command="status")

        assert mock_exec.call_args.kwargs["env"]["AIPASS_CALLER_BRANCH"] == "commons"

    @patch("aipass.drone.apps.modules.router.execute_branch_command")
    @patch("aipass.drone.apps.modules.router.resolve_branch")
    def test_log_tag_names_the_same_caller_that_is_stamped(
        self, mock_resolve, mock_exec, temp_test_dir: Path, monkeypatch
    ):
        """router.py logs the CALLER: tag from its own lookup.

        Two copies of the precedence means the tag can name one branch while
        the work is stamped with another — the log would exonerate the very
        caller under investigation.
        """
        home = _plant_passport(temp_test_dir / "aipass", "AIPASS")
        mock_resolve.return_value = str(temp_test_dir)
        mock_exec.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="", command="")
        monkeypatch.setenv("AIPASS_BRANCH_NAME", "commons")
        monkeypatch.chdir(home)

        with patch("aipass.drone.apps.modules.router.logger") as mock_logger:
            route_command("@testbranch", "status")

        routing = " ".join(str(c) for c in mock_logger.info.call_args_list)
        assert "CALLER:COMMONS" in routing


# ---------------------------------------------------------------------------
# AIPASS_CALLER_BRANCH env var
# ---------------------------------------------------------------------------


class TestCallerBranchEnvVar:
    """Tests that execute_branch_command sets AIPASS_CALLER_BRANCH."""

    @patch("aipass.drone.apps.handlers.router_handler.execute_command")
    def test_sets_caller_branch_from_passport(self, mock_exec, temp_test_dir: Path, monkeypatch):
        """AIPASS_CALLER_BRANCH is set when passport.json exists in cwd.

        The delenv is load-bearing: AIPASS_BRANCH_NAME now outranks the passport
        and is set in every dispatched agent's shell, so without it this test
        asserts on whoever ran pytest rather than on the fixture.
        """
        monkeypatch.delenv("AIPASS_BRANCH_NAME", raising=False)
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
