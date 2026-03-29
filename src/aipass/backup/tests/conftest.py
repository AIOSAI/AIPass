"""Shared pytest fixtures for backup branch tests."""
import pytest
import shutil
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock


# ─── Infrastructure Mocking ─────────────────────────────

@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure before any backup imports.

    Mocks prax logger, cli console, and prevents real file I/O
    from json_handler's module-level operations.
    """
    mock_logger = MagicMock()
    mock_logger.info = MagicMock()
    mock_logger.warning = MagicMock()
    mock_logger.error = MagicMock()
    mock_logger.debug = MagicMock()

    mock_prax = MagicMock()
    mock_prax.logger = mock_logger

    mock_console = MagicMock()
    mock_cli = MagicMock()
    mock_cli.apps.modules.console = mock_console

    # Inject mocks into sys.modules
    monkeypatch.setitem(sys.modules, "aipass.prax", mock_prax)

    # Force re-import of backup modules so they pick up mocked prax
    backup_modules_to_reload = [
        key for key in sys.modules
        if key.startswith("aipass.backup.apps")
    ]
    for mod in backup_modules_to_reload:
        monkeypatch.delitem(sys.modules, mod, raising=False)


# ─── File System Fixtures ────────────────────────────────

@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after."""
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir)


@pytest.fixture
def mock_json_handler(monkeypatch):
    """Creates a mock json_handler that can be injected into modules."""
    mock = MagicMock()
    mock.log_operation = MagicMock(return_value=True)
    mock.ensure_module_jsons = MagicMock(return_value=True)
    mock.load_json = MagicMock(return_value={})
    mock.save_json = MagicMock(return_value=True)
    return mock
