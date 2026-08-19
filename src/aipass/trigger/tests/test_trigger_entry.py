# =================== AIPass ====================
# Name: test_trigger_entry.py
# Description: Tests for trigger.py CLI entry point — line coverage
# Version: 1.0.0
# Created: 2026-04-26
# Modified: 2026-04-26
# =============================================

"""Tests for the trigger.py CLI entry point (discover, route, main)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Infrastructure mocks — isolate from real prax / cli
# ---------------------------------------------------------------------------

_mock_console = MagicMock()
_mock_header = MagicMock()
_mock_error = MagicMock()
_mock_logger = MagicMock()


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace heavy infrastructure imports with lightweight mocks."""
    # Reset call counts between tests
    _mock_console.reset_mock()
    _mock_header.reset_mock()
    _mock_error.reset_mock()
    _mock_logger.reset_mock()

    # ---- prax logger ----
    prax_logger_mod = MagicMock()
    prax_logger_mod.system_logger = _mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules.logger", prax_logger_mod)

    # ---- cli ----
    mock_cli = MagicMock()
    mock_cli.console = _mock_console
    mock_cli.header = _mock_header
    mock_cli.error = _mock_error
    monkeypatch.setitem(sys.modules, "aipass.cli", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", mock_cli)

    # ---- force re-import so the module picks up our mocks ----
    monkeypatch.delitem(sys.modules, "aipass.trigger.apps.trigger", raising=False)


def _import_trigger():
    """Import trigger.py fresh (after infrastructure mocks are in place)."""
    import aipass.trigger.apps.trigger as mod

    return mod


# ===================================================================
# discover_modules
# ===================================================================


class TestDiscoverModules:
    """Cover discover_modules() paths."""

    def test_discovers_modules_with_handle_command(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Module .py with handle_command() is discovered."""
        mod_file = tmp_path / "good_mod.py"
        mod_file.write_text(
            "def handle_command(command, args):\n    return False\n",
            encoding="utf-8",
        )

        trigger = _import_trigger()
        monkeypatch.setattr(trigger, "MODULES_DIR", tmp_path)

        # We need importlib to actually find the module, so patch import_module
        fake_module = MagicMock()
        fake_module.handle_command = MagicMock()
        monkeypatch.setattr(trigger.importlib, "import_module", lambda name: fake_module)

        result = trigger.discover_modules()
        assert fake_module in result

    def test_skips_underscore_files(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Files starting with _ (e.g. __init__.py) are skipped."""
        (tmp_path / "__init__.py").write_text("# init", encoding="utf-8")
        (tmp_path / "_private.py").write_text("# private", encoding="utf-8")

        trigger = _import_trigger()
        monkeypatch.setattr(trigger, "MODULES_DIR", tmp_path)

        import_called = False

        def _no_import(name: str):
            nonlocal import_called
            import_called = True

        monkeypatch.setattr(trigger.importlib, "import_module", _no_import)

        result = trigger.discover_modules()
        assert result == []
        assert not import_called

    def test_skips_modules_without_handle_command(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Module lacking handle_command() is silently skipped."""
        (tmp_path / "no_handler.py").write_text("x = 1\n", encoding="utf-8")

        trigger = _import_trigger()
        monkeypatch.setattr(trigger, "MODULES_DIR", tmp_path)

        fake_module = MagicMock(spec=[])  # spec=[] means NO attributes
        monkeypatch.setattr(trigger.importlib, "import_module", lambda name: fake_module)

        result = trigger.discover_modules()
        assert result == []

    def test_handles_import_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Module that raises on import is skipped and logged."""
        (tmp_path / "bad_mod.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")

        trigger = _import_trigger()
        monkeypatch.setattr(trigger, "MODULES_DIR", tmp_path)

        monkeypatch.setattr(
            trigger.importlib,
            "import_module",
            MagicMock(side_effect=ImportError("boom")),
        )

        result = trigger.discover_modules()
        assert result == []
        _mock_logger.error.assert_called()

    def test_returns_empty_when_dir_missing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Non-existent MODULES_DIR returns empty list and warns."""
        trigger = _import_trigger()
        monkeypatch.setattr(trigger, "MODULES_DIR", tmp_path / "nope")

        result = trigger.discover_modules()
        assert result == []
        _mock_logger.warning.assert_called()


# ===================================================================
# route_command
# ===================================================================


class TestRouteCommand:
    """Cover route_command() paths."""

    def test_routes_to_first_matching_module(self) -> None:
        """Module returning True from handle_command is accepted."""
        trigger = _import_trigger()
        mock_mod = MagicMock()
        mock_mod.handle_command.return_value = True
        assert trigger.route_command("fire", [], [mock_mod]) is True
        mock_mod.handle_command.assert_called_once_with("fire", [])

    def test_returns_false_when_no_module_handles(self) -> None:
        """All modules return False so route_command returns False."""
        trigger = _import_trigger()
        mock_mod = MagicMock()
        mock_mod.handle_command.return_value = False
        assert trigger.route_command("bogus", [], [mock_mod]) is False

    def test_handles_module_exception(self) -> None:
        """Exception in handle_command is caught and logged."""
        trigger = _import_trigger()
        mock_mod = MagicMock()
        mock_mod.__name__ = "aipass.trigger.apps.modules.broken"
        mock_mod.handle_command.side_effect = RuntimeError("boom")
        assert trigger.route_command("fire", [], [mock_mod]) is False
        _mock_logger.error.assert_called()

    def test_stops_after_first_handler(self) -> None:
        """Only the first module that returns True is used."""
        trigger = _import_trigger()
        mod_a = MagicMock()
        mod_a.handle_command.return_value = True
        mod_b = MagicMock()
        mod_b.handle_command.return_value = True

        assert trigger.route_command("cmd", ["a"], [mod_a, mod_b]) is True
        mod_a.handle_command.assert_called_once()
        mod_b.handle_command.assert_not_called()

    def test_tries_next_module_on_false(self) -> None:
        """When first module returns False, second is tried."""
        trigger = _import_trigger()
        mod_a = MagicMock()
        mod_a.handle_command.return_value = False
        mod_b = MagicMock()
        mod_b.handle_command.return_value = True

        assert trigger.route_command("cmd", [], [mod_a, mod_b]) is True
        mod_a.handle_command.assert_called_once()
        mod_b.handle_command.assert_called_once()

    def test_empty_modules_returns_false(self) -> None:
        """Empty module list means nothing can handle the command."""
        trigger = _import_trigger()
        assert trigger.route_command("anything", [], []) is False


# ===================================================================
# print_introspection
# ===================================================================


class TestPrintIntrospection:
    """Cover print_introspection() paths."""

    def test_prints_module_info_with_doc(self) -> None:
        """Module with __doc__ gets its first line as description."""
        trigger = _import_trigger()
        mock_mod = MagicMock()
        mock_mod.__name__ = "aipass.trigger.apps.modules.fire"
        mock_mod.__doc__ = "Fire all the things\nSecond line ignored"

        trigger.print_introspection([mock_mod])
        # Verify console.print was called with the module name
        calls = [str(c) for c in _mock_console.print.call_args_list]
        joined = " ".join(calls)
        assert "fire" in joined

    def test_prints_module_info_without_doc(self) -> None:
        """Module with __doc__=None shows 'No description'."""
        trigger = _import_trigger()
        mock_mod = MagicMock()
        mock_mod.__name__ = "aipass.trigger.apps.modules.silent"
        mock_mod.__doc__ = None

        trigger.print_introspection([mock_mod])
        calls = [str(c) for c in _mock_console.print.call_args_list]
        joined = " ".join(calls)
        assert "No description" in joined

    def test_prints_no_modules_message(self) -> None:
        """Empty module list shows 'No modules discovered'."""
        trigger = _import_trigger()
        trigger.print_introspection([])
        calls = [str(c) for c in _mock_console.print.call_args_list]
        joined = " ".join(calls)
        assert "No modules discovered" in joined


# ===================================================================
# print_help
# ===================================================================


class TestPrintHelp:
    """Cover print_help() paths."""

    def test_prints_help_with_modules_and_doc(self) -> None:
        """Help output includes module name and docstring first line."""
        trigger = _import_trigger()
        mock_mod = MagicMock()
        mock_mod.__name__ = "aipass.trigger.apps.modules.status"
        mock_mod.__doc__ = "Show status information\nDetails"

        trigger.print_help([mock_mod])
        _mock_header.assert_called()
        calls = [str(c) for c in _mock_console.print.call_args_list]
        joined = " ".join(calls)
        assert "status" in joined

    def test_prints_help_with_modules_no_doc(self) -> None:
        """Help output shows 'No description' when module lacks docstring."""
        trigger = _import_trigger()
        mock_mod = MagicMock()
        mock_mod.__name__ = "aipass.trigger.apps.modules.quiet"
        mock_mod.__doc__ = None

        trigger.print_help([mock_mod])
        calls = [str(c) for c in _mock_console.print.call_args_list]
        joined = " ".join(calls)
        assert "No description" in joined

    def test_prints_help_no_modules(self) -> None:
        """Help output shows 'No modules discovered' for empty list."""
        trigger = _import_trigger()
        trigger.print_help([])
        calls = [str(c) for c in _mock_console.print.call_args_list]
        joined = " ".join(calls)
        assert "No modules discovered" in joined


# ===================================================================
# main
# ===================================================================


class TestMain:
    """Cover main() paths."""

    def test_no_args_shows_introspection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No CLI args triggers print_introspection and returns 0."""
        trigger = _import_trigger()
        monkeypatch.setattr(sys, "argv", ["trigger"])
        monkeypatch.setattr(trigger, "discover_modules", lambda: [])

        result = trigger.main()
        assert result == 0
        # print_introspection prints "No modules discovered"
        calls = [str(c) for c in _mock_console.print.call_args_list]
        joined = " ".join(calls)
        assert "No modules discovered" in joined

    def test_version_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The --version flag prints version string and returns 0."""
        trigger = _import_trigger()
        monkeypatch.setattr(sys, "argv", ["trigger", "--version"])
        monkeypatch.setattr(trigger, "discover_modules", lambda: [])

        result = trigger.main()
        assert result == 0
        _mock_console.print.assert_any_call(f"TRIGGER v{trigger.__version__}")

    def test_version_short_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The -V short flag prints version string and returns 0."""
        trigger = _import_trigger()
        monkeypatch.setattr(sys, "argv", ["trigger", "-V"])
        monkeypatch.setattr(trigger, "discover_modules", lambda: [])

        result = trigger.main()
        assert result == 0
        _mock_console.print.assert_any_call(f"TRIGGER v{trigger.__version__}")

    def test_help_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The --help flag calls print_help and returns 0."""
        trigger = _import_trigger()
        monkeypatch.setattr(sys, "argv", ["trigger", "--help"])
        monkeypatch.setattr(trigger, "discover_modules", lambda: [])

        result = trigger.main()
        assert result == 0
        _mock_header.assert_called()

    def test_help_short_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The -h short flag calls print_help and returns 0."""
        trigger = _import_trigger()
        monkeypatch.setattr(sys, "argv", ["trigger", "-h"])
        monkeypatch.setattr(trigger, "discover_modules", lambda: [])

        result = trigger.main()
        assert result == 0

    def test_help_word(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The bare 'help' command calls print_help and returns 0."""
        trigger = _import_trigger()
        monkeypatch.setattr(sys, "argv", ["trigger", "help"])
        monkeypatch.setattr(trigger, "discover_modules", lambda: [])

        result = trigger.main()
        assert result == 0

    def test_valid_command_routes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Known command is routed to the matching module and returns 0."""
        trigger = _import_trigger()
        monkeypatch.setattr(sys, "argv", ["trigger", "fire", "startup"])
        mock_mod = MagicMock()
        mock_mod.handle_command.return_value = True
        monkeypatch.setattr(trigger, "discover_modules", lambda: [mock_mod])

        result = trigger.main()
        assert result == 0
        mock_mod.handle_command.assert_called_once_with("fire", ["startup"])

    def test_valid_command_no_extra_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Command with no trailing args passes empty list."""
        trigger = _import_trigger()
        monkeypatch.setattr(sys, "argv", ["trigger", "fire"])
        mock_mod = MagicMock()
        mock_mod.handle_command.return_value = True
        monkeypatch.setattr(trigger, "discover_modules", lambda: [mock_mod])

        result = trigger.main()
        assert result == 0
        mock_mod.handle_command.assert_called_once_with("fire", [])

    def test_unknown_command_returns_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unrecognised command calls error() and returns 1."""
        trigger = _import_trigger()
        monkeypatch.setattr(sys, "argv", ["trigger", "bogus"])
        mock_mod = MagicMock()
        mock_mod.handle_command.return_value = False
        monkeypatch.setattr(trigger, "discover_modules", lambda: [mock_mod])

        result = trigger.main()
        assert result == 1
        _mock_error.assert_called_once()

    def test_unknown_command_error_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error call includes the unknown command name and suggestion."""
        trigger = _import_trigger()
        monkeypatch.setattr(sys, "argv", ["trigger", "xyzzy"])
        monkeypatch.setattr(trigger, "discover_modules", lambda: [])

        result = trigger.main()
        assert result == 1
        args, kwargs = _mock_error.call_args
        assert "xyzzy" in args[0]
        assert "suggestion" in kwargs


class TestVersionString:
    """`--version` and the README header must never drift apart again."""

    def test_cli_version_matches_readme_header(self) -> None:
        """The version printed by the CLI is the version the README publishes.

        These were 2.2.0 (CLI) and 2.6.0 (README) when APLAN-0008 measured them:
        four documented releases — the escalation lane and the reload sentinel
        among them — shipped without the string moving. Nothing enforced the
        pairing, so it drifted silently and `--version` misreported the branch.
        """
        import re

        from aipass.trigger.apps.trigger import __version__

        readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
        match = re.search(r"^\*\*Version:\*\*\s*(\S+)", readme, re.MULTILINE)
        assert match, "README must publish a **Version:** header"
        assert __version__ == match.group(1), (
            f"CLI reports {__version__}, README publishes {match.group(1)} — bump both"
        )


class TestUnknownCommandMessage:
    """An unroutable invocation must name the words that failed."""

    def test_unknown_subcommand_names_full_invocation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`medic nonsense` reports both words, not just `medic`.

        Found live in APLAN-0008: `drone @trigger medic nonsense` printed
        "Unknown command: medic". The medic module exists — the subcommand did
        not — so the message accused the one word that was valid.
        """
        trigger = _import_trigger()
        monkeypatch.setattr(sys, "argv", ["trigger", "medic", "nonsense"])
        monkeypatch.setattr(trigger, "discover_modules", lambda: [])

        assert trigger.main() == 1
        printed = [str(c) for c in _mock_error.call_args_list]
        assert any("medic nonsense" in p for p in printed), printed
