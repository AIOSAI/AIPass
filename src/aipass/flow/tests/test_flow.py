# =================== AIPass ====================
# Name: test_flow.py
# Description: Tests for flow.py CLI entry point
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-09-27
# =============================================

"""Tests for apps/flow.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that flow.py parses and imports
# seedgo: no-test-needed(stdlib) — the `if __name__ == "__main__":` guard's sys.exit() and os._exit() calls

from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from aipass.cli.apps.modules import reset_command_state
from aipass.flow.apps.flow import (
    discover_modules,
    main,
    print_help,
    print_introspection,
    print_module_help,
    route_command,
)


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
        fake_dir = tmp_path / "nonexistent"
        with patch(f"{_FLOW}.MODULES_DIR", fake_dir):
            result = discover_modules()
        assert result == []

    def test_discovers_module_with_handle_command(self, tmp_path: Path) -> None:
        """Discovers .py files that expose handle_command()."""
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
        mod = _make_handling_module("create_plan")
        result = route_command("create", [".", "subject"], [mod])

        assert result is True
        mod.handle_command.assert_called_once_with("create", [".", "subject"])

    def test_returns_false_when_no_module_handles(self) -> None:
        """Returns False when no module claims the command."""
        mod = _make_module("create_plan")  # handle_command returns False
        result = route_command("unknown", [], [mod])

        assert result is False

    def test_handles_broken_pipe_error(self) -> None:
        """Catches BrokenPipeError, returns True, and offers the command to no one else.

        A broken pipe means the claiming module was already writing its answer, so the
        command is handled: the next module must not be asked to run it a second time.
        Mutant: the BrokenPipeError branch's `return True` -> `continue` reddens this.
        """
        mod = _make_module("list_plans")
        mod.handle_command.side_effect = BrokenPipeError  # type: ignore[union-attr]
        later = _make_handling_module("list_other")

        result = route_command("list", [], [mod, later])
        assert result is True
        mod.handle_command.assert_called_once_with("list", [])
        later.handle_command.assert_not_called()

    def test_handles_generic_exception(self) -> None:
        """Catches generic exceptions, logs, and continues to next module."""
        bad_mod = _make_module("bad")
        bad_mod.handle_command.side_effect = RuntimeError("kaboom")  # type: ignore[union-attr]

        good_mod = _make_handling_module("good")

        result = route_command("cmd", [], [bad_mod, good_mod])
        assert result is True
        good_mod.handle_command.assert_called_once()

    def test_returns_false_on_empty_modules(self) -> None:
        """Returns False when modules list is empty."""
        result = route_command("anything", [], [])
        assert result is False

    def test_stops_routing_after_first_handler(self) -> None:
        """Stops after the first module claims the command."""
        mod_a = _make_handling_module("first")
        mod_b = _make_module("second")

        result = route_command("cmd", [], [mod_a, mod_b])
        assert result is True
        mod_b.handle_command.assert_not_called()

    def test_all_modules_fail_with_exceptions(self) -> None:
        """Returns False when every module raises an exception."""
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
        with (
            patch(f"{_FLOW}.discover_modules", return_value=[]),
            patch("sys.argv", ["flow"]),
        ):
            result = main()
        assert result == 1

    def test_introspection_on_no_args(self) -> None:
        """Shows introspection when called with no arguments."""
        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_introspection") as mock_intro,
            patch("sys.argv", ["flow"]),
        ):
            result = main()

        assert result == 0
        mock_intro.assert_called_once_with([mod])

    def test_version_long_flag(self) -> None:
        """--version prints version and returns 0."""
        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch("sys.argv", ["flow", "--version"]),
        ):
            result = main()
        assert result == 0

    def test_version_short_flag(self) -> None:
        """-V prints version and returns 0."""
        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch("sys.argv", ["flow", "-V"]),
        ):
            result = main()
        assert result == 0

    def test_help_long_flag(self) -> None:
        """--help shows help and returns 0."""
        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_help") as mock_help,
            patch("sys.argv", ["flow", "--help"]),
        ):
            result = main()

        assert result == 0
        mock_help.assert_called_once()

    def test_help_short_flag(self) -> None:
        """-h shows help and returns 0."""
        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_help") as mock_help,
            patch("sys.argv", ["flow", "-h"]),
        ):
            result = main()

        assert result == 0
        mock_help.assert_called_once()

    def test_help_word(self) -> None:
        """'help' word shows help and returns 0."""
        mod = _make_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_help") as mock_help,
            patch("sys.argv", ["flow", "help"]),
        ):
            result = main()

        assert result == 0
        mock_help.assert_called_once()

    def test_routes_known_command(self) -> None:
        """Routes a valid command and returns 0."""
        mod = _make_handling_module("create_plan")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch("sys.argv", ["flow", "create", ".", "subject"]),
        ):
            result = main()

        assert result == 0
        mod.handle_command.assert_called_once_with("create", [".", "subject"])

    def test_unknown_command_returns_1(self) -> None:
        """Returns 1 for an unrecognized command."""
        mod = _make_module("create_plan")  # handle_command returns False

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch("sys.argv", ["flow", "bogus"]),
        ):
            result = main()

        assert result == 1

    def test_unknown_command_with_help_flag(self) -> None:
        """Shows module help when unknown command is followed by --help."""
        mod = _make_module("create_plan")  # handle_command returns False

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_module_help") as mock_mod_help,
            patch("sys.argv", ["flow", "bogus", "--help"]),
        ):
            result = main()

        assert result == 0
        mock_mod_help.assert_called_once_with("bogus", [mod])

    def test_unknown_command_with_short_help_flag(self) -> None:
        """Shows module help when unknown command is followed by -h."""
        mod = _make_module("create_plan")  # handle_command returns False

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch(f"{_FLOW}.print_module_help") as mock_mod_help,
            patch("sys.argv", ["flow", "bogus", "-h"]),
        ):
            result = main()

        assert result == 0
        mock_mod_help.assert_called_once_with("bogus", [mod])

    def test_command_with_no_extra_args(self) -> None:
        """Routes command with empty remaining args."""
        mod = _make_handling_module("list_plans")

        with (
            patch(f"{_FLOW}.discover_modules", return_value=[mod]),
            patch("sys.argv", ["flow", "list"]),
        ):
            result = main()

        assert result == 0
        mod.handle_command.assert_called_once_with("list", [])

    def test_main_catches_unhandled_exception(self) -> None:
        """main() catches unexpected exceptions from _main_impl and returns 1."""
        with patch(f"{_FLOW}.discover_modules", side_effect=RuntimeError("boom")):
            with patch("sys.argv", ["flow"]):
                result = main()
        assert result == 1


# ===========================================================================
# print_introspection
# ===========================================================================


class TestPrintIntrospection:
    """Tests for print_introspection()."""

    def test_with_modules(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Displays module names and descriptions."""
        mod = _make_module("create_plan", doc="Create a new plan")
        print_introspection([mod])

        out, _err = capsys.readouterr()
        assert "create_plan" in out
        assert "Create a new plan" in out

    def test_with_empty_modules(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Displays fallback text when no modules discovered."""
        print_introspection([])

        out, _err = capsys.readouterr()
        assert "No modules discovered" in out
        assert "Discovered Modules: 0" in out

    def test_module_without_docstring(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Uses 'No description' when module has no docstring."""
        mod = _make_module("bare_mod", doc=None)
        print_introspection([mod])

        out, _err = capsys.readouterr()
        assert "bare_mod" in out
        assert "No description" in out

    @pytest.mark.parametrize("names", [("alpha",), ("alpha", "beta")])
    def test_every_discovered_module_is_named(self, names, capsys: pytest.CaptureFixture[str]) -> None:
        """One module or several, each one appears in the listing.

        MERGED (DPLAN-0323 contested band, 2026-09-07) with the former
        ``test_multiple_modules``, which ran the identical call path with two
        list entries instead of one and asserted nothing — 'lists all
        discovered modules' was never read back. Mutation-checked before
        merging: dropping the second module changed no branch, so the count is
        a parameter, not a test. The oracle is new: both rows now READ the
        output, so deleting the loop body reds them.

        FLOOR BEFORE THE LOOP (FPLAN-0508, VACUOUS-LOOP). Every assertion here
        sat inside `for name in names`, so a parametrise row that arrived empty
        would pass the unit without reading one character of the listing. The
        floor is the row's own width, and the printed text must be non-empty
        before it is searched - a console that printed nothing at all would
        otherwise satisfy an empty loop in silence.

        THE DESCRIPTION MUST NOT ECHO THE NAME, and it used to. The doc was
        ``f"{name} module"``, so `name in printed` was satisfied by the
        DESCRIPTION column whether or not the name column printed anything at
        all. Measured, not suspected: blanking `module_name` in the f-string at
        flow.py:210 left all five rows of this class green. The descriptions
        are name-free now and asserted beside the names, so each column has to
        carry its own value.

        The non-empty floor is now the count the listing prints, read off the
        real channel: a listing that printed nothing, or miscounted, fails
        before the loop is reached.
        Mutant: `{len(modules)}` -> `{len(modules) - 1}` in print_introspection reddens this.
        """
        assert len(names) >= 1
        docs = {name: f"purpose text {index}" for index, name in enumerate(names)}

        print_introspection([_make_module(name, doc=docs[name]) for name in names])

        printed, _err = capsys.readouterr()
        assert f"Discovered Modules: {len(names)}" in printed
        for name in names:
            assert name in printed
            assert docs[name] in printed


# ===========================================================================
# print_help
# ===========================================================================


class TestPrintHelp:
    """Tests for print_help()."""

    def test_with_modules(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Shows formatted help with module listing."""
        mod = _make_module("create_plan", doc="Create a new plan")
        print_help([mod])

        out, _err = capsys.readouterr()
        assert "USAGE:" in out
        assert "AVAILABLE COMMANDS:" in out
        assert "create" in out
        assert "Create a new plan" in out

    def test_with_empty_modules(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Shows help even when no modules are discovered."""
        print_help([])

        out, _err = capsys.readouterr()
        assert "USAGE:" in out
        assert "No modules discovered" in out

    @pytest.mark.parametrize(
        ("module_name", "expected_verb"),
        [("create_plan", "create"), ("templates", "templates")],
    )
    def test_the_help_table_prints_the_verb_that_executes(
        self, module_name, expected_verb, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Only the verb the dispatcher accepts is printed, never the filename.

        REWRITTEN 2026-09-15 (FPLAN-0612). The old rows asserted the table
        printed 'short, full' for an underscored name, which pinned a claim the
        dispatcher does not honour: `drone @flow list_plans` is refused, exit 1.
        The help screen said the opposite in prose, so the pin certified the
        lie rather than catching it. The contract now is the measured one -
        the table prints what executes and nothing else.
        """
        print_help([_make_module(module_name, doc="Any description")])

        printed, _err = capsys.readouterr()
        assert expected_verb in printed
        if module_name != expected_verb:
            assert module_name not in printed

    def test_a_module_owning_several_verbs_declares_them(self, capsys: pytest.CaptureFixture[str]) -> None:
        """COMMAND_VERBS wins over the filename-derived short name.

        template_manager owns templates/register/unregister/scan and answers to
        none of them under the derived name 'template', which the help table
        published as a command until 2026-09-15.
        """
        mod = _make_module("template_manager", doc="Template Manager Module")
        mod.__dict__["COMMAND_VERBS"] = ("templates", "register", "unregister", "scan")
        print_help([mod])

        printed, _err = capsys.readouterr()
        assert "templates, register, unregister, scan" in printed
        assert "template_manager" not in printed

    def test_module_without_docstring(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Uses 'No description' for undocumented modules."""
        mod = _make_module("mystery", doc=None)
        print_help([mod])

        out, _err = capsys.readouterr()
        assert "mystery" in out
        assert "No description" in out


# ===========================================================================
# print_module_help
# ===========================================================================


class TestPrintModuleHelp:
    """Tests for print_module_help()."""

    def test_exact_match(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Finds module by exact name match."""
        mod = _make_module("create_plan", doc="Create plans\nMore details here")
        print_module_help("create_plan", [mod])

        out, err = capsys.readouterr()
        assert "Create plans" in out
        assert "Unknown command" not in out + err

    def test_no_match(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Shows error for unknown command.

        The diagnostic leaves through cli's error() on stderr, the pointer through
        console on stdout, so BOTH channels are read - asserting only on stdout
        would have missed the whole message.
        Mutant: the `error(...)` call in print_module_help's no-match branch removed reddens this.
        """
        mod = _make_module("create_plan")
        print_module_help("nonexistent", [mod])

        out, err = capsys.readouterr()
        assert "Unknown command: nonexistent" in err
        assert "Run drone @flow --help for available commands" in out
        reset_command_state()

    def test_module_without_docstring(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Shows 'No documentation available' for undocumented module."""
        mod = _make_module("bare_mod", doc=None)
        print_module_help("bare_mod", [mod])

        out, _err = capsys.readouterr()
        assert "No documentation available" in out

    def test_a_multiline_docstring_is_shown_whole_and_stripped(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Every line reaches the reader, without the leading/trailing blanks.

        KEPT rather than merged into ``test_exact_match`` (DPLAN-0323 contested
        band, 2026-09-07). The two make the same found-module call, but this
        one's subject is what ``print_module_help`` does to a docstring that
        spans lines — ``.strip()`` on the whole string, not the first line
        only, which is what the module listing does instead. Mutation-checked:
        with the assertions it now carries, printing only the first line reds
        it; before, it asserted nothing and both spellings passed.
        """
        mod = _make_module(
            "list_plans",
            doc="\nList plans\n\nShows all plans in the registry.\n",
        )
        print_module_help("list_plans", [mod])

        printed, _err = capsys.readouterr()
        assert "List plans" in printed
        assert "Shows all plans in the registry." in printed
        assert not printed.strip().endswith("\\n")
