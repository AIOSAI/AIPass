# =================== AIPass ====================
# Name: conftest.py
# Description: Shared pytest fixtures for prax tests
# Version: 2.5.0
# Created: 2025-11-08
# Modified: 2026-10-10
# =============================================

"""Shared pytest fixtures for prax tests.

The real logger and json service run in every test, redirected under that
test's tmp_path; the consoles are pinned and the header's trigger recorded.
"""

import os
import tempfile

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import sys
import types
import pytest
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

# The real display: the two fixtures below pin and reset the consoles the
# product actually prints through.
from aipass.cli.apps.modules import display
from aipass.prax.apps.handlers.config import load as config_load
from aipass.prax.apps.handlers.monitoring import branch_detector, filesystem_handler
from aipass.prax.apps.handlers.registry import load as registry_load
from aipass.prax.apps.handlers.registry import save as registry_save
from aipass.prax.tests.support_test_filesystem_handler import _DOUBLES
from aipass.prax.tests.support_test_operations import _DASHBOARD_MODULES, _Screen

collect_ignore_glob = [".archive/*"]


# =============================================
# SYS.MODULES HYGIENE
# =============================================


@pytest.fixture(autouse=True)
def _resync_module_attrs() -> Generator[None, None, None]:
    """Keep sys.modules and parent-package attributes honest after module surgery.

    Ported from backup/trigger (the desync class devpulse fixed fleet-wide), but
    prax leaks in the OPPOSITE direction, so a straight port would not have cured
    it. Both directions are reconciled here:

      * backup's direction — sys.modules holds the real module while the parent
        package attribute still points at a throwaway twin. patch.dict restores
        the sys.modules DICT on exit and never the parent's ATTRIBUTE.
      * prax's direction — the mock is in sys.modules ITSELF, left by a raw
        ``sys.modules[name] = MagicMock()`` in a test helper with no patch.dict
        and no monkeypatch to undo it. Re-pointing the attribute at sys.modules
        would then propagate the mock rather than remove it.

    The second direction is the live CI red: a leaked MagicMock standing in for
    the ``handlers.config`` package makes ``import ...config.load as load_mod``
    resolve through the mock, because ``import x.y as z`` binds by walking parent
    ATTRIBUTES (with a sys.modules fallback) rather than by dict lookup. The test
    then calls ``load_log_config()`` on a mock and compares a MagicMock to 3.
    Which tests share a process decides who gets hit, so it is xdist- and
    order-dependent — Windows drew the short straw, and serial Linux stayed green.

    After every test: evict non-module entries that outlived their patch, point
    parent attributes back at the real sys.modules entry, and drop attributes
    whose module is no longer in sys.modules so the next import loads cleanly.

    Declared FIRST in this file on purpose. Autouse fixtures tear down in reverse
    setup order, so being first means running last — after monkeypatch has undone
    the deliberate mocks in mock_prax_infrastructure. Otherwise this fixture would
    treat that fixture's still-installed mocks as leaks.
    """
    yield

    # 1. Mocks that no patch.dict or monkeypatch ever restored.
    leaked = {
        n
        for n, m in sys.modules.items()
        if n.startswith("aipass") and m is not None and not isinstance(m, types.ModuleType)
    }
    # Evicting a package must take its submodules with it. A child left behind in
    # sys.modules without its parent is worse than the leak: ``import a.b.c`` finds
    # the child, skips importing the parent entirely, and then dies on the attribute
    # walk with "cannot import name 'b'".
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

    # 2. Parent attributes still aimed at a throwaway twin.
    for name, mod in snapshot:
        parent_name, _, leaf = name.rpartition(".")
        if not parent_name:
            continue
        parent = sys.modules.get(parent_name)
        if parent is not None and getattr(parent, leaf, mod) is not mod:
            setattr(parent, leaf, mod)

    # 3. Attributes whose module was evicted entirely — let the next import reload.
    for pkg_name, pkg in snapshot:
        for attr, value in list(vars(pkg).items()):
            if (
                isinstance(value, types.ModuleType)
                and getattr(value, "__name__", "") == f"{pkg_name}.{attr}"
                and f"{pkg_name}.{attr}" not in sys.modules
            ):
                delattr(pkg, attr)


