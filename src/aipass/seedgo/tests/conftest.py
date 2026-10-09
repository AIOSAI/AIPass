# =================== META ====================
# Name: conftest.py
# Description: Shared pytest fixtures for seedgo tests
# Version: 2.3.0
# Created: 2026-03-05
# Modified: 2026-10-08
# =============================================

"""Shared pytest fixtures for seedgo tests.

The autouse fixture here is the load-bearing one: seedgo's json_handler binds
the fleet's one json service (DPLAN-0325), which writes into seedgo_json/
unless AIPASS_TEST_LOG_DIR says otherwise. mock_infrastructure sets that
variable per test, so every test lands in its own tmp_path without knowing it.
"""

import os
import sys
from types import ModuleType
import tempfile

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import copy
import shutil
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

# Never discover out of .archive/: it holds verbatim disposal copies (the old
# handler's tests, the pre-service durability suite) that must not be collected
# or rglob-walked into dotted module names (DPLAN-0325, spec 4c).
collect_ignore_glob = [".archive/*", "**/.archive/*"]


@pytest.fixture
def quarantined_document_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect EVERY handler's document directory, not only the one under test.

    Closing a side channel that was found by auditing this suite's own syscalls
    rather than by reasoning about it. Measured chain, branch-local run,
    2026-09-01::

        test_load_json_survives_a_corrupt_document[ai_mail]
          -> ai_mail json_utils ensure_json_exists   (regenerating, so it warns)
          -> prax logger.warning -> _ensure_watcher
          -> trigger core.fire -> _ensure_initialized -> registry.setup_handlers
          -> TRIGGER's json_handler.log_operation
          -> mkdir + atomic rename inside src/aipass/trigger/trigger_json

    So provoking a diagnostic in the subject wrote into a THIRD branch's live
    document directory — through a path that never touches the subject's
    redirect, which is why per-subject redirection alone could not have caught
    it. Every discovered handler is redirected for the duration of every test;
    ``redirected`` then re-points the subject at its own directory, and because
    monkeypatch restores in reverse order both survive teardown intact.

    WHAT THIS DOES NOT CLOSE, stated rather than left to be rediscovered. The
    same logger boot also runs trigger's startup handler, which persists
    trigger's own state through ``trigger/apps/config.py::atomic_write_json`` —
    a writer that is not a json_handler and holds its own directory. One mkdir
    and one rename per pytest process still land there. Reaching into another
    branch's config module to silence it would couple this suite to the
    internals of a branch it does not test, so it is reported instead. It is
    pre-existing: the same events were measured under seedgo's existing
    test_json_durability.py, which imports no handler but this branch's.

    Args:
        tmp_path: pytest's per-test directory.
        monkeypatch: Restores every binding at teardown.
    """
    for branch in BRANCHES:
        redirect_documents(implementation(branch), tmp_path / "quarantine" / branch, monkeypatch)


@pytest.fixture
def coverage_audit_seams(monkeypatch):
    """Patch audit_display's and branch_audit's own seams with mocks.

    audit_display and branch_audit are imported for real at module top, so
    isolation is applied at the edge each one actually reads (its own bound
    name for logger / warning / json_handler / ignore_handler / scan_branch)
    instead of intercepting the packages in sys.modules. The console stays
    real: it writes to stdout at print time, and the render tests read capsys.
    """
    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    mock_ignore_handler = MagicMock()
    mock_ignore_handler.get_audit_ignore_patterns = MagicMock(return_value=[])
    # The ignore list removes nothing here, as the empty pattern list above says.
    mock_ignore_handler.audit_ignore_match = MagicMock(return_value=None)
    mock_ignore_handler.ignored_tracked_source = MagicMock(return_value=[])
    mock_ignore_handler.is_seedgo_ignored = real_is_seedgo_ignored
    mock_ignore_handler.load_ignore_entries = real_load_ignore_entries
    mock_scan_branch = MagicMock(return_value=None)

    # -- audit_display's own seams --------------------------------------
    monkeypatch.setattr(audit_display, "warning", MagicMock())
    monkeypatch.setattr(audit_display, "json_handler", mock_json_handler)

    # -- branch_audit's own seams ----------------------------------------
    monkeypatch.setattr(branch_audit, "logger", mock_logger)
    monkeypatch.setattr(branch_audit, "json_handler", mock_json_handler)
    monkeypatch.setattr(branch_audit, "ignore_handler", mock_ignore_handler)
    monkeypatch.setattr(branch_audit, "dead_rules", MagicMock())
    monkeypatch.setattr(branch_audit, "inert", MagicMock())
    monkeypatch.setattr(branch_audit, "scan_branch", mock_scan_branch)


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


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect seedgo's json writes into a temp dir.

    autouse=True on purpose: the shim's names write into the real seedgo_json/
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
    # tmp_path/seedgo/ in every test and collide with a test that builds a
    # directory of its own branch's name (backup hit it first, 2026-09-03).
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Pin the product's consoles to one width for the whole run.

    Rich sizes an unpinned console on every print: 80 columns on POSIX and 79
    on Windows under pytest's capture, the terminal's width under -s, COLUMNS
    when it is exported. A line that wraps on one OS and not another turns a
    substring assertion into a coin toss (DPLAN-0354, test template v1 item 20).
    """
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
    """No test fires a real event: a recorder stands at both homes of the bus.

    Two homes, because two names reach it. The cli header keeps the trigger it
    loaded in ``display._TRIGGER`` behind ``display._TRIGGER_LOADED``, so a
    replacement at the trigger's own home comes too late once one header has
    run in the session; the recorder goes into the cached name and the flag is
    set, api's cure of 09-27. ``tests_lane._announce_bump`` imports ``trigger``
    from ``aipass.trigger.apps.modules.core`` inside the function, so it reads
    that module's name on every call. Leg 3's probe counted 27 fires reaching
    the bus from this suite (seedgo, fleet green leg 4).

    Returns:
        The recorder, so a test can assert what would have fired.
    """
    recorder = BusRecorder()
    monkeypatch.setattr(display, "_TRIGGER", recorder)
    monkeypatch.setattr(display, "_TRIGGER_LOADED", True)
    monkeypatch.setattr(trigger_core, "trigger", recorder)
    return recorder


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    display.reset_command_state()


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

    monkeypatch.setattr(seedgo_entry, "logger", _CapturingLogger())
    return captured


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    """Point is_bypassed's json_handler at a mock for every test here.

    The bypass tests call the real is_bypassed, which appends to the
    repo-tracked seedgo_json/utils_log.json via the json_handler global in
    its OWN module — xdist workers racing on that shared file corrupt it
    (JSONDecodeError: Extra data). sys.modules patching never reaches a
    function's globals, so the pin must land on the utils module object.
    """
    mock_handler = MagicMock()
    mock_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(_bypass_utils, "json_handler", mock_handler)


