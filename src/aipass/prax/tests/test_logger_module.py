# =================== AIPass ====================
# Name: test_logger_module.py
# Description: Unit tests for PRAX logger module (public API)
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""
Tests for prax logger module — the core public API for system-wide logging.

logger.py imports from 8+ handler files at module level, so we must inject
mock modules into sys.modules for every handler dependency BEFORE importing
the module under test. The conftest autouse fixture mocks the logger module
itself (for other tests), but here we need to test logger.py internals so
we bypass that and do our own heavier mocking.

All module imports happen inside test functions so that mocks are in place
before the import chain triggers.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


# =============================================
# HELPERS
# =============================================

MODULE_NAME = "aipass.prax.apps.modules.logger"

# All handler dependencies that logger.py imports at module level
HANDLER_DEPS = [
    "aipass.prax.apps.handlers.logging.setup",
    "aipass.prax.apps.handlers.logging.introspection",
    "aipass.prax.apps.handlers.logging.override",
    "aipass.prax.apps.handlers.logging.direct",
    "aipass.prax.apps.handlers.logging.lifecycle",
    "aipass.prax.apps.handlers.discovery.watcher",
    "aipass.prax.apps.handlers.registry.load",
    "aipass.prax.apps.handlers.config.load",
    "aipass.prax.apps.handlers.json",
    "aipass.cli.apps.modules",
    "aipass.cli.apps.modules.display",
    "aipass.cli.apps.modules.console",
]


def _build_handler_mocks():
    """Create mock modules for every handler dependency.

    Returns a dict of module_path -> MagicMock with the attributes
    that logger.py actually uses wired up.
    """
    mocks = {}
    for dep in HANDLER_DEPS:
        mocks[dep] = MagicMock()

    # Wire up specific attributes that logger.py accesses at import time

    # setup.py exports
    setup = mocks["aipass.prax.apps.handlers.logging.setup"]
    mock_stdlib_logger = MagicMock()
    mock_stdlib_logger.info = MagicMock()
    mock_stdlib_logger.warning = MagicMock()
    mock_stdlib_logger.error = MagicMock()
    mock_stdlib_logger.debug = MagicMock()
    setup.setup_individual_logger = MagicMock(return_value=mock_stdlib_logger)
    setup.get_captured_loggers_count = MagicMock(return_value=5)
    setup.enable_terminal_output = MagicMock()
    setup.disable_terminal_output = MagicMock()

    # introspection.py exports
    intro = mocks["aipass.prax.apps.handlers.logging.introspection"]
    intro.get_calling_module = MagicMock(return_value="test_module")
    intro.get_caller_info = MagicMock(return_value=("test_module", "/fake/path.py", "prax"))

    # override.py exports
    override = mocks["aipass.prax.apps.handlers.logging.override"]
    override.is_override_active = MagicMock(return_value=False)

    # direct.py exports
    direct = mocks["aipass.prax.apps.handlers.logging.direct"]
    mock_direct_logger = MagicMock()
    direct.get_direct_logger = MagicMock(return_value=mock_direct_logger)
    direct.direct_log = MagicMock()
    direct.DirectLogger = MagicMock

    # watcher.py exports
    watcher = mocks["aipass.prax.apps.handlers.discovery.watcher"]
    watcher.start_file_watcher = MagicMock()
    watcher.is_file_watcher_active = MagicMock(return_value=True)

    # registry/load.py exports
    registry = mocks["aipass.prax.apps.handlers.registry.load"]
    registry.load_module_registry = MagicMock(
        return_value=[
            {"name": "mod_a"},
            {"name": "mod_b"},
            {"name": "mod_c"},
        ]
    )

    # config/load.py exports
    config = mocks["aipass.prax.apps.handlers.config.load"]
    config.get_system_logs_dir = MagicMock(return_value=Path("/tmp/prax/logs/system"))
    config.get_module_logs_dir = MagicMock(return_value=Path("/tmp/prax/logs/modules"))
    config.PRAX_JSON_DIR = Path("/tmp/prax/json")

    # json handler
    json_mod = mocks["aipass.prax.apps.handlers.json"]
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_mod.json_handler = mock_json_handler

    # CLI modules
    cli = mocks["aipass.cli.apps.modules"]
    mock_console = MagicMock()
    mock_console.print = MagicMock()
    cli.console = mock_console

    cli_display = mocks["aipass.cli.apps.modules.display"]
    cli_display.console = mock_console

    cli_console_mod = mocks["aipass.cli.apps.modules.console"]
    cli_console_mod.print = MagicMock()

    return mocks


