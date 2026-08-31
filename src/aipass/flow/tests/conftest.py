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
import sys
from unittest.mock import MagicMock, patch

# Pre-import modules so patch() path resolution works.
# Without these imports, the intermediate packages lack the sub-module
# attributes that unittest.mock.patch needs for dotted-path traversal.
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.flow.apps.handlers.json.json_handler  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401


def pytest_configure(config):
    """Register flow's markers where BOTH test universes can see them.

    The commit gate runs this suite with rootdir pinned to the branch by
    ``pytest.ini``; CI composes every conftest in one process from the repo root
    under ``-c pyproject.toml``, where ``pytest.ini`` is never read. A marker
    registered only in ``pytest.ini`` is therefore unknown in CI — two
    PytestUnknownMarkWarning per run, and under a stricter config a hard error.
    ``conftest.py`` is loaded in both universes, so this is the one place a
    branch-local marker can be declared once and mean the same thing twice.

    Same species as FPLAN-0461: green per-branch says nothing about the composed
    world. Caught here by running both rootdirs, which is why that is the rule.

    Args:
        config: The pytest config being built.
    """
    config.addinivalue_line(
        "markers",
        "real_logger: opt out of the autouse mock_logger fixture — for tests whose "
        "SUBJECT is the log line (caplog reads the real logging module)",
    )


@pytest.fixture(autouse=True)
def mock_logger(request, monkeypatch):
    """Mock the prax logger every flow module actually calls.

    FIXED 2026-08-31. This used to patch
    ``aipass.prax.apps.modules.logger.system_logger`` — the SOURCE attribute —
    while every flow module does ``from ... import system_logger as logger`` at
    import time and therefore holds its OWN binding. Patching upstream of a
    binding that was already taken reaches nothing, and it was measured
    reaching nothing: with the old patch active, a consumer's ``logger`` was
    still the real object. @seedgo published the technique alongside the
    standard after @prax ruled (``drone @seedgo standard imports``); the sibling
    fixture ten lines down, ``mock_json_handler``, had it right all along
    because it patches an attribute the consumer resolves at CALL time.

    No test lost or gained an assertion: three tests take this fixture as a
    parameter and none of them assert on it, so there was no assertion surface
    to break — which is also why the broken version never showed up as a
    failure.

    Nothing leaked in the meantime. Containment comes from
    ``AIPASS_TEST_LOG_DIR``, set at the top of this file ahead of every import;
    a broken fixture sitting behind a working mechanism is a different thing
    from a leak, and reporting it as one would have sent the wrong fix.

    OPT OUT with ``@pytest.mark.real_logger`` when the test's SUBJECT is the log
    line — ``caplog`` reads the real logging module, and a mock that swallows
    the call makes such a test vacuous. Found the honest way: turning this
    fixture on reddened exactly one test, and that test was right. The first
    measurement ("three tests take this fixture and none assert on it") counted
    the wrong population; caplog users take no fixture parameter at all.
    """
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
def mock_json_handler():
    """Mock json_handler to prevent real JSON operations."""
    with patch("aipass.flow.apps.handlers.json.json_handler.log_operation") as mock_log_op:
        yield mock_log_op


@pytest.fixture(autouse=True)
def mock_console():
    """Mock CLI console to prevent real console output."""
    with (
        patch("aipass.cli.apps.modules.console") as console_mock,
        patch("aipass.cli.apps.modules.error") as error_mock,
        patch("aipass.cli.apps.modules.warning") as warning_mock,
        patch("aipass.cli.apps.modules.success") as success_mock,
        patch("aipass.cli.apps.modules.header") as header_mock,
    ):
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
                "relative_path": "FPLAN-0001_test_plan_one_2026-03-20.md",
            },
            "2": {
                "subject": "Closed plan",
                "status": "closed",
                "created": "2026-03-18",
                "closed": "2026-03-19",
                "closed_reason": "completed",
                "file_path": str(tmp_path / "FPLAN-0002_closed_plan_2026-03-18.md"),
                "location": str(tmp_path),
                "relative_path": "FPLAN-0002_closed_plan_2026-03-18.md",
            },
            "3": {
                "subject": "Another open",
                "status": "open",
                "created": "2026-03-22",
                "file_path": str(tmp_path / "FPLAN-0003_another_open_2026-03-22.md"),
                "location": str(tmp_path),
                "relative_path": "FPLAN-0003_another_open_2026-03-22.md",
            },
        },
    }
    registry_file = tmp_path / "fplan_registry.json"
    registry_file.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return registry_file, registry


@pytest.fixture
def mock_template_registry(tmp_path):
    """Create a mock template registry."""
    registry = {
        "types": {
            "flow_plans": {"prefix": "FPLAN", "shorthand": "fplan", "created": "2026-03-07"},
            "dev_plans": {"prefix": "DPLAN", "shorthand": "dplan", "created": "2026-03-07"},
        }
    }
    registry_file = tmp_path / "template_registry.json"
    registry_file.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return registry_file, registry
