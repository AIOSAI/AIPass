# =================== AIPass ====================
# Name: test_logger_module.py
# Description: Unit tests for PRAX logger module (public API)
# Version: 1.3.0
# Created: 2026-04-03
# Modified: 2026-11-16
# =============================================

"""Tests for apps/modules/logger.py."""

# logger.py is bound once at the top; _inject_and_import doubles each handler name on it per test.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that each __all__ re-export, e.g. get_direct_logger(), names a real import (F822)
# sentry: no-test-needed(through_the_command) — append_jsonl()'s writing, covered by tests/test_jsonl_writer.py

import ast
import json
import os
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aipass.cli import display
from aipass.prax.apps.handlers.config import load as config_load
from aipass.prax.apps.handlers.logging import jsonl_writer
from aipass.prax.apps.modules import logger as logger_module


MODULE_NAME = "aipass.prax.apps.modules.logger"
WATCHER = "aipass.prax.apps.handlers.discovery.watcher"

HANDLER_DEPS = [
    "aipass.prax.apps.handlers.logging.setup",
    "aipass.prax.apps.handlers.logging.introspection",
    "aipass.prax.apps.handlers.logging.direct",
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

    intro = mocks["aipass.prax.apps.handlers.logging.introspection"]
    intro.get_caller_info = MagicMock(return_value=("test_module", "/fake/path.py", "prax"))

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
    ],
    "aipass.prax.apps.handlers.logging.introspection": [("get_caller_info", "get_caller_info")],
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
    # logger.py reaches the watcher through sys.modules, never a module-level import.
    monkeypatch.setitem(sys.modules, WATCHER, mocks[WATCHER])
    return logger_module, mocks


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
            "module_logs_dir",
            "registry_file",
            "system_logs_dir",
            "total_modules",
        ]
        # The discovery registry, not the logger's own data file.
        assert Path(result["registry_file"]).name == "prax_registry.json"

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

    def test_a_missing_cli_console_raises(self, monkeypatch, tmp_path):
        """No rich fallback: a broken CLI is an error, not a second console."""
        mod, _mocks = _inject_and_import(monkeypatch, tmp_path)
        monkeypatch.delattr(display, "console")
        monkeypatch.delattr("aipass.cli.console", raising=False)  # the door caches a name it already handed out

        with pytest.raises(ImportError):
            mod.print_introspection()


def _exec_prax_init() -> dict:
    """Execute prax/__init__.py as source and return its namespace: what ships, not a restatement."""
    init_path = Path(__file__).resolve().parents[1] / "__init__.py"
    namespace: dict = {"__name__": "aipass.prax._fallback_probe", "__file__": str(init_path)}
    exec(compile(init_path.read_text(encoding="utf-8"), str(init_path), "exec"), namespace)
    return namespace


_BROKEN_CHAIN_PROBE = """
import json, sys
sys.modules["aipass.prax.apps.handlers.logging.setup"] = None  # import of a None entry raises ImportError
results = {}
for spelling in sys.argv[1:]:
    try:
        exec(spelling, {})
        results[spelling] = "imported"
    except Exception as exc:
        results[spelling] = "ImportError" if isinstance(exc, ImportError) else type(exc).__name__
print(json.dumps(results))
"""


def _spellings_under_a_broken_chain() -> dict:
    """Each spelling's outcome in a fresh interpreter whose setup.py cannot import."""
    spellings = [
        "from aipass.prax import logger",
        "from aipass.prax.apps.modules.logger import system_logger",
        "from aipass.prax.apps.modules.logger import get_direct_logger",
    ]
    result = subprocess.run(
        [sys.executable, "-c", _BROKEN_CHAIN_PROBE, *spellings],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(Path(__file__).resolve().parents[3]),
        env={**os.environ},
        timeout=120,
    )
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def _load_lazily(name: str):
    """Resolve a prax package name with the real logger import forced to fail.

    Lazy (PEP 562): the import runs on attribute access, so this calls the module's __getattr__."""
    namespace = _exec_prax_init()
    real_import = namespace["importlib"].import_module

    def broken_logger_chain(module_name: str):
        if module_name == namespace["_LOGGER_MODULE"]:
            raise ImportError(f"logger chain broken for {module_name}")
        return real_import(module_name)

    namespace["importlib"] = types.SimpleNamespace(import_module=broken_logger_chain)
    return namespace["__getattr__"](name)


