# =================== AIPass ====================
# Name: conftest.py
# Description: Backup test configuration -- shared pytest fixtures
# Version: 1.1.0
# Created: 2026-06-12
# Modified: 2026-08-08
# =============================================

"""Backup test configuration -- ported from skills conftest pattern."""

import os
import tempfile

if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import importlib  # noqa: E402
import logging  # noqa: E402
import sys  # noqa: E402
import types  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Generator  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

BRANCH_MODULE = "aipass.backup"

HANDLER_PKG = f"{BRANCH_MODULE}.apps.handlers"
JSON_MOD_PATH = f"{BRANCH_MODULE}.apps.handlers.json.json_handler"

if HANDLER_PKG not in sys.modules:
    _stub = types.ModuleType(HANDLER_PKG)
    _handlers_dir = Path(__file__).resolve().parents[1] / "apps" / "handlers"
    _stub.__path__ = [str(_handlers_dir)]  # type: ignore[attr-defined]
    sys.modules[HANDLER_PKG] = _stub

_json_mod = importlib.import_module(JSON_MOD_PATH)

_JSON_DIR_ATTR: str | None = None
_JSON_DIR_CANDIDATES = [
    "BACKUP_JSON_DIR",
    "JSON_DIR",
    "BRANCH_JSON_DIR",
    "_JSON_DIR",
]

for _candidate in _JSON_DIR_CANDIDATES:
    if hasattr(_json_mod, _candidate):
        _JSON_DIR_ATTR = _candidate
        break


@pytest.fixture(autouse=True)
def _resync_module_attrs() -> Generator[None, None, None]:
    """Keep parent-package attributes honest after sys.modules surgery.

    _fresh_import (test_drive_pipeline) and _load_module_fresh
    (test_cli_routing) delete modules from sys.modules and re-import them
    under mocked dependencies. patch.dict restores the sys.modules DICT at
    exit, but never the parent package's ATTRIBUTE, which keeps pointing at
    the throwaway twin — one that may lack submodule attributes entirely when
    they resolved to sys.modules mocks during its import. The next test then
    resolves two different objects for one dotted name: mock.patch walks the
    stale attribute (AttributeError: module ...drive has no attribute
    'client') while importlib walks sys.modules. Only surfaces when an
    unlucky xdist worker runs a polluting module before a victim — CI-only
    red, invisible in serial runs.

    After every test: point parent attributes back at the sys.modules entry,
    and drop attributes whose module was evicted from sys.modules entirely so
    the next import performs a clean load.
    """
    yield
    snapshot = [(n, m) for n, m in sys.modules.items() if n.startswith("aipass") and m is not None]
    for name, mod in snapshot:
        parent_name, _, leaf = name.rpartition(".")
        if not parent_name:
            continue
        parent = sys.modules.get(parent_name)
        if parent is not None and getattr(parent, leaf, mod) is not mod:
            setattr(parent, leaf, mod)
    for pkg_name, pkg in snapshot:
        for attr, value in list(vars(pkg).items()):
            if (
                isinstance(value, types.ModuleType)
                and getattr(value, "__name__", "") == f"{pkg_name}.{attr}"
                and f"{pkg_name}.{attr}" not in sys.modules
            ):
                delattr(pkg, attr)


@pytest.fixture()
def temp_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after.

    Uses tmp_path (pytest builtin) and yields a temp_dir subdirectory.
    Cleanup via rmtree is handled by pytest's tmp_path automatically.
    """
    test_dir = tmp_path / "test_workspace"
    test_dir.mkdir(parents=True, exist_ok=True)
    yield test_dir


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
        "log": [{"timestamp": "2026-03-28T10:00:00", "operation": "test"}],
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
    so it picks up the mocked dependency. Useful for testing import-time
    behavior.  Uses importlib.reload to force re-execution of module-level code.
    """
    mock_mod = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        f"{BRANCH_MODULE}.apps.handlers.json.json_handler",
        mock_mod,
    )
    reimported = importlib.import_module(JSON_MOD_PATH)
    importlib.reload(reimported)
    return mock_mod
