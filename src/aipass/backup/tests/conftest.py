# =================== META ====================
# Name: conftest.py
# Description: Backup test configuration -- shared pytest fixtures
# Version: 1.3.0
# Created: 2026-06-12
# Modified: 2026-09-25
# =============================================

"""Backup test configuration -- ported from skills conftest pattern."""

import os
import tempfile

if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import logging
import sys
import types
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest

from aipass.backup.apps.handlers.drive import client as drive_client
from aipass.backup.apps.handlers.drive import upload as drive_upload
from aipass.backup.apps.handlers.json import json_handler
from aipass.cli.apps.modules import display

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

    The seam gets its OWN directory rather than tmp_path itself. The service
    spells the sandbox ``<seam>/<branch>/<branch>_json``, so pointing the seam
    straight at tmp_path creates ``tmp_path/backup/`` in every single test --
    and this branch is NAMED backup, so a test building its own ``backup/``
    directory under tmp_path collided with the fixture rather than with
    anything it did (test_ignore_pathspec's mirror-cleanup pair, 2026-09-03).

    And that directory sits BESIDE tmp_path, not inside it (2026-09-23). Until
    now the seam was ``tmp_path/_aipass_json_seam``, so the sandbox the fixture
    builds -- ``<seam>/backup/backup_json/`` plus the audit stream's
    ``<seam>/backup/logs/`` -- lived INSIDE the directory tests hand to the
    product as a project root. Any test that walked, counted or mirrored a bare
    tmp_path saw files the product never created and the test never wrote, and
    a count written against that total was measuring the fixture. A fixture
    that changes the answer to the question under test is a lie in the
    scaffolding, so the seam moved out: a sibling under the same per-test
    pytest directory, still unique per test, still swept up with it, but never
    inside a tree under measurement.

    Returns:
        The sandbox directory the handler now writes into.
    """
    seam = tmp_path.parent / f"{tmp_path.name}_aipass_json_seam"
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(seam))

    logger_names = [
        BRANCH_MODULE,
        "aipass.prax.json",
    ]
    for logger_name in logger_names:
        log = logging.getLogger(logger_name)
        monkeypatch.setattr(log, "handlers", [logging.NullHandler()])

    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Pin the product's consoles to one width for the whole run.

    Rich sizes an unpinned console on every print: 80 columns on POSIX and 79
    on Windows under pytest's capture, the terminal's width under -s, COLUMNS
    when it is exported. A line that wraps on one OS and not another turns a
    substring assertion into a coin toss (DPLAN-0354, test template v1 item 20).
    """
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    display.reset_command_state()


def _no_live_google(*args, **kwargs):
    """Stand where Google stands. A test that reaches the wire dies here instead."""
    raise RuntimeError("a test reached the live Google Drive edge")


@pytest.fixture(autouse=True)
def sealed_google_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seal both doors to the real account, and the media reader, before EVERY test.

    autouse and suite-wide on purpose. This fixture used to live inside
    test_drive_pipeline.py, where a file-level autouse reaches exactly one
    file -- so test_drive_mocked.py, which drives the same four drive_*
    modules, ran unsealed. ``drive_check``, ``drive_clear`` and ``drive_sync``
    reach a REAL Google account (drive_check's own 2026-08-13 comment records
    ``drive_check foo --help`` making a live auth), and in an unsealed file the
    dial happens BEFORE the assertion that would have failed the test: the
    account is touched either way, and the red only arrives afterwards.

    Exactly two calls can reach the live account --
    ``google_client.get_drive_service`` (the OAuth flow) and
    ``google_client.api_call_with_retry`` (every request) -- and both are bound
    as module attributes of ``handlers/drive/client.py`` at import time, so one
    monkeypatch on that one module closes both doors for the whole process.
    ``googleapiclient.http.MediaFileUpload`` opens the local file for a
    resumable upload, so it is replaced as well.

    A call that gets through RAISES rather than dials, so the seal is
    self-reporting: reaching the edge is a loud RuntimeError, never a quiet
    network round trip. test_drive_mocked.py pins that refusal directly.

    Both modules are bound at this file's top, which is the same object
    sys.modules hands the product: patching the attribute here is patching the
    name the product resolves at call time.
    """
    monkeypatch.setattr(drive_client, "get_drive_service", _no_live_google)
    monkeypatch.setattr(drive_client, "api_call_with_retry", _no_live_google)
    monkeypatch.setattr(drive_upload, "MediaFileUpload", MagicMock(name="MediaFileUpload"))


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