class TestBrokenChainRaises:
    """No fallback: a logger chain that cannot import raises, in every spelling."""

    def test_the_short_spelling_raises_in_process(self):
        with pytest.raises(ImportError, match="logger chain broken"):
            _load_lazily("logger")

    def test_every_spelling_raises_when_a_handler_cannot_import(self):
        """An induced break in a subprocess, so nothing leaks into this one."""
        assert _spellings_under_a_broken_chain() == {
            "from aipass.prax import logger": "ImportError",
            "from aipass.prax.apps.modules.logger import system_logger": "ImportError",
            "from aipass.prax.apps.modules.logger import get_direct_logger": "ImportError",
        }

    def test_the_package_defines_no_fallback_logger(self):
        namespace = _exec_prax_init()

        assert "NullLogger" not in namespace
        assert "_logging" not in namespace and "logging" not in namespace

    def test_append_jsonl_resolves_to_the_writer_when_the_logger_chain_is_broken(self):
        """The writer is its own door: a broken logger graph cannot take append_jsonl down with it."""
        assert _load_lazily("append_jsonl") is jsonl_writer.append_jsonl

    def test_a_healthy_chain_hands_back_the_real_system_logger(self):
        namespace = _exec_prax_init()

        assert namespace["__getattr__"]("logger") is sys.modules[MODULE_NAME].system_logger

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
    # Its diagnostics ride prax's trail: the writer and trail, nothing of door one.
    "aipass.prax.apps.handlers.logging",
    "aipass.prax.apps.handlers.logging.jsonl_writer",
    "aipass.prax.apps.handlers.logging.trail",
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


_DOOR_PROBE = """
import json, sys
import aipass.prax
cold = sorted(n for n in sys.modules if n == "aipass" or n.startswith("aipass."))
for name in sys.argv[1:]:
    getattr(aipass.prax, name)
warm = sorted(n for n in sys.modules if n == "aipass" or n.startswith("aipass."))
print(json.dumps([cold, warm]))
"""

_WRITER_DOOR = {
    "aipass",
    "aipass.prax",
    "aipass.prax.apps",
    "aipass.prax.apps.handlers",
    "aipass.prax.apps.handlers.logging",
    "aipass.prax.apps.handlers.logging.jsonl_writer",
}


def _aipass_modules_through_the_door(*names: str) -> tuple:
    """aipass modules a fresh interpreter holds after `import aipass.prax`, then after resolving *names*."""
    result = subprocess.run(
        [sys.executable, "-c", _DOOR_PROBE, *names],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(Path(__file__).resolve().parents[3]),
        env={**os.environ},
        timeout=120,
    )
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    cold, warm = json.loads(result.stdout.strip().splitlines()[-1])
    return set(cold), set(warm)


class TestStandaloneDoors:
    """append_jsonl and trail resolve straight to their own modules, never through the logger graph."""

    def test_append_jsonl_resolves_without_the_logger_module(self):
        """Shipped defect: the append_jsonl door went through modules.logger and its whole graph."""
        cold, warm = _aipass_modules_through_the_door("append_jsonl")

        assert cold == {"aipass", "aipass.prax"}
        assert warm == _WRITER_DOOR

    def test_trail_resolves_without_the_logger_module(self):
        """Door two: trail loads its own module and the writer, nothing of the logger graph."""
        cold, warm = _aipass_modules_through_the_door("trail")

        assert cold == {"aipass", "aipass.prax"}
        assert warm == _WRITER_DOOR | {"aipass.prax.apps.handlers.logging.trail"}


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
    """The hot path imports no trigger: at module level every log line would pay its graph."""

    def test_logging_a_line_does_not_load_the_trigger_core(self, tmp_path):
        """A process that only logs must load nothing under aipass.trigger.apps.modules."""
        loaded = _trigger_modules_after_one_log_line(tmp_path)

        assert not any(n.startswith("aipass.trigger.apps.modules") for n in loaded), (
            f"the logging path reached trigger's core: {loaded}"
        )

    def test_the_trigger_footprint_of_a_log_line_is_the_measured_set(self, tmp_path):
        """The exact list. A new trigger import on the logging path is a decision, not a drift."""
        assert _trigger_modules_after_one_log_line(tmp_path) == _TRIGGER_SHELLS_AFTER_ONE_LOG_LINE


