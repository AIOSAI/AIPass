# =================== AIPass ====================
# Name: test_activation.py
# Description: Tests for command activation, listing, removal, and custom execution
# Version: 1.0.3
# Created: 2026-03-17
# Modified: 2026-09-28
# =============================================

"""Tests for apps/drone.py: activate, list, remove, target, and running a custom command."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module under test parses and imports

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aipass.drone.apps.handlers.command_registry import ops, lookup
from aipass.drone.apps.handlers.command_registry.formatters import (
    format_activation_results,
    format_command_list,
    format_removal,
)
from aipass.drone.apps.handlers.executor import CommandResult
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.drone import main
from aipass.drone.apps.handlers.registry_handler import reset_registry_path, set_registry_path
from aipass.drone.apps.modules import BranchNotFoundError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the registry at a temp file so tests never touch the real one."""
    registry_file = tmp_path / "drone_command_registry.json"
    monkeypatch.setattr(ops, "REGISTRY_FILE", registry_file)
    return registry_file


def _seed_commands(**commands: dict[str, Any]) -> None:
    """Register commands via ops.add_command for test setup."""
    for name, data in commands.items():
        ops.add_command(
            name=name,
            target=data.get("target", "@test"),
            command=data.get("command", name),
            args=data.get("args"),
            description=data.get("description", ""),
            source_branch=data.get("source_branch", "test"),
        )


def _drone(*argv: str) -> int:
    """Run ``drone <argv>`` through main(), the door a user types into."""
    with patch("sys.argv", ["drone", *argv]):
        return main()


# ===================================================================
# 1. Formatters
# ===================================================================


