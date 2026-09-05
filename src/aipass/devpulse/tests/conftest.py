# =================== AIPass ====================
# Name: conftest.py
# Description: Shared pytest fixtures for devpulse tests
# Version: 1.2.0
# Created: 2025-11-08
# Modified: 2026-09-03
# =============================================

"""Shared pytest fixtures for devpulse tests.

The first thing this file does is arm the fleet's test-redirect seam. The json
handler is the one-source shim (DPLAN-0325): prax's service derives this
branch's ``devpulse_json`` directory PER CALL and honours ``AIPASS_TEST_LOG_DIR``
itself, so setting the variable here, before any import of the shim, is the
only redirect a suite needs. Nothing patches handler attributes any more.
"""

import os
import tempfile

if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

from unittest.mock import patch

import pytest
import shutil
from pathlib import Path
from typing import Generator

from aipass.devpulse.apps.handlers.json import json_handler


def pytest_configure(config: pytest.Config) -> None:
    # Registered here, not pytest.ini: the composed run (rootdir=repo,
    # -c pyproject.toml) never reads this branch's ini, and its
    # --strict-markers would turn an unknown marker into an error.
    config.addinivalue_line("markers", "integration: live-dispatch integration tests (WATCHDOG_INTEGRATION=1)")


@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after"""
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir)


@pytest.fixture
def sample_test_data() -> dict:
    """Provides sample test data."""
    return {"test_key": "test_value", "sample_data": "example"}


@pytest.fixture
def mock_logger():
    """Mock the prax logger to suppress output during tests."""
    with patch("aipass.prax.logger") as mock_log:
        yield mock_log


@pytest.fixture
def mock_json_handler():
    """Mock json_handler to prevent filesystem writes during tests."""
    with patch("aipass.devpulse.apps.handlers.json.json_handler.log_operation") as mock_json:
        yield mock_json


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect this branch's json writes into a per-test sandbox.

    The module-level seam above gives the whole process one directory; this
    autouse fixture narrows it to one per test. The service recomputes its
    directory on every call, so setting the variable after import still takes
    effect. The sandbox is MEASURED off the shim rather than spelled out, so it
    cannot drift from what the service does (template conftest shape).

    Returns:
        The sandbox directory the handler now writes into.
    """
    # Own subdirectory on purpose: the service spells the sandbox
    # <seam>/<branch>/<branch>_json, so a seam AT tmp_path would create
    # tmp_path/<branch>/ in every test and collide with a test that builds a
    # directory of its own branch's name (backup hit it first, 2026-09-03).
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture
def hermetic_mail_doors(tmp_path_factory, monkeypatch):
    """Point @ai_mail's path doors at a fake live repo that carries the marker.

    The watchdog re-root (feed.feed_file / dispatches' register transplant)
    learns the feed's shape by walking UP from @ai_mail's live answer to the
    parent holding AIPASS_REGISTRY.json. That marker is runtime state: it
    exists on any machine the system has run on and on NO fresh checkout —
    which is exactly CI. 37 tests passed here for weeks and failed the first
    fresh-checkout run (PR #739, 2026-08-23), because they were implicitly
    testing this machine, not the code.

    This fixture makes the live half of the walk hermetic too: a tmp "live"
    repo with the marker and the owner's real shape. The production walk stays
    exactly as ruled (no fallback, loud refusal) — only the tests stop needing
    a machine with history. Tests opt in via a module-local autouse wrapper
    rather than branch-wide autouse, so a future test that MEANS to exercise
    live resolution can still exist by simply not opting in.
    """
    live = tmp_path_factory.mktemp("live_mail_repo")
    (live / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    aipass_dir = live / ".aipass"
    aipass_dir.mkdir()
    feed = aipass_dir / "notifications.jsonl"
    register = aipass_dir / "dispatch_register.jsonl"
    monkeypatch.setattr("aipass.ai_mail.feed_path", lambda: feed)
    monkeypatch.setattr("aipass.ai_mail.register_path", lambda: register)
    # The register transplant lives INSIDE @ai_mail (outstanding_dispatches →
    # register_file), which resolves through its own find_repo_root — the
    # public register_path door above never enters that path. Patching another
    # branch's internal symbol is a reach, done knowingly and only in-process:
    # @ai_mail is dispatched (2026-08-23) about giving the transplant a seam
    # that does not require this; when that lands, this line becomes harmless.
    monkeypatch.setattr("aipass.ai_mail.apps.handlers.dispatch.register.find_repo_root", lambda: live)
    return live