def _inject_and_import(monkeypatch):
    """Inject handler mocks into sys.modules and (re-)import logger.py.

    Returns (logger_module, handler_mocks_dict).
    """
    mocks = _build_handler_mocks()

    # Clear cached module so it re-imports fresh
    sys.modules.pop(MODULE_NAME, None)

    # Inject all handler mocks
    for mod_path, mock_obj in mocks.items():
        monkeypatch.setitem(sys.modules, mod_path, mock_obj)

    # Now import — the module-level imports will resolve to our mocks
    import aipass.prax.apps.modules.logger as logger_mod
    import importlib

    importlib.reload(logger_mod)

    return logger_mod, mocks


# =============================================
# get_system_logger
# =============================================


class TestGetSystemLogger:
    """Tests for get_system_logger() — returns a logger with standard methods."""

    def test_returns_logger_object(self, monkeypatch):
        """get_system_logger returns an object from setup_individual_logger."""
        mod, mocks = _inject_and_import(monkeypatch)

        result = mod.get_system_logger()

        assert result is not None
        setup = mocks["aipass.prax.apps.handlers.logging.setup"]
        setup.setup_individual_logger.assert_called_once()

    def test_returned_logger_has_info_method(self, monkeypatch):
        """The returned logger has an info() method."""
        mod, _mocks = _inject_and_import(monkeypatch)

        result = mod.get_system_logger()

        assert hasattr(result, "info")
        assert callable(result.info)

    def test_returned_logger_has_warning_method(self, monkeypatch):
        """The returned logger has a warning() method."""
        mod, _mocks = _inject_and_import(monkeypatch)

        result = mod.get_system_logger()

        assert hasattr(result, "warning")
        assert callable(result.warning)

    def test_returned_logger_has_error_method(self, monkeypatch):
        """The returned logger has an error() method."""
        mod, _mocks = _inject_and_import(monkeypatch)

        result = mod.get_system_logger()

        assert hasattr(result, "error")
        assert callable(result.error)

    def test_passes_caller_info_to_setup(self, monkeypatch):
        """get_system_logger passes caller_path and caller_branch from introspection."""
        mod, mocks = _inject_and_import(monkeypatch)

        mod.get_system_logger()

        intro = mocks["aipass.prax.apps.handlers.logging.introspection"]
        intro.get_caller_info.assert_called_once()

        setup = mocks["aipass.prax.apps.handlers.logging.setup"]
        call_kwargs = setup.setup_individual_logger.call_args
        assert call_kwargs[1]["caller_path"] == "/fake/path.py"
        assert call_kwargs[1]["caller_branch"] == "prax"


# =============================================
# get_system_status
# =============================================


