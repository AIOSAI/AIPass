# =================== AIPass ====================
# Name: test_api_entry.py
# Description: Tests for api.py entry point CLI
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-05-12
# =============================================

"""Tests for api.py — main entry point CLI for drone @api."""

from unittest.mock import MagicMock, patch

from aipass.api.apps.api import discover_modules, main, print_help, print_introspection, route_command

PATCH_CONSOLE = "aipass.api.apps.api.console"
PATCH_HEADER = "aipass.api.apps.api.header"
PATCH_ERROR = "aipass.api.apps.api.error"
PATCH_LOGGER = "aipass.api.apps.api.logger"
PATCH_JSON_HANDLER = "aipass.api.apps.api.json_handler"
PATCH_DISCOVER = "aipass.api.apps.api.discover_modules"
PATCH_MODULES_DIR = "aipass.api.apps.api.MODULES_DIR"


def _make_fake_module(name: str, *, has_handle_command: bool = True) -> MagicMock:
    """Build a MagicMock that looks like a discovered api module."""
    mod = MagicMock()
    mod.__name__ = f"aipass.api.apps.modules.{name}"
    if not has_handle_command:
        del mod.handle_command
    return mod


class TestDiscoverModules:
    """Tests for discover_modules()."""

    @patch(PATCH_LOGGER)
    def test_modules_dir_missing(self, mock_logger, tmp_path):
        """Returns empty list and warns when modules/ does not exist."""
        missing = tmp_path / "nonexistent"
        with patch(PATCH_MODULES_DIR, missing):
            result = discover_modules()

        assert result == []
        mock_logger.warning.assert_called_once()

    @patch(PATCH_LOGGER)
    def test_discovers_valid_modules(self, mock_logger, tmp_path):
        """Finds and returns modules that expose handle_command()."""
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        (modules_dir / "good.py").write_text("def handle_command(cmd, args): pass\n", encoding="utf-8")

        fake_module = _make_fake_module("good")

        with (
            patch(PATCH_MODULES_DIR, modules_dir),
            patch("aipass.api.apps.api.importlib.import_module", return_value=fake_module),
        ):
            result = discover_modules()

        assert len(result) == 1
        assert result[0] is fake_module

    @patch(PATCH_LOGGER)
    def test_skips_module_without_handle_command(self, mock_logger, tmp_path):
        """Warns and skips modules lacking handle_command()."""
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        (modules_dir / "nohandler.py").write_text("x = 1\n", encoding="utf-8")

        fake_module = _make_fake_module("nohandler", has_handle_command=False)

        with (
            patch(PATCH_MODULES_DIR, modules_dir),
            patch("aipass.api.apps.api.importlib.import_module", return_value=fake_module),
        ):
            result = discover_modules()

        assert result == []
        mock_logger.warning.assert_any_call("  [!] nohandler - missing handle_command()")

    @patch(PATCH_LOGGER)
    def test_handles_import_error(self, mock_logger, tmp_path):
        """Logs error and skips modules that fail to import."""
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        (modules_dir / "broken.py").write_text("raise ImportError\n", encoding="utf-8")

        with (
            patch(PATCH_MODULES_DIR, modules_dir),
            patch("aipass.api.apps.api.importlib.import_module", side_effect=ImportError("bad import")),
        ):
            result = discover_modules()

        assert result == []
        mock_logger.error.assert_called_once()

    @patch(PATCH_LOGGER)
    def test_skips_underscore_files(self, mock_logger, tmp_path):
        """Ignores __init__.py and _private.py files."""
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir()
        (modules_dir / "__init__.py").write_text("", encoding="utf-8")
        (modules_dir / "_private.py").write_text("def handle_command(cmd, args): pass\n", encoding="utf-8")

        with (
            patch(PATCH_MODULES_DIR, modules_dir),
            patch("aipass.api.apps.api.importlib.import_module") as mock_import,
        ):
            result = discover_modules()

        assert result == []
        mock_import.assert_not_called()


class TestPrintIntrospection:
    """Tests for print_introspection()."""

    @patch(PATCH_ERROR)
    @patch(PATCH_CONSOLE)
    @patch(PATCH_DISCOVER, return_value=[])
    def test_no_modules(self, mock_discover, mock_console, mock_error):
        """Shows error when no modules are discovered."""
        print_introspection()

        mock_error.assert_called_once()

    @patch(PATCH_ERROR)
    @patch(PATCH_CONSOLE)
    @patch(PATCH_DISCOVER)
    def test_with_modules(self, mock_discover, mock_console, mock_error):
        """Lists discovered modules without error."""
        fake_module = _make_fake_module("test_mod")
        mock_discover.return_value = [fake_module]

        print_introspection()

        mock_error.assert_not_called()
        assert mock_console.print.call_count >= 1


