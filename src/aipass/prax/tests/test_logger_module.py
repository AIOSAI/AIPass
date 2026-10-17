# =================== AIPass ====================
# Name: test_logger_module.py
# Description: Unit tests for PRAX logger module (public API)
# Version: 1.1.0
# Created: 2026-04-03
# Modified: 2026-10-17
# =============================================

"""Tests for apps/modules/logger.py."""

# logger.py is bound once at the top; _inject_and_import doubles each handler name on it per test.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that each __all__ re-export, e.g. get_direct_logger(), names a real import (F822)
# seedgo: no-test-needed(through_the_command) — append_jsonl()'s writing, covered by tests/test_jsonl_writer.py
# seedgo: no-test-needed(through_the_command) — check_file_watcher_liveness() itself, covered by tests/test_watcher.py

import json
import os
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.cli.apps.modules import display
from aipass.prax.apps.handlers.config import load as config_load
from aipass.prax.apps.handlers.logging import lifecycle
from aipass.prax.apps.modules import logger as logger_module
from aipass.trigger.apps.modules import core as trigger_core


MODULE_NAME = "aipass.prax.apps.modules.logger"

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
]


def _build_handler_mocks(tmp_path):
    """Create mock modules for every handler dependency, keyed by module path."""
    mocks = {}
    for dep in HANDLER_DEPS:
        mocks[dep] = MagicMock()

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

    intro = mocks["aipass.prax.apps.handlers.logging.introspection"]
    intro.get_calling_module = MagicMock(return_value="test_module")
    intro.get_caller_info = MagicMock(return_value=("test_module", "/fake/path.py", "prax"))

    override = mocks["aipass.prax.apps.handlers.logging.override"]
    override.is_override_active = MagicMock(return_value=False)

    direct = mocks["aipass.prax.apps.handlers.logging.direct"]
    mock_direct_logger = MagicMock()
    direct.get_direct_logger = MagicMock(return_value=mock_direct_logger)
    direct.direct_log = MagicMock()
    direct.DirectLogger = MagicMock

    watcher = mocks["aipass.prax.apps.handlers.discovery.watcher"]
    watcher.start_file_watcher = MagicMock()
    watcher.is_file_watcher_active = MagicMock(return_value=True)

    registry = mocks["aipass.prax.apps.handlers.registry.load"]
    registry.load_module_registry = MagicMock(
        return_value=[
            {"name": "mod_a"},
            {"name": "mod_b"},
            {"name": "mod_c"},
        ]
    )

    config = mocks["aipass.prax.apps.handlers.config.load"]
    config.get_system_logs_dir = MagicMock(return_value=tmp_path / "prax" / "logs" / "system")
    config.get_module_logs_dir = MagicMock(return_value=tmp_path / "prax" / "logs" / "modules")
    config.PRAX_JSON_DIR = tmp_path / "prax" / "json"

    json_mod = mocks["aipass.prax.apps.handlers.json"]
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_mod.json_handler = mock_json_handler

    # The cli package is not doubled: tests read the real console with capsys.
    return mocks


# The names logger.py takes from each handler at import: (its name, the handler's name).
_IMPORTED_NAMES = {
    "aipass.prax.apps.handlers.logging.setup": [
        ("setup_individual_logger", "setup_individual_logger"),
        ("get_captured_loggers_count", "get_captured_loggers_count"),
        ("_enable_terminal", "enable_terminal_output"),
        ("_disable_terminal", "disable_terminal_output"),
    ],
    "aipass.prax.apps.handlers.logging.introspection": [("get_caller_info", "get_caller_info")],
    "aipass.prax.apps.handlers.logging.override": [("is_override_active", "is_override_active")],
    "aipass.prax.apps.handlers.discovery.watcher": [
        ("is_file_watcher_active", "is_file_watcher_active"),
        ("check_file_watcher_liveness", "check_file_watcher_liveness"),
    ],
    "aipass.prax.apps.handlers.registry.load": [
        ("load_module_registry", "load_module_registry"),
        ("load_last_scan", "load_last_scan"),
    ],
    "aipass.prax.apps.handlers.config.load": [
        ("get_system_logs_dir", "get_system_logs_dir"),
        ("get_module_logs_dir", "get_module_logs_dir"),
    ],
    "aipass.prax.apps.handlers.logging.direct": [
        ("get_direct_logger", "get_direct_logger"),
        ("direct_log", "direct_log"),
        ("DirectLogger", "DirectLogger"),
    ],
    "aipass.prax.apps.handlers.json": [("json_handler", "json_handler")],
}


