# =================== META ====================
# Name: conftest.py
# Description: Shared pytest fixtures for seedgo tests
# Version: 2.4.2
# Created: 2026-03-05
# Modified: 2026-10-24
# =============================================

"""Shared pytest fixtures for seedgo tests."""

import os
import sys
from types import ModuleType
import tempfile

# Set before any prax import so logger initialization sees it.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import copy
from pathlib import Path
from typing import Generator, List, Tuple

import pytest
from unittest.mock import MagicMock

from aipass.cli.apps.modules import display
from aipass.seedgo.apps import seedgo as seedgo_entry
from aipass.seedgo.apps.handlers.aipass_standards import trinity_check, trinity_groups
from aipass.seedgo.apps.handlers.audit import audit_display, branch_audit
from aipass.seedgo.apps.handlers.bypass import utils as _bypass_utils
from aipass.seedgo.apps.handlers.bypass.ignore_handler import (
    is_seedgo_ignored as real_is_seedgo_ignored,
    load_ignore_entries as real_load_ignore_entries,
)
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.tests.support_json_handler_contract import BRANCHES, implementation, redirect_documents
from aipass.seedgo.tests.support_trinity_check import _CONFIG, _TEMPLATES
from aipass.trigger.apps.modules import core as trigger_core

# .archive/ holds verbatim disposal copies that must never be collected or rglob-walked.
collect_ignore_glob = [".archive/*", "**/.archive/*"]


@pytest.fixture
def quarantined_document_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect EVERY handler's document directory, not only the one under test."""
    # A subject's diagnostic can boot the logger and fire trigger into a third branch's json dir; ``redirected``
    # re-points the subject after, and trigger's atomic_write_json (not a json_handler) is reported, not silenced.
    for branch in BRANCHES:
        redirect_documents(implementation(branch), tmp_path / "quarantine" / branch, monkeypatch)


@pytest.fixture
def coverage_audit_seams(monkeypatch):
    """Patch audit_display's and branch_audit's own seams with mocks."""
    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    mock_ignore_handler = MagicMock()
    mock_ignore_handler.audit_ignore_match = MagicMock(return_value=None)
    mock_ignore_handler.ignored_tracked_source = MagicMock(return_value=[])
    mock_ignore_handler.is_seedgo_ignored = real_is_seedgo_ignored
    mock_ignore_handler.load_ignore_entries = real_load_ignore_entries
    mock_scan_branch = MagicMock(return_value=None)

    monkeypatch.setattr(audit_display, "warning", MagicMock())
    monkeypatch.setattr(audit_display, "json_handler", mock_json_handler)

    monkeypatch.setattr(branch_audit, "logger", mock_logger)
    monkeypatch.setattr(branch_audit, "json_handler", mock_json_handler)
    monkeypatch.setattr(branch_audit, "ignore_handler", mock_ignore_handler)
    monkeypatch.setattr(branch_audit, "dead_rules", MagicMock())
    monkeypatch.setattr(branch_audit, "inert", MagicMock())
    monkeypatch.setattr(branch_audit, "scan_branch", mock_scan_branch)


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect seedgo's json writes into a temp dir."""
    # autouse: a forgotten redirect pollutes the real seedgo_json/; the sandbox is measured off the shim.
    # Own subdirectory: a seam AT tmp_path creates tmp_path/seedgo/ and collides with a test's own branch dir.
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Pin the product's consoles to one width for the whole run."""
    # Unpinned, Rich sizes per OS and terminal (80 POSIX, 79 Windows, COLUMNS): a wrap flips substring asserts.
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


class BusRecorder:
    """Stands where @trigger's bus stands: records every fire and sends none."""

    def __init__(self) -> None:
        self.fired: List[Tuple[str, dict]] = []

    def fire(self, event: str, **data) -> dict:
        """Record one event in call order, as the bus would have received it."""
        self.fired.append((event, data))
        return {}


@pytest.fixture(autouse=True)
def bus(monkeypatch) -> BusRecorder:
    """No test fires a real event: a recorder stands where the bus lives."""
    # ``tests_lane._announce_bump`` imports trigger from core on every call.
    recorder = BusRecorder()
    monkeypatch.setattr(trigger_core, "trigger", recorder)
    return recorder


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    display.reset_command_state()


@pytest.fixture
def mock_logger(monkeypatch) -> List[Tuple[str, tuple]]:
    """Capture calls made to the entry point's logger."""
    captured: List[Tuple[str, tuple]] = []

    class _CapturingLogger:
        def info(self, *args, **kwargs):
            captured.append(("info", args))

        def warning(self, *args, **kwargs):
            captured.append(("warning", args))

        def error(self, *args, **kwargs):
            captured.append(("error", args))

    monkeypatch.setattr(seedgo_entry, "logger", _CapturingLogger())
    return captured


@pytest.fixture
def _mock_infrastructure(monkeypatch):
    """Patch the logger and json_handler at the edge, on both modules that read them."""
    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    for module in (trinity_check, trinity_groups):
        monkeypatch.setattr(module, "logger", mock_logger)
        monkeypatch.setattr(module, "json_handler", mock_json_handler)
    return {"logger": mock_logger, "json_handler": mock_json_handler}


@pytest.fixture
def checker(_mock_infrastructure):
    """The trinity_check module, infrastructure patched at the edge."""
    return trinity_check


@pytest.fixture
def trinity(checker, monkeypatch):
    """trinity_check with the pinned config and gold templates in place."""
    monkeypatch.setattr(checker, "load_memory_config", lambda: copy.deepcopy(_CONFIG))
    monkeypatch.setattr(checker, "_load_templates", lambda: copy.deepcopy(_TEMPLATES))
    return checker


@pytest.fixture
def _pin_bypass_log(monkeypatch):
    """Point is_bypassed's json_handler at a mock for every test here."""
    # is_bypassed writes tracked seedgo_json/utils_log.json via its own module's global; xdist races corrupt it.
    mock_handler = MagicMock()
    mock_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(_bypass_utils, "json_handler", mock_handler)


#: A checker imported while its infrastructure is a MagicMock binds that mock, and monkeypatch cannot
#: undo a name another module already bound.
_CHECKER_PKG = "aipass.seedgo.apps.handlers.aipass_standards"


@pytest.fixture(autouse=True)
def _evict_modules_imported_under_a_stub():
    """Drop any checker module a test imported while its infrastructure was mocked."""
    # A re-imported checker keeps names bound from the mock, and delitem(raising=False) records nothing cold.
    # Only arrivals holding a MagicMock go; this tears down after monkeypatch restored sys.modules.
    yield
    package = sys.modules.get(_CHECKER_PKG)
    poisoned = {
        name
        for name in list(sys.modules)
        if name.startswith(_CHECKER_PKG + ".")
        and sys.modules.get(name) is not None
        and any(isinstance(value, MagicMock) for value in vars(sys.modules[name]).values())
    }
    # A submodule is also an attribute on its parent, and `from pkg import sub` reads that first: both go.
    if package is not None:
        for leaf, value in list(vars(package).items()):
            if isinstance(value, ModuleType) and any(isinstance(v, MagicMock) for v in vars(value).values()):
                poisoned.add(f"{_CHECKER_PKG}.{leaf}")
    for name in poisoned:
        sys.modules.pop(name, None)
        if package is not None:
            leaf = name.rsplit(".", 1)[-1]
            if isinstance(getattr(package, leaf, None), ModuleType):
                delattr(package, leaf)
