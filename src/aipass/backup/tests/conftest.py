"""Shared pytest fixtures for backup branch tests."""
import json
import pytest
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Generator
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
def sample_source_tree(tmp_path):
    """Creates a realistic source directory tree for backup testing."""
    source = tmp_path / "source"
    source.mkdir()

    # Create some files
    (source / "file1.txt").write_text("hello world", encoding="utf-8")
    (source / "file2.py").write_text("print('hello')", encoding="utf-8")

    # Nested structure
    sub = source / "subdir"
    sub.mkdir()
    (sub / "nested.json").write_text('{"key": "value"}', encoding="utf-8")
    (sub / "deep" / "deeper").mkdir(parents=True)
    (sub / "deep" / "deeper" / "bottom.txt").write_text("bottom", encoding="utf-8")

    return source


@pytest.fixture
def sample_backup_dir(tmp_path):
    """Creates a backup destination directory."""
    backup = tmp_path / "backup_dest"
    backup.mkdir()
    return backup


@pytest.fixture
def sample_test_data() -> dict:
    """Provides sample test data."""
    return {
        "test_key": "test_value",
        "sample_data": "example"
    }


@pytest.fixture
def mock_json_handler(monkeypatch):
    """Creates a mock json_handler that can be injected into modules."""
    mock = MagicMock()
    mock.log_operation = MagicMock(return_value=True)
    mock.ensure_module_jsons = MagicMock(return_value=True)
    mock.load_json = MagicMock(return_value={})
    mock.save_json = MagicMock(return_value=True)
    return mock


@pytest.fixture
def mock_backup_result():
    """Creates a mock BackupResult for testing operations."""
    result = MagicMock()
    result.files_checked = 0
    result.files_copied = 0
    result.files_added = 0
    result.files_skipped = 0
    result.files_deleted = 0
    result.errors = 0
    result.error_details = []
    result.warnings = []
    result.critical_errors = []
    result.success = True
    result.add_error = MagicMock()
    result.add_warning = MagicMock()
    return result
