# =================== AIPass ====================
# Name: test_flow.py
# Description: Tests for flow.py CLI entry point
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-05-12
# =============================================

"""
Tests for Flow CLI entry point (apps/flow.py)

Covers:
- discover_modules() — module auto-discovery from modules/ directory
- route_command() — command routing to modules
- main() / _main_impl() — CLI entry point, argument parsing, dispatch
- print_introspection() — module listing (no-args output)
- print_help() — full help display
- print_module_help() — per-module help display
"""

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FLOW = "aipass.flow.apps.flow"


def _make_module(
    name: str,
    *,
    has_handle: bool = True,
    doc: str | None = "Short description line",
) -> ModuleType:
    """Create a fake module object that mimics a flow submodule."""
    mod = ModuleType(f"aipass.flow.apps.modules.{name}")
    mod.__doc__ = doc
    if has_handle:
        mod.handle_command = MagicMock(return_value=False)  # type: ignore[attr-defined]
    return mod


def _make_handling_module(name: str, doc: str | None = "Handles things") -> ModuleType:
    """Create a module whose handle_command returns True (claims the command)."""
    mod = _make_module(name, doc=doc)
    mod.handle_command.return_value = True  # type: ignore[union-attr]
    return mod


# ===========================================================================
# discover_modules
# ===========================================================================


class TestDiscoverModules:
    """Tests for discover_modules()."""

    def test_empty_when_modules_dir_missing(self, tmp_path: Path) -> None:
        """Returns empty list when modules/ directory does not exist."""
        from aipass.flow.apps.flow import discover_modules

        fake_dir = tmp_path / "nonexistent"
        with patch(f"{_FLOW}.MODULES_DIR", fake_dir):
            result = discover_modules()
        assert result == []

    def test_discovers_module_with_handle_command(self, tmp_path: Path) -> None:
        """Discovers .py files that expose handle_command()."""
        from aipass.flow.apps.flow import discover_modules

        # Create a fake .py file in the modules dir
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        (modules_dir / "good_mod.py").write_text("# stub", encoding="utf-8")

        fake_module = _make_module("good_mod")

        with (
            patch(f"{_FLOW}.MODULES_DIR", modules_dir),
            patch(f"{_FLOW}.importlib.import_module", return_value=fake_module),
        ):
            result = discover_modules()

        assert len(result) == 1
        assert result[0] is fake_module

    def test_skips_module_without_handle_command(self, tmp_path: Path) -> None:
        """Skips modules that lack handle_command()."""
        from aipass.flow.apps.flow import discover_modules

        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        (modules_dir / "no_handle.py").write_text("# stub", encoding="utf-8")

        fake_module = _make_module("no_handle", has_handle=False)

        with (
            patch(f"{_FLOW}.MODULES_DIR", modules_dir),
            patch(f"{_FLOW}.importlib.import_module", return_value=fake_module),
        ):
            result = discover_modules()

        assert result == []

    def test_skips_underscore_files(self, tmp_path: Path) -> None:
        """Ignores files starting with underscore (e.g., __init__.py)."""
        from aipass.flow.apps.flow import discover_modules

        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        (modules_dir / "__init__.py").write_text("# init", encoding="utf-8")
        (modules_dir / "_private.py").write_text("# private", encoding="utf-8")

        import_mock = MagicMock()

        with (
            patch(f"{_FLOW}.MODULES_DIR", modules_dir),
            patch(f"{_FLOW}.importlib.import_module", import_mock),
        ):
            result = discover_modules()

        assert result == []
        import_mock.assert_not_called()

    def test_handles_import_error_gracefully(self, tmp_path: Path) -> None:
        """Logs error and continues when a module fails to import."""
        from aipass.flow.apps.flow import discover_modules

        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        (modules_dir / "bad_mod.py").write_text("# broken", encoding="utf-8")

        with (
            patch(f"{_FLOW}.MODULES_DIR", modules_dir),
            patch(
                f"{_FLOW}.importlib.import_module",
                side_effect=ImportError("boom"),
            ),
        ):
            result = discover_modules()

        assert result == []

    def test_discovers_multiple_modules(self, tmp_path: Path) -> None:
        """Discovers all valid modules in the directory."""
        from aipass.flow.apps.flow import discover_modules

        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        (modules_dir / "alpha.py").write_text("# stub", encoding="utf-8")
        (modules_dir / "beta.py").write_text("# stub", encoding="utf-8")

        mod_a = _make_module("alpha")
        mod_b = _make_module("beta")

        def _fake_import(name: str) -> ModuleType:
            """Route import calls to pre-built fake modules."""
            if "alpha" in name:
                return mod_a
            return mod_b

        with (
            patch(f"{_FLOW}.MODULES_DIR", modules_dir),
            patch(f"{_FLOW}.importlib.import_module", side_effect=_fake_import),
        ):
            result = discover_modules()

        assert len(result) == 2


