# ===================AIPASS====================
# META DATA HEADER
# Name: conftest.py - Skills test configuration
# Date: 2026-03-07
# Version: 2.0.0
# Category: skills/tests
#
# CHANGELOG (Max 5 entries):
#   - v2.0.0 (2026-03-28): Added temp_dir, sample_data, mock_infrastructure,
#     mock_logger, mock_json_handler fixtures for test quality compliance
#   - v1.0.0 (2026-03-07): Initial implementation
#
# CODE STANDARDS:
#   - Adds skills root to sys.path for test imports
# =============================================

"""Skills test configuration."""
import os
import tempfile

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import importlib
import logging
import sys
import types
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest

# Add skills root to path for imports
skills_root = Path(__file__).parent.parent
if str(skills_root) not in sys.path:
    sys.path.insert(0, str(skills_root))


# ---------------------------------------------------------------------------
# Dynamic import for json_handler isolation
# ---------------------------------------------------------------------------

BRANCH_MODULE = "skills"

_handler_pkg = f"{BRANCH_MODULE}.apps.handlers"
_json_mod_path = f"{BRANCH_MODULE}.apps.handlers.json.json_handler"

# Ensure the handler package is importable
if _handler_pkg not in sys.modules:
    _stub = types.ModuleType(_handler_pkg)
    _handlers_dir = Path(__file__).resolve().parents[1] / "apps" / "handlers"
    _stub.__path__ = [str(_handlers_dir)]
    sys.modules[_handler_pkg] = _stub

_json_mod = importlib.import_module(_json_mod_path)


# ---------------------------------------------------------------------------
# JSON_DIR variable discovery
# ---------------------------------------------------------------------------

_JSON_DIR_ATTR: str | None = None
_JSON_DIR_CANDIDATES = [
    "SKILLS_JSON_DIR",
    "JSON_DIR",
    "BRANCH_JSON_DIR",
    "_JSON_DIR",
]

for _candidate in _JSON_DIR_CANDIDATES:
    if hasattr(_json_mod, _candidate):
        _JSON_DIR_ATTR = _candidate
        break


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def temp_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after."""
    test_dir = tmp_path / "test_workspace"
    test_dir.mkdir(parents=True, exist_ok=True)
    yield test_dir
    for child in test_dir.iterdir():
        if child.is_file():
            child.unlink()


@pytest.fixture()
def sample_data() -> dict:
    """Sample test data for JSON operations."""
    return {
        "config": {
            "module_name": "test_module",
            "version": "1.0.0",
            "config": {"max_log_entries": 50},
            "timestamp": "2026-03-28",
        },
        "data": {
            "module_name": "test_module",
            "created": "2026-03-28",
            "last_updated": "2026-03-28",
            "operations_total": 0,
            "operations_successful": 0,
            "operations_failed": 0,
        },
        "log": [
            {"timestamp": "2026-03-28T10:00:00", "operation": "test"}
        ],
    }


@pytest.fixture(autouse=True)
def mock_infrastructure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Autouse fixture that isolates JSON operations and silences logging.

    This fixture:
      1. Redirects the branch's JSON_DIR to tmp_path (test isolation)
      2. Patches the branch logger to a NullHandler (no console noise)
    """
    if _JSON_DIR_ATTR is not None:
        monkeypatch.setattr(_json_mod, _JSON_DIR_ATTR, tmp_path)

    logger_names = [
        f"aipass.{BRANCH_MODULE}",
        BRANCH_MODULE,
        f"{BRANCH_MODULE}.apps.handlers.json.json_handler",
    ]
    for logger_name in logger_names:
        log = logging.getLogger(logger_name)
        monkeypatch.setattr(log, "handlers", [logging.NullHandler()])


@pytest.fixture()
def mock_logger() -> MagicMock:
    """Standalone mock logger for tests that need to verify logging calls."""
    mock = MagicMock(spec=logging.Logger)
    mock.debug = MagicMock()
    mock.info = MagicMock()
    mock.warning = MagicMock()
    mock.error = MagicMock()
    mock.critical = MagicMock()
    return mock


@pytest.fixture()
def mock_json_handler() -> MagicMock:
    """Standalone mock json_handler for isolating from real file I/O."""
    handler = MagicMock()
    handler.load_json = MagicMock(return_value={})
    handler.save_json = MagicMock(return_value=True)
    handler.ensure_json_exists = MagicMock(return_value=True)
    handler.ensure_module_jsons = MagicMock(return_value=True)
    handler.get_json_path = MagicMock(return_value=Path("/tmp/mock.json"))
    handler.validate_json_structure = MagicMock(return_value=True)
    handler.log_operation = MagicMock(return_value=True)
    return handler


@pytest.fixture()
def reimport_after_mock(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Fixture demonstrating reimport_after_mock pattern.

    Patches sys.modules to inject a mock, then reimports the handler module
    so it picks up the mocked dependency. Useful for testing import-time behavior.
    """
    mock_mod = MagicMock()
    monkeypatch.setitem(sys.modules, f"{BRANCH_MODULE}.apps.handlers.json.json_handler", mock_mod)
    reimported = importlib.import_module(_json_mod_path)
    importlib.reload(reimported)
    return mock_mod