class TestPrintHelp:
    """Tests for print_help()."""

    @patch(PATCH_CONSOLE)
    @patch(PATCH_HEADER)
    def test_runs_without_error(self, mock_header, mock_console):
        """Help output renders without raising."""
        print_help()

        mock_header.assert_called_once()
        assert mock_console.print.call_count >= 1


class TestRouteCommand:
    """Tests for route_command()."""

    @patch(PATCH_LOGGER)
    def test_command_handled(self, mock_logger):
        """Returns True when a module handles the command."""
        module = MagicMock()
        module.handle_command.return_value = True

        result = route_command("get-key", ["openrouter"], [module])

        assert result is True
        module.handle_command.assert_called_once_with("get-key", ["openrouter"])

    @patch(PATCH_LOGGER)
    def test_command_not_handled(self, mock_logger):
        """Returns False when no module handles the command."""
        module = MagicMock()
        module.handle_command.return_value = False

        result = route_command("unknown", [], [module])

        assert result is False

    @patch(PATCH_LOGGER)
    def test_module_raises_exception(self, mock_logger):
        """Returns False and logs error when module raises."""
        module = MagicMock()
        module.handle_command.side_effect = RuntimeError("boom")

        result = route_command("get-key", [], [module])

        assert result is False
        mock_logger.error.assert_called_once()


class TestMain:
    """Tests for main() entry point."""

    @patch(PATCH_JSON_HANDLER)
    @patch(PATCH_ERROR)
    @patch(PATCH_CONSOLE)
    @patch(PATCH_DISCOVER, return_value=[])
    @patch("aipass.api.apps.api.print_introspection")
    def test_no_args_shows_introspection(self, mock_introspect, mock_discover, mock_console, mock_error, mock_jh):
        """No arguments triggers introspection display."""
        with patch("sys.argv", ["api"]):
            result = main()

        assert result == 0
        mock_introspect.assert_called_once()
        mock_jh.log_operation.assert_called_once_with("api_introspection_displayed", {"trigger": "no_args"})

    @patch(PATCH_JSON_HANDLER)
    @patch(PATCH_CONSOLE)
    def test_version_flag(self, mock_console, mock_jh):
        """--version prints version string."""
        with patch("sys.argv", ["api", "--version"]):
            result = main()

        assert result == 0
        mock_console.print.assert_called_once_with("API v1.0.0")

    @patch(PATCH_JSON_HANDLER)
    @patch(PATCH_CONSOLE)
    def test_version_short_flag(self, mock_console, mock_jh):
        """-V prints version string."""
        with patch("sys.argv", ["api", "-V"]):
            result = main()

        assert result == 0
        mock_console.print.assert_called_once_with("API v1.0.0")

    @patch(PATCH_JSON_HANDLER)
    @patch(PATCH_CONSOLE)
    @patch(PATCH_HEADER)
    @patch("aipass.api.apps.api.print_help")
    def test_help_flag(self, mock_help, mock_header, mock_console, mock_jh):
        """--help triggers help display."""
        with patch("sys.argv", ["api", "--help"]):
            result = main()

        assert result == 0
        mock_help.assert_called_once()
        mock_jh.log_operation.assert_called_once_with("api_help_displayed", {"trigger": "--help"})

    @patch(PATCH_JSON_HANDLER)
    @patch(PATCH_CONSOLE)
    @patch(PATCH_HEADER)
    @patch("aipass.api.apps.api.print_help")
    def test_h_flag(self, mock_help, mock_header, mock_console, mock_jh):
        """-h triggers help display."""
        with patch("sys.argv", ["api", "-h"]):
            result = main()

        assert result == 0
        mock_help.assert_called_once()
        mock_jh.log_operation.assert_called_once_with("api_help_displayed", {"trigger": "-h"})

    @patch(PATCH_JSON_HANDLER)
    @patch(PATCH_CONSOLE)
    @patch(PATCH_HEADER)
    @patch("aipass.api.apps.api.print_help")
    def test_help_command(self, mock_help, mock_header, mock_console, mock_jh):
        """'help' subcommand triggers help display."""
        with patch("sys.argv", ["api", "help"]):
            result = main()

        assert result == 0
        mock_help.assert_called_once()
        mock_jh.log_operation.assert_called_once_with("api_help_displayed", {"trigger": "help"})

    @patch(PATCH_JSON_HANDLER)
    @patch(PATCH_ERROR)
    @patch(PATCH_CONSOLE)
    @patch("aipass.api.apps.api.route_command", return_value=True)
    @patch(PATCH_DISCOVER)
    def test_valid_command_routing(self, mock_discover, mock_route, mock_console, mock_error, mock_jh):
        """Valid command is routed to modules and returns 0."""
        fake_module = MagicMock()
        mock_discover.return_value = [fake_module]

        with patch("sys.argv", ["api", "get-key", "openrouter"]):
            result = main()

        assert result == 0
        mock_route.assert_called_once_with("get-key", ["openrouter"], [fake_module])
        mock_jh.log_operation.assert_called_once_with(
            "api_command_attempted", {"command": "get-key", "modules_discovered": 1}
        )

    @patch(PATCH_JSON_HANDLER)
    @patch(PATCH_ERROR)
    @patch(PATCH_LOGGER)
    @patch(PATCH_CONSOLE)
    @patch("aipass.api.apps.api.route_command", return_value=False)
    @patch(PATCH_DISCOVER)
    def test_unknown_command(self, mock_discover, mock_route, mock_console, mock_logger, mock_error, mock_jh):
        """Unhandled command returns 1 and shows error."""
        mock_discover.return_value = [MagicMock()]

        with patch("sys.argv", ["api", "bogus"]):
            result = main()

        assert result == 1
        mock_error.assert_called_once()
        mock_logger.warning.assert_called_once()

    @patch(PATCH_JSON_HANDLER)
    @patch(PATCH_ERROR)
    @patch(PATCH_LOGGER)
    @patch(PATCH_CONSOLE)
    @patch(PATCH_DISCOVER, return_value=[])
    def test_no_modules_found(self, mock_discover, mock_console, mock_logger, mock_error, mock_jh):
        """Returns 1 and shows error when no modules are found."""
        with patch("sys.argv", ["api", "get-key"]):
            result = main()

        assert result == 1
        mock_error.assert_called_once()
        mock_logger.error.assert_called_once()

    @patch(PATCH_JSON_HANDLER)
    @patch(PATCH_ERROR)
    @patch(PATCH_LOGGER)
    @patch(PATCH_CONSOLE)
    @patch(PATCH_DISCOVER, side_effect=RuntimeError("catastrophic"))
    def test_unhandled_exception(self, mock_discover, mock_console, mock_logger, mock_error, mock_jh):
        """Unhandled exception returns 1 and logs error."""
        with patch("sys.argv", ["api", "get-key"]):
            result = main()

        assert result == 1
        mock_logger.error.assert_called_once()


