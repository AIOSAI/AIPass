# =================== AIPass ====================
# Name: tests/conftest.py
# Description: Shared pytest fixtures for CLI branch tests
# Version: 3.0.0
# Created: 2026-03-07
# Modified: 2026-03-27
# =============================================

"""Shared pytest fixtures for CLI tests."""

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
