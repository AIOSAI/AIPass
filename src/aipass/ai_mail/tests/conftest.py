
# ===================AIPASS====================
# META DATA HEADER
# Name: tests/conftest.py
# Date: 2025-11-08
# Version: 1.1.0
# Category: cortex/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.1.0 (2026-03-27): Added mock_logger, mock_json_handler fixtures
#   - v1.0.0 (2025-11-08): Initial implementation - Shared pytest fixtures
#
# CODE STANDARDS:
#   - Error handling: Use error handler system (apps/handlers/error/)
# =============================================

"""Shared pytest fixtures for ai_mail tests"""
import pytest
import shutil
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock


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
    return {
        "test_key": "test_value",
        "sample_data": "example"
    }


@pytest.fixture
def mock_logger(monkeypatch):
    """Mock the prax logger to prevent real log I/O during tests."""
    mock_log = MagicMock()
    return mock_log


@pytest.fixture
def mock_json_handler(monkeypatch):
    """Mock json_handler to prevent real JSON file operations during tests."""
    mock_json = MagicMock()
    mock_json.log_operation.return_value = True
    mock_json.ensure_module_jsons.return_value = True
    mock_json.load_json.return_value = None
    mock_json.save_json.return_value = True
    return mock_json
