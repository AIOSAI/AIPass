# =================== AIPass ====================
# Name: conftest.py
# Description: Shared pytest fixtures for prax tests
# Version: 2.1.0
# Created: 2025-11-08
# Modified: 2026-08-09
# =============================================

"""Shared pytest fixtures for prax tests.

Provides infrastructure mocking so test modules can import prax code
without triggering real logging, file watching, or CLI dependencies.
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
from typing import Generator
from unittest.mock import MagicMock

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
# INFRASTRUCTURE MOCKS
# =============================================


@pytest.fixture(autouse=True)
def mock_prax_infrastructure(monkeypatch):
    """Mock heavy prax infrastructure before any prax imports.

    Patches sys.modules so that importing prax modules doesn't trigger
    real logging setup, CLI initialization, or json_handler file I/O.
    """
    # Mock prax logger module
    mock_logger_mod = MagicMock()
    mock_logger = MagicMock()
    mock_logger.info = MagicMock()
    mock_logger.warning = MagicMock()
    mock_logger.error = MagicMock()
    mock_logger.debug = MagicMock()
    mock_logger_mod.system_logger = mock_logger
    mock_logger_mod.get_direct_logger = MagicMock(return_value=mock_logger)
    mock_logger_mod.get_system_logger = MagicMock(return_value=mock_logger)
    mock_logger_mod.DirectLogger = MagicMock
    mock_logger_mod.SystemLogger = MagicMock

    # Mock json_handler
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    mock_json_mod = MagicMock()
    mock_json_mod.json_handler = mock_json_handler

    # Mock CLI modules
    mock_cli = MagicMock()
    mock_console = MagicMock()
    mock_console.print = MagicMock()
    mock_cli.console = mock_console
    mock_cli.header = MagicMock()
    mock_cli.error = MagicMock()
    mock_cli.warning = MagicMock()

    # Inject mocks into sys.modules
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules.logger", mock_logger_mod)
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.handlers.json", mock_json_mod)
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.handlers.json.json_handler", mock_json_handler)
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", mock_cli)

    # Store mocks for test access
    class Mocks:
        logger = mock_logger
        json_handler = mock_json_handler
        console = mock_console
        cli = mock_cli

    return Mocks
