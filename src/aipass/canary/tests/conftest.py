# =================== AIPass ====================
# Name: conftest.py
# Description: Shared pytest fixtures for canary - json seam, console width, command state, logger capture
# Version: 3.3.0
# Created: 2025-11-08
# Modified: 2026-10-17
#
# CHANGELOG (Max 5 entries):
#   - v3.3.0 (2026-10-10): temp_test_dir and sample_test_data retired - the template's
#     fixtures, requested only by the git-ignored .archive scaffold (seedgo, PR #774)
#   - v3.2.0 (2026-10-04): Template item 5 header - AIPass banner, the five META fields
#   - v3.1.0 (2026-10-03): Template C1/C2 - pinned console width, command state reset
#     after every test; product import moved to the top
#   - v3.0.0 (2026-09-03): The json redirect is the AIPASS_TEST_LOG_DIR seam — the
#     fleet service resolves its directory per call, so there is no singleton
#     and no private attribute left to patch (DPLAN-0325)
#   - v2.0.0 (2026-08-22): Real fixtures — temp dirs, captured logger, sandboxed
#     json handler, and an autouse guard that keeps tests out of canary_json/
#   - v1.0.0 (2025-11-08): Initial implementation - Shared pytest fixtures
#
# CODE STANDARDS:
#   - Error handling: Use error handler system (apps/handlers/error/)
# =============================================

"""Shared pytest fixtures for canary tests."""

import os
import tempfile
from pathlib import Path
from typing import Generator, List, Tuple

# Before any aipass import: the repo-root conftest refuses a branch's json shim while this is unset.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest

from aipass.canary.apps import canary as canary_entry
from aipass.canary.apps.handlers.json import json_handler
from aipass.cli.apps.modules import display

# .archive/ holds disposal copies that must never be collected or rglob-walked into module names.
collect_ignore_glob = [".archive/*", "**/.archive/*"]


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Unpinned, Rich sizes per print: 80 POSIX, 79 Windows under capture, the terminal under -s, COLUMNS if set."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    display.reset_command_state()


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect canary's json writes into a temp dir and return the sandbox the handler writes into.

    Autouse, so no test writes the real canary_json/; the service resolves its directory per call."""
    # Own subdir: the service builds <seam>/canary/canary_json, so tmp_path/canary/ would collide.
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture
def mock_logger(monkeypatch) -> List[Tuple[str, tuple]]:
    """Capture the entry point's logger calls as (level, args) tuples."""
    captured: List[Tuple[str, tuple]] = []

    class _CapturingLogger:
        def info(self, *args, **kwargs):
            captured.append(("info", args))

        def warning(self, *args, **kwargs):
            captured.append(("warning", args))

        def error(self, *args, **kwargs):
            captured.append(("error", args))

    monkeypatch.setattr(canary_entry, "logger", _CapturingLogger())
    return captured
