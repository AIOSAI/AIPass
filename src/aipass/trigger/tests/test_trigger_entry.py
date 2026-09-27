# =================== AIPass ====================
# Name: test_trigger_entry.py
# Description: Tests for trigger.py CLI entry point — line coverage
# Version: 1.0.0
# Created: 2026-04-26
# Modified: 2026-09-27
# =============================================

"""Tests for the apps/trigger.py CLI entry point (discover, route, main)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(behaviour) — each command's own behaviour under apps/modules/; each has its own test file

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Infrastructure mocks — isolate from real prax / cli
# ---------------------------------------------------------------------------

_mock_logger = MagicMock()


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace heavy infrastructure imports with lightweight mocks."""
    # Reset call counts between tests
    _mock_logger.reset_mock()

    # ---- prax logger ----
    prax_logger_mod = MagicMock()
    prax_logger_mod.system_logger = _mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules.logger", prax_logger_mod)

    # ---- cli ----
    # cli is REAL here (2026-09-27): console output is read with capsys and a
    # refusal from error() on stderr. The exit seam was already real; a mocked
    # console only let the tests read call args instead of what a user sees.

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

    def test_prints_module_info_with_doc(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Module with __doc__ gets its first line as description."""
        trigger = _import_trigger()
        mock_mod = MagicMock()
        mock_mod.__name__ = "aipass.trigger.apps.modules.fire"
        mock_mod.__doc__ = "Fire all the things\nSecond line ignored"

        trigger.print_introspection([mock_mod])
        # Verify console.print was called with the module name
        joined = capsys.readouterr().out
        assert "fire" in joined

    def test_prints_module_info_without_doc(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Module with __doc__=None shows 'No description'."""
        trigger = _import_trigger()
        mock_mod = MagicMock()
        mock_mod.__name__ = "aipass.trigger.apps.modules.silent"
        mock_mod.__doc__ = None

        trigger.print_introspection([mock_mod])
        joined = capsys.readouterr().out
        assert "No description" in joined

    def test_prints_no_modules_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Empty module list shows 'No modules discovered'."""
        trigger = _import_trigger()
        trigger.print_introspection([])
        joined = capsys.readouterr().out
        assert "No modules discovered" in joined


# ===================================================================
# print_help
# ===================================================================


class TestPrintHelp:
    """Cover print_help() paths."""

    def test_prints_help_with_modules_and_doc(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Help output includes module name and docstring first line."""
        trigger = _import_trigger()
        mock_mod = MagicMock()
        mock_mod.__name__ = "aipass.trigger.apps.modules.status"
        mock_mod.__doc__ = "Show status information\nDetails"

        trigger.print_help([mock_mod])
        joined = capsys.readouterr().out
        assert "status" in joined
        assert "TRIGGER - Branch Management System" in joined

    def test_prints_help_with_modules_no_doc(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Help output shows 'No description' when module lacks docstring."""
        trigger = _import_trigger()
        mock_mod = MagicMock()
        mock_mod.__name__ = "aipass.trigger.apps.modules.quiet"
        mock_mod.__doc__ = None

        trigger.print_help([mock_mod])
        joined = capsys.readouterr().out
        assert "No description" in joined

    def test_prints_help_no_modules(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Help output shows 'No modules discovered' for empty list."""
        trigger = _import_trigger()
        trigger.print_help([])
        joined = capsys.readouterr().out
        assert "No modules discovered" in joined


# ===================================================================
# main
# ===================================================================


class TestMain:
    """Cover main() paths."""

    def test_no_args_shows_introspection(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No CLI args triggers print_introspection and returns 0."""
        trigger = _import_trigger()
        monkeypatch.setattr(trigger, "discover_modules", lambda: [])

        result = trigger.main([])
        assert result == 0
        # print_introspection prints "No modules discovered"
        joined = capsys.readouterr().out
        assert "No modules discovered" in joined

    def test_version_flag(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        """The --version flag prints version string and returns 0."""
        trigger = _import_trigger()
        monkeypatch.setattr(trigger, "discover_modules", lambda: [])

        result = trigger.main(["--version"])
        assert result == 0
        assert f"TRIGGER v{trigger.__version__}" in capsys.readouterr().out

    def test_version_short_flag(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        """The -V short flag prints version string and returns 0."""
        trigger = _import_trigger()
        monkeypatch.setattr(trigger, "discover_modules", lambda: [])

        result = trigger.main(["-V"])
        assert result == 0
        assert f"TRIGGER v{trigger.__version__}" in capsys.readouterr().out

    def test_help_flag(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        """The --help flag calls print_help and returns 0."""
        trigger = _import_trigger()
        monkeypatch.setattr(trigger, "discover_modules", lambda: [])

        result = trigger.main(["--help"])
        assert result == 0
        assert "TRIGGER - Branch Management System" in capsys.readouterr().out

    def test_help_short_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The -h short flag calls print_help and returns 0."""
        trigger = _import_trigger()
        monkeypatch.setattr(trigger, "discover_modules", lambda: [])

        result = trigger.main(["-h"])
        assert result == 0

    def test_help_word(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The bare 'help' command calls print_help and returns 0."""
        trigger = _import_trigger()
        monkeypatch.setattr(trigger, "discover_modules", lambda: [])

        result = trigger.main(["help"])
        assert result == 0

    def test_valid_command_routes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Known command is routed to the matching module and returns 0."""
        trigger = _import_trigger()
        mock_mod = MagicMock()
        mock_mod.handle_command.return_value = True
        monkeypatch.setattr(trigger, "discover_modules", lambda: [mock_mod])

        result = trigger.main(["fire", "startup"])
        assert result == 0
        mock_mod.handle_command.assert_called_once_with("fire", ["startup"])

    def test_a_module_that_refuses_through_error_exits_non_zero(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Handled is not succeeded — a routed refusal must reach the shell.

        Every module of mine that declined through error() still exited 0,
        because main() returned the literal 0 on any truthy route and nothing
        ever read cli's failure flag (canary's fleet sweep, 2026-09-07). A
        caller's `drone @trigger log_events start && <next>` therefore ran
        <next> with no watcher. The route is still handled, so the unknown
        command gate cannot catch this; resolve_exit is what separates the two.
        """
        trigger = _import_trigger()

        def _refuse(command, args):
            from aipass.cli.apps.modules import error

            error("Not started — withdrawn by ruling, not failed")
            return True

        mock_mod = MagicMock()
        mock_mod.handle_command.side_effect = _refuse
        monkeypatch.setattr(trigger, "discover_modules", lambda: [mock_mod])

        result = trigger.main(["start"])

        assert result == 2, "a handled command that refused must not report success"
        assert capsys.readouterr().err.count("❌") == 1

    def test_a_previous_refusal_does_not_colour_the_next_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The failure flag is process-level, so main() resets it at the door.

        cli keeps the flag in module state that outlives a single main(). In a
        long-lived process — anything importing and calling main() twice — one
        refusal would otherwise make every later command exit 2 forever.
        """
        from aipass.cli.apps.modules import mark_command_failed

        trigger = _import_trigger()
        mock_mod = MagicMock()
        mock_mod.handle_command.return_value = True
        monkeypatch.setattr(trigger, "discover_modules", lambda: [mock_mod])

        mark_command_failed()

        assert trigger.main(["fire", "startup"]) == 0

    def test_valid_command_no_extra_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Command with no trailing args passes empty list."""
        trigger = _import_trigger()
        mock_mod = MagicMock()
        mock_mod.handle_command.return_value = True
        monkeypatch.setattr(trigger, "discover_modules", lambda: [mock_mod])

        result = trigger.main(["fire"])
        assert result == 0
        mock_mod.handle_command.assert_called_once_with("fire", [])

    def test_unknown_command_returns_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Unrecognised command reports one error on stderr and returns 1.

        Mutant run: dropping the error() call on the unknown-command arm reddens this.
        """
        trigger = _import_trigger()
        mock_mod = MagicMock()
        mock_mod.handle_command.return_value = False
        monkeypatch.setattr(trigger, "discover_modules", lambda: [mock_mod])

        result = trigger.main(["bogus"])
        assert result == 1
        assert capsys.readouterr().err.count("❌") == 1

    def test_unknown_command_error_message(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Error call includes the unknown command name and suggestion."""
        trigger = _import_trigger()
        monkeypatch.setattr(trigger, "discover_modules", lambda: [])

        result = trigger.main(["xyzzy"])
        assert result == 1
        err = capsys.readouterr().err
        assert "Unknown command: xyzzy" in err
        assert "→ Try:" in err


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

    def test_unknown_subcommand_names_full_invocation(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`medic nonsense` reports both words, not just `medic`.

        Found live in APLAN-0008: `drone @trigger medic nonsense` printed
        "Unknown command: medic". The medic module exists — the subcommand did
        not — so the message accused the one word that was valid.
        """
        trigger = _import_trigger()
        monkeypatch.setattr(trigger, "discover_modules", lambda: [])

        assert trigger.main(["medic", "nonsense"]) == 1
        err = capsys.readouterr().err
        assert "medic nonsense" in err, err

    @pytest.mark.parametrize("module_name", ["errors", "escalation"])
    def test_real_module_refuses_unknown_subcommand_through_the_gate(
        self, monkeypatch: pytest.MonkeyPatch, module_name: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A real module's unknown subcommand exits 1, not 0.

        `errors` printed its own refusal and returned True; `escalation`
        printed help and returned True. Both told the entry point "handled",
        so the invocation exited 0 — a refusal that reports success is
        indistinguishable from a command that worked (FPLAN-0492). Modules
        discovered for real here: mocking them away would prove nothing.
        """
        trigger = _import_trigger()

        assert trigger.main([module_name, "not_a_subcommand_xyz"]) == 1
        err = capsys.readouterr().err
        assert f"{module_name} not_a_subcommand_xyz" in err, err
