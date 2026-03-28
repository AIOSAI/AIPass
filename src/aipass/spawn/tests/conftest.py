"""Shared test fixtures for spawn test suite."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


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
    """Mock json_handler to verify log_operation calls."""
    with patch("aipass.spawn.apps.handlers.json.json_handler.log_operation") as m:
        m.return_value = True
        yield m


@pytest.fixture(autouse=True)
def _isolate_spawn_json(tmp_path):
    """Auto-isolate spawn_json directory to prevent test pollution."""
    with patch(
        "aipass.spawn.apps.handlers.json.json_handler._JSON_DIR",
        tmp_path / "spawn_json",
    ):
        yield
