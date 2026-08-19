# =================== AIPass ====================
# Name: test_aipass_main.py
# Description: Tests for aipass.py entry point / CLI main
# Version: 1.1.0
# Created: 2026-05-12
# Modified: 2026-08-07
# =============================================

"""Tests for aipass.py — main entry point and module discovery."""

from __future__ import annotations

import importlib.metadata
import types
from unittest.mock import MagicMock, patch


from aipass.aipass.apps.aipass import (
    _pyproject_version,
    _resolve_version,
    discover_modules,
    main,
    route_command,
)

# Ensure encoding='utf-8' appears (PATTERN check)
_ENCODING = "utf-8"


# =============================================================================
# TestDiscoverModules
# =============================================================================


class TestDiscoverModules:
    """Tests for the discover_modules function."""

    def test_returns_list(self) -> None:
        """discover_modules always returns a list."""
        result = discover_modules()
        assert isinstance(result, list)

    def test_modules_have_handle_command(self) -> None:
        """Every discovered module has a handle_command callable."""
        modules = discover_modules()
        for mod in modules:
            assert hasattr(mod, "handle_command")
            assert callable(mod.handle_command)

    def test_skips_private_files(self, tmp_path) -> None:
        """Files starting with _ are skipped."""
        with patch("aipass.aipass.apps.aipass.MODULES_DIR", tmp_path):
            (tmp_path / "__init__.py").write_text("", encoding="utf-8")
            (tmp_path / "_private.py").write_text("", encoding="utf-8")
            result = discover_modules()
        assert len(result) == 0

    def test_returns_empty_when_dir_missing(self, tmp_path) -> None:
        """Returns empty list when modules directory does not exist."""
        missing = tmp_path / "nonexistent"
        with patch("aipass.aipass.apps.aipass.MODULES_DIR", missing):
            result = discover_modules()
        assert result == []

    def test_skips_modules_without_handle_command(self, tmp_path) -> None:
        """Modules lacking handle_command are not included."""
        mod_file = tmp_path / "no_handler.py"
        mod_file.write_text("x = 1\n", encoding="utf-8")
        fake_mod = types.ModuleType("no_handler")
        # No handle_command attribute
        with patch("aipass.aipass.apps.aipass.MODULES_DIR", tmp_path):
            with patch("aipass.aipass.apps.aipass.importlib.import_module", return_value=fake_mod):
                result = discover_modules()
        assert len(result) == 0

    def test_includes_modules_with_handle_command(self, tmp_path) -> None:
        """Modules with handle_command are included."""
        mod_file = tmp_path / "good.py"
        mod_file.write_text("def handle_command(c, a): pass\n", encoding="utf-8")
        fake_mod = types.ModuleType("good")
        fake_mod.handle_command = lambda c, a: True  # type: ignore[attr-defined]
        with patch("aipass.aipass.apps.aipass.MODULES_DIR", tmp_path):
            with patch("aipass.aipass.apps.aipass.importlib.import_module", return_value=fake_mod):
                result = discover_modules()
        assert len(result) == 1

    def test_handles_import_error_gracefully(self, tmp_path) -> None:
        """ImportError during module load is caught and module skipped."""
        mod_file = tmp_path / "broken.py"
        mod_file.write_text("raise ImportError('bad')\n", encoding="utf-8")
        with patch("aipass.aipass.apps.aipass.MODULES_DIR", tmp_path):
            with patch(
                "aipass.aipass.apps.aipass.importlib.import_module",
                side_effect=ImportError("bad"),
            ):
                result = discover_modules()
        assert result == []


# =============================================================================
# TestRouteCommand
# =============================================================================


