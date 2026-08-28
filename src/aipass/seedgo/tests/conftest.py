"""Shared pytest fixtures for seedgo tests"""

# =================== META ====================
# Name: conftest.py
# Description: Shared pytest fixtures for seedgo tests
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

import os
import tempfile

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest
import shutil
from pathlib import Path
from typing import Generator


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


@pytest.fixture(scope="session")
def preexisting_live_tmp_files() -> set:
    """Names of *.tmp files already in the live json dir when the session began.

    The orphan-tmp test reads LIVE state, so anything that dies mid-write
    anywhere on the machine -- another audit, a killed CI step, a previous
    session's SIGKILL -- lands in its assertion and fails a run that changed
    nothing. Snapshotting at session start turns that assertion into
    "this session left no NEW orphan", which is the claim it can actually
    make.

    Pre-existing orphans are NOT swept under the rug: the test warns on each
    one by name so a real accumulation stays visible instead of becoming the
    permanent baseline nobody reads.
    """
    from aipass.seedgo.apps.handlers.json import json_handler

    live_dir = json_handler.JSON_DIR
    if not live_dir.exists():
        return set()
    return {p.name for p in live_dir.glob("*.tmp")}
