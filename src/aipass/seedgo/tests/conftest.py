"""Shared pytest fixtures for seedgo tests.

The autouse fixture here is the load-bearing one: seedgo's json_handler binds
the fleet's one json service (DPLAN-0325), which writes into seedgo_json/
unless AIPASS_TEST_LOG_DIR says otherwise. mock_infrastructure sets that
variable per test, so every test lands in its own tmp_path without knowing it.
"""

# =================== META ====================
# Name: conftest.py
# Description: Shared pytest fixtures for seedgo tests
# Version: 2.0.0
# Created: 2026-03-05
# Modified: 2026-09-03
# =============================================

import os
import tempfile

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import shutil
from pathlib import Path
from typing import Generator, List, Tuple

import pytest

from aipass.seedgo.apps.handlers.json import json_handler

# Never discover out of .archive/: it holds verbatim disposal copies (the old
# handler's tests, the pre-service durability suite) that must not be collected
# or rglob-walked into dotted module names (DPLAN-0325, spec 4c).
collect_ignore_glob = [".archive/*", "**/.archive/*"]


@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after"""
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir)


@pytest.fixture
def sample_test_data() -> dict:
    """Provides sample test data

    Customize this fixture for your module's needs
    """
    return {"test_key": "test_value", "sample_data": "example"}


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect seedgo's json writes into a temp dir.

    autouse=True on purpose: the shim's names write into the real seedgo_json/
    unless the seam is set, so a test that forgets to redirect pollutes the
    branch. The guard belongs on every test, not on the ones that remember.

    The service recomputes its directory on every call, so setting the variable
    here — after import — still takes effect. The sandbox is MEASURED off the
    shim rather than spelled out, so it cannot drift from what the service does.

    Returns:
        The sandbox directory the handler now writes into.
    """
    # Own subdirectory on purpose: the service spells the sandbox
    # <seam>/<branch>/<branch>_json, so a seam AT tmp_path would create
    # tmp_path/seedgo/ in every test and collide with a test that builds a
    # directory of its own branch's name (backup hit it first, 2026-09-03).
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
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

    from aipass.seedgo.apps import seedgo as seedgo_entry

    monkeypatch.setattr(seedgo_entry, "logger", _CapturingLogger())
    return captured