# ===========================================================================
# route_command
# ===========================================================================


class TestRouteCommand:
    """Tests for route_command()."""

    def test_routes_to_handling_module(self) -> None:
        """Returns True when a module handles the command."""
        from aipass.flow.apps.flow import route_command

        mod = _make_handling_module("create_plan")
        result = route_command("create", [".", "subject"], [mod])

        assert result is True
        mod.handle_command.assert_called_once_with("create", [".", "subject"])

    def test_returns_false_when_no_module_handles(self) -> None:
        """Returns False when no module claims the command."""
        from aipass.flow.apps.flow import route_command

        mod = _make_module("create_plan")  # handle_command returns False
        result = route_command("unknown", [], [mod])

        assert result is False

    def test_handles_broken_pipe_error(self) -> None:
        """Catches BrokenPipeError and returns True."""
        from aipass.flow.apps.flow import route_command

        mod = _make_module("list_plans")
        mod.handle_command.side_effect = BrokenPipeError  # type: ignore[union-attr]

        result = route_command("list", [], [mod])
        assert result is True

    def test_handles_generic_exception(self) -> None:
        """Catches generic exceptions, logs, and continues to next module."""
        from aipass.flow.apps.flow import route_command

        bad_mod = _make_module("bad")
        bad_mod.handle_command.side_effect = RuntimeError("kaboom")  # type: ignore[union-attr]

        good_mod = _make_handling_module("good")

        result = route_command("cmd", [], [bad_mod, good_mod])
        assert result is True
        good_mod.handle_command.assert_called_once()

    def test_returns_false_on_empty_modules(self) -> None:
        """Returns False when modules list is empty."""
        from aipass.flow.apps.flow import route_command

        result = route_command("anything", [], [])
        assert result is False

    def test_stops_routing_after_first_handler(self) -> None:
        """Stops after the first module claims the command."""
        from aipass.flow.apps.flow import route_command

        mod_a = _make_handling_module("first")
        mod_b = _make_module("second")

        result = route_command("cmd", [], [mod_a, mod_b])
        assert result is True
        mod_b.handle_command.assert_not_called()

    def test_all_modules_fail_with_exceptions(self) -> None:
        """Returns False when every module raises an exception."""
        from aipass.flow.apps.flow import route_command

        mod = _make_module("failing")
        mod.handle_command.side_effect = ValueError("nope")  # type: ignore[union-attr]

        result = route_command("cmd", [], [mod])
        assert result is False


# ===========================================================================
# main / _main_impl
# ===========================================================================


