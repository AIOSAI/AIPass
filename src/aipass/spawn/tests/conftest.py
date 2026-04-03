"""Shared test fixtures for spawn test suite."""
import os
import tempfile

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import json
import shutil
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Registry backup/restore — prevents test ghost entries in AIPASS_REGISTRY.json
# ---------------------------------------------------------------------------

def _find_registry_path() -> Path:
    """Locate AIPASS_REGISTRY.json from the spawn branch."""
    return Path(__file__).resolve().parents[4] / "AIPASS_REGISTRY.json"


@pytest.fixture(autouse=True, scope="session")
def _protect_registry():
    """Backup AIPASS_REGISTRY.json before the test session, restore after.

    Prevents tests that call spawn_agent/grant_passport without a
    registry_path override from permanently polluting the real registry.
    """
    reg = _find_registry_path()
    backup = reg.with_suffix(".json.test_backup")

    if reg.exists():
        shutil.copy2(reg, backup)

    yield

    if backup.exists():
        shutil.copy2(backup, reg)
        backup.unlink()


@pytest.fixture
def sample_data():
    """Pre-populated JSON test data for spawn operations."""
    return {
        "metadata": {"version": "1.0.0", "created": "2026-03-27"},
        "files": {"F001": {"path": "test.py", "hash": "abc123"}},
        "directories": {"D001": {"path": "apps/"}},
    }


@pytest.fixture
def mock_infrastructure(tmp_path):
    """Mock filesystem structure mimicking a spawned branch."""
    branch = tmp_path / "test_branch"
    for d in ["apps/modules", "apps/handlers", ".trinity", ".aipass"]:
        (branch / d).mkdir(parents=True)
    passport = {
        "branch_info": {"branch_name": "test_branch"},
        "identity": {"citizen_class": "builder"},
    }
    (branch / ".trinity" / "passport.json").write_text(
        json.dumps(passport), encoding="utf-8"
    )
    return branch


@pytest.fixture
def mock_logger():
    """Mock aipass.prax logger for testing log calls."""
    with patch("aipass.prax.logger") as m:
        yield m


@pytest.fixture
def mock_json_handler():
    """Mock json_handler.log_operation at the call site in file_ops.

    Uses patch.object on the module reference held by file_ops to avoid
    stale-reference issues when other test suites reload json_handler.
    """
    import aipass.spawn.apps.handlers.file_ops as _fo

    with patch.object(_fo.json_handler, "log_operation") as m:
        m.return_value = True
        yield m


@pytest.fixture(autouse=True)
def _isolate_spawn_json(tmp_path):
    """Auto-isolate spawn_json directory to prevent test pollution."""
    import aipass.spawn.apps.handlers.json.json_handler as _jh

    with patch.object(_jh, "_JSON_DIR", tmp_path / "spawn_json"):
        yield
