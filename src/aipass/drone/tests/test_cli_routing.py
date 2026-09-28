# =================== AIPass ====================
# Name: test_cli_routing.py
# Description: CLI Routing Tests for Drone (adapted from universal template)
# Version: 1.0.3
# Created: 2026-03-27
# Modified: 2026-09-28
# =============================================

"""Tests for apps/drone.py, the drone CLI entry point and its routing."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — importlib.import_module() itself, beneath the bare-module lane

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from aipass.drone.apps.drone import (
    main,
    print_help,
    print_introspection,
)
from aipass.drone.apps.handlers.executor import CommandResult
from aipass.drone.apps.modules import RegistryError
from aipass.drone.cli import main as cli_main


def test_print_help(capsys: pytest.CaptureFixture[str]) -> None:  # CR-007
    """print_help() runs without error and produces stdout output."""
    print_help()
    captured = capsys.readouterr()
    assert len(captured.out) > 0, "print_help() must produce output"


def test_print_introspection(capsys: pytest.CaptureFixture[str]) -> None:  # CR-008
    """print_introspection() runs without error and produces stdout output."""
    print_introspection()
    captured = capsys.readouterr()
    assert len(captured.out) > 0, "print_introspection() must produce output"


def test_short_help() -> None:  # CR-002
    """drone -h flag triggers help and exits cleanly."""
    with patch("sys.argv", ["drone", "-h"]):
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
        with patch("sys.argv", ["drone", "--version"]):
            result = main()
        assert result == 0

    def test_version_short_flag(self) -> None:
        """-V prints version and returns 0."""
        with patch("sys.argv", ["drone", "-V"]):
            result = main()
        assert result == 0


class TestMainHelp:
    """drone --help, -h, and help command."""

    def test_help_long_flag(self) -> None:
        """--help returns 0."""
        with patch("sys.argv", ["drone", "--help"]):
            result = main()
        assert result == 0

    def test_help_word(self) -> None:
        """bare 'help' returns 0."""
        with patch("sys.argv", ["drone", "help"]):
            result = main()
        assert result == 0


class TestMainNoArgs:
    """drone with no args shows introspection."""

    def test_no_args_introspection(self) -> None:
        """No args calls print_introspection and returns 0."""
        with (
            patch("sys.argv", ["drone"]),
            patch(f"{_DRONE}.print_introspection"),
        ):
            result = main()
        assert result == 0

    def test_no_args_registry_error(self) -> None:
        """RegistryError during introspection returns 1."""
        with (
            patch("sys.argv", ["drone"]),
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
        with (
            patch("sys.argv", ["drone", "systems"]),
            patch(f"{_DRONE}._handle_systems", return_value=0) as mock_sys,
        ):
            result = main()
        assert result == 0
        mock_sys.assert_called_once()

    def test_systems_registry_error(self) -> None:
        """RegistryError in systems returns 1."""
        with (
            patch("sys.argv", ["drone", "systems"]),
            patch(
                f"{_DRONE}._handle_systems",
                side_effect=RegistryError("broken"),
            ),
        ):
            result = main()
        assert result == 1

    def test_systems_unexpected_error(self) -> None:
        """Unexpected Exception in systems returns 1."""
        with (
            patch("sys.argv", ["drone", "systems"]),
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
        with patch("sys.argv", ["drone", "scan"]):
            result = main()
        assert result == 1

    def test_scan_success(self) -> None:
        """scan with target delegates to scan module."""
        with (
            patch("sys.argv", ["drone", "scan", "@seedgo"]),
            patch(
                "aipass.drone.apps.modules.scan.scan",
                return_value=[{"name": "audit"}],
            ),
        ):
            result = main()
        assert result == 0

    def test_scan_failure(self) -> None:
        """scan returning None means failure -> exit 1."""
        with (
            patch("sys.argv", ["drone", "scan", "@seedgo"]),
            patch("aipass.drone.apps.modules.scan.scan", return_value=None),
        ):
            result = main()
        assert result == 1


class TestMainActivate:
    """drone activate command."""

    def test_activate_no_target(self) -> None:
        """activate with no target shows help and returns 0."""
        with patch("sys.argv", ["drone", "activate"]):
            result = main()
        assert result == 0

    def test_activate_help_flag(self) -> None:
        """activate --help shows help and returns 0."""
        with patch("sys.argv", ["drone", "activate", "--help"]):
            result = main()
        assert result == 0

    def test_activate_with_target(self) -> None:
        """activate with target delegates to _handle_activate."""
        with (
            patch("sys.argv", ["drone", "activate", "@seedgo"]),
            patch(f"{_DRONE}._handle_activate", return_value=0) as mock_act,
        ):
            result = main()
        assert result == 0
        mock_act.assert_called_once_with("@seedgo")


class TestMainList:
    """drone list command."""

    def test_list_delegates(self) -> None:
        """list delegates to _handle_list."""
        with (
            patch("sys.argv", ["drone", "list"]),
            patch(f"{_DRONE}._handle_list", return_value=0) as mock_list,
        ):
            result = main()
        assert result == 0
        mock_list.assert_called_once()


class TestMainRemove:
    """drone remove command."""

    def test_remove_no_name(self) -> None:
        """remove with no name returns 1."""
        with patch("sys.argv", ["drone", "remove"]):
            result = main()
        assert result == 1

    def test_remove_with_name(self) -> None:
        """remove with name delegates to _handle_remove."""
        with (
            patch("sys.argv", ["drone", "remove", "audit"]),
            patch(f"{_DRONE}._handle_remove", return_value=0) as mock_rm,
        ):
            result = main()
        assert result == 0
        mock_rm.assert_called_once_with("audit")


class TestMainAtTarget:
    """drone @target routing."""

    def test_at_target_delegates(self) -> None:
        """@target routes to _handle_target."""
        with (
            patch("sys.argv", ["drone", "@seedgo", "audit"]),
            patch(f"{_DRONE}._handle_target", return_value=0) as mock_tgt,
        ):
            result = main()
        assert result == 0
        mock_tgt.assert_called_once_with(["@seedgo", "audit"])


class TestMainModuleRouting:
    """drone bare module name routing."""

    def test_discovered_module_bool_true(self) -> None:
        """Discovered module returning True yields exit 0."""
        mock_mod = type(sys)("fake_mod")
        mock_mod.handle_command = lambda cmd, args: True

        with (
            patch("sys.argv", ["drone", "config", "list"]),
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
        mock_mod = type(sys)("fake_mod")
        mock_mod.handle_command = lambda cmd, args: False

        with (
            patch("sys.argv", ["drone", "config", "broken"]),
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
        mock_mod = type(sys)("fake_mod")
        mock_mod.handle_command = lambda cmd, args: {
            "stdout": "output",
            "stderr": "",
            "exit_code": 0,
        }

        with (
            patch("sys.argv", ["drone", "config", "list"]),
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
        with (
            patch("sys.argv", ["drone", "config", "list"]),
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
        with (
            patch("sys.argv", ["drone", "audit", "aipass"]),
            patch(f"{_DRONE}._discover_modules", return_value=[]),
            patch(f"{_DRONE}._handle_custom_command", return_value=0),
        ):
            result = main()
        assert result == 0

    def test_custom_command_not_matched(self) -> None:
        """Unmatched command falls through to unknown."""
        with (
            patch("sys.argv", ["drone", "nonexistent_cmd"]),
            patch(f"{_DRONE}._discover_modules", return_value=[]),
            patch(f"{_DRONE}._handle_custom_command", return_value=-1),
            patch(
                "aipass.drone.apps.modules.resolver.branch_exists",
                return_value=False,
            ),
        ):
            result = main()
        assert result == 1

    def test_a_command_registry_that_cannot_load_exits_1_naming_it(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A failed command-registry heal is a named failure, not a traceback; mutant: the router's catch removed."""

        def unreadable() -> dict:
            raise OSError("registry unreadable")

        with (
            patch("sys.argv", ["drone", "audit", "aipass"]),
            patch(f"{_DRONE}._discover_modules", return_value=[]),
            patch("aipass.drone.apps.handlers.command_registry.lookup.load_registry", unreadable),
        ):
            result = main()
        _out, err = capsys.readouterr()
        assert result == 1
        assert "command registry" in err
        assert "registry unreadable" in err