class TestMain:
    """Tests for main() entry point."""

    def test_returns_1_when_no_modules(self) -> None:
        """Returns 1 and prints error when no modules discovered."""
        from aipass.flow.apps.flow import main

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[]),
            patch.object(sys, "argv", ["flow"]),
        ):
            result = main()
        assert result == 1

    def test_introspection_on_no_args(self) -> None:
        """Shows introspection when called with no arguments."""
        from aipass.flow.apps.flow import main

        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_introspection") as mock_intro,
            patch.object(sys, "argv", ["flow"]),
        ):
            result = main()

        assert result == 0
        mock_intro.assert_called_once_with([mod])

    def test_version_long_flag(self) -> None:
        """--version prints version and returns 0."""
        from aipass.flow.apps.flow import main

        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch.object(sys, "argv", ["flow", "--version"]),
        ):
            result = main()
        assert result == 0

    def test_version_short_flag(self) -> None:
        """-V prints version and returns 0."""
        from aipass.flow.apps.flow import main

        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch.object(sys, "argv", ["flow", "-V"]),
        ):
            result = main()
        assert result == 0

    def test_help_long_flag(self) -> None:
        """--help shows help and returns 0."""
        from aipass.flow.apps.flow import main

        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_help") as mock_help,
            patch.object(sys, "argv", ["flow", "--help"]),
        ):
            result = main()

        assert result == 0
        mock_help.assert_called_once()

    def test_help_short_flag(self) -> None:
        """-h shows help and returns 0."""
        from aipass.flow.apps.flow import main

        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_help") as mock_help,
            patch.object(sys, "argv", ["flow", "-h"]),
        ):
            result = main()

        assert result == 0
        mock_help.assert_called_once()

    def test_help_word(self) -> None:
        """'help' word shows help and returns 0."""
        from aipass.flow.apps.flow import main

        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_help") as mock_help,
            patch.object(sys, "argv", ["flow", "help"]),
        ):
            result = main()

        assert result == 0
        mock_help.assert_called_once()

    def test_routes_known_command(self) -> None:
        """Routes a valid command and returns 0."""
        from aipass.flow.apps.flow import main

        mod = _make_handling_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch.object(sys, "argv", ["flow", "create", ".", "subject"]),
        ):
            result = main()

        assert result == 0
        mod.handle_command.assert_called_once_with("create", [".", "subject"])

    def test_unknown_command_returns_1(self) -> None:
        """Returns 1 for an unrecognized command."""
        from aipass.flow.apps.flow import main

        mod = _make_module("create_plan")  # handle_command returns False

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch.object(sys, "argv", ["flow", "bogus"]),
        ):
            result = main()

        assert result == 1

    def test_unknown_command_with_help_flag(self) -> None:
        """Shows module help when unknown command is followed by --help."""
        from aipass.flow.apps.flow import main

        mod = _make_module("create_plan")  # handle_command returns False

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_module_help") as mock_mod_help,
            patch.object(sys, "argv", ["flow", "bogus", "--help"]),
        ):
            result = main()

        assert result == 0
        mock_mod_help.assert_called_once_with("bogus", [mod])

    def test_unknown_command_with_short_help_flag(self) -> None:
        """Shows module help when unknown command is followed by -h."""
        from aipass.flow.apps.flow import main

        mod = _make_module("create_plan")  # handle_command returns False

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_module_help") as mock_mod_help,
            patch.object(sys, "argv", ["flow", "bogus", "-h"]),
        ):
            result = main()

        assert result == 0
        mock_mod_help.assert_called_once_with("bogus", [mod])

    def test_command_with_no_extra_args(self) -> None:
        """Routes command with empty remaining args."""
        from aipass.flow.apps.flow import main

        mod = _make_handling_module("list_plans")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch.object(sys, "argv", ["flow", "list"]),
        ):
            result = main()

        assert result == 0
        mod.handle_command.assert_called_once_with("list", [])

    def test_main_catches_unhandled_exception(self) -> None:
        """main() catches unexpected exceptions from _main_impl and returns 1."""
        from aipass.flow.apps.flow import main

        with patch(f"{_FLOW}.discover_modules", side_effect=RuntimeError("boom")):
            with patch.object(sys, "argv", ["flow"]):
                result = main()
        assert result == 1


# ===========================================================================
# print_introspection
# ===========================================================================


class TestPrintIntrospection:
    """Tests for print_introspection()."""

    def test_with_modules(self) -> None:
        """Displays module names and descriptions."""
        from aipass.flow.apps.flow import print_introspection

        mod = _make_module("create_plan", doc="Create a new plan")
        print_introspection([mod])

    def test_with_empty_modules(self) -> None:
        """Displays fallback text when no modules discovered."""
        from aipass.flow.apps.flow import print_introspection

        print_introspection([])

    def test_module_without_docstring(self) -> None:
        """Uses 'No description' when module has no docstring."""
        from aipass.flow.apps.flow import print_introspection

        mod = _make_module("bare_mod", doc=None)
        print_introspection([mod])

    @pytest.mark.parametrize("names", [("alpha",), ("alpha", "beta")])
    def test_every_discovered_module_is_named(self, names) -> None:
        """One module or several, each one appears in the listing.

        MERGED (DPLAN-0323 contested band, 2026-09-07) with the former
        ``test_multiple_modules``, which ran the identical call path with two
        list entries instead of one and asserted nothing — 'lists all
        discovered modules' was never read back. Mutation-checked before
        merging: dropping the second module changed no branch, so the count is
        a parameter, not a test. The oracle is new: both rows now READ the
        output, so deleting the loop body reds them.
        """
        from aipass.flow.apps.flow import print_introspection

        with patch(f"{_FLOW}.console") as mock_console:
            print_introspection([_make_module(name, doc=f"{name} module") for name in names])

        printed = " ".join(str(call.args[0]) for call in mock_console.print.call_args_list if call.args)
        for name in names:
            assert name in printed


