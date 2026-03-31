# =================== AIPass ====================
# Name: conftest.py
# Description: Shared pytest fixtures for prax tests
# Version: 2.0.0
# Created: 2025-11-08
# Modified: 2026-03-24
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
import pytest
from unittest.mock import MagicMock

collect_ignore_glob = [".archive/*"]


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
