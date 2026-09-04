"""Shared pytest fixtures for drone tests."""

import os
import tempfile

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest

from aipass.drone.apps.handlers.json import json_handler

# Never discover out of .archive/: it holds verbatim disposal copies (the old
# handler's tests, the DPLAN-0059 stamp trio, the json-dir seam suite) that must
# not be collected or rglob-walked into dotted module names (DPLAN-0325, spec 4c).
collect_ignore_glob = [".archive/*", "**/.archive/*"]


@pytest.fixture(autouse=True)
def _clean_identity_dedupe() -> Generator[None, None, None]:
    """Give every test a fresh caller-identity dedupe set.

    router_handler suppresses repeated identity messages for the life of the
    PROCESS, and pytest is one process. Without this, whether a test sees its
    log line depends on which tests ran before it — the exact order-dependent
    flake that only surfaces when someone runs a single test in isolation.

    Reaches the module-private set on purpose. Production never needs to forget
    what it has already logged, so exporting a reset() just to serve this
    fixture would put a test-only function in the shipped API.
    """
    from aipass.drone.apps.handlers import router_handler

    router_handler._LOGGED_IDENTITY_SIGNATURES.clear()
    yield
    router_handler._LOGGED_IDENTITY_SIGNATURES.clear()


@pytest.fixture(autouse=True)
def _isolate_deletion_log(tmp_path: Path) -> Generator[None, None, None]:
    """Point the deletion record at tmp for every test.

    Without this, any test that exercises a delete path writes a real record
    into the live project's ``.ai_central/deletions.jsonl`` — the suite would
    quietly forge entries in the fleet's audit trail, which is worse than the
    usual test-pollution because the whole value of that file is that its
    contents happened.
    """
    os.environ["AIPASS_DELETION_LOG"] = str(tmp_path / "deletions.jsonl")
    yield
    os.environ.pop("AIPASS_DELETION_LOG", None)


