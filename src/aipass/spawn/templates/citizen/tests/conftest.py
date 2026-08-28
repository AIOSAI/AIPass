# ===================AIPASS====================
# META DATA HEADER
# Name: tests/conftest.py
# Date: {{DATE}}
# Version: 2.0.0
# Category: {{BRANCH}}/tests
#
# CHANGELOG (Max 5 entries):
#   - v2.0.0 ({{DATE}}): Real fixtures - temp dirs, captured logger, sandboxed
#     json handler, and an autouse guard that keeps tests out of {{BRANCH}}_json/
#   - v1.0.0 (2025-11-08): Initial implementation - Shared pytest fixtures
#
# CODE STANDARDS:
#   - Error handling: Use error handler system (apps/handlers/error/)
# =============================================

"""Shared pytest fixtures for {{BRANCH}} tests.

The autouse fixture here is the load-bearing one: this branch's json_handler is
a module-level singleton pointed at {{BRANCH}}_json/, so without redirection
every test that touches it would write real files into the branch.
mock_infrastructure repoints that singleton at a tmp_path for each test.
"""

import shutil
import tempfile
from pathlib import Path
from typing import Generator, List, Tuple

import pytest

from aipass.aipass.shared.json_handler import JsonHandler
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
    """Redirect the branch json_handler singleton at a temp dir.

    autouse=True on purpose: the re-exported handler functions are bound methods
    of one module-level instance, so a test that forgets to redirect writes into
    the real {{BRANCH}}_json/. The guard belongs on every test, not on the ones
    that remember.

    Returns:
        The sandbox directory the handler now writes into.
    """
    sandbox = tmp_path / "{{BRANCH}}_json"
    sandbox.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(json_handler._handler, "_json_dir", sandbox)
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


@pytest.fixture
def mock_json_handler(tmp_path) -> JsonHandler:
    """A throwaway JsonHandler writing into an isolated directory.

    Returns:
        JsonHandler bound to a fresh tmp directory.
    """
    return JsonHandler(json_dir=tmp_path / "isolated_json")
