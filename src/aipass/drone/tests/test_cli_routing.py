# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: CLI Routing Tests for Drone (adapted from universal template)
# Version: 1.0.0
# Created: 2026-03-27
# Modified: 2026-03-27
# =============================================

"""
CLI Routing Tests for Drone

Drone's CLI entry point is apps/drone.py (not cli_handler.py).
This file tests print_help, print_introspection, and short_help (-h)
using drone.py's functions directly.

Covers the 2 missing CLI routing items:
  - short_help (CR-002)
  - print_help (CR-007)
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def test_print_help(capsys: pytest.CaptureFixture[str]) -> None:  # CR-007
    """print_help() runs without error and produces stdout output."""
    from aipass.drone.apps.drone import print_help

    print_help()
    captured = capsys.readouterr()
    assert len(captured.out) > 0, "print_help() must produce output"


def test_print_introspection(capsys: pytest.CaptureFixture[str]) -> None:  # CR-008
    """print_introspection() runs without error and produces stdout output."""
    from aipass.drone.apps.drone import print_introspection

    print_introspection()
    captured = capsys.readouterr()
    assert len(captured.out) > 0, "print_introspection() must produce output"


def test_short_help() -> None:  # CR-002
    """drone -h flag triggers help and exits cleanly."""
    from aipass.drone.apps.drone import main

    with patch.object(sys, "argv", ["drone", "-h"]):
        result = main()
    assert result == 0, "drone -h must return exit code 0"


# ===========================================================================
# main() dispatch — version, help, introspection
# ===========================================================================

_DRONE = "aipass.drone.apps.drone"


class TestMainVersion:
    """drone --version and -V flags."""

    def test_version_long_flag(self) -> None:
        """--version prints version and returns 0."""
        from aipass.drone.apps.drone import main

        with patch.object(sys, "argv", ["drone", "--version"]):
            result = main()
        assert result == 0

    def test_version_short_flag(self) -> None:
        """-V prints version and returns 0."""
        from aipass.drone.apps.drone import main

        with patch.object(sys, "argv", ["drone", "-V"]):
            result = main()
        assert result == 0


class TestMainHelp:
    """drone --help, -h, and help command."""

    def test_help_long_flag(self) -> None:
        """--help returns 0."""
        from aipass.drone.apps.drone import main

        with patch.object(sys, "argv", ["drone", "--help"]):
            result = main()
        assert result == 0

    def test_help_word(self) -> None:
        """bare 'help' returns 0."""
        from aipass.drone.apps.drone import main

        with patch.object(sys, "argv", ["drone", "help"]):
            result = main()
        assert result == 0


class TestMainNoArgs:
    """drone with no args shows introspection."""

    def test_no_args_introspection(self) -> None:
        """No args calls print_introspection and returns 0."""
        from aipass.drone.apps.drone import main

        with (
            patch.object(sys, "argv", ["drone"]),
            patch(f"{_DRONE}.print_introspection"),
        ):
            result = main()
        assert result == 0

    def test_no_args_registry_error(self) -> None:
        """RegistryError during introspection returns 1."""
        from aipass.drone.apps.drone import main
        from aipass.drone.apps.modules import RegistryError

        with (
            patch.object(sys, "argv", ["drone"]),
            patch(
                f"{_DRONE}.print_introspection",
                side_effect=RegistryError("no registry"),
            ),
        ):
            result = main()
        assert result == 1


# ===========================================================================
# main() dispatch — built-in commands
# ===========================================================================


class TestMainSystems:
    """drone systems command."""

    def test_systems_success(self) -> None:
        """systems delegates to _handle_systems and returns 0."""
        from aipass.drone.apps.drone import main

        with (
            patch.object(sys, "argv", ["drone", "systems"]),
            patch(f"{_DRONE}._handle_systems", return_value=0) as mock_sys,
        ):
            result = main()
        assert result == 0
        mock_sys.assert_called_once()

    def test_systems_registry_error(self) -> None:
        """RegistryError in systems returns 1."""
        from aipass.drone.apps.drone import main
        from aipass.drone.apps.modules import RegistryError

        with (
            patch.object(sys, "argv", ["drone", "systems"]),
            patch(
                f"{_DRONE}._handle_systems",
                side_effect=RegistryError("broken"),
            ),
        ):
            result = main()
        assert result == 1

    def test_systems_unexpected_error(self) -> None:
        """Unexpected Exception in systems returns 1."""
        from aipass.drone.apps.drone import main

        with (
            patch.object(sys, "argv", ["drone", "systems"]),
            patch(
                f"{_DRONE}._handle_systems",
                side_effect=RuntimeError("boom"),
            ),
        ):
            result = main()
        assert result == 1


class TestMainScan:
    """drone scan command."""

    def test_scan_no_target(self) -> None:
        """scan with no target returns 1."""
        from aipass.drone.apps.drone import main

        with patch.object(sys, "argv", ["drone", "scan"]):
            result = main()
        assert result == 1

    def test_scan_success(self) -> None:
        """scan with target delegates to scan module."""
        from aipass.drone.apps.drone import main

        with (
            patch.object(sys, "argv", ["drone", "scan", "@seedgo"]),
            patch(
                "aipass.drone.apps.modules.scan.scan",
                return_value=[{"name": "audit"}],
            ),
        ):
            result = main()
        assert result == 0

    def test_scan_failure(self) -> None:
        """scan returning None means failure -> exit 1."""
        from aipass.drone.apps.drone import main

        with (
            patch.object(sys, "argv", ["drone", "scan", "@seedgo"]),
            patch("aipass.drone.apps.modules.scan.scan", return_value=None),
        ):
            result = main()
        assert result == 1


class TestMainActivate:
    """drone activate command."""

    def test_activate_no_target(self) -> None:
        """activate with no target shows help and returns 0."""
        from aipass.drone.apps.drone import main

        with patch.object(sys, "argv", ["drone", "activate"]):
            result = main()
        assert result == 0

    def test_activate_help_flag(self) -> None:
        """activate --help shows help and returns 0."""
        from aipass.drone.apps.drone import main

        with patch.object(sys, "argv", ["drone", "activate", "--help"]):
            result = main()
        assert result == 0

    def test_activate_with_target(self) -> None:
        """activate with target delegates to _handle_activate."""
        from aipass.drone.apps.drone import main

        with (
            patch.object(sys, "argv", ["drone", "activate", "@seedgo"]),
            patch(f"{_DRONE}._handle_activate", return_value=0) as mock_act,
        ):
            result = main()
        assert result == 0
        mock_act.assert_called_once_with("@seedgo")


class TestMainList:
    """drone list command."""

    def test_list_delegates(self) -> None:
        """list delegates to _handle_list."""
        from aipass.drone.apps.drone import main

        with (
            patch.object(sys, "argv", ["drone", "list"]),
            patch(f"{_DRONE}._handle_list", return_value=0) as mock_list,
        ):
            result = main()
        assert result == 0
        mock_list.assert_called_once()


class TestMainRemove:
    """drone remove command."""

    def test_remove_no_name(self) -> None:
        """remove with no name returns 1."""
        from aipass.drone.apps.drone import main

        with patch.object(sys, "argv", ["drone", "remove"]):
            result = main()
        assert result == 1

    def test_remove_with_name(self) -> None:
        """remove with name delegates to _handle_remove."""
        from aipass.drone.apps.drone import main

        with (
            patch.object(sys, "argv", ["drone", "remove", "audit"]),
            patch(f"{_DRONE}._handle_remove", return_value=0) as mock_rm,
        ):
            result = main()
        assert result == 0
        mock_rm.assert_called_once_with("audit")


class TestMainAtTarget:
    """drone @target routing."""

    def test_at_target_delegates(self) -> None:
        """@target routes to _handle_target."""
        from aipass.drone.apps.drone import main

        with (
            patch.object(sys, "argv", ["drone", "@seedgo", "audit"]),
            patch(f"{_DRONE}._handle_target", return_value=0) as mock_tgt,
        ):
            result = main()
        assert result == 0
        mock_tgt.assert_called_once_with(["@seedgo", "audit"])


class TestMainModuleRouting:
    """drone bare module name routing."""

    def test_discovered_module_bool_true(self) -> None:
        """Discovered module returning True yields exit 0."""
        from aipass.drone.apps.drone import main

        mock_mod = type(sys)("fake_mod")
        mock_mod.handle_command = lambda cmd, args: True

        with (
            patch.object(sys, "argv", ["drone", "config", "list"]),
            patch(
                f"{_DRONE}._discover_modules",
                return_value=[("config", "Config module")],
            ),
            patch(
                f"{_DRONE}.importlib.import_module",
                return_value=mock_mod,
            ),
        ):
            result = main()
        assert result == 0

    def test_discovered_module_bool_false(self) -> None:
        """Discovered module returning False yields exit 1."""
        from aipass.drone.apps.drone import main

        mock_mod = type(sys)("fake_mod")
        mock_mod.handle_command = lambda cmd, args: False

        with (
            patch.object(sys, "argv", ["drone", "config", "broken"]),
            patch(
                f"{_DRONE}._discover_modules",
                return_value=[("config", "Config module")],
            ),
            patch(
                f"{_DRONE}.importlib.import_module",
                return_value=mock_mod,
            ),
        ):
            result = main()
        assert result == 1

    def test_discovered_module_dict_result(self) -> None:
        """Discovered module returning dict uses stdout/stderr/exit_code."""
        from aipass.drone.apps.drone import main

        mock_mod = type(sys)("fake_mod")
        mock_mod.handle_command = lambda cmd, args: {
            "stdout": "output",
            "stderr": "",
            "exit_code": 0,
        }

        with (
            patch.object(sys, "argv", ["drone", "config", "list"]),
            patch(
                f"{_DRONE}._discover_modules",
                return_value=[("config", "Config module")],
            ),
            patch(
                f"{_DRONE}.importlib.import_module",
                return_value=mock_mod,
            ),
        ):
            result = main()
        assert result == 0

    def test_discovered_module_exception(self) -> None:
        """Module raising exception returns 1."""
        from aipass.drone.apps.drone import main

        with (
            patch.object(sys, "argv", ["drone", "config", "list"]),
            patch(
                f"{_DRONE}._discover_modules",
                return_value=[("config", "Config module")],
            ),
            patch(
                f"{_DRONE}.importlib.import_module",
                side_effect=ImportError("nope"),
            ),
        ):
            result = main()
        assert result == 1


class TestMainCustomCommand:
    """drone custom command matching fallback."""

    def test_custom_command_matched(self) -> None:
        """Custom command matched returns its result."""
        from aipass.drone.apps.drone import main

        with (
            patch.object(sys, "argv", ["drone", "audit", "aipass"]),
            patch(f"{_DRONE}._discover_modules", return_value=[]),
            patch(f"{_DRONE}._handle_custom_command", return_value=0),
        ):
            result = main()
        assert result == 0

    def test_custom_command_not_matched(self) -> None:
        """Unmatched command falls through to unknown."""
        from aipass.drone.apps.drone import main

        with (
            patch.object(sys, "argv", ["drone", "nonexistent_cmd"]),
            patch(f"{_DRONE}._discover_modules", return_value=[]),
            patch(f"{_DRONE}._handle_custom_command", return_value=-1),
            patch(
                "aipass.drone.apps.modules.resolver.branch_exists",
                return_value=False,
            ),
        ):
            result = main()
        assert result == 1


class TestMainUnknownCommand:
    """drone unknown command handling with branch hint."""

    def test_unknown_bare_branch_name(self) -> None:
        """Bare branch name shows @ prefix hint."""
        from aipass.drone.apps.drone import main

        with (
            patch.object(sys, "argv", ["drone", "seedgo"]),
            patch(f"{_DRONE}._discover_modules", return_value=[]),
            patch(f"{_DRONE}._handle_custom_command", return_value=-1),
            patch(
                "aipass.drone.apps.modules.resolver.branch_exists",
                return_value=True,
            ),
        ):
            result = main()
        assert result == 1

    def test_unknown_branch_check_fails(self) -> None:
        """Exception in branch_exists doesn't crash -- still returns 1."""
        from aipass.drone.apps.drone import main

        with (
            patch.object(sys, "argv", ["drone", "broken_cmd"]),
            patch(f"{_DRONE}._discover_modules", return_value=[]),
            patch(f"{_DRONE}._handle_custom_command", return_value=-1),
            patch(
                "aipass.drone.apps.modules.resolver.branch_exists",
                side_effect=Exception("boom"),
            ),
        ):
            result = main()
        assert result == 1