class TestGetSystemStatus:
    """Tests for get_system_status() — returns a dict with system info."""

    def test_returns_dict(self, monkeypatch):
        """get_system_status returns a dictionary."""
        mod, _mocks = _inject_and_import(monkeypatch)

        result = mod.get_system_status()

        assert isinstance(result, dict)

    def test_contains_total_modules_key(self, monkeypatch):
        """Result includes total_modules count from registry."""
        mod, _mocks = _inject_and_import(monkeypatch)

        result = mod.get_system_status()

        assert "total_modules" in result
        assert result["total_modules"] == 3  # 3 modules in mock registry

    def test_contains_individual_loggers_key(self, monkeypatch):
        """Result includes individual_loggers count."""
        mod, _mocks = _inject_and_import(monkeypatch)

        result = mod.get_system_status()

        assert "individual_loggers" in result
        assert result["individual_loggers"] == 5  # from mock

    def test_contains_system_logs_dir(self, monkeypatch):
        """Result includes system_logs_dir path."""
        mod, _mocks = _inject_and_import(monkeypatch)

        result = mod.get_system_status()

        assert "system_logs_dir" in result
        assert "prax" in result["system_logs_dir"]

    def test_contains_module_logs_dir(self, monkeypatch):
        """Result includes module_logs_dir path."""
        mod, _mocks = _inject_and_import(monkeypatch)

        result = mod.get_system_status()

        assert "module_logs_dir" in result

    def test_contains_file_watcher_status(self, monkeypatch):
        """Result includes file_watcher_active boolean."""
        mod, _mocks = _inject_and_import(monkeypatch)

        result = mod.get_system_status()

        assert "file_watcher_active" in result
        assert result["file_watcher_active"] is True

    def test_contains_override_status(self, monkeypatch):
        """Result includes logger_override_active boolean."""
        mod, _mocks = _inject_and_import(monkeypatch)

        result = mod.get_system_status()

        assert "logger_override_active" in result
        assert result["logger_override_active"] is False

    def test_contains_registry_file(self, monkeypatch):
        """Result includes registry_file path."""
        mod, _mocks = _inject_and_import(monkeypatch)

        result = mod.get_system_status()

        assert "registry_file" in result

    def test_calls_load_module_registry(self, monkeypatch):
        """get_system_status calls load_module_registry to count modules."""
        mod, mocks = _inject_and_import(monkeypatch)

        mod.get_system_status()

        registry = mocks["aipass.prax.apps.handlers.registry.load"]
        registry.load_module_registry.assert_called_once()


# =============================================
# handle_command
# =============================================


class TestHandleCommand:
    """Tests for handle_command() — introspection gate and routing."""

    def test_no_args_calls_introspection_returns_true(self, monkeypatch):
        """Empty args list prints introspection and returns True."""
        mod, mocks = _inject_and_import(monkeypatch)

        result = mod.handle_command("logger", [])

        assert result is True

    def test_help_flag_returns_true(self, monkeypatch):
        """--help flag prints introspection and returns True."""
        mod, _mocks = _inject_and_import(monkeypatch)

        result = mod.handle_command("logger", ["--help"])

        assert result is True

    def test_h_flag_returns_true(self, monkeypatch):
        """-h flag prints introspection and returns True."""
        mod, _mocks = _inject_and_import(monkeypatch)

        result = mod.handle_command("logger", ["-h"])

        assert result is True

    def test_help_word_returns_true(self, monkeypatch):
        """'help' subcommand prints introspection and returns True."""
        mod, _mocks = _inject_and_import(monkeypatch)

        result = mod.handle_command("logger", ["help"])

        assert result is True

    def test_unknown_arg_returns_false(self, monkeypatch):
        """Unknown argument returns False (unhandled)."""
        mod, _mocks = _inject_and_import(monkeypatch)

        result = mod.handle_command("logger", ["unknown-subcommand"])

        assert result is False

    def test_logs_operation_via_json_handler(self, monkeypatch):
        """handle_command logs the operation through json_handler."""
        mod, mocks = _inject_and_import(monkeypatch)

        mod.handle_command("logger", ["--help"])

        json_handler = mocks["aipass.prax.apps.handlers.json"].json_handler
        json_handler.log_operation.assert_called_once_with("logger_handle_command", {"args": ["--help"]})

    def test_no_args_logs_operation(self, monkeypatch):
        """handle_command with no args still logs the operation."""
        mod, mocks = _inject_and_import(monkeypatch)

        mod.handle_command("logger", [])

        json_handler = mocks["aipass.prax.apps.handlers.json"].json_handler
        json_handler.log_operation.assert_called_once_with("logger_handle_command", {"args": []})


# =============================================
# initialize_logging_system
# =============================================


