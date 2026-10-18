# =================== AIPass ====================
# Name: conftest.py
# Description: Shared pytest fixtures for prax tests
# Version: 2.5.0
# Created: 2025-11-08
# Modified: 2026-10-17
# =============================================

"""Shared pytest fixtures for prax tests."""

import os
import tempfile

# Set before any prax import: the logger reads it at initialization.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import sys
import types
import pytest
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

from aipass.cli.apps.modules import display
from aipass.prax.apps.handlers.config import load as config_load
from aipass.prax.apps.handlers.monitoring import branch_detector, filesystem_handler
from aipass.prax.apps.handlers.registry import load as registry_load
from aipass.prax.apps.handlers.registry import save as registry_save
from aipass.prax.tests.support_test_filesystem_handler import _DOUBLES
from aipass.prax.tests.support_test_operations import _DASHBOARD_MODULES, _Screen

collect_ignore_glob = [".archive/*"]


@pytest.fixture(autouse=True)
def _resync_module_attrs() -> Generator[None, None, None]:
    """Keep sys.modules and parent-package attributes honest after module surgery.

    Reconciles both leak directions: a mock left in sys.modules itself, and a parent
    attribute still aimed at a throwaway twin (``import x.y as z`` walks attributes).
    Declared FIRST on purpose: autouse fixtures tear down in reverse, so this runs
    after monkeypatch has undone mock_prax_infrastructure's deliberate mocks.
    """
    yield

    leaked = {
        n
        for n, m in sys.modules.items()
        if n.startswith("aipass") and m is not None and not isinstance(m, types.ModuleType)
    }
    # Evict a package's submodules too: an orphaned child makes ``import a.b.c`` skip
    # the parent and die on the attribute walk ("cannot import name 'b'").
    doomed = sorted(
        n for n in sys.modules if n.startswith("aipass") and any(n == pkg or n.startswith(pkg + ".") for pkg in leaked)
    )
    for name in doomed:
        removed = sys.modules.pop(name, None)
        parent_name, _, leaf = name.rpartition(".")
        parent = sys.modules.get(parent_name)
        if parent is not None and getattr(parent, leaf, None) is removed:
            delattr(parent, leaf)

    snapshot = [(n, m) for n, m in sys.modules.items() if n.startswith("aipass") and isinstance(m, types.ModuleType)]

    for name, mod in snapshot:
        parent_name, _, leaf = name.rpartition(".")
        if not parent_name:
            continue
        parent = sys.modules.get(parent_name)
        if parent is not None and getattr(parent, leaf, mod) is not mod:
            setattr(parent, leaf, mod)

    for pkg_name, pkg in snapshot:
        for attr, value in list(vars(pkg).items()):
            if (
                isinstance(value, types.ModuleType)
                and getattr(value, "__name__", "") == f"{pkg_name}.{attr}"
                and f"{pkg_name}.{attr}" not in sys.modules
            ):
                delattr(pkg, attr)


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Pin the consoles: Rich sizes an unpinned one per print (80 POSIX, 79 Windows, -s, COLUMNS)."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next.

    Declared above mock_prax_infrastructure so the reset runs after its redirects come out.
    """
    yield
    display.reset_command_state()


@pytest.fixture(autouse=True)
def header_fires_into_a_recorder(monkeypatch) -> MagicMock:
    """header() fires cli_header_displayed into a recorder; the real trigger would call the live bus."""
    recorder = MagicMock()
    monkeypatch.setattr(display, "_TRIGGER", recorder)
    monkeypatch.setattr(display, "_TRIGGER_LOADED", True)
    return recorder


@pytest.fixture(autouse=True)
def mock_prax_infrastructure(monkeypatch, tmp_path) -> Path:
    """The real logger and json handler under tmp_path: both read AIPASS_TEST_LOG_DIR per call."""
    root = tmp_path / "aipass_test_logs"
    json_dir = root / "prax" / "prax_json"
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(root))
    monkeypatch.setattr(config_load, "PRAX_JSON_DIR", json_dir)
    # Fixed at import to the live git-ignored prax_json: dev seats and CI read different formats.
    monkeypatch.setattr(config_load, "PRAX_LOGGER_CONFIG_FILE", json_dir / "prax_logger_config.json")
    monkeypatch.setattr(registry_load, "REGISTRY_FILE", json_dir / "prax_registry.json")
    monkeypatch.setattr(registry_save, "PRAX_JSON_DIR", json_dir)
    monkeypatch.setattr(registry_save, "REGISTRY_FILE", json_dir / "prax_registry.json")
    return root


@pytest.fixture
def _branch_detector_fresh(monkeypatch):
    """Double branch_detector's collaborators where it binds them and empty its singleton."""
    monkeypatch.setattr(branch_detector, "logger", MagicMock())
    monkeypatch.setattr(branch_detector, "json_handler", MagicMock())
    monkeypatch.setattr(branch_detector, "_detector_instance", None)


@pytest.fixture
def _filesystem_handler_doubled(monkeypatch):
    """Double every name filesystem_handler bound, plus its logger and json service, for one test.

    Tests read the doubles back through support_test_filesystem_handler._DOUBLES.
    """
    event_queue = MagicMock()
    event_queue.MonitoringEvent = MagicMock()
    event_queue.MonitoringQueue = MagicMock
    branch_detector = MagicMock()
    branch_detector.detect_branch_from_path = MagicMock(return_value="PRAX")
    filters = MagicMock()
    filters.should_monitor = MagicMock(return_value=True)
    filters.get_priority = MagicMock(return_value="info")
    queue = MagicMock()
    queue.enqueue = MagicMock(return_value=True)

    monkeypatch.setattr(filesystem_handler, "MonitoringEvent", event_queue.MonitoringEvent)
    monkeypatch.setattr(filesystem_handler, "MonitoringQueue", event_queue.MonitoringQueue)
    monkeypatch.setattr(filesystem_handler, "detect_branch_from_path", branch_detector.detect_branch_from_path)
    monkeypatch.setattr(filesystem_handler, "should_monitor", filters.should_monitor)
    monkeypatch.setattr(filesystem_handler, "get_priority", filters.get_priority)
    monkeypatch.setattr(filesystem_handler, "logger", MagicMock())
    monkeypatch.setattr(filesystem_handler, "json_handler", MagicMock())
    for name, double in (
        ("event_queue", event_queue),
        ("branch_detector", branch_detector),
        ("filters", filters),
        ("queue", queue),
    ):
        monkeypatch.setitem(_DOUBLES, name, double)


@pytest.fixture
def _dashboard_quiet(monkeypatch):
    """A logger and a json service that write nothing, on every dashboard module."""
    for module in _DASHBOARD_MODULES:
        for name in ("logger", "json_handler"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, MagicMock())


@pytest.fixture
def screen(capsys) -> _Screen:
    return _Screen(capsys)
