# ===================AIPASS====================
# META DATA HEADER
# Name: tests/conftest.py
# Date: 2025-11-08
# Version: 2.0.0
# Category: api/tests
#
# CHANGELOG (Max 5 entries):
#   - v2.0.0 (2026-03-27): Added mock_infrastructure, mock_logger,
#     mock_json_handler fixtures for test quality compliance
#   - v1.0.0 (2025-11-08): Initial implementation - Shared pytest fixtures
#
# CODE STANDARDS:
#   - Error handling: Use error handler system (apps/handlers/error/)
# =============================================

"""Shared pytest fixtures for api tests"""

import os
import tempfile

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import importlib
import logging
import sys
import threading
import types
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest


# ============ BRANCH CONFIG ============
BRANCH_MODULE = "api"
# =======================================

# ---------------------------------------------------------------------------
# Dynamic import for json_handler isolation
# ---------------------------------------------------------------------------

_handler_pkg = f"aipass.{BRANCH_MODULE}.apps.handlers"
_json_mod_path = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"

if _handler_pkg not in sys.modules:
    _stub = types.ModuleType(_handler_pkg)
    _handlers_dir = Path(__file__).resolve().parents[3] / "aipass" / BRANCH_MODULE / "apps" / "handlers"
    _stub.__path__ = [str(_handlers_dir)]
    sys.modules[_handler_pkg] = _stub

_json_mod = importlib.import_module(_json_mod_path)