class TestRouterNormalisesHelpFlag:
    """The router must normalise a help flag anywhere in the args.

    This is the fleet pattern @aipass/@backup/@daemon use: every module then
    receives exactly ["--help"] and none can be reached with a stray flag still
    in its args. Checking only remaining_args[0] let `get-key openrouter --help`
    reach the retrieval path and disclose key material.
    """

    def _run(self, argv):
        """Run main() with argv, returning the args each module was handed."""
        seen = []

        def fake_handle(command, args):
            seen.append((command, list(args)))
            return True

        module = MagicMock()
        module.handle_command.side_effect = fake_handle

        with (
            patch("aipass.api.apps.api.discover_modules", return_value=[module]),
            patch("aipass.api.apps.api.json_handler"),
            patch("sys.argv", ["api.py"] + argv),
        ):
            main()
        return seen

    def test_trailing_help_normalised_to_help_only(self):
        """`get-key openrouter --help` reaches the module as ["--help"]."""
        assert self._run(["get-key", "openrouter", "--help"]) == [("get-key", ["--help"])]

    def test_trailing_short_flag_normalised(self):
        """`cleanup 30 -h` reaches the module as ["--help"], not as a value."""
        assert self._run(["cleanup", "30", "-h"]) == [("cleanup", ["--help"])]

    def test_help_deep_in_args_normalised(self):
        """A help flag past the second position is still a help request."""
        assert self._run(["integrations", "call", "publish_devto", "--help"]) == [("integrations", ["--help"])]

    def test_normal_args_pass_through_untouched(self):
        """Commands without a help flag are handed their real args."""
        assert self._run(["get-key", "openrouter"]) == [("get-key", ["openrouter"])]