#: The package whose modules a test's sys.modules stubs can poison. A checker
#: imported while its infrastructure is a MagicMock binds that mock at import
#: time, and monkeypatch cannot undo a name another module already bound.
_CHECKER_PKG = "aipass.seedgo.apps.handlers.aipass_standards"


@pytest.fixture(autouse=True)
def _evict_modules_imported_under_a_stub():
    """Drop any checker module a test imported while its infrastructure was mocked.

    THE LEAK THIS CLOSES (todo 139, template v1 item 18). Twenty-five files in
    this suite share one fixture shape: monkeypatch.setitem(sys.modules,
    "...handlers.bypass", MagicMock()) followed by monkeypatch.delitem of the
    checker they are about to exercise, so it re-imports against the mocks.
    monkeypatch restores the sys.modules ENTRIES, but trigger_check does
    `from ...bypass.utils import matching_rule` at import time -- the name is
    bound before teardown and stays bound. delitem with raising=False records
    nothing when the key is absent, which is the cold-run case, so the poisoned
    module was left in sys.modules and test_bypass.py later read
    `mock.utils.matching_rule()` out of it. Alphabetical order hid it for
    months: test_bypass runs FIRST in a forward run and last in a reverse one.

    Scoped by measurement, not by name: only modules that ARRIVED during the
    test, and only the ones actually HOLDING a MagicMock, so a clean test pays
    nothing and re-imports nothing. Reading the arrived module rather than the
    stub is deliberate -- a conftest fixture tears down LAST, after monkeypatch
    has already put sys.modules back, so the stub is gone by then and only the
    bound name is left to see.
    """
    yield
    package = sys.modules.get(_CHECKER_PKG)
    poisoned = {
        name
        for name in list(sys.modules)
        if name.startswith(_CHECKER_PKG + ".")
        and sys.modules.get(name) is not None
        and any(isinstance(value, MagicMock) for value in vars(sys.modules[name]).values())
    }
    # sys.modules is only half of it. Importing a submodule also sets it as an
    # ATTRIBUTE on its parent package, and `from pkg import sub` reads that
    # attribute before it ever consults sys.modules -- so a module already
    # popped from sys.modules comes straight back through the package, still
    # holding its mock. Both have to go.
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
