# ===================AIPASS====================
# Name: conftest.py
# Description: Skills test configuration
# Version: 3.1.0
# Created: 2026-03-07
# Modified: 2026-09-27
# Category: skills/tests
#
# CHANGELOG (Max 5 entries):
#   - v3.1.0 (2026-09-27): C1 console width pin, C2 command-state reset; unused temp_dir, mock_logger removed
#   - v3.0.0 (2026-09-03): The json redirect is the AIPASS_TEST_LOG_DIR seam - no attribute to patch (DPLAN-0325)
#   - v2.1.0 (2026-07-22): mock_infrastructure re-resolves json_handler at setup - fixed real-file leaks
#   - v2.0.0 (2026-03-28): Added sample_data, mock_infrastructure, mock_json_handler fixtures
#   - v1.0.0 (2026-03-07): Initial implementation
#
# CODE STANDARDS:
#   - Sets the AIPASS_TEST_LOG_DIR seam before the first aipass import
# =============================================

"""Skills test configuration.

The autouse fixture here is the load-bearing one: this branch's json_handler
binds the fleet's one json service (DPLAN-0325), which writes into skills_json/
unless AIPASS_TEST_LOG_DIR says otherwise. mock_infrastructure sets that
variable per test, so every test lands in its own tmp_path without knowing it.
"""

import os
import tempfile

# Redirect prax logs AND the fleet json service to a temp directory during
# tests. Must be set before any prax imports to catch logger initialization.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import logging
from pathlib import Path
from typing import Generator

import pytest

# aipass is an installed package (pip install -e), so nothing here hacks
# sys.path to reach it — a conftest that prepends src/ hides a broken install
# and shadows the wheel the e2e job measures.
from aipass.cli.apps.modules import display
from aipass.skills.apps.handlers.json import json_handler

BRANCH_MODULE = "aipass.skills"

# Archived files are a record, never a subject: nothing under .archive/ is
# collected, imported or discovered (DPLAN-0325 - a sibling branch's rglob
# walked into one and generated a dotted name that would not parse).
collect_ignore_glob = [".archive/*", "**/.archive/*"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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

    autouse=True on purpose: the shim's names write into the real skills_json/
    unless the seam is set, so a test that forgets to redirect pollutes the
    branch. The guard belongs on every test, not on the ones that remember.

    The service recomputes its directory on every call, so setting the variable
    here - after import - still takes effect. The sandbox is MEASURED off the
    shim rather than spelled out, so it cannot drift from what the service does.

    Returns:
        The sandbox directory the handler now writes into.
    """
    # Own subdirectory on purpose: the service spells the sandbox
    # <seam>/skills/skills_json, so a seam AT tmp_path would create
    # tmp_path/skills/ in every test and collide with a test that builds a
    # directory of its own branch's name.
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)

    logger_names = [
        BRANCH_MODULE,
        "aipass.prax.json",
    ]
    for logger_name in logger_names:
        log = logging.getLogger(logger_name)
        monkeypatch.setattr(log, "handlers", [logging.NullHandler()])

    return sandbox


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Rich sizes an unpinned console on every print: 80 on POSIX and 79 on Windows
    under pytest's capture, the terminal's width under -s, COLUMNS when exported."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    display.reset_command_state()