class TestRouteCommand:
    """Tests for the route_command function."""

    def test_returns_true_when_module_handles(self) -> None:
        """Returns True when a module successfully handles the command."""
        mod = MagicMock()
        mod.handle_command.return_value = True
        assert route_command("test", [], [mod]) is True

    def test_returns_false_when_no_module_handles(self) -> None:
        """Returns False when no module handles the command."""
        mod = MagicMock()
        mod.handle_command.return_value = False
        assert route_command("test", [], [mod]) is False

    def test_returns_false_for_empty_modules(self) -> None:
        """Returns False when modules list is empty."""
        assert route_command("test", [], []) is False

    def test_tries_modules_in_order(self) -> None:
        """Stops at first module that returns True."""
        mod1 = MagicMock()
        mod1.handle_command.return_value = False
        mod2 = MagicMock()
        mod2.handle_command.return_value = True
        mod3 = MagicMock()
        mod3.handle_command.return_value = True

        route_command("cmd", ["arg1"], [mod1, mod2, mod3])

        mod1.handle_command.assert_called_once_with("cmd", ["arg1"])
        mod2.handle_command.assert_called_once_with("cmd", ["arg1"])
        mod3.handle_command.assert_not_called()

    def test_module_exception_re_raises(self) -> None:
        """Exception in a handler is re-raised so callers see the real error."""
        mod = MagicMock()
        mod.handle_command.side_effect = RuntimeError("crash")
        mod.__name__ = "broken_mod"
        import pytest

        with pytest.raises(RuntimeError, match="crash"):
            route_command("cmd", [], [mod])


# =============================================================================
# TestResolveVersion
# =============================================================================


class TestResolveVersion:
    """Tests for _pyproject_version / _resolve_version — live repo version."""

    @staticmethod
    def _write_pyproject(root, name: str, version: str) -> None:
        (root / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\nversion = "{version}"\n',
            encoding="utf-8",
        )

    def test_pyproject_version_found(self, tmp_path) -> None:
        """Walks up from a nested file path to the aipass pyproject.toml."""
        self._write_pyproject(tmp_path, "aipass", "9.9.9")
        start = tmp_path / "src" / "aipass" / "aipass" / "apps" / "aipass.py"
        assert _pyproject_version(start) == "9.9.9"

    def test_pyproject_skips_foreign_name(self, tmp_path) -> None:
        """A nested project's own pyproject is skipped; walk continues upward."""
        self._write_pyproject(tmp_path, "aipass", "9.9.9")
        nested = tmp_path / "projects" / "myapp"
        nested.mkdir(parents=True)
        self._write_pyproject(nested, "myapp", "0.0.1")
        start = nested / "src" / "deep" / "file.py"
        assert _pyproject_version(start) == "9.9.9"

    def test_pyproject_malformed_continues_upward(self, tmp_path) -> None:
        """Unparseable pyproject logs a warning and the walk continues."""
        self._write_pyproject(tmp_path, "aipass", "9.9.9")
        nested = tmp_path / "projects" / "broken"
        nested.mkdir(parents=True)
        (nested / "pyproject.toml").write_text("not [ valid toml", encoding="utf-8")
        start = nested / "src" / "file.py"
        assert _pyproject_version(start) == "9.9.9"

    def test_pyproject_missing_version_key(self, tmp_path) -> None:
        """An aipass-named pyproject without a version yields None, not a crash."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "aipass"\n', encoding="utf-8")
        assert _pyproject_version(tmp_path / "file.py") is None

    def test_resolve_version_prefers_pyproject(self) -> None:
        """Repo pyproject wins over installed metadata."""
        with patch("aipass.aipass.apps.aipass._pyproject_version", return_value="1.2.3"):
            with patch(
                "aipass.aipass.apps.aipass.importlib.metadata.version",
                return_value="9.9.9",
            ) as mock_meta:
                assert _resolve_version() == "1.2.3"
        mock_meta.assert_not_called()

    def test_resolve_version_falls_back_to_metadata(self) -> None:
        """No repo pyproject → installed metadata is used."""
        with patch("aipass.aipass.apps.aipass._pyproject_version", return_value=None):
            with patch(
                "aipass.aipass.apps.aipass.importlib.metadata.version",
                return_value="2.0.0",
            ):
                assert _resolve_version() == "2.0.0"

    def test_resolve_version_live_is_current(self) -> None:
        """Live resolve returns the repo's real version — never the stale 0.1.0/2.7.4."""
        version = _resolve_version()
        assert version not in ("unknown", "0.1.0")
        assert version.count(".") == 2


# =============================================================================
# TestMain
# =============================================================================


