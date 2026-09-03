# ===================AIPASS====================
# META DATA HEADER
# Name: tests/conftest.py
# Date: {{DATE}}
# Version: 3.0.0
# Category: {{BRANCH}}/tests
#
# CHANGELOG (Max 5 entries):
#   - v3.0.0 ({{DATE}}): The json redirect is the AIPASS_TEST_LOG_DIR seam - the
#     fleet service resolves its directory per call, so there is no singleton
#     and no private attribute left to patch (DPLAN-0325)
#   - v2.0.0 ({{DATE}}): Real fixtures - temp dirs, captured logger, sandboxed
#     json handler, and an autouse guard that keeps tests out of {{BRANCH}}_json/
#   - v1.0.0 (2025-11-08): Initial implementation - Shared pytest fixtures
#
# CODE STANDARDS:
#   - Error handling: Use error handler system (apps/handlers/error/)
# =============================================

"""Shared pytest fixtures for {{BRANCH}} tests.

The autouse fixture here is the load-bearing one: this branch's json_handler
binds the fleet's one json service, which writes into {{BRANCH}}_json/ unless
AIPASS_TEST_LOG_DIR says otherwise. mock_infrastructure sets that variable per
test, so every test lands in its own tmp_path without knowing it.
"""

import shutil
import tempfile
from pathlib import Path
from typing import Generator, List, Tuple

import pytest

from aipass.{{BRANCH}}.apps.handlers.json import json_handler


@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after."""
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir)


@pytest.fixture
def sample_test_data() -> dict:
    """Provides sample test data shaped like a valid 'data' JSON document."""
    return {
        "created": "{{DATE}}",
        "last_updated": "{{DATE}}",
        "test_key": "test_value",
        "sample_data": "example",
    }


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect this branch's json writes into a temp dir.

    autouse=True on purpose: the shim's names write into the real
    {{BRANCH}}_json/ unless the seam is set, so a test that forgets to redirect
    pollutes the branch. The guard belongs on every test, not on the ones that
    remember.

    The service recomputes its directory on every call, so setting the variable
    here - after import - still takes effect. The sandbox is MEASURED off the
    shim rather than spelled out, so it cannot drift from what the service does.

    Returns:
        The sandbox directory the handler now writes into.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture
def mock_logger(monkeypatch) -> List[Tuple[str, tuple]]:
    """Capture calls made to the entry point's logger.

    Returns:
        A list that fills with (level, args) tuples as the code under test logs.
    """
    captured: List[Tuple[str, tuple]] = []

    class _CapturingLogger:
        def info(self, *args, **kwargs):
            captured.append(("info", args))

        def warning(self, *args, **kwargs):
            captured.append(("warning", args))

        def error(self, *args, **kwargs):
            captured.append(("error", args))

    from aipass.{{BRANCH}}.apps import {{BRANCH}} as branch_entry

    monkeypatch.setattr(branch_entry, "logger", _CapturingLogger())
    return captured