class TestInitializeLoggingSystem:
    """Tests for initialize_logging_system() — delegates to lifecycle handler."""

    def test_calls_lifecycle_run_initialize(self, monkeypatch):
        """initialize_logging_system calls run_initialize from lifecycle handler."""
        mod, mocks = _inject_and_import(monkeypatch)

        # The lifecycle handler is lazy-imported inside the function,
        # so we need to mock it in sys.modules
        mock_lifecycle = MagicMock()
        mock_lifecycle.run_initialize = MagicMock(
            return_value={
                "modules_count": 42,
            }
        )
        monkeypatch.setitem(
            sys.modules,
            "aipass.prax.apps.handlers.logging.lifecycle",
            mock_lifecycle,
        )

        mod.initialize_logging_system()

        mock_lifecycle.run_initialize.assert_called_once_with("prax_logger")

    def test_prints_initialization_message(self, monkeypatch):
        """initialize_logging_system prints init and completion messages."""
        mod, mocks = _inject_and_import(monkeypatch)

        mock_lifecycle = MagicMock()
        mock_lifecycle.run_initialize = MagicMock(
            return_value={
                "modules_count": 10,
            }
        )
        monkeypatch.setitem(
            sys.modules,
            "aipass.prax.apps.handlers.logging.lifecycle",
            mock_lifecycle,
        )

        mod.initialize_logging_system()

        console = mocks["aipass.cli.apps.modules"].console
        calls = [str(c) for c in console.print.call_args_list]
        assert any("Initializing" in c for c in calls)
        assert any("initialized" in c.lower() for c in calls)


# =============================================
# shutdown_logging_system
# =============================================


class TestShutdownLoggingSystem:
    """Tests for shutdown_logging_system() — delegates to lifecycle handler."""

    def test_calls_lifecycle_run_shutdown(self, monkeypatch):
        """shutdown_logging_system calls run_shutdown from lifecycle handler."""
        mod, mocks = _inject_and_import(monkeypatch)

        mock_lifecycle = MagicMock()
        mock_lifecycle.run_shutdown = MagicMock()
        monkeypatch.setitem(
            sys.modules,
            "aipass.prax.apps.handlers.logging.lifecycle",
            mock_lifecycle,
        )

        mod.shutdown_logging_system()

        mock_lifecycle.run_shutdown.assert_called_once_with("prax_logger")

    def test_prints_shutdown_messages(self, monkeypatch):
        """shutdown_logging_system prints shutdown and completion messages."""
        mod, mocks = _inject_and_import(monkeypatch)

        mock_lifecycle = MagicMock()
        mock_lifecycle.run_shutdown = MagicMock()
        monkeypatch.setitem(
            sys.modules,
            "aipass.prax.apps.handlers.logging.lifecycle",
            mock_lifecycle,
        )

        mod.shutdown_logging_system()

        console = mocks["aipass.cli.apps.modules"].console
        calls = [str(c) for c in console.print.call_args_list]
        assert any("Shutting down" in c for c in calls)
        assert any("complete" in c.lower() for c in calls)


# =============================================
# enable_terminal_output / disable_terminal_output
# =============================================


class TestTerminalOutputControl:
    """Tests for enable/disable terminal output pass-through functions."""

    def test_enable_delegates_to_setup_handler(self, monkeypatch):
        """enable_terminal_output calls the setup handler's enable function."""
        mod, mocks = _inject_and_import(monkeypatch)

        mod.enable_terminal_output()

        setup = mocks["aipass.prax.apps.handlers.logging.setup"]
        setup.enable_terminal_output.assert_called_once()

    def test_disable_delegates_to_setup_handler(self, monkeypatch):
        """disable_terminal_output calls the setup handler's disable function."""
        mod, mocks = _inject_and_import(monkeypatch)

        mod.disable_terminal_output()

        setup = mocks["aipass.prax.apps.handlers.logging.setup"]
        setup.disable_terminal_output.assert_called_once()


# =============================================
# SystemLogger class
# =============================================


