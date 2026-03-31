# ===================AIPASS====================
# META DATA HEADER
# Name: conftest.py - The Commons test configuration
# Date: 2026-03-07
# Version: 1.0.0
# Category: commons/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-07): Initial creation (FPLAN-0411)
#
# CODE STANDARDS:
#   - Pytest fixtures for The Commons test suite
#   - Uses temporary database for test isolation
# =============================================

"""
The Commons - Test Configuration

Provides pytest fixtures for database setup, teardown,
and test isolation using temporary databases.
"""
import os
import tempfile

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

from pathlib import Path

import pytest

try:
    from aipass.prax.apps.modules.logger import system_logger as logger
except ImportError:
    import logging
    logger = logging.getLogger("commons.tests")


@pytest.fixture
def tmp_db_path(tmp_path):
    """
    Provide a temporary database path for test isolation.

    Each test gets its own fresh database file that is
    automatically cleaned up after the test completes.

    Yields:
        Path to temporary database file.
    """
    db_file = tmp_path / "test_commons.db"
    yield db_file


@pytest.fixture
def initialized_db(tmp_db_path):
    """
    Provide an initialized temporary database with schema and seed data.

    Creates a fresh database with all tables, default rooms,
    and room personalities. Closes the connection after the test.

    Yields:
        sqlite3.Connection to the initialized test database.
    """
    from commons.apps.handlers.database.db import init_db, close_db

    conn = init_db(db_path=tmp_db_path)
    yield conn
    close_db(conn)


@pytest.fixture
def sample_data():
    """
    Provide sample_data for tests that need representative data structures.

    Returns a dict with sample post, comment, and agent data
    that mirrors the commons database schema.
    """
    return {
        "post": {
            "title": "Test Post",
            "content": "This is a test post body.",
            "room": "general",
            "author": "TEST_AGENT",
        },
        "comment": {
            "content": "This is a test comment.",
            "post_id": 1,
            "author": "TEST_AGENT",
        },
        "agent": {
            "branch_name": "TEST_AGENT",
            "display_name": "Test Agent",
        },
    }