class TestNoWatcherHookOnTheLogPath:
    """A log line checks no watcher: nothing in production starts one (start_file_watcher has test callers only)."""

    def test_system_logger_has_no_watcher_hook(self):
        assert not hasattr(logger_module.SystemLogger, "_ensure_watcher")
        assert not hasattr(logger_module.SystemLogger, "_watcher_started")


_PRAX_ROOT = Path(__file__).resolve().parents[1]
_SKIP_PARTS = {".archive", "tests", "__pycache__", "docs.local", "dropbox", "tools"}


def _imports_stdlib_logging(path: Path) -> bool:
    """True when the file imports stdlib logging in any spelling."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "logging" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == "logging":
            return True
    return False


_LEVEL_METHODS = {"debug", "info", "warning", "error", "critical"}


def _defines_level_shaped_class(path: Path) -> bool:
    """True when the file defines a class with two or more level methods, sentry's K1 shape."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ClassDef):
            methods = {n.name for n in node.body if isinstance(n, ast.FunctionDef)}
            if len(methods & _LEVEL_METHODS) >= 2:
                return True
    return False


class TestPublishedLoggingFacts:
    """What prax publishes through its modules door for other branches to read."""

    def test_logging_allowed_is_exactly_the_files_that_hold_stdlib_logging(self):
        production = [*_PRAX_ROOT.glob("*.py"), *(_PRAX_ROOT / "apps").rglob("*.py")]
        holders = {
            "prax/" + p.relative_to(_PRAX_ROOT).as_posix()
            for p in production
            if not _SKIP_PARTS & set(p.relative_to(_PRAX_ROOT).parts) and _imports_stdlib_logging(p)
        }

        assert {path for path, _why in logger_module.LOGGING_ALLOWED} == holders

    def test_every_allowed_file_says_why_in_one_line(self):
        for path, why in logger_module.LOGGING_ALLOWED:
            assert why.strip() and "\n" not in why, path

    def test_logger_doors_is_exactly_the_files_that_define_a_level_shaped_class(self):
        production = [*_PRAX_ROOT.glob("*.py"), *(_PRAX_ROOT / "apps").rglob("*.py")]
        holders = {
            "prax/" + p.relative_to(_PRAX_ROOT).as_posix()
            for p in production
            if not _SKIP_PARTS & set(p.relative_to(_PRAX_ROOT).parts) and _defines_level_shaped_class(p)
        }

        assert {path for path, _why in logger_module.LOGGER_DOORS} == holders

    def test_every_door_file_says_why_in_one_line(self):
        for path, why in logger_module.LOGGER_DOORS:
            assert why.strip() and "\n" not in why, path

    def test_log_backup_count_is_the_deepest_configured_tier(self, monkeypatch):
        config_load.PRAX_LOGGER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        config_load.PRAX_LOGGER_CONFIG_FILE.write_text(
            json.dumps({"config": {"system_logs": {"backup_count": 5}, "local_logs": {"backup_count": 2}}}),
            encoding="utf-8",
        )

        assert logger_module.log_backup_count() == 5

    def test_log_backup_count_without_a_config_is_the_code_default(self):
        assert logger_module.log_backup_count() == max(
            config_load.DEFAULT_SYSTEM_LOGS["backup_count"], config_load.DEFAULT_LOCAL_LOGS["backup_count"]
        )