class TestSystemLogger:
    """Tests for the SystemLogger class — auto-routing logger proxy."""

    def test_system_logger_instance_exists(self, monkeypatch):
        """Module exports a system_logger instance of SystemLogger."""
        mod, _mocks = _inject_and_import(monkeypatch)

        assert hasattr(mod, "system_logger")
        assert isinstance(mod.system_logger, mod.SystemLogger)

    def test_system_logger_has_info(self, monkeypatch):
        """SystemLogger exposes an info() method."""
        mod, _mocks = _inject_and_import(monkeypatch)

        assert callable(getattr(mod.system_logger, "info", None))

    def test_system_logger_has_warning(self, monkeypatch):
        """SystemLogger exposes a warning() method."""
        mod, _mocks = _inject_and_import(monkeypatch)

        assert callable(getattr(mod.system_logger, "warning", None))

    def test_system_logger_has_error(self, monkeypatch):
        """SystemLogger exposes an error() method."""
        mod, _mocks = _inject_and_import(monkeypatch)

        assert callable(getattr(mod.system_logger, "error", None))

    def test_info_calls_get_system_logger(self, monkeypatch):
        """SystemLogger.info() delegates to get_system_logger().info()."""
        mod, mocks = _inject_and_import(monkeypatch)

        # Reset watcher flag so _ensure_watcher runs
        mod.SystemLogger._watcher_started = True

        mod.system_logger.info("test message %s", "arg1")

        setup = mocks["aipass.prax.apps.handlers.logging.setup"]
        setup.setup_individual_logger.assert_called()

    def test_warning_calls_get_system_logger(self, monkeypatch):
        """SystemLogger.warning() delegates to get_system_logger().warning()."""
        mod, mocks = _inject_and_import(monkeypatch)

        mod.SystemLogger._watcher_started = True

        mod.system_logger.warning("warn: %s", "problem")

        setup = mocks["aipass.prax.apps.handlers.logging.setup"]
        setup.setup_individual_logger.assert_called()

    def test_error_calls_get_system_logger(self, monkeypatch):
        """SystemLogger.error() delegates to get_system_logger().error()."""
        mod, mocks = _inject_and_import(monkeypatch)

        mod.SystemLogger._watcher_started = True

        mod.system_logger.error("error: %s", "failure")

        setup = mocks["aipass.prax.apps.handlers.logging.setup"]
        setup.setup_individual_logger.assert_called()


# =============================================
# Module constants
# =============================================


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_module_name_is_prax_logger(self, monkeypatch):
        """MODULE_NAME is set to 'prax_logger'."""
        mod, _mocks = _inject_and_import(monkeypatch)

        assert mod.MODULE_NAME == "prax_logger"

    def test_data_file_is_path(self, monkeypatch):
        """DATA_FILE is a pathlib.Path."""
        mod, _mocks = _inject_and_import(monkeypatch)

        assert isinstance(mod.DATA_FILE, Path)

    def test_data_file_contains_module_name(self, monkeypatch):
        """DATA_FILE filename includes the module name."""
        mod, _mocks = _inject_and_import(monkeypatch)

        assert "prax_logger" in mod.DATA_FILE.name


# =============================================
# print_introspection
# =============================================


class TestPrintIntrospection:
    """Tests for print_introspection() — displays module info."""

    def test_prints_handler_info(self, monkeypatch):
        """print_introspection prints handler connection details."""
        mod, mocks = _inject_and_import(monkeypatch)

        mod.print_introspection()

        console = mocks["aipass.cli.apps.modules.display"].console
        calls = [str(c) for c in console.print.call_args_list]
        assert any("Connected Handlers" in c for c in calls)

    def test_prints_logger_module_name(self, monkeypatch):
        """print_introspection mentions the logger module."""
        mod, mocks = _inject_and_import(monkeypatch)

        mod.print_introspection()

        console = mocks["aipass.cli.apps.modules.display"].console
        calls = [str(c) for c in console.print.call_args_list]
        assert any("logger" in c.lower() for c in calls)

    def test_fallback_to_rich_when_cli_unavailable(self, monkeypatch):
        """print_introspection falls back to rich Console if CLI import fails."""
        mod, mocks = _inject_and_import(monkeypatch)

        # Make the CLI display import raise ImportError
        cli_display_mock = mocks["aipass.cli.apps.modules.display"]
        cli_display_mock.console = MagicMock(side_effect=ImportError("no CLI"))

        # Remove the display module so the import inside print_introspection fails
        monkeypatch.delitem(sys.modules, "aipass.cli.apps.modules.display", raising=False)

        # Should not raise — falls back to rich.console.Console
        with patch("rich.console.Console") as mock_rich:
            mock_rich_instance = MagicMock()
            mock_rich.return_value = mock_rich_instance

            # Force re-import to pick up removed module
            sys.modules.pop(MODULE_NAME, None)
            import importlib
            import aipass.prax.apps.modules.logger as fresh_mod

            importlib.reload(fresh_mod)

            fresh_mod.print_introspection()

            mock_rich.assert_called_once()
            mock_rich_instance.print.assert_called()