def _inject_and_import(monkeypatch, tmp_path):
    """(logger_module, mocks): every handler name doubled on it, first-log-line latch reset."""
    mocks = _build_handler_mocks(tmp_path)
    for dep, names in _IMPORTED_NAMES.items():
        for local, source in names:
            monkeypatch.setattr(logger_module, local, getattr(mocks[dep], source))
    monkeypatch.setattr(logger_module.SystemLogger, "_watcher_started", False)
    return logger_module, mocks


def _lifecycle_doubled(monkeypatch, modules_count: int = 0) -> MagicMock:
    """Double the two doors on the real lifecycle module; logger.py imports them lazily."""
    doubled = MagicMock()
    doubled.run_initialize.return_value = {"modules_count": modules_count}
    monkeypatch.setattr(lifecycle, "run_initialize", doubled.run_initialize)
    monkeypatch.setattr(lifecycle, "run_shutdown", doubled.run_shutdown)
    return doubled


def _inject_trigger(monkeypatch):
    """Mock the trigger core that the two lifecycle doors import lazily.

    Not in HANDLER_DEPS: trigger is no module-level dependency of logging. Returns the recorder."""
    recorder = MagicMock()
    recorder.fire = MagicMock(return_value={"handlers": 0, "ran": 0, "failed": 0})
    monkeypatch.setattr(trigger_core, "trigger", recorder)
    return recorder