# Never discover out of .archive/: it holds verbatim disposal copies of the
# suites the one json service subsumed, and rglobbing into a dot-directory
# generates the dotted module name ...json..archive.json_handler, a SyntaxError
# that kills the file that walked there (DPLAN-0325, hooks' finding).
collect_ignore_glob = [".archive/*", "**/.archive/*"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def temp_test_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after"""
    test_dir = tmp_path / "test_workspace"
    test_dir.mkdir(parents=True, exist_ok=True)
    yield test_dir
    for child in test_dir.iterdir():
        if child.is_file():
            child.unlink()


@pytest.fixture()
def sample_test_data() -> dict:
    """Provides sample test data"""
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
) -> Path:
    """Autouse fixture that isolates JSON operations and silences logging.

    This fixture:
      1. Redirects the branch's json writes into a temp dir (test isolation)
      2. Patches the branch logger to a NullHandler (no console noise)

    Redirected through the fleet seam, not by patching a module attribute.
    It used to search the handler for API_JSON_DIR / JSON_DIR / BRANCH_JSON_DIR
    / _JSON_DIR and monkeypatch whichever it found — and, finding none, do
    NOTHING and say nothing. Since DPLAN-0325 the handler is a shim over the
    one prax service, which holds no directory constant at all and resolves
    its directory from AIPASS_TEST_LOG_DIR on EVERY call, so the search would
    have gone silently empty and let the whole suite write into the real
    api_json/.

    Own subdirectory on purpose: the service spells the sandbox
    <seam>/<branch>/<branch>_json, so a seam AT tmp_path would create
    tmp_path/api/ in every test and collide with a test that builds a
    directory of its own branch's name.

    Deliberately does NOT create the sandbox. It is autouse over 1560 tests,
    most of which never touch json at all, and an eager mkdir puts a directory
    in every one of their tmp_paths — measured: it turned
    test_the_staged_file_does_not_survive_a_failed_write red, a test that
    asserts its tmp_path is empty after a failed atomic write and was right to.
    The service builds the directory chain on the first call that needs it
    (pinned by test_auto_creates_directory), so nothing is lost by waiting.

    Returns:
        The sandbox directory the handler will write into. May not exist yet.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = _json_mod.get_json_path("probe", "config").parent

    logger_names = [
        f"aipass.{BRANCH_MODULE}",
        BRANCH_MODULE,
        f"{BRANCH_MODULE}.apps.handlers.json.json_handler",
    ]
    for logger_name in logger_names:
        log = logging.getLogger(logger_name)
        monkeypatch.setattr(log, "handlers", [logging.NullHandler()])

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


@pytest.fixture()
def mock_json_handler() -> MagicMock:
    """Standalone mock json_handler for isolating from real file I/O."""
    handler = MagicMock()
    handler.load_json = MagicMock(return_value={})
    handler.save_json = MagicMock(return_value=True)
    handler.ensure_json_exists = MagicMock(return_value=True)
    handler.ensure_module_jsons = MagicMock(return_value=True)
    # gettempdir(), not a literal /tmp: this stand-in is only ever compared
    # against, never opened, but a POSIX literal is still a POSIX literal and
    # the fleet runs a Windows job.
    handler.get_json_path = MagicMock(return_value=Path(tempfile.gettempdir()) / "mock.json")
    handler.validate_json_structure = MagicMock(return_value=True)
    handler.log_operation = MagicMock(return_value=True)
    return handler


@pytest.fixture(autouse=True)
def _no_fleet_cache_between_tests() -> Generator[None, None, None]:
    """
    Clear the fleet snapshot cache around every test (DPLAN-0305).

    read_snapshot caches @baud's envelope for ~1.5s and coalesces concurrent
    callers onto one exec. That is right in a server and WRONG across tests: a
    case that patches subprocess and counts execs would count the previous
    case's cached answer instead, and pass while measuring nothing. Cleared
    both sides so neither the test nor its neighbour can inherit one.

    Silently skipped when the [host] extra is absent — this fixture is autouse
    for the whole suite, so it must never be the reason a run cannot collect.
    """
    try:
        from aipass.api.apps.handlers.host import fleet as _fleet
    except Exception:  # pragma: no cover - only when the extra is missing
        yield
        return

    _fleet.reset_snapshot_cache()
    yield
    _fleet.reset_snapshot_cache()


@pytest.fixture(autouse=True)
def _no_remembered_git_refusals_between_tests() -> Generator[None, None, None]:
    """
    Forget every remembered git refusal around each test (@trigger, 2026-08-19).

    The git lane keeps a could-not-read answer for 60s so a phone polling every
    5 seconds stops re-spawning drone at a root that cannot authenticate. Right
    in a server and WRONG across tests, for the same reason as the fleet cache
    above and then some: 60s outlives an entire suite run, so ONE test that
    provokes a refusal would silence every later test on that lane — and they
    would pass, because a remembered refusal raises exactly what a fresh one
    does. Cleared both sides.

    Silently skipped when the [host] extra is absent — this fixture is autouse
    for the whole suite, so it must never be the reason a run cannot collect.
    """
    try:
        from aipass.api.apps.handlers.host import refusals as _refusals
    except Exception:  # pragma: no cover - only when the extra is missing
        yield
        return

    _refusals._reset_refusals()
    yield
    _refusals._reset_refusals()


@pytest.fixture(autouse=True)
def _no_leaked_pump_reservations() -> Generator[None, None, None]:
    """
    Give the attach lane's thread count back after every test (DPLAN-0305).

    The socket pump has a real cap now, and a spawned PTY holds one slot until
    its session hangs up. Several tests in this suite spawn one and never do —
    correctly, they are testing the spawn, not the lifecycle — so the count
    only ever climbs across a run and would eventually refuse terminals to
    tests that never took one. Measured: 5 slots held by the end of a full run.

    PRODUCTION IS NOT PAPERED OVER BY THIS. The release is pinned where it
    belongs — _pump's finally always hangs up (test_the_pump_always_hangs_up),
    hangup always releases, and a failed spawn releases too, each proven by a
    mutation. This only stops one test's leftovers from being another's cap.
    """
    try:
        from aipass.api.apps.handlers.host import attach as _attach
    except Exception:  # pragma: no cover - only when the extra is missing
        yield
        return

    yield
    _attach._PUMP_SLOTS = threading.BoundedSemaphore(_attach.PUMP_WORKERS)
