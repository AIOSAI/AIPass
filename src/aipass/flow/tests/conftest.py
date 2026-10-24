# =================== AIPass ====================
# Name: conftest.py
# Description: Shared fixtures for flow tests - log redirect, console pin, command-state reset
# Version: 1.3.0
# Created: 2026-03-05
# Modified: 2026-10-24
# =============================================

"""Shared pytest fixtures for flow tests"""

import os
import tempfile

# Must be set before any prax import, or logger initialization writes to the real log dir.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest
from pathlib import Path
from typing import Generator
import sys
from unittest.mock import MagicMock, patch

# patch() needs these sub-module attributes for dotted-path traversal.
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.flow.apps.handlers.json.json_handler  # noqa: F401
from aipass.flow.apps.handlers.json import json_handler as json_handler_module
import aipass.cli.apps.modules  # noqa: F401
from aipass.cli.apps.modules import display

# Import-time find_repo_root() fallback logs would leak into mock_json_handler counts; pinned complete.
import aipass.flow.apps.handlers.dashboard.push_central  # noqa: F401
import aipass.flow.apps.handlers.mbank.process  # noqa: F401
import aipass.flow.apps.handlers.plan.close_helpers  # noqa: F401
import aipass.flow.apps.handlers.plan.restore_ops  # noqa: F401
import aipass.flow.apps.modules.aggregate_central  # noqa: F401
import aipass.flow.apps.modules.registry_monitor  # noqa: F401


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


def pytest_configure(config):
    """Register flow's markers where BOTH test universes can see them."""
    config.addinivalue_line(
        "markers",
        "real_logger: opt out of the autouse mock_logger fixture — for tests whose "
        "SUBJECT is the log line (caplog reads the real logging module)",
    )


@pytest.fixture(autouse=True)
def mock_logger(request, monkeypatch):
    """Mock the prax logger at each flow consumer's own binding (bound at import); opt out: real_logger."""
    if request.node.get_closest_marker("real_logger"):
        yield None
        return

    mock = MagicMock()
    for name, module in list(sys.modules.items()):
        if not name.startswith("aipass.flow.apps"):
            continue
        for attribute in ("logger", "system_logger"):
            if getattr(module, attribute, None) is not None:
                monkeypatch.setattr(module, attribute, mock, raising=False)
    # The source too, so a module imported LATER in the test binds the mock.
    monkeypatch.setattr("aipass.prax.apps.modules.logger.system_logger", mock)
    yield mock


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect flow's json writes into a temp dir; autouse, else the json service writes the real flow_json/."""
    # A seam AT tmp_path would create tmp_path/flow/ and collide with tests that build that dir.
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler_module.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture(autouse=True)
def mock_json_handler(request):
    """Spy on the audit line, so a test can assert WHICH operation was logged."""
    if request.node.module.__name__.endswith("test_json_handler"):
        yield None
        return

    with patch("aipass.flow.apps.handlers.json.json_handler.log_operation") as mock_log_op:
        yield mock_log_op
