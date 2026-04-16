# =================== AIPass ====================
# Name: test_conftest_template.py
# Description: Universal conftest.py Test Fixtures Template
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""
Universal conftest.py Template

Copy this file to any AIPass branch's tests/ directory as conftest.py.
Change BRANCH_MODULE below.

Provides standard fixtures:
  - temp_test_dir: tmp_path-based isolated directory with cleanup
  - sample_test_data: reusable dict of sample data
  - mock_infrastructure: autouse fixture that patches logger + json_handler
  - mock_logger: standalone mock logger fixture
  - mock_json_handler: standalone mock json_handler fixture

These fixtures establish a consistent test environment across all branches.
"""

import importlib
import logging
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ============ BRANCH CONFIG ============
# Change these two lines when deploying to a branch:
BRANCH_MODULE = "seedgo"  # e.g. "prax", "drone", "backup", "cli", etc.
# For commons: "commons" (import path is different: aipass -> just commons)
# For skills: "skills" (import path is different: aipass -> just skills)
# =======================================

# ---------------------------------------------------------------------------
# Dynamic import with cross-branch guard bypass
# ---------------------------------------------------------------------------

if BRANCH_MODULE in ("commons", "skills"):
    _handler_pkg = f"{BRANCH_MODULE}.apps.handlers"
    _json_mod_path = f"{BRANCH_MODULE}.apps.handlers.json.json_handler"
else:
    _handler_pkg = f"aipass.{BRANCH_MODULE}.apps.handlers"
    _json_mod_path = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"

if _handler_pkg not in sys.modules:
    _stub = types.ModuleType(_handler_pkg)
    if BRANCH_MODULE in ("commons", "skills"):
        _handlers_dir = Path(__file__).resolve().parents[3] / BRANCH_MODULE / "apps" / "handlers"
    else:
        _handlers_dir = Path(__file__).resolve().parents[3] / "aipass" / BRANCH_MODULE / "apps" / "handlers"
    _stub.__path__ = [str(_handlers_dir)]
    sys.modules[_handler_pkg] = _stub

_json_mod = importlib.import_module(_json_mod_path)


# ---------------------------------------------------------------------------
# JSON_DIR variable discovery (same pattern as json_handler template)
# ---------------------------------------------------------------------------

_JSON_DIR_ATTR: str | None = None
_JSON_DIR_CANDIDATES = [
    f"{BRANCH_MODULE.upper()}_JSON_DIR",
    "JSON_DIR",
    "BRANCH_JSON_DIR",
    f"{BRANCH_MODULE}_json",
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
def temp_test_dir(tmp_path: Path):
    """Provide a temporary directory for test isolation.

    Yields the tmp_path directory. Cleanup is handled automatically by
    pytest's tmp_path mechanism, but this fixture provides a named
    semantic entry point for branch tests.
    """
    test_dir = tmp_path / "test_workspace"
    test_dir.mkdir(parents=True, exist_ok=True)
    yield test_dir
    # Cleanup: tmp_path is automatically removed by pytest after the test
    # session. Explicit cleanup here handles any branch-specific teardown
    # that may be needed.
    for child in test_dir.iterdir():
        if child.is_file():
            child.unlink()


@pytest.fixture()
def sample_test_data() -> dict:
    """Provide a reusable sample data dictionary for tests.

    Returns a dict with standard AIPass data structure keys
    (created, last_updated) plus sample entries that tests can
    use for validation, serialization, and round-trip checks.
    """
    return {
        "created": "2026-01-01",
        "last_updated": "2026-01-15",
        "entries": [
            {"id": 1, "name": "alpha", "status": "active"},
            {"id": 2, "name": "beta", "status": "pending"},
        ],
        "metadata": {
            "source": "test_fixture",
            "version": "1.0.0",
        },
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

    Applied automatically to every test in the directory.
    """
    # Isolate JSON directory
    if _JSON_DIR_ATTR is not None:
        original_value = getattr(_json_mod, _JSON_DIR_ATTR)
        if isinstance(original_value, str):
            monkeypatch.setattr(_json_mod, _JSON_DIR_ATTR, str(tmp_path))
        else:
            monkeypatch.setattr(_json_mod, _JSON_DIR_ATTR, tmp_path)

    # Silence branch logger
    logger_names = [
        f"aipass.{BRANCH_MODULE}",
        BRANCH_MODULE,
        f"{BRANCH_MODULE}.apps.handlers.json.json_handler",
    ]
    for logger_name in logger_names:
        logger = logging.getLogger(logger_name)
        monkeypatch.setattr(logger, "handlers", [logging.NullHandler()])


@pytest.fixture()
def mock_logger() -> MagicMock:
    """Provide a standalone mock logger for tests that need to verify logging calls.

    Returns a MagicMock with standard logging method stubs (debug, info,
    warning, error, critical). Use this when you need to assert that
    specific log messages were emitted.

    Example:
        def test_something(mock_logger, monkeypatch):
            monkeypatch.setattr(my_module, "logger", mock_logger)
            my_module.do_thing()
            mock_logger.info.assert_called_once()
    """
    logger = MagicMock(spec=logging.Logger)
    logger.debug = MagicMock()
    logger.info = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    logger.critical = MagicMock()
    return logger


@pytest.fixture()
def mock_json_handler() -> MagicMock:
    """Provide a standalone mock json_handler for tests that need to isolate
    from real file I/O.

    Returns a MagicMock with stubs for all standard json_handler functions.
    Useful when testing modules that CALL json_handler but you want to
    verify the calls without touching the filesystem.

    Example:
        def test_my_module(mock_json_handler, monkeypatch):
            monkeypatch.setattr(my_module, "json_handler", mock_json_handler)
            mock_json_handler.load_json.return_value = {"key": "val"}
            result = my_module.process()
            mock_json_handler.save_json.assert_called_once()
    """
    handler = MagicMock()
    handler.load_json = MagicMock(return_value={})
    handler.save_json = MagicMock(return_value=True)
    handler.ensure_json_exists = MagicMock(return_value=True)
    handler.ensure_module_jsons = MagicMock(return_value=True)
    handler.get_json_path = MagicMock(return_value=Path("/tmp/mock.json"))
    handler.validate_json_structure = MagicMock(return_value=True)
    handler.log_operation = MagicMock(return_value=True)
    return handler
