# ===================AIPASS====================
# META DATA HEADER
# Name: tests/conftest.py
# Date: 2025-11-08
# Version: 1.0.0
# Category: spawn/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2025-11-08): Initial implementation - Shared pytest fixtures
#
# CODE STANDARDS:
#   - Error handling: Use error handler system (apps/handlers/error/)
# =============================================

"""Shared pytest fixtures for aipass tests."""

import pytest
import shutil
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch


@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after."""
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir)


@pytest.fixture
def sample_test_data() -> dict:
    """Provides sample test data."""
    return {"test_key": "test_value", "sample_data": "example"}


@pytest.fixture
def mock_json_handler():
    """Mock json_handler with functional load_path but stubbed logging.

    Use when tests need real file I/O via load_path but want to
    suppress log_operation and ensure_module_jsons side effects.
    """
    with (
        patch("aipass.aipass.apps.handlers.json.json_handler.log_operation") as mock_log,
        patch(
            "aipass.aipass.apps.handlers.json.json_handler.ensure_module_jsons",
            return_value=True,
        ) as mock_ensure,
    ):
        mock = MagicMock()
        mock.log_operation = mock_log
        mock.ensure_module_jsons = mock_ensure
        yield mock