class TestGetSystemLogger:
    """Tests for get_system_logger() — returns a logger with standard methods."""

    def test_returns_logger_object(self, monkeypatch, tmp_path):
        """get_system_logger returns an object from setup_individual_logger."""
        mod, mocks = _inject_and_import(monkeypatch, tmp_path)

        result = mod.get_system_logger()

        setup = mocks["aipass.prax.apps.handlers.logging.setup"]
        assert result is setup.setup_individual_logger.return_value
        name, path, branch = mocks["aipass.prax.apps.handlers.logging.introspection"].get_caller_info.return_value
        setup.setup_individual_logger.assert_called_once_with(name, caller_path=path, caller_branch=branch)

    def test_returned_logger_has_info_method(self, monkeypatch, tmp_path):
        """The returned logger has an info() method."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        result = mod.get_system_logger()

        assert hasattr(result, "info")
        assert callable(result.info)

    def test_returned_logger_has_warning_method(self, monkeypatch, tmp_path):
        """The returned logger has a warning() method."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        result = mod.get_system_logger()

        assert hasattr(result, "warning")
        assert callable(result.warning)

    def test_returned_logger_has_error_method(self, monkeypatch, tmp_path):
        """The returned logger has an error() method."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        result = mod.get_system_logger()

        assert hasattr(result, "error")
        assert callable(result.error)

    def test_passes_caller_info_to_setup(self, monkeypatch, tmp_path):
        """get_system_logger passes caller_path and caller_branch from introspection."""
        mod, mocks = _inject_and_import(monkeypatch, tmp_path)

        mod.get_system_logger()

        intro = mocks["aipass.prax.apps.handlers.logging.introspection"]
        intro.get_caller_info.assert_called_once()

        setup = mocks["aipass.prax.apps.handlers.logging.setup"]
        call_kwargs = setup.setup_individual_logger.call_args
        assert call_kwargs[1]["caller_path"] == "/fake/path.py"
        assert call_kwargs[1]["caller_branch"] == "prax"


class TestGetSystemStatus:
    """Tests for get_system_status() — returns a dict with system info."""

    def test_returns_dict(self, monkeypatch, tmp_path):
        """The status dict carries exactly the documented keys: the shape, not one entry."""
        mod, mocks = _inject_and_import(monkeypatch, tmp_path)

        result = mod.get_system_status()

        assert isinstance(result, dict)
        assert sorted(result) == [
            "file_watcher_active",
            "individual_loggers",
            "last_scan",
            "logger_override_active",
            "module_logs_dir",
            "registry_file",
            "system_logs_dir",
            "total_modules",
        ]
        # DATA_FILE was built at import from PRAX_ROOT/prax_json, not the conftest's PRAX_JSON_DIR.
        assert result["registry_file"] == str(config_load.PRAX_ROOT / "prax_json" / "prax_logger_data.json")

    def test_contains_total_modules_key(self, monkeypatch, tmp_path):
        """Result includes total_modules count from registry."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        result = mod.get_system_status()

        assert "total_modules" in result
        assert result["total_modules"] == 3  # 3 modules in mock registry

    def test_contains_individual_loggers_key(self, monkeypatch, tmp_path):
        """Result includes individual_loggers count."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        result = mod.get_system_status()

        assert "individual_loggers" in result
        assert result["individual_loggers"] == 5  # from mock

    def test_contains_system_logs_dir(self, monkeypatch, tmp_path):
        """Result includes system_logs_dir path."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        result = mod.get_system_status()

        assert "system_logs_dir" in result
        assert "prax" in result["system_logs_dir"]

    def test_contains_module_logs_dir(self, monkeypatch, tmp_path):
        """Result includes module_logs_dir path."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        result = mod.get_system_status()

        assert "module_logs_dir" in result

    def test_contains_file_watcher_status(self, monkeypatch, tmp_path):
        """Result includes file_watcher_active boolean."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        result = mod.get_system_status()

        assert "file_watcher_active" in result
        assert result["file_watcher_active"] is True

    def test_contains_override_status(self, monkeypatch, tmp_path):
        """Result includes logger_override_active boolean."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        result = mod.get_system_status()

        assert "logger_override_active" in result
        assert result["logger_override_active"] is False

    def test_contains_registry_file(self, monkeypatch, tmp_path):
        """Result includes registry_file path."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        result = mod.get_system_status()

        assert "registry_file" in result

    def test_calls_load_module_registry(self, monkeypatch, tmp_path):
        """get_system_status calls load_module_registry to count modules."""
        mod, mocks = _inject_and_import(monkeypatch, tmp_path)

        mod.get_system_status()

        registry = mocks["aipass.prax.apps.handlers.registry.load"]
        registry.load_module_registry.assert_called_once_with()


class TestHandleCommand:
    """Tests for handle_command() — introspection gate and routing."""

    @staticmethod
    def _introspections(monkeypatch, mod):
        """Record each print_introspection call handle_command makes: the effect, not the True."""
        seen = []
        monkeypatch.setattr(mod, "print_introspection", lambda: seen.append("introspection"))
        return seen

    def test_no_args_calls_introspection_returns_true(self, monkeypatch, tmp_path):
        """Empty args list prints introspection and returns True."""
        mod, mocks = _inject_and_import(monkeypatch, tmp_path)
        seen = self._introspections(monkeypatch, mod)

        result = mod.handle_command("logger", [])

        assert result is True
        assert seen == ["introspection"]

    def test_help_flag_returns_true(self, monkeypatch, tmp_path):
        """--help flag prints introspection and returns True."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)
        seen = self._introspections(monkeypatch, mod)

        result = mod.handle_command("logger", ["--help"])

        assert result is True
        assert seen == ["introspection"]

    def test_h_flag_returns_true(self, monkeypatch, tmp_path):
        """-h flag prints introspection and returns True."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)
        seen = self._introspections(monkeypatch, mod)

        result = mod.handle_command("logger", ["-h"])

        assert result is True
        assert seen == ["introspection"]

    def test_help_word_returns_true(self, monkeypatch, tmp_path):
        """'help' subcommand prints introspection and returns True."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)
        seen = self._introspections(monkeypatch, mod)

        result = mod.handle_command("logger", ["help"])

        assert result is True
        assert seen == ["introspection"]

    def test_unknown_arg_returns_false(self, monkeypatch, tmp_path):
        """Unknown argument returns False (unhandled) and prints nothing."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)
        seen = self._introspections(monkeypatch, mod)

        result = mod.handle_command("logger", ["unknown-subcommand"])

        assert result is False
        assert seen == []

    def test_logs_operation_via_json_handler(self, monkeypatch, tmp_path):
        """handle_command logs the operation through json_handler."""
        mod, mocks = _inject_and_import(monkeypatch, tmp_path)

        mod.handle_command("logger", ["--help"])

        json_handler = mocks["aipass.prax.apps.handlers.json"].json_handler
        json_handler.log_operation.assert_called_once_with("logger_handle_command", {"args": ["--help"]})


