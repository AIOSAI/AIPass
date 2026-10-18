# =================== AIPass ====================
# Name: conftest.py
# Description: The Commons test configuration
# Version: 1.2.0
# Created: 2026-03-07
# Modified: 2026-10-17
# =============================================

"""The Commons - Test Configuration"""

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

# Must be set before any prax import: the logger reads it at initialization.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")


import logging

import pytest

logger = logging.getLogger(__name__)

try:
    from aipass.prax.apps.modules.logger import system_logger as logger
except ImportError:
    logger.warning("[conftest] prax logger unavailable — using stdlib logging")

from aipass.cli.apps.modules import display
from aipass.cli.apps.modules.display import reset_command_state
from aipass.commons.apps.handlers.json import json_handler
from aipass.commons.apps.modules.database import close_db, init_db

# .archive/ holds old suite copies; collecting a dot-directory yields an invalid dotted module name.
collect_ignore_glob = [".archive/*", "**/.archive/*"]


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect commons's json writes into a temp dir; autouse, since unset they hit the real commons_json/.

    A subdirectory, not tmp_path itself: the sandbox is <seam>/commons/..., which would collide with tests' own dirs.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Pin the product's consoles to one width: Rich's unpinned width differs per platform and terminal."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


@pytest.fixture(autouse=True)
def _clear_command_state():
    """Clear the CLI's process-level failure flag around every test, since pytest shares one process."""
    reset_command_state()
    yield
    reset_command_state()


@pytest.fixture(scope="session")
def _template_db_path(tmp_path_factory):
    """Build the initialized schema+seed DB once per session."""
    template = tmp_path_factory.mktemp("template") / "template_commons.db"
    conn = init_db(db_path=template)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    close_db(conn)
    return template


@pytest.fixture
def initialized_db(_template_db_path, tmp_path):
    """Provide an initialized temporary database, copied from the session template."""
    db_file = tmp_path / "test_commons.db"
    shutil.copy2(str(_template_db_path), str(db_file))

    conn = sqlite3.connect(str(db_file), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA synchronous = OFF")
    yield conn
    conn.close()
