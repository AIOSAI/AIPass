# ===================AIPASS====================
# META DATA HEADER
# Name: tests/conftest.py
# Date: 2025-11-08
# Version: 1.1.0
# Category: trigger/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.1.0 (2026-08-08): Suite-wide escalation lane isolation
#   - v1.0.0 (2025-11-08): Initial implementation - Shared pytest fixtures
#
# CODE STANDARDS:
#   - Error handling: Use error handler system (apps/handlers/error/)
# =============================================

"""Shared pytest fixtures for trigger tests"""

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

# Imported here, while the REAL aipass.trigger.apps.config is still in place,
# so the whole suite shares ONE escalation module. Handlers reach the lane with
# `from aipass.trigger.apps.handlers import escalation`, which reuses whatever
# is already imported — without this, the first test file to mock the config
# module would leave a mock-configured copy (MagicMock file lock, stale tmp
# paths) cached for every test that follows.
from aipass.trigger.apps.handlers import escalation as _escalation
from aipass.trigger.apps.handlers.json import config_loader as _config_loader


@pytest.fixture(scope="session")
def escalation_sandbox(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Session-wide stand-in for trigger_json/ and its custom_config/."""
    return tmp_path_factory.mktemp("escalation_sandbox")


@pytest.fixture(autouse=True)
def isolate_escalation_state(monkeypatch: pytest.MonkeyPatch, escalation_sandbox: Path) -> Generator[None, None, None]:
    """Keep the escalation lane off live state for every test in the suite.

    handle_error_detected and handle_warning_logged record into the lane before
    any dispatch gate, so any test that fires one of those events would
    otherwise count into the real trigger_json/escalation_state.json and read —
    or, when it is missing, regenerate — the operator's trigger.config.json.
    setup_handlers() also wires a live email callback into the lane; it is
    reset here so no test can send a digest.

    Tests that need their own state file or config simply patch over these.
    """
    state_file = escalation_sandbox / "escalation_state.json"
    state_file.unlink(missing_ok=True)
    monkeypatch.setattr(_escalation, "STATE_FILE", state_file)
    monkeypatch.setattr(_escalation, "ESCALATION_LOG", escalation_sandbox / "escalation.jsonl")
    monkeypatch.setattr(_escalation, "_send_email", None)
    monkeypatch.setattr(_config_loader, "CONFIG_PATH", escalation_sandbox / "custom_config" / "trigger.config.json")
    monkeypatch.setattr(_config_loader, "_LOADER_LOG", escalation_sandbox / "config_loader.jsonl")
    _escalation.reset_config_cache()
    yield
    _escalation.reset_config_cache()


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