class TestMainUnknownCommand:
    """drone unknown command handling with branch hint."""

    def test_unknown_bare_branch_name(self) -> None:
        """Bare branch name shows @ prefix hint."""
        with (
            patch("sys.argv", ["drone", "seedgo"]),
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
        with (
            patch("sys.argv", ["drone", "broken_cmd"]),
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
    """`drone systems` logic paths, through main()."""

    def test_no_registry(self, capsys: pytest.CaptureFixture[str]) -> None:
        """No registry in the cwd tree says so and exits 0 (mutant: the message print removed)."""
        with (
            patch("sys.argv", ["drone", "systems"]),
            patch(f"{_DRONE}._cwd_has_registry", return_value=False),
        ):
            result = main()
        assert result == 0
        assert "No registry found" in capsys.readouterr().out

    def test_with_branches_and_modules(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Modules list under services, agents under branches (mutant: the branch loop print removed)."""
        branches = [
            {"name": "drone", "profile": "library", "description": "Router"},
            {"name": "myapp", "profile": "agent"},
        ]
        with (
            patch("sys.argv", ["drone", "systems"]),
            patch(f"{_DRONE}._cwd_has_registry", return_value=True),
            patch(f"{_DRONE}.get_all_branches", return_value=branches),
            patch(f"{_DRONE}.list_modules", return_value=["git"]),
            patch(
                f"{_DRONE}.get_module_info",
                return_value=type("I", (), {"description": "Git ops"})(),
            ),
        ):
            result = main()
        out = capsys.readouterr().out
        assert result == 0
        assert "Git ops" in out
        assert "@myapp" in out

    def test_aipass_home_hint(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        """`drone systems` prints the AIPASS_HOME hint when unset (mutant: hint print removed)."""
        monkeypatch.delenv("AIPASS_HOME", raising=False)
        with (
            patch("sys.argv", ["drone", "systems"]),
            patch(f"{_DRONE}._cwd_has_registry", return_value=True),
            patch(f"{_DRONE}.get_all_branches", return_value=[]),
            patch(f"{_DRONE}.list_modules", return_value=[]),
        ):
            result = main()
        assert result == 0
        assert "export AIPASS_HOME=" in capsys.readouterr().out


class TestHandleModule:
    """`drone @<module>` introspection, help, and command routing, through main()."""

    @staticmethod
    def _run(argv: list[str], **patches: Any) -> tuple[int, MagicMock]:
        """Run main() on a module target with every branch and module edge stubbed."""
        with (
            patch("sys.argv", ["drone", *argv]),
            patch(f"{_DRONE}.is_module", return_value=True),
            patch(f"{_DRONE}.branch_exists", return_value=False),
            patch(f"{_DRONE}.route_command") as mock_route,
            patch(f"{_DRONE}.get_module_introspective", return_value=patches.get("intro", "")),
            patch(f"{_DRONE}.get_module_help", return_value=patches.get("help", "")),
            patch(f"{_DRONE}.route_module_command", **patches.get("route", {"return_value": {}})) as mock_rmc,
        ):
            result = main()
        mock_route.assert_not_called()
        return result, mock_rmc

    def test_no_args_introspection(self, capsys: pytest.CaptureFixture[str]) -> None:
        """No args prints the introspection text (mutant: the intro print removed)."""
        result, _ = self._run(["@git"], intro="Module info")
        assert result == 0
        assert "Module info" in capsys.readouterr().out

    def test_no_args_no_introspection(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Empty introspection prints the fallback (mutant: the fallback print removed)."""
        result, _ = self._run(["@git"])
        assert result == 0
        assert "No information available for @git." in capsys.readouterr().out

    def test_help_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--help prints the help text (mutant: the help print removed)."""
        result, _ = self._run(["@git", "--help"], help="Help text")
        assert result == 0
        assert "Help text" in capsys.readouterr().out

    def test_help_no_text(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--help with no text prints the fallback (mutant: the fallback print removed)."""
        result, _ = self._run(["@git", "--help"])
        assert result == 0
        assert "No help available for @git." in capsys.readouterr().out

    def test_a_module_that_cannot_load_is_named_on_stderr_not_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        """No args on a module that cannot load exits 1 and says so; mutant killed: None read as no information."""
        result, _ = self._run(["@git"], intro=None)
        out, err = capsys.readouterr()
        assert result == 1
        assert "module @git is registered but not available: it could not load" in err
        assert "No information available" not in out

    def test_help_on_a_module_that_cannot_load_is_named_on_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--help on a module that cannot load exits 1 and says so; mutant killed: None read as no help."""
        result, _ = self._run(["@git", "--help"], help=None)
        out, err = capsys.readouterr()
        assert result == 1
        assert "module @git is registered but not available: it could not load" in err
        assert "No help available" not in out

    def test_command_routing(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A verb routes through route_module_command and its stdout is written (mutant: stdout write removed)."""
        result, mock_rmc = self._run(
            ["@git", "status"], route={"return_value": {"stdout": "ok", "stderr": "", "exit_code": 0}}
        )
        assert result == 0
        mock_rmc.assert_called_once_with("git", "status", None)
        assert capsys.readouterr().out == "ok"

    def test_command_import_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """ImportError during a module verb exits 1 and says why on stderr (mutant: except returns 0)."""
        result, _ = self._run(["@git", "status"], route={"side_effect": ImportError("missing")})
        assert result == 1
        assert "not available: missing" in capsys.readouterr().err


# ===========================================================================
# @target paths
# ===========================================================================


class TestHandleTarget:
    """`drone @branch ...` routing, through main(); every branch and module edge is a recording stub."""

    @staticmethod
    def _run(argv: list[str], is_module: bool, result: CommandResult | None = None) -> tuple[int, MagicMock, MagicMock]:
        with (
            patch("sys.argv", ["drone", *argv]),
            patch(f"{_DRONE}.is_module", return_value=is_module),
            patch(f"{_DRONE}.branch_exists", return_value=False),
            patch(f"{_DRONE}.route_command", return_value=result) as mock_route,
            patch(f"{_DRONE}._handle_module", return_value=0) as mock_hm,
        ):
            rc = main()
        return rc, mock_route, mock_hm

    def test_module_route(self) -> None:
        """A non-interactive module verb goes to the module, never a branch (mutant: lane `if False`)."""
        rc, mock_route, mock_hm = self._run(["@git", "diff"], is_module=True)
        assert rc == 0
        mock_hm.assert_called_once_with("git", ["diff"])
        mock_route.assert_not_called()

    def test_no_args_introspection(self) -> None:
        """@target alone routes with interactive=True (mutant: introspection routes interactive=False)."""
        ok = CommandResult(stdout="", stderr="", exit_code=0, branch="seedgo", command="")
        rc, mock_route, _ = self._run(["@seedgo"], is_module=False, result=ok)
        assert rc == 0
        mock_route.assert_called_once_with("@seedgo", interactive=True)

    def test_help_flag(self) -> None:
        """@target --help routes with interactive=True (mutant: help routes interactive=False)."""
        ok = CommandResult(stdout="", stderr="", exit_code=0, branch="seedgo", command="--help")
        rc, mock_route, _ = self._run(["@seedgo", "--help"], is_module=False, result=ok)
        assert rc == 0
        mock_route.assert_called_once_with("@seedgo", "--help", interactive=True)

    def test_command_routing(self, capsys: pytest.CaptureFixture[str]) -> None:
        """@target verb routes with its args and writes the child's stdout (mutant: stdout write removed)."""
        out = CommandResult(stdout="output", stderr="", exit_code=0, branch="seedgo", command="audit")
        rc, mock_route, _ = self._run(["@seedgo", "audit", "aipass"], is_module=False, result=out)
        assert rc == 0
        assert mock_route.call_args.args == ("@seedgo", "audit")
        assert mock_route.call_args.kwargs["args"] == ["aipass"]
        assert capsys.readouterr().out == "output"

    def test_short_help_flag(self) -> None:
        """@target -h routes with interactive=True (mutant: help routes interactive=False)."""
        ok = CommandResult(stdout="", stderr="", exit_code=0, branch="seedgo", command="-h")
        rc, mock_route, _ = self._run(["@seedgo", "-h"], is_module=False, result=ok)
        assert rc == 0
        mock_route.assert_called_once_with("@seedgo", "-h", interactive=True)

    def test_status_routes_interactive(self) -> None:
        """status routes with interactive=True for Rich color output (mutant: `interactive = False`)."""
        ok = CommandResult(stdout="", stderr="", exit_code=0, branch="hooks", command="status")
        rc, mock_route, _ = self._run(["@hooks", "status"], is_module=False, result=ok)
        assert rc == 0
        assert mock_route.call_args.kwargs["interactive"] is True

    def test_help_for_a_module_that_is_not_a_local_branch(self) -> None:
        """@seedgo --help where seedgo is a module and no branch goes to the module (mutant: lane `if False`)."""
        # Once pinned via the exception fallback (route_command raised, the handler re-routed);
        # the lane is now DECIDED before any branch call, not discovered by failing one (DPLAN-0315 item 1).
        rc, mock_route, mock_hm = self._run(["@seedgo", "--help"], is_module=True)
        assert rc == 0
        mock_hm.assert_called_once_with("seedgo", ["--help"])
        mock_route.assert_not_called()

    def test_command_for_a_module_that_is_not_a_local_branch(self) -> None:
        """Same for a real verb: degradation outside AIPass stays intact (mutant: lane `if False`)."""
        rc, mock_route, mock_hm = self._run(["@seedgo", "audit"], is_module=True)
        assert rc == 0
        mock_hm.assert_called_once_with("seedgo", ["audit"])
        mock_route.assert_not_called()


# ===========================================================================
# custom command paths
# ===========================================================================


class TestHandleCustomCommand:
    """Custom command matching and routing, through main()."""

    _MATCH = "aipass.drone.apps.modules.commands.match"

    def test_no_match(self, capsys: pytest.CaptureFixture[str]) -> None:
        """No match falls through to the unknown-command error (mutant: no-match returns 0)."""
        with (
            patch("sys.argv", ["drone", "unknown"]),
            patch(self._MATCH, return_value=None),
            patch(f"{_DRONE}.route_command") as mock_route,
            patch("aipass.drone.apps.modules.resolver.branch_exists", return_value=False),
        ):
            result = main()
        assert result == 1
        mock_route.assert_not_called()
        assert "unknown command 'unknown'" in capsys.readouterr().err

    def test_matched_routes_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A matched shortcut routes its stored target, verb and args (mutant: stored args dropped)."""
        cmd_data = {
            "target": "@seedgo",
            "command": "audit",
            "args": ["aipass"],
        }
        mock_result = CommandResult(stdout="ok", stderr="", exit_code=0, branch="seedgo", command="audit")
        with (
            patch("sys.argv", ["drone", "audit"]),
            patch(self._MATCH, return_value=(cmd_data, [])),
            patch(f"{_DRONE}.route_command", return_value=mock_result) as mock_route,
            patch(f"{_DRONE}._handle_module", return_value=0) as mock_hm,
        ):
            result = main()
        assert result == 0
        assert mock_route.call_args.args == ("@seedgo", "audit")
        assert mock_route.call_args.kwargs["args"] == ["aipass"]
        mock_hm.assert_not_called()
        assert capsys.readouterr().out == "ok"


# ===========================================================================
# Helper functions
# ===========================================================================


def _viewed(token: str) -> str:
    """The message ID `drone @ai_mail view <token>` hands the router, from the current seat."""
    _, mock_route, _ = _route(["@ai_mail", "view", token])
    return mock_route.call_args.kwargs["args"][0]


def _inbox_seat(tmp_path: Path, body: str) -> None:
    """Build a citizen seat whose inbox.json holds `body`."""
    (tmp_path / ".trinity").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".ai_mail.local").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".ai_mail.local" / "inbox.json").write_text(body, encoding="utf-8")


class TestReadInboxMessageId:
    """`drone @ai_mail view N` reads the Nth message in display order, through main()."""

    def test_valid_index(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Display order is the array reversed (mutant: messages[n - 1])."""
        _inbox_seat(tmp_path, json.dumps({"messages": [{"id": "newest"}, {"id": "oldest"}]}))
        monkeypatch.chdir(tmp_path)
        assert _viewed("1") == "oldest"
        assert _viewed("2") == "newest"

    def test_out_of_range(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An out-of-range index passes through as typed (mutant: the lower bound `0 <= n`)."""
        _inbox_seat(tmp_path, json.dumps({"messages": [{"id": "abc"}]}))
        monkeypatch.chdir(tmp_path)
        assert _viewed("5") == "5"
        assert _viewed("0") == "0"

    def test_corrupt_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A corrupt inbox passes the token through (mutant: the except re-raises)."""
        _inbox_seat(tmp_path, "{bad json")
        monkeypatch.chdir(tmp_path)
        assert _viewed("1") == "1"


class TestResolveMailToken:
    """`view <token>` resolution, through main() — a real message ID always beats the index convenience.

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
        """An all-digit message ID is an ID, not an index (mutant: the pre-fix index-first resolver)."""
        self._seat(tmp_path, ["b7c79832", "04727185"])
        monkeypatch.chdir(tmp_path)
        assert _viewed("04727185") == "04727185"

    def test_id_wins_over_valid_index_collision(self, tmp_path: Path, monkeypatch) -> None:
        """An all-digit ID that is also a valid index opens itself (mutant: the pre-fix index-first resolver)."""
        # The silent half of the defect: no error, just the wrong mail.
        self._seat(tmp_path, ["deadbeef", "00000002"])
        monkeypatch.chdir(tmp_path)
        # Display index 2 would be "deadbeef" (array is reversed for display).
        assert _viewed("00000002") == "00000002"

    def test_index_still_resolves_when_not_an_id(self, tmp_path: Path, monkeypatch) -> None:
        """A bare index still maps to display order (mutant: the index path disabled)."""
        self._seat(tmp_path, ["newest", "oldest"])
        monkeypatch.chdir(tmp_path)
        assert _viewed("1") == "oldest"
        assert _viewed("2") == "newest"

    def test_failed_resolution_preserves_original_token(self, tmp_path: Path, monkeypatch) -> None:
        """On failure return what the user typed (mutant: the pre-fix str(int(token)) round trip)."""
        # str(int("08532166")) drops the leading zero, so the not-found error
        # named an ID the user never typed.
        self._seat(tmp_path, ["b7c79832"])
        monkeypatch.chdir(tmp_path)
        assert _viewed("08532166") == "08532166"

    def test_hex_id_passes_through(self, tmp_path: Path, monkeypatch) -> None:
        """A hex ID is returned untouched, in the inbox or not (mutant: the fall-through returns token.upper())."""
        self._seat(tmp_path, ["b7c79832"])
        monkeypatch.chdir(tmp_path)
        assert _viewed("b7c79832") == "b7c79832"
        assert _viewed("c4d41074") == "c4d41074"

    def test_no_inbox_returns_token_unchanged(self, tmp_path: Path, monkeypatch) -> None:
        """No seat, no inbox: the token passes through (mutant: the pre-fix str(int(token)) round trip)."""
        monkeypatch.chdir(tmp_path)
        assert _viewed("04727185") == "04727185"
        assert _viewed("3") == "3"


class TestDiscoverModules:
    """Module auto-discovery, read through print_introspection()."""

    def test_discovers_modules_with_handle_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Modules with handle_command are listed (mutant: `if not hasattr(module, "handle_command")`)."""
        print_introspection()
        out = capsys.readouterr().out
        assert "git_module" in out
        assert "resolver" in out

    def test_skips_private_files(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Files starting with _ are not listed (HELD: the skip-guard mutant survives; no _file has handle_command)."""
        print_introspection()
        assert "__init__" not in capsys.readouterr().out


class TestCliEntryPoint:
    """cli.py entry point."""

    def test_cli_main_calls_drone_main(self) -> None:
        """cli.main() calls drone main and exits."""
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
        with patch("sys.argv", ["drone", "aipass"]):
            result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "aipass isn't reachable through drone" in captured.err
        assert "aipass --help" in captured.err

    def test_at_aipass_shows_guidance(self, capsys: pytest.CaptureFixture[str]) -> None:
        """'drone @aipass' prints guidance to stderr."""
        with patch("sys.argv", ["drone", "@aipass"]):
            result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "aipass isn't reachable through drone" in captured.err
        assert "drone systems" in captured.err

    def test_bare_aipass_no_traceback(self, capsys: pytest.CaptureFixture[str]) -> None:
        """No python traceback leaks on 'drone aipass'."""
        with patch("sys.argv", ["drone", "aipass"]):
            result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "Traceback" not in captured.err
        assert "ModuleNotFoundError" not in captured.err

    def test_at_aipass_no_at_misdirect(self, capsys: pytest.CaptureFixture[str]) -> None:
        """No 'use @aipass' misdirect on 'drone @aipass'."""
        with patch("sys.argv", ["drone", "@aipass"]):
            result = main()
        assert result == 1
        captured = capsys.readouterr()
        assert "Use '@aipass'" not in captured.err

    def test_real_branch_still_routes(self) -> None:
        """Real branches still route normally after aipass intercept."""
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


def _route(argv: list[str], *, is_module: bool = False, branch_exists: bool = True) -> tuple[int, MagicMock, MagicMock]:
    """Run main() on argv with the branch and module edges as recording stubs."""
    with (
        patch("sys.argv", ["drone", *argv]),
        patch(f"{_DRONE}.is_module", return_value=is_module),
        patch(f"{_DRONE}.branch_exists", return_value=branch_exists),
        patch(f"{_DRONE}.route_command") as mock_route,
        patch(f"{_DRONE}._handle_module", return_value=0) as mock_module,
    ):
        mock_route.return_value = SimpleNamespace(stdout="", stderr="", exit_code=0)
        rc = main()
    return rc, mock_route, mock_module


class TestExtractTimeout:
    """--drone-timeout is taken off the args and handed to the router, through main()."""

    def test_no_flag(self) -> None:
        """Args without --drone-timeout pass through unchanged (mutant: the no-flag return drops args[0])."""
        _, mock_route, _ = _route(["@memory", "close", "FPLAN-0313"])
        assert mock_route.call_args == call("@memory", "close", args=["FPLAN-0313"], timeout=None, interactive=False)

    def test_flag_at_end(self) -> None:
        """--drone-timeout N at the end is extracted (mutant: the flag left in the args)."""
        _, mock_route, _ = _route(["@memory", "process-plans", "--drone-timeout", "120"])
        assert mock_route.call_args == call("@memory", "process-plans", args=None, timeout=120, interactive=False)

    def test_flag_at_start(self) -> None:
        """--drone-timeout N at the start is extracted (mutant: the flag left in the args)."""
        _, mock_route, _ = _route(["@memory", "--drone-timeout", "90", "close", "FPLAN-0313"])
        assert mock_route.call_args == call("@memory", "close", args=["FPLAN-0313"], timeout=90, interactive=False)

    def test_flag_in_middle(self) -> None:
        """--drone-timeout N in the middle is extracted (mutant: the flag left in the args)."""
        _, mock_route, _ = _route(["@memory", "close", "--drone-timeout", "60", "FPLAN-0313"])
        assert mock_route.call_args == call("@memory", "close", args=["FPLAN-0313"], timeout=60, interactive=False)

    def test_flag_without_value(self) -> None:
        """A trailing --drone-timeout with no value is left to the target (mutant: the no-value guard removed)."""
        _, mock_route, _ = _route(["@memory", "close", "--drone-timeout"])
        assert mock_route.call_args == call(
            "@memory", "close", args=["--drone-timeout"], timeout=None, interactive=False
        )

    def test_flag_non_integer_value(self) -> None:
        """A non-integer value is left to the target (mutant: the ValueError path cuts the args)."""
        _, mock_route, _ = _route(["@memory", "close", "--drone-timeout", "abc"])
        assert mock_route.call_args == call(
            "@memory", "close", args=["--drone-timeout", "abc"], timeout=None, interactive=False
        )

    def test_empty_args(self) -> None:
        """A bare target stays introspection (mutant: an empty arg list defaults to --help)."""
        _, mock_route, _ = _route(["@memory"])
        assert mock_route.call_args == call("@memory", interactive=True)

    def test_plain_timeout_passes_through(self) -> None:
        """--timeout (without drone- prefix) is NOT consumed (mutant: the flag test matches --timeout)."""
        _, mock_route, _ = _route(["@memory", "watchdog", "agent", "@memory", "--timeout", "1800"])
        assert mock_route.call_args == call(
            "@memory", "watchdog", args=["agent", "@memory", "--timeout", "1800"], timeout=None, interactive=True
        )


# ---------------------------------------------------------------------------
# An accepted --drone-timeout that cannot be applied says so
# ---------------------------------------------------------------------------


class TestInertTimeoutIsReported:
    """Two lanes take no timeout: module routing and interactive commands.

    The flag parses in both, so before this the operator's number vanished in
    silence — `drone @seedgo audit ... --drone-timeout 5` ran unbounded and
    said nothing. A silently discarded cap is the same species of defect as a
    silent kill, which is what the rest of this change removes.
    """

    def test_a_dropped_timeout_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """An interactive route logs the dropped number (mutant: the logger.warning removed)."""
        with caplog.at_level("WARNING"):
            _route(["@seedgo", "audit", "aipass", "--drone-timeout", "5"])
        assert any("--drone-timeout 5" in record.getMessage() for record in caplog.records)

    def test_the_reason_travels_with_the_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """'Ignored' without 'why' sends the operator hunting (mutant: the reason dropped from the message)."""
        with caplog.at_level("WARNING"):
            _route(["@git", "diff", "--drone-timeout", "5"], is_module=True, branch_exists=False)
        assert any("in-process" in record.getMessage() for record in caplog.records)

    def test_no_flag_means_no_noise(self, caplog: pytest.LogCaptureFixture) -> None:
        """No flag, no warning (mutant: the None guard tests `== 0`)."""
        with caplog.at_level("WARNING"):
            _route(["@seedgo", "audit", "aipass"])
        assert not [r for r in caplog.records if r.levelname == "WARNING"]

    def test_the_operator_is_told_not_just_the_log(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A log line the operator never reads is not a report (mutant: the err_console print removed)."""
        _route(["@git", "diff", "--drone-timeout", "5"], is_module=True, branch_exists=False)
        assert "--drone-timeout 5" in capsys.readouterr().err

    def test_an_interactive_route_reports_before_running(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The interactive lane reports the dropped cap (mutant: its report call removed)."""
        # End to end through _handle_target: this is the lane that was silent.
        _, mock_route, _ = _route(["@seedgo", "audit", "aipass", "--drone-timeout", "5"])
        assert "--drone-timeout 5 not applied" in capsys.readouterr().err
        assert mock_route.call_args.kwargs["interactive"] is True

    def test_a_captured_route_stays_quiet_and_keeps_the_number(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The flag still works where it applies (mutant: route_command gets timeout=None)."""
        _, mock_route, _ = _route(["@memory", "search", "x", "--drone-timeout", "5"])
        assert "not applied" not in capsys.readouterr().err
        assert mock_route.call_args.kwargs["timeout"] == 5

    def test_a_module_route_reports_before_running(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The module lane reports too, and the flag never reaches the module (mutant: its report call removed)."""
        # Separate from the interactive case on purpose: the two lanes are different branches
        # of _handle_target, and a mutation proved one test cannot pin both.
        rc, mock_route, mock_module = _route(
            ["@git", "status", "--drone-timeout", "5"], is_module=True, branch_exists=False
        )
        assert rc == 0
        assert "--drone-timeout 5 not applied" in capsys.readouterr().err
        assert mock_module.call_args.args[1] == ["status"], "the flag itself must not reach the module"
        mock_route.assert_not_called()