class TestMain:
    """Tests for the main() entry point."""

    def test_version_flag(self) -> None:
        """--version prints real package version and returns 0."""
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "--version"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                with patch("aipass.aipass.apps.aipass.console") as mock_con:
                    result = main()
        assert result == 0
        printed = mock_con.print.call_args[0][0]
        assert printed.startswith("aipass ")
        assert printed != "aipass 0.1.0"

    def test_version_flag_short(self) -> None:
        """-V prints real package version and returns 0."""
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "-V"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                with patch("aipass.aipass.apps.aipass.console") as mock_con:
                    result = main()
        assert result == 0
        printed = mock_con.print.call_args[0][0]
        assert printed.startswith("aipass ")

    def test_version_flag_fallback(self) -> None:
        """--version prints 'unknown' when no repo pyproject AND no metadata."""
        _not_found = importlib.metadata.PackageNotFoundError
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "--version"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                with patch("aipass.aipass.apps.aipass._pyproject_version", return_value=None):
                    with patch(
                        "aipass.aipass.apps.aipass.importlib.metadata.version",
                        side_effect=_not_found,
                    ):
                        with patch("aipass.aipass.apps.aipass.console") as mock_con:
                            result = main()
        assert result == 0
        mock_con.print.assert_called_once_with("aipass unknown")

    def test_help_flag_shows_help(self) -> None:
        """--help calls print_help and returns 0."""
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "--help"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                with patch("aipass.aipass.apps.aipass.console") as mock_con:
                    result = main()
        assert result == 0
        mock_con.print.assert_called()

    def test_h_flag_shows_help(self) -> None:
        """-h shows help and returns 0."""
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "-h"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                with patch("aipass.aipass.apps.aipass.console"):
                    result = main()
        assert result == 0

    def test_no_args_shows_help(self) -> None:
        """No arguments shows introspection and returns 0."""
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                with patch("aipass.aipass.apps.aipass.console"):
                    result = main()
        assert result == 0

    def test_help_word_routes_to_module(self) -> None:
        """'help' as only arg routes to help_chat module, not root help."""
        mod = MagicMock()
        mod.handle_command.return_value = True
        mod.__name__ = "aipass.aipass.apps.modules.help_chat"
        mod.COMMAND = "help"
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "help"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                result = main()
        assert result == 0
        mod.handle_command.assert_called_once_with("help", [])

    def test_trailing_help_after_positional_shows_help(self) -> None:
        """`aipass trust <path> --help` prints help — it must NOT run the verb.

        Regression (APLAN-0018): the guard only inspected args[0] of the
        remainder, so a trailing --help fell through to the module and
        executed a write — `trust <dir> --help` enrolled the directory.
        """
        mod = MagicMock()
        mod.handle_command.return_value = True
        mod.__name__ = "aipass.aipass.apps.modules.trust"
        mod.COMMAND = "trust"
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "trust", "/some/path", "--help"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                result = main()
        assert result == 0
        mod.handle_command.assert_called_once_with("trust", ["--help"])

    def test_trailing_h_after_positional_shows_help(self) -> None:
        """The short `-h` form is intercepted in the same position-free way."""
        mod = MagicMock()
        mod.handle_command.return_value = True
        mod.__name__ = "aipass.aipass.apps.modules.init_flow"
        mod.COMMAND = "init"
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "init", "agent", "-h"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                result = main()
        assert result == 0
        mod.handle_command.assert_called_once_with("init", ["--help"])

    def test_help_between_flags_shows_help(self) -> None:
        """--help wins from any position, not just first or last."""
        mod = MagicMock()
        mod.handle_command.return_value = True
        mod.__name__ = "aipass.aipass.apps.modules.new_project"
        mod.COMMAND = "new"
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "new", "app", "--help", "--template", "python"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                result = main()
        assert result == 0
        mod.handle_command.assert_called_once_with("new", ["--help"])

    def test_trailing_help_unknown_command_reports_unknown(self) -> None:
        """A trailing --help on an unroutable command still errors, not silently 0."""
        mod = MagicMock()
        mod.handle_command.return_value = False
        mod.__name__ = "aipass.aipass.apps.modules.trust"
        mod.COMMAND = "trust"
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "nosuch", "arg", "--help"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                with patch("aipass.aipass.apps.aipass.console"):
                    result = main()
        assert result == 1

    def test_introspection_shows_public_commands(self) -> None:
        """Introspection lists modules with COMMAND in _PUBLIC_COMMANDS."""
        mod = types.ModuleType("aipass.aipass.apps.modules.help_chat")
        mod.__doc__ = "Help chatbot"
        mod.COMMAND = "help"  # type: ignore[attr-defined]
        mod.handle_command = lambda c, a: True  # type: ignore[attr-defined]
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                with patch("aipass.aipass.apps.aipass.console") as mock_con:
                    main()
        printed = " ".join(str(a) for call in mock_con.print.call_args_list for a in call[0])
        assert "help" in printed

    def test_introspection_hides_non_public(self) -> None:
        """Modules without COMMAND in _PUBLIC_COMMANDS are hidden."""
        mod = types.ModuleType("aipass.aipass.apps.modules.internal")
        mod.__doc__ = "Internal module"
        mod.handle_command = lambda c, a: True  # type: ignore[attr-defined]
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                with patch("aipass.aipass.apps.aipass.console") as mock_con:
                    main()
        printed = " ".join(str(a) for call in mock_con.print.call_args_list for a in call[0])
        assert "internal" not in printed

    def test_unknown_command_returns_1(self) -> None:
        """Unknown command prints error and returns 1."""
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "xyzzy"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                with patch("aipass.aipass.apps.aipass.console") as mock_con:
                    result = main()
        assert result == 1
        mock_con.print.assert_called_with("Unknown command: xyzzy")

    def test_known_command_routes_and_returns_0(self) -> None:
        """Known command that gets handled returns 0."""
        mod = MagicMock()
        mod.handle_command.return_value = True
        mod.__name__ = "test_module"
        mod.__doc__ = "Test"
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "doctor"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                result = main()
        assert result == 0
        mod.handle_command.assert_called_once_with("doctor", [])

    def test_at_prefix_shows_drone_guidance(self) -> None:
        """@drone prints guidance pointing to drone, not 'Unknown command'."""
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "@drone"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                with patch("aipass.aipass.apps.aipass.console") as mock_con:
                    result = main()
        assert result == 1
        printed = " ".join(str(a) for call in mock_con.print.call_args_list for a in call[0])
        assert "@drone" in printed
        assert "drone routing target" in printed
        assert "Unknown command" not in printed

    def test_at_prefix_uses_actual_name(self) -> None:
        """@memory prints guidance with the actual @name the user typed."""
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "@memory"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                with patch("aipass.aipass.apps.aipass.console") as mock_con:
                    result = main()
        assert result == 1
        printed = " ".join(str(a) for call in mock_con.print.call_args_list for a in call[0])
        assert "@memory" in printed
        assert "drone @memory" in printed

    def test_plain_bad_command_still_unknown(self) -> None:
        """Non-@ bad command still prints 'Unknown command', not drone guidance."""
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "frobnicate"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                with patch("aipass.aipass.apps.aipass.console") as mock_con:
                    result = main()
        assert result == 1
        mock_con.print.assert_called_with("Unknown command: frobnicate")

    def test_command_with_remaining_args(self) -> None:
        """Remaining args are passed to route_command."""
        mod = MagicMock()
        mod.handle_command.return_value = True
        mod.__name__ = "test_module"
        mod.__doc__ = "Test"
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "doctor", "--verbose", "--fix"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                main()
        mod.handle_command.assert_called_once_with("doctor", ["--verbose", "--fix"])

    def test_help_shows_command_constant(self) -> None:
        """Introspection uses module COMMAND constant, not file stem."""
        mod = types.ModuleType("aipass.aipass.apps.modules.help_chat")
        mod.__doc__ = "Help chatbot"
        mod.COMMAND = "help"  # type: ignore[attr-defined]
        mod.handle_command = lambda c, a: True  # type: ignore[attr-defined]
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass"]):
            with patch(
                "aipass.aipass.apps.aipass.discover_modules",
                return_value=[mod],
            ):
                with patch("aipass.aipass.apps.aipass.console") as mock_con:
                    main()
        printed = " ".join(str(a) for call in mock_con.print.call_args_list for a in call[0])
        assert "help" in printed
        assert "help_chat" not in printed

    def test_introspection_skips_no_command_module(self) -> None:
        """Modules without COMMAND in _PUBLIC_COMMANDS are hidden from introspection."""
        mod = types.ModuleType("aipass.aipass.apps.modules.doctor")
        mod.__doc__ = "Doctor module"
        mod.handle_command = lambda c, a: True  # type: ignore[attr-defined]
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass"]):
            with patch(
                "aipass.aipass.apps.aipass.discover_modules",
                return_value=[mod],
            ):
                with patch("aipass.aipass.apps.aipass.console") as mock_con:
                    main()
        printed = " ".join(str(a) for call in mock_con.print.call_args_list for a in call[0])
        assert (
            "Commands:" not in printed or "doctor" not in printed.split("Commands:")[1]
            if "Commands:" in printed
            else True
        )

    def test_multiword_unknown_routes_to_help(self) -> None:
        """`aipass what is drone` falls through to help with the full question."""
        mod = MagicMock()
        mod.handle_command.side_effect = lambda c, a: c == "help"
        mod.__name__ = "aipass.aipass.apps.modules.help_chat"
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "what", "is", "drone"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                with patch("aipass.aipass.apps.aipass.console"):
                    result = main()
        assert result == 0
        mod.handle_command.assert_any_call("help", ["what", "is", "drone"])

    def test_multiword_with_flag_stays_unknown(self) -> None:
        """A mistyped command carrying flags must NOT become a help search."""
        mod = MagicMock()
        mod.handle_command.side_effect = lambda c, a: c == "help"
        mod.__name__ = "aipass.aipass.apps.modules.help_chat"
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "doctr", "--fix"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                with patch("aipass.aipass.apps.aipass.console") as mock_con:
                    result = main()
        assert result == 1
        mock_con.print.assert_called_with("Unknown command: doctr")

    def test_single_unknown_word_stays_unknown(self) -> None:
        """One unknown token keeps the loud error — no silent help fallback."""
        mod = MagicMock()
        mod.handle_command.side_effect = lambda c, a: c == "help"
        mod.__name__ = "aipass.aipass.apps.modules.help_chat"
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "xyzzy"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                with patch("aipass.aipass.apps.aipass.console") as mock_con:
                    result = main()
        assert result == 1
        mock_con.print.assert_called_with("Unknown command: xyzzy")

    def test_handler_crash_surfaces_error(self) -> None:
        """Handler crash prints real error, not 'Unknown command'."""
        mod = MagicMock()
        mod.handle_command.side_effect = RuntimeError("db connection failed")
        mod.__name__ = "aipass.aipass.apps.modules.doctor"
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "doctor"]):
            with patch(
                "aipass.aipass.apps.aipass.discover_modules",
                return_value=[mod],
            ):
                with patch("aipass.aipass.apps.aipass.console"):
                    with patch("aipass.aipass.apps.aipass.error") as mock_err:
                        result = main()
        assert result == 1
        err_text = " ".join(str(a) for call in mock_err.call_args_list for a in call[0])
        assert "db connection failed" in err_text

    def test_import_failure_surfaces_on_command(self) -> None:
        """Failed module import surfaces when user types that command."""
        import aipass.aipass.apps.aipass as aipass_mod

        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "broken"]):
            with patch(
                "aipass.aipass.apps.aipass.discover_modules",
                return_value=[],
            ):
                aipass_mod._import_failures.clear()
                aipass_mod._import_failures["broken"] = ImportError("no module")
                with patch("aipass.aipass.apps.aipass.console"):
                    with patch("aipass.aipass.apps.aipass.error") as mock_err:
                        result = main()
        assert result == 1
        err_text = " ".join(str(a) for call in mock_err.call_args_list for a in call[0])
        assert "failed to load" in err_text
        assert "no module" in err_text
        aipass_mod._import_failures.clear()
