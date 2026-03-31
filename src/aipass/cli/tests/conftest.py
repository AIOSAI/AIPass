# =================== AIPass ====================
# Name: tests/conftest.py
# Description: Shared pytest fixtures for CLI branch tests
# Version: 3.0.0
# Created: 2026-03-07
# Modified: 2026-03-27
# =============================================

"""Shared pytest fixtures for CLI tests."""
import os
import tempfile

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest


@pytest.fixture
def sample_data():
    """Reusable sample test data for CLI module tests."""
    return {
        "module_name": "test_module",
        "version": "1.0.0",
        "config": {"max_log_entries": 100},
        "created": "2026-01-01",
        "last_updated": "2026-01-01",
    }


@pytest.fixture(autouse=True)
def _ensure_test_isolation():
    """Auto-applied fixture ensuring clean state between tests."""
    yield
    # teardown: no shared state to clean up currently