# ===========================================================================
# print_help
# ===========================================================================


class TestPrintHelp:
    """Tests for print_help()."""

    def test_with_modules(self) -> None:
        """Shows formatted help with module listing."""
        from aipass.flow.apps.flow import print_help

        mod = _make_module("create_plan", doc="Create a new plan")
        print_help([mod])

    def test_with_empty_modules(self) -> None:
        """Shows help even when no modules are discovered."""
        from aipass.flow.apps.flow import print_help

        print_help([])

    @pytest.mark.parametrize(
        ("module_name", "expected_short"),
        [("create_plan", "create"), ("templates", None)],
    )
    def test_a_short_form_is_shown_only_when_the_name_has_one(self, module_name, expected_short) -> None:
        """An underscored name prints 'short, full'; a single word prints once.

        MERGED (DPLAN-0323 contested band, 2026-09-07) from
        ``test_module_with_underscore`` and ``test_module_without_underscore``,
        which made the identical call as their sibling with a different name
        string and asserted nothing — the 'no short form' and 'shows short and
        full name' claims were never read. Kept as a PARAMETRISED pair rather
        than deleted, because unlike the introspection twins these two DO
        straddle a real branch (``if short_name != module_name`` in flow.py),
        and each row now carries the oracle its own claim needs.
        """
        from aipass.flow.apps.flow import print_help

        with patch(f"{_FLOW}.console") as mock_console:
            print_help([_make_module(module_name, doc="Any description")])

        printed = " ".join(str(call.args[0]) for call in mock_console.print.call_args_list if call.args)
        assert module_name in printed
        if expected_short:
            assert f"{expected_short}," in printed
        else:
            assert f"{module_name}," not in printed

    def test_module_without_docstring(self) -> None:
        """Uses 'No description' for undocumented modules."""
        from aipass.flow.apps.flow import print_help

        mod = _make_module("mystery", doc=None)
        print_help([mod])


# ===========================================================================
# print_module_help
# ===========================================================================


class TestPrintModuleHelp:
    """Tests for print_module_help()."""

    def test_exact_match(self) -> None:
        """Finds module by exact name match."""
        from aipass.flow.apps.flow import print_module_help

        mod = _make_module("create_plan", doc="Create plans\nMore details here")
        print_module_help("create_plan", [mod])

    def test_no_match(self) -> None:
        """Shows error for unknown command."""
        from aipass.flow.apps.flow import print_module_help

        mod = _make_module("create_plan")
        print_module_help("nonexistent", [mod])

    def test_module_without_docstring(self) -> None:
        """Shows 'No documentation available' for undocumented module."""
        from aipass.flow.apps.flow import print_module_help

        mod = _make_module("bare_mod", doc=None)
        print_module_help("bare_mod", [mod])

    def test_a_multiline_docstring_is_shown_whole_and_stripped(self) -> None:
        """Every line reaches the reader, without the leading/trailing blanks.

        KEPT rather than merged into ``test_exact_match`` (DPLAN-0323 contested
        band, 2026-09-07). The two make the same found-module call, but this
        one's subject is what ``print_module_help`` does to a docstring that
        spans lines — ``.strip()`` on the whole string, not the first line
        only, which is what the module listing does instead. Mutation-checked:
        with the assertions it now carries, printing only the first line reds
        it; before, it asserted nothing and both spellings passed.
        """
        from aipass.flow.apps.flow import print_module_help

        mod = _make_module(
            "list_plans",
            doc="\nList plans\n\nShows all plans in the registry.\n",
        )
        with patch(f"{_FLOW}.console") as mock_console:
            print_module_help("list_plans", [mod])

        printed = " ".join(str(call.args[0]) for call in mock_console.print.call_args_list if call.args)
        assert "List plans" in printed
        assert "Shows all plans in the registry." in printed
        assert not printed.strip().endswith("\\n")
