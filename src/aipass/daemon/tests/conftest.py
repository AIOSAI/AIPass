# ===================AIPASS====================
# META DATA HEADER
# Name: tests/conftest.py
# Date: 2025-11-08
# Version: 1.0.0
# Category: daemon/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2025-11-08): Initial implementation - Shared pytest fixtures
#
# CODE STANDARDS:
#   - Error handling: Use error handler system (apps/handlers/error/)
# =============================================
#
# @Meta header not seedgo standards

"""Shared pytest fixtures for daemon tests"""

import os
import tempfile

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest
import shutil
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

from aipass.daemon.apps.handlers.json import json_handler

# Never discover out of .archive/: it holds verbatim disposal copies of the
# suites the one json service subsumed, and rglobbing into a dot-directory
# generates the dotted module name ...json..archive.json_handler, a SyntaxError
# that kills the file that walked there (DPLAN-0325, hooks' finding).
collect_ignore_glob = [".archive/*", "**/.archive/*"]


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect daemon's json writes into a temp dir.

    autouse on purpose: since DPLAN-0325 the handler is a shim over the one
    prax service, and the service resolves its directory from
    AIPASS_TEST_LOG_DIR on EVERY call. Unset, the nine names write into the
    real daemon_json/, so a test that forgets to redirect pollutes the branch.
    The guard belongs on every test, not on the ones that remember.

    Own subdirectory on purpose: the service spells the sandbox
    <seam>/<branch>/<branch>_json, so a seam AT tmp_path would create
    tmp_path/daemon/ in every test and collide with a test that builds a
    directory of its own branch's name.

    Returns:
        The sandbox directory the handler now writes into.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after"""
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir)


@pytest.fixture
def sample_test_data() -> dict:
    """Provides sample test data

    Customize this fixture for your module's needs
    """
    return {"test_key": "test_value", "sample_data": "example"}


@pytest.fixture()
def mock_json_handler() -> MagicMock:
    """Standalone mock json_handler for isolation tests."""
    handler = MagicMock()
    handler.load_json = MagicMock(return_value={})
    handler.save_json = MagicMock(return_value=True)
    handler.ensure_json_exists = MagicMock(return_value=True)
    handler.ensure_module_jsons = MagicMock(return_value=True)
    # gettempdir(), not a literal /tmp: this stand-in is only ever compared
    # against, never opened, but a POSIX literal is still a POSIX literal and
    # the fleet runs a Windows job.
    handler.get_json_path = MagicMock(return_value=Path(tempfile.gettempdir()) / "mock.json")
    handler.validate_json_structure = MagicMock(return_value=True)
    handler.log_operation = MagicMock(return_value=True)
    return handler
