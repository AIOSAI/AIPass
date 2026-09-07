# ===================AIPASS====================
# META DATA HEADER
# Name: conftest.py - Skills test configuration
# Date: 2026-03-07
# Version: 3.0.0
# Category: skills/tests
#
# CHANGELOG (Max 5 entries):
#   - v3.0.0 (2026-09-03): The json redirect is the AIPASS_TEST_LOG_DIR seam -
#     the fleet service resolves its directory per call, so there is no module
#     attribute left to patch and no handler to re-import (DPLAN-0325)
#   - v2.1.0 (2026-07-22): mock_infrastructure re-resolves json_handler via
#     import_module at fixture-setup time instead of patching the stale
#     module captured at conftest load — fixes real-file leaks (t_config.json
#     etc.) when a combined multi-branch run pops sys.modules mid-session
#   - v2.0.0 (2026-03-28): Added temp_dir, sample_data, mock_infrastructure,
#     mock_logger, mock_json_handler fixtures for test quality compliance
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
from typing import Generator, List, Tuple

import pytest

# aipass is an installed package (pip install -e), so nothing here hacks
# sys.path to reach it — a conftest that prepends src/ hides a broken install
# and shadows the wheel the e2e job measures.
from aipass.skills.apps.handlers.json import json_handler  # noqa: E402

BRANCH_MODULE = "aipass.skills"

# Archived files are a record, never a subject: nothing under .archive/ is
# collected, imported or discovered (DPLAN-0325 - a sibling branch's rglob
# walked into one and generated a dotted name that would not parse).
collect_ignore_glob = [".archive/*", "**/.archive/*"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def temp_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after."""
    test_dir = tmp_path / "test_workspace"
    test_dir.mkdir(parents=True, exist_ok=True)
    yield test_dir
    for child in test_dir.iterdir():
        if child.is_file():
            child.unlink()


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


@pytest.fixture()
def mock_logger(monkeypatch: pytest.MonkeyPatch) -> List[Tuple[str, tuple]]:
    """Capture calls made to the entry point's logger.

    Returns:
        A list that fills with (level, args) tuples as the code under test logs.
    """
    captured: List[Tuple[str, tuple]] = []

    class _CapturingLogger:
        def debug(self, *args: object, **kwargs: object) -> None:
            captured.append(("debug", args))

        def info(self, *args: object, **kwargs: object) -> None:
            captured.append(("info", args))

        def warning(self, *args: object, **kwargs: object) -> None:
            captured.append(("warning", args))

        def error(self, *args: object, **kwargs: object) -> None:
            captured.append(("error", args))

    from aipass.skills.apps import skills as branch_entry

    monkeypatch.setattr(branch_entry, "logger", _CapturingLogger())
    return captured