# ===========================================================================
# _handle_systems() paths
# ===========================================================================


class TestHandleSystems:
    """_handle_systems() logic paths."""

    def test_no_registry(self) -> None:
        """No registry in CWD tree returns 0 with message."""
        from aipass.drone.apps.drone import _handle_systems

        with patch(f"{_DRONE}._cwd_has_registry", return_value=False):
            result = _handle_systems()
        assert result == 0

    def test_with_branches_and_modules(self) -> None:
        """Normal case with modules and branches."""
        from aipass.drone.apps.drone import _handle_systems

        branches = [
            {"name": "drone", "profile": "library", "description": "Router"},
            {"name": "myapp", "profile": "agent"},
        ]
        with (
            patch(f"{_DRONE}._cwd_has_registry", return_value=True),
            patch(f"{_DRONE}.get_all_branches", return_value=branches),
            patch(f"{_DRONE}.list_modules", return_value=["git"]),
            patch(
                f"{_DRONE}.get_module_info",
                return_value=type("I", (), {"description": "Git ops"})(),
            ),
        ):
            result = _handle_systems()
        assert result == 0

    def test_aipass_home_hint(self) -> None:
        """Shows hint when AIPASS_HOME not set and drone not in branches."""
        import os

        from aipass.drone.apps.drone import _handle_systems

        with (
            patch(f"{_DRONE}._cwd_has_registry", return_value=True),
            patch(f"{_DRONE}.get_all_branches", return_value=[]),
            patch(f"{_DRONE}.list_modules", return_value=[]),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("AIPASS_HOME", None)
            result = _handle_systems()
        assert result == 0


# ===========================================================================
# _handle_module() paths
# ===========================================================================


class TestHandleModule:
    """_handle_module() introspection, help, and command routing."""

    def test_no_args_introspection(self) -> None:
        """No args shows introspection text."""
        from aipass.drone.apps.drone import _handle_module

        with patch(
            f"{_DRONE}.get_module_introspective",
            return_value="Module info",
        ):
            result = _handle_module("git", [])
        assert result == 0

    def test_no_args_no_introspection(self) -> None:
        """No args with empty introspection text shows fallback."""
        from aipass.drone.apps.drone import _handle_module

        with patch(f"{_DRONE}.get_module_introspective", return_value=""):
            result = _handle_module("git", [])
        assert result == 0

    def test_help_flag(self) -> None:
        """--help shows help text."""
        from aipass.drone.apps.drone import _handle_module

        with patch(f"{_DRONE}.get_module_help", return_value="Help text"):
            result = _handle_module("git", ["--help"])
        assert result == 0

    def test_help_no_text(self) -> None:
        """--help with no text shows fallback."""
        from aipass.drone.apps.drone import _handle_module

        with patch(f"{_DRONE}.get_module_help", return_value=""):
            result = _handle_module("git", ["--help"])
        assert result == 0

    def test_command_routing(self) -> None:
        """Command routes through route_module_command."""
        from aipass.drone.apps.drone import _handle_module

        with patch(
            f"{_DRONE}.route_module_command",
            return_value={"stdout": "ok", "stderr": "", "exit_code": 0},
        ):
            result = _handle_module("git", ["status"])
        assert result == 0

    def test_command_import_error(self) -> None:
        """ImportError during module command returns 1."""
        from aipass.drone.apps.drone import _handle_module

        with patch(
            f"{_DRONE}.route_module_command",
            side_effect=ImportError("missing"),
        ):
            result = _handle_module("git", ["status"])
        assert result == 1


# ===========================================================================
# _handle_target() paths
# ===========================================================================


class TestHandleTarget:
    """_handle_target() routing for @branch commands."""

    def test_module_route(self) -> None:
        """Module target (non-interactive) routes to _handle_module."""
        from aipass.drone.apps.drone import _handle_target

        with (
            patch(f"{_DRONE}.is_module", return_value=True),
            patch(f"{_DRONE}._handle_module", return_value=0) as mock_hm,
        ):
            result = _handle_target(["@git", "diff"])
        assert result == 0
        mock_hm.assert_called_once_with("git", ["diff"])

    def test_no_args_introspection(self) -> None:
        """@target with no args routes via route_command with interactive=True."""
        from aipass.drone.apps.drone import _handle_target
        from aipass.drone.apps.handlers.executor import CommandResult

        mock_result = CommandResult(
            stdout="",
            stderr="",
            exit_code=0,
            branch="seedgo",
            command="",
        )
        with (
            patch(f"{_DRONE}.is_module", return_value=False),
            patch(f"{_DRONE}.route_command", return_value=mock_result) as mock_route,
        ):
            result = _handle_target(["@seedgo"])
        assert result == 0
        mock_route.assert_called_once_with("@seedgo", interactive=True)

    def test_help_flag(self) -> None:
        """@target --help routes via route_command with interactive=True."""
        from aipass.drone.apps.drone import _handle_target
        from aipass.drone.apps.handlers.executor import CommandResult

        mock_result = CommandResult(
            stdout="",
            stderr="",
            exit_code=0,
            branch="seedgo",
            command="--help",
        )
        with (
            patch(f"{_DRONE}.is_module", return_value=False),
            patch(f"{_DRONE}.route_command", return_value=mock_result) as mock_route,
        ):
            result = _handle_target(["@seedgo", "--help"])
        assert result == 0
        mock_route.assert_called_once_with("@seedgo", "--help", interactive=True)

    def test_command_routing(self) -> None:
        """@target command routes via route_command."""
        from aipass.drone.apps.drone import _handle_target
        from aipass.drone.apps.handlers.executor import CommandResult

        mock_result = CommandResult(
            stdout="output",
            stderr="",
            exit_code=0,
            branch="seedgo",
            command="audit",
        )
        with (
            patch(f"{_DRONE}.is_module", return_value=False),
            patch(f"{_DRONE}.route_command", return_value=mock_result),
        ):
            result = _handle_target(["@seedgo", "audit", "aipass"])
        assert result == 0

    def test_short_help_flag(self) -> None:
        """@target -h routes via route_command with interactive=True."""
        from aipass.drone.apps.drone import _handle_target
        from aipass.drone.apps.handlers.executor import CommandResult

        mock_result = CommandResult(stdout="", stderr="", exit_code=0, branch="seedgo", command="-h")
        with (
            patch(f"{_DRONE}.is_module", return_value=False),
            patch(f"{_DRONE}.route_command", return_value=mock_result) as mock_route,
        ):
            result = _handle_target(["@seedgo", "-h"])
        assert result == 0
        mock_route.assert_called_once_with("@seedgo", "-h", interactive=True)

    def test_status_routes_interactive(self) -> None:
        """status command routes with interactive=True for Rich color output."""
        from aipass.drone.apps.drone import _handle_target
        from aipass.drone.apps.handlers.executor import CommandResult

        mock_result = CommandResult(stdout="", stderr="", exit_code=0, branch="hooks", command="status")
        with (
            patch(f"{_DRONE}.is_module", return_value=False),
            patch(f"{_DRONE}.route_command", return_value=mock_result) as mock_route,
        ):
            result = _handle_target(["@hooks", "status"])
        assert result == 0
        call_kwargs = mock_route.call_args.kwargs
        assert call_kwargs["interactive"] is True

    def test_help_flag_module_fallback(self) -> None:
        """--help BranchNotFoundError for a module falls back to _handle_module."""
        from aipass.drone.apps.drone import _handle_target
        from aipass.drone.apps.modules import BranchNotFoundError

        with (
            patch(f"{_DRONE}.is_module", side_effect=[False, True]),
            patch(f"{_DRONE}.route_command", side_effect=BranchNotFoundError("not found")),
            patch(f"{_DRONE}._handle_module", return_value=0) as mock_hm,
        ):
            result = _handle_target(["@seedgo", "--help"])
        assert result == 0
        mock_hm.assert_called_once_with("seedgo", ["--help"])

    def test_branch_not_found_module_fallback(self) -> None:
        """BranchNotFoundError for a module falls back to _handle_module."""
        from aipass.drone.apps.drone import _handle_target
        from aipass.drone.apps.modules import BranchNotFoundError

        with (
            patch(f"{_DRONE}.is_module", side_effect=[False, True]),
            patch(
                f"{_DRONE}.route_command",
                side_effect=BranchNotFoundError("not found"),
            ),
            patch(f"{_DRONE}._handle_module", return_value=0) as mock_hm,
        ):
            result = _handle_target(["@seedgo", "audit"])
        assert result == 0
        mock_hm.assert_called_once()


# ===========================================================================
# _handle_custom_command() paths
# ===========================================================================


class TestHandleCustomCommand:
    """_handle_custom_command() matching and routing."""

    _MATCH = "aipass.drone.apps.modules.commands.match"

    def test_no_match(self) -> None:
        """No match returns -1 sentinel."""
        from aipass.drone.apps.drone import _handle_custom_command

        with patch(self._MATCH, return_value=None):
            result = _handle_custom_command(["unknown"])
        assert result == -1

    def test_matched_routes_success(self) -> None:
        """Matched command routes and returns exit code."""
        from aipass.drone.apps.drone import _handle_custom_command
        from aipass.drone.apps.handlers.executor import CommandResult

        cmd_data = {
            "target": "@seedgo",
            "command": "audit",
            "args": ["aipass"],
        }
        mock_result = CommandResult(
            stdout="ok",
            stderr="",
            exit_code=0,
            branch="seedgo",
            command="audit",
        )
        with (
            patch(self._MATCH, return_value=(cmd_data, [])),
            patch(f"{_DRONE}.route_command", return_value=mock_result),
        ):
            result = _handle_custom_command(["audit"])
        assert result == 0


# ===========================================================================
# Helper functions
# ===========================================================================


class TestReadInboxMessageId:
    """_read_inbox_message_id() edge cases."""

    def test_valid_index(self, tmp_path: Path) -> None:
        """Returns message ID for valid display-order index (reversed from array)."""
        inbox = tmp_path / "inbox.json"
        inbox.write_text(
            json.dumps({"messages": [{"id": "newest"}, {"id": "oldest"}]}),
            encoding="utf-8",
        )
        from aipass.drone.apps.drone import _read_inbox_message_id

        assert _read_inbox_message_id(inbox, 1) == "oldest"
        assert _read_inbox_message_id(inbox, 2) == "newest"

    def test_out_of_range(self, tmp_path: Path) -> None:
        """Returns None for out-of-range index."""
        inbox = tmp_path / "inbox.json"
        inbox.write_text(
            json.dumps({"messages": [{"id": "abc"}]}),
            encoding="utf-8",
        )
        from aipass.drone.apps.drone import _read_inbox_message_id

        assert _read_inbox_message_id(inbox, 5) is None
        assert _read_inbox_message_id(inbox, 0) is None

    def test_corrupt_file(self, tmp_path: Path) -> None:
        """Returns None for corrupt inbox."""
        inbox = tmp_path / "inbox.json"
        inbox.write_text("{bad json", encoding="utf-8")
        from aipass.drone.apps.drone import _read_inbox_message_id

        assert _read_inbox_message_id(inbox, 1) is None


class TestResolveMailToken:
    """_resolve_mail_token() — a real message ID always beats the index convenience.

    ai_mail IDs are str(uuid4())[:8] — 8 hex chars with no version nibble, so
    (10/16)^8 = 2.3% of them contain no a-f and are indistinguishable from an
    inbox index by shape alone. Reported live by @trigger 2026-08-13 after a
    message in their own inbox could not be opened by the ID the listing printed.
    """

    @staticmethod
    def _seat(tmp_path: Path, ids: list[str]) -> None:
        """Build a citizen seat with an inbox holding `ids` in array order."""
        (tmp_path / ".trinity").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
        (tmp_path / ".ai_mail.local").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".ai_mail.local" / "inbox.json").write_text(
            json.dumps({"messages": [{"id": i} for i in ids]}),
            encoding="utf-8",
        )

    def test_all_digit_id_resolves_to_itself(self, tmp_path: Path, monkeypatch) -> None:
        """An all-digit message ID is an ID, not an index — the reported bug."""
        self._seat(tmp_path, ["b7c79832", "04727185"])
        monkeypatch.chdir(tmp_path)
        from aipass.drone.apps.drone import _resolve_mail_token

        assert _resolve_mail_token("04727185") == "04727185"

    def test_id_wins_over_valid_index_collision(self, tmp_path: Path, monkeypatch) -> None:
        """An all-digit ID that is ALSO a valid index must not open another message.

        This is the silent half of the defect: no error, just the wrong mail.
        """
        self._seat(tmp_path, ["deadbeef", "00000002"])
        monkeypatch.chdir(tmp_path)
        from aipass.drone.apps.drone import _resolve_mail_token

        # Display index 2 would be "deadbeef" (array is reversed for display).
        assert _resolve_mail_token("00000002") == "00000002"

    def test_index_still_resolves_when_not_an_id(self, tmp_path: Path, monkeypatch) -> None:
        """The convenience survives: a bare index still maps to display order."""
        self._seat(tmp_path, ["newest", "oldest"])
        monkeypatch.chdir(tmp_path)
        from aipass.drone.apps.drone import _resolve_mail_token

        assert _resolve_mail_token("1") == "oldest"
        assert _resolve_mail_token("2") == "newest"

    def test_failed_resolution_preserves_original_token(self, tmp_path: Path, monkeypatch) -> None:
        """On failure return what the user typed — never int-round-trip it.

        str(int("08532166")) drops the leading zero, so the not-found error
        named an ID the user never typed. That mangling is what made the
        original report take a minute to read instead of a second.
        """
        self._seat(tmp_path, ["b7c79832"])
        monkeypatch.chdir(tmp_path)
        from aipass.drone.apps.drone import _resolve_mail_token

        assert _resolve_mail_token("08532166") == "08532166"

    def test_hex_id_passes_through(self, tmp_path: Path, monkeypatch) -> None:
        """A normal hex ID is returned untouched whether or not it is in the inbox."""
        self._seat(tmp_path, ["b7c79832"])
        monkeypatch.chdir(tmp_path)
        from aipass.drone.apps.drone import _resolve_mail_token

        assert _resolve_mail_token("b7c79832") == "b7c79832"
        assert _resolve_mail_token("c4d41074") == "c4d41074"

    def test_no_inbox_returns_token_unchanged(self, tmp_path: Path, monkeypatch) -> None:
        """No seat, no inbox — pass the token through rather than inventing one."""
        monkeypatch.chdir(tmp_path)
        from aipass.drone.apps.drone import _resolve_mail_token

        assert _resolve_mail_token("04727185") == "04727185"
        assert _resolve_mail_token("3") == "3"


