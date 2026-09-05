# ===================AIPASS====================
# META DATA HEADER
# Name: tests/conftest.py
# Date: 2025-11-08
# Version: 1.0.0
# Category: spawn/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2025-11-08): Initial implementation - Shared pytest fixtures
#
# CODE STANDARDS:
#   - Error handling: Use error handler system (apps/handlers/error/)
# =============================================

"""Shared pytest fixtures for aipass tests."""

import pytest
import shutil
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

from aipass.aipass.apps.handlers.json import json_handler


@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after."""
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir)


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect this branch's json writes into a temp dir.

    autouse=True on purpose: the shim's names write into the real ``aipass_json/``
    unless the seam is set, so a test that forgets to redirect pollutes the
    branch. The guard belongs on every test, not on the ones that remember.

    The service recomputes its directory on every call, so setting the variable
    here -- after import -- still takes effect. The sandbox is MEASURED off the
    shim rather than spelled out, so it cannot drift from what the service does.

    Returns:
        The sandbox directory the handler now writes into.
    """
    # Own subdirectory on purpose: the service spells the sandbox
    # <seam>/<branch>/<branch>_json, so a seam AT tmp_path would create
    # tmp_path/aipass/ in every test and collide with a test that builds a
    # directory of its own branch's name (backup hit it first, 2026-09-03).
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture(autouse=True)
def isolate_profile_store(tmp_path_factory) -> Generator[Path, None, None]:
    """Point the user profile at a temp dir for EVERY test in this branch.

    Not belt-and-braces — it closes a live-state leak found 2026-08-27:
    test_init_flow injects a MagicMock at
    sys.modules["aipass.aipass.apps.modules.profile"], but
    ``from ...modules import profile`` resolves the attribute already set on
    the parent package whenever another test file imported the real module
    first. The mock is then silently bypassed and the profile stage writes the
    REAL store. test_help_flag + test_init_flow together rewrote the live
    profile to null defaults; either file alone was clean, which is why no
    single-file run ever caught it.

    Autouse and unconditional because the leak is an ORDERING effect: any test
    that reaches profile code through an unmocked path is a candidate, and
    naming them one by one only holds until the next import order changes.
    """
    from aipass.aipass.apps.modules import profile as profile_mod

    store_dir = tmp_path_factory.mktemp("profile_store")
    with (
        patch.object(profile_mod, "_PROFILE_JSON", store_dir / profile_mod._PROFILE_FILENAME),
        patch.object(profile_mod, "_LEGACY_LOCAL_JSON", store_dir / "local.json"),
    ):
        yield store_dir


@pytest.fixture
def sample_test_data() -> dict:
    """Provides sample test data."""
    return {"test_key": "test_value", "sample_data": "example"}


@pytest.fixture
def mock_json_handler():
    """Mock json_handler with functional read_json but stubbed logging.

    Use when tests need real file I/O via read_json but want to
    suppress log_operation and ensure_module_jsons side effects.
    """
    with (
        patch("aipass.aipass.apps.handlers.json.json_handler.log_operation") as mock_log,
        patch(
            "aipass.aipass.apps.handlers.json.json_handler.ensure_module_jsons",
            return_value=True,
        ) as mock_ensure,
    ):
        mock = MagicMock()
        mock.log_operation = mock_log
        mock.ensure_module_jsons = mock_ensure
        yield mock