class TestInitializeLoggingSystem:
    """Tests for initialize_logging_system() — delegates to lifecycle handler."""

    def test_calls_lifecycle_run_initialize(self, monkeypatch, tmp_path):
        """initialize_logging_system calls run_initialize from lifecycle handler."""
        mod, mocks = _inject_and_import(monkeypatch, tmp_path)
        mock_lifecycle = _lifecycle_doubled(monkeypatch, modules_count=42)

        _inject_trigger(monkeypatch)

        mod.initialize_logging_system()

        mock_lifecycle.run_initialize.assert_called_once_with("prax_logger")

    def test_prints_initialization_message(self, monkeypatch, tmp_path, capsys):
        """initialize_logging_system prints init and completion messages."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)
        _lifecycle_doubled(monkeypatch, modules_count=10)

        _inject_trigger(monkeypatch)

        capsys.readouterr()
        mod.initialize_logging_system()

        assert capsys.readouterr().out.splitlines() == [
            "[prax_logger] Initializing system-wide logging...",
            "[prax_logger] System initialized - 10 modules, individual logging",
        ]

    def test_fires_the_lifecycle_event_after_run_initialize(self, monkeypatch, tmp_path):
        """seedgo trigger.md Pattern 9: the explicit lifecycle door fires logging_system_initialized."""
        mod, _ = _inject_and_import(monkeypatch, tmp_path)
        _lifecycle_doubled(monkeypatch, modules_count=42)
        trigger = _inject_trigger(monkeypatch)

        mod.initialize_logging_system()

        trigger.fire.assert_called_once_with("logging_system_initialized", modules_count=42)

    def test_a_failed_fire_does_not_fail_the_initialize(self, monkeypatch, tmp_path, capsys):
        """These doors must still work where trigger cannot import or inotify is exhausted."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)
        _lifecycle_doubled(monkeypatch, modules_count=7)
        trigger = _inject_trigger(monkeypatch)
        trigger.fire.side_effect = OSError("inotify watch limit reached")

        capsys.readouterr()
        mod.initialize_logging_system()  # must not raise

        assert (
            capsys.readouterr().out.splitlines()[-1]
            == "[prax_logger] System initialized - 7 modules, individual logging"
        )


class TestShutdownLoggingSystem:
    """Tests for shutdown_logging_system() — delegates to lifecycle handler."""

    def test_calls_lifecycle_run_shutdown(self, monkeypatch, tmp_path):
        """shutdown_logging_system calls run_shutdown from lifecycle handler."""
        mod, mocks = _inject_and_import(monkeypatch, tmp_path)
        mock_lifecycle = _lifecycle_doubled(monkeypatch)

        _inject_trigger(monkeypatch)

        mod.shutdown_logging_system()

        mock_lifecycle.run_shutdown.assert_called_once_with("prax_logger")

    def test_prints_shutdown_messages(self, monkeypatch, tmp_path, capsys):
        """shutdown_logging_system prints shutdown and completion messages."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)
        _lifecycle_doubled(monkeypatch)

        _inject_trigger(monkeypatch)

        capsys.readouterr()
        mod.shutdown_logging_system()

        assert capsys.readouterr().out.splitlines() == [
            "[prax_logger] Shutting down logging system...",
            "[prax_logger] Shutdown complete",
        ]

    def test_fires_the_lifecycle_event_after_run_shutdown(self, monkeypatch, tmp_path):
        """The other half of the Pattern 9 pair, fired last: the system IS down."""
        mod, _ = _inject_and_import(monkeypatch, tmp_path)
        _lifecycle_doubled(monkeypatch)
        trigger = _inject_trigger(monkeypatch)

        mod.shutdown_logging_system()

        trigger.fire.assert_called_once_with("logging_system_shutdown")

    def test_a_failed_fire_does_not_fail_the_shutdown(self, monkeypatch, tmp_path):
        """A shutdown that cannot announce itself is still a shutdown."""
        mod, mocks = _inject_and_import(monkeypatch, tmp_path)
        mock_lifecycle = _lifecycle_doubled(monkeypatch)
        trigger = _inject_trigger(monkeypatch)
        trigger.fire.side_effect = ImportError("no aipass.trigger on this host")

        mod.shutdown_logging_system()  # must not raise

        mock_lifecycle.run_shutdown.assert_called_once_with("prax_logger")


class TestTerminalOutputControl:
    """Tests for enable/disable terminal output pass-through functions."""

    def test_enable_delegates_to_setup_handler(self, monkeypatch, tmp_path):
        """enable_terminal_output calls the setup handler's enable function."""
        mod, mocks = _inject_and_import(monkeypatch, tmp_path)

        mod.enable_terminal_output()

        setup = mocks["aipass.prax.apps.handlers.logging.setup"]
        # Neither door takes an argument: the claim is one delegation and nothing else.
        setup.enable_terminal_output.assert_called_once_with()
        setup.disable_terminal_output.assert_not_called()

    def test_disable_delegates_to_setup_handler(self, monkeypatch, tmp_path):
        """disable_terminal_output calls the setup handler's disable function."""
        mod, mocks = _inject_and_import(monkeypatch, tmp_path)

        mod.disable_terminal_output()

        setup = mocks["aipass.prax.apps.handlers.logging.setup"]
        setup.disable_terminal_output.assert_called_once_with()
        setup.enable_terminal_output.assert_not_called()


_PROXIED_LEVELS = ("debug", "info", "warning", "error")


class TestSystemLogger:
    """Tests for the SystemLogger class — auto-routing logger proxy."""

    def test_system_logger_instance_exists(self, monkeypatch, tmp_path):
        """Module exports a system_logger instance of SystemLogger."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        assert hasattr(mod, "system_logger")
        assert isinstance(mod.system_logger, mod.SystemLogger)

    def test_system_logger_has_info(self, monkeypatch, tmp_path):
        """SystemLogger exposes an info() method."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        assert callable(getattr(mod.system_logger, "info", None))

    def test_system_logger_has_warning(self, monkeypatch, tmp_path):
        """SystemLogger exposes a warning() method."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        assert callable(getattr(mod.system_logger, "warning", None))

    def test_system_logger_has_error(self, monkeypatch, tmp_path):
        """SystemLogger exposes an error() method."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        assert callable(getattr(mod.system_logger, "error", None))

    def test_system_logger_has_debug(self, monkeypatch, tmp_path):
        """SystemLogger exposes a debug() method."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        assert callable(getattr(mod.system_logger, "debug", None))

    @pytest.mark.parametrize("level", _PROXIED_LEVELS)
    def test_each_level_delegates_to_that_level_of_the_routed_logger(self, monkeypatch, level, tmp_path):
        """Each proxy method goes through the per-caller lookup and calls THAT level, no other."""
        mod, mocks = _inject_and_import(monkeypatch, tmp_path)

        mod.SystemLogger._watcher_started = True
        setup = mocks["aipass.prax.apps.handlers.logging.setup"]
        routed = setup.setup_individual_logger.return_value

        getattr(mod.system_logger, level)("detail: %s", "value")

        setup.setup_individual_logger.assert_called()
        getattr(routed, level).assert_called_once_with("detail: %s", "value")
        for other_level in _PROXIED_LEVELS:
            if other_level != level:
                getattr(routed, other_level).assert_not_called()


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_module_name_is_prax_logger(self, monkeypatch, tmp_path):
        """MODULE_NAME is set to 'prax_logger'."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        assert mod.MODULE_NAME == "prax_logger"

    def test_data_file_is_path(self, monkeypatch, tmp_path):
        """DATA_FILE is a Path, and it is PRAX_JSON_DIR/prax_logger_data.json."""
        mod, mocks = _inject_and_import(monkeypatch, tmp_path)

        # Real config: DATA_FILE was built at import, before the conftest's PRAX_JSON_DIR.
        json_dir = config_load.PRAX_ROOT / "prax_json"
        assert isinstance(mod.DATA_FILE, Path)
        assert mod.DATA_FILE.name == "prax_logger_data.json"
        assert mod.DATA_FILE == json_dir / "prax_logger_data.json"

    def test_data_file_contains_module_name(self, monkeypatch, tmp_path):
        """DATA_FILE filename includes the module name."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        assert "prax_logger" in mod.DATA_FILE.name


class TestPrintIntrospection:
    """Tests for print_introspection() — displays module info."""

    def test_prints_handler_info(self, monkeypatch, tmp_path, capsys):
        """print_introspection prints handler connection details."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        capsys.readouterr()
        mod.print_introspection()

        assert "Connected Handlers:" in capsys.readouterr().out.splitlines()

    def test_prints_logger_module_name(self, monkeypatch, tmp_path, capsys):
        """print_introspection mentions the logger module."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        capsys.readouterr()
        mod.print_introspection()

        assert capsys.readouterr().out.splitlines()[1] == "logger Module"

    def test_fallback_to_rich_when_cli_unavailable(self, monkeypatch, tmp_path, capsys):
        """print_introspection falls back to rich Console if CLI import fails."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)

        # Without its console name, print_introspection's from-import raises ImportError.
        monkeypatch.delattr(display, "console")

        capsys.readouterr()
        mod.print_introspection()  # must not raise

        assert capsys.readouterr().out.splitlines()[1] == "logger Module"


def _exec_prax_init() -> dict:
    """Execute prax/__init__.py as source and return its namespace: what ships, not a restatement."""
    init_path = Path(__file__).resolve().parents[1] / "__init__.py"
    namespace: dict = {"__name__": "aipass.prax._fallback_probe", "__file__": str(init_path)}
    exec(compile(init_path.read_text(encoding="utf-8"), str(init_path), "exec"), namespace)
    return namespace


def _load_lazily(name: str):
    """Resolve a prax package name with the real logger import forced to fail.

    Lazy (PEP 562): the fallback fires on attribute access, so this calls the module's __getattr__."""
    namespace = _exec_prax_init()
    real_import = namespace["importlib"].import_module

    def broken_logger_chain(module_name: str):
        if module_name == namespace["_LOGGER_MODULE"]:
            raise ImportError(f"logger chain broken for {module_name}")
        return real_import(module_name)

    namespace["importlib"] = types.SimpleNamespace(import_module=broken_logger_chain)
    return namespace["__getattr__"](name)


def _load_fallback_logger():
    """The NullLogger instance the package falls back to."""
    return _load_lazily("logger")


class TestNullLoggerFallback:
    """Tests for the NullLogger used when prax's own import chain breaks."""

    def test_falls_back_when_logger_import_fails(self):
        """A broken prax must still hand callers a usable logger."""
        fallback = _load_fallback_logger()

        assert type(fallback).__name__ == "NullLogger"

    def test_exposes_every_system_logger_level(self):
        """Fallback parity: a level NullLogger lacks is an AttributeError when prax is already broken.

        Read from source: conftest's mock SystemLogger would make the check vacuous."""
        import ast

        source_path = Path(__file__).resolve().parents[1] / "apps" / "modules" / "logger.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        levels = [
            item.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "SystemLogger"
            for item in node.body
            if isinstance(item, ast.FunctionDef) and not item.name.startswith("_")
        ]

        fallback = _load_fallback_logger()

        assert "debug" in levels, "SystemLogger has no debug() — parity check is vacuous"
        for level in levels:
            assert callable(getattr(fallback, level, None)), f"NullLogger is missing {level}()"

    def test_levels_swallow_the_call_and_delegate(self):
        """Swallowing is the whole contract: each level returns None and hands the message on unaltered."""
        fallback = _load_fallback_logger()

        with patch.object(fallback, "_logger") as inner:
            assert fallback.debug("debug via fallback") is None
            assert fallback.info("info via fallback") is None
            assert fallback.warning("warning via fallback") is None
            assert fallback.error("error via fallback") is None

        inner.debug.assert_called_once_with("debug via fallback")
        inner.info.assert_called_once_with("info via fallback")
        inner.warning.assert_called_once_with("warning via fallback")
        inner.error.assert_called_once_with("error via fallback")

    def test_append_jsonl_degrades_to_none(self):
        """A broken logger chain leaves append_jsonl importable and falsy, never raising."""
        assert _load_lazily("append_jsonl") is None

    def test_fallback_is_not_built_when_the_logger_imports(self):
        """The fallback is the broken path only: a healthy prax hands back the real SystemLogger."""
        namespace = _exec_prax_init()

        resolved = namespace["__getattr__"]("logger")

        assert type(resolved).__name__ != "NullLogger"
        assert resolved is sys.modules[MODULE_NAME].system_logger

    def test_resolved_name_is_cached_in_globals(self):
        """PEP 562 __getattr__ fires once per name: the second access comes from the module dict."""
        namespace = _exec_prax_init()

        first = namespace["__getattr__"]("logger")

        assert namespace["logger"] is first

    def test_unknown_name_raises_attribute_error(self):
        """__getattr__ must not answer for names the package does not export."""
        namespace = _exec_prax_init()

        with pytest.raises(AttributeError):
            namespace["__getattr__"]("no_such_prax_name")