class TestDiscoverModules:
    """_discover_modules() auto-discovery."""

    def test_discovers_modules_with_handle_command(self) -> None:
        """Modules with handle_command are discovered."""
        from aipass.drone.apps.drone import _discover_modules

        result = _discover_modules()
        names = [m[0] for m in result]
        assert "git_module" in names
        assert "resolver" in names

    def test_skips_private_files(self) -> None:
        """Files starting with _ are skipped."""
        from aipass.drone.apps.drone import _discover_modules

        result = _discover_modules()
        names = [m[0] for m in result]
        assert "__init__" not in names


class TestCliEntryPoint:
    """cli.py entry point."""

    def test_cli_main_calls_drone_main(self) -> None:
        """cli.main() calls drone main and exits."""
        from aipass.drone.cli import main as cli_main

        with (
            patch("aipass.drone.cli._drone_main", return_value=0),
            pytest.raises(SystemExit) as exc_info,
        ):
            cli_main()
        assert exc_info.value.code == 0


# ===========================================================================
# aipass intercept — drone aipass / drone @aipass
# ===========================================================================


class TestAipassIntercept:
    """'aipass' is a user CLI, not a drone-routable branch."""

    def test_bare_aipass_shows_guidance(self, capsys: pytest.CaptureFixture[str]) -> None:
        """'drone aipass' prints guidance to stderr."""
        from aipass.drone.apps.drone import main

        with patch("sys.argv", ["drone", "aipass"]):
            result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "aipass isn't reachable through drone" in captured.err
        assert "aipass --help" in captured.err

    def test_at_aipass_shows_guidance(self, capsys: pytest.CaptureFixture[str]) -> None:
        """'drone @aipass' prints guidance to stderr."""
        from aipass.drone.apps.drone import main

        with patch("sys.argv", ["drone", "@aipass"]):
            result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "aipass isn't reachable through drone" in captured.err
        assert "drone systems" in captured.err

    def test_bare_aipass_no_traceback(self, capsys: pytest.CaptureFixture[str]) -> None:
        """No python traceback leaks on 'drone aipass'."""
        from aipass.drone.apps.drone import main

        with patch("sys.argv", ["drone", "aipass"]):
            result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "Traceback" not in captured.err
        assert "ModuleNotFoundError" not in captured.err

    def test_at_aipass_no_at_misdirect(self, capsys: pytest.CaptureFixture[str]) -> None:
        """No 'use @aipass' misdirect on 'drone @aipass'."""
        from aipass.drone.apps.drone import main

        with patch("sys.argv", ["drone", "@aipass"]):
            result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "Use '@aipass'" not in captured.err

    def test_real_branch_still_routes(self) -> None:
        """Real branches still route normally after aipass intercept."""
        from aipass.drone.apps.drone import main

        with (
            patch("sys.argv", ["drone", "@git", "status"]),
            patch(f"{_DRONE}.is_module", return_value=True),
            patch(f"{_DRONE}.route_module_command", return_value={"stdout": "ok", "stderr": "", "exit_code": 0}),
        ):
            result = main()
        assert result == 0


