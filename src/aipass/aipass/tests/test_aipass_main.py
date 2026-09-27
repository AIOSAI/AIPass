# =================== AIPass ====================
# Name: test_aipass_main.py
# Description: Tests for aipass.py entry point / CLI main
# Version: 1.4.2
# Created: 2026-05-12
# Modified: 2026-09-27
# =============================================

"""Tests for apps/aipass.py and the handlers it drives."""

# main entry point and module discovery.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/aipass.py parses and imports
# seedgo: no-test-needed(documentation) — that the public entry-point functions carry docstrings

from __future__ import annotations

import importlib.metadata
import re
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import aipass.aipass.apps.aipass as aipass_mod
import aipass.aipass.apps.modules as modules_pkg
from aipass.aipass.apps.aipass import (
    _pyproject_version,
    _resolve_version,
    discover_modules,
    main,
    print_help,
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
        """discover_modules returns the live module set, not merely a list.

        The isinstance got company 2026-09-08 (v5 assertion_shape): on its own
        it was equally true of the empty list a broken MODULES_DIR returns.
        Measured on this tree the same day: 11 modules, and the COMMANDs are
        read off the modules themselves so a new one joins the pin by existing.
        The loaded set is pinned to the public files on disk, so a module that
        silently fails to load is named rather than counted.
        Mutant: `if hasattr(module, "handle_command"):` -> `if hasattr(module, "handle_cmd"):` -> red.
        """
        modules_dir = Path(modules_pkg.__file__).parent
        with patch.object(aipass_mod, "MODULES_DIR", modules_dir):
            result = discover_modules()
        assert isinstance(result, list)
        on_disk = sorted(p.stem for p in modules_dir.glob("*.py") if not p.name.startswith("_"))
        assert sorted(m.__name__.rsplit(".", 1)[1] for m in result) == on_disk
        commands = sorted(str(getattr(m, "COMMAND", "")) for m in result)
        assert len(result) >= 11, f"discover_modules found {len(result)}: {commands}"
        assert "doctor" in commands
        assert "help" in commands

    def test_modules_have_handle_command(self) -> None:
        """Every discovered module has a handle_command callable."""
        modules = discover_modules()
        # THE FLOOR (v5 unentered_assert, 2026-09-08). An empty MODULES_DIR
        # made this a silent pass: the body never ran and the run said so
        # nowhere. 11 measured on this tree the same day.
        assert len(modules) >= 11, f"discover_modules found {len(modules)} - the loop below proves nothing"
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
        """ImportError during module load is caught and module skipped.

        A real failure: no aipass.aipass.apps.modules.broken exists to import.
        Mutant: `except Exception as e:` -> `except KeyError as e:` -> red.
        """
        mod_file = tmp_path / "broken.py"
        mod_file.write_text("raise ImportError('bad')\n", encoding="utf-8")
        with patch("aipass.aipass.apps.aipass.MODULES_DIR", tmp_path):
            result = discover_modules()
        assert result == []


# =============================================================================
# TestRouteCommand
# =============================================================================


class TestRouteCommand:
    """Tests for the route_command function."""

    def test_returns_true_when_module_handles(self) -> None:
        """Mutant: True returned without asking the module -> red."""
        mod = MagicMock()
        mod.handle_command.return_value = True
        assert route_command("test", ["x"], [mod]) is True
        mod.handle_command.assert_called_once_with("test", ["x"])

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

    def test_version_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--version prints the real package version and returns 0.

        Mutant: version line not printed -> red.
        """
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "--version"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                result = main()
        out, err = capsys.readouterr()
        assert result == 0
        assert out.startswith("aipass ")
        assert out.strip() != "aipass 0.1.0"
        assert err == ""

    def test_version_flag_short(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: version line not printed -> red."""
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "-V"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                result = main()
        out, _err = capsys.readouterr()
        assert result == 0
        assert out.startswith("aipass ")

    def test_version_flag_fallback(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--version prints 'unknown' when no repo pyproject AND no metadata.

        Mutant: version line not printed -> red.
        """
        _not_found = importlib.metadata.PackageNotFoundError
        with (
            patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "--version"]),
            patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]),
            patch("aipass.aipass.apps.aipass._pyproject_version", return_value=None),
            patch("aipass.aipass.apps.aipass.importlib.metadata.version", side_effect=_not_found),
        ):
            result = main()
        out, _err = capsys.readouterr()
        assert result == 0
        assert out == "aipass unknown\n"

    def test_help_flag_shows_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: --help prints the introspection instead of the help -> red."""
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "--help"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                result = main()
        out, _err = capsys.readouterr()
        assert result == 0
        assert "Usage:" in out
        assert "Examples:" in out

    def test_h_flag_shows_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: --help prints the introspection instead of the help -> red."""
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "-h"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                result = main()
        out, _err = capsys.readouterr()
        assert result == 0
        assert "Usage:" in out

    def test_no_args_shows_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: bare invocation prints the full help -> red."""
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                result = main()
        out, _err = capsys.readouterr()
        assert result == 0
        assert "Run 'aipass --help' for usage and examples" in out
        assert "Usage:" not in out

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

    def test_trailing_help_unknown_command_reports_unknown(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A trailing --help on an unroutable command still errors, not silently 0.

        Mutant: help-guard 'Unknown command' line not printed -> red.
        """
        mod = MagicMock()
        mod.handle_command.return_value = False
        mod.__name__ = "aipass.aipass.apps.modules.trust"
        mod.COMMAND = "trust"
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "nosuch", "arg", "--help"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                result = main()
        out, _err = capsys.readouterr()
        assert result == 1
        assert "Unknown command: nosuch" in out

    def test_introspection_shows_public_commands(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: no public command collected -> red."""
        mod = types.ModuleType("aipass.aipass.apps.modules.help_chat")
        mod.__doc__ = "Help chatbot"
        mod.COMMAND = "help"  # type: ignore[attr-defined]
        mod.handle_command = lambda c, a: True  # type: ignore[attr-defined]
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                main()
        out, _err = capsys.readouterr()
        assert "Commands:" in out
        assert "README-backed Q&A" in out

    def test_introspection_hides_non_public(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: modules listed by file stem, public filter dropped -> red."""
        mod = types.ModuleType("aipass.aipass.apps.modules.internal")
        mod.__doc__ = "Internal module"
        mod.handle_command = lambda c, a: True  # type: ignore[attr-defined]
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                main()
        out, _err = capsys.readouterr()
        assert "internal" not in out
        assert "Commands:" not in out

    def test_unknown_command_returns_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: final 'Unknown command' line not printed -> red."""
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "xyzzy"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                result = main()
        out, _err = capsys.readouterr()
        assert result == 1
        assert out == "Unknown command: xyzzy\n"

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

    def test_at_prefix_shows_drone_guidance(self, capsys: pytest.CaptureFixture[str]) -> None:
        """@drone prints guidance pointing to drone, not 'Unknown command'.

        Mutant: '@name is a drone routing target' line not printed -> red.
        """
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "@drone"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                result = main()
        out, _err = capsys.readouterr()
        assert result == 1
        assert "@drone is a drone routing target" in out
        assert "Unknown command" not in out

    def test_at_prefix_uses_actual_name(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: 'Reach an agent: drone @name' line not printed -> red."""
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "@memory"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                result = main()
        out, _err = capsys.readouterr()
        assert result == 1
        assert "@memory is a drone routing target" in out
        assert "drone @memory ..." in out

    def test_plain_bad_command_still_unknown(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Non-@ bad command still prints 'Unknown command', not drone guidance.

        Mutant: final 'Unknown command' line not printed -> red.
        """
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "frobnicate"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[]):
                result = main()
        out, _err = capsys.readouterr()
        assert result == 1
        assert out == "Unknown command: frobnicate\n"

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

    def test_help_shows_command_constant(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: introspection names modules by file stem -> red."""
        mod = types.ModuleType("aipass.aipass.apps.modules.help_chat")
        mod.__doc__ = "Help chatbot"
        mod.COMMAND = "help"  # type: ignore[attr-defined]
        mod.handle_command = lambda c, a: True  # type: ignore[attr-defined]
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass"]):
            with patch(
                "aipass.aipass.apps.aipass.discover_modules",
                return_value=[mod],
            ):
                main()
        out, _err = capsys.readouterr()
        assert "README-backed Q&A" in out
        assert "help_chat" not in out

    def test_introspection_skips_no_command_module(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: a module without COMMAND listed by file stem -> red."""
        mod = types.ModuleType("aipass.aipass.apps.modules.doctor")
        mod.__doc__ = "Doctor module"
        mod.handle_command = lambda c, a: True  # type: ignore[attr-defined]
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass"]):
            with patch(
                "aipass.aipass.apps.aipass.discover_modules",
                return_value=[mod],
            ):
                main()
        out, _err = capsys.readouterr()
        assert "Commands:" not in out
        assert "doctor" not in out

    def test_multiword_unknown_routes_to_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: 'answering as' notice not printed -> red."""
        mod = MagicMock()
        mod.handle_command.side_effect = lambda c, a: c == "help"
        mod.__name__ = "aipass.aipass.apps.modules.help_chat"
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "what", "is", "drone"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                result = main()
        out, _err = capsys.readouterr()
        assert result == 0
        mod.handle_command.assert_any_call("help", ["what", "is", "drone"])
        assert "answering as: aipass help what is drone" in out

    def test_multiword_with_flag_stays_unknown(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A mistyped command carrying flags must NOT become a help search.

        Mutant: final 'Unknown command' line not printed -> red.
        """
        mod = MagicMock()
        mod.handle_command.side_effect = lambda c, a: c == "help"
        mod.__name__ = "aipass.aipass.apps.modules.help_chat"
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "doctr", "--fix"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                result = main()
        out, _err = capsys.readouterr()
        assert result == 1
        assert out == "Unknown command: doctr\n"

    def test_single_unknown_word_stays_unknown(self, capsys: pytest.CaptureFixture[str]) -> None:
        """One unknown token keeps the loud error — no silent help fallback.

        Mutant: final 'Unknown command' line not printed -> red.
        """
        mod = MagicMock()
        mod.handle_command.side_effect = lambda c, a: c == "help"
        mod.__name__ = "aipass.aipass.apps.modules.help_chat"
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "xyzzy"]):
            with patch("aipass.aipass.apps.aipass.discover_modules", return_value=[mod]):
                result = main()
        out, _err = capsys.readouterr()
        assert result == 1
        assert out == "Unknown command: xyzzy\n"

    def test_handler_crash_surfaces_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Handler crash prints the real error, not 'Unknown command'.

        Mutant: crash reported on the console, not error() -> red.
        """
        mod = MagicMock()
        mod.handle_command.side_effect = RuntimeError("db connection failed")
        mod.__name__ = "aipass.aipass.apps.modules.doctor"
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "doctor"]):
            with patch(
                "aipass.aipass.apps.aipass.discover_modules",
                return_value=[mod],
            ):
                result = main()
        out, err = capsys.readouterr()
        assert result == 1
        assert "'doctor' crashed: db connection failed" in err
        assert "Unknown command" not in out

    def test_import_failure_surfaces_on_command(self, tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
        """Mutant: load failure reported on the console, not error() -> red.

        The failure is a real one: a modules dir under tmp_path holding a file
        whose import fails, found by main()'s own discover_modules.
        Mutant: `_import_failures[file_path.stem] = e` -> `pass` -> red.
        """
        (tmp_path / "broken.py").write_text("def handle_command(c, a):\n    return False\n", encoding="utf-8")
        with patch("aipass.aipass.apps.aipass.sys.argv", ["aipass", "broken"]):
            with patch.object(aipass_mod, "MODULES_DIR", tmp_path):
                result = main()
        out, err = capsys.readouterr()
        assert result == 1
        assert "'broken' failed to load: No module named 'aipass.aipass.apps.modules.broken'" in err
        assert "Unknown command" not in out


# =============================================================================
# TestHelpAgreesWithCode
# =============================================================================


class TestHelpAgreesWithCode:
    """print_help against the verbs the dispatcher actually routes.

    The README carried a hand-typed command table for months and was the only
    witness to three of these; the table is gone (FPLAN-0616), so the page can
    no longer cover for a help line that disagrees with the code.
    """

    @staticmethod
    def _help_text(capsys: pytest.CaptureFixture[str]) -> str:
        """Rendered help as the user reads it on stdout."""
        print_help(modules=[])
        return capsys.readouterr().out

    def test_help_names_revoke(self, capsys: pytest.CaptureFixture[str]) -> None:
        """`revoke` routes in trust.py, so help must name it — it named only `trust`."""
        assert "revoke <path>" in self._help_text(capsys)

    def test_help_does_not_claim_bare_json_is_json_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        """JSON comes from `doctor --fix --json`; `--json` alone falls through."""
        text = self._help_text(capsys)
        assert "doctor --fix --json" in text
        assert "JSON output for structure scan" not in text

    def test_help_names_init_run_not_bare_init(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Bare `init` prints usage; `init run` is what walks the stages."""
        text = self._help_text(capsys)
        assert "init run" in text
        assert re.search(r"aipass init(?! run)", text) is None