# Measured: the json service through the lazy init pulls these and nothing else; the logger graph stays out.
EXPECTED_COLD_FOOTPRINT = {
    "aipass",
    "aipass.prax",
    "aipass.prax.apps",
    "aipass.prax.apps.handlers",
    "aipass.prax.apps.handlers.json",
    "aipass.prax.apps.handlers.json.json_service",
}

# Neither stdlib nor ours: _distutils_hack comes from setuptools' .pth wherever setuptools is installed.
_INTERPRETER_NOISE = {"__main__", "sitecustomize", "_distutils_hack"}

_FOOTPRINT_PROBE = """
import json, sys
from aipass.prax import json_handler  # noqa: F401
print(json.dumps(sorted(n for n in sys.modules if n.split(".")[0] not in sys.stdlib_module_names)))
"""


def _cold_import_footprint() -> set:
    """Non-stdlib modules a fresh interpreter loads for the json service alone."""
    result = subprocess.run(
        [sys.executable, "-c", _FOOTPRINT_PROBE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(Path(__file__).resolve().parents[3]),
        env={**os.environ},
        timeout=120,
    )
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    return set(json.loads(result.stdout.strip().splitlines()[-1])) - _INTERPRETER_NOISE


class TestLazyInitImportFootprint:
    """The lazy init's whole purpose, pinned in a subprocess: pytest has already imported prax's world."""

    def test_json_service_pulls_no_third_party(self):
        """Stdlib guard: the json path must reach no package outside aipass."""
        footprint = _cold_import_footprint()

        third_party = {n for n in footprint if n.split(".")[0] != "aipass"}
        assert third_party == set(), f"json service dragged in third-party modules: {sorted(third_party)}"

    def test_json_service_pulls_only_prax_modules(self):
        """Every aipass module loaded belongs to prax — no cross-branch edge."""
        footprint = _cold_import_footprint()

        strangers = {n for n in footprint if n != "aipass" and not n.startswith("aipass.prax")}
        assert strangers == set(), f"json service reached outside prax: {sorted(strangers)}"

    def test_cold_footprint_is_the_measured_set(self):
        """The exact list. A new import on this path is a decision, not a drift."""
        assert _cold_import_footprint() == EXPECTED_COLD_FOOTPRINT

    def test_the_logger_graph_stays_cold(self):
        """The named costs of the eager init: the logger module, watchdog and aipass.trigger."""
        footprint = _cold_import_footprint()

        assert "aipass.prax.apps.modules.logger" not in footprint
        assert not any(n == "watchdog" or n.startswith("watchdog.") for n in footprint)
        assert not any(n == "aipass.trigger" or n.startswith("aipass.trigger.") for n in footprint)


_TRIGGER_PROBE = """
import json, sys
from aipass.prax import logger
logger.info("probe line")
print(json.dumps(sorted(n for n in sys.modules if n == "aipass.trigger" or n.startswith("aipass.trigger."))))
"""


def _trigger_modules_after_one_log_line(log_dir) -> list:
    """aipass.trigger modules a fresh interpreter holds after logging once."""
    result = subprocess.run(
        [sys.executable, "-c", _TRIGGER_PROBE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(Path(__file__).resolve().parents[3]),
        env={**os.environ, "AIPASS_TEST_LOG_DIR": str(log_dir)},
        timeout=120,
    )
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


# Logging one line loads nothing under aipass.trigger; an entry here is a new edge onto the logging path.
_TRIGGER_SHELLS_AFTER_ONE_LOG_LINE = []


class TestLoggingPathIsTriggerFree:
    """Lifecycle events live on the two explicit doors, not on the hot path.

    The doors import trigger inside themselves; at module level every log line would pay its graph."""

    def test_logging_a_line_does_not_load_the_trigger_core(self, tmp_path):
        """A process that only logs must load nothing under aipass.trigger.apps.modules."""
        loaded = _trigger_modules_after_one_log_line(tmp_path)

        assert not any(n.startswith("aipass.trigger.apps.modules") for n in loaded), (
            f"the logging path reached trigger's core: {loaded}"
        )

    def test_the_trigger_footprint_of_a_log_line_is_the_measured_set(self, tmp_path):
        """The exact list. A new trigger import on the logging path is a decision, not a drift."""
        assert _trigger_modules_after_one_log_line(tmp_path) == _TRIGGER_SHELLS_AFTER_ONE_LOG_LINE


class TestEnsureWatcherStartsNothing:
    """Logging is not a reason to watch the filesystem: discovery is a scheduled scan."""

    def test_first_log_line_starts_no_watcher(self, monkeypatch, tmp_path):
        """The first log line starts no watcher, background or not."""
        mod, mocks = _inject_and_import(monkeypatch, tmp_path)
        watcher = mocks["aipass.prax.apps.handlers.discovery.watcher"]
        watcher.start_file_watcher_in_background = MagicMock()
        mod.SystemLogger._watcher_started = False

        mod.SystemLogger()._ensure_watcher()

        watcher.start_file_watcher_in_background.assert_not_called()
        watcher.start_file_watcher.assert_not_called()

    def test_the_logger_no_longer_binds_the_background_start(self, monkeypatch, tmp_path):
        """A name the module does not import cannot be called by accident."""
        mod, _ = _inject_and_import(monkeypatch, tmp_path)

        assert not hasattr(mod, "start_file_watcher_in_background")

    def test_later_log_lines_still_check_liveness(self, monkeypatch, tmp_path):
        """The check serves initialize_logging_system, whose watcher can still die under its process."""
        mod, _ = _inject_and_import(monkeypatch, tmp_path)
        # Patched on the module, not the watcher mock: logger.py from-imports the name.
        liveness = MagicMock()
        monkeypatch.setattr(mod, "check_file_watcher_liveness", liveness)
        mod.SystemLogger._watcher_started = True

        mod.SystemLogger()._ensure_watcher()

        liveness.assert_called_once_with()

    def test_the_first_line_does_not_pay_for_the_liveness_check(self, monkeypatch, tmp_path):
        """`_watcher_started` means "past the first log line", when no watcher can exist yet."""
        mod, _ = _inject_and_import(monkeypatch, tmp_path)
        liveness = MagicMock()
        monkeypatch.setattr(mod, "check_file_watcher_liveness", liveness)
        mod.SystemLogger._watcher_started = False

        mod.SystemLogger()._ensure_watcher()

        liveness.assert_not_called()
        assert mod.SystemLogger._watcher_started is True