# ---------------------------------------------------------------------------
# _extract_timeout — --timeout flag parsing
# ---------------------------------------------------------------------------


class TestExtractTimeout:
    """Tests for --drone-timeout flag extraction from arg lists."""

    def test_no_flag(self) -> None:
        """Args without --drone-timeout pass through unchanged."""
        from aipass.drone.apps.drone import _extract_timeout

        args = ["close", "FPLAN-0313"]
        cleaned, timeout = _extract_timeout(args)
        assert cleaned == ["close", "FPLAN-0313"]
        assert timeout is None

    def test_flag_at_end(self) -> None:
        """--drone-timeout N at end of args is extracted."""
        from aipass.drone.apps.drone import _extract_timeout

        cleaned, timeout = _extract_timeout(["process-plans", "--drone-timeout", "120"])
        assert cleaned == ["process-plans"]
        assert timeout == 120

    def test_flag_at_start(self) -> None:
        """--drone-timeout N at start of args is extracted."""
        from aipass.drone.apps.drone import _extract_timeout

        cleaned, timeout = _extract_timeout(["--drone-timeout", "90", "close", "FPLAN-0313"])
        assert cleaned == ["close", "FPLAN-0313"]
        assert timeout == 90

    def test_flag_in_middle(self) -> None:
        """--drone-timeout N in the middle of args is extracted."""
        from aipass.drone.apps.drone import _extract_timeout

        cleaned, timeout = _extract_timeout(["close", "--drone-timeout", "60", "FPLAN-0313"])
        assert cleaned == ["close", "FPLAN-0313"]
        assert timeout == 60

    def test_flag_without_value(self) -> None:
        """--drone-timeout at end with no value returns None and leaves args."""
        from aipass.drone.apps.drone import _extract_timeout

        args = ["close", "--drone-timeout"]
        cleaned, timeout = _extract_timeout(args)
        assert cleaned == args
        assert timeout is None

    def test_flag_non_integer_value(self) -> None:
        """--drone-timeout with non-integer value returns None and leaves args."""
        from aipass.drone.apps.drone import _extract_timeout

        args = ["close", "--drone-timeout", "abc"]
        cleaned, timeout = _extract_timeout(args)
        assert cleaned == args
        assert timeout is None

    def test_empty_args(self) -> None:
        """Empty arg list returns empty with None timeout."""
        from aipass.drone.apps.drone import _extract_timeout

        cleaned, timeout = _extract_timeout([])
        assert cleaned == []
        assert timeout is None

    def test_plain_timeout_passes_through(self) -> None:
        """--timeout (without drone- prefix) is NOT consumed — passes to target."""
        from aipass.drone.apps.drone import _extract_timeout

        args = ["watchdog", "agent", "@memory", "--timeout", "1800"]
        cleaned, timeout = _extract_timeout(args)
        assert cleaned == args
        assert timeout is None
