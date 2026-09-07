# =================== AIPass ====================
# Name: conftest.py
# Version: 2.0.0
# Description: Shared pytest fixtures for hooks tests
# Branch: hooks
# Layer: tests
# Created: 2026-05-18
# Modified: 2026-09-03
# =============================================

"""Shared pytest fixtures for hooks tests.

The json redirect is the ``AIPASS_TEST_LOG_DIR`` seam (DPLAN-0325). This
branch's ``json_handler`` binds the fleet's one json service, which resolves
this branch's document directory PER CALL and honours that variable itself —
there is no singleton and no private attribute left to patch.

The variable is armed twice, on purpose. At import, so it is set before any
test runs: the repo-root conftest REFUSES a run that reaches a shim-bound
``log_operation`` with the seam unset, because such a run would write into live
``<branch>_json`` directories, and its autouse fixture runs before this file's.
Then per test by ``mock_infrastructure``, so each test gets its own tmp_path.
"""

import importlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import patch

if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest

from aipass.hooks.apps.handlers.json import json_handler

collect_ignore_glob = [".archive/*"]


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect this branch's json writes into a temp dir.

    autouse=True on purpose: the shim's names write into the real hooks_json/
    unless the seam is set, so a test that forgets to redirect pollutes the
    branch. The guard belongs on every test, not on the ones that remember.

    The service recomputes its directory on every call, so setting the variable
    here — after import — still takes effect. The sandbox is MEASURED off the
    shim rather than spelled out, so it cannot drift from what the service does.

    Returns:
        The sandbox directory the handler now writes into.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after."""
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir)


@pytest.fixture
def sample_hooks_config() -> dict:
    """Minimal hooks.json config for testing."""
    return {
        "hooks_enabled": True,
        "UserPromptSubmit": {
            "test_hook": {
                "enabled": True,
                "command": "echo 'test output'",
                "matcher": "",
            }
        },
        "PreToolUse": {
            "matcher_hook": {
                "enabled": True,
                "command": "echo 'matched'",
                "matcher": "Edit|Write",
            },
            "disabled_hook": {
                "enabled": False,
                "command": "echo 'should not fire'",
                "matcher": "",
            },
        },
    }


@pytest.fixture
def hooks_config_file(temp_test_dir: Path, sample_hooks_config: dict) -> Path:
    """Creates a .aipass/hooks.json in temp dir."""
    config_dir = temp_test_dir / ".aipass"
    config_dir.mkdir()
    config_file = config_dir / "hooks.json"
    config_file.write_text(json.dumps(sample_hooks_config), encoding="utf-8")
    return config_file


@pytest.fixture
def mock_logger():
    """Mock the prax system logger."""
    with patch("aipass.hooks.apps.modules.engine.logger") as mock:
        yield mock


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run for hook execution tests."""
    with patch("aipass.hooks.apps.modules.engine.subprocess.run") as mock:
        yield mock


@pytest.fixture(autouse=True)
def isolated_cadence_state(tmp_path_factory, monkeypatch):
    """Keep per-session cadence/advisory state out of the LIVE seat's files.

    cadence persists throttle state in the system temp dir keyed by
    CLAUDE_CODE_SESSION_ID, so an unisolated run both reads and WRITES the
    state of whatever session is executing the suite — a test could silence a
    real advisory for ten turns, or be silenced by one. Same class of defect as
    the 12 fixture lines this branch put in the production presence_gate.log.

    Tests that exercise cadence itself patch _GUARD_DIR on top of this.
    """
    cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
    monkeypatch.setattr(cadence, "_GUARD_DIR", tmp_path_factory.mktemp("cadence_state"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "pytest-session")
