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
from aipass.flow.apps.handlers.json import json_handler as json_handler_module
import aipass.cli.apps.modules  # noqa: F401

# Pre-import every module that calls find_repo_root() at MODULE level, for a
# different reason: to move an IMPORT-TIME diagnostic out of every test window.
#
# find_repo_root logs repo_root_fallback through json_handler.log_operation when
# the marker walk finds nothing. AIPASS_REGISTRY.json is gitignored and
# machine-local, so on a dev box the fallback never runs and on a bare CI
# checkout it runs on EVERY import. These six modules take that walk while
# LOADING, so on CI the diagnostic lands in whichever test window happens to
# trigger the first import — and mock_json_handler (autouse) counts it.
#
# That is what reddened test_push_central on all four Python versions of commit
# 28ee90d5 (round 5, @devpulse). The count it broke was not wrong; it was
# measuring the host. A per-test fix would have left the other sites one
# xdist worker-split away: measured in a bare world, running each
# count-asserting test in FULL isolation, TWO of the ten fail — CI had only
# found one. Importing here settles the walk before any test window exists, on
# every machine, and the counts go back to meaning what they say.
#
# TestThePreImportListIsComplete (tests/test_conftest_fixtures.py) fails if a
# new module-level caller appears and is not added here.
import aipass.flow.apps.handlers.dashboard.push_central  # noqa: F401
import aipass.flow.apps.handlers.mbank.process  # noqa: F401
import aipass.flow.apps.handlers.plan.close_helpers  # noqa: F401
import aipass.flow.apps.handlers.plan.restore_ops  # noqa: F401
import aipass.flow.apps.modules.aggregate_central  # noqa: F401
import aipass.flow.apps.modules.registry_monitor  # noqa: F401


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
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect flow's json writes into a temp dir.

    autouse=True on purpose: flow's handler is a shim that binds the fleet json
    service (DPLAN-0325), whose names write into the real flow_json/ unless the
    seam is set, so a test that forgets to redirect pollutes the branch. The
    guard belongs on every test, not on the ones that remember.

    The service recomputes its directory on every call, so setting the variable
    here — after import — still takes effect. The sandbox is MEASURED off the
    shim rather than spelled out, so it cannot drift from what the service does.

    Returns:
        The sandbox directory the handler now writes into.
    """
    # Own subdirectory on purpose: the service spells the sandbox
    # <seam>/<branch>/<branch>_json, so a seam AT tmp_path would create
    # tmp_path/flow/ in every test and collide with a test that builds a
    # directory of its own branch's name (backup hit it first, 2026-09-03).
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler_module.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture(autouse=True)
def mock_json_handler(request):
    """Spy on the audit line, so a test can assert WHICH operation was logged.

    Eight suites take this fixture by name and assert on its calls, so it stays
    a spy rather than becoming the seam — ``mock_infrastructure`` above is what
    actually keeps writes out of flow_json/, and it does so for all nine names
    rather than this one.

    It patches a module attribute, which the shim's OWN wiring test must see
    unpatched: that file's whole subject is that each name IS the service's
    bound method, and a MagicMock in its place is exactly the drift it looks
    for. Excluded by module rather than by marker so the fleet's canonical
    wiring test stays byte-identical across every migrated branch.
    """
    if request.node.module.__name__.endswith("test_json_handler"):
        yield None
        return

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
def sample_test_data() -> dict:
    """Reusable sample data shaped like a valid 'data' JSON document.

    The branch template ships this and 17 of 18 branches carry it; flow's
    conftest had lost it, and the gap was invisible because an unrelated
    handler test happened to mention the name. Restored with the sweep that
    archived that test (DPLAN-0325 pair 7) rather than left to look covered.
    """
    return {
        "created": "2026-09-04",
        "last_updated": "2026-09-04",
        "test_key": "test_value",
        "sample_data": "example",
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


# Never discover out of .archive/: it holds verbatim disposal copies (the old
# handler's tests, the pre-service durability suite) that must not be collected
# or rglob-walked into dotted module names (DPLAN-0325, spec 4c).
collect_ignore_glob = [".archive/*", "**/.archive/*"]