class TestFormatCommandList:
    """Tests for format_command_list()."""

    def test_displays_commands(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should display a table with command details."""
        commands = [
            {
                "name": "audit",
                "target": "@seedgo",
                "command": "audit",
                "args": ["aipass"],
                "description": "Run audit",
            },
            {
                "name": "check",
                "target": "@seedgo",
                "command": "check",
                "args": [],
                "description": "Run checks",
            },
        ]
        format_command_list(commands)

        captured = capsys.readouterr()
        assert "audit" in captured.out
        assert "check" in captured.out
        assert "@seedgo" in captured.out
        assert "registered" in captured.out
        assert "custom" in captured.out

    def test_empty_list(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should show informational message when no commands exist."""
        format_command_list([])

        captured = capsys.readouterr()
        assert "No custom commands registered" in captured.out
        assert "drone activate" in captured.out


class TestFormatActivationResults:
    """Tests for format_activation_results()."""

    def test_shows_added(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should display added commands."""
        format_activation_results("seedgo", ["audit", "list"], [])

        captured = capsys.readouterr()
        assert "Activated" in captured.out
        assert "@seedgo" in captured.out
        assert "+ audit" in captured.out
        assert "+ list" in captured.out

    def test_shows_skipped(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should display skipped commands."""
        format_activation_results("seedgo", [], ["audit"])

        captured = capsys.readouterr()
        assert "Skipped" in captured.out
        assert "already registered" in captured.out
        assert "- audit" in captured.out

    def test_shows_both_added_and_skipped(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should display both added and skipped when both exist."""
        format_activation_results("seedgo", ["list"], ["audit"])

        captured = capsys.readouterr()
        assert "Activated" in captured.out
        assert "Skipped" in captured.out

    def test_shows_no_commands(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should show a message when nothing was added or skipped."""
        format_activation_results("seedgo", [], [])

        captured = capsys.readouterr()
        assert "No commands discovered" in captured.out

    def test_adds_at_prefix(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should add @ prefix to branch name if missing."""
        format_activation_results("seedgo", ["cmd"], [])

        captured = capsys.readouterr()
        assert "@seedgo" in captured.out


class TestFormatRemoval:
    """Tests for format_removal()."""

    def test_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should show removal confirmation on success."""
        format_removal("audit", True)

        captured = capsys.readouterr()
        assert "Removed custom command" in captured.out
        assert "audit" in captured.out

    def test_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should show not-found message on failure."""
        format_removal("ghost", False)

        captured = capsys.readouterr()
        assert "not found" in captured.out
        assert "ghost" in captured.out


# ===================================================================
# 2. _handle_activate
# ===================================================================


class TestHandleActivate:
    """``drone activate @branch`` scans and registers."""

    @patch("aipass.drone.apps.modules.commands.format_activation_results")
    @patch("aipass.drone.apps.modules.commands.add")
    @patch("aipass.drone.apps.modules.scan.scan")
    def test_registers_discovered_commands(
        self,
        mock_scan: MagicMock,
        mock_add: MagicMock,
        mock_format: MagicMock,
    ) -> None:
        """Should register all commands discovered by scan; mutant killed: main() not routing 'activate'."""

        mock_scan.return_value = [
            {"name": "audit", "description": "Run audit", "source": "help"},
            {"name": "list", "description": "List items", "source": "module"},
        ]
        mock_add.return_value = True

        result = _drone("activate", "@seedgo")

        assert result == 0
        assert mock_add.call_count == 2
        mock_format.assert_called_once()
        # Check the added list in format call
        call_args = mock_format.call_args
        assert "audit" in call_args[0][1]  # added list
        assert "list" in call_args[0][1]

    @patch("aipass.drone.apps.modules.commands.format_activation_results")
    @patch("aipass.drone.apps.modules.commands.add")
    @patch("aipass.drone.apps.modules.scan.scan")
    def test_skips_existing_commands(
        self,
        mock_scan: MagicMock,
        mock_add: MagicMock,
        mock_format: MagicMock,
    ) -> None:
        """Should skip commands that already exist in registry; mutant killed: main() not routing 'activate'."""

        mock_scan.return_value = [
            {"name": "audit", "description": "Run audit", "source": "help"},
        ]
        mock_add.return_value = False  # Already exists

        result = _drone("activate", "@seedgo")

        assert result == 0
        call_args = mock_format.call_args
        assert call_args[0][1] == []  # added = empty
        assert "audit" in call_args[0][2]  # skipped list

    @patch("aipass.drone.apps.modules.scan.scan")
    def test_returns_1_on_resolution_failure(self, mock_scan: MagicMock) -> None:
        """Should return 1 when scan cannot resolve the target; mutant killed: an unresolved target returning 0."""

        mock_scan.return_value = None

        result = _drone("activate", "@nonexistent")

        assert result == 1

    @patch("aipass.drone.apps.modules.scan.scan")
    def test_returns_0_on_empty_scan(self, mock_scan: MagicMock) -> None:
        """Should return 0 when scan finds no commands; mutant killed: main() not routing 'activate'."""

        mock_scan.return_value = []

        result = _drone("activate", "@emptybranch")

        assert result == 0


# ===================================================================
# 3. _handle_list
# ===================================================================


class TestHandleList:
    """``drone list`` shows the registered custom commands."""

    @patch("aipass.drone.apps.modules.commands.format_command_list")
    def test_calls_formatter(self, mock_format: MagicMock) -> None:
        """Should load commands and pass to formatter; mutant killed: main() not routing 'list'."""

        ops.add_command("audit", "@seedgo", "audit")

        result = _drone("list")

        assert result == 0
        mock_format.assert_called_once()
        commands_arg = mock_format.call_args[0][0]
        assert len(commands_arg) == 1
        assert commands_arg[0]["name"] == "audit"

    @patch("aipass.drone.apps.modules.commands.format_command_list")
    def test_empty_registry(self, mock_format: MagicMock) -> None:
        """Should pass empty list to formatter when no commands exist; mutant killed: main() not routing 'list'."""

        result = _drone("list")

        assert result == 0
        mock_format.assert_called_once_with([])


# ===================================================================
# 4. _handle_remove
# ===================================================================


class TestHandleRemove:
    """``drone remove <name>`` removes a custom command."""

    @patch("aipass.drone.apps.modules.commands.format_removal")
    def test_removes_existing(self, mock_format: MagicMock) -> None:
        """Should remove an existing command and return 0; mutant killed: main() not routing 'remove'."""

        ops.add_command("audit", "@seedgo", "audit")

        result = _drone("remove", "audit")

        assert result == 0
        mock_format.assert_called_once_with("audit", True)
        assert not ops.command_exists("audit")

    @patch("aipass.drone.apps.modules.commands.format_removal")
    def test_nonexistent_returns_1(self, mock_format: MagicMock) -> None:
        """Should return 1 when trying to remove a nonexistent command; mutant killed: main() not routing 'remove'."""

        result = _drone("remove", "ghost")

        assert result == 1
        mock_format.assert_called_once_with("ghost", False)


# ===================================================================
# 5. _handle_custom_command
# ===================================================================


class TestHandleCustomCommand:
    """``drone <custom name>`` routes a registered custom command."""

    @patch("aipass.drone.apps.drone.route_command")
    def test_routes_matched_command(self, mock_route: MagicMock) -> None:
        """Should route a matched custom command through route_command.

        Mutant killed: main() skipping the custom-command match."""

        ops.add_command("audit", "@seedgo", "audit", args=["aipass"])

        mock_route.return_value = CommandResult(
            stdout="ok\n",
            stderr="",
            exit_code=0,
            branch="seedgo",
            command="audit",
        )

        result = _drone("audit")

        assert result == 0
        mock_route.assert_called_once_with(
            "@seedgo",
            "audit",
            args=["aipass"],
            timeout=None,
            interactive=True,
        )

    @patch("aipass.drone.apps.drone.route_command")
    def test_appends_remaining_args(self, mock_route: MagicMock) -> None:
        """Should append remaining args to configured args; mutant killed: main() skipping the custom-command match."""

        ops.add_command("audit", "@seedgo", "audit", args=["aipass"])

        mock_route.return_value = CommandResult(
            stdout="",
            stderr="",
            exit_code=0,
            branch="seedgo",
            command="audit",
        )

        result = _drone("audit", "@drone")

        assert result == 0
        mock_route.assert_called_once_with(
            "@seedgo",
            "audit",
            args=["aipass", "@drone"],
            timeout=None,
            interactive=True,
        )

    def test_an_unmatched_name_is_an_unknown_command(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """An unmatched name is an unknown command; mutant killed: an unmatched name returning 0 as if it had run."""
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text('{"metadata": {}, "branches": []}', encoding="utf-8")
        set_registry_path(registry)
        try:
            result = _drone("nonexistent")
        finally:
            reset_registry_path()

        assert result == 1
        assert "unknown command 'nonexistent'" in capsys.readouterr().err

    @patch("aipass.drone.apps.drone.route_command")
    def test_interactive_detection_for_command(self, mock_route: MagicMock) -> None:
        """Should set interactive=True for interactive commands.

        Mutant killed: main() skipping the custom-command match."""

        ops.add_command("mon", "@prax", "monitor")

        mock_route.return_value = CommandResult(
            stdout="",
            stderr="",
            exit_code=0,
            branch="prax",
            command="monitor",
        )

        _drone("mon")

        call_kwargs = mock_route.call_args.kwargs
        assert call_kwargs["interactive"] is True

    @patch("aipass.drone.apps.drone.route_command")
    def test_interactive_detection_for_branch(self, mock_route: MagicMock) -> None:
        """Should set interactive=True for CLI branch commands.

        Mutant killed: main() skipping the custom-command match."""

        ops.add_command("status", "@cli", "status")

        mock_route.return_value = CommandResult(
            stdout="",
            stderr="",
            exit_code=0,
            branch="cli",
            command="status",
        )

        _drone("status")

        call_kwargs = mock_route.call_args.kwargs
        assert call_kwargs["interactive"] is True

    @patch("aipass.drone.apps.drone.route_command")
    def test_watchdog_routes_interactive(self, mock_route: MagicMock) -> None:
        """watchdog command should route with interactive=True (long-running poller).

        Mutant killed: main() not routing '@target'."""

        mock_route.return_value = CommandResult(
            stdout="",
            stderr="",
            exit_code=0,
            branch="devpulse",
            command="watchdog",
        )

        _drone("@devpulse", "watchdog", "--help")

        call_kwargs = mock_route.call_args.kwargs
        assert call_kwargs["interactive"] is True

    @patch("aipass.drone.apps.drone.route_command")
    def test_propagates_exit_code(self, mock_route: MagicMock) -> None:
        """Should return the route_command exit code; mutant killed: main() skipping the custom-command match."""

        ops.add_command("failing", "@test", "fail")

        mock_route.return_value = CommandResult(
            stdout="",
            stderr="error\n",
            exit_code=2,
            branch="test",
            command="fail",
        )

        result = _drone("failing")

        assert result == 2

    @patch("aipass.drone.apps.drone.route_command")
    def test_handles_route_exception(self, mock_route: MagicMock) -> None:
        """Should return 1 when route_command raises; mutant killed: a failed custom route returning 0."""

        ops.add_command("bad", "@ghost", "cmd")

        mock_route.side_effect = BranchNotFoundError("not found")

        result = _drone("bad")

        assert result == 1

    @patch("aipass.drone.apps.drone.route_command")
    def test_a_failed_match_log_write_still_runs_the_matched_command(
        self,
        mock_route: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A failed operation log is never "registry could not load", and the warning names the command.

        Mutants killed: the log write unguarded; the warning removed (caplog assert)."""

        ops.add_command("audit", "@seedgo", "audit")
        mock_route.return_value = CommandResult(stdout="", stderr="", exit_code=0, branch="seedgo", command="audit")

        def broken_log(*_args: Any, **_kwargs: Any) -> bool:
            raise json_handler.InvalidDocument("log document is not a list")

        monkeypatch.setattr(json_handler, "log_operation", broken_log)

        result = _drone("audit")

        assert result == 0
        mock_route.assert_called_once_with("@seedgo", "audit", args=None, timeout=None, interactive=True)
        assert "could not load" not in capsys.readouterr().err
        assert "match log for 'audit' not written: log document is not a list" in caplog.text

    @patch("aipass.drone.apps.drone.route_command")
    def test_a_registry_that_cannot_load_is_named_and_exits_1(
        self, mock_route: MagicMock, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A registry that cannot load is named, exit 1, nothing routed, and it is not read as an unknown command.

        Mutants killed: the catch returns 0; the catch returns -1 (main then falls to
        "unknown command", also exit 1: only stderr tells the two apart)."""

        def unreadable() -> dict[str, Any]:
            raise OSError("registry unreadable")

        monkeypatch.setattr(lookup, "load_registry", unreadable)

        result = _drone("audit")

        assert result == 1
        mock_route.assert_not_called()
        err = capsys.readouterr().err
        assert "command registry could not load: registry unreadable" in err
        assert "unknown command" not in err

    @patch("aipass.drone.apps.drone.route_command")
    def test_no_args_passes_none(self, mock_route: MagicMock) -> None:
        """Should pass args=None when configured args and remaining args are both empty.

        Mutant killed: main() skipping the custom-command match."""

        ops.add_command("simple", "@test", "simple")

        mock_route.return_value = CommandResult(
            stdout="",
            stderr="",
            exit_code=0,
            branch="test",
            command="simple",
        )

        _drone("simple")

        call_kwargs = mock_route.call_args.kwargs
        assert call_kwargs["args"] is None


# ===================================================================
# 6. main() integration
# ===================================================================


class TestMainIntegration:
    """Tests for main() routing of new commands."""

    @patch("aipass.drone.apps.drone._handle_activate")
    def test_activate_route(self, mock_activate: MagicMock) -> None:
        """main() routes 'activate @branch' to _handle_activate."""

        mock_activate.return_value = 0

        with patch("sys.argv", ["drone", "activate", "@seedgo"]):
            result = main()

        assert result == 0
        mock_activate.assert_called_once_with("@seedgo")

    def test_activate_no_target(self) -> None:
        """main() returns 0 and shows help when activate has no target."""

        with patch("sys.argv", ["drone", "activate"]):
            result = main()

        assert result == 0

    @patch("aipass.drone.apps.drone._handle_list")
    def test_list_route(self, mock_list: MagicMock) -> None:
        """main() routes 'list' to _handle_list."""

        mock_list.return_value = 0

        with patch("sys.argv", ["drone", "list"]):
            result = main()

        assert result == 0
        mock_list.assert_called_once()

    @patch("aipass.drone.apps.drone._handle_remove")
    def test_remove_route(self, mock_remove: MagicMock) -> None:
        """main() routes 'remove name' to _handle_remove."""

        mock_remove.return_value = 0

        with patch("sys.argv", ["drone", "remove", "audit"]):
            result = main()

        assert result == 0
        mock_remove.assert_called_once_with("audit")

    def test_remove_no_name(self) -> None:
        """main() returns 1 when remove is called without a name."""

        with patch("sys.argv", ["drone", "remove"]):
            result = main()

        assert result == 1

    @patch("aipass.drone.apps.drone._handle_custom_command")
    def test_custom_command_route(self, mock_custom: MagicMock) -> None:
        """main() routes unrecognized commands to custom command matching."""

        mock_custom.return_value = 0

        with patch("sys.argv", ["drone", "audit"]):
            result = main()

        assert result == 0
        mock_custom.assert_called_once_with(["audit"])

    @patch("aipass.drone.apps.drone._handle_custom_command")
    def test_unknown_command_when_no_custom_match(self, mock_custom: MagicMock) -> None:
        """main() shows unknown command when custom matching returns -1."""

        mock_custom.return_value = -1

        with patch("sys.argv", ["drone", "nonexistent"]):
            result = main()

        assert result == 1

    @patch("aipass.drone.apps.drone.route_command")
    def test_custom_command_end_to_end(self, mock_route: MagicMock) -> None:
        """Full integration: registered command routes through route_command."""

        ops.add_command("audit", "@seedgo", "audit", args=["aipass"])

        mock_route.return_value = CommandResult(
            stdout="audit output\n",
            stderr="",
            exit_code=0,
            branch="seedgo",
            command="audit",
        )

        with patch("sys.argv", ["drone", "audit"]):
            result = main()

        assert result == 0
        mock_route.assert_called_once_with(
            "@seedgo",
            "audit",
            args=["aipass"],
            timeout=None,
            interactive=True,
        )

    @patch("aipass.drone.apps.drone.route_command")
    def test_custom_command_with_extra_args_end_to_end(self, mock_route: MagicMock) -> None:
        """Full integration: remaining args appended to configured args."""

        ops.add_command("audit", "@seedgo", "audit", args=["aipass"])

        mock_route.return_value = CommandResult(
            stdout="",
            stderr="",
            exit_code=0,
            branch="seedgo",
            command="audit",
        )

        with patch("sys.argv", ["drone", "audit", "@drone"]):
            result = main()

        assert result == 0
        mock_route.assert_called_once_with(
            "@seedgo",
            "audit",
            args=["aipass", "@drone"],
            timeout=None,
            interactive=True,
        )

    def test_builtin_commands_take_priority(self) -> None:
        """Built-in commands like 'systems' should NOT be overridden by custom commands."""

        # Register a custom command named 'systems' (should be shadowed)
        ops.add_command("systems", "@test", "systems")

        with patch("aipass.drone.apps.drone._handle_systems", return_value=0) as mock_sys:
            with patch("sys.argv", ["drone", "systems"]):
                result = main()

        assert result == 0
        mock_sys.assert_called_once()

    def test_at_target_takes_priority_over_custom(self) -> None:
        """@target routing should take priority over custom command matching."""

        with patch("aipass.drone.apps.drone._handle_target", return_value=0) as mock_target:
            with patch("sys.argv", ["drone", "@seedgo", "audit"]):
                result = main()

        assert result == 0
        mock_target.assert_called_once()


# ===================================================================
# 7. match_command integration
# ===================================================================


class TestMatchCommandIntegration:
    """Tests verifying match_command works correctly with registered commands."""

    def test_multi_word_custom_command(self) -> None:
        """Multi-word commands should match and leave remaining args."""
        ops.add_command("plan create", "@flow", "create", args=["--type=plan"])

        result = lookup.match_command(["plan", "create", "my-plan"])

        assert result is not None
        cmd, remaining = result
        assert cmd["name"] == "plan create"
        assert cmd["target"] == "@flow"
        assert remaining == ["my-plan"]

    @patch("aipass.drone.apps.drone.route_command")
    def test_multi_word_end_to_end(self, mock_route: MagicMock) -> None:
        """Multi-word custom command routes correctly through main()."""

        ops.add_command("plan create", "@flow", "create", args=["--type=plan"])

        mock_route.return_value = CommandResult(
            stdout="created\n",
            stderr="",
            exit_code=0,
            branch="flow",
            command="create",
        )

        with patch("sys.argv", ["drone", "plan", "create", "my-plan"]):
            result = main()

        assert result == 0
        mock_route.assert_called_once_with(
            "@flow",
            "create",
            args=["--type=plan", "my-plan"],
            timeout=None,
            interactive=False,
        )
