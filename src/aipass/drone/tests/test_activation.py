# =================== AIPass ====================
# Name: test_activation.py
# Description: Tests for command activation, listing, removal, and custom execution
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""Tests for command activation, listing, removal, and custom execution.

Covers:
- ``drone activate @branch`` registers discovered commands
- ``drone list`` displays custom commands
- ``drone remove <name>`` removes a custom command
- Custom command execution via ``main()`` flow
- ``match_command`` integration with ``route_command``
- Formatter output for activation, listing, removal
"""

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
    """Tests for _handle_activate() in drone.py."""

    @patch("aipass.drone.apps.drone._handle_activate.__wrapped__", create=True)
    def _get_handler(self):
        """Import the handler to test."""
        from aipass.drone.apps.drone import _handle_activate

        return _handle_activate

    @patch("aipass.drone.apps.modules.commands.format_activation_results")
    @patch("aipass.drone.apps.modules.commands.add")
    @patch("aipass.drone.apps.modules.scan.scan")
    def test_registers_discovered_commands(
        self,
        mock_scan: MagicMock,
        mock_add: MagicMock,
        mock_format: MagicMock,
    ) -> None:
        """Should register all commands discovered by scan."""
        from aipass.drone.apps.drone import _handle_activate

        mock_scan.return_value = [
            {"name": "audit", "description": "Run audit", "source": "help"},
            {"name": "list", "description": "List items", "source": "module"},
        ]
        mock_add.return_value = True

        result = _handle_activate("@seedgo")

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
        """Should skip commands that already exist in registry."""
        from aipass.drone.apps.drone import _handle_activate

        mock_scan.return_value = [
            {"name": "audit", "description": "Run audit", "source": "help"},
        ]
        mock_add.return_value = False  # Already exists

        result = _handle_activate("@seedgo")

        assert result == 0
        call_args = mock_format.call_args
        assert call_args[0][1] == []  # added = empty
        assert "audit" in call_args[0][2]  # skipped list

    @patch("aipass.drone.apps.modules.scan.scan")
    def test_returns_1_on_resolution_failure(self, mock_scan: MagicMock) -> None:
        """Should return 1 when scan cannot resolve the target."""
        from aipass.drone.apps.drone import _handle_activate

        mock_scan.return_value = None

        result = _handle_activate("@nonexistent")

        assert result == 1

    @patch("aipass.drone.apps.modules.scan.scan")
    def test_returns_0_on_empty_scan(self, mock_scan: MagicMock) -> None:
        """Should return 0 when scan finds no commands."""
        from aipass.drone.apps.drone import _handle_activate

        mock_scan.return_value = []

        result = _handle_activate("@emptybranch")

        assert result == 0


# ===================================================================
# 3. _handle_list
# ===================================================================


class TestHandleList:
    """Tests for _handle_list() in drone.py."""

    @patch("aipass.drone.apps.modules.commands.format_command_list")
    def test_calls_formatter(self, mock_format: MagicMock) -> None:
        """Should load commands and pass to formatter."""
        from aipass.drone.apps.drone import _handle_list

        ops.add_command("audit", "@seedgo", "audit")

        result = _handle_list()

        assert result == 0
        mock_format.assert_called_once()
        commands_arg = mock_format.call_args[0][0]
        assert len(commands_arg) == 1
        assert commands_arg[0]["name"] == "audit"

    @patch("aipass.drone.apps.modules.commands.format_command_list")
    def test_empty_registry(self, mock_format: MagicMock) -> None:
        """Should pass empty list to formatter when no commands exist."""
        from aipass.drone.apps.drone import _handle_list

        result = _handle_list()

        assert result == 0
        mock_format.assert_called_once_with([])


# ===================================================================
# 4. _handle_remove
# ===================================================================


class TestHandleRemove:
    """Tests for _handle_remove() in drone.py."""

    @patch("aipass.drone.apps.modules.commands.format_removal")
    def test_removes_existing(self, mock_format: MagicMock) -> None:
        """Should remove an existing command and return 0."""
        from aipass.drone.apps.drone import _handle_remove

        ops.add_command("audit", "@seedgo", "audit")

        result = _handle_remove("audit")

        assert result == 0
        mock_format.assert_called_once_with("audit", True)
        assert not ops.command_exists("audit")

    @patch("aipass.drone.apps.modules.commands.format_removal")
    def test_nonexistent_returns_1(self, mock_format: MagicMock) -> None:
        """Should return 1 when trying to remove a nonexistent command."""
        from aipass.drone.apps.drone import _handle_remove

        result = _handle_remove("ghost")

        assert result == 1
        mock_format.assert_called_once_with("ghost", False)


# ===================================================================
# 5. _handle_custom_command
# ===================================================================


class TestHandleCustomCommand:
    """Tests for _handle_custom_command() in drone.py."""

    @patch("aipass.drone.apps.drone.route_command")
    def test_routes_matched_command(self, mock_route: MagicMock) -> None:
        """Should route a matched custom command through route_command."""
        from aipass.drone.apps.drone import _handle_custom_command

        ops.add_command("audit", "@seedgo", "audit", args=["aipass"])

        mock_route.return_value = CommandResult(
            stdout="ok\n",
            stderr="",
            exit_code=0,
            branch="seedgo",
            command="audit",
        )

        result = _handle_custom_command(["audit"])

        assert result == 0
        mock_route.assert_called_once_with(
            "@seedgo",
            "audit",
            args=["aipass"],
            interactive=True,
        )

    @patch("aipass.drone.apps.drone.route_command")
    def test_appends_remaining_args(self, mock_route: MagicMock) -> None:
        """Should append remaining args to configured args."""
        from aipass.drone.apps.drone import _handle_custom_command

        ops.add_command("audit", "@seedgo", "audit", args=["aipass"])

        mock_route.return_value = CommandResult(
            stdout="",
            stderr="",
            exit_code=0,
            branch="seedgo",
            command="audit",
        )

        result = _handle_custom_command(["audit", "@drone"])

        assert result == 0
        mock_route.assert_called_once_with(
            "@seedgo",
            "audit",
            args=["aipass", "@drone"],
            interactive=True,
        )

    def test_returns_negative_1_on_no_match(self) -> None:
        """Should return -1 when no custom command matches."""
        from aipass.drone.apps.drone import _handle_custom_command

        result = _handle_custom_command(["nonexistent"])

        assert result == -1

    @patch("aipass.drone.apps.drone.route_command")
    def test_interactive_detection_for_command(self, mock_route: MagicMock) -> None:
        """Should set interactive=True for interactive commands."""
        from aipass.drone.apps.drone import _handle_custom_command

        ops.add_command("mon", "@prax", "monitor")

        mock_route.return_value = CommandResult(
            stdout="",
            stderr="",
            exit_code=0,
            branch="prax",
            command="monitor",
        )

        _handle_custom_command(["mon"])

        call_kwargs = mock_route.call_args.kwargs
        assert call_kwargs["interactive"] is True

    @patch("aipass.drone.apps.drone.route_command")
    def test_interactive_detection_for_branch(self, mock_route: MagicMock) -> None:
        """Should set interactive=True for CLI branch commands."""
        from aipass.drone.apps.drone import _handle_custom_command

        ops.add_command("status", "@cli", "status")

        mock_route.return_value = CommandResult(
            stdout="",
            stderr="",
            exit_code=0,
            branch="cli",
            command="status",
        )

        _handle_custom_command(["status"])

        call_kwargs = mock_route.call_args.kwargs
        assert call_kwargs["interactive"] is True

    @patch("aipass.drone.apps.drone.route_command")
    def test_watchdog_routes_interactive(self, mock_route: MagicMock) -> None:
        """watchdog command should route with interactive=True (long-running poller)."""
        from aipass.drone.apps.drone import _handle_target

        mock_route.return_value = CommandResult(
            stdout="",
            stderr="",
            exit_code=0,
            branch="devpulse",
            command="watchdog",
        )

        _handle_target(["@devpulse", "watchdog", "--help"])

        call_kwargs = mock_route.call_args.kwargs
        assert call_kwargs["interactive"] is True

    @patch("aipass.drone.apps.drone.route_command")
    def test_propagates_exit_code(self, mock_route: MagicMock) -> None:
        """Should return the route_command exit code."""
        from aipass.drone.apps.drone import _handle_custom_command

        ops.add_command("failing", "@test", "fail")

        mock_route.return_value = CommandResult(
            stdout="",
            stderr="error\n",
            exit_code=2,
            branch="test",
            command="fail",
        )

        result = _handle_custom_command(["failing"])

        assert result == 2

    @patch("aipass.drone.apps.drone.route_command")
    def test_handles_route_exception(self, mock_route: MagicMock) -> None:
        """Should return 1 when route_command raises."""
        from aipass.drone.apps.drone import _handle_custom_command
        from aipass.drone.apps.modules import BranchNotFoundError

        ops.add_command("bad", "@ghost", "cmd")

        mock_route.side_effect = BranchNotFoundError("not found")

        result = _handle_custom_command(["bad"])

        assert result == 1

    @patch("aipass.drone.apps.drone.route_command")
    def test_no_args_passes_none(self, mock_route: MagicMock) -> None:
        """Should pass args=None when configured args and remaining args are both empty."""
        from aipass.drone.apps.drone import _handle_custom_command

        ops.add_command("simple", "@test", "simple")

        mock_route.return_value = CommandResult(
            stdout="",
            stderr="",
            exit_code=0,
            branch="test",
            command="simple",
        )

        _handle_custom_command(["simple"])

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
        from aipass.drone.apps.drone import main

        mock_activate.return_value = 0

        with patch("sys.argv", ["drone", "activate", "@seedgo"]):
            result = main()

        assert result == 0
        mock_activate.assert_called_once_with("@seedgo")

    def test_activate_no_target(self) -> None:
        """main() returns 0 and shows help when activate has no target."""
        from aipass.drone.apps.drone import main

        with patch("sys.argv", ["drone", "activate"]):
            result = main()

        assert result == 0

    @patch("aipass.drone.apps.drone._handle_list")
    def test_list_route(self, mock_list: MagicMock) -> None:
        """main() routes 'list' to _handle_list."""
        from aipass.drone.apps.drone import main

        mock_list.return_value = 0

        with patch("sys.argv", ["drone", "list"]):
            result = main()

        assert result == 0
        mock_list.assert_called_once()

    @patch("aipass.drone.apps.drone._handle_remove")
    def test_remove_route(self, mock_remove: MagicMock) -> None:
        """main() routes 'remove name' to _handle_remove."""
        from aipass.drone.apps.drone import main

        mock_remove.return_value = 0

        with patch("sys.argv", ["drone", "remove", "audit"]):
            result = main()

        assert result == 0
        mock_remove.assert_called_once_with("audit")

    def test_remove_no_name(self) -> None:
        """main() returns 1 when remove is called without a name."""
        from aipass.drone.apps.drone import main

        with patch("sys.argv", ["drone", "remove"]):
            result = main()

        assert result == 1

    @patch("aipass.drone.apps.drone._handle_custom_command")
    def test_custom_command_route(self, mock_custom: MagicMock) -> None:
        """main() routes unrecognized commands to custom command matching."""
        from aipass.drone.apps.drone import main

        mock_custom.return_value = 0

        with patch("sys.argv", ["drone", "audit"]):
            result = main()

        assert result == 0
        mock_custom.assert_called_once_with(["audit"])

    @patch("aipass.drone.apps.drone._handle_custom_command")
    def test_unknown_command_when_no_custom_match(self, mock_custom: MagicMock) -> None:
        """main() shows unknown command when custom matching returns -1."""
        from aipass.drone.apps.drone import main

        mock_custom.return_value = -1

        with patch("sys.argv", ["drone", "nonexistent"]):
            result = main()

        assert result == 1

    @patch("aipass.drone.apps.drone.route_command")
    def test_custom_command_end_to_end(self, mock_route: MagicMock) -> None:
        """Full integration: registered command routes through route_command."""
        from aipass.drone.apps.drone import main

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
            interactive=True,
        )

    @patch("aipass.drone.apps.drone.route_command")
    def test_custom_command_with_extra_args_end_to_end(self, mock_route: MagicMock) -> None:
        """Full integration: remaining args appended to configured args."""
        from aipass.drone.apps.drone import main

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
            interactive=True,
        )

    def test_builtin_commands_take_priority(self) -> None:
        """Built-in commands like 'systems' should NOT be overridden by custom commands."""
        from aipass.drone.apps.drone import main

        # Register a custom command named 'systems' (should be shadowed)
        ops.add_command("systems", "@test", "systems")

        with patch("aipass.drone.apps.drone._handle_systems", return_value=0) as mock_sys:
            with patch("sys.argv", ["drone", "systems"]):
                result = main()

        assert result == 0
        mock_sys.assert_called_once()

    def test_at_target_takes_priority_over_custom(self) -> None:
        """@target routing should take priority over custom command matching."""
        from aipass.drone.apps.drone import main

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
        from aipass.drone.apps.drone import main

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
            interactive=False,
        )
