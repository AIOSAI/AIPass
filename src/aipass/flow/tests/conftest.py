"""Shared pytest fixtures for flow tests"""
import os
import tempfile

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest
import json
import shutil
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

# Pre-import modules so patch() path resolution works.
# Without these imports, the intermediate packages lack the sub-module
# attributes that unittest.mock.patch needs for dotted-path traversal.
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.flow.apps.handlers.json.json_handler  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401


@pytest.fixture(autouse=True)
def mock_logger():
    """Mock prax logger to prevent real log writes."""
    with patch("aipass.prax.apps.modules.logger.system_logger") as mock:
        yield mock


@pytest.fixture(autouse=True)
def mock_json_handler():
    """Mock json_handler to prevent real JSON operations."""
    with patch(
        "aipass.flow.apps.handlers.json.json_handler.log_operation"
    ) as mock_log_op:
        yield mock_log_op


@pytest.fixture(autouse=True)
def mock_console():
    """Mock CLI console to prevent real console output."""
    with patch("aipass.cli.apps.modules.console") as console_mock, \
         patch("aipass.cli.apps.modules.error") as error_mock, \
         patch("aipass.cli.apps.modules.warning") as warning_mock, \
         patch("aipass.cli.apps.modules.success") as success_mock, \
         patch("aipass.cli.apps.modules.header") as header_mock:
        yield {
            "console": console_mock,
            "error": error_mock,
            "warning": warning_mock,
            "success": success_mock,
            "header": header_mock,
        }


@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after"""
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir)


@pytest.fixture
def mock_registry(tmp_path):
    """Create a mock plan registry with sample data."""
    registry = {
        "next_number": 5,
        "last_updated": "2026-03-24",
        "plans": {
            "1": {
                "subject": "Test plan one",
                "status": "open",
                "created": "2026-03-20",
                "file_path": str(tmp_path / "FPLAN-0001_test_plan_one_2026-03-20.md"),
                "location": str(tmp_path),
                "relative_path": "FPLAN-0001_test_plan_one_2026-03-20.md"
            },
            "2": {
                "subject": "Closed plan",
                "status": "closed",
                "created": "2026-03-18",
                "closed": "2026-03-19",
                "closed_reason": "completed",
                "file_path": str(tmp_path / "FPLAN-0002_closed_plan_2026-03-18.md"),
                "location": str(tmp_path),
                "relative_path": "FPLAN-0002_closed_plan_2026-03-18.md"
            },
            "3": {
                "subject": "Another open",
                "status": "open",
                "created": "2026-03-22",
                "file_path": str(tmp_path / "FPLAN-0003_another_open_2026-03-22.md"),
                "location": str(tmp_path),
                "relative_path": "FPLAN-0003_another_open_2026-03-22.md"
            }
        }
    }
    registry_file = tmp_path / "fplan_registry.json"
    registry_file.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return registry_file, registry


@pytest.fixture
def mock_template_registry(tmp_path):
    """Create a mock template registry."""
    registry = {
        "types": {
            "flow_plans": {
                "prefix": "FPLAN",
                "shorthand": "fplan",
                "created": "2026-03-07"
            },
            "dev_plans": {
                "prefix": "DPLAN",
                "shorthand": "dplan",
                "created": "2026-03-07"
            }
        }
    }
    registry_file = tmp_path / "template_registry.json"
    registry_file.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return registry_file, registry
