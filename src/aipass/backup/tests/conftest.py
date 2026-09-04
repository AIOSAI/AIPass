# =================== AIPass ====================
# Name: conftest.py
# Description: Backup test configuration -- shared pytest fixtures
# Version: 1.2.0
# Created: 2026-06-12
# Modified: 2026-09-03
# =============================================

"""Backup test configuration -- ported from skills conftest pattern."""

import os
import tempfile

if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import logging  # noqa: E402
import sys  # noqa: E402
import types  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Generator  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402

BRANCH_MODULE = "aipass.backup"

HANDLER_PKG = f"{BRANCH_MODULE}.apps.handlers"

if HANDLER_PKG not in sys.modules:
    _stub = types.ModuleType(HANDLER_PKG)
    _handlers_dir = Path(__file__).resolve().parents[1] / "apps" / "handlers"
    _stub.__path__ = [str(_handlers_dir)]  # type: ignore[attr-defined]
    sys.modules[HANDLER_PKG] = _stub


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
def mock_infrastructure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect this branch's json writes into a temp dir, and silence logging.

    autouse on purpose: under DPLAN-0325 the shim's names write into the real
    ``backup_json/`` unless the seam is set, so a test that forgets to redirect
    pollutes the branch. The guard belongs on every test, not on the ones that
    remember. The env var at the top of this file covers import time; this
    narrows it to one directory PER TEST.

    Nothing is patched on the shim -- it has no attributes to patch, and that
    is the point. The service recomputes its directory on every call, so
    setting the variable here, after import, still takes effect. The sandbox is
    MEASURED off the shim rather than spelled out, so it cannot drift from what
    the service actually does. The same seam covers backup's own audit stream
    (``apps/handlers/audit/trail.py``), which recomputes its path per call too.

    The seam gets its OWN subdirectory rather than tmp_path itself. The service
    spells the sandbox ``<seam>/<branch>/<branch>_json``, so pointing the seam
    straight at tmp_path creates ``tmp_path/backup/`` in every single test --
    and this branch is NAMED backup, so a test building its own ``backup/``
    directory under tmp_path collided with the fixture rather than with
    anything it did (test_ignore_pathspec's mirror-cleanup pair, 2026-09-03).

    Returns:
        The sandbox directory the handler now writes into.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))

    logger_names = [
        BRANCH_MODULE,
        "aipass.prax.json",
    ]
    for logger_name in logger_names:
        log = logging.getLogger(logger_name)
        monkeypatch.setattr(log, "handlers", [logging.NullHandler()])

    from aipass.backup.apps.handlers.json import json_handler

    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


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