# =============================================
# CONSOLE WIDTH AND COMMAND STATE
# =============================================


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Rich sizes an unpinned console on every print: 80 on POSIX and 79 on Windows
    under pytest's capture, the terminal's width under -s, COLUMNS when exported."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next.

    Declared above mock_prax_infrastructure so the reset runs after its redirects
    come out.
    """
    yield
    display.reset_command_state()


@pytest.fixture(autouse=True)
def header_fires_into_a_recorder(monkeypatch) -> MagicMock:
    """header() keeps the trigger it loaded in display._TRIGGER and fires
    cli_header_displayed through it; a real console would open a call on the live
    bus. Chosen by prax, leg 3, of the three cures: no file of cli is touched and
    no test can forget it."""
    recorder = MagicMock()
    monkeypatch.setattr(display, "_TRIGGER", recorder)
    monkeypatch.setattr(display, "_TRIGGER_LOADED", True)
    return recorder


# =============================================
# INFRASTRUCTURE MOCKS
# =============================================


@pytest.fixture(autouse=True)
def mock_prax_infrastructure(monkeypatch, tmp_path) -> Path:
    """The real logger and the real json handler, writing under this test's tmp_path.

    No stand-ins (prax, leg 13): AIPASS_TEST_LOG_DIR is the seam both already
    read on every call (system logs, module logs, each branch's json dir), and the
    path constants computed at import are pointed at the same root. A test that
    needs to see a log line reads the file there or uses caplog.

    Returns the root everything under test writes into.
    """
    root = tmp_path / "aipass_test_logs"
    json_dir = root / "prax" / "prax_json"
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(root))
    monkeypatch.setattr(config_load, "PRAX_JSON_DIR", json_dir)
    # Fixed at import to the git-ignored live prax_json, so a dev seat read its log
    # format and a clean CI checkout read the default (prax, PR #774).
    monkeypatch.setattr(config_load, "PRAX_LOGGER_CONFIG_FILE", json_dir / "prax_logger_config.json")
    monkeypatch.setattr(registry_load, "REGISTRY_FILE", json_dir / "prax_registry.json")
    monkeypatch.setattr(registry_save, "PRAX_JSON_DIR", json_dir)
    monkeypatch.setattr(registry_save, "REGISTRY_FILE", json_dir / "prax_registry.json")
    return root


# =============================================
# SHARED BY THE SPLIT TEST FILES
# =============================================


@pytest.fixture
def _branch_detector_fresh(monkeypatch):
    """Double branch_detector's collaborators where it binds them and empty its singleton.

    Replaces a re-import under a mocked Path, json.load and open: the module
    reads no file at import, so all the re-import gave was an empty singleton.

    Autouse in test_monitoring_handlers.py until its split (2026-10-08); the
    detector and external-project files each request it with a module pytestmark.
    """
    monkeypatch.setattr(branch_detector, "logger", MagicMock())
    monkeypatch.setattr(branch_detector, "json_handler", MagicMock())
    monkeypatch.setattr(branch_detector, "_detector_instance", None)


@pytest.fixture
def _filesystem_handler_doubled(monkeypatch):
    """filesystem_handler is bound at the top and never reloaded; each name it took
    from the event queue, the branch detector and the filters is doubled on it for
    one test, with its logger and json service (prax, leg 13: the raw sys.modules
    stubs of watchdog and three handlers were the import_site rows).

    Autouse in test_filesystem_handler.py until its split (2026-10-08); the four
    filesystem_handler files each request it with a module pytestmark, and read the
    doubles back through support_test_filesystem_handler._import_filesystem_handler.
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
    """What the reload under the conftest stubs used to give each test: a logger
    and a json service that write nothing (prax, leg 11).

    Autouse in test_operations.py until its split (2026-10-08); the four
    test_operations files each request it with a module pytestmark.
    """
    for module in _DASHBOARD_MODULES:
        for name in ("logger", "json_handler"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, MagicMock())


@pytest.fixture
def screen(capsys) -> _Screen:
    return _Screen(capsys)
