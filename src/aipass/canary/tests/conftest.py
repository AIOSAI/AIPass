# =================== AIPass ====================
# Name: conftest.py
# Description: Shared pytest fixtures for canary - json seam, console width, command state, logger capture
# Version: 3.3.0
# Created: 2025-11-08
# Modified: 2026-10-10
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

"""Shared pytest fixtures for canary tests.

The autouse fixture here is the load-bearing one: canary's json_handler binds
the fleet's one json service, which writes into canary_json/ unless
AIPASS_TEST_LOG_DIR says otherwise. mock_infrastructure sets that variable per
test, so every test lands in its own tmp_path without knowing it.
"""

import os
import tempfile
from pathlib import Path
from typing import Generator, List, Tuple

# The seam must exist at IMPORT time, not only inside the autouse fixture: the
# repo-root conftest guard refuses to import a branch's json shim while
# AIPASS_TEST_LOG_DIR is unset (61 errors under `-c pyproject.toml --rootdir=.`
# on 2026-09-06). Sixteen branches set it here; this one set it per-test only
# and passed in CI solely because a sibling conftest had already set it.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest

from aipass.canary.apps import canary as canary_entry
from aipass.canary.apps.handlers.json import json_handler
from aipass.cli.apps.modules import display

# Never discover out of .archive/: it holds verbatim disposal copies (old
# handler tests, the archived json_dir pin) that must not be collected or
# rglob-walked into dotted module names (DPLAN-0325, spec 4c).
collect_ignore_glob = [".archive/*", "**/.archive/*"]


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


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect canary's json writes into a temp dir.

    autouse=True on purpose: the shim's names write into the real canary_json/
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
    # tmp_path/canary/ in every test and collide with a test that builds a
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

    monkeypatch.setattr(canary_entry, "logger", _CapturingLogger())
    return captured