@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after."""
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir)


OWNER_REGISTRY_ID = "test-registry-0000-0000"


def make_owner_project(
    root: Path,
    *,
    branch: str = "devpulse",
    registry_name: str = "AIPASS_REGISTRY.json",
    citizen_class: str = "manager",
    owner: bool = True,
    registry_id: str = OWNER_REGISTRY_ID,
    passport_registry_id: str | None = None,
    branch_dir: Path | None = None,
    record_path: str | None = None,
) -> Path:
    """Mint a project in which *branch* genuinely holds owner-tier, and return its home.

    Owner-tier is earned from four independent facts (DPLAN-0281), so a fixture
    that forges only a branch name no longer proves anything. This writes all
    four — manager class, matching tenancy, owner flag, recorded path — and every
    keyword exists so a test can break exactly ONE of them and watch the gate bite.

    Args:
        branch_dir: where the passport lives; defaults to *root*.
        record_path: what the registry records as the branch path. Defaults to
            the real branch_dir; pass a different value to test path-binding, or
            a relative string to exercise external-project style registries.
    """
    home = branch_dir if branch_dir is not None else root
    home.mkdir(parents=True, exist_ok=True)

    registry = {
        "metadata": {"id": registry_id, "name": "TEST-PROJECT", "version": "1.0.0"},
        "branches": [
            {
                "name": branch,
                "path": record_path if record_path is not None else str(home),
                "email": f"@{branch}",
                "status": "active",
                "owner": owner,
            }
        ],
    }
    (root / registry_name).write_text(json.dumps(registry, indent=2), encoding="utf-8")

    trinity = home / ".trinity"
    trinity.mkdir(parents=True, exist_ok=True)
    passport = {
        "branch_info": {"branch_name": branch},
        "identity": {"name": branch, "citizen_class": citizen_class},
        "citizenship": {
            "registered": True,
            "registry_id": passport_registry_id if passport_registry_id is not None else registry_id,
        },
    }
    (trinity / "passport.json").write_text(json.dumps(passport, indent=2), encoding="utf-8")
    return home


@pytest.fixture
def sample_registry(temp_test_dir: Path) -> Path:
    """Create a sample AIPASS_REGISTRY.json for testing."""
    registry = {
        "metadata": {"version": "1.0.0"},
        "branches": [
            {
                "name": "TEST_BRANCH",
                "path": str(temp_test_dir / "test_branch"),
                "profile": "library",
                "description": "Test branch",
                "email": "@test_branch",
                "status": "active",
            }
        ],
    }
    registry_path = temp_test_dir / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps(registry, indent=2))
    return registry_path


@pytest.fixture()
def sample_data() -> dict:
    """Provide reusable sample data dict with required keys."""
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


@pytest.fixture()
def mock_logger() -> MagicMock:
    """Standalone mock logger for testing logging calls."""
    mock = MagicMock(spec=logging.Logger)
    mock.debug = MagicMock()
    mock.info = MagicMock()
    mock.warning = MagicMock()
    mock.error = MagicMock()
    mock.critical = MagicMock()
    return mock


@pytest.fixture()
def mock_json_handler() -> MagicMock:
    """Standalone mock json_handler for isolation tests."""
    handler = MagicMock()
    handler.load_json = MagicMock(return_value={})
    handler.save_json = MagicMock(return_value=True)
    handler.ensure_json_exists = MagicMock(return_value=True)
    handler.ensure_module_jsons = MagicMock(return_value=True)
    handler.get_json_path = MagicMock(return_value=Path("/tmp/mock.json"))
    handler.validate_json_structure = MagicMock(return_value=True)
    handler.log_operation = MagicMock(return_value=True)
    return handler


# ---------------------------------------------------------------------------
# The deletable-cwd marker
# ---------------------------------------------------------------------------

DELETABLE_CWD_MARKER = "deletable_cwd"

WINDOWS_CWD_REASON = (
    "This test builds its world by deleting the directory the process stands in. "
    "Windows holds the current directory open without delete sharing, so rmtree(cwd) "
    "raises PermissionError WinError 32 and the directory is never removed — the RECIPE "
    "is unavailable there, not the STATE. A disconnected share or an ejected volume still "
    "leaves a live Windows process whose getcwd() raises, so the guards themselves stay "
    "pinned on every OS by the patched-Path.cwd construction (tests/test_no_cwd_sweep.py "
    "and the portable siblings beside each skipped test). What Windows loses is only the "
    "end-to-end half: that a real deletion actually produces the state."
)


def pytest_configure(config):
    """Register the marker here rather than in pytest.ini.

    The composed CI run loads this suite from the repository root with a
    different inifile, so a marker declared in drone's own pytest.ini would be
    unknown there — and --strict-markers turns an unknown marker into a
    collection error. A conftest travels with the tests that use it.
    """
    config.addinivalue_line(
        "markers",
        f"{DELETABLE_CWD_MARKER}: needs a process to delete the directory it stands in (POSIX only)",
    )


def pytest_collection_modifyitems(config, items):
    """Skip deletable-cwd tests on Windows only, and say the whole reason."""
    if sys.platform != "win32":
        return
    skip = pytest.mark.skip(reason=WINDOWS_CWD_REASON)
    for item in items:
        if DELETABLE_CWD_MARKER in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect drone's json writes into a temp dir.

    autouse=True on purpose: drone's handler is a shim that binds the fleet json
    service (DPLAN-0325), whose names write into the real drone_json/ unless the
    seam is set, so a test that forgets to redirect pollutes the branch. The
    guard belongs on every test, not on the ones that remember. Measured before
    this existed: 4189 of this branch's 7652 audit-tests hygiene records were
    these writes.

    The service recomputes its directory on every call, so setting the variable
    here — after import — still takes effect. That call-time resolution is the
    whole point, and it is what the archived test_json_dir_seam.py pinned when
    the resolution was drone's own: a value captured at import cannot be
    redirected by a conftest that runs afterwards. The property now belongs to
    the service and is pinned once for the fleet by seedgo's contract.

    The sandbox is MEASURED off the shim rather than spelled out, so it cannot
    drift from what the service does.

    Returns:
        The sandbox directory the handler now writes into.
    """
    # Own subdirectory on purpose: the service spells the sandbox
    # <seam>/<branch>/<branch>_json, so a seam AT tmp_path would create
    # tmp_path/drone/ in every test and collide with a test that builds a
    # directory of its own branch's name (backup hit it first, 2026-09-03).
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox
